# -*- coding: utf-8 -*-
"""DiveToPalworld 共通コア: ジョブ設定・パス解決・pakインデックス・RefSkeletonパーサ。

このモジュールは標準ライブラリのみ使用(pip禁止)。Blender同梱Pythonでも
システムPythonでも動く。UE/Blenderの各工程はジョブJSON経由で疎結合。
"""

import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palworld_locate  # noqa: E402  公開issue #8対応(WP16): Palworld探索の唯一の場所

# ---------------------------------------------------------------- job / paths

# 後方互換の最終保険としてのみ残す(レジストリ/vdf探索が両方失敗した場合の
# 表示用フォールバック文字列。実在確認はしない = 決め打ちで信用しない)。
DEFAULT_PALWORLD_PAK = (
    r"C:\Program Files (x86)\Steam\steamapps\common\Palworld"
    r"\Pal\Content\Paks\Pal-Windows.pak")
DEFAULT_UE_ROOT = r"C:\Program Files\Epic Games\UE_5.1"


def load_job(job_json_path):
    """ジョブJSONを読み、既定値を補完して返す。job_dirはJSONの置き場所。

    WP16(公開issue #8): paths.palworld_pak がjob.jsonに無い場合(GUIが
    未解決だった/古いjob.json/手書き等)、決め打ちのCドライブパスへ黙って
    フォールバックせず、palworld_locate経由でレジストリ+Steamの
    libraryfolders.vdfを探索する。見つからなければpaths.palworld_pakを
    Noneのままにし、job["_palworld_pak_search_error"]に「探した場所」つきの
    メッセージを残す(呼び出し側=extract_vanilla.py/convert_noue.pyが
    存在チェック時にこれを使ってユーザー向けの明確なエラーを出す)。
    job.jsonに明示指定があれば、それを常に最優先で尊重する(setdefaultなので
    既存の値は上書きしない)。
    """
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    job["job_dir"] = os.path.dirname(os.path.abspath(job_json_path))
    paths = job.setdefault("paths", {})
    if not paths.get("palworld_pak"):
        try:
            paths["palworld_pak"] = palworld_locate.find_palworld_pak()
        except palworld_locate.PalworldNotFoundError as e:
            paths["palworld_pak"] = None
            job["_palworld_pak_search_error"] = str(e)
    paths.setdefault("ue_root", DEFAULT_UE_ROOT)
    job.setdefault("genders", ["Male", "Female"])
    job.setdefault("shoulder_offset_deg", 0.0)
    job.setdefault("merge_fingers", False)
    job.setdefault("merge_eyes", True)
    job.setdefault("drop_bones", [])
    # FBX入力時のボーン対応表(Unity輸出)。未指定ならFBXの隣を自動探索
    job.setdefault("humanoid_json", None)
    # 揺れ髪(既定OFF 2026-07-21深夜に実機で「揺れない」と確定):
    # 実装自体は完動(SpringBone自動読込→バニラ髪チェーンへ載せ替え→表示は完璧)だが、
    # バニラ髪SKは素のメッシュで、揺れはゲーム本体側の未解明の仕組みが駆動しており
    # 差し替えメッシュには効かなかった。ぱん裁定「こだわりじゃないので諦める」。
    # 再挑戦するならPost-Process AnimBP(エンジン標準AnimDynamics)方式 — DEV_NOTES参照
    job.setdefault("hair_sway", False)
    job.setdefault("hair_bones", [])
    # 揺れもの実験: 指定ボーン(チェーン順)のウェイトをバニラ服揺れチェーン
    # (OldCloth001_04..07)へ載せ替える。docs\sway_design.md参照
    job.setdefault("sway_cloth_bones", [])
    job.setdefault("unlit", False)
    # dev#157 / WP-I157(2026-07-30): サイズ可変(スケルトン一様スケール)。
    # 隠し設定(GUI未露出、CLI/job.json手書き専用)。root不動点で全ボーンの
    # ローカルTranslationをk倍する(build_avatar_variant.apply_uniform_scale
    # 参照)。既定1.0は無条件で完全no-op(pakバイト不変)
    job.setdefault("uniform_scale", 1.0)
    # 全マテリアルを強制両面にする(裏面が透けるモデル対策)。
    # 既定ON(2026-07-21ぱん裁定): 透け事故ゼロを優先。負荷増はプレイヤー1体分なので実害なし
    job.setdefault("force_two_sided", True)
    # 影の持ち上げ量 k = 0.0(=影そのまま)〜1.0(=実質アンリット)。
    # BaseColor×(1-k) + Emissive×k の配合で影の底を明るくする
    # (U50-unify で live_template._unify_slot_materials が実装。
    #  k=1.0 で実機の環境光被りが消える=真のunlit、work\u50_unify\shadow_metrics.txt)。
    # **GUI表示の「影の濃さ」は 1-k(向きが逆)**。GUI 30% == k=0.7。
    # 既定 0.7(2026-07-26 責任者裁定「k=0.7でいったん固定」。GUI側の
    #  スライダ既定も 30% = k=0.7 に揃えてある)。
    job.setdefault("shadow_lift", 0.7)
    job.setdefault("avatar_name", "Avatar")
    return job


def job_subdir(job, *parts):
    d = os.path.join(job["job_dir"], *parts)
    os.makedirs(d, exist_ok=True)
    return d


def unrealpak_exe(job):
    return os.path.join(job["paths"]["ue_root"],
                        "Engine", "Binaries", "Win64", "UnrealPak.exe")


# ------------------------------------------------------------------ pak index

