"""Operator helper. Caller must back up, verify target, and use an explicit transaction."""
EVENTS=('application_submitted','application_approved','application_rejected','application_verified','connection_request','connection_accepted','connection_declined','chat_ready')

def reset(connection):
    with connection.cursor() as q:
        q.execute("SELECT pg_advisory_xact_lock(301,10)")
        q.execute('LOCK TABLE support_buddy_applications,support_buddy_drafts,match_requests IN ACCESS EXCLUSIVE MODE')
        removed={}
        # Every buddy is being reset, so every old connection and pending buddy alert is invalid.
        for table in ['caregiver_sharing_decisions','connection_request_details','connection_accept_notices','connection_request_drafts','buddy_profile_edit_drafts','buddy_profile_edits','buddy_whatsapp_consent','admin_verification_drafts','match_chat_deliveries','match_chat_permissions','match_chat_prompts','match_previews','match_search_sessions','buddy_list_sessions','admin_review_events','match_requests','support_buddy_drafts','support_buddy_applications']:
            q.execute('SELECT to_regclass(%s)',(table,))
            if q.fetchone()[0] is not None:
                q.execute('DELETE FROM '+table);removed[table]=q.rowcount
        q.execute("DELETE FROM notification_outbox WHERE event=ANY(%s)",(list(EVENTS),));removed['old_buddy_notifications']=q.rowcount
        q.execute("UPDATE users SET state='main_menu' WHERE state LIKE 'buddy_registration_%%' OR state LIKE 'buddy_profile_%%' OR state LIKE 'buddy_contact_%%' OR state LIKE 'buddy_request_%%' OR state LIKE 'contact_share_%%' OR state LIKE 'contact_chat_%%' OR state LIKE 'match_existing_%%' OR state LIKE 'match_request_%%' OR state IN ('confirm_match','match_pending','matched','match_seen','match_alternatives','buddy_unavailable','buddy_requests','buddy_directory','directory_detail','ai_onboarding','ai_onboarding_confirm')")
        removed['navigation_states_reset']=q.rowcount
        return removed
