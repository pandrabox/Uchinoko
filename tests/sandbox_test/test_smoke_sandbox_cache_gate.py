# -*- coding: utf-8 -*-
r"""dev#226(2026-07-30)の単体試験: devtools\sandbox_test\smoke_sandbox.py
の`probe_cache_gate()`(WSB内、convert.ps1呼び出し直前の二段目ゲート)。

このゲートは「ホスト側cache_gate.pyがEXTRA_MAPPEDへ共有キャッシュを
持ち込むと判定した場合でも、WSB内で実際に計算したfingerprintと一致する
保証がない限りconvert.ps1へD2P_SHARED_CACHEを渡してはいけない」という
安全弁である(一致しないままread-onlyマウントへ書き込みを試みると
`build_live_template()`のロック取得が失敗して変換自体がFAILする恐れが
あるため)。ここではWindows Sandbox・実convert.ps1は一切起動せず、
`subprocess.run`をモックして判定ロジックだけを検証する。

実行: python -m pytest tests\sandbox_test\test_smoke_sandbox_cache_gate.py -v
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(REPO, "devtools", "sandbox_test", "smoke_sandbox.py")

spec = importlib.util.spec_from_file_location("smoke_sandbox_cache_gate_test", MODULE_PATH)
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _probe_json_line(vanilla_fresh, live_template_fresh):
    payload = {"vanilla_full_fresh": vanilla_fresh, "vanilla_fingerprint": {},
               "vanilla_dir": "C:\\d2p_shared_cache\\vanilla\\abc",
               "live_template_fresh": live_template_fresh,
               "live_template_fingerprint": {}, "live_template_dir": "C:\\d2p_shared_cache\\live_template\\def"}
    return "D2P_PROBE_CACHE_JSON:" + json.dumps(payload)


def test_no_mount_dir_skips_probe_entirely(tmp_path, monkeypatch):
    """マウントが無い(=ホスト側ゲートがコールドと判定した)場合、
    subprocessを一切呼ばずattempted=Falseで即返す。"""
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(tmp_path / "does_not_exist"))
    called = {"run": False}
    monkeypatch.setattr(ss.subprocess, "run",
                         lambda *a, **kw: called.__setitem__("run", True) or _FakeCompletedProcess())

    result = ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert result["attempted"] is False
    assert result["brought_in"] is False
    assert called["run"] is False


def test_mount_present_and_both_fresh_brings_in(tmp_path, monkeypatch):
    """負の対照①相当: マウントがあり両方freshならbrought_in=True。"""
    mount = tmp_path / "d2p_shared_cache"
    mount.mkdir()
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(mount))
    monkeypatch.setattr(ss.subprocess, "run",
                         lambda *a, **kw: _FakeCompletedProcess(0, _probe_json_line(True, True)))

    result = ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert result["attempted"] is True
    assert result["brought_in"] is True
    assert result["probe"]["vanilla_full_fresh"] is True


@pytest.mark.parametrize("vanilla_fresh,lt_fresh", [(False, True), (True, False), (False, False)])
def test_mount_present_but_not_both_fresh_stays_cold(tmp_path, monkeypatch, vanilla_fresh, lt_fresh):
    """dev#226の要 -- fingerprint不一致(=WSB内で計算した実際の値と違う)なら
    read-onlyマウントへの書き込み事故を避けるため、必ずコールドへ倒す。"""
    mount = tmp_path / "d2p_shared_cache"
    mount.mkdir()
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(mount))
    monkeypatch.setattr(
        ss.subprocess, "run",
        lambda *a, **kw: _FakeCompletedProcess(0, _probe_json_line(vanilla_fresh, lt_fresh)))

    result = ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert result["attempted"] is True
    assert result["brought_in"] is False


def test_probe_cache_nonzero_exit_falls_back_to_cold(tmp_path, monkeypatch):
    mount = tmp_path / "d2p_shared_cache"
    mount.mkdir()
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(mount))
    monkeypatch.setattr(ss.subprocess, "run",
                         lambda *a, **kw: _FakeCompletedProcess(1, "traceback boom", "err"))

    result = ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert result["brought_in"] is False


def test_probe_cache_missing_json_marker_falls_back_to_cold(tmp_path, monkeypatch):
    mount = tmp_path / "d2p_shared_cache"
    mount.mkdir()
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(mount))
    monkeypatch.setattr(ss.subprocess, "run",
                         lambda *a, **kw: _FakeCompletedProcess(0, "some other output\nno marker here"))

    result = ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert result["brought_in"] is False


def test_probe_cache_malformed_json_falls_back_to_cold(tmp_path, monkeypatch):
    mount = tmp_path / "d2p_shared_cache"
    mount.mkdir()
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(mount))
    monkeypatch.setattr(ss.subprocess, "run",
                         lambda *a, **kw: _FakeCompletedProcess(0, "D2P_PROBE_CACHE_JSON:{not valid json"))

    result = ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert result["brought_in"] is False


def test_probe_cache_timeout_falls_back_to_cold(tmp_path, monkeypatch):
    mount = tmp_path / "d2p_shared_cache"
    mount.mkdir()
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(mount))

    def _raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="probe", timeout=60)
    monkeypatch.setattr(ss.subprocess, "run", _raise_timeout)

    result = ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert result["attempted"] is True
    assert result["brought_in"] is False


def test_probe_cache_sets_d2p_shared_cache_env_for_probe_subprocess(tmp_path, monkeypatch):
    """probe自体の呼び出しにも(結果を左右する)D2P_SHARED_CACHEをマウント先へ
    明示設定していること(でなければ何を確認しているのか分からなくなる)。"""
    mount = tmp_path / "d2p_shared_cache"
    mount.mkdir()
    monkeypatch.setattr(ss, "SANDBOX_SHARED_CACHE", str(mount))
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return _FakeCompletedProcess(0, _probe_json_line(True, True))
    monkeypatch.setattr(ss.subprocess, "run", _fake_run)

    ss.probe_cache_gate("C:\\app_root", "C:\\work_dir", "C:\\pak")

    assert captured["env"] is not None
    assert captured["env"].get("D2P_SHARED_CACHE") == str(mount)
    assert "--probe-cache" in captured["cmd"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
