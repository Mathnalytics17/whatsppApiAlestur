import os
import requests


PHP_LEADS_API_URL = os.getenv("PHP_LEADS_API_URL", "").strip()
PHP_LEADS_API_TOKEN = os.getenv("PHP_LEADS_API_TOKEN", "").strip()


def create_or_update_php_lead(user, session, accepted=True, latest_message=None):
    """
    Envía un lead al sistema PHP cuando el usuario acepta la política.
    No rompe el chatbot si la API PHP falla.
    """

    if not PHP_LEADS_API_URL:
        print("⚠️ PHP_LEADS_API_URL no configurado. Lead no enviado a PHP.", flush=True)
        return False

    if not PHP_LEADS_API_TOKEN:
        print("⚠️ PHP_LEADS_API_TOKEN no configurado. Lead no enviado a PHP.", flush=True)
        return False

    payload = {
        "phone": user.phone_number,
        "name": user.name or "Contacto externo / WhatsApp",
        "bot_session": user.bot_session,
        "source": "whatsapp",
        "origin": "contacto externo/whatsapp",
        "policy_accepted": bool(accepted),
        "message": latest_message or "",
        "external_reference": f"{user.bot_session}:{user.phone_number}",
        "metadata": {
            "chatbot_user_id": user.id,
            "chatbot_session_id": session.id if session else None,
            "wpp_session": user.bot_session,
        },
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PHP_LEADS_API_TOKEN}",
    }

    try:
        response = requests.post(
            PHP_LEADS_API_URL,
            json=payload,
            headers=headers,
            timeout=20,
        )

        print(
            "📤 PHP Leads API:",
            response.status_code,
            response.text[:1000],
            flush=True,
        )

        return 200 <= response.status_code < 300

    except Exception as e:
        print("❌ Error enviando lead al PHP:", repr(e), flush=True)
        return False