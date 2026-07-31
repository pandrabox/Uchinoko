# -*- coding: utf-8 -*-
"""SKスタブ(Head/Hair/HeadEquip用ダミーSkeletalMesh)のuassetを実行時生成する
モジュール(dev issue #26: スタブ306件の実行時生成化)。

背景:
  noue_master\\pak_extract_extra\\ 配下のSK系スタブ306件(uasset 153 + uexp 153)は
  「headボーン100%ウェイトの極小三角形」をUEで1回だけcookした自作ダミーだが、
  内部にPalworld由来のパス文字列・SK_PalHuman_Skeletonへの参照・bind pose数値が
  焼き込まれている。配布物からこれらを消すため、初回実行時にユーザーのマシン上で
  同一バイト列を再生成する方式へ移行する(work\\wp_stub\\REPORT.md参照)。

本モジュールの守備範囲(2026-07-28時点):
  - uasset側153件の**完全生成**(バイト一致検証済み、work\\wp_stub\\sha1_match_log.txt):
    入力は「パッケージパス+オブジェクト名(noue_template_manifest.jsonのパス表から
    導出可能)」「ボーン名65件(実行時にpak_live_extractでユーザーのPalworldから
    取得可能)」「GUID/PackageSource(自作cook成果物の固有値。153件のテーブル、
    Palworld由来ではない)」のみ。**Palworld由来の数値は一切埋め込まれていない**
    (uassetにはそもそも数値データが無い。文字列とテーブル構造だけ)。
  - uexp側(153件共通の1ブロブ、7,532B)は本モジュールでは生成しない。
    uexpにはbind pose(RefBonePose、double×10×65 = 5,200B)・バウンズ・頂点座標
    (headボーン位置由来)というPalworld派生数値が含まれ、これらは
    「バニラからのライブ抽出値」とビット一致しない(Blender→FBX→UE cookの
    往復による凍結値。実測: 65ボーン中ビット一致は root のみ、
    work\\wp_stub\\pose_compare.json)。バイト完全一致とPalworld由来数値の
    完全除去が両立しないため、uexpの扱いはオーナー裁定待ち
    (work\\wp_stub\\REPORT.md の選択肢A/B参照)。

uassetのバイナリ構造(153件の実測に基づく。work\\wp_stub\\analyze*.py):
  [Summary(可変長: パッケージパスfstringを含む)]
  [NameTable 77件 = group1(export参照名: ボーン65+MaterialSlot、小文字比較で
   ソート済み) + group2(ヘッダ専用名11件、同ソート)。各エントリは
   fstring + NonCasePreservingHash(u16) + CasePreservingHash(u16)]
  [Imports 5件] [Export 1件(96B)] [Depends(i32 0)] [ARD(i32 0)]
  [PreloadDependencies 3件(-5, -1, -4)]
"""
import json
import os
import struct

_HERE = os.path.dirname(os.path.abspath(__file__))
NOUE_MASTER_DIR = os.path.join(_HERE, "noue_master")
SCAFFOLD_PATH = os.path.join(NOUE_MASTER_DIR, "stub_uexp_scaffold.bin")
ASSET_IDS_PATH = os.path.join(NOUE_MASTER_DIR, "stub_asset_ids.json")

SKELETON_PACKAGE_PATH = "/Game/Pal/Model/Character/Skeleton/Human/SK_PalHuman_Skeleton"
PAK_PREFIX = "Pal/Content/Pal/Model/Character/"
# 共通骨格(=スタブのRefSkeleton)の導出元。extract_vanilla.pyのrefskel_male/female
# と同じバニラ資産(Male∩Femaleの交差がcommon_bones.jsonと完全一致することを
# work\wp_stub\verify_bone_derivation.py で実測済み)
_REFSKEL_SOURCES = (
    "Player/Outfit/SK_Player_Male_Outfit_OldCloth001/SK_Player_Male_Outfit_OldCloth001",
    "Player/Outfit/SK_Player_Female_Outfit_OldCloth001/SK_Player_Female_Outfit_OldCloth001",
)


