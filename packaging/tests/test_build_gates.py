"""dev#532 D1: negative-control tests for app_py\\build.py's shipping gates
(gate_bat_isolation / gate_pth_content).

These two gates are the machine-checkable form of the dev#532 comment-thread
constraint: "bat is %~dp0-relative only (no bare python reference) + -E +
explicit TCL_LIBRARY/TK_LIBRARY overrides. python3xx._pth content is
cross-checked by the shipping gate."

Self-contained (no network, no real embeddable Python download): builds tiny
synthetic Uchinoko.bat / python3xx._pth fixtures on disk and checks both the
positive case (the real templates from build.py) and negative controls
(deliberately broken variants) so the gate is proven to actually catch
regressions, not just rubber-stamp whatever it's given (CLAUDE.md "検証の作法":
"負の対照を取る").

Run directly: `python packaging\\tests\\test_build_gates.py`
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app_py"))
import build  # noqa: E402


def test_real_hidden_bat_template_passes_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_batgate_pos_") as tmp:
        bat = Path(tmp) / "Uchinoko.bat"
        bat.write_text(build.BAT_TEMPLATE_HIDDEN, encoding="utf-8")
        ok, problems = build.gate_bat_isolation(bat)
        assert ok, problems


def test_real_console_bat_template_passes_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_batgate_pos_console_") as tmp:
        bat = Path(tmp) / "Uchinoko.bat"
        bat.write_text(build.BAT_TEMPLATE_CONSOLE, encoding="utf-8")
        ok, problems = build.gate_bat_isolation(bat)
        assert ok, problems


def test_missing_dash_e_flag_fails_gate() -> None:
    """負の対照: -E フラグを落とすと環境隔離が破れる(PYTHON*環境変数の
    ユーザー上書きを許してしまう)ため、必ず検出できること。"""
    broken = build.BAT_TEMPLATE_HIDDEN.replace(
        'pythonw.exe" -E -X utf8 "%HERE%res\\app\\main.py"',
        'pythonw.exe" -X utf8 "%HERE%res\\app\\main.py"',
    )
    assert " -E " not in broken
    with tempfile.TemporaryDirectory(prefix="d2p_batgate_neg_e_") as tmp:
        bat = Path(tmp) / "Uchinoko.bat"
        bat.write_text(broken, encoding="utf-8")
        ok, problems = build.gate_bat_isolation(bat)
        assert not ok, "removing -E must fail the gate"
        assert any("-E" in p or "-E " in p for p in problems), problems


def test_missing_tcl_library_override_fails_gate() -> None:
    """負の対照: TCL_LIBRARY/TK_LIBRARYの明示上書きを落とすと、環境変数の
    汚染(別バージョンのTcl/Tkがpath上にある等)でtkinterが壊れうる。"""
    broken = "\n".join(
        line
        for line in build.BAT_TEMPLATE_HIDDEN.splitlines()
        if "TCL_LIBRARY" not in line and "TK_LIBRARY" not in line
    )
    with tempfile.TemporaryDirectory(prefix="d2p_batgate_neg_tcl_") as tmp:
        bat = Path(tmp) / "Uchinoko.bat"
        bat.write_text(broken, encoding="utf-8")
        ok, problems = build.gate_bat_isolation(bat)
        assert not ok, "removing TCL_LIBRARY/TK_LIBRARY overrides must fail the gate"


def test_bare_python_reference_fails_gate() -> None:
    """負の対照: %HERE%res\\python_embed\\ を経由しない裸のpython(w).exe参照
    (PATH依存、環境隔離を破る)は検出できること。"""
    broken = build.BAT_TEMPLATE_HIDDEN + '\n"pythonw.exe" "somewhere_else.py"\n'
    with tempfile.TemporaryDirectory(prefix="d2p_batgate_neg_bare_") as tmp:
        bat = Path(tmp) / "Uchinoko.bat"
        bat.write_text(broken, encoding="utf-8")
        ok, problems = build.gate_bat_isolation(bat)
        assert not ok, "a bare python(w).exe reference outside python_embed must fail the gate"


def test_missing_bat_fails_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_batgate_missing_") as tmp:
        ok, problems = build.gate_bat_isolation(Path(tmp) / "does_not_exist.bat")
        assert not ok
        assert problems


_GOOD_PTH = "python311.zip\n.\n#import site\n"
_BAD_PTH_NO_DOT = "python311.zip\n#import site\n"
_BAD_PTH_SITE_ENABLED = "python311.zip\n.\nimport site\n"


def test_good_pth_passes_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_pthgate_pos_") as tmp:
        embed_dir = Path(tmp)
        (embed_dir / "python311._pth").write_text(_GOOD_PTH, encoding="utf-8")
        ok, problems = build.gate_pth_content(embed_dir)
        assert ok, problems


def test_pth_missing_dot_entry_fails_gate() -> None:
    """負の対照: '.' が無いとアプリ本体/tkinter DLLがsys.pathに載らず起動しない。"""
    with tempfile.TemporaryDirectory(prefix="d2p_pthgate_neg_dot_") as tmp:
        embed_dir = Path(tmp)
        (embed_dir / "python311._pth").write_text(_BAD_PTH_NO_DOT, encoding="utf-8")
        ok, problems = build.gate_pth_content(embed_dir)
        assert not ok, "missing '.' entry must fail the gate"


def test_pth_site_enabled_fails_gate() -> None:
    """負の対照: 'import site' が有効化されると、user-site/PYTHONPATH経由で
    ピン留めしたランタイム外のパッケージが紛れ込みうる(実行時pip禁止の趣旨に反する)。"""
    with tempfile.TemporaryDirectory(prefix="d2p_pthgate_neg_site_") as tmp:
        embed_dir = Path(tmp)
        (embed_dir / "python311._pth").write_text(_BAD_PTH_SITE_ENABLED, encoding="utf-8")
        ok, problems = build.gate_pth_content(embed_dir)
        assert not ok, "active 'import site' must fail the gate"


def test_pth_missing_file_fails_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_pthgate_missing_") as tmp:
        ok, problems = build.gate_pth_content(Path(tmp))
        assert not ok
        assert problems


# --- dev#577: python3.dllフォワード先検証(blender_patch混入事故の再発防止) ---
# v2.3.0 D1ビルドで、Python 3.13由来のpython3.dll(python313へフォワード)が
# blender_patchに混入し、開発機(PATHにpython313.dllあり)では動くのに
# クリーンなWSB/実ユーザー機でだけ import ooz がDLL load failedになった。
# 検証はエクスポート転送文字列(python3XX)そのものを見る。

def _fake_redirector(tmp: str, name: str, targets: list[bytes]) -> Path:
    p = Path(tmp) / name
    body = b"MZ fake redirector " + b" ".join(t + b".PyObject_Str" for t in targets)
    p.write_bytes(body)
    return p


def test_python3_dll_forwarding_to_python311_passes() -> None:
    with tempfile.TemporaryDirectory(prefix="d2p_py3dll_pos_") as tmp:
        p = _fake_redirector(tmp, "python3.dll", [b"python311"])
        assert build._validate_python3_dll(p, "test") == p


def test_python3_dll_forwarding_to_python313_fails() -> None:
    """負の対照(実事故の再現): 3.13由来のリダイレクタは必ず弾くこと。"""
    with tempfile.TemporaryDirectory(prefix="d2p_py3dll_neg313_") as tmp:
        p = _fake_redirector(tmp, "python3.dll", [b"python313"])
        try:
            build._validate_python3_dll(p, "test")
        except SystemExit as exc:
            assert "python313" in str(exc) and "python311" in str(exc)
        else:
            raise AssertionError("python313-forwarding dll must be rejected")


def test_python3_dll_with_no_forward_target_fails() -> None:
    """負の対照: リダイレクタですらないファイル(転送文字列なし)も弾くこと。"""
    with tempfile.TemporaryDirectory(prefix="d2p_py3dll_negnone_") as tmp:
        p = Path(tmp) / "python3.dll"
        p.write_bytes(b"MZ not a redirector at all")
        try:
            build._validate_python3_dll(p, "test")
        except SystemExit:
            pass
        else:
            raise AssertionError("non-redirector dll must be rejected")


def test_resolve_python3_dll_prefers_env_override_and_validates(monkeypatch=None) -> None:
    """D2P_PYTHON311_DLLの明示指定も検証を通ること(誤った3.13指定はビルド失敗)。"""
    import os as _os

    with tempfile.TemporaryDirectory(prefix="d2p_py3dll_resolve_") as tmp:
        bad = _fake_redirector(tmp, "bad_python3.dll", [b"python313"])
        old = _os.environ.get("D2P_PYTHON311_DLL")
        _os.environ["D2P_PYTHON311_DLL"] = str(bad)
        try:
            try:
                build._resolve_python3_dll(Path(tmp))
            except SystemExit:
                pass
            else:
                raise AssertionError("env-override pointing at a 3.13 dll must abort the build")
            # 正しい個体なら通る
            good = _fake_redirector(tmp, "good_python3.dll", [b"python311"])
            _os.environ["D2P_PYTHON311_DLL"] = str(good)
            assert build._resolve_python3_dll(Path(tmp)) == good
        finally:
            if old is None:
                _os.environ.pop("D2P_PYTHON311_DLL", None)
            else:
                _os.environ["D2P_PYTHON311_DLL"] = old


def test_resolve_python3_dll_defaults_to_python_embed() -> None:
    """既定経路: python_embed\\python3.dll(ピン留め済みembeddable由来)を使うこと。"""
    import os as _os

    with tempfile.TemporaryDirectory(prefix="d2p_py3dll_embed_") as tmp:
        embed = Path(tmp)
        _fake_redirector(tmp, "python3.dll", [b"python311"])
        old = _os.environ.pop("D2P_PYTHON311_DLL", None)
        try:
            assert build._resolve_python3_dll(embed) == embed / "python3.dll"
        finally:
            if old is not None:
                _os.environ["D2P_PYTHON311_DLL"] = old


def _run_all() -> int:
    tests = [
        test_real_hidden_bat_template_passes_gate,
        test_real_console_bat_template_passes_gate,
        test_missing_dash_e_flag_fails_gate,
        test_missing_tcl_library_override_fails_gate,
        test_bare_python_reference_fails_gate,
        test_missing_bat_fails_gate,
        test_good_pth_passes_gate,
        test_pth_missing_dot_entry_fails_gate,
        test_pth_site_enabled_fails_gate,
        test_pth_missing_file_fails_gate,
        test_python3_dll_forwarding_to_python311_passes,
        test_python3_dll_forwarding_to_python313_fails,
        test_python3_dll_with_no_forward_target_fails,
        test_resolve_python3_dll_prefers_env_override_and_validates,
        test_resolve_python3_dll_defaults_to_python_embed,
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
