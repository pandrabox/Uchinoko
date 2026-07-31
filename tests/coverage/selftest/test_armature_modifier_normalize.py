# -*- coding: utf-8 -*-
r"""公開issue #18: Armatureモディファイア無効フラグの入口正規化のユニット確認。

背景: 制作者が編集中に表示を切ったまま保存したファイルで、step02の
bake_pose_into_meshes の modifier_apply がBlender自身の
`RuntimeError: モディファイアーはOFFです` で変換停止していた。
修正は「エラーにせず入口(step01)+適用直前(step02)で強制ONに正規化して進む」。

vp_modnorm はbpy非依存(ダックタイピング)なので、Blender外のこのテストで
直接検証できる。実変換は伴わない(モックのみ)。

    python -m pytest tests\coverage\selftest\test_armature_modifier_normalize.py -q
"""
import os
import sys

BLENDER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "pipeline", "blender")
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

import vp_modnorm  # noqa: E402


# ---------------------------------------------------------------------------
# bpyの代役: 属性だけ合わせた素のオブジェクト
# ---------------------------------------------------------------------------

class FakeArmatureObject:
    """Armatureモディファイアのターゲット役(名前だけ持てば十分)。"""
    def __init__(self, name):
        self.name = name


_DEFAULT_TARGET = FakeArmatureObject("Armature")  # 既存テスト互換の既定ターゲット


class FakeModifier:
    def __init__(self, name, mtype, show_viewport=True, show_render=True,
                 target=_DEFAULT_TARGET):
        self.name = name
        self.type = mtype
        self.show_viewport = show_viewport
        self.show_render = show_render
        # dev#299: ARMATUREモディファイアのターゲット。Noneなら「参照切れ
        # (破棄済みArmatureを指していた)」を表す。ARMATURE以外の型では
        # 未使用(実bpyでも他モディファイア種別には無い属性)。既定は
        # 「有効なターゲットあり」(既存テストが暗黙に前提としていた状態)。
        self.object = target


class FakeMesh:
    def __init__(self, name, modifiers=(), parent_type="OBJECT"):
        self.name = name
        self.modifiers = list(modifiers)
        self.parent_type = parent_type  # 真の非スキンメッシュ=ボーン親も無い


def fake_modifier_apply(mod):
    """Blenderの modifier_apply の停止条件を再現するモック。
    show_viewport=False のモディファイアを適用しようとすると、実際の
    Blender(日本語UI)と同じ RuntimeError で停止する。"""
    if not mod.show_viewport:
        raise RuntimeError("モディファイアーはOFFです")
    return True


# ---------------------------------------------------------------------------
# 正: 無効フラグのArmatureモディファイアが強制ONへ正規化される
# ---------------------------------------------------------------------------

def test_disabled_armature_modifier_is_forced_on():
    mesh = FakeMesh("geo_00", [FakeModifier("Armature", "ARMATURE",
                                            show_viewport=False,
                                            show_render=False)])
    logs = []
    result = vp_modnorm.normalize_armature_modifiers(
        [mesh], tag="test", log=logs.append)
    mod = mesh.modifiers[0]
    assert mod.show_viewport is True
    assert mod.show_render is True
    assert result == [("geo_00", "Armature", ("show_viewport", "show_render"))]
    # 英語の正規化ログが出ること(停止ではなくログで通過する仕様)
    assert len(logs) == 1
    assert "forced ON" in logs[0]
    assert "geo_00" in logs[0] and "Armature" in logs[0]


def test_viewport_only_disabled_is_forced_on():
    mesh = FakeMesh("geo_01", [FakeModifier("Armature", "ARMATURE",
                                            show_viewport=False,
                                            show_render=True)])
    result = vp_modnorm.normalize_armature_modifiers([mesh], log=lambda s: None)
    assert mesh.modifiers[0].show_viewport is True
    assert mesh.modifiers[0].show_render is True
    assert result == [("geo_01", "Armature", ("show_viewport",))]


# ---------------------------------------------------------------------------
# 負の対照: 触ってはいけないものに触らない
# ---------------------------------------------------------------------------

def test_negative_true_unskinned_mesh_untouched():
    """真の非スキンメッシュ(モディファイア無し・ボーン親無し)は対象外。"""
    mesh = FakeMesh("geo_02", modifiers=[], parent_type="OBJECT")
    logs = []
    result = vp_modnorm.normalize_armature_modifiers(
        [mesh], log=logs.append)
    assert result == []
    assert logs == []
    assert mesh.modifiers == []  # 追加も削除もされない


def test_negative_non_armature_modifier_untouched():
    """ARMATURE以外のモディファイアは無効のまま維持(勝手にONにしない)。"""
    sub = FakeModifier("Subdivision", "SUBSURF", show_viewport=False)
    mesh = FakeMesh("geo_03", [sub])
    result = vp_modnorm.normalize_armature_modifiers([mesh], log=lambda s: None)
    assert result == []
    assert sub.show_viewport is False


def test_negative_already_enabled_not_reported():
    """全フラグONのモディファイアはログにも結果にも出ない(ノイズを増やさない)。"""
    mesh = FakeMesh("geo_04", [FakeModifier("Armature", "ARMATURE")])
    logs = []
    result = vp_modnorm.normalize_armature_modifiers([mesh], log=logs.append)
    assert result == []
    assert logs == []


# ---------------------------------------------------------------------------
# 修正前は停止 → 修正後は通過(チェック関数単体での赤→緑)
# ---------------------------------------------------------------------------

