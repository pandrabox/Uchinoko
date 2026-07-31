"""U4 T1: 実アバターメッシュ(パルワールド骨格にウェイト済み)のレンダー頂点分割ダンプ。

パイプライン調査結果(work\\toto配下の実成果物とpipeline\\blender\\step0*.pyの
ソースを読んで特定):
  - `pipeline\\blender\\step02_retarget.py` の出力 `converted\\step02_{gender}.blend`
    が「パル骨格へウェイト移植+バインド済み」の最終形(docstring:
    「ウェイトをパル名へ移植...バインド」)。
  - `step03_export_fbx.py` はこれをFBX化するだけの後工程(ジオメトリ・
    ウェイトの追加変更なし。HairSwayオブジェクトと`hair_*`ボーンを本体
    出力から除外するのみ)。
  - よって本スクリプトは`step02_{gender}.blend`を直接開き、step03と同じ
    「HairSwayを除く全MESHオブジェクト」を対象にする(FBXへの往復エクスポート/
    インポートによる再量子化を避けるため、devtools\\dump_restore_geometry.py
    (FBXベース)より.blend直読みを選んだ)。
  - toto(女性)実測: step02_female.blend は ARMATURE(65ボーン、Bronze001と
    同数=同一パル骨格) + MESH geo_00(21402頂点)/geo_01(1399)/geo_02(4320)/
    geo_03(2524)の4オブジェクト。HairSwayオブジェクトは非存在(hair_sway
    機能未使用のtoto build)。

## レンダー頂点分割(UEのcookと同じ考え方)

Blenderの頂点は複数ポリゴンで共有され、UV/法線はループ(頂点×隣接面)属性
なので、(位置, UV, 法線, タンジェント, 従法線符号)の組が異なるループは
別頂点として複製する。同じ組のループは同一頂点として共有する(重複排除)。
スキンウェイトは元のBlender頂点(vi)に紐づくため、分割後の複数頂点が
同じviを指していれば同じウェイトを持つ。

## 出力形式(次の人が別メッシュで再現できる粒度)

JSON、トップレベル:
  {"gender": "Female", "source_blend": "...", "max_influences": 8,
   "num_vertices": N, "num_triangles": T,
   "vertices": [{"pos":[x,y,z](m,ワールド座標), "normal":[x,y,z],
                 "tangent":[x,y,z], "bitangent_sign": +-1.0,
                 "uv":[u,v], "weights": [[bone_name, weight], ...] (和=1)}, ...],
   "triangles": [[i0,i1,i2], ...] }

pos/normal/tangentはワールド座標変換済み(devtools\\dump_restore_geometry.py
と同じ流儀: mw@position、(mw.to_3x3().normalized())@法線/タンジェント)。
weightsは頂点ごとに重み降順ソート済み、上位max_influences個に切り捨てた上で
和=1へ再正規化済み(cooked skin_weightのu8エンコード時の再正規化と二重に
なるが、G1ゲート(和=1±1e-3)をダンプ単体で検証可能にするため、この段階で
正規化しておく)。

## 重要な単位系の罠(本セッションで発見、次の人向けに明記)

`pipeline\\blender\\step02_retarget.py`の`global_scale_and_place()`は
アバターをパルワールドの実寸(RefSkeletonがcm単位)に直接一致させるよう
スケール・配置する。**その結果、step02_{gender}.blendのオブジェクト座標の
生の数値は「Blenderが1ユニット=1mだと仮定して扱う値」がそのまま
センチメートル相当になる**(scale_lengthは変更されておらずBlender既定の
ままだが、メッシュの実寸自体をパルワールドのcm数値に合わせて拡大している
ため)。実測: toto(Female)のz座標範囲が[0.0, 126.0](=U3が20角両錐の
Z_TOP=126cmとして独立に定めた「頭の高さ」と完全一致)。実際に1m=1mの
メッシュなら数値は[0, 1.26]になるはずで、そうなっていない。

`pipeline\\py\\vp_meshrestore.py`の`encode_position()`/
`blender_pos_to_ue_cm()`は「Blender側位置はm単位」という前提で内部で
×100している(P2セッションがFBX経由(=step03のglobal_scale=0.01適用後、
実寸mに変換された後)のジオメトリで検証した式のため)。本ダンプは
step03のFBXエクスポートを経由せず.blendを直接読むため、その×100は
二重適用になり10000倍の位置ズレを起こす(実際に発生し、build_avatar_variant.py
の最初の実行でvp_core.parse_skeletalmesh_buffersの範囲外チェック
(position頂点0=(0.0, 1585.97, 9296.11)cm)で検出した)。

対策: 本スクリプトは`pos`をワールド座標の生値を**100で割ってから**
記録する(=`encode_position()`が想定する「m単位」に変換してから渡す。
ちょうどstep03_export_fbx.pyの`global_scale=0.01`と同じ意味の補正)。
normal/tangentは単位方向ベクトルなのでスケールの影響を受けず補正不要。

実行: <blender.exe> --background --factory-startup --python-exit-code 1 --python dump_avatar_mesh.py -- \\
    <step02_blend_path> <gender:Male|Female> <out.json> [max_influences=8] [avatar_meta.jsonパス]

## U7 T1で追加: マテリアル別三角形分類(format=2)

各三角形に`material`(0=body/1=parka)を追加した。判定は`avatar_meta.json`
(既定: step02_blend_pathと同じ`converted`フォルダの`avatar_meta.json`)の
`slots[m??]['orig_name']`を読み、`classify_material()`で0/1へ分類する
(オブジェクト単位ではなく、面のマテリアルスロット単位。1オブジェクトに
複数マテリアルが混在する場合(alicia実測: geo_07/geo_08)にも対応する)。

判定規則(`classify_material`のdocstring参照): orig_nameが完全一致
'body'→0、'parka'→1。それ以外は'wear'/'cloth'/'parka'/'outfit'/'costume'の
いずれかを含むかで判定(含む→1=parka、含まない→0=body)。toto(Female)は
'body'/'parka'の完全一致のみで100%決着(オラクル実測: m00=49435/m01=8446、
テンプレートSK Section0/1と厳密一致)。alicia(Male)は12マテリアル
(m00〜m11)を持ち、'body_wear'/'wear'/'hair_wear'の3件が'wear'を含むため
1(parka)、残り9件(body/eye/face/eye_white/face_mastuge/hair/
hair_trans_zwrite/hair_trans/other_zwrite)は0(body)に分類される
(m11 'Alicia_other_zwrite'は装飾品/アクセサリの可能性があり判別が難しい
ため既定の0側へ倒した。次の人向けの判断根拠は
docs\\REPORT_U7_*.md参照。オラクル未確認、後述)。

出力トップレベルに以下を追加: `"format": 2`,
`"material_slot_map": {slot_name: 0|1, ...}`,
`"material_triangle_counts": {"0": N0, "1": N1}`。
`triangles`の各要素は`[i0, i1, i2, material]`(4要素、末尾がmaterial)に変更
(旧format=1の3要素`[i0,i1,i2]`とは非互換。旧形式ダンプ・旧build_avatar_variant.py
はそのままでは読めなくなる。次工程(T2)のビルダーは新format=2前提で書き直す)。

## dev#193で追加: NaN/Inf頂点位置のfail-fast検出

問合せW5S4T8HL(BOOTHミラー)で判明: Blenderのアーマチュアデフォーム評価が
まれにNaN頂点位置を生む(根本原因は未確定、スケール0ボーン仮説あり・別issue
で追う)。従来はここで検出せず、55%地点でOutfit SK 58件へ注入する段になって
初めて`vp_core.parse_skeletalmesh_buffers`が1件ずつバラバラに検出していた
(「どのメッシュのどの頂点か」が全く見えない)。本スクリプトは頂点のワールド
座標を計算した直後に`math.isfinite()`で有限性を検証し、違反があれば対象
メッシュオブジェクト名・頂点インデックス・最大寄与ボーン名を含む
`RuntimeError`を工程の頭で1回だけ出す。変換結果(正常ケースの出力)は不変
(検出のみの追加、Layers-Affected: none)。

## dev#153で強化: 「最初の1個」ではなく分布と発生段階まで出す

dev#193の実装は**最初に見つけたNaN頂点1個で即raise**していた。これは下流
(`vp_core._parse_skeletalmesh_buffers_with_index`、頂点0から昇順に走査して
最初の範囲外で`SkMeshParseError`)と全く同じ盲点で、実報告W5S4T8HLの
「position頂点135279が範囲外」も**「135279番が壊れている」ではなく
「0〜135278番は有限、最初の破綻が135279番」**という意味しかない。
何個壊れているのか(1頂点なのかオブジェクト丸ごとなのか)は分からず、
原因の切り分けに最も効く情報がちょうど落ちていた。

WP153のBlender 4.3.2実測(work\\wp153\\probe*.log)で確認した性質:
  - ボーン/オブジェクトのスケール0・極小・特異な親inverse・Preserve Volume
    (デュアルクォータニオン)の反平行特異点は、いずれもNaNを生まない
    (mathutilsの`normalized()`はゼロ長ベクトルへゼロを返し、
    `rotation_difference()`はゼロベクトルへ単位クォータニオンを返す)。
    dev#258の否定結果はオブジェクト階層・DQS・親inverseまで拡張して成立する。
  - **1本のボーンのポーズ行列がNaNだと、そのボーンにウェイトされた頂点だけが
    まとめてNaNになる**(他オブジェクトは無傷)。つまり実報告の
    「途中の頂点番号から壊れる」形と一致するのは、全体的な変換破綻ではなく
    **特定ボーン/特定オブジェクトの局所破綻**である。
  - NaN頂点座標はFBXの往復では運ばれない(Blenderのメッシュ検証が非有限座標を
    0へ潰す)。すなわちNaNはインポート後に作られている。

したがって本ガードは、検出したら即raiseせず**そのオブジェクトを走査し切って
から**、①影響頂点数/全頂点数 ②発生段階(オブジェクト変換行列/変形前の元座標/
アーマチュア変形/ループ属性)③寄与ボーンとそのポーズ行列の有限性、を1つの
エラーにまとめて出す。ログだけが唯一の診断チャネルである(検体は入手できない)
という本プロジェクトの前提から、この分布情報は必須である。

法線・タンジェント・UVも同時に検証する。位置と違って**下流に検査が一切無く**、
`vp_meshrestore.encode_uv0()`はNaN UVをhalf floatとして黙って書き込むため
(WP153実測: `encode_uv0(nan,0.0)` -> `007e003c`、例外なし)、「変換は成功
したのに絵が壊れている」という最も報告しづらい形で出てしまう。
"""
import json
import math
import os
import sys

