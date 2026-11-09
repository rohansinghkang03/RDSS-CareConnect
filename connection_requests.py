"""Reviewed per-match introductions and explicit, single-action contact permission."""
import hashlib
import json
import os
from database import get_connection
from match_browsing import preference_key
from profile_validation import is_safe_profile_value

NOTICE='careconnect-request-sharing-v1'
def enabled():return os.getenv('CONNECTION_REQUEST_V2_ENABLED','').lower()=='true'
def key(*values):return hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
BUDDY_VERSION='careconnect-buddy-whatsapp-v1'
def buddy_notice():
    return ("I agree that my WhatsApp number may be shared with a caregiver whose connection request I accept, once that caregiver also agrees to share their number. My number will not be publicly listed or shared merely because someone views my profile. Accepting a request starts a separate private WhatsApp chat opportunity; CareConnect cannot read or delete that conversation. I can withdraw future sharing permission, but numbers or links already released cannot be recalled. ")
def upfront_authorized(c,sender,application_id,lock=False):
    row=c.execute("SELECT status,notice_version,consent_text FROM buddy_whatsapp_consent WHERE sender=? AND application_id=?"+(' FOR UPDATE' if lock else ''),(sender,application_id)).fetchone()
    return bool(row and row['status']=='granted' and row['notice_version']==BUDDY_VERSION and row['consent_text']==buddy_notice())
def set_upfront(c,sender,application_id,agree):
    c.execute('INSERT INTO buddy_whatsapp_consent(sender,application_id,status,notice_version,consent_text) VALUES(?,?,?,?,?) ON CONFLICT(sender) DO UPDATE SET application_id=EXCLUDED.application_id,status=EXCLUDED.status,notice_version=EXCLUDED.notice_version,consent_text=EXCLUDED.consent_text,updated_at=CURRENT_TIMESTAMP',(sender,application_id,'granted' if agree else 'revoked',BUDDY_VERSION,buddy_notice()))
    if not agree:
        c.execute("UPDATE match_chat_permissions p SET decision='revoked',updated_at=CURRENT_TIMESTAMP FROM match_requests r WHERE p.request_id=r.id AND p.sender=? AND r.buddy_sender=?",(sender,sender))
def consent_text():
    return ("Only your chosen name, message, support preference and timing will be sent to this buddy now. "
            "By confirming, you agree to share your WhatsApp number with this specific buddy if they accept. "
            "Their acceptance will also authorise sharing their number with you. You can then open a private WhatsApp chat. "
            "CareConnect cannot read or delete messages in that private chat. You send the first message yourself. "
            "Future link releases can be stopped, but numbers and links already released cannot be recalled. "
            "This permission is separate from AI profiling. You can cancel and keep using other CareConnect features.")
def _preview(c,sender,lock=False):
    row=c.execute('SELECT * FROM match_previews WHERE requester=?'+(' FOR UPDATE' if lock else ''),(sender,)).fetchone()
    if not row:raise PermissionError('No current buddy selection')
    from database_pg_functions import _eligible_buddy
    if row['buddy_sender']==sender or not _eligible_buddy(c,row['buddy_id'],row['buddy_sender']):raise PermissionError('Buddy no longer eligible')
    return row
def _draft(c,sender,p):
    row=c.execute('SELECT * FROM connection_request_drafts WHERE sender=? FOR UPDATE',(sender,)).fetchone()
    prefs=preference_key(p)
    if not row or row['buddy_id']!=p['buddy_id'] or row['buddy_sender']!=p['buddy_sender'] or row['preference_key']!=prefs:return None
    return row
def begin(sender):
    c=get_connection()
    try:
        with c:
            p=_preview(c,sender,True);prefs=preference_key(p)
            if not _draft(c,sender,p):
                c.execute('DELETE FROM connection_request_drafts WHERE sender=?',(sender,))
                c.execute('INSERT INTO connection_request_drafts(sender,buddy_id,buddy_sender,preference_key) VALUES(?,?,?,?)',(sender,p['buddy_id'],p['buddy_sender'],prefs))
            c.execute("UPDATE users SET state='match_request_name' WHERE sender=?",(sender,))
    finally:c.close()
    return name_prompt()
