# -*- coding: utf-8 -*-
r"""Blender headless: blendのメッシュごとの「マテリアルスロット割り当て」を
決定的なJSONに落とす(WP-C F4対応、検証官指摘 2026-07-28)。

背景: `dump_avatar_mesh.py` の三角形は material を body/parka の
**クラス(0/1)**でしか持たない(`[i0,i1,i2,material_class]`)。一方、下流の
`vp_atlas_uvbake.py` は `poly.material_index`(**スロット単位**)を読んで
スロットごとに別々のアトラスセルへUVを変換する。したがって「面のスロット
割り当てが m00↔m01 で入れ替わる」変化はメッシュダンプに現れないのに
pakを変える(ダイジェスト不変・pak可変=誤スキップの盲点)。
本スクリプトはその盲点を塞ぐため、オブジェクトごとに
    - スロット名の並び(material_slots)
    - 全ポリゴンの material_index 列のsha256
を出力する。中間ハッシュ(intermediate_hash.compute_intermediate_hash)の
コンポーネント `slots_{gender}` になる。

使い方(intermediate_hash._run_slot_dump から呼ばれる):
    blender --background --factory-startup -t 1 --python-exit-code 1 \
        --python dump_slot_assignments.py -- <blend> <out.json>
"""
import hashlib
import json
import sys

import bpy

sep = sys.argv.index("--")
blend_path = sys.argv[sep + 1]
out_path = sys.argv[sep + 2]

bpy.ops.wm.open_mainfile(filepath=blend_path)

out = {}
mesh_objs = sorted((o for o in bpy.data.objects if o.type == "MESH"),
                   key=lambda o: o.name)
for obj in mesh_objs:
    mesh = obj.data
    slot_names = [ms.material.name if ms.material else None
                  for ms in obj.material_slots]
    idx = [0] * len(mesh.polygons)
    mesh.polygons.foreach_get("material_index", idx)
    h = hashlib.sha256(",".join(map(str, idx)).encode("ascii"))
    out[obj.name] = {
        "slot_names": slot_names,
        "num_polygons": len(idx),
        "poly_material_index_sha256": h.hexdigest(),
    }

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, sort_keys=True)
print("[dump_slot_assignments] DONE objects=%d" % len(out))
