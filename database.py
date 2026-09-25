import sqlite3
import os

DATABASE_NAME = os.path.join(
    os.path.dirname(__file__),
    "careconnect.db"
)


def get_connection():
    return sqlite3.connect(DATABASE_NAME)


def create_tables():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS caregivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mood TEXT NOT NULL,
            support_type TEXT NOT NULL,
            availability TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            sender TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            mood TEXT,
            support_type TEXT,
            availability TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS match_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester TEXT NOT NULL,
            caregiver_name TEXT NOT NULL,
            match_percentage INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)

    connection.commit()
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
        SELECT sender, state, mood, support_type, availability
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
        "mood": row[2],
        "support_type": row[3],
        "availability": row[4]
    }


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
            mood = ?,
            support_type = ?,
            availability = ?
        WHERE sender = ?
    """, (
        new_state,
        new_mood,
        new_support_type,
        new_availability,
        sender
    ))

    connection.commit()
    connection.close()


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
        SELECT id, requester, caregiver_name, match_percentage, status
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
        "status": row[4]
    }


def get_pending_requests_for_caregiver(caregiver_name):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, requester, caregiver_name, match_percentage, status
        FROM match_requests
        WHERE caregiver_name = ?
        AND status = 'pending'
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
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE match_requests
        SET status = ?
        WHERE id = ?
    """, (
        status,
        request_id
    ))

    connection.commit()
    connection.close()


if __name__ == "__main__":
    create_tables()

    if len(get_caregivers()) == 0:
        add_caregiver(
            "Sarah",
            "Burnt out",
            "Someone to listen",
            "Evening"
        )

        add_caregiver(
            "Michelle",
            "Lonely",
            "Casual conversation",
            "Flexible"
        )

        add_caregiver(
            "Daniel",
            "Stressed",
            "Advice from another caregiver",
            "Afternoon"
        )

        add_caregiver(
            "Aisha",
            "Stressed",
            "Casual conversation",
            "Flexible"
        )

    print("CareConnect database ready.")

    print("\nCaregivers:")

    for caregiver in get_caregivers():
        print(caregiver)

    print("\nMatch requests:")

    for match_request in get_match_requests():
        print(match_request)