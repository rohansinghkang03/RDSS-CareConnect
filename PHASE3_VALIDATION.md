# Phase 3 validation — 8 November 2026

## Completed locally

- 86 automated integration/regression tests passed: existing Phase 2 behaviour plus reporting, privacy, sessions, signed callbacks, token accounting, migration checks, retention maintenance and synthetic cleanup.
- Tests used only the verified isolated PostgreSQL cluster on this Mac, with unique test schemas removed afterwards. WhatsApp/OpenAI requests were mocked. No hosted database connections, deployment or real messages/API calls were made.
- Migration applied repeatedly without changing report IDs or approved profile values. An incompatible column was rejected. Preflight rollback preserved data.
- Administrator checks covered approved/unapproved numbers, case-sensitive passwords, failed-attempt limits, expiry, password rotation, removal from the allowlist and logout.
- Profile tests covered original/edited outcomes, old-permission renewal, withdrawal/regrant races, unsafe legacy fields, and withdrawal during upload. Network transfers do not hold consent locks.
- Message tests covered duplicate provider callbacks, read-implies-delivery, accepted identifiers, unconfirmed sends and signed webhook handling.
- Background jobs covered duplicate requests, restricted recipient, temporary-file cleanup, removed administrators, restart recovery, and ambiguous send failures that require review rather than automatic resend.
- Cost tests covered both usage formats, failed/unknown usage, cached input, blank rates, rate edits and blank versus known-zero costs. Raw chat, phone numbers and PINs were excluded from generated reports.
- A 240-row caregiver export verified expansion beyond the original 220-row template capacity. Leading `=` input remained literal cell text.
- Three-year maintenance dry-run deleted nothing; apply removed only the deliberately expired synthetic record in its test and preserved the recent record.

## Independent workbook rehearsal

The 30-record first batch and additional 20-record batch were generated in isolated PostgreSQL and cleaned up after export. Native formula recalculation in the spreadsheet authoring engine matched the Python-populated caches for the key report figures and cost formulas. All 10 sheet previews were reviewed; chart baselines, axes and caregiver ID widths were corrected.

| Fixture report | Active fixture caregivers | Permitted fixture profiles in summary | AI input tokens |
|---|---:|---:|---:|
| First 30 caregivers, last 7 days | 7 | 30 | 7,210 |
| All 50 caregivers, last 30 days | 50 | 50 | 62,250 |

Token/cost reconciliation used explicit fictional rates only in disposable verification copies. Delivered templates retain blank price placeholders. Formula error scans found no matches. Generated reports retain native charts and refreshed caches.

## Still required before acceptance

1. Explicit approval for the existing hosted test database migration and web-service deployment.
2. Real WhatsApp login, 7-day request after seeding the first 30 fixture records, and review of the returned attachment.
3. Add 20 fixture records, request the 30-day attachment, and reconcile its fixture rows/totals with the saved manifest.
4. Check actual Meta media permissions, asynchronous delivery callbacks and account-specific failure behaviour; these cannot be established by mocked tests.
5. Review RDSS notices, operational retention scopes, file-copy handling and verified billing rates before broader administrator use.

This is evidence of local correctness, not a guarantee of zero defects or hosted delivery. The existing Python 3.9 environment emits an old LibreSSL warning; the test run passed, but the deployed Python/TLS runtime should remain supported and maintained.
