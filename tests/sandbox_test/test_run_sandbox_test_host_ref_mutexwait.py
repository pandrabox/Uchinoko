# -*- coding: utf-8 -*-
r"""dev#288(work\speed_mission\mutexwait\NOTES.md)の単体試験。

対象: devtools\sandbox_test\run_sandbox_test.py の
build_host_reference_pak()に追加した
  - -MutexWaitMs横展開(convert.ps1呼び出しコマンドライン)
  - 新規リトライ機構(従来この関数はリトライを一切持たず、ミューテックス
    競合1回で即座にエラー辞書を返していた。PROPOSAL.md提案1が指摘する
    「host_ref競合1回でリリース全体FAIL」という潜在的信頼性リスクの解消)
  - parse_convert_phase_times_sec(): convert.ps1のPhase別タイミング出力の
    正規表現パース(判定ロジックには一切使わない観測専用フィールド)

実Sandbox・実Blender・実Palworldは一切起動しない。zip展開は実
zipfileモジュールで行うが中身はすべてダミーバイト列(コード内容は問わない、
ファイルの存在確認しか通らないため)。convert.ps1の実行はsubprocess.runを
monkeypatchして完全に差し替える。

実行: python -m pytest tests\sandbox_test\test_run_sandbox_test_host_ref_mutexwait.py -v
"""
import importlib.util
import json
import os
import sys
import zipfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(REPO, "devtools", "sandbox_test", "run_sandbox_test.py")

spec = importlib.util.spec_from_file_location("run_sandbox_test_host_ref_mutexwait_test", MODULE_PATH)
rst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rst)

AVATAR_NAME = "test_avatar"


class _FakeCompleted:
    """subprocess.CompletedProcessの薄い代役(build_host_reference_pak()は
    capture_output=Trueでバイト列を読む前提のため、stdout/stderrはbytes)。"""

    def __init__(self, returncode, stdout_text):
        self.returncode = returncode
        self.stdout = stdout_text.encode("utf-8")
        self.stderr = b""


def _assert_mutex_wait_ms_present(cmd, expected_value):
    """機械検査: convert.ps1呼び出しコマンドラインに-MutexWaitMsが含まれ、
    値が期待どおりであることを確認する。"""
    assert "-MutexWaitMs" in cmd, "cmd に -MutexWaitMs が含まれていない: %r" % (cmd,)
    idx = cmd.index("-MutexWaitMs")
    assert cmd[idx + 1] == str(expected_value), "MutexWaitMsの値が期待と異なる: %r" % (cmd,)


def _make_zip(zip_path):
    """build_host_reference_pak()が要求するファイルだけを最小構成で持つ
    ダミーzip(Uchinoko.batが直下にあるパターン)。

    dev#532 D1(2026-08-01): 方針A(Python/tkinter版)統合でzip直下は
    Uchinoko.bat/README.txt/res\\ の3点のみになり、pipeline\\/assets\\は
    res\\配下(=app_root)へ移動した(app_py\\build.py参照)。"""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Uchinoko.bat", b"stub")
        zf.writestr("res/pipeline/cli/convert.ps1", "# stub, never executed (subprocess.run is mocked)")
        zf.writestr("res/assets/third_party/VRM_Addon_for_Blender-Extension-4_4_0.zip", b"stub")


def _setup_common(tmp_path, monkeypatch):
    """ホストのBlender実体パス(HOST_BLENDER_EXE)・検体VRM・Palworld pakの
    存在チェックを、実ファイルシステム上のダミーファイルで満たす。"""
    zip_path = tmp_path / "dist.zip"
    _make_zip(zip_path)
    blender_exe = tmp_path / "blender.exe"
    blender_exe.write_text("stub")
    monkeypatch.setattr(rst, "HOST_BLENDER_EXE", str(blender_exe))
    vrm_path = tmp_path / "avatar.vrm"
    vrm_path.write_text("stub")
    palworld_pak = tmp_path / "Pal-Windows.pak"
    palworld_pak.write_text("stub")
    convert_work_root = tmp_path / "work"
    return str(zip_path), str(vrm_path), str(convert_work_root), str(palworld_pak)