import bmesh
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
blend_path, gender, out_path = argv[0], argv[1], argv[2]
max_influences = int(argv[3]) if len(argv) > 3 else 8
avatar_meta_path = argv[4] if len(argv) > 4 else os.path.join(
    os.path.dirname(blend_path), "avatar_meta.json")

ROUND = 6


# U50-single: 単一マテリアル化(pipeline\py\vp_atlas.py の同名定数と同期必須)
SINGLE_MATERIAL = True


def classify_material(orig_name):
    """avatar_meta.jsonのslots[m??]['orig_name']から0(body)/1(parka)を判定する。

    完全一致'body'->0、'parka'->1。それ以外は'wear'/'cloth'/'parka'/'outfit'/
    'costume'/'overalls'/'mohu'/'mofu'のいずれかを含むかどうかで判定する
    (着脱可能な衣装・装飾を示す語を含めば1=parka、含まなければ0=body)。
    toto実測ではbody/parkaの完全一致のみで全マテリアルが決着する(単純な
    1オブジェクト=1マテリアル構成)。alicia実測(12マテリアル)は'wear'を
    含む3件(body_wear/wear/hair_wear)が1、残り9件が0になる。'overalls'は
    U16 Shata実測で追加(既存キーワードに一致する語が皆無だと全三角形が
    material=0に倒れ、2セクションSKへの注入が「material=1の三角形が0件」で
    全滅する事故を確認したため)。'mohu'/'mofu'はFIX3a(2026-07-24)で追加:
    毛皮襟パーツ(heon/zizi/flatif等の"mohu"、pgftestの"0mofu")が従来
    material=0(body)へ強制併合され素肌メッシュと同一セクションで重なる
    (z-fighting/裂けの疑い、docs\\DIAG_TEARING_2026-07-24.md)ため、
    衣装側(material=1)へ回す試行。

    U50-single(2026-07-25、責任者裁定): **常に0を返す**(単一マテリアル化)。
    キーワード判定はSK側のスロット役(t00/t01)と一致して初めて正しく、
    実測で注入対象60SK中16SKが不一致だった(work\\u50_equip\\out\\FINDINGS2.txt
    5節)。1マテリアルへ畳めばこの不整合は起こりようがない(実測NG 0件)。
    `pipeline\\py\\vp_atlas.py`の`classify_material()`(同期必須)も同時に
    単一化してある。"""
    if SINGLE_MATERIAL:
        return 0
    name = orig_name.lower()
    if name == "body":
        return 0
    if name == "parka":
        return 1
    for kw in ("wear", "cloth", "parka", "outfit", "costume", "overalls",
               "mohu", "mofu"):
        if kw in name:
            return 1
    return 0


