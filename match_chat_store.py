"""Contact links require a valid accepted pair and fresh consent from both participants."""
import os
import re
import uuid
import hashlib
import json
from database_postgres import get_connection

VERSION='careconnect-direct-chat-v1'
PHONE=re.compile(r'[1-9][0-9]{6,14}\Z')

def _key(request_id,requester,buddy_sender,buddy_id):
    return hashlib.sha256(json.dumps([request_id,requester,buddy_sender,buddy_id],separators=(',',':')).encode()).hexdigest()

def enabled():return os.getenv('MATCH_CHAT_ENABLED','').lower()=='true'

def _pair(cur,sender,request_id):
    if not isinstance(request_id,int) or isinstance(request_id,bool) or not 0<request_id<=2147483647:
        raise PermissionError('Connection unavailable')
    cur.execute('''SELECT r.requester,r.buddy_sender,r.status,
           b.status,b.consent,b.verification_required,b.verified_at,b.submitted_at,r.buddy_id,b.display_name
        FROM match_requests r JOIN support_buddy_applications b
          ON b.id=r.buddy_id AND b.sender=r.buddy_sender
        JOIN users a ON a.sender=r.requester JOIN users z ON z.sender=r.buddy_sender
        WHERE r.id=%s AND (r.requester=%s OR r.buddy_sender=%s) FOR UPDATE OF r''',
        (request_id,sender,sender))
    row=cur.fetchone()
    if (not row or row[2]!='accepted' or row[3]!='approved' or row[4]!=1
        or (row[5] and not row[6]) or not row[7] or row[0]==row[1]
        or not all(isinstance(v,str) and PHONE.fullmatch(v) for v in row[:2])):
        raise PermissionError('Connection unavailable')
    test_scope=os.getenv('MATCH_CHAT_TEST_NUMBERS','').strip()
    if test_scope:
        allowed={part.strip().removeprefix('+') for part in test_scope.split(',')
                 if PHONE.fullmatch(part.strip().removeprefix('+'))}
        if not set(row[:2])<=allowed:raise PermissionError('Connection outside the current test scope')
    from profile_validation import is_safe_profile_value
    label=row[9] or 'Support Buddy'
    if len(label)>100 or not is_safe_profile_value(label):label='Support Buddy'
    return {'participants':(row[0],row[1]),'key':_key(request_id,row[0],row[1],row[8]),
            'partner_label':label if sender==row[0] else 'Caregiver for connection #'+str(request_id)}

def _permissions(cur,request_id,pair):
    cur.execute('''SELECT sender,decision FROM match_chat_permissions WHERE request_id=%s
      AND sender=ANY(%s) AND consent_version=%s AND pair_key=%s
      AND updated_at>=CURRENT_TIMESTAMP-INTERVAL '3 years' ''',(request_id,list(pair['participants']),VERSION,pair['key']))
    return dict(cur.fetchall())

def inspect(sender,request_id,prepare=False):
    if not enabled():return {'state':'disabled'}
    connection=get_connection()
    try:
        with connection,connection.cursor() as cur:
            pair=_pair(cur,sender,request_id)
            decisions=_permissions(cur,request_id,pair)
            own=decisions.get(sender,'not_given')
            ready=all(decisions.get(p)=='granted' for p in pair['participants'])
            if prepare and own!='granted':
                cur.execute('''INSERT INTO match_chat_prompts(sender,request_id,pair_key) VALUES(%s,%s,%s)
                  ON CONFLICT(sender) DO UPDATE SET request_id=EXCLUDED.request_id,pair_key=EXCLUDED.pair_key,shown_at=CURRENT_TIMESTAMP''',
                  (sender,request_id,pair['key']))
            return {'state':'ready' if ready else 'waiting' if own=='granted' else 'consent',
                    'own':own,'request_id':request_id,'partner_label':pair['partner_label']}
    finally:connection.close()

def prepare_prompt(sender,request_id):
    if not enabled():raise PermissionError('Direct chat disabled')
    return inspect(sender,request_id,prepare=True)

