import requests
import json


def SendMessageWhatsapp(data):
    try:
        token = "EAAOPn6NZBxg0BRpDAv258gYyMVMk3caecEQ6XhANsLT75QF2RTVyZCrNl6slRDFDSLzYaeTlM6TXuIEQdB00WTeSiQ1d9YVKgKpsWO7WNsj31rZBpKGFv5lC6qIav9ZAG3QZBYeZCqZBnLNwhKuUdBCKZCKI8hqm9zZAKJHnvSFdnlyvlUCdDjmdN6c4QZCnSPxzanJnZB1Uy9rkcJrUqxwvX4lUQcZBRhSktGAiLh6i4zryyxZCGFWRBH5jw17BQmO0ZBryxtZAs6V8GZAYHtZCJZBijqZAa5ojwYIrgatFodfRUZCHUgZDZD"
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
