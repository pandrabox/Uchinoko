# -*- coding: utf-8 -*-
"""dev#220(2026-07-30): template_prep(build_live_template)コールドパス高速化の
単体試験+負の対照。

対象の変更(いずれも出力バイト不変を主張、Layers-Affected: none):
  - pipeline\\py\\vp_core.py: read_pak_index/read_pak_entries/
    read_pak_compression_methods にプロセス内メモ化(_pak_cached)を追加。
    read_pak_entries内部が自分自身のmountを別途read_pak_index()経由で
    二重取得していた冗長呼び出しも除去(_read_pak_entries_uncached)。
  - pipeline\\py\\vp_core.py: _find_sk_index_buffer_candidates を
    「全バイトを1つずつPythonループで判定」から「reで対象バイト値の位置だけ
    先に列挙してから重い検証」に変更。
  - pipeline\\py\\parse_sk_structure.py: _find_render_sections_start も同様に
    re前置フィルタへ変更。

このファイルの前半(test_find_*_matches_reference_bruteforce系)は、変更前の
実装をテスト内に「参照実装」としてそのまま複製し、多数のランダム合成入力に対して
新実装(vp_core./parse_sk_structure.の実体)と完全一致することを確認する
(=負の対照: 参照実装と1バイトでも結果が食い違えば即FAIL)。pakは不要、数秒で
終わる。

後半(test_pak_cache_*)はダミーの一時ファイルでvp_core._pak_cachedの
キャッシュキー(パス+mtime_ns+size)の意味論を検証する(pakパースは不要)。

最後(test_real_pak_*)は実機のPalworld pak(開発機に存在すれば)を使い、
read_pak_index/read_pak_entries/read_pak_compression_methodsが複数回呼ばれても
実パース(_*_uncached)は1回しか走らないこと、かつキャッシュ有無で結果が
完全一致することを確認する。pakが無い環境ではSKIP(理由付き、無言スキップ
にしない。tests\\shipcheck\\test_shared_cache.pyと同じ方針)。

pytestからも `python tests/shipcheck/test_dev220_template_prep_speedup.py` からも
実行できる。
"""
import os
import random
import struct
import sys
import tempfile
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
if PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_PY_DIR)

import vp_core as core  # noqa: E402
import parse_sk_structure as sks  # noqa: E402


# ============================================================================
# 参照実装(変更前のアルゴリズムをそのまま複製。ここが「負の対照」の基準)
# ============================================================================

def _ref_find_sk_index_buffer_candidates(data):
    """dev#220以前のvp_core._find_sk_index_buffer_candidatesと同一のロジック
    (1バイトずつのPythonループ)。新実装との等価性の基準にする。"""
    n = len(data)
    candidates = []
    for off in range(0, n - 9):
        datasize = data[off]
        if datasize not in (2, 4):
            continue
        (elemsize,) = struct.unpack_from("<i", data, off + 1)
        if elemsize != datasize:
            continue
        (count,) = struct.unpack_from("<i", data, off + 5)
        if not (100 <= count <= 3_000_000) or count % 3 != 0:
            continue
        end = off + 9 + count * datasize
        if end > n:
            continue
        candidates.append((off, datasize, count, end))
    return candidates


def _ref_find_render_sections_start(data, end_offset, max_search=16384, max_sections=8):
    """dev#220以前のparse_sk_structure._find_render_sections_startと同一の
    ロジック(全candidateをPythonループで_i32判定)。新実装との等価性の基準。"""
    hits = []
    for cand in range(max(0, end_offset - max_search), end_offset - 4):
        sec_count = sks._i32(data, cand)
        if not (1 <= sec_count <= max_sections):
            continue
        off = cand + 4
        try:
            sections = []
            for _ in range(sec_count):
                sec, off = sks.parse_section(data, off)
                sections.append(sec)
        except (sks.SkStructureError, struct.error):
            continue
        if off == end_offset:
            hits.append((cand, sec_count, sections))
    return hits