def _finite3(v):
    """3成分ベクトル(mathutils.Vector / tuple)の全成分が有限かどうか。"""
    return math.isfinite(v[0]) and math.isfinite(v[1]) and math.isfinite(v[2])


def _finite_matrix(m):
    return all(math.isfinite(c) for row in m for c in row)


def _armature_object_of(obj):
    """メッシュオブジェクトを変形しているArmatureモディファイアの対象を返す。"""
    for mod in obj.modifiers:
        if mod.type == "ARMATURE" and mod.object is not None:
            return mod.object
    return None


def _diagnose_non_finite(obj, mesh, mw, weights_by_vertex, bad_pos, bad_attrs):
    """非有限ジオメトリの診断文を組み立てる(dev#153)。

    検体は入手できない(有料アセットで再配布不可)ため、**ログ本文だけで
    次の一手が決まる**ところまで書き切るのがこの関数の責務である。具体的には:

      - どのオブジェクトの何頂点が壊れたか(分布。1頂点かオブジェクト全滅かで
        原因の階層が変わる)
      - どの段階で壊れたか。`mw`(オブジェクトのワールド行列)/ 変形前の元座標
        (`obj.data.vertices[].co`)/ アーマチュア変形後の評価座標、の3点を
        個別に検査して段階を一意に決める
      - どのボーンが関与しているか。壊れた頂点のウェイト先ボーンを集計し、
        さらにそのボーンのポーズ行列自体が非有限かどうかまで見る
        (WP153実測: ポーズ行列がNaNのボーンは、そのボーンにウェイトされた
        頂点だけを丸ごとNaNにする)
    """
    lines = []
    n_eval = len(mesh.vertices)
    # 三角形ループ経由の検出(bad_pos)は「三角形に使われている頂点」しか見て
    # おらず分布の母数として不正確なので、失敗が確定したこの時点で評価済み
    # メッシュ全体を1回だけ走査し直して正確な影響範囲を出す
    # (この全走査は失敗経路にしか無いので、正常時の速度には一切影響しない)。
    if bad_pos:
        for i, v in enumerate(mesh.vertices):
            if i not in bad_pos:
                p = (mw @ v.co) * 0.01
                if not _finite3(p):
                    bad_pos[i] = (p.x, p.y, p.z)
    n_bad = len(bad_pos)
    first_vi = min(bad_pos) if bad_pos else None

    def w_of(vi):
        """weights_by_vertex は元(変形前)の頂点配列で作られている。モディファイアが
        頂点数を変えた場合は評価後インデックスと対応しないので None を返す。"""
        if vi is None or vi >= len(weights_by_vertex):
            return None
        return weights_by_vertex[vi]

    if bad_pos:
        _fw = w_of(first_vi)
        lines.append(
            f"non-finite vertex position detected in {obj.name!r} "
            f"vertex_index={first_vi}: pos={bad_pos[first_vi]} "
            f"top_weight_bone={(_fw[0][0] if _fw else None)!r}")
    else:
        lines.append(f"non-finite loop attribute detected in {obj.name!r}")
    lines.append(f"  object                : {obj.name!r}")

    if bad_pos:
        pct = (100.0 * n_bad / n_eval) if n_eval else 0.0
        lines.append(
            f"  affected vertices     : {n_bad} / {n_eval} evaluated vertices "
            f"({pct:.1f}%)")
        sample = sorted(bad_pos)[:16]
        lines.append(f"  affected indices      : {sample}"
                     f"{' ...' if n_bad > len(sample) else ''}")
        lines.append(
            "  distribution          : "
            + ("ALL vertices of this object -> cause is object-level or "
               "bone-level, not per-vertex"
               if n_bad == n_eval else
               "a subset of this object's vertices -> cause is per-vertex "
               "or limited to one bone's influence set"))

    # --- 段階の特定 ---
    mw_ok = _finite_matrix(mw)
    lines.append(f"  matrix_world finite   : {mw_ok}")

    rest_verts = obj.data.vertices
    rest_comparable = len(rest_verts) == n_eval
    rest_bad = None
    if bad_pos and rest_comparable:
        rest_bad = [vi for vi in bad_pos if not _finite3(rest_verts[vi].co)]
        lines.append(
            f"  pre-deform (rest) co  : non-finite in {len(rest_bad)} of "
            f"{n_bad} affected vertices "
            f"(total source vertices={len(rest_verts)})")
    elif bad_pos:
        lines.append(
            "  pre-deform (rest) co  : not comparable "
            f"(source verts={len(rest_verts)} != evaluated verts={n_eval}; "
            "a modifier changed the vertex count)")

    if not mw_ok:
        stage = ("object_transform -- the evaluated object's world matrix is "
                 "itself non-finite; every vertex of this object is corrupted "
                 "by definition")
    elif rest_bad:
        stage = ("source_geometry -- the coordinates were ALREADY non-finite "
                 "before armature evaluation (born upstream of this script: "
                 "import / step01 / step02 output)")
    elif bad_pos and rest_comparable:
        stage = ("armature_deform -- rest coordinates are finite but the "
                 "deformed coordinates are not (born in Blender's armature "
                 "evaluation of this .blend)")
    elif bad_pos:
        stage = "unknown -- rest/evaluated vertex indices are not comparable"
    else:
        stage = "loop_attribute -- positions are finite; a per-loop attribute is not"
    lines.append(f"  stage                 : {stage}")

    # --- ボーンの関与 ---
    if bad_pos:
        bone_hits = {}
        for vi in bad_pos:
            for bone_name, _w in (w_of(vi) or ()):
                bone_hits[bone_name] = bone_hits.get(bone_name, 0) + 1
        top = sorted(bone_hits.items(), key=lambda kv: -kv[1])[:8]
        lines.append(f"  bones weighted to them: {top}"
                     f"{' ...' if len(bone_hits) > len(top) else ''}")
        arm = _armature_object_of(obj)
        if arm is None:
            lines.append("  armature              : (no armature modifier on this object)")
        else:
            nf_bones = [pb.name for pb in arm.pose.bones
                        if not _finite_matrix(pb.matrix)]
            lines.append(
                f"  armature              : {arm.name!r} "
                f"matrix_world_finite={_finite_matrix(arm.matrix_world)} "
                f"non_finite_pose_bones={nf_bones[:8]}"
                f"{' ...' if len(nf_bones) > 8 else ''} "
                f"({len(nf_bones)}/{len(arm.pose.bones)})")

    # --- ループ属性(法線/タンジェント/UV) ---
    if bad_attrs:
        counts = {}
        for kind, _li, _vi, _val in bad_attrs:
            counts[kind] = counts.get(kind, 0) + 1
        kind, li, vi, val = bad_attrs[0]
        lines.append(f"  non-finite loop attrs : {counts} "
                     f"(first: {kind} loop={li} vertex_index={vi} value={val})")
        lines.append(
            "  note                  : loop attributes have NO downstream "
            "check -- vp_meshrestore.encode_uv0() packs a NaN UV silently, so "
            "this would otherwise ship as a 'successful' but visually broken pak")

    lines.append(
        "  Aborting dump before this NaN/Inf reaches downstream SK injection "
        "(dev#193 fail-fast / dev#153 diagnostics; see W5S4T8HL). "
        "Report this whole block when filing an issue.")
    return "\n".join(lines)


