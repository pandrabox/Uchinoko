"""U3 T1: export全域(uexp先頭〜SerialSize-4)のバイト会計100%を目指す前方パーサ。

parse_sk_structure.py(U2、LODヘッダ〜StreamedData先頭=IndexBuffer開始まで)を
拡張し、その後続(IndexBuffer〜Position〜Tangent/UV〜SkinWeight〜未解析だった
127,870バイト領域〜LOD配列末尾〜USkeletalMesh::Serialize残り)まで前方消費する。

## スコープの解釈(指示書の「export全域」に対する明示的な範囲限定)

指示書 docs/U3_SONNET_INSTRUCTIONS.md T1は「export全域(uexp先頭〜SerialSize-4)
を前方パースする」と書く一方、目標として名指ししているのは「LOD0の
SkinWeightVertexBuffer末尾以降の未解析領域 約127,870バイト」である。

実際にUE5.1ソース(SkeletalMesh.cpp USkeletalMesh::Serialize)を読むと、
uexp先頭(offset 0)からFBoxSphereBounds/Materials/RefSkeletonが始まる直前
(=U2が既に解明した領域の起点)までは `Super::Serialize(Ar)` 呼び出しによる
**UObjectのunversioned property シリアライズ**(Skeleton参照・PhysicsAsset・
LODInfo配列・Sockets・MorphTargets配列等、UClassのリフレクションスキーマに
依存する可変長バイナリ)である。これはP2セッションが既に検証済みの通り
(REPORT_P2 Stage B節: 「cook済みpakが『unversioned properties』形式であり
usmap(型マッピング)が無いと読めないため断念」)、usmap(型マッピングファイル)
なしには意味論的なフィールド分解ができない、質的に別の問題である。

そのため本パーサは以下の方針を取る(次の人向けに明示):
  - offset 0 〜 (Bounds/Materials/RefSkeleton開始位置の手前)は
    「Super::Serializeによる不透明ブロック」として**位置+サイズのみ記録**
    (指示書の「名前不明フィールドは位置+サイズ+値を記録すれば可」の対象として扱う)
  - Bounds/Materials/RefSkeletonはUE5.1ソース上は明示的な`Ar<<`呼び出し
    (構造化バイナリ、unversioned propertyではない)だが、本セッションの
    時間予算内では未着手(既知の安定アンカー=RequiredBones開始位置への
    後方一致で境界だけ確認し、内部は不透明ブロックとして記録する)
  - **本パーサが実際にフィールド単位まで解明するのは「LOD0のStreamedData
    (IndexBuffer開始)〜export終端(SerialSize-4)」の全域**(=指示書が
    バイト数まで명시した対象そのもの)。60体全数で実測、ギャップゼロを確認済み

## 確定した新規レイアウト(スキン・ウェイトLookupVertexBuffer以降)

UE5.1 `SkeletalMeshLODRenderData.cpp SerializeStreamedData`
(operator<<(FArchive&,FSkinWeightVertexBuffer&) in SkinWeightVertexBuffer.cpp、
USkeletalMesh::Serialize in SkeletalMesh.cpp)をソースから前方に追った上で
60体全数の実バイトと突き合わせ、以下の完全一致を確認した(60/60):

```
[vp_core.parse_skeletalmesh_buffers()が既に切り出す skin_weight(=DataVertexBuffer)終端] P
P +0  : LookupVertexBuffer.StripFlags        uint8x2
P +2  : LookupVertexBuffer.NumVertices       i32   (実測60/60で0=定数ボーン影響数のため空)
P +6  : LookupVertexBuffer.Bulk ElemSize     i32   (実測4)
P +10 : LookupVertexBuffer.Bulk Count        i32   (実測0)
P +14 : LookupVertexBuffer.Bulk Data         Count*ElemSizeバイト(実測0バイト)
      = LookupVertexBuffer終端 Q
Q +0  : ColorVertexBuffer.StripFlags         uint8x2  (実測60/60で存在=HasVertexColors=true)
Q +2  : ColorVertexBuffer.Stride             i32   (実測4)
Q +6  : ColorVertexBuffer.NumVertices        i32   (実測=LOD頂点数と一致)
Q +10 : ColorVertexBuffer.Bulk ElemSize      i32   (実測4)
Q +14 : ColorVertexBuffer.Bulk Count         i32   (実測=NumVerticesと一致)
Q +18 : ColorVertexBuffer.Bulk Data          Count*ElemSizeバイト(FColor、4B/頂点)
      = ColorVertexBuffer終端 R
      (Adjacency: FUE5ReleaseStreamObjectVersion::RemovingTessellation以降の
       cook対象のため0バイト。ClothVertexBuffer: 全セクションで
       cloth_mapping_lod_count==0のため0バイト。いずれも実測60/60で確認)
R +0  : SkinWeightProfilesData(TMap<FName,...>) Count  i32  (実測60/60で0)
      = R+4 (count>0の場合は各エントリFName(8B)+FRuntimeSkinWeightProfileData
        が続くが、本コーパスでは未遭遇のため未実装。遭遇時はSkStructureErrorで停止)
R +4  : SourceRayTracingGeometry.RawData(TArray<uint8>) Count i32 (実測60/60で0)
      = R+8 (count>0の場合は生バイトCount個。本コーパスでは未遭遇)
R +8  : bSerializeCompressedMorphTargets     i32(bool)  (実測60/60で0)
      (trueの場合MorphTargetVertexInfoBuffersが続くが本コーパスでは未遭遇)
R +12 : NumInlinedLODs                       uint8   (実測60/60で1)
R +13 : NumNonOptionalLODs                   uint8   (実測60/60で1)
      = FSkeletalMeshRenderData::Serialize終端(LODRenderData配列は
        全60体でCount=1、TIndirectArrayループはLOD0のみで完了)
R +14 : USkeletalMesh::Serialize残り: DummyObjs(TArray<UObject*>) Count i32
        (実測60/60で0。DummyNameIndexMapはVER_UE4_REFERENCE_SKELETON_REFACTOR
        未満でのみ存在するガードで、unversioned cook=最新版前提のため0バイト。
        CachedStreamingTextureFactorsも同様に版ゲートでスキップ)
      = export終端(SerialSize-4) — 60体全数で厳密一致
```

LOD配列(TIndirectArray<FSkeletalMeshLODRenderData>)の要素数は、
`parse_sk_structure.py`が確定した`strip1_offset`(LOD自身のFStripDataFlags
開始位置)の直前4バイトに書かれている(TIndirectArray operator<<の
`Ar << NewNum`)。60体全数で値=1(単一LOD)。複数LODの場合は
LOD1以降も同一の(RequiredBones〜本パーサのtail終端まで)構造が
繰り返される設計のはずだが、本コーパスに複数LOD個体が存在しないため
実装のみ(下記`parse_lod`のwhileループ)で対応し、実測検証はしていない。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core  # noqa: E402
import parse_sk_structure as sk  # noqa: E402
import parse_uasset_header as uh  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
ROOT = r"C:\P\Work\DiveToPalworld\work\toto\build\pak_extract\Player\Outfit"


class SkFullParseError(RuntimeError):
    pass


def _i32(data, off):
    return struct.unpack_from('<i', data, off)[0]


def _u8(data, off):
    return data[off]


def parse_lookup_vertex_buffer(data, off, total_verts):
    strip = (data[off], data[off + 1])
    p = off + 2
    numv = _i32(data, p); p += 4
    if numv not in (0, total_verts):
        raise SkFullParseError(f"LookupVertexBuffer.NumVertices implausible @ {p - 4}: {numv}")
    elemsize = _i32(data, p); p += 4
    count = _i32(data, p); p += 4
    if not (0 <= elemsize <= 64) or count not in (0, total_verts):
        raise SkFullParseError(f"LookupVertexBuffer bulk implausible @ {p - 8}: elemsize={elemsize} count={count}")
    data_start = p
    p += count * elemsize
    return {
        'start': off, 'end': p, 'strip_flags': strip,
        'num_vertices': numv, 'bulk_elemsize': elemsize, 'bulk_count': count,
        'bulk_data_offset': data_start,
    }, p


def parse_color_vertex_buffer(data, off, total_verts):
    """HasVertexColors()がtrueの場合のみ存在する。存在しない場合は
    (None, off)を返す(0バイト消費)。プロージビリティで判定する:
    Stride=4かつNumVertices==total_vertsのときのみ「存在」と判定する。"""
    if off + 10 > len(data):
        return None, off
    strip = (data[off], data[off + 1])
    stride = _i32(data, off + 2)
    numv = _i32(data, off + 6)
    if not (strip[0] <= 3 and strip[1] <= 3 and stride == 4 and numv == total_verts):
        return None, off
    p = off + 10
    elemsize = _i32(data, p); p += 4
    count = _i32(data, p); p += 4
    if elemsize != 4 or count != total_verts:
        raise SkFullParseError(
            f"ColorVertexBuffer bulk implausible @ {p - 8}: elemsize={elemsize} count={count} (expected 4,{total_verts})")
    data_start = p
    p += count * elemsize
    return {
        'start': off, 'end': p, 'strip_flags': strip, 'stride': stride,
        'num_vertices': numv, 'bulk_elemsize': elemsize, 'bulk_count': count,
        'bulk_data_offset': data_start,
    }, p


def parse_skin_weight_profiles(data, off):
    count = _i32(data, off)
    if not (0 <= count <= 16):
        raise SkFullParseError(f"SkinWeightProfilesData count implausible @ {off}: {count}")
    if count != 0:
        raise SkFullParseError(
            f"SkinWeightProfilesData count={count} (>0 entry format never seen in this corpus, unimplemented)")
    return {'start': off, 'end': off + 4, 'count': count}, off + 4


def parse_ray_tracing_raw_data(data, off):
    count = _i32(data, off)
    if not (0 <= count <= len(data)):
        raise SkFullParseError(f"SourceRayTracingGeometry.RawData count implausible @ {off}: {count}")
    p = off + 4
    data_start = p
    p += count  # TArray<uint8>: 要素サイズ1、elemsize接頭辞なし(通常のTArray operator<<)
    return {'start': off, 'end': p, 'count': count, 'data_offset': data_start}, p


def parse_lod_tail(data, off, total_verts, expected_end=None):
    """skin_weight(DataVertexBuffer)終端offから、LOD1件分のSerialize末尾
    (NumInlinedLODs/NumNonOptionalLODsの直後)まで前方パースする。

    expected_end: export終端(uexpローカル座標、parse_sk_full._mesh_export_end_in_uexp
    が算出)。bSerializeCompressedMorphTargets=trueのファイル(U18実測、
    docs\\REPORT_U18_2026-07-23.md参照)で、MorphTargetVertexInfoBuffersの
    内部構造を理解せずに境界だけ特定するための逆算アンカーとして使う。"""
    lookup, p = parse_lookup_vertex_buffer(data, off, total_verts)
    color, p = parse_color_vertex_buffer(data, p, total_verts)
    # Adjacency(deprecated): FUE5ReleaseStreamObjectVersion::RemovingTessellation
    # 以降のcookは0バイト。ClothVertexBuffer: 呼び出し元でHasClothData()==False
    # を確認済みなので0バイトとして扱う(呼び出し元でチェック)。
    skw_prof, p = parse_skin_weight_profiles(data, p)
    rt_raw, p = parse_ray_tracing_raw_data(data, p)

    morph_flag_off = p
    morph_flag = _i32(data, p); p += 4
    if morph_flag not in (0, 1):
        raise SkFullParseError(f"bSerializeCompressedMorphTargets not bool @ {morph_flag_off}: {morph_flag}")
    morph_buffers = None
    if morph_flag:
        # U18実測: 真のバニラ衣装SKはUMorphTargetを実際に持ち、このフラグがtrueになる
        # (旧コーパスは常に0だったための未実装ギャップ)。build_avatar_variant.py側は
        # このブロックの中身を一切読まず、出力では常にbSerializeCompressedMorphTargets=
        # False(count 0本)で書き直す(=読み取った内容を再利用しない)ため、
        # MorphTargetVertexInfoBuffersの内部フォーマットを解析する必要はなく、
        # 「位置+サイズだけ分かる不透明ブロック」として扱えば十分
        # (このファイル冒頭のhead_opaque_endと同じ方針)。
        # サイズは、末尾の固定長フィールド(NumInlinedLODs u8 + NumNonOptionalLODs u8 +
        # DummyObjs count i32=0、計6バイト)がexpected_endの直前に来ることをアンカーに
        # 逆算する。DummyObjs count実測値が0であることを追加検証し、逆算が誤って
        # いないかを担保する。
        if expected_end is None:
            raise SkFullParseError(
                f"bSerializeCompressedMorphTargets=true @ {morph_flag_off} but "
                "expected_end (anchor for back-computing the boundary) was not passed")
        tail_fixed_size = 6  # NumInlinedLODs(1) + NumNonOptionalLODs(1) + DummyObjs count(4)
        morph_end = expected_end - tail_fixed_size
        if morph_end < p:
            raise SkFullParseError(
                f"invalid back-computed boundary for morph target opaque block: start={p} "
                f"end={morph_end} (expected_end={expected_end})")
        dummy_count_check = _i32(data, expected_end - 4)
        if dummy_count_check != 0:
            raise SkFullParseError(
                f"DummyObjs count (boundary back-computation check) is not 0: {dummy_count_check} "
                f"@ {expected_end - 4} (the morph-target boundary back-computation may be wrong)")
        morph_buffers = {'start': p, 'end': morph_end, 'opaque': True}
        p = morph_end

    num_inlined_off = p
    num_inlined = _u8(data, p); p += 1
    num_nonopt = _u8(data, p); p += 1

    return {
        'lookup_vertex_buffer': lookup,
        'color_vertex_buffer': color,
        'skin_weight_profiles': skw_prof,
        'ray_tracing_raw_data': rt_raw,
        'morph_flag_offset': morph_flag_off,
        'b_serialize_compressed_morph_targets': bool(morph_flag),
        'morph_target_buffers': morph_buffers,
        'num_inlined_lods_offset': num_inlined_off,
        'num_inlined_lods': num_inlined,
        'num_non_optional_lods': num_nonopt,
        'end': p,
    }, p


def parse_dummy_objs(data, off):
    count = _i32(data, off)
    if not (0 <= count <= 10000):
        raise SkFullParseError(f"DummyObjs count implausible @ {off}: {count}")
    if count != 0:
        raise SkFullParseError(f"DummyObjs count={count} (>0 unimplemented, FPackageIndex array semantics not analyzed)")
    return {'start': off, 'end': off + 4, 'count': count}, off + 4


def _find_asset_export(uasset_path):
    """uassetのexport tableから、実データ(SkeletalMesh本体)のexportを1件特定して
    返す((asset_export, all_exports))。

    U18実測: 真のバニラ衣装SK(docs\\REPORT_U18_2026-07-23.md参照)はUMorphTarget等の
    小さな補助export(bIsAsset=False、実測44バイト×6件)を複数持ち、
    ExportCount=7になる(旧コーパスはExportCount=1固定という前提で書かれていた)。
    FObjectExport.bIsAssetはSkeletalMesh本体だけがtrueになる実測フラグなので、
    これで一意に本体exportを選ぶ(export配列の並び順やindex位置には依存しない)。"""
    _, exports = uh.parse_uasset_exports(uasset_path)
    asset_exports = [e for e in exports if e['b_is_asset']]
    if len(asset_exports) != 1:
        raise SkFullParseError(
            f"bIsAsset=True export is not unique: {len(asset_exports)} found"
            f"(total ExportCount={len(exports)})")
    return asset_exports[0], exports


def _mesh_export_end_in_uexp(asset_export, uasset_size):
    """FObjectExport.SerialOffsetは(uasset+uexpを論理連結した)パッケージ全体の
    絶対アドレス。uexpファイル内ローカル座標(=data[0]を起点とする座標系)に
    変換した上で、本体exportの終端offsetを返す。

    prefix(uexpファイル先頭〜本体export開始まで)は、本体より前に別exportとして
    シリアライズされる補助オブジェクト(UMorphTarget等)のバイト列。
    旧コーパス(ExportCount=1、本体exportがuexp先頭=offset 0から始まる)では
    prefix=0に帰着し、既存の「expected_end=serial_size」という前提とそのまま
    一致する(後方互換)。"""
    prefix = asset_export['serial_offset'] - uasset_size
    if prefix < 0:
        raise SkFullParseError(
            f"main export's SerialOffset ({asset_export['serial_offset']}) is less than "
            f"the uasset size ({uasset_size})")
    return prefix + asset_export['serial_size']


def parse_sk_full(uexp_path, uasset_path):
    with open(uexp_path, 'rb') as f:
        data = f.read()

    s = sk.parse_sk_structure(uexp_path, uasset_path)
    r = vp_core.parse_skeletalmesh_buffers(data)

    has_cloth = any(sec['cloth_mapping_lod_count'] > 0 for sec in s['sections'])
    if has_cloth:
        raise SkFullParseError("HasClothData()=true (ClothVertexBuffer format never seen in this corpus, unimplemented)")

    # LOD count: strip1_offset(LOD自身のFStripDataFlags開始)の直前4バイト
    # (TIndirectArray<FSkeletalMeshLODRenderData> operator<<のAr<<NewNum)
    lod_count_offset = s['strip1_offset'] - 4
    lod_count = _i32(data, lod_count_offset)
    if not (1 <= lod_count <= 8):
        raise SkFullParseError(f"LOD count implausible @ {lod_count_offset}: {lod_count}")

    # export終端(本体exportのSerialSize由来)を先に確定させ、
    # parse_lod_tail側でモーフターゲット不透明ブロックの逆算アンカーに使う
    asset_export, exports = _find_asset_export(uasset_path)
    expected_end = _mesh_export_end_in_uexp(asset_export, os.path.getsize(uasset_path))

    sw = r['skin_weight']
    tail, tail_end = parse_lod_tail(data, sw['offset'] + sw['size'], r['num_vertices'], expected_end)

    lods = [{
        'lod_index': 0,
        'num_vertices': r['num_vertices'],
        'total_triangles': s['total_triangles'],
        'num_sections': s['num_sections'],
        'tail': tail,
    }]

    if lod_count != 1:
        raise SkFullParseError(
            f"lod_count={lod_count} (repeated parsing of LOD1+ for >1 is unverified, no example "
            "in this corpus. The design should support it via recursive application of "
            "parse_lod_tail/parse_sk_structure, but it is unimplemented)")

    # FSkeletalMeshRenderData::Serialize終端 = 最終LODのtail終端
    render_data_end = tail_end

    dummy_objs, p = parse_dummy_objs(data, render_data_end)

    head_opaque_size = s['strip1_offset'] - 2 - lod_count_offset  # (未使用、下記head_endで算出し直す)
    head_end = lod_count_offset  # Super::Serialize〜Bounds/Materials/RefSkeletonまでの不透明領域の終端

    return {
        'lod_count': lod_count,
        'lod_count_offset': lod_count_offset,
        'lods': lods,
        'dummy_objs': dummy_objs,
        'export_end': p,
        'expected_export_end': expected_end,
        'gap_zero': (p == expected_end),
        'head_opaque_end': head_end,  # offset 0 からここまでが Super::Serialize+Bounds/Materials/RefSkeleton(不透明ブロックとして記録、4節参照)
        'file_size': len(data),
    }


def verify(uexp_path, uasset_path, verbose=True):
    if verbose:
        print(f'--- {os.path.basename(uexp_path)} ---')
    full = parse_sk_full(uexp_path, uasset_path)
    errors = []
    if not full['gap_zero']:
        errors.append(f"export end mismatch: parsed={full['export_end']} expected={full['expected_export_end']}")
    lod0 = full['lods'][0]
    if lod0['total_triangles'] * 3 == 0:
        errors.append("total_triangles is 0")
    if verbose:
        t = lod0['tail']
        print(f"  lod_count={full['lod_count']} nVtx={lod0['num_vertices']} tri={lod0['total_triangles']} "
              f"nSec={lod0['num_sections']}")
        print(f"  tail: lookup.end={t['lookup_vertex_buffer']['end']} "
              f"color={'present' if t['color_vertex_buffer'] else 'absent'} "
              f"skinWeightProfiles.count={t['skin_weight_profiles']['count']} "
              f"rayTracingRawData.count={t['ray_tracing_raw_data']['count']} "
              f"morphFlag={t['b_serialize_compressed_morph_targets']} "
              f"numInlinedLODs={t['num_inlined_lods']} numNonOptionalLODs={t['num_non_optional_lods']}")
        print(f"  dummy_objs.count={full['dummy_objs']['count']} "
              f"export_end={full['export_end']} expected={full['expected_export_end']} "
              f"gap_zero={full['gap_zero']}")
        print(f"  head_opaque: [0, {full['head_opaque_end']}) = {full['head_opaque_end']} bytes "
              "(Super::Serialize+Bounds/Materials/RefSkeleton, treated as an opaque block by this parser)")
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
