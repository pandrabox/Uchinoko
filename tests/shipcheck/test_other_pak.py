# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7/WP-A11(dev#549): 旧 `--check-other-pak` 隠しCLI(app\\DiveToPalworld.cs
CheckOtherPakLogic L.5539-5601、CountOtherPaks/SummarizeOtherPaks)のPython版試験。

旧 test_*_cs.py との違い: `--check-other-pak` にはこれまで tests\\shipcheck\\
配下の専用ラッパーファイルが存在しなかった(11個の--check-*隠しCLIのうち、
tests\\shipcheck\\test_*_cs.pyという専用テストが無かった4つのうちの1つ)。
Python化に伴い、app_py\\pak_manager.py を直接importして検査する。

検査しているケース(移植元 CheckOtherPakLogic、実ファイルシステムを使う
使い捨てフォルダ検査。実Palworldインストール非依存):
  case1  … 自分自身(現行名Uchinoko_P.pak+レガシー名2種)とバニラ本体
           (Pal-Windows.pak)だけ -> 他MODなし(count=0)
  case2  … 正の対照: ダミーの他.pakを1件追加 -> count=1
  case2b … 2件目を追加 -> count=2
  case3  … 撤去したら元に戻る(negative control: 常態への復帰、count=0)
  case4  … フォルダ不明(判定不能) -> count=None(0で決め打ちしない)

SummarizeOtherPaks(件数を"other_paks: none" / "other_paks: 1 (.pak)" /
"other_paks: unknown (paks dir not found)" という文言へ整形し、かつファイル名を
一切出さない伏字化裁定dev#103を守る関数)は dev#532方針A WP-A11(dev#549)で
pak_manager.summarize_other_paks() として移植した。
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

import pak_manager  # noqa: E402


@pytest.fixture()
def fake_paks_dir(tmp_path):
    d = tmp_path / "fake_paks"
    d.mkdir()
    (d / pak_manager.PAL_WINDOWS_PAK_NAME).write_bytes(b"\x00")
    (d / pak_manager.INSTALL_NAME).write_bytes(b"\x00")
    (d / pak_manager.LEGACY_INSTALL_NAMES[0]).write_bytes(b"\x00")
    return d


def test_case1_self_legacy_vanilla_only_counts_zero(fake_paks_dir):
    n = pak_manager.count_other_paks(str(fake_paks_dir))
    assert n == 0
    assert pak_manager.summarize_other_paks(n) == "other_paks: none"


def test_case2_one_other_mod_counts_one_and_no_name_leak(fake_paks_dir):
    dummy_name = "ZZZ_SomeOtherModWithASecretName_P.pak"
    (fake_paks_dir / dummy_name).write_bytes(b"\x00")
    n = pak_manager.count_other_paks(str(fake_paks_dir))
    assert n == 1
    # 負の対照(dev#103裁定の核心): count_other_paksの戻り値はint|Noneのみで
    # ファイル名を一切含みえない設計であることの確認(型そのものが伏字化を保証)
    assert isinstance(n, int)
    line = pak_manager.summarize_other_paks(n)
    assert line == "other_paks: 1 (.pak)"
    assert "SomeOtherMod" not in line, (
        "ファイル名が診断ログの文言へ漏れた(dev#103裁定違反): " + line
    )


def test_case2b_two_other_mods_counts_two(fake_paks_dir):
    (fake_paks_dir / "ZZZ_SomeOtherMod_P.pak").write_bytes(b"\x00")
    (fake_paks_dir / "AAA_AnotherMod_P.pak").write_bytes(b"\x00")
    assert pak_manager.count_other_paks(str(fake_paks_dir)) == 2


def test_case3_removed_returns_to_zero(fake_paks_dir):
    dummy = fake_paks_dir / "ZZZ_SomeOtherMod_P.pak"
    dummy.write_bytes(b"\x00")
    assert pak_manager.count_other_paks(str(fake_paks_dir)) == 1
    dummy.unlink()
    n = pak_manager.count_other_paks(str(fake_paks_dir))
    assert n == 0
    assert pak_manager.summarize_other_paks(n) == "other_paks: none"


def test_case4_unresolvable_dir_returns_none(tmp_path):
    does_not_exist = tmp_path / "does_not_exist_dir"
    n = pak_manager.count_other_paks(str(does_not_exist))
    assert n is None
    assert pak_manager.count_other_paks(None) is None
    assert pak_manager.summarize_other_paks(n) == "other_paks: unknown (paks dir not found)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
