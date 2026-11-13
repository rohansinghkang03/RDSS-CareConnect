"""Stable paged lists, with current eligibility checked again before selection."""
import re
from database import get_connection,get_user,update_user
from conversation_context import protect
from match_browsing import preference_key
from basic_profile import enabled,get,preferences

def session(sender):
    c=get_connection()
    try:
        row=c.execute("SELECT * FROM buddy_list_sessions WHERE sender=? AND updated_at>CURRENT_TIMESTAMP-INTERVAL '30 minutes'",(sender,)).fetchone();return dict(row) if row else None
    finally:c.close()
def candidates(sender):
    from handlers import find_matches
    return find_matches(get_user(sender))
def show(sender,fresh=False,page=None):
    if not get(sender):return preferences(sender)
    user=get_user(sender);matches=candidates(sender);s=session(sender)
    if fresh or not s or s['preference_key']!=preference_key(user):
        c=get_connection()
        try:
            with c:c.execute('INSERT INTO buddy_list_sessions(sender,buddy_ids,preference_key,page) VALUES(?,?,?,0) ON CONFLICT(sender) DO UPDATE SET buddy_ids=EXCLUDED.buddy_ids,preference_key=EXCLUDED.preference_key,page=0,updated_at=CURRENT_TIMESTAMP',(sender,[m['buddy_id'] for m in matches],preference_key(user)))
        finally:c.close()
        s=session(sender)
    if not s['buddy_ids']:
        update_user(sender,state='buddy_directory')
        return "No eligible buddies share your confirmed chat languages just now. You can change your languages in 'profile' or try again later. We will not change your languages automatically. Type 'preferences' to review your search."
    selected_page=s['page'] if page is None else max(0,min(page,(len(s['buddy_ids'])-1)//5))
    c=get_connection()
    try:
        with c:c.execute('UPDATE buddy_list_sessions SET page=? WHERE sender=?',(selected_page,sender))
        requests=c.execute("SELECT buddy_id,status FROM match_requests WHERE requester=? AND status IN ('pending','accepted') ORDER BY id",(sender,)).fetchall()
    finally:c.close()
    statuses={r['buddy_id']:r['status'] for r in requests};eligible={m['buddy_id']:m for m in matches}
    lines=['People you could connect with 💜','Page '+str(selected_page+1)+' of '+str((len(s['buddy_ids'])+4)//5),'Reply with a number to view someone. No request is sent yet.']
    for pos,identifier in enumerate(s['buddy_ids'][selected_page*5:selected_page*5+5],selected_page*5+1):
        m=eligible.get(identifier)
        if not m:lines.append(str(pos)+'. No longer available');continue
        protect(m['name'],m.get('languages',''))
        fit={'exact':'Fits your support and timing preferences','support':'Fits your support preference, with different availability','time':'Fits your timing, with different support offered','other':'Different support and availability'}.get(m['tier'],'')
        status={'pending':'Request pending','accepted':'Already connected'}.get(statuses.get(identifier),'')
        lines.append(str(pos)+'. '+m['name']+(' ('+status+')' if status else '')+'\nSpeaks '+m.get('languages','').replace('|',', ')+'\nUsually available: '+', '.join(m['offered_times'])+'\nPrefers: '+m.get('contact_methods','WhatsApp text').replace('|',', ')+'\nOffers: '+', '.join(m['offered_support'])+'\n'+fit)
    update_user(sender,state='buddy_directory')
    return '\n\n'.join(lines)+"\n\nThese are usual schedules, not live online availability.\nSend 'more' for the next page, 'previous' for the previous page, 'refresh' for updated results or 'preferences' to change your search."
def select(sender,number):
    s=session(sender)
    if not s or s['preference_key']!=preference_key(get_user(sender)):return show(sender,fresh=True)
    index=int(number)-1
    if index<0 or index>=len(s['buddy_ids']):return 'Choose a listed number.\n\n'+show(sender)
    match=next((m for m in candidates(sender) if m['buddy_id']==s['buddy_ids'][index]),None)
    if not match:return 'That buddy is no longer eligible for this search.\n\n'+show(sender)
    c=get_connection()
    try:r=c.execute("SELECT id,status FROM match_requests WHERE requester=? AND buddy_id=? AND status IN ('pending','accepted') ORDER BY id DESC LIMIT 1",(sender,match['buddy_id'])).fetchone()
    finally:c.close()
    if r:
        if r['status']=='accepted':
            from handlers import existing_match_message
            return existing_match_message(sender,match,r['id'])
        protect(match['name']);update_user(sender,state='buddy_directory')
        return 'Your request to '+match['name']+' is still pending (request #'+str(r['id'])+"). No duplicate request has been sent. Send 'back' to return to the buddy list."
    from database import save_match_preview
    save_match_preview(sender,match,get_user(sender));protect(match['name'],match.get('introduction'))
    update_user(sender,state='directory_detail')
    return match['name']+' 💜\n\nSpeaks '+match['languages'].replace('|',', ')+'\nUsually available: '+', '.join(match['offered_times'])+'\nContact preference: '+match.get('contact_methods','').replace('|',', ')+'\nSupport offered: '+', '.join(match['offered_support'])+'\n\nIntroduction: '+(match.get('introduction') or 'No introduction provided.')+"\n\n1. Prepare a connection request\n2. Return to the buddy list\n\nTheir usual availability is not a promise they are online now."
def handle(sender,text,state):
    if not enabled():return None
    cmd=text.strip().casefold().rstrip(' .,!。！')
    if cmd=='preferences' and state in {'buddy_directory','directory_detail','confirm_match','match_seen','match_alternatives'}:return preferences(sender)
    if state=='directory_detail':
        if cmd in {'back','2'}:return show(sender)
        if cmd=='1':
            from connection_requests import begin
            return begin(sender)
        if cmd in {'menu','profile','language','status','my status','help','ai chat','resources'}:return None
        return 'Reply 1 to prepare a request or 2 to return to the buddy list. Nothing has been sent.'
    if state=='buddy_directory':
        cmd={'show me more buddies':'more','next page':'more','show more':'more','lagi':'more','seterusnya':'more','下一页':'more','下一頁':'more','previous page':'previous','上一页':'previous','上一頁':'previous','change my preferences':'preferences'}.get(cmd,cmd)
        if cmd=='preferences':return preferences(sender)
        number=re.search(r'\b(?:view|show|talk to|speak with|choose|select|pilih)\s+(?:(?:buddy|number)\s+)?(\d{1,5})\b',cmd)
        if number:return select(sender,number[1])
        if cmd in {'more','next','previous','back','refresh'}:
            s=session(sender);page=(s['page'] if s else 0)+(1 if cmd in {'more','next'} else -1)
            return show(sender,fresh=cmd=='refresh',page=page)
        if re.fullmatch(r'\d{1,5}',cmd):return select(sender,cmd)
        if cmd in {'menu','profile','language','status','my status','help','ai chat','resources'}:return None
        # Match public names locally, without exposing any person's profile to AI.
        s=session(sender);matches=candidates(sender)
        named=[m for m in matches if len(m['name'])>=2 and re.search(r'(?<!\w)'+re.escape(m['name'].casefold())+r'(?!\w)',cmd)]
        if len(named)==1 and s and named[0]['buddy_id'] in s['buddy_ids']:return select(sender,s['buddy_ids'].index(named[0]['buddy_id'])+1)
        if len(named)>1:return 'More than one buddy has that name. Please use their list number.\n\n'+show(sender)
        return None
    return None
