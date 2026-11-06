# CareConnect Phase 2 deployment readiness

Local hardening is complete for the tested paths. Production release still requires the gates below. No live database access, migration, WhatsApp/AI request, push or deployment was performed during this audit.

## Changes and compatibility

- Restored the AI chat, resources, buddy onboarding, match confirmation, pending and matched branches accidentally deleted by the staged handlers.py change. Existing buddy registration and admin commands remain.
- Preserved message case through the webhook and AI chat. Fixed literal newline escapes in profile prompts. Withdrawal works from any conversation state.
- Shared conservative validation now guards proposals, original approvals, edited approvals and draft edits. Obvious contact identifiers, Unicode-obfuscated numbers, links, controls and oversized values are rejected. Names and identifiers in arbitrary free text cannot be guaranteed absent by regex screening; users must review each suggestion and staff must review the privacy wording before launch.
- Consent-row-first locking serializes profile writes with withdrawal/refusal. Both withdrawal and refusal erase profile fields, suggestions and unfinished drafts. Consent epochs reject AI outputs from a prior grant, including withdrawal followed by re-grant.
- Withdrawal cannot recall messages already transmitted to an AI provider. Historical chat messages are separate from profile data and are not deleted by profile withdrawal. The consent notice and retention policy must make this scope clear.
- Profile extraction requests set store=False. Existing chatbot operations retain their current behavior. AI timeout is 30 seconds with one retry; SQL statements and lock waits are bounded.
- Signed webhooks process every text message in batched entries. Completed message IDs are deduplicated using a SHA-256 receipt; no sender, message or reply text is stored in receipts. All actions for a sender are serialized across workers.
- Removed unauthenticated `/test/...` and `/caregiver/...` browser routes, including match-changing GET requests. Buddy decisions continue through existing WhatsApp commands. Staff relying on old browser links must switch to an authenticated workflow before launch.
- No raw message, sender, reply, HTTP response body or database traceback is logged by the new webhook/analytics/delivery paths. Existing chat history remains in its original database tables.
- App import no longer creates tables. Provision the reviewed Phase 1 schema and run the explicit Phase 2 migration before starting the new release. Procfile runs two Gunicorn workers with a 120 second timeout.

## Migration procedure (only on an explicitly approved target)

1. Verify a restorable database backup and restore it into staging. Do not use a production URL for local tests.
2. Supply a separately selected `CARECONNECT_MIGRATION_URL` in the shell; the migration utility does not load `.env` and does not default to `DATABASE_URL`. Require TLS for remote targets, with the team's chosen certificate policy.
3. Run `python tools/phase2_migrate.py`. This executes the complete migration and rolls it back. It checks prerequisites, table column signatures, required constraints, NOT NULL guards and the single-pending-suggestion index. Schema locks/timeouts are bounded.
4. Resolve any schema mismatch or duplicate pending suggestions by an explicitly reviewed repair. The migration never silently deletes duplicates. Constraint checks are deliberately conservative: equivalent constraints formatted differently on a different PostgreSQL major version can require review. Validate against the actual target major version in staging.
5. Once approved, run `python tools/phase2_migrate.py --apply`. All schema changes and the unique index commit together. Re-running is supported. The migration upgrades the older Phase 2 draft with `pending_edit_value` and `consent_epoch`.
6. Start the app only after schema success. Check the home route, webhook verification and signed synthetic text messages. Never run automatic table creation against production at import/startup.

## Failed-delivery recovery and operational limits

Receipts have `processing`, `completed`, or `failed` states. Completed duplicates are acknowledged without repeating actions. Duplicate processing/failed receipts return 503 and require reconciliation. This deliberately avoids repeating approvals, match requests or an uncertain send. Exactly-once WhatsApp delivery is not guaranteed across a process crash or a network timeout.

Before launch, assign an operator and alert on failed receipts, processing receipts older than 3 minutes, webhook 5xx, SQL timeout errors and WhatsApp delivery failures. Reconcile using the WhatsApp message ID in the authorized provider dashboard and its SHA-256 hash. Check whether the application action committed and whether delivery occurred. Do not delete or reset a receipt blindly: if the action committed, send a reviewed response through the authorized channel without repeating the action. If no action committed, a deliberate retry may be authorized. A persistent worker/outbox is a future improvement for higher throughput; this synchronous release must pass the staging load and provider timeout/retry tests first.

Agree a retention period for receipt metadata and usage events. Keep receipt hashes for at least the provider's confirmed retry window; pruning early permits replay. No automatic cleanup policy is enabled without that decision.

## One-week release plan and required gates

- Day 1–2: review this diff; install pinned requirements in a clean supported Python/OpenSSL environment; run isolated tests. The existing Mac Python 3.9 environment warns that its LibreSSL build is unsupported by urllib3 v2; use a supported runtime for staging/production and rerun checks.
- Day 3: backup/restore rehearsal and dry-run/apply/re-run on staging with the same PostgreSQL major version as production. Check existing nonempty Phase 1 and Phase 2 data, not only the synthetic fixture.
- Day 4: authorized Meta test-number end-to-end checks: signature verification, all menu choices, multilingual text, registration, buddy request/response, profile accept/edit/reject/withdrawal, duplicate and out-of-order deliveries, and timeout/crash recovery. Confirm `PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, access token, verify token and model availability.
- Day 5: privacy/retention wording review, staff signoff, load test, monitoring and receipt recovery rehearsal. Configure secrets through Render settings; never commit `.env` or backups. Confirm existing admin credentials are strong and restricted.
- Day 6: explicit user approval for live database access/migration and deployment. Take the approved backup, run preflight/apply, then deploy this reviewed commit. No production action is authorized by this document.
- Day 7: smoke checks and observation window with a named rollback owner. Roll back the application to the prior known-good commit if required; keep additive schema/data in place. Never drop Phase 2 tables as an automatic rollback.

## Local verification

Use a newly initialized disposable PostgreSQL cluster at `/tmp/careconnect-phase2-audit-pg`, listening only on `127.0.0.1:55489`, UTF-8, with no live data. The tests refuse a server with another data directory, ignore `DATABASE_URL`, create a uniquely named synthetic schema, and drop that schema afterward. They use the current OS username. Run `python -m unittest discover -s tests -v` from the repository with dependencies installed. AI and WhatsApp transport are mocked; application routing, SQL and concurrent transactions are real.

Initial cluster setup (local test only): `initdb -D /tmp/careconnect-phase2-audit-pg -A trust --no-locale --encoding=UTF8`; create `/tmp/careconnect-phase2-audit-socket`, then `pg_ctl -D /tmp/careconnect-phase2-audit-pg -l /tmp/careconnect-phase2-audit-pg.log -o '-h 127.0.0.1 -p 55489 -k /tmp/careconnect-phase2-audit-socket' start`. Stop with `pg_ctl -D /tmp/careconnect-phase2-audit-pg stop`. Never point these commands at an existing data directory. The trust-authentication test server must remain local and stopped when unused.

The automated suite covers privacy write boundaries, ownership, replay, explicit edit confirmation, refusal/withdrawal cleanup, approval and draft races in both lock orders, stale outputs after re-grant, chat-window isolation, migration reruns/data preservation/rollback/schema drift/duplicate pending rows, restored routing, signature rejection, batch/case handling, duplicate receipts, private error handling, unsafe-route removal, and signed webhook → real handler → real profile database transitions. This is local integration evidence; external provider and production release gates remain above.
