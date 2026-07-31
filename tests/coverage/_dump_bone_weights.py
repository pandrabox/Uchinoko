# -*- coding: utf-8 -*-
r"""Blender ヘッドレスから呼ぶ内部ヘルパ(probes.pick_drop_bone_candidate_weighted 専用)。

指定 .blend を開き、アーマチュアの各ボーン(子孫込み)について、
`pipeline\blender\step01_import_vrm.py::drop_bone_meshes()` と**同じ閾値**
(合計ウェイト>0.5)で「実際に削除対象になる頂点数」を実測し、JSON へ書き出す。

2026-07-26 発覚: 削除ボーン検査の自動候補選定(probes.pick_drop_bone_candidate)は
ボーン名だけで選んでおり、Humanoid以外に見えても実際には頂点ウェイトを一切
持たないボーン(fbx_flat_ma の cheek_L)を選んで「削除しても何も変わらない」
無意味な検査になっていた。名前ではなく実データで選ぶために本スクリプトを作った。

呼び出し: blender --background <blend> --python _dump_bone_weights.py -- <out_json> <normalized_humanoid_prefixes_json>
"""
import json
import sys

import bpy


def _normalize(name):
    return name.lower().replace("_", " ").replace(".", " ")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    out_json = argv[0]
    exclude_prefixes = json.loads(argv[1]) if len(argv) > 1 else []

    arm = None
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            arm = obj
            break

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]

    counts = {}
    if arm is not None:
        for bone in arm.data.bones:
            nb = _normalize(bone.name)
            if any(nb.startswith(p) for p in exclude_prefixes):
                continue
            targets = {bone.name}
            for child in bone.children_recursive:
                targets.add(child.name)
            total = 0
            for obj in meshes:
                idx = {vg.index for vg in obj.vertex_groups if vg.name in targets}
                if not idx:
                    continue
                total += sum(
                    1 for v in obj.data.vertices
                    if sum(g.weight for g in v.groups if g.group in idx) > 0.5
                )
            if total > 0:
                counts[bone.name] = total

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(counts, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
