# -*- coding: utf-8 -*-
"""U16: Blender headless — マテリアルアトラスUV焼き込み。

指定した step02_{gender}.blend を開き、avatar_meta.jsonのスロットID
(=Blenderマテリアル名。convert_noue.py/resolve_textures()のdocstring、
および research\\ue_exit\\dump_avatar_mesh.py の運用実態のとおり、
Blender側マテリアル名は"m00","m01",...のスロットIDそのもの)ごとに
与えられたアフィン変換 (su,sv,ou,ov: u'=u*su+ou, v'=v*sv+ov) を
そのマテリアルが使う面のUVループへ適用し、新しいblendとして保存する。

対象スロットは適用前に、まず**面(ポリゴン)単位のタイル正規化**を行う
(2026-07-25追加。UVアイランドを隣のタイル v∈[-1,0] 等へ置いたままの
メッシュを、面ごとの整数シフトで [0,1] のタイルへ戻す。WRAPアドレッシングと
厳密に等価なので見た目は変わらない。詳細は `vp_atlas.py` の
「UVのタイル正規化」節)。

2026-07-29改訂(dev#18 主要ケース修理、診断確定: work\\wp_comodo\\
fix_experiment_clamp.py で実証済み): 正規化後もなお `[0,1]` をはみ出す面の
扱いを、**スロット単位の丸ごと除外から次の3分類へ**変更した。

  1. 面が完全にセル内(はみ出し <= `vp_atlas.UV_IN_RANGE_TOL`)
     → 従来どおりそのまま変換
  2. 面がセル境界をわずかに跨ぐ(`UV_IN_RANGE_TOL` < はみ出し
     <= `vp_atlas.UV_CELL_CLAMP_TOL`)
     → **面単位**で、跨いだ頂点をセル境界へクランプ(`vp_atlas.clamp01`)
       してから変換を継続する。クランプは面のUVスパンを縮めるだけで面は
       裂けない(実測: comodo m04(epron) 3頂点クランプでプレビューと完全
       一致)。同一スロット内の他のUVアイランド(セル内に完結する面)の
       UVはこの処置で一切動かない(境界を跨いだ面の、境界外にある頂点
       だけを動かす。スロット全体へのスケール/オフセット変換は行わない)
  3. 面が実質1タイル以上に広がる(はみ出し > `UV_CELL_CLAMP_TOL`。真の
     タイリング面。レース・網目模様等)
     → 2026-07-29 オーナー裁定により、**個別除外ではなく**その面を含む
       **UV島(連結成分)全体を等倍(アスペクト保持)で縮小してセルに
       フィット**させ、通常の再マップに乗せる(Pass 2内のケース3経路)。
       繰り返し柄が「1周期の拡大表示」になる近似であり、正確な表示では
       ない。**面ごとに別々に縮小すると島内で裂ける**ため、必ず連結UV島
       単位で同一のスケール・アンカーを使う。
       島の同定に失敗した(=どの島にも割り当てられなかった)面だけが、
       最後の砦として個別除外(元のUVのまま)される。通常は発生しない。

       **記録と警報の分離(2026-07-29指揮者裁定)**: 縮小フィットの処置内容
       (島ごとのスケール・歪み量`distortion=1-scale`)は`report.json`へ
       **常に**記録するが、エンドユーザー向け`##AVATAR_WARNING##`が発火する
       のは`distortion > UV_CELL_CLAMP_TOL`のときだけ(=実害があるときだけ)。
       この判定は**新しい定数を作らず**、既存の`UV_CELL_CLAMP_TOL`
       (「この程度のUV変位はクランプで丸めてよい=視覚上無害」という
       既存の意味)を縮小フィットの歪み量にもそのまま適用しているだけで、
       閾値の緩和ではなく既存許容度の一貫適用である(comodo実測:
       scale=0.999999970 → distortion=2.98e-8 ≪ 0.02 → 無害なので警告なし。
       一方、真のタイリング(scale≒1/3)は distortion≒0.67 ≫ 0.02 で警告あり)。

       **暫定実装であることの明記**: このUV島同定(`find_uv_islands()`)は
       メッシュ頂点index+UV値の一致を連結条件とする簡易 union-find で、
       bmeshのエッジ厳密比較ではない(通常のUVアンラップでは同一頂点で
       UV値が一致していれば同じ島とみなして問題ない)。等倍縮小フィットも
       「見た目の近似」であり正確なベイクではない。将来、本命のUVベイク
       実装に置き換わる前提の仮実装(#18)。

旧実装(2026-07-26追加、その後2026-07-29に上記へ置き換え)は上記の判定を
**スロット全体**の正規化後バウンディングボックスに対して行っていたため、
スロット中のごく一部の面が境界を跨いだだけで**スロット全面**がアトラス
対象から除外され、無関係な大部分の面まで巻き添えで見た目が壊れる不具合が
あった(dev#18、comodoのエプロンがアトラス画像そのものを表示してしまう
症状の真因)。

閾値定数(`UV_IN_RANGE_TOL` / `UV_CELL_CLAMP_TOL`)そのものは一切変更していない
(値を寄せる修正は却下する方針のため)。変わったのは適用粒度と、はみ出しが
大きい場合の処置(除外→縮小フィット)。

`##AVATAR_WARNING##`(呼び出し元 convert_noue.apply_atlas_uv_bake が出す
GUI向け警告)は、report.jsonの`excluded_reason`キーで引き続きトリガーする。
このキーが立つのは、**最後の砦の個別除外**が1件でもあるか、**縮小フィットの
歪み量が`UV_CELL_CLAMP_TOL`を超える島**が1件でもある場合のみ(上記「記録と
警報の分離」参照)。convert_noue.py側の文言更新は別タスク。

元のblend(呼び出し元の step02_female.blend / step02_male.blend)は
一切変更しない(=新しいファイルパスへ`bpy.ops.wm.save_as_mainfile`で
別名保存する。convert.ps1が共用するBlender工程の成果物を汚染しない
ための設計)。

実行:
  <blender.exe> --background --factory-startup --python-exit-code 1 --python \\
      vp_atlas_uvbake.py -- <blend_in> <blend_out> <transform.json> <report.json>

transform.json (入力): {"m00": [su,sv,ou,ov], ...} (アトラス対象スロットのみ。
  convert_noue.py が vp_atlas.slot_transforms(plan) の出力をそのままdumpする)

report.json (出力): {"m00": {"bbox":[umin,umax,vmin,vmax]|null,
  "bbox_normalized":[...], "wrap_shifted_faces":int,
  "n_faces":int, "n_faces_normal":int, "n_faces_clamped":int,
  "n_faces_island_fit":int, "n_islands_fit":int, "n_faces_excluded":int,
  "overshoot_after_shift":float, "cell_clamped":bool, "island_fit":bool,
  "tiling":bool, "applied":bool, "excluded_reason":str(縮小フィット/除外が
  ある場合のみ), "note":str(省略可)}, ...}
"""
import json
import os
import sys
from collections import defaultdict

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import vp_atlas  # noqa: E402

