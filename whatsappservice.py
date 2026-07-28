import os
import time
import requests


WPPCONNECT_URL = os.getenv("WPPCONNECT_URL", "http://wppconnect:21465").rstrip("/")
DEFAULT_SESSION = os.getenv("WPPCONNECT_SESSION") or os.getenv("WPPCONNECT_DEFAULT_SESSION", "alestur_ventas")
DEFAULT_TOKEN = os.getenv("WPPCONNECT_TOKEN", "")

SEND_DELAY_SECONDS = float(os.getenv("WPPCONNECT_SEND_DELAY_SECONDS", "1.2"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("WPPCONNECT_REQUEST_TIMEOUT_SECONDS", "30"))


def _env_key_for_session(session_name):
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(session_name).upper())
    return f"WPPCONNECT_TOKEN_{safe}"


def get_token(session_name=None):
    session_name = session_name or DEFAULT_SESSION
    return os.getenv(_env_key_for_session(session_name)) or DEFAULT_TOKEN


def _headers(session_name=None):
    token = get_token(session_name)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _sleep_between_messages():
    if SEND_DELAY_SECONDS > 0:
        time.sleep(SEND_DELAY_SECONDS)


def build_wpp_phone_payload(number):
    """
    Construye SIEMPRE el payload correcto para WPPConnect.

    - 225872464322752@lid -> phone=225872464322752, isLid=True
    - 573001112233@c.us   -> phone=573001112233, isLid=False
    - 573001112233        -> phone=573001112233, isLid=False
    - grupo@g.us          -> phone=grupo@g.us, isGroup=True
    """
    if not number:
        return {
            "phone": number,
            "isGroup": False,
            "isNewsletter": False,
            "isLid": False,
        }

    raw = str(number).replace("+", "").strip()

    is_lid = raw.endswith("@lid")
    is_group = raw.endswith("@g.us")

    if is_lid:
        phone = raw[:-4]
    elif raw.endswith("@c.us"):
        phone = raw[:-5]
    else:
        phone = raw

    return {
        "phone": phone,
        "isGroup": is_group,
        "isNewsletter": False,
        "isLid": is_lid,
    }


def _wpp_response_was_delivered(response):
    """
    WPPConnect puede devolver HTTP 200/201 aunque WhatsApp haya fallado.
    Si viene ack=-1 o isSendFailure=True, NO se considera entregado.
    """
    if response.status_code not in [200, 201]:
        return False

    try:
        data = response.json()
    except Exception:
        return True

    items = data.get("response")

    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                if item.get("isSendFailure") is True or item.get("ack") == -1:
                    return False

    if isinstance(items, dict):
        if items.get("isSendFailure") is True or items.get("ack") == -1:
            return False

    return True


