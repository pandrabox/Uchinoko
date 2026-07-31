# -*- coding: utf-8 -*-
"""Step04: 素のプレイヤーの顔・髪を消すためのダミー(極小)メッシュFBXを生成する。

実行: blender --background --factory-startup --python-exit-code 1 --python step04_make_dummies.py -- <job.json>
出力: converted/Dummy.fbx(headボーンに100%ウェイトの極小三角形。Head/Hair共用)

アーマチュアはバニラ値そのまま(チビ化しない)。ダミーは不可視なので
バインド位置はどうでもよく、PalModでも素の骨格で実証済み。
"""

import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_bl
from vp_bl import core

TAG = "step04"


def main():
    job, _ = vp_bl.load_job_from_argv()
    conv = core.job_subdir(job, "converted")
    vanilla = os.path.join(job["job_dir"], "vanilla")

    import json
    with open(os.path.join(vanilla, "common_bones.json"), encoding="utf-8") as f:
        common = json.load(f)["common"]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm = vp_bl.build_pal_armature(
        os.path.join(vanilla, "refskel_male.json"), common)

    head = arm.data.bones.get("head")
    if head is None:
        core.die(TAG, "no head bone")
    pos = arm.matrix_world @ head.head_local

    mesh = bpy.data.meshes.new("Dummy")
    s = 0.1  # 0.1cmの極小三角形
    mesh.from_pydata([pos, pos + Vector((s, 0, 0)), pos + Vector((0, s, 0))],
                     [], [(0, 1, 2)])
    obj = bpy.data.objects.new("Dummy", mesh)
    bpy.context.scene.collection.objects.link(obj)
    vg = obj.vertex_groups.new(name="head")
    vg.add([0, 1, 2], 1.0, "REPLACE")
    obj.parent = arm
    mod = obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm

    arm.name = "Armature"
    arm.data.name = "Armature"

    out = os.path.join(conv, "Dummy.fbx")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=out, use_selection=True, global_scale=0.01,
        apply_scale_options="FBX_SCALE_NONE", add_leaf_bones=False,
        armature_nodetype="NULL", bake_anim=False, mesh_smooth_type="FACE",
        path_mode="COPY", embed_textures=False)
    print(f"[{TAG}] exported: {out}")


main()
