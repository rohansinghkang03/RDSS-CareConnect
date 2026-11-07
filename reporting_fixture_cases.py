"""Synthetic coverage cases for the second batch. No external calls or real identities."""
import hashlib
from datetime import datetime,time,timedelta
from collections import Counter
from reporting_data import SGT,FEATURES

def normalise(record,index):
    r=record;d=r['date']
    r.update(index=index,first_seen=d,profile_status='granted',profile_version='careconnect-profiling-v2-reports',
             profile_fields={'care_recipient_profile':'Synthetic caregiving context','support_needs':'Peer support','availability':'Evenings'},
             language=['English','Malay','Tamil','Mandarin'][index%4],application_status=['approved','pending','rejected'][index%3],application_date=d)
    r['activities']=[d]
    r['events']=[dict(event=e,date=d,category=str(index%4+1) if e=='resource_category_opened' else None) for e in ['ai_chat_started','resource_hub_opened','resource_category_opened','buddy_application_started','buddy_application_submitted']]
    r['facts']=[dict(event='consent_granted',date=d),dict(event='search_preview' if r['preview'] else 'search_no_preview',date=d)]
    r['requests']=[dict(id=r['request_id'],date=d,status=r['request_status'])]
    r['ai_calls']=[dict(id=r['ai_id'],date=d,feature='AI Chat',model='synthetic-test-model',tier='default',outcome='completed',input=r['input_tokens'],cached=r['cached_tokens'],output=r['output_tokens'])]
    r['messages']=[dict(receipt=r['receipt_hash'],attempt=r['outgoing_id'],provider=r['provider_id'],date=d,outcome='accepted',delivered=True,read=r['read'],failed=False,category='service',billable=False)]

