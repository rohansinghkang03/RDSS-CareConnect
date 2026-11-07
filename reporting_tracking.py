"""Structured reporting metadata only. Never record prompts, replies or phone numbers in AI logs."""
import contextvars
import hashlib
import logging
import uuid
from contextlib import contextmanager
from database_postgres import get_connection

log = logging.getLogger(__name__)
FEATURES = frozenset({'AI Chat','Translation','Menu routing','Profile extraction','Language detection','Matching onboarding','Matching preferences','Confirmation'})
_feature = contextvars.ContextVar('reporting_feature', default='AI Chat')

def write(sql, params=()):
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute(sql, params)
    finally:
        connection.close()

def safe_write(sql, params=()):
    try:
        write(sql, params)
        return True
    except Exception:
        log.warning('Reporting metadata unavailable')
        return False

def record_activity(sender, message_hash):
    # Caller holds the sender advisory lock and has claimed the durable receipt.
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cur:
                cur.execute("INSERT INTO reporting_settings(key,value) VALUES('tracking_live_start',CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING")
                cur.execute("INSERT INTO users(sender,state) VALUES(%s,'main_menu') ON CONFLICT DO NOTHING",(sender,))
                cur.execute("INSERT INTO reporting_activity(message_hash,report_id) SELECT %s,report_id FROM reporting_people WHERE sender=%s ON CONFLICT DO NOTHING RETURNING message_hash",(message_hash,sender))
                if cur.fetchone():
                    cur.execute('UPDATE reporting_people SET last_active=CURRENT_TIMESTAMP WHERE sender=%s',(sender,))
    finally:
        connection.close()

def record_search(sender, found):
    safe_write("INSERT INTO reporting_facts(report_id,event) SELECT report_id,%s FROM reporting_people WHERE sender=%s",('search_preview' if found else 'search_no_preview',sender))

@contextmanager
def feature_context(feature):
    if feature not in FEATURES:
        raise ValueError('Unsupported reporting feature')
    token = _feature.set(feature)
    try:
        yield
    finally:
        _feature.reset(token)

def _get(obj, name, default=None):
    return obj.get(name,default) if isinstance(obj,dict) else getattr(obj,name,default)

def _integer(value):
    return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None

def tracked_create(create, feature, **kwargs):
    """Normalise the two non-streaming API usage formats; unknown is never zero."""
    if feature not in FEATURES:
        raise ValueError('Unsupported reporting feature')
    import os
    if os.getenv('REPORTING_ENABLED','').lower()!='true':
        return create(**kwargs)
    call_id = uuid.uuid4().hex
    model = str(kwargs.get('model','unknown'))[:120]
    try:
        response = create(**kwargs)
    except Exception:
        safe_write('INSERT INTO reporting_ai(id,feature,model,outcome) VALUES(%s,%s,%s,%s)',(call_id,feature,model,'failed'))
        raise
    usage = _get(response,'usage')
    input_tokens = _integer(_get(usage,'input_tokens',_get(usage,'prompt_tokens')))
    output_tokens = _integer(_get(usage,'output_tokens',_get(usage,'completion_tokens')))
    details = _get(usage,'input_tokens_details',_get(usage,'prompt_tokens_details'))
    cached = _integer(_get(details,'cached_tokens'))
    if _get(details,'cache_write_tokens',0):
        # Separate cache-write pricing is outside the three-rate workbook model.
        cached=None
    if cached is not None and (input_tokens is None or cached>input_tokens):
        cached = None
    reported = _get(response,'model')
    if isinstance(reported,str) and reported:
        model = reported[:120]
    tier = _get(response,'service_tier')
    tier = tier[:40] if isinstance(tier,str) else None
    safe_write('INSERT INTO reporting_ai(id,feature,model,outcome,input_tokens,cached_tokens,output_tokens,service_tier) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
               (call_id,feature,model,'completed' if input_tokens is not None and output_tokens is not None else 'unknown',input_tokens,cached,output_tokens,tier))
    return response

def feature_call(feature, create, **kwargs):
    return tracked_create(create,feature,**kwargs)

def record_status(status):
    from datetime import datetime, timezone
    if not isinstance(status,dict):
        return
    identifier, state = status.get('id'),status.get('status')
    if not isinstance(identifier,str) or not identifier or len(identifier)>512 or state not in {'sent','delivered','read','failed'}:
        return
    try:
        stamp = datetime.fromtimestamp(int(status['timestamp']),timezone.utc)
        if not 2020<=stamp.year<=2100:
            return
    except (KeyError,ValueError,TypeError,OverflowError,OSError):
        return
    pricing = status.get('pricing') or {}
    if not isinstance(pricing,dict):
        pricing={}
    category = pricing.get('category')
    category = category if category in {'service','utility','marketing','authentication'} else None
    billable = pricing.get('billable')
    billable = billable if isinstance(billable,bool) else None
    model = pricing.get('pricing_model')
    model = model if model in {'PMP','CBP','NBP'} else None
    # Deduplicate and preserve any billing details arriving in a later callback.
    write('''INSERT INTO reporting_statuses(provider_id,status,occurred_at,category,billable,pricing_model)
      VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(provider_id,status) DO UPDATE SET
      occurred_at=LEAST(reporting_statuses.occurred_at,EXCLUDED.occurred_at),
      category=COALESCE(EXCLUDED.category,reporting_statuses.category),
      billable=COALESCE(EXCLUDED.billable,reporting_statuses.billable),
      pricing_model=COALESCE(EXCLUDED.pricing_model,reporting_statuses.pricing_model)''',
      (identifier,state,stamp,category,billable,model))
