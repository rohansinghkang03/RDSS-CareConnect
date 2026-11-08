"""Private URL delivery after mutual-consent checks; never resend ambiguous outcomes."""
import logging
import whatsapp
import match_chat_store as store

log=logging.getLogger(__name__)

def _record(identifier,outcome,provider_id=None):
    try:store.record_delivery(identifier,outcome,provider_id)
    except Exception:log.warning('Direct-chat delivery audit unavailable; no private details logged')

def _blocked(sender):
    return whatsapp.send_message(sender,"This chat link is no longer available. No new number has been shared.\n\nYou can type these other commands too:\n'my chats' — Your connections\n'menu' — Main menu")

def send(sender,reply):
    from match_chat import ChatReply
    if not isinstance(reply,ChatReply):return whatsapp.send_message(sender,reply)
    body=str(reply)
    if len(body)>1024:
        # The explanatory text contains no contact URL. Recheck after sending it,
        # so withdrawal during this separate network operation prevents release.
        try:status=store.inspect(sender,reply.request_id)
        except (PermissionError,ValueError):return _blocked(sender)
        if status['state']!='ready':return _blocked(sender)
        whatsapp.send_message(sender,body)
        body="Your match chat is ready. Tap the button to open WhatsApp.\n\nYou can type these other commands too:\n'my chats' — Your connections\n'menu' — Main menu"
    try:identifier,url=store.authorize_delivery(sender,reply.request_id)
    except (PermissionError,ValueError):return _blocked(sender)
    try:
        provider=whatsapp.send_chat_url_button(sender,body,reply.label,url)
    except whatsapp.WhatsAppRejected as error:
        _record(identifier,'failed')
        # Only a definitive invalid-button rejection permits a new fallback send.
        if error.http_status!=400 or error.provider_code not in {100,131009}:raise
        try:identifier,url=store.authorize_delivery(sender,reply.request_id)
        except (PermissionError,ValueError):return _blocked(sender)
        try:provider=whatsapp.send_message(sender,body+'\n\nChat link: '+url)
        except whatsapp.WhatsAppRejected:
            _record(identifier,'failed');raise
        except Exception:
            _record(identifier,'unknown');raise
    except Exception:
        _record(identifier,'unknown');raise
    _record(identifier,'accepted',provider)
    return provider
