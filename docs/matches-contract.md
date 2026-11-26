# Matches, messages and reveals

Deploy the backend and mobile changes together. Run `python manage.py migrate`
before enabling the updated client; chat migration `0002_reliable_messages` adds
retry identifiers and the pending moderation index. Redis, the Celery worker
(including the `moderation` queue) and Celery beat must be running. The beat task
retries queued messages whose initial moderation dispatch failed or stalled.

## Inbox and likes

- `GET /api/v1/matches/?paged=1` returns `items`, `next_cursor`, `total_count`
  and total unread message count. Each item includes its actual latest visible
  preview, activity time, unread count, viewer profile ID and reveal status
  (`none`, `incoming`, `outgoing`, `revealed`). Legacy clients can still request
  the unpaginated first 50 matches.
- `GET /api/v1/likes/` returns an eligible nearby incoming-like count. Identities
  are withheld unless an active Premium entitlement exists. Premium results
  contain anonymous discovery cards and a signed pagination cursor. Liking back
  uses the normal eligibility-checked swipe endpoint and a stable client UUID.
- `GET /api/v1/likes/sent/` lists the likes you sent that have not been answered
  or withdrawn, newest first, 20 per page with a signed cursor. No Premium is
  needed. Each item is the anonymous discovery card plus `client_swipe_id`,
  `liked_at` and `expires_at` (`liked_at` + 24h, when the like is withdrawn
  automatically). Likes that became a live match are not listed; close the
  match instead. Withdraw a listed like with `POST /api/v1/swipes/undo/` and
  its `client_swipe_id`. `distance_bucket` is null when either side has no cell.
- Cursors expire after 24 hours and are signed and scoped to the viewer and
  collection. After expiration, restart from the first page. Activity ordering
  can change while paging a live inbox; clients deduplicate by match ID.

## Messaging

- `GET /api/v1/matches/{id}/messages/?paged=1&cursor=...` returns up to 50
  messages in chronological order plus `next_cursor` for older history. Tuple
  cursors handle messages with identical timestamps.
- `POST .../messages/` accepts `body` and optional `client_message_id` UUID.
  The updated app always supplies the same UUID when retrying an unchanged
  failed draft. A retry returns the original message; reusing that UUID for
  different text is rejected. Legacy clients without UUIDs lack this guarantee.
- Newly accepted messages are `queued`. Only the sender can see queued, flagged
  or blocked messages. The worker applies the existing English/Swahili/Sheng
  pattern rules; flagged text is held for human review. Only clear messages are
  shown or published to the other participant. There is no managed AI classifier
  connected by this change.
- `POST .../read/` accepts `through_message_id`. The mobile app acknowledges
  incoming clear messages after rendering while the conversation is visible and
  the user is at its newest end. Later messages remain unread.
- REST messages, inbox, read acknowledgements and reveal actions are throttled.
  WebSocket access is revalidated on inbound events and outbound messages,
  including JWT expiry, current membership, blocks and account status. Cleared
  message content is loaded from the database rather than trusted from events.

## Reveal and safety

Reveal request/respond/withdraw endpoints support the full mutual-consent flow.
Both people require verification when `REQUIRE_VERIFICATION_PRE_UNMASK=True`.
Sensitive-data consent must remain active. Self-acceptance is rejected; declined
requests impose a 24-hour requester cooldown. Retries of accepted requests do not
send duplicate notifications.

`GET .../revealed/` checks current consent and eligibility and issues original
photo URLs lasting five minutes. Anonymous inbox payloads never include original
photos. The app hides revealed details when backgrounded and rechecks access on
resume and every ten seconds while the revealed-profile sheet is open. Signed
URLs already issued remain valid until their expiry; closing a conversation
prevents issuing more URLs, and cannot recall photos already viewed.

`DELETE /api/v1/matches/{id}/` idempotently closes a match and clears reveal
consents. Blocking also closes the match. Closed, blocked and suspended-account
conversations are excluded from inboxes and denied by chat and reveal endpoints.
Reporting uses the existing private evidence-validated report API.

Moderators can review held messages at
`GET /api/v1/admin/moderation/messages/{message_id}/` and submit
`POST` with `action: approve|block` and a required `reason`. Access requires an
active staff moderation role; reads and decisions are audited. Approvals publish
once, remain subject to current match access, and resolve their flag records.

## Mobile delivery and release checks

The mobile inbox refreshes every 20 seconds and on foreground push events; open
chat polls every five seconds while visible. Polling does not require FCM
credentials. Notification taps open the specific match after authentication and
onboarding. Background polling pauses. FCM remains a hint, not the source of truth.

Run `flutter test` and backend `pytest --ds=config.settings.test` in the existing
PostGIS/GDAL CI job. Before production, exercise two staging accounts through
match, message, read receipt, reveal approval/decline/withdraw, report, block and
unmatch. Test worker outage recovery and device notification delivery separately.
