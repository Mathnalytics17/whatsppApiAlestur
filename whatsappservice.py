import requests
import json


def SendMessageWhatsapp(data):
    try:
        token = "EAAUGZCgGxfcQBP90DbaLZAKZCNIZAPUS4AdMWFZC1AxsKXZC2V8PJ4BEJQ9TZA4Mg0ZC5KmPnXPVKeTx68t6bufIzMCpj2o0ijPx3FSLxZBAMOWg1r6C9YIZCl1kuEMtUSb7W8l7x2QcEeMf1BMGzZBSMLwS2GZA9UTqygiEqO9R7jagHrrWemMZCxcdQNGmGuAZCDQgZDZD"
        api_url = "https://graph.facebook.com/v22.0/869379529587385/messages"
        
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
