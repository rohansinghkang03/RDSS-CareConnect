"""Three-year retention, once daily when the service is awake; no import-time I/O."""
import logging
import os
import threading
import time
from database_postgres import get_connection
from phase3_manage import RETENTION,retention_scopes

log=logging.getLogger('gunicorn.error.retention')
_lock=threading.Lock()
_thread=None
_next_check=0.0

def cleanup_if_due():
    """One atomic sweep across processes. A failed sweep leaves its due marker intact."""
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_xact_lock(301,307)')
                if not cur.fetchone()[0]:return None
                cur.execute("SELECT value>CURRENT_TIMESTAMP-INTERVAL '1 day' FROM reporting_settings WHERE key='retention_last_success'")
                last=cur.fetchone()
                if last and last[0]:return None
                counts={}
                for table,column in retention_scopes(cur,RETENTION).items():
                    cur.execute(f"DELETE FROM {table} WHERE {column}<CURRENT_TIMESTAMP-INTERVAL '3 years'")
                    counts[table]=cur.rowcount
                cur.execute('DELETE FROM reporting_admin_sessions WHERE expires_at<CURRENT_TIMESTAMP')
                counts['reporting_admin_sessions']=cur.rowcount
                cur.execute("INSERT INTO reporting_settings(key,value) VALUES('retention_last_success',CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
        # Log only counts, after commit; never log record contents or credentials.
        log.info('Three-year retention completed: %s',counts)
        return counts
    finally:connection.close()

def _run():
    global _next_check
    try:
        cleanup_if_due()
    except Exception:
        with _lock:_next_check=time.monotonic()+60
        log.warning('Three-year retention incomplete; will retry on later service activity')

def wake_cleanup():
    """No web-request blocking; durable daily marker survives restarts and idle sleep."""
    global _thread,_next_check
    if os.getenv('RETENTION_ENABLED','').lower()!='true':return
    with _lock:
        if time.monotonic()<_next_check or (_thread and _thread.is_alive()):return
        _next_check=time.monotonic()+300
        _thread=threading.Thread(target=_run,name='careconnect-retention',daemon=True)
        _thread.start()
