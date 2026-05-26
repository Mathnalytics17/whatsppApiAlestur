import os


def normalize_choice_text(text):
    """Normaliza respuestas escritas o provenientes de listas/botones."""
    text = str(text or "").strip().lower()
    replacements = {
        "✅": "",
        "❌": "",
        "1️⃣": "1",
        "2️⃣": "2",
        "sí": "sí",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return " ".join(text.split()).strip(" .,!¡¿?;:\"'`´")


def is_accept_response(text):
    text = normalize_choice_text(text)
    return text in {
        "1",
        "001",
        "acepto",
        "aceptar",
        "si acepto",
        "sí acepto",
        "si",
        "sí",
        "s",
        "yes",
        "ok",
        "de acuerdo",
        "acepto la política",
        "acepto la politica",
    }


def is_reject_response(text):
    text = normalize_choice_text(text)
    return text in {
        "2",
        "002",
        "no",
        "n",
        "no acepto",
        "no_acepto",
        "rechazo",
        "rechazar",
        "no acepto la política",
        "no acepto la politica",
    }


def GetTextUser(message):
    """
    Extrae texto tanto de Meta Cloud API como de respuestas interactivas/listas.
    """
    if not isinstance(message, dict):
        return ""

    if message.get("body"):
        return str(message.get("body")).strip()

    if message.get("content"):
        return str(message.get("content")).strip()

    if message.get("selectedRowId"):
        return str(message.get("selectedRowId")).strip()

    if message.get("listResponse"):
        obj = message.get("listResponse") or {}
        return str(obj.get("selectedRowId") or obj.get("rowId") or obj.get("title") or "").strip()

    if message.get("buttonReply"):
        obj = message.get("buttonReply") or {}
        return str(obj.get("id") or obj.get("displayText") or obj.get("text") or "").strip()

    typeMessage = message.get("type")

    if typeMessage in ["text", "chat"]:
        text_obj = message.get("text")
        if isinstance(text_obj, dict):
            return str(text_obj.get("body") or "").strip()
        if isinstance(text_obj, str):
            return text_obj.strip()

    if typeMessage == "interactive":
        interactiveObject = message.get("interactive") or {}
        typeInteractive = interactiveObject.get("type")

        if typeInteractive == "button_reply":
            obj = interactiveObject.get("button_reply") or {}
            return str(obj.get("id") or obj.get("title") or "").strip()

        if typeInteractive == "list_reply":
            obj = interactiveObject.get("list_reply") or {}
            return str(obj.get("id") or obj.get("title") or "").strip()

    print("sin mensaje", flush=True)
    return ""


def TextMessage(text, number):
    return {
        "messaging_product": "whatsapp",
        "to": number,
        "text": {"body": text},
        "type": "text",
    }


def TextDocumentMessage(number, filename):
    base_url = os.getenv("PUBLIC_FILES_BASE_URL", "https://alesturslimitadaapi.top/archivos").rstrip("/")
    link = f"{base_url}/{filename}"
    return {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "document",
        "document": {"link": link, "caption": "Documento adjunto"},
    }


def ListMessage(number, body, button_text, rows, title="Alestur Receptivos"):
    """
    Mensaje tipo lista para WPPConnect. Sirve para Acepto/No acepto, Sí/No, etc.
    rows: [{"id": "001", "title": "✅ Acepto", "description": "..."}]
    """
    return {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "list",
        "list": {
            "description": body,
            "buttonText": button_text,
            "sections": [
                {
                    "title": title,
                    "rows": [
                        {
                            "rowId": str(row.get("id") or row.get("rowId") or row.get("title")),
                            "title": str(row.get("title") or "")[:24],
                            "description": str(row.get("description") or "")[:72],
                        }
                        for row in rows
                    ],
                }
            ],
        },
    }


def PolicyListMessage(number):
    return ListMessage(
        number=number,
        body=(
            "👋 Bienvenido a Alestur. Nos complace poder brindarte asistencia.\n\n"
            "Antes de continuar, necesitamos tu autorización para el tratamiento de datos personales. "
            "Por favor lee la política enviada y selecciona una opción."
        ),
        button_text="Seleccionar opción",
        title="Política de datos",
        rows=[
            {
                "id": "001",
                "title": "✅ Acepto",
                "description": "Acepto la política de tratamiento de datos",
            },
            {
                "id": "002",
                "title": "❌ No acepto",
                "description": "No acepto la política de tratamiento de datos",
            },
        ],
    )


def YesNoListMessage(number, body, yes_id="si", no_id="no", title="Selecciona una opción"):
    return ListMessage(
        number=number,
        body=body,
        button_text="Responder",
        title=title,
        rows=[
            {"id": yes_id, "title": "✅ Sí", "description": "Sí"},
            {"id": no_id, "title": "❌ No", "description": "No"},
        ],
    )


def ButtonMessage(number):
    """Compatibilidad con el código anterior: ahora usa lista, no botones viejos."""
    return PolicyListMessage(number)