TAG = "vp_atlas_uvbake"

argv = sys.argv[sys.argv.index("--") + 1:]
if len(argv) < 4:
    raise RuntimeError(
        "使い方: blender --background --factory-startup --python-exit-code 1 --python "
        "vp_atlas_uvbake.py -- <blend_in> <blend_out> <transform.json> <report.json>")
blend_in, blend_out, transform_json, report_json = argv[0], argv[1], argv[2], argv[3]

with open(transform_json, encoding="utf-8") as f:
    transform_map = json.load(f)  # {slot: [su,sv,ou,ov]}

bpy.ops.wm.open_mainfile(filepath=blend_in)

mesh_objs = [o for o in bpy.data.objects if o.type == "MESH"]
if not mesh_objs:
    raise RuntimeError(f"MESHオブジェクトが見つからない: {blend_in}")


# find_uv_islands()はvp_atlas.py(bpy非依存の純粋モジュール)へ移設した
# (2026-07-29、work\wp_18fix\verify_case1_invariant.py 等の検証スクリプトが
# 本番と同一ロジックでUV島同定を再計算できるようにするため)。


# --- Pass 1: スロットごとに**面(ポリゴン)単位で**UVループを収集し、
#     生のバウンディングボックスを取る ---
# (面単位にするのは Pass 1.5 のタイル正規化と、Pass 2 の面/島単位の
#  クランプ/縮小フィット判定のため)
slot_faces = {}     # slot_name -> [(obj_name, poly_index, [loop_index, ...]), ...]
slot_bbox = {}      # slot_name -> [umin,umax,vmin,vmax] (シフト前)
uv_by_obj = {}      # obj_name -> uv_layers[0].data (書き戻し用)
mesh_by_obj = {}    # obj_name -> obj.data (Pass 1.6 のUV島同定用)
n_no_uv = 0

