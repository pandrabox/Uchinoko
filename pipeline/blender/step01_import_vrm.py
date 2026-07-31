# -*- coding: utf-8 -*-
"""Step01: VRMを読み込み、移植用に正規化する。

実行: blender --background --factory-startup --python-exit-code 1 --python step01_import_vrm.py -- <job.json>
出力: <job>/converted/step01_clean.blend
      <job>/textures/*.png(ベースカラーテクスチャ)
      <job>/converted/avatar_meta.json(Humanoidマップ・スロット表・警告・
        非スキンメッシュの元の親ボーン名)

やること:
  1. VRMアドオンでインポート(0.x / 1.0 両対応)
  2. アーマチュア変換Apply、シェイプキー全削除(表情非対応)
  3. ボーンコンストレイント全削除(SpringBone/Node Constraintの剛体化)
  4. Humanoid定義から {パルボーン: 実ボーン名} を確定
  5. マテリアルをASCII安全名(m00..)に改名し、ベースカラーテクスチャをPNG抽出
"""

import contextlib
import json
import os
import re
import shutil
import struct
import sys
import zlib

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_bl
import vp_modnorm
from vp_bl import core

TAG = "step01"


def _matte_rgb():
    """U50診断用: D2P_MATTE_COLOR環境変数('R,G,B'各0-255)をタプルで返す。
    未設定・空・不正値ならNone(呼び出し側はNoneなら完全no-op)。ハードコード
    禁止(現場で色を選び直せるようにするための要件)。"""
    raw = os.environ.get("D2P_MATTE_COLOR")
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 3:
        print(f"[{TAG}][WARN] invalid D2P_MATTE_COLOR (specify as R,G,B): {raw!r} — ignoring")
        return None
    try:
        r, g, b = (max(0, min(255, int(p.strip()))) for p in parts)
    except ValueError:
        print(f"[{TAG}][WARN] invalid D2P_MATTE_COLOR (not integers): {raw!r} — ignoring")
        return None
    return (r, g, b)


def _png_size(path):
    """PNGファイルのIHDRチャンクからwidth/heightを読む(PNG仕様上IHDRは常に
    signature直後の最初のチャンクなので固定オフセットで安全に読める)。
    PNGでない/壊れている場合はNone。"""
    with open(path, "rb") as f:
        head = f.read(33)
    if len(head) < 33 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def apply_matte_if_enabled(path):
    """U50診断用: D2P_MATTE_COLOR設定時のみ、既にtex_dirへ書き出し済みの
    PNGテクスチャ(path)を、同じ解像度・RGBA・アルファ255固定の単色で上書き
    する。実機SSで「この色が写っている画素=キャラ領域」と直接判定するための
    マット注入(推定ではなく色注入でシルエットを得る)。

    未設定(既定)なら os.environ.get が None を返した時点で即returnし、
    ファイルI/Oを一切行わない完全no-op。対象はPNGのみ(拡張子が.png以外の
    コピーは対象外・警告のみで元ファイルは無改変のまま残す)。"""
    color = _matte_rgb()
    if color is None:
        return
    if not path.lower().endswith(".png"):
        print(f"[{TAG}][WARN] matte only supports PNG, skipping: {path}")
        return
    size = _png_size(path)
    if size is None:
        print(f"[{TAG}][WARN] failed to parse PNG header, skipping matte: {path}")
        return
    w, h = size
    r, g, b = color
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # bitdepth8, colortype6=RGBA
    row = bytes([0]) + bytes((r, g, b, 255)) * w  # フィルタ0(None) + 画素データ
    raw = row * h
    idat = zlib.compress(raw, 6)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    print(f"[{TAG}] D2P_MATTE_COLOR applied: overwrote {path} with solid RGBA({r},{g},{b},255) "
          f"({w}x{h})")


def import_vrm(job):
    # VRMのライセンス確認ダイアログはヘッドレスで出せない。ツール側(GUI/CLI)で
    # 「アバターの規約を確認した」チェックを必須にした上で、アドオン公式の
    # 自動確認モードで通す(規約確認の責任はユーザーにある旨をUI/READMEに明記)
    os.environ["BLENDER_VRM_AUTOMATIC_LICENSE_CONFIRMATION"] = "true"
    before = set(bpy.data.objects)
    bpy.ops.import_scene.vrm(filepath=job["vrm_path"])
    new_objs = set(bpy.data.objects) - before
    arm = next((o for o in new_objs if o.type == "ARMATURE"), None)
    if arm is None:
        core.die(TAG, "VRM import produced no Armature")
    return arm


def _safe_exists(path):
    """os.path.existsの完全非例外版。Windowsではパス長超過・不正な文字などで
    OSError/ValueErrorが飛びうるため、判定不能は一律「無い」とみなす
    (存在判定でクラッシュしてはならない)。"""
    try:
        return os.path.exists(path)
    except (OSError, ValueError):
        return False


def _is_within(path, base):
    """pathがbaseの内側(base自身は含まない)かどうか。両者とも正規化済み前提。"""
    p = os.path.normcase(path)
    b = os.path.normcase(base)
    return p.startswith(b + os.sep)


def _immediate_subdirs(base):
    """base直下のサブディレクトリ(ソート順)。列挙不能なら空リスト。"""
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(base, n)
        try:
            if os.path.isdir(p):
                out.append(p)
        except OSError:
            continue
    return out


