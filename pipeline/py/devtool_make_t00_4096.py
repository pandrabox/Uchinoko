# -*- coding: utf-8 -*-
"""【開発側1回きりの資産製造ツール】t00(単一アトラス用テクスチャ資産)を
2048x2048 から 4096x4096 へ作り直す。

*** これはエンドユーザーが実行するものではありません。***
配布物にもエンドユーザーの手順にも一切現れません。`pipeline\\py\\ue_archive\\
09_build_noue_variants.py`(noue用マテリアル資産をUEで焼くツール。dev#114で
pipeline\\ue\\から移設)と同じ
「開発側で資産を1回作ってリポジトリへ入れる」位置づけです。
**ただし本ツールは UE を使いません**(cook済みTexture2Dのバイト構造を
そのまま組み替えるだけ。純Python+numpy)。UEを使わない理由:
  - UEモードの変換は別件で preflight FAIL する既知の不具合がある
    (docs\\DEV_NOTES.md (25))ため、資産製造の経路として信頼できない
  - 出力が決定論的で、差分がレビューできる

なぜ必要か:
  `vp_texinject.inject_texture_file()` はアトラスPNGを **テンプレート資産の
  実解像度へリサイズ**する(vp_texinject.py の resize_nearest)。したがって
  アトラスを何ピクセルで作っても、t00 資産が 2048 のままなら実機解像度は
  2048 で頭打ちになる。単一マテリアル化で body/parka を1枚へ畳むと、
  1枚あたりに使える面積が減るため、t00 資産自体を 4096 にしないと画質が
  落ちる(work\\u50_equip\\out\\FINDINGS2.txt 3.2節)。

やること(cooked Texture2D のバイト構造。vp_core.parse_texture2d /
live_template._flatten_cooked_texture と同じ理解):
  1. プロパティブロック先頭の ImportedSize(int32 x2) を 2048 -> 4096
  2. FTexturePlatformData の SizeX/SizeY(PF_文字列の16バイト手前)を 4096
  3. NumMips を 12 -> 13 にし、先頭へ 4096x4096 のミップを1段追加する
     (中身は既存 mip0 をニアレストで2倍にしたもの。実運用では
      inject_texture_file が全ミップを上書きするため内容自体は重要ではない)
  4. 全ミップの abs_off(uasset+uexp を1本の仮想バイナリと見なした絶対
     オフセット)を新しい配置で計算し直す
  5. 全ミップを BULKDATA_ForceInlinePayload(flags=0x48)に揃える
     (.ubulk を使わない本プロジェクトの方針。実機実証済みの値)
  6. uasset 側の Export SerialSize と BulkDataStartOffset を更新する
     (live_template._patch_texture_uasset_serial_size と同じ)

使い方:
    python pipeline\\py\\devtool_make_t00_4096.py            # 上書き(バックアップ付き)
    python pipeline\\py\\devtool_make_t00_4096.py --out DIR  # 別の場所へ出す
    python pipeline\\py\\devtool_make_t00_4096.py --check    # 現状の解像度を見るだけ
"""
import argparse
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import live_template as lt  # noqa: E402
import vp_core  # noqa: E402
import vp_tex  # noqa: E402

ASSET_DIR = os.path.join(HERE, "noue_master", "pak_extract_extra",
                         "Player", "ModelMaterials", "MainShader")
# 元(2048)の資産はここへ退避しておく。pak_extract_extra の外に置くのは、
# あちらが noue_template_manifest.json の "project" 列挙でpakへ収録される
# 場所だから(余計なファイルを増やさない)。再実行はこの退避物を種にする。
SRC_DIR = os.path.join(HERE, "noue_master", "tex_src_2048")
TARGET_SIZE = 4096
INLINE_FLAGS = 0x48  # BULKDATA_SingleUse | BULKDATA_ForceInlinePayload(実機実証済み)


class UpscaleError(RuntimeError):
    pass


def _find_pf(data):
    i = data.find(b"PF_")
    while i >= 0:
        end = data.find(b"\x00", i)
        if i >= 4 and end > i:
            (slen,) = struct.unpack_from("<i", data, i - 4)
            if slen == end - i + 1:
                return i, data[i:end].decode("ascii")
        i = data.find(b"PF_", end)
    raise UpscaleError("PF_ string not found (not a Texture2D uexp)")


