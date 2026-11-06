"""Explicit migration preflight; dry run by default. Does not load .env."""
import argparse
import os
from pathlib import Path
import psycopg2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn-env', default='CARECONNECT_MIGRATION_URL', help='Environment variable holding an explicitly selected database URL')
    parser.add_argument('--apply', action='store_true', help='Commit the migration; otherwise all schema changes roll back')
    args = parser.parse_args()
    dsn = os.getenv(args.dsn_env)
    if not dsn:
        parser.error('Set the explicitly selected migration URL; no database was contacted')
    sql = (Path(__file__).resolve().parents[1] / 'phase2_schema.sql').read_text()
    if not args.apply:
        sql = sql.rsplit('COMMIT;', 1)[0] + 'ROLLBACK;'
    conn = psycopg2.connect(dsn, connect_timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    except Exception:
        conn.rollback()
        # PostgreSQL diagnostics can contain private values; do not print them.
        raise SystemExit('Migration failed and rolled back. Review schema and duplicate pending rows in an authorized environment.') from None
    finally:
        conn.close()
    print('Migration applied.' if args.apply else 'Preflight passed; all changes rolled back.')


if __name__ == '__main__':
    main()