def fbx_texture_candidates(recorded_path, base_dir):
    """FBXに記録されたテクスチャ参照を解決するための候補パスを、
    **明示的に与えたルート(base_dir)基準だけ**で、正規化済みで組み立てる。

    dev#369の構造的原因: BlenderのFBXインポータ(io_scene_fbx.import_fbx.
    blen_read_texture_image)は、FBXが持つ `RelativeFilename` を
    `os.path.join(basedir, filepath)` で**今そのFBXが置かれているフォルダ**
    に対して連結する。ところがその相対パスは、FBXを書き出した側(Unityの
    FBX Exporter)が**別の基準ディレクトリ**(ユーザーのUnityプロジェクト、
    例: %LOCALAPPDATA%\\VRChatProjects\\...)で記録したものである。
    D2Pは輸出したFBXを `work\\<名前>_export\\` へ置くため、基準が食い違い、
    `work\\X_export\\..\\..\\..\\..\\..\\..\\..\\..\\AppData\\Local\\...` という
    「基準の違う相対パスを別の基準へ連結した」だけの無意味なパスが生まれる。

    そのパスは正規化されないままBlenderの `bpy.path.resolve_ncase()` に渡り、
    `_ncase_path_found()` の `os.listdir(dirpath)` が `PermissionError` しか
    捕捉していないため、それ以外のOSError(実報告では `..` 8段ぶんの冗長な
    24文字がWin32のパス長上限を越えて出た `FileNotFoundError [WinError 3]`)が
    そのまま外へ抜け、**変換全体が停止**していた。

    したがって修正は「`..` の段数を数え直す」ことではない。
      * 候補は必ず **正規化してから** OSへ渡す(冗長な `..` を一切通さない)
      * 連結の基準は **明示的に渡されたルートのみ**とする
      * base_dirの外へ逃げる記録パスは「別の基準で書かれたもの」とみなして
        後回しにし、まずはbase_dir配下(D2P輸出物の実体がある場所)を見る

    返り値: 候補パスのリスト(重複除去済み・すべて正規化済み・優先度順)。
    """
    base = os.path.normpath(os.path.abspath(base_dir))
    raw = (recorded_path or "")
    raw = raw.replace("/", os.sep).replace("\\", os.sep)
    if not raw:
        return []
    if os.path.isabs(raw):
        norm = os.path.normpath(raw)
    else:
        norm = os.path.normpath(os.path.join(base, raw))
    name = os.path.basename(norm)
    inside = _is_within(norm, base)

    cands = []

    def add(p):
        p = os.path.normpath(p)
        if p not in cands:
            cands.append(p)

    # 1) base_dirの内側に収まる参照は、記録されたパスをそのまま採用する
    #    (D2P輸出物がサブフォルダを持つ通常ケース。従来の挙動を保つ)
    if inside:
        add(norm)
    # 2) base_dir直下のファイル名一致(Unity輸出はテクスチャをFBXと同じ
    #    フォルダへ書き出すため、実運用ではここで当たる)
    if name:
        add(os.path.join(base, name))
        # 3) base_dir直下のサブフォルダのファイル名一致
        for sub in _immediate_subdirs(base):
            add(os.path.join(sub, name))
    # 4) base_dirの外を指す記録パス(=別の基準で書かれたもの)は最後の手段。
    #    正規化済みなので冗長な `..` はOSへ渡らない
    if not inside:
        add(norm)
    return cands


def resolve_fbx_texture(recorded_path, base_dir):
    """fbx_texture_candidates()の候補を順に見て、最初に実在したものを返す。

    返り値: (解決したパス or None, 試した候補の全リスト)。
    解決できなかった場合に候補リストを必ず返すのは、失敗時に
    「どの基準で・どこを探したか」をログへ残せるようにするため
    (自動探索は必ず探索先と判定をログに残す、というプロジェクト規約)。
    """
    cands = fbx_texture_candidates(recorded_path, base_dir)
    for c in cands:
        if _safe_exists(c):
            return c, cands
    return None, cands


@contextlib.contextmanager
def rooted_fbx_texture_resolution(base_dir):
    """FBXインポートの間だけ、Blenderの外部テクスチャ解決を
    「明示ルート基準・正規化済み・非致命」へ差し替えるコンテキストマネージャ。

    io_scene_fbx は `from bpy_extras import image_utils` してから
    `image_utils.load_image(...)` を呼ぶ(=呼び出し時にモジュール属性を引く)
    ので、ここで属性を差し替えれば確実に経路を押さえられる。差し替えるのは
    引数の組み立てだけで、実際の画像ロード・プレースホルダ生成はBlender本体の
    load_image()にそのまま任せる(挙動の再実装をしない)。
    """
    try:
        from bpy_extras import image_utils
    except ImportError:  # Blender外(単体テスト等)では何もしない
        yield
        return
    original = image_utils.load_image

    def rooted_load_image(imagepath, dirname="", **kwargs):
        root = dirname or base_dir
        recorded = str(imagepath or "")
        resolved, cands = resolve_fbx_texture(recorded, root)
        if resolved is not None:
            return original(resolved, dirname=root, **kwargs)
        # 解決できなかった: どの基準で何を試したかを必ず残す。
        # ここで停止はしない(FBX入力のテクスチャはUnity輸出の
        # material_map.jsonが正本であり、Blender側の解決は補助にすぎない)。
        print(f"[{TAG}][WARN] FBX texture reference could not be resolved: {recorded}")
        print(f"[{TAG}]   base used: {root}")
        for c in cands:
            print(f"[{TAG}]   tried: {c}")
        # ファイル名だけをBlenderへ渡す(place_holder=Trueなので
        # プレースホルダ画像が返る。二度と冗長な `..` を渡さない)
        fallback = os.path.basename(recorded.replace("/", os.sep).replace("\\", os.sep))
        return original(fallback or recorded, dirname=root, **kwargs)

    image_utils.load_image = rooted_load_image
    try:
        yield
    finally:
        image_utils.load_image = original


