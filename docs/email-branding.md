# Transactional email branding

The magic-link email uses the user-supplied AK eye-and-heart mark, copied without
redrawing from the supplied profile-logo JPEG. The shipped image is
`apps/accounts/resources/anonymoke-logo.jpeg`. The app's header wordmark and
launcher assets are unchanged.

The email uses the dark brand palette, a #6A4AF0 sign-in action, the actual
configured expiry, single-use guidance and a clear transactional footer.
A text alternative carries the same sign-in link and expiry. Inline table-based
styles and fluid widths support narrow screens and clients with limited CSS.
The logo is a CID attachment, so no external image-hosting URL is needed.
Visible brand text remains present when an inbox blocks the image.

## Railway configuration

```env
RESEND_FROM_EMAIL=AnonymoKE <noreply@anonymoke.co.ke>
RESEND_API_KEY=<your Resend API key>
```

The sender domain must be verified in Resend. There is no need to publish a
Resend dashboard template: the backend sends the bundled HTML and text.
Existing Railway values override defaults; set the friendly sender name explicitly
if the variable currently contains only a bare email address.

Optional settings:

- `RESEND_REPLY_TO_EMAIL`: a real, monitored bare email address. It becomes the
  Reply-To address and the Support footer link. Leave empty until replies can
  actually be received. Resend domain verification alone does not create an inbox.
- `EMAIL_PRIVACY_URL`: the published HTTPS privacy-policy URL.
- `EMAIL_TERMS_URL`: the published HTTPS terms URL.

Unset optional links are omitted. The footer always includes anonymoke.co.ke,
why the message was sent, what to do if it was not requested, and the current year.
The email uses the existing `MAGIC_LINK_BASE_URL` configuration; an HTML template
does not add native HTTPS App/Universal Link handling. See
[authentication-screen.md](authentication-screen.md) for the handoff contract.

Keep open/click tracking disabled for authentication messages in the Resend
domain settings. The template adds no tracking pixels or remote fonts.
This is transactional mail; it does not subscribe the recipient to marketing.

## Inbox sender profile logo

The logo inside the email and the profile photo beside a sender in an inbox are
configured separately. Neither a Resend `from` address nor an embedded logo sets
that inbox photo. Inbox providers control its display.

For BIMI, use this same AK eye-and-heart mark, obtain an appropriate compliant
vector original (SVG Tiny PS), and complete the provider's domain authentication,
certificate and DNS requirements. The supplied JPEG is a brand reference, not a
BIMI-ready SVG or a certificate. Do not wrap it in SVG and claim BIMI compliance.
No BIMI record, certificate, or provider profile has been published by this change.

For Gmail, follow its current VMC/CMC, DMARC and hosted-logo requirements.
Display still depends on the receiving provider and its eligibility checks.

References:

- [Resend inline images](https://resend.com/docs/dashboard/emails/embed-inline-images)
- [Resend send-email API](https://resend.com/docs/api-reference/emails/send-email)
- [Resend inbox-logo note](https://resend.com/legal/terms-of-service#15-third-party-trademarks)
- [Google BIMI setup](https://knowledge.workspace.google.com/admin/security/set-up-bimi)
- [Resend authentication-message tracking guidance](https://resend.com/guides/email/deliverability/avoid-outlook-spam-folder)

## Resend transport diagnostics

The backend identifies itself with the `AnonymoKE/1.0` User-Agent. The generic
Python urllib User-Agent was rejected by Resend's edge with HTTP 403/code 1010,
while the application User-Agent could read the verified sending domain.
Failed sends log only HTTP status or exception class; recipient addresses,
magic-link tokens, request bodies and API keys are excluded from these diagnostics.
The public auth endpoint retains its generic delivery-unavailable response.

## Clickable sign-in handoff

The production email button and fallback text use an HTTPS app link rather than
a custom scheme, which email clients may strip or ignore. The owned API domain
serves a scanner-safe browser handoff for older installs and Android certificate
association for new builds. Tokens use URL fragments. See
[authentication-screen.md](authentication-screen.md#email-handoff) for deployment
settings and device checks. Old emails require a fresh request after the change.

## Verification

`python -B -m unittest apps.accounts.test_mail_unit -v` renders the actual
templates with mocked Resend delivery and needs no database or GDAL.
It covers URL escaping, matching HTML/text expiry and links, the embedded asset,
optional footer destinations, provider errors and missing credentials.

Real inbox rendering and delivery require a configured Resend key and a real
recipient test. No live messages are sent by this verification.
