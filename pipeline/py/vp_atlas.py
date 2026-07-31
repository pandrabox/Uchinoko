# -*- coding: utf-8 -*-
"""U16: マテリアルアトラス化(固定2スロット body=t00/parka=t01 のまま、
3枚以上マテリアルを持つアバターの見た目崩れに対処する)。

背景(docs\\TODO.md「マテリアル数の多いアバターの見た目崩れ対策」参照):
既存アーキテクチャはUEのSK側テクスチャスロットが2枚(body/parka)固定。
`pipeline\\py\\convert_noue.py`の(旧)`resolve_textures`は各ラベルにつき
「代表スロット1枚」のPNGだけを選んで注入していたため、3枚以上マテリアルを
持つアバター(alicia=12マテリアル等)は対応しない部位が誤ったテクスチャで
描画され見た目が崩れていた(個別バグではなくアーキテクチャ上の制約)。

戦略(2026-07-23深夜ぱん確定): マテリアル数を可変にする方向(UEスロット数を
増やす)は不採用。**アトラス化**を採用: 固定2スロットのまま、ラベル
(body/parka)内の distinct テクスチャファイルをグリッド分割で1枚のキャンバスへ
敷き詰め、該当スロットのUV座標を対応するマス目へスケール+オフセット変換する。
タイリングUV(0〜1を大きく超える。レース・網目模様等)は検出のみ行い、
検出したスロットはアトラス化対象から外して見た目崩れを許容する(YAGNI、
焼き込み修復はしない)。

本モジュールは純粋なnumpy/標準ライブラリのみに依存する(Blender同梱Python・
システムPython両方で動く。`pipeline\\py\\vp_atlas_uvbake.py`がBlender
headlessから本モジュールをimportしてタイリング判定に使う)。

## マテリアル分類(classify_material)について — 重要な同期要件

`research\\ue_exit\\dump_avatar_mesh.py`の`classify_material()`と**完全に
同一ロジック**を意図的に複製している(そちらはBlenderスクリプトで
`bpy`に依存するため通常のpythonからimportできない。本ファイルは
book-keeping専用の純粋移植)。dump_avatar_mesh.pyはSKメッシュの三角形を
body(0)/parka(1)の2セクションへ分類する際にこの関数を使う。
本モジュール(convert_noue.py経由でテクスチャアトラスのラベル分類に使う)が
**同じ分類結果を出さない**と、あるスロットの三角形がSKのbodyセクションに
入っているのにテクスチャはparkaアトラス(またはその逆)に焼かれる、という
致命的な不整合が起きる。dump_avatar_mesh.pyのclassify_material()を変更する
場合は必ず本関数も同時に変更すること(FIX3a 2026-07-24: "mohu"/"mofu"追加を
両ファイル同時に反映済み)。

## グリッド分割・キャンバス解像度(枠内判断、実測に基づく)

- グリッド: `compute_grid(n)`で `cols=ceil(sqrt(n))`, `rows=ceil(n/cols)`。
  bin-packingはしない(タスク指示どおりYAGNI)。alicia実測: body系distinct
  テクスチャ5枚→3x2グリッド(1マス余り)、parka系3枚→2x2グリッド
  (1マス余り)。余りマスは単に使われない(UVがそこを指す面が存在しない)。
- セルサイズ: 既定**2048px角**(U50-single で 1024 から引き上げ)。
  最終的に`vp_texinject.inject_texture_file()`がテンプレート(t00)の実解像度へ
  再度ニアレストネイバーでリサイズするため、本モジュールの出力解像度は
  中間値でしかない。**t00 を 4096 化したのに cell が 1024 のままだと、
  1024→2048 へ引き伸ばした画をさらに焼くだけで実質の画質は上がらない。**
  2048/4096 の組み合わせなら:
    distinct 2枚 → 1x2グリッド、cell 2048(元PNG等倍)
    distinct 4枚 → 2x2グリッド、cell 2048(元PNG等倍)
    distinct 9枚 → 3x3グリッド、cell 1365(従来の682の2倍)
  となり、**実測9体のどれでも従来より解像度が下がらない**
  (work\\u50_equip\\out\\atlas_census.csv)。
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import vp_tex          # noqa: E402
import vp_texinject    # noqa: E402


# ------------------------------------------------------------ マテリアル分類

# U50-single(2026-07-25、責任者裁定「入力アバターが何マテリアルでも1枚の
# アトラス・1マテリアルに畳む」): body/parka の2ラベル振り分けを廃止した。
#
# 廃止の理由(work\u50_equip\out\FINDINGS2.txt 5節の機械判定):
#   キーワードによる body/parka 判定は、SK側のスロット役(t00/t01)と
#   一致しなければ「三角形はbodyセクションなのにテクスチャはparkaアトラス」
#   という致命的な不整合になる。実測で注入対象60SK中16SKがこの不整合
#   (Bronze001/Plastic001/Kigurumi001系)を起こしていた。
#   1マテリアルへ畳めば、この不整合は**起こりようがなくなる**(実測NG 0件)。
#
# 画質は t00 資産を 4096 化して担保する(pipeline\py\devtool_make_t00_4096.py)。
SINGLE_MATERIAL = True


def classify_material(orig_name):
    """avatar_meta.jsonのslots[m??]['orig_name']から材質ラベルを返す。

    U50-single 以降は**常に0(単一マテリアル)**を返す。
    `research\\ue_exit\\dump_avatar_mesh.py`の`classify_material()`と
    完全同一の値を返す必要がある(モジュールdocstring「同期要件」参照)ため、
    あちらも同時に単一化してある。"""
    if SINGLE_MATERIAL:
        return 0
    name = (orig_name or "").lower()
    if name == "body":
        return 0
    if name == "parka":
        return 1
    for kw in ("wear", "cloth", "parka", "outfit", "costume", "overalls",
               "mohu", "mofu"):
        if kw in name:
            return 1
    return 0


LABELS = {0: "body", 1: "parka"}


# ---------------------------------------------------------------- グリッド計算

def compute_grid(n):
    """n個のセルを収める grid (rows, cols) を返す。bin-packingなしの単純な
    正方形寄りグリッド分割(タスク指示どおりYAGNI)。n<=0は呼び出し側の誤り。"""
    if n <= 0:
        raise ValueError("compute_grid: n must be >= 1")
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return rows, cols


def cell_transform(index, rows, cols):
    """グリッド中のindex番目(行優先: index = r*cols+c)のセルへ、[0,1]の
    UVを写すアフィン変換 (su, sv, ou, ov) を返す。
    使い方: u' = u*su + ou ; v' = v*sv + ov"""
    r, c = divmod(index, cols)
    su, sv = 1.0 / cols, 1.0 / rows
    ou, ov = c * su, r * sv
    return su, sv, ou, ov


def apply_transform(u, v, transform):
    """**画像座標系(v下向き = UEのUV)** で変換を適用する。"""
    su, sv, ou, ov = transform
    return u * su + ou, v * sv + ov


def to_blender_transform(transform):
    """`cell_transform()` が返す**画像座標系(v下向き)**の変換を、
    **Blenderの UV 座標系(v上向き)**で同じ結果になる変換へ書き換える。

    ■なぜ要るか(U50-single で実機NGになった原因、2026-07-25)
    `pipeline\\py\\vp_meshrestore.py: encode_uv0()` が
        V_ue = 1 - V_blender
    と**上下を反転して**cook済みメッシュへ書き出している(実測で確定済み)。
    一方 `cell_transform()` は「アトラス画像の何行目か」= v下向きの座標系で
    オフセットを作る。したがって Blender 空間のUVへそのまま適用すると、
    行(v)方向だけ**上下が逆のセル**を指してしまう。

    ■なぜ今まで露見しなかったか
    実在アバターはラベルあたりの distinct テクスチャが常に2枚以下で、
    `compute_grid(n<=2)` は必ず **rows=1** を返していた。rows=1 では
    sv=1.0 / ov=0.0 となり、v の変換が恒等写像になるため**バグが効かなかった**。
    単一アトラス化で 1ラベルに4枚入り rows=2 になった瞬間に露見した。
    (alicia のような5枚以上のアバターは以前から踏んでいたはずの潜在バグ)

    ■導出
      欲しい結果:  v_ue_final = v_ue_src * sv + ov
      パイプライン: v_ue_final = 1 - v_b_final , v_ue_src = 1 - v_b_src
      ⇒ v_b_final = v_b_src * sv + (1 - sv - ov)
    u は反転しないのでそのまま。
    """
    su, sv, ou, ov = transform
    return (su, sv, ou, 1.0 - sv - ov)


# -------------------------------------------------- UVのタイル正規化(2026-07-25)
#
# ■なぜ要るか(alicia が FATAL で止まっていた真因)
# アトラス化は「1スロットのUVが [0,1] に収まっている」ことを前提にしている。
# セル変換 u'=u*su+ou は u∈[0,1] のときだけ自分のセルに収まるからである。
# ところが実在アバターには、**UVアイランドを隣のタイル(v∈[-1,0] 等)へ
# 置いたまま**のメッシュがある。UEでもBlenderでもテクスチャのアドレッシングは
# WRAP なので、単体テクスチャで描く限り見た目は完全に正しい。しかしアトラスへ
# 詰めた瞬間、そのアイランドは**隣のセル(別のテクスチャ)を舐めてしまう**。
#
# 実測(AliciaSolid_vrm-0.51.vrm, work\\u51_matsonly):
#   m00 Alicia_body      : 2808面中 **4面**だけが v を1タイル下に置いていた
#   m01 Alicia_body_wear : 2800面中 5面
#   m02 Alicia_wear      : 14446面中 9194面
#   → m00 はセル外判定でFATAL、m01/m02 は detect_tiling に「タイリング」と
#     誤認されてアトラス対象から丸ごと外れていた(=見た目崩れ)。
#
# ■直し方(面単位の整数シフト。WRAP と厳密に等価で、情報を失わない)
# 面(ポリゴン)ごとにUVレンジを見て、[0,1] のタイルへ戻す**整数**を足す。
# 面を丸ごと平行移動するので面内の補間は一切変わらず、WRAP アドレッシングでは
# u と u±1 が同じテクセルを指すため、**アトラス化前の見た目と完全に一致する**。
# 面をまたぐ継ぎ目も、元々 WRAP で繋がっていた通りに繋がる。
#
# 「面それ自体が1タイルより広い」(レース・網目模様など本物のタイリング)は
# シフトでは救えない。その場合はシフト後もバウンディングボックスが [0,1] を
# はみ出したままなので、従来どおり `detect_tiling()` がアトラス対象から外す。

# 面のUVが「もう [0,1] に収まっている」とみなす許容差。これ以下のはみ出しは
# シフトも切り詰めも一切しない(既存アバターのUVを1ビットも変えないため)。
UV_IN_RANGE_TOL = 1e-4

# 整数シフト後にまだ残るごく僅かなはみ出し(パディング・座標精度由来)を
# セル境界へ切り詰めてよい上限。実測 alicia m03(Alicia_eye)は v が
# -0.004824 まで出ており、これは1タイル分のズレではなく単なる縁のはみ出し。
# **本物のタイリングは必ず 1.0 以上ずれる**ので、この値との間には桁の開きがある。
#
# 2026-07-29追加(dev#18主要ケース修理): この判定は`vp_atlas_uvbake.py`の
# Pass 2で**面(ポリゴン)単位**に適用される(スロット全体のbboxではない)。
#   - はみ出し <= この値 かつ > UV_IN_RANGE_TOL: 跨いだ頂点だけを
#     `clamp01()`でセル境界へ切り詰めて変換を続行する(面は裂けない。
#     診断実験 work\\wp_comodo\\fix_experiment_clamp.py で実証済み)
#   - この値を超えるはみ出し(面自体が1タイル以上に広がる本物のタイリング。
#     `face_wrap_shift`のdocstring参照)は、**その面だけ**個別除外し
#     元のUVのまま触らない(旧実装はスロット全体を丸ごと除外しており、
#     境界を跨ぐ面がわずか数枚でも無関係な大部分の面まで巻き添えで
#     見た目が壊れていた。comodoのエプロンがアトラス画像そのものを
#     表示してしまう不具合の真因)
# 値そのもの(0.02)は緩めていない。変わったのは適用粒度(スロット→面)のみ。
UV_CELL_CLAMP_TOL = 0.02


def face_wrap_shift(lo, hi, tol=UV_IN_RANGE_TOL):
    """1つの面のUVレンジ [lo,hi](u軸またはv軸)を [0,1] のタイルへ戻すための
    **整数**シフト量を返す。

    - すでに [0,1] に(tol の範囲で)収まっているなら **0**。
      これにより既存アバターのUVは1ビットも変わらない(無退行の根拠)。
    - そうでなければ面の中心が [0,1) に入る整数を返す。
    - 面自体が1タイルより広いときは、中心を合わせても収まらない。
      収まったかどうかは呼び出し側が(シフト後のbboxで)判定すること。
    """
    if lo >= -tol and hi <= 1.0 + tol:
        return 0
    return -int(math.floor((lo + hi) * 0.5))


def clamp01(x):
    """[0,1] へ切り詰める。`UV_CELL_CLAMP_TOL` 以内のはみ出しにのみ使うこと。"""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def bbox_overshoot(bbox):
    """bbox=[umin,umax,vmin,vmax] が [0,1]x[0,1] からはみ出している最大量。
    収まっていれば 0.0。"""
    umin, umax, vmin, vmax = bbox
    return max(-umin, umax - 1.0, -vmin, vmax - 1.0, 0.0)


# ---------------------------------------------------------- UV島(連結成分)同定
#
# 2026-07-29追加(dev#18 主要ケース修理、オーナー裁定): ケース3(セルを大きく
# 超えるUVを持つ面の扱い)を「個別除外」から「UV島単位の等倍縮小フィット」へ
# 変更した際に必要になった。面ごとに別々にフィットすると島の内部で裂けるため、
# 「この面を含むUV島全体」を特定する必要がある。
# `vp_atlas_uvbake.py`(本番、Blender headless)と検証スクリプト
# (`work\\wp_18fix\\verify_case1_invariant.py`等)の両方が**同一ロジック**で
# 島を再計算できるよう、bpy非依存のこのモジュールへ置く。

def find_uv_islands(mesh, uv_data, poly_index_list):
    """`poly_index_list`(同一メッシュ内のポリゴンindexの列)を、UV連結成分
    (=UV島)へ分割する。

    `mesh`は`obj.data`(bpyのMesh)、`uv_data`は`obj.data.uv_layers[0].data`
    を想定するが、`mesh.polygons[pi].loop_indices`
    (ループindexのイテラブル)・`mesh.loops[li].vertex_index`
    (int)・`uv_data[li].uv`([u,v]でindexアクセス可能)の3つのインターフェース
    さえ満たせば任意のオブジェクトで動く(bpy非依存)。

    暫定実装(2026-07-29、dev#18): 「同じメッシュ頂点を指し、かつUV値が
    一致する2つのループは同じ島」を連結条件とする単純なunion-findで、
    bmeshのエッジ厳密比較ではない。通常のUVアンラップ(頂点が同じなら
    UVも同じ=繋がっている、UVシームがあれば頂点は同じでもUV値が違う=
    切れている)ではこれで正しく島を分離できる。将来、本命のUVベイク
    実装に置き換わる前提の仮実装。

    戻り値: [[poly_index, ...], ...] (島ごとのポリゴンindexリスト)
    """
    parent = {pi: pi for pi in poly_index_list}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    vkey_to_polys = {}
    for pi in poly_index_list:
        poly = mesh.polygons[pi]
        for li in poly.loop_indices:
            vidx = mesh.loops[li].vertex_index
            uv = uv_data[li].uv
            key = (vidx, round(float(uv[0]), 5), round(float(uv[1]), 5))
            vkey_to_polys.setdefault(key, []).append(pi)
    for polys in vkey_to_polys.values():
        for i in range(1, len(polys)):
            union(polys[0], polys[i])

    islands = {}
    for pi in poly_index_list:
        islands.setdefault(find(pi), []).append(pi)
    return list(islands.values())


# ------------------------------------------------------------ タイリング検出

def detect_tiling(u_min, u_max, v_min, v_max, extent_threshold=1.5, bound_margin=0.5):
    """マテリアルが使う面のUVバウンディングボックスが[0,1]を大きく超えるか
    (=タイリング用UVらしいか)を判定する。

    - u/vいずれかのレンジ(max-min)が`extent_threshold`を超える
    - または min/max が [-bound_margin, 1+bound_margin] の範囲を外れる
    のいずれかでTrue。レース・網目模様等でよくある「UVが0〜3, 0〜4」の
    ようなケースを確実に捕まえつつ、通常のUVアイランドが持ちうる軽微な
    はみ出し(パディング等、-0.02〜1.02程度)は誤検出しないよう
    マージンを設けている(実測に基づく既定値。次の人が閾値を調整する場合は
    このdocstringのケースを両方満たすテストで確認すること)。"""
    u_range = u_max - u_min
    v_range = v_max - v_min
    if u_range > extent_threshold or v_range > extent_threshold:
        return True
    if u_min < -bound_margin or u_max > 1.0 + bound_margin:
        return True
    if v_min < -bound_margin or v_max > 1.0 + bound_margin:
        return True
    return False


# --------------------------------------------------------- 単色(texture=null)マテリアル
#
# 2026-07-26追加(オーナー裁定「seedは結局なんなの? もしかして元のマテリアルが
# colorだけとか?」— 実データで確認済み、仮説的中): VRMのマテリアルは
# 必ずしもテクスチャを持たない。`base_color_texture`が無く単色
# (Principled BSDFのBase Colorのみ)のマテリアルは`avatar_meta.json`上で
# `texture: null` になるが、`base_color`(RGBA)は`step01_import_vrm.py:
# get_base_color()`が必ず記録している(既定値 [1,1,1,1] を含め常に非None)。
#
# 旧実装(`if not tex: continue`)はこれを「テクスチャ解決に失敗した」ものと
# 誤認し、アトラス計画から静かに全面除外していた。除外されるとUVが一切
# 変換されず、単一共有アトラス(SINGLE_MATERIAL=True)上の無関係な領域を
# 指してしまう(seedの胸ロゴ`m16`で実測確認: 生UVがたまたま髪/ロボアーム
# 領域を指し、そこが胸に描画されていた)。
#
# 修正方針: texture=nullでもbase_colorがあれば「そのマテリアル専用の
# アトラスセルを、そのbase_colorの単色で塗りつぶす」ことでアトラス計画に
# 正規に組み込む。ジオメトリ側(m16は独立した36面の小さいUVアイランド)が
# ロゴの形を作っているため、セルをどのUV範囲でサンプルしても単色である限り
# 見た目は完全に再現できる。
SOLID_COLOR_PREFIX = "\x00solid_color\x00"


def solid_color_key(rgba):
    """base_color(RGBA, 0..1 float 4要素)から、texture_orderで実PNGファイル名と
    衝突しない一意なキーを作る。同じ色は同じキーになるため、複数スロットが
    同色ならアトラスセルを共有して無駄なく詰められる。"""
    r, g, b, a = (round(float(x), 5) for x in rgba[:4])
    return f"{SOLID_COLOR_PREFIX}{r},{g},{b},{a}"


def is_solid_color_key(key):
    """`solid_color_key()`が作った合成キーかどうか(=実ファイルではない)。"""
    return isinstance(key, str) and key.startswith(SOLID_COLOR_PREFIX)


def parse_solid_color_key(key):
    """`solid_color_key()`の逆変換。(r,g,b,a) の4-tuple(float)を返す。"""
    payload = key[len(SOLID_COLOR_PREFIX):]
    return tuple(float(x) for x in payload.split(","))


def linear_to_srgb(c):
    """Blenderのマテリアル係数(リニア色空間 0..1)を、PNGが期待する
    sRGBガンマ符号化(0..1)へ変換する。

    ■なぜ要るか(実測で確認済み): seedのm16 base_color=[0.019,0.171,0.279]は
    リニア値。既存の全テクスチャ(t00.png等)はアーティストが作った通常の
    sRGB画像で、Blenderの TEX_IMAGE ノードもUE側のテクスチャサンプルも
    「PNGはsRGB符号化されている」前提で一貫して扱っている(本リポジトリに
    それを覆す設定は無い)。したがって単色セルもこのリニア→sRGB変換を経て
    PNGへ書き込まないと、テクスチャ経由で読んだときだけ暗く/くすんで見える
    (実測: 変換前 RGB(5,44,71)の暗紺、変換後 RGB(37,115,144)の水色。
    破損前レンダリング`_visual_check_seed_ref_crop.png`のロゴの水色と
    変換後の値が一致することを目視確認済み)。"""
    c = 0.0 if c < 0.0 else (1.0 if c > 1.0 else c)
    if c <= 0.0031308:
        return c * 12.92
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def solid_color_image(rgba, size=8):
    """rgba(リニア0..1、4要素)で塗りつぶした size x size の RGBA uint8画像を作る。
    後段の`build_atlas_image`が`resize_nearest`で目的のセルサイズへ拡大するため、
    ここでの実サイズは何でもよい(単色なので拡大しても劣化しない)。
    アルファはsRGB変換の対象外(アルファチャンネルは元々リニア量)。"""
    import numpy as np
    r, g, b, a = rgba[0], rgba[1], rgba[2], rgba[3]
    r8 = round(linear_to_srgb(r) * 255)
    g8 = round(linear_to_srgb(g) * 255)
    b8 = round(linear_to_srgb(b) * 255)
    a8 = round((0.0 if a < 0.0 else (1.0 if a > 1.0 else a)) * 255)
    img = np.empty((size, size, 4), dtype=np.uint8)
    img[:, :, 0] = r8
    img[:, :, 1] = g8
    img[:, :, 2] = b8
    img[:, :, 3] = a8
    return img


# ------------------------------------------------------------ アトラス画像合成

def resize_nearest(rgba, new_w, new_h):
    """vp_texinject.resize_nearest の再利用(ニアレストネイバー)"""
    return vp_texinject.resize_nearest(rgba, new_w, new_h)


def build_atlas_image(images, cell_size=2048, max_canvas=4096):
    """images: [(h,w,4) uint8 ndarray, ...] を順番に(index=i -> row,col=
    compute_grid経由の行優先配置)1枚のキャンバスへ敷き詰める。

    戻り値: (canvas (H,W,4) uint8 ndarray, rows, cols, 実際に使ったcell_size)"""
    import numpy as np
    n = len(images)
    if n == 0:
        raise ValueError("build_atlas_image: images is empty")
    rows, cols = compute_grid(n)
    cs = cell_size
    if cs * max(rows, cols) > max_canvas:
        cs = max(64, max_canvas // max(rows, cols))
    canvas = np.zeros((rows * cs, cols * cs, 4), dtype=np.uint8)
    canvas[:, :, 3] = 255
    for i, img in enumerate(images):
        r, c = divmod(i, cols)
        resized = resize_nearest(img, cs, cs)
        canvas[r * cs:(r + 1) * cs, c * cs:(c + 1) * cs] = resized
    return canvas, rows, cols, cs


def build_atlas_from_paths(paths, cell_size=2048, max_canvas=4096):
    """PNGファイルパスのリスト(順序=グリッド配置順)からアトラスを合成する。

    要素が`solid_color_key()`で作った合成キー(実ファイルではない)の場合は
    ファイルを読まず、その場で単色画像を合成する(texture=nullマテリアル用)。"""
    images = []
    for p in paths:
        if is_solid_color_key(p):
            images.append(solid_color_image(parse_solid_color_key(p)))
        else:
            _, _, rgba = vp_tex.decode_png(p)
            images.append(rgba)
    return build_atlas_image(images, cell_size=cell_size, max_canvas=max_canvas)


# ------------------------------------------------------------ ラベル単位プラン

def plan_label(texture_order):
    """texture_order: 1ラベル(body/parka)に属する distinct テクスチャ
    ファイル名の順序付きリスト(重複無し、呼び出し側で重複排除済み前提)。

    戻り値: (transforms: {texture_filename: (su,sv,ou,ov)}, rows, cols)
    len(texture_order)<=1 の場合は ({}, 1, 1) を返す
    (=アトラス不要のシグナル。呼び出し側はtransformsが空ならアトラス化を
    スキップし、従来どおり元のPNGをそのまま使うこと)。"""
    n = len(texture_order)
    if n <= 1:
        return {}, 1, 1
    rows, cols = compute_grid(n)
    transforms = {tex: cell_transform(i, rows, cols) for i, tex in enumerate(texture_order)}
    return transforms, rows, cols


def plan_avatar(meta):
    """avatar_meta.json(dict、キーは"slots"を含む)から、body/parkaそれぞれの
    アトラスプランを作る。分類は`classify_material()`(モジュール上部、
    dump_avatar_mesh.pyと同期必須)。

    PNG以外のテクスチャを参照するスロットは対象から除外する(既存の
    「PNG以外は自動注入をスキップ」制約を踏襲。除外リストを第2戻り値で返す)。

    2026-07-26追加: `texture: null`(テクスチャを持たず単色のみのマテリアル。
    モジュール上部「単色(texture=null)マテリアル」節参照)は、
    `base_color`があれば`solid_color_key()`で合成した仮想テクスチャ扱いで
    正規にプランへ組み込む(=もう`if not tex: continue`で静かに除外しない)。
    `base_color`すら無い(旧形式meta等)場合のみ、真に解決不能として
    第2戻り値へ`(slot_id, "<no-texture-no-basecolor:orig_name>")`の形で記録し
    除外する(呼び出し側convert_noue.pyがこの形式を検出して警告を出す)。

    戻り値: (plan, skipped)
      plan = {
        "body": {
          "texture_order": [distinct filename または solid_color_key, ...]  (初出順),
          "texture_transform": {filename: (su,sv,ou,ov)} (アトラス不要なら空dict),
          "rows": int, "cols": int,
          "slots": [slot_id, ...] (このラベルの全スロットid),
          "slot_texture": {slot_id: filename または solid_color_key},
        },
        "parka": {...(同様)},
      }
      skipped = [(slot_id, texture_filename), ...]  (非PNG除外)
              + [(slot_id, "<no-texture-no-basecolor:orig_name>"), ...]  (真に解決不能)
    """
    slots = meta.get("slots", {})
    per_label = {
        0: {"order": [], "seen": set(), "slots": [], "slot_texture": {}, "alpha_mask": False},
        1: {"order": [], "seen": set(), "slots": [], "slot_texture": {}, "alpha_mask": False},
    }
    skipped_non_png = []
    for slot_id in sorted(slots.keys()):
        info = slots[slot_id]
        tex = info.get("texture")
        if not tex:
            base_color = info.get("base_color")
            if base_color and len(base_color) >= 4:
                tex = solid_color_key(base_color)
            else:
                orig_name = info.get("orig_name", "")
                skipped_non_png.append(
                    (slot_id, f"<no-texture-no-basecolor:{orig_name}>"))
                continue
        elif not tex.lower().endswith(".png"):
            skipped_non_png.append((slot_id, tex))
            continue
        label = classify_material(info.get("orig_name", ""))
        bucket = per_label[label]
        bucket["slots"].append(slot_id)
        bucket["slot_texture"][slot_id] = tex
        if (info.get("alpha_mode") or "").upper() == "MASK":
            bucket["alpha_mask"] = True
        if tex not in bucket["seen"]:
            bucket["seen"].add(tex)
            bucket["order"].append(tex)

    plan = {}
    for label, name in LABELS.items():
        bucket = per_label[label]
        transforms, rows, cols = plan_label(bucket["order"])
        plan[name] = {
            "texture_order": bucket["order"],
            "texture_transform": transforms,
            "rows": rows,
            "cols": cols,
            "slots": bucket["slots"],
            "slot_texture": bucket["slot_texture"],
            "alpha_mask": bucket["alpha_mask"],
        }
    return plan, skipped_non_png


def slot_transforms(plan):
    """plan_avatar()の戻り値(plan)から、アトラスが有効なラベルに属する
    スロットのみを集めた {slot_id: (su,sv,ou,ov)} を作る。
    アトラス不要なラベル(texture_transformが空)のスロットは含まれない
    (=そのラベルのスロットはUV変換不要、元のUVのまま使う)。
    戻り値が空dictなら、このアバターはどのラベルもアトラス化不要
    (=既存の1テクスチャ直接注入のみで完結、Blender UV焼き込み工程は
    スキップしてよい)。"""
    out = {}
    for label_info in plan.values():
        tt = label_info["texture_transform"]
        if not tt:
            continue
        for slot, tex in label_info["slot_texture"].items():
            xf = tt.get(tex)
            if xf:
                out[slot] = xf
    return out
