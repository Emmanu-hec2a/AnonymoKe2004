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

Sign-in emails now use an ordinary HTTPS URL:

```env
MAGIC_LINK_BASE_URL=https://api.anonymoke.co.ke/auth/magic-link#token=
```

The token is in the URL fragment so it is not sent in HTTP requests, proxy access
logs or referrers. The email's primary button and fallback text link use the same
URL. Request a fresh email after deployment: existing emails retain their old
custom-scheme links, which some email clients suppress.

Android's manifest registers the owned `api.anonymoke.co.ke` domain with
`android:autoVerify`, restricted to `/auth/magic-link` and `/auth/magic-link/`.
The backend publishes `/.well-known/assetlinks.json` as JSON without a redirect,
for package `co.anonymoke.anonymoke` and both supplied SHA-256 certificates.
`ANDROID_APP_LINK_SHA256_FINGERPRINTS` optionally overrides the comma-separated
public certificate list. Register the actual release/Play signing certificate
when introducing a new signing configuration, and retire obsolete certificates.

A new APK is required for Android to acquire the new HTTPS intent filter. The
existing APK can still use the browser handoff: the HTTPS page shows an explicit
**Open AnonymoKE** action using the registered custom callback. Android's action
targets the package with an `intent://` URL; iOS uses the existing custom scheme.
Browsers that suppress external app navigation may require opening the page in
the default browser. No store/download link is invented before public release.
iOS Universal Links remain pending Apple App ID/team/domain provisioning; this
change does not claim native iOS HTTPS association is configured.

The landing page requires a deliberate tap, never calls the verification API,
and does not consume links on GET/HEAD, so mail scanners cannot redeem a token by
visiting it. It clears the token from browser history, uses a per-response CSP
nonce, disables caching/referrers/framing and loads no third-party resources.
Malformed or ambiguous token parameters show a recovery message without an app
launch. Keep Resend open/click tracking disabled for authentication messages so
the provider does not wrap the associated URL.

The app parser defaults `AUTH_LINK_HOST` to the owned API domain. It accepts one
bounded URL-safe token in the HTTPS fragment, plus legacy HTTPS-query and custom
callback forms. It rejects mixed query/fragment credentials, duplicate tokens,
extra fields, untrusted origins, userinfo and non-default explicit ports.
Initial/stream duplicates across URL forms are ignored. Tokens remain in memory
and never enter the internal router URL or token-paste fields. A custom
`AUTH_LINK_HOST` still requires matching native and hosted domain association.

A valid link signs in when signed out. An existing signed-in account requires
confirmation before using another link. Expired/reused links offer recovery;
transient failures allow retry. No token is redeemed by the email request or
public landing endpoints.

For physical-device verification, install the new APK and tap a fresh email.
Inspect domain verification on Android with:

```cmd
adb shell pm verify-app-links --re-verify co.anonymoke.anonymoke
adb shell pm get-app-links co.anonymoke.anonymoke
```

The API host should show `verified`. User-selected default-link settings and
email in-app browsers can affect the final handoff. Test both cold and running
app states. Do not put a real sign-in token into terminal commands or logs.

References: [Android App Links](https://developer.android.com/training/app-links/add-applinks),
[Android verification](https://developer.android.com/training/app-links/verify-applinks),
[Flutter app-link setup](https://docs.flutter.dev/cookbook/navigation/set-up-app-links),
[Chrome Android intents](https://developer.chrome.com/docs/android/intents).

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

## Android account chooser returns without signing in

The native Google SDK can report Android OAuth configuration failures using the
same cancellation code as an intentional dismissal. Google sign-in now displays
`Google sign-in was not completed. Try again or use email.` for this ambiguous
result, resets the loading state and allows another attempt. Apple cancellation
keeps its existing behavior. Two regression checks cover the mapping and a
successful retry; all 36 targeted Flutter auth tests pass.

Register the fingerprint of the APK's actual signing certificate, rather than
assuming a certificate inspected with keytool is the one Gradle used. The current
Android release configuration still uses the debug signing configuration. Build
13 was checked directly and has these fingerprints:

```text
SHA-1:   63:B4:D6:24:14:D6:30:80:00:67:E4:86:F7:F9:0E:10:68:FB:8A:B9
SHA-256: D6:D8:9F:61:38:46:F1:78:2B:81:78:3D:6D:C7:80:68:5B:64:1B:76:7C:DF:70:25:13:CA:AF:48:94:0F:E6:5F
```

In Firebase project settings, add the appropriate fingerprints to Android app
`co.anonymoke.anonymoke`, then download the newly generated google-services.json
to `android/app/google-services.json`. Preserve registrations for other active
signing certificates. When a dedicated release or Play signing certificate is
introduced, register that certificate as well. Do not fabricate an Android OAuth
client registration by editing the JSON's certificate hash manually.

The Django Google audience must still be the Web/server client ID shown above;
the native Android client ID is not the ID-token audience for this flow.
[Flutter Android sign-in troubleshooting](https://pub.dev/packages/google_sign_in_android)
describes the cancellation/configuration ambiguity and required registration.

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

The latest HTTPS handoff change passes 40 targeted Flutter authentication tests,
18 isolated backend email/handoff tests and 13 JavaScript handoff behavior cases.
Dart analysis, backend lint and Android manifest validation pass. A real headless
browser verified 390px and 320px viewports, visible Android app actions, removal
of the token from browser history and no horizontal overflow. No APK was built.

The checks cover trusted origins, fragment/query ambiguity, duplicate delivery,
JWT/session routing, secure storage/logout races, malformed link recovery,
scanner-safe public GET/HEAD responses, nonce CSP, certificate association and
real HTML/plain-text email rendering with mocked delivery. Database/GIS auth
integration tests were not rerun locally because native GDAL is unavailable;
Railway's image retains its native GIS and migration-parity build checks.

Resend's verified sending domain was checked read-only, with open and click
tracking confirmed disabled. No live test email or valid sign-in token was
created by these checks. Final cold/warm app handoff must be confirmed on the
physical device with a fresh email after deployment. New Android HTTPS handling
requires a rebuilt APK and successful OS domain verification; existing APKs use
the browser handoff. iOS Universal Link provisioning remains separate.

Implementation references: [Google Sign-In](https://pub.dev/packages/google_sign_in),
[Apple Sign-In](https://pub.dev/packages/sign_in_with_apple),
[app_links](https://pub.dev/packages/app_links),
[Flutter deep-link configuration](https://docs.flutter.dev/release/breaking-changes/deep-links-flag-change),
[Google server token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).
