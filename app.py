import os
from flask import Flask, request

from handlers import handle_message 
from whatsapp import send_message

from database import (
    create_match_request,
    create_tables,
    create_user,
    get_caregivers,
    get_latest_match_request,
    get_pending_requests_for_caregiver,
    get_user,
    reset_user,
    update_match_request_status,
    update_user
)

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

create_tables()

@app.route("/caregiver/<caregiver_name>/requests")
def caregiver_requests(caregiver_name):
    requests = get_pending_requests_for_caregiver(caregiver_name)

    if len(requests) == 0:
        return f"""
Caregiver: {caregiver_name}

No pending requests.
"""

    request_item = requests[0]

    return f"""
Caregiver: {caregiver_name}

Pending request:

From: {request_item["requester"]}
Match: {request_item["match_percentage"]}%

Request ID: {request_item["id"]}

Accept:
http://127.0.0.1:8000/caregiver/{caregiver_name}/accept/{request_item["id"]}

Decline:
http://127.0.0.1:8000/caregiver/{caregiver_name}/decline/{request_item["id"]}
"""


@app.route("/caregiver/<caregiver_name>/accept/<int:request_id>")
def accept_request(caregiver_name, request_id):
    update_match_request_status(
        request_id,
        "accepted"
    )

    return f"""
{caregiver_name} accepted request #{request_id}.

Status: Accepted
"""


@app.route("/caregiver/<caregiver_name>/decline/<int:request_id>")
def decline_request(caregiver_name, request_id):
    update_match_request_status(
        request_id,
        "declined"
    )

    return f"""
{caregiver_name} declined request #{request_id}.

Status: Declined
"""


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return challenge, 200

    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" in value:
            message = value["messages"][0]

            sender = message["from"]
            message_type = message["type"]

            if message_type == "text":
                text = message["text"]["body"].strip().lower()

                reply = handle_message(sender, text)

                send_message(sender, reply)

                print("\n========== NEW MESSAGE ==========")
                print("From:", sender)
                print("Message:", text)
                print("Bot Reply:")
                print(reply)
                print("=================================\n")

    except (KeyError, IndexError, TypeError) as error:
        print("Webhook received, but no readable message found:")
        print(error)

    return "EVENT_RECEIVED", 200


@app.route("/test/<sender>/<message>")
def test_message(sender, message):
    reply = handle_message(sender, message.lower())

    return f"""
User: {sender}

Message:
{message}

-----------------------

Bot Reply:

{reply}
"""


@app.route("/", methods=["GET"])
def home():
    return "RDSS CareConnect is running!", 200


if __name__ == "__main__":
    app.run(port=8000, debug=True)