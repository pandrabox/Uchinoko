"""dev#532 WP-B1: negative-control test for packaging\\check_signatures.py.

Self-contained (no network, no dependency on any prior build.py run):
  - positive control: a copy of C:\\Windows\\System32\\notepad.exe (Microsoft-
    signed on every real Windows install) placed under a name NOT in the
    self-made-names allowlist -> must classify as Signed=True and must not
    break the gate.
  - negative control: a deliberately garbage byte stream saved as
    "Uchinoko.exe" (a name that IS in the default self-made-names allowlist)
    -> Get-AuthenticodeSignature must NOT report it Valid, so the gate must
    flip to GATE=FAIL.

Run directly: `python packaging\\tests\\test_check_signatures.py`
(uses only stdlib; no pytest dependency required, though pytest can also
collect this file since assertions are plain `assert`).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_signatures  # noqa: E402

NOTEPAD = Path(r"C:\Windows\System32\notepad.exe")


def _build_positive_only_payload(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(NOTEPAD, root / "signed_reference.exe")


def _add_negative_control(root: Path) -> None:
    # Not a real PE at all. Get-AuthenticodeSignature must gracefully report
    # a non-Valid status for this (verified empirically: "UnknownError"),
    # not raise - this is the same shape of "unsigned self-made artifact"
    # that check_signatures.ps1's original negative control (the real
    # unsigned Uchinoko.exe from v2.2.14) caught.
    (root / "Uchinoko.exe").write_bytes(
        b"not a real PE file - negative control for dev#532 WP-B1 gate test\n" * 4
    )


def test_positive_only_passes_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_sigtest_pos_") as tmp:
        root = Path(tmp)
        _build_positive_only_payload(root)
        rows, gate_pass = check_signatures.classify(root)
        assert len(rows) == 1, rows
        assert rows[0].signed is True, rows[0]
        assert rows[0].status == "Valid", rows[0]
        assert gate_pass is True, "positive-only payload must pass the gate"


def test_negative_control_flips_gate_to_fail() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_sigtest_neg_") as tmp:
        root = Path(tmp)
        _build_positive_only_payload(root)
        _add_negative_control(root)
        rows, gate_pass = check_signatures.classify(root)
        assert len(rows) == 2, rows
        by_name = {r.rel_path: r for r in rows}
        assert by_name["signed_reference.exe"].signed is True
        neg = by_name["Uchinoko.exe"]
        assert neg.signed is False, neg
        assert neg.status != "Valid", neg
        assert neg.self_made_name_match is True
        assert gate_pass is False, "unsigned self-made-named PE must fail the gate"


def test_write_report_matches_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_sigtest_report_") as tmp:
        root = Path(tmp)
        _build_positive_only_payload(root)
        _add_negative_control(root)
        rows, gate_pass = check_signatures.classify(root)
        report_path = root.parent / "report.txt"
        written_pass = check_signatures.write_report(rows, report_path)
        assert written_pass == gate_pass
        text = report_path.read_text(encoding="utf-8")
        assert "GATE=FAIL" in text
        assert "SELF_MADE_NAME_MATCHES_UNSIGNED=1" in text


def _run_all() -> int:
    tests = [
        test_positive_only_passes_gate,
        test_negative_control_flips_gate_to_fail,
        test_write_report_matches_gate,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR: {t.__name__}: {exc!r}")
    print(f"---\n{len(tests) - failures}/{len(tests)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
