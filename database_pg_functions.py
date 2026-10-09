"""PostgreSQL database implementation for RDSS CareConnect.

Keep database_sqlite.py and the SQLite .db backup unchanged.
This module uses the 10-table schema already defined in database_postgres.py.
"""
import re
from database_postgres import get_connection as _pg_connect, create_tables as _create_tables


class _Row(dict):
    """Support both row[0] and row['column'] like sqlite3.Row."""
    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class _Cursor:
    def __init__(self, connection):
        self._cursor = connection._connection.cursor()
        self.lastrowid = None

    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        if re.search(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', sql, re.I):
            sql = re.sub(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', 'INSERT INTO', sql, flags=re.I)
            sql += ' ON CONFLICT DO NOTHING'
        self._cursor.execute(sql, params)
        if re.search(r'\bRETURNING\s+id\b', sql, re.I):
            result = self._cursor.fetchone()
            self.lastrowid = result[0] if result else None
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._row(row) if row is not None else None

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]

    def _row(self, row):
        names = [col[0] for col in self._cursor.description]
        return _Row(names, row)

    def __iter__(self):
        for row in self._cursor:
            yield self._row(row)


class _Connection:
    def __init__(self):
        self._connection = _pg_connect()
        self.row_factory = None

    def cursor(self):
        return _Cursor(self)

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def get_connection():
    return _Connection()


def create_tables():
    """Create schema and enforce one pending request per buddy pair."""
    _create_tables()
    connection = get_connection()
    try:
        with connection:
            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS unique_pending_buddy_pair
                ON match_requests (requester, buddy_id, buddy_sender)
                WHERE status = 'pending' AND buddy_id IS NOT NULL
            """)
    finally:
        connection.close()


def add_caregiver(name, mood, support_type, availability):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO caregivers (
            name,
            mood,
            support_type,
            availability
        )
        VALUES (?, ?, ?, ?)
    """, (
        name,
        mood,
        support_type,
        availability
    ))

    connection.commit()
    connection.close()


def get_caregivers():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, name, mood, support_type, availability
        FROM caregivers
    """)

    rows = cursor.fetchall()
    connection.close()

    caregivers = []

    for row in rows:
        caregivers.append({
            "id": row[0],
            "name": row[1],
            "mood": row[2],
            "support_type": row[3],
            "availability": row[4]
        })

    return caregivers


def get_user(sender):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT sender, state, full_name, mood, support_type, availability,
               language_preference
        FROM users
        WHERE sender = ?
    """, (sender,))

    row = cursor.fetchone()
    connection.close()

    if row is None:
        return None

    return {
        "sender": row[0],
        "state": row[1],
        "full_name": row[2],
        "mood": row[3],
        "support_type": row[4],
        "availability": row[5],
        "language_preference": row[6]
    }


def get_language_preference(sender):
    """Read a short language label without loading conversation history."""
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT language_preference FROM users WHERE sender = ?",
            (sender,)
        ).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def set_language_preference(sender, language):
    """Store only a validated language label, never caregiver message text."""
    if not isinstance(language, str) or not language or len(language) > 80:
        raise ValueError("Invalid language preference")
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO users (sender, state, language_preference) "
                "VALUES (?, 'main_menu', ?) "
                "ON CONFLICT (sender) DO UPDATE "
                "SET language_preference = EXCLUDED.language_preference",
                (sender, language)
            )
    finally:
        connection.close()


