"""Fixed operational alerts: no names, contact links or private applicant details."""
MESSAGES={
 'application_submitted':"A new Support Buddy application is waiting for review 💜\nType 'admin login' to sign in, then 'applications' to review it.",
 'application_approved':"You're approved as a Support Buddy! 💜\nThank you for offering your time and a listening ear. You can now be considered for caregiver connections. This doesn't guarantee an immediate match.\nType 'application status' to view your application.",
 'application_rejected':"An update on your Support Buddy application 💜\nYour application wasn't approved this time. Thank you for taking the time to apply. You can contact RDSS if you'd like to discuss the outcome.\nType 'application status' to view your application, or 'contact rdss' for contact information.",
 'application_verified':"One step closer 💜\nYour Support Buddy verification is complete. Your application is still awaiting a decision.\nType 'application status' to check it.",
 'connection_request':"Type 'requests' to view and respond to your new connection request.\n\nPsst, you've got a connection request! 💜\nA caregiver would like to connect with you. Take a look whenever you're ready—there's no pressure to accept.",
 'connection_accepted':"Good news—your connection request was accepted! 💜\nYou can take the next step at your own pace. You will both need to agree before your WhatsApp numbers are shared.\nType 'my chats' to view your connection.",
 'connection_declined':"An update on your connection request 💜\nThis buddy isn't able to connect this time. It doesn't mean there isn't someone else you could connect with.\nType 'find a buddy' to explore another connection.",
 'chat_ready':"Your connection is ready for a chat 💜\nYou've both agreed to share your WhatsApp numbers. You decide when to say hello.\nType 'my chats' to get your chat button."
}

def render(event,language='English',request_id=None,ready=False):
    # The worker applies the established presentation language without exposing records.
    body=MESSAGES[event]
    if event in {'connection_accepted','chat_ready'} and isinstance(request_id,int):
        if ready:
            body="Good news—your connection is ready for WhatsApp! 💜\nYou've both agreed to share your numbers for this connection. Tap the chat button to open a separate private conversation. You choose when to send the first message. CareConnect cannot read that chat.\nType 'chat "+str(request_id)+"' if you need the button again."
        else:
            body="Good news—your connection request was accepted! 💜\nWould you like to continue on WhatsApp? Read the number-sharing notice and choose whether to agree. Your number is not released until both permissions are in place.\nType 'chat "+str(request_id)+"' to review this connection's sharing permission."
    return body+"\n\nYou can type these other commands too:\n'menu' — Main menu\n'notifications off' — Stop these alerts"
