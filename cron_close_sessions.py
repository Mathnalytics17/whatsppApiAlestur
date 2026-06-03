from datetime import datetime, timedelta, timezone
import os

from models import db, Session, SessionContext
from app import app, send_yes_no_buttons, get_or_create_state, close_session, mark_session_abandoned


INACTIVITY_DAYS = int(os.getenv("INACTIVITY_DAYS", "15"))
SURVEY_TTL_DAYS = int(os.getenv("SURVEY_TTL_DAYS", "7"))

INACTIVITY_DELTA = timedelta(days=INACTIVITY_DAYS)
SURVEY_TTL_DELTA = timedelta(days=SURVEY_TTL_DAYS)

FINAL_STATES = {"finalizado", "rechazado"}
SURVEY_STATES = {"esperando_calificacion", "encuesta_satisfaccion"}
PRE_CONSENT_STATES = {"inicio", "esperando_aceptacion"}


def ensure_aware(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def human_delta(delta):
    days = delta.days
    if days >= 1:
        return f"{days} día" + ("s" if days != 1 else "")

    hours = int(delta.total_seconds() // 3600)
    if hours >= 1:
        return f"{hours} hora" + ("s" if hours != 1 else "")

    minutes = int(delta.total_seconds() // 60)
    return f"{minutes} minuto" + ("s" if minutes != 1 else "")


def get_context(session, key):
    return SessionContext.query.filter_by(
        session_id=session.id,
        context_key=key
    ).first()


def set_context(session, key, value):
    now = datetime.now(timezone.utc)
    ctx = get_context(session, key)

    if not ctx:
        ctx = SessionContext(session_id=session.id, context_key=key)
        db.session.add(ctx)

    ctx.context_value = value
    ctx.updated_at = now
    db.session.commit()
    return ctx


def delete_context(session, key):
    ctx = get_context(session, key)
    if ctx:
        db.session.delete(ctx)
        db.session.commit()


with app.app_context():
    now = datetime.now(timezone.utc)

    get_or_create_state("inicio", "Inicio de la conversación")
    get_or_create_state("esperando_aceptacion", "Esperando aceptación de política de datos")
    get_or_create_state("aceptado", "Política aceptada; puede continuar el asesor humano")
    get_or_create_state("rechazado", "Política rechazada")
    get_or_create_state("esperando_calificacion", "Esperando si el usuario desea calificar")
    get_or_create_state("encuesta_satisfaccion", "Encuesta de satisfacción")
    get_or_create_state("finalizado", "Sesión finalizada")

    active_sessions = Session.query.filter_by(is_active=True).all()

    print(
        f"[CRON] Ejecutando ciclo de inactividad. Activas={len(active_sessions)} "
        f"INACTIVITY={human_delta(INACTIVITY_DELTA)} SURVEY_TTL={human_delta(SURVEY_TTL_DELTA)}",
        flush=True
    )

    for session in active_sessions:
        state_name = session.state.state_name.lower() if session.state else "inicio"

        print(
            f"[CRON] Sesión={session.id} Bot={session.user.bot_session} "
            f"Cliente={session.user.phone_number} Estado={state_name}",
            flush=True
        )

        if state_name in FINAL_STATES:
            print(f"[CRON] Corrigiendo sesión activa en estado final. Sesión={session.id}", flush=True)
            close_session(session, "estado_final_activo_corregido")
            continue

        last_msg = ensure_aware(session.last_message_time or session.start_time)
        if not last_msg:
            continue

        delta = now - last_msg

        print(
            f"[CRON] Sesión={session.id} Inactiva={human_delta(delta)}",
            flush=True
        )

        # Limpiar warning viejo del flujo anterior. El nuevo flujo ya no usa warning.
        delete_context(session, "inactivity_warning_sent")

        # ============================================================
        # 1) Sesiones que están esperando encuesta
        # ============================================================
        if state_name in SURVEY_STATES:
            poll_ctx = get_context(session, "timeout_poll_sent")

            if not poll_ctx:
                set_context(session, "timeout_poll_sent", now.isoformat())
                print(f"[CRON] timeout_poll_sent creado para sesión={session.id}", flush=True)
                continue

            try:
                poll_time = datetime.fromisoformat(poll_ctx.context_value)
            except Exception:
                poll_time = now

            poll_time = ensure_aware(poll_time)

            if now - poll_time > SURVEY_TTL_DELTA:
                print(f"[CRON] Cerrando encuesta expirada. Sesión={session.id}", flush=True)
                close_session(session, "encuesta_expirada")

            continue

        # ============================================================
        # 2) Sesiones donde nunca aceptaron política
        # ============================================================
        # No se manda encuesta si nunca aceptó política. Se cierra por abandono
        # para que, cuando vuelva a escribir, empiece un ciclo nuevo y se pida política.
        if state_name in PRE_CONSENT_STATES:
            if delta > INACTIVITY_DELTA:
                print(f"[CRON] Cerrando sesión sin aceptación por abandono. Sesión={session.id}", flush=True)
                close_session(session, "politica_no_respondida")
            continue

        # ============================================================
        # 3) Sesiones aceptadas/atendidas
        # ============================================================
        # A los 15 días NO se cierra todavía: se envía encuesta y la sesión queda activa.
        if delta > INACTIVITY_DELTA:
            timeout_poll_ctx = get_context(session, "timeout_poll_sent")
            if timeout_poll_ctx:
                continue

            print(f"[CRON] Enviando encuesta por inactividad. Sesión={session.id}", flush=True)

            mark_session_abandoned(session)

            session.current_state_id = get_or_create_state(
                "esperando_calificacion",
                "Esperando que el usuario decida si quiere calificar por inactividad"
            ).id
            db.session.commit()

            send_yes_no_buttons(
                session,
                session.user.phone_number,
                "Ha pasado un tiempo desde nuestra última conversación. ¿Deseas calificar tu experiencia con nosotros?",
                yes_label="Sí",
                no_label="No",
                update_last_message=False
            )

            set_context(session, "timeout_poll_sent", now.isoformat())
            continue