def create_user(sender):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO users (
            sender,
            state
        )
        VALUES (?, ?)
    """, (
        sender,
        "main_menu"
    ))

    connection.commit()
    connection.close()


def update_user(
    sender,
    state=None,
    full_name=None,
    mood=None,
    support_type=None,
    availability=None
):
    current_user = get_user(sender)

    if current_user is None:
        create_user(sender)
        current_user = get_user(sender)

    connection = get_connection()
    cursor = connection.cursor()

    new_state = state if state is not None else current_user["state"]
    new_full_name = (
        full_name
        if full_name is not None
        else current_user["full_name"]
    )
    new_mood = mood if mood is not None else current_user["mood"]

    new_support_type = (
        support_type
        if support_type is not None
        else current_user["support_type"]
    )

    new_availability = (
        availability
        if availability is not None
        else current_user["availability"]
    )

    cursor.execute("""
        UPDATE users
        SET
            state = ?,
            full_name = ?,
            mood = ?,
            support_type = ?,
            availability = ?
        WHERE sender = ?
    """, (
        new_state,
        new_full_name,
        new_mood,
        new_support_type,
        new_availability,
        sender
    ))

    connection.commit()
    connection.close()

# Only explicit submission creates a pending application. Older empty application
# rows are retained, but submitted_at distinguishes them from real submissions.
SUPPORT_BUDDY_FIELDS = (
    "full_name", "rdss_member", "display_name", "languages",
    "caregiver_experience", "support_types", "availability", "contact_methods",
    "introduction", "verification_required", "consent", "consent_text", "consent_at"
)
_UNSET = object()


def get_support_buddy_draft(sender):
    connection = get_connection()
    try:
        connection.row_factory = None  # PostgreSQL rows support names and positions
        row = connection.execute(
            "SELECT * FROM support_buddy_drafts WHERE sender = ?", (sender,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def get_support_buddy_application(sender):
    connection = get_connection()
    try:
        connection.row_factory = None  # PostgreSQL rows support names and positions
        row = connection.execute(
            "SELECT * FROM support_buddy_applications "
            "WHERE sender = ? AND submitted_at IS NOT NULL", (sender,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def start_support_buddy_draft(sender):
    """Resume an existing draft without erasing answers."""
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO support_buddy_drafts (sender) VALUES (?)",
                (sender,)
            )
    finally:
        connection.close()


def update_support_buddy_draft(
    sender, full_name=_UNSET, rdss_member=_UNSET, display_name=_UNSET,
    languages=_UNSET, caregiver_experience=_UNSET, support_types=_UNSET,
    availability=_UNSET, contact_methods=_UNSET, verification_required=_UNSET,
    introduction=_UNSET
):
    # An omitted argument preserves its value; explicit None clears it.
    values = locals().copy()
    changes = {key: value for key, value in values.items()
               if key in SUPPORT_BUDDY_FIELDS and value is not _UNSET}
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO support_buddy_drafts (sender) VALUES (?)", (sender,)
            )
            if changes:
                assignments = ", ".join(key + " = ?" for key in changes)
                connection.execute(
                    "UPDATE support_buddy_drafts SET " + assignments +
                    ", consent = 0, consent_text = NULL, consent_at = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE sender = ?",
                    tuple(changes.values()) + (sender,)
                )
    finally:
        connection.close()


def cancel_support_buddy_draft(sender):
    connection = get_connection()
    try:
        with connection:
            connection.execute("DELETE FROM support_buddy_drafts WHERE sender = ?", (sender,))
            connection.execute("UPDATE users SET state = 'main_menu' WHERE sender = ?", (sender,))
    finally:
        connection.close()


def submit_support_buddy_application(sender, consent_text):
    """Atomically save a complete, consented application; repeated submits are safe."""
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        with connection:
            connection.execute("SELECT 1")  # Transaction already active; row locks below
            existing = connection.execute(
                "SELECT * FROM support_buddy_applications WHERE sender = ?", (sender,)
            ).fetchone()
            if existing and existing["submitted_at"] and existing["status"] not in ("rejected", "declined"):
                return False
            draft = connection.execute(
                "SELECT * FROM support_buddy_drafts WHERE sender = ? FOR UPDATE", (sender,)
            ).fetchone()
            required = ("full_name", "rdss_member", "languages", "caregiver_experience",
                        "support_types", "availability", "contact_methods")
            if not draft or any(not draft[key] for key in required):
                raise ValueError("Please complete the registration questions first.")
            if draft["display_name"] is None or draft["introduction"] is None:
                raise ValueError("Please answer or skip the optional questions first.")
            if not consent_text:
                raise ValueError("Consent is required to submit.")
            now = connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
            values = dict(draft)
            values.update(consent=1, consent_text=consent_text, consent_at=now,
                          verification_required=int(draft["rdss_member"] == "No"))
            columns = ", ".join(SUPPORT_BUDDY_FIELDS)
            placeholders = ", ".join("?" for _ in SUPPORT_BUDDY_FIELDS)
            updates = ", ".join(key + " = excluded." + key for key in SUPPORT_BUDDY_FIELDS)
            connection.execute(
                "INSERT INTO support_buddy_applications (sender, " + columns +
                ", status, submitted_at) VALUES (?, " + placeholders + ", 'pending', ?) "
                "ON CONFLICT(sender) DO UPDATE SET " + updates +
                ", status = 'pending', submitted_at = excluded.submitted_at, "
                "admin_notes = '', verified_at = NULL, verified_by = NULL, "
                "reviewed_at = NULL, reviewed_by = NULL, "
                "review_version = support_buddy_applications.review_version + 1",
                (sender,) + tuple(values[key] for key in SUPPORT_BUDDY_FIELDS) + (now,)
            )
            connection.execute("DELETE FROM support_buddy_drafts WHERE sender = ?", (sender,))
            connection.execute(
                "UPDATE users SET state = 'buddy_registration_submitted' WHERE sender = ?", (sender,)
            )
            return True
    finally:
        connection.close()


def create_support_buddy_application(sender):
    """Compatibility entry point: registration starts a draft, not a submission."""
    start_support_buddy_draft(sender)


def reset_user(sender):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE users
        SET
            state = 'main_menu',
            mood = NULL,
            support_type = NULL,
            availability = NULL
        WHERE sender = ?
    """, (sender,))

    cursor.execute("DELETE FROM match_previews WHERE requester = ?", (sender,))
    connection.commit()
    connection.close()


