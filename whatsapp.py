"""WhatsApp delivery with bounded waits and private logging."""
import requests
import uuid
from config import ACCESS_TOKEN, PHONE_NUMBER_ID


def send_message(recipient, message):
    return _send(recipient,'text',{'body':message})


def _send(recipient,kind,payload):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise RuntimeError("WhatsApp configuration missing")
    from reporting_tracking import safe_write
    import os
    enabled=os.getenv('REPORTING_ENABLED','').lower()=='true'
    attempt=uuid.uuid4().hex
    if enabled:
        safe_write('INSERT INTO reporting_outgoing(attempt_id,kind,outcome) VALUES(%s,%s,\'attempted\')',(attempt,kind))
    try:
        response = requests.post(
        f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": recipient,
              "type": kind, kind:payload},
        timeout=(5, 20),
        )
    except requests.RequestException:
        if enabled:safe_write("UPDATE reporting_outgoing SET outcome='unknown' WHERE attempt_id=%s",(attempt,))
        raise RuntimeError('WhatsApp request outcome unknown') from None
    if not response.ok:
        if enabled:safe_write("UPDATE reporting_outgoing SET outcome='failed' WHERE attempt_id=%s",(attempt,))
        # Never include response bodies, URLs, tokens or recipient identifiers.
        raise RuntimeError("WhatsApp delivery failed")
    try:
        identifier=response.json()['messages'][0]['id']
        if not isinstance(identifier,str) or not identifier:raise ValueError()
    except (ValueError,KeyError,IndexError,TypeError):
        if enabled:safe_write("UPDATE reporting_outgoing SET outcome='unknown' WHERE attempt_id=%s",(attempt,))
        raise RuntimeError('WhatsApp response missing message identifier') from None
    if enabled:safe_write("UPDATE reporting_outgoing SET outcome='accepted',provider_id=%s WHERE attempt_id=%s",(identifier,attempt))
    return identifier


def upload_document(path):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise RuntimeError('WhatsApp configuration missing')
    if path.stat().st_size>20*1024*1024:raise ValueError('Report exceeds the configured 20 MB limit')
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    try:
        with path.open('rb') as stream:
            response=requests.post(f'https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/media',
                headers={'Authorization':f'Bearer {ACCESS_TOKEN}'},data={'messaging_product':'whatsapp','type':mime},
                files={'file':(path.name,stream,mime)},timeout=(5,45))
        if not response.ok:raise ValueError()
        identifier=response.json()['id']
        if not isinstance(identifier,str) or not identifier.isdigit():raise ValueError()
        return identifier
    except (requests.RequestException,ValueError,KeyError,TypeError):
        raise RuntimeError('WhatsApp document upload failed') from None


def send_document(recipient,media_id,filename,caption):
    return _send(recipient,'document',{'id':media_id,'filename':filename,'caption':caption})


def delete_media(media_id):
    try:
        requests.delete(f'https://graph.facebook.com/v25.0/{media_id}',headers={'Authorization':f'Bearer {ACCESS_TOKEN}'},timeout=(5,20))
    except requests.RequestException:
        pass
