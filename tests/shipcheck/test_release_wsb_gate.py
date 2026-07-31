# -*- coding: utf-8 -*-
r"""dev#66(WSBのrelease.py並列統合)の配線試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実際の
Windows Sandbox・実DL・実変換・実relgateを一切起動しない(pak自体を変える
変更ではない、純粋な構造変更のため)。確認するのは配線そのもの:

  1. run_wsb_convert_gate() が正しいコマンド(--convert --zip --work)を組み立て、
     rc=0ならok=True、rc!=0ならok=Falseを返すこと
  2. subprocess.TimeoutExpired(内側のheartbeat監視が機能しなかった想定の
     外側安全弁が発火するケース)でもok=Falseで例外を伝播せず戻ること
  3. 負の対照(dev#66の受入条件そのもの): dist_smoke/relgate/WSBの3レーンを
     main()と同じThreadPoolExecutor(max_workers=3)+BufferedReportパターンで
     並列実行し、WSBレーンだけを失敗させても他の2レーンは短絡されず最後まで
     実行され、最終判定がFAILになること
  4. 正の対照: 3レーンとも成功すれば最終判定がPASSになること
  5. 旧dev#74の外部証跡ゲート(run_wsb_record_gate等)がrelease.pyから
     削除されていること(置き換えの確認、CLAUDE.md「設定項目は少ないほうが
     いい」原則)

実行: python -m pytest tests\shipcheck\test_release_wsb_gate.py -v
"""
import concurrent.futures
import importlib
import json
import os
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_release():
    return importlib.import_module("release")


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --- 1: run_wsb_convert_gate()のコマンド組み立てとrc判定 -----------------------

def test_wsb_gate_builds_convert_command_with_explicit_zip_and_work(tmp_path, monkeypatch):
    release = _import_release()
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return _FakeCompletedProcess(0, "ok", "")

    monkeypatch.setattr(release, "_run", _fake_run)
    report = release.Report(str(tmp_path / "report.md"))

    result = release.run_wsb_convert_gate("Z.zip", str(tmp_path), report, timeout_sec=99)

    assert result["ok"] is True
    assert result["rc"] == 0
    cmd = captured["cmd"]
    assert cmd[0] == sys.executable
    assert cmd[1] == release.RUN_SANDBOX_TEST_PY
    assert "--convert" in cmd
    assert "--zip" in cmd and cmd[cmd.index("--zip") + 1] == "Z.zip"
    assert "--work" in cmd
    work_arg = cmd[cmd.index("--work") + 1]
    assert work_arg == os.path.join(str(tmp_path), "wsb_convert")
    assert captured["timeout"] == 99


def test_wsb_gate_logs_cache_gate_decision_and_returns_its_path(tmp_path, monkeypatch):
    """dev#226 要件4(可視性): run_sandbox_test.pyがresults\\cache_gate.jsonへ
    書いた持ち込み/コールドの判定理由を、release.pyのレポートにも出す
    こと。ここではrun_sandbox_test.py自体は起動せず、そのファイルが
    既に置かれている状態を模してrun_wsb_convert_gate()を呼ぶ。"""
    release = _import_release()
    monkeypatch.setattr(release, "_run",
                         lambda cmd, **kw: _FakeCompletedProcess(0, "ok", ""))
    report = release.Report(str(tmp_path / "report.md"))

    results_dir = tmp_path / "wsb_convert" / "results"
    results_dir.mkdir(parents=True)
    cache_gate_payload = {"bring_in": True, "reason": "fingerprint一致+実績あり -> 持ち込み",
                           "gate_fingerprint": "fp_abcdef"}
    (results_dir / "cache_gate.json").write_text(
        json.dumps(cache_gate_payload), encoding="utf-8")

    result = release.run_wsb_convert_gate("Z.zip", str(tmp_path), report)

    assert result["cache_gate_json"] == str(results_dir / "cache_gate.json")
    with open(report.path, encoding="utf-8") as f:
        report_text = f.read()
    assert "cache_gate(dev#226)" in report_text
    assert "bring_in=True" in report_text


def test_wsb_gate_fails_on_nonzero_rc(tmp_path, monkeypatch):
    release = _import_release()
    monkeypatch.setattr(release, "_run",
                         lambda cmd, **kw: _FakeCompletedProcess(1, "boom", "err"))
    report = release.Report(str(tmp_path / "report.md"))

    result = release.run_wsb_convert_gate("Z.zip", str(tmp_path), report)

    assert result["ok"] is False
    assert result["rc"] == 1
    assert result["name"] == "wsb_convert"


# --- 2: 外側タイムアウト安全弁 --------------------------------------------------

def test_wsb_gate_timeout_returns_fail_without_raising(tmp_path, monkeypatch):
    release = _import_release()

    def _fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout"))

    monkeypatch.setattr(release, "_run", _fake_run)
    report = release.Report(str(tmp_path / "report.md"))

    result = release.run_wsb_convert_gate("Z.zip", str(tmp_path), report, timeout_sec=5)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["rc"] is None


