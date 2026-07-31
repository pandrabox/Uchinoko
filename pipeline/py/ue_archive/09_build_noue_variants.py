# -*- coding: utf-8 -*-
"""U13-T1: noueモード用マスター+MICマテリアル資産を開発側UEでビルドする(一度きり)。

dev#114(2026-07-29): UEクックパイプライン(convert.ps1の`$Mode -eq "ue"`分岐・
pipeline\\ue\\・pipeline\\templates\\ue_project\\)を完全削除した際、本スクリプトと
依存2本(vp_ue.py / vp_ue_mat.py)だけは「noue実行時に読まれる資産
(pipeline\\py\\noue_master\\、19MB・git追跡済み)を過去に一度だけ生成した開発専用
UEスクリプト」であり、将来この資産セットを作り直す手段として温存する必要がある
(研究正本 work\\rd_110\\PROPOSAL.md 4.4節)ため、pipeline\\ue\\から
pipeline\\py\\ue_archive\\へ移設した。**noueの実行時(通常の変換)はこのスクリプトを
一切呼ばない**(live_template.pyがpipeline\\py\\noue_master\\の成果物を読み取り専用で
参照するだけ)。将来これを再実行する場合、pipeline\\templates\\ue_project\\
(削除済み)相当のUEプロジェクトを手動で用意する必要がある。

既存vp_ue_mat.py::make_material()(旧UEクックモードが使っていたフルバイクMaterial)は
無改変のまま温存する。本スクリプトは全く別名の新規アセット(恒久マスター)+一時的に
"M_VP_{slot}"という正規名で作り直すコンボ別アセットを追加するだけで、その既存資産には
一切触れない(退行防止)。

設計(docs\\REPORT_U13_2026-07-23.md T0診断で実証済みの前提に基づく):
  - 両面表示(two_sided)はUE Material側の静的プロパティのためcook後に変えられない
    → スロット別・1面/2面別に恒久マスター4種を用意する(M_VP_{slot}_LitMaster{1S,2S})
    このマスターはpak_extractに恒久同梱し、二度と作り直さない(初回のみ生成)
  - 影の濃さ(shadow_lift)はMaterialInstanceConstant(MIC)のScalarParameterValueとして
    cook後もバイトパッチ可能(T0.2実証済み)。MICは"M_VP_{slot}"という正規名で
    (SK側の参照名と一致させる必要があるため)、コンボごとに作り直してcookし、
    結果をコンボ別ステージングフォルダへコピーする(呼び出し側の責務)
  - アンリット(unlit)はshading_modelという静的プロパティのため、影の濃さの概念が
    無くMIC化の必要も無い。"M_VP_{slot}"を通常のMaterialとして直接作る(旧来のmake_material()
    と同じ自己完結スタイル)

実行(1回のUnrealEditor-Cmd呼び出しにつき1コンボ分の"M_VP_{slot}"を作る。
恒久マスターは初回呼び出し時のみ作成、以降は既存を再利用してGUID安定=シェーダ
再コンパイルを避ける):
  環境変数 D2P_JOB=<job.json> D2P_U13_COMBO=<Lit1S|Lit2S|Unlit1S|Unlit2S>
  UnrealEditor-Cmd.exe <ue_project> -run=pythonscript
      -script=pipeline\\py\\ue_archive\\09_build_noue_variants.py -stdout -unattended -nopause -nosplash
  (呼び出し側は保存後に別途RunUATでcookし、Saved\\Cooked配下のM_VP_{slot}を
   コンボ別ステージングフォルダへコピーすること)
"""
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_ue as C
import vp_ue_mat as M

ASSET_TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary

COMBO = os.environ.get("D2P_U13_COMBO")
if COMBO not in ("Lit1S", "Lit2S", "Unlit1S", "Unlit2S"):
    raise RuntimeError(f"環境変数D2P_U13_COMBOが不正: {COMBO!r}")
UNLIT = COMBO.startswith("Unlit")
TWO_SIDED = COMBO.endswith("2S")
# プレースホルダ値はマスターの既定値(0.0)と絶対に一致させない。一致すると
# UEが「親と同じなので上書き不要」と判断しScalarParameterValueの実体を
# cook済みuexpへ一切書き出さない(U13-T0検証で実測確認)
SHADOW_LIFT_PLACEHOLDER = 0.5


def master_name(slot):
    return f"M_VP_{slot}_LitMaster{'2S' if TWO_SIDED else '1S'}"


