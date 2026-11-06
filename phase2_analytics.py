"""Phase 2 opt-in profile suggestions and structured analytics (PostgreSQL).

No WhatsApp message text is accepted by record_usage_event. This module is
intentionally not wired into message routing until event semantics are agreed.
"""
from database_postgres import get_connection
from profile_validation import is_safe_profile_value

EVENT_TYPES = frozenset({
    "main_menu_opened", "ai_chat_started", "resource_hub_opened", "resource_category_opened",
    "buddy_search_started", "buddy_match_found", "buddy_match_unavailable",
    "buddy_application_started", "buddy_application_submitted",
    "support_need_selected", "profile_suggestion_reviewed",
})
PROFILE_FIELDS = frozenset({
    "care_recipient_profile", "support_needs", "availability", "caregiving_context"
})


def record_usage_event(sender, event_type, category=None):
    """Record a structured event; never pass chat text as category."""
    if event_type not in EVENT_TYPES:
        raise ValueError("Unsupported analytics event")
    allowed_categories = {
        "resource_category_opened": {"1", "2", "3", "4"}
    }

    permitted = allowed_categories.get(event_type, set())

    if category is not None and (
        not isinstance(category, str) or category not in permitted
    ):
        raise ValueError("Unsupported analytics category")
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO usage_events (sender,event_type,category) VALUES (%s,%s,%s)",
                    (sender, event_type, category),
                )
    finally:
        connection.close()


def propose_profile_field(sender, field_name, proposed_value, expected_epoch=None):
    """Store a suggestion, NOT an approved profile field."""
    if field_name not in PROFILE_FIELDS:
        raise ValueError("Unsupported profile field")
    if not is_safe_profile_value(proposed_value):
        raise ValueError("Suggestion must contain text")
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT status, consent_epoch FROM caregiver_profiling_consent
                    WHERE sender=%s FOR UPDATE""",
                    (sender,),
                )
                consent_row = cursor.fetchone()
                if consent_row is None or consent_row[0] != "granted":
                    raise PermissionError("AI profiling consent is not active")
                if expected_epoch is not None and consent_row[1] != expected_epoch:
                    raise PermissionError("Consent changed during profile generation")
                cursor.execute(
                    """INSERT INTO caregiver_profile_suggestions
                    (sender,field_name,proposed_value) VALUES (%s,%s,%s)
                    RETURNING id""", (sender,field_name,proposed_value.strip()))
                return cursor.fetchone()[0]
    finally:
        connection.close()


def review_profile_suggestion(sender, suggestion_id, accept, reviewed_value=None):
    """Accept/edit or reject a suggestion owned by this caregiver atomically."""
    if not isinstance(accept, bool):
        raise ValueError("accept must be boolean")
    if accept and reviewed_value is not None and (not isinstance(reviewed_value,str) or not reviewed_value.strip()):
        raise ValueError("Edited value must contain text")
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT status FROM caregiver_profiling_consent
                    WHERE sender=%s FOR UPDATE""",
                    (sender,),
                )
                consent_row = cursor.fetchone()
                if accept and (
                    consent_row is None or consent_row[0] != "granted"
                ):
                    raise PermissionError("AI profiling consent is not active")
                cursor.execute("""SELECT field_name,proposed_value FROM caregiver_profile_suggestions
                    WHERE id=%s AND sender=%s AND status='pending' FOR UPDATE""",
                    (suggestion_id,sender))
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("Suggestion not found or already reviewed")
                field_name, proposed = row
                value = (reviewed_value.strip() if reviewed_value is not None else proposed) if accept else None
                if field_name not in PROFILE_FIELDS or (accept and not is_safe_profile_value(value)):
                    raise ValueError("Invalid profile value")
                cursor.execute("""UPDATE caregiver_profile_suggestions
                    SET status=%s,reviewed_value=%s,pending_edit_value=NULL,reviewed_at=CURRENT_TIMESTAMP
                    WHERE id=%s AND sender=%s""",
                    ('accepted' if accept else 'rejected',value,suggestion_id,sender))
                if accept:
                    cursor.execute("""INSERT INTO caregiver_profile_fields
                        (sender,field_name,field_value) VALUES (%s,%s,%s)
                        ON CONFLICT(sender,field_name) DO UPDATE
                        SET field_value=EXCLUDED.field_value,updated_at=CURRENT_TIMESTAMP""",
                        (sender,field_name,value))
    finally:
        connection.close()


