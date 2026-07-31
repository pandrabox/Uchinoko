# -*- coding: utf-8 -*-
"""Blender工程の共通ヘルパー: ジョブ読込・パルアーマチュア構築・VRM Humanoidマップ。

パルアーマチュアはPSKを使わず、実行時抽出したRefSkeleton JSON(数値のみ)から
直接構築する。UE→Blenderの座標変換は M=diag(1,-1,1) の共役
(PalMod add_hair_bones/patch_psk_to_1_0 で較正・実証済みの規約)。
"""

import json
import os
import re
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "py"))
import vp_core as core  # noqa: E402


def blender_argv():
    """blender ... -- <args> の <args> 部分。"""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def load_job_from_argv():
    args = blender_argv()
    if not args:
        core.die("vp_bl", "no job JSON specified (-- job.json)")
    return core.load_job(args[0]), args[1:]


def die(tag, msg):
    core.die(tag, msg)


# ------------------------------------------------ パルアーマチュア構築(PSK不使用)

# UEワールド → Blenderワールド: 位置 p_b = M @ p_ue、回転 R_b = M R_ue M^-1
_M = Matrix(((1, 0, 0), (0, -1, 0), (0, 0, 1)))
_Minv = _M.inverted()


def _ue_world_chain(refskel):
    """RefSkeletonローカル値をUEワールドへ連鎖合成して {bone: (quat, pos)} を返す。"""
    world = {}

    def rec(name):
        if name in world:
            return world[name]
        b = refskel[name]
        q = Quaternion((b["quat"][3], b["quat"][0], b["quat"][1], b["quat"][2]))
        p = Vector(b["pos"])
        if b["parent"] is None or b["parent"] not in refskel:
            world[name] = (q, p)
        else:
            pq, pp = rec(b["parent"])
            world[name] = (pq @ q, pp + pq @ p)
        return world[name]

    for n in refskel:
        rec(n)
    return world


def build_pal_armature(refskel_path, common_bones, name="PalArmature"):
    """RefSkeleton JSONからパル骨格アーマチュアを構築する(cm単位)。
    common_bones に無いボーン(衣装固有クロスボーン)は作らない。"""
    with open(refskel_path, encoding="utf-8") as f:
        refskel = json.load(f)
    keep = [b for b in refskel if b in set(common_bones)]
    world = _ue_world_chain(refskel)

    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    for bone_name in keep:  # refskelは親→子順
        uq, up = world[bone_name]
        p = _M @ up
        q = (_M @ uq.to_matrix() @ _Minv).to_quaternion()
        b = eb.new(bone_name)
        b.head = (0, 0, 0)
        b.tail = (0, 4, 0)  # 長さ4cm(向きはmatrixで決まる)
        b.matrix = Matrix.LocRotScale(p, q, Vector((1, 1, 1)))
        parent = refskel[bone_name]["parent"]
        if parent and parent in eb:
            b.parent = eb[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[vp_bl] pal armature built: {len(keep)} bones from "
          f"{os.path.basename(refskel_path)}")
    return arm


# ------------------------------------------------------- VRM Humanoidマッピング

# VRM1(アドオンのsnake_case属性名) → パルボーン
VRM1_TO_PAL = {
    "hips": "pelvis", "spine": "spine_01", "chest": "spine_02",
    "upper_chest": "spine_03", "neck": "neck_01", "head": "head",
    "left_shoulder": "clavicle_l", "left_upper_arm": "upperarm_l",
    "left_lower_arm": "lowerarm_l", "left_hand": "hand_l",
    "right_shoulder": "clavicle_r", "right_upper_arm": "upperarm_r",
    "right_lower_arm": "lowerarm_r", "right_hand": "hand_r",
    "left_upper_leg": "thigh_l", "left_lower_leg": "calf_l",
    "left_foot": "foot_l", "left_toes": "ball_l",
    "right_upper_leg": "thigh_r", "right_lower_leg": "calf_r",
    "right_foot": "foot_r", "right_toes": "ball_r",
    # 指: VRM1の親指は Metacarpal/Proximal/Distal の3節
    "left_thumb_metacarpal": "thumb_01_l", "left_thumb_proximal": "thumb_02_l",
    "left_thumb_distal": "thumb_03_l",
    "right_thumb_metacarpal": "thumb_01_r", "right_thumb_proximal": "thumb_02_r",
    "right_thumb_distal": "thumb_03_r",
}
for _f_vrm, _f_pal in (("index", "index"), ("middle", "middle"),
                       ("ring", "ring"), ("little", "pinky")):
    for _s_vrm, _s_pal in (("proximal", "01"), ("intermediate", "02"),
                           ("distal", "03")):
        for _side, _sfx in (("left", "l"), ("right", "r")):
            VRM1_TO_PAL[f"{_side}_{_f_vrm}_{_s_vrm}"] = f"{_f_pal}_{_s_pal}_{_sfx}"