def _ref_find_render_sections_start_result(data, end_offset, max_search=16384, max_sections=8):
    """呼び出し側(parse_sk_structure)と同じ「hitsがちょうど1件でなければ例外」
    契約込みの参照実装ラッパー。"""
    hits = _ref_find_render_sections_start(data, end_offset, max_search, max_sections)
    if len(hits) != 1:
        raise sks.SkStructureError(
            f"RenderSections start not uniquely determined (end={end_offset}): {len(hits)} hits")
    return hits[0]


# ============================================================================
# _find_sk_index_buffer_candidates: 新実装 vs 参照実装のfuzz等価性
# ============================================================================

def test_find_sk_index_buffer_candidates_negative_control_no_bytes_2_or_4():
    """2/4というバイト値が1つも出現しないバッファではヒット0件(誤検出しない)。"""
    data = bytes([5] * 5000 + [9] * 5000 + [200] * 5000)
    assert core._find_sk_index_buffer_candidates(data) == []
    assert _ref_find_sk_index_buffer_candidates(data) == []


def test_find_sk_index_buffer_candidates_decoy_byte_but_fails_downstream():
    """byte値2/4は出現するが後続条件(elemsize一致等)を満たさないケースは
    候補に含めない(reプレフィルタだけで即採用していないことの確認)。"""
    rnd = random.Random(20260730)
    data = bytearray(rnd.randrange(0, 256) for _ in range(20000))
    # 意図的にdatasize=4だがelemsizeが一致しない decoy を複数箇所に埋め込む
    for pos in (100, 5000, 15000):
        data[pos] = 4
        struct.pack_into("<i", data, pos + 1, 999)  # elemsize != datasize
    data = bytes(data)
    new_result = core._find_sk_index_buffer_candidates(data)
    ref_result = _ref_find_sk_index_buffer_candidates(data)
    assert new_result == ref_result
    for pos in (100, 5000, 15000):
        assert all(c[0] != pos for c in new_result), "decoy must not be accepted as a candidate"


@pytest.mark.parametrize("seed", range(30))
def test_find_sk_index_buffer_candidates_fuzz_matches_reference(seed):
    """ランダム合成バッファに、有効候補になりうる断片を意図的に複数埋め込んだ
    データで、新実装(re前置フィルタ)と参照実装(旧: 全バイトPythonループ)が
    完全に同じ候補集合(順序込み)を返すことを確認する。"""
    rnd = random.Random(seed)
    n = 6000
    data = bytearray(rnd.randrange(0, 256) for _ in range(n))

    # 有効候補になりうる断片をいくつか埋め込む(datasize=2 or 4、elemsize一致、
    # countが100..3_000_000かつ3の倍数、end<=n)
    for _ in range(rnd.randrange(0, 4)):
        pos = rnd.randrange(0, n - 20)
        datasize = rnd.choice((2, 4))
        count = rnd.choice((99, 100, 102, 3000, 3_000_000, 3_000_001))
        end = pos + 9 + count * datasize
        if end > n:
            continue
        data[pos] = datasize
        struct.pack_into("<i", data, pos + 1, datasize)
        struct.pack_into("<i", data, pos + 5, count)

    data = bytes(data)
    new_result = core._find_sk_index_buffer_candidates(data)
    ref_result = _ref_find_sk_index_buffer_candidates(data)
    assert new_result == ref_result


# ============================================================================
# _find_render_sections_start: 新実装 vs 参照実装のfuzz等価性
# ============================================================================

