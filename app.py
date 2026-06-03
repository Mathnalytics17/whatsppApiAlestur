from flask import Flask, request, jsonify
import os
import re
import util
import whatsappservice
from models import db, User, Session, Message, State, SessionContext, PolicyConsent
from php_leads_service import create_or_update_php_lead
import config
from datetime import datetime, timedelta, timezone
import requests


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

    # Regla dura:
    # NO se actualiza last_message_time al cerrar.
    # last_message_time representa únicamente el último mensaje real del cliente.

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


def log_message(session, direction, text, message_type="text", update_last_message=None):
    now = datetime.now(timezone.utc)

    msg = Message(
        session_id=session.id,
        direction=direction,
        message_text=text or "",
        message_type=message_type,
        timestamp=now
    )
    db.session.add(msg)

    # Regla dura:
    # La inactividad se mide SOLO por mensajes entrantes reales del cliente.
    # Los mensajes salientes del bot, documentos, listas, warnings y encuestas
    # nunca renuevan last_message_time aunque alguien pase update_last_message=True.
    if direction == "in":
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


def clear_session_context(session, key):
    ctx = SessionContext.query.filter_by(
        session_id=session.id,
        context_key=key
    ).first()

    if ctx:
        db.session.delete(ctx)
        db.session.commit()


def clear_survey_context(session):
    clear_session_context(session, "timeout_poll_sent")
    clear_session_context(session, "inactivity_warning_sent")


def current_session_has_accepted_policy(session):
    """
    La autorización de política pertenece al ciclo/conversación actual.
    No es global ni permanente entre conversaciones cerradas.
    """
    if not session:
        return False

    return (
        PolicyConsent.query
        .filter_by(session_id=session.id, accepted=True)
        .first()
        is not None
    )


def move_session_to_accepted(session):
    session.current_state_id = get_or_create_state("aceptado").id
    db.session.commit()


def get_session_context(session, key):
    return SessionContext.query.filter_by(
        session_id=session.id,
        context_key=key
    ).first()


