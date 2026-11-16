# Safety tab readiness audit

Historical findings recorded before implementation. The fixes, current contract,
test evidence and remaining release validation are in [safety-contract.md](safety-contract.md).

Reviewed: 14 November 2026. Verdict: connected to the backend, but not ready for
production safety use. This review did not change application code or build an APK.

Scope: live Flutter Safety and management screens, API client, trusted contacts,
date plans, panic dispatch, recipient acknowledgements, notification delivery,
verification, block/report access, and existing test coverage.

## Release blockers

1. **Panic cannot be resolved through "I am safe".** PanicAlertView changes a
   session to `panic`; SafetyOverviewView returns only `active` sessions, removing
   the date card after reload. DateSessionSafeView rejects a panic session with
   HTTP 409. A safe check-in only updates the owner's session and audit log;
   recipient alert payloads expose no resolution/safe status. Add an explicit
   panic-to-safe transition and communicate resolution to the trusted contact.

2. **Alert status conflates persistence, push and delivery.** The broker-failure
   branch writes `sent` and `delivered_at`. The worker also records `sent` when
   send_user_event returns without Firebase configuration or enabled devices.
   Per-device FCM failures are not returned to the caller. Declaring max_retries
   on dispatch_panic_alert does not cause retries: its exception handler returns
   `failed` without calling retry. Keep the durable in-app alert, distinguish it
   from push acceptance and recipient acknowledgement, and retry transient push
   and queue failures without duplicating alerts.

3. **The live recipient experience can miss alerts.** Safety loads a Future once;
   there is no periodic, resume or pull-to-refresh mechanism. Foreground FCM
   refreshes the Matches inbox only. The alert card shows and acknowledges only
   `alerts.first`; older unread alerts have no list/action in the UI, even though
   the overview includes a total. Provide refresh and access to all pending alerts.

4. **Trusted-contact replacement and linking need hardening.** Editing the name or
   phone preserves linked_user, potentially displaying a replacement person's
   name while sending to the previous account. There is no mobile unlink/replace
   flow. Invite issue/accept endpoints have no throttles, and acceptance does not
   atomically lock and consume the invitation. Two concurrent redemptions can
   overwrite the recipient. Separate label edits from account replacement, show
   the linked identity, and implement revocation and atomic, throttled linking.

5. **Verification is an unfinished integration.** provider_for implements only
   DummyEmailAdapter. A real provider name raises an unavailable error. The app
   discards the start response and displays an instruction message without a
   provider handoff, capture flow or status refresh. Credentials alone cannot
   complete a real selfie/identity check with this implementation.

6. **Date-sharing/check-in behavior is incomplete.** Creating a plan persists it
   for its owner but does not expose or notify it to the linked contact before a
   panic. check_in_due_at is stored and displayed; no scheduled reminder,
   overdue handling or session expiry exists. share_approximate_location is a
   boolean with no approximate-area payload. Implement these behaviors, or adjust
   the controls and wording to accurately describe the supported functionality.

## Additional reliability and UX gaps

- The mobile panic sender creates a new UUID on each attempt instead of preserving
  one through an ambiguous network failure. If the first request commits but the
  response is lost, retrying can return active_date_required rather than recovering
  the existing alert. Persist the retry key and reconcile alert status.
- Panic and safe/date writes do not consistently lock their session row. Concurrent
  requests can race; active-plan creation relies on a database unique constraint
  without handling its concurrent IntegrityError.
- Date cancellation exists in the API/client but has no Safety screen action.
- Report and blocked lists stop at 100 rows without pagination or a truncation
  indicator. Their GETs share write-rate limits. Management has no pull-to-refresh
  or resume refresh, and asynchronous actions need mounted/busy guards.
- The panic hold timer is not cancelled on app lifecycle changes. Most write
  actions also allow repeated taps. Some sheets dispose text controllers before
  their dismissal animation has necessarily completed.
- Long venue/contact text is placed in unconstrained Row children in the live
  screen. Existing visual regressions exercise the reference Safety screen, not
  live API-backed data or the panic workflow.

## Existing protections verified in code

- Owner-scoped safety records and recipient-scoped acknowledgement endpoints.
- Durable in-app recipient records created with the panic alert in one transaction.
- Server panic idempotency uniqueness and panic request throttling.
- Expiring, hashed invite codes and a self-link check.
- Encrypted optional contact phone storage.
- Owner-scoped block/report lists; blocking closes matches and clears reveal consent.
- Report evidence is restricted to a match between reporter and reported account.

## Verification evidence and limits

Five isolated probes executed the actual extracted source functions with mocked
infrastructure. They confirmed: broker failure writes sent/delivered state;
notification no-op produces sent; temporary notification failure does not retry;
panic-to-safe returns 409; and replacement contact details retain the original
linked account. These are source-function reproductions, not database or device
integration tests.

There are no dedicated Safety or verification test modules. The prior full mobile
suite passed 42 tests, but does not establish live Safety-flow readiness. Local
backend database verification remains unavailable because GDAL is missing. Before
release, add dedicated regressions and pass the PostGIS CI suite, then use two
Railway staging accounts/devices to exercise linking, shared plans, panic, receipt,
acknowledgement, safe resolution, reconnects and queue/push outages.

All findings can be addressed within the current in-app alert design. SMS or
WhatsApp integration is not required for these fixes.
