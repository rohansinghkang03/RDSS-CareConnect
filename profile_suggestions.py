"""Optional AI-assisted caregiver profile suggestions."""

import json
import re

from chatbot import client, MODEL
from reporting_tracking import feature_call
from phase2_analytics import PROFILE_FIELDS


PROFILE_EXTRACTION_INSTRUCTIONS = """
You assist a caregiver in preparing a private, editable profile.

Use only facts explicitly stated in the supplied caregiver messages.
Do not infer diagnoses, relationships, financial circumstances,
or personal attributes that have not been clearly provided.

Return a JSON object containing only these optional keys:
care_recipient_profile, support_needs, availability, caregiving_context.

Each value must be a concise, plain-language string.
Use standard neutral wording in the relevant language, without slang or dialect labels.
Do not use "Singlish Malay" as a language category; standard language labels are English and Malay.
Omit any field without sufficient evidence.
Do not include names, phone numbers, addresses or identifiers.
Do not give medical advice.
Do not include any explanation outside the JSON object.
"""



from profile_validation import is_safe_profile_value

def generate_profile_suggestions(messages):
    """Generate draft suggestions; never save or approve them."""
    if not isinstance(messages, list):
        raise ValueError("Messages must be a list")

    if not messages or len(messages) > 50:
        raise ValueError("Provide between 1 and 50 messages")

    if any(not isinstance(item, str) or not item.strip()
           for item in messages):
        raise ValueError("Messages must contain nonempty text")

    # Exclude messages with obvious identifiers before AI transmission.
    sensitive_terms = re.compile(
        r"(?:https?://|www[.]|"
        r"\b(?:nric|fin|passport|address|postal|postcode|"
        r"contact number|phone number|my name is)\b)",
        re.IGNORECASE,
    )

    safe_messages = [
        message for message in messages
        if is_safe_profile_value(message)
        and not sensitive_terms.search(message)
    ]

    if not safe_messages:
        raise ValueError(
            "No messages eligible for privacy-conscious profile extraction"
        )

    response = feature_call("Profile extraction", client.responses.create,
        model=MODEL,
        instructions=PROFILE_EXTRACTION_INSTRUCTIONS,
        input=json.dumps(safe_messages, ensure_ascii=False),
        store=False,
    )

    try:
        result = json.loads(response.output_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid profile suggestion response") from exc

    if not isinstance(result, dict):
        raise ValueError("Profile suggestions must be a JSON object")

    suggestions = {}

    for field, value in result.items():
        if field not in PROFILE_FIELDS:
            continue

        if not is_safe_profile_value(value):
            continue

        suggestions[field] = value.strip()

    return suggestions


PROFILE_FIELD_LABELS = {
    "care_recipient_profile": "Care recipient",
    "support_needs": "Support needs",
    "availability": "Availability",
    "caregiving_context": "Caregiving situation",
}


def format_profile_suggestion(field_name, proposed_value):
    """Format a draft suggestion for caregiver review."""
    if field_name not in PROFILE_FIELDS:
        raise ValueError("Unsupported profile field")

    if not is_safe_profile_value(proposed_value):
        raise ValueError("Invalid profile suggestion")

    label = PROFILE_FIELD_LABELS[field_name]

    return (
        "CareConnect AI Profile 💜\n\n"
        f"Suggested {label.lower()}:\n"
        f"{proposed_value.strip()}\n\n"
        "Does this describe your situation accurately?\n\n"
        "1. Accept suggestion\n"
        "2. Edit suggestion\n"
        "3. Reject suggestion\n\n"
        "Type 'menu' to return to the main menu."
    )


def prepare_profile_review(sender):
    """Return a pending suggestion or prepare a new review."""
    from phase2_analytics import (
        get_profiling_consent,
        get_pending_profile_suggestion,
        prepare_consented_profile_context,
        get_profiling_epoch,
    )

    if get_profiling_consent(sender) != "granted":
        raise PermissionError("AI profiling consent is not active")

    pending = get_pending_profile_suggestion(sender)

    if pending is not None:
        return {
            "status": "pending",
            "suggestion": pending,
            "message": format_profile_suggestion(
                pending["field_name"],
                pending["proposed_value"],
            ),
        }

    epoch = get_profiling_epoch(sender)
    messages = prepare_consented_profile_context(sender)
    if epoch != get_profiling_epoch(sender):
        raise PermissionError("Consent changed during profile preparation")

    if not messages:
        return {
            "status": "empty",
            "suggestion": None,
            "message": (
                "There are no eligible AI Chat messages to review yet. "
                "You can continue chatting and try again later. 💜"
            ),
        }

    return {
        "status": "ready",
        "suggestion": None,
        "messages": messages,
        "consent_epoch": epoch,
        "message": (
            "Your eligible AI Chat messages are ready for "
            "profile suggestion generation."
        ),
    }


def generate_and_prepare_profile_review(sender):
    """Generate one unapproved profile suggestion for caregiver review."""
    from phase2_analytics import (
        get_profiling_consent,
        get_pending_profile_suggestion,
        propose_profile_field,
    )

    review = prepare_profile_review(sender)

    if review["status"] != "ready":
        return review

    suggestions = generate_profile_suggestions(review["messages"])

    if get_profiling_consent(sender) != "granted":
        raise PermissionError("Profiling consent is no longer active")

    existing = get_pending_profile_suggestion(sender)
    if existing is not None:
        return prepare_profile_review(sender)

    if not suggestions:
        return {
            "status": "empty",
            "suggestion": None,
            "message": (
                "There isn't enough information to suggest a profile "
                "detail yet. You can continue chatting and try again later. 💜"
            ),
        }

    for field_name in (
        "support_needs",
        "care_recipient_profile",
        "availability",
        "caregiving_context",
    ):
        if field_name not in suggestions:
            continue

        proposed_value = suggestions[field_name]

        try:
            suggestion_id = propose_profile_field(
                sender, field_name, proposed_value, expected_epoch=review["consent_epoch"]
            )
        except Exception as exc:
            # Recover only from our specific pending-suggestion index.
            if (
                getattr(exc, "pgcode", None) == "23505"
                and getattr(
                    getattr(exc, "diag", None),
                    "constraint_name",
                    None,
                ) == "uq_caregiver_one_pending_suggestion"
            ):
                return prepare_profile_review(sender)
            raise

        return {
            "status": "pending",
            "suggestion": {
                "id": suggestion_id,
                "field_name": field_name,
                "proposed_value": proposed_value,
            },
            "message": format_profile_suggestion(
                field_name, proposed_value
            ),
        }

    raise RuntimeError("No supported profile suggestion was available")