def record_sharing_decision(sender, match_request_id, approved_summary=None):
    """Record explicit decision. Does not send the summary to any third party."""
    if approved_summary is not None and (not isinstance(approved_summary,str) or not approved_summary.strip()):
        raise ValueError("Summary must be nonempty if sharing")
    decision = 'share' if approved_summary is not None else 'decline'
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO caregiver_sharing_decisions
                    (sender,match_request_id,decision,approved_summary)
                    VALUES (%s,%s,%s,%s) RETURNING id""",
                    (sender,match_request_id,decision,approved_summary.strip() if approved_summary else None))
                return cursor.fetchone()[0]
    finally:
        connection.close()


PROFILING_CONSENT_VERSION = "careconnect-profiling-v1"


def get_profiling_consent(sender):
    """Return current profiling consent status; default to no consent."""
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM caregiver_profiling_consent WHERE sender=%s",
                    (sender,),
                )
                row = cursor.fetchone()
                return row[0] if row else "not_given"
    finally:
        connection.close()


def grant_profiling_consent(sender):
    """Record explicit caregiver opt-in to AI-assisted profiling."""
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO caregiver_profiling_consent
                        (sender, status, consent_version, granted_at, withdrawn_at, consent_epoch)
                    VALUES (%s, 'granted', %s, CURRENT_TIMESTAMP, NULL, 1)
                    ON CONFLICT (sender) DO UPDATE
                    SET status='granted',
                        consent_epoch=caregiver_profiling_consent.consent_epoch + 1,
                        consent_version=EXCLUDED.consent_version,
                        granted_at=CURRENT_TIMESTAMP,
                        withdrawn_at=NULL,
                        updated_at=CURRENT_TIMESTAMP
                """, (sender, PROFILING_CONSENT_VERSION))
    finally:
        connection.close()


def decline_profiling_consent(sender):
    """Refusal also erases any data from a previous grant."""
    _revoke_profiling_consent(sender, "declined")


def withdraw_profiling_consent(sender):
    """Withdraw consent and delete profiling data in one transaction."""
    _revoke_profiling_consent(sender, "withdrawn")


def _revoke_profiling_consent(sender, status):
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO caregiver_profiling_consent
                        (sender, status, withdrawn_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (sender) DO UPDATE
                    SET status=EXCLUDED.status,
                        withdrawn_at=CURRENT_TIMESTAMP,
                        updated_at=CURRENT_TIMESTAMP
                """, (sender, status))

                # Suggestions may contain sensitive proposed/reviewed text.
                # Delete them, including any unconfirmed edits.
                cursor.execute("""
                    DELETE FROM caregiver_profile_suggestions
                    WHERE sender=%s
                """, (sender,))

                # Remove all previously approved profiling fields.
                cursor.execute("""
                    DELETE FROM caregiver_profile_fields
                    WHERE sender=%s
                """, (sender,))
    finally:
        connection.close()


def get_consented_profile_messages(sender, limit=10):
    """Read caregiver messages after active profiling consent."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ValueError("Invalid message limit")

    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT cm.message
                    FROM conversation_messages AS cm
                    JOIN caregiver_profiling_consent AS consent
                      ON consent.sender = cm.sender
                    WHERE cm.sender = %s
                      AND cm.role = 'user'
                      AND consent.status = 'granted'
                      AND cm.created_at AT TIME ZONE 'UTC' >= consent.granted_at
                    ORDER BY cm.id DESC
                    LIMIT %s
                """, (sender, limit))

                rows = cursor.fetchall()
                return [row[0] for row in reversed(rows)]
    finally:
        connection.close()


def prepare_consented_profile_context(sender, limit=10):
    """Prepare profile context only while profiling consent is active."""
    if get_profiling_consent(sender) != "granted":
        raise PermissionError("AI profiling consent is not active")

    messages = get_consented_profile_messages(sender, limit=limit)

    if get_profiling_consent(sender) != "granted":
        raise PermissionError("AI profiling consent was withdrawn")

    return messages


def get_pending_profile_suggestion(sender):
    """Retrieve the oldest pending suggestion belonging to this caregiver."""
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT s.id, s.field_name, s.proposed_value
                    FROM caregiver_profile_suggestions AS s
                    JOIN caregiver_profiling_consent AS c
                      ON c.sender = s.sender
                    WHERE s.sender = %s
                      AND s.status = 'pending'
                      AND c.status = 'granted'
                    ORDER BY s.id ASC
                    LIMIT 1
                """, (sender,))

                row = cursor.fetchone()

                if row is None:
                    return None

                return {
                    "id": row[0],
                    "field_name": row[1],
                    "proposed_value": row[2],
                }
    finally:
        connection.close()