def _bone_count_error_message(got, expected=65):
    """骨数が期待(65本)から変わったときのエラーメッセージ。
    Palworld本体のアップデートで骨格構成が変わると、ユーザーの手元で必ず
    この停止に至る(黙って壊れない設計)。ログは英語、ユーザー向け案内は
    日本語で併記する(「ログをコピー」で送られてきた本文がそのまま両方の
    読者に届くため、1つのメッセージに両言語を持たせる)。"""
    return (
        "[stub] Common skeleton has %d bones (expected %d). "
        "Palworld itself may have been updated in a way this tool does not "
        "support yet. Please check for a DiveToPalworld update." % (got, expected))

# ---------------------------------------------------------------------------
# UE FName ハッシュ(FNameEntrySerializedの2つのu16。実測: 153ファイル×77名で検証)
#   h1 = FCrc::Strihash_DEPRECATED<ANSICHAR>(大文字化, 旧CRCテーブル) & 0xFFFF
#   h2 = FCrc::StrCrc32<ANSICHAR>(標準CRC32テーブル, 1文字=4バイトステップ) & 0xFFFF
# ---------------------------------------------------------------------------

def _make_table_deprecated():
    t = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
        t.append(c)
    return t


def _make_table_crc32():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        t.append(c)
    return t


_T_DEP = _make_table_deprecated()
_T_STD = _make_table_crc32()


def ue_name_hashes(s):
    """FNameEntrySerializedの(NonCasePreservingHash, CasePreservingHash)を返す。"""
    h = 0
    for ch in s.upper():
        h = ((h >> 8) & 0x00FFFFFF) ^ _T_DEP[(h ^ (ord(ch) & 0xFF)) & 0xFF]
    h1 = h & 0xFFFF
    crc = 0xFFFFFFFF
    for ch in s:
        c = ord(ch)
        for _ in range(4):
            crc = (crc >> 8) ^ _T_STD[(crc ^ (c & 0xFF)) & 0xFF]
            c >>= 8
    h2 = (crc ^ 0xFFFFFFFF) & 0xFFFF
    return h1, h2


def _name_sort_key(s):
    """cook済みNameTableのソート順(実測: 小文字化したASCII昇順)。"""
    return s.lower()


def _sorted_export_names(bone_names):
    """NameTable group1(export参照名 = ボーン65+MaterialSlot)のソート済みリスト。
    uassetのNameTable先頭66件と、uexp内の名前index参照の両方がこの写像を使う
    (必ず同一のソートを共有すること)。"""
    return sorted(list(bone_names) + ["MaterialSlot"], key=_name_sort_key)


def _fstring(s):
    b = s.encode("ascii") + b"\x00"
    return struct.pack("<i", len(b)) + b


def _name_entry(s):
    h1, h2 = ue_name_hashes(s)
    return _fstring(s) + struct.pack("<HH", h1, h2)


# ---------------------------------------------------------------------------
# 固定セグメント(153ファイル実測で全件同一。work\wp_stub\extract_consts.py)
# ---------------------------------------------------------------------------

# magic(0x9E2A83C1) + legacy_ver(-8) + version群/CustomVersion(cook済みは全て0)
_SEG_A = bytes.fromhex("c1832a9ef8ffffff0000000000000000000000000000000000000000")
_PACKAGE_FLAGS = 0x80002200
_NAME_COUNT = 77
_ENGINE_BLOCK = b"\x00" * 36  # SavedBy/CompatibleWith EngineVersion(ゼロ)+CompressionFlags+CompressedChunks数
_PRELOAD_DEPS = struct.pack("<iii", -5, -1, -4)
_UEXP_SERIAL_SIZE = 7528  # uexp(7,532B)からフッターmagic 4Bを除いた本体
_NAMES_REFERENCED_FROM_EXPORT_DATA = 66  # ボーン65+MaterialSlot