def enrich(cur,manifest,anchor,now):
    for i,r in enumerate(manifest['records']):normalise(r,i)
    prefix='fixture-'+manifest['run_id']+'-case-'
    def stamp(d,hour=12):
        result=datetime.combine(datetime.fromisoformat(str(d)).date(),time(hour),SGT)
        return min(result,now-timedelta(seconds=2))
    def exchange(r,key,d,hour=12,chat=False):
        when=stamp(d,hour);day=str(when.astimezone(SGT).date());digest=hashlib.sha256((prefix+key).encode()).hexdigest();attempt=prefix+'out-'+key;provider=prefix+'provider-'+key
        cur.execute('INSERT INTO reporting_activity(message_hash,report_id,occurred_at) VALUES(%s,%s,%s)',(digest,r['report_id'],when));r['activities'].append(day)
        cur.execute("INSERT INTO whatsapp_receipts(message_hash,status,received_at,completed_at) VALUES(%s,'completed',%s,%s)",(digest,when,when))
        cur.execute("INSERT INTO reporting_outgoing(attempt_id,provider_id,kind,outcome,created_at) VALUES(%s,%s,'text','accepted',%s)",(attempt,provider,when))
        for state in ['delivered','read']:cur.execute("INSERT INTO reporting_statuses(provider_id,status,occurred_at,category,billable,pricing_model) VALUES(%s,%s,%s,'service',false,'PMP')",(provider,state,when))
        r['messages'].append(dict(receipt=digest,attempt=attempt,provider=provider,date=day,outcome='accepted',delivered=True,read=True,failed=False,category='service',billable=False))
        events=['ai_chat_started','resource_hub_opened','resource_category_opened'] if chat else ['main_menu_opened']
        for event in events:
            category='2' if event=='resource_category_opened' else None
            cur.execute('INSERT INTO usage_events(sender,event_type,category,occurred_at) VALUES(%s,%s,%s,%s)',(r['sender'],event,category,when));r['events'].append(dict(event=event,date=day,category=category))
        if chat:
            identifier=prefix+'ai-'+key
            cur.execute("INSERT INTO reporting_ai(id,feature,model,outcome,input_tokens,cached_tokens,output_tokens,service_tier,occurred_at) VALUES(%s,'AI Chat','synthetic-test-model','completed',500,0,50,'default',%s)",(identifier,when))
            r['ai_calls'].append(dict(id=identifier,date=day,feature='AI Chat',model='synthetic-test-model',tier='default',outcome='completed',input=500,cached=0,output=50))
        return when
    for j,r in enumerate(manifest['records'][30:]):
        d=r['date'];when=stamp(d,(j*2)%24);sender=r['sender'];person=r['report_id']
        # Spread actual interaction timestamps across all 12 bands.
        cur.execute('UPDATE reporting_activity SET occurred_at=%s WHERE message_hash=%s',(when,r['receipt_hash']))
        cur.execute('UPDATE reporting_people SET first_seen=%s WHERE sender=%s',(when,sender))
        cur.execute('UPDATE whatsapp_receipts SET received_at=%s,completed_at=%s WHERE message_hash=%s',(when,when,r['receipt_hash']))
        cur.execute('UPDATE usage_events SET occurred_at=%s WHERE sender=%s',(when,sender))
        cur.execute('UPDATE reporting_facts SET occurred_at=%s WHERE report_id=%s',(when,person))
        cur.execute('UPDATE reporting_ai SET occurred_at=%s WHERE id=%s',(when,r['ai_id']))
        cur.execute('UPDATE reporting_outgoing SET created_at=%s WHERE attempt_id=%s',(when,r['outgoing_id']))
        cur.execute('UPDATE support_buddy_applications SET created_at=%s,submitted_at=%s WHERE id=%s',(when,when.isoformat(),r['application_id']))
        cur.execute('UPDATE match_requests SET created_at=%s,responded_at=%s WHERE id=%s',(when.isoformat(),when.isoformat() if r['request_status']!='pending' else None,r['request_id']))
        cur.execute('UPDATE caregiver_profile_fields SET updated_at=%s WHERE sender=%s',(when,sender))
        cur.execute('UPDATE caregiver_profiling_consent SET granted_at=%s,updated_at=%s WHERE sender=%s',(when,when,sender))
        call=r['ai_calls'][0];call.update(feature=FEATURES[j%len(FEATURES)],model='synthetic-test-model-b' if j%3==0 else 'synthetic-test-model',tier='priority' if j%4==0 else 'default')
        if j==12:call.update(outcome='failed',input=None,cached=None,output=None)
        if j==13:call.update(outcome='unknown',cached=None)
        if j==14:call.update(cached=0)
        cur.execute('UPDATE reporting_ai SET feature=%s,model=%s,service_tier=%s,outcome=%s,input_tokens=%s,cached_tokens=%s,output_tokens=%s WHERE id=%s',(call['feature'],call['model'],call['tier'],call['outcome'],call['input'],call['cached'],call['output'],call['id']))
        message=r['messages'][0]
        if j<4:message.update(category=['service','utility','marketing','authentication'][j],billable=True)
        if j==7:message.update(outcome='failed',delivered=False,read=False,failed=True)
        if j==8:message.update(outcome='unknown',delivered=False,read=False)
        if j==9:message.update(delivered=False,read=False)
        if j==10:message.update(outcome='attempted',delivered=False,read=False)
        cur.execute('DELETE FROM reporting_statuses WHERE provider_id=%s',(r['provider_id'],))
        cur.execute('UPDATE reporting_outgoing SET outcome=%s WHERE attempt_id=%s',(message['outcome'],r['outgoing_id']))
        states=(['delivered'] if message['delivered'] else [])+(['read'] if message['read'] else [])+(['failed'] if message['failed'] else [])
        for state in states:cur.execute("INSERT INTO reporting_statuses(provider_id,status,occurred_at,category,billable,pricing_model) VALUES(%s,%s,%s,%s,%s,'PMP')",(r['provider_id'],state,when,message['category'],message['billable']))
        if j in {0,1,2}:
            cur.execute("INSERT INTO caregiver_profile_suggestions(sender,field_name,proposed_value,pending_edit_value) VALUES(%s,'support_needs','Peer support',%s) RETURNING id",(sender,'Practical caregiving tips' if j==1 else None));sid=cur.fetchone()[0]
            status='rejected' if j==2 else 'accepted';value='Practical caregiving tips' if j==1 else 'Peer support'
            cur.execute('UPDATE caregiver_profile_suggestions SET status=%s,reviewed_value=%s,pending_edit_value=NULL,reviewed_at=%s WHERE id=%s',(status,None if j==2 else value,when,sid))
            label=['profile_accepted','profile_edited','profile_rejected'][j];r['facts'].append(dict(event=label,date=d))
            cur.execute('UPDATE reporting_facts SET occurred_at=%s WHERE report_id=%s AND event=%s',(when,person,label))
            if j!=2:
                cur.execute("UPDATE caregiver_profile_fields SET field_value=%s WHERE sender=%s AND field_name='support_needs'",(value,sender));r['profile_fields']['support_needs']=value
        if j in {3,4}:
            status='declined' if j==3 else 'withdrawn';r['profile_status']=status;r['profile_fields']={}
            cur.execute('UPDATE caregiver_profiling_consent SET status=%s,withdrawn_at=%s,updated_at=%s WHERE sender=%s',(status,when,when,sender))
            cur.execute('DELETE FROM caregiver_profile_fields WHERE sender=%s',(sender,));cur.execute('DELETE FROM caregiver_profile_suggestions WHERE sender=%s',(sender,))
            r['facts'].append(dict(event='consent_'+status,date=d));cur.execute('UPDATE reporting_facts SET occurred_at=%s WHERE report_id=%s AND event=%s',(when,person,'consent_'+status))
        if j==5:
            r['profile_version']='careconnect-profiling-v1';cur.execute("UPDATE caregiver_profiling_consent SET consent_version='careconnect-profiling-v1' WHERE sender=%s",(sender,))
        if j in {6,7,8}:r['first_seen']=None;cur.execute('UPDATE reporting_people SET first_seen=NULL WHERE sender=%s',(sender,))
        if j>=9:
            prior=anchor-timedelta(days=35+j);r['first_seen']=str(prior)
            cur.execute('UPDATE reporting_people SET first_seen=%s WHERE sender=%s',(stamp(prior),sender))
            prior_stamp=exchange(r,'history-'+str(j),prior,20,chat=True)
            status=['accepted','declined','pending'][j%3]
            cur.execute("INSERT INTO match_requests(requester,caregiver_name,match_percentage,status,created_at,responded_at) VALUES(%s,'Synthetic historical buddy',80,%s,%s,%s) RETURNING id",(sender,status,prior_stamp.isoformat(),prior_stamp.isoformat() if status!='pending' else None));r['requests'].append(dict(id=cur.fetchone()[0],date=str(prior),status=status))
            outcome='search_preview' if j%2 else 'search_no_preview'
            cur.execute('INSERT INTO reporting_facts(report_id,event,occurred_at) VALUES(%s,%s,%s)',(person,outcome,prior_stamp));r['facts'].append(dict(event=outcome,date=str(prior)))
            if j>=16:
                r['application_date']=str(prior)
                cur.execute('UPDATE support_buddy_applications SET submitted_at=%s,created_at=%s WHERE id=%s',(prior_stamp.isoformat(),prior_stamp,r['application_id']))
                cur.execute("UPDATE usage_events SET occurred_at=%s WHERE sender=%s AND event_type IN ('buddy_application_started','buddy_application_submitted')",(prior_stamp,sender))
                for event in r['events']:
                    if event['event'] in {'buddy_application_started','buddy_application_submitted'}:event['date']=str(prior)
        if j==6:exchange(r,'extra-current',anchor-timedelta(days=2),18,chat=True)
        if j==15:r['profile_fields']['availability']='Flexible';cur.execute("UPDATE caregiver_profile_fields SET field_value='Flexible' WHERE sender=%s AND field_name='availability'",(sender,))
        if j==16:r['profile_fields'].pop('support_needs');cur.execute("DELETE FROM caregiver_profile_fields WHERE sender=%s AND field_name='support_needs'",(sender,))
        if j==17:
            value='Synthetic ongoing caregiving. Would like practical ideas for balancing everyday routines, planning breaks and connecting with other caregivers. Prefers clear information about support services and a friendly conversation.'
            r['profile_fields']['caregiving_context']=value
            cur.execute("INSERT INTO caregiver_profile_fields(sender,field_name,field_value) VALUES(%s,'caregiving_context',%s)",(sender,value))
        if j==18:r['profile_fields'].pop('availability');cur.execute("DELETE FROM caregiver_profile_fields WHERE sender=%s AND field_name='availability'",(sender,))
        if j==19:r['profile_fields'].pop('care_recipient_profile');cur.execute("DELETE FROM caregiver_profile_fields WHERE sender=%s AND field_name='care_recipient_profile'",(sender,))
    # Exercise every weekday/time-band heatmap cell with one approved synthetic buddy.
    r=manifest['records'][30];r['first_seen']=str(anchor-timedelta(days=7))
    cur.execute('UPDATE reporting_people SET first_seen=%s WHERE sender=%s',(stamp(r['first_seen'],0),r['sender']))
    for days_back in range(1,8):
        for band in range(12):exchange(r,f'heat-{days_back}-{band}',anchor-timedelta(days=days_back),band*2)
    for r in manifest['records']:
        cur.execute('UPDATE reporting_people SET last_active=(SELECT MAX(occurred_at) FROM reporting_activity WHERE report_id=%s) WHERE sender=%s',(r['report_id'],r['sender']))
    manifest['coverage_cases']=['all 12 time bands and 7 weekdays for users and approved buddies','previous-period comparisons','new, returning and unknown-first-seen users','original, edited and rejected profile reviews','declined, withdrawn and legacy permission excluded from individual export','missing optional profile values and wrapped long text','all application and request statuses','accepted, failed, unconfirmed and not-yet-delivered sends','four confirmed billable categories and confirmed-free messages','all eight AI features, two models, multiple tiers, zero cached input and unknown/failed usage']

