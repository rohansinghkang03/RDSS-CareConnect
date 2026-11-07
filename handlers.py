from reporting_tracking import feature_call
import hmac
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from conversation_context import protect

from chatbot import ask_careconnect, extract_matching_preferences, generate_onboarding_reply, interpret_confirmation, safe_adapt_message, remember_matching_language, get_matching_language_example
from dotenv import load_dotenv

load_dotenv()

def parse_admin_phone_numbers(value):
    """Read a comma-separated allowlist in WhatsApp's country-code/digits form."""
    if not isinstance(value, str):
        return frozenset()
    numbers = set()
    for entry in value.split(","):
        number = entry.strip().removeprefix("+")
        if re.fullmatch(r"[1-9][0-9]{6,14}", number):
            numbers.add(number)
    return frozenset(numbers)


ADMIN_PHONE_NUMBERS = parse_admin_phone_numbers(os.getenv("ADMIN_PHONE_NUMBERS", ""))
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
    set_language_preference,
    reset_user,
    start_support_buddy_draft,
    update_support_buddy_draft,
    update_user
)

from matching import find_matches

from resources import get_resource_reply, get_resources_menu


PROFILING_CONSENT_PROMPT = (
    "CareConnect AI Profile 💜\n\n"
    "With your permission, CareConnect may use your future AI Chat "
    "messages to suggest information for your caregiver profile, "
    "such as your caregiving situation and the support you need.\n\n"
    "You can review, edit or reject each suggestion before it is saved. "
    "This is optional. To withdraw and delete your profile, return to "
    "the main menu, choose 6 (My profile), then 3 (Withdraw permission). "
    "Your profile will not be shared with another caregiver through "
    "this feature.\n\n"
    "RDSS administrators may also download your approved profile and individual usage summary "
    "for support planning. Reports use an internal ID and exclude your chat text and contact details. "
    "Choosing Yes includes this reporting purpose for your existing approved profile and future approvals. "
    "You can withdraw permission here; RDSS must also handle previously downloaded copies under its retention policy.\n\n"
    "1. Yes, enable profile suggestions\n"
    "2. No, thanks\n\n"
    "Withdrawing deletes profiling information, not your AI chat history.\n\n"
    "Type 'profile' to return to your profile, or 'menu' for the main menu."
)


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
    "I agree to receive WhatsApp updates about my Support Buddy application and incoming connection requests. I can type 'notifications off' to stop alerts. "
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
        if field in ('full_name','display_name','introduction'):
            protect(value)
        if value is None or (field not in ("display_name", "introduction") and not value):
            return step
    return "review"


def registration_review(sender):
    draft = get_support_buddy_draft(sender)
    if not draft:
        reset_user(sender)
        return caregiver_message(sender, "No registration draft found. Type 'menu' and choose 4 to begin.")
    lines = ["Review your Support Buddy application", ""]
    for _, field, label in REGISTRATION_FIELDS:
        value = draft.get(field)
        if field in ('full_name','display_name','introduction'):
            protect(value)
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
    message = (
        registration_review(sender)
        if step == "review"
        else registration_prompt(step)
    )
    return caregiver_message(sender, message)


def format_sgt_timestamp(value):
    """Format UTC database timestamps for caregivers in Singapore."""
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if raw.endswith(" UTC"):
            raw = raw[:-4]
        raw = raw.replace("Z", "+00:00")
        # PostgreSQL text timestamps may use +00; Python 3.9 requires +00:00.
        if "T" in raw or " " in raw:
            raw = re.sub(r"([+-]\d{2})$", r"\1:00", raw)
        raw = re.sub(
            r"(\d{2}:\d{2}:\d{2})\.(\d{1,6})(?=$|[+-])",
            lambda match: match[1] + "." + match[2].ljust(6, "0"), raw,
        )
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Asia/Singapore")).strftime("%-d %B %Y, %-I:%M %p SGT")


def application_status_reply(sender):
    application = get_support_buddy_application(sender)

    if application:
        status = application["status"]

        label = {
            "pending": "Pending RDSS review",
            "approved": "Approved",
            "rejected": "Not approved",
            "declined": "Not approved"
        }.get(status, status)

        reply = "Your Support Buddy Application 💜\n\nStatus: " + label
        reply += "\nSubmitted: " + format_sgt_timestamp(application["submitted_at"])

        if application["verification_required"]:
            reply += "\nExtra verification: " + (
                "Complete"
                if application.get("verified_at")
                else "Required for non-RDSS members"
            )

        if get_support_buddy_draft(sender):
            reply += (
                "\n\nYou also have an unfinished draft. "
                "Type 'menu' and choose 4 to resume."
            )

        return caregiver_message(
            sender,
            reply + "\n\nType 'menu' to return to the main menu.",
            required_text=format_sgt_timestamp(application["submitted_at"])
        )

    if get_support_buddy_draft(sender):
        return caregiver_message(sender, (
            "Your Support Buddy application is still a draft. 💜\n\n"
            "It hasn't been submitted to RDSS yet.\n\n"
            "Type 'menu', then choose 4 to continue."
        ))

    return caregiver_message(sender, (
        "You haven't submitted a Support Buddy application yet. 💜\n\n"
        "If you'd like to support another caregiver, "
        "type 'menu' and choose 4 to begin."
    ))


