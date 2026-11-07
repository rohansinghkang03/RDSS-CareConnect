"""Repeatable 30 + 20 caregiver test dataset, with exact manifests and scoped cleanup.

Refuses writes unless CARECONNECT_TEST_DATABASE=true. Use only on an explicitly
authorised test database. Never sends WhatsApp messages or calls AI.
"""
import argparse
import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime,time,timedelta
from pathlib import Path
from database_postgres import get_connection
from reporting_data import SGT

def expected(records,days,anchor):
    lower=anchor-timedelta(days=days-1)
    selected=[r for r in records if lower<=datetime.fromisoformat(r['date']).date()<=anchor]
    counts=Counter(r['request_status'] for r in selected)
    return {'caregivers_active':len(selected),'new_users':len(selected),'ai_chat_entries':len(selected),
            'resource_visits':len(selected),'completed_searches':len(selected),
            'matching_previews':sum(r['preview'] for r in selected),'searches_no_preview':sum(not r['preview'] for r in selected),
            'requests_sent':len(selected),'accepted':counts['accepted'],'declined':counts['declined'],'pending':counts['pending'],
            'ai_requests':len(selected),'input_tokens':sum(r['input_tokens'] for r in selected),
            'cached_input_tokens':sum(r['cached_tokens'] for r in selected),'output_tokens':sum(r['output_tokens'] for r in selected),
            'received_messages':len(selected),'outgoing_messages':len(selected),'delivered_messages':len(selected),'read_messages':sum(r['read'] for r in selected),
            'report_ids_in_period':sorted(r['report_id'] for r in selected)}

