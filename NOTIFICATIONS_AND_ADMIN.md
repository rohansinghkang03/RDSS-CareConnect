# Admin help, navigation and operational alerts

Admin help is limited to report requests (last 7/30 days), opening pending applications and application counts. The approved phone number and current PIN session are checked before interpretation. PIN, note and application-review screens never use this classifier. It cannot approve, reject, verify, delete, edit records, change access, alter report recipients or invent dates. Common wording works without a model. Unknown names, identifiers, credentials and out-of-vocabulary text stay out of AI; unknown requests fall back to the numbered menu. Custom date ranges retain their existing explicit format.

Secondary navigation is grouped under “You can type these other commands too:”. Primary choices and free text remain unchanged. Commands vary by screen, and the existing final translation protects literal commands and private values.

## Alerts

With `NOTIFICATIONS_ENABLED=true`, new application consent and connection-request confirmation explain WhatsApp updates. Existing users/admins can type `notifications on`. Type `notifications off`, `stop notifications`, `stop alerts`, `unsubscribe` or `stop` to stop alerts. Profile consent, contact-sharing permission and notification settings are independent. Login still needs the normal PIN; notification commands do not grant access.

New events are inserted into a durable outbox in the same transaction as the application/request decision. Events cover new applications (opted-in, still-approved admin numbers), application approval/rejection/verification, new incoming connections, accepted/declined connections, and mutual chat readiness. Submissions and sent requests are also acknowledged in the normal reply. No historical events are backfilled. Alerts contain no names, private notes, phone numbers or direct contact URLs. They do not move the recipient out of their current screen. The existing translation layer adapts the fixed notice to their established language/style; private records are never submitted for translation.

The worker rechecks current event validity and subscription before sending. Changed outcomes and obsolete application review versions cancel stale events. A unique key and row claims prevent duplicates across workers. Definitive provider rejection becomes failed; ambiguous delivery becomes unknown and is never blindly retried. Network sends do not hold database locks. Withdrawal cannot recall a message already released/in flight. Pending notices expire after 30 days; metadata is included in three-year retention.

## Platform limit and remaining setup

Free-form alerts send only while the recipient's latest inbound message is under 23 hours 55 minutes old (a safety margin within WhatsApp's 24-hour service window). Outside that window, they remain queued for the recipient's next message. No unapproved template is sent. Fully proactive closed-window delivery remains pending Meta-approved utility templates and their integration; this release does not claim that capability.

The existing free Render service resumes the queue on service activity and after replies. It can sleep while idle; this is not a continuously running or guaranteed immediate notification service. No paid service was added. WhatsApp acceptance is not a delivery/read receipt.

Apply `notifications_schema.sql` explicitly after a database backup and rollback preflight. It adds two tables, without changing existing account data. Feature flag defaults off. Validate isolated tests before setting it true. Disable the flag to stop processing without changing contact/profile permissions.

Reference: https://whatsappbusiness.com/policy/