def save_pending_profile_edit(sender, suggestion_id, edited_value):
    """Store an edited draft without approving it."""

    if not is_safe_profile_value(edited_value):
        raise ValueError("Invalid edited profile value")

    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT status FROM caregiver_profiling_consent WHERE sender=%s FOR UPDATE", (sender,))
                consent = cursor.fetchone()
                if not consent or consent[0] != "granted":
                    raise PermissionError("AI profiling consent is not active")
                cursor.execute("""
                    UPDATE caregiver_profile_suggestions AS s
                    SET pending_edit_value = %s
                    WHERE s.id = %s
                      AND s.sender = %s
                      AND s.status = 'pending'
                      AND EXISTS (
                          SELECT 1
                          FROM caregiver_profiling_consent AS c
                          WHERE c.sender = s.sender
                            AND c.status = 'granted'
                      )
                    RETURNING s.id
                """, (edited_value.strip(), suggestion_id, sender))

                if cursor.fetchone() is None:
                    raise PermissionError(
                        "Suggestion unavailable or consent inactive"
                    )
    finally:
        connection.close()


def get_pending_profile_edit(sender, suggestion_id):
    """Retrieve only this caregiver's unapproved edited draft."""
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT s.pending_edit_value
                    FROM caregiver_profile_suggestions AS s
                    JOIN caregiver_profiling_consent AS c
                      ON c.sender = s.sender
                    WHERE s.id = %s
                      AND s.sender = %s
                      AND s.status = 'pending'
                      AND c.status = 'granted'
                """, (suggestion_id, sender))

                row = cursor.fetchone()
                return row[0] if row else None
    finally:
        connection.close()


def cancel_pending_profile_edit(sender, suggestion_id):
    """Discard a pending edit without approving anything."""
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE caregiver_profile_suggestions
                    SET pending_edit_value = NULL
                    WHERE id = %s
                      AND sender = %s
                      AND status = 'pending'
                """, (suggestion_id, sender))
    finally:
        connection.close()


def confirm_pending_profile_edit(sender, suggestion_id):
    """Approve an edited suggestion with consent-first locking."""
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT status
                    FROM caregiver_profiling_consent
                    WHERE sender = %s
                    FOR UPDATE
                """, (sender,))

                consent = cursor.fetchone()
                if consent is None or consent[0] != "granted":
                    raise PermissionError(
                        "Edited suggestion unavailable or consent inactive"
                    )

                cursor.execute("""
                    SELECT field_name, pending_edit_value
                    FROM caregiver_profile_suggestions
                    WHERE id = %s
                      AND sender = %s
                      AND status = 'pending'
                      AND pending_edit_value IS NOT NULL
                    FOR UPDATE
                """, (suggestion_id, sender))

                row = cursor.fetchone()
                if row is None:
                    raise PermissionError(
                        "Edited suggestion unavailable or consent inactive"
                    )

                field_name, edited_value = row

                if field_name not in PROFILE_FIELDS or not is_safe_profile_value(edited_value):
                    raise ValueError("Invalid pending edit")

                cursor.execute("""
                    UPDATE caregiver_profile_suggestions
                    SET status = 'accepted',
                        reviewed_value = %s,
                        pending_edit_value = NULL,
                        reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND sender = %s
                """, (edited_value, suggestion_id, sender))

                cursor.execute("""
                    INSERT INTO caregiver_profile_fields
                        (sender, field_name, field_value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (sender, field_name)
                    DO UPDATE SET
                        field_value = EXCLUDED.field_value,
                        updated_at = CURRENT_TIMESTAMP
                """, (sender, field_name, edited_value))
    finally:
        connection.close()


def get_profiling_epoch(sender):
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT consent_epoch FROM caregiver_profiling_consent WHERE sender=%s AND status='granted'", (sender,))
                row = cursor.fetchone()
                if row is None:
                    raise PermissionError("AI profiling consent is not active")
                return row[0]
    finally:
        connection.close()
