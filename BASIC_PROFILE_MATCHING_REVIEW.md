# Shared basic profile and buddy directory

Prepared for GitHub review. Deployment and feature activation remain separate.

## Behaviour

Everyone has one confirmed basic profile linked to their WhatsApp account: a public display name and languages they can comfortably use in a buddy chat. Bot reply language remains independent. First-time language selection opens the short basic-profile flow; matching/application entry points also require the basic profile. Users may leave onboarding for the main menu, AI Chat or resources.

The My profile menu contains basic details, matching preferences, the Support Buddy profile/application and optional AI profile/privacy settings. Support Buddy registration reuses the shared display name and chat languages. Private full name remains a separate RDSS verification field. Editing common details updates the public application fields without changing approval or consent. Request review prefills the shared name; name edits go through the basic profile rather than creating a second identity.

Language choice 5 reads: “Other (please specify which languages, and type all of them)”. Languages may be entered as numbers, comma-separated names, supported synonyms or own-script names. Singlish Malay is stored as English and Malay. Custom languages are normalized consistently. Saved matching languages never change merely because the conversation changes language.

Matching requires a shared confirmed chat language. All otherwise eligible approved buddies with a shared language can be browsed, ranked by support and timing fit. Different support/time combinations are explicitly labelled. No shared-language option is silently substituted. Self and declined-buddy exclusions remain.

The directory shows five public summaries per page: display name, languages, usual availability, contact preferences and support offered. Selection numbers refer to a stored per-user list for 30 minutes, not a freshly reordered query. Eligibility is checked again before details and before sending. Expired or changed searches require a refreshed list rather than acting on an old number. Existing pending/accepted connections are labelled and reused.

Selecting a buddy opens their public details and introduction; it does not send anything. Preparing a request collects the optional message, shows the full sharing notice and requires a final numbered confirmation. Current shared-language compatibility and shared display name are checked at send time. Buddy acceptance checks current language compatibility too. Previously released WhatsApp links cannot be recalled.

## AI and language assistance

New menus expose bounded numbered choices to the existing multilingual routing layer. Private name/language fields use deterministic parsing and strong explicit-language-switch handling; help/navigation questions are not saved as answers. Public-name selection is resolved locally without placing buddy records into the AI routing prompt. Natural page-navigation phrases and selection requests open previews only. New text uses the existing protected-value translation layer. No AI-inferred choice can save the basic profile or grant final number-sharing permission.

Abandoned admin PIN prompts expire after 15 minutes, returning to the ordinary menu rather than treating a later greeting as a PIN. Active authenticated session checks are unchanged. AI chat instructions discourage long dashes in generated prose while preserving user text.

## Deployment prerequisites (not executed here)

1. Preserve a database backup.
2. Apply `connection_request_v2_schema.sql` followed by `basic_profile_schema.sql`, transactionally; review both on the target schema first.
3. Enable `CONNECTION_REQUEST_V2_ENABLED=true` and `BASIC_PROFILE_ENABLED=true` together. Defaults are false. Readiness checks reject an incomplete schema or missing prerequisite.
4. Deploy only with owner approval, then perform live two-phone acceptance tests. Keep existing chat/notification/reporting flags configured as appropriate.
5. Current test Support Buddy applications were reset by explicit owner request after a verified backup and isolated restore/cleanup rehearsal. New registrations must be created through the new interface once deployed.

Three-year retention includes new profile, draft, list-session and admin-login-prompt tables. No safety-conversation recording or complaints feature is included.
