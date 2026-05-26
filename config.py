import os

DATABASE_URL = os.getenv("DATABASE_URL")

DB_USER = os.getenv("POSTGRES_USER", "alestur_user")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "superpassword")
DB_NAME = os.getenv("POSTGRES_DB", "alestur_db")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")

SQLALCHEMY_DATABASE_URI = DATABASE_URL or f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

SECRET_KEY = os.getenv("SECRET_KEY", "superpassword")
