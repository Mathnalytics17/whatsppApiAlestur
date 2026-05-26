TRUNCATE TABLE
  messages,
  policy_consents,
  session_context,
  sessions,
  users
RESTART IDENTITY CASCADE;

INSERT INTO states (state_name, description)
VALUES
  ('inicio', 'Inicio de la conversación'),
  ('esperando_aceptacion', 'Esperando aceptación de política de datos'),
  ('aceptado', 'Política aceptada; puede continuar el asesor humano'),
  ('rechazado', 'Política rechazada'),
  ('esperando_calificacion', 'Esperando si el usuario desea calificar'),
  ('encuesta_satisfaccion', 'Encuesta de satisfacción'),
  ('finalizado', 'Sesión finalizada')
ON CONFLICT (state_name) DO UPDATE SET description = EXCLUDED.description;
