"""Durable, opt-in operational alerts. Never retry an ambiguous network send."""
import logging
import os
import threading
from database_postgres import get_connection

log=logging.getLogger(__name__)
_lock=threading.Lock();_thread=None

def enabled():return os.getenv('NOTIFICATIONS_ENABLED','').lower()=='true'

def subscribe(connection,sender):
    if enabled():connection.execute('INSERT INTO notification_preferences(sender,enabled) VALUES(?,TRUE) ON CONFLICT(sender) DO UPDATE SET enabled=TRUE,updated_at=CURRENT_TIMESTAMP',(sender,))

def enqueue(connection,recipient,event,entity_id,event_key):
    if enabled():connection.execute('INSERT INTO notification_outbox(recipient,event,entity_id,event_key) VALUES(?,?,?,?) ON CONFLICT DO NOTHING',(recipient,event,entity_id,str(event_key)))

def touch(sender,timestamp=None,require_timestamp=False):
    if not enabled():return
    import time
    if timestamp is None:
        if require_timestamp:return
        stamp=int(time.time())
    else:
        if not isinstance(timestamp,(str,int)) or isinstance(timestamp,bool) or not str(timestamp).isdigit():return
        stamp=int(timestamp)
        if stamp<=0 or stamp>time.time()+120:return
    connection=get_connection()
    try:
        with connection,connection.cursor() as cur:
            cur.execute('INSERT INTO notification_preferences(sender,last_inbound) SELECT sender,to_timestamp(%s) FROM users WHERE sender=%s ON CONFLICT(sender) DO UPDATE SET last_inbound=GREATEST(notification_preferences.last_inbound,EXCLUDED.last_inbound)',(stamp,sender))
    finally:connection.close()

def command(sender,text):
    if not enabled():return None
    value=text.strip().casefold()
    if value in {'stop notifications','stop alerts','unsubscribe','stop'}:value='notifications off'
    if value not in {'notifications','notifications on','notifications off'}:return None
    connection=get_connection()
    try:
        with connection,connection.cursor() as cur:
            if value!='notifications':
                cur.execute('INSERT INTO notification_preferences(sender,enabled) VALUES(%s,%s) ON CONFLICT(sender) DO UPDATE SET enabled=EXCLUDED.enabled,updated_at=CURRENT_TIMESTAMP',(sender,value.endswith(' on')))
                if value.endswith(' off'):cur.execute("UPDATE notification_outbox SET state='cancelled',updated_at=CURRENT_TIMESTAMP WHERE recipient=%s AND state='queued'",(sender,))
            cur.execute('SELECT enabled FROM notification_preferences WHERE sender=%s',(sender,));row=cur.fetchone()
    finally:connection.close()
    return ('WhatsApp update alerts are '+('on' if row and row[0] else 'off')+'. 💜\n'
            "Alerts cover applications and connections. You choose whether to respond. Turning alerts off does not withdraw profile or contact-sharing permission.\n\n"
            "You can type these other commands too:\n'notifications on' — Receive update alerts\n'notifications off' — Stop update alerts\n'menu' — Return to your menu")

def _valid(cur,event,entity,recipient,event_key=None):
    if event.startswith('application_'):
        cur.execute('SELECT sender,status,verified_at,review_version FROM support_buddy_applications WHERE id=%s AND submitted_at IS NOT NULL',(entity,));row=cur.fetchone()
        if not row:return False
        if event_key is not None and event_key!=str(entity)+':'+str(row[3]):return False
        if event=='application_submitted':
            from handlers import parse_admin_phone_numbers
            return recipient in parse_admin_phone_numbers(os.getenv('ADMIN_PHONE_NUMBERS','')) and row[1]=='pending'
        return row[0]==recipient and ((event=='application_approved' and row[1]=='approved') or (event=='application_rejected' and row[1] in {'declined','rejected'}) or (event=='application_verified' and row[1]=='pending' and row[2] is not None))
    cur.execute('SELECT requester,buddy_sender,status FROM match_requests WHERE id=%s',(entity,));row=cur.fetchone()
    if not row:return False
    if event=='connection_request':return row[1]==recipient and row[2]=='pending'
    if event in {'connection_accepted','connection_declined'}:return row[0]==recipient and row[2]==event.removeprefix('connection_')
    if event=='chat_ready':
        import match_chat_store as store
        try:return recipient in row[:2] and store.inspect(recipient,entity)['state']=='ready'
        except (PermissionError,ValueError):return False
    return False

