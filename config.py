import os

# Configuración de conexión a la base de datos PostgreSQL
DB_USER = "flask_user"          # usuario que creaste en PostgreSQL
DB_PASS = "tu_clave_segura"     # contraseña que le diste (puedes dejarla simple mientras pruebas)
DB_NAME = "whatsapp_api"        # nombre de la base creada
DB_HOST = "localhost"           # servidor local
DB_PORT = "5432"                # puerto por defecto de PostgreSQL

SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Clave secreta de Flask (para sesiones, formularios, etc.)
SECRET_KEY = "supersecretkey"