PAK_MAGIC = 0x5A6F12E1

# dev#220(2026-07-30): build_live_template()は同一プロセス内でread_pak_index/
# read_pak_entries/read_pak_compression_methods(いずれも同一pak_pathに対する
# 決定的な読み取り専用パース)を短時間に複数回呼ぶ(実測: 1回のtemplate_prepで
# read_pak_entriesだけで5回、うち1回あたり1.2〜3秒 = 合計15秒超)。pakファイルは
# 呼び出し間で変化しない前提のため、(絶対パス, mtime_ns, size)をキーにプロセス内
# メモ化する。ファイルが変化すればキーも変わるため誤ヒットはしない。出力は
# 従来と完全に同じ値(参照が使い回されるだけ)。
_PAK_PARSE_CACHE = {}


def _pak_cache_key(path):
    st = os.stat(path)
    return (os.path.abspath(path), st.st_mtime_ns, st.st_size)


def _pak_cached(path, kind, builder):
    key = (kind,) + _pak_cache_key(path)
    if key in _PAK_PARSE_CACHE:
        return _PAK_PARSE_CACHE[key]
    result = builder()
    _PAK_PARSE_CACHE[key] = result
    return result


def _read_fstring(f):
    (n,) = struct.unpack("<i", f.read(4))
    if n == 0:
        return ""
    if n > 0:
        return f.read(n)[:-1].decode("ascii", errors="replace")
    return f.read(-n * 2)[:-2].decode("utf-16-le", errors="replace")


def read_pak_compression_methods(path):
    """pak footerのFPakInfo.CompressionMethods配列を読む(読み取り専用、プロセス内
    メモ化あり=_pak_cached、dev#220)。返り値: {圧縮方式コード: 方式名の文字列}。"""
    return _pak_cached(path, "compression_methods",
                        lambda: _read_pak_compression_methods_uncached(path))


def _read_pak_compression_methods_uncached(path):
    """pak footerのFPakInfo.CompressionMethods配列を読む(読み取り専用)。
    返り値: {圧縮方式コード: 方式名の文字列}。コード0は常に"None"(暗黙、配列には
    含まれない)。実測(2026-07-23、Pal-Windows.pak): IndexHash(20byte)の直後、
    bEncryptedIndex/EncryptionKeyGuidフィールドは無く、いきなり32byte固定長×
    最大5枠のASCII名(null終端・0パディング)が続く。空枠(先頭byteが0)は無視する。"""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        tail_len = min(4096, size)
        f.seek(size - tail_len)
        tail = f.read()
        i = tail.rfind(struct.pack("<I", PAK_MAGIC))
        if i < 0:
            raise RuntimeError(f"pak magic not found: {path}")
        magic_pos_abs = size - tail_len + i
        f.seek(magic_pos_abs)
        footer = f.read(size - magic_pos_abs)

    pos = 4 + 4 + 8 + 8  # magic, version, index_offset, index_size
    pos += 20  # index_hash(SHA1)
    methods = {0: "None"}
    code = 1
    name_len = 32
    while pos + name_len <= len(footer):
        raw = footer[pos:pos + name_len]
        pos += name_len
        if raw[0] == 0:
            break
        methods[code] = raw.split(b"\x00", 1)[0].decode("ascii")
        code += 1
    return methods


def read_pak_entries(path):
    """pak v11の各エントリの実データ位置を返す(sanitizedpakの注入座標系、プロセス内
    メモ化あり=_pak_cached、dev#220)。返り値: (mount, {エントリパス: {...}})"""
    return _pak_cached(path, "entries",
                        lambda: _read_pak_entries_uncached(path))


