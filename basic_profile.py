"""Confirmed shared identity and languages, separate from AI profiling and UI language."""
import os,re,unicodedata
from database import get_connection,get_user,update_user
from conversation_context import protect
from buddy_profile import validate_name

LANGUAGES={'1':'English','2':'Mandarin','3':'Malay','4':'Tamil','5':'Other'}
SUPPORT={'1':'Someone to listen','2':'Advice from another caregiver','3':'Casual conversation','4':'Someone with similar experiences'}
TIMES={'1':'Morning','2':'Afternoon','3':'Evening','4':'Weekends','5':'Flexible'}
def enabled():
    from connection_requests import enabled as connection_enabled
    return os.getenv('BASIC_PROFILE_ENABLED','').lower()=='true' and connection_enabled()
def get(sender):
    c=get_connection()
    try:
        r=c.execute('SELECT * FROM basic_profiles WHERE sender=?',(sender,)).fetchone();return dict(r) if r else None
    finally:c.close()
def language_set(value):
    aliases={'english':'English','英语':'English','英語':'English','mandarin':'Mandarin','chinese':'Mandarin','中文':'Mandarin','华语':'Mandarin','華語':'Mandarin','malay':'Malay','melayu':'Malay','bahasa melayu':'Malay','bahasa malaysia':'Malay','tamil':'Tamil','தமிழ்':'Tamil'}
    value=re.sub(r'^(?:i (?:can |only )?speak|i am comfortable (?:speaking|with)|saya (?:boleh )?(?:cakap|berbahasa))\s+', '', value.strip(),flags=re.I)
    value=re.sub(r'\bsinglish(?:\s+malay)?\b',lambda m:'English, Malay' if 'malay' in m[0].lower() else 'English',value,flags=re.I)
    if re.fullmatch(r'[1-5](?:[\s,]+[1-5])*',value):value=re.sub(r'\s+',',',value)
    parts=re.split(r'\s*(?:[|,，、;/&\n]|\band\b|\bdan\b)\s*',value.strip(),flags=re.I)
    result=[]
    for part in parts:
        part=part.strip()
        if not part:continue
        if part.isdecimal():part=LANGUAGES.get(part,'')
        if not part or part.casefold() in {'other','others','5'}:raise ValueError('Please specify which languages, and type all of them. For example: Hindi, Hokkien.')
        canonical=aliases.get(part.casefold())
        if canonical is None:
            if not 2<=len(part)<=40 or len(part.split())>4 or not all(unicodedata.category(ch)[0] in 'LM' or ch in " -'’" for ch in part):raise ValueError('Please type language names separated by commas, for example English, Malay, Hindi.')
            canonical=part.casefold().capitalize()
        if canonical not in result:result.append(canonical)
    if not result or len(result)>12:raise ValueError('Please list between 1 and 12 languages.')
    return '|'.join(result)
def begin(sender,destination='profile'):
    saved=get(sender);c=get_connection()
    try:
        with c:c.execute('INSERT INTO basic_profile_drafts(sender,display_name,chat_languages,destination) VALUES(?,?,?,?) ON CONFLICT(sender) DO UPDATE SET display_name=EXCLUDED.display_name,chat_languages=EXCLUDED.chat_languages,destination=EXCLUDED.destination,updated_at=CURRENT_TIMESTAMP',(sender,saved['display_name'] if saved else None,saved['chat_languages'] if saved else None,destination))
    finally:c.close()
    update_user(sender,state='basic_name');return screen(sender,'basic_name')
def draft(sender):
    c=get_connection()
    try:
        r=c.execute("SELECT * FROM basic_profile_drafts WHERE sender=? AND updated_at>CURRENT_TIMESTAMP-INTERVAL '30 minutes'",(sender,)).fetchone();return dict(r) if r else None
    finally:c.close()
def put(sender,field,value):
    if field not in {'display_name','chat_languages'}:raise ValueError('Invalid field')
    c=get_connection()
    try:
        with c:
            r=c.execute('UPDATE basic_profile_drafts SET '+field+'=?,updated_at=CURRENT_TIMESTAMP WHERE sender=? RETURNING sender',(value,sender)).fetchone()
            if not r:raise ValueError('Your draft expired. Type profile to begin again.')
    finally:c.close()
