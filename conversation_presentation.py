"""One final adaptation of fixed text; private values stay outside translation input."""
import re
import uuid
from conversation_context import current,target

def render_reply(sender,reply):
    from chatbot import safe_adapt_message
    context=current.get()
    if not context or not context['language']:return reply
    if context['language'].casefold()=='english' and context['style']=='standard':return reply
    if context['fixed_localized'] and context['style']=='standard':return reply
    protected=set(context['protected'])
    protected.update(re.findall(r"https?://[^\s]+|'[a-z][a-z0-9 -]{0,50}'|__PROFILE_[A-Z_]+__",reply))
    protected.update(re.findall(r'\b\d{1,2} [A-Za-z]+ \d{4}, \d{1,2}:\d{2} [AP]M SGT\b',reply))
    nonce=uuid.uuid4().hex[:8];values={};template=reply
    # One regex pass avoids recursively replacing caregiver-supplied marker-looking text.
    if protected:
        pattern='|'.join(re.escape(v) for v in sorted(protected,key=len,reverse=True))
        def replace(match):
            marker='__CC_'+nonce+'_'+str(len(values))+'__';values[marker]=match[0];return marker
        template=re.sub(pattern,replace,template)
    context['defer']=False
    try:translated=safe_adapt_message(template,target())
    except Exception:translated=template
    finally:context['defer']=True
    original_options=re.findall(r'^\s*(\d+)\.',template,re.M)
    from conversation_script import script_ok
    if (not isinstance(translated,str) or not translated.strip()
        or any(translated.count(key)!=1 for key in values)
        or re.findall(r'^\s*(\d+)\.',translated,re.M)!=original_options
        or not script_ok(translated,context['language'],context['style'])):translated=template
    if values:
        translated=re.sub('|'.join(re.escape(k) for k in values),lambda m:values[m[0]],translated)
    return translated