def set_session_context(session, key, value):
    now = datetime.now(timezone.utc)
    ctx = get_session_context(session, key)

    if not ctx:
        ctx = SessionContext(session_id=session.id, context_key=key)
        db.session.add(ctx)

    ctx.context_value = value
    ctx.updated_at = now
    db.session.commit()
    return ctx


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
def send_lead_to_php(user, session, first_message=None):
    """
    Envía el contacto aceptado hacia la página PHP para crear/actualizar un lead.
    No rompe el flujo del chatbot si la API PHP falla.
    """

    api_url = os.getenv("PHP_LEADS_API_URL", "").strip()
    api_token = os.getenv("PHP_LEADS_API_TOKEN", "").strip()

    if not api_url or not api_token:
        print("⚠️ PHP_LEADS_API_URL o PHP_LEADS_API_TOKEN no configurado. No se envió lead a PHP.", flush=True)
        return False

    phone_value = user.phone_number or ""

    payload = {
        # Campos que espera tu PHP
        "accepted": True,
        "phone": phone_value.replace("@lid", "").replace("@c.us", "") if phone_value else "",
        "phone_number": phone_value,
        "phone_jid": phone_value if "@" in phone_value else "",
        "jid": phone_value if "@" in phone_value else "",
        "name": user.name or "Contacto externo / WhatsApp",
        "bot_session": user.bot_session,
        "session": user.bot_session,
        "last_message": first_message or "Aceptó la política de tratamiento de datos personales",
        "message": first_message or "Aceptó la política de tratamiento de datos personales",
        "chatbot_user_id": user.id,
        "chatbot_session_id": session.id,
        "consent_at": datetime.now(timezone.utc).isoformat(),

        # Compatibilidad adicional
        "source": "chatbot_whatsapp",
        "channel": "whatsapp",
        "policy_accepted": True,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_token}",
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=15)

        print(
            f"📤 Lead enviado a PHP: {response.status_code} {response.text}",
            flush=True
        )

        return 200 <= response.status_code < 300

    except Exception as e:
        print(f"❌ Error enviando lead a PHP: {e}", flush=True)
        return False
    
    
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
        # Si el cliente vuelve después de una encuesta pendiente, el warning viejo no aplica.
        clear_inactivity_warning(session)

    log_message(session, "in", text)

    current_state = db.session.get(State, session.current_state_id)
    state_name = current_state.state_name.lower() if current_state else "inicio"
    text_lower = normalize_answer(text)

    print(f"🌀 Estado actual: {state_name} | sesión WPP: {bot_session} | cliente: {number}", flush=True)

    # ================== ESTADO INICIO ==================
    # La política se pide por ciclo/conversación, no de forma global.
    # Si por algún bug esta sesión ya tiene aceptación, se repara y pasa a aceptado.
    if state_name == "inicio":
        if current_session_has_accepted_policy(session):
            move_session_to_accepted(session)
            print(
                f"✅ Sesión actual ya tenía política aceptada. No se vuelve a solicitar. "
                f"Cliente={number} | sesión={bot_session}",
                flush=True
            )
            return

        send_policy_buttons(session, number)
        send_policy_documents(session, number)

        session.current_state_id = get_or_create_state("esperando_aceptacion").id
        db.session.commit()
        return

    # ================== ACEPTACIÓN ==================
    if state_name == "esperando_aceptacion":
        if is_accept(text_lower):
            save_policy_consent(session, accepted=True)

            send_lead_to_php(
                user=user,
                session=session,
                first_message=text
            )

            session.current_state_id = get_or_create_state("aceptado").id
            db.session.commit()

            send_text(
                session,
                number,
                "Perfecto. Uno de nuestros Asesores se comunicará con usted"
            )
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
            send_text(session, number, "Gracias por tu tiempo.")
            close_session(session, "no_quiso_calificar")
            return

        # Regla dura:
        # Si el cliente escribe algo distinto de sí/no, quiere retomar la conversación.
        # Se cancela la encuesta, la sesión sigue abierta y NO se vuelve a pedir política.
        clear_survey_context(session)
        move_session_to_accepted(session)

        print(
            f"🔁 Encuesta cancelada por mensaje normal. Cliente={number} | sesión={bot_session}",
            flush=True
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

            send_text(session, number, "Gracias por permitirnos estar conectados con usted a través de este canal. Hasta luego.")
            close_session(session, "encuesta_satisfecho")
            return

        if is_no(text_lower):
            ctx.context_value = "no_satisfecho"
            ctx.updated_at = now
            db.session.commit()

            send_text(session, number, "Gracias por tu sinceridad. Hasta luego.")
            close_session(session, "encuesta_no_satisfecho")
            return

        # También en la segunda pregunta: si escribe algo normal, retoma conversación.
        clear_survey_context(session)
        move_session_to_accepted(session)

        print(
            f"🔁 Encuesta de satisfacción cancelada por mensaje normal. Cliente={number} | sesión={bot_session}",
            flush=True
        )
        return

    # ================== ASESOR HUMANO ==================
    # Estado aceptado: el bot no responde; solo registra mensajes.
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
# API CRM PARA PHP ADMIN
# ============================================================

from functools import wraps
from flask import Response
import csv
import io


CRM_API_TOKEN = os.getenv("CRM_API_TOKEN", "")


def crm_auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not CRM_API_TOKEN:
            return jsonify({
                "status": "error",
                "message": "CRM_API_TOKEN no está configurado en el servidor"
            }), 500

        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({
                "status": "error",
                "message": "Token no enviado"
            }), 401

        token = auth_header.replace("Bearer ", "").strip()

        if token != CRM_API_TOKEN:
            return jsonify({
                "status": "error",
                "message": "Token inválido"
            }), 403

        return fn(*args, **kwargs)

    return wrapper


def format_datetime(value):
    if not value:
        return None

    try:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def get_policy_status_for_user(user_id):
    """
    Retorna el último consentimiento registrado del usuario.
    No usa BOOL_OR porque si una persona primero dijo No y luego Acepto,
    debe mandar el último estado real.
    """
    consent = (
        PolicyConsent.query
        .filter(PolicyConsent.user_id == user_id)
        .order_by(PolicyConsent.created_at.desc(), PolicyConsent.id.desc())
        .first()
    )

    if not consent:
        return {
            "policy_status": "Pendiente",
            "policy_accepted": None,
            "policy_date": None,
        }

    if consent.accepted is True:
        status = "Aceptó"
    else:
        status = "No aceptó"

    return {
        "policy_status": status,
        "policy_accepted": bool(consent.accepted),
        "policy_date": format_datetime(consent.created_at),
    }


def get_latest_session_for_user(user_id):
    return (
        Session.query
        .filter(Session.user_id == user_id)
        .order_by(Session.last_message_time.desc().nullslast(), Session.id.desc())
        .first()
    )


def get_latest_message_for_user(user_id):
    return (
        Message.query
        .join(Session, Session.id == Message.session_id)
        .filter(Session.user_id == user_id)
        .order_by(Message.timestamp.desc().nullslast(), Message.id.desc())
        .first()
    )


def build_contact_payload(user):
    latest_session = get_latest_session_for_user(user.id)
    latest_message = get_latest_message_for_user(user.id)
    policy = get_policy_status_for_user(user.id)

    total_messages = (
        Message.query
        .join(Session, Session.id == Message.session_id)
        .filter(Session.user_id == user.id)
        .count()
    )

    current_state = None
    is_active = False
    last_message_time = None

    if latest_session:
        is_active = bool(latest_session.is_active)
        last_message_time = latest_session.last_message_time

        if latest_session.current_state_id:
            state = State.query.get(latest_session.current_state_id)
            if state:
                current_state = state.state_name

    return {
        "id": user.id,
        "user_id": user.id,
        "phone_number": user.phone_number,
        "name": user.name,
        "bot_session": user.bot_session,
        "created_at": format_datetime(user.created_at),

        "policy_status": policy["policy_status"],
        "policy_accepted": policy["policy_accepted"],
        "policy_date": policy["policy_date"],

        "last_message_time": format_datetime(last_message_time),
        "current_state": current_state,
        "is_active": is_active,
        "total_messages": total_messages,

        "latest_message": {
            "id": latest_message.id if latest_message else None,
            "direction": latest_message.direction if latest_message else None,
            "message_text": latest_message.message_text if latest_message else None,
            "message_type": latest_message.message_type if latest_message else None,
            "timestamp": format_datetime(latest_message.timestamp) if latest_message else None,
        } if latest_message else None,
    }


@app.route("/api/crm/health", methods=["GET"])
@crm_auth_required
def crm_health():
    return jsonify({
        "status": "ok",
        "message": "CRM API funcionando",
    }), 200


@app.route("/api/crm/contacts", methods=["GET"])
@crm_auth_required
def crm_contacts():
    """
    Lista contactos para el panel PHP.

    Filtros opcionales:
    - ?session=alestur_ventas
    - ?policy=accepted | rejected | pending
    - ?q=texto
    - ?limit=50
    - ?offset=0
    """

    session_filter = request.args.get("session", "").strip()
    policy_filter = request.args.get("policy", "").strip().lower()
    q = request.args.get("q", "").strip()

    try:
        limit = int(request.args.get("limit", 100))
    except Exception:
        limit = 100

    try:
        offset = int(request.args.get("offset", 0))
    except Exception:
        offset = 0

    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    query = User.query

    if session_filter:
        query = query.filter(User.bot_session == session_filter)

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                User.phone_number.ilike(like),
                User.name.ilike(like),
                User.bot_session.ilike(like),
            )
        )

    users = (
        query
        .order_by(User.created_at.desc(), User.id.desc())
        .all()
    )

    contacts = [build_contact_payload(user) for user in users]

    if policy_filter:
        if policy_filter in ["accepted", "acepto", "aceptó"]:
            contacts = [c for c in contacts if c["policy_accepted"] is True]
        elif policy_filter in ["rejected", "no_acepto", "no acepto", "no aceptó"]:
            contacts = [c for c in contacts if c["policy_accepted"] is False]
        elif policy_filter in ["pending", "pendiente"]:
            contacts = [c for c in contacts if c["policy_accepted"] is None]

    contacts = sorted(
        contacts,
        key=lambda item: item["last_message_time"] or "",
        reverse=True
    )

    total = len(contacts)
    contacts_page = contacts[offset:offset + limit]

    return jsonify({
        "status": "ok",
        "total": total,
        "limit": limit,
        "offset": offset,
        "contacts": contacts_page,
        "data": contacts_page,
    }), 200


