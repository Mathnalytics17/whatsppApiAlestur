BEGIN;

INSERT INTO states (state_name, description)
VALUES
    ('inicio', 'Inicio de la conversación'),
    ('esperando_aceptacion', 'Esperando aceptación de política de datos'),
    ('aceptado', 'Política aceptada; puede continuar el asesor humano'),
    ('rechazado', 'Política rechazada'),
    ('esperando_calificacion', 'Esperando si el usuario desea calificar'),
    ('encuesta_satisfaccion', 'Encuesta de satisfacción'),
    ('finalizado', 'Sesión finalizada')
ON CONFLICT (state_name) DO NOTHING;

-- 1) Recalcular last_message_time con el último mensaje ENTRANTE real del cliente.
-- Esto corrige sesiones donde los mensajes salientes del bot renovaron la inactividad.
WITH latest_in AS (
    SELECT
        session_id,
        MAX(timestamp) AS latest_in_timestamp
    FROM messages
    WHERE direction = 'in'
    GROUP BY session_id
)
UPDATE sessions s
SET last_message_time = latest_in.latest_in_timestamp
FROM latest_in
WHERE s.id = latest_in.session_id
  AND s.is_active = true;

-- 2) Si una sesión activa recibió "Acepto" pero no quedó registro de policy_consents,
-- crearlo SOLO para esa misma sesión. No se propaga a conversaciones cerradas ni a otras sesiones.
INSERT INTO policy_consents (user_id, session_id, accepted, created_at)
SELECT DISTINCT
    s.user_id,
    s.id,
    true,
    NOW()
FROM sessions s
JOIN messages m ON m.session_id = s.id
WHERE s.is_active = true
  AND m.direction = 'in'
  AND lower(trim(m.message_text)) IN (
      'acepto',
      'aceptar',
      'si acepto',
      'sí acepto',
      'de acuerdo',
      'estoy de acuerdo'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM policy_consents pc
      WHERE pc.session_id = s.id
        AND pc.accepted = true
  );

-- 3) Si una sesión activa ya aceptó política EN ESA MISMA sesión,
-- pero quedó en inicio/esperando_aceptacion, pasarla a aceptado.
UPDATE sessions s
SET current_state_id = (
    SELECT id FROM states WHERE state_name = 'aceptado'
)
FROM states st
WHERE s.current_state_id = st.id
  AND s.is_active = true
  AND st.state_name IN ('inicio', 'esperando_aceptacion')
  AND EXISTS (
      SELECT 1
      FROM policy_consents pc
      WHERE pc.session_id = s.id
        AND pc.accepted = true
  );

-- 4) Si estaba esperando encuesta, pero el último mensaje entrante fue algo normal
-- y no una respuesta sí/no, se considera conversación retomada.
WITH latest_in AS (
    SELECT DISTINCT ON (s.id)
        s.id AS session_id,
        lower(trim(m.message_text)) AS latest_text,
        m.timestamp AS latest_in_timestamp
    FROM sessions s
    JOIN messages m ON m.session_id = s.id
    WHERE s.is_active = true
      AND m.direction = 'in'
    ORDER BY s.id, m.timestamp DESC, m.id DESC
)
UPDATE sessions s
SET current_state_id = (
    SELECT id FROM states WHERE state_name = 'aceptado'
)
FROM latest_in li, states st
WHERE s.id = li.session_id
  AND s.current_state_id = st.id
  AND s.is_active = true
  AND st.state_name IN ('esperando_calificacion', 'encuesta_satisfaccion')
  AND li.latest_text NOT IN (
      'si',
      'sí',
      's',
      'yes',
      'acepto calificar',
      'calificar',
      'no',
      'n',
      'no calificar'
  );

-- 5) Borrar contextos de encuesta/warning de sesiones que ya volvieron a aceptado.
DELETE FROM session_context sc
USING sessions s, states st
WHERE sc.session_id = s.id
  AND s.current_state_id = st.id
  AND s.is_active = true
  AND st.state_name = 'aceptado'
  AND sc.context_key IN ('timeout_poll_sent', 'inactivity_warning_sent');

-- 6) El flujo nuevo ya no usa warning de inactividad.
DELETE FROM session_context
WHERE context_key = 'inactivity_warning_sent';

-- 7) Corregir sesiones que estén activas en estados finales.
UPDATE sessions s
SET
    is_active = false,
    end_time = COALESCE(end_time, NOW())
FROM states st
WHERE s.current_state_id = st.id
  AND s.is_active = true
  AND st.state_name IN ('rechazado', 'finalizado');

COMMIT;
