from datetime import datetime, timedelta, timezone
import os

from models import db, Session, SessionContext
from app import app, send_text, send_yes_no_buttons, get_or_create_state, mark_session_abandoned

INACTIVITY_MINUTES = int(os.getenv("INACTIVITY_MINUTES", "10"))
WARNING_EXTRA_MINUTES = int(os.getenv("WARNING_EXTRA_MINUTES", "3"))

with app.app_context():
    now = datetime.now(timezone.utc)
    active_sessions = Session.query.filter_by(is_active=True).all()

    print(
        f"[CRON] Ejecutando cierre de sesiones. Activas={len(active_sessions)} "
        f"INACTIVITY_MINUTES={INACTIVITY_MINUTES} WARNING_EXTRA_MINUTES={WARNING_EXTRA_MINUTES}",
        flush=True
    )

    for s in active_sessions:
        if not s.last_message_time:
            continue

        last_msg = s.last_message_time
        if last_msg.tzinfo is None:
            last_msg = last_msg.replace(tzinfo=timezone.utc)

        delta = now - last_msg

        warning_ctx = SessionContext.query.filter_by(
            session_id=s.id,
            context_key="inactivity_warning_sent"
        ).first()

        print(
            f"[CRON] Sesión={s.id} Bot={s.user.bot_session} Cliente={s.user.phone_number} "
            f"Estado={s.state.state_name if s.state else None} "
            f"Inactiva={int(delta.total_seconds())}s Warning={bool(warning_ctx)}",
            flush=True
        )

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
        if warning_time.tzinfo is None:
            warning_time = warning_time.replace(tzinfo=timezone.utc)

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

            send_yes_no_buttons(
                s,
                number,
                "Hemos cerrado esta conversación por inactividad. ¿Deseas calificar tu experiencia con nosotros?",
                yes_label="Sí",
                no_label="No",
                update_last_message=False
            )

            db.session.delete(warning_ctx)
            db.session.commit()
