"""One consistent read-only snapshot. Dates are Singapore calendar dates."""
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import re
from database_postgres import get_connection
from profile_validation import is_safe_profile_value

SGT=timezone(timedelta(hours=8))
FEATURES=['AI Chat','Translation','Menu routing','Profile extraction','Language detection','Matching onboarding','Matching preferences','Confirmation']

def parse_period(text, now=None):
    today=(now or datetime.now(SGT)).astimezone(SGT).date()
    text=text.strip().lower()
    if text in {'7','last7d','last 7 days'}:
        return today-timedelta(days=6),today
    if text in {'30','last30d','last 30 days'}:
        return today-timedelta(days=29),today
    pieces=text.split()
    if len(pieces)!=2:
        raise ValueError('Choose 7 or 30, or enter two dates: DD-MM-YYYY DD-MM-YYYY.')
    try:
        start,end=(datetime.strptime(s,'%d-%m-%Y').date() for s in pieces)
    except ValueError:
        raise ValueError('Use DD-MM-YYYY DD-MM-YYYY, for example 01-11-2026 07-11-2026.') from None
    if end<start or (end-start).days>=31 or end>today:
        raise ValueError('Choose 1 to 31 days, ending today or earlier.')
    return start,end

def timestamp(value):
    if isinstance(value,datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value,str):
        try:
            value=value.replace('Z','+00:00')
            if re.search(r'[ T]\d{2}:\d{2}',value):value=re.sub(r'([+-]\d{2})$',r'\1:00',value)
            # PostgreSQL text timestamps may have 1–6 fractional digits; Python 3.9
            # accepts only millisecond/microsecond precision reliably.
            value=re.sub(r'\.(\d{1,6})(?=[+-]|$)',lambda m:'.'+m.group(1).ljust(6,'0'),value)
            return timestamp(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None

def snapshot(start,end, excluded=()):
    if not isinstance(start,date) or not isinstance(end,date) or not 0<=(end-start).days<31:
        raise ValueError('Unsupported report range')
    days=(end-start).days+1
    previous=start-timedelta(days=days)
    lower=datetime.combine(previous,time.min,SGT)
    upper=datetime.combine(end+timedelta(days=1),time.min,SGT)
    connection=get_connection()
    try:
        connection.set_session(isolation_level='REPEATABLE READ',readonly=True)
        with connection:
            with connection.cursor() as cur:
                def query(sql,params=()):
                    cur.execute(sql,params)
                    rows=cur.fetchmany(100001)
                    if len(rows)>100000:
                        raise ValueError('Report is too large; select a shorter period')
                    return rows
                generated=query('SELECT CURRENT_TIMESTAMP')[0][0]
                coverage=dict(query('SELECT key,value FROM reporting_settings'))
                if 'phase3_v1' not in coverage:
                    raise RuntimeError('Reporting migration is not installed')
                if 'tracking_live_start' in coverage:coverage['coverage_start']=coverage['tracking_live_start']
                synthetic='synthetic_test_start' in coverage
                if synthetic:coverage['coverage_start']=coverage['synthetic_test_start']
                # Only the approved fields below leave this function. Never query conversation text.
                people=query('''SELECT p.sender,p.report_id,p.first_seen,p.observed_since,p.last_active,
                  u.language_preference,COALESCE(c.status,'not_given'),c.consent_version
                  FROM reporting_people p JOIN users u ON u.sender=p.sender
                  LEFT JOIN caregiver_profiling_consent c ON c.sender=p.sender''')
                people=[p for p in people if p[0] not in excluded]
                if len(people)>2000:
                    raise ValueError('Report exceeds the 2,000-caregiver limit; contact the administrator for a larger export.')
                ids={p[1] for p in people}
                senders={p[0] for p in people}
                activity=query('SELECT report_id,occurred_at FROM reporting_activity WHERE occurred_at>=%s AND occurred_at<%s',(lower,upper))
                activity=[r for r in activity if r[0] in ids]
                events=query('SELECT sender,event_type,category,occurred_at FROM usage_events WHERE occurred_at>=%s AND occurred_at<%s',(lower,upper))
                events=[r for r in events if r[0] in senders]
                facts=query('SELECT report_id,event,occurred_at FROM reporting_facts WHERE occurred_at>=%s AND occurred_at<%s',(lower,upper))
                facts=[r for r in facts if r[0] in ids]
                # The reporting-consent version covers administrator exports. Older grants are not expanded silently.
                fields=query('''SELECT p.report_id,f.field_name,f.field_value FROM caregiver_profile_fields f
                  JOIN reporting_people p ON p.sender=f.sender JOIN caregiver_profiling_consent c ON c.sender=f.sender
                  WHERE c.status='granted' AND c.consent_version='careconnect-profiling-v2-reports' ''')
                fields=[r for r in fields if r[0] in ids]
                permission_versions=query("SELECT p.report_id,c.consent_epoch FROM caregiver_profiling_consent c JOIN reporting_people p ON p.sender=c.sender WHERE c.status='granted' AND c.consent_version='careconnect-profiling-v2-reports'")
                requests=query('SELECT requester,status,created_at FROM match_requests')
                applications=query('SELECT sender,status,submitted_at FROM support_buddy_applications WHERE submitted_at IS NOT NULL')
                approved={r[0] for r in query("SELECT sender FROM support_buddy_applications WHERE status='approved' AND consent=1 AND submitted_at IS NOT NULL AND (verification_required=0 OR verified_at IS NOT NULL)")}
                receipts=query('SELECT received_at FROM whatsapp_receipts WHERE received_at>=%s AND received_at<%s',(lower,upper))
                outgoing=query('''SELECT o.created_at,o.outcome,
                  EXISTS(SELECT 1 FROM reporting_statuses s WHERE s.provider_id=o.provider_id AND s.status IN ('delivered','read')),
                  EXISTS(SELECT 1 FROM reporting_statuses s WHERE s.provider_id=o.provider_id AND s.status='failed'),
                  EXISTS(SELECT 1 FROM reporting_statuses s WHERE s.provider_id=o.provider_id AND s.status='read')
                  FROM reporting_outgoing o WHERE o.created_at>=%s AND o.created_at<%s''',(lower,upper))
                ai=query('SELECT feature,model,outcome,input_tokens,cached_tokens,output_tokens,service_tier,occurred_at FROM reporting_ai WHERE occurred_at>=%s AND occurred_at<%s',(datetime.combine(start,time.min,SGT),upper))
                billing=query('''SELECT DISTINCT o.provider_id,s.category,s.billable,s.pricing_model FROM reporting_outgoing o
                  JOIN reporting_statuses s ON s.provider_id=o.provider_id
                  WHERE o.created_at>=%s AND o.created_at<%s AND s.status IN ('delivered','read')''',(datetime.combine(start,time.min,SGT),upper))
    finally:
        connection.close()
    def day(stamp):
        return stamp.astimezone(SGT).date()
    dates=[previous+timedelta(days=i) for i in range(days*2)]
    daily={d:Counter() for d in dates}
    active=defaultdict(set); person_active=defaultdict(set); person_events=defaultdict(Counter)
    id_for={p[0]:p[1] for p in people}
    approved_ids={id_for[s] for s in approved if s in id_for}
    heat=defaultdict(set); heat_buddy=defaultdict(set)
    for person,stamp in activity:
        d=day(stamp); active[d].add(person)
        if d>=start:
            person_active[person].add(d)
            band=stamp.astimezone(SGT).hour//2
            heat[d,band].add(person)
            if person in approved_ids:
                heat_buddy[d,band].add(person)
    event_columns={'ai_chat_started':'ai','resource_hub_opened':'resource','buddy_application_started':'app_start','buddy_application_submitted':'app_submit'}
    categories=Counter()
    for sender,event,category,stamp in events:
        d=day(stamp)
        if event in event_columns:
            daily[d][event_columns[event]]+=1
            if d>=start:
                person_events[id_for[sender]][event_columns[event]]+=1
        if event=='resource_category_opened' and d>=start:
            categories[category]+=1
    for person,event,stamp in facts:
        d=day(stamp);daily[d][event]+=1
        if d>=start:
            person_events[person][event]+=1
    invalid_dates=0
    for sender,status,value in requests:
        stamp=timestamp(value)
        if sender not in senders:
            continue
        if stamp is None:
            invalid_dates+=1;continue
        d=day(stamp)
        if d in daily:
            daily[d]['requests']+=1;daily[d]['request_'+status]+=1
            if d>=start:
                person_events[id_for[sender]]['requests']+=1
                person_events[id_for[sender]]['request_'+status]+=1
    for sender,status,value in applications:
        stamp=timestamp(value)
        if sender not in senders:
            continue
        if stamp is None:
            invalid_dates+=1;continue
        d=day(stamp)
        if d in daily:
            daily[d]['application_cohort']+=1;daily[d]['application_'+status]+=1
    for (stamp,) in receipts:
        daily[day(stamp)]['received']+=1
    for stamp,outcome,delivered,failed,read in outgoing:
        counts=daily[day(stamp)]
        counts['outgoing']+=int(outcome=='accepted')
        counts['delivered']+=int(delivered)
        counts['failed']+=int((failed or outcome=='failed') and not delivered)
        counts['read']+=int(read)
        counts['unknown_sends']+=int(outcome in {'unknown','attempted'})
    first_seen={p[1]:p[2] for p in people}
    for d in dates:
        daily[d]['active']=len(active[d])
        daily[d]['new']=sum(1 for stamp in first_seen.values() if stamp and day(stamp)==d)
    periods=[]
    for a,b in [(previous,start-timedelta(days=1)),(start,end)]:
        unique=set().union(*(active[d] for d in dates if a<=d<=b))
        new=sum(1 for stamp in first_seen.values() if stamp and a<=day(stamp)<=b)
        returning=sum(1 for person in unique if first_seen[person] and day(first_seen[person])<a)
        unknown=sum(1 for person in unique if first_seen[person] is None)
        # Legacy registrations cannot be placed at a historical point in time.
        registered=len(people) if b==generated.astimezone(SGT).date() else None
        consent=[sum(daily[d]['consent_'+s] for d in dates if a<=d<=b) for s in ('granted','declined','withdrawn')]
        periods.append([f'{a:%d %b %Y} – {b:%d %b %Y}',len(unique),new,returning,registered,*consent])
    def heatmap(source):
        result=[]
        for weekday in range(7):
            matching=[d for d in dates if d>=max(start,coverage['coverage_start'].astimezone(SGT).date()) and d.weekday()==weekday]
            result.append([sum(len(source[d,h]) for d in matching)/len(matching) if matching else None for h in range(12)])
        return result
    approved_fields=defaultdict(dict)
    omitted_fields=0
    for person,key,value in fields:
        if is_safe_profile_value(value):approved_fields[person][key]=value
        else:omitted_fields+=1
    caregivers=[]
    for sender,person,first,observed,last,language,consent,consent_version in sorted(people,key=lambda p:p[1]):
        if consent!='granted' or consent_version!='careconnect-profiling-v2-reports':
            continue
        f=approved_fields[person];e=person_events[person]
        context='; '.join(f[k] for k in ('care_recipient_profile','caregiving_context') if k in f)
        caregivers.append([person,consent,language,context or None,f.get('support_needs'),f.get('availability'),
                           first,last,len(person_active[person]),e['ai'],e['resource'],e['search_preview']+e['search_no_preview'],e['search_preview'],e['search_no_preview'],e['requests'],e['request_accepted'],e['request_declined'],e['request_pending']])
    warnings=[f"Complete activity and cost tracking began {coverage['coverage_start'].astimezone(SGT):%d %b %Y %H:%M} SGT. Earlier figures are incomplete.",
              'New/returning user counts exclude legacy accounts with unknown first-seen dates. Registered total is available only for a report ending today.',
              'Application cohorts describe the latest submission per application. Request outcomes are current at generation.',
              'Individual caregiver rows require current reporting-version permission. Other users contribute only to aggregate activity. Older permissions are not extended to individual exports.',
              'Messages and AI costs include administrator operations. Caregiver activity excludes configured admin numbers.',
              'Costs are estimates. Unknown rates/usage remain blank. Activity is not online presence or confirmed availability.']
    warnings.append('Heatmap averages use days with tracking coverage only. Today may be incomplete.')
    if synthetic:warnings.insert(0,'SYNTHETIC TEST DATA is included. This workbook is for test reconciliation, not operational reporting.')
    if invalid_dates:
        warnings.append(f'{invalid_dates} legacy request/application records have unreadable dates and were excluded from period totals.')
    if omitted_fields:warnings.append(f'{omitted_fields} legacy profile fields failed export privacy validation and were omitted.')
    return dict(start=start,end=end,previous=previous,generated=generated,coverage=coverage['coverage_start'],daily=daily,periods=periods,
                heat=heatmap(heat),buddy_heat=heatmap(heat_buddy),categories=categories,ai=ai,billing=billing,caregivers=caregivers,warnings=warnings,
                permissions={person:epoch for person,epoch in permission_versions if person in {r[0] for r in caregivers}},fields=fields,synthetic=synthetic)

@contextmanager
def permission_guard(data):
    """Authorise the export boundary against current permission and approved fields.

    Recheck the consent generation and approved fields after workbook preparation.
    Release database locks BEFORE external network operations, so withdrawal
    never waits for an upload/send timeout. Recheck again after upload, before
    starting delivery. An already-started transfer cannot be recalled.
    """
    connection=get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                current={person:{} for person in data['permissions']}
                people=list(data['permissions'])
                cur.execute('''SELECT p.report_id,c.status,c.consent_version,c.consent_epoch FROM caregiver_profiling_consent c
                  JOIN reporting_people p ON p.sender=c.sender WHERE p.report_id=ANY(%s) ORDER BY c.sender FOR SHARE OF c''',(people,))
                permissions=cur.fetchall()
                if len(permissions)!=len(people):raise PermissionError('Reporting permission changed during preparation')
                for person,status,version,epoch in permissions:
                    if (status,version,epoch)!=('granted','careconnect-profiling-v2-reports',data['permissions'][person]):
                        raise PermissionError('Reporting permission changed during preparation')
                cur.execute('''SELECT p.report_id,f.field_name,f.field_value FROM caregiver_profile_fields f
                  JOIN reporting_people p ON p.sender=f.sender WHERE p.report_id=ANY(%s)''',(people,))
                for person,key,value in cur.fetchall():current[person][key]=value
                old={person:{} for person in data['permissions']}
                for person,key,value in data['fields']:
                    if person in old:old[person][key]=value
                if current!=old:raise PermissionError('Profile changed during preparation')
    finally:
        connection.close()
    yield