for obj in mesh_objs:
    if not obj.data.uv_layers:
        n_no_uv += 1
        continue
    uv_data = obj.data.uv_layers[0].data
    uv_by_obj[obj.name] = uv_data
    mesh_by_obj[obj.name] = obj.data
    obj_slot_names = [ms.material.name if ms.material else None
                       for ms in obj.material_slots]
    for poly in obj.data.polygons:
        idx = poly.material_index
        slot_name = obj_slot_names[idx] if idx < len(obj_slot_names) else None
        if slot_name is None or slot_name not in transform_map:
            continue
        lis = list(poly.loop_indices)
        slot_faces.setdefault(slot_name, []).append((obj.name, poly.index, lis))
        for li in lis:
            uv = uv_data[li].uv
            u, v = float(uv[0]), float(uv[1])
            bbox = slot_bbox.get(slot_name)
            if bbox is None:
                slot_bbox[slot_name] = [u, u, v, v]
            else:
                if u < bbox[0]:
                    bbox[0] = u
                if u > bbox[1]:
                    bbox[1] = u
                if v < bbox[2]:
                    bbox[2] = v
                if v > bbox[3]:
                    bbox[3] = v

# --- Pass 1.5(2026-07-25、alicia が FATAL で止まっていた真因の修正):
#     **面単位のタイル正規化**。UVアイランドを隣のタイル(v∈[-1,0] 等)へ
#     置いたままのメッシュを、面ごとの整数シフトで [0,1] のタイルへ戻す。
#     WRAP アドレッシングと厳密に等価なので見た目は変わらない。
#     詳しい理由は vp_atlas.py の「UVのタイル正規化」節を読むこと。
#     ここではまだUVを書き換えない(書き換えは Pass 2 でまとめて行う)。
#     シフト後の面ごとのbbox(lo_u,hi_u,lo_v,hi_v)も、Pass 2 の面単位の
#     はみ出し判定のためにここで一緒に持っておく。
slot_shift = {}       # slot_name -> [(obj_name, poly_index, [li,...], ku, kv,
                       #                lo_u, hi_u, lo_v, hi_v), ...]
slot_norm_bbox = {}   # slot_name -> [umin,umax,vmin,vmax] (シフト後、診断用)
slot_n_shifted = {}   # slot_name -> シフトした面数
for slot_name, faces in slot_faces.items():
    shifted = []
    n_shifted = 0
    nb = None
    for obj_name, pi, lis in faces:
        uv_data = uv_by_obj[obj_name]
        ulo = vlo = 1e9
        uhi = vhi = -1e9
        for li in lis:
            uv = uv_data[li].uv
            u, v = float(uv[0]), float(uv[1])
            if u < ulo:
                ulo = u
            if u > uhi:
                uhi = u
            if v < vlo:
                vlo = v
            if v > vhi:
                vhi = v
        ku = vp_atlas.face_wrap_shift(ulo, uhi)
        kv = vp_atlas.face_wrap_shift(vlo, vhi)
        if ku or kv:
            n_shifted += 1
        lo_u, hi_u, lo_v, hi_v = ulo + ku, uhi + ku, vlo + kv, vhi + kv
        shifted.append((obj_name, pi, lis, ku, kv, lo_u, hi_u, lo_v, hi_v))
        if nb is None:
            nb = [lo_u, hi_u, lo_v, hi_v]
        else:
            if lo_u < nb[0]:
                nb[0] = lo_u
            if hi_u > nb[1]:
                nb[1] = hi_u
            if lo_v < nb[2]:
                nb[2] = lo_v
            if hi_v > nb[3]:
                nb[3] = hi_v
    slot_shift[slot_name] = shifted
    slot_norm_bbox[slot_name] = nb
    slot_n_shifted[slot_name] = n_shifted

