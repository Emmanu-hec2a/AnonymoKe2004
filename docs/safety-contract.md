# Safety and verification

Implementation updated 14 November 2026. Deploy the backend migrations and mobile
changes together. No APK was built as part of this update.

## Alerts and shared plans

Alerts stay within AnonymoKE. The trusted contact needs an active account linked
through an invitation. Saving a plan immediately makes it available to that
account and queues a push. Venue labels are entered by the owner.

- Hold the panic control for two seconds. Releasing early, dragging or leaving
  the foreground cancels the hold. Screen-reader activation asks for confirmation.
- The client derives a stable retry UUID from the date plan. The server also
  deduplicates different keys for the same plan. The in-app alert, recipient and
  notification outbox are committed together before a success response.
- An alert remains available even if Redis, the worker or Firebase is unavailable.
  This requires the API and database to be reachable; a failed offline request
  is not presented as a saved alert.
- Panic stays visible on the owner’s date card. **I am safe** resolves either an
  active or panic plan and shares the resolution. Panic cannot be cancelled to
  silently dismiss it. A safe check-in does not assert the contact has read it.
- Each received alert has its own acknowledgement. Only its linked recipient
  can acknowledge it. Acknowledgement does not mark the owner safe.
- Contact replacement requires unlinking the old account. An open date plan must
  be resolved first. The linked account’s alias is shown separately from the
  contact label. Invites expire in 24 hours, are hashed, throttled and consumed
  atomically; self-linking and subsequent redemption are rejected.

Alert status has three distinct meanings:

| Value | Meaning |
| --- | --- |
| `stored` | Alert and recipient committed in the database |
| `push_accepted` | Firebase accepted at least one device notification |
| `acknowledged` | The contact explicitly pressed the acknowledgement action |

`delivered_at` is populated only on acknowledgement for compatibility with older
clients. `push_status` exposes queued, processing, unavailable, failed, cancelled
or push_accepted independently. Push acceptance is not proof of device display.
Legacy `sent` records are corrected during the migration.

The outbox uses expiring worker leases and bounded backoff for transient failures.
Beat re-enqueues due records after broker recovery. Missing credentials or device
tokens produce `unavailable`, with periodic recovery and a manual retry action.
Old unresolved pushes expire after 24 hours. Worker crashes can cause duplicate
push notifications; the database alert and acknowledgement remain idempotent.
Resolved plans, inactive accounts and unlinked recipients suppress stale pushes.

## Check-ins and privacy

Beat sends an owner reminder around the deadline, starting 15 minutes before it. A deadline
missed by 15 minutes queues a contact notice labelled as a missed check-in, not a
confirmed emergency. Updating the deadline resets these markers and cancels old
queued reminders. Already handled plans cannot starve later check-ins.

An active plan expires 24 hours after its deadline. Panic stays open until the
owner checks in safe; it is never automatically described as resolved. Closed
plans and their alerts/delivery records are purged after `SAFETY_RETENTION_DAYS`
(90 by default). Account erasure cascades through owned safety records.

Approximate-area sharing is opt-in. It requires current location consent and a
recent saved discovery cell. The payload rounds the cell to one decimal degree
and labels a 12 km area; it is not live tracking or the venue’s exact coordinates.
Withdrawing location consent removes saved safety areas and disables sharing.

The live screen refreshes every 10 seconds while foregrounded, on resume, on pull
and on safety push events. Older history pages remain stable while being browsed;
pull-to-refresh fetches current data. Block/report and safety history endpoints
support signed, viewer-scoped cursors, 30 items per page and actual totals.

## Smile ID setup

