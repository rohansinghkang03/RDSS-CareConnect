import hmac
import os

from chatbot import ask_careconnect, extract_matching_preferences, generate_onboarding_reply
from dotenv import load_dotenv

load_dotenv()

ADMIN_PHONE_NUMBER = os.getenv("ADMIN_PHONE_NUMBER", "")
ADMIN_PIN = os.getenv("ADMIN_PIN", "")

from database import (
    create_selected_match_request,
    save_match_preview,
    get_buddy_requests,
    get_buddy_request,
    respond_to_buddy_request,
    cancel_support_buddy_draft,
    get_support_buddy_application,
    get_support_buddy_draft,
    get_admin_application,
    list_admin_applications,
    review_support_buddy_application,
    get_admin_review_events,
    submit_support_buddy_application,
    create_user,
    get_latest_match_request,
    get_user,
    reset_user,
    start_support_buddy_draft,
    update_support_buddy_draft,
    update_user
)

from matching import find_matches

from resources import get_resource_reply, get_resources_menu


# Registration states are separate from the existing Find a Buddy flow.
REGISTRATION_FIELDS = (
    ("name", "full_name", "Full name"),
    ("rdss", "rdss_member", "RDSS member"),
    ("display_name", "display_name", "Display name"),
    ("languages", "languages", "Languages"),
    ("experience", "caregiver_experience", "Caregiving experience"),
    ("support_types", "support_types", "Support offered"),
    ("availability", "availability", "Availability"),
    ("contact_methods", "contact_methods", "Contact preferences"),
    ("introduction", "introduction", "Introduction")
)
REGISTRATION_OPTIONS = {
    "rdss": {"1": "Yes", "2": "No"},
    "languages": {"1": "English", "2": "Mandarin", "3": "Malay", "4": "Tamil", "5": "Other"},
    "experience": {"1": "Less than 1 year", "2": "1-3 years", "3": "3-5 years", "4": "More than 5 years"},
    "support_types": {"1": "Someone to listen", "2": "Advice from another caregiver",
                      "3": "Casual conversation", "4": "Someone with similar experiences"},
    "availability": {"1": "Morning", "2": "Afternoon", "3": "Evening", "4": "Weekends", "5": "Flexible"},
    "contact_methods": {"1": "WhatsApp text", "2": "Voice notes", "3": "Voice calls"}
}
MULTI_SELECT_FIELDS = {"languages", "support_types", "availability", "contact_methods"}
REGISTRATION_QUESTIONS = {
    "name": "What is your full name?\nThis is only for RDSS to review your application.",
    "rdss": "Are you currently part of the RDSS community?\nNon-members may apply with extra verification.",
    "display_name": 'What would you like other caregivers to know you as?\nUse a nickname, or type \'skip\' to use "Support Buddy". Your full name will not be used as your public name.',
    "languages": "Which languages are you comfortable chatting in?",
    "experience": "How long have you been a caregiver?",
    "support_types": "What kinds of support can you offer another caregiver?",
    "availability": "When are you usually available to chat?",
    "contact_methods": "How would you prefer to communicate?",
    "introduction": "Write a short introduction about yourself (up to 500 characters), or type 'skip'.\nThis may be shared with potential matches."
}
CONSENT_TEXT = (
    "I agree that RDSS may contact me about my Support Buddy application and "
    "share my public profile with potential matches: my display name (or 'Support Buddy'), "
    "languages, caregiving experience, support offered, availability, contact preferences "
    "and introduction. My full name and contact details are not part of that public profile."
)


def registration_prompt(step):
    prompt = REGISTRATION_QUESTIONS[step]
    if step in REGISTRATION_OPTIONS:
        prompt += "\n\n" + "\n".join(
            number + ". " + label for number, label in REGISTRATION_OPTIONS[step].items()
        )
    if step in MULTI_SELECT_FIELDS:
        prompt += "\n\nChoose one or more numbers, separated by commas or spaces. Example: 1,2"
    return prompt + "\n\nType 'menu' to pause, or 'cancel' to cancel this draft."


def next_registration_step(draft):
    for step, field, _ in REGISTRATION_FIELDS:
        value = draft.get(field)
        if value is None or (field not in ("display_name", "introduction") and not value):
            return step
    return "review"


