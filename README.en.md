# Uchinoko for Palworld

*[日本語](README.md)*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/pandrabox/Uchinoko)](https://github.com/pandrabox/Uchinoko/releases)
[![Build](https://github.com/pandrabox/Uchinoko/actions/workflows/build.yml/badge.svg)](https://github.com/pandrabox/Uchinoko/actions/workflows/build.yml)

**A tool for VRChatters who want to play Palworld as their own avatar.**
(Formerly named DiveToPalworld. Renamed in v2.0.0.)
Just drop in a prefab or VRM file, and it replaces the Palworld player model with your own avatar.
Take your usual avatar and run wild across the world of Palworld!


## Features
- Simple: launch the exe -> drop in a file -> convert
- Fully local: your avatar data is never sent anywhere
- Modular Avatar support: the avatar you always use works as-is
- Reversible: restore the original state with one button
- No setup required: all you need is a Palworld and VRChat (Unity) environment

## Download

Get the latest release from [GitHub Releases](https://github.com/pandrabox/Uchinoko/releases).
It is also available on [BOOTH](https://osaki-vrc.booth.pm/items/8662197) (pay-what-you-want).

Windows binaries are intended to be code-signed using a certificate provided by the
[SignPath Foundation](https://signpath.org/). We are preparing to submit the signing
application (as of 2026-07, **the application has not been submitted yet**).
<!-- TODO: once the application is submitted, update this note to say it is now awaiting
     review; once signing is approved, update this note to reflect that signing is active -->
Once submitted and approved, it will be applied to future releases. After that, the SmartScreen
warning described below (under "If something goes wrong") is expected to no longer appear.

## System Requirements
- Windows 11
- Palworld 1.0.1 (or later; Steam version only — Xbox / Game Pass is not supported. See the in-app notes for the latest verified version)
- Unity 2022.3.22f1 (not needed for VRM input)
- A PC with a GPU
- Internet connection (on first launch, the tool automatically downloads Blender, about 350MB. See the bundled MANUAL for details)

## How to Use
- See the bundled MANUAL. The download includes both `manual.html` (Japanese) and
  `manual.en.html` (English, generated from
  [`manual/manual.en.md`](manual/manual.en.md)).
- On first launch, Windows may show a SmartScreen warning ("Windows protected your PC"). See
  "About the SmartScreen Warning" below for details.

## Supported Scope
- Input: a Humanoid Avatar prefab, or VRM 0.0 / 1.0
- Full Modular Avatar support. NDMF plugins other than Modular Avatar are not supported (they are intentionally removed during conversion)
- Only Humanoid bones are supported. Anything else is transferred to the nearest Humanoid bone ancestor
- Shadow strength adjustment (in-game only; the preview image does not change)

## Not Yet Supported (may be supported in the future)
- Dynamic bones / cloth physics (jiggle)

## Not Supported (will not be supported, now or in the future)
- Multiplayer
- Double-sided shaders
- Overriding collab outfits
- Unity 2019
- Using this tool together with other pak MODs (a warning is shown if another pak MOD is detected)

## About Collab Outfits
- While a collab outfit is equipped in Palworld, this tool's overwrite is skipped

| Collab | Unsupported outfits |
|---|---|
| Terraria | Holy Plate / Holy Mask / Holy Headgear / Holy Helm / Holy Hood / Moon Lord's Mask / Cthulhu's Eye Mask |
| ULTRAKILL | V1 Armor / V2 Armor |

**Workaround**: use the **"Antique Dresser"** (Ancient tech, Lv. 24) to change into an
appearance other than these outfits before using this tool.


## About the SmartScreen Warning

On first launch, Windows may show a SmartScreen warning ("Windows protected your PC" /
"Unknown publisher"). **This does not mean the tool is dangerous.**

- **Why it appears**: This tool is an individually developed executable with no code
  signature. SmartScreen evaluates a file's reputation, and this warning tends to appear for
  two reasons: (1) with no signature and not yet a large distribution volume, reputation has
  not accumulated, and (2) every build produces different bytes, so each release is treated as
  a file "never seen before."
- **How to launch**: If the warning appears, click "More info," then "Run anyway."
- **How to verify this yourself**: Every build is produced by a public GitHub Actions
  workflow, so anyone can review the build steps and logs
  ([Actions](https://github.com/pandrabox/Uchinoko/actions)). The source code is fully public
  as well ([repository](https://github.com/pandrabox/Uchinoko)).
- **What changes once signing is obtained**: Once code signing through the
  [SignPath Foundation](https://signpath.org/) is approved, the executable's file properties
  are expected to show a verifiable publisher name (SignPath Foundation). **Signing has not
  been obtained yet** — see "Code Signing" below for details.
  <!-- TODO: once signing is obtained, update this with steps for verifying the publisher name
       (Properties -> Digital Signatures tab). -->
- If this does not resolve the issue, or you are unsure, please contact us via "Contact" below.


## If something goes wrong: Security software blocks the tool as a "severe threat"

Because this tool is an individually developed, unsigned executable, generic heuristic/ML-based
detection in security software (such as Windows Defender) can sometimes flag and block it as a
"severe threat." This is a different symptom from the "unknown publisher" warning, and it does
not mean the tool actually contains malware.

- **The cause is structural.** As a small, unsigned executable, every build produces different
  bytes, so security software evaluates it as a file it has "never seen before" each time.
- **It is still detected today.** Our most recent measurement (2026-07-30, the single application
  binary after removing the launcher) was flagged by **3 of 74** VirusTotal engines.
  **Detection varies build to build** — if you are blocked, you can also try an earlier version
  still available on the distribution page. We have since removed more code and have not
  re-tested the current build, so we cannot state today's exact count.
- **A controlled experiment confirmed the detection is unrelated to this tool's code.** A
  do-nothing empty program built with the same compiler was flagged more, not less: **12 of 74**
  engines with assembly metadata, **4 of 74** without — both higher than the real application's
  3 of 74. See the "A note on antivirus false positives" section of [SECURITY.md](SECURITY.md)
  for details.
- If you want to verify this yourself, all builds are produced by a public GitHub Actions
  workflow, so anyone can build from source using the same steps and check the result
  ([repository](https://github.com/pandrabox/Uchinoko)).
- As a permanent fix, we are working on code signing (the application has not been submitted
  yet) — see **Code Signing** below for details.
- We do not provide instructions for changing your security software's settings (such as adding
  exclusions). If the issue persists, please contact us using the in-app "Inquiry" button
  described in the **Contact** section below.


## Code Signing

We are currently **preparing to submit an application for free code signing through the
[SignPath Foundation](https://signpath.org/)** (as of 2026-07, **the application has not been
submitted yet, and signing has not been obtained**). <!-- TODO: once the application is
submitted, update this section to say it has been submitted and is now awaiting review; once
signing is obtained, update this section with instructions for verifying that the executable's
publisher is "SignPath Foundation." -->

SignPath Foundation is a non-profit that provides free certificates to open-source projects,
including comparable tools that parse and convert proprietary game data formats from other
titles (e.g. CryEngine Converter, ValveResourceFormat). Once signing is obtained, the executable
will carry a verifiable publisher identity, which should help with the "every build starts from
zero reputation" issue described above.

For transparency: the diagnostic report sent via the in-app "Inquiry" button is only sent when
the user explicitly clicks that button. See [PRIVACY.en.md](PRIVACY.en.md) for details on what
is sent.

Governance information such as the signing request approvers/committers is documented in
[CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md).


## Contact

For bug reports, requests, or rights-related concerns, please use the "Contact" button
in the app. You can review and edit the diagnostic log before sending it, and check the
status of your inquiry afterward on a dedicated page.


## About This Tool

This is an **unofficial, fan-made tool**.
**It is not affiliated with, endorsed by, or related to Pocketpair, Inc. or the Palworld team in any way.**
Palworld is a trademark of Pocketpair, Inc.


## Disclaimer
This tool is distributed after being verified safe in the author's own environment, but the
risk of accidents is never zero, so backing up your data is recommended:
- The source Unity project used for conversion
- Your Palworld save data
The author accepts no liability for any disadvantage arising from the use of this tool.


## License

The tool itself is under the **MIT License** ([LICENSE](LICENSE)).

The **full distribution package** bundles the following
third-party software, each under its own license, separate from the tool itself:

The paths in the table below reflect the new flat layout produced by current
source/CI (the full application placed directly at the package root).
**The currently downloadable release (v2.2.12) predates this change and
still ships the old `_internal\` layout** (this will only reach the
distributed package starting with the next release — see "A note on
antivirus false positives" in [SECURITY.md](SECURITY.md) for why we have not
cut that release yet). If you are using v2.2.12, prefix every path below
with `_internal\`.

| Component | License | Bundling / Source |
|---|---|---|
| Blender 4.3.2 Portable (unmodified official build) | GPL | Not included in the distributed package. Automatically downloaded from the official site [blender.org](https://www.blender.org/download/) on first launch and placed in `assets\tools\` |
| VRM Add-on for Blender 4.4.0 | MIT | Bundled in `third_party\` (`assets\third_party\` in the distributed package). Source: [VRM-Addon-for-Blender](https://github.com/saturday06/VRM-Addon-for-Blender) |
| pyooz 0.0.8 (`ooz.pyd` etc.) | GPLv3+ | Used to decompress the Oodle-compatible compression (ooz) used by Palworld's pak files. Only the patch material is bundled in `assets\blender_patch\`, and it is placed into the Blender Python environment (downloaded on first launch) at that time. Source: [PyPI](https://pypi.org/project/pyooz/) / [GitHub](https://github.com/zao/pyooz) |

Only `pipeline\py\ooz_worker_gpl.py` is GPLv3+. The pyooz source is bundled in `third_party\pyooz-0.0.8-source\`.

For a detailed list of third-party components, their sources, and the license boundary
explanation, see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). For the provenance of the
Unreal Engine format asset files bundled under `pipeline\py\noue_master\`, see
[PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md).


## Building From Source

The distributed zip (the BOOTH full-set package) is built with `pwsh -File build\make_dist.ps1`.
Since v2.0.0, the Blender portable build is no longer bundled in this build zip; users instead
fetch it from the official site on first launch via `pipeline\cli\ensure_blender.ps1`, so you no
longer need to prepare the Blender portable build yourself when building.
There are two prerequisites that a plain clone of this repository does not provide (both must be
obtained separately for licensing reasons, and cannot be bundled in the repository):

| Prerequisite | Source | How to place it |
|---|---|---|
| pyooz 0.0.8 (`ooz.pyd`) | `pip install pyooz`, or build it from the bundled source at `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` | Auto-detected if present in the user site-packages of your Python 3.13 environment (the default `pip install` location) |
| python3.dll (Python 3.11, stable ABI redirector) | Install Python 3.11 (64-bit) from the official site [python.org](https://www.python.org/downloads/release/python-3110/) | Auto-detected if installed in the default location. If placed elsewhere, set the full path in the `D2P_PYTHON311_DLL` environment variable |

You also need .NET Framework 4.8 (`csc.exe`, bundled with Windows 11) and PowerShell 7+ (`pwsh`).

If you run `build\make_dist.ps1` without these prerequisites in place, it stops the build and
tells you exactly what is missing and where to get it (it is not designed to fail silently).

Once everything is in place, running `pwsh -File build\make_dist.ps1` produces
`dist\Uchinoko_for_Palworld_vX.Y.Z_full.zip`.

For more detailed build instructions (building just the exe, verification records,
and an honest list of what is not yet verified), see [BUILD.md](BUILD.md).


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute, [SECURITY.md](SECURITY.md)
for how to report a vulnerability, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the
code of conduct participants are expected to follow.
If you are auditing or reviewing this repository from the outside, see
[REVIEWER_NOTES.md](REVIEWER_NOTES.md) for a one-page summary linking the key documents.
