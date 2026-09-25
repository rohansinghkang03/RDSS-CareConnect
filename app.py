from flask import Flask, request

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

VERIFY_TOKEN = "rdss-careconnect-verify"

create_tables()


def find_matches(user):
    caregivers = get_caregivers()

    results = []

    for caregiver in caregivers:
        score = 0

        if caregiver["mood"] == user["mood"]:
            score += 1

        if caregiver["support_type"] == user["support_type"]:
            score += 1

        if (
            caregiver["availability"] == user["availability"]
            or caregiver["availability"] == "Flexible"
            or user["availability"] == "Flexible"
        ):
            score += 1

        percentage = round((score / 3) * 100)

        results.append({
            "name": caregiver["name"],
            "score": score,
            "percentage": percentage
        })

    results.sort(
        key=lambda person: person["score"],
        reverse=True
    )

    return results


def handle_message(sender, text):
    user = get_user(sender)

    if user is None:
        create_user(sender)
        user = get_user(sender)

    state = user["state"]

    if text == "status":
        latest_request = get_latest_match_request(sender)

        if latest_request is None:
            return """
You do not have any match requests yet.

Type 'menu' to return to the main menu.
"""

        if latest_request["status"] == "pending":
            return f"""
Your connection request to {latest_request["caregiver_name"]} is still pending.

Match: {latest_request["match_percentage"]}%

Type 'menu' to return to the main menu.
"""

        elif latest_request["status"] == "accepted":
            update_user(
                sender,
                state="matched"
            )

            return f"""
Great news!

{latest_request["caregiver_name"]} accepted your connection request.

Match: {latest_request["match_percentage"]}%
Status: Accepted

You are now matched.

Type 'menu' to return to the main menu.
"""

        elif latest_request["status"] == "declined":
            reset_user(sender)

            return f"""
{latest_request["caregiver_name"]} was unable to accept your connection request.

Status: Declined

You can search for another buddy.

Type 'menu' to return to the main menu.
"""

    if text in ["hi", "hello", "hey", "start", "menu"]:
        reset_user(sender)

        return """
Welcome to RDSS CareConnect

1. Find a Buddy
2. Talk to CareConnect AI
3. Resources
4. Contact RDSS

You can also type 'status' to check a match request.
"""

    if state == "main_menu":
        if text == "1":
            update_user(
                sender,
                state="buddy_mood"
            )

            return """
Let's find you a suitable support buddy.

How are you feeling today?

1. Okay
2. Stressed
3. Lonely
4. Burnt out
"""

        elif text == "2":
            return "CareConnect AI will be added soon."

        elif text == "3":
            return "RDSS resources will be added here."

        elif text == "4":
            return "RDSS contact information will be added here."

        return "Please type 1, 2, 3 or 4. Type 'menu' to restart."

    elif state == "buddy_mood":
        moods = {
            "1": "Okay",
            "2": "Stressed",
            "3": "Lonely",
            "4": "Burnt out"
        }

        if text in moods:
            update_user(
                sender,
                state="buddy_support",
                mood=moods[text]
            )

            return """
What kind of support are you looking for?

1. Someone to listen
2. Advice from another caregiver
3. Casual conversation
4. Someone with similar experiences
"""

        return "Please choose 1, 2, 3 or 4."

    elif state == "buddy_support":
        support_types = {
            "1": "Someone to listen",
            "2": "Advice from another caregiver",
            "3": "Casual conversation",
            "4": "Someone with similar experiences"
        }

        if text in support_types:
            update_user(
                sender,
                state="buddy_availability",
                support_type=support_types[text]
            )

            return """
When would you usually prefer to chat?

1. Morning
2. Afternoon
3. Evening
4. Flexible
"""

        return "Please choose 1, 2, 3 or 4."

    elif state == "buddy_availability":
        availability = {
            "1": "Morning",
            "2": "Afternoon",
            "3": "Evening",
            "4": "Flexible"
        }

        if text in availability:
            update_user(
                sender,
                availability=availability[text]
            )

            user = get_user(sender)
            matches = find_matches(user)

            if len(matches) == 0:
                reset_user(sender)

                return """
No caregivers are currently available.

Type 'menu' to return to the main menu.
"""

            best_match = matches[0]

            update_user(
                sender,
                state="confirm_match"
            )

            return f"""
Best match found:

{best_match["name"]} - {best_match["percentage"]}% match

Would you like to send a connection request?

1. Yes
2. No
"""

        return "Please choose 1, 2, 3 or 4."

    elif state == "confirm_match":
        user = get_user(sender)
        matches = find_matches(user)

        if len(matches) == 0:
            reset_user(sender)

            return "No matches are currently available. Type 'menu' to restart."

        best_match = matches[0]

        if text == "1":
            create_match_request(
                requester=sender,
                caregiver_name=best_match["name"],
                match_percentage=best_match["percentage"]
            )

            update_user(
                sender,
                state="match_pending"
            )

            return f"""
Connection request sent to {best_match["name"]}.

Status: Pending

Type 'status' to check whether they have responded.

Type 'menu' to return to the main menu.
"""

        elif text == "2":
            reset_user(sender)

            return """
No problem. The match request was cancelled.

Type 'menu' to return to the main menu.
"""

        return "Please type 1 for Yes or 2 for No."

    elif state == "match_pending":
        return """
Your connection request is still pending.

Type 'status' to check for an update.

Type 'menu' to return to the main menu.
"""

    elif state == "matched":
        latest_request = get_latest_match_request(sender)

        if latest_request is not None:
            return f"""
You are currently matched with {latest_request["caregiver_name"]}.

Type 'menu' to return to the main menu.
"""

        return "You are currently matched."

    return "Type 'menu' to return to the main menu."


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