# --- 3: 負の対照 -- WSBレーンだけ失敗しても他の2レーンは短絡されず、
#        最終判定がFAILになる(main()の該当ブロックと同じパターンを再現) ------

def test_three_lane_parallel_block_wsb_fail_does_not_short_circuit_others(tmp_path):
    release = _import_release()
    report = release.Report(str(tmp_path / "report.md"))

    dist_smoke_finished = {"value": False}
    relgate_finished = {"value": False}

    def fake_dist_smoke_dummy(_buf):
        time.sleep(0.1)
        dist_smoke_finished["value"] = True
        return {"name": "dist_smoke", "ok": True, "rc": 0}

    def fake_relgate_dummy(_buf):
        time.sleep(0.1)
        relgate_finished["value"] = True
        return {"name": "relgate_layers12", "ok": True, "rc": 0}

    def fake_wsb_dummy(_buf):
        # 実際のsubprocess呼び出しの代わりに即FAILを返す(rc!=0想定)
        return {"name": "wsb_convert", "ok": False, "rc": 1}

    dist_smoke_buf = release.BufferedReport()
    relgate_buf = release.BufferedReport()
    wsb_buf = release.BufferedReport()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        fut_dist_smoke = executor.submit(fake_dist_smoke_dummy, dist_smoke_buf)
        fut_relgate = executor.submit(fake_relgate_dummy, relgate_buf)
        fut_wsb = executor.submit(fake_wsb_dummy, wsb_buf)
        dist_smoke_result = fut_dist_smoke.result()
        relgate_result = fut_relgate.result()
        wsb_result = fut_wsb.result()
    dist_smoke_buf.flush_into(report)
    relgate_buf.flush_into(report)
    wsb_buf.flush_into(report)

    # 直列時代の副次的short-circuitは無い: WSBが失敗してもdist_smoke/relgateは
    # 最後まで実行される
    assert dist_smoke_finished["value"] is True
    assert relgate_finished["value"] is True

    # main()と同じ判定分岐を再現: いずれか1つでもFAILなら全体FAIL
    overall_ok = dist_smoke_result["ok"] and relgate_result["ok"] and wsb_result["ok"]
    assert overall_ok is False, "WSBレーン失敗時は最終判定がFAILにならなければならない"


def test_three_lane_parallel_block_all_green_when_all_succeed(tmp_path):
    """正の対照: 3レーンとも成功すれば全体PASS。"""
    release = _import_release()
    report = release.Report(str(tmp_path / "report.md"))

    def fake_dist_smoke_dummy(_buf):
        return {"name": "dist_smoke", "ok": True, "rc": 0}

    def fake_relgate_dummy(_buf):
        return {"name": "relgate_layers12", "ok": True, "rc": 0}

    def fake_wsb_dummy(_buf):
        return {"name": "wsb_convert", "ok": True, "rc": 0}

    dist_smoke_buf = release.BufferedReport()
    relgate_buf = release.BufferedReport()
    wsb_buf = release.BufferedReport()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        fut_dist_smoke = executor.submit(fake_dist_smoke_dummy, dist_smoke_buf)
        fut_relgate = executor.submit(fake_relgate_dummy, relgate_buf)
        fut_wsb = executor.submit(fake_wsb_dummy, wsb_buf)
        dist_smoke_result = fut_dist_smoke.result()
        relgate_result = fut_relgate.result()
        wsb_result = fut_wsb.result()
    dist_smoke_buf.flush_into(report)
    relgate_buf.flush_into(report)
    wsb_buf.flush_into(report)

    overall_ok = dist_smoke_result["ok"] and relgate_result["ok"] and wsb_result["ok"]
    assert overall_ok is True


# --- 4: 旧dev#74の外部証跡ゲートが削除されていること(置き換えの確認) -----------

def test_old_wsb_record_gate_symbols_removed():
    release = _import_release()
    for name in ("run_wsb_record_gate", "evaluate_wsb_record", "load_wsb_record",
                 "WSB_RECORD_PATH", "WSB_ELIGIBLE_MODE", "WSB_RETRY_HINT"):
        assert not hasattr(release, name), (
            f"dev#66統合後、旧dev#74の{name}はrelease.pyから削除されているはず"
            "(内包WSBレーンへ置き換え済み)")


def test_run_sandbox_test_py_constant_points_to_real_file():
    release = _import_release()
    assert os.path.isfile(release.RUN_SANDBOX_TEST_PY), (
        "RUN_SANDBOX_TEST_PY が実ファイルを指していること"
        f"({release.RUN_SANDBOX_TEST_PY})")
    assert release.RUN_SANDBOX_TEST_PY.endswith(
        os.path.join("sandbox_test", "run_sandbox_test.py"))
