# CareConnect administrator reports

## What administrators do

1. From an approved WhatsApp number, send `admin login`.
2. Enter the existing administrator password/PIN. A successful login lasts 30 minutes.
3. Choose **4 — Download statistics (Excel)**.
4. Send **7** or **30**, or two dates such as `01-11-2026 07-11-2026`. Custom ranges support 1–31 days. The ending date cannot be in the future.
5. The bot acknowledges the request, prepares the file in the background and sends it to the requesting approved number. The file caption includes basic recorded figures.
6. Send `report status` to check progress. Send `admin logout` when finished.

`menu` returns to the administrator menu during an authenticated session. Five failed password attempts within 15 minutes temporarily block further attempts for that number. Changing the password or removing an approved number invalidates access at the next check. Each file delivery checks the current session and allowlist again.

Reports are private administrator snapshots, without an Excel opening password. Handle downloaded copies under RDSS's access and retention policy. Local temporary files are removed after generation/delivery attempts. Meta receives the uploaded attachment; successfully submitted media is not deleted immediately because WhatsApp still needs to retrieve it. Downloaded copies cannot be remotely erased by withdrawing bot consent.

## What the report means

- Dates and time bands use Singapore time. Last 7/30 days includes today, which may be incomplete. Comparisons use the preceding equal-length period.
- Active users means observed bot interactions, not WhatsApp online presence. Admin numbers are excluded from caregiver activity; message and AI totals include administrative operations.
- Old accounts do not receive an invented registration date. New/returning counts exclude accounts whose first-seen date is unknown. Registered-to-date is shown only for a report ending today.
- Individual rows require currently granted `careconnect-profiling-v2-reports` permission. Older profiling permission continues to work for existing profiling functions but does not authorise these individual exports. The updated permission screen explains the reporting purpose; existing users can read it and choose Yes to renew. Other users contribute to aggregate activity only.
- Individual fields contain approved profile values only. No chat text, phone numbers, PINs or API credentials are exported. Internal report IDs are pseudonymous, not anonymous.
- Request outcomes classify requests created in the selected period by their status at generation. Application outcomes classify each application's latest submission. Application resubmission history is not reconstructed from overwritten records.
- Search totals count completed matching attempts with an explicit result. They are not counts of people who merely opened onboarding, or of pending buddy requests.
- Profile outcome and consent action metadata contains no profile text. Consent withdrawal still deletes approved fields and suggestions immediately. A permission change or approved-field edit while a report is being prepared cancels its individual export rather than delivering a stale copy.
- Permission is rechecked immediately before upload and again before document delivery. Brief database checks release their locks before network transfers, so withdrawal never waits for an external timeout. An upload/delivery already started under valid permission cannot be recalled; downloaded or in-flight copies require separate handling.
- Incoming counts cover the valid text messages the bot processes. Accepted outgoing, provider delivery, read receipts, failures and unconfirmed attempts are distinct. Read implies delivery; duplicate status callbacks do not create extra messages.
- Provider usage is recorded for AI Chat, translation, language detection, menu routing, onboarding, preference extraction, confirmation and profile extraction. Routing/onboarding share one overview row; **AI usage** contains model/tier detail. Automatic SDK retries are disabled to avoid hidden requests. Failed calls may still have unknown provider charges.
- Input tokens include cached input. Cost formulas charge uncached and cached input separately. Rates are blank placeholders, supplied per model/tier on **AI usage** and per WhatsApp billing class on **Controls**. Use the applicable date/market rates; mixed markets may require verified weighted rates. Conversation-based or missing provider billing metadata is not treated as a known per-message charge.
- Hosting/database charges are manual allocations for the selected period. Unknown rates, classifications or usage keep the affected estimate blank. Reports are not invoices; reconcile against provider invoices.
- The professional workbook has 10 tabs, native charts, activity heatmaps, formula-linked costs and an expandable caregiver table. Generated files refresh formula and chart caches for mobile previews, while Excel recalculates formulas after editable rates change. No spreadsheet engine is required on Render.
- The current export supports up to 2,000 caregiver records and 100,000 rows per queried source. Larger datasets fail explicitly instead of being silently truncated. Historical records with unreadable timestamps are reported as exclusions. Rates with additional cache-write pricing remain unavailable rather than being understated.

## Release checklist — explicit approval required

No hosted database changes or deployment were performed while preparing this feature.

1. Review the changed code, the updated consent wording and this report scope. Confirm that the hosted target is the intended test service/database. Preserve existing backups; take an authorised database backup before applying the migration.
2. Deploy the code with `REPORTING_ENABLED=false` initially. Keep the existing administrator number list/password and WhatsApp settings. Do not put secrets in GitHub.
3. Against the approved database target, run `python phase3_manage.py preflight`. It exercises the additive migration and rolls it back. It must pass before proceeding.
4. With explicit database-change approval, run `python phase3_manage.py migrate --apply`. This creates reporting tables, indexes and transaction-bound profile event triggers. It does not erase existing profiles, applications or requests. Re-running preserves existing report IDs and coverage metadata. Triggers start recording business changes after migration even while the report UI is disabled.
5. Set `REPORTING_ENABLED=true` on the approved web service and restart/redeploy it. Keep at least one application worker running for background jobs. The existing `gunicorn app:app` start command is supported; do not use application preloading as a worker-launch mechanism. The worker starts lazily on a web request and resumes persisted queued jobs after a restart.
6. Check `/health`: reporting must be `ready`. Then log in through WhatsApp and request a report. Check access denial from an unapproved number and expiry/logout behaviour.
7. Perform the 30 + 20 synthetic reconciliation sequence below on an authorised test database. Check the returned attachments, then remove the test run. Clear `CARECONNECT_TEST_DATABASE` afterwards.
8. Review RDSS's notices, file handling and the three-year maintenance scope before opening administrator access broadly. Schedule the approved maintenance command using the team's existing operations process. No additional database service is required.

