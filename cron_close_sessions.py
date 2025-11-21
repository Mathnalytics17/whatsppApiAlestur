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

        # Normalizar last_message_time a timezone-aware
        last_msg = s.last_message_time
        if last_msg.tzinfo is None:
            last_msg = last_msg.replace(tzinfo=timezone.utc)

        delta = now - last_msg

        # Buscar si ya tiene aviso enviado
        warning_ctx = SessionContext.query.filter_by(
            session_id=s.id,
            context_key="inactivity_warning_sent"
        ).first()

        # =============================================================
        # 1) Enviar AVISO de inactividad si pasa INACTIVITY_MINUTES
        # =============================================================
        if delta > timedelta(minutes=INACTIVITY_MINUTES) and not warning_ctx:

            print(f"[WARN] Enviando aviso de inactividad a sesión {s.id}")

            number = s.user.phone_number

            message = (
                "Hemos notado que llevas un tiempo sin responder. "
                f"Si no recibimos un mensaje dentro de los próximos {WARNING_EXTRA_MINUTES} minutos, "
                "cerraremos la conversación automáticamente."
            )

            # ⚠️ IMPORTANTE: evitar actualizar last_message_time
            send_text(s, number, message, update_last_message=False)

            # Registrar que se envió el warning
            warning_ctx = SessionContext(
                session_id=s.id,
                context_key="inactivity_warning_sent",
                context_value=now.isoformat(),
                updated_at=now
            )
            db.session.add(warning_ctx)
            db.session.commit()
            continue

        # Si no tiene warning, o aún no supera el tiempo, pasar
        if not warning_ctx:
            continue

        # =============================================================
        # 2) Verificar si el usuario respondió DESPUÉS del warning
        # =============================================================

        warning_time = datetime.fromisoformat(warning_ctx.context_value)

        if last_msg > warning_time:
            # El usuario volvió → eliminar warning y NO cerrar
            print(f"[INFO] Usuario volvió después del warning en sesión {s.id}. Limpio warning.")
            db.session.delete(warning_ctx)
            db.session.commit()
            continue

        # =============================================================
        # 3) Cerrar sesión si pasó el tiempo extra
        # =============================================================

        if delta > timedelta(minutes=INACTIVITY_MINUTES + WARNING_EXTRA_MINUTES):

            print(f"[TIMEOUT] Cerrando por inactividad sesión {s.id}")

            # Marcar abandono
            mark_session_abandoned(s)

            # Pasar a estado de encuesta automática
            encuesta_state = get_or_create_state(
                "esperando_calificacion",
                "Esperando que el usuario decida si quiere calificar (timeout)"
            )
            s.current_state_id = encuesta_state.id
            db.session.commit()

            number = s.user.phone_number

            closing_msg = (
                "Hemos cerrado esta conversación por inactividad. "
                "¿Deseas calificar tu experiencia con nosotros? Responde *Sí* o *No*."
            )

            # ⚠️ IMPORTANTE: no actualizar last_message_time
            send_text(s, number, closing_msg, update_last_message=False)

            # Eliminar warning
            db.session.delete(warning_ctx)
            db.session.commit()
