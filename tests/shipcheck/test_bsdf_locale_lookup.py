# -*- coding: utf-8 -*-
"""dev#159 受入試験: 非英語ロケールでのBSDFノード名KeyError恒久修正。

対象: pipeline\\blender\\render_preview.py の replace_with_preview_materials()
      pipeline\\blender\\render_atlas_check.py の bind_atlas_to_all_slots()

背景(rd_124指摘(2)、dev#159): 両関数とも `m.node_tree.nodes["Principled BSDF"]`
のようにノードの**表示名**でBSDFノードを直引きしていた。Blenderの表示名は
UI言語(ロケール)+「新規データを翻訳」設定が有効だと翻訳される
(例: 日本語環境では "Principled BSDF" ではなく別の文字列になる)ため、
非英語ロケールのユーザー環境でKeyErrorが起き変換が落ちる。
正しいパターンは `step01_import_vrm.py:get_base_color()` の
`next(n for n in nodes if n.type == "BSDF_PRINCIPLED")`(type識別子はロケール非依存)。

このリポジトリに同梱されているBlender(tools\\blender-4.3.2-windows-x64)は
国際化言語パックを含まないポータブルビルドで、実際に
`bpy.context.preferences.view.language` を切り替えても新規ノード名が
翻訳されないことを実機で確認済み(UI言語を切り替える方式ではロケール依存の
再現ができない)。そのため本試験は、ロケール依存の**唯一の可変要素である
ノードの`.name`**を直接書き換えて模擬する: 実際の関数が内部で
`bpy.data.materials.new()` → `use_nodes = True` の順で自動生成するBSDFノードの
生成直後の`.name`を、翻訳された環境を模した非英語文字列へ差し替えたうえで、
対象関数(現物のソースをexecで取り出したもの)をそのまま呼ぶ。
`.type`(BSDF_PRINCIPLED)はロケールに関わらず不変なので、この模擬は
「表示名だけがロケールで変わる」という実際の不具合条件を忠実に再現している。

G1(赤): 修正**前**のソース(dev#159修正コミット8c2dea7の親=バグ現物。
        テストファイル内にリテラル埋め込み。理由は下記「自己無効化の教訓」参照)を
        ロケール模擬環境で実行するとKeyErrorになること。
G2(緑): 修正**後**のソース(現在のワーキングツリー)を同じロケール模擬環境で
        実行すると例外なく成功すること。
G3(負の対照): 修正後のソースを**ロケール模擬なし(英語locale相当)**で実行しても
        従来どおり成功すること(修正が通常経路を壊していないこと)。

Blenderが見つからない環境ではpytest.skip(理由付き)。

自己無効化の教訓(2026-07-31): 初版はG1のソースを `git show HEAD:...` で
取得していた。これはコミット時点(修正前)にしか正しく動かない仕掛けで、
このテスト自身が修正と同一コミットでmasterへマージされた結果、マージ後は
HEAD=修正後になりG1が恒久的に赤くなった(dev#159/PR#356で指摘されたが
未修正のままマージされ実際に発生・本WPで検出)。修正前ソースは
git履歴ではなく本ファイル内のリテラル文字列として固定する(CIの
shallow clone(fetch-depth既定1)でも壊れない)。
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
COVERAGE_DIR = os.path.join(REPO_ROOT, "tests", "coverage")
if COVERAGE_DIR not in sys.path:
    sys.path.insert(0, COVERAGE_DIR)
import matrix  # noqa: E402

BLENDER_EXE = matrix.resolve_blender_exe()

RENDER_PREVIEW_SCRIPT = os.path.join(REPO_ROOT, "pipeline", "blender", "render_preview.py")
RENDER_ATLAS_CHECK_SCRIPT = os.path.join(REPO_ROOT, "pipeline", "blender", "render_atlas_check.py")

WP_DIR = os.path.join(REPO_ROOT, "work", "issue_zero", "i159", "pytest_scratch")

# ロケール翻訳を模した非英語ノード名(実際の日本語Blenderが出しうる文字列の一例)
FAKE_LOCALIZED_NODE_NAME = "プリンシプルBSDF・ロケール模擬"

# 修正前(rd_124指摘の現物、dev#159修正コミット8c2dea7の親)のソース。
# git履歴からではなく本ファイル内のリテラルとして固定する(理由はモジュール
# docstring末尾「自己無効化の教訓」を参照)。
_OLD_RENDER_PREVIEW_SRC = r'''
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
            bsdf = m.node_tree.nodes["Principled BSDF"]
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
'''

_OLD_RENDER_ATLAS_CHECK_SRC = r'''
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
    bsdf = mat.node_tree.nodes["Principled BSDF"]
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
'''


# ============================================================================
# ロケール模擬つきでBSDF生成を横取りするラッパー。exec前にソース中の
# `bpy.data.materials.new(...)` 呼び出し1箇所を `_rig_new_material(...)` へ
# 差し替えて注入する。修正前後どちらのソースにも共通して存在する行なので
# 両方に効く(この呼び出し行自体は本WPの修正対象ではなく、直後の
# BSDFノード取得だけが修正対象のため)。
# ============================================================================

_RIG_HELPER_PY = (
    "def _rig_new_material(name, localize):\n"
    "    mat = bpy.data.materials.new(name)\n"
    "    mat.use_nodes = True\n"
    "    if localize:\n"
    "        node = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')\n"
    "        node.name = " + repr(FAKE_LOCALIZED_NODE_NAME) + "\n"
    "    return mat\n"
)

_RENDER_PREVIEW_CALL_SITE = 'bpy.data.materials.new(f"prev_{name}")'
_RENDER_PREVIEW_RIG_CALL = '_rig_new_material(f"prev_{name}", _D2P_LOCALIZE)'

_RENDER_ATLAS_CALL_SITE = 'bpy.data.materials.new("prev_atlas")'
_RENDER_ATLAS_RIG_CALL = '_rig_new_material("prev_atlas", _D2P_LOCALIZE)'


# ドライバ本体: CALL_SITE/RIG_CALL/RIG_HELPERは _DRIVER_WRAP_PY 側で
# モジュールグローバルとして先頭に埋め込まれる(このテンプレート内では
# 定義せず参照するだけ)。
_RUN_PREVIEW_BODY_PY = r'''
import json
import sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src_path = argv[0]
localize = argv[1] == "localize"
out_json = argv[2]

# render_preview.py本体は `sys.path.insert(0, dirname(__file__)); import vp_bl` で
# 同ディレクトリのvp_blを読む。ここではソースをスクラッチ領域にコピーして実行する
# ため、execのnsに渡す__file__はスクラッチ側を指してしまいvp_blが見つからない。
# 実物のpipeline\\blender\\をsys.pathへ足して解決する(ロケール修正の検証とは無関係な
# import解決の都合であり、テスト対象のロジックには影響しない)。
sys.path.insert(0, PIPELINE_BLENDER_DIR)

bpy.ops.wm.read_factory_settings(use_empty=True)

# 検体: "Body" マテリアルを持つメッシュ1個。texture=Noneの単色スロット
# (info["texture"]が無い側の分岐でもbsdf直引きに到達することを確認する)。
bpy.ops.mesh.primitive_cube_add(size=1.0)
obj = bpy.context.active_object
src_mat = bpy.data.materials.new("Body")
obj.data.materials.append(src_mat)

job = {"job_dir": "__unused__"}
meta = {"slots": {"Body": {"texture": None, "base_color": [0.25, 0.5, 0.75, 1.0]}}}

with open(src_path, encoding="utf-8") as f:
    src = f.read()
assert src.rstrip().endswith("main()"), "render_preview.pyの末尾形状が想定と違う"
src_no_main = src.rsplit("main()", 1)[0]
assert CALL_SITE in src_no_main, "想定した呼び出し箇所が見つからない: %r" % (CALL_SITE,)
src_rigged = RIG_HELPER + "\n" + src_no_main.replace(CALL_SITE, RIG_CALL, 1)

ns = {"__file__": src_path, "__name__": "d2p_render_preview_under_test",
      "_D2P_LOCALIZE": localize}

result = {"ok": False, "error": None, "error_type": None, "base_color": None}
try:
    exec(compile(src_rigged, src_path, "exec"), ns)
    replace_with_preview_materials = ns["replace_with_preview_materials"]
    replace_with_preview_materials(job, meta)
    new_mat = obj.material_slots[0].material
    bsdf = next(n for n in new_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    result["ok"] = True
    result["base_color"] = list(bsdf.inputs["Base Color"].default_value)
except Exception as e:  # noqa: BLE001 (意図的に全捕捉して赤緑判定に使う)
    result["error"] = str(e)
    result["error_type"] = type(e).__name__

with open(out_json, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print("[run_preview] wrote: %s ok=%s" % (out_json, result["ok"]))
'''

_RUN_ATLAS_BODY_PY = r'''
import json
import sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src_path = argv[0]
localize = argv[1] == "localize"
atlas_path = argv[2]
out_json = argv[3]

bpy.ops.wm.read_factory_settings(use_empty=True)

# 最小のアトラス画像(2x2)を用意する(bpy.data.images.loadは実ファイルが要る)。
img = bpy.data.images.new("atlas_src", 2, 2)
img.filepath_raw = atlas_path
img.file_format = "PNG"
img.save()
bpy.data.images.remove(img)

with open(src_path, encoding="utf-8") as f:
    src = f.read()
assert src.rstrip().endswith("main()"), "render_atlas_check.pyの末尾形状が想定と違う"
src_no_main = src.rsplit("main()", 1)[0]
assert CALL_SITE in src_no_main, "想定した呼び出し箇所が見つからない: %r" % (CALL_SITE,)
src_rigged = RIG_HELPER + "\n" + src_no_main.replace(CALL_SITE, RIG_CALL, 1)

ns = {"__file__": src_path, "__name__": "d2p_render_atlas_check_under_test",
      "_D2P_LOCALIZE": localize}

result = {"ok": False, "error": None, "error_type": None}
try:
    exec(compile(src_rigged, src_path, "exec"), ns)
    bind_atlas_to_all_slots = ns["bind_atlas_to_all_slots"]
    bind_atlas_to_all_slots(atlas_path)
    mat = bpy.data.materials.get("prev_atlas")
    result["ok"] = mat is not None and mat.use_nodes
except Exception as e:  # noqa: BLE001
    result["error"] = str(e)
    result["error_type"] = type(e).__name__

with open(out_json, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print("[run_atlas] wrote: %s ok=%s" % (out_json, result["ok"]))
'''

# CALL_SITE/RIG_CALL/RIG_HELPERをBlenderサブプロセス側のグローバルとして
# 先頭に埋め込み、本体(_RUN_*_BODY_PY)がそれを参照する形にする。
_DRIVER_WRAP_PY = """
CALL_SITE = {call_site}
RIG_CALL = {rig_call}
RIG_HELPER = {rig_helper}
PIPELINE_BLENDER_DIR = {pipeline_blender_dir}