def registration_review(sender):
    draft = get_support_buddy_draft(sender)
    if not draft:
        reset_user(sender)
        return "No registration draft found. Type 'menu' and choose 4 to begin."
    lines = ["Review your Support Buddy application", ""]
    for _, field, label in REGISTRATION_FIELDS:
        value = draft.get(field)
        if field == "display_name" and value == "":
            value = "Support Buddy (no display name chosen)"
        elif field == "introduction" and value == "":
            value = "Skipped"
        elif value is None:
            value = "Not answered"
        if field in MULTI_SELECT_FIELDS:
            value = value.replace("|", ", ")
        lines.append(label + ": " + str(value))
    lines += ["", "Full name is only visible to RDSS.",
              "Extra verification: " + ("Required" if draft.get("rdss_member") == "No" else "Not required"),
              "", "1. Continue to consent and submit", "2. Edit an answer", "3. Cancel application"]
    return "\n".join(lines)


def registration_destination(sender, step):
    update_user(sender, state="buddy_registration_" + step)
    return registration_review(sender) if step == "review" else registration_prompt(step)


def application_status_reply(sender):
    application = get_support_buddy_application(sender)
    if application:
        status = application["status"]
        label = {"pending": "Pending RDSS review", "approved": "Approved",
                 "rejected": "Not approved", "declined": "Not approved"}.get(status, status)
        reply = "Support Buddy application\n\nStatus: " + label
        reply += "\nSubmitted: " + application["submitted_at"] + " UTC"
        if application["verification_required"]:
            reply += "\nExtra verification: " + ("Complete" if application.get("verified_at") else "Required for non-RDSS members")
        if get_support_buddy_draft(sender):
            reply += "\nYou also have an unfinished draft. Choose 4 from the menu to resume."
        return reply + "\n\nType 'menu' to return to the main menu."
    if get_support_buddy_draft(sender):
        return "Your Support Buddy application is a draft and has not been submitted.\nType 'menu', then choose 4 to resume."
    return "You have not submitted a Support Buddy application. Type 'menu', then choose 4 to begin."


def begin_registration(sender):
    application = get_support_buddy_application(sender)
    if application and application["status"] not in ("rejected", "declined"):
        return application_status_reply(sender)
    start_support_buddy_draft(sender)
    draft = get_support_buddy_draft(sender)
    return "Become a CareConnect Support Buddy\n\n" + registration_destination(sender, next_registration_step(draft))


def admin_menu_reply():
    return """
Admin menu

1. View pending applications
2. Application summary
3. Log out
"""


def admin_application_list():
    applications, total, counts = list_admin_applications("pending", 1, 25)
    if not applications:
        return "No pending Support Buddy applications.\n\n" + admin_menu_reply()

    lines = ["Pending Support Buddy applications", ""]
    for index, application in enumerate(applications, 1):
        member_label = "RDSS member" if application["rdss_member"] == "Yes" else "Non-member"
        verification = " · verification needed" if application["verification_required"] and not application["verified_at"] else ""
        lines.append(
            f"{index}. {application['full_name']} — {member_label}{verification}"
        )
    lines += ["", "Reply with an application number to open it.", "Type 'menu' to return to the admin menu."]
    return "\n".join(lines)


def admin_application_summary():
    _, _, counts = list_admin_applications("all", 1, 1)
    return (
        "Support Buddy application summary\n\n"
        f"Pending: {counts.get('pending', 0)}\n"
        f"Approved: {counts.get('approved', 0)}\n"
        f"Not approved: {counts.get('rejected', 0)}\n\n"
        + admin_menu_reply()
    )


def admin_application_detail(application_id):
    application = get_admin_application(application_id)
    if application is None:
        return "That application is no longer available.\n\n" + admin_application_list()

    verification = "Not required"
    if application["verification_required"]:
        verification = "Complete" if application["verified_at"] else "Required before approval"
    lines = [
        "Support Buddy application",
        "",
        f"Name: {application['full_name']}",
        f"Display name: {application['display_name'] or 'Support Buddy'}",
        f"RDSS member: {application['rdss_member']}",
        f"Languages: {(application['languages'] or '').replace('|', ', ')}",
        f"Experience: {application['caregiver_experience']}",
        f"Support offered: {(application['support_types'] or '').replace('|', ', ')}",
        f"Availability: {(application['availability'] or '').replace('|', ', ')}",
        f"Contact: {(application['contact_methods'] or '').replace('|', ', ')}",
        f"Introduction: {application['introduction'] or 'Skipped'}",
        f"Verification: {verification}",
        f"Status: {application['status']}",
        "",
        "1. Approve",
        "2. Reject",
        "3. Mark verification complete",
        "4. Add private note",
        "5. Back to applications",
    ]
    if application["admin_notes"]:
        lines.insert(-5, f"Private note: {application['admin_notes']}")
    return "\n".join(lines)


