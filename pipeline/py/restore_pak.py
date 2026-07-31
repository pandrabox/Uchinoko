# -*- coding: utf-8 -*-
"""sanitizedpak復元CLI(受領側・UE非依存)。

sanitizedpak + recipe.json + テクスチャPNG から完全pakを復元する。
UnrealPakは使わない: PNG→ミップ生成→DXT1/5エンコード(numpy)→
recipe座標へのバイト注入→pakエントリのSHA1更新、のみで完結する。

実行はBlender同梱Python(numpy必須):
  python.exe restore_pak.py --sanitized <avatar.sanitizedpak> --recipe <recipe.json>
      --png-dir <改変PNGのフォルダ> --out <出力pak>

開発検証用(元バイトをそのまま注入=バイト同一復元の機械検証):
  python.exe restore_pak.py ... --inject-original <pak_extractフォルダ>

無改変復元の禁止(2026-07-21ぱん裁定): 全スロットのピクセルSHA1が元と一致した
場合のみNG(最低1枚は改変必須)。判定は「だいたいでいい」位置づけ(UV未参照領域の
改変は素通りする)— 意思表示+抑止のゲート。
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core
import vp_tex
import vp_meshrestore as vmr

TAG = "restore"


def find_entry(entries, rel):
    """recipeのentry(抽出ツリー相対)をpakインデックスのフルパスへ後方一致で解決"""
    rel_posix = rel.replace("\\", "/")
    cands = [k for k in entries
             if k.replace("\\", "/").endswith("/" + rel_posix)
             or k.replace("\\", "/") == rel_posix]
    if len(cands) != 1:
        vp_core.die(TAG, f"could not uniquely resolve pak entry: {rel} (candidates {len(cands)})")
    return cands[0]


def restore_geometry_bytes(uexp_bytes, bone_names, bone_map, avatar_objects,
                           obj_names, table):
    """Plan B: recipeの頂点対応表(table: [[obj_idx, vertex_idx] or None, ...])と
    復元時ジオメトリダンプ(avatar_objects: {obj_name: [[x,y,z,u,v,nx,ny,nz,
    tx,ty,tz,bsign,[[bone_name,weight],...]], ...]})から頂点バッファを
    エンコードし、注入済みのuexpバイト列(bytearray)を返す。

    bone_names/bone_mapはrecipe(sanitize時、skin_weightが0フィルされる前に
    検出・保存されたもの)から渡す。**0フィル後のuexpからは再検出できない**
    (used_local_bone_indicesの手がかりが消えているため。過去にこれで
    ValueErrorを出した実例があるので、必ずrecipe側の値を使うこと)。
    戻り値: (data: bytearray, n_matched: int, n_total: int)
    """
    data = bytearray(uexp_bytes)
    r = vp_core.parse_skeletalmesh_buffers(bytes(data))
    numv = r["num_vertices"]
    pos_r, tan_r, uv_r, w_r = r["position"], r["tangent"], r["uv"], r["skin_weight"]
    if len(table) != numv:
        vp_core.die(TAG, f"correspondence table vertex count mismatch: table={len(table)} cooked={numv}")
    if not bone_map:
        vp_core.die(TAG, "recipe has no bone_map (re-run sanitize_pak.py with the latest version)")

    global_to_local = {}
    for li, gi in enumerate(bone_map):
        global_to_local.setdefault(gi, li)
    name_to_local = {bone_names[g]: l for g, l in global_to_local.items()}

    n_matched = 0
    for i in range(numv):
        entry = table[i]
        if entry is None:
            continue
        obj_idx, vi = entry
        obj_name = obj_names[obj_idx]
        rows = avatar_objects.get(obj_name)
        if rows is None or vi >= len(rows) or rows[vi] is None:
            continue
        x, y, z, u, v, nx, ny, nz, tx, ty, tz, bsign, weight_pairs = rows[vi]

        poff = pos_r["offset"] + i * 12
        data[poff:poff + 12] = vmr.encode_position(x, y, z)

        toff = tan_r["offset"] + i * tan_r["stride"]
        data[toff:toff + 8] = vmr.encode_tangent_pair((nx, ny, nz), (tx, ty, tz), bsign)

        uvoff = uv_r["offset"] + i * uv_r["num_tex_coords"] * uv_r["item_stride"]
        data[uvoff:uvoff + 4] = vmr.encode_uv0(u, v)

        woff = w_r["offset"] + i * w_r["stride"]
        data[woff:woff + 16] = vmr.encode_skin_weight(
            [(n, w) for n, w in weight_pairs], name_to_local)

        n_matched += 1

    return data, n_matched, numv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sanitized", required=True)
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--png-dir", default=None, help="改変テクスチャPNGのフォルダ")
    ap.add_argument("--out", required=True)
    ap.add_argument("--inject-original", default=None,
                    help="開発検証用: pak_extractから元バイトを注入")
    ap.add_argument("--restore-geometry-male", default=None,
                    help="Phase 2 Plan B: devtools/dump_restore_geometry.py の出力"
                         "(Avatar_Male.fbx側)。SK_Player_Male_Outfit_*に使う")
    ap.add_argument("--restore-geometry-female", default=None,
                    help="同上、Avatar_Female.fbx側。SK_Player_Female_Outfit_*に使う")
    ap.add_argument("--allow-unmodified", action="store_true",
                    help="無改変復元NGゲートを無効化(開発用)")
    args = ap.parse_args()
    if not args.inject_original and not args.png_dir:
        vp_core.die(TAG, "either --png-dir or --inject-original is required")

    with open(args.recipe, encoding="utf-8") as f:
        recipe = json.load(f)
    if recipe.get("format") != "d2p-sanitized-recipe-1":
        vp_core.die(TAG, f"unknown recipe format: {recipe.get('format')}")

    meshes = recipe.get("meshes", [])
    if (meshes and not args.inject_original
            and not (args.restore_geometry_male or args.restore_geometry_female)):
        vp_core.die(TAG, "a recipe containing meshes requires either --inject-original "
                    "(dev verification) or --restore-geometry-male/-female (Plan B production restore)")

    with open(args.sanitized, "rb") as f:
        pak = bytearray(f.read())
    _mount, entries = vp_core.read_pak_entries(args.sanitized)

    unmodified = []
    verified = 0
    for tex in recipe["textures"]:
        key = find_entry(entries, tex["entry"])
        e = entries[key]
        if e["compression"] != 0:
            vp_core.die(TAG, f"entry is not uncompressed: {key}")
        if e["size"] != tex["uexp_size"]:
            vp_core.die(TAG, f"uexp size mismatch: {key} "
                        f"pak={e['size']} recipe={tex['uexp_size']}")
        base = e["data_offset"]

        if args.inject_original:
            src = os.path.join(args.inject_original, tex["entry"])
            with open(src, "rb") as f:
                data = f.read()
            if len(data) != tex["uexp_size"]:
                vp_core.die(TAG, f"original uexp size mismatch: {src}")
            for m in tex["mips"]:
                pak[base + m["offset"]:base + m["offset"] + m["size"]] = \
                    data[m["offset"]:m["offset"] + m["size"]]
        else:
            png = os.path.join(args.png_dir, tex["source_png"])
            if not os.path.exists(png):
                vp_core.die(TAG, f"missing texture: {tex['source_png']} "
                            f"(place it in {args.png_dir})")
            w, h, rgba = vp_tex.decode_png(png)
            if (w, h) != (tex["size_x"], tex["size_y"]):
                vp_core.die(TAG, f"{tex['source_png']}: resolution {w}x{h} differs "
                            f"from expected {tex['size_x']}x{tex['size_y']}")
            if tex.get("pixel_sha1") and vp_tex.pixel_sha1(rgba) == tex["pixel_sha1"]:
                unmodified.append(tex["source_png"])
            mips = vp_tex.make_mips(rgba, len(tex["mips"]))
            for m, img in zip(tex["mips"], mips):
                blob = vp_tex.encode(img, tex["pixel_format"])
                if len(blob) != m["size"]:
                    vp_core.die(TAG, f"encoded size mismatch {m['w']}x{m['h']}: "
                                f"{len(blob)} != {m['size']}")
                pak[base + m["offset"]:base + m["offset"] + m["size"]] = blob

        # 復元uexpの検証(元バイト注入時はrecipeのSHA1と一致するはず)
        restored = bytes(pak[base:base + e["size"]])
        if args.inject_original:
            if hashlib.sha1(restored).hexdigest() != tex["sha1_original_uexp"]:
                vp_core.die(TAG, f"restored uexp does not match the original: {key}")
            verified += 1
        # pakローカルヘッダのエントリSHA1を更新
        # (v11非圧縮: offset8+csize8+usize8+method4 の直後20バイトがhash)
        hoff = e["offset"] + 28
        pak[hoff:hoff + 20] = hashlib.sha1(restored).digest()
        print(f"[{TAG}] injected: {tex['entry']} ({len(tex['mips'])}mips)")

    n = len(recipe["textures"])
    if (not args.inject_original and not args.allow_unmodified
            and n > 0 and len(unmodified) == n):
        vp_core.die(TAG, "all textures are identical to the original. Unmodified restore "
                    "is not allowed (use at least one modified texture)")

    mesh_verified = 0
    restore_geo_by_gender = {}
    for gender, path in (("Male", args.restore_geometry_male),
                         ("Female", args.restore_geometry_female)):
        if path:
            with open(path, encoding="utf-8") as f:
                restore_geo_by_gender[gender] = json.load(f)
    correspondence_by_gender = recipe.get("vertex_correspondence") or {}
    if (args.restore_geometry_male or args.restore_geometry_female) and not correspondence_by_gender:
        vp_core.die(TAG, "recipe has no vertex_correspondence "
                    "(re-run sanitize_pak.py --strip-vertices with the latest version)")

    for mesh in meshes:
        key = find_entry(entries, mesh["entry"])
        e = entries[key]
        if e["compression"] != 0:
            vp_core.die(TAG, f"entry is not uncompressed: {key}")
        if e["size"] != mesh["uexp_size"]:
            vp_core.die(TAG, f"uexp size mismatch: {key} "
                        f"pak={e['size']} recipe={mesh['uexp_size']}")
        base = e["data_offset"]

        if args.inject_original:
            src = os.path.join(args.inject_original, mesh["entry"])
            with open(src, "rb") as f:
                data = f.read()
            if len(data) != mesh["uexp_size"]:
                vp_core.die(TAG, f"original uexp size mismatch: {src}")
            for region in mesh["regions"].values():
                off, size = region["offset"], region["size"]
                pak[base + off:base + off + size] = data[off:off + size]

            restored = bytes(pak[base:base + e["size"]])
            if hashlib.sha1(restored).hexdigest() != mesh["sha1_original_uexp"]:
                vp_core.die(TAG, f"restored uexp does not match the original: {key}")
            mesh_verified += 1
            hoff = e["offset"] + 28
            pak[hoff:hoff + 20] = hashlib.sha1(restored).digest()
            print(f"[{TAG}] injected (vertices): {mesh['entry']} (verts={mesh['num_vertices']})")
        else:
            gender = mesh.get("gender")
            restore_geo = restore_geo_by_gender.get(gender)
            correspondence = correspondence_by_gender.get(gender)
            if restore_geo is None or correspondence is None:
                vp_core.die(TAG, f"{mesh['entry']}: gender={gender} has neither "
                            "--restore-geometry-{male,female} nor the recipe's "
                            "vertex_correspondence")
            uexp_bytes = bytes(pak[base:base + e["size"]])
            restored, n_matched, numv = restore_geometry_bytes(
                uexp_bytes, mesh.get("bone_names"), mesh.get("bone_map"),
                restore_geo["objects"],
                correspondence["avatar_objects"], correspondence["table"])
            pak[base:base + e["size"]] = restored
            mesh_verified += 1
            hoff = e["offset"] + 28
            pak[hoff:hoff + 20] = hashlib.sha1(bytes(restored)).digest()
            print(f"[{TAG}] injected (vertices/PlanB,{gender}): {mesh['entry']} "
                  f"({n_matched}/{numv} vertices)")

    with open(args.out, "wb") as f:
        f.write(pak)
    mode = "original byte injection" if args.inject_original else "PNG-encode injection"
    print(f"[{TAG}] done({mode}): {args.out}")
    if args.inject_original:
        print(f"[{TAG}] byte-identity verification (textures): {verified}/{n} PASS")
        if meshes:
            print(f"[{TAG}] byte-identity verification (meshes): {mesh_verified}/{len(meshes)} PASS")
    else:
        if unmodified:
            print(f"[{TAG}] unmodified slot(s): {unmodified} (allowed since at least one slot was modified)")
        if args.restore_geometry_male or args.restore_geometry_female:
            print(f"[{TAG}] Plan B vertex restore: {mesh_verified}/{len(meshes)} mesh(es) processed"
                  "(byte-identity verification not applicable. See devtools/test_planb_restore.py for position error etc.)")


if __name__ == "__main__":
    main()
