from datetime import datetime, timedelta, timezone
import os

from models import db, Session, SessionContext
from app import app, send_text, send_yes_no_buttons, get_or_create_state, mark_session_abandoned

INACTIVITY_MINUTES = int(os.getenv("INACTIVITY_MINUTES", "10"))
WARNING_EXTRA_MINUTES = int(os.getenv("WARNING_EXTRA_MINUTES", "3"))

# Estados en los que el bot NO debe insistir ni mandar mensajes automáticos repetidos.
SKIP_INACTIVITY_STATES = {
    "esperando_aceptacion",
    "esperando_calificacion",
    "encuesta_satisfaccion",
    "rechazado",
    "finalizado",
}

with app.app_context():
    now = datetime.now(timezone.utc)
    active_sessions = Session.query.filter_by(is_active=True).all()

    print(
        f"[CRON] Ejecutando cierre de sesiones. Activas={len(active_sessions)} "
        f"INACTIVITY_MINUTES={INACTIVITY_MINUTES} WARNING_EXTRA_MINUTES={WARNING_EXTRA_MINUTES}",
        flush=True
    )

    for s in active_sessions:
        state_name = s.state.state_name.lower() if s.state else None

        print(
            f"[CRON] Sesión={s.id} Bot={s.user.bot_session} Cliente={s.user.phone_number} "
            f"Estado={state_name}",
            flush=True
        )

        # Evita el bug de mensajes repetidos cuando ya está esperando aceptación/calificación.
        if state_name in SKIP_INACTIVITY_STATES:
            print(f"[CRON] Skip sesión={s.id}; estado no requiere cierre por inactividad", flush=True)
            continue

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

        timeout_poll_ctx = SessionContext.query.filter_by(
            session_id=s.id,
            context_key="timeout_poll_sent"
        ).first()

        print(
            f"[CRON] Sesión={s.id} Inactiva={int(delta.total_seconds())}s "
            f"Warning={bool(warning_ctx)} TimeoutPoll={bool(timeout_poll_ctx)}",
            flush=True
        )

        if timeout_poll_ctx:
            continue

        if delta > timedelta(minutes=INACTIVITY_MINUTES) and not warning_ctx:
            print(f"[WARN] Enviando aviso de inactividad a sesión {s.id}", flush=True)

            number = s.user.phone_number
            message = (
                "Hemos notado que llevas un tiempo sin responder. "
                f"Si no se recibe un mensaje dentro de los próximos {WARNING_EXTRA_MINUTES} minutos, "
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
            s.last_message_time = now

            timeout_poll_ctx = SessionContext(
                session_id=s.id,
                context_key="timeout_poll_sent",
                context_value=now.isoformat(),
                updated_at=now
            )
            db.session.add(timeout_poll_ctx)
            db.session.commit()

            number = s.user.phone_number
            send_yes_no_buttons(
                s,
                number,
                "Su sesión ha sido cerrada por inactividad, ¿Deseas calificar su experiencia con nosotros?",
                yes_label="Sí",
                no_label="No",
                update_last_message=False
            )

            db.session.delete(warning_ctx)
            db.session.commit()
