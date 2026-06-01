from flask import Flask, request, jsonify
import os
import re
import util
import whatsappservice
from models import db, User, Session, Message, State, SessionContext, PolicyConsent

import config
from datetime import datetime, timedelta, timezone

INACTIVITY_MINUTES = int(os.getenv("INACTIVITY_MINUTES", "10"))
WARNING_EXTRA_MINUTES = int(os.getenv("WARNING_EXTRA_MINUTES", "3"))
IGNORE_SAVED_CONTACTS = os.getenv("IGNORE_SAVED_CONTACTS", "false").lower() == "true"
CRM_API_TOKEN = os.getenv("CRM_API_TOKEN", "").strip()

app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)


# ============================================================
# HELPERS GENERALES
# ============================================================

def make_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def iso(dt):
    if dt is None:
        return None
    return make_aware(dt).isoformat()


def require_crm_token():
    """
    Protección simple para que la API del CRM/PHP no quede pública.
    Acepta:
    - Authorization: Bearer <CRM_API_TOKEN>
    - X-API-Token: <CRM_API_TOKEN>
    """
    if not CRM_API_TOKEN:
        return jsonify({"status": "error", "message": "CRM_API_TOKEN no está configurado en el servidor"}), 500

    auth = request.headers.get("Authorization", "").strip()
    header_token = request.headers.get("X-API-Token", "").strip()

    token = header_token
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()

    if token != CRM_API_TOKEN:
        return jsonify({"status": "error", "message": "No autorizado"}), 401

    return None


def normalize_bot_session(session_name):
    session_name = (session_name or os.getenv("WPPCONNECT_SESSION", "alestur_ventas")).strip()
    return session_name or "alestur_ventas"


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
    name = name.lower().strip()
    state = State.query.filter_by(state_name=name).first()
    if not state:
        state = State(state_name=name, description=description or name)
        db.session.add(state)
        db.session.commit()
    return state


def seed_default_states():
    states = [
        ("inicio", "Inicio de la conversación"),
        ("esperando_aceptacion", "Esperando aceptación de política de datos"),
        ("aceptado", "Política aceptada; puede continuar el asesor humano"),
        ("rechazado", "Política rechazada"),
        ("esperando_calificacion", "Esperando si el usuario desea calificar"),
        ("encuesta_satisfaccion", "Encuesta de satisfacción"),
        ("finalizado", "Sesión finalizada"),
    ]
    for name, description in states:
        get_or_create_state(name, description)


def get_or_create_user(phone_number, bot_session=None):
    bot_session = normalize_bot_session(bot_session)

    user = User.query.filter_by(
        phone_number=phone_number,
        bot_session=bot_session
    ).first()

    if not user:
        user = User(phone_number=phone_number, bot_session=bot_session)
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


def log_message(session, direction, text, message_type="text", update_last_message=True):
    now = datetime.now(timezone.utc)

    msg = Message(
        session_id=session.id,
        direction=direction,
        message_text=text or "",
        message_type=message_type
    )
    db.session.add(msg)

    if update_last_message:
        session.last_message_time = now

    db.session.commit()
    return msg


def send_text(session, number, text, update_last_message=True):
    bot_session = session.user.bot_session if session and session.user else None
    data = util.TextMessage(text, number=number)
    whatsappservice.SendMessageWhatsapp(data, session_name=bot_session)

    log_message(
        session,
        "out",
        text,
        message_type="text",
        update_last_message=update_last_message
    )


def send_yes_no_buttons(session, number, text, yes_label="Sí", no_label="No", update_last_message=True):
    bot_session = session.user.bot_session if session and session.user else None
    data = util.YesNoButtonMessage(number=number, text=text, yes_label=yes_label, no_label=no_label)
    sent = whatsappservice.SendMessageWhatsapp(data, session_name=bot_session)

    if not sent:
        fallback = f"{text}\n\nResponde con una opción:\n- {yes_label}\n- {no_label}"
        send_text(session, number, fallback, update_last_message=update_last_message)
        return

    log_message(
        session,
        "out",
        text,
        message_type="interactive",
        update_last_message=update_last_message
    )