# VRM0(camelCase) → パルボーン
VRM0_TO_PAL = {
    "hips": "pelvis", "spine": "spine_01", "chest": "spine_02",
    "upperChest": "spine_03", "neck": "neck_01", "head": "head",
    "leftShoulder": "clavicle_l", "leftUpperArm": "upperarm_l",
    "leftLowerArm": "lowerarm_l", "leftHand": "hand_l",
    "rightShoulder": "clavicle_r", "rightUpperArm": "upperarm_r",
    "rightLowerArm": "lowerarm_r", "rightHand": "hand_r",
    "leftUpperLeg": "thigh_l", "leftLowerLeg": "calf_l",
    "leftFoot": "foot_l", "leftToes": "ball_l",
    "rightUpperLeg": "thigh_r", "rightLowerLeg": "calf_r",
    "rightFoot": "foot_r", "rightToes": "ball_r",
    # 指: VRM0の親指は Proximal/Intermediate/Distal
    "leftThumbProximal": "thumb_01_l", "leftThumbIntermediate": "thumb_02_l",
    "leftThumbDistal": "thumb_03_l",
    "rightThumbProximal": "thumb_01_r", "rightThumbIntermediate": "thumb_02_r",
    "rightThumbDistal": "thumb_03_r",
}
for _f_vrm, _f_pal in (("Index", "index"), ("Middle", "middle"),
                       ("Ring", "ring"), ("Little", "pinky")):
    for _s_vrm, _s_pal in (("Proximal", "01"), ("Intermediate", "02"),
                           ("Distal", "03")):
        for _side, _sfx in (("left", "l"), ("right", "r")):
            VRM0_TO_PAL[f"{_side}{_f_vrm}{_s_vrm}"] = f"{_f_pal}_{_s_pal}_{_sfx}"


# Unity Humanoid(humanName) → パルボーン。humanoid.json(Unityの
# HumanoidMapExporter.csが書き出す対応表)用。指はスペース区切りの正式名
UNITY_TO_PAL = {
    "Hips": "pelvis", "Spine": "spine_01", "Chest": "spine_02",
    "UpperChest": "spine_03", "Neck": "neck_01", "Head": "head",
    "LeftShoulder": "clavicle_l", "LeftUpperArm": "upperarm_l",
    "LeftLowerArm": "lowerarm_l", "LeftHand": "hand_l",
    "RightShoulder": "clavicle_r", "RightUpperArm": "upperarm_r",
    "RightLowerArm": "lowerarm_r", "RightHand": "hand_r",
    "LeftUpperLeg": "thigh_l", "LeftLowerLeg": "calf_l",
    "LeftFoot": "foot_l", "LeftToes": "ball_l",
    "RightUpperLeg": "thigh_r", "RightLowerLeg": "calf_r",
    "RightFoot": "foot_r", "RightToes": "ball_r",
}
for _f_u, _f_pal in (("Thumb", "thumb"), ("Index", "index"),
                     ("Middle", "middle"), ("Ring", "ring"),
                     ("Little", "pinky")):
    for _s_u, _s_pal in (("Proximal", "01"), ("Intermediate", "02"),
                         ("Distal", "03")):
        for _side, _sfx in (("Left", "l"), ("Right", "r")):
            UNITY_TO_PAL[f"{_side} {_f_u} {_s_u}"] = f"{_f_pal}_{_s_pal}_{_sfx}"