def admin_application_id_for_choice(choice):
    applications, _, _ = list_admin_applications("pending", 1, 25)
    try:
        index = int(choice) - 1
    except ValueError:
        return None
    if index < 0 or index >= len(applications):
        return None
    return applications[index]["id"]


def handle_admin_message(sender, text, state):
    command = text.strip().lower()

    if command == "admin login":
        update_user(sender, state="admin_pin")
        return "Enter your admin PIN."

    if state == "admin_pin":
        if hmac.compare_digest(command, ADMIN_PIN):
            update_user(sender, state="admin_menu")
            return "Admin login successful.\n\n" + admin_menu_reply()
        return "Incorrect PIN. Try again or type 'menu'."

    if state == "admin_menu":
        if command == "1":
            update_user(sender, state="admin_applications")
            return admin_application_list()
        if command == "2":
            return admin_application_summary()
        if command in ("3", "admin logout", "menu"):
            update_user(sender, state="main_menu")
            return "You have been logged out."
        return "Please choose 1, 2 or 3.\n\n" + admin_menu_reply()

    if state == "admin_applications":
        if command in ("menu", "back"):
            update_user(sender, state="admin_menu")
            return admin_menu_reply()
        application_id = admin_application_id_for_choice(command)
        if application_id is None:
            return "Please reply with a listed application number, or type 'menu'.\n\n" + admin_application_list()
        update_user(sender, state=f"admin_review_{application_id}")
        return admin_application_detail(application_id)

    if state.startswith("admin_review_"):
        application_id = int(state.rsplit("_", 1)[1])
        application = get_admin_application(application_id)
        if application is None:
            update_user(sender, state="admin_applications")
            return admin_application_list()
        if command == "5":
            update_user(sender, state="admin_applications")
            return admin_application_list()
        if command == "4":
            update_user(sender, state=f"admin_note_{application_id}")
            return "Type the private admin note to save, or type 'cancel'."
        if command not in ("1", "2", "3"):
            return "Please choose 1, 2, 3, 4 or 5.\n\n" + admin_application_detail(application_id)
        action = {"1": "approve", "2": "reject", "3": "verify"}[command]
        try:
            review_support_buddy_application(
                application_id,
                action,
                application["admin_notes"] or "",
                sender,
                application["review_version"]
            )
        except (LookupError, ValueError) as error:
            return str(error) + "\n\n" + admin_application_detail(application_id)
        update_user(sender, state="admin_applications")
        label = {"approve": "approved", "reject": "rejected", "verify": "marked verified"}[action]
        return f"Application {label}.\n\n" + admin_application_list()

    if state.startswith("admin_note_"):
        application_id = int(state.rsplit("_", 1)[1])
        if command == "cancel":
            update_user(sender, state=f"admin_review_{application_id}")
            return admin_application_detail(application_id)
        application = get_admin_application(application_id)
        if application is None:
            update_user(sender, state="admin_applications")
            return admin_application_list()
        try:
            review_support_buddy_application(
                application_id,
                "notes",
                text.strip(),
                sender,
                application["review_version"]
            )
        except (LookupError, ValueError) as error:
            return str(error) + "\n\nType another note or 'cancel'."
        update_user(sender, state=f"admin_review_{application_id}")
        return "Private note saved.\n\n" + admin_application_detail(application_id)

    return None