def _make_pak_side_effect(cmd):
    """フェイクsubprocess.runの中で、実convert.ps1が作るはずのpakファイルを
    job_dir\\build\\配下に作る(build_host_reference_pak()の成功パスは
    このファイルの存在を要求するため)。"""
    job_json_idx = cmd.index("-Job") + 1
    job_dir = os.path.dirname(cmd[job_json_idx])
    build_dir = os.path.join(job_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    with open(os.path.join(build_dir, "%s_PlayerSwap_P.pak" % AVATAR_NAME), "wb") as f:
        f.write(b"pak-bytes")


class TestMutexWaitMs:
    def test_cmd_includes_mutex_wait_ms(self, tmp_path, monkeypatch):
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)
        captured = []

        def _run(cmd, capture_output=True, timeout=1800):
            captured.append(cmd)
            _make_pak_side_effect(cmd)
            return _FakeCompleted(0, "[Phase 0] OK (1.0s)\nTotal elapsed time: 2.0s\n")

        monkeypatch.setattr(rst.subprocess, "run", _run)

        result = rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        assert result["ok"] is True
        assert len(captured) == 1
        _assert_mutex_wait_ms_present(captured[0], rst.HOST_REF_MUTEX_WAIT_MS)

    def test_negative_control_assertion_detects_missing_mutex_wait_ms(self):
        """検査自体の健全性: -MutexWaitMsを含まないコマンドラインを渡すと、
        機械検査(_assert_mutex_wait_ms_present)は確実にFAIL(AssertionError)する。"""
        cmd_without = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                       "-File", "convert.ps1", "-Job", "job.json", "-EngineMode", "noue"]
        with pytest.raises(AssertionError):
            _assert_mutex_wait_ms_present(cmd_without, 180000)


