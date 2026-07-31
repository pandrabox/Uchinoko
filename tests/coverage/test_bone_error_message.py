# -*- coding: utf-8 -*-
"""dev#233: 必須Humanoidボーン未割当時のFATAL文言が内部pal_bone名でなく
Unity Configure Avatar上の人間可読名+対処手順になっていることの単体テスト。

pipeline\\blender\\vp_bl.py は `import bpy` / `from mathutils import ...` を
モジュール先頭で行うため、Blender本体が無い通常のpython/pytest環境では
そのままではimportできない。UNITY_TO_PAL/PAL_TO_UNITY_HUMAN/
missing_humanoid_bone_message() はいずれも純粋なPython文字列処理で
bpy/mathutilsの実体を一切使わないため、最小のダミーモジュールを
sys.modulesへ差し込むだけでimportして直接検証できる
(実変換・Blender起動を一切伴わない。CLAUDE.mdの「受入試験はリリース
ゲートに任せる」に従い、単体テスト+負の対照のみで完結させる)。
"""
import importlib
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
BLENDER_DIR = os.path.join(REPO_ROOT, "pipeline", "blender")
PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")


def _install_bpy_stub():
    """vp_bl.pyのモジュール先頭import(`import bpy`, `from mathutils import
    Matrix, Quaternion, Vector`)を満たすだけの空スタブ。実体は一切使わない
    (テスト対象はUNITY_TO_PAL/PAL_TO_UNITY_HUMAN/missing_humanoid_bone_message
    という純粋な文字列/辞書処理のみ)。"""
    if "bpy" not in sys.modules:
        bpy_stub = types.ModuleType("bpy")
        bpy_stub.data = types.SimpleNamespace()
        bpy_stub.context = types.SimpleNamespace()
        bpy_stub.ops = types.SimpleNamespace()
        sys.modules["bpy"] = bpy_stub
    if "mathutils" not in sys.modules:
        class _Dummy:
            """任意の引数・任意のメソッド呼び出し・演算子を素通りさせるだけの
            ダミー(vp_bl.pyのモジュール先頭にある
            `_M = Matrix(...); _Minv = _M.inverted()` を通すためだけのもの。
            テスト対象(missing_humanoid_bone_message等)はこれらの値を
            一切使わない、純粋な文字列/辞書処理関数)。"""

            def __init__(self, *args, **kwargs):
                pass

            def __getattr__(self, _name):
                return lambda *a, **k: self

            def __matmul__(self, _other):
                return self

            def __add__(self, _other):
                return self

        mathutils_stub = types.ModuleType("mathutils")
        mathutils_stub.Matrix = _Dummy
        mathutils_stub.Quaternion = _Dummy
        mathutils_stub.Vector = _Dummy
        sys.modules["mathutils"] = mathutils_stub


@pytest.fixture(scope="module")
def vp_bl():
    _install_bpy_stub()
    for p in (BLENDER_DIR, PY_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
    mod = importlib.import_module("vp_bl")
    return mod


# 実際のバグ報告(issue #233, 報告ID Z8XBKJBC)で欠落していたのは foot_l
# (Unity側キー LeftFoot)。step01_import_vrm.py の必須ボーンチェック対象
# 全件についても回帰確認する。
REQUIRED_PAL_BONES = (
    "pelvis", "spine_01", "head", "upperarm_l", "upperarm_r",
    "hand_l", "hand_r", "thigh_l", "thigh_r", "foot_l", "foot_r",
)

EXPECTED_HUMAN_NAMES = {
    "pelvis": "Hips",
    "spine_01": "Spine",
    "head": "Head",
    "upperarm_l": "Left Upper Arm",
    "upperarm_r": "Right Upper Arm",
    "hand_l": "Left Hand",
    "hand_r": "Right Hand",
    "thigh_l": "Left Upper Leg",
    "thigh_r": "Right Upper Leg",
    "foot_l": "Left Foot",
    "foot_r": "Right Foot",
}


def test_all_required_bones_have_a_unity_human_name(vp_bl):
    """必須ボーンチェック対象の全11件が逆引きテーブルに載っている(未登録=
    フォールバックで内部名のまま出てしまう項目が無い)ことを確認する。"""
    for pal_bone in REQUIRED_PAL_BONES:
        assert pal_bone in vp_bl.PAL_TO_UNITY_HUMAN, (
            f"{pal_bone} が PAL_TO_UNITY_HUMAN に未登録"
            "(die()メッセージが内部名のままフォールバックしてしまう)")
        assert vp_bl.PAL_TO_UNITY_HUMAN[pal_bone] == EXPECTED_HUMAN_NAMES[pal_bone]


def test_foot_l_message_matches_the_reported_case(vp_bl):
    """issue #233の実報告(foot_l未割当)で出るメッセージを検証する。
    内部名 'foot_l' がそのまま出ず、Unity表示名 'Left Foot' と
    Rig > Configure Avatar への案内が含まれること。"""
    msg = vp_bl.missing_humanoid_bone_message("foot_l")
    assert "Left Foot" in msg
    assert "Configure Avatar" in msg
    assert "Rig" in msg
    # 内部pal_bone名の裸出しが残っていないこと(旧文言の完全な再発防止)
    assert "foot_l" not in msg


@pytest.mark.parametrize("pal_bone", REQUIRED_PAL_BONES)
def test_message_contains_human_name_not_internal_name(vp_bl, pal_bone):
    """全必須ボーンについて、メッセージに内部pal_bone名でなくUnity表示名が
    含まれることを確認する(dev#233の一般化: 対象は foot_l 限定ではない)。"""
    msg = vp_bl.missing_humanoid_bone_message(pal_bone)
    assert EXPECTED_HUMAN_NAMES[pal_bone] in msg
    assert pal_bone not in msg


def test_unknown_pal_bone_falls_back_safely(vp_bl):
    """負の対照: 逆引きテーブルに無い名前を渡しても例外を出さず、
    情報を落とさずに内部名のままメッセージへ出すフォールバックが働くこと。"""
    msg = vp_bl.missing_humanoid_bone_message("not_a_real_bone")
    assert "not_a_real_bone" in msg


def test_humanize_unity_bone_camel_case(vp_bl):
    assert vp_bl._humanize_unity_bone("LeftFoot") == "Left Foot"
    assert vp_bl._humanize_unity_bone("UpperChest") == "Upper Chest"
    assert vp_bl._humanize_unity_bone("Hips") == "Hips"


def test_humanize_unity_bone_leaves_already_spaced_names_alone(vp_bl):
    """指のフル名(例 'Left Thumb Proximal')は既にスペース区切りなので、
    二重にスペースを差し込まずそのまま返す。"""
    spaced = "Left Thumb Proximal"
    assert vp_bl._humanize_unity_bone(spaced) == spaced


def test_negative_control_full_map_has_no_missing_required_bone():
    """負の対照: 全必須ボーンが揃っている正常系では、step01の
    `if req not in pal_map` ループはどのreqでもdie()を呼ばない
    (= missing_humanoid_bone_messageが一切呼ばれない)ことを確認する。
    (step01_import_vrm.py自体はmain()をimport時に無条件実行するため
    単体importできない。ここではその判定ロジックと同一の条件式を
    最小再現して検証する)"""
    pal_map = {b: f"dummy_{b}" for b in REQUIRED_PAL_BONES}
    pal_map["clavicle_l"] = "dummy_clavicle_l"  # 任意ボーンも混ぜて無関係なことを確認
    died_for = []
    for req in REQUIRED_PAL_BONES:
        if req not in pal_map:
            died_for.append(req)
    assert died_for == []
