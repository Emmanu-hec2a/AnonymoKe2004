# Onboarding Step 2: Who do you want to meet?

Updated 15 November 2026. This change covers matching preferences in Step 2 and
their submission at the final onboarding save. The app version remains
`1.0.0+11`; no APK was built. Step 3 is covered in `onboarding-step-3.md`;
Step 4 is covered in `onboarding-step-4.md`; Step 5 still needs its individual review.

## Screen behavior

- Live onboarding starts with no target gender selected. Continue requires a
  selection. Demo mode keeps its sample choice.
- Men, Women and Non-binary can be selected together or individually. Everyone
  clears specific selections; choosing a specific gender clears Everyone.
  Tapping a selected chip removes it. An empty selection cannot advance.
- The age slider supports every integer from 18 to 100. The previous `40+`
  endpoint incorrectly submitted a hard limit of 40. Both displayed bounds now
  match the inclusive limits saved to the server. Older ranges restore accurately.
- Distance supports integers from 1 to 50 km. This step selects a discovery radius;
  it does not request location permission or collect coordinates.
- The screen retains the dark brand palette, violet pill selections, white age
  thumbs, violet-to-coral age track, violet distance track, privacy note and mutual
  matching explanation. The footer sits toward the bottom when space allows;
  content scrolls on smaller screens and with larger text.
- Continue validates and scrolls to the first invalid section. Draft choices
  survive back navigation through Steps 1 and 3. An account change resets them.
  Step 2 makes no API calls and does not persist preferences to disk.

## Save contract

Final submission revalidates both reviewed steps before making any network
requests. Invalid, empty, duplicate or contradictory gender selections, reversed
or out-of-bounds ages, and distances outside 1–50 km are rejected.

After recording consent, onboarding sends profile fields and matching preferences
in one `PATCH /api/v1/me/profile/` request, including:

```json
{
  "target_genders": ["W", "NB"],
  "min_age_pref": 45,
  "max_age_pref": 85,
  "max_distance_km": 50
}
```

The server already wraps this endpoint in a database transaction, including the
associated matching-preference row. Validation errors and database failures roll
back the entire PATCH. Onboarding no longer makes a second preferences PUT that
could fail after the profile was marked onboarded. The older PUT endpoint remains
available for existing clients and uses the same gender validation.

Matching fields require active sensitive-data consent; changing the radius also
requires location consent. Consent requests and the profile PATCH remain separate
transactions. A failed save preserves the local draft for retry. In-flight saves
use an immutable snapshot and stop remaining requests when the account changes.

The discovery service uses these saved inclusive bounds and target genders, while
also enforcing the other person's gender, age and distance preferences. Preferences
are returned only through owner endpoints, never in public discovery cards.

## Verification

- `test/onboarding_preferences_test.dart`: 29 tests cover selections, slider
  gestures and boundaries, older ranges, navigation, account isolation, narrow
  layouts at text scales 1/1.5/2, invalid final saves, the actual HTTP request
  sequence, save snapshots and retry behavior.
- The Step 1 suite remains covered alongside Step 2: 53 onboarding tests total.
- The full Flutter regression suite passes all 129 tests; static analysis is clean.
- All 32 locally executable backend unit tests pass; Ruff and OpenAPI parsing pass.
- Eight new pure backend tests cover matching choices, malformed input, integer
  types, age ordering and distance boundaries.
- Four new profile API/database tests cover boundary saves, invalid writes,
  rollback after a database failure and location-consent gating. Two discovery
  tests cover older adults, gender selections and reciprocal matching. These six
  tests require PostGIS/GDAL. The local database test command stops during Django
  startup because the GDAL library is missing, before any database tests execute.
  Run the existing backend CI workflow before deployment.

No migration or new provider credentials are needed for these changes.
Physical-device slider and screen-reader checks remain release verification work.
