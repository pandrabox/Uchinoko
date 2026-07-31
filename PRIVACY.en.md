# Privacy Policy

*[日本語](PRIVACY.md)*

Last updated: 2026-07-31

Uchinoko for Palworld ("the tool") is a Windows desktop application that converts a VRChat avatar into a playable character model for Palworld. The tool runs **entirely locally**, and your avatar's 3D model data (mesh, textures, etc.) is never sent anywhere.

The tool communicates over the network in exactly two situations, described below.

## 1. The Contact/bug-report feature (only when you explicitly choose to send)

Pressing the in-app "Contact" (問合せ) button opens a screen where you can review and edit what will be sent. **Only after you press the Send button on that screen** is the following information transmitted to `https://report.osakishokai.com`. **Nothing is ever sent automatically.**

Items included:

- Tool version
- Distribution channel (BOOTH, itch.io, GitHub, or dev build)
- Local date/time at the moment of sending
- OS description (product name and build number read from the Windows registry, e.g. "Windows 11", "build 26200.xxxx")
- UI display language and OS locale setting
- The selected avatar's **filename only** (the full folder path is not included)
- The detected Palworld version-compatibility result
- A list of other detected pak MODs
- The full session execution log for that run

These fields are assembled by `BuildDiagnosticsText()` in `app\DiveToPalworld.cs`. The avatar's actual 3D model data (mesh, textures) is never part of this payload.

### Automatic masking before anything leaves your device

Immediately before sending, the following masking (`SanitizeForClipboard()`) is applied automatically:

- Known user-profile folder paths (e.g. `%LOCALAPPDATA%`) are replaced with placeholder tokens
- Steam 64-bit IDs (17-digit numbers starting with `7656119`) are masked
- The Windows account name and machine name are masked
- Any other absolute drive path or network path is replaced with a structure-preserving placeholder that keeps only its length and file extension (e.g. `<path len=42 ext=.prefab>`) — the actual path text is never sent

### Optional items

- **Image attachment**: the web-based inquiry form lets you optionally attach one image. GPS and other EXIF metadata is automatically stripped before the image is stored.
- **Reply-notification email**: on the page shown after sending, you can optionally register an email address to be notified when a reply is posted. This is only used if you register it, and delivery is handled through a third-party email service, Resend. If you don't register an address, you can still check for replies by revisiting the page's URL.

## 2. Update check (automatic, silent)

On every startup, the tool automatically fetches a static file, `https://dl.osakishokai.com/versions.json`, to check whether a newer version is available. This is an asynchronous, low-priority request that fails silently if you're offline. The request itself does not carry any user- or avatar-identifying data beyond what any ordinary web request includes (your IP address and User-Agent may appear in the server's access logs, as with any HTTP request).

## 3. Where data is stored, and for how long

Data submitted through the contact feature is stored in a service operated by the developer on Cloudflare Workers (a Cloudflare D1 database plus R2 object storage).

Each report is assigned a random 8-character ID. Anyone who has the URL containing that ID (`https://report.osakishokai.com/r/<ID>`) can view and reply to that thread — there is no additional password or login. Please do not share this URL with anyone you don't want to see the thread.

**The current implementation has no automatic deletion or retention-expiry mechanism.** Data remains stored until the developer manually deletes it.

## 4. Who can access it

Submitted data can be accessed only by the developer (pandrabox / Osaki Shokai) using administrative credentials. In addition, Cloudflare (infrastructure provider) and Resend (email delivery for reply notifications) technically handle this data to the extent necessary to provide their services — both are general-purpose cloud/email vendors.

## 5. Contact

For questions about this policy, or requests to review or delete your data, please use the in-app "Contact" button or open an Issue on this project's GitHub repository.

## 6. Changes

This policy may be updated as the tool's implementation changes.