def send_policy_buttons(session, number):
    bot_session = session.user.bot_session if session and session.user else None
    data_button = util.PolicyButtonMessage(number=number)
    sent = whatsappservice.SendMessageWhatsapp(data_button, session_name=bot_session)

    body_text = data_button["interactive"]["body"]["text"]

    if not sent:
        fallback = (
            body_text
            + "\n\nResponde con una opción:\n- Acepto\n- No acepto"
        )
        send_text(session, number, fallback)
        return

    log_message(session, "out", body_text, message_type="interactive")


def send_policy_documents(session, number):
    filenames = [
        "politica_datos.pdf",
        "autorizacion_datos.pdf",
    ]

    bot_session = session.user.bot_session if session and session.user else None

    for filename in filenames:
        data = util.TextDocumentMessage(number, filename)
        whatsappservice.SendMessageWhatsapp(data, session_name=bot_session)
        log_message(
            session,
            "out",
            f"Documento enviado: {filename}",
            message_type="document"
        )


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


def normalize_answer(text):
    text = (text or "").strip().lower()
    text = text.replace("í", "i")
    text = re.sub(r"\s+", " ", text)
    return text


def is_yes(text):
    return normalize_answer(text) in ["si", "s", "yes", "acepto calificar", "calificar"]


def is_no(text):
    return normalize_answer(text) in ["no", "n", "no calificar"]


def is_accept(text):
    t = normalize_answer(text)
    return t in ["acepto", "aceptar", "si acepto", "de acuerdo", "estoy de acuerdo"]


def is_reject(text):
    t = normalize_answer(text)
    return t in ["no acepto", "no aceptar", "rechazo", "no"]


# ============================================================
# LÓGICA DE MENSAJES
# ============================================================

def handle_new_message(text, number, bot_session=None):
    now = datetime.now(timezone.utc)
    bot_session = normalize_bot_session(bot_session)

    user = get_or_create_user(number, bot_session=bot_session)
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
        clear_inactivity_warning(session)

    log_message(session, "in", text)

    current_state = db.session.get(State, session.current_state_id)
    state_name = current_state.state_name.lower() if current_state else "inicio"
    text_lower = normalize_answer(text)

    print(f"🌀 Estado actual: {state_name} | sesión WPP: {bot_session} | cliente: {number}", flush=True)

    # ================== ESTADO INICIO ==================
    # Se activa con el primer mensaje que escriba la persona. No depende de "hola".
    if state_name == "inicio":
        send_policy_buttons(session, number)
        send_policy_documents(session, number)

        session.current_state_id = get_or_create_state("esperando_aceptacion").id
        db.session.commit()
        return

    # ================== ACEPTACIÓN ==================
    if state_name == "esperando_aceptacion":
        if is_accept(text_lower):
            save_policy_consent(session, accepted=True)

            session.current_state_id = get_or_create_state("aceptado").id
            db.session.commit()

            send_text(session, number, "Perfecto ✅. Uno de nuestros Asesores se comunicará con usted ")
            return

        if is_reject(text_lower):
            save_policy_consent(session, accepted=False)

            session.current_state_id = get_or_create_state("rechazado").id
            db.session.commit()

            send_text(session, number, "Sin aceptar la política no podemos continuar. La sesión será cerrada.")
            close_session(session, "no_acepta_politica")
            return

        send_policy_buttons(session, number)
        return

    # ================== PREGUNTA ENCUESTA ==================
    if state_name == "esperando_calificacion":
        if is_yes(text_lower):
            session.current_state_id = get_or_create_state("encuesta_satisfaccion").id
            db.session.commit()

            send_yes_no_buttons(
                session,
                number,
                "¿Quedaste satisfecho con la atención?",
                yes_label="Sí",
                no_label="No"
            )
            return

        if is_no(text_lower):
            send_text(session, number, "Gracias por tu tiempo 😊")
            close_session(session, "no_quiso_calificar")
            return

        send_yes_no_buttons(
            session,
            number,
            "¿Deseas calificar tu experiencia con nosotros?",
            yes_label="Sí",
            no_label="No"
        )
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

        if is_yes(text_lower):
            ctx.context_value = "satisfecho"
            ctx.updated_at = now
            db.session.commit()

            send_text(session, number, "Gracias, por permitirnos estar conectados con usted a través de este canal ¡hasta luego!")
            close_session(session, "encuesta_satisfecho")
            return

        if is_no(text_lower):
            ctx.context_value = "no_satisfecho"
            ctx.updated_at = now
            db.session.commit()

            send_text(session, number, "Gracias por tu sinceridad 🙏, ¡hasta luego!")
            close_session(session, "encuesta_no_satisfecho")
            return

        send_yes_no_buttons(
            session,
            number,
            "Por favor confirma: ¿quedaste satisfecho con la atención?",
            yes_label="Sí",
            no_label="No"
        )
        return

    # ================== ASESOR HUMANO ==================
    # Estado "aceptado": el bot ya no responde; solo registra mensajes.
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
        accessToken = os.getenv("META_VERIFY_TOKEN", "7393374SHDSJ23UD")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if token and challenge and token == accessToken:
            return challenge
        return "", 400
    except Exception:
        return "", 400