def show(sender):
    row=get(sender)
    if not row:return begin(sender)
    from database import get_language_preference
    protect(row['display_name'],row['chat_languages'])
    update_user(sender,state='basic_menu')
    return 'My profile 💜\n\nDisplay name: '+row['display_name']+'\nCareConnect language: '+str(get_language_preference(sender) or 'English')+'\nBuddy chat languages: '+row['chat_languages'].replace('|',', ')+"\n\n1. Edit my basic details\n2. My matching preferences\n3. My Support Buddy profile\n4. AI profile and privacy settings\n5. Main menu"
def screen(sender,state):
    row=draft(sender)
    if state=='basic_buddy_apply':
        from buddy_profile import show as show_buddy
        return show_buddy(sender)
    if state=='basic_menu':return show(sender)
    if state=='basic_name':return 'What would you like us to call you? 💜\n\nUse a name or nickname. It will appear to potential Support Buddy connections. Leave out phone numbers and contact details.'
    if state=='basic_languages':return 'Which languages are you comfortable chatting in with another caregiver?\n\n1. English\n2. Mandarin\n3. Malay\n4. Tamil\n5. Other (please specify which languages, and type all of them)\n\nChoose several, such as 1, 3, or type the language names. This is separate from the language CareConnect uses.'
    if state=='basic_other':return 'Please specify which languages, and type all of them.\n\nInclude every language you are comfortable using, for example English, Malay, Hindi. This replaces your current buddy chat language selection.'
    if not row:return 'Your draft expired. Type profile to start again.'
    protect(row['display_name'],row['chat_languages'])
    return 'Review my basic profile 💜\n\nDisplay name: '+str(row['display_name'])+'\nBuddy chat languages: '+str(row['chat_languages']).replace('|',', ')+"\n\nYour profile is linked to this WhatsApp account. Your number is shared only through the separate connection-permission process.\n\n1. Save my basic profile\n2. Edit an answer"
def save(sender):
    c=get_connection()
    try:
        with c:
            r=c.execute("SELECT * FROM basic_profile_drafts WHERE sender=? AND updated_at>CURRENT_TIMESTAMP-INTERVAL '30 minutes' FOR UPDATE",(sender,)).fetchone()
            if not r:raise ValueError('Your draft expired. Type profile to start again.')
            name=validate_name(r['display_name'] or '');languages=language_set(r['chat_languages'] or '')
            # Lock published application first, matching existing buddy-edit lock order.
            c.execute('SELECT id FROM support_buddy_applications WHERE sender=? FOR UPDATE',(sender,)).fetchone()
            c.execute('INSERT INTO basic_profiles(sender,display_name,chat_languages) VALUES(?,?,?) ON CONFLICT(sender) DO UPDATE SET display_name=EXCLUDED.display_name,chat_languages=EXCLUDED.chat_languages,updated_at=CURRENT_TIMESTAMP',(sender,name,languages))
            c.execute('UPDATE support_buddy_applications SET display_name=?,languages=? WHERE sender=?',(name,languages,sender))
            c.execute('UPDATE support_buddy_drafts SET display_name=?,languages=? WHERE sender=?',(name,languages,sender))
            c.execute('DELETE FROM buddy_list_sessions WHERE sender=?',(sender,))
            c.execute('DELETE FROM basic_profile_drafts WHERE sender=?',(sender,))
            return r['destination']
    finally:c.close()
def preferences(sender):
    if not get(sender):return begin(sender,'matches')
    user=get_user(sender);update_user(sender,state='basic_preferences')
    return 'Find a Support Buddy 💜\n\nLanguages: '+get(sender)['chat_languages'].replace('|',', ')+'\nLooking for: '+(user.get('support_type') or 'Not set')+'\nUsual availability: '+(user.get('availability') or 'Not set')+'\n\n1. Show potential buddies\n2. Change my preferences'
