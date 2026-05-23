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


def SendMessageWhatsapp(data):
    """
    Adaptador para mantener compatible tu código viejo.

    Tu app actualmente llama:
        whatsappservice.SendMessageWhatsapp(data)

    Entonces esta función traduce tus datos actuales al formato de WPPConnect.
    """

    try:
        number = data.get("to") or data.get("phone")
        message_type = data.get("type", "text")

        if not number:
            print("❌ No llegó número destino en data:", data)
            return False

        # Mensaje de texto normal
        if message_type == "text":
            text = data.get("text", {}).get("body") or data.get("message") or ""

            payload = {
                "phone": clean_phone(number),
                "message": text,
                "isGroup": False
            }

            url = f"{WPPCONNECT_URL}/api/{WPPCONNECT_SESSION}/send-message"
            response = requests.post(url, json=payload, headers=_headers(), timeout=30)

            print("📤 WPPConnect send-message:", response.status_code, response.text)
            return response.status_code in [200, 201]

        # Botones: en WhatsApp Web automation esto puede variar.
        # Para empezar lo convertimos a texto normal, que es más estable.
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

            payload = {
                "phone": clean_phone(number),
                "message": text,
                "isGroup": False
            }

            url = f"{WPPCONNECT_URL}/api/{WPPCONNECT_SESSION}/send-message"
            response = requests.post(url, json=payload, headers=_headers(), timeout=30)

            print("📤 WPPConnect interactive->text:", response.status_code, response.text)
            return response.status_code in [200, 201]

        # Documentos: de momento mandamos el link como texto.
        # Después podemos cambiarlo por send-file o send-link-preview.
        if message_type == "document":
            doc = data.get("document", {})
            link = doc.get("link")
            caption = doc.get("caption", "Documento adjunto")

            text = f"{caption}:\n{link}"

            payload = {
                "phone": clean_phone(number),
                "message": text,
                "isGroup": False
            }

            url = f"{WPPCONNECT_URL}/api/{WPPCONNECT_SESSION}/send-message"
            response = requests.post(url, json=payload, headers=_headers(), timeout=30)

            print("📤 WPPConnect document->link:", response.status_code, response.text)
            return response.status_code in [200, 201]

        print("⚠️ Tipo de mensaje no soportado todavía:", message_type, data)
        return False

    except Exception as exception:
        print("❌ Error enviando por WPPConnect:", exception)
        return False


def clean_phone(number):
    """
    WPPConnect puede recibir números normales o JIDs completos.
    Si viene @lid o @c.us, lo dejamos intacto.
    """
    if not number:
        return number

    number = str(number).replace("+", "").strip()
    return number