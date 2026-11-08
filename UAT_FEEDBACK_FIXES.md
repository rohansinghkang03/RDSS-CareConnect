# WhatsApp feedback fixes

- Admin PIN screen offers cancellation only; it no longer claims a not-yet-signed-in user can return to an admin menu or sign out.
- One command section per message, with back/menu first, individually described. Literal command protection no longer preserves duplicate legacy reminders. Saved private values remain untouched.
- Non-sensitive menus invite conversational requests before the numbered choices. Sensitive confirmations explain the need for the explicit numbered decision.
- Supports the reported phrases “on notifications”, “may I have the statistics from the last 30 days” and “may I view monthly statistics”. Monthly/weekly wording asks for the actual reporting range rather than silently assuming a calendar period.
- AI restrictions explain the requested action, why it stays under human control, and the available manual process. There is no invented bulk-delete menu.
- Admin review omits “Verification: Not required”. Required verification shows pending; completed verification shows the date/time. The proposed policy requiring verification for every applicant before approval or rejection is deferred, as requested.
- “Anyone else?”, similar phrases, or No on a preview skip that candidate. Per-search history persists across worker restarts. An explicit new search clears only that user's browsing history. Eligibility, self-match and latest-declined exclusions stay enforced. A different preference group is explained and offered before selection; no request is sent while browsing.
- Notification messages use the same grouped navigation design. Direct-chat delivery fallback text also uses a single command section.
- Safe WhatsApp failure logs include HTTP status and provider code, without tokens, recipient numbers, message contents or URLs.

## Delivery failure finding
The configured Render WhatsApp credential was checked read-only with Meta. Meta returned HTTP401, code190, subcode463: expired token. Incoming messages at the reported stoppage reached the bot, but their outgoing replies failed. This is separate from the 30-minute administrator sign-in session. No credential was changed automatically. A token replacement must be entered by the owner; a system-user token is the intended longer-term setup. Tokens can still be revoked.

## Test checkpoint
The user stopped while browsing alternative matches. Buddy-side notifications and the real chat-button flow are still untested. Preserve that distinction: a passed synthetic test suite and healthy service do not prove live WhatsApp delivery while its access token is expired. A fresh reset of the specifically identified business test account was requested after these fixes. Preserve the personal account and unrelated records.
