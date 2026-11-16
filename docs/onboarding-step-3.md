# Onboarding Step 3: Voice capsule

Updated 15 November 2026. The mobile version remains `1.0.0+11`; no APK was built.
Step 4 is covered in `onboarding-step-4.md`; Step 5 still needs its individual review.

## Recording and preview

Step 3 now uses the native microphone instead of a simulated timer. It requests
permission only after Record is tapped, records mono AAC at 48 kHz, displays
elapsed time and measured microphone levels, and stops at the 15-second deadline.
The stop path releases the microphone without waiting for waveform stream cleanup.
Very short or empty captures cannot be saved.

Re-record replaces the local capsule after the new recording starts successfully.
Preview plays the local original and can be stopped; starting a new recording
also stops playback. Backgrounding, leaving the step and recorder interruptions
stop capture/playback. A late permission response after backgrounding or changing
accounts is stopped and discarded. Recording never restarts automatically.

The coral recorder ring/control, violet waveform and checkbox, dark surfaces and
Save capsule button retain the reference styling. Controls scroll on small screens
and stack with larger text. The fixed recorder graphic has a screen-reader label
for the recording state and elapsed duration.

The disguise checkbox is interactive. It selects backend pitch processing when
sharing; Preview is explicitly labelled as the original. Shared disguised audio
remains processed after a match. The screen no longer promises automatic removal
of the disguise on matching. Pitch shifting does not guarantee speaker anonymity.

## Local draft and consent

- **Save capsule** retains a local draft and advances to Step 4. It makes no API
  calls and grants no consent. Returning from Step 4 restores the draft.
- **Skip for now** discards the local capsule and releases its recorder/files.
  Microphone denial remains recoverable through this optional path.
- Live onboarding defaults voice consent to false. The final privacy checkbox is
  the choice to upload/share; local capture alone never enables sharing.
- Draft metadata stays in memory; native audio is staged in the app's temporary
  cache. Restarting the process does not restore a draft. Normal cleanup runs on
  skip, account changes and successful completion, including Demo completion.
  Abrupt process termination can leave cache files for OS reclamation.

## Final save and backend

Final submission validates the earlier steps, requires a saved photo and rejects
an active/pending recording. After recording consent choices, the Step 4 photo
must become ready before a saved, consented capsule uses:

1. `POST /api/v1/me/media/upload-url/` with kind `audio`, MIME `audio/mp4`, byte
   length and the chosen `disguise_voice` value.
2. A PUT of the bytes to the presigned private R2 URL using the transport without
   a session Authorization header.
3. `POST /api/v1/me/media/complete/` with the same upload ID.
4. The combined profile/preferences PATCH with the accepted photo receipt.

A failed upload blocks the profile-completion PATCH and retains the draft for
retry. An ambiguous completion failure reuses the ticket and avoids uploading
bytes again. Account checks run between stages so an account change prevents
remaining audio requests. Rejected media is not reported as a successful final
save. Processing/ready responses are accepted; processing is asynchronous and the
Profile tab refreshes media status. Account/profile completion does not guarantee
that the capsule has already passed processing or is available for playback.

Declined voice consent or an unsaved recording results in no audio upload. After
successful final submission the local recording resources are cleared.

The worker accepts up to 500 ms of input encoder padding, publishes at most 15
seconds, rejects invalid/non-finite durations, selects one audio stream, strips
global/stream metadata and chapters, and restricts decoder protocols/formats.
These controls use the documented FFmpeg
[protocol options](https://www.ffmpeg.org/ffprobe-all.html) and
[format allow list](https://www.ffmpeg.org/ffmpeg-formats.html).
Voice consent is checked again under the account lock before publication. A late
older worker cannot replace a newer ready capsule. The owner media/profile APIs
reference processed audio, not the incoming original.

Audio transcription/content moderation remains a separate public-launch gap;
this media processor validates and transforms audio but does not transcribe it.

## Validation and deployment

- 29 new Flutter tests exercise timing, sample levels, permission/lifecycle races,
  playback, drafts, skip, account isolation, larger text, consent and upload retries.
- The full Flutter suite passes all 158 tests, with a clean analyzer. The executable
  backend regression run has 39 passing tests and two FFmpeg-dependent skips; Ruff
  and Python/OpenAPI/CI syntax checks pass.
- Seven new backend unit tests cover audio privacy and duration validation.
- Two real FFmpeg tests verify actual pitch changes and metadata removal. They
  skip locally because FFmpeg/ffprobe are absent. CI now installs FFmpeg alongside
  GDAL so those tests run there.
- Five new API/worker integration tests cover the disguise flag, processed-only
  publication, consent revocation, ownership and stale-worker protection. They
  require the PostGIS/GDAL environment and have not run locally.

Deploy API and worker changes together. R2 credentials and private buckets, the
Celery media worker and beat recovery job are required for live upload/processing.
The existing Docker image includes FFmpeg. No new provider credentials or
migration were added. Phone microphone, interruptions and playback still need a
physical-device check; R2 and worker processing need a staging round trip.