# Export(FObjectExport 96B)の雛形(153ファイル実測: object_name index(+16)と
# SerialOffset(+36, i64)以外は全件同一バイト。work\wp_stub\analyze9.py)。
# 内訳: Class=-1(SkeletalMesh import), Super=0, Template=-4(Default__SkeletalMesh),
# Outer=0, ObjectFlags=0xB, SerialSize=7528, 依存カウント群(Preload 3件と整合)。
_EXPORT_TEMPLATE = bytes.fromhex(
    "ffffffff00000000fcffffff000000004a000000000000000b000000"
    "681d0000000000005908000000000000000000000000000000000000"
    "00000000000000000100000001000000000000000000000001000000"
    "000000000200000000000000")
assert len(_EXPORT_TEMPLATE) == 96


def _build_export(object_name_idx, serial_offset):
    b = bytearray(_EXPORT_TEMPLATE)
    struct.pack_into("<i", b, 16, object_name_idx)   # ObjectName(FName index)
    struct.pack_into("<q", b, 36, serial_offset)     # SerialOffset(=TotalHeaderSize)
    return bytes(b)


def build_stub_uasset(package_path, object_name, bone_names,
                      skeleton_package_path, guid_bytes, package_source):
    """SKスタブのuasset(2.1KB級)を完全生成する。

    package_path: 例 "/Game/Pal/Model/Character/Player/Hair/Hair001/SK_Player_Hair001"
                  (noue_template_manifest.jsonの相対パスから機械的に導出できる)
    object_name:  例 "SK_Player_Hair001"(package_pathの末尾要素)
    bone_names:   共通骨格65本のボーン名リスト(順不同でよい。実行時は
                  pak_live_extract経由でユーザーのPalworldから取得する)
    skeleton_package_path: "/Game/Pal/Model/Character/Skeleton/Human/SK_PalHuman_Skeleton"
    guid_bytes:   16B。自作cook成果物(2026-07のUE cook)固有のGUID
    package_source: u32。同上(cook時に決まった値)
    """
    if len(bone_names) != 65:
        raise ValueError(_bone_count_error_message(len(bone_names)))
    skeleton_object_name = skeleton_package_path.rsplit("/", 1)[1]

    group1 = _sorted_export_names(bone_names)
    group2 = sorted([
        package_path,
        skeleton_package_path,
        "/Script/CoreUObject",
        "/Script/Engine",
        "Class",
        "Default__SkeletalMesh",
        "Package",
        skeleton_object_name,
        object_name,
        "SkeletalMesh",
        "Skeleton",
    ], key=_name_sort_key)
    names = group1 + group2
    if len(names) != _NAME_COUNT:
        raise ValueError("name table must have %d entries, got %d" % (_NAME_COUNT, len(names)))
    idx = {s: i for i, s in enumerate(names)}

    name_table = b"".join(_name_entry(s) for s in names)

    def imp(class_package, class_name, outer, obj):
        # FObjectImport 32B: ClassPackage(FName 8B) + ClassName(FName 8B) +
        # OuterIndex(4B) + ObjectName(FName 8B) + bImportOptional(4B)
        return struct.pack("<iiiiiiii", idx[class_package], 0, idx[class_name], 0,
                           outer, idx[obj], 0, 0)

    imports = b"".join([
        imp("/Script/CoreUObject", "Class", -3, "SkeletalMesh"),
        imp("/Script/CoreUObject", "Package", 0, skeleton_package_path),
        imp("/Script/CoreUObject", "Package", 0, "/Script/Engine"),
        imp("/Script/Engine", "SkeletalMesh", -3, "Default__SkeletalMesh"),
        imp("/Script/Engine", "Skeleton", -2, skeleton_object_name),
    ])

    depends = struct.pack("<i", 0)
    ard = struct.pack("<i", 0)

    # --- オフセット計算(Summaryは固定長部+package_path fstringのみ可変) ---
    pkg_fstr = _fstring(package_path)
    # Summary長 = SEG_A(28) + ths(4) + fstring + 固定尾部
    fixed_tail_len = (4        # package_flags
                      + 11 * 4  # name_count..depends_offset
                      + 4 * 4   # softpkgref count/off, searchable, thumbnail
                      + 16      # Guid
                      + 4 + 8   # gen_count + FGenerationInfo(1,77)
                      + len(_ENGINE_BLOCK)
                      + 4       # PackageSource
                      + 4       # AdditionalPackagesToCook count
                      + 4       # AssetRegistryDataOffset
                      + 8       # BulkDataStartOffset
                      + 4       # WorldTileInfoDataOffset
                      + 4       # ChunkIDs count
                      + 4 + 4   # PreloadDependencyCount/Offset
                      + 4       # NamesReferencedFromExportDataCount
                      + 8)      # PayloadTocOffset
    name_offset = len(_SEG_A) + 4 + len(pkg_fstr) + fixed_tail_len
    import_offset = name_offset + len(name_table)
    export_offset = import_offset + len(imports)
    depends_offset = export_offset + 96
    ard_offset = depends_offset + len(depends)
    preload_offset = ard_offset + len(ard)
    total_header_size = preload_offset + len(_PRELOAD_DEPS)
    bulk_data_start = total_header_size + _UEXP_SERIAL_SIZE

    export = _build_export(idx[object_name], total_header_size)

    summary = bytearray()
    summary += _SEG_A
    summary += struct.pack("<i", total_header_size)
    summary += pkg_fstr
    summary += struct.pack("<I", _PACKAGE_FLAGS)
    summary += struct.pack("<ii", _NAME_COUNT, name_offset)
    summary += struct.pack("<ii", 0, import_offset)   # SoftObjectPaths count/offset
    summary += struct.pack("<ii", 0, 0)               # GatherableText count/offset
    summary += struct.pack("<ii", 1, export_offset)
    summary += struct.pack("<ii", 5, import_offset)
    summary += struct.pack("<i", depends_offset)
    summary += struct.pack("<iiii", 0, 0, 0, 0)       # SoftPkgRef cnt/off, Searchable, Thumbnail
    summary += bytes(guid_bytes)
    summary += struct.pack("<iii", 1, 1, _NAME_COUNT)  # gen_count + FGenerationInfo
    summary += _ENGINE_BLOCK
    summary += struct.pack("<I", package_source)
    summary += struct.pack("<i", 0)                   # AdditionalPackagesToCook
    summary += struct.pack("<i", ard_offset)
    summary += struct.pack("<q", bulk_data_start)
    summary += struct.pack("<i", 0)                   # WorldTileInfoDataOffset
    summary += struct.pack("<i", 0)                   # ChunkIDs count
    summary += struct.pack("<ii", 3, preload_offset)
    summary += struct.pack("<i", _NAMES_REFERENCED_FROM_EXPORT_DATA)
    summary += struct.pack("<q", -1)                  # PayloadTocOffset
    assert len(summary) == name_offset, (len(summary), name_offset)

    out = bytes(summary) + name_table + imports + export + depends + ard + _PRELOAD_DEPS
    assert len(out) == total_header_size
    return out


