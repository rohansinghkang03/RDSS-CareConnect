from chatbot import ask_careconnect

from database import (
    create_match_request,
    cancel_support_buddy_draft,
    get_support_buddy_application,
    get_support_buddy_draft,
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
            reply += "\nExtra verification is required for non-RDSS members."
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


def handle_message(sender, text):
    user = get_user(sender)

    if user is None:
        create_user(sender)
        user = get_user(sender)

    state = user["state"]

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
4. Become a Support Buddy
5. Contact RDSS

You can also type 'status' to check a match request.
Type 'application status' to check your Support Buddy application.
"""

    if state.startswith("buddy_registration_"):
        return handle_registration(sender, text, state)

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
