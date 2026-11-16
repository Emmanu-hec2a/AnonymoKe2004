# AnonymoKE backend — Phase 0

## Confirmed decisions

- Repository scope: backend.
- Product name: AnonymoKE.
- Authentication direction: Google and Apple social sign-in plus email magic links.
- Email delivery: Resend.
- Object storage: Cloudflare R2.
- Location is foreground-only and server-snapped; raw coordinates are never persisted or returned.
- Backend remains the source of truth for privacy, matching, disclosure, safety, and payments.

## Contract changes requiring confirmation before Phase 1

The original brief specified phone + SMS OTP. That is replaced by the selected authentication direction.
The exact token exchange contract will be proposed before implementation; no mobile or admin client should
generate against auth endpoints until that proposal is approved.

Proposed endpoint family:

- `POST /auth/magic-link/request/`
- `POST /auth/magic-link/verify/`
- `POST /auth/social/google/verify/`
- `POST /auth/social/apple/verify/`

## Pending product decisions

- Package ID and brand palette.
- Verification provider and per-check budget.
- Image/text moderation approach.
- R2 region and cross-border transfer position.
- First launch area.
- Voice pitch-shift option.
- Kenyan legal review of sensitive orientation-revealing data handling.
- Purchase-record retention period.

## Phase 0 exit criteria

- Django settings are isolated for dev, staging, and production.
- Environment variables are documented and secrets are excluded from source control.
- Health and readiness endpoints exist.
- Local PostGIS, Redis, and S3-compatible storage dependencies are defined.
- Draft OpenAPI 3.1 contract is checked into the repository.
- CI runs formatting/linting and tests once dependencies are installed.

## Phase 1 implementation status

- Unified JWT session DTO, refresh-token rotation, and DRF authentication boundary added.
- Magic-link request/verify flow added with 10-minute TTL, 60-second cooldown, and hourly limit.
- Google/Apple provider boundary and verified-email account linking added; provider-specific OIDC validation remains an adapter implementation.
- Verification provider interface and discovery/unmask feature flags added.
- Consent records, profile updates, isolated target-gender preferences, and consent-gated snapped location updates added.
- R2 purge adapter boundary, cascade-safe erasure service, and seven-year financial-record retention model added.
- Layer 1 moderation scan, managed moderation boundary, report model, and configurable three-unique-report suspension action added.

Raw coordinates are accepted only for a location update request, snapped with a per-user HMAC offset, persisted as a grid cell, and never returned or logged.

## Local validation note

GeoDjango imports the native GDAL library during Django startup. Windows development therefore needs either
Docker/PostGIS or a local GDAL installation before `manage.py check`, migrations, and Django tests can run.
The repository includes PostGIS and Redis services in `docker-compose.yml`; Docker Desktop is the preferred local path.