def begin_registration(sender):
    application = get_support_buddy_application(sender)
    if application and application["status"] not in ("rejected", "declined"):
        return application_status_reply(sender)
    track_usage_safely(sender, "buddy_application_started")
    start_support_buddy_draft(sender)
    draft = get_support_buddy_draft(sender)
    return (
        caregiver_message(sender, "Become a Support Buddy 💜")
        + "\n\n"
        + registration_destination(sender, next_registration_step(draft))
    )


def admin_menu_reply():
    return (
        "RDSS Admin Panel 💜\n\n"
        "1. View pending applications\n"
        "2. Application summary\n"
        "3. Log out\n"
        "4. Download statistics (Excel)\n\n"
        "Reply with a number. Type 'menu' to return here."
    )


def admin_application_list(sender=None):
    applications, total, counts = list_admin_applications("pending", 1, 25)
    if not applications:
        if sender is not None:
            update_user(sender, state="admin_menu")
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
    if sender not in ADMIN_PHONE_NUMBERS:
        if state.startswith("admin_"):
            update_user(sender, state="main_menu")
        return "Admin access is not enabled for this WhatsApp number. Type 'menu' for the main menu."
    command = text.strip().lower()
    reports_enabled=os.getenv('REPORTING_ENABLED','').lower()=='true'
    if reports_enabled:
        from reporting_auth import session_valid, login, logout

    if not ADMIN_PIN and (command == "admin login" or state.startswith("admin_")):
        if state.startswith("admin_"):
            update_user(sender, state="main_menu")
        return "Admin login is unavailable. Please contact the system administrator."

    if command == "admin login":
        update_user(sender, state="admin_pin")
        return "Enter your admin PIN."

    if state.startswith("admin_") and command == "menu":
        if state == "admin_pin":
            update_user(sender, state="main_menu")
            return "Admin login cancelled. Type 'menu' to open the caregiver menu."
        update_user(sender, state="admin_menu")
        return admin_menu_reply()

    if state.startswith("admin_") and command == "admin logout":
        if reports_enabled:logout(sender)
        update_user(sender, state="main_menu")
        return "You have been logged out."

    if state == "admin_pin":
        if reports_enabled:
            outcome=login(sender,text,ADMIN_PIN,ADMIN_PHONE_NUMBERS)
            if outcome=='ok':
                update_user(sender,state='admin_menu')
                return 'Admin login successful. Your session lasts 30 minutes.\n\n'+admin_menu_reply()
            if outcome=='locked':return "Too many incorrect attempts. Please wait 15 minutes. Type 'menu' to cancel."
            return "Incorrect PIN. Try again or type 'menu'."
        if ADMIN_PIN and hmac.compare_digest(text.strip().encode("utf-8"), ADMIN_PIN.encode("utf-8")):
            update_user(sender, state="admin_menu")
            return "Admin login successful.\n\n" + admin_menu_reply()
        return "Incorrect PIN. Try again or type 'menu'."

    if reports_enabled and state.startswith('admin_'):
        if not session_valid(sender,ADMIN_PIN,ADMIN_PHONE_NUMBERS):
            logout(sender)
            update_user(sender,state='main_menu')
            return "Your admin session has expired or changed. Type 'admin login' to sign in again."
        if command in {'notifications','notifications on','notifications off'}:
            from notifications import command as notification_command
            return notification_command(sender,command)
        if state in {'admin_menu','admin_report_period','admin_applications'} and not command.isdigit():
            from admin_assist import resolve
            intent=resolve(text)
            if intent:
                action,period=intent
                if action=='report':
                    if period:
                        from reporting_jobs import request_report
                        result=request_report(sender,period,ADMIN_PIN,ADMIN_PHONE_NUMBERS)
                        update_user(sender,state='admin_menu')
                        return result
                    update_user(sender,state='admin_menu');state='admin_menu';command='4'
                elif action in {'applications','summary'}:
                    update_user(sender,state='admin_menu');state='admin_menu';command='1' if action=='applications' else '2'
        if command=='report status':
            from reporting_jobs import job_status
            return job_status(sender)
        if state=='admin_report_period':
            from reporting_jobs import request_report
            try:
                reply=request_report(sender,text,ADMIN_PIN,ADMIN_PHONE_NUMBERS)
            except ValueError as exc:
                return str(exc)+"\n\nType 'menu' for the admin menu."
            update_user(sender,state='admin_menu')
            return reply

    if state == "admin_menu":
        if command == "1":
            applications, _, _ = list_admin_applications("pending", 1, 25)
            update_user(sender, state="admin_applications" if applications else "admin_menu")
            return admin_application_list(sender)
        if command == "2":
            return admin_application_summary()
        if command == "3":
            if reports_enabled:logout(sender)
            update_user(sender, state="main_menu")
            return "You have been logged out."
        if command=='4':
            if not reports_enabled:return 'Statistics are not enabled yet.\n\n'+admin_menu_reply()
            update_user(sender,state='admin_report_period')
            return ("CareConnect statistics\n\nReply 7 for the last 7 days, or 30 for the last 30 days.\n"
                    "For custom dates (up to 31 days), enter DD-MM-YYYY DD-MM-YYYY.\n\n"
                    "The Excel file includes administrator-only caregiver summaries. Keep downloaded copies private.\n"
                    "Type 'menu' to return to the admin menu.")
        return "Please choose an option.\n\n" + admin_menu_reply()

    if state == "admin_applications":
        if not list_admin_applications("pending", 1, 1)[0]:
            update_user(sender, state="admin_menu")
            return "No pending Support Buddy applications.\n\n" + admin_menu_reply()
        if command in ("menu", "back"):
            update_user(sender, state="admin_menu")
            return admin_menu_reply()
        application_id = admin_application_id_for_choice(command)
        if application_id is None:
            return "Please reply with a listed application number, or type 'menu'.\n\n" + admin_application_list(sender)
        update_user(sender, state=f"admin_review_{application_id}")
        return admin_application_detail(application_id)

    if state.startswith("admin_review_"):
        if command == "back":
            update_user(sender, state="admin_applications")
            return admin_application_list(sender)
        application_id = int(state.rsplit("_", 1)[1])
        application = get_admin_application(application_id)
        if application is None:
            update_user(sender, state="admin_applications")
            return admin_application_list(sender)
        if command == "5":
            update_user(sender, state="admin_applications")
            return admin_application_list(sender)
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
        return f"Application {label}.\n\n" + admin_application_list(sender)

    if state.startswith("admin_note_"):
        if command == "back":
            update_user(sender, state="admin_menu")
            return admin_menu_reply()
        application_id = int(state.rsplit("_", 1)[1])
        if command == "cancel":
            update_user(sender, state=f"admin_review_{application_id}")
            return admin_application_detail(application_id)
        application = get_admin_application(application_id)
        if application is None:
            update_user(sender, state="admin_applications")
            return admin_application_list(sender)
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
            track_usage_safely(sender, "buddy_application_submitted")
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
        if request and request.get('status')=='accepted':
            from match_chat_store import enabled
            if enabled():
                from match_chat import screen
                return screen(sender,number)
        return "Request #" + str(number) + " was already " + request["status"] + ". Type 'requests' for pending requests."
    reply = "Request #" + str(number) + " " + decision + ". The caregiver can type 'status' to see your response."
    if decision == "accepted":
        from match_chat_store import enabled
        if enabled():
            from match_chat import screen
            return screen(sender,number)
        reply += "\nAcceptance is recorded. Chat between buddies and contact sharing are not enabled yet."
    return reply + "\nType 'requests' to see other pending requests."


