# Authentication screen and mobile handoff

Updated 15 November 2026. Version remains `1.0.0+11`. No APK built.

## Interface

The entry screen uses the supplied AK mark, dark surfaces, brand accents and a
violet email action. It has compact privacy promises, native provider actions,
email validation, readable errors and independent Terms/Privacy links. Legal
acceptance remains explicit in onboarding Step 5. Short screens, the keyboard
and larger system text can scroll through all actions.

Google and email are available on Android and iOS. Apple uses native iOS sign-in
and is shown on iOS. Android Apple web authentication is not implemented. Demo
offers a separate preview button that neither creates an account nor calls the
auth API. The regular sign-in buttons still use the real integrations in Demo.

## Session handling

Native Google/Apple ID tokens go to the Django social verification endpoints.
Firebase Auth is not used; Firebase remains the push-notification service. Every
successful provider returns the same Django session DTO. Secure storage must
succeed before navigation. The session's `is_onboarded` flag selects onboarding
or Discover.

Startup refresh is shared, and interactive sign-in waits for restoration. Secure
writes are ordered with logout. Late sign-in/restore responses cannot restore a
logged-out session. The shared secure store also rejects background API refresh
results from an earlier session revision, so they cannot overwrite logout or a
new login. Returning to sign-in revalidates an in-memory session instead of
routing with a stale cached flag. Account-switch confirmation remains idle
until the user chooses an action. Failed storage writes clear partial credentials.
Push token
registration is best effort after authentication and does not undo a valid
login. Signed-out push registration cannot start an unrelated token refresh.
Public auth endpoints do not receive an old bearer header or trigger the API
interceptor's automatic refresh on authentication errors.

## Email handoff

Successful requests lead to **Check your email**. The screen shows the requested
address, expiry, resend countdown and change-email control. Resend and expiry
metadata come from the server, with the original 60-second/10-minute contract
as the client's backwards-compatible defaults. Accepted requests do not claim
delivery or disclose whether an account exists. Cooldown/hourly suppression
still returns the same accepted response.

The configured custom URL `anonymoke://auth/magic-link?token=...` is registered
on Android and iOS. `app_links` handles initial and subsequent links, and
Flutter's competing deep-link handler is disabled. The parser accepts only the
expected host/path, one token, its bounded URL-safe format and no fragment,
userinfo or explicit port. Initial/stream duplicates are ignored. Tokens remain
in memory and do not enter the internal router URL or token-paste fields.

A valid link signs in automatically when signed out. An existing signed-in
account requires confirmation before using another link. Expired/reused links
offer recovery; transient failures allow retry. No link is redeemed by the
backend's email request endpoint.

The existing custom scheme supports device/staging testing. Before public
launch, configure an owned HTTPS auth domain, Android verified App Links and
iOS Universal Links. `AUTH_LINK_HOST` restricts the Dart parser to that hostname
and `/auth/magic-link`; it does not publish association files or configure OS
domain entitlements by itself. Publish the domain's `assetlinks.json` and
`apple-app-site-association`, add the corresponding native HTTPS intent/domain
configuration, and set `MAGIC_LINK_BASE_URL` to that HTTPS URL. Test delivery and
handoff with the actual email clients on physical devices.

## Branded sign-in email

The backend sends the supplied AK eye-and-heart logo, dark brand styling, the
violet sign-in action, matching HTML/plain-text expiry and a transactional footer.
See [email-branding.md](email-branding.md) for the friendly sender address,
optional footer links, bundled assets and separate inbox-avatar/BIMI setup.

## Configuration

