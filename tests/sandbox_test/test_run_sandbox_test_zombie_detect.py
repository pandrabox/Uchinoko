# -*- coding: utf-8 -*-
r"""dev#224(work\night_20260729\wsb_recon.md 2.1/2.2節の実測)の単体試験。

対象: devtools\sandbox_test\run_sandbox_test.py に追加した
  - start_sandbox() の戻り値変更: (id, used_fallback) タプル化
    (フォールバック(.wsb関連付け起動)を使ったかどうかを呼び出し側へ伝える)
  - is_fallback_zombie(): フォールバック起動でrunner_started.txtが閾値秒
    以内に出現しないケースを「ゾンビ状態」と判定する純関数
  - build_fallback_zombie_evidence(): ゾンビ検知時の診断情報辞書を組み立てる純関数
  - main()内ポーリングループへの上記の配線(inspect.getsourceによる静的確認。
    main()自体はWindows Sandbox起動を要するため実行はしない)

実Sandbox・実Blender・実Palworldは一切起動しない(CLAUDE.md制約: WSBを起動しない)。
subprocess.run/os.startfileはmonkeypatchで完全に差し替える。

実行: python -m pytest tests\sandbox_test\test_run_sandbox_test_zombie_detect.py -v
"""
import importlib.util
import inspect
import os
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(REPO, "devtools", "sandbox_test", "run_sandbox_test.py")

spec = importlib.util.spec_from_file_location("run_sandbox_test_zombie_detect_test", MODULE_PATH)
rst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rst)


class _FakeCompletedFail:
    """wsb start が常に失敗するcompleted process代役。"""

    def __init__(self, returncode=1, stderr="boom"):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


class _FakeCompletedOk:
    """wsb start が成功するcompleted process代役(idを返す)。"""

    def __init__(self, sid):
        self.returncode = 0
        self.stdout = '{"Id": "%s"}' % sid
        self.stderr = ""


class TestIsFallbackZombie:
    """is_fallback_zombie(): ゾンビ判定の核となる純関数。"""

    def test_true_when_fallback_and_not_started_and_over_threshold(self):
        assert rst.is_fallback_zombie(True, False, 91, threshold_sec=90) is True

    def test_false_at_exact_threshold_boundary(self):
        """閾値ちょうど(91秒目に入る直前)は誤検知しない(>であって>=でない)。"""
        assert rst.is_fallback_zombie(True, False, 90, threshold_sec=90) is False

    def test_negative_control_normal_cli_path_never_flags_even_if_slow(self):
        """負の対照①: wsb CLI正常系(used_fallback=False)は、どれだけ待っても
        (=fallback検知の役割ではないので)このチェックはFalseのまま。
        既存のheartbeat監視(HEARTBEAT_STALE_SEC)が別途カバーする役割分担。"""
        assert rst.is_fallback_zombie(False, False, 999999, threshold_sec=90) is False

    def test_negative_control_started_seen_suppresses_detection(self):
        """負の対照②: フォールバック経路でもrunner起動さえ確認できていれば
        (=LogonCommandは発火した)、どれだけ経過してもゾンビ扱いしない。"""
        assert rst.is_fallback_zombie(True, True, 999999, threshold_sec=90) is False

    def test_uses_module_default_threshold_when_unspecified(self):
        # 閾値省略時はモジュール定数FALLBACK_STARTED_TIMEOUT_SEC(90)を使う
        assert rst.is_fallback_zombie(True, False, rst.FALLBACK_STARTED_TIMEOUT_SEC + 0.1) is True
        assert rst.is_fallback_zombie(True, False, rst.FALLBACK_STARTED_TIMEOUT_SEC - 0.1) is False

    def test_default_threshold_is_far_below_full_900s_timeout(self):
        """短縮効果の機械検査: 新閾値は既定タイムアウト900秒よりはるかに小さい
        (=正常系に対する実測オーバーヘッド11.2秒(wsb_recon.md)へ余裕を持たせた
        値であり、900秒フルを待たない設計になっていることの確認)。"""
        assert rst.FALLBACK_STARTED_TIMEOUT_SEC < 900
        assert rst.FALLBACK_STARTED_TIMEOUT_SEC <= 120  # 提案レンジ(60〜90秒)に収まる


class TestBuildFallbackZombieEvidence:
    def test_evidence_dict_shape(self):
        evidence = rst.build_fallback_zombie_evidence(95.44, 90, timestamp="2026-07-30T00:00:00")
        assert evidence["used_fallback"] is True
        assert evidence["started_seen"] is False
        assert evidence["threshold_sec"] == 90
        assert evidence["elapsed_since_start_sec"] == 95.4  # round(...,1)
        assert evidence["detected_at"] == "2026-07-30T00:00:00"
        assert "90秒" in evidence["note"]
        assert "runner_started.txt" in evidence["note"]

    def test_timestamp_defaults_to_now_when_unspecified(self):
        evidence = rst.build_fallback_zombie_evidence(10.0, 90)
        assert evidence["detected_at"]  # 何らかの非空文字列が入る


