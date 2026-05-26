# Alestur WhatsApp chatbot - versión multi-número

Archivos incluidos:
- app.py
- whatsappservice.py
- util.py
- cron_close_sessions.py
- models.py
- config.py
- .env.example
- scripts/reset_chatbot_db.sql

## Qué cambia

1. Soporta varios números de WhatsApp conectados a WPPConnect.
2. Usa la `session` que llega en el webhook para saber desde qué número debe responder.
3. Guarda usuarios por `(phone_number, bot_session)`, no solo por teléfono.
4. Usa botones reales de WPPConnect para:
   - Acepto / No acepto
   - Sí / No
5. Si los botones fallan, hace fallback automático a texto.
6. El bot inicia con cualquier primer mensaje del usuario. No depende de "hola".
7. El estado `aceptado` no responde automáticamente; deja pasar al asesor humano.
8. El cron respeta la sesión del número conectado.
9. Incluye delay configurable entre mensajes.

## Importante

Como `models.py` agrega `bot_session` en users, lo más limpio es resetear la DB si no necesitas datos viejos.

Comando recomendado:

```bash
docker exec -i flask_db psql -U alestur_user -d alestur_db < scripts/reset_chatbot_db.sql
```

Luego recrea el contenedor web:

```bash
docker rm -f flask_app
docker-compose up -d --no-deps web
docker rm -f flask_cron
docker-compose up -d --no-deps cron
```

## Generar tokens por número/sesión

Ejemplo:

```bash
curl -X POST "http://localhost:21465/api/alestur_ventas/THISISMYSECURETOKEN/generate-token"
curl -X POST "http://localhost:21465/api/alestur_reservas/THISISMYSECURETOKEN/generate-token"
```

Luego pones los tokens en `.env`:

```env
WPPCONNECT_TOKEN_ALESTUR_VENTAS=...
WPPCONNECT_TOKEN_ALESTUR_RESERVAS=...
```

## Iniciar sesión con webhook

Para cada número/sesión:

```bash
TOKEN='TOKEN_DE_LA_SESION'
curl -X POST "http://localhost:21465/api/alestur_ventas/start-session" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": "https://alesturslimitadaapi.top/wppconnect",
    "waitQrCode": false
  }'
```

Para ver QR en logs:

```bash
docker logs -f wppconnect
```

## Ver cron en tiempo real

```bash
docker logs -f flask_cron
```

## Probar webhook manual

```bash
curl -X POST "https://alesturslimitadaapi.top/wppconnect" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "onmessage",
    "session": "alestur_ventas",
    "from": "573001112233@c.us",
    "chatId": "573001112233@c.us",
    "fromMe": false,
    "isGroupMsg": false,
    "body": "prueba"
  }'
```