def _imported_size_offsets(uexp, old_size):
    """プロパティブロック(unversioned property)先頭にある ImportedSize
    (int32 x2)の位置を、ヘッダを実際にパースして求める。
    値が old_size と一致することを確認できた場合だけ返す(でなければ None)。"""
    try:
        import vp_matparam
        slots, off, _raw = vp_matparam._read_unversioned_header(uexp, 0)
    except Exception:
        return None
    if len(slots) < 2:
        return None
    # 先頭2値が連続indexの int32 で、両方 old_size ならそれが ImportedSize
    a, b = struct.unpack_from("<ii", uexp, off)
    if a == old_size and b == old_size and slots[0][0] + 1 == slots[1][0]:
        return off, off + 4
    return None


def upscale_texture(uasset, uexp, target=TARGET_SIZE):
    """cooked Texture2D の (uasset, uexp) を target x target へ作り直す。"""
    lay = vp_core.parse_texture2d(uexp)
    pf = lay["pixel_format"]
    old = lay["size_x"]
    if lay["size_x"] != lay["size_y"]:
        raise UpscaleError(f"only square textures are supported: {lay['size_x']}x{lay['size_y']}")
    if target <= old:
        raise UpscaleError(f"only upscaling is supported: {old} -> {target}")
    if target % old != 0:
        raise UpscaleError(f"only integer multiples are supported: {old} -> {target}")
    if pf not in vp_core.TEX_FORMATS:
        raise UpscaleError(f"unsupported pixel format: {pf}")

    n_new_levels = 0
    s = old
    while s < target:
        s *= 2
        n_new_levels += 1

    # --- 新しい上位ミップの画素を作る(既存 mip0 を整数倍のニアレストで拡大) ---
    import numpy as np  # noqa: F401  (vp_tex 経由で使う)
    m0 = lay["mips"][0]
    base_rgba = vp_tex.decode_dxt(uexp[m0["offset"]:m0["offset"] + m0["size"]],
                                 m0["w"], m0["h"], pf)
    new_top = []
    for lvl in range(n_new_levels, 0, -1):
        side = old * (2 ** lvl)
        img = vp_tex.resize_nearest(base_rgba, side, side) \
            if hasattr(vp_tex, "resize_nearest") else None
        if img is None:
            import vp_texinject
            img = vp_texinject.resize_nearest(base_rgba, side, side)
        new_top.append((side, vp_tex.encode(img, pf)))

    # --- uexp のミップリストを丸ごと組み直す ---
    pf_off, _pf = _find_pf(uexp)
    pos = uexp.find(b"\x00", pf_off) + 1
    first_mip, num_mips = struct.unpack_from("<ii", uexp, pos)
    header_end = pos + 8

    old_entries = []
    p = header_end
    for mi in range(num_mips):
        (flags,) = struct.unpack_from("<I", uexp, p)
        p += 4
        size64 = bool(flags & 0x2000)
        if size64:
            count, size_on_disk = struct.unpack_from("<qq", uexp, p)
            p += 16
        else:
            count, size_on_disk = struct.unpack_from("<ii", uexp, p)
            p += 8
        p += 8  # abs_off(再計算する)
        payload = b""
        if flags & 0x40:
            payload = bytes(uexp[p:p + count])
            p += count
        w, h, z = struct.unpack_from("<iii", uexp, p)
        p += 12
        if z != 1:
            raise UpscaleError(f"mip{mi}: z={z} (unsupported)")
        old_entries.append((size64, count, size_on_disk, payload, w, h, z))
    tail = bytes(uexp[p:])

    entries = []
    for side, blob in new_top:
        entries.append((False, len(blob), len(blob), blob, side, side, 1))
    entries += old_entries

    new_num_mips = len(entries)
    uasset_size = len(uasset)
    body = bytearray()
    running = header_end
    for (size64, count, size_on_disk, payload, w, h, z) in entries:
        if len(payload) != count:
            raise UpscaleError(f"payload length mismatch {w}x{h}: {len(payload)} != {count}")
        cf = 16 if size64 else 8
        new_local = running + 4 + cf + 8
        body += struct.pack("<I", INLINE_FLAGS)
        if size64:
            body += struct.pack("<qq", count, size_on_disk)
        else:
            body += struct.pack("<ii", count, size_on_disk)
        body += struct.pack("<q", uasset_size + new_local)
        body += payload
        body += struct.pack("<iii", w, h, z)
        running = new_local + count + 12

    new_uexp = bytearray(uexp[:header_end] + bytes(body) + tail)
    struct.pack_into("<ii", new_uexp, header_end - 8, first_mip, new_num_mips)
    struct.pack_into("<ii", new_uexp, pf_off - 16, target, target)
    imp = _imported_size_offsets(uexp, old)
    if imp:
        struct.pack_into("<ii", new_uexp, imp[0], target, target)
    new_uexp = bytes(new_uexp)

    new_uasset = lt._patch_texture_uasset_serial_size(uasset, len(new_uexp))

    # 自己検査: 組み直したものが既存パーサで矛盾なく読めること
    chk = vp_core.parse_texture2d(new_uexp)
    if chk["size_x"] != target or chk["size_y"] != target:
        raise UpscaleError("failed to rewrite SizeX/SizeY")
    if len(chk["mips"]) != new_num_mips:
        raise UpscaleError("mip count mismatch")
    if chk["uasset_size"] != len(new_uasset):
        raise UpscaleError(
            f"abs_off base does not match uasset size: {chk['uasset_size']} != {len(new_uasset)}")
    if chk["mips"][0]["w"] != target:
        raise UpscaleError("mip0 dimensions mismatch")
    return new_uasset, new_uexp, dict(
        old=old, new=target, mips=(num_mips, new_num_mips),
        uexp=(len(uexp), len(new_uexp)), imported_size_patched=bool(imp))


