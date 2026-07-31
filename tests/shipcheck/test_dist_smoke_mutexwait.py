# -*- coding: utf-8 -*-
r"""dev#288(work\speed_mission\mutexwait\NOTES.md)の単体試験。

対象: tests\shipcheck\dist_smoke.py に追加した
  - run_convert()への-MutexWaitMs横展開(convert.ps1呼び出しコマンドライン、
    devtools\relgate.py::run_convert()と同じパターンの横展開)
  - 外側リトライの意味論(ミューテックス競合時のみリトライ、それ以外は
    従来どおり即return。既定値だけ20回x45秒→5回x5秒へ変更)
  - parse_convert_phase_times_sec(): convert.ps1のPhase別タイミング出力の
    正規表現パース(判定ロジックには一切使わない観測専用フィールド)

実convert.ps1・実subst・実Blenderは一切呼ばない(subprocess.run/time.sleepを
monkeypatchする純粋な単体試験)。pipeline\配下のコードは読むだけで変更していない。

実行: python -m pytest tests\shipcheck\test_dist_smoke_mutexwait.py -v
"""
import importlib.util
import os
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(REPO, "tests", "shipcheck", "dist_smoke.py")

spec = importlib.util.spec_from_file_location("dist_smoke_mutexwait_test", MODULE_PATH)
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)


class _FakeCompleted:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _assert_mutex_wait_ms_present(cmd, expected_value):
    """機械検査: convert.ps1呼び出しコマンドラインに-MutexWaitMsが含まれ、
    値が期待どおりであることを確認する。"""
    assert "-MutexWaitMs" in cmd, "cmd に -MutexWaitMs が含まれていない: %r" % (cmd,)
    idx = cmd.index("-MutexWaitMs")
    assert cmd[idx + 1] == str(expected_value), "MutexWaitMsの値が期待と異なる: %r" % (cmd,)


# --- 実ログからの抜粋フィクスチャ(run_20260730_011737、絶対パスは
# work\speed_mission\mutexwait\NOTES.md「読んだ一次資料」参照)。
# 実測どおり[Phase 1] OK行はこの2ログには存在しない(パーサはこの前提で
# Noneを返すfail-safe設計になっている、下記テストで確認する)。 ---
DIST_SMOKE_LOG_EXCERPT = (
    "=== Phase 0: preparing reference vanilla data ===\n"
    "...\n"
    "[Phase 0] OK (3.3s)\n"
    "=== Phase 1: Blender pipeline ===\n"
    "...\n"
    "[pipeline] Mutex released after Phase 1\n"
    "=== Phase 2-6(noue): build_pak_from_avatar.py end-to-end build ===\n"
    "...\n"
    "[noue build] OK (124.4s)\n"
    "Total elapsed time: 139.5s\n"
)

HOST_REF_LOG_EXCERPT = (
    "[Phase 0] OK (4.4s)\n"
    "[pipeline] Mutex released after Phase 1\n"
    "[noue build] OK (75.1s)\n"
    "Total elapsed time: 92.8s\n"
)

# 現行master(pipeline\cli\convert.ps1 L946)は[Phase 1] OK行を出すが、
# サンプル実ログの記録時点ではまだ存在しなかった。この行が出るケースも
# 合成テキストで確認しておく。
SYNTHETIC_LOG_WITH_PHASE1 = (
    "[Phase 0] OK (2.0s)\n"
    "[Phase 1] OK (12.3s)\n"
    "[noue build] OK (50.0s)\n"
    "Total elapsed time: 65.0s\n"
)


class TestDefaults:
    def test_default_mutex_wait_ms_matches_relgate(self):
        # devtools\relgate.py::DEFAULT_MUTEX_WAIT_MS(180000)と値を揃える設計
        assert ds.DEFAULT_MUTEX_WAIT_MS == 180000

    def test_default_retry_is_insurance_sized_not_old_polling(self):
        # 旧既定(20回x45秒の固定ポーリング)からrelgate.py同等の
        # 保険値(5回x5秒)へ変更(-MutexWaitMsが主経路になったため)
        assert ds.DEFAULT_MAX_RETRIES == 5
        assert ds.DEFAULT_RETRY_WAIT_SEC == 5


