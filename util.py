import os


PUBLIC_FILES_BASE_URL = os.getenv(
    "PUBLIC_FILES_BASE_URL",
    "https://alesturslimitadaapi.top/archivos"
)


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
    link = f"{PUBLIC_FILES_BASE_URL.rstrip('/')}/{filename}"

    return {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "document",
        "document": {
            "link": link,
            "caption": "Documento adjunto",
        },
    }


def PolicyButtonMessage(number):
    # Mantengo el nombre viejo para no tocar app.py, pero ahora se envía como LISTA.
    return YesNoButtonMessage(
        number=number,
        text=(
            "👋 Hola, soy su asistente virtual de Alestur Ltda."
            "Gracias por contactarnos.Para continuar, necesitamos su autorización para el tratamiento de datos personales, conforme a la Ley 1581 de 2012."
            "📄 Por favor, lea la política enviada y seleccione una opción:"
        ),
        yes_label="Acepto",
        no_label="No acepto",
        button_text="Seleccionar opción",
        section_title="Tratamiento de datos",
    )


def ButtonMessage(number):
    # Compatibilidad con el nombre viejo.
    return PolicyButtonMessage(number)


def YesNoButtonMessage(number, text, yes_label="Sí", no_label="No", button_text="Responder", section_title="Opciones"):
    """
    Mantiene el nombre viejo, pero construye una LISTA de WPPConnect.
    Así el usuario no depende de escribir exactamente “sí/no” o “acepto/no acepto”.
    whatsappservice.py lo traduce a /send-list-message.
    """
    return {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": button_text,
                "sections": [
                    {
                        "title": section_title,
                        "rows": [
                            {
                                "id": "yes",
                                "title": yes_label,
                                "description": "",
                            },
                            {
                                "id": "no",
                                "title": no_label,
                                "description": "",
                            },
                        ],
                    }
                ],
            },
        },
    }
