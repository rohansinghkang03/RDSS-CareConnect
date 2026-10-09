"""One-time, guarded CareConnect migration. Run on Mac after reviewing backup location."""
import argparse
import datetime
import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse, unquote

from dotenv import load_dotenv
import psycopg2

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true', help='Back up and apply migration')
args = parser.parse_args()
url = os.getenv('DATABASE_URL')
if not url:
    raise SystemExit('STOP: DATABASE_URL not found in .env')
parsed = urlparse(url)
print('Target host:', parsed.hostname)
print('Target database:', parsed.path.lstrip('/'))
print('Credentials: hidden')
if not args.apply:
    print('DRY RUN ONLY. Run with --apply after confirming the target is correct.')
    raise SystemExit(0)
if not shutil.which('pg_dump'):
    raise SystemExit('STOP: pg_dump not installed; no changes made. Install PostgreSQL client tools first.')
confirm = input('Type APPLY to back up and migrate this database: ')
if confirm != 'APPLY':
    raise SystemExit('Cancelled; no changes made.')
backup_dir = ROOT / 'private_db_backups'
backup_dir.mkdir(mode=0o700, exist_ok=True)
backup = backup_dir / ('careconnect_before_language_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.dump')
env = os.environ.copy()
env.update({
    'PGHOST': parsed.hostname or '',
    'PGPORT': str(parsed.port or 5432),
    'PGDATABASE': unquote(parsed.path.lstrip('/')),
    'PGUSER': unquote(parsed.username or ''),
    'PGPASSWORD': unquote(parsed.password or ''),
    'PGSSLMODE': 'require',
})
print('Creating private database backup...')
try:
    subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--no-acl', '--file', str(backup)], env=env, check=True)
except (OSError, subprocess.CalledProcessError) as exc:
    raise SystemExit('STOP: Backup failed. No migration attempted. ' + str(exc))
backup.chmod(0o600)
if backup.stat().st_size == 0:
    raise SystemExit('STOP: Backup is empty. No migration attempted.')
print('Backup saved:', backup)
print('Backup size (bytes):', backup.stat().st_size)
print('Note: Backup contains private caregiver data. Do not commit or share it.')

conn = psycopg2.connect(url, connect_timeout=10, sslmode='require')
try:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        before_count = cur.fetchone()[0]
        cur.execute("SELECT sender, state, full_name, mood, support_type, availability FROM users ORDER BY sender")
        before = cur.fetchall()
        cur.execute((ROOT / 'migration_language_preference.sql').read_text())
        cur.execute("SELECT COUNT(*) FROM users")
        after_count = cur.fetchone()[0]
        cur.execute("SELECT sender, state, full_name, mood, support_type, availability FROM users ORDER BY sender")
        after = cur.fetchall()
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='language_preference'")
        if not cur.fetchone() or before_count != after_count or before != after:
            raise RuntimeError('Verification failed: rolling back migration')
    conn.commit()
    print('MIGRATION SUCCESS: language_preference column exists.')
    print('Existing user count unchanged:', after_count)
    print('Existing user fields unchanged: YES')
except Exception:
    conn.rollback()
    print('Migration rolled back; database backup retained.')
    raise
finally:
    conn.close()