def create_match_request(
    requester,
    caregiver_name,
    match_percentage
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO match_requests (
            requester,
            caregiver_name,
            match_percentage,
            status
        )
        VALUES (?, ?, ?, ?)
    """, (
        requester,
        caregiver_name,
        match_percentage,
        "pending"
    ))

    connection.commit()
    connection.close()


def get_match_requests():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, requester, caregiver_name, match_percentage, status
        FROM match_requests
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()
    connection.close()

    requests = []

    for row in rows:
        requests.append({
            "id": row[0],
            "requester": row[1],
            "caregiver_name": row[2],
            "match_percentage": row[3],
            "status": row[4]
        })

    return requests


def get_latest_match_request(requester):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, requester, caregiver_name, match_percentage, status, buddy_id
        FROM match_requests
        WHERE requester = ?
        ORDER BY id DESC
        LIMIT 1
    """, (requester,))

    row = cursor.fetchone()
    connection.close()

    if row is None:
        return None

    return {
        "id": row[0],
        "requester": row[1],
        "caregiver_name": row[2],
        "match_percentage": row[3],
        "status": row[4],
        "buddy_id": row[5]
    }


def get_pending_requests_for_caregiver(caregiver_name):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, requester, caregiver_name, match_percentage, status
        FROM match_requests
        WHERE caregiver_name = ?
        AND status = 'pending'
        AND buddy_id IS NULL AND buddy_sender IS NULL
        ORDER BY id ASC
    """, (caregiver_name,))

    rows = cursor.fetchall()
    connection.close()

    requests = []

    for row in rows:
        requests.append({
            "id": row[0],
            "requester": row[1],
            "caregiver_name": row[2],
            "match_percentage": row[3],
            "status": row[4]
        })

    return requests


def update_match_request_status(request_id, status):
    """Legacy demo requests only; identified requests require their recipient."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE match_requests
        SET status = ?
        WHERE id = ?
          AND buddy_id IS NULL AND buddy_sender IS NULL
    """, (
        status,
        request_id
    ))

    connection.commit()
    connection.close()


def save_match_preview(requester, match, user):
    """Persist the displayed choice and its score, including across restarts."""
    connection = get_connection()
    try:
        with connection:
            connection.execute("""
                INSERT INTO match_previews
                    (requester, buddy_id, buddy_sender, caregiver_name,
                     match_percentage, support_type, availability)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (requester) DO UPDATE SET
                    buddy_id = EXCLUDED.buddy_id,
                    buddy_sender = EXCLUDED.buddy_sender,
                    caregiver_name = EXCLUDED.caregiver_name,
                    match_percentage = EXCLUDED.match_percentage,
                    support_type = EXCLUDED.support_type,
                    availability = EXCLUDED.availability
            """, (requester, match["buddy_id"], match["sender"], match["name"],
                  match["percentage"], user.get("support_type"), user.get("availability")))
            connection.execute("UPDATE users SET state = 'confirm_match' WHERE sender = ?", (requester,))
    finally:
        connection.close()


def _eligible_buddy(connection, buddy_id, sender):
    return connection.execute("""
        SELECT id FROM support_buddy_applications
        WHERE id = ? AND sender = ? AND status = 'approved'
          AND submitted_at IS NOT NULL AND consent = 1
          AND (verification_required = 0 OR verified_at IS NOT NULL)
    """, (buddy_id, sender)).fetchone() is not None


def create_selected_match_request(requester):
    """Consume one preview atomically. Never select a replacement on confirm."""
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        with connection:
            connection.execute("SELECT 1")  # Transaction already active; row locks below
            preview = connection.execute(
                "SELECT * FROM match_previews WHERE requester = ? FOR UPDATE", (requester,)
            ).fetchone()
            if preview is None:
                return "missing", None
            if preview["buddy_sender"] == requester or not _eligible_buddy(
                connection, preview["buddy_id"], preview["buddy_sender"]
            ):
                connection.execute("DELETE FROM match_previews WHERE requester = ?", (requester,))
                connection.execute("UPDATE users SET state = 'main_menu' WHERE sender = ?", (requester,))
                return "unavailable", None

            # A retried confirmation or another search must not duplicate a pending request.
            existing = connection.execute("""
                SELECT * FROM match_requests
                WHERE requester = ? AND buddy_id = ? AND buddy_sender = ? AND status = 'pending'
                ORDER BY id DESC LIMIT 1
            """, (requester, preview["buddy_id"], preview["buddy_sender"])).fetchone()
            if existing is None:
                cursor = connection.execute("""
                    INSERT INTO match_requests
                        (requester, caregiver_name, match_percentage, status, buddy_id,
                         buddy_sender, support_type, availability, created_at)
                    VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    RETURNING id
                """, (requester, preview["caregiver_name"], preview["match_percentage"],
                      preview["buddy_id"], preview["buddy_sender"],
                      preview["support_type"], preview["availability"]))
                request = connection.execute(
                    "SELECT * FROM match_requests WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
                outcome = "created"
            else:
                request = existing
                outcome = "existing"
            connection.execute("DELETE FROM match_previews WHERE requester = ?", (requester,))
            connection.execute("UPDATE users SET state = 'match_pending' WHERE sender = ?", (requester,))
            return outcome, dict(request)
    finally:
        connection.close()


def get_buddy_requests(sender, page=1, page_size=5):
    """Only the recipient's pending requests; names are never used for routing."""
    page = max(1, page)
    page_size = max(1, min(5, page_size))
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        rows = connection.execute("""
            SELECT r.* FROM match_requests r
            JOIN support_buddy_applications b ON b.id = r.buddy_id AND b.sender = r.buddy_sender
            WHERE r.buddy_sender = ? AND r.status = 'pending'
            ORDER BY r.id ASC LIMIT ? OFFSET ?
        """, (sender, page_size + 1, (page - 1) * page_size)).fetchall()
        return [dict(row) for row in rows[:page_size]], len(rows) > page_size
    finally:
        connection.close()