def _finish(identifier,state,provider=None):
    c=get_connection()
    try:
        with c,c.cursor() as cur:cur.execute('UPDATE notification_outbox SET state=%s,provider_id=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s',(state,provider,identifier))
    finally:c.close()

def process_one():
    if not enabled():return False
    c=get_connection();job=None
    try:
        with c,c.cursor() as cur:
            cur.execute("UPDATE notification_outbox SET state='cancelled',updated_at=CURRENT_TIMESTAMP WHERE state='queued' AND created_at<CURRENT_TIMESTAMP-INTERVAL '30 days'")
            # A lost worker after sending is ambiguous, never an automatic resend.
            cur.execute("UPDATE notification_outbox SET state='unknown',updated_at=CURRENT_TIMESTAMP WHERE state='sending' AND updated_at<CURRENT_TIMESTAMP-INTERVAL '10 minutes'")
            cur.execute("SELECT o.id,o.recipient,o.event,o.entity_id,o.event_key FROM notification_outbox o JOIN notification_preferences p ON p.sender=o.recipient WHERE o.state='queued' AND p.enabled AND p.last_inbound>CURRENT_TIMESTAMP-INTERVAL '23 hours 55 minutes' ORDER BY o.id FOR UPDATE OF o SKIP LOCKED LIMIT 1")
            job=cur.fetchone()
            if not job:return False
            if not _valid(cur,job[2],job[3],job[1],job[4]):
                cur.execute("UPDATE notification_outbox SET state='cancelled',updated_at=CURRENT_TIMESTAMP WHERE id=%s",(job[0],));return True
            cur.execute("UPDATE notification_outbox SET state='sending',updated_at=CURRENT_TIMESTAMP WHERE id=%s",(job[0],))
    finally:c.close()
    # Recheck subscription after committing claim and immediately before release.
    c=get_connection()
    try:
        with c,c.cursor() as cur:
            cur.execute("SELECT enabled AND last_inbound>CURRENT_TIMESTAMP-INTERVAL '23 hours 55 minutes' FROM notification_preferences WHERE sender=%s",(job[1],))
            row=cur.fetchone();valid=row and row[0] and _valid(cur,job[2],job[3],job[1],job[4])
            cur.execute("SELECT u.language_preference,COALESCE(p.style,'standard') FROM users u LEFT JOIN communication_preferences p ON p.sender=u.sender WHERE u.sender=%s",(job[1],))
            presentation=cur.fetchone() or ('English','standard')
    finally:c.close()
    if not enabled():_finish(job[0],'queued');return False
    if not valid:_finish(job[0],'cancelled');return True
    import whatsapp
    from notification_messages import render
    try:
        from conversation_context import conversation
        from conversation_presentation import render_reply
        with conversation(presentation[0] or 'English',presentation[1]):
            body=render_reply(job[1],render(job[2]))
        provider=whatsapp.send_message(job[1],body)
    except whatsapp.WhatsAppRejected:_finish(job[0],'failed')
    except Exception:_finish(job[0],'unknown')
    else:_finish(job[0],'accepted',provider)
    return True

def _run():
    try:
        for _ in range(10):
            if not process_one():break
    except Exception:log.warning('Notification worker paused; no recipient details logged')

def wake_worker():
    global _thread
    if not enabled():return
    with _lock:
        if _thread and _thread.is_alive():return
        _thread=threading.Thread(target=_run,name='careconnect-notifications',daemon=True);_thread.start()
