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
- Simple: launch `Uchinoko.bat` -> drop in a file -> convert
- Fully local: your avatar data is never sent anywhere
- Modular Avatar support: the avatar you always use works as-is
- Reversible: restore the original state with one button
- No setup required: all you need is a Palworld and VRChat (Unity) environment

## Download

Get the latest release from [GitHub Releases](https://github.com/pandrabox/Uchinoko/releases).
It is also available on [BOOTH](https://osaki-vrc.booth.pm/items/8662197) (pay-what-you-want).

## System Requirements
- Windows 11
- Palworld 1.0.1 (Steam version) — Xbox / Game Pass is not supported
- Unity 2022.3.22f1 (not needed for VRM input)
- A PC with a GPU
- Internet connection (on first launch, the tool automatically downloads Blender, about 350MB)

## How to Use
- Double-click `Uchinoko.bat` to launch it
- The manual is available online: https://dl.osakishokai.com/manual
- On first launch, Windows may show a confirmation screen for the downloaded file. See "About the Startup Confirmation Screen" below for details.

## Supported Scope
- Input: a VRChat prefab (Modular Avatar support) / VRM 0.0 / VRM 1.0
- NDMF plugins other than Modular Avatar are not supported (they are intentionally removed during conversion)
- Only Humanoid bones are supported. Anything else is transferred to the nearest Humanoid bone ancestor
- Shadow strength adjustment (in-game only; the preview image does not change)

## Not Supported
- Dynamic bones / cloth physics (jiggle)
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


## About the Startup Confirmation Screen

On first launch, Windows may show a confirmation screen such as "Windows protected your PC" or
"the publisher could not be verified." **This does not mean the tool is dangerous.**

- **Why it appears**: `Uchinoko.bat` is a file you run from a downloaded zip, and Windows
  sometimes asks for confirmation on files obtained over the internet. The only executable
  bundled with this tool is the official python.org Python runtime — this tool does not bundle
  any self-made executable (exe/dll, etc.).
- **How to launch**: If the confirmation screen appears, review its contents and choose to run
  it.
- **How to verify this yourself**: The source code is available in our
  [public repository](https://github.com/pandrabox/Uchinoko).
- If this does not resolve the issue, or you are unsure, please contact us via "Contact" below.


## On Detection by Antivirus Software

Past versions (up through the v2.2.x line) were sometimes flagged by multiple antivirus
products. We take no position on whether any individual detection was correct. Starting with
v2.3.0, the distributed package no longer contains any self-compiled executable (PE) files. See
the "On detection by antivirus software" section of [SECURITY.md](SECURITY.md) for details.

We do not provide instructions for changing your security software's settings (such as adding
exclusions). If the issue persists, please contact us using "Contact" below.


## Contact

For bug reports, requests, or rights-related concerns, please use the "Contact" button in the
app. You can review and edit the diagnostic log before sending it, and check the status of your
inquiry afterward on a dedicated page.


## About This Tool

This is an **unofficial, fan-made tool**.
**It is not affiliated with, endorsed by, or related to Pocketpair, Inc. or the Palworld team in
any way.**
Palworld is a trademark of Pocketpair, Inc.


## Disclaimer
This tool is distributed after being verified safe in the author's own environment, but the risk
of accidents is never zero, so backing up your data is recommended:
- The source Unity project used for conversion
- Your Palworld save data
The author accepts no liability for any disadvantage arising from the use of this tool.


## License

The tool itself is under the **MIT License** ([LICENSE](LICENSE)).

The **full distribution package** bundles the following third-party software, each under its own
license, separate from the tool itself:

| Component | License | Bundling / Source |
|---|---|---|
| Blender 4.3.2 Portable (unmodified official build) | GPL | Not included in the distributed package. Automatically downloaded from the official site [blender.org](https://www.blender.org/download/) on first launch and placed in `res\assets\tools\` |
| VRM Add-on for Blender 4.4.0 | MIT | Bundled in `res\assets\third_party\`. Source: [VRM-Addon-for-Blender](https://github.com/saturday06/VRM-Addon-for-Blender) |
| pyooz 0.0.8 (`ooz.pyd` etc.) | GPLv3+ | Used to decompress the Oodle-compatible compression (ooz) used by Palworld's pak files. Only the patch material is bundled in `res\assets\blender_patch\`, and it is placed into the downloaded Blender's Python environment on first launch. Source: [PyPI](https://pypi.org/project/pyooz/) / [GitHub](https://github.com/zao/pyooz) |
| Python (embeddable, unmodified official build) | PSF License | Bundled in `res\python_embed\`. Source: [python.org](https://www.python.org/) |
| Tcl/Tk runtime | Tcl/Tk License | Bundled in `res\python_embed\` (extracted from the official python.org full installer) |

Only `pipeline\py\ooz_worker_gpl.py` is GPLv3+. The pyooz source is bundled in
`third_party\pyooz-0.0.8-source\`.

For a detailed list of third-party components, their sources, and the license boundary
explanation, see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).


## Prerequisites for Building From Source

The distributed package (`Uchinoko.bat` + `res\`) is built with `python app_py\build.py`.
There is one prerequisite that a plain clone of this repository does not provide (it cannot be
bundled in the repository for licensing reasons, and must be obtained separately):

| Prerequisite | Source | How to place it |
|---|---|---|
| pyooz 0.0.8 (`ooz.pyd`) | `pip install pyooz`, or build it from the bundled source at `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` | Auto-detected if present in the user site-packages of your Python environment (the default `pip install` location) |

Running `python app_py\build.py` produces the distribution folder (`Uchinoko.bat` /
`README.txt` / `res\`) under `packaging\dist\Uchinoko\` (the Python runtime itself is fetched
automatically from the official python.org embeddable build and bundled; the Blender portable
build is not bundled at this point — it is instead fetched automatically the first time the user
launches the tool).

To build the distributable zip (the BOOTH full-set package), also run
`pwsh -File build\make_dist.ps1` (internally it calls `python app_py\build.py` and then zips
the result). If you run it without these prerequisites in place, it stops the build and tells
you exactly what is missing and where to get it (it is not designed to fail silently). Once
everything is in place, it produces `dist\Uchinoko_vX.Y.Z_full.zip`.

For more detailed build instructions, see [`packaging\README.md`](packaging/README.md).


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute, [SECURITY.md](SECURITY.md) for how
to report a vulnerability, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the code of conduct
participants are expected to follow.
If you are auditing or reviewing this repository from the outside, see
[REVIEWER_NOTES.md](REVIEWER_NOTES.md) for a one-page summary linking the key documents.
