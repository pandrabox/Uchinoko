# -*- coding: utf-8 -*-
"""sanitizedpak Phase 2 Plan B: 復元時にstep01〜03を製品FBXへ再実行し、
再生ジオメトリをcooked頂点バッファへ注入するための共通ロジック。

vp_core.py(Phase 1/Stage A、リファクタ禁止)はインポートするだけで変更しない。
本モジュールは新規追加であり、sanitize_pak.py/restore_pak.pyのCLIには
まだ配線していない(2026-07-22時点ではPoC検証のみ。docs/REPORT_P2_2026-07-22.md
のPlan B節を参照)。

## 前提(実測で検証済み。docs/REPORT_P2_2026-07-22.md参照)
- cookedのローカル座標(cm) = (100*bx, -100*by, 100*bz)  (b=Blender側の位置、m単位)
- cookedタンジェント(FPackedNormal x2, TangentX+TangentZ)は
  「符号付きバイト値(2の補数)/127.0」で各成分を復号する(UEの一般的な
  0-255バイアス式ではない。本SK特有か要再検証だが実測でnormal dot=0.9954,
  tangent dot=0.9708, 符号(TangentZ.W)一致率99.0%を確認)
- cooked UVはBlenderのVに対し V_ue = 1 - V_blender (上原点/下原点の差)
- skin_weightのbone_idxは「セクション内ローカル索引(BoneMap)」経由。
  BoneMapはFSkelMeshSectionの TArray<uint16>(i32カウント接頭辞)として
  Indicesバッファより前に存在し、シグネチャ(カウント一致+全値<bone数+
  多様性)でほぼ一意に特定できる(find_bonemap)
- 頂点対応表(cooked_index -> avatar側(obj,vertex_index))は「位置最近傍」
  (UV最近傍より曖昧性が少ない。左右ミラーはUV空間でのみ衝突し、実座標では
  区別できるため)。実測: 100%が1cm以内で発見、うち約59%は0.3cm以上離れた
  次点が無い厳密一意、残りは「同一/近接位置の重複頂点」(ハード法線/UVシーム
  分割)で位置的に判別不能=どちらを選んでも視覚上ほぼ差が出ない
"""
import math
import struct


class BoneMapNotFoundError(RuntimeError):
    pass


# ------------------------------------------------------------ 座標・方向変換

def blender_pos_to_ue_cm(x, y, z):
    """Blender側位置(m)→cooked座標(cm)。実測で特定した剛体変換。"""
    return (100.0 * x, -100.0 * y, 100.0 * z)


def blender_dir_to_ue(x, y, z):
    """Blender側方向ベクトル(法線/タンジェント)→cooked座標系の単位ベクトル。"""
    v = (x, -y, z)
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-9:
        return v
    return (v[0] / n, v[1] / n, v[2] / n)


# --------------------------------------------------------------- BoneMap探索

def find_bonemap(data, index_buffer_offset, n_bones, required_len,
                 min_distinct_ratio=0.8):
    """FSkelMeshSection::BoneMap(TArray<uint16>、i32カウント接頭辞)を
    シグネチャ探索で特定する。Indicesバッファより前の領域のみ探索。

    required_len: skin_weightバッファで実際に使われている
      ローカルボーン索引の最大値+1(呼び出し側で集計する。これにより
      カウント一致という強い制約が使え、探索がほぼ一意に定まる)。

    戻り値: (count_field_offset, bonemap: tuple[int])
    例外: 候補が0件または複数件ならBoneMapNotFoundError
    """
    candidates = []
    limit = index_buffer_offset - 4
    for off in range(0, limit):
        (count,) = struct.unpack_from("<i", data, off)
        if count != required_len:
            continue
        arr_off = off + 4
        if arr_off + count * 2 > index_buffer_offset:
            continue
        vals = struct.unpack_from(f"<{count}H", data, arr_off)
        if not all(v < n_bones for v in vals):
            continue
        if len(set(vals)) < count * min_distinct_ratio:
            continue  # 単調/反復パターンは偽陽性(実測で確認済みの除外条件)
        candidates.append((off, vals))
    if len(candidates) != 1:
        raise BoneMapNotFoundError(
            f"BoneMap could not be uniquely determined: {len(candidates)} found required_len={required_len}")
    return candidates[0]


def used_local_bone_indices(data, skin_weight_info):
    """skin_weightバッファから実際に使われている(weight>0の)ローカル索引集合を返す。"""
    off = skin_weight_info["offset"]
    stride = skin_weight_info["stride"]
    maxinf = skin_weight_info["max_bone_influences"]
    numv = skin_weight_info["num_vertices"]
    used = set()
    for i in range(numv):
        raw = data[off + i * stride: off + i * stride + stride]
        idxs = raw[:maxinf]
        wts = raw[maxinf:]
        for bi, w in zip(idxs, wts):
            if w > 0:
                used.add(bi)
    return used


