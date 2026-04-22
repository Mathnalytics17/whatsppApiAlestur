from flask import Flask, request, jsonify
import util
import whatsappservice
from models import db, User, Session, Message, State, SessionContext, PolicyConsent

import config
from datetime import datetime, timedelta, timezone

# minutos sin mensaje para empezar a avisar
INACTIVITY_MINUTES = 10
WARNING_EXTRA_MINUTES = 3  # minutos extra después del aviso para cerrar + encuesta

app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)

# ============================================================
# HELPERS
# ============================================================

def make_aware(dt):
    """Convierte un datetime naive en aware (UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

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
    """Cierra una sesión y guarda razón opcional."""
    if not session or not session.is_active:
        return

    now = datetime.now(timezone.utc)

    session.is_active = False
    session.end_time = now
    session.current_state_id = get_or_create_state("finalizado").id
    session.last_message_time = now

    if reason:
        ctx = SessionContext.query.filter_by(
            session_id=session.id,
            context_key="close_reason"
        ).first()

        if not ctx:
            ctx = SessionContext(session_id=session.id, context_key="close_reason")
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

def send_text(session, number, text, update_last_message=True):
    data = util.TextMessage(text, number=number)
    whatsappservice.SendMessageWhatsapp(data)

    # Solo actualiza last_message_time si viene del usuario o del humano,
    # NO en los mensajes automáticos (warning, timeout, encuesta)
    if update_last_message:
        log_message(session, "out", text)
    else:
        # Log sin modificar last_message_time
        msg = Message(
            session_id=session.id,
            direction="out",
            message_text=text,
            message_type="text"
        )
        db.session.add(msg)
        db.session.commit()

def send_policy_buttons(session, number):
    data_button = util.ButtonMessage(number=number)
    whatsappservice.SendMessageWhatsapp(data_button)
    body_text = data_button["interactive"]["body"]["text"]
    log_message(session, "out", body_text, message_type="interactive")

def send_policy_documents(session, number):
    """
    Envía los PDFs que tienes en tu VPS bajo /archivos
    Ejemplo de rutas:
      https://luismolinatest.com/archivos/politica_tratamiento_datos.pdf
      https://luismolinatest.com/archivos/autorizacion_tratamiento_datos.pdf
    """
    filenames = [
        "politica_tratamiento_datos.pdf",
        "autorizacion_tratamiento_datos.pdf",
    ]
    for filename in filenames:
        data = util.TextDocumentMessage(number, filename)
        whatsappservice.SendMessageWhatsapp(data)
        log_message(session, "out", f"Documento enviado: {filename}", message_type="document")

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
    ctx = SessionContext.query.filter_by(
        session_id=session.id,
        context_key="inactivity_warning_sent"
    ).first()

    if ctx:
        db.session.delete(ctx)
        db.session.commit()

# ============================================================
# LÓGICA DE MENSAJES
# ============================================================

def handle_new_message(text, number):
    now = datetime.now(timezone.utc)
    user = get_or_create_user(number)

    session = get_active_session(user)

    if not session:
        session = Session(
            user_id=user.id,
            start_time=now,
            is_active=True,
            current_state_id=get_or_create_state("inicio").id,
            last_message_time=now
        )
        db.session.add(session)
        db.session.commit()
    else:
        # si había warning de inactividad, se limpia porque el usuario volvió
        clear_inactivity_warning(session)

    # mensaje entrante del usuario
    log_message(session, "in", text)

    current_state = db.session.get(State, session.current_state_id)
    state_name = current_state.state_name.lower() if current_state else "inicio"
    text_lower = text.strip().lower()

    print(f"🌀 Estado actual: {state_name}")

    # ================== ESTADO INICIO ==================
    if state_name == "inicio":
        # Siempre que entra por primera vez:
        #  1) botones Acepto / No acepto
        #  2) PDFs de política y autorización
        send_policy_buttons(session, number)
        send_policy_documents(session, number)

        session.current_state_id = get_or_create_state("esperando_aceptacion").id
        db.session.commit()
        return

    # ================== ACEPTACIÓN ==================
    # ================== ACEPTACIÓN ==================
    if state_name == "esperando_aceptacion":

        # Normalizamos texto
        t = text_lower.strip()

        # ------------------------------
        # Caso A: ACEPTÓ correctamente
        # ------------------------------
        if t == "acepto":
            save_policy_consent(session, accepted=True)

            session.current_state_id = get_or_create_state("aceptado").id
            db.session.commit()

            send_text(
                session,
                number,
                "Perfecto ✅. Un asesor humano se comunicará contigo."
            )
            return

        # ------------------------------
        # Caso B: NO ACEPTÓ
        # ------------------------------
        if t in ["no acepto", "no"]:
            save_policy_consent(session, accepted=False)

            session.current_state_id = get_or_create_state("rechazado").id
            db.session.commit()

            send_text(
                session,
                number,
                "Sin aceptar la política no podemos continuar. La sesión será cerrada."
            )
            close_session(session, "no_acepta_politica")
            return

        # ------------------------------
        # Caso C: Cualquier otra cosa
        # ------------------------------
        send_text(
            session,
            number,
            "Por favor responde *Acepto* o *No acepto* para continuar."
        )
        return


    # ================== PREGUNTA ENCUESTA ==================
    if state_name == "esperando_calificacion":
        if text_lower in ["si", "sí", "s", "yes"]:
            session.current_state_id = get_or_create_state("encuesta_satisfaccion").id
            db.session.commit()

            send_text(session, number, "¿Quedaste satisfecho con la atención? (Sí / No)")
            return

        if text_lower in ["no", "n"]:
            send_text(session, number, "Gracias por tu tiempo 😊")
            close_session(session, "no_quiso_calificar")
            return

        send_text(session, number, "Responde *Sí* o *No* por favor.")
        return

    # ================== ENCUESTA ==================
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

            send_text(session, number, "Gracias por calificar 🙌. ¡Hasta pronto!")
            close_session(session, "encuesta_satisfecho")
            return

        if text_lower in ["no", "n"]:
            ctx.context_value = "no_satisfecho"
            ctx.updated_at = now
            db.session.commit()

            send_text(session, number, "Gracias por tu sinceridad 🙏")
            close_session(session, "encuesta_no_satisfecho")
            return

        send_text(session, number, "Responde *Sí* o *No* por favor.")
        return

    # ================== ASESOR HUMANO ==================
    # Estado "aceptado" u otros donde ya habla el humano → solo registramos
    return

# ============================================================
# ENDPOINTS
# ============================================================

@app.route('/welcome', methods=['GET'])
def Index():
    return 'welcome to the jungle'

@app.route('/whatsapp', methods=['GET'])
def VerifyToken():
    try:
        accessToken = "7393374SHDSJ23UD"
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if token and challenge and token == accessToken:
            return challenge
        return "", 400
    except:
        return "", 400

@app.route('/whatsapp', methods=['POST'])
def RecievedMessage():
    try:
        body = request.get_json()
        entry = body['entry'][0]
        message = entry['changes'][0]['value']['messages'][0]

        number = message['from']
        text = util.GetTextUser(message)

        handle_new_message(text, number)

        print("💬 Mensaje recibido:", text)
        return "EVENT_RECEIVED"

    except Exception as e:
        print("❌ Error procesando mensaje:", e)
        return "EVENT_RECEIVED"

@app.route('/sessions/<int:session_id>/close', methods=['POST'])
def close_session_manual(session_id):
    session = Session.query.get_or_404(session_id)

    if not session.is_active:
        return jsonify({"message": "La sesión ya está cerrada"}), 400

    number = session.user.phone_number

    session.current_state_id = get_or_create_state("esperando_calificacion").id
    db.session.commit()

    send_text(
        session,
        number,
        "La conversación ha finalizado. ¿Deseas calificar tu experiencia? (Sí / No)"
    )

    return jsonify({"message": "Sesión marcada para calificación"}), 200

@app.route('/sessions/active', methods=['GET'])
def list_active_sessions():
    sessions = Session.query.filter_by(is_active=True).all()
    data = [{
        "id": s.id,
        "user_phone": s.user.phone_number,
        "start_time": s.start_time.isoformat() if s.start_time else None,
        "last_message_time": s.last_message_time.isoformat() if s.last_message_time else None,
        "state": s.state.state_name if s.state else None
    } for s in sessions]

    return jsonify(data), 200

# ============================================================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