def handle_registration(sender, text, state):
    answer = text.strip()
    command = answer.lower()
    if state == "buddy_registration_submitted":
        return application_status_reply(sender)
    draft = get_support_buddy_draft(sender)
    if draft is None:
        reset_user(sender)
        return "No registration draft found. Type 'menu' and choose 4 to begin."
    if command == "cancel":
        update_user(sender, state="buddy_registration_cancel")
        return "Cancel this draft? Your saved draft answers will be deleted.\n\n1. Yes, cancel\n2. Keep my draft"
    if state == "buddy_registration_cancel":
        if answer == "1":
            cancel_support_buddy_draft(sender)
            return "Your draft has been cancelled. Type 'menu' to return to the main menu."
        if answer == "2":
            return registration_destination(sender, next_registration_step(draft))
        return "Please choose 1 to cancel or 2 to keep your draft."
    if state == "buddy_registration_draft_saved":
        # Resume drafts created by the earlier partial implementation.
        return registration_destination(sender, next_registration_step(draft))
    if state == "buddy_registration_review":
        if answer == "1":
            missing = next_registration_step(draft)
            if missing != "review":
                return registration_destination(sender, missing)
            update_user(sender, state="buddy_registration_consent")
            return CONSENT_TEXT + "\n\n1. I agree - submit my application\n2. Back to review (do not submit)\n3. Cancel application"
        if answer == "2":
            update_user(sender, state="buddy_registration_edit")
            return "Which answer would you like to edit?\n\n" + "\n".join(
                str(i) + ". " + label for i, (_, _, label) in enumerate(REGISTRATION_FIELDS, 1)
            ) + "\n0. Back to review"
        if answer == "3":
            return handle_registration(sender, "cancel", state)
        return "Please choose 1, 2 or 3.\n\n" + registration_review(sender)
    if state == "buddy_registration_consent":
        if answer == "1":
            try:
                submitted = submit_support_buddy_application(sender, CONSENT_TEXT)
            except ValueError:
                return registration_destination(sender, next_registration_step(draft))
            if not submitted:
                return application_status_reply(sender)
            return "Your Support Buddy application has been submitted.\n\n" + application_status_reply(sender) + "\nType 'application status' anytime to check it."
        if answer == "2":
            return registration_destination(sender, "review")
        if answer == "3":
            return handle_registration(sender, "cancel", state)
        return "Please choose 1 to agree and submit, 2 to return to review, or 3 to cancel."
    if state == "buddy_registration_edit":
        if answer == "0":
            return registration_destination(sender, "review")
        choices = {str(i): step for i, (step, _, _) in enumerate(REGISTRATION_FIELDS, 1)}
        if answer not in choices:
            return "Please choose an answer from 1 to 9, or 0 to return to review."
        step = choices[answer]
        update_user(sender, state="buddy_registration_edit_" + step)
        return registration_prompt(step)
    editing = state.startswith("buddy_registration_edit_")
    prefix = "buddy_registration_edit_" if editing else "buddy_registration_"
    step = state[len(prefix):]
    fields = {item[0]: item[1] for item in REGISTRATION_FIELDS}
    if step not in fields:
        return registration_destination(sender, next_registration_step(draft))
    if step in REGISTRATION_OPTIONS:
        options = REGISTRATION_OPTIONS[step]
        choices = answer.replace(",", " ").split() if step in MULTI_SELECT_FIELDS else [answer]
        if not choices or any(choice not in options for choice in choices):
            return "Please choose using the numbers shown.\n\n" + registration_prompt(step)
        value = "|".join(dict.fromkeys(options[choice] for choice in choices))
    else:
        if not answer:
            return "Please enter an answer.\n\n" + registration_prompt(step)
        limit = 500 if step == "introduction" else 100
        if len(answer) > limit:
            return "Please use no more than " + str(limit) + " characters.\n\n" + registration_prompt(step)
        value = "" if step in ("display_name", "introduction") and command == "skip" else answer
    changes = {fields[step]: value}
    if step == "rdss":
        changes["verification_required"] = int(value == "No")
    update_support_buddy_draft(sender, **changes)
    if step == "name":
        update_user(sender, full_name=value)
    draft = get_support_buddy_draft(sender)
    return registration_destination(sender, "review" if editing else next_registration_step(draft))


