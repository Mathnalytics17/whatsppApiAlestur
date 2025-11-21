from datetime import datetime, timedelta, timezone
from models import db, Session, SessionContext
from app import app, send_text, get_or_create_state, mark_session_abandoned

INACTIVITY_MINUTES = 10
WARNING_EXTRA_MINUTES = 3

with app.app_context():

    now = datetime.now(timezone.utc)
    sessions = Session.query.filter_by(is_active=True).all()

    for s in sessions:
        if not s.last_message_time:
            continue

        # manejar timezone correctamente
        last_msg = s.last_message_time
        if last_msg.tzinfo is None:
            last_msg = last_msg.replace(tzinfo=timezone.utc)

        delta = now - last_msg

        # Verificar si existe warning previo
        warning_ctx = SessionContext.query.filter_by(
            session_id=s.id,
            context_key="inactivity_warning_sent"
        ).first()

        # ------------------------------------------
        # 1) Enviar aviso de inactividad
        # ------------------------------------------

        if delta > timedelta(minutes=INACTIVITY_MINUTES) and not warning_ctx:
            print(f"[WARN] Enviando aviso de inactividad a sesión {s.id}")
            number = s.user.phone_number

            msg = (
                "Hemos notado que llevas un tiempo sin responder. "
                f"Si no recibimos un mensaje dentro de los próximos {WARNING_EXTRA_MINUTES} minutos, "
                "cerraremos la conversación automáticamente."
            )
            send_text(s, number, msg)

            warning_ctx = SessionContext(
                session_id=s.id,
                context_key="inactivity_warning_sent",
                context_value=now.isoformat(),
                updated_at=now
            )
            db.session.add(warning_ctx)
            db.session.commit()
            continue

        # ------------------------------------------
        # 2) Cerrar sesión por inactividad
        # ------------------------------------------

        if warning_ctx:
            warning_time = datetime.fromisoformat(warning_ctx.context_value)

            # PREVENCIÓN: si el usuario respondió después del aviso → no cerrar
            if last_msg > warning_time:
                # limpiar warning porque el usuario volvió
                db.session.delete(warning_ctx)
                db.session.commit()
                continue

            # si ya pasó el tiempo extra → cerrar
            if delta > timedelta(minutes=INACTIVITY_MINUTES + WARNING_EXTRA_MINUTES):
                print(f"[TIMEOUT] Cerrando por inactividad sesión {s.id}")

                mark_session_abandoned(s)

                encuesta_state = get_or_create_state(
                    "esperando_calificacion",
                    "Esperando calificación por timeout"
                )
                s.current_state_id = encuesta_state.id
                db.session.commit()

                number = s.user.phone_number
                send_text(
                    s, number,
                    "Hemos cerrado esta conversación por inactividad. "
                    "¿Deseas calificar tu experiencia con nosotros? Responde Sí o No."
                )
