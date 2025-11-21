from datetime import datetime, timedelta, timezone

from models import db, Session, SessionContext
from app import app, send_text, get_or_create_state, mark_session_abandoned

INACTIVITY_MINUTES = 10
WARNING_EXTRA_MINUTES = 3  # minutos después del aviso para cerrar

with app.app_context():
    now = datetime.now(timezone.utc)

    active_sessions = Session.query.filter_by(is_active=True).all()

    for s in active_sessions:
        if not s.last_message_time:
            continue

        # ---- FIX: convertir last_message_time a timezone-aware ----
        if s.last_message_time.tzinfo is None:
            last_time = s.last_message_time.replace(tzinfo=timezone.utc)
        else:
            last_time = s.last_message_time

        delta = now - last_time

        # ---- 1) Aviso de inactividad ----
        warning_ctx = SessionContext.query.filter_by(
            session_id=s.id,
            context_key="inactivity_warning_sent"
        ).first()

        if delta > timedelta(minutes=INACTIVITY_MINUTES) and not warning_ctx:
            print(f"[WARN] Enviando aviso de inactividad a sesión {s.id}")
            number = s.user.phone_number

            text = (
                "Hemos notado que llevas un tiempo sin responder. "
                "Si no recibimos un mensaje en los próximos "
                f"{WARNING_EXTRA_MINUTES} minutos, cerraremos la conversación automáticamente."
            )
            send_text(s, number, text)

            warning_ctx = SessionContext(
                session_id=s.id,
                context_key="inactivity_warning_sent",
                context_value=now.isoformat(),
                updated_at=now,
            )
            db.session.add(warning_ctx)
            db.session.commit()
            continue

        # ---- 2) Cierre por inactividad + encuesta ----
        if delta > timedelta(minutes=INACTIVITY_MINUTES + WARNING_EXTRA_MINUTES):
            abandoned_ctx = SessionContext.query.filter_by(
                session_id=s.id,
                context_key="abandoned"
            ).first()

            if abandoned_ctx:
                continue

            print(f"[TIMEOUT] Cerrando por inactividad sesión {s.id}")

            mark_session_abandoned(s)

            encuesta_state = get_or_create_state(
                "esperando_calificacion",
                "Esperando que el usuario decida si quiere calificar (timeout)"
            )
            s.current_state_id = encuesta_state.id
            db.session.commit()

            number = s.user.phone_number
            text = (
                "Hemos cerrado esta conversación por inactividad. "
                "¿Deseas calificar tu experiencia con nosotros? "
                "Responde *Sí* o *No*."
            )
            send_text(s, number, text)
