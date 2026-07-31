# -*- coding: utf-8 -*-
"""vp_matparam — cook済み MaterialInstanceConstant のパラメータを
**標準ライブラリのみ**で編集する(.NET / UAssetAPI / usmap 不要)。

U50: `work\\u50_unify\\mattune\\MatTune\\Program.cs`(UAssetAPI、.NET 9)が
行っていた編集を純Pythonで置き換える。エンドユーザーに .NET を要求しないため。

対応する編集:
  set_vector(name, (r,g,b,a))  VectorParameterValues を設定(無ければ既存
                               要素[0]を複製して名前だけ変えて末尾に追加)
  set_scalar(name, value)      ScalarParameterValues を設定(同上)
  emissive_from_base()         TextureParameterValues の "Base Texture" 要素を
                               複製して "Emissive Texture" として末尾に追加
                               (参照オブジェクトは Base Texture と同一)
  drop_scalar(name)            ScalarParameterValues から削除

MatTune.exe と同一の意味論(複製元・複製位置・NameMap追記順)になるよう
作ってある。受入検証は `work\\u50_purepy\\verify_vs_mattune.py`
(uexp バイト完全一致を確認)。

--------------------------------------------------------------------------
バイト構造(UE5 unversioned property serialization)
--------------------------------------------------------------------------
uexp 先頭は export[0](MaterialInstanceConstant)の unversioned property
ストリーム:

  FUnversionedHeader = uint16 フラグメント列(最後の要素で bIsLast)
      packed & 0x007f      SkipNum      (直前のプロパティ index からの飛ばし数)
      packed & 0x0080      bHasAnyZeroes
      packed & 0x0100      bIsLast
      packed >> 9          ValueNum     (このフラグメントが持つ値の個数)
  続けて、bHasAnyZeroes を持つフラグメントの値の総数ぶんのゼロマスク
  (<=8bit:1byte / <=16bit:2byte / それ以上:32bit単位)。
  ゼロと印された値は**ペイロード0バイト**。

MaterialInstanceConstant のプロパティ index(実測。SRC衣装MIと素体MIの
両方で一致):
  10 = Parent (FPackageIndex, 4byte)
  12 = bOverrideSubsurfaceProfile 相当の1byte(素体MIには無い)
  14 = ScalarParameterValues  (TArray<FScalarParameterValue>)
  15 = VectorParameterValues  (TArray<FVectorParameterValue>)
  16 = DoubleVectorParameterValues (UE5で追加。実測サンプルには出現せず)
  17 = TextureParameterValues (TArray<FTextureParameterValue>)
  20 以降 = BasePropertyOverrides / SubsurfaceProfile / TextureStreamingData
           等(本モジュールは触らない。バイト列をそのまま残す)

TArray は「int32 要素数 + 要素の並び」(要素ごとの型情報は無い)。
各要素(FScalar/FVector/FTextureParameterValue)は:

  [要素の FUnversionedHeader]      値3個: ParameterInfo / ParameterValue /
                                    ExpressionGUID
  [ParameterInfo の FUnversionedHeader]  値3個: Name / Association / Index
  FName Name (int32 index + int32 number = 8byte)
  uint8 Association
  int32 Index
  ParameterValue   (Scalar=float 4 / Vector=FLinearColor 16 /
                    DoubleVector=FVector4d 32 / Texture=FPackageIndex 4)
  FGuid ExpressionGUID (16byte)

ParameterValue / ExpressionGUID がゼロのときはゼロマスクで省略される
(実測: RefractionDepthBias は両方省略で18byte、Subsurface Texture は
参照 null のため ParameterValue のみ省略)。**FName が index 0/number 0
でもゼロ扱いにはならない**(実測: SRC の "Base Texture" は NameMap[0])
ため、ParameterInfo のヘッダは原本のバイトをそのまま引き継ぐ。

--------------------------------------------------------------------------
uasset 側の書き換え(先行実装 work\\u50_diag\\emissive_impl\\
insert_emissive_proto.py と同じ。UAssetAPI をオラクルにした差分比較で
検証済みの経路)
--------------------------------------------------------------------------
NameMap への追記のみ(新規 import は作らないので Import Table /
PreloadDependencies は不変)。

**罠**: ExportMap の SerialOffset は「uasset+uexp を1本の仮想バイナリと
見なした絶対オフセット」だが、シフト量は **uasset の増加分だけ**である。
uexp の増加分を足すと二重計上になる(先行実装が実際に踏んだバグ)。
SerialSize は uexp の増加分だけ増える。BulkDataStartOffset は
uasset+uexp 合算ぶんシフトする。
"""
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# U51(research\ue_exit→pipeline\py移設): parse_uasset_header.pyは元research\ue_exit\
# から無改変のままpipeline\py\へコピーされた(research\ue_exit\側は開発参照用に
# 残置、実行時には見ない)。_HEREから直接importできる

