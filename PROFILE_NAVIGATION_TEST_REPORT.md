# Phase 2 navigation follow-up

Result: **29 tests passed** in 1.493 seconds against the isolated local PostgreSQL cluster. Changed Python sources passed syntax and whitespace checks. Provider transport and translations were mocked; selected-language wording still needs a WhatsApp smoke check.

Main menu choices 1–5 remain unchanged. Added 6 (My profile and privacy settings), 7 (My request/application status), and 8 (Change language). Profile and status commands also remain available as shortcuts.

The profile page shows only the current sender's approved fields and current permission status. Its numbered options expose suggestion review, permission details, withdrawal/deletion, the main menu, and AI Chat. Numbered withdrawal asks for confirmation and supports cancellation. The existing explicit withdrawal command remains supported. Reading an active permission notice again does not reset consent or its eligible-message window.

Profile prompts use the selected language through the existing translation helper. Saved values, suggestions, and edited wording are inserted after translating the fixed template; private profile text is not sent for translation or rewritten. Missing template markers or navigation commands trigger an English fallback. Arbitrary language quality is not established by mocked translation tests.

Every handler reply has an existing navigation instruction or receives a contextual footer. AI replies link to the main menu and profile controls; buddy/application flows link to the main menu and status; initial language selection explains how to continue to the main menu. Existing menu instructions are not duplicated. Translation and preference failures retain a usable menu command.

Added checks cover numbered menus, saved-profile ownership and viewing, enable/decline, withdrawal cancellation and confirmation, stale-field suppression without consent, profile service failures, rejection/edit cancellation, translation privacy and exact-wording preservation, AI footers, contextual status links, language selection, nonduplicated navigation, fallback behavior, and exits from invalid-edit/withdrawal prompts. All previous privacy, concurrency, migration, routing and webhook checks also pass.

No schema migration is required for this follow-up. No Render database connection, AI provider request, WhatsApp send or deployment was performed by these tests. The three pre-existing untracked local files remain untouched.

## Malay cancellation follow-up

The WhatsApp cancellation test preserved permission but its response fell back to English. The profile renderer had a strict ASCII-quote check that could reject a valid translated command; the exact provider output that triggered this particular fallback is not available. That check now accepts intact command words with alternative punctuation while still rejecting missing commands.

Malay profile pages, saved-field labels, permission status, cancellation notices and withdrawal confirmation now have fixed local wording. These recognized templates do not depend on a translation-model response. Saved caregiver text remains inserted verbatim afterward. Unknown templates and other languages retain the existing translation path and English safety fallback.

Verification: 32 isolated integration tests passed, including cancellation remaining in Malay with model translation deliberately unavailable, saved non-Malay text preserved inside a Malay profile, withdrawal deletion/status, smart-quoted command handling and missing-command rejection. Syntax and whitespace checks passed. No database migration is required.