def import_fbx_avatar(job, warnings, humanoid_json=None):
    """FBX入力(VRChatter向け)。Humanoid対応表はhumanoid.json(Unity輸出)から。"""
    import json
    import mathutils
    before = set(bpy.data.objects)
    # dev#369: FBXに記録されたテクスチャ相対パスは、書き出した側(Unity
    # プロジェクト)の基準で書かれている。それをFBXの現在位置へ連結する
    # Blender既定の解決は、基準が違うため無意味なパスを生み、しかも
    # 失敗が致命的(FileNotFoundErrorで変換全体が停止)だった。
    # 明示ルート(FBXのあるフォルダ)基準の解決へ差し替える。
    with rooted_fbx_texture_resolution(os.path.dirname(
            os.path.abspath(job["vrm_path"]))):
        bpy.ops.import_scene.fbx(filepath=job["vrm_path"])
    new_objs = set(bpy.data.objects) - before
    arms = [o for o in new_objs if o.type == "ARMATURE"]
    if not arms:
        core.die(TAG, "FBX import produced no Armature")
    # 複数アーマチュアがある変則FBXは、ボーン数最大のものを本体とみなす
    arm = max(arms, key=lambda a: len(a.data.bones))
    if len(arms) > 1:
        warnings.append(f"detected multiple Armatures. Using {arm.name} (others discarded)")
    # ミラー由来の負スケールは法線が裏返る恐れがある(焼き込みはするが警告)
    for o in new_objs:
        if o.type == "MESH" and min(o.scale) < 0:
            warnings.append(f"mesh with negative scale: {o.name} (faces may be flipped)")

    # 座標系の平坦化(Unity FBX Exporter産FBX対策、2026-07-22 toto実測):
    # 親Empty(Armatureノード)がスケールを持ち「アーマチュア空間 != ワールド」に
    # なる(ボーンだけ2.18倍など。ワールドでは整合するのでBlender上は正常に見える)。
    # step02リターゲットはアーマチュア空間で読むため、親子を切ってワールド変換を
    # 実体へ焼き込み、空間を一致させる。あわせて単位もmへ正規化する
    meshes = [o for o in new_objs if o.type == "MESH"]
    # 非スキンメッシュ(頂点グループ0)の元の親ボーン名を、直後のparent_clear()で
    # 親子関係が切れる前に記録しておく。ボーン直付け(parent_type=BONE)だけで
    # なく、ボーン末端のEmpty子ノード経由(PhysBoneCollider等と同型)で間接的に
    # ぶら下がっているケースも、Empty側の親を遡って最初のBONE親を採用する。
    # D2P平坦化FBXではこの後メッシュのparent_type/parent_boneをOBJECT/""へ
    # 強制するため(下のコメント参照)、元の親ボーン情報はここでしか取れない。
    # step02のzero-weight rescueが「元の親ボーンに対応するパルボーンへ束縛」
    # するために使う(帽子・リボン等が腰[pelvis固定]でなく頭に付くようにする)。
    source_parent_bone = {}
    for o in meshes:
        if len(o.vertex_groups) > 0:
            continue  # スキン済みは対象外(ここでの推定は使わない)
        cur = o
        seen = set()
        bone_name = None
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if cur.parent_type == "BONE" and cur.parent_bone:
                bone_name = cur.parent_bone
                break
            cur = cur.parent
        source_parent_bone[o.name] = bone_name
    keep = [arm] + meshes
    # FBXシーンルート(toto等)の行列 = 「Unityワールド→Blenderワールド」変換。
    # D2P平坦化FBXの頂点データはUnityワールド座標なので、メッシュにはこれを使う
    # (アーマチュア行列はeRoot=Hipsノードの平行移動を含むため使えない)
    root_obj = arm
    while root_obj.parent is not None:
        root_obj = root_obj.parent
    root_mat = root_obj.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    for o in list(new_objs):
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    # D2P平坦化済みFBX(DiveToPalworldExporter産)は「メッシュ頂点データと
    # ボーンデータが同一空間」なので、メッシュのオブジェクト行列を
    # アーマチュアと同一にすれば厳密に整合する(BlenderのFBXインポータが
    # スキンメッシュを誤配置する問題の決定的な回避。2026-07-22)
    flattened = False
    if humanoid_json:
        try:
            with open(humanoid_json, encoding="utf-8") as f:
                flattened = bool(json.load(f).get("d2p_flattened"))
        except Exception:
            pass
    # D2P平坦化FBXの前提「メッシュ頂点データとボーンデータが同一空間」は、
    # Unity側 DiveToPalworldExporter.FlattenSkinnedMeshes() が
    # **SkinnedMeshRenderer のみ**を対象に頂点をバインド時ワールドへ焼き込み、
    # ルート直下・ローカル原点へ再配置しているために成り立つ(unity側は
    # 読み取り専用で確認済み。書き込みは対象外ファイルのため不可)。
    # 素のMeshRenderer(帽子・リボン等、スキニングされずボーンやその末端の
    # Empty子ノードへTransformで直付けされたアクセサリ)はUnity側で一切
    # 平坦化されず、元のノード位置のまま輸出される。この種のメッシュは
    # 直前のparent_clear(CLEAR_KEEP_TRANSFORM)で既に正しいワールド位置が
    # matrix_worldへ解決されている。
    #
    # 判定は「頂点グループ(スキンウェイト)を1つでも持つか」で行う。
    # BlenderのFBXインポータはDeformer(スキン)クラスタ情報がFBX側にあれば
    # 頂点グループを作る(元FBXでの親ノード種別・Armatureモディファイアの
    # 有無に関わらない)。頂点グループが1つも無いメッシュだけが真に
    # 「スキンされていない=位置は親ノードのTransformのみで決まる」もの。
    #
    # 判定基準を「Armatureモディファイアの有無」にしてはいけない
    # (2026-07-26 agyo検体で実測・却下): 単一ボーン100%ウェイトのスキン
    # メッシュをUnity FBX Exporterが「ボーン直接子」として最適化書き出しする
    # ケース(このファイル下部、OBJECT強制コメント参照)では、頂点グループ
    # 自体は複数個・実データ入りで存在するのにArmatureモディファイアが
    # 付かない(agyoのBody/karada/mohuで確認: n_vgroups=13/50/8だが
    # has_armature_modifier=False)。ここでmodifier有無を判定に使うと、
    # これら本来flatten対象のスキン済みメッシュを「非スキン」と誤判定し、
    # root_mat上書きをスキップしてしまい、平坦化FBX対応の本来の目的
    # (BlenderのFBXインポータがスキンメッシュを誤配置する問題の回避、
    # 2026-07-22)を壊す。
    #
    # 一方、頂点グループの有無なら両ケースを正しく区別できる:
    # 2026-07-26実測(flatver101_sunaoのFootLPBC/FootRPBC、PhysBoneCollider
    # 用の空リーフ)は頂点グループ0(真に非スキン)。一律上書きすると左右の
    # コライダーが別々の位置を失い同一座標(root_mat)へ収束することを確認
    # 済み(左右のmatrix_world.translationが完全一致した)。
    if flattened:
        unskinned = [o for o in meshes if len(o.vertex_groups) == 0]
        skinned_names = {o.name for o in meshes} - {o.name for o in unskinned}
        for o in meshes:
            if o.name not in skinned_names:
                continue
            o.matrix_world = root_mat.copy()
        warnings.append("D2P flattened FBX: pinned mesh matrices to the FBX root")
        if unskinned:
            warnings.append(
                "D2P flattened FBX: preserved position for non-skinned meshes "
                f"(attached directly to a bone/leaf node): {[o.name for o in unskinned]}")
    height = 0.0
    for o in meshes:
        for c in o.bound_box:
            height = max(height, (o.matrix_world @ mathutils.Vector(c)).z)
    if height > 10.0:  # 高さ10m超の人型はいない=cm単位と判断(Unity FBX Exporterはcm)
        s = mathutils.Matrix.Scale(0.01, 4)
        for o in keep:
            o.matrix_world = s @ o.matrix_world
        warnings.append(f"normalized units cm->m (pre-normalization height {height:.0f})")
    # 複数オブジェクトが同一Meshデータを共有(multi-user)していると、直後の
    # transform_applyがRuntimeErrorで即abortする(2026-07-26実測: PhysBone
    # Collider用にボーン末端の子として置かれた空リーフが、コンポーネント除去後
    # Unity FBX Exporterによって共有プレースホルダーMeshとして書き出される
    # ケースで発生。FootLPBC/FootRPBC等)。個別オブジェクトのtransformを
    # 安全に焼き込めるよう、共有Meshデータを複製して単一ユーザー化してから進む
    single_usered = []
    for o in meshes:
        if o.data is not None and o.data.users > 1:
            o.data = o.data.copy()
            single_usered.append(o.name)
    if single_usered:
        warnings.append(f"made multi-user mesh single-user: {single_usered}")
        print(f"[{TAG}] multi-user mesh made single-user: {single_usered}")
    bpy.ops.object.select_all(action="DESELECT")
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # メッシュはアーマチュアの子に戻す(ワールド維持)。step02の
    # global_scale_and_placeはchildren_recursiveへまとめてtransform_applyする
    # 前提のため、親子が切れているとメッシュだけ置き去りになり大破する
    # (2026-07-22実測: 糸状Vプレビューの真因)
    #
    # 単一ボーン100%ウェイトのスキンメッシュをUnity FBX Exporterが
    # 「ボーン直接子(parent_type=BONE, parent_bone=<bone>)」として最適化
    # 書き出しすることがある(2026-07-26実測: 特定検体の素体メッシュで発生)。
    # 上のparent_clear(CLEAR_KEEP_TRANSFORM)はparent=Noneにするがparent_bone
    # 属性の値は消さずに残す。その状態でo.parent=armだけを代入すると
    # Blenderがparent_boneの残留値を見てparent_typeを暗黙にBONEへ戻してしまい、
    # 以降のArmatureモディファイア評価がボーンローカル空間(Y軸基準)で解釈され
    # 90度分の姿勢ずれが生じる(2026-07-26 diag_M_ptcheckで実測確認済み)。
    # ここでは全メッシュに対しparent_type/parent_boneを明示的にOBJECTへ強制
    # することで、由来に関わらず「Armatureモディファイアで駆動する通常の
    # オブジェクト子」という意図した構造を保証する(名前のハードコードではなく
    # parent_type構造そのものへの一般的な対処)。
    for o in meshes:
        o.parent = arm
        o.parent_type = "OBJECT"
        o.parent_bone = ""
        o.matrix_parent_inverse = arm.matrix_world.inverted()
    return arm, source_parent_bone


