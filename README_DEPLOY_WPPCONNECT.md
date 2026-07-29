# Deploy limpio del chatbot Alestur con WPPConnect

## Cambios incluidos

- Crea tablas y estados automáticamente al arrancar con Gunicorn.
- Soporta respuestas a números `@lid` usando `isLid: true` cuando aplica.
- Ignora eventos que no son mensajes reales (`onack`, `status-find`, presencia, QR, etc.).
- Evita bucles con mensajes propios.
- Mantiene flujo: bienvenida, política, documentos, `Acepto` / `No acepto`, asesor humano, cierre por inactividad y encuesta.
- El cron ya no vuelve a disparar warnings cuando la sesión está en encuesta/calificación.
- `DATABASE_URL`, token, tiempos y archivos quedan por `.env`.

## .env sugerido

```env
FLASK_ENV=production
SECRET_KEY=superpassword
DATABASE_URL=postgresql://alestur_user:superpassword@db:5432/alestur_db

WPPCONNECT_URL=http://wppconnect:21465
WPPCONNECT_SESSION=alestur_ventas
WPPCONNECT_TOKEN=$2b$10$PEGA_AQUI_TU_TOKEN_NUEVO

PUBLIC_FILES_BASE_URL=https://alesturslimitadaapi.top/archivos
POLICY_DOCUMENTS=politica_datos.pdf,autorizacion_datos.pdf

INACTIVITY_MINUTES=10
WARNING_EXTRA_MINUTES=3

# true = si el contacto está guardado en WhatsApp, el bot no responde.
# false = responde a todos los clientes que escriban.
IGNORE_SAVED_CONTACTS=false
```

## Limpieza segura de datos del chatbot

Esto borra usuarios, sesiones, mensajes y consentimientos, pero conserva las tablas y vuelve a sembrar estados:

```bash
docker exec -i flask_db psql -U alestur_user -d alestur_db < scripts/reset_chatbot_db.sql
```

## Rebuild limpio del backend

Si `docker-compose` vuelve a dar `KeyError: ContainerConfig`, borra los contenedores específicos y levanta de nuevo:

```bash
docker rm -f flask_app flask_cron wppconnect 2>/dev/null || true
docker-compose build web cron wppconnect
docker-compose up -d db wppconnect web nginx cron
```

## Redeploy limpio de WPPConnect

Para aplicar cambios de versiÃ³n de WhatsApp Web y limpiar contenedores/locks viejos de Chromium sin borrar la base de datos:

```bash
cd /var/www/APIWPALESTUR
git pull
sh scripts/redeploy_wppconnect_clean.sh
```

Si Chromium sigue bloqueado o quieres empezar WPPConnect realmente desde cero, borra tambiÃ©n los volÃºmenes de sesiÃ³n/tokens de WPPConnect. Esto puede pedir QR y regenerar/configurar token:

```bash
sh scripts/redeploy_wppconnect_clean.sh --wipe-session
```

La versiÃ³n de WhatsApp Web se controla desde `.env`:

```env
WPPCONNECT_WHATSAPP_VERSION=2.3000.1044015310-alpha
```

## Generar token nuevo WPPConnect

```bash
curl -X POST "http://localhost:21465/api/alestur_ventas/THISISMYSECURETOKEN/generate-token"
```

Pega el `token` en `.env` como `WPPCONNECT_TOKEN`, recrea backend:

```bash
docker rm -f flask_app flask_cron
docker-compose up -d --no-deps web cron
```

## Iniciar sesión con webhook

```bash
TOKEN='PEGA_AQUI_EL_TOKEN'

curl -X POST "http://localhost:21465/api/alestur_ventas/start-session" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": "https://alesturslimitadaapi.top/wppconnect",
    "waitQrCode": false,
    "autoClose": 180000
  }'
```

## Pruebas rápidas

```bash
curl https://alesturslimitadaapi.top/health

curl -X POST "https://alesturslimitadaapi.top/wppconnect" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "onmessage",
    "session": "alestur_ventas",
    "from": "573157337390@c.us",
    "chatId": "573157337390@c.us",
    "fromMe": false,
    "isGroupMsg": false,
    "body": "Hola prueba webhook"
  }'

docker logs --tail=150 flask_app
```

## SSL del origen y Cloudflare 526

Cloudflare muestra `526` cuando esta en modo Full/Strict y el certificado del servidor origen esta vencido, invalido o no coincide con el dominio. Este proyecto monta `/etc/letsencrypt` dentro del contenedor `flask_nginx`, asi que el certificado se renueva en el host y luego se recarga Nginx.

Revisar vencimiento del certificado del origen:

```bash
cd /var/www/APIWPALESTUR
sh scripts/check_origin_ssl_expiry.sh alesturslimitadaapi.top
```

Renovar y recargar Nginx:

```bash
sh scripts/renew_origin_ssl.sh alesturslimitadaapi.top
```

Cron recomendado para revisar a diario y renovar cuando Certbot lo considere necesario:

```cron
15 3 * * * cd /var/www/APIWPALESTUR && sh scripts/renew_origin_ssl.sh alesturslimitadaapi.top >> /var/log/alestur_ssl_renew.log 2>&1
```

En Cloudflare, usar SSL/TLS `Full (strict)` solo si el origen tiene certificado vigente. Si el certificado del origen vence, Cloudflare puede devolver `526` aunque el certificado visible del navegador sea el de Cloudflare.

## Nota importante sobre `@lid`

WhatsApp Web a veces convierte números reales en identificadores `@lid`. Por eso el backend conserva el `from` exacto entrante y al responder envía `isLid: true` cuando el destino termina en `@lid`.