@app.route('/whatsapp', methods=['POST'])
def RecievedMessage():
    try:
        body = request.get_json()
        entry = body['entry'][0]
        message = entry['changes'][0]['value']['messages'][0]

        number = message['from']
        text = util.GetTextUser(message)

        handle_new_message(text, number, bot_session=os.getenv("WPPCONNECT_SESSION", "alestur_ventas"))

        print("💬 Mensaje Meta recibido:", text, flush=True)
        return "EVENT_RECEIVED"
    except Exception as e:
        print("❌ Error procesando mensaje Meta:", e, flush=True)
        return "EVENT_RECEIVED"


@app.route('/wppconnect', methods=['POST'])
def WppconnectWebhook():
    try:
        body = request.get_json() or {}
        print("📥 Webhook WPPConnect recibido:", body, flush=True)

        event = body.get("event")

        # Solo procesamos mensajes reales.
        if event and event not in ["onmessage", "onMessage", "message"]:
            print(f"⏭️ Evento ignorado de WPPConnect: {event}", flush=True)
            return jsonify({"status": "ignored_event"}), 200

        # Ignorar ACKs/mensajes enviados por nosotros mismos
        msg_id = body.get("id") or {}
        if isinstance(msg_id, dict) and msg_id.get("fromMe") is True:
            print("⏭️ Mensaje propio/ACK ignorado", flush=True)
            return jsonify({"status": "ignored_from_me"}), 200

        if body.get("fromMe") is True:
            print("⏭️ Mensaje propio ignorado", flush=True)
            return jsonify({"status": "ignored_from_me"}), 200

        data = body.get("data") or body.get("message") or {}

        if isinstance(data, dict) and data.get("fromMe") is True:
            print("⏭️ Mensaje propio ignorado desde data", flush=True)
            return jsonify({"status": "ignored_from_me"}), 200

        extracted = extract_wppconnect_message(body)

        if not extracted:
            return jsonify({"status": "ignored"}), 200

        text = extracted["text"]
        number = extracted["number"]
        bot_session = normalize_bot_session(extracted.get("bot_session") or body.get("session"))

        if not text or not number:
            return jsonify({"status": "ignored_empty"}), 200

        print(f"💬 WPPConnect mensaje recibido de {number} para {bot_session}: {text}", flush=True)

        handle_new_message(text, number, bot_session=bot_session)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("❌ Error procesando webhook WPPConnect:", repr(e), flush=True)
        return jsonify({"status": "error"}), 200