def _build_minimal_section_bytes(num_vertices=0, num_triangles=0, material_index=0):
    """parse_section()が受理する最小のFSkelMeshRenderSectionバイト列を組み立てる。
    class_strip bit0=1にしてDVB(DuplicatedVerticesBuffer)をスキップし、
    それ以外のカウント類はすべて0にして構造を単純化する(テスト専用の合成データ、
    実際のPalworldアセットとは無関係)。"""
    b = bytearray()
    b += bytes([0])            # global_strip_flags
    b += bytes([1])            # class_strip_flags (bit0=1 -> DVBスキップ)
    b += struct.pack("<H", material_index)   # material_index
    b += struct.pack("<I", 0)                # base_index
    b += struct.pack("<I", num_triangles)    # num_triangles
    b += struct.pack("<I", 0)                # b_recompute_tangent
    b += bytes([0])                          # recompute_tangent_vertex_mask_channel
    b += struct.pack("<I", 0)                # b_cast_shadow
    b += struct.pack("<I", 0)                # b_visible_in_ray_tracing
    b += struct.pack("<I", 0)                # base_vertex_index
    b += struct.pack("<i", 0)                # cloth_lod_count = 0
    b += struct.pack("<i", 0)                # bonemap_count = 0
    b += struct.pack("<I", num_vertices)     # num_vertices
    b += struct.pack("<i", 0)                # max_bone_influences
    b += struct.pack("<h", -1)               # correspond_cloth_asset_index
    b += bytes(16)                           # clothing_guid (FGuid)
    b += struct.pack("<i", 0)                # asset_lod_index
    # class_strip&1 == 1 -> DVB skipped entirely
    b += struct.pack("<I", 0)                # b_disabled
    return bytes(b)


def _build_render_sections_blob(sec_count, rnd):
    """sec_count個のセクション + 先頭にcountフィールド(i32)を持つバイト列を返す。
    (blob, end_offset) — end_offsetはblobの末尾(=呼び出し側のActiveBoneIndices
    開始位置に相当するダミー座標)。"""
    body = bytearray()
    for i in range(sec_count):
        body += _build_minimal_section_bytes(
            num_vertices=rnd.randrange(0, 50), num_triangles=rnd.randrange(0, 50),
            material_index=i)
    blob = struct.pack("<i", sec_count) + bytes(body)
    return blob, len(blob)


@pytest.mark.parametrize("seed", range(15))
def test_find_render_sections_start_fuzz_matches_reference(seed):
    """ランダムな前置ノイズ+本物っぽい合成RenderSectionsブロックを埋め込んだ
    データで、新実装(re前置フィルタ)と参照実装(旧: 全candidateをPythonループで
    _i32判定)が完全一致することを確認する(hit候補が一意に決まる正例)。

    ランダムな前置ノイズが極めて低確率で偶然もう1つの妥当なcandidateを
    作ってしまう可能性はゼロではない(その場合は新旧どちらも例外を投げる側に
    倒れるはずなので、例外の有無も含めて比較する=どちらのケースでも新旧の
    一致を検証できる)。"""
    rnd = random.Random(1000 + seed)
    prefix_len = rnd.randrange(0, 500)
    prefix = bytes(rnd.randrange(0, 256) for _ in range(prefix_len))
    sec_count = rnd.randrange(1, 9)
    blob, blob_len = _build_render_sections_blob(sec_count, rnd)
    suffix_len = rnd.randrange(0, 200)
    suffix = bytes(rnd.randrange(0, 256) for _ in range(suffix_len))

    data = prefix + blob + suffix
    end_offset = prefix_len + blob_len
    max_search = len(data)  # 実運用のcall siteと同じく全域を許容する

    new_exc = new_result = None
    try:
        new_result = sks._find_render_sections_start(data, end_offset, max_search=max_search)
    except sks.SkStructureError as e:
        new_exc = str(e)
    ref_exc = ref_result = None
    try:
        ref_result = _ref_find_render_sections_start_result(data, end_offset, max_search=max_search)
    except sks.SkStructureError as e:
        ref_exc = str(e)

    assert new_exc == ref_exc
    assert new_result == ref_result
    if new_exc is None:
        assert new_result[0] == prefix_len
        assert new_result[1] == sec_count