def ensure_lit_master(slot, tex_asset):
    """恒久マスター(スロット別・1面/2面別)。既存なら再利用(シェーダ再コンパイル回避)。"""
    name = master_name(slot)
    path = f"{C.DIR_MATERIALS}/{name}"
    if EAL.does_asset_exist(path):
        return EAL.load_asset(path)
    mat = ASSET_TOOLS.create_asset(name, C.DIR_MATERIALS, unreal.Material,
                                   unreal.MaterialFactoryNew())
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    mat.set_editor_property("two_sided", TWO_SIDED)
    mat.set_editor_property("used_with_skeletal_mesh", True)

    tex_node = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSample, -400, 0)
    tex_node.texture = tex_asset

    rough = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 250)
    rough.set_editor_property("r", 1.0)
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    spec = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 350)
    spec.set_editor_property("r", 0.0)
    MEL.connect_material_property(spec, "", unreal.MaterialProperty.MP_SPECULAR)

    shadow_param = MEL.create_material_expression(
        mat, unreal.MaterialExpressionScalarParameter, -250, 150)
    shadow_param.set_editor_property("parameter_name", "ShadowLift")
    shadow_param.set_editor_property("default_value", 0.0)
    one_minus = MEL.create_material_expression(mat, unreal.MaterialExpressionOneMinus, -100, 100)
    MEL.connect_material_expressions(shadow_param, "", one_minus, "")

    mul_b = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, 50, -50)
    MEL.connect_material_expressions(tex_node, "RGB", mul_b, "A")
    MEL.connect_material_expressions(one_minus, "", mul_b, "B")
    MEL.connect_material_property(mul_b, "", unreal.MaterialProperty.MP_BASE_COLOR)

    mul_e = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, 50, 80)
    MEL.connect_material_expressions(tex_node, "RGB", mul_e, "A")
    MEL.connect_material_expressions(shadow_param, "", mul_e, "B")
    MEL.connect_material_property(mul_e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    MEL.connect_material_property(tex_node, "A", unreal.MaterialProperty.MP_OPACITY_MASK)
    MEL.recompile_material(mat)
    EAL.save_asset(path)
    unreal.log(f"[u13] permanent master saved: {path} (two_sided={TWO_SIDED})")
    return mat


def rebuild_canonical_slot_lit(slot, master):
    """"M_VP_{slot}"(正規名、SK側の参照名と一致)をMIC(parent=master)として作り直す。"""
    path = f"{C.DIR_MATERIALS}/M_VP_{slot}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    factory = unreal.MaterialInstanceConstantFactoryNew()
    mic = ASSET_TOOLS.create_asset(f"M_VP_{slot}", C.DIR_MATERIALS,
                                    unreal.MaterialInstanceConstant, factory)
    mic.set_editor_property("parent", master)
    MEL.set_material_instance_scalar_parameter_value(mic, "ShadowLift", SHADOW_LIFT_PLACEHOLDER)
    EAL.save_asset(path)
    unreal.log(f"[u13] canonical MIC rebuilt: {path} (parent={master.get_name()})")


def rebuild_canonical_slot_unlit(slot, tex_asset):
    """"M_VP_{slot}"(正規名)を自己完結のMaterial(アンリット)として作り直す。"""
    path = f"{C.DIR_MATERIALS}/M_VP_{slot}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    mat = ASSET_TOOLS.create_asset(f"M_VP_{slot}", C.DIR_MATERIALS, unreal.Material,
                                   unreal.MaterialFactoryNew())
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    mat.set_editor_property("two_sided", TWO_SIDED)
    mat.set_editor_property("used_with_skeletal_mesh", True)
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)

    tex_node = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSample, -400, 0)
    tex_node.texture = tex_asset
    MEL.connect_material_property(tex_node, "RGB", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.connect_material_property(tex_node, "A", unreal.MaterialProperty.MP_OPACITY_MASK)
    MEL.recompile_material(mat)
    EAL.save_asset(path)
    unreal.log(f"[u13] canonical unlit material rebuilt: {path}")


textures = M.import_textures(C)
n_slots = 0
for slot, info in C.SLOTS.items():
    tex = textures.get(info["texture"]) if info["texture"] else None
    if tex is None:
        unreal.log_warning(f"[u13] slot {slot}: テクスチャ無し、noueバリアント生成をスキップ")
        continue
    n_slots += 1
    if UNLIT:
        rebuild_canonical_slot_unlit(slot, tex)
    else:
        master = ensure_lit_master(slot, tex)
        rebuild_canonical_slot_lit(slot, master)

unreal.log(f"[u13] combo={COMBO} slots={n_slots}")
unreal.log("===== U13_NOUE_VARIANTS_DONE =====")
