"""Fixed operational alerts: no names, contact links or private applicant details."""
MESSAGES={
 'application_submitted':"A new Support Buddy application is waiting for review 💜\nType 'admin login' to sign in, then 'applications' to review it.",
 'application_approved':"You're approved as a Support Buddy! 💜\nThank you for offering your time and a listening ear. You can now be considered for caregiver connections. This doesn't guarantee an immediate match.\nType 'application status' to view your application.",
 'application_rejected':"An update on your Support Buddy application 💜\nYour application wasn't approved this time. Thank you for taking the time to apply. You can contact RDSS if you'd like to discuss the outcome.\nType 'application status' to view your application, or 'contact rdss' for contact information.",
 'application_verified':"One step closer 💜\nYour Support Buddy verification is complete. Your application is still awaiting a decision.\nType 'application status' to check it.",
 'connection_request':"Psst, you've got a connection request! 💜\nA caregiver would like to connect with you. Take a look whenever you're ready—there's no pressure to accept.\nType 'requests' to review and respond.",
 'connection_accepted':"Good news—your connection request was accepted! 💜\nYou can take the next step at your own pace. You will both need to agree before your WhatsApp numbers are shared.\nType 'my chats' to view your connection.",
 'connection_declined':"An update on your connection request 💜\nThis buddy isn't able to connect this time. It doesn't mean there isn't someone else you could connect with.\nType 'find a buddy' to explore another connection.",
 'chat_ready':"Your connection is ready for a chat 💜\nYou've both agreed to share your WhatsApp numbers. You decide when to say hello.\nType 'my chats' to get your chat button."
}

def render(event,language='English'):
    # The worker applies the established presentation language without exposing records.
    return MESSAGES[event]+"\n\nYou can type these other commands too:\n'menu' — Main menu\n'notifications off' — Stop these alerts"
