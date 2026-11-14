# Personal profile release and stress review

## Minor issues fixed

- Main menu greets the confirmed public display name. Completing a new basic account opens that personal main menu.
- Support Buddy real name remains a separate private RDSS verification field; shared display name and languages supply public listings.
- Accepted connections now show the counterpart's current public display name on both sides, without exposing private full names.
- AI profiling withdrawal directions follow the new nested My profile > AI profile and privacy settings > Withdraw permission menu.
- Clean-slate operator reset empties personal records, saved languages, forms, sessions, matching/chat permissions and queued reports/alerts. Admin numbers/PIN remain environment configuration; sessions are re-created by login. Unknown database tables cause a refusal rather than blind deletion.

## Validation

379 complete isolated regression checks passed, followed by 51 role/profile checks after the final first-account menu adjustment. New role journeys cover profile creation, buddy application with separate private name, named admin verification/approval, incoming requests, single acceptance, both chat views, language barriers, expired/foreign list selection, adversarial fields and preservation of admin login after reset.

Concurrency stress submitted 48 duplicate confirmations and 48 duplicate acceptances through 12 workers. Exactly one request and two participant permissions remained. Existing suites also cover profile consent/withdrawal races, notification/report failures, report periods, request ownership and language/script handling. All test WhatsApp and AI calls are mocked; no stress traffic is sent to real users.

Both schema migrations were restored and rehearsed against a fresh private database dump, applied twice without changing existing data, and the clean-slate procedure was rehearsed locally before use. Backup comparisons normalize UTC timestamps to avoid false differences between local and Render time zones.

## Larger matters requiring team decisions

No new blocking defect was found by this automated run. The following existing limits remain and are not claimed solved:

- External private WhatsApp chats are unmoderated and unreadable by CareConnect. Complaints, suspension and safety escalation remain separate planned work, requiring human ownership.
- Buddy schedules are stated preferences, not live presence. Matching must not claim someone is currently online.
- Proactive WhatsApp delivery remains subject to Meta's messaging window/template rules and valid credentials. The bot cannot promise delivery outside the permitted channel conditions.
- Resource content still needs RDSS approval. The final privacy wording, operational responsibilities and SOP need RDSS review.
- Automated tests cannot establish the quality of every real AI translation or every handset/button interaction. A live two-phone acceptance pass is still required after deployment.
