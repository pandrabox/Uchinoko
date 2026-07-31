"""U2 T1: LODヘッダ〜RenderSections〜StreamedData先頭までの前方(forward)パーサ。

UE5.1ソース(Engine/Private/SkeletalMeshLODRenderData.cpp,
FSkeletalMeshLODRenderData::Serialize / operator<<(FArchive&, FSkelMeshRenderSection&))
通りのフィールド順・サイズで前から完全にバイトを消費する。ソース確認済みの要点:
  - FArchive::operator<<(bool&) はcooked(非エディタ)ビルドでは4バイト(uint32)
    (Core/Public/Serialization/Archive.h 1432-1462)
  - FStripDataFlags = GlobalStripFlags(uint8) + ClassStripFlags(uint8) = 2バイト
    (Engine/Public/EngineUtils.h 832-837)
  - FSkelMeshRenderSection::operator<< は先頭で「セクション自身の」
    FStripDataFlags(2B)を読む(LODヘッダのStripFlagsとは別物)
  - FClothingSectionData = FGuid(16B) + AssetLodIndex(int32,4B) = 20B
  - DuplicatedVerticesBuffer はセクション内(ClothingDataの直後、bDisabledの直前)
    でシリアライズされる。ClassStripFlags のbit0(DuplicatedVertices=1)が
    立っていれば省略。DupVertData(TArray<uint32>)+DupVertIndexData
    (TArray<FIndexLengthPair>、8B/要素)の2本、どちらも通常のTArray operator<<
    (カウントi32 + 生バイト。BulkSerializeのelement-size接頭辞は付かない
    — Ar<<Data.DupVertDataはTResourceArrayのoperator<<経由でTArray::operator<<
    に委譲されるため。Array.h 1233-1263 / DynamicRHIResourceArray.h 124-137)

RequiredBones/RenderSections境界は「前方シミュレーションが既知の終端
(ActiveBoneIndices開始位置、S2で確定済みのIndexBuffer位置から逆算)に
過不足なく一致する」ことで一意に確定する(値が食い違えば即エラーになる
フィールドモデルなので、誤ったcandidateはほぼ確実にどこかで例外か
終端不一致になる)。
"""
import os
import re
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core  # noqa: E402  (read-only import, Phase1コード変更禁止)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
ROOT = r"C:\P\Work\DiveToPalworld\work\toto\build\pak_extract\Player\Outfit"


class SkStructureError(RuntimeError):
    pass


def _u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


def _i16(data, off):
    return struct.unpack_from('<h', data, off)[0]


def _u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def _i32(data, off):
    return struct.unpack_from('<i', data, off)[0]


def _find_tarray_u16_end(data, end_offset, max_search=4096, max_count=1000):
    """TArray<uint16>(カウントi32接頭辞)がちょうどend_offsetで終わる位置を
    後方探索する(RequiredBones/ActiveBoneIndices共通の汎用ロケータ)。"""
    for off in range(end_offset - 4, max(0, end_offset - max_search), -1):
        cnt = _i32(data, off)
        if 0 <= cnt <= max_count and off + 4 + cnt * 2 == end_offset:
            return off, cnt
    raise SkStructureError(f"TArray<uint16> ending at {end_offset} not found")