def _humanize_unity_bone(name):
    """Unity HumanBone名をConfigure Avatarパネルの表示名に近い形へ整形する。
    'LeftFoot' -> 'Left Foot' のようにキャメルケースへ空白を挿入する。
    指のフル名(既にスペース区切り、例 'Left Thumb Proximal')はそのまま返す
    (dev#233: エラーメッセージで内部pal_bone名でなくUnity側の人間可読名を出すため)"""
    if " " in name:
        return name
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


# パルボーン → Unity Humanoid人間可読名(逆引き)。UNITY_TO_PALはUnity名→pal名の
# 全単射なので素直に反転できる。die()メッセージで内部名でなくUnityのRigタブ/
# Configure Avatar上の表示名を出すために使う(dev#233)
PAL_TO_UNITY_HUMAN = {
    _pal: _humanize_unity_bone(_unity) for _unity, _pal in UNITY_TO_PAL.items()
}


def missing_humanoid_bone_message(pal_bone):
    """必須Humanoidボーン未割当のFATAL文言を組み立てる(dev#233)。

    内部pal_bone名(例: foot_l)をそのまま出すと非エンジニアのユーザーは
    Unity側のどこを直せばいいか分からない。Unity Configure Avatar上の
    表示名(例: Left Foot)+具体的な対処手順に変換して返す。
    pal_bone が逆引きテーブルに無い(想定外)場合は内部名のままフォールバック
    する(黙って情報を落とすより、原文言のまま出すほうが安全)。
    """
    human = PAL_TO_UNITY_HUMAN.get(pal_bone, pal_bone)
    return (f"required Humanoid bone is unassigned: {human}. "
            "Open the avatar in Unity, select it, and check the Rig tab > "
            f"Configure Avatar to assign {human}, then re-export.")


def _compat_name(name):
    """Unity FBX ExporterのMaya互換命名と同じ変換(スペース・ドット→_)。
    互換命名で書かれた既存FBXも読めるようにするフォールバック用"""
    return name.replace(" ", "_").replace(".", "_")


def humanoid_map_from_json(arm, json_path, warnings):
    """Unity輸出のhumanoid.jsonから {パルボーン: 実ボーン名} を作る(FBX入力用)。"""
    import json as _json
    with open(json_path, encoding="utf-8") as f:
        data = _json.load(f)
    human = data.get("humanoid", {})

    def resolve(bone_name):
        if bone_name in arm.data.bones:
            return bone_name
        if _compat_name(bone_name) in arm.data.bones:
            return _compat_name(bone_name)
        return None

    # Unity FBX Exporter産FBXはスケルトンルートがeRootで書かれ、Blenderの
    # インポータがアーマチュアオブジェクトへ変換するためルートボーン(Hips等)が
    # ボーン一覧から消える(2026-07-21、toto統合FBXで実測)。要求名が
    # アーマチュア名と一致する場合は原点にルートボーンを新造して復元する
    hips_name = human.get("Hips")
    if hips_name and resolve(hips_name) is None:
        obj_base = arm.name.split(".")[0]
        if obj_base in (hips_name, _compat_name(hips_name)):
            import bpy
            # 位置はhumanoid.jsonのhips_local(Unity座標m)から。
            # step01の平坦化(ワールド焼き込み+m正規化)後の空間では
            # Unity(x,y,z) → Blender (-x, -z, y) [m]
            hl = data.get("hips_local")
            if hl:
                head = (-hl[0], -hl[2], hl[1])
            else:
                head = (0.0, 0.0, 0.0)
                warnings.append("no hips_local, restoring to origin (old humanoid.json. "
                                "Re-export from Unity if the position is off)")
            bpy.context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode="EDIT")
            eb = arm.data.edit_bones.new(hips_name)
            eb.head = head
            eb.tail = (head[0], head[1] + 0.05, head[2])  # +Y恒等姿勢(長さは不問)
            for b in list(arm.data.edit_bones):
                if b.parent is None and b.name != hips_name:
                    b.parent = eb
            bpy.ops.object.mode_set(mode="OBJECT")
            warnings.append(f"skeleton root restored: {hips_name} head={head}"
                            "(the FBX's eRoot had been turned into an armature)")

    pal_map = {}
    for human_name, bone_name in human.items():
        pal = UNITY_TO_PAL.get(human_name)
        if pal is None:
            continue  # 目・顎などは意図的に対象外(祖先統合でheadへ)
        actual = resolve(bone_name)
        if actual is not None:
            pal_map[pal] = actual
        else:
            warnings.append(f"humanoid.json: bone not in FBX: "
                            f"{human_name} -> {bone_name}")
    if "pelvis" not in pal_map or "head" not in pal_map:
        die("vp_bl", "could not resolve humanoid.json's required bones (Hips/Head)")
    return pal_map


