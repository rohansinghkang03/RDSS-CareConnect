# Phase 4: conversational routing and language matching

Scope: AI assists caregiver navigation across the main menu, profile/consent/review,
resources, status, buddy matching and registration. Numbers and exact commands
remain deterministic fallbacks. Administrative PINs, notes and application records
are never sent to conversational AI; admin menus also accept fixed word aliases.

## Behaviour

- Explicit language changes are checked before a screen consumes its answer.
  Bare language names work on menus; explicit phrases work in free-text forms.
  A profile edit containing "English" remains the literal edit, while a language
  selection in a buddy application remains an answer to that field.
- Changing language preserves the current screen, consent and pending edits.
  The language-picker screen records and resumes the interrupted screen.
- The latest clear substantive message sets response language and style. Numbers,
  short acknowledgements and credentials do not reset it. Style is saved separately
  from standard language labels; Malay-English code-switching is reported as
  "English and Malay", not "Singlish Malay".
- AI decisions use a strict JSON schema plus application validation. Only known
  destinations/current option numbers reach existing handlers. The model never
  writes profile fields, approves applications, accepts requests or bypasses PINs.
- AI-inferred consequential selections ask for an explicit confirmation. Literal
  yes/no is handled only within a relevant confirmation screen. Literal yes to
  a displayed profile suggestion accepts it; no retains the edit/reject choices.
  Exact translated action phrases such as "terima cadangan" also work directly.
- Fixed reply text is adapted once at the end of the turn. Saved profile wording,
  free-text application values, generated AI replies, exact dates, URLs and command
  tokens are masked and restored unchanged. Invalid translation falls back safely.
  Known standard Malay profile text retains its established fixed fallback.
- Main-menu routing and language/style detection share one request. Preference
  extraction and AI Chat remain separately metered existing features. No prompt or
  reply text is added to reporting metadata; provider response storage is disabled.
- AI Chat instructions now consistently match casual language and explicitly forbid
  claiming a profile/preference was saved. Actual saving still requires consent and
  the existing review/confirmation flow.

## Release procedure

Run all tests on the isolated PostgreSQL cluster at localhost:55489; the test harness
asserts its data directory and creates/drops a unique schema. Real-model checks use
fictional inputs only with reporting/database writes disabled and no WhatsApp sends.
Apply phase4_schema.sql only after backup and rollback preflight. It adds a small
communication preferences table and normalises known old dialect labels, without
deleting any existing records. Existing service settings and secrets are preserved.
`python phase4_manage.py` performs the rollback preflight;
`python phase4_manage.py --apply` commits the migration on the authorised target.

Manual WhatsApp acceptance: switch language from profile/review/registration screens;
cancel withdrawal in Malay; ask for resources/status without numbers; provide multiple
registration languages/times in words; chat in informal Malay-English, Chinese, Tamil
and English; then use numbers and confirm the language persists. Verify ambiguous
consent questions do not save or delete anything. Review actual response quality and
latency; AI interpretation is fallible and numbered fallbacks remain available.

Resources still contain placeholders pending RDSS source approval. This phase does
not add unverified contacts, matching availability claims or automatic peer contact.

Communication style/resume records use the existing three-year cleanup based on
their last update, without deleting accounts. Maintenance remains compatible with
an installation before the optional communication preferences table exists.

## Validation evidence — 8 November 2026

129 automated regression checks cover Phases 2–4, including routing, consent races, report generation, retention and the new language workflows. Real-model checks used 20 fictional routing inputs plus chat/translation examples in English/Singlish, Malay-English, Chinese and Tamil. Ordinary chat is not swallowed by same-screen routing; immediate-danger wording reaches the fixed safety message. Model classifications can still vary: an instruction-bypass example returned help in one run and no validated decision in another; both paths preserve consent and leave application writes under explicit handler control. No WhatsApp messages or hosted synthetic records were created by these AI checks. Native-language user acceptance remains necessary; test evidence is not a guarantee for every possible utterance.

AI requests within one message share a 24-second wall-clock budget, including routing, extraction and translation. A depleted budget prevents another provider call; existing fixed menus/fallbacks remain available. This reduces the risk of a sequence of individually slow calls overrunning the default web worker timeout. Database/network outages can still delay service, and real user latency must be assessed in WhatsApp.
