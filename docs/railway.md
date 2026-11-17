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
- `RESEND_API_KEY` and `RESEND_FROM_EMAIL=AnonymoKE <noreply@anonymoke.co.ke>`; optional reply inbox and
  legal footer URLs are described in [email-branding.md](email-branding.md)
- Google and Apple provider credentials
- R2 endpoint, access key, secret key, and bucket names
- Media limits and `MEDIA_REQUIRE_EXACTLY_ONE_FACE`
- Smile ID settings and confirmed adult-verification policy from [safety-contract.md](safety-contract.md)
- `FIREBASE_PROJECT_ID=anonymoke-e038b`
- `FIREBASE_SERVICE_ACCOUNT_JSON` containing the Firebase Admin service-account JSON for the project
- Verification, moderation, and Sentry credentials when those integrations are enabled
- `PAYMENT_PROVIDER=daraja` plus Daraja consumer key/secret, `DARAJA_SHORTCODE`,
  `DARAJA_TILL_NUMBER`, passkey, `DARAJA_CALLBACK_BASE_URL`, and a high-entropy
  `DARAJA_CALLBACK_TOKEN` before enabling purchases

Payments use Buy Goods STK Push (`CustomerBuyGoodsOnline`). Set `DARAJA_SHORTCODE` to the store/head-office
shortcode registered during Daraja go-live; it supplies `BusinessShortCode` and the password for both STK
initiation and status queries. Set `DARAJA_TILL_NUMBER` to the receiving customer-facing Till number; it
supplies `PartyB`. Both values must be configured explicitly, even when Safaricom assigns the same number.
For live payments, set `DARAJA_BASE_URL=https://api.safaricom.co.ke`. Keep the sandbox URL for staging tests.

## Worker and beat variables

The worker and beat services use the same environment variables as the API service. They should use the same
image and release version as the API service.

The API image also serves WebSockets through Daphne at `/ws/v1/matches/{match_id}/?token=<access-jwt>`.
Keep the access token short-lived and use the normal refresh endpoint before reconnecting after expiry.

## Migration consistency and GDAL

The Docker builder and runtime use Python 3.12 on Debian Trixie, whose GDAL
packages provide 3.10. The image checks that Django loads GDAL 3.9 or newer.
This satisfies the native-library requirement behind Django's `gis.W001` check;
no system-check warning is suppressed.

The image also runs `makemigrations --check --dry-run --noinput` during the build.
That check uses development settings and an isolated in-memory SQLite connection
only to compare model and migration state. It never connects to the Railway
production database, generates migration files, or changes the runtime database
configuration. Deployment still applies committed migrations through the existing
`migrate --noinput` pre-deploy command.

The `align_model_state` migrations reconcile existing index names, serialize the
custom User manager, and align the payment-callback JSON field's validation metadata.
They preserve existing records. The Profile migration depends on
`0003_profile_media_controls`, which already depends on `0003_mediaasset`.

When changing models, generate and review migrations in development, commit them
with the model change, then deploy. Avoid generating migration files at container
startup because they would be release-specific and ephemeral.

References: [Django GDAL security requirement](https://docs.djangoproject.com/en/5.2/releases/5.2.19/),
[Debian Trixie GDAL](https://packages.debian.org/trixie/gdal-bin).

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

