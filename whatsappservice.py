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


def _send_text(number, text, label="send-message"):
    payload = build_wpp_phone_payload(number)
    payload["message"] = text
    return _post_wpp("send-message", payload, label)


def _send_list(number, list_obj, label="send-list-message"):
    payload = build_wpp_phone_payload(number)
    payload.update({
        "description": list_obj.get("description") or "Selecciona una opción",
        "buttonText": list_obj.get("buttonText") or "Responder",
        "sections": list_obj.get("sections") or [],
    })

    ok = _post_wpp("send-list-message", payload, label)
    if ok:
        return True

    # Fallback: si la lista falla, no rompemos el flujo. Enviamos texto numerado.
    fallback_lines = [payload["description"], "", "Responde con una de estas opciones:"]
    idx = 1
    for section in payload.get("sections", []):
        for row in section.get("rows", []):
            fallback_lines.append(f"{idx}. {row.get('title', '')}")
            idx += 1
    return _send_text(number, "\n".join(fallback_lines), f"{label}->fallback-text")


def SendMessageWhatsapp(data):
    try:
        number = data.get("to") or data.get("phone")
        message_type = data.get("type", "text")

        if not number:
            print("❌ No llegó número destino en data:", data, flush=True)
            return False

        if message_type == "text":
            text = data.get("text", {}).get("body") or data.get("message") or ""
            return _send_text(number, text, "send-message")

        if message_type == "document":
            doc = data.get("document", {})
            link = doc.get("link")
            caption = doc.get("caption", "Documento adjunto")
            text = f"{caption}:\n{link}"
            return _send_text(number, text, "document->link")

        if message_type == "list":
            return _send_list(number, data.get("list") or {}, "send-list-message")

        if message_type == "interactive":
            # Compatibilidad con tu estructura vieja de Meta: interactive/buttons -> WPPConnect list.
            body = data.get("interactive", {}).get("body", {}).get("text", "")
            buttons = data.get("interactive", {}).get("action", {}).get("buttons", [])
            rows = []
            for btn in buttons:
                reply = btn.get("reply", {})
                title = reply.get("title")
                btn_id = reply.get("id") or title
                if title:
                    rows.append({
                        "rowId": str(btn_id),
                        "title": str(title)[:24],
                        "description": f"Seleccionar: {title}"[:72],
                    })

            if rows:
                return _send_list(number, {
                    "description": body,
                    "buttonText": "Seleccionar opción",
                    "sections": [{"title": "Alestur", "rows": rows}],
                }, "interactive->list")

            return _send_text(number, body, "interactive->text")

        print("⚠️ Tipo de mensaje no soportado todavía:", message_type, data, flush=True)
        return False

    except Exception as exception:
        print("❌ Error enviando por WPPConnect:", exception, flush=True)
        return False
