"""Own public nickname correction, without changing private identity or approval."""
from database import get_connection,get_support_buddy_application,update_user
from profile_validation import is_safe_profile_value
from conversation_context import protect
from connection_requests import enabled

def validate_name(value):
    value=value.strip()
    if not 1<=len(value)<=60 or not any(c.isalpha() for c in value) or not is_safe_profile_value(value):raise ValueError("Please use a name or nickname up to 60 characters, not just numbers. Leave out phone numbers, addresses, email addresses and links.")
    return value

def show(sender,notice=''):
    from handlers import caregiver_message
    app=get_support_buddy_application(sender)
    if not app:return caregiver_message(sender,"No submitted Support Buddy profile is available. Choose Become a Support Buddy from the main menu to apply.")
    protect(app['display_name'])
    c=get_connection()
    try:
        from connection_requests import upfront_authorized
        sharing=upfront_authorized(c,sender,app['id'])
    finally:c.close()
    update_user(sender,state='buddy_profile_menu')
    return caregiver_message(sender,(notice+'\n\n' if notice else '')+'Your Support Buddy profile 💜\n\nDisplay name: '+(app['display_name'] or 'Support Buddy')+'\nApplication status: '+app['status'].capitalize()+'\nBuddy WhatsApp-sharing permission: '+('Enabled' if sharing else 'Not enabled')+"\n\nYou can update your public display name here.\n\n1. Edit display name\n2. Return to profile and privacy settings\n3. WhatsApp-sharing permission")

def prepare_name(sender,value):
    value=validate_name(value);c=get_connection()
    try:
        with c:
            row=c.execute('SELECT id,display_name,review_version FROM support_buddy_applications WHERE sender=? AND submitted_at IS NOT NULL FOR UPDATE',(sender,)).fetchone()
            if not row:raise PermissionError('No submitted profile')
            c.execute('INSERT INTO buddy_profile_edit_drafts(sender,application_id,proposed_name,source_name,source_review_version) VALUES(?,?,?,?,?) ON CONFLICT(sender) DO UPDATE SET application_id=EXCLUDED.application_id,proposed_name=EXCLUDED.proposed_name,source_name=EXCLUDED.source_name,source_review_version=EXCLUDED.source_review_version,created_at=CURRENT_TIMESTAMP',(sender,row['id'],value,row['display_name'],row['review_version']))
    finally:c.close()

def confirmation(sender):
    from handlers import caregiver_message
    c=get_connection()
    try:row=c.execute('SELECT proposed_name FROM buddy_profile_edit_drafts WHERE sender=?',(sender,)).fetchone()
    finally:c.close()
    if not row:return show(sender,'There is no pending display-name change.')
    protect(row['proposed_name']);update_user(sender,state='buddy_profile_confirm')
    return caregiver_message(sender,'Use this public display name?\n\n'+row['proposed_name']+'\n\nIt will be shown on your Support Buddy profile. Your other information and permissions stay unchanged.\n\n1. Confirm and save\n2. Cancel without changing')

def commit_name(sender):
    c=get_connection()
    try:
        with c:
            app=c.execute('SELECT * FROM support_buddy_applications WHERE sender=? AND submitted_at IS NOT NULL FOR UPDATE',(sender,)).fetchone()
            draft=c.execute("SELECT * FROM buddy_profile_edit_drafts WHERE sender=? AND created_at>CURRENT_TIMESTAMP-INTERVAL '30 minutes' FOR UPDATE",(sender,)).fetchone()
            if not app or not draft or app['id']!=draft['application_id'] or app['display_name']!=draft['source_name'] or app['review_version']!=draft['source_review_version']:raise PermissionError('Profile changed; please review again')
            name=validate_name(draft['proposed_name'])
            c.execute('UPDATE support_buddy_applications SET display_name=? WHERE id=? AND sender=?',(name,app['id'],sender))
            c.execute('INSERT INTO buddy_profile_edits(sender,application_id,old_name,new_name) VALUES(?,?,?,?)',(sender,app['id'],app['display_name'],name))
            c.execute('DELETE FROM buddy_profile_edit_drafts WHERE sender=?',(sender,))
    finally:c.close()

def current_screen(sender,state):
    from handlers import caregiver_message
    if state=='buddy_contact_consent':
        from connection_requests import buddy_notice
        return caregiver_message(sender,'Support Buddy WhatsApp-sharing permission 💜\n\n'+buddy_notice()+'\n\n1. I agree / enable permission\n2. Withdraw buddy sharing permission\n3. Back to my buddy profile\n\nWithdrawing stops future link releases for connections where you are the buddy. Existing numbers or chats cannot be recalled. It does not withdraw AI profiling consent.')
    if state=='buddy_profile_name':return caregiver_message(sender,"What public name or nickname would you like to use?\nUse up to 60 characters. Nothing changes until you confirm.")
    return confirmation(sender) if state=='buddy_profile_confirm' else show(sender)

def handle(sender,text,state):
    value=text.strip();command=value.casefold()
    if command not in {'buddy profile','my buddy profile'} and not state.startswith(('buddy_profile_','buddy_contact_')):return None
    if not enabled():return "Support Buddy profile editing is not available yet. Type 'menu' for the main menu."
    if command in {'buddy profile','my buddy profile'}:return show(sender)
    if command in {'menu','back','profile','my profile','language','status','my status','help','resources'}:return None
    if command=='cancel' or (state=='buddy_profile_confirm' and command=='2'):
        c=get_connection()
        try:
            with c:c.execute('DELETE FROM buddy_profile_edit_drafts WHERE sender=?',(sender,))
        finally:c.close()
        return show(sender,'Display-name change cancelled. Your profile is unchanged.')
    try:
        if state=='buddy_contact_consent':
            if command in {'1','2'}:
                from connection_requests import set_upfront
                c=get_connection()
                try:
                    with c:
                        row=c.execute('SELECT id FROM support_buddy_applications WHERE sender=? AND submitted_at IS NOT NULL FOR UPDATE',(sender,)).fetchone()
                        if not row:raise PermissionError('No submitted profile')
                        set_upfront(c,sender,row['id'],command=='1')
                finally:c.close()
                return show(sender,'Buddy WhatsApp-sharing permission '+('enabled.' if command=='1' else 'withdrawn; future buddy contact links are stopped.'))
            if command=='3':return show(sender)
            return current_screen(sender,state)
        if state=='buddy_profile_menu':
            if command=='1':update_user(sender,state='buddy_profile_name');return current_screen(sender,'buddy_profile_name')
            if command=='3':update_user(sender,state='buddy_contact_consent');return current_screen(sender,'buddy_contact_consent')
            if command=='2':
                from profile_navigation import show_profile
                return show_profile(sender)
            return show(sender)
        if state=='buddy_profile_name':prepare_name(sender,value);return confirmation(sender)
        if command=='1':commit_name(sender);return show(sender,'Your public display name has been updated. 💜')
        return 'Please use 1 to confirm this exact name, or 2 to cancel.\n\n'+confirmation(sender)
    except ValueError as error:return str(error)+'\n\n'+current_screen(sender,state)
    except PermissionError:return show(sender,'Your profile changed or this confirmation expired. Please start the edit again; nothing was overwritten.')
