# Live Profile tab

Updated 14 November 2026. Deploy the backend and mobile changes together. The
mobile version remains `1.0.0+11`; this update does not build an APK.

## Supported actions

- The header shows the owner's private photo; the camera control opens camera or
  gallery selection. Uploading requires an explicit Upload action. Android lost
  picker selections are recovered when the photo picker is reopened.
- **See how others see me** uses the separate blurred URL, alias, age, height,
  interests and bio. It does not display the private photo or matching preferences.
- Alias, bio and height can be edited. Interests can be added and removed, with
  a limit of ten, 2–24 characters each and case-insensitive duplicate checks.
- Premium and Boost quantities come from active entitlements. Expired items are
  excluded. Boost opens `/app/boost`; View plans opens the purchase screen.
- The voice control fetches a fresh owner URL before playback. Re-recording uses
  the microphone, stops at 15 seconds or when backgrounded, and supports local
  preview before upload. Permission denial does not fabricate a saved recording.
- The disguise choice is sent to the backend and applies an audio pitch shift;
  the displayed state comes from processed profile metadata. Existing audio is
  marked undisguised rather than being falsely labelled as masked. Pitch shifting
  does not guarantee speaker anonymity.
- Discovery preferences restore current target genders, ages 18–100 and distance
  1–50 km, and save together in one PATCH. Selecting Everyone excludes individual
  genders. Matching and location consent are enforced on the server.
- Privacy choices can grant or withdraw location, matching-details and voice
  processing consent. Withdrawal asks for confirmation. Location withdrawal clears
  saved cells and shared safety areas; matching withdrawal removes target-gender
  preferences. Re-enabling consent does not restore deleted preferences/location.
- Pause changes `is_discoverable` on the backend. Private media can be deleted
  explicitly, including older recorded uploads for the selected media kind.
- Download fetches owner-scoped JSON and opens an explicit OS Save File picker:
  Android Storage Access Framework or iOS Files. Cancellation never reports a
  successful download. This action does not invoke a share sheet or automatically
  send personal data to another app. iOS export scratch files are protected and
  removed after completion/cancellation, or on the next process launch.
- Account deletion requires typing `DELETE` exactly. A successful backend purge
  clears local credentials and auth state and returns to sign-in. Storage failure
  keeps the account available for retry and is not reported as completed erasure.

The live screen refreshes on entry, resume, pull-to-refresh, after returning from
edits/purchases, and periodically while foregrounded. Perk/media-status outages
do not remove the account controls. A 401 removes displayed profile data. Narrow
screens and larger fonts put card actions below the text to preserve readability.

## API and storage behaviour

`GET/PATCH /api/v1/me/profile/` now includes owner-only `avatar_url`,
`blurred_avatar_url`, `has_avatar`, `audio_url`, `audio_duration_ms`,
`audio_disguised` and `target_genders`. Do not reuse this owner DTO as another
person's discovery response. Media URLs expire after five minutes; storage keys,
birth dates and credentials are not returned in the profile response.

`PATCH /me/profile/` accepts matching preferences atomically with age/distance
changes. Read-only age and verification fields cannot be self-assigned. Public
text rejects contact details, commercial sexual content and combined monetary
solicitation patterns. This is the existing local moderation layer; a face check
does not constitute an identity or explicit-content classification.

Media flow: request `/me/media/upload-url/`, PUT bytes to the presigned HTTPS URL,
then POST the same `upload_id` to `/me/media/complete/`. Raw upload transport has
no Authorization interceptor. An ambiguous completion retries the same ticket
without uploading bytes again. Processing/rejection is shown separately from
the previously accepted media, which remains active until replacement succeeds.

The worker strips image metadata, checks for one frontal face and creates a
separate blurred image. Its OpenCV classifier is bundled with provenance and
license in `apps/profiles/resources/`; deployment does not fetch a model at runtime.
Audio processing requires FFmpeg/FFprobe. The worker preserves a durable processing
intent, retries transient infrastructure failures, claims jobs with expiring
leases and prevents an older completed upload from replacing a newer accepted
selection. Beat recovers stalled media jobs every minute.

All potential output keys are recorded before uploading objects, including keys
from partial processing failures. Media publication and account erasure lock the
account in the same order. `DELETE /me/media/{avatar|audio}/` clears owned objects,
asset records and active references. Bulk R2 deletion uses batches of at most
1,000 keys per request and treats per-object errors as failures.

The JSON export includes account/profile/private-identity data, consent history,
authored messages, media metadata, matching preferences, swipes, matches, reports,
blocks, owned date plans, contact details, purchases, financial records and local
verification metadata. It excludes credentials and another user's private
identity. It does not contain photo/audio binaries. The response is marked
`Cache-Control: no-store`. Export requests are throttled to three per hour.

## Deployment and validation

Run `python manage.py migrate` before deploying the updated client. Migration
`profiles/0003_profile_media_controls` adds voice-disguise metadata and processing
recovery fields/index. Run the existing `media` worker queue and Celery beat.
Configure R2 private/derived buckets and credentials on both API and worker.
Configure an incoming-object lifecycle rule so abandoned presigned uploads expire;
presigned upload links can remain usable until their own expiry after a deletion.
Provider-held Smile ID erasure remains subject to the separate verification setup
described in [safety-contract.md](safety-contract.md).

Verified locally:

- 76 Flutter tests pass, including 19 new live Profile tests.
- Flutter analyzer and backend Ruff are clean.
- 18 database-independent Python tests pass, including actual image blurring,
  metadata stripping, face rejection, bulk deletion failure handling and the
  existing Smile ID contract tests.
- The Android Save File bridge compiles against the installed Android/Flutter
  SDKs without generating an APK. The iOS permission plist parses correctly.
- Twenty new backend integration tests cover owner isolation, preference writes,
  media processing/recovery and erasure/export behaviour. They remain unexecuted
  locally because the Windows environment lacks GDAL; run the existing PostGIS CI
  suite and migration drift check before production sign-off.

Complete staging checks with actual R2 objects, microphone/camera permissions,
upload interruption, worker recovery and account erasure. Test OS destination
selection/cancellation on Android and iOS. iOS native compilation/device testing
requires macOS/Xcode and remains outstanding.