If the hosting plan suspends idle services, background work may pause until the service wakes. A subsequent `report status` message wakes the web service and resumes queued/building work. A job interrupted after it began sending is marked **review**, never blindly resent. If the report has not arrived, check the chat and request a new copy deliberately. Upload/send timeouts may have ambiguous provider outcomes.

Rollback: set `REPORTING_ENABLED=false` to stop report requests, activity/API accounting and background processing; revert application code if needed. Preserve the additive reporting tables and triggers for investigation. Do not drop tables or restore a database backup over newer records casually. Existing Phase 2 functionality must be checked after rollback.

## Three-year maintenance

`python phase3_manage.py retention` prints a dry-run count for each supported record scope. It deletes nothing. `python phase3_manage.py retention --apply` performs the approved deletion.

The helper uses three calendar years from each record's event/creation timestamp. Approved profile fields use last update; suggestions use creation; chat messages use their own creation date. It covers usage events, receipt metadata, reporting activity/facts, AI usage, outgoing/status metadata, jobs, attempts, profile fields/suggestions and conversation messages. Expired sessions are also removed on apply. Profile withdrawal is an earlier independent deletion rule.

This helper does not invent expiry dates for legacy users, erase operational buddy applications/requests, delete backups, or remove administrator-downloaded copies. RDSS must confirm the retention/renewal clock for continuing buddy membership and operational records before automating their removal. Run approved maintenance regularly; changing a workbook cell does not change server retention. No retention deletion was applied to the hosted database during development.

Automatic maintenance: set `RETENTION_ENABLED=true` on the existing web service. Each service request wakes a non-blocking cleanup check, throttled locally to once per five minutes. A database advisory lock and the durable `reporting_settings.retention_last_success` timestamp ensure a successful sweep runs at most once every 24 hours across workers/restarts. All scoped deletes and the success marker commit together; failures roll back and retry on later activity. Logs contain per-table counts only. Disable the environment flag to stop automatic sweeps; manual preview/apply remains available.

This is activity-triggered automatic maintenance, not an independent clock scheduler. On a sleeping Free Render service no code executes: an overdue sweep catches up when the next request wakes it. No new paid service is required. Exact daily execution during complete inactivity requires an independent scheduler. The same exclusions above apply; this is not a claim that every record/copy in the organisation expires automatically.

## Agreed WhatsApp reconciliation sequence

The fixture loader refuses to write unless the operator explicitly sets `CARECONNECT_TEST_DATABASE=true` for the authorised target. It never calls OpenAI or WhatsApp. Synthetic senders are visibly labelled and are not real phone numbers. Use a test service/database without caregiver traffic while these records exist.

1. `python reporting_fixtures.py seed30 --manifest reporting_test_manifests/batch30.json`
2. Save the printed run ID. This creates 30 synthetic caregiver records with dates distributed across the last 30 days. Request **7** through WhatsApp and send the returned Excel file for reconciliation. There should be **7 fixture caregivers active** in this period; all 30 permitted fixture profiles appear in the summary, with the others having zero activity for the period.
3. After reviewing that first attachment, run `python reporting_fixtures.py add20 --run-id RUN_ID --full-cases --manifest reporting_test_manifests/batch50.json`. The full-case mode adds the 20 people plus explicitly recorded historical interactions and coverage cases; it does not replace the first 30 people.
4. Request **30** through WhatsApp and send that attachment. There should now be **50 fixture caregivers active** and **47 permitted individual profile rows**. The other three are intentionally declined, withdrawn or older-permission cases. The original records are retained for this second stage, rather than replaced. All eight AI features, all weekday/time-band heatmap cells, previous-period activity, known/unknown usage and message outcomes are exercised.
5. Each manifest records exact IDs, dates, outcomes and tokens, plus independent expected 7/30-day fixture contributions. Existing records and administrator message traffic can contribute additional overall totals; compare fixture rows separately and account for the baseline rather than assuming every total must equal the fixture count.
6. Check remaining fields: edited/accepted/rejected profile outcomes; withdrawal while preparing; unknown versus zero costs; mixed models; duplicate/late callbacks; date cutoffs; unauthorised/expired sessions; upload/send failure; more than 220 caregiver rows. These cases also have automated local coverage where implemented.
7. After both attachment checks, run `python reporting_fixtures.py cleanup --run-id RUN_ID --manifest reporting_test_manifests/cleanup.json`. Cleanup deletes only records tied to that run's explicit manifest, preserving unrelated records. If the test crosses Singapore midnight, use fixed custom dates from the manifest anchor to keep the comparisons identical.

Known billing categories remain visible when another delivery lacks billing metadata; the unclassified count is shown separately and the overall WhatsApp charge remains unavailable until complete. AI usage columns explicitly show known token subtotals, with incomplete-call counts alongside them. No missing usage is priced as zero.

Do not enable test mode or seed fixtures on the hosted database without explicit target approval.

## Implementation references

- OpenAI usage fields: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create and https://developers.openai.com/api/reference/resources/responses/methods/retrieve
- Meta document-by-ID flow: https://www.postman.com/meta/whatsapp-business-platform/request/zjtbdpz/send-document-message-by-id
- Meta document object: https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/messages/document/

Prices are intentionally not embedded. API calls in the automated suite are mocked; hosted delivery and actual account permissions require the approved WhatsApp acceptance test.