def _report(path):
    with open(path, "rb") as f:
        d = f.read()
    lay = vp_core.parse_texture2d(d)
    print(f"  {os.path.basename(path)}: {lay['pixel_format']} "
          f"{lay['size_x']}x{lay['size_y']} mips={len(lay['mips'])} uexp={len(d)}B")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="t00")
    ap.add_argument("--size", type=int, default=TARGET_SIZE)
    ap.add_argument("--out", default=None, help="出力先ディレクトリ(既定は同梱資産を上書き)")
    ap.add_argument("--check", action="store_true", help="現状の解像度を表示するだけ")
    a = ap.parse_args()

    # 種は tex_src_2048\ を優先(2回目以降の再実行でも 2048 から作り直せる)
    src_dir = SRC_DIR if os.path.exists(os.path.join(SRC_DIR, a.name + ".uexp")) else ASSET_DIR
    ua_p = os.path.join(src_dir, a.name + ".uasset")
    ue_p = os.path.join(src_dir, a.name + ".uexp")
    if a.check:
        for nm in ("t00", "t01"):
            p = os.path.join(ASSET_DIR, nm + ".uexp")
            if os.path.exists(p):
                _report(p)
        return 0

    with open(ua_p, "rb") as f:
        ua = f.read()
    with open(ue_p, "rb") as f:
        ue = f.read()
    new_ua, new_ue, info = upscale_texture(ua, ue, a.size)
    print(f"[t00-4096] {info['old']} -> {info['new']} / mips {info['mips'][0]} -> "
          f"{info['mips'][1]} / uexp {info['uexp'][0]} -> {info['uexp'][1]}B / "
          f"ImportedSize updated={info['imported_size_patched']}")

    out_dir = a.out or ASSET_DIR
    os.makedirs(out_dir, exist_ok=True)
    if out_dir == ASSET_DIR and src_dir == ASSET_DIR:
        os.makedirs(SRC_DIR, exist_ok=True)
        for ext in (".uasset", ".uexp"):
            dst = os.path.join(SRC_DIR, a.name + ext)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(ASSET_DIR, a.name + ext), dst)
                print(f"[t00-4096] backing up original (2048): {dst}")
    with open(os.path.join(out_dir, a.name + ".uasset"), "wb") as f:
        f.write(new_ua)
    with open(os.path.join(out_dir, a.name + ".uexp"), "wb") as f:
        f.write(new_ue)
    print(f"[t00-4096] writing to: {out_dir}")
    _report(os.path.join(out_dir, a.name + ".uexp"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
