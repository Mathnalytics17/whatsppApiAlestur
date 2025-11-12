from flask import Flask, request, jsonify
import util
import whatsappservice
from models import db, User, Session, Message, State, SessionContext, PolicyConsent

import config
from datetime import datetime, timedelta, timezone

# (por ahora no usamos INACTIVITY_MINUTES, se deja para una versión futura)
INACTIVITY_MINUTES = 10

app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)

# ============================================================
# HELPERS DE ESTADOS / USUARIOS / SESIONES
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
    # guardamos todos los nombres de estado en minúsculas
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
    """Cierra una sesión y opcionalmente guarda la razón en SessionContext."""
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
            ctx = SessionContext(session_id=session.id, context_key="close_reason")
            db.session.add(ctx)
        ctx.context_value = reason
        ctx.updated_at = now

    db.session.commit()

def log_message(session, direction, text, message_type="text"):
    """Registra un mensaje y actualiza last_message_time de la sesión."""
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
    # IDs de tus documentos en Drive (política, etc.)
    ids = [
        "1tZYPCZgQ6KTqKS-YUBu_yw50uT5KhcGr",
        "1BOFQmRfLeCW2BkQn2U1QG5m4WTrke2m4",
    ]
    for doc_id in ids:
        data = util.TextDocumentMessage(number, doc_id)
        whatsappservice.SendMessageWhatsapp(data)
        log_message(session, "out", f"Documento enviado: {doc_id}", message_type="document")

# ============================================================
# LÓGICA PRINCIPAL DEL FLUJO
# ============================================================

def handle_new_message(text, number):
    now = datetime.now(timezone.utc)
    user = get_or_create_user(number)

    # 1) Buscar sesión activa SIN cerrarla por inactividad (por ahora)
    session = get_active_session(user)

    # 2) Si no hay sesión activa, crear una nueva
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

    # 3) Registrar el mensaje entrante
    log_message(session, "in", text)

    # 4) Revisar estado actual
    current_state = db.session.get(State, session.current_state_id) if session.current_state_id else None
    state_name = current_state.state_name.lower() if current_state and current_state.state_name else "inicio"

    print(f"🌀 Estado actual: {state_name}")  # Debug

    text_lower = text.strip().lower()

    # ======================= ESTADO: INICIO =======================
    if state_name == "inicio":
        # Enviar bienvenida + política + botones + documentos
        send_policy_buttons(session, number)
        send_policy_documents(session, number)
        esperando_state = get_or_create_state(
            "esperando_aceptacion",
            "Esperando aceptación de política de datos"
        )
        session.current_state_id = esperando_state.id
        db.session.commit()
        print("➡️ Estado cambiado a esperando_aceptacion")
        return

    # ================= ESTADO: ESPERANDO ACEPTACIÓN ===============
    if state_name == "esperando_aceptacion":
        print("📩 Esperando aceptación del usuario...")
        if "acepto" in text_lower:
            # Guardar aceptación explícitamente en tabla policy_consents
            save_policy_consent(session, accepted=True)

            aceptado_state = get_or_create_state(
                "aceptado",
                "Términos aceptados, pasa a asesor humano"
            )
            session.current_state_id = aceptado_state.id
            db.session.commit()

            send_text(session, number, "Perfecto ✅. Un asesor humano se comunicará contigo en breve.")
            return

        elif "no acepto" in text_lower or text_lower == "no":
            # Guardar NO aceptación explícitamente
            save_policy_consent(session, accepted=False)

            rechazado_state = get_or_create_state(
                "rechazado",
                "Usuario no aceptó los términos"
            )
            session.current_state_id = rechazado_state.id
            db.session.commit()

            send_text(
                session,
                number,
                "Para continuar con la atención es necesario aceptar "
                "nuestra Política de Tratamiento de Datos Personales. "
                "Tu sesión será cerrada."
            )
            close_session(session, reason="no_acepta_politica")
            return

        else:
            send_text(session, number, "Por favor responde *Acepto* o *No acepto* para continuar.")
            return

    # ============== ESTADO: ESPERANDO DECISIÓN ENCUESTA ===========
    if state_name == "esperando_calificacion":
        if text_lower in ["si", "sí", "s", "yes"]:
            encuesta_state = get_or_create_state(
                "encuesta_satisfaccion",
                "Usuario aceptó calificar"
            )
            session.current_state_id = encuesta_state.id
            db.session.commit()
            send_text(
                session,
                number,
                "¿Quedaste satisfecho con la atención recibida? (Responde *Sí* o *No*)"
            )
            return

        elif text_lower in ["no", "n"]:
            send_text(
                session,
                number,
                "Gracias por tu tiempo 😊. Esperamos poder ayudarte en otra ocasión."
            )
            close_session(session, reason="no_quiso_calificar")
            return

        else:
            send_text(session, number, "Por favor responde *Sí* o *No* para continuar.")
            return

    # ============== ESTADO: ENCUESTA SATISFACCIÓN =================
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
            send_text(
                session,
                number,
                "Gracias por calificar nuestro servicio 🙌. ¡Hasta pronto! 👋"
            )
            close_session(session, reason="encuesta_satisfecho")
            return

        elif text_lower in ["no", "n"]:
            ctx.context_value = "no_satisfecho"
            ctx.updated_at = now
            db.session.commit()
            send_text(
                session,
                number,
                "Gracias por tu sinceridad. Trabajaremos para mejorar 💪. ¡Hasta pronto! 👋"
            )
            close_session(session, reason="encuesta_no_satisfecho")
            return

        else:
            send_text(session, number, "Por favor responde *Sí* o *No* para continuar.")
            return

    # ============== ESTADOS DONDE HABLA EL ASESOR HUMANO ==========
    # Ejemplo: 'aceptado' -> ya está con humano; aquí el bot solo registra.
    return