def find_humanoid_json(job):
    """humanoid.jsonの場所: job指定 → <fbx名>.humanoid.json → 同フォルダのhumanoid.json"""
    if job.get("humanoid_json") and os.path.exists(job["humanoid_json"]):
        return job["humanoid_json"]
    fbx = job["vrm_path"]
    stem = os.path.splitext(fbx)[0]
    for cand in (stem + ".humanoid.json",
                 os.path.join(os.path.dirname(fbx), "humanoid.json")):
        if os.path.exists(cand):
            return cand
    core.die(TAG, "humanoid.json not found. FBX input requires a bone mapping table.\n"
             "Open the avatar in Unity, export it via the bundled unity\\HumanoidMapExporter.cs "
             "(place it under Assets/Editor) using the menu Tools > DiveToPalworld > "
             "Export Humanoid Map, and place the result in the same folder as the FBX")


def cleanup_objects(arm, warnings):
    """アーマチュアと、その配下のメッシュ以外を消す。非表示メッシュも落とす。"""
    keep_meshes = []
    for obj in list(bpy.data.objects):
        if obj is arm:
            continue
        if obj.type == "MESH" and (obj.parent is arm or any(
                m.type == "ARMATURE" and m.object is arm
                for m in obj.modifiers)):
            if obj.hide_viewport or obj.hide_render:
                warnings.append(f"excluded hidden mesh: {obj.name}")
                bpy.data.objects.remove(obj, do_unlink=True)
            else:
                keep_meshes.append(obj)
        else:
            bpy.data.objects.remove(obj, do_unlink=True)
    if not keep_meshes:
        core.die(TAG, "avatar has no meshes at all")
    # メッシュ名を無害な連番へ強制リネーム。VRMのメッシュ名がパルのボーン名と
    # 衝突すると(例: Seed-sanの「head」メッシュ)、FBX往復でUEがボーン側を
    # 「head1」にリネームし、頭がアニメ非追従になる実害を確認済み
    orig_names = {}
    for i, obj in enumerate(keep_meshes):
        orig = obj.name
        obj.name = f"geo_{i:02d}"
        if obj.data:
            obj.data.name = obj.name
        orig_names[obj.name] = orig
        if orig != obj.name:
            print(f"[{TAG}] mesh renamed: '{orig}' -> {obj.name}")
    return keep_meshes, orig_names


