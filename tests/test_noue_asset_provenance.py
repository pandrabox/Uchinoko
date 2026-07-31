# -*- coding: utf-8 -*-
"""`pipeline\\py\\noue_master\\`(34ファイル/17ペア)が自作資産である
という主張(PROVENANCE_NOUE_ASSETS.md)を機械的に検証する回帰試験。

実体は `devtools\\verify_noue_asset_provenance.py`。ここでは:
  1. 34ファイル全件の import-table 解析が例外なく通り、自パッケージ/
     UEエンジン標準名前空間(`/Script/*`)以外を一切参照していないこと
  2. t00(4096px版)の再生成が、種(tex_src_2048)からバイト一致で
     再現できること(devtool_make_t00_4096.py、UE不使用)
  3. 全 .uexp(357KB級のコンパイル済みシェーダーblobを含む)に
     Palworld/ゲームを示す識別子が印字可能文字列として一切現れないこと

を確認する。ネットワーク・実機・Unreal Engine 依存は無し(常にfast gate扱い)。
負の対照(ユーザーのPalworldインストールから実在アセットを取り出して判定が
反転することの確認)は、パイプラインのCI環境にPalworldが無いため本ファイルには
含めない(手動実行専用。devtools\\verify_noue_asset_provenance.py --file <path>
で誰でも再現できる)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DEVTOOLS = os.path.join(REPO_ROOT, "devtools")
if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)

import verify_noue_asset_provenance as vnap  # noqa: E402


def test_all_34_files_present_and_paired():
    targets = vnap.find_all_uasset()
    assert len(targets) == 17, f"expected 17 uasset files (17 pairs=34 files), got {len(targets)}"
    total = 0
    for p in targets:
        assert os.path.exists(p)
        uexp = p[:-len(".uasset")] + ".uexp"
        assert os.path.exists(uexp), f"missing paired uexp for {p}"
        total += 2
    assert total == 34


def test_import_table_has_no_disallowed_package_references():
    targets = vnap.find_all_uasset()
    results = [vnap.analyze_file(p) for p in targets]
    assert len(results) == 17
    for r in results:
        assert r["uexp_pair_structurally_consistent"], (
            f"{r['file']}: uexp/uasset structural mismatch: {r['uexp_pair_error']}")
        assert not r["disallowed_packages"], (
            f"{r['file']}: references disallowed (non-Script/non-own) packages: "
            f"{r['disallowed_packages']}")


def test_t00_4096_regen_matches_committed_bytes():
    result = vnap.regen_check()
    assert result["returncode"] == 0, result["stderr"]
    assert result["matches"] == {"uasset": True, "uexp": True}


def test_shader_blobs_contain_no_game_identifiers():
    targets = vnap.find_all_uasset()
    any_hit = {}
    for p in targets:
        uexp = p[:-len(".uasset")] + ".uexp"
        r = vnap.scan_uexp_for_game_strings(uexp)
        if r["hit_patterns"]:
            any_hit[uexp] = r["hit_patterns"]
    assert not any_hit, f"Palworld/game identifiers found in: {any_hit}"