@app.route("/api/crm/contacts/<int:user_id>", methods=["GET"])
@crm_auth_required
def crm_contact_detail(user_id):
    user = User.query.get(user_id)

    if not user:
        return jsonify({
            "status": "error",
            "message": "Contacto no encontrado"
        }), 404

    return jsonify({
        "status": "ok",
        "contact": build_contact_payload(user),
    }), 200


def get_messages_payload_for_user(user_id):
    user = User.query.get(user_id)

    if not user:
        return None

    messages = (
        Message.query
        .join(Session, Session.id == Message.session_id)
        .filter(Session.user_id == user_id)
        .order_by(Message.timestamp.asc().nullslast(), Message.id.asc())
        .all()
    )

    data = []

    for message in messages:
        data.append({
            "id": message.id,
            "session_id": message.session_id,
            "direction": message.direction,
            "message_text": message.message_text,
            "content": message.message_text,  # Alias para compatibilidad con PHP viejo
            "message_type": message.message_type,
            "timestamp": format_datetime(message.timestamp),
        })

    return {
        "contact": build_contact_payload(user),
        "messages": data,
        "data": data,
        "total": len(data),
    }


@app.route("/api/crm/contacts/<int:user_id>/messages", methods=["GET"])
@crm_auth_required
def crm_contact_messages(user_id):
    payload = get_messages_payload_for_user(user_id)

    if payload is None:
        return jsonify({
            "status": "error",
            "message": "Contacto no encontrado"
        }), 404

    return jsonify({
        "status": "ok",
        **payload,
    }), 200