def _post_wpp(path, payload, session_name=None):
    session_name = session_name or DEFAULT_SESSION
    url = f"{WPPCONNECT_URL}/api/{session_name}/{path.lstrip('/')}"

    print("📤 WPPConnect URL:", url, flush=True)
    print("📤 WPPConnect payload:", payload, flush=True)

    _sleep_between_messages()

    response = requests.post(
        url,
        json=payload,
        headers=_headers(session_name),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    print("📤 WPPConnect response:", response.status_code, response.text, flush=True)
    return response


def SendMessageWhatsapp(data, session_name=None):
    """
    Adaptador compatible con tu código viejo de Meta Cloud API, pero enviando por WPPConnect.
    Maneja correctamente @lid en texto, listas, botones convertidos a listas y documentos.
    """
    try:
        session_name = session_name or DEFAULT_SESSION
        number = data.get("to") or data.get("phone")
        message_type = data.get("type", "text")

        if not number:
            print("❌ No llegó número destino en data:", data, flush=True)
            return False

        if message_type == "text":
            text = data.get("text", {}).get("body") or data.get("message") or ""
            return _send_text(number, text, session_name=session_name, label="send-message")

        if message_type == "interactive":
            interactive_type = data.get("interactive", {}).get("type")

            if interactive_type == "list":
                # _send_interactive_list ya realiza un único fallback a texto.
                return _send_interactive_list(data, number, session_name=session_name)

            if interactive_type == "button":
                # _send_buttons_as_list ya realiza un único fallback a texto.
                return _send_buttons_as_list(data, number, session_name=session_name)

            text = _interactive_to_text(data)
            return _send_text(number, text, session_name=session_name, label="fallback-interactive-text")

        if message_type == "document":
            doc = data.get("document", {})
            link = doc.get("link", "")
            caption = doc.get("caption", "Documento adjunto")
            text = f"{caption}:\n{link}" if link else caption
            return _send_text(number, text, session_name=session_name, label="document-as-link")

        print("⚠️ Tipo de mensaje no soportado todavía:", message_type, data, flush=True)
        return False

    except Exception as exception:
        print("❌ Error enviando por WPPConnect:", repr(exception), flush=True)
        return False


def _send_text(number, text, session_name=None, label="send-message"):
    payload = build_wpp_phone_payload(number)
    payload["message"] = text

    print(
        f"📞 Destino WPPConnect: {payload.get('phone')} | isLid={payload.get('isLid')}",
        flush=True,
    )

    response = _post_wpp("send-message", payload, session_name=session_name)
    delivered = _wpp_response_was_delivered(response)

    if not delivered:
        print(f"⚠️ WPPConnect {label}: WhatsApp NO entregó el mensaje", flush=True)

    return delivered


def _interactive_to_text(data):
    interactive = data.get("interactive", {})
    body = interactive.get("body", {}).get("text", "")
    action = interactive.get("action", {})

    options = []

    for btn in action.get("buttons", []):
        title = btn.get("reply", {}).get("title")
        if title:
            options.append(f"- {title}")

    for section in action.get("sections", []):
        for row in section.get("rows", []):
            title = row.get("title")
            if title:
                options.append(f"- {title}")

    text = body or "Selecciona una opción:"
    if options:
        text += "\n\nResponde con una de estas opciones:\n" + "\n".join(options)
    return text


def _send_interactive_list(data, number, session_name=None):
    interactive = data.get("interactive", {})
    body = interactive.get("body", {}).get("text", "")
    action = interactive.get("action", {})
    sections = action.get("sections", [])
    button_text = action.get("button") or action.get("buttonText") or "Responder"

    if not body or not sections:
        return False

    converted_sections = []
    for section in sections:
        rows = []
        for row in section.get("rows", []):
            title = row.get("title")
            if not title:
                continue

            rows.append({
                "rowId": row.get("id") or row.get("rowId") or title,
                "title": title,
                "description": row.get("description", ""),
            })

        if rows:
            converted_sections.append({
                "title": section.get("title", "Opciones"),
                "rows": rows,
            })

    if not converted_sections:
        return False

    payload = build_wpp_phone_payload(number)
    payload.update({
        "description": body,
        "buttonText": button_text,
        "sections": converted_sections,
    })

    response = _post_wpp("send-list-message", payload, session_name=session_name)

    if _wpp_response_was_delivered(response):
        return True

    print("⚠️ Lista falló. Enviando fallback como texto.", flush=True)
    fallback_text = _interactive_to_text(data)
    return _send_text(number, fallback_text, session_name=session_name, label="fallback-list-text")


def _send_buttons_as_list(data, number, session_name=None):
    interactive = data.get("interactive", {})
    body = interactive.get("body", {}).get("text", "")
    buttons = interactive.get("action", {}).get("buttons", [])

    rows = []
    for i, btn in enumerate(buttons):
        title = btn.get("reply", {}).get("title")
        if title:
            rows.append({
                "rowId": btn.get("reply", {}).get("id") or str(i + 1),
                "title": title,
                "description": "",
            })

    if not body or not rows:
        return False

    payload = build_wpp_phone_payload(number)
    payload.update({
        "description": body,
        "buttonText": "Responder",
        "sections": [{"title": "Opciones", "rows": rows}],
    })

    response = _post_wpp("send-list-message", payload, session_name=session_name)

    if _wpp_response_was_delivered(response):
        return True

    print("⚠️ Botones convertidos a lista fallaron. Enviando fallback como texto.", flush=True)
    fallback_text = _interactive_to_text(data)
    return _send_text(number, fallback_text, session_name=session_name, label="fallback-buttons-text")


def clean_phone(number):
    if not number:
        return number
    return str(number).replace("+", "").strip()