def show_match_choice(sender, match, user):
    """Display one candidate; only the later explicit confirmation sends a request."""
    save_match_preview(sender,match,user)
    protect(match['name'])
    details="\n".join('- '+item for item in match['shared_preferences'])
    tier=match.get('tier','exact')
    if tier=='support':
        opening=("We haven't found someone who fits both preferences, but there may still be a lovely connection here. 💜\n\n"
                 +match['name']+" offers the kind of support you're looking for. Their usual times are "
                 +', '.join(match['offered_times'])+", which differ from your preferred time. Would you be open to trying those times?")
    elif tier=='time':
        opening=("If your preferred timing matters more to you, here's another possibility. 💜\n\n"
                 +match['name']+" has a usual schedule that fits yours. They offer "
                 +', '.join(match['offered_support'])+", rather than your selected support preference. Would you like to get to know them?")
    else:opening="We may have found someone you could connect with! 💜\n\n"+match['name']
    return caregiver_message(sender,opening+'\n\n'+details+
        "\n\nThese are their usual preferences, not a promise that they are online now. They will need to accept your request."
        "\n\nWould you like to send them a connection request? We will send WhatsApp updates about this connection. Type 'notifications off' anytime to stop alerts.\n1. Yes, send request\n2. No, go back\n\nType 'menu' for the main menu.",required_text=match['name'])


def show_match_alternatives(sender, matches=None):
    user=get_user(sender)
    matches=find_matches(user) if matches is None else matches
    if not matches:return buddy_unavailable_reply(sender,no_matches=True)
    # New exact candidates may have become eligible since the previous search.
    exact=next((m for m in matches if m.get('tier','exact')=='exact'),None)
    if exact:return show_match_choice(sender,exact,user)
    update_user(sender,state='match_alternatives')
    lines=["I haven't found someone who fits both your support preference and timing just yet. That doesn't have to be the end of the search. 💜",
           "Would you be open to one of these options?"]
    if any(m['tier']=='support' for m in matches):lines.append('1. Keep my support preference and try a different time')
    if any(m['tier']=='time' for m in matches):lines.append('2. Keep my preferred timing and explore a different kind of support')
    lines.append("3. Change my preferences\n4. Talk to CareConnect AI\n\nI'll show you the person's details before you decide. Nothing is sent yet. Their usual timing doesn't mean they are online now.\n\nType 'menu' for the main menu.")
    return caregiver_message(sender,'\n\n'.join(lines))


def buddy_unavailable_reply(sender, no_matches=False):
    track_usage_safely(sender, "buddy_match_unavailable")
    update_user(sender, state="buddy_unavailable")

    if no_matches:
        introduction = (
            "I couldn't find a Support Buddy who matches "
            "your preferences right now."
        )
    else:
        introduction = (
            "Unfortunately, this Support Buddy isn't "
            "available to connect right now."
        )

    message = (
        introduction
        + "\n\n"
        + "I understand this might be disappointing, "
        + "especially when you're looking for someone to talk to. "
        + "You're welcome to try again or talk with CareConnect AI "
        + "in the meantime.\n\n"
        + "What would you like to do next?\n\n"
        + "1. Find another buddy\n"
        + "2. Talk to CareConnect AI\n"
        + "3. Return to the main menu"
    )

    language_example = get_matching_language_example(sender)

    if language_example:
        return safe_adapt_message(
            message,
            language_example
        )

    return message



