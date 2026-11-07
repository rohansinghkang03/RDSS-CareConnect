"""Request-local presentation data. Never persist a caregiver's message as a language."""
from contextvars import ContextVar
from contextlib import contextmanager
import time

current=ContextVar('careconnect_conversation',default=None)

@contextmanager
def conversation(language='',style='standard'):
    value={'language':language,'style':style,'protected':set(),'defer':True,
           'generated':False,'fixed_localized':False,'deadline':time.monotonic()+24}
    token=current.set(value)
    try:yield value
    finally:current.reset(token)

def protect(*values):
    context=current.get()
    if context:
        context['protected'].update(v for v in values if isinstance(v,str) and v)

def generated():
    context=current.get()
    if context:context['generated']=True

def target(fallback=''):
    context=current.get()
    if not context:return fallback
    label=context['language'] or fallback
    return label+({'standard':'','casual':'; natural casual wording',
        'singlish':'; natural Singaporean Singlish',
        'casual-mixed':'; natural informal code-switching, Singaporean Malay and English when selected',
        'romanised':'; romanised writing, matching the selected language'}.get(context['style'],''))
