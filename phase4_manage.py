"""Additive Phase 4 preflight. Uses the operator's explicitly authorised database."""
import argparse
from pathlib import Path
from database_postgres import get_connection

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    connection=get_connection()
    try:
        sql=(Path(__file__).parent/'phase4_schema.sql').read_text().replace('BEGIN;','',1).rsplit('COMMIT;',1)[0]
        with connection.cursor() as cur:cur.execute(sql)
        if args.apply:
            connection.commit();print('Phase 4 communication preferences migration applied.')
        else:
            connection.rollback();print('Phase 4 preflight passed. All changes rolled back.')
    finally:connection.close()

if __name__=='__main__':main()