| Setting | Where | Purpose |
| --- | --- | --- |
| `GOOGLE_WEB_CLIENT_ID` | Flutter build definition | Web/server OAuth client audience; Android may also load its registered web client from google-services.json. |
| `GOOGLE_IOS_CLIENT_ID` | Flutter build definition | Native iOS OAuth client. Register its reversed-client URL scheme in Xcode/Info.plist. |
| `GOOGLE_OIDC_CLIENT_ID` | Django environment | Must match the Google web/server client audience used by the mobile SDK. |
| `APPLE_BUNDLE_ID` | Django environment | Native iOS ID-token audience, e.g. `co.anonymoke.anonymoke`. |
| `APPLE_SERVICE_ID` | Django environment | Additional Apple service audience when applicable. |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | Django environment | Resend key and verified sender domain/address. |
| `MAGIC_LINK_BASE_URL` | Django environment | Email link prefix, including `?token=`. |
| `AUTH_LINK_HOST` | Flutter build definition | Optional owned HTTPS auth hostname; requires native domain association as described above. |
| `TERMS_URL`, `PRIVACY_POLICY_URL`, `CONSENT_VERSION` | Flutter build definitions | Default to bundled in-app policies, revision `2026-11-16`; optional HTTPS overrides must match the displayed revision. |

Register the Android package and signing certificate fingerprints in Google
Cloud/Firebase. iOS includes the Sign in with Apple entitlement in the Runner
build configurations; enable that capability for the App ID and use a matching
provisioning profile. No server credentials or signing keys were added to source.
The existing Firebase app startup also requires the matching iOS Firebase
configuration when building for iOS.

The configured mobile Google Web/server audience is:

```env
GOOGLE_OIDC_CLIENT_ID=441811643862-eekavq3aeaa7nbigi5omagv354a482h0.apps.googleusercontent.com
```

Set this value in Railway. The mobile app includes it as its default
`GOOGLE_WEB_CLIENT_ID` and Android type-3 OAuth client. Platform client IDs and
signing fingerprints still need registration in the same Google Cloud project.
This native ID-token flow does not consume a Google client secret or use a web
OAuth redirect endpoint.

## Backend guarantees

Unconfigured email delivery returns `email_delivery_unavailable`, rather than
pretending a message was sent. Provider failures discard the undelivered token
so a retry is not trapped behind its cooldown. A PostgreSQL transaction advisory
lock serializes request limits for the normalized email across workers. The
configured cooldown and five-per-hour default remain authoritative on the server.
Magic links expire, are hashed at rest and are single-use under a row lock.

Auth responses use `Cache-Control: no-store`. Auth routes have IP throttles and
consistent validation errors. Social verification requires the signature,
issuer, audience, expiry, issue time, subject and a verified valid email. Both
canonical Google issuers are supported; Apple accepts only configured bundle or
service audiences. Concurrent social identity creation uses the unique provider
subject constraint without failing a second legitimate request.

## Verification

The full Flutter suite passes all 244 tests and static analysis is clean.
All 34 auth checks also pass in Demo mode. The Android auth and check-email
screens were rendered and visually inspected; the temporary rendering helper
was removed, and previews remain under the client's `build/ui_previews` folder.
34 new auth tests cover API/session behavior, link parsing and handoff, provider
cancellation, retry/cooldown, account switching, storage failure, logout races,
Demo visibility and keyboard/larger-text layouts. Nine isolated backend token
validation tests pass. Backend lint, syntax, OpenAPI and platform XML/plist checks
pass. Eight API integration tests were added; local Django startup stops before
tests because GDAL is unavailable. Run these in the PostGIS/GDAL CI environment.

Native OAuth dialogs, platform callback registration, release signing, real
Resend delivery and cold/warm/background device handoff still need configured
credentials and physical-device validation. This implementation does not claim
those external integrations have already been exercised.

Implementation references: [Google Sign-In](https://pub.dev/packages/google_sign_in),
[Apple Sign-In](https://pub.dev/packages/sign_in_with_apple),
[app_links](https://pub.dev/packages/app_links),
[Flutter deep-link configuration](https://docs.flutter.dev/release/breaking-changes/deep-links-flag-change),
[Google server token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).