def derive_pkg_and_object(rel_path):
    """manifestの相対パス(例 'Player/Hair/Hair001/SK_Player_Hair001.uasset')から
    (package_path, object_name) を導出する。"""
    rel = rel_path.replace("\\", "/")
    for ext in (".uasset", ".uexp"):
        if rel.endswith(ext):
            rel = rel[: -len(ext)]
            break
    return "/Game/Pal/Model/Character/" + rel, rel.rsplit("/", 1)[1]


# ===========================================================================
# uexp生成(案B、2026-07-28指揮者裁定): 同梱するのは「穴あきスカフォールド」
# (stub_uexp_scaffold.bin、Palworld派生数値を全てゼロ化済み)だけにし、
# RefSkeleton構造・bind pose・バウンズ・頂点座標は初回実行時にユーザーの
# Palworld本体からのライブ抽出値で埋める。
#
# 決定性の根拠(全ユーザーで同一バイトになる理由):
#   1) bind poseはライブ抽出したバニラuexpの該当80Bを**生バイトのまま**コピーする
#      (浮動小数点演算を一切挟まない)。同一バージョンのPal-Windows.pakは
#      全ユーザーで同一バイトなので、注入結果も同一
#   2) 骨の順序・親子は「Male∩Femaleの交差(Male順)」という決定的な集合演算
#      (extract_vanilla.pyのcommon_bones.jsonと同一の定義。順序込みの一致を実測済み)
#   3) バウンズ/頂点はheadボーンのワールド位置から計算するが、入力(バニラpose)が
#      全ユーザー同一で、計算はIEEE-754 double/f32の加算・乗算のみ(libm不使用)
#      なのでCPython実装間で結果は同一
#   ※Palworld本体のアップデートで骨格が変わった場合は値が変わりうるが、それは
#     「ユーザーの手元のゲームに合わせて再生成される」だけであり配布物は不変。
# ===========================================================================