def handle_buddy_request_command(sender, text):
    parts = text.split()
    if not parts or parts[0] not in ("requests", "request", "accept", "decline"):
        return None
    command = parts[0]
    if command == "requests" and len(parts) == 1:
        number = 1
    elif (len(parts) == 2 and parts[1].isascii() and parts[1].isdigit()
          and len(parts[1]) <= 9 and int(parts[1]) > 0):
        number = int(parts[1])
    else:
        return (
            "Type 'requests' to see incoming connection requests.\n"
            "Use the request ID shown: 'request 12', 'accept 12' or 'decline 12'.\n"
            "For another page, type 'requests 2'."
        )

    if command == "requests":
        requests, has_more = get_buddy_requests(sender, page=number)
        if not requests:
            return (
                "No pending connection requests on this page for your account.\n"
                "Type 'requests' for the first page, or 'menu' for the main menu."
            )
        lines = ["Your incoming connection requests (page " + str(number) + "):"]
        for request in requests:
            lines.append(
                "\nRequest #" + str(request["id"]) + "\n"
                + "Support wanted: " + (request["support_type"] or "Not recorded") + "\n"
                + "Preferred time: " + (request["availability"] or "Not recorded")
            )
        example = str(requests[0]["id"])
        lines.append("\nUse the request ID: 'request " + example + "', 'accept " + example + "' or 'decline " + example + "'.")
        if has_more:
            lines.append("Next page: 'requests " + str(number + 1) + "'.")
        lines.append("Type 'requests' to refresh or 'menu' for the main menu.")
        return "\n".join(lines)

    if command == "request":
        request = get_buddy_request(sender, number)
        if request is None:
            return "That request was not found for your account. Type 'requests' to see your requests."
        reply = (
            "Connection request #" + str(number) + "\n"
            + "Status: " + request["status"].capitalize() + "\n"
            + "Support wanted: " + (request["support_type"] or "Not recorded") + "\n"
            + "Preferred time: " + (request["availability"] or "Not recorded")
        )
        if request["status"] == "pending":
            reply += "\n\nType 'accept " + str(number) + "' or 'decline " + str(number) + "'."
        return reply + "\nType 'requests' for your inbox."

    decision = "accepted" if command == "accept" else "declined"
    outcome, request = respond_to_buddy_request(sender, number, decision)
    if outcome == "not_found":
        return "That request was not found for your account. Type 'requests' to see your requests."
    if outcome == "unavailable":
        return "Your Support Buddy profile must be approved and verified where required before accepting. Type 'application status' to check it."
    if outcome == "already_resolved":
        return "Request #" + str(number) + " was already " + request["status"] + ". Type 'requests' for pending requests."
    reply = "Request #" + str(number) + " " + decision + ". The caregiver can type 'status' to see your response."
    if decision == "accepted":
        reply += "\nAcceptance is recorded. Chat between buddies and contact sharing are not enabled yet."
    return reply + "\nType 'requests' to see other pending requests."


def buddy_unavailable_reply(sender, no_matches=False):
    update_user(sender, state="buddy_unavailable")
    message = (
        "We couldn't find an available buddy for your preferences right now."
        if no_matches else "This buddy isn't available to connect right now."
    )
    return message + """

What would you like to do next?

1. Find another buddy
2. Talk to CareConnect AI
3. Return to the main menu
"""


def handle_message(sender, text):
    user = get_user(sender)

    if user is None:
        create_user(sender)
        user = get_user(sender)

    state = user["state"]

    original_text = text.strip()
    text = original_text.lower()

    buddy_reply = handle_buddy_request_command(sender, text)
    if buddy_reply is not None:
        return buddy_reply

    if sender == ADMIN_PHONE_NUMBER:
        admin_reply = handle_admin_message(sender, text, state)
        if admin_reply is not None:
            return admin_reply

    if text.strip().lower() in ("application status", "application_status"):
        return application_status_reply(sender)

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

Status: Accepted

You are now matched.

Acceptance is recorded. Chat between buddies and contact sharing are not enabled yet.

Type 'menu' to return to the main menu.
"""

        elif latest_request["status"] == "declined":
            return buddy_unavailable_reply(sender)

    if state == "buddy_unavailable":
        if text in ("1", "2"):
            # Reuse the existing Find a Buddy and AI entry points below.
            reset_user(sender)
            state = "main_menu"
        elif text == "3":
            text = "menu"
        elif text not in ("hi", "hello", "hey", "start", "menu"):
            return "Please choose 1, 2 or 3.\n\n1. Find another buddy\n2. Talk to CareConnect AI\n3. Return to the main menu"

    if text in ["hi", "hello", "hey", "start", "menu"]:
        reset_user(sender)

        return """
Welcome to RDSS CareConnect

1. Find a Buddy
2. Talk to CareConnect AI
3. Resources
4. Become a Support Buddy
5. Contact RDSS

You can also type 'status' to check a match request.
Type 'application status' to check your Support Buddy application.
Support Buddies can type 'requests' to view incoming connection requests.
"""

    if state.startswith("buddy_registration_"):
        return handle_registration(sender, text, state)

    if state == "main_menu":
        if text == "1":
            update_user(
                sender,
                state="ai_onboarding",
                support_type="",
                availability=""
            )

            return (
                "Hey! I'm here to help you find another caregiver "
                "you can connect with.\n\n"
                "How have things been for you lately? "
                "You can tell me as much or as little as you like.\n\n"
                "Feel free to speak in whichever language "
                "you're most comfortable with."
            )

        elif text == "2":
            update_user(
                sender,
                state="ai_chat"
            )

            return """
