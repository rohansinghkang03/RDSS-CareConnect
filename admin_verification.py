"""Private, explicit administrator attribution; never sent to a language model."""
import unicodedata
from database import get_connection, update_user

def validate_name(value):
    value=value.strip()
    if not 2 <= len(value) <= 120 or not any(c.isalpha() for c in value) or any(not (unicodedata.category(c)[0] in 'LM' or c in " '-.·’") for c in value):
        raise ValueError('Please enter your full name using letters, spaces, apostrophes or hyphens (up to 120 characters).')
    return value

def begin(sender, application):
    from handlers import admin_application_detail
    if application['status']!='pending' or (application['verified_at'] and application.get('verified_by_name')):
        return 'Verification is already complete or this application has been reviewed.\n\n'+admin_application_detail(application['id'])
    c=get_connection()
    try:
        with c:
            c.execute('INSERT INTO admin_verification_drafts(sender,application_id,review_version) VALUES(?,?,?) ON CONFLICT(sender) DO UPDATE SET application_id=EXCLUDED.application_id,review_version=EXCLUDED.review_version,verifier_name=NULL,created_at=CURRENT_TIMESTAMP',(sender,application['id'],application['review_version']))
    finally:c.close()
    update_user(sender,state='admin_verify_name_'+str(application['id']))
    return "Enter your full name to record who completed verification. Only confirm after checking the applicant according to RDSS procedures.\n\nType 'back' to cancel or 'menu' for the admin menu."

def handle(sender,text,state):
    from handlers import admin_application_detail
    from database import review_support_buddy_application
    application_id=int(state.rsplit('_',1)[1]); command=text.strip().lower()
    c=get_connection()
    try:
        if command in {'back','cancel','2'} and (not state.startswith('admin_verify_name_') or command!='2'):
            with c:c.execute('DELETE FROM admin_verification_drafts WHERE sender=?',(sender,))
            update_user(sender,state='admin_review_'+str(application_id))
            return 'Verification cancelled.\n\n'+admin_application_detail(application_id)
        row=c.execute("SELECT * FROM admin_verification_drafts WHERE sender=? AND application_id=? AND created_at>CURRENT_TIMESTAMP-INTERVAL '30 minutes'",(sender,application_id)).fetchone()
        if not row:
            update_user(sender,state='admin_review_'+str(application_id))
            return 'Verification expired. Choose verification again.\n\n'+admin_application_detail(application_id)
        if state.startswith('admin_verify_name_'):
            try:name=validate_name(text)
            except ValueError as error:return str(error)+" Type 'back' to cancel."
            with c:c.execute('UPDATE admin_verification_drafts SET verifier_name=? WHERE sender=?',(name,sender))
            update_user(sender,state='admin_verify_confirm_'+str(application_id))
            return 'Confirm you have completed verification.\n\nVerified by: '+name+"\n\n1. Confirm verification\n2. Cancel\n\nType 'back' to cancel or 'menu' for the admin menu."
        if command!='1':return "Please choose 1 to confirm verification or 2 to cancel. Type 'menu' for the admin menu."
        try:
            app=c.execute('SELECT admin_notes FROM support_buddy_applications WHERE id=?',(application_id,)).fetchone()
            review_support_buddy_application(application_id,'verify',app['admin_notes'] or '',sender,row['review_version'],verifier_name=row['verifier_name'])
        except (ValueError,LookupError) as error:
            update_user(sender,state='admin_review_'+str(application_id))
            return str(error)+'\n\n'+admin_application_detail(application_id)
        with c:c.execute('DELETE FROM admin_verification_drafts WHERE sender=?',(sender,))
        update_user(sender,state='admin_review_'+str(application_id))
        return 'Verification recorded. You can now approve this application.\n\n'+admin_application_detail(application_id)
    finally:c.close()