def apply_transforms(arm):
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for child in arm.children_recursive:
        child.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def drop_shape_keys():
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data.shape_keys:
            n = len(obj.data.shape_keys.key_blocks)
            obj.shape_key_clear()
            print(f"[{TAG}] shape keys dropped: {obj.name} ({n})")


def drop_bone_meshes(arm, meshes, drop_bones, warnings):
    """指定ボーン(とその子孫)にウェイトが乗った頂点を削除する(上級者向け)。
    Humanoid外アクセサリ(例: Seed-sanのロボアーム)を消したい時に使う。
    合計ウェイト>0.5の頂点を削除し、空になったメッシュはオブジェクトごと消す。"""
    if not drop_bones:
        return meshes
    targets = set()
    for name in drop_bones:
        bone = arm.data.bones.get(name)
        if bone is None:
            warnings.append(f"drop_bones: bone not found: {name}")
            continue
        targets.add(bone.name)
        for child in bone.children_recursive:
            targets.add(child.name)
    if not targets:
        return meshes
    print(f"[{TAG}] drop_bones: {sorted(drop_bones)} -> {len(targets)} bone(s) targeted (incl. descendants)")

    survivors = []
    for obj in meshes:
        idx = {vg.index for vg in obj.vertex_groups if vg.name in targets}
        if not idx:
            survivors.append(obj)
            continue
        sel = [v.index for v in obj.data.vertices
               if sum(g.weight for g in v.groups if g.group in idx) > 0.5]
        if not sel:
            survivors.append(obj)
            continue
        if len(sel) == len(obj.data.vertices):
            name = obj.name
            bpy.data.objects.remove(obj, do_unlink=True)
            print(f"[{TAG}] drop_bones: removed entire mesh: {name}")
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for i in sel:
            obj.data.vertices[i].select = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
        print(f"[{TAG}] drop_bones: {obj.name}: deleted {len(sel)} vertex(es)")
        if len(obj.data.vertices) == 0:
            bpy.data.objects.remove(obj, do_unlink=True)
        else:
            survivors.append(obj)
    if not survivors:
        core.die(TAG, "drop_bones removed every mesh (the spec is too broad)")
    return survivors