# ============================================================
# ENDPOINTS
# ============================================================

@app.route('/welcome', methods=['GET'])
def Index():
    return 'welcome to the jungle'

# Verificación del webhook de WhatsApp (GET)
@app.route('/whatsapp', methods=['GET'])
def VerifyToken():
    try:
        accessToken = "7393374SHDSJ23UD"
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if token is not None and challenge is not None and token == accessToken:
            return challenge
        else:
            return "", 400
    except:
        return "", 400

# Webhook de WhatsApp / Mensaje entrante (POST)
@app.route('/whatsapp', methods=['POST'])
def RecievedMessage():
    try:
        body = request.get_json()
        entry = (body['entry'])[0]
        changes = (entry['changes'])[0]
        value = changes['value']
        message = (value['messages'])[0]
        number = message['from']
        text = util.GetTextUser(message=message)

        handle_new_message(text, number)
        print("💬 Mensaje recibido:", text)
        return "EVENT_RECEIVED"
        
    except Exception as e:
        print("❌ Error procesando mensaje:", e)
        return "EVENT_RECEIVED"

# Cerrar una sesión manualmente y disparar encuesta
@app.route('/sessions/<int:session_id>/close', methods=['POST'])
def close_session_manual(session_id):
    session = Session.query.get_or_404(session_id)
    if not session.is_active:
        return jsonify({"message": "La sesión ya está cerrada"}), 400

    number = session.user.phone_number
    encuesta_state = get_or_create_state(
        "esperando_calificacion",
        "Esperando que el usuario decida si quiere calificar"
    )
    session.current_state_id = encuesta_state.id
    db.session.commit()

    send_text(
        session,
        number,
        "La conversación ha finalizado. ¿Deseas calificar tu experiencia con nosotros? "
        "Responde *Sí* o *No*."
    )
    return jsonify({"message": "Sesión marcada para calificación"}), 200

# Ver sesiones activas (para inspeccionar en Postman)
@app.route('/sessions/active', methods=['GET'])
def list_active_sessions():
    sessions = Session.query.filter_by(is_active=True).all()
    data = []
    for s in sessions:
        data.append({
            "id": s.id,
            "user_phone": s.user.phone_number,
            "start_time": s.start_time.isoformat() if s.start_time else None,
            "last_message_time": s.last_message_time.isoformat() if s.last_message_time else None,
            "state": s.state.state_name if s.state else None
        })
    return jsonify(data), 200

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