with open(avatar_meta_path, encoding="utf-8") as f:
    _avatar_meta = json.load(f)
slot_material_class = {
    slot: classify_material(info.get("orig_name", ""))
    for slot, info in _avatar_meta.get("slots", {}).items()
}
# U16: preflight G4の収録数整合のためavatar_meta.jsonの"slots"を2枠へ
# 絞り込んだ場合(trim_avatar_meta.py)でも、絞り落とされたスロットの
# orig_nameは"_all_slots_orig_name"に退避されているので、そちらを使って
# classify_material()し直す(絞り込み前と同じ分類結果を保つ。絞り込み後の
# "slots"だけを見ると情報が失われ、全三角形がmaterial=0に潰れる事故になる)
for slot, orig_name in _avatar_meta.get("_all_slots_orig_name", {}).items():
    if slot not in slot_material_class:
        slot_material_class[slot] = classify_material(orig_name or "")
print(f"[dump_avatar_mesh] slot_material_class={slot_material_class}")

bpy.ops.wm.open_mainfile(filepath=blend_path)

if "HairSway" in bpy.data.objects:
    bpy.data.objects.remove(bpy.data.objects["HairSway"], do_unlink=True)

deps = bpy.context.evaluated_depsgraph_get()

mesh_objs = [o for o in bpy.data.objects if o.type == "MESH"]
if not mesh_objs:
    raise RuntimeError(f"no MESH object found: {blend_path}")

