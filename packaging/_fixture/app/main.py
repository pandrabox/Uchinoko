"""dev#532 WP-B1 fixture app.

Stands in for the real app_py\\main.py (WP-A1, not yet landed as of this WP).
Demonstrates the console-hidden + log-file pattern that build.py's generated
Uchinoko.bat relies on:

  - pythonw.exe has no console, so sys.stdout/sys.stderr are only valid when
    something sets up a real file handle for them before this module's code
    runs. Historically (pre dev#593) that was Uchinoko.bat itself, via
    `pythonw.exe ... > res\\logs\\launch.log 2>&1`. Since dev#593, the bat
    launches pythonw.exe asynchronously via `start ""` (so its own console
    window can close immediately) and does no redirection at all, so
    sys.stdout/sys.stderr are always None when this script is launched that
    way. This fixture therefore opens res\\logs\\launch.log itself (same
    minimal pattern as app_py\\main.py's `_setup_launch_log()`, dev#593)
    before doing anything else, so print()/faulthandler output still lands
    in the log file the way build.py's self_test_bat() expects.
  - faulthandler.enable() (default target: sys.stderr) additionally captures
    native crashes (segfaults) into the same log file.

This stub does NOT open a visible window (per WP-B1 instructions: GUI-opening
verification on the build host is out of scope, deferred to WSB). It proves
tkinter itself is wired up correctly by creating a Tk root, withdrawing it
immediately (no visible window), and destroying it.
"""
import os
import sys

APP_VERSION = "wp532-b1-fixture-0.1"


class _NullWriter:
    """dev#593: last-resort fallback if launch.log cannot be opened (e.g.
    permissions). Keeps the fixture from crashing on a None stdout/stderr
    even when logging itself is unavailable."""

    def write(self, _s: object) -> int:
        return 0

    def flush(self) -> None:
        return None


def _setup_launch_log() -> None:
    """dev#593 minimal log setup, mirroring app_py\\main.py's
    `_setup_launch_log()`. Only acts when sys.stdout/sys.stderr are not
    already usable (always true under the async `start ""` bat launch;
    a no-op when run directly under a real console, e.g. `python main.py`
    during development)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(app_root, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(
            os.path.join(log_dir, "launch.log"),
            "w",
            encoding="utf-8",
            errors="backslashreplace",
            buffering=1,
        )
    except OSError:
        sys.stdout = _NullWriter()
        sys.stderr = _NullWriter()
        return
    if sys.stdout is None:
        sys.stdout = log_file
    if sys.stderr is None:
        sys.stderr = log_file


_setup_launch_log()

import faulthandler  # noqa: E402


def main() -> int:
    faulthandler.enable()  # default target: sys.stderr -> now always a real stream
    print("Uchinoko fixture app: import OK")
    print(f"APP_VERSION={APP_VERSION}")
    print(f"python={sys.version.split()[0]} executable={sys.executable}")

    import tkinter

    root = tkinter.Tk()
    root.withdraw()  # never show a window during this smoke check
    tk_version = str(tkinter.TkVersion)
    root.destroy()
    print(f"TK_OK TkVersion={tk_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
