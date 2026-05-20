import requests
import json


def SendMessageWhatsapp(data):
    try:
        token = "EAAOPn6NZBxg0BRtgtR6Ye6YqybXzZAKFyZBn1uRpC8eEzws0xY8d4CooJitM2WQ6XAnRXhTNdbFDWhULmEUqGugscTfJahFz0twwrRajblmkGgtKtU6Ouo8WFZBF6L7lTvZBuZBuZCROeuZBGOp419rNcYyXEE5DLZCFjSfkb3kTWTzuRvZCvTgnZBaLTmmNM6OakAtPhZBvYkFlfR5vxl74lQADSdU3gwN90S1F0zxZB08au1vZB2Bi3aHI8Wus2gjcYZCKqrkYhoT8SWEYg4E5dPLdNZB06gZDZD"
        api_url = "https://graph.facebook.com/v25.0/1275099422350391/messages"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token
        }

        response = requests.post(api_url, data=json.dumps(data), headers=headers)
        
        if response.status_code == 200:
            return True
        return False
    except Exception as exception:
        print(exception)
        return False
