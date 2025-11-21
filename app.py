from flask import Flask, request, jsonify
import util
import whatsappservice
from models import db, User, Session, Message, State, SessionContext, PolicyConsent

import config
from datetime import datetime, timedelta, timezone

# minutos sin mensaje para enviar aviso
INACTIVITY_MINUTES = 10
# minutos extra después del aviso para cerrar la sesión
WARNING_EXTRA_MINUTES = 3

app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)

# ============================================================
# HELPERS
# ============================================================

def save_policy_consent(session, accepted: bool):
    consent = PolicyConsent(
        user_id=session.user_id,
        session_id=session.id,
        accepted=accepted
    )
    db.session.add(consent)
    db.session.commit()
    return consent

def get_or_create_state(name, description=None):
    name = name.lower()
    state = State.query.filter_by(state_name=name).first()
    if not state:
        state = State(state_name=name, description=description or name)
        db.session.add(state)
        db.session.commit()
    return state

def get_or_create_user(phone_number):
    user = User.query.filter_by(phone_number=phone_number).first()
    if not user:
        user = User(phone_number=phone_number)
        db.session.add(user)
        db.session.commit()
    return user

def get_active_session(user):
    return (
        Session.query
        .filter_by(user_id=user.id, is_active=True)
        .order_by(Session.start_time.desc())
        .first()
    )

def close_session(session, reason=None):
    if not session or not session.is_active:
        return

    now = datetime.now(timezone.utc)
    session.is_active = False
    session.end_time = now
    final_state = get_or_create_state("finalizado", "Sesión finalizada")
    session.current_state_id = final_state.id
    session.last_message_time = now

    if reason:
        ctx = SessionContext.query.filter_by(
            session_id=session.id,
            context_key="close_reason"
        ).first()

        if not ctx:
            ctx = SessionContext(
                session_id=session.id,
                context_key="close_reason"
            )
            db.session.add(ctx)

        ctx.context_value = reason
        ctx.updated_at = now

    db.session.commit()

def log_message(session, direction, text, message_type="text"):
    now = datetime.now(timezone.utc)
    msg = Message(
        session_id=session.id,
        direction=direction,
        message_text=text,
        message_type=message_type
    )
    db.session.add(msg)
    session.last_message_time = now
    db.session.commit()
    return msg

def send_text(session, number, text):
    data = util.TextMessage(text, number=number)
    whatsappservice.SendMessageWhatsapp(data)
    log_message(session, "out", text)

def send_policy_buttons(session, number):
    data_button = util.ButtonMessage(number=number)
    whatsappservice.SendMessageWhatsapp(data_button)
    body_text = data_button["interactive"]["body"]["text"]
    log_message(session, "out", body_text, message_type="interactive")

def send_policy_documents(session, number):
    ids = [
        "1tZYPCZgQ6KTqKS-YUBu_yw50uT5KhcGr",
        "1BOFQmRfLeCW2BkQn2U1QG5m4WTrke2m4",
    ]
    for doc_id in ids:
        data = util.TextDocumentMessage(number, doc_id)
        whatsappservice.SendMessageWhatsapp(data)
        log_message(session, "out", f"Documento enviado: {doc_id}", message_type="document")

def mark_session_abandoned(session):
    now = datetime.now(timezone.utc)
    ctx = SessionContext.query.filter_by(
        session_id=session.id,
        context_key="abandoned"
    ).first()

    if not ctx:
        ctx = SessionContext(
            session_id=session.id,
            context_key="abandoned",
            context_value="true",
            updated_at=now
        )
        db.session.add(ctx)
    else:
        ctx.context_value = "true"
        ctx.updated_at = now

    db.session.commit()

def clear_inactivity_warning(session):
    """Elimina el aviso en cuanto el usuario responde."""
    ctx = SessionContext.query.filter_by(
        session_id=session.id,
        context_key="inactivity_warning_sent"
    ).first()

    if ctx:
        db.session.delete(ctx)
        db.session.commit()

# ============================================================
# FLUJO PRINCIPAL
# ============================================================

