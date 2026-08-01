# test_warm_startup.py -- WP-A9受入条件: warm_startup.py の移植ケース表を
# pytestで検査する(dev#532 方針A、C5が発見した割り当て漏れの穴埋め、
# work\wp532A\C5_NOTES.md §1)。
#
# ケース表は devtools\shipcheck_src\warm_startup_check.cs の
# RunWarmStartupChecks() case1〜case4を、DI(popen差し替え)方式で
# 単体試験へ焼き直したもの(C5_NOTES.md §1.3推奨(b)を採用: 実プロセス起動の
# 確認自体はここでは行わず、ガード判定・ログ配線・例外非伝播だけを検査する。
# 実際にBlenderが起動できることの確認はWSB通し試験=D1のGATEに委ねる)。
#
# 対応表(warm_startup_check.cs -> 本ファイル):
#   case1 (blenderReady=false) -> test_case1_*
#   case2 (runningProc!=null)  -> test_case2_*
#   case3 (条件成立、正例)     -> test_case3_*
#   case4 (負の対照、不正exe)  -> test_case4_*

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import warm_startup  # noqa: E402


def _read(work_root: str, name: str) -> str:
    path = Path(work_root) / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _wait_until(predicate, timeout_sec: float = 5.0, step: float = 0.05) -> bool:
    """完了ログはバックグラウンドスレッドで非同期に書かれるため、C#版の
    WaitForLogContains/WaitForFileExists(devtools\\shipcheck_src\\
    warm_startup_check.cs L.278-304)と同じ短間隔ポーリングで待つ。"""
    waited = 0.0
    while waited < timeout_sec:
        if predicate():
            return True
        time.sleep(step)
        waited += step
    return predicate()


class _FakeProc:
    """subprocess.Popen互換の最小フェイク。stdoutは行のリスト(str、末尾\\n
    有無どちらでも可)をイテレータとして渡す。wait()呼び出し後にreturncodeが
    確定する(実subprocess.Popenと同じ「wait前はNone」の挙動を再現)。"""

    def __init__(self, lines: Optional[List[str]] = None, returncode: int = 0, delay: float = 0.0):
        self.stdout = iter(lines or [])
        self._returncode = returncode
        self._delay = delay
        self.returncode: Optional[int] = None

    def wait(self) -> int:
        if self._delay:
            time.sleep(self._delay)
        self.returncode = self._returncode
        return self.returncode


def _make_recording_popen(fake_proc_factory):
    calls: List[Tuple[tuple, dict]] = []

    def _popen(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        return fake_proc_factory()

    return _popen, calls


# ---------------------------------------------------------------------------
# case1: blenderReady=false -> 両メソッドとも無音を許さない
# ---------------------------------------------------------------------------


def test_case1_blender_not_ready_logs_reason_and_launches_nothing(tmp_path):
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "no_such_blender.exe")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("popen must not be called when blenderReady=false")

    warm_startup.warm_blender_process_on_startup(
        work_root, blender_ready=False, conversion_running=False,
        blender_exe=blender_exe, popen=_must_not_be_called,
    )
    warm_startup.warm_shared_cache_on_startup(
        str(tmp_path), work_root, blender_ready=False, blender_exe=blender_exe,
        pak_path=None, popen=_must_not_be_called,
    )

    log = _read(work_root, "warm_startup.log")
    assert "blender-prewarm: skip (blenderReady=false)" in log
    assert "warm-cache: skip (blenderReady=false)" in log
    assert not (Path(work_root) / "warm_blender.log").exists()
    assert not (Path(work_root) / "warm_cache.log").exists()


# ---------------------------------------------------------------------------
# case2: runningProc(変換中)相当 -> WarmBlenderProcessOnStartupだけskip
# ---------------------------------------------------------------------------


def test_case2_conversion_running_skips_blender_prewarm_only(tmp_path):
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "blender.exe")
    Path(blender_exe).write_text("stub")  # 実在確認ゲートを通すだけ(実行はしない)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("popen must not be called while a conversion is running")

    warm_startup.warm_blender_process_on_startup(
        work_root, blender_ready=True, conversion_running=True,
        blender_exe=blender_exe, popen=_must_not_be_called,
    )

    log = _read(work_root, "warm_startup.log")
    assert "blender-prewarm: skip (conversion already running)" in log
    assert not (Path(work_root) / "warm_blender.log").exists()


# ---------------------------------------------------------------------------
# case3: 条件が揃うと実際にプロセス起動が呼ばれ、完了ログが残る(正例)
# ---------------------------------------------------------------------------


def test_case3_ready_and_idle_launches_and_logs_completion(tmp_path):
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "blender.exe")
    Path(blender_exe).write_text("stub")

    popen, calls = _make_recording_popen(lambda: _FakeProc(returncode=0))

    warm_startup.warm_blender_process_on_startup(
        work_root, blender_ready=True, conversion_running=False,
        blender_exe=blender_exe, popen=popen,
    )

    assert _wait_until(lambda: "exited code=" in _read(work_root, "warm_startup.log"))
    log = _read(work_root, "warm_startup.log")
    assert "blender-prewarm: started" in log
    assert "blender-prewarm: exited code=0" in log
    assert len(calls) == 1
    launched_args = calls[0][0][0]
    assert launched_args[0] == blender_exe
    assert "--background" in launched_args


