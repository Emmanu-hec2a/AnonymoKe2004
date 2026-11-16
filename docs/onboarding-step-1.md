# Onboarding Step 1: About you

Updated 15 November 2026. This covers Step 1 and the validation of its fields at
the final onboarding save. Step 2 is covered in `onboarding-step-2.md`;
Steps 3 and 4 have separate contracts; Step 5 still needs its individual review.
The mobile version remains `1.0.0+11`; no APK was built for this change.

## Screen behavior

- Alias starts empty. Users can type their own name or tap Shuffle for a random
  adjective, noun and four-digit suffix. Suggestions contain no location names
  and never immediately repeat the current alias. Aliases are not unique account
  identifiers. Trimmed aliases must contain 2–40 Unicode code points and no control
  characters. Existing server text moderation also applies when saving.
- Live onboarding requires an explicit Man, Woman or Non-binary selection. Demo
  mode retains its sample selections.
- DOB supports `DD / MM / YYYY` entry and a calendar restricted to adults aged
  18–100. Invalid calendar dates, future dates and out-of-range ages are rejected.
  The computed age appears inside the DOB input; the helper beneath has no
  hardcoded age. Age checks use the calendar date in Kenya on both client and server.
- Height is optional. A supplied value must be an integer from 100 to 250 cm.
  Clearing a previous value removes it from the draft and submits JSON `null`.
- Continue validates the form and focuses the first invalid input. Successful
  navigation retains the in-memory draft when returning from Step 2. The content
  scrolls when the keyboard or larger text leaves insufficient vertical space.
- Changing authenticated accounts resets the private draft and its visible form.
  Draft DOB and gender are not persisted to disk by this screen.

## Backend contract

Step 1 makes no profile or consent requests. Its values are revalidated when the
existing final onboarding save runs. That save records the consent choices first,
then PATCHes `/api/v1/me/profile/` with fields including:

```json
{
  "alias": "My own alias",
  "gender": "W",
  "birth_date": "1999-03-14",
  "height_cm": null
}
```

The backend requires active `sensitive_data` consent for DOB or gender changes.
DOB is write-only, encrypted at rest, and omitted from owner profile responses;
the server computes `age_years`. Client-provided `age_years` remains read-only.
Validation failures cannot partially change profile fields.

Saving uses a snapshot of the draft. Duplicate submissions are suppressed, and
the account is checked between requests so an account change stops remaining
writes. Profile fields and matching preferences now use one atomic PATCH, as
described in the Step 2 contract. Consent requests are still separate from that
PATCH; the complete final-save flow is part of the Step 5 review.

## Verification

- `test/onboarding_about_you_test.dart`: 24 tests cover form errors, date and
  birthday boundaries, custom aliases, height removal, back navigation, picker
  cancellation, account changes, final-save guards and narrow layouts at text
  scales 1, 1.5 and 2 with a keyboard inset.
- `apps.profiles.test_validation_unit`: six executable backend validation tests.
- Five additional API/database tests in `apps/profiles/tests.py` cover consent
  gating, encryption and write-only responses, the Kenya midnight boundary,
  invalid writes and height removal. These require PostGIS and GDAL. They have
  not run locally because this Windows environment lacks the GIS runtime; run
  the existing backend CI workflow before deployment.

Physical-device keyboard, date picker and screen-reader checks remain release
verification tasks. No live credentials were required for these local checks.
