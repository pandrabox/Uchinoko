# -*- coding: utf-8 -*-
"""Step02: パル骨格への載せ替え(オートフィット+チビ骨格方式)。性別ごとに実行。

実行: blender --background --factory-startup --python-exit-code 1 --python step02_retarget.py -- <job.json> <Male|Female>
入力: converted/step01_clean.blend + vanilla/refskel_{gender}.json
出力: converted/step02_{gender}.blend

方式はPalModで実証済みのチビ骨格(検査⑨⑩で100点):
  - アバターを体幹比でパル(cm)系へスケール、腰位置合わせ
  - 腕チェーンをパル方向へ回転(A→Tポーズ化)+肩スライダー適用
  - 形状をメッシュへ焼き込み、接地
  - パル骨格の関節をアバターの関節位置へ移動(向き不変、位置のみ=チビ骨格)
  - ウェイトをパル名へ移植(Humanoid外は最寄り祖先へ統合)、バインド
"""

import json
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_bl
import vp_modnorm
from vp_bl import core

TAG = "step02"

# 腕チェーンの回転フィット(パル名で表現。アバター側はpal_mapで引く)
ROTATE_CHAINS = [
    ("clavicle_l", "upperarm_l"), ("upperarm_l", "lowerarm_l"),
    ("lowerarm_l", "hand_l"), ("hand_l", "middle_01_l"),
    ("clavicle_r", "upperarm_r"), ("upperarm_r", "lowerarm_r"),
    ("lowerarm_r", "hand_r"), ("hand_r", "middle_01_r"),
]

# チビ骨格で明示移動する候補(マップされているものだけ移動)
CHIBI_CANDIDATES = [
    "spine_01", "spine_02", "spine_03", "neck_01", "head",
    "clavicle_l", "clavicle_r",
    "upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r",
    "thigh_l", "calf_l", "foot_l", "ball_l",
    "thigh_r", "calf_r", "foot_r", "ball_r",
]
for _f in ("thumb", "index", "middle", "ring", "pinky"):
    for _s in ("01", "02", "03"):
        for _side in ("l", "r"):
            CHIBI_CANDIDATES.append(f"{_f}_{_s}_{_side}")

# 体幹チェーン(未マップの中間ボーンは比率補間で配置)
SPINE_CHAIN = ["pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head"]

# セグメント中間のtwistボーンは区間比率でスケール配置
CHIBI_TWIST_BONES = {
    "upperarm_twist_01_l": ("upperarm_l", "lowerarm_l"),
    "upperarm_twist_01_r": ("upperarm_r", "lowerarm_r"),
    "lowerarm_twist_01_l": ("lowerarm_l", "hand_l"),
    "lowerarm_twist_01_r": ("lowerarm_r", "hand_r"),
    "thigh_twist_01_l": ("thigh_l", "calf_l"),
    "thigh_twist_01_r": ("thigh_r", "calf_r"),
    "calf_twist_01_l": ("calf_l", "foot_l"),
    "calf_twist_01_r": ("calf_r", "foot_r"),
}

ZERO_WEIGHT_FALLBACK_BONE = "pelvis"

# 揺れ髪: ゲーム物理はhair_*ボーンを頭基準のアニメ位置で駆動する。
# PalMod検査⑪の教訓: 頭から遠いもの(尻尾)を載せると頭に張り付くが、
# 頭に付いている本物の髪ならこの仕組みに正しく乗れる。
# チェーン構成はバニラ髪RefSkeletonから動的に導出(1.0はhair_01..26)
HAIR_SPLIT_THRESHOLD = 0.5


def _bone_world(arm, bone_name):
    return arm.matrix_world @ arm.data.bones[bone_name].head_local


def _pose_head_world(arm, name):
    return arm.matrix_world @ arm.pose.bones[name].head


def global_scale_and_place(avatar_arm, pal_arm, pal_map):
    """体幹長(hips→head)の比で全体スケールを決め、腰位置を合わせる。"""
    av_hips = _bone_world(avatar_arm, pal_map["pelvis"])
    av_head = _bone_world(avatar_arm, pal_map["head"])
    pal_pelvis = _bone_world(pal_arm, "pelvis")
    pal_head = _bone_world(pal_arm, "head")
    av_len = (av_head - av_hips).length
    if av_len < 1e-6:
        core.die(TAG, "cannot measure the avatar's torso length")
    s = (pal_head - pal_pelvis).length / av_len
    avatar_arm.scale = (s, s, s)
    bpy.context.view_layer.update()
    av_hips2 = _bone_world(avatar_arm, pal_map["pelvis"])
    avatar_arm.location += pal_pelvis - av_hips2
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    avatar_arm.select_set(True)
    for child in avatar_arm.children_recursive:
        child.select_set(True)
    bpy.context.view_layer.objects.active = avatar_arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"[{TAG}] global fit: scale x{s:.3f}, pelvis aligned")


def auto_fit_pose(avatar_arm, pal_arm, pal_map):
    """腕チェーンだけ、パル骨格の関節方向へ回転(A→Tポーズ化)。
    方向の基準は関節(子ボーンのhead)位置(合成テールは信用しない)。"""
    pal_mw = pal_arm.matrix_world
    done = 0
    for pal_bone, pal_child in ROTATE_CHAINS:
        av_bone = pal_map.get(pal_bone)
        av_child = pal_map.get(pal_child)
        if av_bone is None or av_child is None:
            print(f"[{TAG}][WARN] chain skip: {pal_bone}->{pal_child}")
            continue
        pal_dir = (pal_mw @ pal_arm.data.bones[pal_child].head_local
                   - pal_mw @ pal_arm.data.bones[pal_bone].head_local).normalized()
        cur_head = _pose_head_world(avatar_arm, av_bone)
        cur_dir = (_pose_head_world(avatar_arm, av_child) - cur_head).normalized()
        rot = cur_dir.rotation_difference(pal_dir).to_matrix().to_4x4()
        pb = avatar_arm.pose.bones[av_bone]
        cur = avatar_arm.matrix_world @ pb.matrix
        trans = cur.translation.copy()
        new_m = rot @ cur
        new_m.translation = trans
        pb.matrix = avatar_arm.matrix_world.inverted() @ new_m
        bpy.context.view_layer.update()
        done += 1
    print(f"[{TAG}] auto-fit: arm chains rotated ({done} bones)")


