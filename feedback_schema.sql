BEGIN;
SELECT pg_advisory_xact_lock(301,7);
CREATE TABLE IF NOT EXISTS match_search_sessions (
 sender TEXT PRIMARY KEY REFERENCES users(sender) ON DELETE CASCADE,
 preference_key TEXT NOT NULL CHECK(length(preference_key)=64),
 seen_buddies INTEGER[] NOT NULL DEFAULT '{}',
 tier TEXT NOT NULL CHECK(tier IN ('exact','support','time')),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
DO $$ BEGIN
 PERFORM sender,preference_key,seen_buddies,tier,updated_at FROM match_search_sessions LIMIT 0;
END $$;
COMMIT;
