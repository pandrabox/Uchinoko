# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7: 旧 tests\\shipcheck\\test_sanitize_clipboard_cs.py
(app\\DiveToPalworld.cs CheckSanitizeForClipboardLogic、
SanitizeForClipboard() L.4673-4737)のPython版試験。

旧テストはcsc.exeでビルドしたexeを`--check-sanitize-clipboard <outDir>`で
起動して検査していた。Python版は app_py\\inquiry.py の
sanitize_for_clipboard() を直接importする。

二重管理の回避: 同じ7(+1)ケースは既に app_py\\tests\\test_inquiry.py
(WP-A5受入試験)に1:1移植済みのため、ここではロジックを複製せず
sanitize_for_clipboard() を直接呼ぶ最小の検査に留める。

検査しているケース(移植元 CheckSanitizeForClipboardLogic):
  case1  … %USERPROFILE%配下は従来どおりトークン化(正の対照、無退行)
  case2  … SteamID64は従来どおりマスク(正の対照、無退行)
  case3  … 単語境界に一致するアカウント名の保険置換(正の対照、無退行)
  case4  … 【核心・dev#7】非%USERPROFILE%ドライブの絶対パスが生で残らない
  case4b … 【診断可用性】マスク後も拡張子等の原因切り分け情報が残る
  case5  … 【核心・dev#7】UNCパスも同様にマスクされる
  case6  … 【負の対照】パスに見えない通常の文章・URLは誤って壊されない
  case7  … 【負の対照】空文字列・nullを渡しても例外にならない
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import inquiry  # noqa: E402


def test_case1_userprofile_is_tokenized():
    up = os.environ.get("USERPROFILE")
    assert up, "このテストはWindows環境(USERPROFILE設定済み)を前提とする"
    under_up = os.path.join(up, "Downloads", "avatar.vrm")
    r1 = inquiry.sanitize_for_clipboard("input: " + under_up)
    assert "%USERPROFILE%" in r1
    assert up not in r1


def test_case2_steamid64_is_masked():
    r2 = inquiry.sanitize_for_clipboard("steamid: 76561198012345678")
    assert "<SteamID>" in r2
    assert "76561198012345678" not in r2


def test_case3_username_word_boundary_is_masked():
    user_name = os.environ.get("USERNAME") or ""
    if len(user_name) <= 3:
        return  # C#版と同じく短い名前は対象外(誤爆防止)
    r3 = inquiry.sanitize_for_clipboard(
        "path fragment: xxx-" + user_name + "-yyy has " + user_name + " alone"
    )
    assert "<user>" in r3
    assert user_name not in r3


def test_case4_non_userprofile_drive_absolute_path_is_masked():
    fake_user_folder = r"D:\Users\SampleTaro\UnityProjects\MyAvatarProject\Assets\avatar.prefab"
    r4 = inquiry.sanitize_for_clipboard("Unity project: " + fake_user_folder)
    assert fake_user_folder not in r4
    assert "SampleTaro" not in r4
    # case4b(診断可用性): マスク後も原因切り分けに使える拡張子情報は残ること
    assert "ext=.prefab" in r4


def test_case5_unc_path_is_masked():
    fake_unc_path = r"\\BUILDSERVER\share\SampleHanako\SteamLibrary\steamapps\common\Palworld\Pal-Windows.pak"
    r5 = inquiry.sanitize_for_clipboard("Palworld pak: " + fake_unc_path)
    assert fake_unc_path not in r5
    assert "SampleHanako" not in r5


def test_case6_unrelated_text_is_not_corrupted():
    plain = "status: converting avatar, see https://example.com/help for C: drive info"
    r6 = inquiry.sanitize_for_clipboard(plain)
    assert "https://example.com/help" in r6


def test_case7a_empty_string_passthrough():
    assert inquiry.sanitize_for_clipboard("") == ""


def test_case7b_none_passthrough():
    assert inquiry.sanitize_for_clipboard(None) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
