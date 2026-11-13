"""Explicit reporting migration and retention maintenance. Never runs on import.

Default commands are read-only/dry-run. Database target comes from the operator's
environment; run only against an explicitly authorised target.
"""
import argparse
from pathlib import Path
from database_postgres import get_connection

RETENTION={
 'reporting_activity':'occurred_at', 'reporting_facts':'occurred_at',
 'reporting_ai':'occurred_at','reporting_statuses':'occurred_at',
 'reporting_outgoing':'created_at','reporting_jobs':'created_at',
 'reporting_login_attempts':'attempted_at',
 'usage_events':'occurred_at','whatsapp_receipts':'received_at',
 'caregiver_profile_suggestions':'created_at','caregiver_profile_fields':'updated_at',
 'conversation_messages':'created_at',
}
OPTIONAL_RETENTION={'admin_login_prompts':'shown_at','basic_profiles':'updated_at','basic_profile_drafts':'updated_at','buddy_list_sessions':'updated_at','admin_verification_drafts':'created_at','buddy_whatsapp_consent':'updated_at','buddy_profile_edit_drafts':'created_at','buddy_profile_edits':'changed_at','connection_request_drafts':'updated_at','connection_request_details':'shared_at','connection_accept_notices':'shown_at','match_search_sessions':'updated_at','notification_outbox':'created_at','notification_preferences':'updated_at','communication_preferences':'updated_at','match_chat_permissions':'updated_at',
                    'match_chat_deliveries':'created_at','match_chat_prompts':'shown_at'}

def retention_scopes(cursor,scopes=None):
    result=dict(RETENTION if scopes is None else scopes)
    for table,column in OPTIONAL_RETENTION.items():
        cursor.execute('SELECT to_regclass(%s)',(table,))
        if cursor.fetchone()[0] is not None:result[table]=column
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['preflight','migrate','retention'])
    parser.add_argument('--apply',action='store_true',help='Commit the authorised migration/deletions; otherwise roll back')
    args=parser.parse_args()
    connection=get_connection()
    try:
        if args.command in {'preflight','migrate'}:
            sql=(Path(__file__).parent/'phase3_schema.sql').read_text()
            # Strip the script's outer transaction for controlled dry-run rollback.
            sql=sql.replace('BEGIN;','',1).rsplit('COMMIT;',1)[0]
            with connection.cursor() as cur:cur.execute(sql)
            if args.command=='migrate' and args.apply:
                connection.commit();print('Reporting migration applied.')
            else:
                connection.rollback();print('Reporting migration preflight passed. All changes rolled back.')
        else:
            with connection.cursor() as cur:
                for table,column in retention_scopes(cur).items():
                    # Identifiers are fixed constants, never user input.
                    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}<CURRENT_TIMESTAMP-INTERVAL '3 years'")
                    print(f'{table}: {cur.fetchone()[0]} expired records')
                    if args.apply:
                        cur.execute(f"DELETE FROM {table} WHERE {column}<CURRENT_TIMESTAMP-INTERVAL '3 years'")
                if args.apply:
                    cur.execute('DELETE FROM reporting_admin_sessions WHERE expires_at<CURRENT_TIMESTAMP')
            if args.apply:connection.commit();print('Three-year retention applied to the listed record scopes.')
            else:connection.rollback();print('Dry run only. No records deleted.')
    finally:connection.close()

if __name__=='__main__':main()
