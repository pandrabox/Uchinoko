# How to Use Uchinoko for Palworld — VRChat Avatar Edition

*[日本語](manual.md) | [한국어](manual.ko.md) | [繁體中文](manual.zh-TW.md) | [简体中文](manual.zh-CN.md)*

## Using Your Avatar
Open your avatar's Unity project (works with Unity 2022.3.22f1).
![](img/2.webp)

Drag your avatar from the Hierarchy and drop it directly under Assets (this turns it into a prefab).
![](img/3.webp)

Right-click the icon you just created and choose "Show in Explorer."
**Quit Unity.**
![](img/4.webp)

Open Uchinoko for Palworld (Uchinoko.exe).
![](img/1.webp)

**The first time only**, Uchinoko automatically downloads the Blender build (about 350MB) needed
for conversion in the background (no dialog appears). While it's getting ready, the status area
at the bottom of the window shows a "setting up" message, and buttons like "Full Convert" stay
disabled. Depending on your connection this can take a few minutes, but **please just wait**. If
you drag and drop a file before setup finishes, it will be processed automatically once setup
completes. If it doesn't go well, see "If something goes wrong" below.

Drag and drop your avatar's prefab file from Explorer onto Uchinoko for Palworld.
![](img/5.webp)

Wait a little while.
![](img/6.webp)

Once a thumbnail appears and "Full Convert (Create MOD)" becomes clickable, click it.
![](img/7.webp)

A terms-of-use dialog appears — please review it and agree.
![](img/8.webp)

After a short wait, the MOD is applied (please make sure Palworld is closed).
![](img/9.webp)


## If something goes wrong: Windows shows "Windows protected your PC" on first launch

This is a SmartScreen warning caused by the executable being unsigned, since this is an
individually developed tool. Click **"More info"** on the screen that appears, then click the
**"Run anyway"** button that shows up to launch it.


## If something goes wrong: First-time setup (downloading Blender) fails

Because of internet connectivity issues and similar causes, the automatic Blender download on
first launch can sometimes fail. If drag-and-drop never finishes loading, or it stops with an
error, suspect this first.

1. Check your internet connection, then either restart Uchinoko for Palworld or click the
   "Retry Blender Setup" button in the bottom right of the window.
2. If it still fails, you can set it up manually.
   1. Download the Windows x64 build (Portable/zip) of Blender 4.3.2 from
      https://www.blender.org/download/.
   2. Extract the downloaded zip, and copy the contents of the folder that contains `blender.exe`
      directly into the `assets\tools\blender-4.3.2-windows-x64\` folder, located next
      to Uchinoko for Palworld (**in some versions this folder is instead located at
      `_internal\assets\tools\blender-4.3.2-windows-x64\`** — check whether there is an
      `_internal` folder next to Uchinoko for Palworld to tell which layout you have).


## If something goes wrong: Security software blocks the tool as a "severe threat"

Because this tool is an individually developed, unsigned executable, generic heuristic/ML-based
detection in security software such as Windows Defender can sometimes flag and block it as a
"severe threat." This is a stronger symptom than the "unknown publisher" warning, and it does
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
  3 of 74. See the "A note on antivirus false positives" section of
  [SECURITY.md](../SECURITY.md) for details.
- If you want to verify this yourself, all builds are produced by a public GitHub Actions
  workflow, so anyone can build from source using the same steps and check the result
  ([repository](https://github.com/pandrabox/Uchinoko)).
- As a permanent fix, we are **preparing to submit an application for code signing through the
  [SignPath Foundation](https://signpath.org/)** (as of 2026-07, the application has not been
  submitted yet, and signing has not been obtained). A signed binary carries a verifiable
  publisher identity, which should substantially reduce this kind of false positive.
  <!-- TODO: once submitted, update this to say it has been submitted and is now awaiting
       review; once signing is obtained, update this note accordingly -->
- We do not provide instructions for changing your security software's settings (such as adding
  exclusions). If the issue persists, please contact us using the in-app "Inquiry" button.


## Tips

- This tool is meant for playing with your own avatar by yourself. It does not support multiplayer or similar.
- Using this tool together with other pak MODs is not supported. A warning is shown if another pak MOD is detected.
- The menu in the bottom right lets you do several things:
  - Apply to Palworld... use this when you've converted multiple avatars and want to switch between
    them, or when the conversion finished but Palworld was running and the MOD couldn't be applied
  - Remove MOD... use this when you want to remove the currently applied MOD
  - Refresh List... refreshes the list of MODs
  - Delete Conversion Result... use this when you want to delete a character you no longer need
  - Contact... use this if you run into trouble
  - Copy Log Manually... attaching this to your inquiry makes it much easier for us to help you