def apply_shoulder_offset(avatar_arm, pal_map, deg):
    """肩スライダー: Upper Armをワールド前後軸まわりに外へ開く(±deg)。
    バインドはバニラのままなので全ポーズが一律この分だけ開く。"""
    import math
    if abs(deg) < 0.01:
        return
    for pal_bone, sign in (("upperarm_l", -1.0), ("upperarm_r", 1.0)):
        av = pal_map.get(pal_bone)
        if av is None:
            continue
        pb = avatar_arm.pose.bones[av]
        rot = Matrix.Rotation(math.radians(sign * deg), 4, "Y")
        cur = avatar_arm.matrix_world @ pb.matrix
        trans = cur.translation.copy()
        new_m = rot @ cur
        new_m.translation = trans
        pb.matrix = avatar_arm.matrix_world.inverted() @ new_m
        bpy.context.view_layer.update()
    print(f"[{TAG}] shoulder offset: ±{deg}deg")


def bake_pose_into_meshes(avatar_arm, mesh_objs):
    # 二重の安全網(公開issue #18): 通常はstep01の入口正規化で処理済みだが、
    # 無効フラグ(show_viewport=False)のArmatureモディファイアが残っていると
    # modifier_applyがBlender自身のRuntimeError(「モディファイアーはOFFです」)で
    # 停止する。ここでも適用直前に強制ONへ正規化してから進む(停止させない)。
    vp_modnorm.normalize_armature_modifiers(mesh_objs, tag=TAG)
    for obj in mesh_objs:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                try:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                except RuntimeError as e:
                    # issue #18のログ改修: どのメッシュ・モディファイアで
                    # 落ちたかを必ずログに残す(従来は特定不能だった)
                    core.die(TAG, "modifier_apply failed on mesh "
                             f"'{obj.name}' modifier '{mod.name}': {e}")


def snap_to_ground(mesh_objs):
    min_z = min((obj.matrix_world @ Vector(c)).z
                for obj in mesh_objs for c in obj.bound_box)
    for obj in mesh_objs:
        obj.location.z -= min_z
    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    print(f"[{TAG}] ground snap: dz={-min_z:.1f}")
    return -min_z


def chibi_fit_armature(pal_arm, avatar_arm, pal_map, dz):
    """パル骨格の関節をアバターの(フィット・接地後の)関節位置へ移動する。
    向き(tail方向・roll)は変えず位置のみ。未マップの体幹中間ボーンは比率補間。"""
    # 1) 明示ターゲット(マップ済み候補)
    targets = {}
    for pal_name in CHIBI_CANDIDATES:
        av = pal_map.get(pal_name)
        if av is None:
            continue
        pb = avatar_arm.pose.bones.get(av)
        if pb is None:
            continue
        w = avatar_arm.matrix_world @ pb.head
        targets[pal_name] = Vector((w.x, w.y, w.z + dz))

    inv_pal = pal_arm.matrix_world.inverted()
    bpy.ops.object.select_all(action="DESELECT")
    pal_arm.select_set(True)
    bpy.context.view_layer.objects.active = pal_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = pal_arm.data.edit_bones
    old_head = {b.name: b.head.copy() for b in eb}

    # 2) 体幹チェーンの未マップ中間(spine_02/03, neck_01等)を旧比率で補間
    chain = [b for b in SPINE_CHAIN if b in eb]
    known = [b for b in chain if b in targets or b == "pelvis"]
    for i, name in enumerate(chain):
        if name in targets or name == "pelvis":
            continue
        below = next((b for b in reversed(chain[:i])
                      if b in targets or b == "pelvis"), None)
        above = next((b for b in chain[i + 1:] if b in targets), None)
        if below is None or above is None:
            continue
        p_below_new = targets.get(below, inv_pal.inverted() @ old_head[below]
                                  if False else None)
        # pelvisは移動しない(グローバル配置で一致済み)→ 旧位置=新位置
        new_below = targets[below] if below in targets \
            else pal_arm.matrix_world @ old_head[below]
        new_above = targets[above]
        seg_old = old_head[above] - old_head[below]
        if seg_old.length < 1e-6:
            continue
        t = (old_head[name] - old_head[below]).length / seg_old.length
        targets[name] = new_below.lerp(new_above, t)
        print(f"[{TAG}] chibi interp: {name} (t={t:.2f} on {below}->{above})")

    moved_delta = {}
    ordered = [b.name for b in pal_arm.data.bones]  # 階層順
    for name in ordered:
        if name not in targets or name not in eb:
            continue
        b = eb[name]
        new_head = inv_pal @ targets[name]
        delta = new_head - b.head
        b.tail = b.tail + delta
        b.head = new_head
        moved_delta[name] = delta

    # 3) twist: 区間比率で配置
    for name, (p_name, c_name) in CHIBI_TWIST_BONES.items():
        if name not in eb or p_name not in old_head or c_name not in old_head:
            continue
        b = eb[name]
        old_seg = old_head[c_name] - old_head[p_name]
        new_seg = eb[c_name].head - eb[p_name].head
        if old_seg.length < 1e-6:
            continue
        t = (old_head[name] - old_head[p_name]).length / old_seg.length
        new_head = eb[p_name].head + new_seg * t
        delta = new_head - b.head
        b.tail = b.tail + delta
        b.head = new_head
        moved_delta[name] = delta

    # 4) その他の子孫(weapon/eyes/root外): 最寄りの移動済み祖先のデルタで平行移動
    def nearest_moved_ancestor(bone):
        p = bone.parent
        while p is not None:
            if p.name in moved_delta:
                return p.name
            p = p.parent
        return None

    for b in eb:
        if b.name in moved_delta:
            continue
        anc = nearest_moved_ancestor(b)
        if anc is None:
            continue
        delta = moved_delta[anc]
        b.tail = b.tail + delta
        b.head = b.head + delta

    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[{TAG}] chibi skeleton: {len(moved_delta)} joints moved "
          f"(+descendants translated) known_chain={known}")


# ------------------------------------------------------------- 揺れ髪(Hairスロット)

def detect_hair_chains(avatar_arm, pal_map, explicit_roots, spring_roots,
                       warnings):
    """揺れ髪に載せるアバターのボーンを {bone名: (root名, 深さ比率0..1)} で返す。

    優先順(2026-07-21ぱん要件):
      1. job.hair_bones(明示指定)
      2. VRM定義のSpringBoneルートのうち**頭の子孫**のもの(自動)。
         尻尾・スカート等の頭外springは除外(頭基準駆動で壊れるため)
      3. フォールバック: 頭の子で非Humanoidかつ子を持つボーン
    """
    mapped = set(pal_map.values())
    head = avatar_arm.data.bones.get(pal_map.get("head", ""))
    if head is None:
        return {}

    def is_head_descendant(bone):
        p = bone.parent
        while p is not None:
            if p == head:
                return True
            p = p.parent
        return False

    if explicit_roots:
        roots = []
        for n in explicit_roots:
            b = avatar_arm.data.bones.get(n)
            if b is None:
                warnings.append(f"hair_bones: bone not found: {n}")
            else:
                roots.append(b)
        src = "explicit"
    elif spring_roots:
        roots, skipped = [], []
        for n in spring_roots:
            b = avatar_arm.data.bones.get(n)
            if b is None:
                continue
            if b.name in mapped:
                continue
            if is_head_descendant(b):
                roots.append(b)
            else:
                skipped.append(n)
        src = "VRM SpringBone definition"
        if skipped:
            print(f"[{TAG}] spring skip (outside head, left rigid): {skipped}")
    else:
        roots = [c for c in head.children
                 if c.name not in mapped and len(c.children) >= 1]
        src = "auto-detected (head children)"
    if roots:
        print(f"[{TAG}] hair-sway source: {src}")
    result = {}
    for root in roots:
        chain = [root] + list(root.children_recursive)
        depth = {root.name: 0}
        for b in chain[1:]:
            depth[b.name] = depth[b.parent.name] + 1
        max_d = max(depth.values()) or 1
        for b in chain:
            result[b.name] = (root.name, depth[b.name] / max_d)
    if result:
        print(f"[{TAG}] hair-sway chains: roots={[r.name for r in roots]} "
              f"bones={len(result)}")
    return result


