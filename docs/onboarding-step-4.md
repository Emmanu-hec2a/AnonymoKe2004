# Onboarding Step 4: Add your photo

Updated 15 November 2026. The app version remains `1.0.0+11`. No APK was built.
Step 5 still needs its individual review.

## Screen and device behavior

- Both cards stay square, with centered profile placeholders before selection.
  The private card and **Choose a photo** open a camera/gallery bottom sheet.
  The private card has a camera affordance. After selection, **Retake or choose
  another photo** sits beside the comparison and opens replacement/removal actions.
- The left card displays the selected private photo. The right card displays a
  separately generated blur; it never receives the private image as its source.
  Continue requires a usable local selection. The badge says **Selected** because
  server face checks happen after final consent.
- The dark palette, violet CTA, teal privacy/check icons, card labels and lock
  message follow the supplied preview. Photo captions share aligned rows, guidance
  is compact, and the content width is capped on wide screens. Text can wrap.
- The footer contains one primary action: **Choose a photo** before selection,
  **Continue** for a usable draft, or **Choose another photo** after rejection.
  It stays at the bottom on regular screens; short screens and larger text use a
  scrollable layout so the action remains reachable.
- Picker cancellation retains the previous selection. Permission errors provide
  recovery guidance. A replacement releases the previous local draft.
- Leaving/re-entering the step or changing accounts invalidates pending picker
  and decode results. Late results cannot populate another account's screen.
  Android picker lost-data recovery remains available on the next picker action.
- Continue stores the draft in memory and advances to privacy choices without a
  network call. Returning restores the selection. Removal, account changes and
  successful final submission release the draft and evict its image-cache entries.

## Local photo preparation

The client validates non-empty files up to 10 MB, dimensions of 200–8000 pixels
per side, at most 32 megapixels, and a single image frame. It decodes the image,
reduces its longest side to at most 1600 pixels and re-encodes it as PNG before
upload. The normalized upload contains no copied source EXIF/GPS metadata.
The separate preview uses a 24-pixel center crop with a strong blur.

Local preparation validates the file and generates a privacy preview. Server
face checks and the final face-centered blur remain authoritative. The original
camera/gallery source belongs to the picker/library and is not deleted by the
app's Remove action; normalized drafts remain in app memory.

## Consent and final save

Final submission requires a saved photo and validates the earlier steps before
making requests. After recording consent, it:

1. Requests an avatar upload ticket and sends the normalized image to private R2.
2. Completes the upload using its stable upload ID.
3. Polls `GET /api/v1/me/media/status/{upload_id}/` until the upload is ready.
4. Saves an optional consented voice capsule, then the profile/preferences PATCH.

Status polling is limited to 15 attempts and a 30-second wait budget. Slow or
interrupted checks preserve the draft for retry. Ambiguous completion failures
reuse the ticket and avoid sending bytes again. The upload ID and media kind
must match the expected photo throughout validation. Removing/replacing the photo
or changing accounts stops remaining requests.

The final PATCH includes the write-only `onboarding_photo_upload_id`. Under the
account lock, the server checks ownership, avatar kind, ready status and exact
agreement with the active private and blurred photo keys. A rejected or stale
receipt cannot finalize onboarding. The user session flag remains incomplete
without a private photo and blurred counterpart.

Rejected photos return the user to Step 4 with a replacement message and retain
the selected image for reference. The primary action requires replacement before
Continue becomes available again.
The final button shows saving/checking progress. Demo mode supports local picking
and preview without R2 calls; it does not claim that server face validation ran.

## Backend processing and privacy

Avatar ticket creation, completion and publication require active privacy and
sensitive-data consent. Status responses contain only owner-scoped metadata,
return 404 for another account and are marked `Cache-Control: no-store`.

The worker rejects unsupported formats, animation, invalid dimensions and excessive
pixel counts before full decoding. It applies EXIF orientation, strips metadata,
reduces large originals, checks exactly one face by default and creates a separate
heavily blurred image. Both original and derived uploads are tracked for erasure.
Download reads are bounded and remote streams are closed; replacing an incoming
object after its HEAD check cannot force an unbounded worker download.

Face presence/count checks are implemented. Nudity/sexual-content classification
still requires an image moderation provider before public launch; the UI presents
the content rules without claiming that classifier is already running.

## Verification and deployment

- The layout refinement was verified with all 30 existing Step 4 Flutter tests,
  static analysis, and rendered empty/selected previews. No APK was built.
- 30 new Flutter tests cover camera/gallery actions, cancellation, replacement,
  removal, draft restoration, permission errors, lifecycle races, larger text,
  real decoding/normalization/blur, validation timeouts, retry identity and consent.
- The full Flutter suite passes all 188 tests and static analysis is clean.
- All 30 Step 4 tests also pass in Demo mode.
- The executable backend regression run has 48 passing unit tests, with the two
  existing FFmpeg-dependent tests skipped locally. Ruff and Python/OpenAPI syntax
  checks pass.
- Nine new backend unit tests cover image dimensions, animation, format,
  orientation, resizing, multiple faces and bounded storage reads.
- Eight API/worker integration tests cover the final receipt, stale/wrong/foreign
  uploads, session completeness, status privacy, consent and object replacement.
  The local integration command stops during Django startup because GDAL is
  missing, before any database tests execute. Run these in the PostGIS/GDAL CI
  environment before deployment.

Deploy backend API and media worker changes before the updated client. Existing
R2 configuration, private/derived buckets, media worker and beat recovery are
required for live validation. There are no new dependencies or migrations.
Physical camera/gallery checks and an R2/worker staging round trip remain release
verification work. Image moderation also remains public-launch work.
