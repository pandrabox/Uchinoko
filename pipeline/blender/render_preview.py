# -*- coding: utf-8 -*-
"""プレビュー描画: 変換結果の目視確認用PNGを出す(肩スライダーのループ用)。

実行: blender --background --factory-startup --python-exit-code 1 --python render_preview.py -- <job.json> <Male|Female>
入力: converted/step02_{gender}.blend + avatar_meta.json + textures/
出力: converted/preview_{gender}_bind.png        (バインドポーズ=Tポーズ 正面)
      converted/preview_{gender}_stand.png       (立ち姿勢=腕下ろし 正面)
      converted/preview_{gender}_stand_side.png  (同 側面)

スペック: めり込み検出は自動判定せず、立ち姿勢+Aポーズのプレビューを人間が目視する。
"""

import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_bl
from vp_bl import core

TAG = "preview"

STAND_ARM_DROP_DEG = 65.0  # Tポーズから腕を下ろす角度(ゲーム内立ちの近似)

# U50: プレビュー較正(work\u50_preview\REPORT.md)。
# 現行プレビューは実機より暗く、とくに陰の底が沈む(実測: 素材別p10で実機の
# 58〜64%、暗いアバターではp10=18/255)。ユーザーが「自分のアバターが壊れて
# いる」と誤解するのを避けるため、カラーマネジメントで一律に持ち上げる。
#   exposure: シーン全体を+1段(明部・暗部を同率で持ち上げる)
#   gamma   : 1より大きくすると暗部ほど強く持ち上がる(陰の底上げ)
# view_transformはBlender 4.3の既定と同じAgXを明示指定する(将来Blenderの
# 既定が変わってもプレビューの見た目が動かないようにするための固定)。
# 実測(work\u50_preview\analysis\variant_stats.json、flatVer2 female_stand):
#   コート平均 156.7->198.0(実機204.1)、顔毛 136.8->184.1(実機202.0)
#   陰の底p10  コート124.7->174.9(実機193.7)、白飛び(>253)は0.0%
PREVIEW_VIEW_TRANSFORM = "AgX"
PREVIEW_EXPOSURE = 1.0
PREVIEW_GAMMA = 1.3


def replace_with_preview_materials(job, meta):
    """Workbenchで確実にテクスチャが出るよう、単純なImage Texture直結の
    マテリアルへ差し替える(プレビュー専用。step02のblendは保存しない)。"""
    tex_dir = os.path.join(job["job_dir"], "textures")
    cache = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            if slot.material is None:
                continue
            name = slot.material.name
            info = meta["slots"].get(name.split(".")[0])
            if info is None:
                continue
            if name in cache:
                slot.material = cache[name]
                continue
            m = bpy.data.materials.new(f"prev_{name}")
            m.use_nodes = True
            # 非英語ロケールではノード表示名("Principled BSDF"相当)が
            # ローカライズされKeyErrorになる。type識別子で引く
            # (step01_import_vrm.py:get_base_color()と同じパターン、dev#159)。
            bsdf = next(n for n in m.node_tree.nodes
                        if n.type == "BSDF_PRINCIPLED")
            if info["texture"]:
                tex = m.node_tree.nodes.new("ShaderNodeTexImage")
                img_path = os.path.join(tex_dir, info["texture"])
                if os.path.exists(img_path):
                    tex.image = bpy.data.images.load(img_path)
                m.node_tree.links.new(tex.outputs["Color"],
                                      bsdf.inputs["Base Color"])
                m.node_tree.nodes.active = tex
            else:
                bsdf.inputs["Base Color"].default_value = info["base_color"]
                m.diffuse_color = info["base_color"]
            cache[name] = m
            slot.material = m


def pose_arms_down(arm, deg):
    """upperarm_l/r をワールド前後軸まわりに回して腕を下ろす(ポーズのみ、
    バインド不変=ゲーム内でアニメが腕を動かすのと同じ経路)。"""
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


def clear_pose(arm):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
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
    job, rest = vp_bl.load_job_from_argv()
    gender = rest[0] if rest else "Male"
    conv = core.job_subdir(job, "converted")
    blend = os.path.join(conv, f"step02_{gender.lower()}.blend")
    if not os.path.exists(blend):
        core.die(TAG, f"step02 produced no output: {blend}")
    bpy.ops.wm.open_mainfile(filepath=blend)
    with open(os.path.join(conv, "avatar_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)

    replace_with_preview_materials(job, meta)

    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "TEXTURE"
    sc.render.resolution_x = 700
    sc.render.resolution_y = 1000
    sc.render.film_transparent = False
    # U50: 較正(上のPREVIEW_*定数のコメント参照)
    sc.view_settings.view_transform = PREVIEW_VIEW_TRANSFORM
    sc.view_settings.exposure = PREVIEW_EXPOSURE
    sc.view_settings.gamma = PREVIEW_GAMMA

    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    g = gender.lower()

    # 1) バインドポーズ(Tポーズ)正面
    render("CamBind", Vector((0, -1, 0)),
           os.path.join(conv, f"preview_{g}_bind.png"))
    # 2) 立ち姿勢(腕下ろし)正面+側面 — 肩まわりのめり込みを見る本命
    pose_arms_down(arm, STAND_ARM_DROP_DEG)
    render("CamStand", Vector((0, -1, 0)),
           os.path.join(conv, f"preview_{g}_stand.png"))
    render("CamStandSide", Vector((-1, 0, 0)),
           os.path.join(conv, f"preview_{g}_stand_side.png"))
    clear_pose(arm)


main()
