"""Per-search preview history. Never sends a request or changes buddy eligibility."""
import hashlib
import json
from database import get_connection

def preference_key(user):
    return hashlib.sha256(json.dumps([user.get('support_type'),user.get('availability')],ensure_ascii=False).encode()).hexdigest()

def remember(connection,sender,match,user):
    connection.execute('''INSERT INTO match_search_sessions(sender,preference_key,seen_buddies,tier)
      VALUES(?,?,ARRAY[?]::integer[],?) ON CONFLICT(sender) DO UPDATE SET
      seen_buddies=CASE WHEN match_search_sessions.preference_key=EXCLUDED.preference_key
        THEN ARRAY(SELECT DISTINCT unnest(match_search_sessions.seen_buddies || EXCLUDED.seen_buddies))
        ELSE EXCLUDED.seen_buddies END,
      preference_key=EXCLUDED.preference_key,tier=EXCLUDED.tier,updated_at=CURRENT_TIMESTAMP''',
      (sender,preference_key(user),match['buddy_id'],match.get('tier','exact')))

def history(sender,user):
    c=get_connection()
    try:
        row=c.execute('SELECT seen_buddies,tier,preference_key FROM match_search_sessions WHERE sender=?',(sender,)).fetchone()
        if not row or row['preference_key']!=preference_key(user):return set(),None
        return set(row['seen_buddies']),row['tier']
    finally:c.close()

def reset(sender):
    c=get_connection()
    try:
        with c:
            c.execute('DELETE FROM match_previews WHERE requester=?',(sender,))
            c.execute('DELETE FROM match_search_sessions WHERE sender=?',(sender,))
    finally:c.close()

def remaining(sender,user,matches):
    seen,_=history(sender,user)
    return [m for m in matches if m['buddy_id'] not in seen]

def preview(sender):
    c=get_connection()
    try:
        row=c.execute('SELECT * FROM match_previews WHERE requester=?',(sender,)).fetchone()
        return dict(row) if row else None
    finally:c.close()

def remember_current(sender,user,matches):
    selected=preview(sender)
    if not selected:return
    match=next((m for m in matches if m['buddy_id']==selected['buddy_id'] and m['sender']==selected['buddy_sender']),None)
    if match:
        c=get_connection()
        try:
            with c:remember(c,sender,match,user)
        finally:c.close()

def accepted_with(sender,buddy_sender):
    c=get_connection()
    try:
        row=c.execute("SELECT * FROM match_requests WHERE status='accepted' AND ((requester=? AND buddy_sender=?) OR (requester=? AND buddy_sender=?)) ORDER BY id DESC LIMIT 1",(sender,buddy_sender,buddy_sender,sender)).fetchone()
        return dict(row) if row else None
    finally:c.close()
