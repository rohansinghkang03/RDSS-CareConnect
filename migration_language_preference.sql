-- CareConnect language preference migration
-- Adds optional language storage to existing caregiver profiles.
-- Does not delete or overwrite existing records.

ALTER TABLE users
ADD COLUMN IF NOT EXISTS language_preference TEXT;