# --- Pass 1.6(2026-07-29追加、dev#18): スロットごとにUV島(連結成分)を
#     同定しておく。ケース2(縮小フィット)を「面ごとに別々に」適用すると
#     島の内部で裂けるため、その面を含む島全体へ同一のスケール・アンカーを
#     適用する必要がある。ここでは検出のみ行い、書き換えは Pass 2 で行う。
slot_islands = {}   # slot_name -> [{"obj_name":str, "polys":[poly_index,...]}, ...]
for slot_name, faces in slot_faces.items():
    by_obj = defaultdict(list)
    for obj_name, pi, _lis in faces:
        by_obj[obj_name].append(pi)
    islands = []
    for obj_name, polys in by_obj.items():
        mesh = mesh_by_obj[obj_name]
        uv_data = uv_by_obj[obj_name]
        for comp in vp_atlas.find_uv_islands(mesh, uv_data, polys):
            islands.append({"obj_name": obj_name, "polys": comp})
    slot_islands[slot_name] = islands

# --- Pass 2(2026-07-29書き直し、dev#18): モジュールdocstring冒頭の3分類を
#     適用する。ケース1/2(面単位: そのまま/クランプ)と、ケース3
#     (UV島単位: 縮小フィット)を分けて処理する。
report = {}
n_applied = 0                 # 変換された面が1つでもあったスロット数
n_wrap_normalized = 0         # ラップシフトが1面でも発生したスロット数
n_clamped = 0                  # クランプされた面が1つでもあったスロット数
n_island_fit_slots = 0         # 縮小フィットが1島でもあったスロット数
n_overshoot_excluded = 0       # 最後の砦の個別除外が1面でもあったスロット数
n_faces_island_fit_total = 0   # 縮小フィットされた面の総数(全スロット合算)
n_faces_excluded_total = 0     # 最後の砦で除外された面の総数(全スロット合算)
# Pass 3 で使う「実際に変換された面の頂点ループ」だけを集めたもの。
# 除外面(元のUVのまま)を含めてしまうと、セル包含チェックが常にNGになる
# (除外面のUVはアトラスセルの外にあって当然のため)。
slot_transformed_loops = {}   # slot_name -> [(obj_name, loop_index), ...]

