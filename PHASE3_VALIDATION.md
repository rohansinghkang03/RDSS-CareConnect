# Phase 3 validation — 8 November 2026

## Completed locally

- 90 automated integration/regression tests passed: existing Phase 2 behaviour plus reporting, privacy, sessions, signed callbacks, token accounting, migration checks, retention maintenance, full-case fixtures and synthetic cleanup.
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

The 30-record first batch and additional 20-record batches were generated in isolated PostgreSQL and cleaned up after export. Native formula recalculation in the spreadsheet authoring engine matched the populated cell caches for report figures and cost formulas. All 10 sheet previews were reviewed. The returned real WhatsApp attachment then exposed empty native chart caches and a daily range that retained 31 slots for seven days. Both were corrected, with direct saved-XML regression tests rather than relying on authoring-engine recalculation alone. A 31-day comparison overlap was also corrected and tested against all 62 daily rows.

| Fixture report | Active fixture caregivers | Permitted fixture profiles in summary | AI input tokens |
|---|---:|---:|---:|
| First 30 caregivers, last 7 days | 7 | 30 | 7,210 |
| All 50 caregivers, last 30 days | 50 | 50 | 62,250 |
| All 50 caregivers, full coverage cases, last 30 days | 50 | 47 | 61,330 known input tokens; two calls have incomplete usage |

Token/cost reconciliation used explicit fictional rates only in disposable verification copies. Delivered templates retain blank price placeholders. Formula error scans found no matches. Generated reports retain native charts and refreshed caches.

## First hosted WhatsApp attachment and expanded matrix

The returned `CareConnectStatistics_08-11-2026_last7d.xlsx` passed 967 data/cell-cache comparisons against the saved first-30 manifest: seven active fixture caregivers, 30 permitted profile rows, seven requests, 7,210 input tokens, 721 cached input tokens and 742 output tokens. The original received file was preserved. Its chart issues are described above; the fixed version requires the next real attachment acceptance check.

The full second batch covers 50 active people, 36 new, 11 returning and three with unknown first-seen dates; 47 permitted profile rows; every one of the 84 cells in each heatmap; all eight AI features across two models/tiers; failed and unknown usage; accepted, edited and rejected profile outcomes; refusal, withdrawal and legacy-permission exclusions; every application/request status; all four confirmed billable categories; free, failed, unconfirmed and pending-delivery messages; and current/previous period comparisons. Long and missing optional profile fields are included.

Independent native-engine checks passed for current 30 days, preceding 30 days, custom 14 days and custom 31 days. Test-rate edits reconciled known WhatsApp categories to USD 0.14 in a disposable complete-metadata copy, and the known-only preceding-period scenario to USD 3.0066 including fictional hosting/database allocations. Mixed unknown usage correctly kept overall cost unavailable despite complete price inputs. Negative-rate checks also kept estimates unavailable. Those fictional rates were restored to blank and not written into delivered files or the hosted database.

## Still required before acceptance

1. Explicit approval for the existing hosted test database migration and web-service deployment.
2. Real WhatsApp login, 7-day request after seeding the first 30 fixture records, and review of the returned attachment.
3. Add 20 fixture records, request the 30-day attachment, and reconcile its fixture rows/totals with the saved manifest.
4. Check actual Meta media permissions, asynchronous delivery callbacks and account-specific failure behaviour; these cannot be established by mocked tests.
5. Review RDSS notices, operational retention scopes, file-copy handling and verified billing rates before broader administrator use.

This is evidence of local correctness, not a guarantee of zero defects or hosted delivery. The existing Python 3.9 environment emits an old LibreSSL warning; the test run passed, but the deployed Python/TLS runtime should remain supported and maintained.
# Automatic retention follow-up — 8 November 2026

94 isolated PostgreSQL tests pass (the existing 90 plus automatic expiry/preservation, atomic rollback, cross-worker lock/restart catch-up, and disabled/retry behaviour). Three calendar years remain fixed in code; all twelve existing retention scopes are used. Background checks are opt-in with RETENTION_ENABLED=true and do not block WhatsApp requests. A durable success timestamp prevents repeated daily sweeps. No new database or paid scheduler is introduced. Free-service sleep delays cleanup until subsequent traffic; operational accounts/applications/requests and external copies remain excluded.