LANGUAGE_CHOICES = {
    "1": "English",
    "2": "Mandarin Chinese",
    "3": "Tamil",
    "4": "Malay"
}

LANGUAGE_SELECTION_MESSAGE = """
Welcome to RDSS CareConnect! 💜

I'm CareConnect, your support companion from
Rare Disorders Society Singapore (RDSS).

I'm here to help you connect with other caregivers,
find helpful resources, or simply have someone to talk to.

Before we begin, which language would you prefer?

1. English
2. 中文
3. தமிழ்
4. Bahasa Melayu

You can also type the name of any other language you prefer.

You can change your language anytime by typing 'language'.
"""

MAIN_MENU_MESSAGE = """
How can I support you today? 💜

1. 🤝 Find a Support Buddy
2. 💬 Talk to CareConnect AI
3. 📚 Explore Resources
4. 💜 Become a Support Buddy
5. 📞 Contact RDSS
6. 👤 My profile and privacy settings
7. 📋 My request / application status
8. 🌐 Change language

You can select a number or simply tell me what you're looking for.

Choose 6 to view your profile, manage permission or delete your profile.

Type 'menu' anytime to return here.
"""



def track_usage_safely(sender, event_type, category=None):
    """Record analytics without interrupting caregiver conversations."""
    try:
        from phase2_analytics import record_usage_event
        record_usage_event(sender, event_type, category)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "CareConnect analytics failed for event %s",
            event_type,
        )


def caregiver_message(sender, message, required_text=None):
    """
    Adapt a fixed CareConnect system message to the caregiver's
    preferred language while preserving important information.

    English messages are returned without an OpenAI call.
    Translation failures fall back to the original message.
    """
    from conversation_context import current
    context=current.get()
    if context and context['defer']:
        protect(required_text)
        return message
    language = get_matching_language_example(sender)

    if not language or language.strip().lower() == "english":
        return message

    return safe_adapt_message(
        message,
        language,
        required_text=required_text
    )



def show_careconnect_menu(sender):
    track_usage_safely(sender, "main_menu_opened")
    from conversation_context import current
    from match_chat_store import enabled
    message=MAIN_MENU_MESSAGE
    if enabled():message+="\n\nType 'my chats' for accepted connections and contact-sharing settings."
    if current.get():return message
    language = get_matching_language_example(sender)

    if not language or language.lower() == "english":
        return message

    return safe_adapt_message(
        message,
        language,
        required_text="'menu'"
    )


def show_status_menu(sender):
    from match_chat_store import enabled
    chat_option="5. Accepted connections / match chat\n" if enabled() else ''
    return caregiver_message(sender, (
        "My status 💜\n\n"
        "1. My buddy connection request\n"
        "2. My Support Buddy application\n"
        "3. Return to main menu\n"
        "4. Incoming buddy connection requests\n"+chat_option+"\n"
        "Choose a number. Type 'menu' for the main menu."
    ))


def select_careconnect_language(sender, answer):
    answer = answer.strip()
    lowered = answer.lower()

    if lowered in ("language", "languages", "back", "hi", "hello", "hey", "start"):
        return LANGUAGE_SELECTION_MESSAGE

    if lowered == "menu":
        language = get_matching_language_example(sender)

        if not language:
            return LANGUAGE_SELECTION_MESSAGE

        update_user(sender, state="main_menu")
        return show_careconnect_menu(sender)

    language = LANGUAGE_CHOICES.get(answer)

    if language is None:
        known_languages = {
            "english": "English",
            "chinese": "Mandarin Chinese",
            "mandarin": "Mandarin Chinese",
            "中文": "Mandarin Chinese",
            "华语": "Mandarin Chinese",
            "tamil": "Tamil",
            "தமிழ்": "Tamil",
            "malay": "Malay",
            "bahasa melayu": "Malay",
            "punjabi": "Punjabi",
            "vietnamese": "Vietnamese",
            "burmese": "Burmese",
            "hindi": "Hindi"
        }

        language = known_languages.get(lowered)

    if language is None and 0 < len(answer) <= 80:
        import re
        from chatbot import client, MODEL

        try:
            response = feature_call("Language detection", client.responses.create,
                model=MODEL,
                instructions=(
                    "You validate language selections for a caregiver "
                    "support chatbot. The user has been asked which "
                    "language they prefer. Accept a language name, "
                    "a language written in its own script, or an "
                    "explicit request to communicate in a language. "
                    "Reject ordinary conversation, greetings, "
                    "requests for help, and ambiguous messages. "
                    "Reply with ONLY the standard English name "
                    "of the requested language, or INVALID. "
                    "Never add explanations."
                ),
                input=answer,
                store=False
            )

            detected = response.output_text.strip()

            if (
                detected != "INVALID"
                and re.fullmatch(r"[A-Za-z][A-Za-z -]{0,59}", detected)
                and len(detected.split()) <= 5
            ):
                language = detected

        except Exception as error:
            print("Language selection error:", type(error).__name__)

    if language is None:
        return (
            "I couldn't identify that language. "
            "Please choose 1, 2, 3 or 4, "
            "or type the name of your preferred language.\n\n"
            + LANGUAGE_SELECTION_MESSAGE
        )

    from conversation_ai import canonical_language,save_style,take_resume_state
    from conversation_script import response_style
    from conversation_context import current
    language=canonical_language(language) or language
    set_language_preference(sender, language)
    hint=answer if any(term in answer.casefold() for term in ('pinyin','romanised','romanized','english letters','latin letters','chinese characters')) else ''
    style=response_style(language,'standard',hint)
    save_style(sender,style)
    if current.get():current.get().update(language=language,style=style)
    resume=take_resume_state(sender) or 'main_menu'
    if resume.startswith('admin_') or resume=='language_selection':resume='main_menu'
    update_user(sender,state=resume)
    if resume!='main_menu':
        from conversation_routing import current_screen
        return current_screen(sender,resume)
    return show_careconnect_menu(sender)