def test_case3_warm_shared_cache_launches_when_all_guards_pass(tmp_path):
    app_root = str(tmp_path)
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "assets" / "tools" / "blender-9.9.9-windows-x64" / "blender.exe")
    os.makedirs(os.path.dirname(blender_exe), exist_ok=True)
    Path(blender_exe).write_text("stub")
    bpython_dir = os.path.join(os.path.dirname(blender_exe), "9.9", "python", "bin")
    os.makedirs(bpython_dir, exist_ok=True)
    Path(os.path.join(bpython_dir, "python.exe")).write_text("stub")
    pak_path = str(tmp_path / "Pal-Windows.pak")
    Path(pak_path).write_text("stub")
    script_dir = os.path.join(app_root, "pipeline", "py")
    os.makedirs(script_dir, exist_ok=True)
    Path(os.path.join(script_dir, "convert_noue.py")).write_text("# stub")

    popen, calls = _make_recording_popen(lambda: _FakeProc(returncode=0))

    warm_startup.warm_shared_cache_on_startup(
        app_root, work_root, blender_ready=True, blender_exe=blender_exe,
        pak_path=pak_path, popen=popen,
    )

    assert _wait_until(lambda: "exited code=" in _read(work_root, "warm_startup.log"))
    log = _read(work_root, "warm_startup.log")
    assert f"warm-cache: started pak={pak_path}" in log
    assert "warm-cache: exited code=0" in log
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# case4: 負の対照 -- 不正exeでもCLIプロセス自体は落ちず、理由がログに残る
# ---------------------------------------------------------------------------


def test_case4_invalid_exe_does_not_propagate_and_logs_exception(tmp_path):
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "blender.exe")
    # 不正なPE(意図的、warm_startup_check.cs case4と同じ発想)。ガードの
    # File.Exists相当(os.path.isfile)は実在チェックのみなので通過する。
    Path(blender_exe).write_bytes(b"\x00\x01\x02\x03")

    def _raising_popen(*args, **kwargs):
        raise OSError("invalid PE (simulated Process.Start failure)")

    threw = False
    try:
        warm_startup.warm_blender_process_on_startup(
            work_root, blender_ready=True, conversion_running=False,
            blender_exe=blender_exe, popen=_raising_popen,
        )
    except Exception:  # noqa: BLE001 -- ここで例外が漏れたら受入失敗
        threw = True

    assert threw is False, "WarmBlenderProcessOnStartup相当が例外を外へ伝播させた"
    log = _read(work_root, "warm_startup.log")
    assert "blender-prewarm: exception" in log
    assert "invalid PE" in log

    # 「プリウォーム失敗が変換を壊さない」の直接確認: 直後に別の(無関係な)
    # warm呼び出しを行っても例外を伝播しないこと(pakが無い環境なのでskipに
    # なるはずだが、例外は出ないこと)。
    later_threw = False
    try:
        warm_startup.warm_shared_cache_on_startup(
            str(tmp_path), work_root, blender_ready=True, blender_exe=blender_exe,
            pak_path=None, popen=_raising_popen,
        )
    except Exception:  # noqa: BLE001
        later_threw = True

    assert later_threw is False, "後続warm呼び出しが例外を伝播した(失敗の巻き添え)"
    # このblender_exeは不正PEでbpython探索も失敗するため、ガードに引っかかって
    # skipになる(理由の詳細は問わない。ここで検査したいのは「例外を出さず
    # 静かにskipすること」そのもの)。
    log2 = _read(work_root, "warm_startup.log")
    assert "warm-cache: skip" in log2


def test_case4_warm_shared_cache_launch_failure_also_does_not_propagate(tmp_path):
    # warm_shared_cache_on_startup自体のpopen()失敗経路も同じ「失敗は無視」を守ること
    # (case4はC#実装ではWarmBlenderProcessOnStartupのみ対象だが、対称性のため
    # warm-cache側も同じ負の対照を追加で検査する)。
    app_root = str(tmp_path)
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "assets" / "tools" / "blender-9.9.9-windows-x64" / "blender.exe")
    os.makedirs(os.path.dirname(blender_exe), exist_ok=True)
    Path(blender_exe).write_text("stub")
    bpython_dir = os.path.join(os.path.dirname(blender_exe), "9.9", "python", "bin")
    os.makedirs(bpython_dir, exist_ok=True)
    Path(os.path.join(bpython_dir, "python.exe")).write_text("stub")
    pak_path = str(tmp_path / "Pal-Windows.pak")
    Path(pak_path).write_text("stub")
    script_dir = os.path.join(app_root, "pipeline", "py")
    os.makedirs(script_dir, exist_ok=True)
    Path(os.path.join(script_dir, "convert_noue.py")).write_text("# stub")

    def _raising_popen(*args, **kwargs):
        raise OSError("simulated launch failure")

    threw = False
    try:
        warm_startup.warm_shared_cache_on_startup(
            app_root, work_root, blender_ready=True, blender_exe=blender_exe,
            pak_path=pak_path, popen=_raising_popen,
        )
    except Exception:  # noqa: BLE001
        threw = True

    assert threw is False
    log = _read(work_root, "warm_startup.log")
    assert "warm-cache: exception" in log
    assert "simulated launch failure" in log