def parse_section(data, off):
    """FSkelMeshRenderSection::operator<< をソース順に前方パースする。
    戻り値: (フィールド辞書, 消費後オフセット)"""
    start = off
    global_strip = data[off]
    class_strip = data[off + 1]
    off += 2

    material_index = _u16(data, off); off += 2
    base_index = _u32(data, off); off += 4
    num_triangles = _u32(data, off); off += 4

    b_recompute_tangent = _u32(data, off); off += 4
    if b_recompute_tangent not in (0, 1):
        raise SkStructureError(f"bRecomputeTangent not bool @ {off - 4}: {b_recompute_tangent}")

    rtvm_channel = data[off]; off += 1

    b_cast_shadow = _u32(data, off); off += 4
    if b_cast_shadow not in (0, 1):
        raise SkStructureError(f"bCastShadow not bool @ {off - 4}: {b_cast_shadow}")

    b_visible_rt = _u32(data, off); off += 4
    if b_visible_rt not in (0, 1):
        raise SkStructureError(f"bVisibleInRayTracing not bool @ {off - 4}: {b_visible_rt}")

    base_vertex_index = _u32(data, off); off += 4

    # ClothMappingDataLODs: TArray<TArray<FMeshToMeshVertData>>。非クロス衣装は空。
    cloth_lod_count = _i32(data, off); off += 4
    if not (0 <= cloth_lod_count <= 8):
        raise SkStructureError(f"ClothMappingDataLODs count implausible @ {off - 4}: {cloth_lod_count}")
    for _ in range(cloth_lod_count):
        inner_count = _i32(data, off); off += 4
        if inner_count != 0:
            # FMeshToMeshVertDataの個別要素パースは非クロスメッシュの範囲外
            raise SkStructureError(
                f"cloth mapping inner data not supported (inner_count={inner_count} @ {off - 4})")

    bonemap_count_off = off
    bonemap_count = _i32(data, off); off += 4
    if not (0 <= bonemap_count <= 500):
        raise SkStructureError(f"BoneMap count implausible @ {off - 4}: {bonemap_count}")
    bonemap_data_off = off
    bone_map = struct.unpack_from(f'<{bonemap_count}H', data, off)
    off += bonemap_count * 2

    num_vertices_off = off
    num_vertices = _u32(data, off); off += 4
    max_bone_influences = _i32(data, off); off += 4
    correspond_cloth_asset_index = _i16(data, off); off += 2

    clothing_guid_off = off
    off += 16  # FGuid
    asset_lod_index = _i32(data, off); off += 4

    dup_vert_count = None
    dup_vert_index_count = None
    dvb_off = off
    dup_vert_data_off = None
    dup_vert_index_count_off = None
    dup_vert_index_data_off = None
    if not (class_strip & 1):
        dup_vert_count = _i32(data, off); off += 4
        dup_vert_data_off = off
        off += dup_vert_count * 4
        dup_vert_index_count_off = off
        dup_vert_index_count = _i32(data, off); off += 4
        dup_vert_index_data_off = off
        if dup_vert_index_count != num_vertices:
            raise SkStructureError(
                f"DVB DupVertIndexData count {dup_vert_index_count} != section NumVertices "
                f"{num_vertices} (section @ {start})")
        off += dup_vert_index_count * 8

    b_disabled_off = off
    b_disabled = _u32(data, off); off += 4
    if b_disabled not in (0, 1):
        raise SkStructureError(f"bDisabled not bool @ {off - 4}: {b_disabled}")

    return {
        'start': start,
        'end': off,
        'global_strip_flags': global_strip,
        'class_strip_flags': class_strip,
        'material_index': material_index,
        'base_index': base_index,
        'num_triangles': num_triangles,
        'b_recompute_tangent': bool(b_recompute_tangent),
        'recompute_tangent_vertex_mask_channel': rtvm_channel,
        'b_cast_shadow': bool(b_cast_shadow),
        'b_visible_in_ray_tracing': bool(b_visible_rt),
        'base_vertex_index': base_vertex_index,
        'cloth_mapping_lod_count': cloth_lod_count,
        'bone_map_offset': bonemap_count_off,
        'bone_map_data_offset': bonemap_data_off,
        'bone_map': list(bone_map),
        'num_vertices_offset': num_vertices_off,
        'num_vertices': num_vertices,
        'max_bone_influences': max_bone_influences,
        'correspond_cloth_asset_index': correspond_cloth_asset_index,
        'clothing_guid_offset': clothing_guid_off,
        'clothing_asset_lod_index': asset_lod_index,
        'dvb_offset': dvb_off,
        'dvb_present': dup_vert_count is not None,
        'dvb_dup_vert_count': dup_vert_count,
        'dvb_dup_vert_data_offset': dup_vert_data_off,
        'dvb_dup_vert_index_count_offset': dup_vert_index_count_off,
        'dvb_dup_vert_index_count': dup_vert_index_count,
        'dvb_dup_vert_index_data_offset': dup_vert_index_data_off,
        'b_disabled_offset': b_disabled_off,
        'b_disabled': bool(b_disabled),
    }, off


# dev#220(2026-07-30): 元実装はcand候補範囲の全バイト位置に対してPythonループで
# _i32(data, cand)を呼び「1<=sec_count<=8か」を判定していた(実測: SK 1件あたり
# 平均約80ms、114件で9秒超。max_search=ab_offで呼ばれるためcandの範囲が
# ファイル先頭近くまで及ぶことがある)。この判定は「リトルエンディアンint32の
# 値が1〜8」という条件そのもので、バイト列としては「先頭byteが0x01〜0x08、
# 続く3byteが0x00」という固定パターンに等しい。re(Cで実装)でこのバイト
# パターンの出現位置だけを先に列挙し、後段の重いparse_section検証はヒットした
# 位置だけに絞る。列挙されるcandidate集合・走査順(昇順)は元のforループと
# 完全に同一(同じcand範囲を同じ条件で走査しているだけ)。
_SEC_COUNT_RE = re.compile(rb"[\x01-\x08]\x00\x00\x00")


