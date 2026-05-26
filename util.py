import os


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


def ButtonMessage(number):
    return {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "Bienvenido a Alestur. Nos complace poder brindarte asistencia en todo lo que necesites. "
                    "Antes de continuar, te pedimos que leas nuestra Política de Tratamiento de Datos Personales. "
                    "Si estás de acuerdo con su contenido, responde *Acepto*; de lo contrario, responde *No acepto*."
                )
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "001", "title": "Acepto"}},
                    {"type": "reply", "reply": {"id": "002", "title": "No acepto"}},
                ]
            },
        },
    }