def load_hair_chains(hair_refskel_path):
    """バニラ髪RefSkeletonから揺れチェーン(長さ2以上の連鎖)を導出する。
    返り値: (refskel dict, [[root, ..., tip], ...])"""
    import json as _json
    with open(hair_refskel_path, encoding="utf-8") as f:
        van = _json.load(f)
    hair_names = [n for n in van if n.startswith("hair_")]
    children = {}
    for n in hair_names:
        p = van[n]["parent"]
        if p and p.startswith("hair_"):
            children.setdefault(p, []).append(n)
    roots = [n for n in hair_names
             if not (van[n]["parent"] or "").startswith("hair_")]
    chains = []
    for r in sorted(roots):
        chain = [r]
        cur = r
        while children.get(cur):
            cur = sorted(children[cur])[0]
            chain.append(cur)
        if len(chain) >= 2:
            chains.append(chain)
    print(f"[{TAG}] vanilla hair: {len(hair_names)} bones, "
          f"{len(chains)} sway chains")
    return van, chains


def add_sway_hair_bones(pal_arm, hair_refskel_path):
    """バニラ髪のhair_01..09を、チビ頭位置+バニラの頭相対オフセットに新造する。
    バインド位置=実行時のアニメ駆動位置に一致させる(頭相対を厳密保存する
    平行移動なので、ゲーム内でレスト時のズレがゼロになる)。"""
    import json as _json

    from mathutils import Matrix, Quaternion
    with open(hair_refskel_path, encoding="utf-8") as f:
        van = _json.load(f)

    world = {}

    def ue_world(name):
        if name in world:
            return world[name]
        b = van[name]
        q = Quaternion((b["quat"][3], b["quat"][0], b["quat"][1], b["quat"][2]))
        p = Vector(b["pos"])
        if b["parent"] is None or b["parent"] not in van:
            world[name] = (q, p)
        else:
            pq, pp = ue_world(b["parent"])
            world[name] = (pq @ q, pp + pq @ p)
        return world[name]

    M = Matrix(((1, 0, 0), (0, -1, 0), (0, 0, 1)))
    Minv = M.inverted()

    def to_blender(name):
        uq, up = ue_world(name)
        return (M @ uq.to_matrix() @ Minv).to_quaternion(), M @ up

    # 頭相対オフセットを保存する平行移動量(チビ頭 − バニラ髪SKの頭)
    _, van_head_pos = to_blender("head")
    chibi_head = (pal_arm.matrix_world
                  @ pal_arm.data.bones["head"].head_local)
    delta = chibi_head - van_head_pos

    bpy.ops.object.select_all(action="DESELECT")
    pal_arm.select_set(True)
    bpy.context.view_layer.objects.active = pal_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = pal_arm.data.edit_bones
    inv_arm = pal_arm.matrix_world.inverted()
    made = 0
    for name in sorted(n for n in van if n.startswith("hair_")):
        if name in eb:
            continue
        q, p = to_blender(name)
        b = eb.new(name)
        b.head = (0, 0, 0)
        b.tail = (0, 4, 0)
        b.matrix = inv_arm @ Matrix.LocRotScale(p + delta, q, Vector((1, 1, 1)))
        parent = van[name]["parent"]
        if parent in eb:
            b.parent = eb[parent]
        made += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"[{TAG}] sway hair bones created: {made} (delta={tuple(round(v,1) for v in delta)})")
    return made > 0


def assign_hair_chains(pal_arm, avatar_arm, hair_bones, sway_chains):
    """アバター髪ボーン → バニラ揺れチェーンのボーン の割当表を作る。
    アバターのチェーン(root)ごとに最寄りのバニラチェーンを選び、
    深さ比率でチェーン内の対応ボーン(根本〜先端)に載せる。"""
    chain_by_root = {}
    for chain in sway_chains:
        b = pal_arm.data.bones.get(chain[0])
        if b is not None:
            chain_by_root[chain[0]] = (
                chain, pal_arm.matrix_world @ b.head_local)
    if not chain_by_root:
        return {}
    assignment = {}
    root_to_chain = {}
    for av_name, (root_name, ratio) in hair_bones.items():
        if root_name not in root_to_chain:
            rb = avatar_arm.data.bones.get(root_name)
            rpos = avatar_arm.matrix_world @ rb.head_local
            nearest = min(chain_by_root.values(),
                          key=lambda cv: (cv[1] - rpos).length)
            root_to_chain[root_name] = nearest[0]
            print(f"[{TAG}] hair chain: {root_name} -> {nearest[0][0]}"
                  f"..{nearest[0][-1]}")
        chain = root_to_chain[root_name]
        idx = min(int(ratio * len(chain)), len(chain) - 1)
        assignment[av_name] = chain[idx]
    return assignment


def split_hair_mesh(meshes, hair_bones):
    """髪頂点(髪ボーン合計ウェイト>閾値)を各メッシュから分離し、
    1つの HairSway オブジェクトに統合して返す。
    分離断片はbefore/afterの集合差分で確実に捕捉する(名前推測は
    ViewLayer外の取り残しを生む — flatv3揺れ髪WIPで実害確認済みの修正)。"""
    fragments = []
    survivors = []
    for obj in meshes:
        idx = {vg.index for vg in obj.vertex_groups if vg.name in hair_bones}
        if not idx:
            survivors.append(obj)
            continue
        sel = [v.index for v in obj.data.vertices
               if sum(g.weight for g in v.groups if g.group in idx)
               > HAIR_SPLIT_THRESHOLD]
        if not sel:
            survivors.append(obj)
            continue
        if len(sel) == len(obj.data.vertices):
            fragments.append(obj)  # メッシュ丸ごと髪
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for i in sel:
            obj.data.vertices[i].select = True
        before = set(bpy.data.objects)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")
        new_frags = [o for o in set(bpy.data.objects) - before
                     if o.type == "MESH"]
        fragments.extend(new_frags)
        survivors.append(obj)
    if not fragments:
        return survivors, None
    bpy.ops.object.select_all(action="DESELECT")
    ok = 0
    for f in fragments:
        try:
            f.select_set(True)
            ok += 1
        except RuntimeError:
            print(f"[{TAG}][WARN] fragment is outside the ViewLayer: {f.name}")
    if ok == 0:
        return survivors, None
    bpy.context.view_layer.objects.active = fragments[0]
    if ok > 1:
        bpy.ops.object.join()
    hair_obj = bpy.context.view_layer.objects.active
    hair_obj.name = "HairSway"
    if hair_obj.data:
        hair_obj.data.name = "HairSway"
    n = len(hair_obj.data.vertices)
    print(f"[{TAG}] hair split: {n} verts -> HairSway")
    return survivors, hair_obj