def _find_render_sections_start(data, end_offset, max_search=16384, max_sections=8):
    """RenderSectionsのcountフィールド位置を、そこからsec_count個のセクションを
    前方パースした終端がちょうどend_offset(=ActiveBoneIndices開始位置)と
    一致するcandidateとして一意に特定する。

    U18実測: 真のバニラ衣装SK(docs\\REPORT_U18_2026-07-23.md参照)はMaterialIndex
    0/1(body/parka)以外に追加の装飾パーツ用マテリアルを持つ個体があり、
    セクション数が旧コーパスの前提(常に2、上限4)を超える(実測: Plastic002系で
    5セクション)。上限をLOD count同様の8へ緩和する(parse_sk_full.pyの
    `1 <= lod_count <= 8`との整合)。"""
    assert max_sections <= 8, (
        "max_sections>8 changes the byte pattern in _SEC_COUNT_RE; "
        "regenerate the regex if this bound is ever raised")
    search_start = max(0, end_offset - max_search)
    search_stop = end_offset - 4  # exclusive、元のrange(...,end_offset-4)と同じ上限
    hits = []
    if search_stop > search_start:
        # finditerのendposは「一致がstring[:endpos]に収まる」条件(match.end()<=endpos)。
        # candの上限をsearch_stop-1(=元のrangeの最終値)にしたいのでendpos=search_stop+3
        # (パターン長4: match.end()=cand+4 <= search_stop+3 <=> cand <= search_stop-1)。
        endpos = search_stop + 3
        for m in _SEC_COUNT_RE.finditer(data, search_start, endpos):
            cand = m.start()
            sec_count = _i32(data, cand)
            off = cand + 4
            try:
                sections = []
                for _ in range(sec_count):
                    sec, off = parse_section(data, off)
                    sections.append(sec)
            except (SkStructureError, struct.error):
                continue
            if off == end_offset:
                hits.append((cand, sec_count, sections))
    if len(hits) != 1:
        raise SkStructureError(
            f"RenderSections start not uniquely determined (end={end_offset}): {len(hits)} hits")
    return hits[0]


def parse_sk_structure(uexp_path, uasset_path):
    with open(uexp_path, 'rb') as f:
        data = f.read()

    r = vp_core.parse_skeletalmesh_buffers(data)
    numv = r['num_vertices']
    idx_off = r['index_buffer']['offset']
    idx_count = r['index_buffer']['count']
    total_triangles = idx_count // 3

    bones = vp_core.load_refskel(uasset_path)
    n_bones = len(bones)

    # StreamedData側アンカー(S2で確定済み、P2報告の連鎖):
    # ... BuffersSize(u32) -> StreamedData自身のFStripDataFlags(2B) -> IndexBuffer
    streamed_strip_off = idx_off - 2
    buffers_size_off = idx_off - 6
    buffers_size = _u32(data, buffers_size_off)

    # ActiveBoneIndices: TArray<uint16>、buffers_size_offでちょうど終わる
    ab_off, ab_count = _find_tarray_u16_end(data, buffers_size_off, max_search=4096, max_count=1000)
    ab_vals = struct.unpack_from(f'<{ab_count}H', data, ab_off + 4)

    # RenderSections: 前方シミュレーションでab_offにちょうど一致するcountフィールドを探す
    # (DVB込みで数十万バイトに及ぶため、探索窓はindex_bufferまでの全域を許容する)
    sec_count_off, sec_count, sections = _find_render_sections_start(data, ab_off, max_search=ab_off)

    # RequiredBones: TArray<uint16>、sec_count_offでちょうど終わる
    rb_off, rb_count = _find_tarray_u16_end(data, sec_count_off, max_search=4096, max_count=500)
    rb_vals = struct.unpack_from(f'<{rb_count}H', data, rb_off + 4)
    if not all(v < n_bones for v in rb_vals):
        raise SkStructureError("RequiredBones values out of bone range")

    # LODヘッダ(固定長、RequiredBonesの直前): FStripDataFlags(2) + bIsLODCookedOut(4,bool) + bInlined(4,bool)
    b_inlined_off = rb_off - 4
    b_lod_cooked_out_off = b_inlined_off - 4
    strip1_off = b_lod_cooked_out_off - 2
    b_inlined = _u32(data, b_inlined_off)
    b_lod_cooked_out = _u32(data, b_lod_cooked_out_off)
    if b_inlined not in (0, 1) or b_lod_cooked_out not in (0, 1):
        raise SkStructureError("LOD header bIsLODCookedOut/bInlined not bool")

    total_sec_tri = sum(s['num_triangles'] for s in sections)
    total_sec_vtx = sum(s['num_vertices'] for s in sections)

    return {
        'num_vertices': numv,
        'total_triangles': total_triangles,
        'num_sections': sec_count,
        'sections': sections,
        'n_bones': n_bones,
        'required_bones': list(rb_vals),
        'required_bones_offset': rb_off,
        'active_bone_indices': list(ab_vals),
        'active_bone_indices_offset': ab_off,
        'render_sections_count_offset': sec_count_off,
        'buffers_size': buffers_size,
        'buffers_size_offset': buffers_size_off,
        'streamed_strip_offset': streamed_strip_off,
        'strip1_offset': strip1_off,
        'b_lod_cooked_out': bool(b_lod_cooked_out),
        'b_inlined': bool(b_inlined),
        'total_section_triangles': total_sec_tri,
        'total_section_vertices': total_sec_vtx,
        'tri_match': total_sec_tri == total_triangles,
        'vtx_match': total_sec_vtx == numv,
        'index_buffer_offset': idx_off,
    }


