"""AI assists navigation; handlers retain all validation, consent and ownership checks."""
import re
import unicodedata
from conversation_context import current,protect
import conversation_ai as ai
from conversation_script import response_style

OPTIONS={
 'main_menu':{'1':'Find a Support Buddy','2':'Talk to CareConnect AI','3':'Explore resources','4':'Become a Support Buddy','5':'Contact RDSS','6':'My profile and privacy','7':'Request/application status','8':'Change language'},
 'profile_menu':{'1':'Review profile suggestions','2':'Read permission / enable suggestions','3':'Withdraw permission and delete profile','4':'Main menu','5':'Continue AI Chat'},
 'profiling_consent':{'1':'Yes, enable suggestions and administrator reporting','2':'No, decline permission'},
 'profile_review':{'1':'Accept suggestion','2':'Edit suggestion','3':'Reject suggestion'},
 'profile_review_confirm':{'1':'Confirm and save exact edit','2':'Cancel edit'},
 'profile_withdraw_confirm':{'1':'Withdraw permission and delete profile','2':'Cancel withdrawal and keep profile'},
 'status_menu':{'1':'My outgoing buddy request status','2':'My Support Buddy application status','3':'Main menu','4':'Incoming buddy requests'},
 'resources_menu':{'1':'RDSS support','2':'Caregiver support','3':'Financial and social support','4':'Urgent support'},
 'resources_detail':{'1':'RDSS support','2':'Caregiver support','3':'Financial and social support','4':'Urgent support'},
 'buddy_unavailable':{'1':'Find another buddy','2':'Talk to CareConnect AI','3':'Main menu'},
 'ai_onboarding_confirm':{'1':'Yes, search using these preferences','2':'Start again / change preferences'},
 'match_alternatives':{'1':'Same support preference, different usual time','2':'Same usual time, different support preference','3':'Change my preferences','4':'Talk to CareConnect AI'},
 'confirm_match':{'1':'Yes, send connection request','2':'No, do not send request'},
 'buddy_registration_review':{'1':'Continue to consent','2':'Edit an answer','3':'Cancel application'},
 'buddy_registration_consent':{'1':'I agree, submit application','2':'Back to review without submitting','3':'Cancel application'},
 'buddy_registration_cancel':{'1':'Yes, cancel and delete draft','2':'Keep draft'},
}
SENSITIVE={'profiling_consent','profile_review','profile_review_confirm','profile_withdraw_confirm',
           'buddy_registration_consent','buddy_registration_cancel','confirm_match'}
SHORT={'yes','no','ok','okay','yup','yeah','thanks','thank you','hi','hello','hey','ya','tak','boleh','சரி','ஆம்','是','好','好的'}
EXPLICIT_CHOICES={
 'profile_review':{'accept suggestion':'1','terima cadangan':'1','接受建议':'1',
                   'edit suggestion':'2','edit cadangan':'2','编辑建议':'2',
                   'reject suggestion':'3','tolak cadangan':'3','拒绝建议':'3'},
 'profile_review_confirm':{'confirm and save':'1','save this exact wording':'1','sahkan dan simpan':'1','确认保存':'1','cancel edit':'2','batal edit':'2','取消编辑':'2'},
 'profile_withdraw_confirm':{'withdraw permission and delete my profile':'1','tarik balik kebenaran dan padam profil saya':'1','撤回同意并删除我的资料':'1',
                           'cancel withdrawal':'2','keep my profile':'2','batal':'2','取消':'2'},
 'buddy_registration_consent':{'i agree':'1','saya setuju':'1','我同意':'1','நான் ஒப்புக்கொள்கிறேன்':'1'},
}
COMMANDS={'menu','profile','my profile','my status','status','application status','application_status',
          'requests','review profile','withdraw profile consent','back','cancel','hi','hello','hey','start'}
DIRECT_DESTINATIONS={'resources':'3','resource hub':'3','ai chat':'2','find a buddy':'1',
                     'become a buddy':'4','contact rdss':'5'}

def private_field(state):
    return state in {'profile_review_edit','buddy_registration_name','buddy_registration_display_name',
        'buddy_registration_introduction','buddy_registration_edit_name','buddy_registration_edit_display_name',
        'buddy_registration_edit_introduction'}

def private_navigation(command):
    """Recognise clear UI questions locally, without sending private form values to AI."""
    text=command.strip(' .?!。？！')
    if re.fullmatch(r'(?:how (?:do|can) i|how to|can you|could you)(?: please)? (?:go to|get to|open|access|show)(?: me)?(?: the)? (?:resources|resource hub)',text):return 'resources','English'
    if re.fullmatch(r'(?:macam mana nak|boleh|nak) (?:pergi|buka|tengok)(?: ke)? (?:resources|resource hub|sumber|pusat sumber)',text):return 'resources','Malay'
    if (re.fullmatch(r'(?:怎么|怎麼|如何)(?:去|进入|進入|打开|打開|查看)(?:资源|資源)(?:中心|页面|頁面)?(?:呢|啊|呀|啦|咯)?',text)
        or re.fullmatch(r'(?:资源|資源)(?:中心)?(?:在哪里|在哪裡|在哪)(?:呢|啊|呀)?',text)):
        return 'resources','Traditional Chinese' if '資' in text else 'Simplified Chinese'
    if text=='வளங்கள் பக்கத்துக்கு எப்படி போவது':return 'resources','Tamil'
    return None

def options_for(state):
    from handlers import REGISTRATION_OPTIONS,REGISTRATION_FIELDS
    if state.startswith('contact_share_'):return {'1':'I agree to share my WhatsApp number with this accepted match','2':'Not now; do not share my number'}
    if state=='status_menu':
        from match_chat_store import enabled
        return OPTIONS[state]|({'5':'Accepted connections / match chat'} if enabled() else {})
    if state=='buddy_registration_edit':return {str(i):label for i,(_,_,label) in enumerate(REGISTRATION_FIELDS,1)}|{'0':'Back to review'}
    step=state.removeprefix('buddy_registration_edit_') if state.startswith('buddy_registration_edit_') else state.removeprefix('buddy_registration_')
    return OPTIONS.get(state,REGISTRATION_OPTIONS.get(step,{}))

def current_screen(sender,state):
    import handlers as h
    import profile_navigation as p
    from database import get_support_buddy_draft
    if state.startswith(('contact_share_','contact_chat_')):
        from match_chat import screen
        return screen(sender,int(state.rsplit('_',1)[1]),offer=False)
    if state=='main_menu':return h.show_careconnect_menu(sender)
    if state=='language_selection':return h.LANGUAGE_SELECTION_MESSAGE
    if state=='profile_menu':return p.show_profile(sender)
    if state=='profiling_consent':return h.PROFILING_CONSENT_PROMPT
    if state in {'profile_review','profile_review_confirm'}:
        pending=p.profiles.get_pending_profile_suggestion(sender)
        if pending:
            if state=='profile_review_confirm':
                value=p.profiles.get_pending_profile_edit(sender,pending['id'])
                if value:return p.edited_message(sender,value)
            return p.suggestion_message(sender,pending)
        return "No pending suggestion is available. Type 'profile' to review your profile."
    if state=='profile_review_edit':return "Please type your corrected profile information. It will only be saved after you confirm the exact wording. Leave out names and contact details. Type 'profile' to leave this edit, or 'menu' for the main menu."
    if state=='profile_withdraw_confirm':return "Withdraw profile permission? This deletes saved profile information, suggestions and unfinished edits. AI chat history remains.\n\n1. Yes, withdraw permission and delete my profile\n2. Cancel and keep my profile\n\nType 'menu' for the main menu."
    if state=='status_menu':return h.show_status_menu(sender)
    if state=='confirm_match':return h.current_match_choice(sender)
    if state=='match_alternatives':return h.show_match_alternatives(sender)
    if state=='ai_onboarding_confirm':
        user=h.get_user(sender)
        return ('Here are your current matching preferences:\nSupport: '+str(user.get('support_type') or 'Not yet specified')
                +'\nPreferred time: '+str(user.get('availability') or 'Not yet specified')
                +"\n\n1. Yes, search using these preferences\n2. Start again / change preferences\n\nType 'menu' for the main menu.")
    if state in {'resources_menu','resources_detail'}:return h.get_resources_menu()
    if state=='buddy_registration_review':return h.registration_review(sender)
    if state=='buddy_registration_consent':return h.CONSENT_TEXT+'\n\n1. I agree - submit my application\n2. Back to review (do not submit)\n3. Cancel application'
    if state.startswith('buddy_registration_'):
        step=state.removeprefix('buddy_registration_edit_') if state.startswith('buddy_registration_edit_') else state.removeprefix('buddy_registration_')
        if step in h.REGISTRATION_QUESTIONS:return h.registration_prompt(step)
    options=options_for(state)
    if options:return '\n'.join(key+'. '+value for key,value in options.items())+"\n\nType 'menu' for the main menu."
    if state=='ai_chat':return "You can keep chatting with CareConnect AI here. Type 'resources' for the Resource Hub, 'profile' for your profile, or 'menu' for the main menu."
    if state=='ai_onboarding':
        user=h.get_user(sender)
        return 'Tell me '+('when you would be comfortable chatting.' if user.get('support_type') else 'what kind of support you would like from another caregiver.')+"\n\nType 'menu' for the main menu."
    return "Your current progress is unchanged. Type 'my status' to check a request/application, or 'menu' for the main menu."

def go_back(sender,state):
    import handlers as h
    if state.startswith(('contact_share_','contact_chat_')):
        from match_chat import list_connections
        h.update_user(sender,state='main_menu');return list_connections(sender)
    if state=='language_selection':
        previous=ai.take_resume_state(sender) or 'main_menu'
        if previous.startswith('admin_'):previous='main_menu'
        h.update_user(sender,state=previous)
        return current_screen(sender,previous)
    if state in {'profile_review_edit','profile_review_confirm'}:
        h.update_user(sender,state='profile_review')
        return current_screen(sender,'profile_review')
    if state.startswith('profile_') or state=='profiling_consent':
        if state=='profile_menu':
            h.update_user(sender,state='main_menu');return h.show_careconnect_menu(sender)
        return current_screen(sender,'profile_menu')
    if state.startswith('buddy_registration_'):
        if state in {'buddy_registration_consent','buddy_registration_edit'} or state.startswith('buddy_registration_edit_'):
            return h.registration_destination(sender,'review')
        draft=h.get_support_buddy_draft(sender)
        if not draft:
            h.update_user(sender,state='main_menu');return h.show_careconnect_menu(sender)
        if state in {'buddy_registration_cancel','buddy_registration_draft_saved'}:
            return h.registration_destination(sender,h.next_registration_step(draft))
        steps=[item[0] for item in h.REGISTRATION_FIELDS]
        step=state.removeprefix('buddy_registration_')
        if step=='review':return h.registration_destination(sender,steps[-1])
        if step in steps and steps.index(step)>0:return h.registration_destination(sender,steps[steps.index(step)-1])
        h.update_user(sender,state='main_menu');return h.show_careconnect_menu(sender)
    if state=='resources_detail':
        h.update_user(sender,state='resources_menu');return h.get_resources_menu()
    if state=='confirm_match':return h.show_match_alternatives(sender)
    if state=='match_alternatives':
        h.update_user(sender,state='ai_onboarding_confirm');return current_screen(sender,'ai_onboarding_confirm')
    if state in {'ai_onboarding_confirm'}:
        previous='ai_onboarding' if state=='ai_onboarding_confirm' else 'ai_onboarding_confirm'
        h.update_user(sender,state=previous);return current_screen(sender,previous)
    h.update_user(sender,state='main_menu');return h.show_careconnect_menu(sender)

def prepare(sender,text,user):
    """Return (handler input, optional fixed reply). No inferred privileged actions."""
    import handlers as h
    state=user['state'];command=text.strip().casefold();context=current.get()
    if state.startswith('admin_') or command=='admin login':
        # Never send PINs, admin notes, private application records or report inputs to AI.
        if context:context.update(language='English',style='standard')
        if command=='back':return ('menu' if state in {'admin_pin','admin_menu','admin_report_period'} else 'back'),None
        if state=='admin_menu':
            command={'reports':'4','statistics':'4','download report':'4','applications':'1','summary':'2','logout':'3'}.get(command,command)
            return command,None
        return text,None
    from admin_assist import notification_alias
    alias=notification_alias(command)
    if alias:return alias,None
    if command in {'notifications','notifications on','notifications off','stop notifications','stop alerts','unsubscribe','stop'}:return text,None
    if state in {'confirm_match','match_alternatives'} and command.strip(' .?!') in {'anyone else','someone else','another buddy','another match','next buddy','next match','show me someone else','show another buddy','orang lain','ada orang lain','换一个','換一個','还有别人吗','還有別人嗎'}:
        return 'next buddy',None
    if not private_field(state):
        normalized=unicodedata.normalize('NFKC',text).strip().replace('،',',').replace('、',',')
        if re.fullmatch(r'[\d,\s.。]+',normalized):
            text=''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in normalized)
            text=re.sub(r'^(\d+)[.。]$',r'\1',text);command=text.casefold()
    free=private_field(state) or state.startswith('buddy_registration_')
    explicit=ai.explicit_language(text,free_text=free)
    if explicit and state!='language_selection':
        h.set_language_preference(sender,explicit)
        style='singlish' if command=='singlish' else 'casual-mixed' if 'singlish malay' in command else 'standard'
        hint=text if any(term in command for term in ('pinyin','romanised','romanized','english letters','latin letters','chinese characters','汉字','漢字')) else ''
        style=response_style(explicit,style,hint)
        ai.save_style(sender,style)
        context.update(language=explicit,style=style)
        return text,'Language updated. Your current progress is unchanged.\n\n'+current_screen(sender,state)
    if command=='language' and state!='language_selection':
        ai.resume_language_screen(sender,state)
        return text,None
    if command=='back':return text,go_back(sender,state)
    if command=='help':return text,current_screen(sender,state)
    if command=='my chats' or re.fullmatch(r'(?:chat|stop chat) \d{1,10}',command):return text,None
    if state.startswith('contact_share_') and command=='i agree to share my whatsapp number with this match':return text,None
    if command in DIRECT_DESTINATIONS:
        if command=='ai chat' and state=='ai_chat':return text,current_screen(sender,state)
        h.update_user(sender,state='main_menu')
        return DIRECT_DESTINATIONS[command],None
    # Numbers/known commands never depend on an AI request succeeding.
    if state=='language_selection' or command in COMMANDS or re.fullmatch(r'[\d,\s]+',command) or re.fullmatch(r'(?:requests|request|accept|decline) \d+',command):return text,None
    if private_field(state):
        destination=private_navigation(command)
        if destination:
            key,language=destination
            h.set_language_preference(sender,language);ai.save_style(sender,'standard')
            context.update(language=language,style='standard')
            h.update_user(sender,state='main_menu')
            return DIRECT_DESTINATIONS[key],None
        if command.strip(' .?!。？！') in {'这是什么意思','這是什麼意思','什么意思','什麼意思','apa maksud ni','apa maksud ini','boleh explain','இதற்கு என்ன அர்த்தம்'}:
            return text,current_screen(sender,state)
        if re.match(r'^(?:how (?:do|can|to)|where (?:do|can|is)|can you|could you|what does)\b',command):
            return text,("Your answer has not been saved. You can type 'resources' to open the Resource Hub, "
                         "'profile' for your profile, 'back' for the previous screen or 'menu' for the main menu.\n\n"+current_screen(sender,state))
        return text,None
    if command in EXPLICIT_CHOICES.get(state,{}):
        choice=EXPLICIT_CHOICES[state][command]
        if state in SENSITIVE and choice=='1':
            return text,"I need you to confirm using the number shown so your agreement is explicit. AI cannot make this decision for you. Nothing has been confirmed yet.\n\n"+current_screen(sender,state)
        return choice,None
    # Literal confirmations are safe only in the screen that actually asks them.
    if state in SENSITIVE and command in {'yes','no','ya','tidak','ஆம்','இல்லை','是','否'}:
        if state=='profile_review' and command not in {'yes','ya','ஆம்','是'}:return text,None
        if command in {'yes','ya','ஆம்','是'}:
            return text,"I need you to confirm using the number shown so your agreement is explicit. Nothing has been confirmed yet.\n\n"+current_screen(sender,state)
        return '2',None
    if command in SHORT:return text,None
    options=options_for(state)
    # Main-menu intent is interpreted by its established classifier; use this call for language only.
    result=ai.classify(text,state,options,allow_choices=bool(options))
    if result is None:return text,None
    registration_language=state in {'buddy_registration_languages','buddy_registration_edit_languages'}
    if result['language'] and not registration_language:
        hint=text
        if result['explicit_language_switch'] and not any(term in command for term in ('pinyin','romanised','romanized','english letters','latin letters','chinese characters','汉字','漢字')):hint=''
        style=response_style(result['language'],result['style'],hint)
        h.set_language_preference(sender,result['language']);ai.save_style(sender,style)
        context.update(language=result['language'],style=style)
    if result['explicit_language_switch'] and not registration_language and result['language']:
        return text,'Language updated. Your current progress is unchanged.\n\n'+current_screen(sender,state)
    if result['action']=='urgent' and result['route_confident']:
        # Fixed verified-behaviour message only: no invented helplines, promises or dispatch.
        return text,h.get_resource_reply('4')
    if result['action']=='match_chat' and result['route_confident']:
        if state.startswith('contact_chat_'):return 'chat '+state.rsplit('_',1)[1],None
        return 'my chats',None
    if state=='main_menu':
        destinations={'find_buddy':'1','ai_chat':'2','resources':'3','volunteer':'4','contact':'5',
                      'profile':'6','my status':'7','status':'7','application status':'7','language':'8'}
        if result['action']=='help':return text,current_screen(sender,state)
        label=destinations.get(result['action'])
        if result['action']=='local' and len(result['choices'])==1:label=result['choices'][0]
        if context:context['main_intent']=(label or ('CLARIFY' if result['action']=='clarify' else 'UNKNOWN')) if result['route_confident'] else 'UNKNOWN'
        return text,None
    if not result['route_confident']:return text,None
    action=result['action'];choices=result['choices']
    if action=='help':return text,'Here is what you can do on this screen. No changes have been made.\n\n'+current_screen(sender,state)
    if action=='next_match' and state in {'confirm_match','match_alternatives'}:return 'next buddy',None
    if action=='back':
        return text,go_back(sender,state)
    if action=='cancel':
        # Cancellation of a destructive action means keep data; never delete on inference.
        if state in {'profile_withdraw_confirm','profile_review_confirm','buddy_registration_cancel'}:return '2',None
        if state.startswith('buddy_registration_'):return 'cancel',None
        return text,'No new action was confirmed.\n\n'+current_screen(sender,state)
    if action=='local' and choices:
        from handlers import MULTI_SELECT_FIELDS
        step=state.removeprefix('buddy_registration_edit_') if state.startswith('buddy_registration_edit_') else state.removeprefix('buddy_registration_')
        if len(choices)>1 and step not in MULTI_SELECT_FIELDS:return text,None
        if state in SENSITIVE or state.startswith('contact_share_'):
            # Edit/back/keep/do-not-send choices do not approve or delete anything.
            if choices==['2'] and state!='profiling_consent':return '2',None
            if state=='buddy_registration_consent' and choices==['3']:return '3',None
            return text,'To make sure this is your choice, please confirm using the number shown. This action needs your explicit agreement; AI cannot make that decision for you.\n\n'+current_screen(sender,state)
        return ','.join(dict.fromkeys(choices)),None
    if action in {'menu','profile','my status','status','application status','requests','language'}:
        if action=='language':ai.resume_language_screen(sender,state)
        return action,None
    destinations={'find_buddy':'1','ai_chat':'2','resources':'3','volunteer':'4','contact':'5'}
    if action in destinations:
        if action=='ai_chat' and state=='ai_chat':return text,None
        if action=='find_buddy' and state in {'ai_onboarding','ai_onboarding_confirm'}:return text,None
        h.update_user(sender,state='main_menu')
        return destinations[action],None
    if action=='clarify':return text,"Would you like to keep going here, talk to CareConnect AI, or find another caregiver? You can tell me in your own words. Type 'menu' for all options."
    return text,None