def extract_spring_roots(arm):
    """VRMのSpringBone定義から揺れ物チェーンのルートボーン名を抽出する。
    (VRM1: spring_bone1.springs の各先頭joint / VRM0: secondaryAnimationのbones)
    step02がこのうち「頭の子孫」だけを揺れ髪として採用する。"""
    ext = arm.data.vrm_addon_extension
    roots = []
    try:
        for spring in ext.spring_bone1.springs:
            joints = [j.node.bone_name for j in spring.joints
                      if j.node.bone_name]
            if joints:
                roots.append(joints[0])
    except AttributeError:
        pass
    try:
        for bg in ext.vrm0.secondary_animation.bone_groups:
            for b in bg.bones:
                if b.bone_name:
                    roots.append(b.bone_name)
    except AttributeError:
        pass
    roots = sorted({r for r in roots if r in arm.data.bones})
    if roots:
        print(f"[{TAG}] spring bone roots: {roots}")
    return roots


def clear_bone_constraints(arm):
    """SpringBone/NodeConstraint類の剛体化: ポーズボーンのコンストレイントを全削除。"""
    n = 0
    for pb in arm.pose.bones:
        for c in list(pb.constraints):
            pb.constraints.remove(c)
            n += 1
    if n:
        print(f"[{TAG}] bone constraints cleared: {n}")


# ------------------------------------------------------------- マテリアル抽出

def get_base_color(mat):
    """(image|None, rgba, alpha_mode, double_sided) を返す。
    MToon(VRMアドオン拡張)→ Principled → 任意のTEX_IMAGE の順で探す。"""
    image, rgba = None, (1.0, 1.0, 1.0, 1.0)
    alpha_mode, double_sided = "OPAQUE", False
    # 1) VRMアドオンのMToon拡張
    try:
        m1 = mat.vrm_addon_extension.mtoon1
        if m1.enabled:
            src = m1.pbr_metallic_roughness.base_color_texture.index.source
            image = src if src is not None else None
            rgba = tuple(m1.pbr_metallic_roughness.base_color_factor)
            alpha_mode = str(m1.alpha_mode)
            double_sided = bool(m1.double_sided)
            return image, rgba, alpha_mode, double_sided
    except AttributeError:
        pass
    # 2) ノードから
    if mat.use_nodes:
        principled = next((n for n in mat.node_tree.nodes
                           if n.type == "BSDF_PRINCIPLED"), None)
        if principled is not None:
            inp = principled.inputs.get("Base Color")
            if inp is not None:
                rgba = tuple(inp.default_value)
                for link in mat.node_tree.links:
                    if link.to_node is principled and link.to_socket is inp \
                            and link.from_node.type == "TEX_IMAGE":
                        image = link.from_node.image
        if image is None:
            tex = next((n for n in mat.node_tree.nodes
                        if n.type == "TEX_IMAGE" and n.image is not None), None)
            if tex is not None:
                image = tex.image
    if getattr(mat, "blend_method", "OPAQUE") in ("CLIP", "HASHED"):
        alpha_mode = "MASK"
    elif getattr(mat, "blend_method", "OPAQUE") == "BLEND":
        alpha_mode = "BLEND"
    double_sided = not mat.use_backface_culling
    return image, rgba, alpha_mode, double_sided


def _resolve_image_file(image, search_dirs):
    """画像の実ファイルを探す。FBXは外部参照が切れていることが多いので、
    Blenderの解決パス → アバター周辺フォルダのファイル名一致 の順で捜索する。"""
    try:
        p = bpy.path.abspath(image.filepath) if image.filepath else ""
    except Exception:
        p = ""
    if p and os.path.exists(p):
        return p
    base = os.path.basename(p) or image.name
    base = re.sub(r"\.\d{3}$", "", base)  # 'body.png.002' → 'body.png'
    if "." not in base:
        base += ".png"
    for d in search_dirs:
        cand = os.path.join(d, base)
        if os.path.exists(cand):
            return cand
    return None