def run(action,run_id=None):
    if os.getenv('CARECONNECT_TEST_DATABASE','').lower()!='true':
        raise PermissionError('Refusing fixture writes: mark the authorised test target CARECONNECT_TEST_DATABASE=true first.')
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute('''CREATE TABLE IF NOT EXISTS reporting_fixture_runs(
                    id TEXT PRIMARY KEY, manifest JSONB NOT NULL)''')
                cur.execute('SELECT pg_advisory_xact_lock(301,306)')
                cur.execute('SELECT CURRENT_TIMESTAMP');now=cur.fetchone()[0];anchor=now.astimezone(SGT).date()
                if action=='seed30':
                    cur.execute('SELECT COUNT(*) FROM reporting_fixture_runs')
                    if cur.fetchone()[0]:raise ValueError('Clean up the existing fixture run before starting another.')
                    run_id=uuid.uuid4().hex[:12];manifest={'run_id':run_id,'anchor':str(anchor),'records':[]}
                else:
                    cur.execute('SELECT manifest FROM reporting_fixture_runs WHERE id=%s FOR UPDATE',(run_id,))
                    row=cur.fetchone()
                    if not row:raise ValueError('Unknown fixture run ID')
                    manifest=row[0];anchor=datetime.fromisoformat(manifest['anchor']).date()
                prefix='fixture-'+run_id+'-'
                if action=='cleanup':
                    records=manifest['records'];senders=[r['sender'] for r in records];ids=[r['report_id'] for r in records]
                    # Every deletion is tied to this manifest; no TRUNCATE, wildcard sender or core-data sweep.
                    for table in ['reporting_activity','reporting_facts']:
                        cur.execute(f'DELETE FROM {table} WHERE report_id=ANY(%s)',(ids,))
                    cur.execute('DELETE FROM usage_events WHERE sender=ANY(%s)',(senders,))
                    cur.execute('DELETE FROM reporting_ai WHERE id=ANY(%s)',([r['ai_id'] for r in records],))
                    cur.execute('DELETE FROM reporting_statuses WHERE provider_id=ANY(%s)',([r['provider_id'] for r in records],))
                    cur.execute('DELETE FROM reporting_outgoing WHERE attempt_id=ANY(%s)',([r['outgoing_id'] for r in records],))
                    cur.execute('DELETE FROM whatsapp_receipts WHERE message_hash=ANY(%s)',([r['receipt_hash'] for r in records],))
                    cur.execute('DELETE FROM match_requests WHERE id=ANY(%s) AND requester=ANY(%s)',([r['request_id'] for r in records],senders))
                    cur.execute('DELETE FROM admin_review_events WHERE application_id=ANY(%s)',([r['application_id'] for r in records],))
                    cur.execute('DELETE FROM support_buddy_drafts WHERE sender=ANY(%s)',(senders,))
                    cur.execute('DELETE FROM support_buddy_applications WHERE id=ANY(%s) AND sender=ANY(%s)',([r['application_id'] for r in records],senders))
                    cur.execute('DELETE FROM users WHERE sender=ANY(%s)',(senders,))
                    cur.execute('DELETE FROM reporting_fixture_runs WHERE id=%s',(run_id,))
                    cur.execute("DELETE FROM reporting_settings WHERE key='synthetic_test_start'")
                    manifest['cleaned']=True
                    return manifest
                count=30 if action=='seed30' else 20
                start=len(manifest['records'])
                if action=='add20' and start!=30:raise ValueError('The second batch requires exactly the first 30 fixture caregivers.')
                for i in range(start,start+count):
                    offset=i if i<30 else (i-30)*3%30
                    d=anchor-timedelta(days=offset)
                    stamp=datetime.combine(d,time(12),SGT)
                    if stamp>now:stamp=now-timedelta(seconds=2)
                    sender=prefix+str(i);person='CC-TEST-'+run_id+'-'+str(i).zfill(3)
                    outcome=['accepted','declined','pending'][i%3];preview=i%4!=0;read=i%2==0
                    inp,cached,out=1000+i*10,100+i,100+i*2
                    ai_id=prefix+'ai-'+str(i);provider=prefix+'provider-'+str(i);attempt=prefix+'out-'+str(i)
                    receipt=hashlib.sha256((prefix+'receipt-'+str(i)).encode()).hexdigest()
                    cur.execute("INSERT INTO users(sender,state,language_preference) VALUES(%s,'main_menu',%s)",(sender,['English','Malay','Tamil','Mandarin'][i%4]))
                    cur.execute('UPDATE reporting_people SET report_id=%s,first_seen=%s,observed_since=%s,last_active=%s WHERE sender=%s',(person,stamp,stamp,stamp,sender))
                    cur.execute('INSERT INTO reporting_activity(message_hash,report_id,occurred_at) VALUES(%s,%s,%s)',(receipt,person,stamp))
                    cur.execute("INSERT INTO caregiver_profiling_consent(sender,status,consent_version,granted_at,consent_epoch) VALUES(%s,'granted','careconnect-profiling-v2-reports',%s,1)",(sender,stamp))
                    for key,value in [('care_recipient_profile','Synthetic caregiving context'),('support_needs','Peer support'),('availability','Evenings')]:
                        cur.execute('INSERT INTO caregiver_profile_fields(sender,field_name,field_value,updated_at) VALUES(%s,%s,%s,%s)',(sender,key,value,stamp))
                    # These are explicitly synthetic approved records, never extracted from conversations.
                    for event,category in [('ai_chat_started',None),('resource_hub_opened',None),('resource_category_opened',str(i%4+1)),('buddy_application_started',None),('buddy_application_submitted',None)]:
                        cur.execute('INSERT INTO usage_events(sender,event_type,category,occurred_at) VALUES(%s,%s,%s,%s)',(sender,event,category,stamp))
                    cur.execute('INSERT INTO reporting_facts(report_id,event,occurred_at) VALUES(%s,%s,%s)',(person,'search_preview' if preview else 'search_no_preview',stamp))
                    cur.execute("UPDATE reporting_facts SET occurred_at=%s WHERE report_id=%s AND event='consent_granted'",(stamp,person))
                    app_status=['approved','pending','rejected'][i%3]
                    cur.execute('''INSERT INTO support_buddy_applications(sender,status,created_at,submitted_at,consent,languages,availability,support_types,display_name)
                        VALUES(%s,%s,%s,%s,1,'English','Evening','Listening ear','Synthetic test buddy') RETURNING id''',(sender,app_status,stamp,stamp.isoformat()))
                    app_id=cur.fetchone()[0]
                    cur.execute("INSERT INTO match_requests(requester,caregiver_name,match_percentage,status,created_at,responded_at) VALUES(%s,'Synthetic test buddy',80,%s,%s,%s) RETURNING id",(sender,outcome,stamp.isoformat(),stamp.isoformat() if outcome!='pending' else None))
                    request_id=cur.fetchone()[0]
                    cur.execute("INSERT INTO reporting_ai(id,feature,model,outcome,input_tokens,cached_tokens,output_tokens,service_tier,occurred_at) VALUES(%s,'AI Chat','synthetic-test-model','completed',%s,%s,%s,'default',%s)",(ai_id,inp,cached,out,stamp))
                    cur.execute("INSERT INTO whatsapp_receipts(message_hash,status,received_at,completed_at) VALUES(%s,'completed',%s,%s)",(receipt,stamp,stamp))
                    cur.execute("INSERT INTO reporting_outgoing(attempt_id,provider_id,kind,outcome,created_at) VALUES(%s,%s,'text','accepted',%s)",(attempt,provider,stamp))
                    for state in ['delivered']+(['read'] if read else []):
                        cur.execute("INSERT INTO reporting_statuses(provider_id,status,occurred_at,category,billable,pricing_model) VALUES(%s,%s,%s,'service',false,'PMP')",(provider,state,stamp))
                    manifest['records'].append(dict(sender=sender,report_id=person,date=str(d),request_status=outcome,preview=preview,read=read,input_tokens=inp,cached_tokens=cached,output_tokens=out,ai_id=ai_id,provider_id=provider,outgoing_id=attempt,receipt_hash=receipt,application_id=app_id,request_id=request_id))
                manifest['expected7d']=expected(manifest['records'],7,anchor)
                manifest['expected30d']=expected(manifest['records'],30,anchor)
                cur.execute('INSERT INTO reporting_fixture_runs(id,manifest) VALUES(%s,%s::jsonb) ON CONFLICT(id) DO UPDATE SET manifest=EXCLUDED.manifest',(run_id,json.dumps(manifest)))
                # Explicit test coverage does not change the real tracking-start marker.
                cur.execute("INSERT INTO reporting_settings(key,value) VALUES('synthetic_test_start',%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",(datetime.combine(anchor-timedelta(days=60),time.min,SGT),))
                return manifest
    finally:connection.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['seed30','add20','cleanup']);parser.add_argument('--run-id')
    parser.add_argument('--manifest',required=True,type=Path,help='Local JSON file containing the exact inputs and expected totals')
    args=parser.parse_args();result=run(args.action,args.run_id)
    args.manifest.parent.mkdir(parents=True,exist_ok=True);args.manifest.write_text(json.dumps(result,indent=2))
    print(f"Fixture run {result['run_id']}: {len(result['records'])} synthetic caregivers. Manifest saved.")

if __name__=='__main__':main()