# ------------------------------------------------------------- ウェイト移植

def attach_orphan_roots(avatar_arm, pal_map):
    """孤立ルート(parent=Noneかつ d2p_skeleton_root以外)を、レスト姿勢の
    ワールド座標で最も近い「マップ済み(=RefSkeletonに実在する)」ボーンへ
    子として接続する。

    背景(2026-07-26): NDMF/Modular AvatarのMerge Armatureが、対応先の
    無い揺れ物サブリグ(胸ゆれ・スカート等、名前が`Foo$<GUID>`形式)を、
    本体骨格へ実際のボーン親子関係としては接続せずに取り込む場合がある。
    その結果 build_group_targets() の祖先walkがそのサブリグの中で尽きて
    しまい、標準骨格側へウェイトを合算できない(agyo検体で実測)。

    接続は EditBone.parent の張り替えのみで、use_connect は付けない。
    Blenderの EditBone.head/tail はアーマチュア空間の絶対座標であり
    parentが何であっても値は変化しない(use_connect時のみ子headが
    強制的に親tailへ一致させられる)。また対象ボーンはこの時点で
    ポーズ変換(matrix_basis)を一切受けていないレスト状態なので、
    後続のpose計算(PoseBone.matrix)もparentの変更では変わらない。
    よってこの処理はメッシュ・レスト姿勢を一切動かさない。
    """
    mapped_names = set(pal_map.values())
    bones = avatar_arm.data.bones
    # 既にマップ済みのボーン(例: FBXのeRoot挿入でHipsがparent=Noneになるケース)は
    # そもそも救済不要(build_group_targetsがinv.get()で直接解決する)。
    # 除外しないと「自分自身への接続」という無意味な結果になる(2026-07-26、
    # jinbe再検証で実測)。
    orphan_roots = [b.name for b in bones
                    if b.parent is None and b.name != "d2p_skeleton_root"
                    and b.name not in mapped_names]
    if not orphan_roots:
        return
    candidates = [b.name for b in bones if b.name in mapped_names]
    if not candidates:
        print(f"[{TAG}][WARN] orphan root connection: no mapped candidate bone "
              f"({orphan_roots}) — passing through with unknown ancestor")
        return

    cand_world = {n: _bone_world(avatar_arm, n) for n in candidates}
    orphan_world = {n: _bone_world(avatar_arm, n) for n in orphan_roots}
    nearest_of = {
        name: min(candidates, key=lambda n: (cand_world[n] - orphan_world[name]).length)
        for name in orphan_roots
    }

    bpy.ops.object.select_all(action="DESELECT")
    avatar_arm.select_set(True)
    bpy.context.view_layer.objects.active = avatar_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = avatar_arm.data.edit_bones
    for name, nearest in nearest_of.items():
        eb[name].use_connect = False
        eb[name].parent = eb[nearest]
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, nearest in nearest_of.items():
        dist = (cand_world[nearest] - orphan_world[name]).length
        print(f"[{TAG}] orphan root attach: {name} -> {nearest} (dist={dist:.2f})")


def build_group_targets(avatar_arm, pal_map, merge_fingers):
    """アバター各ボーン → 最終パルグループ名 の対応表を作る。
    マップ外ボーンは最寄りのマップ済み祖先へ。指統合オプションはここで畳む。"""
    inv = {v: k for k, v in pal_map.items()}  # 実ボーン名 → パル名
    finger_fold = {}
    if merge_fingers:
        for f in ("thumb", "index", "middle", "ring", "pinky"):
            for s in ("01", "02", "03"):
                for side in ("l", "r"):
                    finger_fold[f"{f}_{s}_{side}"] = f"hand_{side}"

    result = {}
    for bone in avatar_arm.data.bones:
        pal = inv.get(bone.name)
        if pal is None:
            anc = bone.parent
            while anc is not None and anc.name not in inv:
                anc = anc.parent
            if anc is None:
                continue  # rootより上: 拾えない(後段の警告+pelvis救済に任せる)
            pal = inv[anc.name]
        result[bone.name] = finger_fold.get(pal, pal)
    return result


def remap_vertex_groups(obj, group_targets):
    """頂点グループをパル名へ集約する(名前衝突安全な二相方式)。

    dev#234: マップ先が見つからない(unknown ancestor)頂点グループは、
    警告後に重みごと除去する(祖先パルボーンへの畳み込みは行わない)。
    根拠: build_group_targets()は既にavatar_arm.data.bones全件について
    祖先を辿ってpal_mapへの解決を尽くしており(かつattach_orphan_roots()が
    孤立ルートを事前に最寄りのマップ済みボーンへ接続済み)、それでも
    group_targetsに現れないのは (a) 頂点グループ名に対応するボーンが
    アーマチュアに実在しない(ダングリング。マージされたサブリグの残骸等)、
    または (b) ボーンは実在するが祖先を辿っても本当にマップ済みへ到達
    できない、のいずれか。どちらも「畳み込み先の祖先パルボーン」を
    remap_vertex_groups()側で新たに探索し直す余地は無い(同じ探索は
    build_group_targets()が既に尽くしている)。除去せずに残すと、その
    頂点グループが元ボーン名(例: "pelvis001")を保持したままメッシュに
    生存し、dump_avatar_mesh.py がそれを拾ってJSONへ書き出し、
    RefSkeletonに存在しないボーン名として後段のSK注入を全滅させる
    (実報告SB7BAUA5)。除去後は既存のrescue_zero_weight_vertices()
    (全グループ合計ウェイトが閾値未満の頂点をpelvis等へ束縛する既存の
    安全網)に一本化される——これはbuild_group_targets()のコメント
    「rootより上: 拾えない(後段の警告+pelvis救済に任せる)」が元々
    想定していた後始末そのもの。"""
    tmp_prefix = "PAL::"
    acc = {}  # 最終パル名 -> 一時グループ
    unmatched = []
    for vg in list(obj.vertex_groups):
        target = group_targets.get(vg.name)
        if target is None:
            unmatched.append(vg.name)
            obj.vertex_groups.remove(vg)  # dev#234: 畳み込み先が無いので重みごと除去
            continue
        tmp_name = tmp_prefix + target
        tmp = obj.vertex_groups.get(tmp_name)
        if tmp is None:
            tmp = obj.vertex_groups.new(name=tmp_name)
            acc[target] = tmp
        src_idx = vg.index
        tmp_idx = tmp.index
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == src_idx and g.weight > 0.0:
                    tmp.add([v.index], g.weight, "ADD")
                    break
        obj.vertex_groups.remove(vg)
    for vg in list(obj.vertex_groups):
        if vg.name.startswith(tmp_prefix):
            vg.name = vg.name[len(tmp_prefix):]
    if unmatched:
        print(f"[{TAG}][WARN] group(s) with unknown ancestor ({obj.name}): {unmatched}")
    print(f"[{TAG}] remap: {obj.name} -> {len(acc)} pal groups")
    return len(acc)


