-- Additive preferences only. No conversation text, profile data or credentials.
BEGIN;
SELECT pg_advisory_xact_lock(301,4);
CREATE TABLE IF NOT EXISTS communication_preferences (
 sender TEXT PRIMARY KEY REFERENCES users(sender) ON DELETE CASCADE,
 style TEXT NOT NULL DEFAULT 'standard' CHECK(style IN ('standard','casual','singlish','casual-mixed','romanised')),
 resume_state TEXT,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
DO $$ BEGIN
 IF EXISTS (
   SELECT 1 FROM (VALUES ('sender','text'),('style','text'),('resume_state','text'),
     ('updated_at','timestamp with time zone')) expected(name,kind)
   LEFT JOIN information_schema.columns c ON c.table_schema=current_schema()
     AND c.table_name='communication_preferences' AND c.column_name=expected.name
   WHERE c.data_type IS DISTINCT FROM expected.kind
 ) THEN RAISE EXCEPTION 'Unexpected communication preferences schema'; END IF;
END $$;
-- Normalise old dialect labels for individual reports, keeping style separately.
INSERT INTO communication_preferences(sender,style)
 SELECT sender,CASE WHEN lower(language_preference)='singlish malay' THEN 'casual-mixed' ELSE 'singlish' END
 FROM users WHERE lower(language_preference) IN ('singlish','english with singlish expressions','singlish malay')
 ON CONFLICT(sender) DO NOTHING;
UPDATE users SET language_preference=CASE lower(language_preference)
 WHEN 'singlish' THEN 'English' WHEN 'english with singlish expressions' THEN 'English'
 WHEN 'singlish malay' THEN 'English and Malay' WHEN 'malay and english' THEN 'English and Malay'
 WHEN 'bahasa melayu' THEN 'Malay' WHEN 'bahasa malaysia' THEN 'Malay'
 ELSE language_preference END
 WHERE lower(language_preference) IN ('singlish','english with singlish expressions','singlish malay',
   'malay and english','bahasa melayu','bahasa malaysia');
COMMIT;
