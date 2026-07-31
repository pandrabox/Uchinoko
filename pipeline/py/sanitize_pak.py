# -*- coding: utf-8 -*-
"""sanitizedpak生成CLI(配布者側)。

cooked抽出ツリー(pak_extract)のテクスチャ実体(全ミップ)を0フィルし、
recipe.json と 非圧縮sanitizedpak を出力する。あわせて検証用に
無加工ツリーからの非圧縮pak(reference_uncompressed.pak)も作る。

実行はBlender同梱Python(ピクセルハッシュにnumpy使用):
  python.exe sanitize_pak.py --extract <pak_extract> --textures <texturesフォルダ>
      --out <出力先> [--unrealpak <UnrealPak.exe>]

設計: docs\\sanitizedpak_design.md / docs\\restore_ui_design.md
- 配布するのは「構造だけのpak」: テクスチャ実体はゼロ。復元は restore_pak.py が
  recipe.jsonの座標へバイト注入する(UE非依存)
- 無改変復元の検知用に、元テクスチャの「ピクセルSHA1」(RGBAデコード後)を記録
  (ファイルSHA1ではない: PNG再保存でバイトが変わっても絵が同じなら一致する)
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core
import vp_tex
import vp_meshrestore as vmr

TAG = "sanitize"
RECIPE_FORMAT = "d2p-sanitized-recipe-1"
MOUNT_PREFIX = "..\\..\\..\\Pal\\Content\\Pal\\Model\\Character\\"
DEFAULT_UNREALPAK = (r"C:\Program Files\Epic Games\UE_5.1"
                     r"\Engine\Binaries\Win64\UnrealPak.exe")


def find_textures(extract):
    """抽出ツリーからTexture2Dのuexpを探す(parse_texture2dが通るものだけ)"""
    out = []
    for dirpath, _, files in sorted(os.walk(extract)):
        for fn in sorted(files):
            if not fn.lower().endswith(".uexp"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                info = vp_core.parse_texture2d(full)
            except Exception:
                continue
            out.append((os.path.relpath(full, extract), info))
    return out


def find_outfit_meshes(extract):
    """抽出ツリーからOutfit配下のSkeletalMesh uexpを探す(parse_skeletalmesh_buffersが
    通るものだけ)。Head/Hair/HeadEquipのダミーはバニラ由来なので対象外(パス絞り込み)。"""
    out = []
    outfit_marker = os.sep + "Outfit" + os.sep
    for dirpath, _, files in sorted(os.walk(extract)):
        if outfit_marker not in (dirpath + os.sep):
            continue
        for fn in sorted(files):
            if not fn.lower().endswith(".uexp"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                info = vp_core.parse_skeletalmesh_buffers(full)
            except vp_core.SkMeshParseError:
                continue
            out.append((os.path.relpath(full, extract), info))
    return out


def build_pak(unrealpak, tree, pak_path, rsp_path):
    """ツリー全体を非圧縮pakに詰める(順序決定的)"""
    lines = []
    for dirpath, _, files in sorted(os.walk(tree)):
        for fn in sorted(files):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, tree)
            lines.append(f'"{full}" "{MOUNT_PREFIX}{rel}"')
    with open(rsp_path, "w", encoding="ascii") as f:
        f.write("\n".join(lines))
    r = subprocess.run([unrealpak, pak_path, f"-Create={rsp_path}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        vp_core.die(TAG, f"UnrealPak failed exit={r.returncode}: {pak_path}\n"
                    + (r.stdout or "")[-2000:])
    return len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True, help="pak_extractフォルダ")
    ap.add_argument("--textures", required=True, help="元テクスチャPNGのフォルダ(t00.png等)")
    ap.add_argument("--out", required=True, help="出力フォルダ")
    ap.add_argument("--unrealpak", default=DEFAULT_UNREALPAK)
    ap.add_argument("--strip-vertices", action="store_true",
                    help="Outfit配下SKの頂点バッファ(位置/法線/UV/ウェイト)も0フィルする"
                         "(Phase 2)")
    ap.add_argument("--avatar-tangent-json-male", default=None,
                    help="Phase 2 Plan B: devtools/dump_fbx_tangent.py の出力"
                         "(sanitize時のAvatar_Male.fbx。SK_Player_Male_Outfit_*の"
                         "頂点対応表構築に使う。Male衣装が無いpakなら省略可)")
    ap.add_argument("--avatar-tangent-json-female", default=None,
                    help="同上、Avatar_Female.fbx側(SK_Player_Female_Outfit_*用)")
    ap.add_argument("--retarget-job", default=None,
                    help="Phase 2 Plan B: sanitize時のjob.json(復元側が同一の"
                         "step01〜03パラメータで再実行するためrecipeへ複製保存する。"
                         "パス類(paths)や購入者固有情報は含めない)")
    args = ap.parse_args()
    if args.strip_vertices and not (args.avatar_tangent_json_male
                                    or args.avatar_tangent_json_female):
        vp_core.die(TAG, "--strip-vertices requires at least one of "
                    "--avatar-tangent-json-male / -female (used to build the Plan B "
                    "vertex correspondence table. Both are required if the pak has "
                    "both Male and Female outfit SK)")

    os.makedirs(args.out, exist_ok=True)
    textures = find_textures(args.extract)
    if not textures:
        vp_core.die(TAG, f"no texture uexp found: {args.extract}")
    print(f"[{TAG}] {len(textures)} texture(s): "
          + ", ".join(rel for rel, _ in textures))

    # 0フィルしたstagingツリーを作る
    staging = os.path.join(args.out, "sanitized_extract")
    if os.path.exists(staging):
        shutil.rmtree(staging)
    shutil.copytree(args.extract, staging)

    recipe_textures = []
    for rel, info in textures:
        src_path = os.path.join(args.extract, rel)
        with open(src_path, "rb") as f:
            original = f.read()
        staged_path = os.path.join(staging, rel)
        data = bytearray(original)
        for m in info["mips"]:
            data[m["offset"]:m["offset"] + m["size"]] = b"\x00" * m["size"]
        with open(staged_path, "wb") as f:
            f.write(data)

        base = os.path.splitext(os.path.basename(rel))[0]
        png = os.path.join(args.textures, base + ".png")
        pixel = None
        if os.path.exists(png):
            w, h, rgba = vp_tex.decode_png(png)
            if (w, h) != (info["size_x"], info["size_y"]):
                print(f"[{TAG}][warn] {base}.png resolution {w}x{h} != "
                      f"cooked {info['size_x']}x{info['size_y']}")
            pixel = vp_tex.pixel_sha1(rgba)
        else:
            print(f"[{TAG}][warn] no original PNG ({png}) — unmodified detection disabled")

        recipe_textures.append({
            "entry": rel.replace("\\", "/"),
            "uexp_size": len(original),
            "sha1_original_uexp": hashlib.sha1(original).hexdigest(),
            "pixel_format": info["pixel_format"],
            "size_x": info["size_x"],
            "size_y": info["size_y"],
            "source_png": base + ".png",
            "pixel_sha1": pixel,
            "mips": info["mips"],
        })
        print(f"[{TAG}] zero-filled: {rel} "
              f"({info['pixel_format']} {info['size_x']}x{info['size_y']} "
              f"{len(info['mips'])}mips)")

    recipe_meshes = []
    vertex_correspondence = {}  # gender -> {source_entry, avatar_objects, table}
    avatar_items_by_gender = {}
    retarget_job_params = None
    if args.strip_vertices:
        meshes = find_outfit_meshes(args.extract)
        if not meshes:
            vp_core.die(TAG, f"no Outfit SK uexp found: {args.extract}")
        print(f"[{TAG}] {len(meshes)} Outfit SK: "
              + ", ".join(rel for rel, _ in meshes))

        # Plan B: 頂点対応表(cooked頂点index -> avatar側(obj,vertex_index))は
        # 性別ごとに別体系(Male/Femaleは実測で身体形状が別物、位置差最大107cm
        # ある個体を確認済み。同一表を使い回すと誤ったジオメトリを注入する)。
        # 各genderの最初のメッシュの「元(0フィル前)」データから位置最近傍で構築する
        gender_json = {"Male": args.avatar_tangent_json_male,
                       "Female": args.avatar_tangent_json_female}
        for gender, path in gender_json.items():
            if not path:
                continue
            with open(path, encoding="utf-8") as f:
                trows = json.load(f)
            positions = {}
            for row in trows:
                obj, vi = row[0], row[1]
                positions.setdefault((obj, vi), tuple(row[2:5]))
            avatar_items_by_gender[gender] = (positions, list(positions.items()))

        if args.retarget_job:
            with open(args.retarget_job, encoding="utf-8") as f:
                _job = json.load(f)
            retarget_job_params = {
                k: _job[k] for k in (
                    "avatar_name", "shoulder_offset_deg", "merge_fingers",
                    "merge_eyes", "unlit", "force_two_sided", "shadow_lift",
                    "drop_bones", "sway_cloth_bones")
                if k in _job
            }

        for rel, info in meshes:
            gender = ("Female" if "Female" in rel else
                      "Male" if "Male" in rel else None)
            if gender not in avatar_items_by_gender:
                vp_core.die(TAG, f"{rel}: avatar-tangent-json for gender={gender} "
                            "was not specified")
            avatar_positions, avatar_items = avatar_items_by_gender[gender]

            src_path = os.path.join(args.extract, rel)
            with open(src_path, "rb") as f:
                original = f.read()
            staged_path = os.path.join(staging, rel)
            data = bytearray(original)
            regions = {
                "position": info["position"],
                "tangent": info["tangent"],
                "uv": info["uv"],
                "skin_weight": info["skin_weight"],
            }
            if gender not in vertex_correspondence:
                pos_r = info["position"]
                cooked_positions = [
                    struct.unpack_from("<fff", original, pos_r["offset"] + i * 12)
                    for i in range(info["num_vertices"])]
                table = vmr.build_position_correspondence(cooked_positions, avatar_items)
                n_missing = sum(1 for t in table if t is None)
                if n_missing:
                    print(f"[{TAG}][warn] vertex correspondence table ({gender}): {n_missing}/{len(table)} "
                          f"not found within 1cm on the avatar side (based on {rel})")
                obj_names = sorted({obj for obj, _ in avatar_positions})
                obj_index = {name: i for i, name in enumerate(obj_names)}
                vertex_correspondence[gender] = {
                    "source_entry": rel.replace("\\", "/"),
                    "avatar_objects": obj_names,
                    "table": [[obj_index[t[0]], t[1]] if t is not None else None
                              for t in table],
                }
                print(f"[{TAG}] built vertex correspondence table ({gender}): "
                      f"{len(table) - n_missing}/{len(table)} (based on: {rel})")

            # Plan B: BoneMap(セクションローカル索引→RefSkeleton索引)は
            # skin_weightが0フィルされる前(=ここ、元バイトの間)にしか
            # 検出できない(0フィル後は必要なused_local_bone_indicesの
            # 手がかりが消える)ので、ここで検出してrecipeへ保存する
            uasset_src = src_path[:-5] + ".uasset"
            names = vp_core.read_names(uasset_src)
            bones, _, _ = vp_core.find_refskeleton(src_path, names, min_bones=40)
            bone_names = [b[0] for b in bones]
            used = vmr.used_local_bone_indices(original, info["skin_weight"])
            bone_map = None
            if used:
                required_len = max(used) + 1
                try:
                    _, bonemap_vals = vmr.find_bonemap(
                        original, info["index_buffer"]["offset"],
                        len(bone_names), required_len)
                    bone_map = list(bonemap_vals)
                except vmr.BoneMapNotFoundError as e:
                    print(f"[{TAG}][warn] failed to determine BoneMap ({rel}): {e}")

            for reg in regions.values():
                data[reg["offset"]:reg["offset"] + reg["size"]] = b"\x00" * reg["size"]
            with open(staged_path, "wb") as f:
                f.write(data)

            recipe_meshes.append({
                "entry": rel.replace("\\", "/"),
                "uexp_size": len(original),
                "sha1_original_uexp": hashlib.sha1(original).hexdigest(),
                "num_vertices": info["num_vertices"],
                "regions": {k: {"offset": v["offset"], "size": v["size"]}
                            for k, v in regions.items()},
                "gender": gender,
                "bone_names": bone_names,
                "bone_map": bone_map,
            })
            print(f"[{TAG}] zero-filled (vertices): {rel} (verts={info['num_vertices']})")

    recipe = {
        "format": RECIPE_FORMAT,
        "mount_prefix": MOUNT_PREFIX,
        "textures": recipe_textures,
        "meshes": recipe_meshes,
        "vertex_correspondence": vertex_correspondence,
        "retarget_job_params": retarget_job_params,
    }
    recipe_path = os.path.join(args.out, "recipe.json")
    with open(recipe_path, "w", encoding="utf-8") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)

    n1 = build_pak(args.unrealpak, staging,
                   os.path.join(args.out, "avatar.sanitizedpak"),
                   os.path.join(args.out, "sanitized.rsp"))
    n2 = build_pak(args.unrealpak, args.extract,
                   os.path.join(args.out, "reference_uncompressed.pak"),
                   os.path.join(args.out, "reference.rsp"))
    print(f"[{TAG}] done: avatar.sanitizedpak({n1}entries) / "
          f"reference_uncompressed.pak({n2}entries) / recipe.json")


if __name__ == "__main__":
    main()