def extract_materials_from_unity_map(meshes, orig_names, tex_dir, fbx_dir,
                                     map_path, warnings):
    """Unityエクスポータのmaterial_map.jsonからスロット表を作る(FBX入力の本命)。
    Unity側で実際に着ているマテリアル(lilToon差し替え済み)の実テクスチャが
    レンダラー名×スロット番号で来るので、FBX内の材質名のズレに影響されない。"""
    os.makedirs(tex_dir, exist_ok=True)
    with open(map_path, encoding="utf-8") as f:
        data = json.load(f)
    mesh_map = data.get("meshes", {})
    slots = {}
    sig_to_mat = {}
    tex_cache = {}

    def copy_tex(unity_file):
        if unity_file in tex_cache:
            return tex_cache[unity_file]
        src = os.path.join(fbx_dir, unity_file)
        if not os.path.exists(src):
            return None
        out_name = f"t{len(tex_cache):02d}" + os.path.splitext(unity_file)[1].lower()
        out_path = os.path.join(tex_dir, out_name)
        shutil.copy(src, out_path)
        apply_matte_if_enabled(out_path)
        tex_cache[unity_file] = out_name
        return out_name

    for obj in meshes:
        orig = orig_names.get(obj.name, obj.name)
        entries = mesh_map.get(orig)
        if entries is None:
            warnings.append(f"mesh not in material_map.json: {orig} (will use a solid color)")
            entries = []
        n_slots = max(len(obj.material_slots), 1)
        if obj.data.materials is None or len(obj.data.materials) == 0:
            obj.data.materials.append(None)
        for i in range(len(obj.material_slots)):
            info = entries[i] if i < len(entries) else None
            tex_file = copy_tex(info["texture"]) if info and info.get("texture") else None
            color = tuple(info.get("color", [1, 1, 1, 1])) if info else (0.5, 0.5, 0.5, 1.0)
            ds = bool(info.get("double_sided")) if info else False
            mat_name = info.get("material_name", "") if info else ""
            sig = (tex_file, color, ds)
            if sig not in sig_to_mat:
                slot = f"m{len(sig_to_mat):02d}"
                m = bpy.data.materials.new(slot)
                m.use_nodes = True
                m.diffuse_color = color
                sig_to_mat[sig] = m
                slots[slot] = {
                    "orig_name": mat_name, "texture": tex_file,
                    "base_color": [round(c, 5) for c in color],
                    "alpha_mode": "MASK", "double_sided": ds,
                }
                print(f"[{TAG}] slot {slot}: '{mat_name}' tex={tex_file} (unity map)")
            obj.material_slots[i].material = sig_to_mat[sig]
        if len(obj.material_slots) < len(entries):
            warnings.append(f"slot count mismatch: {orig} "
                            f"(blender={len(obj.material_slots)} unity={len(entries)})")
    return slots


def extract_materials(meshes, tex_dir, warnings, search_dirs):
    """マテリアルをm00..に改名し、テクスチャとスロット表を作る。"""
    os.makedirs(tex_dir, exist_ok=True)
    mats = []
    for obj in meshes:
        if not obj.data.materials:
            fallback = bpy.data.materials.new("vrm2pal_fallback")
            fallback.diffuse_color = (0.5, 0.5, 0.5, 1.0)
            obj.data.materials.append(fallback)
            warnings.append(f"assigned gray to mesh with no material: {obj.name}")
        for m in obj.data.materials:
            if m is not None and m not in mats:
                mats.append(m)
    slots = {}
    saved_images = {}
    for i, mat in enumerate(mats):
        orig = mat.name
        slot = f"m{i:02d}"
        image, rgba, alpha_mode, double_sided = get_base_color(mat)
        tex_file = None
        if image is not None:
            if image.name in saved_images:
                tex_file = saved_images[image.name]
            else:
                src = _resolve_image_file(image, search_dirs)
                if src is not None:
                    # 実ファイルがあればそのままコピー(再圧縮なし。png/jpg/tga可)
                    ext = os.path.splitext(src)[1].lower() or ".png"
                    tex_file = f"t{len(saved_images):02d}{ext}"
                    out = os.path.join(tex_dir, tex_file)
                    shutil.copy(src, out)
                    apply_matte_if_enabled(out)
                    saved_images[image.name] = tex_file
                elif image.has_data:
                    # 埋め込み画像(VRM等)はBlender経由でPNG化
                    tex_file = f"t{len(saved_images):02d}.png"
                    out = os.path.join(tex_dir, tex_file)
                    img_copy = image.copy()  # 元imageのfilepathを汚さない
                    img_copy.filepath_raw = out
                    img_copy.file_format = "PNG"
                    img_copy.save()
                    bpy.data.images.remove(img_copy)
                    apply_matte_if_enabled(out)
                    saved_images[image.name] = tex_file
                else:
                    warnings.append(f"texture not found: {orig} "
                                    f"({image.name}) — will use a solid color. "
                                    "Place the image file in the same folder as the FBX and re-run")
        mat.name = slot
        slots[slot] = {
            "orig_name": orig, "texture": tex_file,
            "base_color": [round(c, 5) for c in rgba],
            "alpha_mode": alpha_mode, "double_sided": double_sided,
        }
        print(f"[{TAG}] slot {slot}: '{orig}' tex={tex_file} alpha={alpha_mode}")
    return slots