def interpret_main_menu_intent(message):
    """Return a menu number, CLARIFY, or UNKNOWN."""
    from conversation_context import current
    if current.get() and 'main_intent' in current.get():return current.get()['main_intent']
    import re
    from chatbot import client, MODEL

    try:
        response = feature_call("Menu routing", client.responses.create,
            model=MODEL,
            instructions=(
                "Classify a caregiver's message for the RDSS CareConnect "
                "WhatsApp main menu. Return exactly ONE label: "
                "1, 2, 3, 4, 5, 6, 7, 8, CLARIFY, or UNKNOWN. "
                "1 = explicitly wants to connect with another caregiver "
                "or find a Support Buddy. "
                "2 = explicitly wants to talk to CareConnect AI. "
                "3 = requests information, resources, or assistance "
                "such as financial support. "
                "4 = wants to volunteer or register as a Support Buddy. "
                "5 = wants to contact RDSS staff directly. "
                "6 = wants to view their profile or manage profile permission. "
                "7 = wants to check a buddy request or application status. "
                "8 = wants to change their preferred language. "
                "CLARIFY = expresses loneliness, distress, uncertainty, "
                "or a general desire to talk without clearly choosing "
                "AI or peer support. "
                "UNKNOWN = unrelated or impossible to determine. "
                "Never infer a specific service from distress alone. "
                "Do not provide advice or explanations."
            ),
            input=message,
            store=False
        )

        label = response.output_text.strip().upper()

        if re.fullmatch(r"[1-8]|CLARIFY|UNKNOWN", label):
            return label

    except Exception as error:
        print("Main menu intent error:", type(error).__name__)

    return "UNKNOWN"


def main_menu_clarification(sender):
    message = (
        "I'm here to help. 💜\n\n"
        "Would you prefer to:\n"
        "1. Connect with another caregiver\n"
        "2. Talk to CareConnect AI\n\n"
        "You can also tell me a little more about what you need."
    )

    language = get_matching_language_example(sender)

    if language and language.lower() != "english":
        return safe_adapt_message(message, language)

    return message

def add_reply_navigation(sender, reply):
    """Verified contextual navigation, including generated replies and error paths."""
    from conversation_context import current
    context=current.get()
    if not isinstance(reply,str):reply="Sorry, I couldn't prepare that reply. Please try again."
    has_menu=bool(re.search(r"['‘’\"]menu['‘’\"]",reply,re.I))
    has_back=bool(re.search(r"['‘’\"]back['‘’\"]",reply,re.I))
    if has_menu and not context:return reply
    try:
        state=(get_user(sender) or {}).get('state','')
        if has_menu and (has_back or state=='main_menu') and not (context and context['generated']):return reply
        if state=='language_selection':
            footer=("Choose one of the languages above, or type your preferred language, "
                    "to continue to the main menu. Type 'menu' to see the language choices again. "
                    "Type 'back' to return to your previous screen.")
        elif state=='ai_chat':
            footer="Type 'resources' for the Resource Hub, 'profile' for your profile and privacy settings, or 'menu' for the main menu."
        elif state.startswith('profile_') or state=='profiling_consent':
            footer="Type 'back' for the previous profile screen."
            if not has_menu:footer+=" Type 'profile' for your profile, or 'menu' for the main menu."
        elif state.startswith(('contact_share_','contact_chat_')):
            footer="Type 'back' or 'my chats' for your connections, or 'menu' for the main menu."
        elif state.startswith('buddy_registration_'):
            footer="Type 'back' to return within your application, or 'menu' to pause. Type 'my status' to check your application."
        elif state in {'match_pending','matched','buddy_unavailable'}:
            footer="Type 'back' or 'menu' for the main menu, or 'my status' to check your buddy request or application."
        elif state in {'resources_menu','status_menu'}:
            footer="Type 'back' or 'menu' for the main menu."
        elif state in {'ai_onboarding','ai_onboarding_confirm','confirm_match'}:
            footer="Type 'back' to return to the previous screen, 'my status' to check a request, or 'menu' for the main menu."
        elif state.startswith('admin_'):
            footer="Type 'back' or 'menu' for the admin menu. Type 'admin logout' to sign out."
        else:footer="Type 'menu' to return to the menu."
        translated=caregiver_message(sender,footer,required_text="'menu'" if "'menu'" in footer else None)
        if context and context['fixed_localized']:
            from profile_localization import malay_profile_template
            fixed=malay_profile_template(footer)
            if fixed is not None:translated=fixed
            else:context['fixed_localized']=False
        required=re.findall(r"'([a-z ]+)'",footer)
        if not isinstance(translated,str) or any("'"+command+"'" not in translated for command in required):translated=footer
    except Exception:translated="Type 'menu' to return to the menu."
    return reply.rstrip()+'\n\n'+translated


