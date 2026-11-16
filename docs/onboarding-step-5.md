# Onboarding Step 5: Your privacy choices

Updated 15 November 2026. App version remains `1.0.0+11`; no APK built.

## Interface and explicit choice

Step 5 has its own `PrivacyStep` widget. It preserves the dark palette, violet
checkboxes/action, red required asterisks and plain teal shield reminder. Whole
consent rows are tappable. Labels scale with system text size and wrap. Content
width is bounded on wide devices; short screens and larger text scroll through
the footer. The footer stays visible on regular tall screens.

All five consent flags start false, including Demo mode. Location, matching
details, and Terms/Privacy are required. Voice is optional, including when a
recording was saved in Step 3. Turning voice off prevents its upload; its local
draft is released when setup succeeds. Returning to prior steps preserves the
current choices; changing accounts clears them.

The combined legal checkbox records separate terms and privacy decisions. The
Read Terms and Privacy Policy actions open external HTTPS documents separately
and never check the consent box. Opening a link is not treated as acceptance.
These links do not establish that a document was read.

## Published documents and client configuration

Configure these Flutter build definitions before live onboarding:

| Definition | Purpose |
| --- | --- |
| `TERMS_URL` | Published HTTPS Terms document. |
| `PRIVACY_POLICY_URL` | Published HTTPS Privacy Policy document. |
| `CONSENT_VERSION` | Revision recorded for the displayed documents; defaults to the existing `2026-01` contract. |

Both URLs must be HTTPS without embedded credentials. The revision must be
nonempty and at most 64 characters. Live completion is disabled and the
controller rejects saving when this configuration is missing. Demo may preview
the flow without published documents; it records no server consent or profile.
Policy content, publication, version selection and legal review are launch work.
The backend stores the supplied revision; it does not independently fetch the
documents or verify their contents.

## Final submission

The finish button requires all mandatory choices and disables controls during
submission. Native/back-button navigation is blocked while saving. Repeated
submission calls await one shared operation rather than returning early. Consent
setters cannot change a decision in flight; final profile/media use the existing
validated snapshot. Account changes stop remaining writes and stale navigation.

Live saving records the five decisions before any photo/audio upload, validates
the owner-scoped photo receipt, optionally uploads consented voice, and saves
profile/preferences atomically. Only then does the current session become
onboarded. Token values are preserved; a later session restore refreshes its
onboarding flag from the server.

Failures retain choices and local drafts for retry. Messages are readable and do
not expose raw server codes. Invalid earlier fields offer a return to the
relevant step; missing/rejected photos return to Step 4. Processing timeouts keep
the draft for retry. Missing files, invalid prior steps and missing required
consent also block Demo completion; successful Demo completion sends no API calls.

Consent requests and media operations span several requests, not one distributed
transaction. Successful consent writes or media preparation may already exist
after a later request fails. Retrying the latest identical consent decision
returns its existing record under the account lock. A changed decision or
revision still creates an audit record and revokes the previous decision.
Consent responses are marked `Cache-Control: no-store`.

The final photo receipt requires active terms, privacy, location and sensitive
data consent on the server. Ordinary profile updates cannot mark an account
onboarded without all four grants, matching preferences and the private/blurred
photo pair. Account controls remain usable when consent is withdrawn.

## Verification and deployment

Client regressions cover explicit choices, mandatory/optional gating, document
configuration and links, duplicate submission, retry, account isolation, session
completion, Demo behavior and small screens with larger text. The full Flutter
run passed 209 tests; after the final recovery/layout adjustments, all 22 Step 5
tests passed in the live configuration and all 21 applicable tests passed in Demo.
Empty/consented screenshots were rendered and inspected. Static analysis is clean.
Five new backend integration regressions cover final consent gating,
ordinary-PATCH bypass, identical retries, changed document revisions and empty
matching preferences. The local Django integration command cannot start because
GDAL is missing. Run it in the PostGIS/GDAL CI environment before
deployment. Backend lint and Python syntax checks pass.

Deploy backend changes before the client. There are no new dependencies or
migrations. Physical-device browser/document checks and a live consent/media
round trip remain release verification work. Earlier image/audio moderation
launch gaps in the Step 3/4 notes are unchanged.