def extract_wppconnect_message(body):
    data = body.get("data") or body.get("message") or body

    if isinstance(data, list):
        if not data:
            return None
        data = data[0]

    if not isinstance(data, dict):
        return None

    if data.get("fromMe") is True:
        return None

    # Ignorar grupos por ahora
    if data.get("isGroupMsg") is True:
        return None

    sender = data.get("sender") or body.get("sender") or {}

    if IGNORE_SAVED_CONTACTS and sender.get("isMyContact") is True:
        print("⏭️ Contacto guardado ignorado:", sender.get("formattedName") or data.get("from"), flush=True)
        return None

    # Número del cliente
    number = (
        data.get("from")
        or data.get("chatId")
        or data.get("sender", {}).get("id")
        or data.get("author")
    )

    # Texto del mensaje
    text = (
        data.get("body")
        or data.get("text")
        or data.get("content")
        or data.get("message")
        or ""
    )

    if isinstance(text, dict):
        text = (
            text.get("body")
            or text.get("conversation")
            or text.get("text")
            or ""
        )

    if not number:
        return None

    number = normalize_wpp_number(number)

    return {
        "number": number,
        "text": str(text).strip(),
        "bot_session": body.get("session") or data.get("session"),
    }


def normalize_wpp_number(number):
    if not number:
        return number

    number = str(number).replace("+", "").strip()
    return number


@app.route('/sessions/<int:session_id>/close', methods=['POST'])
def close_session_manual(session_id):
    session = Session.query.get_or_404(session_id)

    if not session.is_active:
        return jsonify({"message": "La sesión ya está cerrada"}), 400

    number = session.user.phone_number

    session.current_state_id = get_or_create_state("esperando_calificacion").id
    db.session.commit()

    send_yes_no_buttons(
        session,
        number,
        "La conversación ha finalizado. ¿Deseas calificar tu experiencia?",
        yes_label="Sí",
        no_label="No"
    )

    return jsonify({"message": "Sesión marcada para calificación"}), 200


@app.route('/sessions/active', methods=['GET'])
def list_active_sessions():
    sessions = Session.query.filter_by(is_active=True).all()
    data = [{
        "id": s.id,
        "bot_session": s.user.bot_session,
        "user_phone": s.user.phone_number,
        "start_time": s.start_time.isoformat() if s.start_time else None,
        "last_message_time": s.last_message_time.isoformat() if s.last_message_time else None,
        "state": s.state.state_name if s.state else None
    } for s in sessions]

    return jsonify(data), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


# ============================================================



# ============================================================
# API PRIVADA PARA CRM / PÁGINA PHP
# ============================================================

@app.route("/api/crm/health", methods=["GET"])
def crm_health():
    denied = require_crm_token()
    if denied:
        return denied
    return jsonify({"status": "ok"}), 200


@app.route("/api/crm/contacts", methods=["GET"])
def crm_contacts():
    denied = require_crm_token()
    if denied:
        return denied

    bot_session = request.args.get("bot_session")
    accepted = request.args.get("accepted")
    active = request.args.get("active")
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = max(int(request.args.get("offset", 0)), 0)

    query = User.query
    if bot_session:
        query = query.filter(User.bot_session == bot_session)
    if q:
        query = query.filter((User.phone_number.ilike(f"%{q}%")) | (User.name.ilike(f"%{q}%")))

    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    rows = []

    for user in users:
        latest_session = (
            Session.query
            .filter_by(user_id=user.id)
            .order_by(Session.start_time.desc())
            .first()
        )
        latest_consent = (
            PolicyConsent.query
            .filter_by(user_id=user.id)
            .order_by(PolicyConsent.created_at.desc())
            .first()
        )
        latest_message = None
        if latest_session:
            latest_message = (
                Message.query
                .filter_by(session_id=latest_session.id)
                .order_by(Message.timestamp.desc())
                .first()
            )

        if accepted is not None:
            desired = accepted.lower() in ["1", "true", "yes", "si", "sí", "acepto"]
            if not latest_consent or bool(latest_consent.accepted) != desired:
                continue

        if active is not None:
            desired_active = active.lower() in ["1", "true", "yes", "si", "sí"]
            if not latest_session or bool(latest_session.is_active) != desired_active:
                continue

        rows.append({
            "id": user.id,
            "phone_number": user.phone_number,
            "name": user.name,
            "bot_session": user.bot_session,
            "created_at": iso(user.created_at),
            "latest_session": None if not latest_session else {
                "id": latest_session.id,
                "is_active": latest_session.is_active,
                "state": latest_session.state.state_name if latest_session.state else None,
                "start_time": iso(latest_session.start_time),
                "end_time": iso(latest_session.end_time),
                "last_message_time": iso(latest_session.last_message_time),
            },
            "latest_consent": None if not latest_consent else {
                "accepted": latest_consent.accepted,
                "created_at": iso(latest_consent.created_at),
            },
            "latest_message": None if not latest_message else {
                "direction": latest_message.direction,
                "message_type": latest_message.message_type,
                "content": latest_message.content,
                "timestamp": iso(latest_message.timestamp),
            },
        })

    return jsonify({"status": "ok", "count": len(rows), "results": rows}), 200