vert_key_to_index = {}
vertices = []  # 分割後の頂点(dict)
triangles = []  # [i0,i1,i2] グローバル索引

total_src_verts = 0
total_src_tris = 0

total_material_tri_counts = {0: 0, 1: 0}

for obj in sorted(mesh_objs, key=lambda o: o.name):
    obj_slot_names = [ms.material.name if ms.material else None for ms in obj.material_slots]
    unknown_slots = {s for s in obj_slot_names if s is not None and s not in slot_material_class}
    if unknown_slots:
        # U16実測(Heon等、body/parka以外の3件目以降のマテリアルスロットを持つ
        # kemono系アバター): pak側は解剖学的にbody/parka2スロットしか持たないため
        # (resolve_textures()と同じ理由)、G4整合のためavatar_meta.jsonのslots
        # から2スロットへ絞り込んでいる場合がある。絞り込まれたスロットの
        # 三角形はclassify_material()の既定(0=body)へ倒して警告するに留める
        # (幾何欠落より軽微、ライセンス非関連の技術判断のため0節聖域条項の対象外)
        print(f"[dump_avatar_mesh][WARN] {obj.name}: material slot(s) not in "
              f"avatar_meta.json (defaulting to material=0): {unknown_slots}")
        for s in unknown_slots:
            slot_material_class[s] = 0
    vg_names = {vg.index: vg.name for vg in obj.vertex_groups}
    weights_by_vertex = []
    for v in obj.data.vertices:
        pairs = sorted(
            ((vg_names.get(g.group, "?"), g.weight) for g in v.groups if g.weight > 0),
            key=lambda p: -p[1])[:max_influences]
        total = sum(w for _, w in pairs)
        if total <= 0:
            weights_by_vertex.append(None)
            continue
        norm = [[n, w / total] for n, w in pairs]
        diff = 1.0 - sum(w for _, w in norm)
        norm[0][1] += diff
        weights_by_vertex.append(norm)
    total_src_verts += len(obj.data.vertices)

    eo = obj.evaluated_get(deps)
    mesh = eo.to_mesh()

    # WP-7781(dev#81ケースB): ポリゴンを1枚も持たないメッシュ(当たり判定用・
    # 補助メッシュ等。実報告4AL4M4GTのgeo_00=AvatarHight、頂点1個・ポリゴン0個)。
    # このケースは`mesh.uv_layers`が非空(VRMインポート由来のUVレイヤーという
    # "入れ物"自体は残っている)でも、ループ(=UVデータの実体)が0件のため
    # 直後の`mesh.calc_tangents()`が
    # `Error: Tangent space computation needs a UV Map, ... not found`で
    # 例外を投げる(WP-7781実測、work\\wp_7781\\case_b_baseline.log)。
    # ポリゴンが無ければ三角形化・tangent計算はそもそも無意味なので、
    # calc_tangents()を呼ぶ前にここで検出し、警告のみでメッシュ全体を
    # スキップする(triangles/verticesに一切寄与させない)。
    if len(mesh.polygons) == 0:
        eo.to_mesh_clear()
        print(f"[dump_avatar_mesh][WARN] {obj.name}: mesh has 0 polygons, "
              f"skipping tangent/triangle computation for this object "
              f"(no contribution to vertices/triangles)")
        print(f"[dump_avatar_mesh] {obj.name}: src_verts={len(obj.data.vertices)} "
              f"tris=0 (running total split_verts={len(vertices)}) [skipped: 0 polygons]")
        continue

    if not mesh.uv_layers:
        # WP-7781(dev#81ケースA): ポリゴンは持つがUVレイヤーが0枚のメッシュ
        # (issue #81本文の想定検体そのもの。ボーン1本+UV削除Cubeで実測済み、
        # work\\wp_7781\\case_a_baseline.log)。従来はここで即raiseし変換全体を
        # 停止させていたが、見た目への影響が小さい(a)方針(空UVレイヤー合成+
        # 継続)を採用する。`mesh.uv_layers.new()`はBlenderの既定動作で各面へ
        # (0,0)-(1,0)-(1,1)-(0,1)の単位正方形UVを自動割当する(WP-7781実測、
        # 全頂点(0,0)固定になるわけではない)。この合成UVはcalc_tangents()が
        # 破綻しない非退化な値であれば足り、位置・法線・ウェイトは無傷。
        synth = mesh.uv_layers.new(name="__d2p_synth_uv0")
        print(f"[dump_avatar_mesh][WARN] {obj.name}: no UV layer, "
              f"synthesizing a default UV layer and continuing")
        uvmap_name = synth.name
    else:
        uvmap_name = mesh.uv_layers[0].name
    # calc_tangents()はn-gon(5角形以上)を含むメッシュでは動作しない
    # (Blender API制約: tris/quadsのみ)。Heon実測(jacketメッシュ)で発覚。
    # 既存メッシュ(toto等、既にtris/quadsのみ)への影響を避けるため、
    # n-gonのみを対象にin-place三角形分割する(tris/quadsはそのまま)
    ngon_faces = [f for f in mesh.polygons if len(f.vertices) > 4]
    if ngon_faces:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        ngon_bm_faces = [f for f in bm.faces if len(f.verts) > 4]
        bmesh.ops.triangulate(bm, faces=ngon_bm_faces,
                               quad_method='BEAUTY', ngon_method='BEAUTY')
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        print(f"[dump_avatar_mesh] {obj.name}: triangulating {len(ngon_faces)} n-gon face(s)")
    try:
        mesh.calc_tangents(uvmap=uvmap_name)
    except Exception as e:
        eo.to_mesh_clear()
        raise RuntimeError(f"{obj.name}: calc_tangents failed: {e}")

    mesh.calc_loop_triangles()
    uv_layer = mesh.uv_layers[0].data
    mw = eo.matrix_world
    rot = mw.to_3x3().normalized()

    obj_tri_count = 0
    # dev#153: 非有限値は「最初の1個で即raise」せず、このオブジェクトを
    # 走査し切ってから分布ごと報告する(下記のdiagnose呼び出し)。
    # bad_pos: {vertex_index: (x, y, z)}、bad_attrs: [(kind, loop, vi, value), ...]
    bad_pos = {}
    bad_attrs = []
    for lt in mesh.loop_triangles:
        tri_idx = []
        skip = False
        for li in lt.loops:
            loop = mesh.loops[li]
            vi = loop.vertex_index
            w = weights_by_vertex[vi]
            if w is None:
                skip = True
                break
            pos = (mw @ mesh.vertices[vi].co) * 0.01  # cm相当の生値 -> encode_position前提のm単位へ補正
            # dev#193 fail-fast: W5S4T8HL事案(SK注入58件が個別にバラバラの
            # 「position頂点N位置が範囲外」で終盤失敗)の恒久対策。Blenderの
            # アーマチュアデフォーム評価がNaN/Infを生んだ場合、書き込み側
            # (build_avatar_variant.py/vp_meshrestore.encode_position、
            # いずれも純粋な数値変換でNaNを生成しない)まで素通りさせず、
            # 生成元のメッシュオブジェクト・頂点インデックス・最大寄与ボーン名を
            # 名指しして工程の頭で1回だけ止める。根本原因(スケール0ボーン仮説)
            # は別issueで追う——ここは検出のみ(Layers-Affected: none)。
            if not _finite3(pos):
                # NaN位置をデデュープ辞書のキーへ入れると、NaN != NaN のため
                # 頂点が1つも併合されず(壊れたオブジェクトの頂点数ぶんだけ
                # 辞書が膨らむ)診断の前にメモリを食う。記録だけしてこの
                # 三角形は捨て、走査完了後にまとめて報告する。
                bad_pos.setdefault(vi, (pos.x, pos.y, pos.z))
                skip = True
                continue
            uv = uv_layer[li].uv
            n = (rot @ loop.normal).normalized()
            t = (rot @ loop.tangent).normalized()
            bsign = loop.bitangent_sign
            # dev#153: 法線/タンジェント/UV/従法線符号にも下流に検査が無い。
            # 特にUVは`vp_meshrestore.encode_uv0()`がNaNを黙ってhalf floatへ
            # 書き込むため、「変換成功なのに絵が壊れている」形で出荷される。
            if not (_finite3(n) and _finite3(t) and math.isfinite(uv.x)
                    and math.isfinite(uv.y) and math.isfinite(bsign)):
                for kind, val in (("normal", (n.x, n.y, n.z)),
                                  ("tangent", (t.x, t.y, t.z)),
                                  ("uv", (uv.x, uv.y)),
                                  ("bitangent_sign", (bsign,))):
                    if not all(math.isfinite(c) for c in val):
                        bad_attrs.append((kind, li, vi, val))
                skip = True
                continue
            # WP-7781(dev#77案A、根本原因の構造的除去): キーからtangent/
            # bitangent_signを除外する。tangentはBlenderのmikktspace
            # (mesh.calc_tangents())が内部タスクスケジューラ(BLI_task)の
            # 非決定的な並列評価順序により実行のたびに1e-6オーダーで揺れる値で、
            # これをデデュープキーに含めると丸め境界をたまたま跨いだときに
            # 「別頂点として分離」or「既存頂点へ併合」の判定自体が実行ごとに
            # 変わってしまう(dev#77根本原因、work\\rd_77\\PROPOSAL.md)。
            # tangentはposition+UV+normalから一意に定まる導出量なので、
            # 併合判定はこの3属性(+obj.name/vi)だけで行う。
            key = (obj.name, vi,
                   round(pos.x, ROUND), round(pos.y, ROUND), round(pos.z, ROUND),
                   round(uv.x, ROUND), round(uv.y, ROUND),
                   round(n.x, ROUND), round(n.y, ROUND), round(n.z, ROUND))
            gi = vert_key_to_index.get(key)
            if gi is None:
                gi = len(vertices)
                vert_key_to_index[key] = gi
                vertices.append({
                    "pos": [round(pos.x, ROUND), round(pos.y, ROUND), round(pos.z, ROUND)],
                    "normal": [round(n.x, ROUND), round(n.y, ROUND), round(n.z, ROUND)],
                    "tangent": None,        # 集約後(全obj処理終了後)に確定値を書き込む
                    "bitangent_sign": None,
                    "uv": [round(uv.x, ROUND), round(uv.y, ROUND)],
                    "weights": w,
                    # 集約用の一時バッファ(出力JSONには残さない、後段でpop()する)。
                    # liはこのメッシュのループ配列内位置で、Blenderの評価順序に
                    # 依存しない安定した整数キー。
                    "_tangent_contribs": [],
                })
            vertices[gi]["_tangent_contribs"].append((li, t.x, t.y, t.z, bsign))
            tri_idx.append(gi)
        eo_break = False
        if skip:
            continue
        if tri_idx[0] == tri_idx[1] or tri_idx[1] == tri_idx[2] or tri_idx[0] == tri_idx[2]:
            continue  # 縮退三角形は捨てる(位置・法線・UV全一致の完全重複ループのみ発生しうる)
        poly = mesh.polygons[lt.polygon_index]
        slot_name = obj_slot_names[poly.material_index] if poly.material_index < len(obj_slot_names) else None
        material = slot_material_class[slot_name] if slot_name is not None else 0
        tri_idx.append(material)
        triangles.append(tri_idx)
        total_material_tri_counts[material] += 1
        obj_tri_count += 1

    # dev#153: このオブジェクトの走査が終わった時点で非有限値が1つでも
    # あれば、分布・段階・寄与ボーンをまとめた1本のエラーで停止する
    # (to_mesh_clear()より先に診断する。mesh/評価済みデータがまだ生きている
    # 必要があるため)。
    if bad_pos or bad_attrs:
        msg = _diagnose_non_finite(obj, mesh, mw, weights_by_vertex,
                                   bad_pos, bad_attrs)
        eo.to_mesh_clear()
        raise RuntimeError(msg)

    total_src_tris += obj_tri_count
    eo.to_mesh_clear()
    print(f"[dump_avatar_mesh] {obj.name}: src_verts={len(obj.data.vertices)} "
          f"tris={obj_tri_count} (running total split_verts={len(vertices)})")