def handle_message(sender, text):
    """Contain stale-review races and keep navigation visible on every reply."""
    from conversation_context import conversation
    from conversation_ai import get_style,canonical_language
    from conversation_routing import prepare
    from conversation_presentation import render_reply
    user=get_user(sender)
    if user is None:
        create_user(sender);user=get_user(sender)
    language=canonical_language(get_matching_language_example(sender)) or ''
    with conversation(language,get_style(sender,language)) as turn:
        try:
            routed,reply=prepare(sender,text,user)
            if reply is None:reply=_handle_message(sender,routed)
        except (PermissionError, ValueError):
            reply=caregiver_message(sender,"That action is no longer available. Type 'profile' to view your profile or 'menu' for the main menu. 💜")
        reply=add_reply_navigation(sender,reply)
        from navigation_design import organize
        reply=organize(sender,reply,(get_user(sender) or {}).get('state',''))
        result=render_reply(sender,reply)
        if turn.get('chat_request_id'):
            from match_chat import ChatReply,button_label
            return ChatReply(result,turn['chat_request_id'],button_label(turn['language'],turn['style']))
        return result


def _handle_message(sender, text):
    user = get_user(sender)

    if user is None:
        create_user(sender)
        user = get_user(sender)

    state = user["state"]

    original_text = text.strip()
    text = original_text.lower()

    if sender in ADMIN_PHONE_NUMBERS or text == "admin login" or state.startswith("admin_"):
        admin_reply = handle_admin_message(sender, original_text, state)
        if admin_reply is not None:
            return admin_reply

    from notifications import command as notification_command
    notice=notification_command(sender,text)
    if notice is not None:return notice

    from match_chat import handle as handle_match_chat
    chat_reply=handle_match_chat(sender,text,state)
    if chat_reply is not None:return chat_reply

    buddy_reply = handle_buddy_request_command(sender, text)
    if buddy_reply is not None:
        return buddy_reply

    from profile_navigation import handle_profile_navigation
    profile_reply = handle_profile_navigation(sender, text, state, original_text)
    if profile_reply is not None:
        return profile_reply

    if text == "my status" or (state == "main_menu" and text == "7"):
        update_user(sender, state="status_menu")
        return show_status_menu(sender)

    if state == "status_menu":
        if text == "1":
            text = "status"
        elif text == "2":
            text = "application status"
        elif text == "3":
            text = "menu"
        elif text == "4":
            return handle_buddy_request_command(sender, "requests")
        elif text not in ("menu", "language", "status", "application status"):
            return show_status_menu(sender)

    if state == "main_menu" and text == "8":
        text = "language"

    if text.strip().lower() in ("application status", "application_status"):
        return application_status_reply(sender)

    if text == "status":
        latest_request = get_latest_match_request(sender)
        if latest_request:protect(latest_request.get('caregiver_name'))

        if latest_request is None:
            return caregiver_message(
                    sender,
                    "You do not have any match requests yet.\n\nType 'menu' to return to the main menu.",
                    required_text="'menu'"
                )

        if latest_request["status"] == "pending":
            return (
                    caregiver_message(sender, "Your connection request to ")
                    + latest_request["caregiver_name"]
                    + caregiver_message(
                        sender,
                        " is still pending.\n\nType 'menu' to return to the main menu.",
                        required_text="'menu'"
                    )
                )

        elif latest_request["status"] == "accepted":
            from match_chat_store import enabled
            if enabled():
                from match_chat import screen
                return screen(sender,latest_request['id'])
            update_user(
                sender,
                state="matched"
            )

            return (
                    caregiver_message(sender, "Great news! 💜")
                    + "\n\n"
                    + latest_request["caregiver_name"]
                    + caregiver_message(sender, " accepted your connection request.")
                    + "\n\n"
                    + caregiver_message(
                        sender,
                        "Status: Accepted\n\nYou are now matched.\n\n"
                        "Acceptance is recorded. Chat between buddies and contact sharing "
                        "are not enabled yet.\n\n"
                        "Type 'menu' to return to the main menu.",
                        required_text="'menu'"
                    )
                )

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
            return caregiver_message(
                    sender,
                    "Please choose 1, 2 or 3.\n\n"
                    "1. Find another buddy\n"
                    "2. Talk to CareConnect AI\n"
                    "3. Return to the main menu"
                )

    if text == "language":
        update_user(sender, state="language_selection")
        return LANGUAGE_SELECTION_MESSAGE

    if state == "language_selection":
        return select_careconnect_language(sender, original_text)

    if text in ["hi", "hello", "hey", "start", "menu"]:
        reset_user(sender)

        if not get_matching_language_example(sender):
            update_user(sender, state="language_selection")
            return LANGUAGE_SELECTION_MESSAGE

        return show_careconnect_menu(sender)

    if state.startswith("buddy_registration_"):
        return handle_registration(sender, original_text, state)

    if state == "main_menu":
        if not get_matching_language_example(sender):
            update_user(sender, state="language_selection")
            return LANGUAGE_SELECTION_MESSAGE

        if text not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            intent = interpret_main_menu_intent(original_text)

            if intent == "CLARIFY":
                return main_menu_clarification(sender)

            if intent in ("1", "2", "3", "4", "5", "6", "7", "8"):
                text = intent

            else:
                language = get_matching_language_example(sender)
                message = (
                    "I'm not quite sure what you're looking for. "
                    "You can choose an option from 1 to 8, "
                    "or tell me how I can help."
                )

                if language and language.lower() != "english":
                    return safe_adapt_message(message, language)

                return message

        if text == "1":
            track_usage_safely(sender, "buddy_search_started")
            update_user(
                sender,
                state="ai_onboarding",
                support_type="",
                availability=""
            )

            message = (
                "Let's find someone you can connect with. 💜\n\n"
                "Everyone's caregiving journey is different, and "
                "sometimes it helps to speak with someone who understands.\n\n"
                "I'd like to learn a little about you so I can help "
                "find a suitable Support Buddy.\n\n"
                "How have things been for you lately?\n\n"
                "Feel free to share as much or as little as "
                "you're comfortable with."
            )

            language = get_matching_language_example(sender)

            if language and language.lower() != "english":
                return safe_adapt_message(message, language)

            return message

        elif text == "2":
            update_user(
                sender,
                state="ai_chat"
            )
            track_usage_safely(sender, "ai_chat_started")

            message = (
                "You're chatting with CareConnect AI. 💜\n\n"
                "I'm here to listen, help you work through your thoughts, "
                "or explore possible next steps.\n\n"
                "You can talk about your caregiving experiences, "
                "share what's on your mind, or ask for practical suggestions.\n\n"
                "I'm an AI companion, not a human counsellor, "
                "but I'll do my best to support you.\n\n"
                "What's on your mind today?\n\n"
                "To view your profile, review suggestions or withdraw permission, "
                "type 'menu' and choose 6.\n\n"
                "Type 'menu' anytime to return to the main menu."
            )

            language = get_matching_language_example(sender)

            if language and language.lower() != "english":
                return safe_adapt_message(message, language)

            return message

        elif text == "3":
            update_user(
                sender,
                state="resources_menu"
            )
            track_usage_safely(sender, "resource_hub_opened")

            return caregiver_message(sender, get_resources_menu())

        elif text == "4":
            return begin_registration(sender)

        elif text == "5":
            return caregiver_message(
                    sender,
                    "RDSS contact information will be added here."
                )

        elif text == "6":
            from profile_navigation import show_profile
            return show_profile(sender)

        elif text == "7":
            update_user(sender, state="status_menu")
            return show_status_menu(sender)

        elif text == "8":
            update_user(sender, state="language_selection")
            return LANGUAGE_SELECTION_MESSAGE

        return caregiver_message(
                sender,
                "Please choose a number from 1 to 8. Type 'menu' to restart.",
                required_text="'menu'"
            )


    elif state == "ai_chat":
        reply=ask_careconnect(sender, original_text)
        from conversation_context import generated
        generated()
        if not reply.startswith('Sorry, CareConnect AI is temporarily unavailable.'):
            protect(reply)
        return reply

    elif state == "resources_menu":
        if text == "back":
            update_user(sender,state='main_menu')
            return show_careconnect_menu(sender)
        if text in ("1", "2", "3", "4"):
            update_user(sender, state="resources_detail")
            track_usage_safely(sender, "resource_category_opened", text)
            return caregiver_message(sender, get_resource_reply(text))
        return caregiver_message(sender, get_resources_menu())

    elif state == "resources_detail":
        if text == "back":
            update_user(sender, state="resources_menu")
            return caregiver_message(sender, get_resources_menu())
        if text in ("1", "2", "3", "4"):
            track_usage_safely(sender, "resource_category_opened", text)
            return caregiver_message(sender, get_resource_reply(text))
        return caregiver_message(
            sender, "Type 'back' to view resource categories or 'menu' for the main menu."
        )

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
        if extracted["support_type"] and support_type != current.get("support_type"):
            track_usage_safely(sender, "support_need_selected")

        reply = generate_onboarding_reply(
            original_text,
            support_type=support_type,
            availability=availability
        )
        if reply not in {
            "I'm here to help you find someone to connect with. What kind of support would help you most right now?",
            "When would you usually feel comfortable chatting with another caregiver?",
            "I can help you look for a suitable Support Buddy."}:
            protect(reply)

        if not support_type or not availability:
            return reply

        update_user(sender, state="ai_onboarding_confirm")

        confirmation_message = (
            "Here's what I've understood so far: 💜\n"
            + "Support: " + support_type + "\n"
            + "Preferred time: " + availability + "\n\n"
            + "Does this sound right?\n\n"
            + "1. Yes\n"
            + "2. I'd like to change something"
        )

        return (
            reply
            + "\n\n"
            + safe_adapt_message(
                confirmation_message,
                original_text
            )
        )


    elif state == "ai_onboarding_confirm":
        if text == "2":
            update_user(
                sender,
                state="ai_onboarding",
                support_type="",
                availability=""
            )

            return caregiver_message(
                    sender,
                    "Of course. Tell me what kind of support you're looking for "
                    "and when you'd usually feel comfortable chatting."
                )

        if text not in ("1", "2"):
            intent = interpret_confirmation(original_text)

            if intent == "confirm":
                text = "1"

            elif intent == "change":
                extracted = extract_matching_preferences(original_text)

                if not extracted["support_type"] and not extracted["availability"]:
                    update_user(sender, state="ai_onboarding")
                    return caregiver_message(
                            sender,
                            "Of course. What would you like to change about your preferences?"
                        )

            else:
                return caregiver_message(
                        sender,
                        "Just checking, are these preferences correct? "
                        "You can say yes, tell me what to change, or type 2 to start again."
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
                        caregiver_message(sender, "Of course, I've updated that. 💜")
                        + "\n\n"
                        + caregiver_message(sender, "Support:")
                        + " " + support_type + "\n"
                        + caregiver_message(sender, "Preferred time:")
                        + " " + availability + "\n\n"
                        + caregiver_message(
                            sender,
                            "Shall I look for a Support Buddy?\n\n1. Yes\n2. Start again"
                        )
                    )

            return caregiver_message(
                    sender,
                    "You can type 1 to confirm, 2 to start again, "
                    "or tell me what you'd like to change."
                )

        user = get_user(sender)

        if not user.get("support_type") or not user.get("availability"):
            update_user(sender, state="ai_onboarding")

            return caregiver_message(
                    sender,
                    "I still need a little more information. "
                    "What kind of support would help you most?"
                )

        matches = find_matches(user)

        if os.getenv('REPORTING_ENABLED','').lower()=='true':
            from reporting_tracking import record_search
            record_search(sender,bool(matches))

        if not matches:
            return buddy_unavailable_reply(sender, no_matches=True)

        track_usage_safely(sender, "buddy_match_found")
        best_match = matches[0]

        if best_match.get('tier','exact')!='exact':
            return show_match_alternatives(sender,matches)
        return show_match_choice(sender,best_match,user)

    elif state == 'match_alternatives':
        if text in {'1','2'}:
            tier='support' if text=='1' else 'time'
            candidate=next((m for m in find_matches(user) if m.get('tier')==tier),None)
            if candidate:return show_match_choice(sender,candidate,user)
            return caregiver_message(sender,"That option has changed since we last checked. Let's see what's available now. 💜")+'\n\n'+show_match_alternatives(sender)
        if text=='3':
            update_user(sender,state='ai_onboarding',support_type=None,availability=None)
            return caregiver_message(sender,"Of course. What kind of support would help you most? Type 'menu' to return to the main menu.")
        if text=='4':
            update_user(sender,state='ai_chat')
            return caregiver_message(sender,"I'm here to listen. What's on your mind? 💜 Type 'menu' for the main menu.")
        return show_match_alternatives(sender)

    elif state == "confirm_match":
        if text == "1":
            outcome, request = create_selected_match_request(sender)
            if request:protect(request.get('caregiver_name'))
            if outcome == "missing":
                # A second confirmation may arrive after the first consumed the preview.
                if get_user(sender)["state"] == "match_pending":
                    return caregiver_message(
                            sender,
                            "Your connection request is already saved. Type 'status' to check it.",
                            required_text="'status'"
                        )
                reset_user(sender)
                return caregiver_message(
                        sender,
                        "Your previous match selection is no longer available. Type 'menu' and choose 1 to search again.",
                        required_text="'menu'"
                    )
            if outcome == "unavailable":
                return buddy_unavailable_reply(sender)
            if outcome == "existing":
                return (
                        caregiver_message(sender, "You already have a pending request to ")
                        + request["caregiver_name"]
                        + caregiver_message(
                            sender,
                            ". Type 'status' to check your latest request.",
                            required_text="'status'"
                        )
                    )

            return (
                    caregiver_message(sender, "Connection request sent to ")
                    + request["caregiver_name"]
                    + ".\n\n"
                    + caregiver_message(sender, "Request ID:")
                    + " " + str(request["id"]) + "\n"
                    + caregiver_message(sender, "Status: Pending")
                    + "\n\n"
                    + caregiver_message(
                        sender,
                        "Type 'status' to check whether they have responded.",
                        required_text="'status'"
                    )
                    + "\n\n"
                    + caregiver_message(
                        sender,
                        "Type 'menu' to return to the main menu.",
                        required_text="'menu'"
                    )
                )

        elif text == "2":
            # Keep both alternative routes accessible after declining a preview.
            candidates=find_matches(user)
            if candidates and not any(m.get('tier','exact')=='exact' for m in candidates):
                return show_match_alternatives(sender,candidates)
            reset_user(sender)
            return caregiver_message(
                    sender,
                    (
                        "No worries! 💜\n\n"
                        "Your connection request hasn't been sent.\n\n"
                        "You can look for another Support Buddy whenever you're ready.\n\n"
                        "Type 'menu' to return to the main menu."
                    ),
                    required_text="'menu'"
                )

        return caregiver_message(
                sender,
                "Please type 1 for Yes or 2 for No."
            )

    elif state == "match_pending":
        return caregiver_message(sender, """
Your connection request is awaiting a response. 💜

Type 'status' to check for an update.

Type 'menu' to return to the main menu.
""")

    elif state == "matched":
        latest_request = get_latest_match_request(sender)
        if latest_request:protect(latest_request.get('caregiver_name'))

        if latest_request is not None:
            from match_chat_store import enabled
            if enabled() and latest_request['status']=='accepted':
                from match_chat import screen
                return screen(sender,latest_request['id'])
            return (
                    caregiver_message(sender, "You are currently matched with ")
                    + latest_request["caregiver_name"]
                    + caregiver_message(
                        sender,
                        ".\n\nChat between buddies and contact sharing are not enabled yet.\n\n"
                        "Type 'menu' to return to the main menu.",
                        required_text="'menu'"
                    )
                )

        return caregiver_message(
                sender,
                "You are currently matched."
            )


    return caregiver_message(
        sender,
        "Type 'menu' to return to the main menu.",
        required_text="'menu'"
    )
