import requests
import json


def SendMessageWhatsapp(data):
    try:
        token = "EAAOPn6NZBxg0BRRoYANZC2lu6Fu1iHIlfSZAd8ULrRtTU0v3bDyf2lWsJBJxn2b6HuIV9iFbSm3FlM8m6rPFWkPQbIYhtEgkKFa3AXYXxsjqgUhKd169JgqpM9KBPWA05tafT3bInUPpMCGYZCxefIXKgS2PhTjJ3AVzlvZBK9DXGXdtesV4nAuZAeCGZAz6gZDZD"
        api_url = "https://graph.facebook.com/v25.0/1055049724364109/messages"
        
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
