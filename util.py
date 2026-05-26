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
        "text": {
            "body": text,
        },
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
    return YesNoButtonMessage(
        number=number,
        text=(
            "Bienvenido a Alestur. Nos complace poder brindarte asistencia en todo lo que necesites. "
            "Antes de continuar, te pedimos que leas nuestra Política de Tratamiento de Datos Personales. "
            "Si estás de acuerdo con su contenido, selecciona *Acepto*; de lo contrario, selecciona *No acepto*."
        ),
        yes_label="Acepto",
        no_label="No acepto",
    )


def ButtonMessage(number):
    # Compatibilidad con el nombre viejo.
    return PolicyButtonMessage(number)


def YesNoButtonMessage(number, text, yes_label="Sí", no_label="No"):
    """
    Formato lógico interno. whatsappservice.py lo traduce a WPPConnect send-buttons.
    Si send-buttons falla, whatsappservice/app hacen fallback a texto normal.
    """
    return {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": text,
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "yes",
                            "title": yes_label,
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "no",
                            "title": no_label,
                        },
                    },
                ]
            },
        },
    }