def rescue_zero_weight_vertices(obj, target_bone=ZERO_WEIGHT_FALLBACK_BONE):
    """全頂点(または無重みの頂点)をtarget_boneへ100%束縛する。
    target_boneの既定はpelvis(従来どおり)。呼び出し側(main())が、非スキン
    メッシュ(帽子等)については元の親ボーンから解決したパルボーン名を渡す。"""
    orphans = [v.index for v in obj.data.vertices
               if sum(g.weight for g in v.groups) < 0.01]
    if not orphans:
        return
    vg = obj.vertex_groups.get(target_bone)
    if vg is None:
        vg = obj.vertex_groups.new(name=target_bone)
    vg.add(orphans, 1.0, "REPLACE")
    print(f"[{TAG}] zero-weight rescue: {obj.name}: {len(orphans)} verts -> "
          f"{target_bone}")


def rebind(mesh_objs, pal_arm):
    for obj in mesh_objs:
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                obj.modifiers.remove(mod)
        obj.parent = pal_arm
        obj.matrix_parent_inverse.identity()
        mod = obj.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = pal_arm
        # 注意(2026-07-26 SX班診断で判明): obj.parent への再代入は
        # parent_type/parent_bone を変更しない(Blenderの仕様)。元がボーン子
        # (parent_type=BONE、静的メッシュがVRM/FBXの特定ボーンへ直接固定されて
        # いたケース)だった場合、ここで親アーマチュアをpal_armへ差し替えても
        # parent_bone は元アバターのボーン名のまま残る。pal_armにはパル標準名
        # (head/pelvis等)しか無いため、その名前はほぼ確実に存在せず、
        # Blenderはボーンオフセットを解決できずに黙って親オブジェクト原点
        # (pal_armの原点=足元)を使う。結果、そのメッシュは骨格原点へ落ちる
        # (このファイル末尾のlog_structure_summary()が検出する「原点取り残し」
        # の実際の発生源）。ここではrebind()の挙動そのものは変えず
        # (CLAUDE.mdの方針: 変換の挙動を変えないこと)、main()側で
        # rebind()呼び出し前に記録したparent_type/parent_boneを使って
        # 事後に検出・警告するだけに留める。


# ------------------------------------------------------------- 構造サマリ(成功時ログ)
# 2026-07-26 SX班: 「変換は成功したが結果が異常」(例: 頭に載っていたはずの帽子が
# 足元・原点付近に落ちる)を、アバター本体を貰わずログだけで診断できるようにする。
# CLAUDE.md「値を寄せて合わせる修正は却下」に従い、絶対座標のしきい値は使わない。
# 判定は2段構え:
#   1) 決定的判定(dangling): 元ファイルでボーン子(parent_type=BONE)だった
#      静的メッシュの親ボーン名が、変換後の骨格に存在しない。これは名前の
#      有無という事実であり、しきい値を一切含まない。上のrebind()コメント
#      で説明した実際の破損メカニズムそのものを検出する。
#   2) 補助的判定(要確認): 「アバター自身の全体バウンディングボックス対角線」を
#      物差しにした相対距離のみを使う。検体ごとにスケール(cm/m、体格)が
#      異なるため、絶対値のしきい値は検体を跨いで意味を持たない。相対値なら
#      「その検体の中で明らかに近すぎる」を検体に依存せず言える。
#      誤検出対策: 正常な脚部も骨格原点(接地点)に近いため、位置だけでなく
#      「スキニングが単一グループに偏っている(=事実上の剛体、真の脚部は
#      複数ボーンへ滑らかに分散する)」の両方が揃った場合のみ警告する。
#      それでも断定はできないため文言は「要確認」に留める(1)と違い、
#      これは統計的な目安であり確定情報ではない。
REL_ORIGIN_ALERT = 0.06  # 全体バウンディングボックス対角線に対する比率(検体非依存)。
SUMMARY_MESH_LIMIT = 20  # 非エンジニアが問い合わせ文面に貼ることを想定した上限。
                         # 超える場合は正常メッシュを省略する(異常候補は件数に
                         # 関わらず全件出す)。


def _mesh_world_bbox_center(obj):
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    n = len(corners)
    if n == 0:
        return Vector((0.0, 0.0, 0.0)), []
    center = Vector((sum(c.x for c in corners) / n,
                      sum(c.y for c in corners) / n,
                      sum(c.z for c in corners) / n))
    return center, corners


def _analyze_skinning(obj):
    """頂点グループへの重み配分から、複数ボーンへ滑らかに分散(スキニング)か、
    単一グループへほぼ全重みが集中(実質的に剛体)かを判定する。"""
    idx_to_name = {vg.index: vg.name for vg in obj.vertex_groups}
    if not idx_to_name:
        return {"n_groups": 0, "dominant": None, "dominant_ratio": 0.0}
    weight_sum = {}
    for v in obj.data.vertices:
        for g in v.groups:
            name = idx_to_name.get(g.group)
            if name is None or g.weight <= 0.0:
                continue
            weight_sum[name] = weight_sum.get(name, 0.0) + g.weight
    total = sum(weight_sum.values())
    if total <= 0.0:
        return {"n_groups": 0, "dominant": None, "dominant_ratio": 0.0}
    dominant = max(weight_sum, key=weight_sum.get)
    ratio = weight_sum[dominant] / total
    n_sig = sum(1 for w in weight_sum.values() if w / total > 0.01)
    return {"n_groups": n_sig, "dominant": dominant, "dominant_ratio": ratio}


