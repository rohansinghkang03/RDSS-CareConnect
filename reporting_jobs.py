"""Durable on-demand report jobs. One worker per process, database locks across workers.

No reports are published at public URLs. Sending is never blindly retried after
an ambiguous provider timeout or worker termination.
"""
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from database_postgres import get_connection
from reporting_data import parse_period, snapshot, SGT, permission_guard
from reporting_auth import session_valid, version

log=logging.getLogger(__name__)
_lock=threading.Lock()
_thread=None
_wake=threading.Event()

def credentials():
    # Same normalisation as handlers; reload environment on every job boundary.
    from handlers import parse_admin_phone_numbers
    return os.getenv('ADMIN_PIN',''),parse_admin_phone_numbers(os.getenv('ADMIN_PHONE_NUMBERS',''))

def request_report(sender,text,pin,allowed):
    if not session_valid(sender,pin,allowed):
        raise PermissionError('Please log in again before requesting a report.')
    start,end=parse_period(text)
    connection=get_connection();job_id=uuid.uuid4().hex
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('''INSERT INTO reporting_jobs(id,sender,credential_version,start_date,end_date)
                  VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id''',(job_id,sender,version(pin),start,end))
                if cur.fetchone() is None:
                    return 'A report is already being prepared. Type \'report status\' to check it, or \'admin logout\' to cancel a queued report.'
    finally:
        connection.close()
    wake_worker()
    return f"Your Excel report for {start:%d %b %Y} to {end:%d %b %Y} is queued. It will be sent here.\n\nType 'report status' to check progress, or 'menu' for the admin menu."

def job_status(sender):
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('SELECT status,start_date,end_date FROM reporting_jobs WHERE sender=%s ORDER BY created_at DESC LIMIT 1',(sender,))
                row=cur.fetchone()
    finally:
        connection.close()
    if not row:return "No reports requested yet. Choose 4 from the admin menu."
    state,start,end=row
    labels={'queued':'Queued','building':'Preparing the spreadsheet','sending':'Sending to WhatsApp',
            'sent':'Accepted by WhatsApp for delivery','failed':'Could not prepare the report. You can request it again.',
            'review':'Delivery could not be confirmed. Check this chat before requesting another copy.',
            'cancelled':'Cancelled. Log in and request another report if needed.'}
    return f"Report: {start:%d %b %Y} to {end:%d %b %Y}\n{labels[state]}\n\nType 'menu' for the admin menu."

def _update(job_id,state,provider_id=None):
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('UPDATE reporting_jobs SET status=%s,provider_id=COALESCE(%s,provider_id),updated_at=CURRENT_TIMESTAMP WHERE id=%s',(state,provider_id,job_id))
    finally:
        connection.close()

def process_one():
    """Return whether a job was claimed. Advisory lock prevents concurrent/restarted sends."""
    connection=get_connection()
    job=None
    try:
        # Transaction-level claims alone cannot distinguish a killed worker from a slow one.
        with connection:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(301,304)')
                if not cur.fetchone()[0]:return False
        try:
            with connection:
                with connection.cursor() as cur:
                    # Holding the global worker lock proves no prior worker is still building/sending.
                    cur.execute("UPDATE reporting_jobs SET status='queued',updated_at=CURRENT_TIMESTAMP WHERE status='building'")
                    cur.execute("UPDATE reporting_jobs SET status='review',updated_at=CURRENT_TIMESTAMP WHERE status='sending'")
                    cur.execute("SELECT id,sender,credential_version,start_date,end_date FROM reporting_jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
                    job=cur.fetchone()
                    if job:
                        cur.execute("UPDATE reporting_jobs SET status='building',updated_at=CURRENT_TIMESTAMP WHERE id=%s",(job[0],))
            if not job:return False
            job_id,sender,credential,start,end=job
            pin,allowed=credentials()
            if not session_valid(sender,pin,allowed,credential):
                _update(job_id,'cancelled');return True
            from reporting_workbook import build_report
            from whatsapp import upload_document, send_document, delete_media
            # Temp directory has restrictive permissions and is removed even on exceptions.
            with tempfile.TemporaryDirectory(prefix='careconnect-report-') as directory:
                generated=datetime.now(SGT)
                days=(end-start).days+1
                suffix=f'last{days}d' if end==generated.date() and days in {7,30} else f'{start:%d-%m-%Y}_to_{end:%d-%m-%Y}'
                filename=f'CareConnectStatistics_{generated:%d-%m-%Y}_{suffix}.xlsx'
                path=Path(directory)/filename
                data=snapshot(start,end,excluded=allowed)
                build_report(data,path)
                if not session_valid(sender,*credentials(),expected_version=credential):
                    _update(job_id,'cancelled');return True
                with permission_guard(data):
                    media_id=upload_document(path)
                send_attempted=False
                try:
                    # Recheck both permission version and current session after preparing/uploading.
                    if not session_valid(sender,*credentials(),expected_version=credential):
                        _update(job_id,'cancelled');return True
                    with connection:
                        with connection.cursor() as cur:
                            cur.execute("UPDATE reporting_jobs SET status='sending',updated_at=CURRENT_TIMESTAMP WHERE id=%s AND status='building' RETURNING id",(job_id,))
                            if cur.fetchone() is None:return True
                    with permission_guard(data):
                        if not session_valid(sender,*credentials(),expected_version=credential):
                            raise PermissionError('Administrator access changed before delivery')
                        active=data['periods'][1][1]
                        entries=sum(v['ai'] for d,v in data['daily'].items() if d>=start)
                        requests=sum(v['requests'] for d,v in data['daily'].items() if d>=start)
                        send_attempted=True
                        identifier=send_document(sender,media_id,filename,
                            f'CareConnect statistics, {start:%d %b}–{end:%d %b %Y}.\nRecorded active caregivers: {active}\nAI Chat entries: {entries}\nBuddy requests sent: {requests}\n\nAdministrator copy. See Definitions for coverage. Keep private and dispose of copies under RDSS policy.')
                    _update(job_id,'sent',identifier)
                finally:
                    # Retain a successfully sent media object for WhatsApp to retrieve it.
                    # Unsent uploads can be removed immediately. Successful media cleanup
                    # follows Meta retention, while local temporary files are always removed.
                    with connection:
                        with connection.cursor() as cur:
                            cur.execute('SELECT status FROM reporting_jobs WHERE id=%s',(job_id,));state=cur.fetchone()[0]
                    if not send_attempted:delete_media(media_id)
            return True
        except Exception as error:
            log.error('Report job failed; no private details logged')
            if job:
                with connection:
                    with connection.cursor() as cur:
                        cur.execute('SELECT status FROM reporting_jobs WHERE id=%s',(job[0],));state=cur.fetchone()[0]
                _update(job[0],'cancelled' if isinstance(error,PermissionError) else 'review' if state=='sending' else 'failed')
            return bool(job)
        finally:
            with connection:
                with connection.cursor() as cur:cur.execute('SELECT pg_advisory_unlock(301,304)')
    finally:
        connection.close()

def _run():
    while True:
        try:
            if process_one():continue
        except Exception:
            log.warning('Report worker unavailable; queued jobs remain durable')
        _wake.wait(10);_wake.clear()

def wake_worker():
    global _thread
    if os.getenv('REPORTING_ENABLED','').lower()!='true':return
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread=threading.Thread(target=_run,name='careconnect-reports',daemon=True);_thread.start()
    _wake.set()