def humanoid_to_pal_map(arm):
    """VRMアドオンのHumanoid定義から {パルボーン: 実ボーン名} を作る。
    目・顎は意図的に対象外(非マップ→祖先統合でheadへ吸われる)。
    返り値: (pal_map, spec_version)"""
    ext = arm.data.vrm_addon_extension
    pal_map = {}

    # VRM1
    try:
        hb1 = ext.vrm1.humanoid.human_bones
        for attr, pal in VRM1_TO_PAL.items():
            bp = getattr(hb1, attr, None)
            if bp is None:
                continue
            bone_name = bp.node.bone_name
            if bone_name and bone_name in arm.data.bones:
                pal_map[pal] = bone_name
    except AttributeError:
        pass
    if "pelvis" in pal_map and "head" in pal_map:
        return pal_map, "1.0"

    # VRM0
    pal_map = {}
    try:
        for item in ext.vrm0.humanoid.human_bones:
            pal = VRM0_TO_PAL.get(item.bone)
            if pal is None:
                continue
            bone_name = item.node.bone_name
            if bone_name and bone_name in arm.data.bones:
                pal_map[pal] = bone_name
    except AttributeError:
        pass
    if "pelvis" in pal_map and "head" in pal_map:
        return pal_map, "0.x"

    die("vp_bl", "could not read the VRM Humanoid definition (hips/head unassigned). "
        "The VRM file may be corrupt, or in a format the addon does not support")


def _vrm_op_available():
    try:
        bpy.ops.import_scene.vrm.get_rna_type()
        return True
    except Exception:
        return False


def ensure_vrm_addon(job):
    """VRMアドオンを使える状態にする。

    2026-07-28(dev issue #24 / 公開issue #14): 全Blender起動を--factory-startupに
    したため、ユーザーのuserpref.blendは一切読まれず、アドオンは毎セッション
    「無効」から始まる。ここで毎回enableする(enableはメモリ上の操作のみで
    ディスクのファイルを書き換えないため、並行実行にも安全)。
    以前あった bpy.ops.wm.save_userpref() は廃止した — --factory-startup状態で
    保存すると**ユーザーの実userpref.blendを工場出荷設定で上書き**してしまう
    (ユーザー環境の設定破壊)。絶対に復活させないこと。

    重要: 毎回zipを再インストールすると**アドオンのファイルを毎回書き換える**
    ことになり、並行実行中の別Blenderのインポートを即死させる
    (2026-07-21 flatv3事件)。ファイルが既にディスクにあれば「有効化」だけを
    行い、インストールは初回のみにする。"""
    if _vrm_op_available():
        return
    # 1) 既にディスクにあるextensionを有効化するだけ(ファイル書き換えなし)
    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.user_default.vrm")
        if _vrm_op_available():
            print("[vp_bl] VRM addon enabled for this session (factory-startup, no reinstall)")
            return
    except Exception:
        pass
    # 2) 初回のみ: zipからインストール(enable_on_installでこのセッションでも有効化)
    zip_path = job["paths"].get("vrm_addon_zip")
    if not zip_path or not os.path.exists(zip_path):
        die("vp_bl", f"VRM addon zip not found: {zip_path}")
    bpy.ops.extensions.package_install_files(
        repo="user_default", filepath=zip_path, enable_on_install=True)
    if not _vrm_op_available():
        die("vp_bl", "installed the VRM addon but import_scene.vrm is still not available")
    print("[vp_bl] VRM addon installed+enabled (session only; prefs are never saved)")
