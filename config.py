import os

DB_USER = "alestur_user"
DB_PASS = "superpassword"
DB_NAME = "alestur_db"
DB_HOST = "db"
DB_PORT = "5432"

SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

SECRET_KEY = "superpassword"