for slot_name, xf in transform_map.items():
    bbox = slot_bbox.get(slot_name)
    if bbox is None:
        report[slot_name] = {"bbox": None, "tiling": False, "applied": False,
                              "note": "このblendに対応する面が見つからなかった"}
        continue
    nbox = slot_norm_bbox[slot_name]
    n_shifted = slot_n_shifted[slot_name]
    # U50-single修正(2026-07-25): xf は「アトラス画像の座標系(v下向き=UEのUV)」
    # で作られている。BlenderのUVは v上向きなので、そのまま適用すると行(v)方向
    # だけ上下逆のセルを指す(rows=1のときだけ恒等写像になるため今まで露見
    # しなかった)。詳細は vp_atlas.to_blender_transform() のdocstring。
    bxf = vp_atlas.to_blender_transform(xf)

    faces = slot_shift[slot_name]
    n_faces = len(faces)
    face_by_key = {(obj_name, pi): (lis, ku, kv, lo_u, hi_u, lo_v, hi_v)
                   for obj_name, pi, lis, ku, kv, lo_u, hi_u, lo_v, hi_v in faces}

    # 1) 各面を単独で見て、シフト後もなお上限を超えてはみ出す面を洗い出す
    #    (=ケース3候補。この面を含む島は丸ごとケース3扱いにする)
    flagged = {key for key, (lis, ku, kv, lo_u, hi_u, lo_v, hi_v) in face_by_key.items()
               if vp_atlas.bbox_overshoot([lo_u, hi_u, lo_v, hi_v]) > vp_atlas.UV_CELL_CLAMP_TOL}

    # 2) フラグが1面でも立ったUV島を丸ごとケース3(縮小フィット)へ回す
    islands = slot_islands.get(slot_name, [])
    case3_islands = []
    normal_keys = set()
    case3_keys = set()
    for isl in islands:
        keys = {(isl["obj_name"], pi) for pi in isl["polys"]}
        if keys & flagged:
            case3_islands.append(isl)
            case3_keys |= keys
        else:
            normal_keys |= keys

    n_normal = 0
    n_face_clamped = 0
    n_faces_island_fit = 0
    n_face_excluded = 0
    max_excluded_overshoot = 0.0
    island_fit_details = []
    trans_loops = []

    # --- ケース1/2経路: 面単位、そのまま変換 or クランプして変換 ---
    for key in normal_keys:
        obj_name, pi = key
        lis, ku, kv, lo_u, hi_u, lo_v, hi_v = face_by_key[key]
        overshoot = vp_atlas.bbox_overshoot([lo_u, hi_u, lo_v, hi_v])
        do_clamp = vp_atlas.UV_IN_RANGE_TOL < overshoot <= vp_atlas.UV_CELL_CLAMP_TOL
        uv_data = uv_by_obj[obj_name]
        for li in lis:
            u, v = uv_data[li].uv
            u = float(u) + ku
            v = float(v) + kv
            if do_clamp:
                u = vp_atlas.clamp01(u)
                v = vp_atlas.clamp01(v)
            nu, nv = vp_atlas.apply_transform(u, v, bxf)
            uv_data[li].uv = (nu, nv)
            trans_loops.append((obj_name, li))
        if do_clamp:
            n_face_clamped += 1
        else:
            n_normal += 1

    # --- ケース3経路: UV島単位の等倍縮小フィット(2026-07-29 オーナー裁定) ---
    for isl in case3_islands:
        obj_name = isl["obj_name"]
        mesh = mesh_by_obj[obj_name]
        uv_data = uv_by_obj[obj_name]
        polys = isl["polys"]
        loops_all = []
        umin = vmin = 1e9
        umax = vmax = -1e9
        for pi in polys:
            poly = mesh.polygons[pi]
            for li in poly.loop_indices:
                u, v = uv_data[li].uv
                u = float(u); v = float(v)
                loops_all.append((li, u, v))
                if u < umin:
                    umin = u
                if u > umax:
                    umax = u
                if v < vmin:
                    vmin = v
                if v > vmax:
                    vmax = v
        span_u = umax - umin
        span_v = vmax - vmin
        # アンカー=島bboxの最小隅、スケール=両軸とも同一(アスペクト保持)。
        # 1.0未満に伸ばすことはしない(既にセル内に収まる島を誤って
        # 拡大しないため。max(...,1.0)がその安全弁)。
        scale = 1.0 / max(span_u, span_v, 1.0)
        for li, u, v in loops_all:
            new_u = (u - umin) * scale
            new_v = (v - vmin) * scale
            nu, nv = vp_atlas.apply_transform(new_u, new_v, bxf)
            uv_data[li].uv = (nu, nv)
            trans_loops.append((obj_name, li))
        n_faces_island_fit += len(polys)
        island_fit_details.append({
            "obj_name": obj_name, "n_faces": len(polys),
            "raw_bbox": [round(umin, 6), round(umax, 6), round(vmin, 6), round(vmax, 6)],
            "scale": scale, "distortion": 1.0 - scale})

    # --- 最後の砦: 島の同定に失敗した等で normal/case3 どちらにも
    #     割り当てられなかった面(通常発生しない)。元のUVのまま個別除外する。
    leftover_keys = set(face_by_key) - normal_keys - case3_keys
    for key in leftover_keys:
        lis, ku, kv, lo_u, hi_u, lo_v, hi_v = face_by_key[key]
        overshoot = vp_atlas.bbox_overshoot([lo_u, hi_u, lo_v, hi_v])
        n_face_excluded += 1
        if overshoot > max_excluded_overshoot:
            max_excluded_overshoot = overshoot

    slot_transformed_loops[slot_name] = trans_loops
    applied = (n_normal + n_face_clamped + n_faces_island_fit) > 0
    if applied:
        n_applied += 1
    n_faces_island_fit_total += n_faces_island_fit
    n_faces_excluded_total += n_face_excluded

    if n_shifted:
        n_wrap_normalized += 1
        print(f"[{TAG}] {slot_name}: {n_shifted}面のUVを隣のタイルから [0,1] へ"
              f"戻した(WRAP等価の整数シフト) 生bbox={[round(x, 6) for x in bbox]}"
              f" -> 正規化後={[round(x, 6) for x in nbox]}")
    if n_face_clamped:
        n_clamped += 1
        print(f"[{TAG}] {slot_name}: {n_face_clamped}/{n_faces}面のセル境界への"
              f"わずかなはみ出しをクランプして救済した(上限 "
              f"{vp_atlas.UV_CELL_CLAMP_TOL})")
    # 2026-07-29追加(指揮者裁定): 記録(report.json)と警報(##AVATAR_WARNING##)を
    # 分離する。ケース3(縮小フィット)は常に report.json へ処置内容を残すが、
    # ユーザー向け警告を出すのは**実害がある場合のみ**とする。
    # 「実害がある」の判定基準は**新しい値を作らず**、既存定数
    # `UV_CELL_CLAMP_TOL`(=0.02、「クランプで無害に丸めてよい変位の上限」)を
    # 縮小フィットの歪み量`(1 - scale)`にもそのまま適用する。この定数の意味は
    # 元々「この程度のUV変位は視覚上無害」であり、クランプ由来かスケール由来かを
    # 問わず同じ意味で使えるため、閾値の緩和ではなく**既存許容度の一貫適用**
    # である(comodo実測: scale=0.999999970 -> 歪み量2.98e-8 ≪ 0.02 -> 無害
    # なので警告なし。負の対照Aの真タイリング面は scale≒1/3 -> 歪み量≒0.67
    # ≫ 0.02 で警告あり、という想定どおりの両側の分かれ方になる)。
    significant_islands = [d for d in island_fit_details
                            if d["distortion"] > vp_atlas.UV_CELL_CLAMP_TOL]
    warn_needed = bool(significant_islands) or n_face_excluded > 0

    if case3_islands:
        n_island_fit_slots += 1
        level = "WARN" if significant_islands else "INFO"
        print(f"[{TAG}][{level}] {slot_name}: {len(case3_islands)}個のUV島"
              f"({n_faces_island_fit}/{n_faces}面)が本物のタイリング"
              "(セルを大きく超えるUVアイランド)のため、等倍縮小フィットで"
              "近似表示した(柄の縮尺が変わる。正確な表示は今後対応) "
              f"詳細={island_fit_details}"
              + ("" if significant_islands else
                 " (歪み量が上限以下のため実害なしと判定、警告は出さない)"))
    if n_face_excluded:
        n_overshoot_excluded += 1
        print(f"[{TAG}][WARN] {slot_name}: {n_face_excluded}/{n_faces}面はUV島の"
              "同定に失敗したため個別除外した(元のUVのまま。見た目崩れの"
              "可能性あり。最大overshoot="
              f"{max_excluded_overshoot:.6f})")

    r = {"bbox": bbox, "bbox_normalized": nbox,
         "wrap_shifted_faces": n_shifted,
         "n_faces": n_faces,
         "n_faces_normal": n_normal,
         "n_faces_clamped": n_face_clamped,
         "n_faces_island_fit": n_faces_island_fit,
         "n_islands_fit": len(case3_islands),
         "n_faces_excluded": n_face_excluded,
         "cell_clamped": n_face_clamped > 0,
         "island_fit": len(case3_islands) > 0,
         "tiling": False,
         "applied": applied,
         "blender_transform": list(bxf)}
    # island_fit_details(ケース3の処置内訳: スロット・面数・raw_bbox・
    # scale・distortion)は、警告の要否に関わらず**常に**記録する
    # (観測可能性を落とさない。指揮者裁定「記録は常時」)。
    if island_fit_details:
        r["island_fit_details"] = island_fit_details
    if warn_needed:
        # convert_noue.apply_atlas_uv_bake との互換維持(excluded_reason==
        # "overshoot" をトリガーに ##AVATAR_WARNING## を出す既存経路を流用)。
        # ケース3は「除外」ではなく「近似表示」だが、ユーザー向け警告を出す
        # 経路がこれしか無いため、当面はこのキーを流用する
        # (convert_noue.py側の文言更新は別タスク)。
        overshoots = [max_excluded_overshoot]
        overshoots.extend(d["distortion"] for d in significant_islands)
        r["overshoot_after_shift"] = max(overshoots)
        r["excluded_reason"] = "overshoot"
        notes = []
        if significant_islands:
            notes.append(
                f"{len(significant_islands)}個のUV島"
                f"({sum(d['n_faces'] for d in significant_islands)}面)を"
                "等倍縮小フィットで近似表示した(柄の縮尺が変わります。"
                "正確な表示は今後対応)")
        if n_face_excluded:
            notes.append(f"{n_face_excluded}面はUV島の同定に失敗し個別除外した"
                          "(元のUVのまま。見た目崩れの可能性あり)")
        r["note"] = "; ".join(notes)
    else:
        r["overshoot_after_shift"] = vp_atlas.bbox_overshoot(nbox) if nbox else 0.0
    report[slot_name] = r

