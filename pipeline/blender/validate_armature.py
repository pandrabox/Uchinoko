# -*- coding: utf-8 -*-
"""検証専用: RefSkeleton JSONから構築したアーマチュアが、PalModで実証済みの
PSKインポート産アーマチュア(1.0パッチ済み)と数値一致するかを照合する。

実行: blender --background --factory-startup --python-exit-code 1 --python validate_armature.py -- <job.json>
合格基準: 共通ボーンの位置差 < 0.05cm、回転差 < 0.1deg
"""

import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_bl
from vp_bl import core

PSK_PATH = r"C:\P\Work\PalMod\assets\from_palworld\SK_Player_OldCloth001_1_0patched.psk"
PSK_ADDON_ZIP = r"C:\P\Work\PalMod\tools\io_scene_psk_psa_v7.1.0.zip"


def main():
    job, _ = vp_bl.load_job_from_argv()
    bpy.ops.wm.read_factory_settings(use_empty=True)

    import json
    vanilla = os.path.join(job["job_dir"], "vanilla")
    with open(os.path.join(vanilla, "common_bones.json"), encoding="utf-8") as f:
        common = json.load(f)["common"]

    ours = vp_bl.build_pal_armature(
        os.path.join(vanilla, "refskel_male.json"), common, name="Ours")

    # PSKインポート(PalMod環境の検証用。製品パイプラインでは使わない)
    try:
        bpy.ops.import_scene.psk.get_rna_type()
    except Exception:
        bpy.ops.extensions.package_install_files(
            repo="user_default", filepath=PSK_ADDON_ZIP, enable_on_install=True)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.psk(filepath=PSK_PATH, scale=1.0)
    psk_arm = next(o for o in set(bpy.data.objects) - before
                   if o.type == "ARMATURE")

    worst_p, worst_r = (0.0, ""), (0.0, "")
    n = 0
    for name in common:
        b1 = ours.data.bones.get(name)
        b2 = psk_arm.data.bones.get(name)
        if b1 is None or b2 is None:
            print(f"  [skip] {name} (ours={b1 is not None} psk={b2 is not None})")
            continue
        dp = (b1.matrix_local.translation - b2.matrix_local.translation).length
        q1 = b1.matrix_local.to_quaternion()
        q2 = b2.matrix_local.to_quaternion()
        dr = math.degrees(q1.rotation_difference(q2).angle)
        dr = min(dr, 360 - dr)
        if dp > worst_p[0]:
            worst_p = (dp, name)
        if dr > worst_r[0]:
            worst_r = (dr, name)
        n += 1
    print(f"[validate] {n} bones compared")
    print(f"[validate] worst pos diff: {worst_p[0]:.4f}cm ({worst_p[1]})")
    print(f"[validate] worst rot diff: {worst_r[0]:.4f}deg ({worst_r[1]})")
    if worst_p[0] > 0.05 or worst_r[0] > 0.1:
        core.die("validate", "does not match the PSK-derived armature — re-check the coordinate transform convention")
    print("[validate] PASS — direct RefSkeleton construction is equivalent to the PSK method")


main()
