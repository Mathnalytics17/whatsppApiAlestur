import requests
import json


def SendMessageWhatsapp(data):
    try:
        token = "EAAOPn6NZBxg0BRhChSyGMfkntx7EZCUdANm9JY3PvIlqgdRoMIIDdoSWQzDwBHt9tjID3LgkBfAMadLkFmAOHZB9bCSK11Y0wt7gKZB5hZCXfPWDI6f6FmJ5H18O6QzRu8duMwmZBDhmHwVQekZAs1B9ZCVvovq2dtVVii7oO8WkZCkxOASpxfAZAnBRAu7JM1cijUFgZDZD"
        api_url = "https://graph.facebook.com/v25.0/1146853748510127/messages"
        
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
