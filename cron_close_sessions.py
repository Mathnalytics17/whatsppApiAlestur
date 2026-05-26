import os
from datetime import datetime, timedelta, timezone

from models import db, Session, SessionContext, State
from app import app, send_text, send_yes_no_list, get_or_create_state, mark_session_abandoned

INACTIVITY_MINUTES = int(os.getenv("INACTIVITY_MINUTES", "10"))
WARNING_EXTRA_MINUTES = int(os.getenv("WARNING_EXTRA_MINUTES", "3"))


def aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


with app.app_context():
    now = datetime.now(timezone.utc)
    active_sessions = Session.query.filter_by(is_active=True).all()

    for s in active_sessions:
        current_state = db.session.get(State, s.current_state_id)
        state_name = current_state.state_name if current_state else ""

        # Si ya está en encuesta/calificación, no vuelvas a disparar warnings de inactividad.
        if state_name in ["esperando_calificacion", "encuesta_satisfaccion", "finalizado", "rechazado"]:
            continue

        if not s.last_message_time:
            continue

        last_msg = aware(s.last_message_time)
        delta = now - last_msg

        warning_ctx = SessionContext.query.filter_by(
            session_id=s.id,
            context_key="inactivity_warning_sent"
        ).first()

        if delta > timedelta(minutes=INACTIVITY_MINUTES) and not warning_ctx:
            print(f"[WARN] Enviando aviso de inactividad a sesión {s.id}", flush=True)

            number = s.user.phone_number
            message = (
                "Hemos notado que llevas un tiempo sin responder. "
                f"Si no recibimos un mensaje dentro de los próximos {WARNING_EXTRA_MINUTES} minutos, "
                "cerraremos la conversación automáticamente."
            )

            send_text(s, number, message, update_last_message=False)

            warning_ctx = SessionContext(
                session_id=s.id,
                context_key="inactivity_warning_sent",
                context_value=now.isoformat(),
                updated_at=now
            )
            db.session.add(warning_ctx)
            db.session.commit()
            continue

        if not warning_ctx:
            continue

        warning_time = datetime.fromisoformat(warning_ctx.context_value)
        warning_time = aware(warning_time)

        if last_msg > warning_time:
            print(f"[INFO] Usuario volvió después del warning en sesión {s.id}. Limpio warning.", flush=True)
            db.session.delete(warning_ctx)
            db.session.commit()
            continue

        if delta > timedelta(minutes=INACTIVITY_MINUTES + WARNING_EXTRA_MINUTES):
            print(f"[TIMEOUT] Cerrando por inactividad sesión {s.id}", flush=True)

            mark_session_abandoned(s)
            encuesta_state = get_or_create_state(
                "esperando_calificacion",
                "Esperando que el usuario decida si quiere calificar por timeout"
            )
            s.current_state_id = encuesta_state.id
            db.session.commit()

            number = s.user.phone_number
            closing_msg = (
                "Hemos cerrado esta conversación por inactividad. "
                "¿Deseas calificar tu experiencia con nosotros?"
            )

            send_yes_no_list(s, number, closing_msg, update_last_message=False)
            db.session.delete(warning_ctx)
            db.session.commit()