def get_buddy_request(sender, request_id):
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        row = connection.execute("""
            SELECT r.* FROM match_requests r
            JOIN support_buddy_applications b ON b.id = r.buddy_id AND b.sender = r.buddy_sender
            WHERE r.id = ? AND r.buddy_sender = ?
        """, (request_id, sender)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def respond_to_buddy_request(sender, request_id, decision):
    """Authorize the recipient and resolve a pending request in one transaction."""
    if decision not in ("accepted", "declined"):
        raise ValueError("Choose accepted or declined.")
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        with connection:
            connection.execute("SELECT 1")  # Transaction already active; row locks below
            row = connection.execute("""
                SELECT r.* FROM match_requests r
                JOIN support_buddy_applications b ON b.id = r.buddy_id AND b.sender = r.buddy_sender
                WHERE r.id = ? AND r.buddy_sender = ?
                FOR UPDATE OF r
            """, (request_id, sender)).fetchone()
            if row is None:
                return "not_found", None
            if row["status"] != "pending":
                return "already_resolved", dict(row)
            if decision == "accepted" and not _eligible_buddy(connection, row["buddy_id"], sender):
                return "unavailable", dict(row)
            connection.execute("""
                UPDATE match_requests SET status = ?, responded_at = CURRENT_TIMESTAMP
                WHERE id = ? AND buddy_sender = ? AND status = 'pending'
            """, (decision, request_id, sender))
            result = dict(row)
            result["status"] = decision
            return "updated", result
    finally:
        connection.close()


def save_conversation_message(sender, role, message):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO conversation_messages (
            sender,
            role,
            message
        )
        VALUES (?, ?, ?)
    """, (
        sender,
        role,
        message
    ))

    connection.commit()
    connection.close()


def get_recent_conversation(sender, limit=10):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT role, message
        FROM conversation_messages
        WHERE sender = ?
        ORDER BY id DESC
        LIMIT ?
    """, (
        sender,
        limit
    ))

    rows = cursor.fetchall()
    connection.close()

    rows.reverse()

    messages = []

    for row in rows:
        messages.append({
            "role": row[0],
            "content": row[1]
        })

    return messages


