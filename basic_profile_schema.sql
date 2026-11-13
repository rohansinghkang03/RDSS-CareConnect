BEGIN;
SELECT pg_advisory_xact_lock(301,9);
CREATE TABLE IF NOT EXISTS basic_profiles (
 sender TEXT PRIMARY KEY REFERENCES users(sender) ON DELETE CASCADE,
 display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 60),
 chat_languages TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS basic_profile_drafts (
 sender TEXT PRIMARY KEY REFERENCES users(sender) ON DELETE CASCADE,
 display_name TEXT,
 chat_languages TEXT,
 destination TEXT NOT NULL DEFAULT 'profile',
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS buddy_list_sessions (
 sender TEXT PRIMARY KEY REFERENCES users(sender) ON DELETE CASCADE,
 buddy_ids INTEGER[] NOT NULL,
 preference_key TEXT NOT NULL,
 page INTEGER NOT NULL DEFAULT 0 CHECK(page>=0),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
DO $$ BEGIN
 PERFORM sender,display_name,chat_languages,updated_at FROM basic_profiles LIMIT 0;
 PERFORM sender,display_name,chat_languages,destination,updated_at FROM basic_profile_drafts LIMIT 0;
 PERFORM sender,buddy_ids,preference_key,page,updated_at FROM buddy_list_sessions LIMIT 0;
END $$;
CREATE TABLE IF NOT EXISTS admin_login_prompts (
 sender TEXT PRIMARY KEY REFERENCES users(sender) ON DELETE CASCADE,
 shown_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMIT;
