"""Keep secondary commands together; leave primary choices and private values alone."""
import re
from conversation_context import current

def organize(sender,reply,state):
    if not isinstance(reply,str):return reply
    context=current.get();protected=set(context['protected']) if context else set()
    if context:context['fixed_localized']=False
    if state.startswith('admin_note_') or state=='profile_review_edit':
        # User wording can contain navigation-looking lines: never rewrite it.
        pass
    lines=[]
    for line in reply.splitlines():
        if any(value and value in line for value in protected):lines.append(line);continue
        if line.startswith('You can type these other commands too:'):break
        # Only remove standalone navigation instructions, never prose/consent text.
        if re.match(r"^Type ['‘](?:menu|back|profile|resources|my status|status|application status|requests|admin logout|report status|my chats)['’]",line) and len(line)<350:continue
        lines.append(line)
    if state=='language_selection':commands=[('menu','Show language choices'),('back','Return to the previous screen')]
    elif state.startswith('admin_'):
        commands=[('menu','Admin menu'),('report status','Check your report'),('admin logout','Sign out')]
        if state=='admin_pin':commands=[('menu','Cancel login')]
        elif state=='admin_menu':commands+=[('notifications on','Receive new application alerts'),('notifications off','Stop alerts')]
    else:
        commands=[('menu','Main menu'),('status','Check your connection request')]
        if state.startswith(('profile_','profiling_')):commands.insert(0,('back','Previous profile screen'))
        elif state.startswith('buddy_registration_'):commands.insert(0,('back','Previous application step'))
        elif state.startswith('resources_'):commands.insert(0,('back','Resource categories' if state=='resources_detail' else 'Main menu'))
        elif state.startswith(('contact_share_','contact_chat_')):commands.insert(0,('my chats','Your accepted connections'))
        elif state=='ai_chat':commands.insert(0,('resources','Resource Hub'));commands.insert(1,('profile','Profile and privacy settings'))
        if state=='main_menu':commands+=[('notifications','Manage WhatsApp update alerts')]
    return '\n'.join(lines).rstrip()+"\n\nYou can type these other commands too:\n"+'\n'.join("'"+key+"' — "+label for key,label in commands)