def log_structure_summary(meshes, pal_arm, orig_parent_info, material_count,
                          no_skin_meshes=frozenset(), rescue_target=None):
    """成功時にも構造の要点(名前/頂点数/バウンディングボックス中心/スキニング有無/
    静的メッシュの元親)をログへ残し、「原点取り残し」を機械的に検出して警告する。

    no_skin_meshes: remap_vertex_groups()が「0 pal groups」を返した(=remap後の
    頂点グループが1つも無い)メッシュ名の集合。2026-07-26 HF班診断:
    shapell_Osakiの帽子(Beret)・リボン(Ribbon)の実ログはどちらもこの状態
    だった。一方、健全な既存検体(AliciaSolid_vrm-0.51.vrm、指揮者提供の
    実測データ)は12メッシュ全てが1個以上のpal groupを持ち、0件は無い
    (単一ボーンへの剛体スキニング=グループ1・最大配分100%というパターン
    自体は健全な検体にも6件あり、これだけでは異常の印にならないことが
    実測で確認済み)。つまり「remap後に対応するパルボーンへのウェイトが
    1つも無い」(=zero-weight rescueで全頂点がpelvisへ一律救済される)こと
    自体が、距離やグループ数のようなしきい値を介さない事実そのものであり、
    このメッシュのスキニング(≒追従先ボーン)が丸ごと失われたことの決定的
    な証拠になる。dangling(親ボーン参照切れ)と同格の確定判定として扱う。

    rescue_target: {mesh名: 実際にrescue_zero_weight_vertices()で束縛した
    パルボーン名}。2026-07-26 HB班: 元の親ボーンをpal_mapへ解決できた場合は
    pelvis以外のボーンへ束縛されるため、警告文言もそれに合わせて「pelvisへ
    一律固定」から実態(解決できたボーン名)へ差し替える。解決できず従来通り
    pelvisへ落ちた場合は、これまでどおりの文言のまま。"""
    rescue_target = rescue_target or {}
    infos = []
    all_corners = []
    for obj in meshes:
        center, corners = _mesh_world_bbox_center(obj)
        all_corners.extend(corners)
        skin = _analyze_skinning(obj)
        opt = orig_parent_info.get(obj.name, {})
        infos.append({
            "name": obj.name, "vcount": len(obj.data.vertices),
            "center": center, "skin": skin,
            "orig_parent_type": opt.get("parent_type"),
            "orig_parent_bone": opt.get("parent_bone"),
        })
    if not all_corners:
        print(f"[{TAG}][structure] cannot produce a summary with 0 meshes")
        return

    mn = Vector((min(c.x for c in all_corners), min(c.y for c in all_corners),
                 min(c.z for c in all_corners)))
    mx = Vector((max(c.x for c in all_corners), max(c.y for c in all_corners),
                 max(c.z for c in all_corners)))
    size = mx - mn
    diag = size.length
    origin = pal_arm.matrix_world.translation

    # 単位はcm(vp_bl.build_pal_armature()のdocstring「RefSkeleton JSONから
    # パル骨格アーマチュアを構築する(cm単位)」のとおり。step02の
    # global_scale_and_place()でアバターをこのパル骨格スケールへ合わせ済み)
    print(f"[{TAG}][structure] mesh_count={len(infos)} bone_count={len(pal_arm.data.bones)} "
          f"material_count={material_count} overall_bbox=({size.x:.1f},{size.y:.1f},{size.z:.1f})cm "
          f"skeleton_origin=({origin.x:.2f},{origin.y:.2f},{origin.z:.2f})")

    ok_lines, warn_lines = [], []
    for m in infos:
        d = (m["center"] - origin).length
        rel = (d / diag) if diag > 1e-6 else 0.0
        skin = m["skin"]
        is_rigid = skin["n_groups"] <= 1
        dangling = bool(m["orig_parent_type"] == "BONE" and m["orig_parent_bone"]
                        and m["orig_parent_bone"] not in pal_arm.data.bones)
        no_skin = m["name"] in no_skin_meshes
        cx, cy, cz = (round(v, 1) for v in m["center"])
        skin_desc = (f"skinned(groups={skin['n_groups']}, dominant "
                     f"{skin['dominant_ratio']*100:.0f}%)" if skin["n_groups"] > 0
                     else "no weights")
        parent_desc = ""
        if is_rigid:
            if m["orig_parent_type"] == "BONE" and m["orig_parent_bone"]:
                parent_desc = f" orig_parent=bone '{m['orig_parent_bone']}'"
            elif m["orig_parent_type"]:
                parent_desc = f" orig_parent_type={m['orig_parent_type']}"
        detail = (f"[{TAG}][structure]   - {m['name']}: verts={m['vcount']} {skin_desc} "
                  f"center_cm=({cx},{cy},{cz}) rel_dist_from_origin={rel*100:.1f}%{parent_desc}")
        if dangling:
            # 文言注記(2026-07-26): 「骨格原点へ落ちる」と断定していないのは
            # 意図的。負の対照(work/sx_log/negctrl)でこの経路を実際に再現・
            # 確認したところ、rebind()後もBlenderの評価結果自体は元の位置
            # (頭付近)に留まるケースがあり、"必ず原点へ落ちる"とは言い切れな
            # かった。しかし親ボーン参照が新骨格に存在しないという事実は
            # 変わらず、以降の工程(UEへのバインドポーズ書き出し等、この
            # ファイルの管理外)でどう解釈されるかは保証がない。事実
            # (参照切れ)は断定し、結果への言及は「不定」にとどめる
            warn_lines.append(
                f"[{TAG}][WARN][structural anomaly / dangling parent bone reference] {m['name']}: "
                f"in the source file this was rigidly attached directly to bone "
                f"'{m['orig_parent_bone']}' (a bone-child, not skinning), but the converted "
                f"skeleton has no bone of that name, so the reference could not be resolved. "
                f"The position may not have carried over as intended "
                f"(current center is {d:.1f}cm from the skeleton origin, {rel*100:.1f}% of overall "
                f"size. Please visually check the position in the preview image below)")
            warn_lines.append(detail)
        elif no_skin:
            # 確定判定その2(2026-07-26 HF班、指揮者提供のAlicia負例で設計):
            # remap_vertex_groups()後にこのメッシュへ対応するパルボーンの
            # 頂点グループが1つも無かった=元アバターのどのウェイトも
            # 新骨格へ引き継げず、zero-weight rescueで全頂点が救済措置で
            # 束縛された。距離やグループ数のしきい値を一切使わない事実
            # (remapの戻り値が0だったという事実そのもの)なので、dangling
            # 同様に確定情報として扱う。
            #
            # 2026-07-26 HB班追記: 束縛先はもはやpelvis固定とは限らない。
            # 非スキンメッシュ(帽子・リボン等)は元の親ボーンをpal_mapへ解決
            # できていれば(unskinned_source_bone、main()側で解決)そのボーンへ
            # 束縛されるため、その場合は文言を実態(解決できたボーン名)に
            # 合わせる。解決できず従来通りpelvisへ落ちた場合のみ、以前と同じ
            # 「一律固定」の文言を使う("pelvisへ一律固定"は嘘になってはいけない)
            target = rescue_target.get(m["name"], ZERO_WEIGHT_FALLBACK_BONE)
            if target != ZERO_WEIGHT_FALLBACK_BONE:
                warn_lines.append(
                    f"[{TAG}][WARN][structural / non-skinned mesh binding] "
                    f"{m['name']}: after remap, this mesh had zero vertex groups "
                    f"corresponding to a pal bone (a static mesh not skinned in the source "
                    f"avatar). Its original parent bone was traced and resolved to the pal "
                    f"skeleton's '{target}', and bound to it, so position/follow will match "
                    f"that bone (current center is {d:.1f}cm from the skeleton origin, "
                    f"{rel*100:.1f}% of overall size. Please visually check the position in "
                    f"the preview image below)")
            else:
                warn_lines.append(
                    f"[{TAG}][WARN][structural anomaly / skinning lost (0 pal groups)] "
                    f"{m['name']}: after remap, this mesh had zero vertex groups "
                    f"corresponding to a pal bone. The source avatar's weights could not "
                    f"be carried over to any bone in the new skeleton, so all vertices were "
                    f"rescued and rigidly bound to '{ZERO_WEIGHT_FALLBACK_BONE}'. It will not "
                    f"follow the pose, and the position/orientation is likely not as intended "
                    f"(current center is {d:.1f}cm from the skeleton origin, {rel*100:.1f}% of "
                    f"overall size. Please visually check the position in the preview image "
                    f"below)")
            warn_lines.append(detail)
        elif rel < REL_ORIGIN_ALERT and is_rigid:
            warn_lines.append(
                f"[{TAG}][WARN][please check / near origin] {m['name']}: unusually close to "
                f"the skeleton origin relative to other meshes ({rel*100:.1f}% of overall "
                f"size), and skinning is concentrated in a single group. This may indicate a "
                f"lost parent, so a visual check is recommended (this is not confirmed)")
            warn_lines.append(detail)
        else:
            ok_lines.append(detail)

    for w in warn_lines:
        print(w)
    if len(ok_lines) <= SUMMARY_MESH_LIMIT:
        for line in ok_lines:
            print(line)
    else:
        for line in ok_lines[:SUMMARY_MESH_LIMIT]:
            print(line)
        print(f"[{TAG}][structure]   ...and {len(ok_lines) - SUMMARY_MESH_LIMIT} more omitted "
              f"(within normal range: skinned and sufficiently far from the origin)")