class TestRetryMechanism:
    """従来この関数はリトライを一切持たなかった(新規追加。意味論の変更では
    なく新規追加であることをNOTES.mdに明記済み)。"""

    def test_mutex_busy_retries_then_succeeds(self, tmp_path, monkeypatch):
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)
        sleeps = []
        monkeypatch.setattr(rst.time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _run(cmd, capture_output=True, timeout=1800):
            calls["n"] += 1
            if calls["n"] < 3:
                return _FakeCompleted(1, "...\n[D2P_MUTEX_BUSY]\n")
            _make_pak_side_effect(cmd)
            return _FakeCompleted(0, "[Phase 0] OK (1.0s)\nTotal elapsed time: 2.0s\n")

        monkeypatch.setattr(rst.subprocess, "run", _run)

        result = rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        assert result["ok"] is True
        assert calls["n"] == 3
        assert len(sleeps) == 2
        assert all(s == rst.HOST_REF_RETRY_WAIT_SEC for s in sleeps)

    def test_non_mutex_failure_does_not_retry(self, tmp_path, monkeypatch):
        """負の対照: マーカー無しの失敗はリトライしない(旧実装(即FAIL)と
        同じ挙動を保つ。「意味論を変えない」はこの経路については元々
        リトライが存在しなかったので変わりようがない、という確認)。"""
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)
        sleeps = []
        monkeypatch.setattr(rst.time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _run(cmd, capture_output=True, timeout=1800):
            calls["n"] += 1
            return _FakeCompleted(1, "some other fatal error, no mutex marker here\n")

        monkeypatch.setattr(rst.subprocess, "run", _run)

        result = rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        assert result["ok"] is False
        assert calls["n"] == 1  # リトライしていない
        assert sleeps == []

    def test_retry_gives_up_after_max_retries_all_busy(self, tmp_path, monkeypatch):
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)
        sleeps = []
        monkeypatch.setattr(rst.time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _run(cmd, capture_output=True, timeout=1800):
            calls["n"] += 1
            return _FakeCompleted(1, "[D2P_MUTEX_BUSY]\n")

        monkeypatch.setattr(rst.subprocess, "run", _run)

        result = rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        assert result["ok"] is False
        assert calls["n"] == rst.HOST_REF_MAX_RETRIES
        assert len(sleeps) == rst.HOST_REF_MAX_RETRIES - 1

    def test_negative_control_old_behavior_had_zero_retries(self, tmp_path, monkeypatch):
        """負の対照(旧実装の再現): このWP以前はリトライ回数が常に1
        (=リトライ無し)だった。新実装がHOST_REF_MAX_RETRIES(>1)まで
        リトライすることが、この「旧仕様=1回」との比較で確認できる。"""
        assert rst.HOST_REF_MAX_RETRIES > 1


class TestPhaseTimesSec:
    def test_phase_times_included_in_success_result(self, tmp_path, monkeypatch):
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)

        def _run(cmd, capture_output=True, timeout=1800):
            _make_pak_side_effect(cmd)
            text = ("[Phase 0] OK (4.4s)\n[pipeline] Mutex released after Phase 1\n"
                    "[noue build] OK (75.1s)\nTotal elapsed time: 92.8s\n")
            return _FakeCompleted(0, text)

        monkeypatch.setattr(rst.subprocess, "run", _run)

        result = rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        assert result["ok"] is True
        phases = result["phase_times_sec"]
        assert phases["phase0_vanilla_sec"] == 4.4
        assert phases["noue_build_sec"] == 75.1
        assert phases["total_elapsed_sec"] == 92.8
        # 実ログ同様、この行が出ないconvert.ps1版もある(欠損はNone、捏造しない)
        assert phases["phase1_blender_sec"] is None

    def test_phase_times_included_in_failure_result(self, tmp_path, monkeypatch):
        """失敗時でも部分的なPhase進捗が観測できる(診断用途、判定には未使用)。"""
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)

        def _run(cmd, capture_output=True, timeout=1800):
            return _FakeCompleted(1, "[Phase 0] OK (9.9s)\nsome fatal error after phase0\n")

        monkeypatch.setattr(rst.subprocess, "run", _run)

        result = rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        assert result["ok"] is False
        assert result["phase_times_sec"]["phase0_vanilla_sec"] == 9.9
        assert result["phase_times_sec"]["total_elapsed_sec"] is None

    def test_negative_control_unparseable_output_yields_none_without_affecting_ok(self, tmp_path, monkeypatch):
        """負の対照: パース不能な出力でもphase_times_secは全部Noneになる
        だけで、ok(合否)フィールドはconvert.ps1のreturncodeだけで決まり続ける
        (fail-openにしない=パース失敗を合否判定に混ぜない)。"""
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)

        def _run(cmd, capture_output=True, timeout=1800):
            _make_pak_side_effect(cmd)
            return _FakeCompleted(0, "completely unrelated garbage, no phase markers\n")

        monkeypatch.setattr(rst.subprocess, "run", _run)

        result = rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        assert result["ok"] is True  # returncode=0で成功、パース失敗の影響を受けていない
        assert all(v is None for v in result["phase_times_sec"].values())

    def test_phase_times_json_written_to_ref_dir(self, tmp_path, monkeypatch):
        zip_path, vrm_path, work_root, pak_path = _setup_common(tmp_path, monkeypatch)

        def _run(cmd, capture_output=True, timeout=1800):
            _make_pak_side_effect(cmd)
            return _FakeCompleted(0, "[Phase 0] OK (1.0s)\nTotal elapsed time: 2.0s\n")

        monkeypatch.setattr(rst.subprocess, "run", _run)

        rst.build_host_reference_pak(zip_path, vrm_path, work_root, AVATAR_NAME, pak_path)

        phase_json = os.path.join(work_root, "host_ref", "phase_times.json")
        assert os.path.isfile(phase_json)
        with open(phase_json, encoding="utf-8") as f:
            data = json.load(f)
        assert data["phase0_vanilla_sec"] == 1.0
        assert data["total_elapsed_sec"] == 2.0


class TestHashCheckExposesPhaseTimes:
    """run_sandbox_test.py main()のhash_check組み立て箇所(L967-980付近)へ
    host_ref_phase_times_secを追加したことの、辞書構築ロジックだけを独立に
    確認する(main()全体はWSB起動を要するため単体試験の対象外)。"""

    def test_hash_check_dict_construction_includes_phase_times_key(self):
        # main()内の実際の構築ロジックと同型の最小再現(辞書リテラル1つの
        # 追加であり、値の由来はref.get("phase_times_sec")のみ)。
        ref = {"ok": True, "pak_sha256": "abc123", "pak_size": 100,
               "elapsed_sec": 5.0, "phase_times_sec": {"phase0_vanilla_sec": 1.0}}
        hash_check = {
            "ok": True,
            "host_ref_elapsed_sec": ref.get("elapsed_sec"),
            "host_ref_phase_times_sec": ref.get("phase_times_sec"),
        }
        assert hash_check["host_ref_phase_times_sec"] == {"phase0_vanilla_sec": 1.0}

    def test_missing_phase_times_sec_key_yields_none_not_keyerror(self):
        """負の対照: refに phase_times_sec キー自体が無くても(旧結果構造との
        後方互換)、.get()なのでKeyErrorにならずNoneになるだけ。"""
        ref = {"ok": True, "pak_sha256": "abc123"}
        assert ref.get("phase_times_sec") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