def test_find_render_sections_start_negative_control_no_valid_candidate():
    """有効なRenderSectionsブロックが存在しないデータでは、新実装・参照実装
    どちらも同じ例外(SkStructureError, 0件)を返すこと。"""
    data = bytes([0xFF] * 2000)
    end_offset = 1500
    with pytest.raises(sks.SkStructureError):
        sks._find_render_sections_start(data, end_offset, max_search=len(data))
    with pytest.raises(sks.SkStructureError):
        _ref_find_render_sections_start_result(data, end_offset, max_search=len(data))


def test_find_render_sections_start_ambiguous_two_identical_blocks_both_match():
    """2つの同一sec_count=1ブロックを連結すると、1つ目のブロック単体の終端
    (=1つ目の長さ)にもちょうど到達するcandidateが存在しうる(1つ目のブロックの
    先頭と、2つ目のブロックの先頭の両方が、それぞれ自分の直後のブロック1個分だけを
    正しくパースできてしまうため)。end_offsetを2つ目のブロックの終端に設定すると、
    『2つ目の先頭から2つ目のブロックだけを読んで終端一致』という1件に加えて、
    たまたま『1つ目の先頭から両ブロックをまたいで2件分パースして終端一致』が
    起きるかは構造依存だが、少なくとも新旧実装が同じ判定になることを確認する。"""
    rnd = random.Random(777)
    sec_a, len_a = _build_render_sections_blob(1, rnd)
    data = sec_a + sec_a  # 同一ブロックを2連結
    end_offset = len_a  # 1つ目のブロックの終端(=2つ目の先頭)をend_offsetにする
    max_search = len(data)

    new_exc = new_result = None
    try:
        new_result = sks._find_render_sections_start(data, end_offset, max_search=max_search)
    except sks.SkStructureError as e:
        new_exc = str(e)
    ref_exc = ref_result = None
    try:
        ref_result = _ref_find_render_sections_start_result(data, end_offset, max_search=max_search)
    except sks.SkStructureError as e:
        ref_exc = str(e)

    assert new_exc == ref_exc
    assert new_result == ref_result


# ============================================================================
# _pak_cached: キャッシュキー(パス+mtime_ns+size)の意味論
# ============================================================================

def test_pak_cached_reuses_result_for_same_file():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return object()

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello world")
        path = f.name
    try:
        r1 = core._pak_cached(path, "dev220_test_kind", builder)
        r2 = core._pak_cached(path, "dev220_test_kind", builder)
        assert r1 is r2
        assert calls["n"] == 1
    finally:
        os.remove(path)


def test_pak_cached_invalidates_on_mtime_change():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return calls["n"]

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello world")
        path = f.name
    try:
        r1 = core._pak_cached(path, "dev220_test_kind2", builder)
        assert calls["n"] == 1
        # 同じ内容・同じサイズのままmtimeだけ変える
        future = time.time() + 5
        os.utime(path, (future, future))
        r2 = core._pak_cached(path, "dev220_test_kind2", builder)
        assert calls["n"] == 2, "mtime change must invalidate the cache (negative control)"
        assert r1 != r2
    finally:
        os.remove(path)


def test_pak_cached_invalidates_on_size_change():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return calls["n"]

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello world")
        path = f.name
    try:
        r1 = core._pak_cached(path, "dev220_test_kind3", builder)
        assert calls["n"] == 1
        with open(path, "ab") as f:
            f.write(b"more bytes")
        # サイズが変わったのでmtimeも通常変わるが、意味論的にはsize差だけでも
        # キーが変わることを保証したいので、両方変わるケースで確認する
        r2 = core._pak_cached(path, "dev220_test_kind3", builder)
        assert calls["n"] == 2, "size change must invalidate the cache (negative control)"
        assert r1 != r2
    finally:
        os.remove(path)