def start_registration(sender):
    from handlers import begin_registration
    return begin_registration(sender)
def handle(sender,text,state):
    if not enabled():return None
    command=text.strip().casefold().rstrip(' .,!。！')
    if command in {'profile','my profile'}:return show(sender)
    if command=='back' and state.startswith('basic_'):
        previous={'basic_languages':'basic_name','basic_other':'basic_languages','basic_review':'basic_languages','basic_name':'basic_menu','basic_support':'basic_preferences','basic_time':'basic_support','basic_preferences':'basic_menu'}.get(state,'basic_menu')
        update_user(sender,state=previous);return preferences(sender) if previous=='basic_preferences' else screen(sender,previous)
    if command in {'menu','language','status','my status','resources','ai chat','help','admin login','admin logout','buddy profile'}:return None
    if state=='basic_buddy_apply':
        if command=='1':return start_registration(sender)
        if command=='2':return show(sender)
        return 'Reply 1 to apply or 2 to return to your profile.'
    if state=='basic_menu':
        if command=='1':return begin(sender)
        if command=='2':return preferences(sender)
        if command=='3':
            from buddy_profile import show as buddy_show
            return buddy_show(sender)
        if command=='4':
            from profile_navigation import show_profile
            return show_profile(sender)
        if command=='5':
            update_user(sender,state='main_menu')
            from handlers import show_careconnect_menu
            return show_careconnect_menu(sender)
        return show(sender)
    if state in {'basic_languages','basic_other'}:
        if command=='5' or re.search(r'(?:^|[,\s])5(?:$|[,\s])',command):update_user(sender,state='basic_other');return screen(sender,'basic_other')
        try:value=language_set(text)
        except ValueError as e:return str(e)+'\n\n'+screen(sender,state)
        put(sender,'chat_languages',value);update_user(sender,state='basic_review');return screen(sender,'basic_review')
    if state=='basic_name':
        try:value=validate_name(text)
        except ValueError as e:return str(e)
        put(sender,'display_name',value);update_user(sender,state='basic_languages');return screen(sender,'basic_languages')
    if state=='basic_review':
        if command=='2':update_user(sender,state='basic_name');return screen(sender,'basic_name')
        if command!='1':return 'Please reply 1 to save or 2 to edit. Nothing has been saved.'
        destination=save(sender)
        if destination=='request':
            from connection_requests import begin as begin_request
            return begin_request(sender)
        if destination=='volunteer':return start_registration(sender)
        if destination=='matches':return preferences(sender)
        return 'Basic profile saved. 💜\n\n'+show(sender)
    if state=='basic_preferences':
        if command=='1':
            u=get_user(sender)
            if not u.get('support_type') or not u.get('availability'):update_user(sender,state='basic_support');return support_prompt()
            from buddy_directory import show as show_directory
            return show_directory(sender,fresh=True)
        if command=='2':update_user(sender,state='basic_support');return support_prompt()
        return preferences(sender)
    if state in {'basic_support','basic_time'}:
        choices=SUPPORT if state=='basic_support' else TIMES
        if command not in choices:return support_prompt() if state=='basic_support' else time_prompt()
        update_user(sender,**({'support_type':choices[command],'state':'basic_time'} if state=='basic_support' else {'availability':choices[command],'state':'basic_preferences'}))
        return time_prompt() if state=='basic_support' else preferences(sender)
    return None
def support_prompt():return 'What would help you most? 💜\n\n'+'\n'.join(k+'. '+v for k,v in SUPPORT.items())
def time_prompt():return 'When are you usually available?\n\n'+'\n'.join(k+'. '+v for k,v in TIMES.items())


def assert_shared(connection,requester,buddy):
    rows=connection.execute('SELECT sender,chat_languages FROM basic_profiles WHERE sender IN (?,?) ORDER BY sender FOR SHARE',(requester,buddy)).fetchall()
    values={row['sender']:set(row['chat_languages'].split('|')) for row in rows}
    if not values.get(requester,set()).intersection(values.get(buddy,set())):
        raise PermissionError('No shared confirmed chat language. Please review your profile and buddy choice again.')
