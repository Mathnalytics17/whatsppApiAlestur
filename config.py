import os

DB_USER = "postgres"
DB_PASS = "1"
DB_NAME = "whatsapp_chatbot"
DB_HOST = "localhost"
DB_PORT = "5432"

SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SQLALCHEMY_TRACK_MODIFICATIONS = False
