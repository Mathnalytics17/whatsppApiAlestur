import os
import requests


WPPCONNECT_URL = os.getenv("WPPCONNECT_URL", "http://wppconnect:21465")
WPPCONNECT_SESSION = os.getenv("WPPCONNECT_SESSION", "alestur_ventas")
WPPCONNECT_TOKEN = os.getenv("WPPCONNECT_TOKEN", "")


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
    - phone sin sufijo
    - isLid=True si viene como @lid
    - isGroup=True si viene como @g.us
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

            url = f"{WPPCONNECT_URL}/api/{WPPCONNECT_SESSION}/send-message"
            print("📤 WPPConnect payload:", payload, flush=True)

            response = requests.post(url, json=payload, headers=_headers(), timeout=30)

            print("📤 WPPConnect send-message:", response.status_code, response.text, flush=True)
            return response.status_code in [200, 201]

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

            url = f"{WPPCONNECT_URL}/api/{WPPCONNECT_SESSION}/send-message"
            print("📤 WPPConnect payload:", payload, flush=True)

            response = requests.post(url, json=payload, headers=_headers(), timeout=30)

            print("📤 WPPConnect interactive->text:", response.status_code, response.text, flush=True)
            return response.status_code in [200, 201]

        if message_type == "document":
            doc = data.get("document", {})
            link = doc.get("link")
            caption = doc.get("caption", "Documento adjunto")

            text = f"{caption}:\n{link}"

            payload = build_wpp_phone_payload(number)
            payload["message"] = text

            url = f"{WPPCONNECT_URL}/api/{WPPCONNECT_SESSION}/send-message"
            print("📤 WPPConnect payload:", payload, flush=True)

            response = requests.post(url, json=payload, headers=_headers(), timeout=30)

            print("📤 WPPConnect document->link:", response.status_code, response.text, flush=True)
            return response.status_code in [200, 201]

        print("⚠️ Tipo de mensaje no soportado todavía:", message_type, data, flush=True)
        return False

    except Exception as exception:
        print("❌ Error enviando por WPPConnect:", exception, flush=True)
        return False


def clean_phone(number):
    if not number:
        return number

    return str(number).replace("+", "").strip()


def GetTextUser(message):
    text = ""
    typeMessage = message["type"]

    if typeMessage == "text":
        text = message["text"]["body"]

    elif typeMessage == "interactive":
        interactiveObject = message["interactive"]
        typeInteractive = interactiveObject["type"]

        if typeInteractive == "button_reply":
            text = interactiveObject["button_reply"]["title"]
        elif typeInteractive == "list_reply":
            text = interactiveObject["list_reply"]["title"]
        else:
            print("sin mensaje", flush=True)

    else:
        print("sin mensaje", flush=True)

    return text


def TextMessage(text, number):
    data = {
        "messaging_product": "whatsapp",
        "to": number,
        "text": {
            "body": text,
        },
        "type": "text",
    }
    return data


def TextDocumentMessage(number, filename):
    base_url = "https://alesturslimitadaapi.top/archivos"
    link = f"{base_url}/{filename}"

    data = {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "document",
        "document": {
            "link": link,
            "caption": "Documento adjunto",
        },
    }
    return data


def ButtonMessage(number):
    data = {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "Bienvenido a Alestur. Nos complace poder brindarte asistencia en todo lo que necesites. "
                    "Antes de continuar, te pedimos que leas nuestra Política de Tratamiento de Datos Personales. "
                    "Si estás de acuerdo con su contenido, selecciona *“Acepto”*; de lo contrario, selecciona *“No acepto”*"
                )
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "001",
                            "title": "Acepto",
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "002",
                            "title": "No acepto",
                        },
                    },
                ]
            },
        },
    }
    return data