def name_prompt():return "What name or nickname would you like this buddy to see? 💜\nUse up to 60 characters. Leave out phone numbers and identifying details about someone else. Nothing is sent until you review and confirm."
def message_prompt():return "What would you like to say to this buddy? 💜\nYou can briefly describe what you'd like to talk about (up to 300 characters), or type 'skip'. Leave out phone numbers, addresses and identifying details about someone else. Your private AI chat and saved profile are not copied here."
def save(sender,field,value):
    if field not in {'chosen_name','message'}:raise ValueError('Invalid introduction field')
    value=value.strip()
    if field=='message' and value.casefold()=='skip':value=''
    if len(value)>(60 if field=='chosen_name' else 300) or (field=='chosen_name' and (not value or not any(c.isalpha() for c in value))) or (value and not is_safe_profile_value(value)):
        raise ValueError('Please use a short name/message without phone numbers, addresses, email addresses or links.')
    c=get_connection()
    try:
        with c:
            p=_preview(c,sender,True);draft=_draft(c,sender,p)
            if not draft:raise PermissionError('Buddy selection changed; review your choice again')
            c.execute('UPDATE connection_request_drafts SET '+field+'=?,review_key=NULL,reviewed_at=NULL,notice_version=NULL,updated_at=CURRENT_TIMESTAMP WHERE sender=?',(value,sender))
    finally:c.close()
def _review_key(draft):return key(draft['buddy_id'],draft['buddy_sender'],draft['preference_key'],draft['chosen_name'],draft['message'],NOTICE)
def review(sender):
    from conversation_context import protect
    c=get_connection()
    try:
        with c:
            p=_preview(c,sender,True);d=_draft(c,sender,p)
            if not d or d['chosen_name'] is None or d['message'] is None:raise PermissionError('Complete your introduction first')
            c.execute('UPDATE connection_request_drafts SET review_key=?,reviewed_at=CURRENT_TIMESTAMP,notice_version=? WHERE sender=?',(_review_key(d),NOTICE,sender))
            c.execute("UPDATE users SET state='match_request_review' WHERE sender=?",(sender,))
            protect(p['caregiver_name'],d['chosen_name'],d['message'])
            return ('Review your request to '+p['caregiver_name']+' 💜\n\nName shown: '+d['chosen_name']+'\nYour message: '+(d['message'] or 'No personal message')+
                    '\nSupport wanted: '+str(p['support_type'] or '')+'\nPreferred time: '+str(p['availability'] or '')+'\n\n'+consent_text()+
                    '\n\n1. Send request and agree to this number sharing\n2. Edit my name\n3. Edit my message\n4. Cancel without sending\n\nPlease choose 1 only if you agree. AI cannot make this decision for you.')
    finally:c.close()
def validated_for_send(c,sender,p):
    d=_draft(c,sender,p)
    if not d or not d['chosen_name'] or d['message'] is None or d['notice_version']!=NOTICE or d['review_key']!=_review_key(d):raise PermissionError('Review your introduction and sharing notice before sending')
    fresh=c.execute("SELECT reviewed_at>CURRENT_TIMESTAMP-INTERVAL '30 minutes' FROM connection_request_drafts WHERE sender=?",(sender,)).fetchone()
    if not fresh or not fresh[0]:raise PermissionError('Review expired; please review again before sending')
    if not is_safe_profile_value(d['chosen_name']) or (d['message'] and not is_safe_profile_value(d['message'])):raise PermissionError('Introduction no longer passes privacy checks')
    return d
def pair_key(row):
    from match_chat_store import _key
    return _key(row['id'],row['requester'],row['buddy_sender'],row['buddy_id'])
def grant(c,row,sender):
    from match_chat_store import VERSION
    c.execute("INSERT INTO match_chat_permissions(request_id,sender,decision,consent_version,pair_key) VALUES(?,?,'granted',?,?) ON CONFLICT(request_id,sender) DO UPDATE SET decision='granted',consent_version=EXCLUDED.consent_version,pair_key=EXCLUDED.pair_key,updated_at=CURRENT_TIMESTAMP",(row['id'],sender,VERSION,pair_key(row)))
def details_for_buddy(sender,request_id):
    if not enabled():return None
    c=get_connection()
    try:
        row=c.execute('SELECT d.* FROM connection_request_details d JOIN match_requests r ON r.id=d.request_id WHERE d.request_id=? AND r.buddy_sender=?',(request_id,sender)).fetchone()
        return dict(row) if row else None
    finally:c.close()
def _details_key(c,row):
    d=c.execute('SELECT chosen_name,message,notice_version FROM connection_request_details WHERE request_id=?',(row['id'],)).fetchone()
    return key([d['chosen_name'],d['message'],d['notice_version']] if d else None,row['support_type'],row['availability'])
