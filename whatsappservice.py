import requests
import json


def SendMessageWhatsapp(data):
    try:
        token = "EAAOPn6NZBxg0BRUZAXCYS1ASEsFWFAjfjTiKMg8S8HVdJHPQjhUq6WWF5yVu9TBXw1qkdnFgLZCPTgiQOKu8rxLB8mJ7BIlfGcIgXJiuyCkoazDHGVhme7iiJRzDCygxxvdjAYoJp01mGhH8hjZAATxBPV84OpWoY1GhqVWdEi4yOWdE7nC1C3oPFqsfpAdUhwUczm1Q8uenD5cXJ59NDfYsZCIIKQCx5LiQnvvqljUBBFLbNjxshNZBjlOYTtWIpJVXZCJNnsaUEDFDxJRBeFz"
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