def main():
    job, _ = vp_bl.load_job_from_argv()
    if not os.path.exists(job["vrm_path"]):
        core.die(TAG, f"VRM not found: {job['vrm_path']}")
    out_dir = core.job_subdir(job, "converted")
    tex_dir = core.job_subdir(job, "textures")
    warnings = []

    is_fbx = job["vrm_path"].lower().endswith(".fbx")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if is_fbx:
        humanoid_json = find_humanoid_json(job)
        arm, source_parent_bone = import_fbx_avatar(
            job, warnings, humanoid_json=humanoid_json)
    else:
        vp_bl.ensure_vrm_addon(job)
        arm = import_vrm(job)
        source_parent_bone = {}
    meshes, orig_names = cleanup_objects(arm, warnings)
    # 入口での正規化(公開issue #18・dev#299): 制作者が編集時に表示を切ったまま
    # 保存したArmatureモディファイア(show_viewport/show_render=False)を強制
    # ONにする。また、上のcleanup_objectsで破棄された重複Armatureを指していた
    # ままの、ターゲット参照切れ(object=None)のArmatureモディファイアを除去
    # する(dev#299: 表示フラグがTrueでもBlenderはこれを「無効」と判定し、
    # 放置するとstep02のmodifier_applyが「モディファイアーはOFFです」相当の
    # RuntimeErrorで停止する)。いずれもエラーにせずログを残して進む。
    for mesh_name, _mod, reasons in vp_modnorm.normalize_armature_modifiers(
            meshes, tag=TAG):
        if reasons == vp_modnorm.ORPHAN_TARGET_REASON:
            warnings.append(
                f"armature modifier on '{mesh_name}' had no target armature "
                f"(orphaned reference, likely a discarded duplicate "
                f"Armature) and was removed")
        else:
            warnings.append(
                f"disabled armature modifier on '{mesh_name}' was forced ON "
                f"({', '.join(reasons)})")
    apply_transforms(arm)
    drop_shape_keys()
    # FBXにSpringBone情報は無い(PhysBone等はUnityコンポーネント側のため)
    spring_roots = [] if is_fbx else extract_spring_roots(arm)
    clear_bone_constraints(arm)
    meshes = drop_bone_meshes(arm, meshes, job.get("drop_bones", []), warnings)
    # 非スキンメッシュ(帽子・リボン等)の元の親ボーン名を、リネーム後の最終
    # メッシュ名(geo_XX)へ付け替えてmetaへ渡す。drop_bones等で消えたメッシュは
    # 自然に脱落する。値がNone(遡っても見つからない)のものは記録しない
    # (step02側はunskinned_source_boneに無ければ従来通りpelvis救済へ回る)。
    survivor_names = {o.name for o in meshes}
    unskinned_source_bone = {}
    for new_name, orig in orig_names.items():
        if new_name not in survivor_names:
            continue
        bone_name = source_parent_bone.get(orig)
        if bone_name:
            unskinned_source_bone[new_name] = bone_name
    if unskinned_source_bone:
        print(f"[{TAG}] unskinned source bone: {unskinned_source_bone}")

    if is_fbx:
        pal_map = vp_bl.humanoid_map_from_json(arm, humanoid_json, warnings)
        spec = "fbx+humanoid.json"
    else:
        pal_map, spec = vp_bl.humanoid_to_pal_map(arm)
    print(f"[{TAG}] VRM {spec}, humanoid mapped: {len(pal_map)} pal bones")
    for req in ("pelvis", "spine_01", "head", "upperarm_l", "upperarm_r",
                "hand_l", "hand_r", "thigh_l", "thigh_r", "foot_l", "foot_r"):
        if req not in pal_map:
            # dev#233: 内部pal_bone名(例: foot_l)はユーザーに意味が通じないため、
            # Unity側のConfigure Avatar上の表示名(例: Left Foot)+対処手順に変換して出す
            core.die(TAG, vp_bl.missing_humanoid_bone_message(req))
    if "clavicle_l" not in pal_map:
        warnings.append("no shoulder (clavicle) bone — the shoulder slider applies to the upper arm instead")

    # マテリアル/テクスチャの取得。優先順:
    #   1) Unityエクスポータのmaterial_map.json(FBX入力の本命。実際に着ている
    #      マテリアルの実テクスチャがレンダラー名×スロット番号で確定する)
    #   2) FBX/VRM内のマテリアルから推定(テクスチャはアバター周辺フォルダも捜索)
    avatar_dir = os.path.dirname(job["vrm_path"])
    map_path = os.path.join(avatar_dir, "material_map.json")
    if is_fbx and os.path.exists(map_path):
        slots = extract_materials_from_unity_map(
            meshes, orig_names, tex_dir, avatar_dir, map_path, warnings)
    else:
        search_dirs = [avatar_dir] + [os.path.join(avatar_dir, d)
                                      for d in sorted(os.listdir(avatar_dir))
                                      if os.path.isdir(os.path.join(avatar_dir, d))]
        slots = extract_materials(meshes, tex_dir, warnings, search_dirs)

    meta = {
        "spec_version": spec,
        "armature": arm.name,
        "meshes": [o.name for o in meshes],
        "pal_map": pal_map,
        "slots": slots,
        # 全ボーン一覧(drop_bones指定の参考用。上級者向け)
        "bones": [b.name for b in arm.data.bones],
        # VRM定義のSpringBoneルート(揺れ髪の自動対象。頭の子孫のみstep02が採用)
        "spring_roots": spring_roots,
        # 非スキンメッシュ(頂点グループ0。帽子・リボン等)の元の親ボーン名
        # {geo_XX: 実ボーン名}。step02のzero-weight rescueが、pal_mapの逆引き
        # (build_group_targets、祖先walk込み)でパルボーンへ解決して束縛する。
        # 見つからなかった/スキン済みのメッシュはキー自体が無い
        "unskinned_source_bone": unskinned_source_bone,
        "warnings": warnings,
    }
    with open(os.path.join(out_dir, "avatar_meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    out = os.path.join(out_dir, "step01_clean.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"[{TAG}] saved: {out}")
    for w in warnings:
        print(f"[{TAG}][WARN] {w}")


main()
