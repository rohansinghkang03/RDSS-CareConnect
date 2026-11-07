"""Signed WhatsApp webhook. Importing this module never changes the database."""
import hashlib
import hmac
import logging
import os
from flask import Flask, request
from handlers import handle_message
from whatsapp import send_message
from database_postgres import get_connection

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
logger = logging.getLogger(__name__)


@app.get('/webhook')
def verify_webhook():
    expected = os.getenv('VERIFY_TOKEN', '')
    provided = request.args.get('hub.verify_token', '')
    if (expected and request.args.get('hub.mode') == 'subscribe'
            and hmac.compare_digest(provided, expected)):
        return request.args.get('hub.challenge', ''), 200
    return 'Verification failed', 403


def process_message(message):
    if not isinstance(message, dict) or message.get('type') != 'text':
        return
    sender, identifier = message.get('from'), message.get('id')
    body = message.get('text', {}).get('body') if isinstance(message.get('text'), dict) else None
    if not all(isinstance(v, str) and v for v in (sender, identifier, body)):
        return
    digest = hashlib.sha256(identifier.encode()).hexdigest()
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO whatsapp_receipts(message_hash,status) VALUES (%s,'processing') ON CONFLICT DO NOTHING RETURNING message_hash", (digest,))
                if cursor.fetchone() is None:
                    cursor.execute('SELECT status FROM whatsapp_receipts WHERE message_hash=%s', (digest,))
                    if cursor.fetchone()[0] == 'completed':
                        return
                    raise RuntimeError('Receipt requires reconciliation')
        # Serialize messages for a sender across workers without storing their number.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 301))", (sender,))
        try:
            if os.getenv('REPORTING_ENABLED','').lower()=='true':
                from reporting_tracking import record_activity
                record_activity(sender,digest)
            reply = handle_message(sender, body.strip())
            send_message(sender, reply)
        except Exception:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE whatsapp_receipts SET status='failed' WHERE message_hash=%s", (digest,))
            logger.error('WhatsApp processing failed; receipt requires reconciliation')
            raise RuntimeError('Message processing failed') from None
        else:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE whatsapp_receipts SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE message_hash=%s", (digest,))
        finally:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 301))", (sender,))
    finally:
        connection.close()


@app.post('/webhook')
def receive_message():
    secret = os.getenv('WHATSAPP_APP_SECRET', '')
    signature = request.headers.get('X-Hub-Signature-256', '')
    expected = 'sha256=' + hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(signature, expected):
        return 'Invalid signature', 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return 'Invalid payload', 400
    try:
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                if not isinstance(value, dict):
                    return 'Invalid payload', 400
                if os.getenv('REPORTING_ENABLED','').lower()=='true':
                    from reporting_tracking import record_status
                    for status in value.get('statuses',[]):
                        record_status(status)
                for message in value.get('messages', []):
                    process_message(message)
    except (AttributeError, TypeError):
        return 'Invalid payload', 400
    except Exception:
        logger.error('Webhook failed; inspect receipt status')
        return 'Processing failed', 503
    return 'EVENT_RECEIVED', 200


@app.before_request
def resume_reports():
    # Lazy start avoids database access or threads during module import/preload.
    from reporting_jobs import wake_worker
    wake_worker()
    from retention import wake_cleanup
    wake_cleanup()


@app.get('/')
def home():
    return 'RDSS CareConnect is running!', 200


@app.get('/health')
def health():
    if os.getenv('REPORTING_ENABLED','').lower()!='true':
        return {'status':'ok','reporting':'disabled'},200
    from pathlib import Path
    connection=None
    try:
        connection=get_connection()
        with connection:
            with connection.cursor() as cur:
                cur.execute("SELECT 1 FROM reporting_settings WHERE key='phase3_v1'")
                ready=cur.fetchone() is not None
                cur.execute("SELECT to_regclass('communication_preferences') IS NOT NULL")
                conversation_ready=cur.fetchone()[0]
        ready=ready and (Path(__file__).parent/'report_templates'/'CareConnectStatistics_Template.xlsx').is_file()
        return {'status':'ok' if ready and conversation_ready else 'unavailable',
                'reporting':'ready' if ready else 'unavailable',
                'conversation':'ready' if conversation_ready else 'unavailable'},200 if ready and conversation_ready else 503
    except Exception:
        return {'status':'unavailable','reporting':'unavailable'},503
    finally:
        if connection:connection.close()


if __name__ == '__main__':
    app.run(port=8000, debug=False)