def _read_pak_entries_uncached(path):
    """pak v11の各エントリの実データ位置を返す(sanitizedpakの注入座標系)。
    返り値: (mount, {エントリパス: {"offset","size","csize","compression",
    "data_offset","blocks","block_size","encrypted"}})
    data_offset = pak先頭からの実データ位置(エントリ先頭のローカルヘッダの直後)。
    非圧縮エントリなら data_offset..+size がそのままuexp等の生バイト。
    圧縮エントリ(compression!=0)は"blocks"(entry["offset"]からの相対(start,end)の
    リスト)と"block_size"(1ブロックの解凍後バイト数、最終ブロックのみ端数)を
    参照し、ブロックごとに解凍して連結する(pak_live_extract.py参照)。

    dev#220: 以前はread_pak_index(path)を呼んでmountだけを取り出し、FullDirectory
    Indexを丸ごと(paths一覧として)再構築してから捨てていた(1回あたり数百ms、
    185000エントリ規模のpakで実測)。read_pak_index相当のヘッダ解析はこの関数
    自身がこの直後で(エントリオフセット取得のため)結局もう一度行うので、
    mountはこちらの読み取りからそのまま得れば重複が丸ごと消せる。"""
    # FullDirectoryIndexのencoded entry infoではなく、各エントリのローカルヘッダを
    # 直接読む方が堅い。インデックスを再走査してエントリオフセットを取る
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        tail_len = min(4096, size)
        f.seek(size - tail_len)
        tail = f.read()
        i = tail.rfind(struct.pack("<I", PAK_MAGIC))
        f.seek(size - tail_len + i + 8)
        index_offset, index_size = struct.unpack("<qq", f.read(16))
        f.seek(index_offset)
        idx = io.BytesIO(f.read(index_size))
        mount = _read_fstring(idx)
        idx.read(4 + 8)
        (has_phi,) = struct.unpack("<i", idx.read(4))
        if has_phi:
            phi_offset, phi_size = struct.unpack("<qq", idx.read(16))
            idx.read(20)
        (has_fdi,) = struct.unpack("<i", idx.read(4))
        fdi_offset, fdi_size = struct.unpack("<qq", idx.read(16))
        idx.read(20)
        # encoded pak entries(インデックス末尾のエントリ情報ブロック)
        (n_enc,) = struct.unpack("<i", idx.read(4))
        enc = idx.read(n_enc)

        # FullDirectoryIndexからパス→encodedオフセットを取る
        f.seek(fdi_offset)
        fdi = io.BytesIO(f.read(fdi_size))
        (num_dirs,) = struct.unpack("<i", fdi.read(4))
        entries = {}
        for _ in range(num_dirs):
            d = _read_fstring(fdi)
            (n_files,) = struct.unpack("<i", fdi.read(4))
            for _ in range(n_files):
                fn = _read_fstring(fdi)
                (enc_off,) = struct.unpack("<i", fdi.read(4))
                entries[d + fn] = enc_off

        result = {}
        for p, enc_off in entries.items():
            if enc_off < 0 or enc_off + 4 > len(enc):
                continue  # 特殊値(-1等)は対象外
            # encoded entry: Flags(u32) [offset(u32|u64)] [uncomp(u32|u64)] [comp(...)]
            (flags,) = struct.unpack_from("<I", enc, enc_off)
            pos = enc_off + 4
            comp_method = (flags >> 23) & 0x3F
            if flags & (1 << 31):     # 32bit safe offset
                (offset,) = struct.unpack_from("<I", enc, pos); pos += 4
            else:
                (offset,) = struct.unpack_from("<Q", enc, pos); pos += 8
            if flags & (1 << 30):     # 32bit safe uncompressed size
                (usize,) = struct.unpack_from("<I", enc, pos); pos += 4
            else:
                (usize,) = struct.unpack_from("<Q", enc, pos); pos += 8
            if comp_method != 0:
                if flags & (1 << 29):
                    (csize,) = struct.unpack_from("<I", enc, pos); pos += 4
                else:
                    (csize,) = struct.unpack_from("<Q", enc, pos); pos += 8
            else:
                csize = usize
            # ローカルヘッダ(FPakEntryのシリアライズ)の直後が実データ。
            # v11非圧縮: offset(8)+csize(8)+usize(8)+method(4)+hash(20)+
            #            compblocks(none)+encrypted(1)+blocksize(4) = 53
            local_header = 53
            blocks = None
            block_size = None
            encrypted = False
            if comp_method != 0:
                # 圧縮時はブロック配列が挟まる(count4 + 16/block)。ブロックの
                # (start,end)はoffset(このエントリのローカルヘッダ先頭)からの相対位置
                f.seek(offset + 24 + 4 + 20)
                (n_blocks,) = struct.unpack("<i", f.read(4))
                blocks = [struct.unpack("<qq", f.read(16)) for _ in range(n_blocks)]
                (encrypted_byte,) = struct.unpack("<B", f.read(1))
                encrypted = bool(encrypted_byte)
                (block_size,) = struct.unpack("<I", f.read(4))
                local_header = 24 + 4 + 20 + 4 + n_blocks * 16 + 1 + 4
            result[p] = {"offset": offset, "size": usize, "csize": csize,
                         "compression": comp_method,
                         "data_offset": offset + local_header,
                         "blocks": blocks, "block_size": block_size,
                         "encrypted": encrypted}
        return mount, result


def read_pak_index(path):
    """pak v11のFullDirectoryIndexを読み (mount, [パス...]) を返す(読み取り専用、
    プロセス内メモ化あり=_pak_cached、dev#220)。"""
    return _pak_cached(path, "index", lambda: _read_pak_index_uncached(path))


def _read_pak_index_uncached(path):
    """pak v11のFullDirectoryIndexを読み (mount, [パス...]) を返す(読み取り専用)。"""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        tail_len = min(4096, size)
        f.seek(size - tail_len)
        tail = f.read()
        i = tail.rfind(struct.pack("<I", PAK_MAGIC))
        if i < 0:
            raise RuntimeError(f"pak magic not found: {path}")
        f.seek(size - tail_len + i + 8)
        index_offset, index_size = struct.unpack("<qq", f.read(16))
        f.seek(index_offset)
        idx = io.BytesIO(f.read(index_size))
        mount = _read_fstring(idx)
        idx.read(4 + 8)  # num_entries, seed
        (has_phi,) = struct.unpack("<i", idx.read(4))
        if has_phi:
            idx.read(36)
        (has_fdi,) = struct.unpack("<i", idx.read(4))
        if not has_fdi:
            raise RuntimeError("no FullDirectoryIndex")
        fdi_offset, fdi_size = struct.unpack("<qq", idx.read(16))
        f.seek(fdi_offset)
        fdi = io.BytesIO(f.read(fdi_size))
        (num_dirs,) = struct.unpack("<i", fdi.read(4))
        paths = []
        for _ in range(num_dirs):
            d = _read_fstring(fdi)
            (n_files,) = struct.unpack("<i", fdi.read(4))
            for _ in range(n_files):
                fn = _read_fstring(fdi)
                fdi.read(4)
                paths.append(d + fn)
        return mount, paths


