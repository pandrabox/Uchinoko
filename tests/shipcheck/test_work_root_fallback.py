# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7: 旧 `--check-work-root-fallback` 隠しCLI
(app\\DiveToPalworld.cs CheckWorkRootFallbackLogic L.5804-5873)のPython版試験。

`--check-work-root-fallback` にはこれまで tests\\shipcheck\\配下の専用
ラッパーファイルが存在しなかった。Python版は app_py\\path_health.py の
resolve_work_root/probe_work_root_writable を直接importする。

二重管理の回避: 同じ5ケースは既に app_py\\tests\\test_diagnostics.py
(WP-A6受入試験)に1:1移植済みのため、ここではロジックを複製せず
path_health.py を直接呼ぶ最小の検査に留める。

検査しているケース(移植元 CheckWorkRootFallbackLogic):
  case1 … 基準点: 主系が書き込み可能 -> 主系をそのまま使い、フォールバック先
           へは一切触れない(不要な書き込み可否チェックをしないことも確認)
  case2 … 負の対照: 主系が書き込み不可(実報告R7GJY5W3相当)-> 自動的に
           フォールバックへ切り替わり、主系のエラー文言も保持される
  case3 … 負の対照: 主系・フォールバック先の両方が書き込み不可 -> Failed=true、
           両方のエラーが残り、Pathは空にならない(安全なデフォルト)
  case4 … 実I/O、基準点: 実際に書き込み可能な一時フォルダはエラー無し
           (probe自身が痕跡ファイルを残さない=自己クリーンも確認)
  case5 … 実I/O、負の対照: 存在しないドライブレターの配下は書き込み不可
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


def test_case1_primary_writable_fallback_not_probed():
    probed = {"fallback": False}

    def probe(p):
        if p == "C:\\fallback":
            probed["fallback"] = True
        return None

    res = ph.resolve_work_root("C:\\primary", "C:\\fallback", probe)
    assert not res.used_fallback
    assert not res.failed
    assert res.path == "C:\\primary"
    assert not probed["fallback"]


def test_case2_negative_primary_unwritable_falls_back():
    def probe(p):
        return (
            "UnauthorizedAccessException: Access to the path is denied."
            if p.startswith("C:\\Program Files")
            else None
        )

    res = ph.resolve_work_root(
        "C:\\Program Files\\Uchinoko_for_Palworld\\work", "C:\\fallback", probe
    )
    assert res.used_fallback
    assert not res.failed
    assert res.path == "C:\\fallback"
    assert res.primary_error is not None and "denied" in res.primary_error.lower()


def test_case3_negative_both_unwritable_fails_safely():
    res = ph.resolve_work_root("C:\\primary", "C:\\fallback", lambda p: "Access is denied")
    assert res.failed
    assert res.primary_error is not None
    assert res.fallback_error is not None
    assert res.path  # never empty/None even on failure


def test_case4_real_io_writable_dir_self_cleans(tmp_path):
    real_dir = tmp_path / "real_writable_probe"
    err = ph.probe_work_root_writable(str(real_dir))
    assert err is None
    assert real_dir.is_dir()
    assert list(real_dir.iterdir()) == []  # probe must not leave stray files


def test_case5_negative_nonexistent_drive_fails():
    if os.path.exists("Z:\\"):
        return  # 実在するドライブだと偽陽性になるので実在しない時だけ検査
    err = ph.probe_work_root_writable("Z:\\__d2p_nonexistent_drive_probe__\\work")
    assert err is not None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
