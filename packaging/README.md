# packaging\ (dev#532 WP-B1)

Builds the bat + embeddable-Python distributable that replaces the old
`app\build_app.ps1` (csc.exe / WinForms exe) toolchain. Driven by
`app_py\build.py`; nothing here is meant to be run standalone except the
signature gate and its test.

## Files

- `check_signatures.py` - Python-native PE signature classifier (successor
  to the one-off `work\wp532\proto\check_signatures.ps1` prototype). Scans a
  payload directory for `*.exe`/`*.dll`/`*.pyd`, classifies each as
  signed/unsigned via `Get-AuthenticodeSignature`, and fails (`GATE=FAIL`)
  only if a file whose *name* matches our own build output (default:
  `Uchinoko.exe`, `DiveToPalworld.exe`) is unsigned. Third-party unsigned PEs
  (e.g. pyooz's `ooz.pyd`, a known accepted residual risk - see
  `work\wp532\PROPOSAL.md` SS5) are reported but do not fail the gate.

  ```
  python packaging\check_signatures.py --payload-dir <dir> --report <path>
  ```

- `tests\test_check_signatures.py` - self-contained negative-control test
  (no network, no prior build required). Positive control: a copy of
  `notepad.exe`. Negative control: a garbage byte stream saved as
  `Uchinoko.exe`, which must NOT be classified `Valid` and must flip the
  gate to `FAIL`.

  ```
  python packaging\tests\test_check_signatures.py
  ```

- `_fixture\app\main.py` - stand-in app used by `build.py --fixture` until
  WP-A1 (`app_py\main.py` and friends) lands. Demonstrates the
  console-hidden + redirected-log-file + `faulthandler` pattern that the
  real app should adopt.

- `_cache\` (gitignored) - downloaded python.org artifacts and the
  extracted tkinter bundle, cached across builds.

- `dist\` (gitignored) - default build output (`app_py\build.py`'s `--out`).

## Payload layout produced by `app_py\build.py`

Per owner directive (dev#532 WP-B1 amendment), the payload root contains
**only** these three entries - `build.py` verifies this and fails the build
otherwise:

```
Uchinoko.bat        <- entry point (non-PE)
README.txt
res\
  python_embed\     <- python.org embeddable Python + tkinter overlay
  app\              <- application source (or the _fixture stub)
  licenses\         <- this app's LICENSE, THIRD_PARTY_NOTICES.md,
                       PYTHON_LICENSE.txt, TCL_TK_LICENSE.txt
  logs\             <- created on first run; launch.log lands here
```

See `app_py\build.py`'s module docstring for the full tkinter-bundling
procedure (python.org embeddable zips do not include tkinter; the runtime
pieces are extracted from a scratch install of the official *full*
installer, then the scratch install is uninstalled again).
