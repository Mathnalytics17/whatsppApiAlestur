import requests
import json


def SendMessageWhatsapp(data):
    try:
        token = "EAAOPn6NZBxg0BRlZAYNJJOmOY4H01gz4ME5eGERKAZAodUGOZActXOorwFq0cZCUrZByVcBQKt9r6W3wI9tZB4YY01NI89f7QdbmF11ZCEbD1RuHQmOr8ki36enemj36AXjyNh4sE8FJaZBu8AZCqZAH662MxAPDgF6AkoJRhQJ09xIS2fH4KYjZB1YCPjfsYoREiT4wdUg2o1lqWUyGGkOaTOkDb65sWReKRiCJZCg7w8UZANp6ALEJJXlfV3xXRuPB2qMjbBIjGAKogUJ8rsQZBA6n7nCTAZDZD"
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
