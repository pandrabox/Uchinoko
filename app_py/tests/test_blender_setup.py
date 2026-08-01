# test_blender_setup.py -- WP-A3受入条件: DecideBlenderSetupAction相当の3分岐を
# pytestで網羅する(旧 --check-blender-setup-decision / CheckBlenderSetupDecisionLogic
# L.5055-5083 相当のPython版試験。DESIGN.md §5.2 WP-A3行)。
#
# ケース表は app\DiveToPalworld.cs の CheckBlenderSetupDecisionLogic() が持つ
# 8通り(ensurePs1Exists x blenderExeExists x checkOnlyValid の全組み合わせ)を
# そのまま移植したもの(L.5059-5070)。実Blender・実プロセス起動は行わない
# (CLAUDE.md「受入試験はリリースゲートに任せる」: 変換を伴わない、ロジック単体+
# 負の対照のみで止める)。

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import blender_setup  # noqa: E402
from blender_setup import BlenderSetupAction, decide_blender_setup_action  # noqa: E402

# (ensure_ps1_exists, blender_exe_exists, check_only_valid, expected)
# DiveToPalworld.cs L.5059-5070 の8ケースと1:1(順序・値とも同一)。
CASES = [
    (False, False, False, BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT),
    (False, False, True, BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT),
    (False, True, False, BlenderSetupAction.READY_NO_ACTION),
    (False, True, True, BlenderSetupAction.READY_NO_ACTION),
    (True, False, False, BlenderSetupAction.NEED_FULL_SETUP),
    (True, False, True, BlenderSetupAction.NEED_FULL_SETUP),
    # dev#230の核心: exeはあるがマーカー無効 -> 即readyにせず必ずフル実行
    (True, True, False, BlenderSetupAction.NEED_FULL_SETUP),
    (True, True, True, BlenderSetupAction.READY_NO_ACTION),
]


@pytest.mark.parametrize(
    "ensure_ps1_exists,blender_exe_exists,check_only_valid,expected", CASES
)
def test_decide_blender_setup_action_case_table(
    ensure_ps1_exists, blender_exe_exists, check_only_valid, expected
):
    actual = decide_blender_setup_action(
        ensure_ps1_exists, blender_exe_exists, check_only_valid
    )
    assert actual == expected, (
        f"ensure_ps1_exists={ensure_ps1_exists} blender_exe_exists={blender_exe_exists} "
        f"check_only_valid={check_only_valid}: expected={expected} actual={actual}"
    )


def test_case_table_covers_all_eight_combinations():
    # 網羅性そのものの負の対照: 3引数の全2^3=8通りが表にあることを確認する
    # (表の一部を消しても他のケースだけでは気づけない、という空洞化を防ぐ)。
    seen = {(c[0], c[1], c[2]) for c in CASES}
    assert len(seen) == 8


def test_dev_not_found_ignores_check_only_valid():
    # ensurePs1が無ければcheckOnlyValidの値に関わらずexeの有無だけで決まる
    # (コメントL.5049-5051の主張そのものを明示的に検査する負の対照)。
    a = decide_blender_setup_action(False, False, False)
    b = decide_blender_setup_action(False, False, True)
    assert a == b == BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT


def test_stale_marker_forces_full_setup_not_ready():
    # dev#230の核心そのものへの負の対照: 「exeがあるだけ」でreadyにしてしまう
    # 退行が起きたら必ず落ちる(exe実在=True, checkOnlyValid=False は
    # NEED_FULL_SETUPでなければならない)。
    assert (
        decide_blender_setup_action(True, True, False)
        == BlenderSetupAction.NEED_FULL_SETUP
    )


# ---------------------------------------------------------------------------
# 補助関数の単体試験(実プロセス起動を伴わない範囲)
# ---------------------------------------------------------------------------

def test_find_blender_falls_back_to_bare_name_when_nothing_found(tmp_path, monkeypatch):
    # 候補(assets\tools配下、開発機決め打ちパス)がいずれも存在しない環境では
    # C#版同様 "blender.exe"(PATH解決に委ねる文字列)を返す。
    # _DEV_FALLBACK_BLENDER_DIRはこのリポジトリの指揮者機(ぱんのPC)には実在
    # しうる(dev#149の開発機フォールバックそのもの)ため、テストの再現性を
    # 環境に依存させないよう明示的に存在しないパスへ差し替える。
    monkeypatch.setattr(
        blender_setup, "_DEV_FALLBACK_BLENDER_DIR", str(tmp_path / "no_such_blender_dir")
    )
    empty_root = str(tmp_path)
    result = blender_setup.find_blender(empty_root)
    assert result == "blender.exe"


def test_find_blender_prefers_assets_tools_over_dev_fallback(tmp_path):
    tools_dir = tmp_path / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    exe = tools_dir / "blender.exe"
    exe.write_text("stub")
    result = blender_setup.find_blender(str(tmp_path))
    assert result == str(exe)


