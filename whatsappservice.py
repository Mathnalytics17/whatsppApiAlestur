import os
import time
import requests


WPPCONNECT_URL = os.getenv("WPPCONNECT_URL", "http://wppconnect:21465").rstrip("/")
DEFAULT_SESSION = os.getenv("WPPCONNECT_SESSION", "alestur_ventas")
DEFAULT_TOKEN = os.getenv("WPPCONNECT_TOKEN", "")

SEND_DELAY_SECONDS = float(os.getenv("WPPCONNECT_SEND_DELAY_SECONDS", "1.2"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("WPPCONNECT_REQUEST_TIMEOUT_SECONDS", "30"))


def _env_key_for_session(session_name):
    """
    alestur_ventas -> WPPCONNECT_TOKEN_ALESTUR_VENTAS
    ventas-1       -> WPPCONNECT_TOKEN_VENTAS_1
    """
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
    """
    WPPConnect necesita:
    - phone sin sufijo para @lid y @c.us
    - isLid=True si viene como @lid
    - isGroup=True si viene como @g.us

    OJO: cuando WPPConnect recibe @lid desde el webhook, responder al número real puede fallar
    o irse al chat incorrecto. Por eso para @lid mandamos phone sin @lid + isLid=True.
    """
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
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    print("📤 WPPConnect response:", response.status_code, response.text, flush=True)
    return response


def SendMessageWhatsapp(data, session_name=None):
    """
    Adaptador compatible con tu código viejo.
    Convierte el formato estilo Meta a endpoints de WPPConnect.

    session_name permite usar varios números:
      SendMessageWhatsapp(data, session_name="alestur_ventas")
      SendMessageWhatsapp(data, session_name="alestur_reservas")
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

            payload = build_wpp_phone_payload(number)
            payload["message"] = text

            response = _post_wpp("send-message", payload, session_name=session_name)
            return response.status_code in [200, 201]

        if message_type == "interactive":
            sent = _send_interactive_buttons(data, number, session_name=session_name)
            if sent:
                return True

            # Fallback estable a texto normal
            body = data.get("interactive", {}).get("body", {}).get("text", "")
            buttons = data.get("interactive", {}).get("action", {}).get("buttons", [])

            options = []
            for btn in buttons:
                title = btn.get("reply", {}).get("title")
                if title:
                    options.append(f"- {title}")

            text = body
            if options:
                text += "\n\nResponde con una de estas opciones:\n" + "\n".join(options)

            payload = build_wpp_phone_payload(number)
            payload["message"] = text

            response = _post_wpp("send-message", payload, session_name=session_name)
            return response.status_code in [200, 201]

        if message_type == "document":
            doc = data.get("document", {})
            link = doc.get("link")
            caption = doc.get("caption", "Documento adjunto")

            # Estable: texto con link. Evita fallos con send-file por URL.
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


def _send_interactive_buttons(data, number, session_name=None):
    """
    Intenta usar botones reales de WPPConnect.
    La versión exacta puede variar, por eso probamos payloads conocidos y luego fallback.
    """
    interactive = data.get("interactive", {})
    body = interactive.get("body", {}).get("text", "")
    buttons = interactive.get("action", {}).get("buttons", [])

    button_labels = []
    for btn in buttons:
        title = btn.get("reply", {}).get("title")
        if title:
            button_labels.append(title)

    if not body or not button_labels:
        return False

    base = build_wpp_phone_payload(number)

    # Payload 1: común en WPPConnect Server para /send-buttons
    payloads = [
        {
            **base,
            "message": body,
            "buttons": button_labels,
            "title": "",
            "footer": "",
        },
        {
            **base,
            "title": "",
            "description": body,
            "buttons": button_labels,
            "footer": "",
        },
        {
            **base,
            "message": body,
            "buttonList": [
                {"id": str(i + 1), "text": label}
                for i, label in enumerate(button_labels)
            ],
            "footer": "",
        },
    ]

    for payload in payloads:
        try:
            response = _post_wpp("send-buttons", payload, session_name=session_name)
            if response.status_code in [200, 201]:
                return True
        except Exception as e:
            print("⚠️ send-buttons falló, probando fallback/payload siguiente:", repr(e), flush=True)

    return False


def clean_phone(number):
    if not number:
        return number

    return str(number).replace("+", "").strip()
