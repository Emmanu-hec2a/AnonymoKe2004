# Live discovery

Deploy both repositories together and run `python manage.py migrate` before the
updated mobile app is distributed. The added migrations create `ProfileBoost`
and add the reversible `Swipe.is_undone` marker.

## Session and privacy

JWT failures return 401 with `WWW-Authenticate: Bearer`. The mobile client rotates
the refresh token once and retries the original request with the new access token.
Location is requested only after location and sensitive-data consent is granted.
The server stores the existing snapped location and returns distance buckets,
never coordinates or private identity, in discovery responses.

Discovery, profile details and swipe eligibility require active consent, an active
discoverable adult profile, and an unflagged location captured within seven days.
Both people must meet the other's gender, age and distance preferences. Revocation
of location consent also clears the location; withdrawal of matching consent
clears target-gender preferences. Previously issued media URLs expire after five
minutes. New audio URLs are not issued after voice consent is revoked.

## Endpoints

- `GET /api/v1/discover/`: up to 20 unseen eligible cards. Subsequent requests
  exclude accepted swipes, so the app refills after finishing a batch. Query filters
  can narrow saved preferences. The app saves changed preferences through
  `PATCH /api/v1/me/profile/` before refreshing the feed. Clear filters restores
  ages 18–35 and a 15 km radius without changing gender preferences.
- `GET /api/v1/discover/{profile_id}/`: fresh, eligibility-checked card details
  and expiring media URLs. No original photos, identity, gender, coordinates or
  target-gender preferences are returned.
- `POST /api/v1/swipes/`: requires `profile_id`, `action` and a stable UUID
  `client_swipe_id`. Returns `is_match`, `match_id`, and `client_swipe_id`.
  The mobile app retains a failed card and retries with the same ID. It advances
  only after server acceptance.
- `POST /api/v1/swipes/undo/`: requires `client_swipe_id`. Only the most recent
  accepted pass can be undone, and an active Premium entitlement is required.
  Likes and matches cannot be undone. Repeating an undo is idempotent.
- `GET /api/v1/me/boost/`: returns `active_until` and `available_boosts`.
- `POST /api/v1/me/boost/`: requires a UUID `client_activation_id`. Consumes one
  purchased Boost entitlement and activates ranking priority for 30 minutes.
  Repeating the same activation does not consume another token. Already-active
  Boosts do not stack or consume more tokens. Boost never bypasses safety,
  consent, distance or matching eligibility.

Run integration tests against PostGIS with GDAL available:

```sh
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test apps.discovery
```

The CI workflow provisions GDAL and PostGIS and checks for migration drift.
