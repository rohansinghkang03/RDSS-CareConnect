"""WhatsApp delivery with bounded waits and private logging."""
import requests
from config import ACCESS_TOKEN, PHONE_NUMBER_ID


def send_message(recipient, message):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise RuntimeError("WhatsApp configuration missing")
    response = requests.post(
        f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "to": recipient,
              "type": "text", "text": {"body": message}},
        timeout=(5, 20),
    )
    if not response.ok:
        # Never include response bodies, URLs, tokens or recipient identifiers.
        raise RuntimeError("WhatsApp delivery failed")