def handle_new_message(text, number):
    now = datetime.now(timezone.utc)
    user = get_or_create_user(number)

    # sesión activa
    session = get_active_session(user)

    # si no existía sesión → crearla
    if not session:
        inicio_state = get_or_create_state("inicio", "Sesión recién iniciada")
        session = Session(
            user_id=user.id,
            start_time=now,
            is_active=True,
            current_state_id=inicio_state.id,
            last_message_time=now
        )
        db.session.add(session)
        db.session.commit()

    # Registrar mensaje ANTES de limpiar warning
    log_message(session, "in", text)

    # Usuario respondió → limpiar flag de aviso
    clear_inactivity_warning(session)

    # Estado actual
    current_state = db.session.get(State, session.current_state_id)
    state_name = current_state.state_name.lower() if current_state else "inicio"
    text_lower = text.strip().lower()

    # ----------- ESTADOS -----------

    if state_name == "inicio":
        send_policy_buttons(session, number)
        send_policy_documents(session, number)
        waiting = get_or_create_state("esperando_aceptacion")
        session.current_state_id = waiting.id
        db.session.commit()
        return

    if state_name == "esperando_aceptacion":
        if "acepto" in text_lower:
            save_policy_consent(session, True)
            accepted = get_or_create_state("aceptado")
            session.current_state_id = accepted.id
            db.session.commit()
            send_text(session, number, "Perfecto ✅. Un asesor humano se comunicará contigo en breve.")
            return

        elif "no acepto" in text_lower or text_lower == "no":
            save_policy_consent(session, False)
            rejected = get_or_create_state("rechazado")
            session.current_state_id = rejected.id
            db.session.commit()
            send_text(session, number, "Debes aceptar la política para continuar. Sesión cerrada.")
            close_session(session, reason="no_acepta_politica")
            return

        else:
            send_text(session, number, "Responde *Acepto* o *No acepto*.")
            return

    if state_name == "esperando_calificacion":
        if text_lower in ["si", "sí", "s", "yes"]:
            encuesta = get_or_create_state("encuesta_satisfaccion")
            session.current_state_id = encuesta.id
            db.session.commit()
            send_text(session, number, "¿Quedaste satisfecho? Responde Sí o No.")
            return

        elif text_lower in ["no", "n"]:
            send_text(session, number, "Gracias por tu tiempo 😊")
            close_session(session, reason="no_quiso_calificar")
            return

    if state_name == "encuesta_satisfaccion":
        ctx = SessionContext.query.filter_by(
            session_id=session.id,
            context_key="satisfaccion"
        ).first()

        if not ctx:
            ctx = SessionContext(session_id=session.id, context_key="satisfaccion")
            db.session.add(ctx)

        if text_lower in ["si", "sí", "s", "yes"]:
            ctx.context_value = "satisfecho"
            ctx.updated_at = now
            db.session.commit()

            send_text(session, number, "Gracias 🙌 ¡Hasta pronto!")
            close_session(session, reason="encuesta_satisfecho")
            return

        elif text_lower in ["no", "n"]:
            ctx.context_value = "no_satisfecho"
            ctx.updated_at = now
            db.session.commit()

            send_text(session, number, "Gracias, mejoraremos 💪")
            close_session(session, reason="encuesta_no_satisfecho")
            return

# ============================================================
# ENDPOINTS
# ============================================================

@app.route('/welcome', methods=['GET'])
def Index():
    return "welcome to the jungle"

@app.route('/whatsapp', methods=['POST'])
def RecievedMessage():
    try:
        body = request.get_json()
        message = body['entry'][0]['changes'][0]['value']['messages'][0]
        number = message['from']
        text = util.GetTextUser(message)

        handle_new_message(text, number)
        return "EVENT_RECEIVED"

    except Exception as e:
        print("❌ Error:", e)
        return "EVENT_RECEIVED"

@app.route('/sessions/active', methods=['GET'])
def list_active_sessions():
    active = Session.query.filter_by(is_active=True).all()
    out = [{
        "id": s.id,
        "user_phone": s.user.phone_number,
        "start_time": s.start_time.isoformat(),
        "last_message_time": s.last_message_time.isoformat(),
        "state": s.state.state_name
    } for s in active]
    return jsonify(out), 200

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
