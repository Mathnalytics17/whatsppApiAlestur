import os
import requests

WPPCONNECT_URL = os.getenv("WPPCONNECT_URL", "http://wppconnect:21465").rstrip("/")
WPPCONNECT_SESSION = os.getenv("WPPCONNECT_SESSION", "alestur_ventas")
WPPCONNECT_TOKEN = os.getenv("WPPCONNECT_TOKEN", "").strip().strip("'").strip('"')


def _headers():
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if WPPCONNECT_TOKEN:
        headers["Authorization"] = f"Bearer {WPPCONNECT_TOKEN}"
    return headers


def build_wpp_phone_payload(number):
    """
    WPPConnect necesita:
    - phone sin @lid / @c.us
    - isLid=True cuando el identificador entrante viene como @lid
    - isGroup=True cuando viene como grupo @g.us
    """
    if not number:
        return {"phone": number, "isGroup": False, "isNewsletter": False, "isLid": False}

    number = str(number).replace("+", "").strip()
    is_lid = number.endswith("@lid")
    is_group = number.endswith("@g.us")

    if number.endswith("@lid"):
        phone = number[:-4]
    elif number.endswith("@c.us"):
        phone = number[:-5]
    else:
        phone = number

    return {
        "phone": phone,
        "isGroup": is_group,
        "isNewsletter": False,
        "isLid": is_lid,
    }


def _post_wpp(endpoint, payload, label):
    url = f"{WPPCONNECT_URL}/api/{WPPCONNECT_SESSION}/{endpoint}"
    print(f"📤 WPPConnect payload {label}:", payload, flush=True)

    response = requests.post(url, json=payload, headers=_headers(), timeout=30)
    print(f"📤 WPPConnect {label}:", response.status_code, response.text, flush=True)

    if response.status_code not in (200, 201):
        return False

    try:
        body = response.json()
    except Exception:
        return True

    # WPPConnect puede responder status success aunque WhatsApp falle internamente.
    # Si ack=-1 o isSendFailure=true, para nosotros es envío fallido.
    items = body.get("response")
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and (item.get("isSendFailure") is True or item.get("ack") == -1):
                print("❌ WhatsApp marcó el envío como fallido aunque WPPConnect respondió success", flush=True)
                return False

    return True


def SendMessageWhatsapp(data):
    try:
        number = data.get("to") or data.get("phone")
        message_type = data.get("type", "text")

        if not number:
            print("❌ No llegó número destino en data:", data, flush=True)
            return False

        if message_type == "text":
            text = data.get("text", {}).get("body") or data.get("message") or ""
            payload = build_wpp_phone_payload(number)
            payload["message"] = text
            return _post_wpp("send-message", payload, "send-message")

        if message_type == "interactive":
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
            return _post_wpp("send-message", payload, "interactive->text")

        if message_type == "document":
            doc = data.get("document", {})
            link = doc.get("link")
            caption = doc.get("caption", "Documento adjunto")
            text = f"{caption}:\n{link}"

            payload = build_wpp_phone_payload(number)
            payload["message"] = text
            return _post_wpp("send-message", payload, "document->link")

        print("⚠️ Tipo de mensaje no soportado todavía:", message_type, data, flush=True)
        return False

    except Exception as exception:
        print("❌ Error enviando por WPPConnect:", exception, flush=True)
        return False