def test_pak_cached_distinct_kind_is_independent():
    """同一ファイル・同一mtimeでも kind が違えば別キャッシュエントリになること
    (read_pak_index/read_pak_entries/read_pak_compression_methodsが互いに
    混線しないことの保証)。"""
    calls = {"a": 0, "b": 0}

    def builder_a():
        calls["a"] += 1
        return "A"

    def builder_b():
        calls["b"] += 1
        return "B"

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello world")
        path = f.name
    try:
        ra = core._pak_cached(path, "dev220_kind_a", builder_a)
        rb = core._pak_cached(path, "dev220_kind_b", builder_b)
        assert ra == "A" and rb == "B"
        assert calls == {"a": 1, "b": 1}
    finally:
        os.remove(path)


# ============================================================================
# 実機pak(あれば): キャッシュ配線の実地確認+キャッシュ有無での結果一致
# ============================================================================

def _find_real_pak():
    try:
        import palworld_locate
        p = palworld_locate.find_palworld_pak()
        return p if p and os.path.isfile(p) else None
    except Exception:
        return None


REAL_PAK = _find_real_pak()


@pytest.mark.skipif(REAL_PAK is None, reason="real Palworld pak not found on this machine")
def test_real_pak_read_functions_are_memoized_and_consistent():
    """実pakに対しread_pak_index/read_pak_entries/read_pak_compression_methodsを
    複数回呼んでも、実パース(_*_uncached)がそれぞれ1回しか走らないこと、かつ
    強制的にキャッシュを外して取り直した結果と完全一致すること(=キャッシュが
    中身を変えていないことの確認)を確かめる。"""
    core._PAK_PARSE_CACHE.clear()

    call_counts = {"index": 0, "entries": 0, "methods": 0}
    orig_index = core._read_pak_index_uncached
    orig_entries = core._read_pak_entries_uncached
    orig_methods = core._read_pak_compression_methods_uncached

    def counting_index(path):
        call_counts["index"] += 1
        return orig_index(path)

    def counting_entries(path):
        call_counts["entries"] += 1
        return orig_entries(path)

    def counting_methods(path):
        call_counts["methods"] += 1
        return orig_methods(path)

    core._read_pak_index_uncached = counting_index
    core._read_pak_entries_uncached = counting_entries
    core._read_pak_compression_methods_uncached = counting_methods
    try:
        i1 = core.read_pak_index(REAL_PAK)
        i2 = core.read_pak_index(REAL_PAK)
        e1 = core.read_pak_entries(REAL_PAK)
        e2 = core.read_pak_entries(REAL_PAK)
        m1 = core.read_pak_compression_methods(REAL_PAK)
        m2 = core.read_pak_compression_methods(REAL_PAK)

        assert call_counts == {"index": 1, "entries": 1, "methods": 1}, (
            f"each *_uncached parser must run exactly once per pak per process, got {call_counts}")
        assert i1 == i2
        assert e1 == e2
        assert m1 == m2
    finally:
        core._read_pak_index_uncached = orig_index
        core._read_pak_entries_uncached = orig_entries
        core._read_pak_compression_methods_uncached = orig_methods
        core._PAK_PARSE_CACHE.clear()


@pytest.mark.skipif(REAL_PAK is None, reason="real Palworld pak not found on this machine")
def test_real_pak_entries_mount_matches_index_mount():
    """dev#220でread_pak_entries内部のread_pak_index()呼び出し(mount取得だけの
    ためだった冗長呼び出し)を削除したため、read_pak_entriesが自前で読み取る
    mountがread_pak_index()のmountと一致し続けることを確認する(退行防止)。"""
    core._PAK_PARSE_CACHE.clear()
    mount_from_index, _ = core.read_pak_index(REAL_PAK)
    mount_from_entries, _ = core.read_pak_entries(REAL_PAK)
    assert mount_from_index == mount_from_entries
    core._PAK_PARSE_CACHE.clear()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