_N_COMMON_BONES = 65
_UEXP_SIZE = 7532
# スカフォールドの穴のオフセット(work\wp_stub\analyze5.py / make_scaffold.py実測)
_OFF_BOUNDS_ORIGIN = 144   # FBoxSphereBounds origin(double x3)。extent/radiusは
                           # 三角形サイズ(0.1cm)由来の自作定数なのでスカフォールドに残置
_OFF_BONEINFO_COUNT = 244  # RefBoneInfo: i32 count + count*(name_idx,num,parent)
_OFF_POSE_COUNT = 1028     # RefBonePose: i32 count + count*80B(FTransform double)
_OFF_NAMEMAP_COUNT = 6232  # NameToIndexMap: i32 count + count*(name_idx,num,bone_idx)
_OFF_VERTS = 7336          # 極小三角形の頂点座標 float32 x3 x3
_TRI_SIZE_CM = 0.1


def _read_uasset_names(data):
    """uasset Summaryを最小限だけ前方パースしてNameTableを返す(自己完結、
    live_templateへの依存を作らないための簡約版)。"""
    if struct.unpack_from("<I", data, 0)[0] != 0x9E2A83C1:
        raise ValueError("uasset magic mismatch")
    off = 4
    legacy = struct.unpack_from("<i", data, off)[0]; off += 4
    if legacy != -4:
        off += 4
    off += 4  # file_version_ue4
    if legacy <= -8:
        off += 4  # file_version_ue5
    off += 4  # licensee
    cv_count = struct.unpack_from("<i", data, off)[0]; off += 4
    off += cv_count * 20
    off += 4  # total_header_size
    slen = struct.unpack_from("<i", data, off)[0]; off += 4  # package_name fstring
    off += slen if slen >= 0 else -slen * 2
    off += 4  # package_flags
    name_count = struct.unpack_from("<i", data, off)[0]; off += 4
    name_offset = struct.unpack_from("<i", data, off)[0]; off += 4
    names = []
    off = name_offset
    for _ in range(name_count):
        slen = struct.unpack_from("<i", data, off)[0]; off += 4
        if slen > 0:
            names.append(data[off:off + slen - 1].decode("ascii", errors="replace"))
            off += slen
        elif slen < 0:
            n = -slen * 2
            names.append(data[off:off + n - 2].decode("utf-16-le", errors="replace"))
            off += n
        else:
            names.append("")
        off += 4  # hashes
    return names


