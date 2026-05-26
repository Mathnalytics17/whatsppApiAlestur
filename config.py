import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://alestur_user:superpassword@db:5432/alestur_db"
)

SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