class TestStartSandboxUsedFallbackFlag:
    """start_sandbox()の戻り値タプル化: usedFallbackフラグが両経路で正しいか。"""

    def test_wsb_cli_success_returns_false_fallback_flag(self, tmp_path, monkeypatch):
        wsb_path = tmp_path / "run.wsb"
        wsb_path.write_text("<Configuration></Configuration>", encoding="utf-8")

        def _run(cmd, capture_output=True, text=True, timeout=120):
            assert cmd[:2] == ["wsb", "start"]
            return _FakeCompletedOk("fake-sid-123")

        popen_calls = []
        monkeypatch.setattr(rst.subprocess, "run", _run)
        monkeypatch.setattr(rst.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))
        startfile_calls = []
        monkeypatch.setattr(rst.os, "startfile", lambda p: startfile_calls.append(p))

        sid, used_fallback = rst.start_sandbox(str(wsb_path))

        assert sid == "fake-sid-123"
        assert used_fallback is False
        assert len(popen_calls) == 1  # wsb connectが起動された
        assert startfile_calls == []  # フォールバックは使っていない

    def test_wsb_cli_failure_falls_back_and_returns_true_fallback_flag(self, tmp_path, monkeypatch):
        """負の対照(dev#224の実測再現): 2回とも失敗するとフォールバックへ落ち、
        used_fallback=True・sid=Noneになる(実測でこの経路がゾンビ化したケース)。"""
        wsb_path = tmp_path / "run.wsb"
        wsb_path.write_text("<Configuration></Configuration>", encoding="utf-8")

        calls = {"n": 0}

        def _run(cmd, capture_output=True, text=True, timeout=120):
            calls["n"] += 1
            return _FakeCompletedFail(returncode=2147746294, stderr="CO_E_APPSINGLEUSE")

        monkeypatch.setattr(rst.subprocess, "run", _run)
        startfile_calls = []
        monkeypatch.setattr(rst.os, "startfile", lambda p: startfile_calls.append(p))

        sid, used_fallback = rst.start_sandbox(str(wsb_path))

        assert sid is None
        assert used_fallback is True
        assert calls["n"] == 2  # xml/wsb_path両方の config_arg で試行した
        assert startfile_calls == [str(wsb_path)]

    def test_wsb_cli_not_found_falls_back_and_returns_true_fallback_flag(self, tmp_path, monkeypatch):
        """負の対照: wsb CLI自体が存在しない環境でも同じフォールバック経路へ落ちる。"""
        wsb_path = tmp_path / "run.wsb"
        wsb_path.write_text("<Configuration></Configuration>", encoding="utf-8")

        def _run(cmd, capture_output=True, text=True, timeout=120):
            raise FileNotFoundError("wsb command not found")

        monkeypatch.setattr(rst.subprocess, "run", _run)
        startfile_calls = []
        monkeypatch.setattr(rst.os, "startfile", lambda p: startfile_calls.append(p))

        sid, used_fallback = rst.start_sandbox(str(wsb_path))

        assert sid is None
        assert used_fallback is True
        assert startfile_calls == [str(wsb_path)]


class TestMainWiring:
    """main()全体はWindows Sandbox起動を要するため単体試験の対象外
    (既存test_run_sandbox_test_host_ref_mutexwait.pyの
    TestHashCheckExposesPhaseTimesと同じ方針)。代わりにinspect.getsourceで
    ゾンビ検知が実際にmain()のポーリングループへ配線されていることを
    静的に確認する(=is_fallback_zombie()/build_fallback_zombie_evidence()を
    定義しただけで呼び出し配線を外すと、この試験が赤くなる)。"""

    def test_main_unpacks_used_fallback_from_start_sandbox(self):
        src = inspect.getsource(rst.main)
        assert "sandbox_id, used_fallback = start_sandbox(wsb_path)" in src, (
            "main()がstart_sandbox()の戻り値からused_fallbackを受け取っていない"
            "(start_sandbox()のタプル化に伴う配線漏れ)")

    def test_main_calls_is_fallback_zombie_inside_poll_loop(self):
        src = inspect.getsource(rst.main)
        assert "is_fallback_zombie(used_fallback, started_seen, time.time() - t0)" in src, (
            "main()のポーリングループがis_fallback_zombie()を呼んでいない"
            "(検知ロジックが定義されているだけで配線されていない状態)")

    def test_main_writes_zombie_report_and_fails_fast_on_detection(self):
        src = inspect.getsource(rst.main)
        assert "zombie_report.json" in src, "ゾンビ検知時の診断情報が結果ディレクトリへ保存されていない"
        assert "if zombie_detected:" in src, "zombie_detectedフラグによる早期FAIL分岐が無い"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