def test_apply_stops_without_fix_and_passes_with_fix():
    import pytest
    mesh = FakeMesh("geo_05", [FakeModifier("Armature", "ARMATURE",
                                            show_viewport=False)])
    # 修正前の挙動: 無効フラグのままapplyするとBlender相当のエラーで停止
    with pytest.raises(RuntimeError, match="OFF"):
        fake_modifier_apply(mesh.modifiers[0])
    # 修正後: 正規化してからapplyすれば通過し、正規化ログが残る
    logs = []
    vp_modnorm.normalize_armature_modifiers([mesh], log=logs.append)
    assert fake_modifier_apply(mesh.modifiers[0]) is True
    assert len(logs) == 1 and "forced ON" in logs[0]


def test_mixed_scene_only_armature_targets_normalized():
    """混在シーン: スキン済み(無効Armature)+真の非スキン+無効SUBSURF。
    正規化されるのはArmatureモディファイアだけ。"""
    skinned = FakeMesh("geo_10", [FakeModifier("Armature", "ARMATURE",
                                               show_viewport=False)])
    unskinned = FakeMesh("geo_11", modifiers=[])
    other = FakeMesh("geo_12", [FakeModifier("Decimate", "DECIMATE",
                                             show_viewport=False)])
    result = vp_modnorm.normalize_armature_modifiers(
        [skinned, unskinned, other], log=lambda s: None)
    assert [r[0] for r in result] == ["geo_10"]
    assert skinned.modifiers[0].show_viewport is True
    assert other.modifiers[0].show_viewport is False


# ---------------------------------------------------------------------------
# dev#299: ターゲット参照切れ(mod.object is None)のArmatureモディファイア
# ---------------------------------------------------------------------------
#
# 実機再現(2026-07-30, Blender 4.3.2 headlessで確認): show_viewport/
# show_render が両方Trueでも、ターゲットArmatureが破棄されて mod.object が
# Noneになったモディファイアに bpy.ops.object.modifier_apply を実行すると
# 「Error: Modifier is disabled, skipping apply」で失敗する。旧来の
# normalize_armature_modifiers はフラグしか見ていないため、このケースを
# 検出できず素通りしていた(実報告XU2VAL3E/2PEQ6Y4V、geo_25/Armature_1)。

def test_orphan_target_armature_modifier_is_removed():
    """ターゲットが無い(object=None)Armatureモディファイアは除去される。"""
    orphan = FakeModifier("Armature_1", "ARMATURE", target=None)
    mesh = FakeMesh("geo_25", [orphan])
    logs = []
    result = vp_modnorm.normalize_armature_modifiers(
        [mesh], tag="test", log=logs.append)
    assert mesh.modifiers == []  # 除去された
    assert result == [("geo_25", "Armature_1", vp_modnorm.ORPHAN_TARGET_REASON)]
    assert len(logs) == 1
    assert "removed" in logs[0]
    assert "geo_25" in logs[0] and "Armature_1" in logs[0]


def test_orphan_target_alongside_valid_armature_modifier():
    """dev#299の実報告と同型: 有効な'Armature'(本体アーマチュア束縛)+
    ターゲット切れの'Armature_1'(破棄された重複Armature由来)が同じメッシュに
    同居するケース。有効な方は残り、切れた方だけ除去される。"""
    valid = FakeModifier("Armature", "ARMATURE", target=FakeArmatureObject("Armature"))
    orphan = FakeModifier("Armature_1", "ARMATURE", target=None)
    mesh = FakeMesh("geo_25", [valid, orphan])
    result = vp_modnorm.normalize_armature_modifiers([mesh], log=lambda s: None)
    assert mesh.modifiers == [valid]
    assert result == [("geo_25", "Armature_1", vp_modnorm.ORPHAN_TARGET_REASON)]


def test_negative_valid_target_untouched_even_if_named_like_orphan():
    """名前が'_1'を含んでいても、ターゲットが有効なら一切触らない
    (判定基準は名前ではなくobject参照であることの負の対照)。"""
    mod = FakeModifier("Armature_1", "ARMATURE", target=FakeArmatureObject("Armature.001"))
    mesh = FakeMesh("geo_26", [mod])
    logs = []
    result = vp_modnorm.normalize_armature_modifiers([mesh], log=logs.append)
    assert result == []
    assert logs == []
    assert mesh.modifiers == [mod]


def test_apply_stops_on_orphan_target_without_fix_and_passes_with_fix():
    """赤→緑: ターゲット切れモディファイアはapply前は停止し、正規化(除去)後は
    通過する(除去されているのでそもそもapplyループの対象から外れる)。"""
    import pytest

    def fake_modifier_apply_dev299(mod):
        # 実Blenderのis_disabled: ARMATUREモディファイアはobjectが無いと
        # show_viewport/show_render に関わらず「無効」扱いになる
        if mod.object is None or not mod.show_viewport:
            raise RuntimeError("Modifier is disabled, skipping apply")
        return True

    mesh = FakeMesh("geo_25", [FakeModifier("Armature_1", "ARMATURE", target=None)])
    # 修正前の挙動: ターゲット切れのままapplyすると失敗する
    with pytest.raises(RuntimeError, match="disabled"):
        fake_modifier_apply_dev299(mesh.modifiers[0])
    # 修正後: 正規化(除去)後は、そもそもapplyループの対象に残らない
    vp_modnorm.normalize_armature_modifiers([mesh], log=lambda s: None)
    assert mesh.modifiers == []
    for mod in mesh.modifiers:
        fake_modifier_apply_dev299(mod)  # ループ本体が空なので何も起きない
