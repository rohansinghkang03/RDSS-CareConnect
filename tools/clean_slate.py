"""Explicit operator maintenance only; callers must back up and verify the target first."""
from psycopg2 import sql
PERSON_TABLES=set('''admin_login_attempts admin_review_events admin_sessions caregiver_profile_fields caregiver_profile_suggestions caregiver_profiling_consent caregiver_sharing_decisions caregivers communication_preferences conversation_messages match_chat_deliveries match_chat_permissions match_chat_prompts match_previews match_requests match_search_sessions notification_outbox notification_preferences reporting_activity reporting_admin_sessions reporting_ai reporting_facts reporting_fixture_runs reporting_jobs reporting_login_attempts reporting_outgoing reporting_people reporting_statuses support_buddy_applications support_buddy_drafts usage_events users whatsapp_receipts basic_profiles basic_profile_drafts buddy_list_sessions admin_login_prompts connection_request_drafts connection_request_details connection_accept_notices buddy_profile_edit_drafts buddy_profile_edits buddy_whatsapp_consent admin_verification_drafts'''.split())
def clean(connection):
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(301,11)')
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")
        tables={row[0] for row in cur.fetchall()}
        unexpected=tables-PERSON_TABLES-{'reporting_settings'}
        if unexpected:raise ValueError('Unexpected tables require review before reset: '+', '.join(sorted(unexpected)))
        target=sorted(tables & PERSON_TABLES)
        cur.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY').format(sql.SQL(',').join(map(sql.Identifier,target))))
        if 'reporting_settings' in tables:
            cur.execute("UPDATE reporting_settings SET value=CURRENT_TIMESTAMP WHERE key IN ('coverage_start','tracking_live_start')")
        for table in target:
            cur.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table)))
            if cur.fetchone()[0]:raise ValueError('Reset did not empty '+table)
        return target
