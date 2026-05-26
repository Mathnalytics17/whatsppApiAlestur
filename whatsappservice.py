import os
import time
import requests


WPPCONNECT_URL = os.getenv("WPPCONNECT_URL", "http://wppconnect:21465").rstrip("/")
DEFAULT_SESSION = os.getenv("WPPCONNECT_SESSION") or os.getenv("WPPCONNECT_DEFAULT_SESSION", "alestur_ventas")
DEFAULT_TOKEN = os.getenv("WPPCONNECT_TOKEN", "")

SEND_DELAY_SECONDS = float(os.getenv("WPPCONNECT_SEND_DELAY_SECONDS", "1.2"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("WPPCONNECT_REQUEST_TIMEOUT_SECONDS", "30"))


def _env_key_for_session(session_name):
    safe = "".join(ch if ch.isalnum() else "_" for ch in session_name.upper())
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
    if not number:
        return {
            "phone": number,
            "isGroup": False,
            "isNewsletter": False,
            "isLid": False,
        }

    number = str(number).replace("+", "").strip()

    is_lid = number.endswith("@lid")
    is_group = number.endswith("@g.us")

    if number.endswith("@lid"):
        phone = number.replace("@lid", "")
    elif number.endswith("@c.us"):
        phone = number.replace("@c.us", "")
    else:
        phone = number

    return {
        "phone": phone,
        "isGroup": is_group,
        "isNewsletter": False,
        "isLid": is_lid,
    }


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
    try:
        session_name = session_name or DEFAULT_SESSION
        number = data.get("to") or data.get("phone")
        message_type = data.get("type", "text")

        if not number:
            print("❌ No llegó número destino en data:", data, flush=True)
            return False

        if message_type == "text":
            text = data.get("text", {}).get("body") or data.get("message") or ""
            payload = build_wpp_phone_payload(number)
            payload["message"] = text
            response = _post_wpp("send-message", payload, session_name=session_name)
            return response.status_code in [200, 201]

        if message_type == "interactive":
            interactive_type = data.get("interactive", {}).get("type")

            if interactive_type == "list":
                sent = _send_interactive_list(data, number, session_name=session_name)
                if sent:
                    return True

            # Si en algún punto vuelve a llegar formato button, lo convertimos a lista primero.
            if interactive_type == "button":
                sent = _send_buttons_as_list(data, number, session_name=session_name)
                if sent:
                    return True

            # Fallback estable a texto normal.
            text = _interactive_to_text(data)
            payload = build_wpp_phone_payload(number)
            payload["message"] = text
            response = _post_wpp("send-message", payload, session_name=session_name)
            return response.status_code in [200, 201]

        if message_type == "document":
            doc = data.get("document", {})
            link = doc.get("link")
            caption = doc.get("caption", "Documento adjunto")
            text = f"{caption}:\n{link}"
            payload = build_wpp_phone_payload(number)
            payload["message"] = text
            response = _post_wpp("send-message", payload, session_name=session_name)
            return response.status_code in [200, 201]

        print("⚠️ Tipo de mensaje no soportado todavía:", message_type, data, flush=True)
        return False

    except Exception as exception:
        print("❌ Error enviando por WPPConnect:", repr(exception), flush=True)
        return False


def _interactive_to_text(data):
    interactive = data.get("interactive", {})
    body = interactive.get("body", {}).get("text", "")
    action = interactive.get("action", {})

    options = []

    # Formato button
    for btn in action.get("buttons", []):
        title = btn.get("reply", {}).get("title")
        if title:
            options.append(f"- {title}")

    # Formato list
    for section in action.get("sections", []):
        for row in section.get("rows", []):
            title = row.get("title")
            if title:
                options.append(f"- {title}")

    text = body
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
    return response.status_code in [200, 201]


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
    return response.status_code in [200, 201]


def clean_phone(number):
    if not number:
        return number
    return str(number).replace("+", "").strip()