# ---------------------------------------------------------------------------
# 補助関数・まとめ関数の単体試験
# ---------------------------------------------------------------------------


def test_find_blender_python_returns_none_when_no_sibling_dir(tmp_path):
    blender_exe = tmp_path / "blender.exe"
    blender_exe.write_text("stub")
    assert warm_startup.find_blender_python(str(blender_exe)) is None


def test_find_blender_python_finds_bundled_interpreter(tmp_path):
    blender_exe = tmp_path / "blender.exe"
    blender_exe.write_text("stub")
    bpython_dir = tmp_path / "4.3" / "python" / "bin"
    bpython_dir.mkdir(parents=True)
    (bpython_dir / "python.exe").write_text("stub")
    result = warm_startup.find_blender_python(str(blender_exe))
    assert result == str(bpython_dir / "python.exe")


def test_warm_shared_cache_skips_with_reason_when_pak_missing(tmp_path):
    app_root = str(tmp_path)
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "blender.exe")
    Path(blender_exe).write_text("stub")
    bpython_dir = tmp_path / "4.3" / "python" / "bin"
    bpython_dir.mkdir(parents=True)
    (bpython_dir / "python.exe").write_text("stub")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("popen must not be called when pak is unresolved")

    warm_startup.warm_shared_cache_on_startup(
        app_root, work_root, blender_ready=True, blender_exe=blender_exe,
        pak_path=None, popen=_must_not_be_called,
    )
    log = _read(work_root, "warm_startup.log")
    assert "warm-cache: skip (pak not resolved: null)" in log


def test_warm_shared_cache_skips_with_reason_when_script_missing(tmp_path):
    app_root = str(tmp_path)
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "blender.exe")
    Path(blender_exe).write_text("stub")
    bpython_dir = tmp_path / "4.3" / "python" / "bin"
    bpython_dir.mkdir(parents=True)
    (bpython_dir / "python.exe").write_text("stub")
    pak_path = str(tmp_path / "Pal-Windows.pak")
    Path(pak_path).write_text("stub")
    # convert_noue.pyを意図的に置かない(app_root\pipeline\py\convert_noue.py不在)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("popen must not be called when convert_noue.py is missing")

    warm_startup.warm_shared_cache_on_startup(
        app_root, work_root, blender_ready=True, blender_exe=blender_exe,
        pak_path=pak_path, popen=_must_not_be_called,
    )
    log = _read(work_root, "warm_startup.log")
    assert "warm-cache: skip (convert_noue.py not found:" in log


def test_warm_startup_after_blender_ready_calls_both_when_not_pending(tmp_path):
    app_root = str(tmp_path)
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "blender.exe")
    Path(blender_exe).write_text("stub")

    popen, calls = _make_recording_popen(lambda: _FakeProc(returncode=0))

    warm_startup.warm_startup_after_blender_ready(
        app_root, work_root, blender_exe, pak_path=None,
        conversion_pending=False, popen=popen,
    )

    # warm_shared_cache_on_startupはbpython(Blender同梱python)が見つからず
    # skipするのでpopenは呼ばれず、warm_blender_process_on_startupだけが
    # 実際に起動する(this blender_exe has no sibling python dir, so the
    # bpython guard fires before the pak guard would -- either way it is a
    # silent skip, which is the behavior under test here).
    assert _wait_until(lambda: "exited code=" in _read(work_root, "warm_startup.log"))
    log = _read(work_root, "warm_startup.log")
    assert "warm-cache: skip" in log
    assert "blender-prewarm: started" in log
    assert len(calls) == 1


def test_warm_startup_after_blender_ready_skips_blender_prewarm_when_pending(tmp_path):
    # C#のpendingBlenderReadyAction!=nullの分岐(L.2086-2089)相当:
    # 直後に変換が始まる場合はBlender本体のプリウォームを撃たない。
    app_root = str(tmp_path)
    work_root = str(tmp_path / "work")
    blender_exe = str(tmp_path / "blender.exe")
    Path(blender_exe).write_text("stub")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("popen must not be called for blender-prewarm when pending")

    warm_startup.warm_startup_after_blender_ready(
        app_root, work_root, blender_exe, pak_path=None,
        conversion_pending=True, popen=_must_not_be_called,
    )

    log = _read(work_root, "warm_startup.log")
    assert "warm-cache: skip" in log
    assert "blender-prewarm" not in log
    assert not (Path(work_root) / "warm_blender.log").exists()


def test_warm_diag_log_appends_with_timestamp(tmp_path):
    work_root = str(tmp_path / "work")
    warm_startup.warm_diag_log(work_root, "hello")
    warm_startup.warm_diag_log(work_root, "world")
    lines = _read(work_root, "warm_startup.log").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("hello")
    assert lines[1].endswith("world")