# Alias para evitar 404 si tu PHP quedó usando otra ruta
@app.route("/api/crm/contacts/<int:user_id>/conversation", methods=["GET"])
@crm_auth_required
def crm_contact_conversation(user_id):
    return crm_contact_messages(user_id)


@app.route("/api/crm/conversations/<int:user_id>/messages", methods=["GET"])
@crm_auth_required
def crm_conversation_messages(user_id):
    return crm_contact_messages(user_id)


@app.route("/api/crm/contacts/export", methods=["GET"])
@crm_auth_required
def crm_contacts_export():
    users = User.query.order_by(User.created_at.desc(), User.id.desc()).all()
    contacts = [build_contact_payload(user) for user in users]

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "Telefono",
        "Nombre",
        "Sesion chatbot",
        "Estado politica",
        "Acepto politica",
        "Fecha consentimiento",
        "Estado actual",
        "Sesion activa",
        "Ultimo mensaje",
        "Total mensajes",
        "Creado",
    ])

    for contact in contacts:
        writer.writerow([
            contact["id"],
            contact["phone_number"],
            contact["name"] or "",
            contact["bot_session"] or "",
            contact["policy_status"],
            "" if contact["policy_accepted"] is None else contact["policy_accepted"],
            contact["policy_date"] or "",
            contact["current_state"] or "",
            contact["is_active"],
            contact["last_message_time"] or "",
            contact["total_messages"],
            contact["created_at"] or "",
        ])

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=contactos_chatbot_alestur.csv"
        }
    )


@app.route("/api/crm/contacts/<int:user_id>/messages/export", methods=["GET"])
@crm_auth_required
def crm_contact_messages_export(user_id):
    payload = get_messages_payload_for_user(user_id)

    if payload is None:
        return jsonify({
            "status": "error",
            "message": "Contacto no encontrado"
        }), 404

    contact = payload["contact"]
    messages = payload["messages"]

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Contacto ID",
        "Telefono",
        "Sesion chatbot",
        "Mensaje ID",
        "Direccion",
        "Tipo",
        "Mensaje",
        "Fecha",
    ])

    for message in messages:
        writer.writerow([
            contact["id"],
            contact["phone_number"],
            contact["bot_session"],
            message["id"],
            message["direction"],
            message["message_type"],
            message["message_text"],
            message["timestamp"],
        ])

    csv_content = output.getvalue()
    output.close()

    filename = f"conversacion_{contact['id']}_{contact['bot_session']}.csv"

    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )