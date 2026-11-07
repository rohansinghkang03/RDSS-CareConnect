"""User-visible mutual contact permission. No contact number enters AI presentation."""
import logging
import re
import match_chat_store as store
from database import update_user
from conversation_context import current

log=logging.getLogger(__name__)

class ChatReply(str):
    def __new__(cls,text,request_id,label):
        result=super().__new__(cls,text);result.request_id=request_id;result.label=label
        return result

def button_label(language,style='standard'):
    if style=='romanised':return 'Chat with your match'
    label=(language or '').casefold()
    if label in {'malay','english and malay'}:return 'Chat dengan padanan'
    if 'traditional chinese' in label:return '與配對伙伴聊天'
    if any(v in label for v in ('chinese','mandarin')):return '与配对伙伴聊天'
    if 'tamil' in label:return 'அரட்டை'
    return 'Chat with your match'

def screen(sender,request_id,offer=True):
    from handlers import caregiver_message
    if not store.enabled():return caregiver_message(sender,"Direct match chat is not enabled yet. Type 'menu' for the main menu.")
    try:status=store.inspect(sender,request_id,prepare=True)
    except PermissionError:return "That chat connection is unavailable for your account. No contact link has been released. Type 'my chats' or 'menu'."
    from conversation_context import protect
    protect(status.get('partner_label'))
    heading='Connection #'+str(request_id)+' — '+status.get('partner_label','your match')+'\n\n'
    if status['state']=='ready':
        update_user(sender,state='contact_chat_'+str(request_id))
        context=current.get()
        if context and offer:context['chat_request_id']=request_id
        opening=('Tap "Chat with your match" to open a separate WhatsApp chat. ' if offer
                 else "Type 'chat "+str(request_id)+"' to get the button for your separate WhatsApp chat. ")
        return caregiver_message(sender,
            heading+'Your connection is ready. Both of you have agreed to share your WhatsApp numbers. 💜\n\n'
            +opening+'You choose whether to send the first message. '
            'CareConnect does not receive or read messages in that private chat.\n\n'
            "If you need the button again, type 'chat "+str(request_id)+"'.\n"
            "Type 'stop chat "+str(request_id)+"' to stop future contact-link releases. Links already released cannot be recalled.\n"
            "Type 'my chats' for your connections, or 'menu' for the main menu.")
    if status['state']=='waiting':
        update_user(sender,state='contact_chat_'+str(request_id))
        return caregiver_message(sender,
            heading+'Your contact-sharing permission is recorded. Your match has not yet given current permission. '
            'No contact link can be released until both of you agree.\n\n'
            "Type 'chat "+str(request_id)+"' to check again, 'stop chat "+str(request_id)+"' to withdraw contact permission, "
            "or 'menu' for the main menu.")
    update_user(sender,state='contact_share_'+str(request_id))
    return caregiver_message(sender,
        heading+'Continue with your match on WhatsApp? 💜\n\n'
        'This is a separate permission from your AI caregiver profile. If both of you agree, your WhatsApp number '
        'will be shared with this match, and their number will be shared with you.\n\n'
        'A button opens a separate private chat. CareConnect cannot read or delete those messages. '
        'You send your first message yourself. You can stop future links, but numbers or links already released '
        '(including a send in progress) cannot be recalled. You can block a contact in WhatsApp.\n\n'
        '1. I agree to share my WhatsApp number with this match\n'
        '2. Not now; do not share my number\n\n'
        "Type 'back' for your connections, or 'menu' for the main menu.")

def list_connections(sender):
    from handlers import caregiver_message
    ids=store.accepted_connections(sender)
    if not ids:return caregiver_message(sender,"No accepted, eligible direct-chat connections are available. Type 'status' to check a buddy request, or 'menu' for the main menu.")
    lines=['Your accepted connections 💜','Showing up to 20 recent eligible connections.','']
    lines.extend("Connection #"+str(value)+": type 'chat "+str(value)+"'" for value in ids)
    return caregiver_message(sender,'\n'.join(lines)+"\n\nEach connection needs permission from both people before a chat link is released. Type 'menu' for the main menu.")

def withdraw_contact(sender,request_id):
    try:
        store.decide(sender,request_id,'revoked')
        update_user(sender,state='main_menu')
        return ('Contact-sharing permission withdrawn for this connection. Future link releases are stopped. '
                'Numbers or links already released, including an outgoing send in progress, cannot be recalled. '
                "Use WhatsApp to block a contact if needed. Type 'my chats' for connections or 'menu' for the main menu.")
    except PermissionError:
        return "That connection was not found for your account. Type 'my chats' or 'menu'."
    except Exception:
        log.warning('Contact permission withdrawal unavailable; no private details logged')
        return "Contact permission could not be updated. Please try again. Type 'menu' to return."


def handle(sender,text,state):
    command=text.strip().casefold()
    stop=re.fullmatch(r'stop chat (\d{1,10})',command)
    if stop:return withdraw_contact(sender,int(stop[1]))
    if not store.enabled():
        if command=='my chats' or re.fullmatch(r'(?:chat|stop chat) \d+',command) or state.startswith(('contact_share_','contact_chat_')):
            return "Direct match chat is not enabled yet. Type 'menu' for the main menu."
        return None
    if command in {'menu','profile','my profile','my status','status','application status','language','back','resources','ai chat','help'}:return None
    try:
        if command=='my chats':return list_connections(sender)
        if state=='status_menu' and command=='5':return list_connections(sender)
        match=re.fullmatch(r'(chat|stop chat) (\d{1,10})',command)
        if match:
            request_id=int(match[2])
            return screen(sender,request_id)
        active=re.fullmatch(r'contact_(share|chat)_([1-9][0-9]{0,9})',state)
        if not active:return None
        request_id=int(active[2])
        if active[1]=='share':
            if command in {'1','i agree to share my whatsapp number with this match'}:
                store.decide(sender,request_id,'granted');return screen(sender,request_id)
            if command=='2':
                store.decide(sender,request_id,'declined');update_user(sender,state='main_menu')
                return "Your number has not been shared by this choice. You can continue using CareConnect. Type 'my chats' to revisit accepted connections or 'menu' for the main menu."
            return screen(sender,request_id)
        return screen(sender,request_id,offer=False)
    except PermissionError:
        update_user(sender,state='main_menu')
        return "That chat connection is unavailable for your account. No contact link has been released. Type 'my chats' or 'menu'."
    except Exception:
        log.warning('Direct-chat operation unavailable; no private details logged')
        return "Direct chat is temporarily unavailable. No new contact link has been released. Type 'menu' and try again later."