def expected_full(records,days,anchor):
    lower=anchor-timedelta(days=days-1)
    inside=lambda d:lower<=datetime.fromisoformat(d).date()<=anchor
    result=Counter();ids=[];resources=Counter();features={};billable=Counter();profile_rows=0
    for r in records:
        active=any(inside(d) for d in r['activities'])
        if active:ids.append(r['report_id'])
        if r['first_seen'] and inside(r['first_seen']):result['new_users']+=1
        if active and r['first_seen'] and datetime.fromisoformat(r['first_seen']).date()<lower:result['returning_users']+=1
        if active and r['first_seen'] is None:result['unknown_first_seen_active']+=1
        visible=r['profile_status']=='granted' and r['profile_version']=='careconnect-profiling-v2-reports'
        profile_rows+=visible
        if visible:result['summary_user_days']+=len({d for d in r['activities'] if inside(d)})
        for event in r['events']:
            if not inside(event['date']):continue
            result[event['event']]+=1
            if event['event']=='resource_category_opened':resources[event['category']]+=1
        for fact in r['facts']:
            if inside(fact['date']):result[fact['event']]+=1
        for request in r['requests']:
            if inside(request['date']):result['requests_sent']+=1;result[request['status']]+=1
        if inside(r['application_date']):result['applications_submitted']+=1;result['application_'+r['application_status']]+=1
        for call in r['ai_calls']:
            if not inside(call['date']):continue
            result['ai_requests']+=1;result['unknown_ai_calls']+=int(call['outcome']!='completed' or None in (call['input'],call['cached'],call['output']))
            key=' | '.join([call['feature'],call['model'],call['tier']]);group=features.setdefault(key,Counter());group['requests']+=1
            for field,name in [('input','input_tokens'),('cached','cached_input_tokens'),('output','output_tokens')]:
                if call[field] is not None:result[name]+=call[field];group[name]+=call[field]
            group['unknown_calls']+=int(call['outcome']!='completed' or None in (call['input'],call['cached'],call['output']))
        for message in r['messages']:
            if not inside(message['date']):continue
            result['received_messages']+=1;result['outgoing_messages']+=int(message['outcome']=='accepted')
            result['delivered_messages']+=int(message['delivered']);result['read_messages']+=int(message['read']);result['failed_messages']+=int(message['failed'])
            result['unconfirmed_sends']+=int(message['outcome'] in {'unknown','attempted'})
            if message['delivered'] and message['billable']:billable[message['category']]+=1
    result.update(caregivers_active=len(ids),permitted_profile_rows=profile_rows)
    result['ai_chat_entries']=result['ai_chat_started'];result['resource_visits']=result['resource_hub_opened']
    result['completed_searches']=result['search_preview']+result['search_no_preview'];result['matching_previews']=result['search_preview'];result['searches_no_preview']=result['search_no_preview']
    return dict(result,report_ids_in_period=sorted(ids),resource_categories=dict(resources),ai_groups={k:dict(v) for k,v in features.items()},billable_categories=dict(billable))
