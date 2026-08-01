# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7: 旧 `--check-palworld-compat` 隠しCLI
(tests\\shipcheck\\test_palworld_compat_cs.py、app\\DiveToPalworld.cs
CheckPalworldCompatLogic)のPython版試験。

旧 test_palworld_compat_cs.py は csc.exe でビルドしたexeを
`--check-palworld-compat <outDir>` で起動し、標準出力/結果ファイルを
検査していた(ビルド+プロセス起動で数秒〜数十秒)。Python版は
app_py\\compat_check.py を直接importし、同じ10ケースのうち
Python版に該当ロジックが存在する9ケースをpytestの関数として検査する
(case10=JsonObj波括弧バランス抽出は、標準jsonモジュール採用によりPython版に
該当バグ源自体が存在しないため対象外。app_py\\compat_check.py 冒頭の
docstring L.22-30に指揮者裁定として明記済み)。

二重管理の回避: 同じケース表は既に app_py\\tests\\test_diagnostics.py
(WP-A6受入試験)に1:1移植済みのため、ここではロジックを複製せず、
compat_check.py を直接呼ぶ最小の検査に留める(受入条件は「対応モジュールを
importして実行」であり、ケース数はtest_diagnostics.py側の9ケースで
既に旧test_palworld_compat_cs.pyの9ケース(case10除く)以上を満たしている)。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import compat_check as cc  # noqa: E402

BUNDLED_JSON = (
    '{"known_versions":[{"build_id":"111","pak_size":1000,"label":"1.0.1"}],'
    '"known_vanilla_manifest_sha256":["aaaa"]}'
)


def test_case1_known_version_no_warn():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    st = cc.evaluate(known, det, None)
    assert st.detected and st.known_version and not st.should_warn


def test_case2_remote_only_known_version_merges_additively():
    remote = '{"known_versions":[{"build_id":"222","pak_size":2000,"label":"1.0.2"}]}'
    known = cc.merge_known_good(BUNDLED_JSON, remote)
    det = cc.PalworldDetection(detected=True, build_id="222", pak_size=2000)
    st = cc.evaluate(known, det, None)
    assert st.known_version and not st.should_warn
    assert cc.is_known_version(known, "111", 1000)


def test_case3_unknown_version_known_manifest_no_warn():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    st = cc.evaluate(known, det, "aaaa")
    assert st.manifest_available and st.known_manifest and not st.should_warn


def test_case4_negative_unknown_version_and_manifest_mismatch_warns():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    st = cc.evaluate(known, det, "zzzz")
    assert st.should_warn and st.manifest_available and not st.known_manifest


def test_case5_manifest_not_available_yet_warns():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    st = cc.evaluate(known, det, None)
    assert st.should_warn and not st.manifest_available


def test_case6_undetectable_no_warn():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=False)
    st = cc.evaluate(known, det, None)
    assert not st.detected and not st.should_warn


def test_case7_offline_fallback_bundled_only():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    assert len(known.versions) == 1
    assert len(known.manifest_hashes) == 1


def test_case8_negative_bundled_list_emptied_offline_warns():
    known = cc.merge_known_good('{"known_versions":[],"known_vanilla_manifest_sha256":[]}', None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    st = cc.evaluate(known, det, None)
    assert st.should_warn


def test_case9_log_line_contains_detected_and_supported():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    st = cc.evaluate(known, det, None)
    line = cc.build_log_line(known, st)
    assert "111" in line and "1.0.1" in line


def test_case10_not_applicable_python_uses_stdlib_json():
    # case10(JsonObj balanced-brace extraction)は自前JSONパーサの再帰/波括弧
    # バグを検査するC#固有のケース。Python版はjson.loadsを使うため該当バグ源が
    # 構造的に存在しない(compat_check.py docstring L.22-30、WP-A6裁定)。
    # ネストしたオブジェクトを正しく取り出せることだけ確認して代替する。
    nested = (
        '{"latest":"2.2.13","palworld_known_good":{"known_versions":'
        '[{"build_id":"1","pak_size":1,"label":"a"},'
        '{"build_id":"2","pak_size":2,"label":"b"}],'
        '"known_vanilla_manifest_sha256":["h1","h2"]},"other":1}'
    )
    import json
    block = json.loads(nested)["palworld_known_good"]
    known = cc.merge_known_good(BUNDLED_JSON, json.dumps(block))
    # 同梱1件(build_id=111)+リモート2件(build_id=1,2)が重複なく足し込まれる
    assert len(known.versions) == 3
    assert len(known.manifest_hashes) == 3  # 同梱1件+リモート2件
    assert cc.is_known_version(known, "1", 1)
    assert cc.is_known_version(known, "2", 2)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