def main():
    job, rest = vp_bl.load_job_from_argv()
    gender = rest[0] if rest else "Male"
    if gender not in ("Male", "Female"):
        core.die(TAG, f"invalid gender: {gender}")
    conv = core.job_subdir(job, "converted")
    vanilla = os.path.join(job["job_dir"], "vanilla")

    blend = os.path.join(conv, "step01_clean.blend")
    if not os.path.exists(blend):
        core.die(TAG, f"step01 produced no output: {blend}")
    bpy.ops.wm.open_mainfile(filepath=blend)

    with open(os.path.join(conv, "avatar_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    pal_map = meta["pal_map"]
    # 非スキンメッシュ(帽子・リボン等)の元の親ボーン名(step01が記録)。
    # {geo_XX: 実ボーン名}。zero-weight rescueの束縛先解決に使う
    unskinned_source_bone = meta.get("unskinned_source_bone", {})

    avatar_arm = bpy.data.objects.get(meta["armature"])
    if avatar_arm is None:
        avatar_arm = next((o for o in bpy.data.objects
                           if o.type == "ARMATURE"), None)
    if avatar_arm is None:
        core.die(TAG, "avatar Armature not found")
    meshes = [bpy.data.objects[n] for n in meta["meshes"]
              if n in bpy.data.objects]
    if not meshes:
        core.die(TAG, "avatar mesh not found")

    # 構造サマリ用: rebind()でobj.parentがpal_armへ差し替わる前の、元ファイル
    # 由来のparent_type/parent_boneを記録しておく(rebind()のコメント参照)。
    # remap_vertex_groups等の以降の処理はparent_type/parent_boneを変更しない
    # ため、ここで捕捉すれば rebind() 直前まで有効。
    orig_parent_info = {
        obj.name: {"parent_type": obj.parent_type, "parent_bone": obj.parent_bone}
        for obj in meshes
    }

    with open(os.path.join(vanilla, "common_bones.json"), encoding="utf-8") as f:
        common = json.load(f)["common"]

    # 揺れもの実験(2026-07-22、docs\sway_design.md):
    # バニラ共有骨格の服揺れチェーン(OldCloth001_04..07、pelvis直下)へ
    # 指定アバターボーンのウェイトを載せ替える。ゲームのアニメがこのボーンを
    # 動かすなら差し替えメッシュでも揺れるはず(実機検証待ちの仮説)
    sway_cloth = job.get("sway_cloth_bones") or []
    cloth_chain = []
    build_bones = common
    if sway_cloth:
        prefix = "M_" if gender == "Male" else "F_"
        cloth_chain = [f"{prefix}OldCloth001_{i:02d}" for i in (4, 5, 6, 7)]
        # KawaiiPhysicsノードは01チェーン+04チェーン+bagをまとめて駆動する
        # (実装ABPの実測)。ルートボーン欠落でノードごと不発になる事故を防ぐため、
        # ウェイトを載せないボーンも含めOldCloth系は全てスケルトンに入れる
        siblings = [f"{prefix}OldCloth001_{i:02d}" for i in (1, 2, 3)]
        bag = ("M_Outfit_OldCloth001_bag_01" if gender == "Male"
               else "F_OldCloth001_bag_01")
        build_bones = common + cloth_chain + siblings + [bag]
    pal_arm = vp_bl.build_pal_armature(
        os.path.join(vanilla, f"refskel_{gender.lower()}.json"), build_bones)

    attach_orphan_roots(avatar_arm, pal_map)
    group_targets = build_group_targets(
        avatar_arm, pal_map, job.get("merge_fingers", False))
    if sway_cloth:
        missing = [b for b in cloth_chain if b not in pal_arm.data.bones]
        if missing:
            core.die(TAG, f"sway_cloth: vanilla sway bones were not built: {missing}")
        for i, av in enumerate(sway_cloth):
            group_targets[av] = cloth_chain[min(i, len(cloth_chain) - 1)]
        print(f"[{TAG}] sway_cloth (experimental): {sway_cloth} -> {cloth_chain}")

    global_scale_and_place(avatar_arm, pal_arm, pal_map)
    auto_fit_pose(avatar_arm, pal_arm, pal_map)
    apply_shoulder_offset(avatar_arm, pal_map,
                          float(job.get("shoulder_offset_deg", 0.0)))
    bake_pose_into_meshes(avatar_arm, meshes)
    dz = snap_to_ground(meshes)
    chibi_fit_armature(pal_arm, avatar_arm, pal_map, dz)

    # U21: 指の破裂状変形の根治(noueパイプライン専用)。
    #
    # 背景: chibi_fit_armature()はpal_arm(パル骨格)の関節を「アバターの実際の
    # 関節位置」へ移動する(向き不変・位置のみ、docstring参照)。この移動後の
    # pal_arm rest poseが、以降の remap_vertex_groups/rebind でメッシュ頂点の
    # スキニング基準として使われる(=メッシュはこの配置に対して作られる)。
    #
    # ところがnoueパイプライン(build_avatar_variant.py)はテンプレートSKの
    # RefSkeleton(FTransform、=cookedバインドポーズ)をverbatimコピーするのみで、
    # このchibi-fit後の関節位置を一切反映しない(U21診断で確定、
    # docs/DEV_NOTES.md先頭のU21節参照)。その結果、注入されたメッシュ頂点
    # position(chibi-fit後の配置基準)と、cookedバインドポーズ(テンプレート
    # 自身の配置、既定はバニラ生成キャラの汎用体型)が数cm単位でズレる。
    # 手・腕は目立たないが、指は短いボーンのため即座に破裂状に見える
    # (PalMod HANDOFF.md 不具合③と同型)。
    #
    # 対策: chibi-fit後のpal_arm全ボーンのworld head位置を、メッシュ頂点と
    # 同じ座標規約(dump_avatar_mesh.py/vp_meshrestore.encode_position系列が
    # 検証済みの「Blenderワールド座標(x,y,z)->UE(x,-y,z)」変換、スケールは
    # 既にstep02のglobal_scale_and_place()でPalworld cm相当に揃え済みなので
    # 追加の100倍等は不要)でJSONへダンプする。build_avatar_variant.pyは
    # このJSONを読み、RefSkeletonのバインドポーズ位置(回転・スケールは
    # 元のまま)だけをこの値に一致するようパッチする
    # (chibi_fit_armature()が回転を一切変えない設計であることを利用し、
    # ローカル回転はテンプレート値を使い回してよい。詳細な導出はU21診断の
    # FK往復検証、docs/DEV_NOTES.md参照)。
    _chibi_bone_world_head = {
        b.name: [b.head_local.x, -b.head_local.y, b.head_local.z]
        for b in pal_arm.data.bones
    }
    _chibi_dump_path = os.path.join(
        conv, f"chibi_bone_world_head_{gender.lower()}.json")
    with open(_chibi_dump_path, "w", encoding="utf-8") as f:
        json.dump(_chibi_bone_world_head, f)
    print(f"[{TAG}] chibi_bone_world_head: {len(_chibi_bone_world_head)} bone(s) "
          f"-> {_chibi_dump_path}")

    # 揺れ髪: アバター髪を分離してバニラ髪の揺れチェーンに載せる
    hair_obj = None
    hair_assignment = {}
    hair_refskel = os.path.join(vanilla, "refskel_hair.json")
    if job.get("hair_sway", True):
        if not os.path.exists(hair_refskel):
            print(f"[{TAG}][WARN] refskel_hair.json not found — hair sway disabled "
                  "(vanilla extraction needs to be redone)")
        else:
            local_warn = []
            hair_bones = detect_hair_chains(
                avatar_arm, pal_map, job.get("hair_bones", []),
                meta.get("spring_roots", []), local_warn)
            for w in local_warn:
                print(f"[{TAG}][WARN] {w}")
            _van_hair, sway_chains = load_hair_chains(hair_refskel)
            if hair_bones and sway_chains \
                    and add_sway_hair_bones(pal_arm, hair_refskel):
                meshes, hair_obj = split_hair_mesh(meshes, hair_bones)
                if hair_obj is not None:
                    hair_assignment = assign_hair_chains(
                        pal_arm, avatar_arm, hair_bones, sway_chains)

    # no_skin_meshes: remap後にパルボーンへのウェイトが1つも無かった
    # (=0 pal groups)メッシュ名。log_structure_summary()の確定判定に使う
    # (詳細はlog_structure_summary()のdocstring参照)
    no_skin_meshes = set()
    # rescue_target: 実際にrescue_zero_weight_vertices()で束縛したパルボーン名
    # (log_structure_summary()の警告文言を実態に合わせるため)
    rescue_target = {}
    for obj in meshes:
        n_pal_groups = remap_vertex_groups(obj, group_targets)
        if n_pal_groups == 0:
            no_skin_meshes.add(obj.name)
        # 非スキンメッシュ(帽子・リボン等): 元の親ボーンをHumanoid対応表
        # (build_group_targets()が作った「実ボーン名→パルグループ名」、
        # 祖先walkのフォールバック込み)で解決し、そのパルボーンへ束縛する。
        # 解決できない場合のみ従来通りpelvis(要警告)
        target_bone = ZERO_WEIGHT_FALLBACK_BONE
        src_bone = unskinned_source_bone.get(obj.name)
        if src_bone:
            resolved = group_targets.get(src_bone)
            if resolved:
                target_bone = resolved
            else:
                print(f"[{TAG}][WARN] non-skinned mesh {obj.name}: original parent bone "
                      f"'{src_bone}' does not map to the pal skeleton, "
                      f"rescued to '{ZERO_WEIGHT_FALLBACK_BONE}'")
        rescue_target[obj.name] = target_bone
        rescue_zero_weight_vertices(obj, target_bone)
    if hair_obj is not None:
        hair_targets = dict(group_targets)
        hair_targets.update(hair_assignment)
        if remap_vertex_groups(hair_obj, hair_targets) == 0:
            no_skin_meshes.add(hair_obj.name)
        meshes = meshes + [hair_obj]

    rebind(meshes, pal_arm)
    bpy.data.objects.remove(avatar_arm, do_unlink=True)

    pal_arm.name = "Armature"
    if pal_arm.data:
        pal_arm.data.name = "Armature"

    # 成功時にも構造の要点をログへ残す(帽子が原点へ落ちる、のような
    # 「成功はしたが結果がおかしい」不具合を、検体を貰わずログだけで
    # 診断できるようにするため。CLAUDE.md「数値より先に画像を見る」の
    # ログ版: 実物を見なくても異常な位置関係に機械が気づけるようにする)
    log_structure_summary(meshes, pal_arm, orig_parent_info,
                          len(meta.get("slots", {})), no_skin_meshes,
                          rescue_target)

    out = os.path.join(conv, f"step02_{gender.lower()}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"[{TAG}] saved: {out}")


main()
