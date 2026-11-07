# Direct match chat and alternative matching

Direct chat is disabled by default (`MATCH_CHAT_ENABLED=false`). No hosted migration or WhatsApp trial is implied by the isolated test results.

## Caregiver flow
Searches rank eligible buddies by support and usual availability. Exact fits come first. If none fit both preferences, offer two routes when available: keep support and try another time; keep timing and consider another kind of support. Show the selected person's offered support and usual times before asking to send a request. No live presence is inferred. Self matches, the latest declined buddy and buddies who fail approval/consent/verification checks remain excluded. Candidates with neither preference matching are not suggested.

An accepted request does not itself authorize phone sharing. Both participants must separately agree to sharing their WhatsApp numbers for that specific connection. AI profile permission is independent. Once both agree, a pressable CTA URL button opens a `wa.me` link through the device browser/WhatsApp. The user decides whether to send the first message. The bot cannot read the resulting private conversation.

Use `my chats`, `chat REQUEST_ID`, `stop chat REQUEST_ID`, or `menu`. The latter withdrawal blocks future link releases; a released/in-flight link and a number already seen cannot be recalled. Blocking someone in WhatsApp is separate.

## Controls and delivery
Consent binds to the exact pair and current notice version. Consent prompts expire after 30 minutes. Delivery rechecks ownership, request acceptance, buddy eligibility and both permissions immediately before releasing the URL. No database row lock is held over a network call. Pair reassignment invalidates old grants. Feature shutdown still allows revocation.

`MATCH_CHAT_TEST_NUMBERS` optionally limits enabled testing to connections where both participants appear in the comma-separated international-digits allowlist. No braces are required. Keep the general flag false until migration and a controlled two-person trial are agreed.

A definitive invalid-button rejection permits one freshly authorized plain clickable-link fallback. Ambiguous outcomes, authentication errors and rate limits never cause an automatic duplicate release. Reports count interactive messages alongside text/document attempts. Provider acceptance is not proof of delivery, clicking, or a private chat taking place.

## Migration and verification
Run `python match_chat_manage.py` for a transactional rollback preflight; `--apply` applies the additive migration. It creates three contact-sharing metadata tables and widens outgoing-message kinds without deleting existing rows. Existing three-year retention covers these metadata tables. This does not delete exported files or private WhatsApp chats.

Automated verification uses isolated local PostgreSQL, synthetic participants and mocked WhatsApp delivery: exact/alternative ordering, both alternative routes, explicit request confirmation, ownership, consent, stale notices, eligibility changes, reassignment, withdrawal races, delivery fallback, ambiguous errors, privacy, payload shape, parallel consent/release checks, repeated migration and retention. Real device behavior still requires a controlled WhatsApp trial.

Official platform references:
- https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-cta-url-messages/
- https://faq.whatsapp.com/5913398998672934
