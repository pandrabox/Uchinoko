# -*- coding: utf-8 -*-
"""U50-single 受入ゲート: **UVを焼き直した後のメッシュを実際にレンダリングする**。

2026-07-25の実機NG(顔が無地のグレーになる)は、「MIが1種類」「NG 0件」という
**構造の一致**をいくら確認しても捕まらなかった。UVが別のセルを指していても
構造はすべて正しいままだからである。よって**絵を見る**検証を受入条件に加える。

`converted\\preview_{gender}_stand.png`(アトラス化**前**、per-slotテクスチャで
描いた正解)と、本スクリプトが描く「アトラス化**後**のUV+アトラス画像」の絵が
**同じ見た目になること**が正しい受入条件。

`render_preview.py` と同じカメラ・同じポーズ・同じカラーマネジメント設定を
使う(比較可能にするため)。違うのは:
  - 開く .blend が `build\\atlas\\step02_{gender}_atlas.blend`(焼き直し後)
  - 全マテリアルスロットへ**アトラス画像1枚**を貼る(実機と同じ状態)

実行:
  blender --background --factory-startup --python-exit-code 1 --python render_atlas_check.py -- \\
      <blend> <atlas.png> <out.png>
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

TAG = "atlas_check"

# render_preview.py と同一に保つこと(比較可能性のため)
STAND_ARM_DROP_DEG = 65.0
PREVIEW_VIEW_TRANSFORM = "AgX"
PREVIEW_EXPOSURE = 1.0
PREVIEW_GAMMA = 1.3


def bind_atlas_to_all_slots(atlas_path):
    """全マテリアルスロットへアトラス画像を直結する(実機と同じ=単一マテリアル)。"""
    img = bpy.data.images.load(atlas_path)
    mat = bpy.data.materials.new("prev_atlas")
    mat.use_nodes = True
    # 非英語ロケールではノード表示名("Principled BSDF"相当)がローカライズ
    # されKeyErrorになる。type識別子で引く(step01_import_vrm.py:
    # get_base_color()と同じパターン、dev#159)。
    bsdf = next(n for n in mat.node_tree.nodes
                if n.type == "BSDF_PRINCIPLED")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    mat.node_tree.nodes.active = tex
    n = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            slot.material = mat
            n += 1
    print(f"[{TAG}] applied atlas to {n} slot(s): {atlas_path}")


def pose_arms_down(arm, deg):
    for bone_name, sign in (("upperarm_l", 1.0), ("upperarm_r", -1.0)):
        pb = arm.pose.bones.get(bone_name)
        if pb is None:
            continue
        rot = Matrix.Rotation(math.radians(sign * deg), 4, "Y")
        cur = arm.matrix_world @ pb.matrix
        trans = cur.translation.copy()
        new_m = rot @ cur
        new_m.translation = trans
        pb.matrix = arm.matrix_world.inverted() @ new_m
        bpy.context.view_layer.update()


def scene_bounds():
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    dg = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(dg)
        for corner in ev.bound_box:
            w = ev.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def render(name, cam_dir, out_path):
    lo, hi = scene_bounds()
    center = (lo + hi) / 2
    size = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = size * 1.25
    cam = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = center + cam_dir * size * 3
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    bpy.context.scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)
    print(f"[{TAG}] {out_path}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    if len(argv) < 3:
        raise RuntimeError("usage: ... -- <blend> <atlas.png> <out.png>")
    blend, atlas, out_png = argv[0], argv[1], argv[2]
    bpy.ops.wm.open_mainfile(filepath=blend)
    bind_atlas_to_all_slots(atlas)

    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "TEXTURE"
    sc.render.resolution_x = 700
    sc.render.resolution_y = 1000
    sc.render.film_transparent = False
    sc.view_settings.view_transform = PREVIEW_VIEW_TRANSFORM
    sc.view_settings.exposure = PREVIEW_EXPOSURE
    sc.view_settings.gamma = PREVIEW_GAMMA

    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    pose_arms_down(arm, STAND_ARM_DROP_DEG)
    render("CamStand", Vector((0, -1, 0)), out_png)


main()