def find_ref_skeleton(uasset_bytes, uexp_bytes):
    """cook済みSK uexpからFReferenceSkeleton(RefBoneInfo+RefBonePose)を見つける。
    root(-1)+pelvis(parent 0)の連続レコードをアンカーに探索し、直前のcount、
    直後のpose countの整合で確定する(work\\wp_stub\\analyze6b.pyで実証した方式)。
    戻り値: (bones=[(name, parent_index)], pose_raw=[80Bのbytes])"""
    names = _read_uasset_names(uasset_bytes)
    try:
        root_i = names.index("root")
        pelvis_i = names.index("pelvis")
    except ValueError:
        raise ValueError("root/pelvis not in NameTable (RefSkeleton search precondition broken)")
    for off in range(0, len(uexp_bytes) - 24):
        a = struct.unpack_from("<iii", uexp_bytes, off)
        b = struct.unpack_from("<iii", uexp_bytes, off + 12)
        if not (a[0] == root_i and a[2] == -1 and b[0] == pelvis_i and b[2] == 0):
            continue
        cnt = struct.unpack_from("<i", uexp_bytes, off - 4)[0]
        if not (2 <= cnt <= 1000):
            continue
        pco = off + cnt * 12
        if pco + 4 > len(uexp_bytes) or struct.unpack_from("<i", uexp_bytes, pco)[0] != cnt:
            continue
        bones = []
        ok = True
        for k in range(cnt):
            ni, num, par = struct.unpack_from("<iii", uexp_bytes, off + k * 12)
            if not (0 <= ni < len(names)) or not (-1 <= par < cnt):
                ok = False
                break
            nm = names[ni] + ("_%d" % (num - 1) if num else "")
            bones.append((nm, par))
        if not ok:
            continue
        pose_raw = [bytes(uexp_bytes[pco + 4 + k * 80: pco + 4 + (k + 1) * 80])
                    for k in range(cnt)]
        return bones, pose_raw
    raise ValueError("RefSkeleton not found")


def derive_common_skeleton(pak_path):
    """ユーザーのPalworld本体pakからMale/Female OldCloth001をライブ抽出し、
    共通骨格(65本、Male順、親は最近傍保持祖先へリマップ)とMale基準の
    bind pose生バイトを返す。extract_vanilla.pyのcommon_bones.json定義と
    順序込みで一致することを実測済み(work\\wp_stub\\verify_bone_derivation.py)。"""
    import pak_live_extract  # 遅延import(ooz worker等の重い依存を使用時のみ)
    paths = []
    for rel in _REFSKEL_SOURCES:
        paths += [PAK_PREFIX + rel + ".uasset", PAK_PREFIX + rel + ".uexp"]
    ext = pak_live_extract.extract_files(pak_path, paths)
    m_bones, m_pose = find_ref_skeleton(ext[paths[0]], ext[paths[1]])
    f_bones, _ = find_ref_skeleton(ext[paths[2]], ext[paths[3]])
    m_names = [b[0] for b in m_bones]
    f_names = set(b[0] for b in f_bones)
    keep = [i for i, n in enumerate(m_names) if n in f_names]
    new_index = {i: k for k, i in enumerate(keep)}
    records = []
    pose_raw = []
    for i in keep:
        par = m_bones[i][1]
        while par != -1 and par not in new_index:
            par = m_bones[par][1]
        records.append((m_names[i], new_index[par] if par != -1 else -1))
        pose_raw.append(m_pose[i])
    if len(records) != _N_COMMON_BONES:
        raise ValueError(_bone_count_error_message(len(records)))
    return records, pose_raw


def compute_head_world_pos(records, pose_raw):
    """headボーンのワールド位置(double)を、bind poseの親子合成のみで計算する。
    使う演算は乗算・加算だけ(決定的)。"""
    idx = {nm: k for k, (nm, par) in enumerate(records)}
    poses = [struct.unpack("<10d", raw) for raw in pose_raw]

    def qrot(q, v):
        x, y, z, w = q
        vx, vy, vz = v
        tx = 2 * (y * vz - z * vy)
        ty = 2 * (z * vx - x * vz)
        tz = 2 * (x * vy - y * vx)
        return (vx + w * tx + (y * tz - z * ty),
                vy + w * ty + (z * tx - x * tz),
                vz + w * tz + (x * ty - y * tx))

    k = idx["head"]
    pos = (0.0, 0.0, 0.0)
    while k != -1:
        p = poses[k]
        q, t, s = (p[0], p[1], p[2], p[3]), (p[4], p[5], p[6]), (p[7], p[8], p[9])
        pos = (pos[0] * s[0], pos[1] * s[1], pos[2] * s[2])
        pos = qrot(q, pos)
        pos = (pos[0] + t[0], pos[1] + t[1], pos[2] + t[2])
        k = records[k][1]
    return pos


