# Railway deployment

## Services

Create these services in the Railway project:

1. `api` — this repository, using the checked-in `Dockerfile` and `railway.json`.
2. `worker` — this repository, with start command:
   `celery -A config worker -l INFO -Q critical,realtime,media,moderation,safety,notifications,default,bulk`
3. `beat` — this repository, with start command:
   `celery -A config beat -l INFO`
4. PostgreSQL with PostGIS enabled.
5. Redis.

Railway's PostgreSQL template and Redis service provide the managed infrastructure. Use a PostGIS-enabled
PostgreSQL template or enable PostGIS before running migrations.

## API service

The API service uses the Dockerfile's Daphne command and listens on Railway's injected `PORT`. The healthcheck
path is `/healthz`; it does not require authentication. Migrations run through Railway's pre-deploy command.

## Required variables

Set these in the Railway environment, never in Git:

- `DJANGO_SETTINGS_MODULE=config.settings.prod`
- `DJANGO_SECRET_KEY`
- `JWT_SECRET`
- `DATABASE_URL` from the PostgreSQL service
- `REDIS_URL` from the Redis service
- `ALLOWED_HOSTS` containing the Railway domain and final API domain
- `LOCATION_HMAC_SECRET`
- `FIELD_ENCRYPTION_KEY`
- `RESEND_API_KEY` and `RESEND_FROM_EMAIL`
- Google and Apple provider credentials
- R2 endpoint, access key, secret key, and bucket names
- Media limits and `MEDIA_REQUIRE_EXACTLY_ONE_FACE`
- Smile ID settings and confirmed adult-verification policy from [safety-contract.md](safety-contract.md)
- `FIREBASE_PROJECT_ID=anonymoke-e038b`
- `FIREBASE_SERVICE_ACCOUNT_JSON` containing the Firebase Admin service-account JSON for the project
- Verification, moderation, and Sentry credentials when those integrations are enabled
- `PAYMENT_PROVIDER=daraja` plus Daraja consumer key/secret, shortcode, passkey,
  `DARAJA_CALLBACK_BASE_URL`, and a high-entropy `DARAJA_CALLBACK_TOKEN` before enabling purchases

## Worker and beat variables

The worker and beat services use the same environment variables as the API service. They should use the same
image and release version as the API service.

The API image also serves WebSockets through Daphne at `/ws/v1/matches/{match_id}/?token=<access-jwt>`.
Keep the access token short-lived and use the normal refresh endpoint before reconnecting after expiry.

## First deployment sequence

1. Provision PostGIS PostgreSQL and Redis.
2. Add the variables above to a Railway staging environment.
3. Deploy the `api` service and confirm `/healthz` is green.
4. Confirm the pre-deploy migration completes.
5. Deploy `worker` and `beat`.
6. Create and price active `Product` records before enabling purchases.
7. Confirm an authenticated mobile device registers at `POST /api/v1/me/notifications/devices/` and that the
   worker can deliver a staging push notification.
8. Run the auth, privacy, and Daraja sandbox reconciliation tests against staging before enabling purchases.
9. Apply the media migration and validate the live Profile flows in [profile-contract.md](profile-contract.md).

## FCM service-account setup

Create a Firebase Admin service account for the `anonymoke-e038b` project, generate a private-key JSON file,
and copy the complete JSON object into Railway's `FIREBASE_SERVICE_ACCOUNT_JSON` variable. Keep it only in the
Railway environment; never commit it and never use the Android `google-services.json` file as a server credential.

The API stores one device token per app installation. The worker sends notifications asynchronously after a
successful transaction for likes, matches, chat messages, and reveal requests/decisions. Invalid or unregistered
tokens are disabled automatically.