import live_template as _lt  # noqa: E402
import parse_uasset_header as _puh  # noqa: E402


class MatParamError(RuntimeError):
    pass


# プロパティindex -> 配列種別(値のバイト数)
PROP_SCALAR = 14
PROP_VECTOR = 15
PROP_DOUBLEVECTOR = 16
PROP_TEXTURE = 17
_ARRAY_VALUE_SIZE = {PROP_SCALAR: 4, PROP_VECTOR: 16,
                     PROP_DOUBLEVECTOR: 32, PROP_TEXTURE: 4}
# 配列より手前に出現しうる、サイズが判っている単純プロパティ
_SIMPLE_PROP_SIZE = {10: 4, 12: 1}

_GUID_SIZE = 16


# ---------------------------------------------------------------- header ---

def _read_unversioned_header(data, off):
    """FUnversionedHeader を読む。戻り値 (slots, new_off, raw_bytes)。
    slots = [(property_index, is_zero), ...] の登場順。"""
    start = off
    frags = []
    while True:
        if off + 2 > len(data):
            raise MatParamError("unversioned header ends prematurely")
        packed = struct.unpack_from("<H", data, off)[0]
        off += 2
        frags.append((packed & 0x7F, bool(packed & 0x80),
                      packed >> 9, bool(packed & 0x100)))
        if frags[-1][3]:
            break
        if len(frags) > 256:
            raise MatParamError("too many unversioned header fragments")

    nzero_bits = sum(v for (_s, hz, v, _l) in frags if hz)
    if nzero_bits == 0:
        nzero_bytes = 0
    elif nzero_bits <= 8:
        nzero_bytes = 1
    elif nzero_bits <= 16:
        nzero_bytes = 2
    else:
        nzero_bytes = ((nzero_bits + 31) // 32) * 4
    zmask = int.from_bytes(data[off:off + nzero_bytes], "little") if nzero_bytes else 0
    off += nzero_bytes

    slots = []
    idx = 0
    zbit = 0
    for (skip, hz, vnum, _last) in frags:
        idx += skip
        for _ in range(vnum):
            if hz:
                is_zero = bool((zmask >> zbit) & 1)
                zbit += 1
            else:
                is_zero = False
            slots.append((idx, is_zero))
            idx += 1
    return slots, off, bytes(data[start:off])


def _write_unversioned_header(slots):
    """slots(連続 index 前提)から FUnversionedHeader を組む。
    本モジュールが自前で組むのは「index 0,1,2 の3値」= パラメータ要素の
    ヘッダのみ。それ以外(トップレベル)は原本バイトをそのまま使う。"""
    if [s[0] for s in slots] != list(range(len(slots))):
        raise MatParamError("generating a header for non-contiguous index is unsupported")
    n = len(slots)
    if not 1 <= n <= 127:
        raise MatParamError(f"unsupported value count {n}")
    has_zero = any(z for (_i, z) in slots)
    packed = (n << 9) | 0x0100 | (0x80 if has_zero else 0)
    out = struct.pack("<H", packed)
    if has_zero:
        m = 0
        for i, (_idx, z) in enumerate(slots):
            if z:
                m |= (1 << i)
        out += bytes([m])
    return out


# ----------------------------------------------------------- param entry ---

def _parse_param_entry(data, off, value_size):
    """パラメータ配列の1要素を読む。戻り値 (entry, new_off)。"""
    slots, off2, ehdr = _read_unversioned_header(data, off)
    if [s[0] for s in slots] != [0, 1, 2]:
        raise MatParamError(
            f"@{off}: parameter element value layout {slots} is unsupported "
            f"(only the 3 values ParameterInfo/ParameterValue/ExpressionGUID are supported)")
    if slots[0][1]:
        raise MatParamError(f"@{off}: ParameterInfo is zero-omitted (unsupported)")

    pslots, off3, pihdr = _read_unversioned_header(data, off2)
    if [s[0] for s in pslots] != [0, 1, 2] or any(z for (_i, z) in pslots):
        raise MatParamError(
            f"@{off}: ParameterInfo value layout {pslots} is unsupported "
            f"(only the form with all 3 values Name/Association/Index present is supported)")
    name_idx, name_num = struct.unpack_from("<ii", data, off3)
    assoc = data[off3 + 8]
    index_field = struct.unpack_from("<i", data, off3 + 9)[0]
    p = off3 + 13

    if slots[1][1]:
        value = None
    else:
        value = bytes(data[p:p + value_size])
        if len(value) != value_size:
            raise MatParamError(f"@{off}: not enough ParameterValue bytes")
        p += value_size

    if slots[2][1]:
        guid = None
    else:
        guid = bytes(data[p:p + _GUID_SIZE])
        if len(guid) != _GUID_SIZE:
            raise MatParamError(f"@{off}: not enough ExpressionGUID bytes")
        p += _GUID_SIZE

    entry = dict(pihdr=pihdr, name_idx=name_idx, name_num=name_num,
                 assoc=assoc, index_field=index_field, value=value, guid=guid)
    return entry, p


def _build_param_entry(entry, value_size):
    """entry(dict)を要素バイト列へ。ゼロ判定は『バイト列が全て0か』。
    UAssetAPI/UE の実測挙動と一致することは verify_vs_mattune.py で確認する。"""
    value = entry["value"]
    guid = entry["guid"]
    if value is not None and len(value) != value_size:
        raise MatParamError("ParameterValue size mismatch")
    if guid is not None and len(guid) != _GUID_SIZE:
        raise MatParamError("ExpressionGUID size mismatch")
    value_zero = (value is None) or (value == b"\x00" * value_size)
    guid_zero = (guid is None) or (guid == b"\x00" * _GUID_SIZE)
    hdr = _write_unversioned_header([(0, False), (1, value_zero), (2, guid_zero)])
    out = bytearray(hdr)
    out += entry["pihdr"]
    out += struct.pack("<ii", entry["name_idx"], entry["name_num"])
    out += bytes([entry["assoc"]])
    out += struct.pack("<i", entry["index_field"])
    if not value_zero:
        out += value
    if not guid_zero:
        out += guid
    return bytes(out)


def _parse_param_array(data, off, value_size):
    count = struct.unpack_from("<i", data, off)[0]
    if not (0 <= count <= 512):
        raise MatParamError(f"@{off}: implausible element count {count}")
    p = off + 4
    entries = []
    for _ in range(count):
        e, p = _parse_param_entry(data, p, value_size)
        entries.append(e)
    return dict(start=off, end=p, entries=entries, value_size=value_size)


def _build_param_array(arr):
    out = bytearray(struct.pack("<i", len(arr["entries"])))
    for e in arr["entries"]:
        out += _build_param_entry(e, arr["value_size"])
    return bytes(out)


# ------------------------------------------------------------------- MI ----

def parse_mi_uexp(uexp_bytes):
    """uexp のトップレベルを走査し、Scalar/Vector/(DoubleVector)/Texture の
    各パラメータ配列の位置と内容を返す。配列より後ろのバイトは触らない。"""
    slots, off, _raw = _read_unversioned_header(uexp_bytes, 0)
    arrays = {}
    order = []
    for (idx, is_zero) in slots:
        if is_zero:
            continue
        if idx in _ARRAY_VALUE_SIZE:
            arr = _parse_param_array(uexp_bytes, off, _ARRAY_VALUE_SIZE[idx])
            arrays[idx] = arr
            order.append(idx)
            off = arr["end"]
            continue
        if idx in _SIMPLE_PROP_SIZE:
            off += _SIMPLE_PROP_SIZE[idx]
            continue
        if idx > PROP_TEXTURE:
            break  # 以降は未解釈のまま残す
        raise MatParamError(
            f"unknown top-level property index={idx} @{off} "
            f"(this MI has a shape this module does not expect)")
    if PROP_TEXTURE not in arrays:
        raise MatParamError("TextureParameterValues not found")
    return dict(arrays=arrays, order=order, tail_start=off)


def _rebuild_uexp(uexp_bytes, mi):
    out = bytearray()
    cur = 0
    for idx in mi["order"]:
        arr = mi["arrays"][idx]
        out += uexp_bytes[cur:arr["start"]]
        out += _build_param_array(arr)
        cur = arr["end"]
    out += uexp_bytes[cur:]
    return bytes(out)


# ------------------------------------------------------------------ ops ----

class _NameTable:
    def __init__(self, names):
        self.names = list(names)
        self.orig_count = len(names)
        self.index = {s: i for i, s in enumerate(names)}
        self.added = []

    def get(self, s):
        """既存なら既存 index、無ければ末尾に追記して新 index を返す
        (UAssetAPI の FName.FromString と同じ意味論=op順に追記される)。"""
        if s in self.index:
            return self.index[s]
        i = len(self.names)
        self.names.append(s)
        self.index[s] = i
        self.added.append(s)
        return i


def _find_entry(arr, names, param_name):
    for e in arr["entries"]:
        if 0 <= e["name_idx"] < len(names) and names[e["name_idx"]] == param_name \
                and e["name_num"] == 0:
            return e
    return None


def _clone_entry(src):
    return dict(src)


def edit_material_instance(uasset_bytes, uexp_bytes, ops):
    """cook済み MaterialInstanceConstant の uasset/uexp バイト列へ ops を
    適用し (new_uasset, new_uexp) を返す。入力は変更しない。

    ops は (種別, ...) のタプル列(**順序が NameMap 追記順を決める**):
        ("vector", name, (r, g, b, a))
        ("scalar", name, float)
        ("emissive_from_base",)
        ("drop_scalar", name)

    想定外の構造を見つけたら黙って壊れた出力を返さず MatParamError を送出する。
    """
    h = _lt._parse_header_with_offsets(uasset_bytes)
    names, names_end = _lt._read_name_table(uasset_bytes, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        raise MatParamError(
            f"name table end ({names_end}) != import_offset ({h.import_offset})")
    if h.export_count != 1:
        raise MatParamError(
            f"export_count={h.export_count} (only single-export MI is supported)")

    nt = _NameTable(names)
    mi = parse_mi_uexp(uexp_bytes)
    log = []

    for op in ops:
        kind = op[0]
        if kind == "scalar":
            _, pname, val = op
            arr = mi["arrays"].get(PROP_SCALAR)
            if arr is None or not arr["entries"]:
                raise MatParamError("ScalarParameterValues is missing/empty")
            e = _find_entry(arr, nt.names, pname)
            if e is None:
                e = _clone_entry(arr["entries"][0])
                e["name_idx"] = nt.get(pname)
                e["name_num"] = 0
                arr["entries"].append(e)
                log.append(f"[scalar +] {pname} = {val}")
            else:
                log.append(f"[scalar =] {pname} = {val}")
            e["value"] = struct.pack("<f", float(val))
        elif kind == "vector":
            _, pname, rgba = op
            arr = mi["arrays"].get(PROP_VECTOR)
            if arr is None or not arr["entries"]:
                raise MatParamError("VectorParameterValues is missing/empty")
            e = _find_entry(arr, nt.names, pname)
            if e is None:
                e = _clone_entry(arr["entries"][0])
                e["name_idx"] = nt.get(pname)
                e["name_num"] = 0
                arr["entries"].append(e)
                log.append(f"[vector +] {pname} = {rgba}")
            else:
                log.append(f"[vector =] {pname} = {rgba}")
            c = list(rgba) + [1.0] * (4 - len(rgba))
            e["value"] = struct.pack("<ffff", *[float(x) for x in c[:4]])
        elif kind == "emissive_from_base":
            arr = mi["arrays"].get(PROP_TEXTURE)
            if arr is None:
                raise MatParamError("TextureParameterValues is missing")
            if _find_entry(arr, nt.names, "Emissive Texture") is not None:
                log.append("[emissive] already present")
                continue
            bt = _find_entry(arr, nt.names, "Base Texture")
            if bt is None:
                raise MatParamError('"Base Texture" is missing')
            e = _clone_entry(bt)
            e["name_idx"] = nt.get("Emissive Texture")
            e["name_num"] = 0
            arr["entries"].append(e)
            ref = struct.unpack("<i", e["value"])[0] if e["value"] else 0
            log.append(f"[texture +] Emissive Texture -> fpi={ref} "
                       f"(same object as Base Texture)")
        elif kind == "drop_scalar":
            _, pname = op
            arr = mi["arrays"].get(PROP_SCALAR)
            if arr is None:
                continue
            e = _find_entry(arr, nt.names, pname)
            if e is not None:
                arr["entries"].remove(e)
                log.append(f"[scalar -] {pname}")
        else:
            raise MatParamError(f"unknown op: {kind}")

    new_uexp = _rebuild_uexp(uexp_bytes, mi)
    growth_uexp = len(new_uexp) - len(uexp_bytes)
    new_uasset = _patch_uasset_for_names(uasset_bytes, h, nt.added, growth_uexp)
    return new_uasset, new_uexp, log


def _patch_name_count_side_fields(buf, h, new_name_count):
    """NameCount 以外に「名前の総数」を持つ2つのヘッダフィールドを更新する。
    `_parse_header_with_offsets` が位置を持っていないため相対位置から導出する。

      Generations[0].NameCount            = ThumbnailTableOffset(+4) + FGuid(16)
                                            + int32 GenerationCount + int32 ExportCount
      NamesReferencedFromExportDataCount  = PreloadDependencyOffset + 4

    UAssetAPI(MatTune.exe)が書き戻す値と一致させるための処理
    (この2フィールドだけが uexp 完全一致時に残っていた差だった)。
    導出位置の妥当性を機械チェックし、外れていたら**何もしない**
    (安全側: 既存のlive_template系パッチも同フィールドを触らないため、
    無更新でも既存挙動と同じになる)。"""
    gen_count_off = h.thumbnail_table_offset_off + 4 + 16
    if gen_count_off + 12 <= len(buf):
        gen_count = struct.unpack_from("<i", buf, gen_count_off)[0]
        gen_export_count = struct.unpack_from("<i", buf, gen_count_off + 4)[0]
        if gen_count == 1 and gen_export_count == h.export_count:
            struct.pack_into("<i", buf, gen_count_off + 8, new_name_count)

    nref_off = h.preload_dependency_offset_off + 4
    if nref_off + 4 <= len(buf):
        nref = struct.unpack_from("<i", buf, nref_off)[0]
        if 0 < nref <= h.name_count:
            struct.pack_into("<i", buf, nref_off, new_name_count)


def _patch_uasset_for_names(uasset_bytes, h, new_names, growth_uexp):
    """NameMap 末尾へ new_names を追記し、以降のオフセット類を補正する。
    新規 import は作らないため Import Table / PreloadDependencies は不変。"""
    name_insert = b"".join(_lt._encode_name(s) for s in new_names)
    header_delta = len(name_insert)          # uasset の増加分
    total_delta = header_delta + growth_uexp  # uasset+uexp の合計増加分

    P1 = h.import_offset  # = name table 終端
    new_uasset = bytearray(uasset_bytes[:P1] + name_insert + uasset_bytes[P1:])

    def patch_i32(o, v):
        struct.pack_into("<i", new_uasset, o, v)

    def patch_i64(o, v):
        struct.pack_into("<q", new_uasset, o, v)

    patch_i32(h.total_header_size_off, len(new_uasset))
    patch_i32(h.name_count_off, h.name_count + len(new_names))
    old_soft = struct.unpack_from("<i", uasset_bytes, h.soft_object_paths_offset_off)[0]
    patch_i32(h.soft_object_paths_offset_off, old_soft + header_delta)
    patch_i32(h.export_offset_off, h.export_offset + header_delta)
    patch_i32(h.import_offset_off, h.import_offset + header_delta)
    patch_i32(h.depends_offset_off, h.depends_offset + header_delta)
    # 番兵値(0/-1)はシフトしない(U25で確立済み)
    if h.soft_package_references_offset != 0:
        patch_i32(h.soft_package_references_offset_off,
                  h.soft_package_references_offset + header_delta)
    if h.searchable_names_offset != 0:
        patch_i32(h.searchable_names_offset_off, h.searchable_names_offset + header_delta)
    if h.thumbnail_table_offset != 0:
        patch_i32(h.thumbnail_table_offset_off, h.thumbnail_table_offset + header_delta)
    if h.asset_registry_data_offset != 0:
        patch_i32(h.asset_registry_data_offset_off,
                  h.asset_registry_data_offset + header_delta)
    patch_i64(h.bulk_data_start_offset_off, h.bulk_data_start_offset + total_delta)
    if h.world_tile_info_data_offset != 0:
        patch_i32(h.world_tile_info_data_offset_off,
                  h.world_tile_info_data_offset + header_delta)
    if h.preload_dependency_offset != 0:
        patch_i32(h.preload_dependency_offset_off,
                  h.preload_dependency_offset + header_delta)
    if h.payload_toc_offset != -1:
        patch_i64(h.payload_toc_offset_off, h.payload_toc_offset + header_delta)

    if new_names:
        _patch_name_count_side_fields(new_uasset, h, h.name_count + len(new_names))

    # ExportMap: SerialOffset は **uasset の増加分だけ** ずらす
    # (uexp の増加分を足すと二重計上になる — 先行実装が踏んだ罠)
    eoff = h.export_offset + header_delta
    for i in range(h.export_count):
        entry, eoff = _puh.parse_export_entry(new_uasset, eoff)
        so_off = entry["serial_size_offset"] + 8
        struct.pack_into("<q", new_uasset, so_off,
                         struct.unpack_from("<q", new_uasset, so_off)[0] + header_delta)
        if i == 0:
            ss_off = entry["serial_size_offset"]
            struct.pack_into("<q", new_uasset, ss_off,
                             struct.unpack_from("<q", new_uasset, ss_off)[0] + growth_uexp)
    return bytes(new_uasset)


# ------------------------------------------------------------ self check ---

def roundtrip_is_identical(uasset_bytes, uexp_bytes):
    """無編集で読んで書き戻したときに uexp がバイト完全一致するか。
    構造理解が正しいことの自己検査(組み込み先で安全に使えるかの判定)。"""
    mi = parse_mi_uexp(uexp_bytes)
    return _rebuild_uexp(uexp_bytes, mi) == bytes(uexp_bytes)
