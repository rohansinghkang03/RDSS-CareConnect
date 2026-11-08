"""One contextual command list. Primary choices and private values stay intact."""
import re
import uuid
from conversation_context import current

COMMAND=r"'(?:menu|back|profile|resources|my status|status|application status|requests(?: [0-9]+)?|request [0-9]+|accept [0-9]+|decline [0-9]+|admin logout|admin login|report status|my chats|chat [0-9]+|stop chat [0-9]+|notifications(?: on| off)?|language|cancel|find a buddy|contact rdss|applications)'"
LABELS={'profile':'Profile and privacy settings','resources':'Resource Hub','my status':'Request and application status','status':'Check your connection request','application status':'Check your application','requests':'Incoming connection requests','admin logout':'Sign out','admin login':'Sign in as an administrator','report status':'Check your report','my chats':'Your accepted connections','notifications':'Manage update alerts','notifications on':'Turn update alerts on','notifications off':'Stop update alerts','language':'Change language','cancel':'Cancel this step','find a buddy':'Find a Support Buddy','contact rdss':'Contact RDSS','applications':'View pending applications'}

def organize(sender,reply,state):
    if not isinstance(reply,str):return reply
    context=current.get()
    # Literal command names are protected from translation, not from layout cleanup.
    private=[value for value in (context['protected'] if context else ()) if not re.fullmatch(COMMAND,value)]
    if context:context['fixed_localized']=False
    placeholders={};nonce=uuid.uuid4().hex[:12]
    for index,value in enumerate(sorted(private,key=len,reverse=True)):
        if value in reply:
            marker='__NAV_PRIVATE_'+nonce+'_'+str(index)+'__';placeholders[marker]=value;reply=reply.replace(value,marker)
    # Merge an existing section rather than appending another one.
    body,separator,old_section=reply.partition('You can type these other commands too:')
    discovered=re.findall(COMMAND,old_section)
    lines=[]
    for raw in body.splitlines():
        line=raw.strip()
        if line.startswith('Type ') and re.search(COMMAND,line):
            discovered.extend(re.findall(COMMAND,line));continue
        # Keep meaningful preceding prose, but move trailing generic reminders.
        match=re.search(r"(?:^|[.!?] )Type "+COMMAND,line)
        if match and '__NAV_PRIVATE_' not in line:
            start=match.start()+(2 if match[0].startswith(('. ', '! ', '? ')) else 0)
            discovered.extend(re.findall(COMMAND,line[start:]));raw=line[:start].rstrip()
        raw=re.sub(r"^Reply with a number[.]?(?:.*)$",'',raw)
        raw=re.sub(r"^Select a number to explore a category[.]$",'',raw)
        raw=re.sub(r"^Choose (?:a|one) number[.]?(?:.*)$",'',raw)
        lines.append(raw)
    body='\n'.join(lines).strip()
    body=re.sub(r'\n{3,}','\n\n',body)
    if state.startswith('admin_'):
        if state=='admin_pin':commands=[('back','Cancel login'),('menu','Cancel login and return to the main menu')]
        else:
            back='Admin menu'
            if state.startswith('admin_review_'):back='Application list'
            if state.startswith('admin_note_'):back='Application review without saving this note'
            commands=[('back',back),('menu','Admin menu'),('admin logout','Sign out')]
            if state in {'admin_menu','admin_report_period'}:commands.append(('report status','Check your report'))
            if state=='admin_menu':commands.append(('notifications','Manage update alerts'))
    elif state=='language_selection':commands=[('back','Previous screen'),('menu','Show language choices')]
    else:
        back='Main menu'
        if state.startswith('profile_') or state=='profiling_consent':back='Previous profile screen'
        elif state.startswith('buddy_registration_'):back='Previous application step'
        elif state=='resources_detail':back='Resource categories'
        elif state.startswith(('contact_share_','contact_chat_')):back='Your accepted connections'
        elif state=='confirm_match':back='Matching options'
        elif state in {'ai_onboarding_confirm','match_alternatives'}:back='Matching preferences'
        commands=[('back',back),('menu','Main menu')]
        if state!='main_menu':commands.append(('status','Check your connection request'))
        if state=='confirm_match':commands.append(('next buddy','See another Support Buddy'))
        if state=='ai_chat':commands.extend([('resources','Resource Hub'),('profile','Profile and privacy settings')])
        if state=='main_menu':commands.append(('notifications','Manage update alerts'))
    for quoted in discovered:
        key=quoted[1:-1]
        if key in {'back','menu'}:continue
        if state=='admin_pin':continue
        # General menus need one settings command, rather than both on/off shortcuts.
        if key in {'notifications on','notifications off'} and state in {'main_menu','admin_menu'}:continue
        label=LABELS.get(key)
        if re.fullmatch(r'stop chat [0-9]+',key):label='Withdraw contact-sharing permission for this connection'
        elif re.fullmatch(r'chat [0-9]+',key):label='View this connection and chat permission'
        elif re.fullmatch(r'accept [0-9]+',key):label='Accept this connection request'
        elif re.fullmatch(r'decline [0-9]+',key):label='Decline this connection request'
        elif re.fullmatch(r'request [0-9]+',key):label='View this connection request'
        elif re.fullmatch(r'requests [0-9]+',key):label='Next page of incoming requests'
        if label and key not in {c[0] for c in commands}:commands.append((key,label))
    # Conversational guidance only on non-sensitive choice screens.
    if re.search(r'^\s*[1-9][.]',body,re.M):
        sensitive=state in {'profiling_consent','profile_review','profile_review_confirm','profile_withdraw_confirm','buddy_registration_consent','buddy_registration_cancel','confirm_match'} or state.startswith(('admin_review_','contact_share_'))
        private_admin=state.startswith(('admin_pin','admin_note_'))
        if not sensitive and not private_admin:
            invitation="Tell me what you're looking for! Alternatively, you can use the numbered options below."
            if invitation not in body:body=re.sub(r'(?m)^(?=[ \t]*[1-9][.])',lambda _:invitation+'\n\n',body,count=1)
    # Restore protected values exactly; never rewrite a caregiver's saved wording.
    for marker,value in placeholders.items():body=body.replace(marker,value)
    return body+"\n\nYou can type these other commands too:\n"+'\n'.join("'"+key+"' — "+label for key,label in commands)