def decide(sender,request_id,decision):
    if (not enabled() and decision!='revoked') or decision not in {'granted','declined','revoked'}:raise PermissionError('Connection unavailable')
    if not isinstance(request_id,int) or isinstance(request_id,bool) or not 0<request_id<=2147483647:raise PermissionError('Connection unavailable')
    connection=get_connection()
    try:
        with connection,connection.cursor() as cur:
            if decision=='revoked':
                # Withdrawal remains possible even if a buddy is no longer eligible.
                cur.execute('SELECT requester,buddy_sender,buddy_id FROM match_requests WHERE id=%s AND (requester=%s OR buddy_sender=%s) FOR UPDATE',(request_id,sender,sender))
                row=cur.fetchone()
                if row is None:raise PermissionError('Connection unavailable')
                pair_key=_key(request_id,*row)
            else:
                pair=_pair(cur,sender,request_id);pair_key=pair['key']
                cur.execute('''SELECT 1 FROM match_chat_prompts WHERE sender=%s AND request_id=%s AND pair_key=%s
                   AND shown_at>=CURRENT_TIMESTAMP-INTERVAL '30 minutes' FOR UPDATE''',(sender,request_id,pair_key))
                if cur.fetchone() is None:raise PermissionError('Read current contact permission details first')
            cur.execute('''INSERT INTO match_chat_permissions(request_id,sender,decision,consent_version,pair_key)
              VALUES(%s,%s,%s,%s,%s) ON CONFLICT(request_id,sender) DO UPDATE SET
              decision=EXCLUDED.decision,consent_version=EXCLUDED.consent_version,pair_key=EXCLUDED.pair_key,updated_at=CURRENT_TIMESTAMP''',
              (request_id,sender,decision,VERSION,pair_key))
            cur.execute('DELETE FROM match_chat_prompts WHERE sender=%s',(sender,))
    finally:connection.close()

def accepted_connections(sender):
    if not enabled():return []
    connection=get_connection()
    try:
        with connection,connection.cursor() as cur:
            cur.execute('''SELECT r.id FROM match_requests r JOIN support_buddy_applications b
                ON b.id=r.buddy_id AND b.sender=r.buddy_sender
              WHERE r.status='accepted' AND (r.requester=%s OR r.buddy_sender=%s)
                AND b.status='approved' AND b.consent=1 AND b.submitted_at IS NOT NULL
                AND (b.verification_required=0 OR b.verified_at IS NOT NULL)
              ORDER BY r.id DESC LIMIT 20''',(sender,sender))
            return [row[0] for row in cur.fetchall()]
    finally:connection.close()

def authorize_delivery(sender,request_id):
    """Release gate immediately before provider submission; never expose phone URLs to AI.

    Revocation before this transaction wins prevents release. Once released to an
    outgoing attempt (including an in-flight send), a phone link cannot be recalled.
    Network/AI calls never run under database row locks.
    """
    if not enabled():raise PermissionError('Direct chat disabled')
    connection=get_connection()
    try:
        with connection,connection.cursor() as cur:
            pair=_pair(cur,sender,request_id)
            decisions=_permissions(cur,request_id,pair)
            if not all(decisions.get(p)=='granted' for p in pair['participants']):raise PermissionError('Mutual contact permission required')
            people=pair['participants'];other=people[1] if people[0]==sender else people[0]
            identifier=uuid.uuid4().hex
            cur.execute("INSERT INTO match_chat_deliveries(id,request_id,sender,outcome,pair_key) VALUES(%s,%s,%s,'prepared',%s)",(identifier,request_id,sender,pair['key']))
        return identifier,'https://wa.me/'+other
    finally:connection.close()

def record_delivery(identifier,outcome,provider_id=None):
    if outcome not in {'accepted','failed','unknown'}:raise ValueError('Invalid delivery outcome')
    connection=get_connection()
    try:
        with connection,connection.cursor() as cur:
            cur.execute('UPDATE match_chat_deliveries SET outcome=%s,provider_id=%s WHERE id=%s',(outcome,provider_id,identifier))
    finally:connection.close()
