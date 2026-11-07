"""Explicit additive direct-chat migration. Default is a rollback preflight."""
import argparse
from pathlib import Path
from database_postgres import get_connection

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    connection=get_connection()
    try:
        sql=(Path(__file__).parent/'match_chat_schema.sql').read_text().replace('BEGIN;','',1).rsplit('COMMIT;',1)[0]
        with connection.cursor() as cur:cur.execute(sql)
        if args.apply:connection.commit();print('Direct-chat schema applied. Feature remains controlled by MATCH_CHAT_ENABLED.')
        else:connection.rollback();print('Direct-chat preflight passed. All changes rolled back.')
    finally:connection.close()

if __name__=='__main__':main()
