# Connection and verification updates — local review

These changes are prepared for review. They have not been pushed or deployed, and the Render database has not been changed.

## User-visible changes

- Registration answers no longer change the interface language implicitly. Explicit language-switch requests preserve the current question and never become an introduction. Offered languages are parsed separately from the interface language.
- New connection requests collect a chosen name and an optional short message, then show exactly what will be shared before the caregiver sends the request. Existing requests without these fields do not expose private account names or AI conversations.
- Support Buddies consent to WhatsApp number sharing during registration or through their own profile settings. A caregiver separately agrees for the selected buddy when sending a request. The buddy sees the disclosure before accepting; one acceptance completes the handoff when both permissions are current.
- Legacy requests/accounts receive explicit permission steps where needed. Acceptance notifications point to the actual connection and use the chat button when permission checks allow it.
- An already accepted connection offers continuing the existing chat or finding someone else. Previous suggestions can be revisited without changing preferences.
- Support Buddies can preview and confirm a public display-name correction. Private identity, approval and verification are unchanged. New numeric-only display names are rejected.
- Incoming requests show the approved chosen name/message, explain each request command separately, and use appropriate navigation. All new caregiver copy uses the existing translation layer; private names/messages are protected from translation.
- Read-only admin requests recognize “are there any new applications”. Decisions still require explicit numbered choices.
- Every pending application requires named verification before approval becomes available. Verification asks for the administrator's full name, followed by numbered confirmation. The application shows that name and the verification time. The audit also records the authenticated administrator identity. Cancellation, expired drafts and changed applications cannot complete verification. Existing approved accounts are unchanged.

## Activation for a future approved deployment

1. Preserve a database backup and review the migration against the target schema.
2. Run `connection_request_v2_schema.sql` transactionally. It creates separate request, permission, public-name audit and administrator verification draft tables and adds nullable `verified_by_name`. It does not delete existing data. Re-running it preserves records; schema mismatches abort the transaction.
3. Set `CONNECTION_REQUEST_V2_ENABLED=true` only after the migration. The example configuration defaults to false. Existing match-chat and notification switches remain necessary for those features.
4. Deploy only after owner approval, check readiness, then test both WhatsApp accounts. No production migration or deployment is part of this local batch.

Temporary private inputs expire after 30 minutes for decisions. The existing three-year retention mechanism includes the new tables. No new application or report content is sent to AI for administrator verification.

## Validation

The complete isolated PostgreSQL test suite covers existing flows and the new language, request privacy, number-sharing, legacy compatibility, public-name editing, verification and migration cases. WhatsApp and AI calls are mocked; fixtures are synthetic. See the accompanying test log for the final result.

## 10 November — compact message follow-up (uncommitted)

Routine footers show Back, Menu and Help; contextual Help expands the available commands without changing progress or sending private input to AI. Primary actions stay in the message. Admin PIN screens retain only cancellation navigation. Generic choice guidance is shorter. Invalid consent replies repeat the choices without the full screen; original consent disclosures and explicit numbered decisions remain intact.

Registration and admin reviews preview introductions longer than 160 characters. `full introduction` displays the exact stored text without changing it; admin access still requires the current authorised session. Status, verification and decision options appear before admin application details. Profile privacy has a short summary and `privacy details` for the explanation. Fixed Malay profile wording is preserved. Only the public display name is editable in the Support Buddy profile; other application fields are outside this change.

These edits remain local and uncommitted, alongside the screenshot fixes. Safety-conversation recording remains a proposal only.
