"""Shared PIN with number allowlist, bounded attempts and expiring sessions."""
import hashlib
import hmac
import os
from database_postgres import get_connection

def version(pin):
    secret=os.getenv('WHATSAPP_APP_SECRET','')
    return hmac.new((secret or pin).encode(),('careconnect-admin-v1:'+pin).encode(),hashlib.sha256).hexdigest()

def session_valid(sender, pin, allowed, expected_version=None):
    if not pin or sender not in allowed:
        return False
    credential=version(pin)
    if expected_version and not hmac.compare_digest(credential,expected_version):
        return False
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('SELECT credential_version FROM reporting_admin_sessions WHERE sender=%s AND expires_at>CURRENT_TIMESTAMP',(sender,))
                row=cur.fetchone()
                return bool(row and hmac.compare_digest(row[0],credential))
    finally:
        connection.close()

def login(sender, provided, pin, allowed):
    if not pin or sender not in allowed:
        return 'denied'
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,303))',(sender,))
                cur.execute("DELETE FROM reporting_login_attempts WHERE attempted_at<CURRENT_TIMESTAMP-INTERVAL '1 day'")
                cur.execute("SELECT COUNT(*) FROM reporting_login_attempts WHERE sender=%s AND attempted_at>CURRENT_TIMESTAMP-INTERVAL '15 minutes'",(sender,))
                if cur.fetchone()[0]>=5:
                    return 'locked'
                if not hmac.compare_digest(provided.strip().encode(),pin.encode()):
                    cur.execute('INSERT INTO reporting_login_attempts(sender) VALUES(%s)',(sender,))
                    return 'incorrect'
                cur.execute('DELETE FROM reporting_login_attempts WHERE sender=%s',(sender,))
                cur.execute("INSERT INTO reporting_admin_sessions(sender,credential_version,expires_at) VALUES(%s,%s,CURRENT_TIMESTAMP+INTERVAL '30 minutes') ON CONFLICT(sender) DO UPDATE SET credential_version=EXCLUDED.credential_version,expires_at=EXCLUDED.expires_at",(sender,version(pin)))
                return 'ok'
    finally:
        connection.close()

def logout(sender):
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('DELETE FROM reporting_admin_sessions WHERE sender=%s',(sender,))
                cur.execute("UPDATE reporting_jobs SET status='cancelled',updated_at=CURRENT_TIMESTAMP WHERE sender=%s AND status IN ('queued','building')",(sender,))
    finally:
        connection.close()
