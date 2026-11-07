-- Explicit mutual contact-sharing consent, separate from AI profile consent.
BEGIN;
SELECT pg_advisory_xact_lock(301,5);
-- Preserve existing attempts while including button messages in usage reports.
ALTER TABLE reporting_outgoing DROP CONSTRAINT IF EXISTS reporting_outgoing_kind_check;
ALTER TABLE reporting_outgoing ADD CONSTRAINT reporting_outgoing_kind_check
 CHECK(kind IN ('text','document','interactive'));
CREATE TABLE IF NOT EXISTS match_chat_permissions (
 request_id INTEGER NOT NULL REFERENCES match_requests(id) ON DELETE CASCADE,
 sender TEXT NOT NULL REFERENCES users(sender) ON DELETE CASCADE,
 decision TEXT NOT NULL CHECK(decision IN ('granted','declined','revoked')),
 consent_version TEXT NOT NULL,
 pair_key TEXT NOT NULL CHECK(length(pair_key)=64),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(request_id,sender)
);
CREATE TABLE IF NOT EXISTS match_chat_prompts (
 sender TEXT PRIMARY KEY REFERENCES users(sender) ON DELETE CASCADE,
 request_id INTEGER NOT NULL REFERENCES match_requests(id) ON DELETE CASCADE,
 pair_key TEXT NOT NULL CHECK(length(pair_key)=64),
 shown_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS match_chat_deliveries (
 id TEXT PRIMARY KEY,
 request_id INTEGER NOT NULL REFERENCES match_requests(id) ON DELETE CASCADE,
 sender TEXT NOT NULL REFERENCES users(sender) ON DELETE CASCADE,
 outcome TEXT NOT NULL CHECK(outcome IN ('prepared','accepted','failed','unknown')),
 pair_key TEXT NOT NULL CHECK(length(pair_key)=64),
 provider_id TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS match_chat_delivery_request ON match_chat_deliveries(request_id,sender,created_at);
DO $$ BEGIN
 IF EXISTS (
   SELECT 1 FROM (VALUES
    ('match_chat_permissions','request_id','integer'),('match_chat_permissions','sender','text'),
    ('match_chat_permissions','decision','text'),('match_chat_permissions','consent_version','text'),
    ('match_chat_permissions','pair_key','text'),
    ('match_chat_permissions','updated_at','timestamp with time zone'),
    ('match_chat_deliveries','id','text'),('match_chat_deliveries','request_id','integer'),
    ('match_chat_deliveries','sender','text'),('match_chat_deliveries','outcome','text'),
    ('match_chat_deliveries','pair_key','text'),
    ('match_chat_prompts','sender','text'),('match_chat_prompts','request_id','integer'),
    ('match_chat_prompts','pair_key','text'),('match_chat_prompts','shown_at','timestamp with time zone'),
    ('match_chat_deliveries','provider_id','text'),('match_chat_deliveries','created_at','timestamp with time zone')
   ) expected(tab,col,kind)
   LEFT JOIN information_schema.columns c ON c.table_schema=current_schema()
    AND c.table_name=expected.tab AND c.column_name=expected.col
   WHERE c.data_type IS DISTINCT FROM expected.kind
 ) THEN RAISE EXCEPTION 'Unexpected direct-chat schema'; END IF;
END $$;
COMMIT;