CareConnect AI is here to listen.

You can talk to me about how you're feeling, what you're going through, or anything that's on your mind.

Type 'menu' anytime to return to the main menu.
"""

        elif text == "3":
            update_user(
                sender,
                state="resources_menu"
            )

            return get_resources_menu()

        elif text == "4":
            return begin_registration(sender)

        elif text == "5":
            return "RDSS contact information will be added here."

        return "Please type 1, 2, 3, 4 or 5. Type 'menu' to restart."

    elif state == "ai_chat":
        return ask_careconnect(sender, text)

    elif state == "resources_menu":
        return get_resource_reply(text)

    elif state == "ai_onboarding":
        extracted = extract_matching_preferences(original_text)
        current = get_user(sender)

        support_type = (
            extracted["support_type"]
            or current.get("support_type")
            or ""
        )

        availability = (
            extracted["availability"]
            or current.get("availability")
            or ""
        )

        update_user(
            sender,
            support_type=support_type,
            availability=availability
        )

        reply = generate_onboarding_reply(
            original_text,
            support_type=support_type,
            availability=availability
        )

        if not support_type or not availability:
            return reply

        update_user(sender, state="ai_onboarding_confirm")

        return (
            reply
            + "\n\nHere's what I understood:\n"
            + "Support: " + support_type + "\n"
            + "Preferred time: " + availability + "\n\n"
            + "Is that right?\n\n"
            + "1. Yes\n"
            + "2. Change my preferences"
        )

    elif state == "ai_onboarding_confirm":
        if text == "2":
            update_user(
                sender,
                state="ai_onboarding",
                support_type="",
                availability=""
            )

            return (
                "Of course. Tell me what kind of support "
                "you're looking for and when you'd usually "
                "feel comfortable chatting."
            )

        if text != "1":
            extracted = extract_matching_preferences(original_text)

            if extracted["support_type"] or extracted["availability"]:
                current = get_user(sender)

                support_type = (
                    extracted["support_type"]
                    or current.get("support_type")
                    or ""
                )

                availability = (
                    extracted["availability"]
                    or current.get("availability")
                    or ""
                )

                update_user(
                    sender,
                    support_type=support_type,
                    availability=availability
                )

                return (
                    "Of course, I've updated that.\n\n"
                    "Support: " + support_type + "\n"
                    "Preferred time: " + availability + "\n\n"
                    "Shall I look for a Support Buddy?\n\n"
                    "1. Yes\n"
                    "2. Start again"
                )

            return (
                "You can type 1 to confirm, 2 to start again, "
                "or tell me what you'd like to change."
            )

        user = get_user(sender)

        if not user.get("support_type") or not user.get("availability"):
            update_user(sender, state="ai_onboarding")

            return (
                "I still need a little more information. "
                "What kind of support would help you most?"
            )

        matches = find_matches(user)

        if not matches:
            reset_user(sender)
            return buddy_unavailable_reply(sender, no_matches=True)

        best_match = matches[0]

        save_match_preview(sender, best_match, user)

        preferences_text = "\n".join(
            "- " + item for item in best_match["shared_preferences"]
        )

        return (
            "I found a Support Buddy who shares your preferences:\n\n"
            + best_match["name"] + "\n\n"
            + preferences_text + "\n\n"
            + "Would you like to send a connection request?\n\n"
            + "1. Yes\n"
            + "2. No"
        )

    elif state == "confirm_match":
        if text == "1":
            outcome, request = create_selected_match_request(sender)
            if outcome == "missing":
                # A second confirmation may arrive after the first consumed the preview.
                if get_user(sender)["state"] == "match_pending":
                    return "Your connection request is already saved. Type 'status' to check it."
                reset_user(sender)
                return "Your previous match selection is no longer available. Type 'menu' and choose 1 to search again."
            if outcome == "unavailable":
                return buddy_unavailable_reply(sender)
            if outcome == "existing":
                return "You already have a pending request to " + request["caregiver_name"] + ". Type 'status' to check your latest request."

            return f"""
Connection request sent to {request["caregiver_name"]}.

Request ID: {request["id"]}
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

Chat between buddies and contact sharing are not enabled yet.

Type 'menu' to return to the main menu.
"""

        return "You are currently matched."

    return "Type 'menu' to return to the main menu."