The integration uses hosted [Smile Links](https://docs.usesmileid.com/api-reference/core-resources/smile-links/create-a-smile-link)
for Kenyan National ID document verification. The provider hosts document/selfie
capture; the app opens the session in the browser after explicit consent and
refreshes status on return. The privacy notice is available before agreement.

Configure the API, worker and beat with the same values:

```dotenv
VERIFICATION_PROVIDER=smile_id
SMILE_ID_ENVIRONMENT=production
SMILE_ID_PARTNER_ID=<partner-id>
SMILE_ID_API_KEY=<server-only-key>
SMILE_ID_CALLBACK_URL=https://<api-host>/api/v1/me/verification/webhook/smile_id/
SMILE_ID_PRIVACY_URL=https://<site-host>/verification-privacy
SMILE_ID_REDIRECT_URL=https://<api-host>/api/v1/me/verification/return/
SMILE_ID_LINK_HOSTS=links.usesmileid.com,links.smileidentity.com
SMILE_ID_ADULT_POLICY_CONFIRMED=false
```

Use `sandbox` in development/staging. Confirm the returned hosted link’s actual
domain with Smile ID and add it to the allowlist if it differs; do not use a
wildcard or disable validation. Enable the Kenyan document verification product
on the partner account. Agree the provider’s retention and erasure procedure for
identity documents and selfies before enabling real capture; deleting local
attempts does not delete provider-held data.

**Age policy is a required operator setting.** Obtain confirmation from Smile ID
that this account’s document verification policy rejects under-18s and requires
document authenticity, liveness and selfie-to-document matching. Only then set
`SMILE_ID_ADULT_POLICY_CONFIRMED=true`. The status endpoint exposes an aggregate
result, so the application cannot independently infer age from it. Credentials
alone do not enable the feature. Missing settings keep verification unavailable.

Links are single-use and expire after 30 minutes. Launch URLs are encrypted at
rest and cleared on terminal results. Local attempt metadata and callback hints
are purged after 30 days. No identity documents, selfies or callback PII are saved
in this database. Partner tokens and API keys never go to the mobile client.

Callbacks use the documented [Response-Signature validation](https://docs.usesmileid.com/developer-resources/essentials/verification-webhooks/receive-webhooks/configure-your-webhook-server).
A callback only saves a deduplicated attempt/job hint. The worker retrieves the
[authoritative status](https://docs.usesmileid.com/api-reference/core-resources/verification-status/retrieve-a-verification-result)
with a user-bound token and checks both IDs before accepting `clear`. Callback
status, DOB or a client redirect cannot grant a badge. `attention` remains in
review; `block`/`error` fail. Production rejects sandbox success. Provider/broker
outages retain hints for retry, and pending known jobs are reconciled by beat.
The previous dummy webhook cannot verify Smile ID attempts.

## Deployment and validation

Run `python manage.py migrate` before updating clients. The change adds safety
migration `0005_reliable_safety` and verification migrations
`0003_hosted_verification`, `0004_result_check`.

Run the Railway worker with the `safety`, `notifications` and `moderation` queues
included, and run a single Celery beat service. Recovery runs every 30 seconds,
check-ins every minute, verification reconciliation every two minutes and safety
purging daily. Firebase Admin credentials are required for real push delivery;
the Android google-services.json is not a server credential. Monitor pending
outbox age and unavailable/failed deliveries in staging and production.

Local verification: nine provider contract tests pass without GDAL, backend Ruff
passes, and the full mobile suite passes 57 tests including 15 Safety regressions.
Dedicated backend tests cover persistence, access, recovery, scheduling, consent,
pagination, concurrent invite acceptance and panic deduplication. These database
tests and migration drift checks still require the PostGIS/GDAL CI environment;
the current Windows environment cannot load GDAL. Run:

```text
pytest --ds=config.settings.test
python manage.py makemigrations --check --dry-run --settings=config.settings.test
```

Before release, pass that CI suite, then use two staging accounts/devices to test
linking, pre-panic plan sharing, panic/acknowledgement/safe check-in, permission
changes, missed check-ins, worker/broker interruption and Firebase unavailable.
Run successful adult, underage, mismatch, review and retry cases with the actual
Smile ID account policy. Live provider/device validation remains outstanding.
