-- Reseteo TOTAL del chatbot.
-- Borra conversaciones, usuarios, consentimientos, contextos y estados.
-- Úsalo solo si estás de acuerdo con perder toda la info del chatbot.

TRUNCATE TABLE
    policy_consents,
    session_context,
    messages,
    sessions,
    users,
    states
RESTART IDENTITY CASCADE;

INSERT INTO states (state_name, description) VALUES
('inicio', 'Inicio de la conversación'),
('esperando_aceptacion', 'Esperando aceptación de política de datos'),
('aceptado', 'Política aceptada; puede continuar el asesor humano'),
('rechazado', 'Política rechazada'),
('esperando_calificacion', 'Esperando si el usuario desea calificar'),
('encuesta_satisfaccion', 'Encuesta de satisfacción'),
('finalizado', 'Sesión finalizada');