# ------------------------------------------------- cooked Texture2D mip parser
# 実測レイアウト(2026-07-21深夜、t00.uexpのダンプで特定 — devtools\dump_tex_layout.py):
#   ... SizeX(i32) SizeY(i32) PackedData(u32) FString"PF_xxx"
#       FirstMipToSerialize(i32) NumMips(i32)
#   各ミップ: FByteBulkData = flags(u32) count(i32) size(i32) offset(i64)
#             + payload(インライン直付け) + SizeX(i32) SizeY(i32) SizeZ(i32)
#   count/sizeはi32(flagsにBULKDATA_Size64Bit=0x2000が無い)。旧走査が0件だったのは
#   ここをi64と誤仮定していたため。offsetは「uassetヘッダサイズ+uexp内ローカル位置」の
#   絶対値(t00実測: uasset=721, mip0ローカル125 → 846)。
#   uexp末尾はPACKAGE_FILE_TAG(0x9E2A83C1)。

PACKAGE_FILE_TAG = 0x9E2A83C1
TEX_FORMATS = {"PF_DXT1": ("DXT1", 8), "PF_DXT5": ("DXT5", 16)}


def parse_texture2d(uexp_path_or_bytes):
    """cooked Texture2D uexpのミップ実体領域を返す(sanitize 0フィル/restore注入の座標)。
    返り値: {"pixel_format","size_x","size_y","uasset_size","mips":[{"offset","size","w","h"}]}
    offsetはuexp内ローカル。uasset_sizeはミップのoffset絶対値から逆算した検算用。"""
    if isinstance(uexp_path_or_bytes, (bytes, bytearray)):
        data = bytes(uexp_path_or_bytes)
    else:
        with open(uexp_path_or_bytes, "rb") as f:
            data = f.read()

    # PF_文字列(FStringのlen整合で実物だけ採用)
    pf_off = -1
    i = data.find(b"PF_")
    while i >= 0:
        end = data.find(b"\x00", i)
        if i >= 4 and end > i:
            (slen,) = struct.unpack_from("<i", data, i - 4)
            if slen == end - i + 1:
                pf_off = i
                break
        i = data.find(b"PF_", end)
    if pf_off < 0:
        raise RuntimeError("PF_ string not found (not a Texture2D uexp?)")
    pf = data[pf_off:data.find(b"\x00", pf_off)].decode("ascii")
    size_x, size_y = struct.unpack_from("<ii", data, pf_off - 16)

    pos = data.find(b"\x00", pf_off) + 1
    first_mip, num_mips = struct.unpack_from("<ii", data, pos)
    pos += 8
    if not (0 <= first_mip <= 16 and 1 <= num_mips <= 20):
        raise RuntimeError(f"invalid mip count: first={first_mip} num={num_mips}")

    mips = []
    uasset_size = None
    for mi in range(num_mips):
        (flags,) = struct.unpack_from("<I", data, pos)
        pos += 4
        if flags & 0x2000:  # BULKDATA_Size64Bit(実物では未観測)
            count, size_on_disk = struct.unpack_from("<qq", data, pos)
            pos += 16
        else:
            count, size_on_disk = struct.unpack_from("<ii", data, pos)
            pos += 8
        (abs_off,) = struct.unpack_from("<q", data, pos)
        pos += 8
        if not (flags & 0x40):  # BULKDATA_ForceInlinePayload
            raise RuntimeError(f"mip{mi}: not an inline payload (flags=0x{flags:x})")
        if count != size_on_disk or count <= 0 or pos + count > len(data):
            raise RuntimeError(f"mip{mi}: size mismatch count={count} size={size_on_disk}")
        local = pos
        pos += count
        w, h, z = struct.unpack_from("<iii", data, pos)
        pos += 12
        if z != 1 or not (1 <= w <= 16384 and 1 <= h <= 16384):
            raise RuntimeError(f"mip{mi}: invalid dimensions {w}x{h}x{z}")
        if pf in TEX_FORMATS:
            bs = TEX_FORMATS[pf][1]
            expected = ((w + 3) // 4) * ((h + 3) // 4) * bs
            if expected != count:
                raise RuntimeError(
                    f"mip{mi}: {pf} expected size {expected} != actual {count} ({w}x{h})")
        ua = abs_off - local
        if uasset_size is None:
            uasset_size = ua
        elif ua != uasset_size:
            raise RuntimeError(f"mip{mi}: offset basis drifted ({ua} != {uasset_size})")
        mips.append({"offset": local, "size": count, "w": w, "h": h})

    (tag,) = struct.unpack_from("<I", data, len(data) - 4)
    if tag != PACKAGE_FILE_TAG:
        raise RuntimeError("uexp tail is not PACKAGE_FILE_TAG (parse offset may be wrong)")
    return {"pixel_format": pf, "size_x": size_x, "size_y": size_y,
            "uasset_size": uasset_size, "mips": mips}


# ------------------------------------------------ cooked SkeletalMesh vertex buffers
# 実測レイアウト(2026-07-22、devtools\dump_sk_layout.py方式のダンプ+UE公開実装
# (gildor2/UEViewer社UnMesh4.cpp)照合で特定。60体全SKで検証済み):
#
# FStaticLODModel4::SerializeRenderItem 相当(UE4.19+のcooked専用パス)のうち、
# 頂点バッファ群は次の並びで**連続**している(境界に余計なフィールドは無い):
#   FMultisizeIndexContainer(Indices) → FPositionVertexBuffer4
#     → FStaticMeshVertexBuffer4(Tangent+UV分離ストリーム, UE4.19+形式)
#     → FSkinWeightVertexBuffer(UE5 "Unlimited Bone Influences" メタデータ形式)
#
# Indices: DataSize(u8, 2 or 4) ElementSize(i32,==DataSize) Count(i32, 3の倍数)
#          + 生データ(Count*DataSize バイト)。このシグネチャはuexp内で一意
#          (60体全数で1件のみヒット)なので、Sections配列を解析せずこれを
#          アンカーにできる(Sectionsは版依存フィールドが多く不使用)。
#
# Position: Stride(i32=12) NumVertices(i32) ElemSize(i32=12) ArrayNum(i32=NumVertices)
#           + FVector3f[NumVertices](12byte×N、cm単位ローカル座標)
#
# Tangent+UV: StripFlags(2byte) NumTexCoords(i32) NumVertices(i32)
#             bUseFullPrecisionUVs(i32 bool) bUseHighPrecisionTangentBasis(i32 bool)
#           → Tangentストリーム: ItemSize(i32) ItemCount(i32=NumVertices) + 生データ
#             (ItemSize=8: FPackedNormal×2 = TangentX+TangentZ。ImportBasisは
#             bUseHighPrecisionTangentBasisで16に変わりうるが未実測)
#           → UVストリーム: ItemSize(i32) ItemCount(i32=NumVertices*NumTexCoords) + 生データ
#             (ItemSize=4: half×2 / bUseFullPrecisionUVsなら8: float×2。実測は半精度)
#
# SkinWeight: StripFlags(2byte) bVariableBonesPerVertex(i32 bool)
#             MaxBoneInfluences(i32) NumBones(i32、意味未特定・実測255632で無視)
#             NumVertices(i32) bUse16BitBoneIndex(i32 bool)
#           → 生データBulkSerialize: ElemSize(i32=1) Count(i32=NumVertices*2*MaxBoneInfluences)
#             + 生バイト(頂点毎に BoneIndex[MaxBoneInfluences] + BoneWeight[MaxBoneInfluences]、
#             各1byte。重みは0..255でBoneWeightの合計が255)
#             (bVariableBonesPerVertex/bUse16BitBoneIndexがTrueの形式は本ツール未対応)
#
# これらの後にColorVertexBuffer/AdjacencyIndexBuffer/末尾フィールドが続くが
# 本ツールでは使わないため未解析(devtools\test_sk_parser.pyのコメント参照)。


class SkMeshParseError(RuntimeError):
    pass


# dev#220(2026-07-30): 元実装はuexp全バイト(場合により数MB)を1バイトずつPythonの
# forループで舐め、毎回data[off]の値チェックだけ行っていた(実測: SK 1件あたり
# 平均約95ms、114件で約10.8秒 = template_prepの最大単一犯の一つ)。
# 最初の条件(datasize in (2,4))は「その1バイトの値が2か4である」という単純な
# 述語なので、re(Cで実装された正規表現エンジン)のfinditerで該当バイトの位置だけを
# 先に列挙し、struct.unpack_from以降の重い検証はヒットした位置だけに絞る。
# 見つかる候補集合・順序(offの昇順)は元のforループと完全に同一(同じoff範囲
# [0, n-9)を同じ条件で走査しているだけで、フィルタの実行順を変えていない)。
_SK_IDX_DATASIZE_RE = re.compile(rb"[\x02\x04]")


def _find_sk_index_buffer_candidates(data):
    """FMultisizeIndexContainerのシグネチャ(DataSize+ElemSize+Count)をuexp全体から
    探し、条件を満たす全候補をリストで返す(件数チェックは呼び出し側の責務)。"""
    n = len(data)
    candidates = []
    endpos = max(0, n - 9)
    for m in _SK_IDX_DATASIZE_RE.finditer(data, 0, endpos):
        off = m.start()
        datasize = data[off]
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


def _find_sk_index_buffer(data):
    """FMultisizeIndexContainerのシグネチャ(DataSize+ElemSize+Count)をuexp全体から探す。
    一意ヒットのみ採用(複数/0件ならエラー)。

    U18実測: 真のバニラPalworld衣装SK(圧縮モーフターゲット持ち、
    docs\\REPORT_U18_2026-07-23.md参照)では、モーフターゲットの圧縮バイト列内に
    このシグネチャへ偶然一致する箇所が生じることがあり、候補が2件以上になる
    ケースが実測で見つかった(例: SK_Player_Female_Outfit_Hunter001、正しい候補
    offset=592118 count=197754 の他に、ファイル末尾寄りのoffset=2398978
    count=6630が誤検出された)。この関数自体は「一意ヒットのみ」という既存契約を
    変えない(research\\ue_exit\\build_hair_topology_variant.pyがこの関数を
    monkeypatchして差し替える設計に依存しているため)。曖昧性の解消は
    `parse_skeletalmesh_buffers`側で複数候補を実際に下流までパースしてみて
    整合するものを選ぶ方式に委ねる(`_find_sk_index_buffer_candidates`参照)。"""
    candidates = _find_sk_index_buffer_candidates(data)
    if len(candidates) != 1:
        raise SkMeshParseError(
            f"index buffer signature is not unique: {len(candidates)} found {candidates[:5]}")
    return candidates[0]


def parse_skeletalmesh_buffers(uexp_path_or_bytes):
    """cooked SkeletalMesh uexpの頂点バッファ実体領域を返す(sanitize 0フィル/
    restore注入の座標)。返り値のoffset/sizeはuexp内ローカル絶対位置。
    座標系・検証根拠は本関数直前のコメント参照。

    U18実測: 圧縮モーフターゲットを持つ真のバニラSK(docs\\REPORT_U18_2026-07-23.md
    参照)では、index bufferのシグネチャ走査(_find_sk_index_buffer_candidates)が
    ファイル後方のモーフターゲット圧縮バイト列に偶然一致し、複数候補が
    見つかることがある。これ自体は「一意でなければエラー」という
    _find_sk_index_buffer()の契約は変えず、本関数側で候補を1件ずつ実際に
    下流(position/tangent/uv/skin_weightの整合性チェック)まで試し、
    最初に成功したものを採用する(誤検出候補は必ずposition以降のどこかで
    struct.error/SkMeshParseErrorになることを60/60実測で確認)。"""
    if isinstance(uexp_path_or_bytes, (bytes, bytearray)):
        data = bytes(uexp_path_or_bytes)
    else:
        with open(uexp_path_or_bytes, "rb") as f:
            data = f.read()

    candidates = _find_sk_index_buffer_candidates(data)
    if not candidates:
        raise SkMeshParseError("no index buffer signature found")
    errors = []
    for cand in candidates:
        try:
            return _parse_skeletalmesh_buffers_with_index(data, cand)
        except (SkMeshParseError, struct.error) as e:
            errors.append(f"{cand}: {e}")
    raise SkMeshParseError(
        f"downstream parsing failed for all {len(candidates)} index buffer candidate(s): {errors}")


def _parse_skeletalmesh_buffers_with_index(data, index_buffer_candidate):
    idx_off, idx_datasize, idx_count, idx_end = index_buffer_candidate
    pos = idx_end

    (stride, numv, elemsize, arraynum) = struct.unpack_from("<iiii", data, pos)
    if stride != 12 or elemsize != 12 or arraynum != numv:
        raise SkMeshParseError(
            f"position header mismatch: stride={stride} numv={numv} "
            f"elemsize={elemsize} arraynum={arraynum}")
    pos_off = pos + 16
    pos_size = arraynum * elemsize
    for i in range(numv):
        x, y, z = struct.unpack_from("<fff", data, pos_off + i * 12)
        if not (abs(x) < 500 and abs(y) < 500 and abs(z) < 500):
            raise SkMeshParseError(f"position vertex {i} is out of range: {(x, y, z)}")
    position = {"offset": pos_off, "size": pos_size, "num_vertices": numv, "stride": 12}

    p = pos_off + pos_size
    numtexcoords, numv2 = struct.unpack_from("<ii", data, p + 2)
    bfull, bhq = struct.unpack_from("<ii", data, p + 10)
    if numv2 != numv:
        raise SkMeshParseError(f"StaticMeshVertexBuffer vertex count mismatch: {numv2} != {numv}")
    if not (1 <= numtexcoords <= 8):
        raise SkMeshParseError(f"invalid NumTexCoords: {numtexcoords}")
    p2 = p + 18

    tang_item_size, tang_item_count = struct.unpack_from("<ii", data, p2)
    if tang_item_count != numv:
        raise SkMeshParseError(f"tangent item_count mismatch: {tang_item_count} != {numv}")
    tang_off = p2 + 8
    tang_size = tang_item_count * tang_item_size
    tangent = {"offset": tang_off, "size": tang_size, "num_vertices": numv,
               "stride": tang_item_size, "high_precision": bool(bhq)}

    tex_pos = tang_off + tang_size
    tex_item_size, tex_item_count = struct.unpack_from("<ii", data, tex_pos)
    if tex_item_count != numv * numtexcoords:
        raise SkMeshParseError(
            f"texcoord item_count mismatch: {tex_item_count} != {numv * numtexcoords}")
    tex_off = tex_pos + 8
    tex_size = tex_item_count * tex_item_size
    uv = {"offset": tex_off, "size": tex_size, "num_vertices": numv,
          "num_tex_coords": numtexcoords, "item_stride": tex_item_size,
          "full_precision": bool(bfull)}

    q = tex_off + tex_size
    qp = q + 2
    bvar, maxinf, _numbones, numv3, buse16 = struct.unpack_from("<iiiii", data, qp)
    if numv3 != numv:
        raise SkMeshParseError(f"skin weight vertex count mismatch: {numv3} != {numv}")
    if bvar or buse16:
        raise SkMeshParseError(
            "unsupported skin weight format (bVariableBonesPerVertex/bUse16BitBoneIndex)")
    if not (1 <= maxinf <= 8):
        raise SkMeshParseError(f"invalid max_bone_influences: {maxinf}")
    qp2 = qp + 20
    w_elemsize, w_count = struct.unpack_from("<ii", data, qp2)
    if w_elemsize != 1:
        raise SkMeshParseError(f"invalid skin weight elemsize: {w_elemsize}")
    if w_count != numv * 2 * maxinf:
        raise SkMeshParseError(f"skin weight byte count mismatch: {w_count} != {numv * 2 * maxinf}")
    w_off = qp2 + 8
    w_size = w_count
    skin_weight = {"offset": w_off, "size": w_size, "num_vertices": numv,
                   "max_bone_influences": maxinf, "stride": 2 * maxinf}

    return {
        "num_vertices": numv,
        "index_buffer": {"offset": idx_off, "end": idx_end,
                          "datasize": idx_datasize, "count": idx_count},
        "position": position,
        "tangent": tangent,
        "uv": uv,
        "skin_weight": skin_weight,
    }


# --------------------------------------------------- cooked RefSkeleton parser
# PalMod実証済みパーサ(usmap不要): NameMap読取+フィンガープリント走査

def read_names(uasset_path):
    """cooked uassetのNameMapを読む。"""
    with open(uasset_path, "rb") as f:
        data = f.read()
    if struct.unpack_from("<I", data, 0)[0] != 0x9E2A83C1:
        raise RuntimeError("uasset magic mismatch")
    off = 4
    legacy_ver = struct.unpack_from("<i", data, off)[0]
    off += 4
    if legacy_ver != -4:
        off += 4  # LegacyUE3Version
    off += 4  # FileVersionUE4
    if legacy_ver <= -8:
        off += 4  # FileVersionUE5
    off += 4  # FileVersionLicenseeUE
    (cv_count,) = struct.unpack_from("<i", data, off)
    off += 4 + cv_count * 20
    off += 4  # TotalHeaderSize
    (slen,) = struct.unpack_from("<i", data, off)
    off += 4
    off += slen if slen >= 0 else -slen * 2
    off += 4  # PackageFlags
    name_count, name_offset = struct.unpack_from("<ii", data, off)

    names = []
    off = name_offset
    for _ in range(name_count):
        (slen,) = struct.unpack_from("<i", data, off)
        off += 4
        if slen >= 0:
            s = data[off:off + slen - 1].decode("ascii", errors="replace")
            off += slen
        else:
            n = -slen * 2
            s = data[off:off + n - 2].decode("utf-16-le", errors="replace")
            off += n
        off += 4  # precalc hash
        names.append(s)
    return names


def find_refskeleton(uexp_path, names, with_offset=False, min_bones=40):
    """uexp内のFMeshBoneInfo配列+FTransform配列をフィンガープリントで探す。
    返り値: (bones[(name,parent_idx)], transforms[10要素], tsize)
    with_offset=True なら (data, bones名のみ, transform先頭オフセット) も返す。
    min_bones: 髪など小骨格のメッシュは下げる(既定40=プレイヤー衣装向け)。"""
    with open(uexp_path, "rb") as f:
        data = f.read()
    n_names = len(names)

    for off in range(0, len(data) - 16):
        (count,) = struct.unpack_from("<i", data, off)
        if not (min_bones <= count <= 400):
            continue
        pos = off + 4
        if pos + count * 12 > len(data):
            continue
        ok = True
        bones = []
        for i in range(count):
            idx, num, parent = struct.unpack_from("<iii", data, pos + i * 12)
            # FName番号: num>0 は「{base}_{num-1}」表示(髪SKのhairボーン等で実在)
            if not (0 <= idx < n_names) or not (0 <= num < 100000):
                ok = False
                break
            if i == 0 and parent != -1:
                ok = False
                break
            if i > 0 and not (0 <= parent < i):
                ok = False
                break
            name = names[idx] if num == 0 else f"{names[idx]}_{num - 1}"
            bones.append((name, parent))
        if not ok:
            continue
        tpos = pos + count * 12
        (tcount,) = struct.unpack_from("<i", data, tpos)
        if tcount != count:
            continue
        tpos += 4
        for fmt, size in (("<10d", 80), ("<10f", 40)):
            if tpos + count * size > len(data):
                continue
            vals0 = struct.unpack_from(fmt, data, tpos)
            qn = sum(v * v for v in vals0[0:4])
            if 0.99 < qn < 1.01:
                transforms = [struct.unpack_from(fmt, data, tpos + i * size)
                              for i in range(count)]
                if with_offset:
                    return bones, transforms, size, data, tpos
                return bones, transforms, size
        continue
    raise RuntimeError(f"RefSkeleton not found: {uexp_path}")


def load_refskel(uasset_path, min_bones=40):
    """uasset+uexpからRefSkeletonを dict{bone: {parent,quat,pos,scale}} で返す。"""
    names = read_names(uasset_path)
    uexp = uasset_path[:-7] + ".uexp"
    bones, transforms, tsize = find_refskeleton(uexp, names, min_bones=min_bones)
    out = {}
    for (name, parent), t in zip(bones, transforms):
        out[name] = {"parent": bones[parent][0] if parent >= 0 else None,
                     "quat": list(t[0:4]), "pos": list(t[4:7]),
                     "scale": list(t[7:10])}
    return out


def quat_angle_deg(q1, q2):
    import math
    dot = abs(sum(a * b for a, b in zip(q1, q2)))
    dot = min(1.0, max(-1.0, dot))
    return math.degrees(2 * math.acos(dot))


def die(tag, msg):
    print(f"[{tag}][FATAL] {msg}")
    sys.exit(1)


# ============================================================================
# U54 WP-B(2026-07-27): マシン共有キャッシュ(バニラ準備/ライブテンプレート)
# ----------------------------------------------------------------------------
# noueのバニラ準備(extract_vanilla.py)とlive_template.build_live_template()は
# **完全にアバター非依存**なのに、従来は出力先がjob_dir(work\<AvatarName>\)に
# 閉じており、アバターごとに毎回やり直していた。ここは kind("vanilla"/
# "live_template")非依存の共通インフラ(場所解決・fingerprintハッシュ化・
# クロスプロセスロック・read-only施錠)だけを持ち、何を作るか(builder)は
# 呼び出し側(extract_vanilla.py/live_template.py)の責務のまま。
# ============================================================================

CACHE_LOCK_STALE_SECONDS = 30 * 60  # このロックは意図的に長寿命(pak全走査は分単位)


def shared_cache_root(work_root):
    """共有キャッシュの基底ディレクトリ。env D2P_SHARED_CACHE で丸ごと上書き
    可能(試験・relgateの分離用、複数プロセスの並列実行がお互いを踏まないため)。
    既定は work_root(通常 work\\)直下の _shared_cache。"""
    override = os.environ.get("D2P_SHARED_CACHE")
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.abspath(work_root), "_shared_cache")