class TestRunConvertMutexWaitMs:
    def test_cmd_includes_mutex_wait_ms(self, tmp_path, monkeypatch):
        captured = []

        def _run(cmd, **kwargs):
            captured.append(cmd)
            return _FakeCompleted(0, "[Phase 0] OK (1.0s)\nTotal elapsed time: 2.0s\n")

        monkeypatch.setattr(ds.subprocess, "run", _run)
        log_path = str(tmp_path / "log.txt")

        success, out, attempts = ds.run_convert("convert.ps1", "job.json", {}, log_path)

        assert success is True
        assert attempts == 1
        assert len(captured) == 1
        _assert_mutex_wait_ms_present(captured[0], ds.DEFAULT_MUTEX_WAIT_MS)

    def test_custom_mutex_wait_ms_is_forwarded(self, tmp_path, monkeypatch):
        captured = []

        def _run(cmd, **kwargs):
            captured.append(cmd)
            return _FakeCompleted(0, "Total elapsed time: 1.0s\n")

        monkeypatch.setattr(ds.subprocess, "run", _run)
        log_path = str(tmp_path / "log.txt")

        ds.run_convert("convert.ps1", "job.json", {}, log_path, mutex_wait_ms=99999)

        _assert_mutex_wait_ms_present(captured[0], 99999)

    def test_negative_control_assertion_detects_missing_mutex_wait_ms(self):
        """検査自体の健全性: -MutexWaitMsを含まないコマンドラインを渡すと、
        機械検査(_assert_mutex_wait_ms_present)は確実にFAIL(AssertionError)する。
        (「-MutexWaitMs付与コードを外すと検査がFAILすること」の確認)"""
        cmd_without = ["powershell.exe", "-NoProfile", "-File", "convert.ps1",
                       "-Job", "job.json", "-EngineMode", "noue"]
        with pytest.raises(AssertionError):
            _assert_mutex_wait_ms_present(cmd_without, 180000)


class TestRunConvertRetrySemantics:
    def test_mutex_busy_retries_then_succeeds(self, tmp_path, monkeypatch):
        sleeps = []
        monkeypatch.setattr(ds.time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _run(cmd, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                return _FakeCompleted(1, "...\n[D2P_MUTEX_BUSY]\n")
            return _FakeCompleted(0, "Total elapsed time: 5.0s\n")

        monkeypatch.setattr(ds.subprocess, "run", _run)
        log_path = str(tmp_path / "log.txt")

        success, out, attempts = ds.run_convert("convert.ps1", "job.json", {}, log_path)

        assert success is True
        assert attempts == 3
        assert len(sleeps) == 2
        assert all(s == ds.DEFAULT_RETRY_WAIT_SEC for s in sleeps)

    def test_non_mutex_failure_does_not_retry(self, tmp_path, monkeypatch):
        """負の対照: マーカー無しの失敗はリトライしない(このWPで既存の
        リトライ意味論を変えていないことの確認。元々このコードパスに
        リトライは無かった)。"""
        sleeps = []
        monkeypatch.setattr(ds.time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _run(cmd, **kwargs):
            calls["n"] += 1
            return _FakeCompleted(1, "fatal error, unrelated to mutex\n")

        monkeypatch.setattr(ds.subprocess, "run", _run)
        log_path = str(tmp_path / "log.txt")

        success, out, attempts = ds.run_convert("convert.ps1", "job.json", {}, log_path)

        assert success is False
        assert attempts == 1  # リトライしていない
        assert sleeps == []
        assert calls["n"] == 1

    def test_retry_gives_up_after_max_retries_all_busy(self, tmp_path, monkeypatch):
        sleeps = []
        monkeypatch.setattr(ds.time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _run(cmd, **kwargs):
            calls["n"] += 1
            return _FakeCompleted(1, "[D2P_MUTEX_BUSY]\n")

        monkeypatch.setattr(ds.subprocess, "run", _run)
        log_path = str(tmp_path / "log.txt")

        success, out, attempts = ds.run_convert("convert.ps1", "job.json", {}, log_path)

        assert success is False
        assert calls["n"] == ds.DEFAULT_MAX_RETRIES
        assert len(sleeps) == ds.DEFAULT_MAX_RETRIES - 1


class TestParseConvertPhaseTimesSec:
    def test_parses_real_dist_smoke_log_excerpt(self):
        result = ds.parse_convert_phase_times_sec(DIST_SMOKE_LOG_EXCERPT)
        assert result["phase0_vanilla_sec"] == 3.3
        assert result["noue_build_sec"] == 124.4
        assert result["total_elapsed_sec"] == 139.5
        # 実ログ確認済み: このrunの時点ではconvert.ps1に[Phase 1] OK行が無かった
        assert result["phase1_blender_sec"] is None

    def test_parses_real_host_ref_log_excerpt(self):
        result = ds.parse_convert_phase_times_sec(HOST_REF_LOG_EXCERPT)
        assert result["phase0_vanilla_sec"] == 4.4
        assert result["noue_build_sec"] == 75.1
        assert result["total_elapsed_sec"] == 92.8

    def test_parses_phase1_when_present(self):
        result = ds.parse_convert_phase_times_sec(SYNTHETIC_LOG_WITH_PHASE1)
        assert result["phase1_blender_sec"] == 12.3

    def test_negative_control_unparseable_text_yields_all_none_no_exception(self):
        """負の対照: パース不能な出力を与えても例外を投げず、全フィールドが
        Noneになるだけ(合否判定には一切使わない=fail-openにしない)。"""
        result = ds.parse_convert_phase_times_sec("completely unrelated garbage\n???\n")
        assert all(v is None for v in result.values())

    def test_negative_control_empty_text_yields_all_none(self):
        result = ds.parse_convert_phase_times_sec("")
        assert all(v is None for v in result.values())

    def test_all_expected_keys_present(self):
        result = ds.parse_convert_phase_times_sec("")
        assert set(result.keys()) == {
            "phase0_vanilla_sec", "phase1_blender_sec",
            "noue_build_sec", "total_elapsed_sec",
        }


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
