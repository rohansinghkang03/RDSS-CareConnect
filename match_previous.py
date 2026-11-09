"""Return to previously shown eligible suggestions without changing preferences."""
from database import get_user,update_user
from match_browsing import history

def choices(sender):
    from handlers import find_matches
    user=get_user(sender);seen,_=history(sender,user)
    eligible={m['buddy_id']:m for m in find_matches(user)}
    return {str(i+1):eligible[identifier] for i,identifier in enumerate(sorted(seen)) if identifier in eligible}
def show(sender):
    from handlers import caregiver_message
    from conversation_context import protect
    options=choices(sender)
    if not options:return caregiver_message(sender,"There are no earlier eligible suggestions in this search. Your preferences are unchanged. Type 'menu' to return.")
    update_user(sender,state='match_seen')
    lines=['Your previous suggestions 💜','Choose someone to review again. Nothing is sent by opening their details.']
    for number,match in options.items():
        protect(match['name']);lines.append(number+'. '+match['name']+' — '+', '.join(match['offered_support'])+'; '+', '.join(match['offered_times']))
    return caregiver_message(sender,'\n\n'.join(lines))
def handle(sender,text,state):
    if state!='match_seen':return None
    if text.strip().lower() in {'back','menu','profile','status','my status','language','resources','help'}:return None
    from handlers import show_match_choice
    chosen=choices(sender).get(text.strip())
    return show_match_choice(sender,chosen,get_user(sender)) if chosen else show(sender)