def _f32(x):
    """doubleをfloat32へ丸めた値(double表現)を返す(頂点はf32格納のため)。"""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def build_stub_uexp(records, pose_raw):
    """スカフォールド+ライブ抽出値からスタブuexp(7,532B、153ファイル共通)を組む。"""
    with open(SCAFFOLD_PATH, "rb") as f:
        out = bytearray(f.read())
    if len(out) != _UEXP_SIZE:
        raise ValueError(f"invalid scaffold size: {len(out)}")
    if len(records) != _N_COMMON_BONES:
        raise ValueError(_bone_count_error_message(len(records)))

    bone_names = [nm for nm, _ in records]
    export_names = _sorted_export_names(bone_names)
    name_idx = {s: i for i, s in enumerate(export_names)}

    # RefBoneInfo
    struct.pack_into("<i", out, _OFF_BONEINFO_COUNT, len(records))
    for k, (nm, par) in enumerate(records):
        struct.pack_into("<iii", out, _OFF_BONEINFO_COUNT + 4 + k * 12,
                         name_idx[nm], 0, par)
    # RefBonePose(生バイト注入。浮動小数点演算なし)
    struct.pack_into("<i", out, _OFF_POSE_COUNT, len(records))
    for k, raw in enumerate(pose_raw):
        out[_OFF_POSE_COUNT + 4 + k * 80: _OFF_POSE_COUNT + 4 + (k + 1) * 80] = raw
    # NameToIndexMap(骨順の逐次登録)
    struct.pack_into("<i", out, _OFF_NAMEMAP_COUNT, len(records))
    for k, (nm, par) in enumerate(records):
        struct.pack_into("<iii", out, _OFF_NAMEMAP_COUNT + 4 + k * 12,
                         name_idx[nm], 0, k)

    # 頂点(head位置の0.1cm三角形)とバウンズorigin
    hx, hy, hz = compute_head_world_pos(records, pose_raw)
    v0 = (_f32(hx), _f32(hy), _f32(hz))
    verts = [v0, (v0[0] + _TRI_SIZE_CM, v0[1], v0[2]), (v0[0], v0[1] - _TRI_SIZE_CM, v0[2])]
    for k, (x, y, z) in enumerate(verts):
        struct.pack_into("<fff", out, _OFF_VERTS + k * 12, x, y, z)
    half = _TRI_SIZE_CM / 2.0
    struct.pack_into("<ddd", out, _OFF_BOUNDS_ORIGIN,
                     v0[0] + half, v0[1] - half, v0[2])
    return bytes(out)


def _load_asset_ids():
    with open(ASSET_IDS_PATH, encoding="utf-8") as f:
        return json.load(f)["files"]


def build_stub_files(pak_path, sk_rels):
    """SKスタブ306件(manifest project区分の相対パス)を実行時生成して
    {rel: bytes} で返す。uassetはバイト完全一致の完全生成(検証:
    work\\wp_stub\\sha1_match_log.txt)、uexpはライブ抽出値注入
    (旧同梱スタブとの差はpose/バウンズ/頂点領域のみ。案B、REPORT.md参照)。"""
    records, pose_raw = derive_common_skeleton(pak_path)
    uexp_blob = build_stub_uexp(records, pose_raw)
    bone_names = [nm for nm, _ in records]
    ids = _load_asset_ids()
    out = {}
    for rel in sk_rels:
        r = rel.replace("\\", "/")
        if r.endswith(".uexp"):
            out[rel] = uexp_blob
            continue
        pkg, obj = derive_pkg_and_object(r)
        t = ids.get(r)
        if t is None:
            raise KeyError(f"stub not in stub_asset_ids.json: {r}")
        out[rel] = build_stub_uasset(pkg, obj, bone_names, SKELETON_PACKAGE_PATH,
                                     bytes.fromhex(t["guid"]), t["psrc"])
    return out