@app.route("/api/crm/contacts/<int:user_id>/messages", methods=["GET"])
def crm_contact_messages(user_id):
    denied = require_crm_token()
    if denied:
        return denied

    limit = min(int(request.args.get("limit", 100)), 500)
    user = User.query.get_or_404(user_id)

    sessions = Session.query.filter_by(user_id=user.id).order_by(Session.start_time.desc()).all()
    session_ids = [s.id for s in sessions]

    messages = []
    if session_ids:
        messages = (
            Message.query
            .filter(Message.session_id.in_(session_ids))
            .order_by(Message.timestamp.asc())
            .limit(limit)
            .all()
        )

    return jsonify({
        "status": "ok",
        "user": {
            "id": user.id,
            "phone_number": user.phone_number,
            "name": user.name,
            "bot_session": user.bot_session,
        },
        "messages": [
            {
                "id": m.id,
                "session_id": m.session_id,
                "direction": m.direction,
                "message_type": m.message_type,
                "content": m.content,
                "timestamp": iso(m.timestamp),
            }
            for m in messages
        ]
    }), 200


@app.route("/api/crm/sessions/active", methods=["GET"])
def crm_active_sessions():
    denied = require_crm_token()
    if denied:
        return denied

    bot_session = request.args.get("bot_session")
    query = Session.query.join(User).filter(Session.is_active == True)
    if bot_session:
        query = query.filter(User.bot_session == bot_session)

    sessions = query.order_by(Session.last_message_time.desc()).all()
    return jsonify({
        "status": "ok",
        "count": len(sessions),
        "results": [
            {
                "session_id": s.id,
                "user_id": s.user.id,
                "phone_number": s.user.phone_number,
                "name": s.user.name,
                "bot_session": s.user.bot_session,
                "state": s.state.state_name if s.state else None,
                "start_time": iso(s.start_time),
                "last_message_time": iso(s.last_message_time),
            }
            for s in sessions
        ]
    }), 200


@app.route("/api/crm/sessions/<int:session_id>/close", methods=["POST"])
def crm_close_session(session_id):
    denied = require_crm_token()
    if denied:
        return denied

    session = Session.query.get_or_404(session_id)
    session.is_active = False
    session.end_time = datetime.now(timezone.utc)
    final_state = get_or_create_state("finalizado", "Sesión cerrada manualmente desde CRM")
    session.current_state_id = final_state.id
    db.session.commit()

    return jsonify({"status": "ok", "message": "Sesión cerrada", "session_id": session.id}), 200


@app.route("/api/crm/summary", methods=["GET"])
def crm_summary():
    denied = require_crm_token()
    if denied:
        return denied

    bot_session = request.args.get("bot_session")
    user_query = User.query
    session_query = Session.query.join(User)
    consent_query = PolicyConsent.query.join(User)

    if bot_session:
        user_query = user_query.filter(User.bot_session == bot_session)
        session_query = session_query.filter(User.bot_session == bot_session)
        consent_query = consent_query.filter(User.bot_session == bot_session)

    return jsonify({
        "status": "ok",
        "total_contacts": user_query.count(),
        "active_sessions": session_query.filter(Session.is_active == True).count(),
        "accepted_consents": consent_query.filter(PolicyConsent.accepted == True).count(),
        "rejected_consents": consent_query.filter(PolicyConsent.accepted == False).count(),
    }), 200

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_default_states()
    app.run(debug=True)