# ------------------------------------------------------------- 頂点対応表

def build_position_correspondence(cooked_positions, avatar_items, cell=5.0,
                                  accept_dist_cm=1.0):
    """cooked各頂点(UE座標cm)に対し、avatar_items(list of (key, (bx,by,bz))、
    key=任意のavatar側識別子でobj名+頂点indexのタプル等)から最近傍を
    位置(cm、blender_pos_to_ue_cm変換後)で探し、対応表を返す。

    戻り値: list[ key or None ] (cooked頂点indexと同じ並び。1cm以内に
      候補が無ければNone)
    実測(Stage B/Plan B PoC): 100%が1cm以内で発見。残存する「同一/近接位置の
    重複頂点」の曖昧性はここでは解消しない(先着優先。視覚上の実害は小さいと
    判断済み。docs/REPORT_P2_2026-07-22.md参照)。
    """
    grid = {}
    for key, (bx, by, bz) in avatar_items:
        ux, uy, uz = blender_pos_to_ue_cm(bx, by, bz)
        cell_key = (int(ux // cell), int(uy // cell), int(uz // cell))
        grid.setdefault(cell_key, []).append((key, (ux, uy, uz)))

    result = []
    for (cx, cy, cz) in cooked_positions:
        kx, ky, kz = int(cx // cell), int(cy // cell), int(cz // cell)
        best_key, best_d = None, None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for key, (ux, uy, uz) in grid.get((kx + dx, ky + dy, kz + dz), ()):
                        d = math.sqrt((ux - cx) ** 2 + (uy - cy) ** 2 + (uz - cz) ** 2)
                        if best_d is None or d < best_d:
                            best_d = d
                            best_key = key
        result.append(best_key if (best_d is not None and best_d <= accept_dist_cm) else None)
    return result


# ------------------------------------------------------------------- encode

def _clamp_signed_byte(f):
    b = int(round(f * 127))
    if b < -127:
        b = -127
    elif b > 127:
        b = 127
    return b & 0xFF


def encode_position(x, y, z):
    """Blender側位置(m) -> cooked position bytes(float32*3, 12byte)。"""
    ux, uy, uz = blender_pos_to_ue_cm(x, y, z)
    return struct.pack("<fff", ux, uy, uz)


def encode_tangent_pair(normal_xyz, tangent_xyz, bitangent_sign):
    """Blender側法線・タンジェント(m空間の方向ベクトル)+従法線符号から
    cookedタンジェントバッファ8byte(TangentX 4byte + TangentZ 4byte)を作る。
    実測で確定した「符号付きバイト/127」形式でエンコードする
    (docs/REPORT_P2_2026-07-22.md Plan B節参照)。TangentX.Wは未使用領域
    (実測で常に127=+1相当)なので127固定。"""
    n_ue = blender_dir_to_ue(*normal_xyz)
    t_ue = blender_dir_to_ue(*tangent_xyz)
    tanx = bytes([_clamp_signed_byte(t_ue[0]), _clamp_signed_byte(t_ue[1]),
                 _clamp_signed_byte(t_ue[2]), 127])
    sign_byte = 127 if bitangent_sign >= 0 else (256 - 127)
    tanz = bytes([_clamp_signed_byte(n_ue[0]), _clamp_signed_byte(n_ue[1]),
                 _clamp_signed_byte(n_ue[2]), sign_byte])
    return tanx + tanz


def encode_uv0(u, v_blender):
    """Blender側UV0 -> cooked UV0(half float u,v の2byte*2=4byte)。
    V_ue = 1 - V_blender(実測で確定。上原点/下原点の差)。"""
    return struct.pack("<ee", u, 1.0 - v_blender)


def encode_skin_weight(bone_weight_pairs, name_to_local_index, max_influences=8):
    """[(bone_name, weight), ...](Blender vertex group、任意個数)から
    cooked skin_weightバッファ16byte(ローカル索引8byte+ウェイト8byte、
    合計255)を作る。ローカルBoneMapに無いボーン名は影響を捨てて再正規化する。
    """
    local_pairs = []
    for name, w in bone_weight_pairs:
        li = name_to_local_index.get(name)
        if li is not None and w > 0:
            local_pairs.append((li, w))
    local_pairs.sort(key=lambda p: -p[1])
    local_pairs = local_pairs[:max_influences]
    total = sum(w for _, w in local_pairs) or 1.0
    byte_weights = [round(w / total * 255) for _, w in local_pairs]
    diff = 255 - sum(byte_weights)
    if byte_weights:
        byte_weights[0] += diff
    idxs = [li for li, _ in local_pairs] + [0] * (max_influences - len(local_pairs))
    wts = byte_weights + [0] * (max_influences - len(byte_weights))
    return bytes(idxs) + bytes(wts)