# WP-7781(dev#77案A、4/5ステップ): 全オブジェクト処理後、頂点ごとに集めた
# tangent寄与(_tangent_contribs)を、ループindex(li)昇順という決定論的な
# 順序で単純加算・正規化し、確定値として書き込む。Blenderの評価順序が
# 実行ごとに変わっても、この集約自体は入力データだけで決まるため常に
# 同じ結果になる(=dev#77の非決定性を構造的に断つ)。
for v in vertices:
    contribs = sorted(v.pop("_tangent_contribs"), key=lambda c: c[0])
    sx = sum(c[1] for c in contribs)
    sy = sum(c[2] for c in contribs)
    sz = sum(c[3] for c in contribs)
    length = (sx * sx + sy * sy + sz * sz) ** 0.5
    if length < 1e-9:
        # 縮退(寄与ベクトルの合力がほぼゼロ)。値を寄せる補正ではなく、
        # 縮退時に一意な結果を選ぶための構造的タイブレークとして、
        # ソート後先頭の寄与をそのまま採用する。
        tx, ty, tz = contribs[0][1], contribs[0][2], contribs[0][3]
    else:
        tx, ty, tz = sx / length, sy / length, sz / length
    bsum = sum(c[4] for c in contribs)
    bsign = 1.0 if bsum >= 0 else -1.0
    v["tangent"] = [round(tx, ROUND), round(ty, ROUND), round(tz, ROUND)]
    v["bitangent_sign"] = round(bsign, 2)
    assert "_tangent_contribs" not in v, "一時集約キーがvertexへ残存している(出力汚染)"

out = {
    "format": 2,
    "gender": gender,
    "source_blend": blend_path,
    "max_influences": max_influences,
    "num_vertices": len(vertices),
    "num_triangles": len(triangles),
    "material_slot_map": slot_material_class,
    "material_triangle_counts": {str(k): v for k, v in total_material_tri_counts.items()},
    "vertices": vertices,
    "triangles": triangles,
}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f)

print(f"[dump_avatar_mesh] DONE src_objects={len(mesh_objs)} src_total_verts={total_src_verts} "
      f"split_vertices={len(vertices)} triangles={len(triangles)} "
      f"material_triangle_counts={total_material_tri_counts} -> {out_path}")
