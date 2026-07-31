# -*- coding: utf-8 -*-
"""マテリアル生成まわりの共有実装(01フル構築と08マテリアルのみ更新の両方が使う)。"""

import os

import unreal

ASSET_TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary


def import_textures(C):
    """textures/のPNGをインポートする(既存なら再利用)。{ファイル名: asset}"""
    result = {}
    for name in sorted({s["texture"] for s in C.SLOTS.values() if s["texture"]}):
        asset_path = f"{C.DIR_MATERIALS}/{os.path.splitext(name)[0]}"
        if EAL.does_asset_exist(asset_path):
            result[name] = EAL.load_asset(asset_path)
            continue
        task = unreal.AssetImportTask()
        task.filename = os.path.join(C.TEX_DIR, name)
        task.destination_path = C.DIR_MATERIALS
        task.automated = True
        task.save = True
        ASSET_TOOLS.import_asset_tasks([task])
        if task.imported_object_paths:
            result[name] = EAL.load_asset(task.imported_object_paths[0])
            unreal.log(f"texture: {name}")
        else:
            unreal.log_error(f"texture import failed: {name}")
    return result


def make_material(C, slot, info, tex_asset, replace=False):
    """スペック準拠のマテリアルを生成する。
    マット化Lit(Roughness=1/Specular=0)+影の持ち上げ(SHADOW_LIFT)/アンリット。
    replace=True なら既存を消して作り直す(影の濃さだけ変える高速パス用)。"""
    name = f"M_VP_{slot}"
    path = f"{C.DIR_MATERIALS}/{name}"
    if EAL.does_asset_exist(path):
        if not replace:
            return EAL.load_asset(path)
        EAL.delete_asset(path)
    mat = ASSET_TOOLS.create_asset(name, C.DIR_MATERIALS, unreal.Material,
                                   unreal.MaterialFactoryNew())
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    # 両面: VRM側のフラグ尊重、または強制両面オプション(裏面が透けるモデル対策)
    mat.set_editor_property(
        "two_sided",
        bool(info.get("double_sided")) or getattr(C, "FORCE_TWO_SIDED", False))
    # 使用フラグ必須(無いとシップでWorldGridMaterial化)
    mat.set_editor_property("used_with_skeletal_mesh", True)
    if C.UNLIT:
        mat.set_editor_property("shading_model",
                                unreal.MaterialShadingModel.MSM_UNLIT)
        color_prop = unreal.MaterialProperty.MP_EMISSIVE_COLOR
    else:
        color_prop = unreal.MaterialProperty.MP_BASE_COLOR
        rough = MEL.create_material_expression(
            mat, unreal.MaterialExpressionConstant, -400, 250)
        rough.set_editor_property("r", 1.0)
        MEL.connect_material_property(rough, "",
                                      unreal.MaterialProperty.MP_ROUGHNESS)
        spec = MEL.create_material_expression(
            mat, unreal.MaterialExpressionConstant, -400, 350)
        spec.set_editor_property("r", 0.0)
        MEL.connect_material_property(spec, "",
                                      unreal.MaterialProperty.MP_SPECULAR)
    k = 0.0 if C.UNLIT else C.SHADOW_LIFT  # 影の持ち上げ
    if tex_asset is not None:
        node = MEL.create_material_expression(
            mat, unreal.MaterialExpressionTextureSample, -400, 0)
        node.texture = tex_asset
        if k > 0.001:
            # BaseColor=tex×(1-k)、Emissive=tex×k → 影の底が持ち上がる
            # (日なたは合計≈texで見た目維持。k=1で実質アンリット)
            mul_b = MEL.create_material_expression(
                mat, unreal.MaterialExpressionMultiply, -200, -50)
            mul_b.set_editor_property("const_b", 1.0 - k)
            MEL.connect_material_expressions(node, "RGB", mul_b, "A")
            MEL.connect_material_property(mul_b, "", color_prop)
            mul_e = MEL.create_material_expression(
                mat, unreal.MaterialExpressionMultiply, -200, 80)
            mul_e.set_editor_property("const_b", k)
            MEL.connect_material_expressions(node, "RGB", mul_e, "A")
            MEL.connect_material_property(
                mul_e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        else:
            MEL.connect_material_property(node, "RGB", color_prop)
        MEL.connect_material_property(node, "A",
                                      unreal.MaterialProperty.MP_OPACITY_MASK)
    else:
        c = info["base_color"]
        node = MEL.create_material_expression(
            mat, unreal.MaterialExpressionConstant4Vector, -400, 0)
        if k > 0.001:
            node.set_editor_property("constant", unreal.LinearColor(
                c[0] * (1 - k), c[1] * (1 - k), c[2] * (1 - k), c[3]))
            node_e = MEL.create_material_expression(
                mat, unreal.MaterialExpressionConstant4Vector, -400, 150)
            node_e.set_editor_property("constant", unreal.LinearColor(
                c[0] * k, c[1] * k, c[2] * k, c[3]))
            MEL.connect_material_property(
                node_e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        else:
            node.set_editor_property("constant", unreal.LinearColor(*c))
        MEL.connect_material_property(node, "", color_prop)
    MEL.recompile_material(mat)
    EAL.save_asset(path)
    unreal.log(f"material: {name} (unlit={C.UNLIT} shadow_lift={k})")
    return mat


def assign_materials(sk_mesh, materials_by_slot):
    mats = list(sk_mesh.materials)
    new_mats = []
    for m in mats:
        slot = str(m.material_slot_name)
        replacement = materials_by_slot.get(slot)
        if replacement is not None:
            new_mats.append(unreal.SkeletalMaterial(
                material_interface=replacement, material_slot_name=slot))
        else:
            new_mats.append(m)
            unreal.log_warning(f"slot '{slot}' に対応マテリアル無し(そのまま)")
    sk_mesh.set_editor_property("materials", new_mats)
    EAL.save_asset(sk_mesh.get_path_name().split(".")[0])