# --- Pass 3(U50-single、受入ゲート): 焼き込み後のUVが「意図したセルの中」に
# 収まっているかを**UE座標系(v下向き)に直して**機械確認する。
# 実機NG(2026-07-25、行方向のセル取り違え)は、この検査があれば
# Blender工程だけで捕まえられた。ズレていたら report に out_of_cell=True を
# 立て、呼び出し元(convert_noue.apply_atlas_uv_bake)がビルドを止める。
# 2026-07-29: 面/島単位除外・縮小フィットの導入により、チェック対象は
# **実際に変換されたループのみ**(slot_transformed_loops)。除外面(元のUVの
# まま)まで含めると、除外面のUVはアトラスセルの外にあって当然なので常に
# NGになってしまう。
EPS = 1e-3
for slot_name, xf in transform_map.items():
    r = report.get(slot_name)
    if not r or not r.get("applied"):
        continue
    su, sv, ou, ov = xf
    umin = vmin = 1e9
    umax = vmax = -1e9
    for obj_name, li in slot_transformed_loops[slot_name]:
        u, v_b = uv_by_obj[obj_name][li].uv
        v_ue = 1.0 - float(v_b)          # encode_uv0 と同じ変換
        u = float(u)
        umin = min(umin, u); umax = max(umax, u)
        vmin = min(vmin, v_ue); vmax = max(vmax, v_ue)
    inside = (umin >= ou - EPS and umax <= ou + su + EPS
              and vmin >= ov - EPS and vmax <= ov + sv + EPS)
    r["bbox_after_ue"] = [umin, umax, vmin, vmax]
    r["cell_ue"] = [ou, ou + su, ov, ov + sv]
    r["out_of_cell"] = not inside
    if not inside:
        print(f"[{TAG}][ERROR] {slot_name}: 焼き込み後のUVが意図したセルの外 "
              f"UE空間bbox=u[{umin:.4f},{umax:.4f}] v[{vmin:.4f},{vmax:.4f}] "
              f"期待セル=u[{ou:.4f},{ou + su:.4f}] v[{ov:.4f},{ov + sv:.4f}]")

os.makedirs(os.path.dirname(os.path.abspath(blend_out)) or ".", exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=blend_out)

with open(report_json, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

print(f"[{TAG}] applied={n_applied} overshoot_excluded_slots={n_overshoot_excluded} "
      f"excluded_faces_total={n_faces_excluded_total} "
      f"island_fit_slots={n_island_fit_slots} "
      f"island_fit_faces_total={n_faces_island_fit_total} "
      f"wrap_normalized={n_wrap_normalized} cell_clamped_slots={n_clamped} "
      f"total_transform_slots={len(transform_map)} objects_without_uv={n_no_uv} "
      f"-> {blend_out}")