{body}
"""


def _skip_if_no_blender():
    if not BLENDER_EXE:
        pytest.skip("Blenderが見つからない環境のためskip "
                     "(tests.coverage.matrix.resolve_blender_exe()が解決できなかった)")


def _write(name, content):
    os.makedirs(WP_DIR, exist_ok=True)
    path = os.path.join(WP_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _run_blender(script, args, log_path):
    cmd = [BLENDER_EXE, "--background", "--factory-startup",
           "--python-exit-code", "1", "--python", script, "--", *args]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    return r.returncode


def _read_log(log_path):
    with open(log_path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _run_preview_case(name, src_text, localize):
    _skip_if_no_blender()
    src_path = _write(f"src_preview_{name}.py", src_text)
    driver_script = _write(f"driver_preview_{name}.py", _DRIVER_WRAP_PY.format(
        call_site=repr(_RENDER_PREVIEW_CALL_SITE),
        rig_call=repr(_RENDER_PREVIEW_RIG_CALL),
        rig_helper=repr(_RIG_HELPER_PY),
        pipeline_blender_dir=repr(os.path.join(REPO_ROOT, "pipeline", "blender")),
        body=_RUN_PREVIEW_BODY_PY,
    ))
    out_json = os.path.join(WP_DIR, f"out_preview_{name}.json")
    log = os.path.join(WP_DIR, f"log_preview_{name}.log")
    rc = _run_blender(driver_script, [src_path, "localize" if localize else "plain", out_json], log)
    with open(out_json, encoding="utf-8") as f:
        result = json.load(f)
    result["_rc"] = rc
    result["_log"] = _read_log(log)
    return result


def _run_atlas_case(name, src_text, localize):
    _skip_if_no_blender()
    src_path = _write(f"src_atlas_{name}.py", src_text)
    atlas_path = os.path.join(WP_DIR, f"atlas_{name}.png")
    driver_script = _write(f"driver_atlas_{name}.py", _DRIVER_WRAP_PY.format(
        call_site=repr(_RENDER_ATLAS_CALL_SITE),
        rig_call=repr(_RENDER_ATLAS_RIG_CALL),
        rig_helper=repr(_RIG_HELPER_PY),
        pipeline_blender_dir=repr(os.path.join(REPO_ROOT, "pipeline", "blender")),
        body=_RUN_ATLAS_BODY_PY,
    ))
    out_json = os.path.join(WP_DIR, f"out_atlas_{name}.json")
    log = os.path.join(WP_DIR, f"log_atlas_{name}.log")
    rc = _run_blender(driver_script,
                       [src_path, "localize" if localize else "plain", atlas_path, out_json], log)
    with open(out_json, encoding="utf-8") as f:
        result = json.load(f)
    result["_rc"] = rc
    result["_log"] = _read_log(log)
    return result


# ============================================================================
# render_preview.py::replace_with_preview_materials()
# ============================================================================

def test_dev159_g1_red_old_preview_raises_keyerror_under_locale():
    r = _run_preview_case("old_localized", _OLD_RENDER_PREVIEW_SRC, localize=True)
    assert not r["ok"], (
        f"dev#159再現失敗: 修正前ソースがロケール模擬下でも成功してしまった"
        f"(rigが効いていない可能性): {r}")
    assert r["error_type"] == "KeyError", (
        f"想定と違う例外種別(KeyErrorのはず): {r}")


def test_dev159_g2_green_new_preview_succeeds_under_locale():
    with open(RENDER_PREVIEW_SCRIPT, encoding="utf-8") as f:
        new_src = f.read()
    r = _run_preview_case("new_localized", new_src, localize=True)
    assert r["ok"], (
        f"dev#159修正後もロケール模擬下でKeyError等が発生した: {r}")
    assert r["base_color"] == pytest.approx([0.25, 0.5, 0.75, 1.0], abs=1e-4), r


def test_dev159_g3_negative_control_new_preview_plain_locale_unaffected():
    with open(RENDER_PREVIEW_SCRIPT, encoding="utf-8") as f:
        new_src = f.read()
    r = _run_preview_case("new_plain", new_src, localize=False)
    assert r["ok"], f"負の対照(通常/英語ロケール相当)が修正後に壊れた: {r}"
    assert r["base_color"] == pytest.approx([0.25, 0.5, 0.75, 1.0], abs=1e-4), r


# ============================================================================
# render_atlas_check.py::bind_atlas_to_all_slots()
# ============================================================================

def test_dev159_g1_red_old_atlas_raises_keyerror_under_locale():
    r = _run_atlas_case("old_localized", _OLD_RENDER_ATLAS_CHECK_SRC, localize=True)
    assert not r["ok"], (
        f"dev#159再現失敗: 修正前ソースがロケール模擬下でも成功してしまった: {r}")
    assert r["error_type"] == "KeyError", f"想定と違う例外種別: {r}"


def test_dev159_g2_green_new_atlas_succeeds_under_locale():
    with open(RENDER_ATLAS_CHECK_SCRIPT, encoding="utf-8") as f:
        new_src = f.read()
    r = _run_atlas_case("new_localized", new_src, localize=True)
    assert r["ok"], f"dev#159修正後もロケール模擬下でKeyError等が発生した: {r}"


def test_dev159_g3_negative_control_new_atlas_plain_locale_unaffected():
    with open(RENDER_ATLAS_CHECK_SCRIPT, encoding="utf-8") as f:
        new_src = f.read()
    r = _run_atlas_case("new_plain", new_src, localize=False)
    assert r["ok"], f"負の対照(通常/英語ロケール相当)が修正後に壊れた: {r}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
