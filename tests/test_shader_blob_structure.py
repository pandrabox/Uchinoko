# -*- coding: utf-8 -*-
"""SignPath対応: `devtools\\verify_shader_blob_structure.py` の回帰試験。

対象は `pipeline\\py\\noue_master\\` 配下の357KB級コンパイル済みシェーダー
blob(`M_VP_*_LitMaster{1S,2S}.uexp`)。ここでは:
  1. 4ファイル全件が見つかり、既知のD3Dシェーダーコンテナのチャンク語彙
     (DXBC/DXIL/ISGN/OSGN/SHEX/ISG1/OSG1/HASH/SFI0)が期待どおり検出される
  2. 全"DXIL"パートマーカーについて、直後にLLVMビットコードの正式
     マジックナンバー(`BC\\xC0\\xDE`)が構造的に検証できる
  3. リフレクション情報(RDEF/RDAT、リソース・変数名を含みうる)が
     一切含まれていない
  4. ブロックハッシュ共通部分列検出器そのものの自己診断: 意図的に
     「実データの断片」を模した既知バイト列を注入したコピーに対しては
     検出できる(負の対照)こと、無関係なランダムデータに対しては
     閾値未満しか一致しないこと

実機Palworldへの依存(--real-scan相当)は、CI環境にPalworldが無いため
本ファイルには含めない(手動実行専用。
`python devtools\\verify_shader_blob_structure.py --real-scan` で誰でも
再現できる)。
ネットワーク・実機・Unreal Engine依存は無し(常にfast gate扱い)。
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DEVTOOLS = os.path.join(REPO_ROOT, "devtools")
if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)

import verify_shader_blob_structure as vs  # noqa: E402


def test_all_4_shader_blobs_present():
    assert len(vs.TARGET_SHADER_BLOBS) == 4, (
        f"expected 4 shader blobs (LitMaster1S/2S x m00/m01), "
        f"got {len(vs.TARGET_SHADER_BLOBS)}: {vs.TARGET_SHADER_BLOBS}")
    for p in vs.TARGET_SHADER_BLOBS:
        assert os.path.exists(p)
        assert os.path.getsize(p) > 300_000, (
            f"{p}: unexpectedly small for a compiled-shader blob "
            f"({os.path.getsize(p)} bytes)")


def test_container_marker_vocabulary_matches_declared_platforms():
    """shader_platform_facts.json は PCD3D_SM5 + PCD3D_SM6 でcook済みと
    宣言している。実際に見つかるチャンク語彙がその宣言と整合すること
    (SM5枝: DXBC/ISGN/OSGN/SHEX、SM6枝: DXIL/ISG1/OSG1/HASH/SFI0)。"""
    for p in vs.TARGET_SHADER_BLOBS:
        with open(p, "rb") as f:
            data = f.read()
        markers = vs.scan_container_markers(data)
        for expected in ("DXBC", "ISGN", "OSGN", "SHEX", "DXIL", "ISG1", "OSG1",
                          "HASH", "SFI0"):
            assert markers.get(expected, 0) > 0, (
                f"{p}: expected container marker {expected!r} not found "
                f"(markers={markers})")


def test_dxil_bitcode_magic_verified_for_every_dxil_marker():
    """全"DXIL"パートマーカーの直後(探索窓内)にLLVMビットコードの正式
    マジックナンバーが存在すること。文字列走査ではなく、コンパイル済み
    バイトコードとして意味を持つ固定マジックナンバーの構造検証。"""
    for p in vs.TARGET_SHADER_BLOBS:
        with open(p, "rb") as f:
            data = f.read()
        result = vs.verify_dxil_bitcode_magic(data)
        assert result["dxil_marker_count"] > 0, f"{p}: no DXIL markers found at all"
        assert result["verified"] == result["dxil_marker_count"], (
            f"{p}: {result['dxil_marker_count'] - result['verified']} of "
            f"{result['dxil_marker_count']} DXIL markers had no LLVM bitcode "
            f"magic nearby: {result['unverified_positions']}")


def test_no_reflection_name_chunks_present():
    """RDEF/RDAT(リソース・変数の"名前"を保持しうる唯一のチャンク種別)が
    一切無いこと。shipping向けにリフレクション情報を剥ぎ取る処理を経た
    証拠であり、そもそもパラメータ名の類がこのblobから構造的に
    復元できないことの確認。"""
    for p in vs.TARGET_SHADER_BLOBS:
        with open(p, "rb") as f:
            data = f.read()
        found = vs.check_name_bearing_chunks(data)
        assert not found, f"{p}: found name-bearing chunk(s): {found}"


def test_analyze_blob_end_to_end_reports_clean():
    for p in vs.TARGET_SHADER_BLOBS:
        r = vs.analyze_blob(p)
        assert not r["name_bearing_chunks_found"]
        dxil = r["dxil_bitcode_verification"]
        assert dxil["verified"] == dxil["marker_count"]


# --------------------------------------------------------------------------
# 共通部分列検出器そのものの自己診断(負の対照)。
# 実Palworldデータは使わず、合成データで検出ロジックの健全性を検証する。
# --------------------------------------------------------------------------

def _random_bytes(n, seed):
    rnd = random.Random(seed)
    return bytes(rnd.randrange(256) for _ in range(n))


def test_common_substring_detector_finds_injected_block_negative_control():
    """「実データの断片」を模した既知バイト列を、無関係なランダムデータの
    コピーへ意図的に注入し、検出器がそれを見つけられることを確認する
    (負の対照: 壊したケースが依然として検出されることを示す)。"""
    injected = _random_bytes(200, seed=12345)  # 「流用された断片」を模す
    ref_data = _random_bytes(5000, seed=1) + injected + _random_bytes(5000, seed=2)
    needle = _random_bytes(3000, seed=3) + injected + _random_bytes(3000, seed=4)

    ref_index = vs._block_hash_index(ref_data, block_size=48)
    matches = vs.find_common_substrings(needle, ref_index, ref_data, block_size=48)

    assert matches, "expected the detector to find the deliberately injected 200B overlap"
    best = max(matches, key=lambda m: m["length"])
    assert best["length"] >= 200, (
        f"expected the full 200B injected block to be found (with extension), "
        f"got length={best['length']}")


def test_common_substring_detector_no_false_positives_on_unrelated_random_data():
    """完全に無関係な乱数データ同士では、48バイト以上の一致は
    (確率的に)ほぼ発生しないこと(誤検出が無いことの確認)。"""
    ref_data = _random_bytes(20_000, seed=100)
    needle = _random_bytes(20_000, seed=200)  # 別シード = 独立した乱数列

    ref_index = vs._block_hash_index(ref_data, block_size=48)
    matches = vs.find_common_substrings(needle, ref_index, ref_data, block_size=48)

    assert matches == [], (
        f"expected no matches between independent random byte streams, "
        f"got {len(matches)}: {matches}")


def test_block_hash_index_and_extend_match_are_self_consistent():
    """_block_hash_index + _extend_match の組み合わせで、既知位置に置いた
    既知長の一致が、過不足なくその長さで報告されること
    (前後を非一致バイトで挟んで伸長が止まることを確認)。"""
    payload = _random_bytes(300, seed=42)
    # 前後を別シードの乱数で挟む(payloadとは値が変わる可能性が高いバイトで
    # 境界を作る。境界バイトがたまたま一致しても_extend_matchは伸び続ける
    # だけで正しさが壊れるわけではないため、この検査は下限の確認に留める)。
    prefix = _random_bytes(1000, seed=7)
    suffix = _random_bytes(1000, seed=8)
    ref_data = prefix + payload + suffix
    needle = _random_bytes(500, seed=9) + payload + _random_bytes(500, seed=10)

    ref_index = vs._block_hash_index(ref_data, block_size=48)
    matches = vs.find_common_substrings(needle, ref_index, ref_data, block_size=48,
                                         min_report_len=48)
    assert matches, "expected the 300B shared payload to be detected"
    best = max(matches, key=lambda m: m["length"])
    assert best["length"] >= 300