def verify(uexp_path, uasset_path, verbose=True):
    if verbose:
        print(f'--- {os.path.basename(uexp_path)} ---')
    s = parse_sk_structure(uexp_path, uasset_path)
    errors = []
    if s['num_sections'] == 0:
        errors.append("no sections")
    if not s['tri_match']:
        errors.append(f"tri mismatch: sections={s['total_section_triangles']} vs total={s['total_triangles']}")
    if not s['vtx_match']:
        errors.append(f"vtx mismatch: sections={s['total_section_vertices']} vs total={s['num_vertices']}")
    for i, sec in enumerate(s['sections']):
        if not all(v < s['n_bones'] for v in sec['bone_map']):
            errors.append(f"sec[{i}] BoneMap has value >= n_bones({s['n_bones']})")
    if verbose:
        print(f"  nVtx={s['num_vertices']} tri={s['total_triangles']} nSec={s['num_sections']} "
              f"BuffersSize={s['buffers_size']}")
        print(f"  RequiredBones@{s['required_bones_offset']}({len(s['required_bones'])}) "
              f"ActiveBoneIndices@{s['active_bone_indices_offset']}({len(s['active_bone_indices'])})")
        for i, sec in enumerate(s['sections']):
            print(f"  sec[{i}]: mat={sec['material_index']} baseIdx={sec['base_index']} "
                  f"numTri={sec['num_triangles']} bVtx={sec['base_vertex_index']} "
                  f"nVtx={sec['num_vertices']} BM@{sec['bone_map_offset']}(n={len(sec['bone_map'])}) "
                  f"dvb={sec['dvb_dup_vert_count']}/{sec['dvb_dup_vert_index_count']} "
                  f"end={sec['end']}")
        print(f"  errors={errors}")
    return len(errors) == 0


if __name__ == '__main__':
    uexp = os.path.join(DATA_DIR, 'SK_Player_Female_Outfit_Bronze001.uexp')
    uasset = os.path.join(DATA_DIR, 'SK_Player_Female_Outfit_Bronze001.uasset')
    ok = verify(uexp, uasset)
    print(f'  => {"OK" if ok else "FAIL"}')

    print('\n=== 60-body ===')
    all_ok = True
    n = 0
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if not fn.lower().endswith('.uexp'):
                continue
            uexp = os.path.join(dirpath, fn)
            uasset = uexp[:-5] + '.uasset'
            if not os.path.exists(uasset):
                continue
            try:
                ok = verify(uexp, uasset, verbose=False)
            except Exception as e:
                ok = False
                print(f'  {fn}: EXCEPTION {e}')
            if not ok:
                all_ok = False
                print(f'  {fn}: FAIL')
            n += 1
    print(f'\n{n} files: {"PASS" if (all_ok and n > 0) else "FAIL"}')
    sys.exit(0 if (all_ok and n > 0) else 1)