def test_asset_sub_dir_prefers_assets_subdir_when_present(tmp_path):
    dist_dir = tmp_path / "assets" / "tools"
    dist_dir.mkdir(parents=True)
    assert blender_setup.asset_sub_dir(str(tmp_path), "tools") == str(dist_dir)


def test_asset_sub_dir_falls_back_to_direct_subdir(tmp_path):
    # assets\tools が存在しない開発ツリーでは直下\tools を返す(L.1752-1757)。
    expected = os.path.join(str(tmp_path), "tools")
    assert blender_setup.asset_sub_dir(str(tmp_path), "tools") == expected


def test_ensure_blender_ps1_path_joins_pipeline_cli(tmp_path):
    expected = os.path.join(str(tmp_path), "pipeline", "cli", "ensure_blender.ps1")
    assert blender_setup.ensure_blender_ps1_path(str(tmp_path)) == expected


def test_run_ensure_blender_check_only_returns_false_when_script_missing(tmp_path):
    # ensure_ps1自体が存在しない(≒ファイル起動が失敗する)場合でも例外を投げず
    # False(安全側のフルセットアップへのフォールバック)を返すこと。
    missing_ps1 = str(tmp_path / "no_such_ensure_blender.ps1")
    result = blender_setup.run_ensure_blender_check_only(
        missing_ps1, str(tmp_path), timeout_sec=5.0
    )
    assert result is False


def test_run_ensure_blender_setup_process_relays_progress_and_extracts_fail_message(
    monkeypatch, tmp_path
):
    # 実ensure_blender.ps1もpwshも使わず、subprocess.Popenをダミープロセスへ
    # 差し替えて「##PROGRESS##中継」と「[D2P_BLENDER_SETUP_FAIL]以降の抽出」の
    # 2点だけを検査する(実Blenderダウンロードは受入に含めない、指示書どおり)。
    class _FakeProc:
        def __init__(self, lines, returncode):
            self.stdout = iter(lines)
            self.returncode = returncode

        def wait(self):
            return self.returncode

    fake_lines = [
        "##PROGRESS## 10 Downloading\n",
        "##PROGRESS## 55 Patching\n",
        "[D2P_BLENDER_SETUP_FAIL] something went wrong\nsee log for details\n",
    ]

    def _fake_popen(*args, **kwargs):
        return _FakeProc(fake_lines, returncode=1)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    progress_calls = []
    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1",
        str(tmp_path),
        on_progress=lambda pct, phase: progress_calls.append((pct, phase)),
    )

    assert ok is False
    assert progress_calls == [(10, "Downloading"), (55, "Patching")]
    assert fail_message is not None
    assert fail_message.startswith("[D2P_BLENDER_SETUP_FAIL]")
    assert "something went wrong" in fail_message


def test_run_ensure_blender_setup_process_success_has_no_fail_message(monkeypatch, tmp_path):
    class _FakeProc:
        def __init__(self, lines, returncode):
            self.stdout = iter(lines)
            self.returncode = returncode

        def wait(self):
            return self.returncode

    def _fake_popen(*args, **kwargs):
        return _FakeProc(["##PROGRESS## 100 Done\n"], returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1", str(tmp_path)
    )
    assert ok is True
    assert fail_message is None


def test_do_ensure_blender_ready_ready_no_action_when_no_ensure_script(monkeypatch, tmp_path):
    # ensure_ps1が無く、find_blenderがexeを見つけられる場合(モック)は
    # READY_NO_ACTIONで即成功。ensure_blender.ps1もpwshも一切起動しない。
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("stub")
    monkeypatch.setattr(blender_setup, "find_blender", lambda app_root: str(fake_blender))

    ok, fail_message, action = blender_setup.do_ensure_blender_ready(str(tmp_path))
    assert ok is True
    assert fail_message is None
    assert action == BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT or action == BlenderSetupAction.READY_NO_ACTION
    # ensure_ps1(pipeline\cli\ensure_blender.ps1)は本物がリポジトリに存在するため
    # tmp_pathを渡した場合はensure_ps1_exists=Falseとなり、exeが実在するので
    # DecideBlenderSetupAction(False, True, *)=READY_NO_ACTIONになるはず
    assert action == BlenderSetupAction.READY_NO_ACTION


def test_do_ensure_blender_ready_dev_not_found_when_nothing_exists(tmp_path, monkeypatch):
    # 同様に開発機決め打ちパスの実在に依存しないよう差し替える(上記コメント参照)。
    monkeypatch.setattr(
        blender_setup, "_DEV_FALLBACK_BLENDER_DIR", str(tmp_path / "no_such_blender_dir")
    )
    ok, fail_message, action = blender_setup.do_ensure_blender_ready(str(tmp_path))
    assert ok is False
    assert action == BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
    assert fail_message is not None
