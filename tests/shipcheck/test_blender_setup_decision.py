# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7: 旧 tests\\shipcheck\\test_blender_setup_decision_cs.py
(app\\DiveToPalworld.cs CheckBlenderSetupDecisionLogic、
DecideBlenderSetupAction() L.2019-2030)のPython版試験。

旧テストはcsc.exeでビルドしたexeを`--check-blender-setup-decision <outDir>`
で起動し、全8通り(2^3)の入力組み合わせを検査していた。Python版は
app_py\\blender_setup.py の decide_blender_setup_action() を直接importする
(プロセス起動・ビルド手順が丸ごと不要になった)。

二重管理の回避: 同じ8ケース+2つの負の対照は既に
app_py\\tests\\test_blender_setup.py(WP-A3受入試験)に1:1移植済みのため、
ここではロジックを複製せず decide_blender_setup_action() を直接呼ぶ
最小の検査に留める。

検査しているケース(移植元 CheckBlenderSetupDecisionLogic、全8通り):
  ensurePs1が無い(開発チェックアウト等) -> exeの有無だけで決まる
  (checkOnlyValidの値に関わらず結果不変、2ケースずつで確認) x2
  ensurePs1がありexeもありcheckOnlyValid=true -> ReadyNoAction
  dev#230の核心・負の対照: ensurePs1があり exeはあるが checkOnlyValid=false
  (マーカー無効) -> NeedFullSetup(「exeがあるだけ」で即readyにしない)
  ensurePs1があってもexe自体が無ければ常にNeedFullSetup
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

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
    assert actual == expected


def test_case_table_covers_all_eight_combinations():
    seen = {(c[0], c[1], c[2]) for c in CASES}
    assert len(seen) == 8


def test_stale_marker_forces_full_setup_not_ready():
    # dev#230の核心そのものへの負の対照(退行が起きたら必ず落ちる)
    assert (
        decide_blender_setup_action(True, True, False)
        == BlenderSetupAction.NEED_FULL_SETUP
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
