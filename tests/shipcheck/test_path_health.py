# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7: 旧 `--check-path-health` 隠しCLI(app\\DiveToPalworld.cs
CheckPathHealthLogic L.5678-5754)のPython版試験。

`--check-path-health` にはこれまで tests\\shipcheck\\配下の専用ラッパーファイル
(test_path_health_cs.py相当)が存在しなかった(ship_smoke.py等からも直接は
呼ばれておらず、C#側の単体表として存在するのみだった)。Python版は
app_py\\path_health.py を直接importする。

二重管理の回避: 同じ7ケースは既に app_py\\tests\\test_diagnostics.py
(WP-A6受入試験)に1:1移植済みのため、ここではロジックを複製せず
path_health.py を直接呼ぶ最小の検査に留める(受入条件「対応モジュールを
importして実行」は満たしつつ、ケース表の唯一の正本はtest_diagnostics.py
に保つ)。

検査しているケース(移植元 CheckPathHealthLogic):
  case1 … 健全なパス(問題なし)
  case2 … 負の対照: 長すぎるパス(閾値超過)を検出し、長さをログへ残す
  case3 … 境界値(閾値ちょうど手前)は検出しない
  case4 … UNCパスは常に問題扱い
  case5 … OneDrive配下の検出+負の対照(配下でない/ルート不明なら誤検知しない)
  case6 … 非ASCIIは記録するが単独では問題扱いしない
  case7 … 空パスは安全(例外にならず、問題なし)
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import path_health as ph  # noqa: E402


def test_case1_healthy_path_no_problem():
    f = ph.build_path_facts("install", r"C:\P\Work\DiveToPalworld", None)
    assert not ph.path_health_problem(f)
    assert not f.non_ascii
    assert not f.unc
    assert not f.under_onedrive


def test_case2_negative_too_long_flags_and_logs_length():
    long_path = "C:\\" + ("a" * 220)
    f = ph.build_path_facts("install", long_path, None)
    assert ph.path_health_problem(f)
    line = ph.path_health_line(f)
    assert str(len(long_path)) in line


def test_case3_boundary_length_not_flagged():
    at_threshold = "C:\\" + ("a" * (ph.PATH_LENGTH_WARN_THRESHOLD - 4))
    f = ph.build_path_facts("boundary", at_threshold, None)
    assert not ph.path_health_problem(f)


def test_case4_unc_always_problem():
    f = ph.build_path_facts("unc", r"\\server\share\short", None)
    assert ph.path_health_problem(f)


def test_case5_onedrive_detection_and_negative_controls():
    onedrive = r"C:\Users\someone\OneDrive"
    under = ph.build_path_facts("work", onedrive + r"\DiveToPalworld\work", onedrive)
    assert ph.path_health_problem(under)

    outside = ph.build_path_facts("work", r"C:\DiveToPalworld\work", onedrive)
    assert not ph.path_health_problem(outside)

    no_root_known = ph.build_path_facts("work", onedrive + r"\DiveToPalworld\work", None)
    assert not ph.path_health_problem(no_root_known)


def test_case6_non_ascii_noted_but_not_a_problem():
    f = ph.build_path_facts("install", "C:\\Users\\\u3071\u3093\\DiveToPalworld", None)
    assert f.non_ascii
    assert not ph.path_health_problem(f)
    assert "non-ASCII" in ph.path_health_line(f)


def test_case7_empty_path_is_safe():
    f = ph.build_path_facts("install", None, None)
    assert not ph.path_health_problem(f)
    assert f.length == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