def job_work_root(job):
    """jobのwork_root(job_dirの親、GUIなら work\\)を返す。"""
    return os.path.dirname(os.path.abspath(job["job_dir"]))


def fingerprint_hash(fingerprint):
    """fingerprint(dict等、JSON化できる値)を安定した12桁hexへ変換する。
    dictのキー順に依存しないようsort_keysする。"""
    raw = json.dumps(fingerprint, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def sha256_file(path):
    """ファイル内容のsha256(chunk読み、大容量ファイルでもメモリ一定)。

    dev#226(WSBキャッシュ持ち込みゲート): 共有キャッシュのfingerprintを
    mtimeでなく内容で表すために使う。理由は実測で確認済み——配布zipを
    毎回まっさらなWindows Sandboxへ展開すると、展開先ファイルのmtimeは
    アーカイブ内タイムスタンプではなく「展開した瞬間の時刻」になる
    (Python標準zipfile.extractall()の挙動、2026-07-30実測)。そのため
    mtimeベースの識別子は同一内容でもSandbox起動のたびに変わってしまい、
    クリーン都度環境でのキャッシュ鮮度判定が原理的に成立しない。内容の
    sha256は展開位置・タイミングに一切依存せず安定する。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def shared_cache_dir(work_root, kind, fingerprint):
    """共有キャッシュのディレクトリパスを解決する(存在確認・作成はしない。
    呼び出し側がbuild/lock/read-only判定を行う)。
    <work_root>\\_shared_cache\\<kind>\\<fingerprint先頭12桁>\\
    (D2P_SHARED_CACHEで基底を丸ごと上書き可能)"""
    base = shared_cache_root(work_root)
    return os.path.join(base, kind, fingerprint_hash(fingerprint))


def _cache_lock_path(cache_dir):
    return cache_dir.rstrip("\\/") + ".lock"


def acquire_cache_lock(cache_dir, poll_interval=2.0, stale_seconds=CACHE_LOCK_STALE_SECONDS):
    """cache_dir単位のクロスプロセス排他ロックを取得する(PID+タイムスタンプ、
    stale判定30分、待ち側はポーリング)。GUIのwarmと変換の同時実行、
    relgate並列複数検体の同時実行で壊れないための唯一の排他機構。
    戻り値はロックファイルのパス(release_cache_lockへそのまま渡す)。"""
    lock_path = _cache_lock_path(cache_dir)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    waited = False
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "time": time.time()}, f)
            if waited:
                print(f"[vp_core] acquired shared cache lock: {lock_path}")
            return lock_path
        except FileExistsError:
            age = stale_seconds + 1  # 読めない/壊れたロックはstale扱い(安全側: 奪取)
            try:
                with open(lock_path, encoding="utf-8") as f:
                    info = json.load(f)
                age = time.time() - float(info.get("time", 0))
            except (OSError, ValueError, TypeError):
                pass
            if age > stale_seconds:
                print(f"[vp_core][WARN] shared cache lock is stale ({age:.0f}s ago, "
                      f"stale threshold {stale_seconds}s). Taking over: {lock_path}")
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
                continue
            if not waited:
                print(f"[vp_core] waiting for shared cache lock (another process is building it): {lock_path}")
                waited = True
            time.sleep(poll_interval)


def release_cache_lock(lock_path):
    try:
        os.remove(lock_path)
    except OSError:
        pass


def _set_tree_readonly(root, readonly):
    """root配下の全ファイル(ディレクトリ自体は対象外)にread-only属性を
    付与/解除する。in-place書き込みを即エラーで顕在化させる(silent
    corruptionをloud failureに変える)ためのもの。"""
    if not os.path.isdir(root):
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                mode = stat.S_IREAD if readonly else (stat.S_IREAD | stat.S_IWRITE)
                os.chmod(p, mode)
            except OSError:
                pass


def lock_cache_dir_readonly(cache_dir):
    """構築完了後、cache_dir配下の全ファイルをread-only化する(施錠)。"""
    _set_tree_readonly(cache_dir, True)


def unlock_cache_dir_for_write(cache_dir):
    """再構築/拡張の前にread-only属性を解除する(施錠解除)。
    呼び出し側がcache_dir単位のロックを保持していること前提。"""
    _set_tree_readonly(cache_dir, False)


def cache_tmp_dir(final_dir):
    """final_dirと同じ親ディレクトリに一時ディレクトリを作る(同一ボリューム内
    なので、その後のrename(_replace_dir_atomic)がコピーでなく本当のrenameになる)。"""
    parent = os.path.dirname(final_dir.rstrip("\\/"))
    os.makedirs(parent, exist_ok=True)
    return tempfile.mkdtemp(prefix="d2p_cache_tmp_", dir=parent)


def replace_dir_atomic(tmp_dir, final_dir):
    """tmp_dirをfinal_dirへ設置する(既存final_dirがあればread-only解除→
    退避→削除してから置き換える2段階rename)。呼び出し側がfinal_dir単位の
    ロックを保持していること前提であり、その間は他プロセスがfinal_dirの
    完成を判定できない(マーカー未設置)ため、この2段階の隙間による実害はない。"""
    if os.path.isdir(final_dir):
        _set_tree_readonly(final_dir, False)
        trash = final_dir.rstrip("\\/") + f".old-{os.getpid()}-{int(time.time() * 1000)}"
        os.replace(final_dir, trash)
        shutil.rmtree(trash, ignore_errors=True)
    os.replace(tmp_dir, final_dir)