def show_accept_notice(sender,request_id):
    if not enabled():return ''
    c=get_connection()
    try:
        with c:
            row=c.execute('SELECT * FROM match_requests WHERE id=? AND buddy_sender=? FOR UPDATE',(request_id,sender)).fetchone()
            if not row or row['status']!='pending':return ''
            from database_pg_functions import _eligible_buddy
            if not _eligible_buddy(c,row['buddy_id'],sender):return ''
            if not upfront_authorized(c,sender,row['buddy_id']):return "Before accepting new connections, please enable your Support Buddy WhatsApp-sharing permission. Type 'buddy profile' and choose WhatsApp-sharing permission. You do not need to register again."
            c.execute('INSERT INTO connection_accept_notices(request_id,sender,pair_key,details_key,notice_version) VALUES(?,?,?,?,?) ON CONFLICT(request_id,sender) DO UPDATE SET pair_key=EXCLUDED.pair_key,details_key=EXCLUDED.details_key,notice_version=EXCLUDED.notice_version,shown_at=CURRENT_TIMESTAMP',(request_id,sender,pair_key(row),_details_key(c,row),NOTICE))
    finally:c.close()
    return ('Accepting request #'+str(request_id)+' also gives permission to share your WhatsApp number with this caregiver, and receive theirs when both permissions are in place. '+
            'A button opens a separate private WhatsApp chat. CareConnect cannot read or delete those messages. You choose when to send a message. '+
            'You can stop future links; numbers or links already released cannot be recalled. Declining will not share your number. '+
            'Only accept if you agree to this specific connection and number sharing.')
def acceptance_authorized(c,row,sender):
    notice=c.execute("SELECT * FROM connection_accept_notices WHERE request_id=? AND sender=? AND shown_at>CURRENT_TIMESTAMP-INTERVAL '30 minutes' FOR UPDATE",(row['id'],sender)).fetchone()
    return bool(notice and notice['notice_version']==NOTICE and notice['pair_key']==pair_key(row) and notice['details_key']==_details_key(c,row))
def current_screen(sender,state):
    if state=='match_request_name':return name_prompt()
    if state=='match_request_message':return message_prompt()
    return review(sender)
def handle(sender,text,state):
    if not state.startswith('match_request_'):return None
    if not enabled():return "The updated request flow is not enabled. Type 'menu' to return."
    command=text.strip().casefold()
    if command in {'menu','back','profile','status','my status','language','help','resources','previous suggestions'}:return None
    from database import update_user
    try:
        if command=='cancel' or (state=='match_request_review' and command=='4'):
            c=get_connection()
            try:
                with c:
                    c.execute('DELETE FROM connection_request_drafts WHERE sender=?',(sender,));c.execute('DELETE FROM match_previews WHERE requester=?',(sender,));c.execute("UPDATE users SET state='main_menu' WHERE sender=?",(sender,))
            finally:c.close()
            return "Your request was cancelled. Nothing was sent and no number-sharing permission was granted. 💜"
        if state=='match_request_name':save(sender,'chosen_name',text);update_user(sender,state='match_request_message');return message_prompt()
        if state=='match_request_message':save(sender,'message',text);return review(sender)
        if command in {'2','3'}:
            next_state='match_request_name' if command=='2' else 'match_request_message';update_user(sender,state=next_state);return current_screen(sender,next_state)
        if command=='1':
            from database import create_selected_match_request
            outcome,row=create_selected_match_request(sender)
            if outcome=='accepted':
                from match_chat import screen
                return screen(sender,row['id'])
            if outcome=='unavailable':return "That buddy is no longer available. Nothing was sent. Type 'menu' to search again."
            if row:return "Your request has been sent. 💜\nConnection request #"+str(row['id'])+" is pending. Your chosen name and message are shared with this buddy; your number is only released after both permissions are in place. Type 'status' to check it."
            return "There is no current request preview. Nothing new was sent. Type 'menu' to search again."
        return 'Please choose the numbered option so your sharing decision is explicit.\n\n'+review(sender)
    except ValueError as error:return str(error)+'\n\n'+current_screen(sender,state)
    except PermissionError:
        if state=='match_request_review':
            try:return 'Please review this again before confirming. Nothing was sent.\n\n'+review(sender)
            except PermissionError:pass
        return "Your selection changed or is no longer available. Nothing was sent. Type 'menu' to search again."