def clear_conversation(sender):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM conversation_messages
        WHERE sender = ?
    """, (sender,))

    connection.commit()
    connection.close()


# Admin queries only return explicitly submitted applications.
def list_admin_applications(status="pending", page=1, page_size=25):
    if status not in ("pending", "approved", "rejected", "all"):
        raise ValueError("Invalid application filter.")
    page = max(1, page)
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        where = "submitted_at IS NOT NULL"
        params = []
        if status == "rejected":
            where += " AND status IN ('rejected', 'declined')"
        elif status != "all":
            where += " AND status = ?"
            params.append(status)
        count = connection.execute(
            "SELECT COUNT(*) FROM support_buddy_applications WHERE " + where, params
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT id, full_name, display_name, rdss_member, status, submitted_at, "
            "verification_required, verified_at FROM support_buddy_applications WHERE " + where +
            " ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, submitted_at DESC, id DESC "
            "LIMIT ? OFFSET ?", params + [page_size, (page - 1) * page_size]
        ).fetchall()
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        for row in connection.execute(
            "SELECT status, COUNT(*) AS total FROM support_buddy_applications "
            "WHERE submitted_at IS NOT NULL GROUP BY status"
        ):
            key = "rejected" if row["status"] == "declined" else row["status"]
            counts[key] = counts.get(key, 0) + row["total"]
        return [dict(row) for row in rows], count, counts
    finally:
        connection.close()


def get_admin_application(application_id):
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        row = connection.execute(
            "SELECT * FROM support_buddy_applications WHERE id = ? AND submitted_at IS NOT NULL",
            (application_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def get_admin_review_events(application_id):
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM admin_review_events WHERE application_id = ? ORDER BY id DESC",
            (application_id,)
        )]
    finally:
        connection.close()


def review_support_buddy_application(application_id, action, notes, actor, version):
    if action not in ("notes", "verify", "approve", "reject"):
        raise ValueError("Unknown review action.")
    if len(notes) > 4000:
        raise ValueError("Please keep notes to 4,000 characters or fewer.")
    connection = get_connection()
    connection.row_factory = None  # PostgreSQL rows support names and positions
    try:
        with connection:
            connection.execute("SELECT 1")  # Transaction already active; row locks below
            row = connection.execute(
                "SELECT * FROM support_buddy_applications WHERE id = ? AND submitted_at IS NOT NULL FOR UPDATE",
                (application_id,)
            ).fetchone()
            if row is None:
                raise LookupError("Application not found.")
            if row["review_version"] != version:
                raise ValueError("This application changed since you opened it. Reload it before saving.")
            if action != "notes" and row["status"] != "pending":
                raise ValueError("This application has already been reviewed.")
            if action == "verify" and not row["verification_required"]:
                raise ValueError("This applicant does not need extra verification.")
            if action == "verify" and row["verified_at"]:
                raise ValueError("Verification is already complete.")
            if action == "approve":
                if row["verification_required"] and not row["verified_at"]:
                    raise ValueError("Complete non-member verification before approving.")
                if not row["consent"] or not row["consent_at"] or not row["consent_text"]:
                    raise ValueError("The applicant must give consent before approval.")
            updates = {"admin_notes": notes, "review_version": version + 1}
            now = connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
            if action == "verify":
                updates.update(verified_at=now, verified_by=actor)
            elif action in ("approve", "reject"):
                updates.update(status="approved" if action == "approve" else "rejected",
                               reviewed_at=now, reviewed_by=actor)
            connection.execute(
                "UPDATE support_buddy_applications SET " + ", ".join(key + " = ?" for key in updates) +
                " WHERE id = ?", tuple(updates.values()) + (application_id,)
            )
            connection.execute(
                "INSERT INTO admin_review_events (application_id, action, actor, notes) VALUES (?, ?, ?, ?)",
                (application_id, action, actor, notes)
            )
    finally:
        connection.close()


def get_approved_support_buddies():
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                sender,
                display_name,
                support_types,
                availability
            FROM support_buddy_applications
            WHERE status = 'approved'
              AND submitted_at IS NOT NULL
              AND consent = 1
              AND (
                  verification_required = 0
                  OR verified_at IS NOT NULL
              )
            ORDER BY id
        """)

        rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "sender": row[1],
                "name": row[2] or "Support Buddy",
                "support_types": row[3] or "",
                "availability": row[4] or ""
            }
            for row in rows
        ]

    finally:
        connection.close()
