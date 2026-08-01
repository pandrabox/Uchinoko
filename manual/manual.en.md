# How to Use Uchinoko for Palworld — VRChat Avatar Edition

*[日本語](manual.md)* (한국어 / 繁體中文 / 简体中文: coming soon)

**Note:** The app's appearance changed in v2.3.0, but the button layout and the operating steps are the same as before. Screenshots will be updated over time.

## Using Your Avatar
Open your avatar's Unity project (works with Unity 2022.3.22f1).
![](img/2.webp)

Drag your avatar from the Hierarchy and drop it directly under Assets (this turns it into a prefab).
![](img/3.webp)

Right-click the icon you just created and choose "Show in Explorer."
**Quit Unity.**
![](img/4.webp)

Open Uchinoko for Palworld by double-clicking Uchinoko.bat. The first time, a warning such as "The publisher could not be verified" may appear — it is fine to choose "Open" (or "Run") to continue.
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
      directly into the `res\assets\tools\blender-4.3.2-windows-x64\` folder, located next to
      Uchinoko.bat (create the folder if it does not exist. **In older versions — v2.2.x and
      earlier — this folder is instead located next to the executable, at
      `assets\tools\blender-4.3.2-windows-x64\` or
      `_internal\assets\tools\blender-4.3.2-windows-x64\`**).


## If something goes wrong: Security software shows a warning or blocks the tool

Some antivirus products were reported to warn about or remove the downloaded files. Starting
with v2.3.0, the package no longer contains any executable (.exe) files. If you run into
problems, please contact us via the in-app "Contact" button.


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
