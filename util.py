def GetTextUser(message):
    text = ""
    typeMessage=message['type']
    
    if typeMessage == "text":
        text=(message["text"])["body"]
        
    elif typeMessage=="interactive":
        interactiveObject = message['interactive']
        typeInteractive=interactiveObject['type']
        
        if typeInteractive == "button_reply":
            text = (interactiveObject['button_reply'])['title']
        elif typeInteractive== 'list_reply':
            text= (interactiveObject['list_reply'])['title']
        else:
            print('sin mensaje')

    else:
        print("sin mensaje")
        
    return text


def TextMessage(text,number):
    data={ "messaging_product": "whatsapp", 
              "to": number,
              "text": { 
                  "body":text,
                  }, 
              "type": "text", 
              }
    return data

def TextDocumentMessage(number,id):
    
    data={ 
              "messaging_product": "whatsapp", 
              "to": number,
              "type": "document", 
              "document": { 
                  "link":f'https://drive.google.com/uc?export=download&id={id}',
                  
                      # 👈 tipo MIME correcto (evita que llegue como .bin)
                 "caption": "Documento adjunto"  # 👈 texto descriptivo opcional
                  
                  }, 
              
              }
    return data

def ButtonMessage(number):
    
    data={
    "messaging_product": "whatsapp",
    "to": number,
    "type": "interactive",
    "interactive": {
        "type": "button",
        "body": {
            "text": "Bienvenido a Alestur. Nos complace poder brindarte asistencia en todo lo que necesites. Antes de continuar, te pedimos que leas nuestra Política de Tratamiento de Datos Personales. Si estás de acuerdo con su contenido, selecciona *“Acepto”*; de lo contrario, selecciona *“No acepto”*"
        },
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": "001",
                        "title": "Acepto"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "002",
                        "title": "No acepto"
                    }
                }
            ]
        }
    }
}
    return data