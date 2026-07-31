"""U4 T2: 多ボーン対応の全置換ビルド(本丸)。U7 T2で2セクション(マテリアル別)対応に拡張。

`build_topology_variant.py`(U3 T3、単一ボーン100%ウェイトのプリミティブ)を
土台に、`dump_avatar_mesh.py`(U4 T1)が書き出した実アバターメッシュ
(パルワールド骨格に複数ボーンでウェイト済み)へBronze001のLOD0を全置換する。

U3のT3手順との差分(指示書 docs/U4_SONNET_INSTRUCTIONS.md T2節):
  1. BoneMap: 使用ボーン集合(ウェイトに登場する全ボーン)をグローバル
     ボーン索引(load_refskelで名前引き)の昇順で並べたTArray<uint16>。
     skin_weightのボーン索引はこのBoneMap経由のローカル索引
  2. ActiveBoneIndices: 使用ボーン集合から再構成(昇順、BoneMapと同一集合)。
     RequiredBonesは元の全ボーンリストを不変維持(U3踏襲)
  3. skin_weight: T1ダンプの(ボーン名,重み)をencode_skin_weight()へ。
     重みはu8正規化(vp_meshrestore.encode_skin_weightが内部で実施)
  4. 頂点数65,535以下ならDataSize=2(16bit索引)のまま(toto/Female実測:
     32,015頂点。65,535を超える場合の32bit切替は本スクリプトでは未実装、
     TopoBuildError相当で明示的に停止する)
  5. (U4時点)セクションは1個に統合、MaterialIndexは旧Section0を流用。
     ColorVertexBufferは全頂点白固定

## U7 T2: マテリアル別2セクション分割(本丸)

T1(dump_avatar_mesh.py format=2)が三角形ごとに付与したmaterial(0=body/
1=parka)を使い、UEクックと同じ「セクションごとに連続した頂点範囲+
インデックス範囲」を再現する:
  - 三角形をmaterialでグループ化(0→Section0, 1→Section1、この順で
    MaterialIndexも0/1。テンプレートSKの慣習=Section0がMaterialIndex0と
    厳密一致、U2/U5実測通り)
  - 各セクションの使用頂点(グローバル頂点索引の集合)をソートして
    ローカル0..N-1へ再採番。**両セクションから参照される頂点は複製する**
    (UEクックと同じ挙動。toto側は頂点分割時のキーにobj.name(=1オブジェクト
    1マテリアル)を含むため実質複製が起きないが、alicia側はgeo_07/geo_08が
    複数マテリアル混在のため境界頂点で複製が発生しうる)
  - 新頂点配列は「Section0の頂点→Section1の頂点」の順に連結。
    IndexBufferの値はLOD全体を通した絶対頂点索引(セクションローカール
    ではない。BaseVertexIndexはあくまでセクション先頭のオフセット値)
  - BoneMap/ActiveBoneIndicesはセクションごとに「そのセクションが使う
    頂点だけが参照するボーン集合」で再構築(旧U4/U5の「メッシュ全体で
    1個のBoneMap」より狭い、UEの実際の設計により忠実)。
    ActiveBoneIndicesはLOD全体(=全セクションのBoneMapの和集合)
  - セクション単位のMaxBoneInfluencesは、そのセクションの頂点が実際に
    使う最大ウェイト数から算出(旧実装はバッファ全体の値をそのまま
    転用していたが、本来はセクションごとの実測値であるべき、
    docs/REPORT_U2_2026-07-22.md 4節の指摘に基づき是正)
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core  # noqa: E402
import vp_meshrestore as vm  # noqa: E402
import parse_sk_structure as sk  # noqa: E402
import parse_sk_full as skf  # noqa: E402
import parse_uasset_header as uh  # noqa: E402

HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, 'data')
OUT_DIR = os.path.join(HERE, 'out')
AVATAR_DIR = os.path.join(OUT_DIR, 'avatar')

MATERIAL_ORDER = (0, 1)  # Section0=material0(body)、Section1=material1(parka)


class AvatarBuildError(RuntimeError):
    pass


def load_dump(dump_path):
    with open(dump_path, encoding='utf-8') as f:
        return json.load(f)


def build_duplicated_vertices(sec_verts):
    """U8-T2: 位置一致(byte-exact, encode_position後)頂点をクラスタ化し、
    FDuplicatedVerticesBuffer.DupVertData/DupVertIndexDataを構築する。

    U8診断で判明: 従来実装は全セクションでDupVertData.Num()==0固定
    (「重複なし」規約)だったが、これは実機クラッシュ(D3D11Util.cpp:261
    CreateBuffer E_INVALIDARG)の直接原因だった。UE5.1フォーラム実測
    (forums.unrealengine.com "Duplicating skeletal mesh causes error
    without editor")によれば、`FSkeletalMeshLODRenderData::InitResources`
    に `if (bSkinCacheNeedsDuplicatedVertices) { check(DupVertData.Num()); }`
    という**セクションごとの非空要求**があり、GPU skin cacheが有効な限り
    bRecomputeTangentの値に関係なく全セクションで満たす必要がある
    (実測: pak_extract内の実60体/120セクション全数がdup_vert_count>0、
    従来ビルダー出力は全数0。docs/REPORT_U8参照)。

    UE本来の構築規約(セクション内、レンダー頂点分割後の位置一致=UVシーム/
    ハード法線の分割元)に倣い、同一position(エンコード後バイト完全一致)の
    頂点グループについて、各頂点のDupVertDataに「自分以外の同グループ全員」
    を列挙する。戻り値: (dup_vert_data: list[int](ローカル頂点索引),
    dup_vert_index: list[(length, index)]、長さ=len(sec_verts))。"""
    groups = {}
    for li, v in enumerate(sec_verts):
        key = vm.encode_position(*v['pos'])
        groups.setdefault(key, []).append(li)

    dup_vert_data = []
    dup_vert_index = [None] * len(sec_verts)
    for members in groups.values():
        if len(members) < 2:
            continue
        for li in members:
            others = [m for m in members if m != li]
            start = len(dup_vert_data)
            dup_vert_data.extend(others)
            dup_vert_index[li] = (len(others), start)
    for li in range(len(sec_verts)):
        if dup_vert_index[li] is None:
            dup_vert_index[li] = (0, 0)

    if not dup_vert_data:
        # 位置一致クラスタが1件も無い(理論上あり得るがtoto/alicia実測では
        # 未発生)場合の安全策: 頂点0の自己参照ダミーエントリを1件だけ入れ、
        # DupVertData.Num()>0を満たす(check()通過が目的、意味的には無害)。
        if sec_verts:
            dup_vert_data = [0]
            dup_vert_index[0] = (1, 0)

    return dup_vert_data, dup_vert_index


def pack_section(global_strip, class_strip, material_index, base_index, num_triangles,
                  base_vertex_index, bone_map, num_vertices, max_bone_influences,
                  dup_vert_data, dup_vert_index_data):
    """FSkelMeshRenderSectionのバイト列を組み立てる(U7版: BaseIndex/
    BaseVertexIndexが可変。build_topology_variant.pack_section(U3、単一
    セクション=常に0固定)から分岐した新規実装)。

    U8-T2: DVBは`build_duplicated_vertices()`が実測した位置一致クラスタを
    書く(U4〜U7の「重複なし」固定規約から是正。詳細は同関数のdocstring)。"""
    if len(dup_vert_index_data) != num_vertices:
        raise AvatarBuildError(
            f"dup_vert_index_data length ({len(dup_vert_index_data)}) does not match "
            f"num_vertices ({num_vertices})")
    out = bytearray()
    out += bytes([global_strip, class_strip])
    out += struct.pack('<H', material_index)
    out += struct.pack('<I', base_index)
    out += struct.pack('<I', num_triangles)
    out += struct.pack('<I', 0)              # bRecomputeTangent
    out += bytes([3])                        # RecomputeTangentsVertexMaskChannel = None
    out += struct.pack('<I', 1)              # bCastShadow
    out += struct.pack('<I', 1)              # bVisibleInRayTracing
    out += struct.pack('<I', base_vertex_index)
    out += struct.pack('<i', 0)              # ClothMappingDataLODs count
    out += struct.pack('<i', len(bone_map))
    out += struct.pack(f'<{len(bone_map)}H', *bone_map)
    out += struct.pack('<I', num_vertices)
    out += struct.pack('<i', max_bone_influences)
    out += struct.pack('<h', -1)             # CorrespondClothAssetIndex
    out += b'\x00' * 16                      # ClothingData FGuid
    out += struct.pack('<i', -1)             # AssetLodIndex
    out += struct.pack('<i', len(dup_vert_data))    # DVB.DupVertData count
    out += struct.pack(f'<{len(dup_vert_data)}I', *dup_vert_data)
    out += struct.pack('<i', num_vertices)   # DVB.DupVertIndexData count(=NumVertices)
    for length, index in dup_vert_index_data:
        out += struct.pack('<ii', length, index)
    out += struct.pack('<I', 0)              # bDisabled
    return bytes(out)


# --------------------------------------------------------------------------
# U21: RefSkeletonバインドポーズ位置パッチ(指の破裂状変形の根治)
#
# 診断(docs/DEV_NOTES.md先頭のU21節、2026-07-24): noueパイプラインは
# テンプレートSKのRefSkeleton(FTransform、cookedバインドポーズ)をverbatim
# コピーするのみで、pipeline/blender/step02_retarget.pyのchibi_fit_armature()
# が計算した「アバターに実際にフィットした関節位置」を一切反映しない。
# メッシュ頂点(スキンウェイト対象)はchibi-fit後の配置基準で作られるため、
# 両者が数cm単位でズレ、短い指ボーンで致命的な破裂状変形になる
# (PalMod HANDOFF.md 不具合③と同型)。
#
# chibi_fit_armature()は「向き(回転)は変えず位置のみ」移動する設計
# (step02_retarget.pyのdocstring参照、U21診断のFK往復検証で数値確認済み:
# テンプレートのquatだけを使ったFK合成→逆分解で誤差1e-13cm未満の完全往復)
# なので、回転・スケールはテンプレート値のまま使い回し、位置のみを
# chibi-fit後の値へ差し替えればよい。

def _quat_mul(a, b):
    """UE FTransformの回転合成(親→子、a=親クォータニオン、b=子ローカル)。"""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _quat_conj(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def _quat_rotate(q, v):
    """単位クォータニオンqでベクトルvを回転する(v' = q*v*q^-1)。"""
    x, y, z, w = q
    vx, vy, vz = v
    uvx = y * vz - z * vy
    uvy = z * vx - x * vz
    uvz = x * vy - y * vx
    uuvx = y * uvz - z * uvy
    uuvy = z * uvx - x * uvz
    uuvz = x * uvy - y * uvx
    return (
        vx + 2.0 * (w * uvx + uuvx),
        vy + 2.0 * (w * uvy + uuvy),
        vz + 2.0 * (w * uvz + uuvz),
    )


def compute_component_transforms(bones):
    """bones: {name: {parent, quat, pos, scale}}(vp_core.load_refskel形式、
    親→子の順で並んでいる前提)から、各ボーンのコンポーネント空間(=UEの
    ワールド/骨格ルート基準)の(回転, 位置)を前方運動学で計算して返す。
    戻り値: (comp_rot: {name: quat}, comp_pos: {name: (x,y,z)})。"""
    comp_rot = {}
    comp_pos = {}
    for name, b in bones.items():
        parent = b['parent']
        if parent is None:
            comp_rot[name] = tuple(b['quat'])
            comp_pos[name] = tuple(b['pos'])
        else:
            pr = comp_rot[parent]
            pp = comp_pos[parent]
            comp_rot[name] = _quat_mul(pr, tuple(b['quat']))
            rv = _quat_rotate(pr, b['pos'])
            comp_pos[name] = (pp[0] + rv[0], pp[1] + rv[1], pp[2] + rv[2])
    return comp_rot, comp_pos


def compute_patched_local_positions(bones, avatar_world_pos):
    """avatar_world_pos: {bone_name: (x,y,z)}(chibi-fit後のpal_arm各ボーンの
    ワールド位置、UEコンポーネント空間、pipeline/blender/step02_retarget.pyの
    chibi_bone_world_head_*.json)から、RefSkeletonに書き戻すべき新しい
    ローカル位置を計算する。

    avatar_world_posに存在しないボーンは対象外(戻り値に含めない)。
    これは手抜きではなく数学的に不要: そのボーンの新規ローカル位置は
    「新しい親位置に対して元と同じローカルオフセットを保つ」と定義される
    ため、元のFTransform.pos(テンプレート値)と厳密に一致する
    (回転は不変という前提の下で自明。U21診断で検証済み)。
    そのため書き換えを要するのはavatar_world_posに明示的に含まれる
    ボーンだけでよい。"""
    template_comp_rot, template_comp_pos = compute_component_transforms(bones)
    new_comp_pos = {}
    patched = {}
    for name, b in bones.items():
        parent = b['parent']
        if name in avatar_world_pos:
            new_comp_pos[name] = tuple(avatar_world_pos[name])
        elif parent is None:
            new_comp_pos[name] = template_comp_pos[name]
        else:
            pr = template_comp_rot[parent]
            rv = _quat_rotate(pr, b['pos'])
            pp = new_comp_pos[parent]
            new_comp_pos[name] = (pp[0] + rv[0], pp[1] + rv[1], pp[2] + rv[2])

        if name not in avatar_world_pos:
            continue
        if parent is None:
            patched[name] = new_comp_pos[name]
        else:
            pr = template_comp_rot[parent]
            pp = new_comp_pos[parent]
            diff = (new_comp_pos[name][0] - pp[0],
                    new_comp_pos[name][1] - pp[1],
                    new_comp_pos[name][2] - pp[2])
            patched[name] = _quat_rotate(_quat_conj(pr), diff)
    return patched


def load_chibi_bone_world_head(dump):
    """dumpに対応するchibi_bone_world_head_{gender}.json
    (pipeline/blender/step02_retarget.pyがU21で新規出力するようになった、
    chibi-fit後の全ボーンworld位置)を探して読む。見つからない場合はNoneを
    返す(古いdump/未対応ジョブ向けの後方互換フォールバック。RefSkeleton
    パッチを単純にスキップし、従来通りverbatimコピーのみになる=
    リグレッションではなく現状維持)。

    探索順序:
      1. dump['_job_converted_dir'](build_pak_from_avatar.pyがjob.jsonの
         場所から直接解決して渡す、最も確実。U21初回実装は次のsource_blend
         方式のみで、UVアトラス焼き込み後のblendが別ディレクトリ
         (build/atlas/)に置かれるため常に見つからずサイレントno-opに
         なっていたバグの修正)
      2. dump['source_blend']のdirname直下(後方互換。build_pak_from_avatar.py
         を経由しない直接呼び出し(build_avatar_variant.py単体実行や
         verify_avatar_decode_sections_all.py等)では_job_converted_dirが
         無いため、こちらにフォールバックする)
    """
    gender = dump.get('gender')
    if not gender:
        return None
    candidates = []
    job_conv = dump.get('_job_converted_dir')
    if job_conv:
        candidates.append(os.path.join(job_conv, f"chibi_bone_world_head_{gender.lower()}.json"))
    src = dump.get('source_blend')
    if src:
        candidates.append(os.path.join(os.path.dirname(src),
                                       f"chibi_bone_world_head_{gender.lower()}.json"))
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                raw = json.load(f)
            return {k: tuple(v) for k, v in raw.items()}
    return None


def patch_refskeleton_positions(data, uexp_path, uasset_path, bones, avatar_world_pos):
    """dataの中のRefSkeleton FTransform配列(位置成分のみ)を、
    compute_patched_local_positions()の結果でその場パッチする。
    dataは同一サイズのまま(バイト数不変、オフセット調整不要)。
    avatar_world_posがNone(chibi_bone_world_head_*.json未検出)の場合は
    何もせずdataをそのまま返す。"""
    if avatar_world_pos is None:
        return data
    names = vp_core.read_names(uasset_path)
    raw_bones, transforms, tsize, _data, tpos = vp_core.find_refskeleton(
        uexp_path, names, with_offset=True)
    bone_index = {raw_bones[i][0]: i for i in range(len(raw_bones))}
    elemsize = tsize // 10
    fmt3 = '<3d' if elemsize == 8 else '<3f'

    patched = compute_patched_local_positions(bones, avatar_world_pos)
    out = bytearray(data)
    n_patched = 0
    for name, pos in patched.items():
        i = bone_index.get(name)
        if i is None:
            continue  # avatar_world_posにあってもRefSkeleton側に無いボーン(髪等)は対象外
        off = tpos + i * tsize + 4 * elemsize  # quat(4要素)の直後がpos(3要素)
        struct.pack_into(fmt3, out, off, *pos)
        n_patched += 1
    print(f"[build_avatar_variant] U21 RefSkeleton bind-pose position patch: "
          f"{n_patched}/{len(patched)} bones (matched to post-chibi-fit values)")
    return bytes(out)


# --------------------------------------------------------------------------
# dev#157 / WP-I157(2026-07-30): サイズ可変(スケルトン一様スケール)。
#
# 方式: RefSkeletonの各ボーンのローカルTranslation(FTransform.pos)を、
# root(親を持たない1件)を除く全ボーンについてk倍する(回転・スケール成分は
# 不変)。回転を保ったまま子のローカル並進だけをk倍すると、コンポーネント
# 空間(=ワールド)での関節間距離が一様にk倍になり、頂点バッファ自体
# (スキンウェイト対象)は無改変のまま、GPU skinningが再計算する結果として
# アバター全体が一様スケールされる(UEのスケルタルメッシュはボーン
# Scale3Dでの均一拡大がスキニングへ正しく伝播しない実装であるため、
# Translationスケールで代替する — issue dev#157本文の記述どおり)。
# root自身のTranslationは書き換えない(「root不動点」)。
#
# 本パッチはU21パッチ(chibi-fit位置反映)の**直後**に適用する。U21適用後の
# `data`を読み書きするため、U21がバインドポーズを実測値へ差し替えた場合は
# その差し替え後の値がk倍される(chibi-fit値とスケール値の二重管理を避ける
# ための順序)。
#
# k=1.0のときは何もバイトを書かずdataをそのまま返す(早期return)。これにより
# 既定(uniform_scale未指定/1.0)ではpakバイトが完全不変になることが構造的に
# 保証される(WP-I157受入ゲート「k=1.0でpak SHA256が現行と完全一致」)。
# 詳細: work\issue_zero\i157\NOTES.md(再特定の経緯を含む)。

def apply_uniform_scale(data, uexp_path, uasset_path, k):
    """dataの中のRefSkeleton FTransform配列(位置成分のみ)を、root以外の
    全ボーンについてk倍する。k==1.0なら無改変でdataをそのまま返す
    (バイト単位で早期return、丸めではない厳密no-op)。

    patch_refskeleton_positions()と違い、bones(vp_core.load_refskel()の
    name->{parent,...}辞書)は受け取らない: root判定はraw_bones(uexp_path
    から都度再パースするインデックスベースの生リスト、find_refskeleton()の
    戻り値)のparent_idx==-1だけで足り、名前引きが不要なため
    (名前重複があってもインデックスは常に一意)。"""
    if k == 1.0:
        return data
    names = vp_core.read_names(uasset_path)
    raw_bones, transforms, tsize, _data, tpos = vp_core.find_refskeleton(
        uexp_path, names, with_offset=True)
    elemsize = tsize // 10
    fmt3 = '<3d' if elemsize == 8 else '<3f'

    out = bytearray(data)
    n_scaled = 0
    n_root = 0
    for i, (_name, parent) in enumerate(raw_bones):
        if parent == -1:
            n_root += 1
            continue  # root不動点: Translationを書き換えない
        off = tpos + i * tsize + 4 * elemsize  # quat(4要素)の直後がpos(3要素)
        x, y, z = struct.unpack_from(fmt3, out, off)
        struct.pack_into(fmt3, out, off, x * k, y * k, z * k)
        n_scaled += 1
    print(f"[build_avatar_variant] dev#157 uniform scale patch: k={k} "
          f"{n_scaled} bone(s) scaled, {n_root} root bone(s) left fixed "
          f"(of {len(raw_bones)} total)")
    return bytes(out)


def build_uexp_variant(uexp_path, uasset_path, dump):
    with open(uexp_path, 'rb') as f:
        data = f.read()
    s = sk.parse_sk_structure(uexp_path, uasset_path)
    full = skf.parse_sk_full(uexp_path, uasset_path)
    tail = full['lods'][0]['tail']
    lookup = tail['lookup_vertex_buffer']
    color = tail['color_vertex_buffer']

    # U26実測(docs\REPORT_U26_2026-07-24.md): 真のバニラ衣装SKの一部
    # (実測: SK_Player_Female_Outfit_OldCloth001)は、本体SkeletalMesh exportの
    # *後ろに*さらに補助export(Outer=本体、70byte)を1件持つ。本関数は従来
    # 「本体exportの終端(full['export_end'])=uexpファイルの実質末尾(package tag
    # 直前)」を前提に出力を組み立てていたため、この末尾補助exportのバイト列を
    # 無言で切り捨て、かつbuild_uasset_variant()側もそのexportのSerialOffsetを
    # 更新しないまま放置していた(=本体サイズが変わった後、旧オフセットが新しい
    # 頂点/ウェイトバイト列の**内部**を指す状態になる。エンジンがそのexportを
    # 実際にpreloadする際、無関係なメッシュバイトを当該オブジェクトのプロパティ
    # として誤ってデシリアライズすることになる)。ここでその末尾バイト列を
    # verbatimで保存し、出力の末尾(package tag直前)へ復元する。旧コーパス
    # (末尾補助exportなし)ではtrailing_bytes==b''でno-op、後方互換。
    trailing_bytes = data[full['export_end']:len(data) - 4]
    # U18実測: 真のバニラ衣装SK(docs\REPORT_U18_2026-07-23.md参照)は
    # Owner->GetHasVertexColors()がfalseの個体が多数あり(UE5.1ソース
    # SkeletalMeshLODRenderData.cpp SerializeStreamedData: `if (Owner &&
    # Owner->GetHasVertexColors()) { ColorVertexBuffer.Serialize(...); }`
    # ——このboolはストリーム内に出現せず「不透明ヘッダ」領域(本パーサ未解析、
    # out側もverbatimコピーする箇所)にある既存プロパティなので、有無は
    # ColorVertexBufferの実バイト有無で判定するしかない)、この場合は
    # ColorVertexBuffer自体が丸ごと存在しない(旧コーパスは全数存在で
    # 前提が違った)。存在しない個体には出力側でも書かない(=元のHasVertexColors
    # フラグは不透明ヘッダのverbatimコピーでそのまま維持されるため、
    # 読み手には整合する)。

    bones = vp_core.load_refskel(uasset_path)
    bone_names = list(bones.keys())

    # U21: RefSkeletonバインドポーズ位置をchibi-fit後の値へパッチ(指の破裂状
    # 変形の根治、本ファイル冒頭のコメント参照)。dump未対応(古いdump/
    # chibi_bone_world_head_*.json未検出)なら何もせずverbatimのまま。
    avatar_world_pos = load_chibi_bone_world_head(dump)
    data = patch_refskeleton_positions(data, uexp_path, uasset_path, bones, avatar_world_pos)

    # dev#157 / WP-I157: サイズ可変(スケルトン一様スケール)。U21位置パッチの
    # 直後に適用する(上のapply_uniform_scaleのdocstring参照)。
    # dump未指定(uniform_scaleキー無し)/1.0なら無改変(既定挙動と不変)。
    uniform_scale = dump.get('uniform_scale', 1.0)
    data = apply_uniform_scale(data, uexp_path, uasset_path, uniform_scale)

    if dump.get('format') != 2:
        raise AvatarBuildError(
            f"dump format=2 (with material) is required (actual={dump.get('format')}). "
            "Regenerate with dump_avatar_mesh.py (T1)")

    verts = dump['vertices']
    tris = dump['triangles']  # [i0, i1, i2, material]

    # U50-single(2026-07-25): 単一マテリアル化により dump_avatar_mesh.py の
    # classify_material() は常に0を返す。よって三角形は全て material=0 に入る。
    # 旧「material=0/1 の両方が必要 / 片方が空なら複製して救済」という分岐は
    # 2セクション構成のための措置であり、単一セクションになった今は不要
    # (削除済み)。material=1 が残っている入力(旧ダンプの再利用等)も
    # 幾何を落とさないよう material=0 へ畳んで受け入れる。
    tris_by_mat = {0: [], 1: []}
    for t in tris:
        if len(t) != 4:
            raise AvatarBuildError(f"triangle does not have 4 elements with material: {t}")
        m = t[3]
        if m not in (0, 1):
            raise AvatarBuildError(f"unsupported material value: {m}")
        tris_by_mat[m].append(t[:3])
    if tris_by_mat[1]:
        print(f"[build_avatar_variant] Note: folding {len(tris_by_mat[1])} material=1 "
              "triangle(s) into material=0 (U50-single: single-material layout)")
        tris_by_mat[0] += tris_by_mat[1]
        tris_by_mat[1] = []
    if not tris_by_mat[0]:
        raise AvatarBuildError("0 triangles")

    r0 = vp_core.parse_skeletalmesh_buffers(data)
    max_bone_influences = r0['skin_weight']['max_bone_influences']  # 物理stride計算用(バッファ全体値)
    numtexcoords = r0['uv']['num_tex_coords']

    # U18実測: 真のバニラ衣装SK(docs\REPORT_U18_2026-07-23.md参照)はMaxBoneInfluences=4の
    # 個体が多数あり(旧コーパス=recookされた副産物は常に8で、dump側のBlender出力上限
    # (dump_avatar_mesh.pyが常に8を書く)と偶然一致していただけ)。この等値チェックは
    # 実は安全上不要: 実際のエンコードはencode_skin_weight(max_influences=
    # max_bone_influences)で常にファイル側の値へ切り詰め・再正規化する(強い順に選び
    # 残りは重み0でパディング)ため、dump側が8でファイル側が4でも正しく動作する。
    # 情報ログにのみ残し、致命エラーにはしない。
    dump_max_inf = dump.get('max_influences')
    if dump_max_inf is not None and dump_max_inf != max_bone_influences:
        print(f"[build_avatar_variant] Note: dump max_influences ({dump_max_inf}) does not "
              f"match the source file's MaxBoneInfluences ({max_bone_influences}) "
              "(harmless: encoding truncates to the file-side value)")

    # U18実測: 真のバニラ衣装SK(docs\REPORT_U18_2026-07-23.md参照)は、MaterialIndex
    # 0/1(body/parka相当)以外に2〜4番目のマテリアルスロット(ボタン等の装飾パーツ、
    # 旧コーパス=recookされた副産物には無かった)を追加で持つ個体がある(例:
    # Cloth001=4セクション、Plastic002=5セクション)。本ビルダーはアバター側が
    # 常に2マテリアル(m00 body/m01 parka)のみを提供する設計(docs\TODO.mdの
    # 「テクスチャスロット2枚固定」の制約、既知・別課題)のため、テンプレート側の
    # セクション総数に関わらず「MaterialIndex==0の1件」「MaterialIndex==1の1件」を
    # それぞれ探して使い、それ以外(2番以降)のセクションは出力に含めない
    # (=そのマテリアルスロットは避けられている、旧2セクション専用テンプレートでは
    # 従来通りsections[0]/[1]がそのままMaterialIndex0/1に一致するため後方互換)。
    sections_by_material = {}
    for sec in s['sections']:
        sections_by_material.setdefault(sec['material_index'], sec)

    if 0 not in sections_by_material:
        raise AvatarBuildError(
            f"Template SK has no MaterialIndex=[0] section "
            f"(actual MaterialIndex set={sorted(sections_by_material)}). "
            "This builder requires a MaterialIndex 0 (body) section")
    # U50-single(2026-07-25): **常にMaterialIndex=0の1セクションだけ**を出力する。
    # 全MIが同一マテリアル(Base Texture=t00)になったので、セクションを分ける
    # 意味が無くなった。テンプレート側がMaterialIndex=1以降を持っていても
    # 使わない(そのスロットは描画されない)。
    # これにより「テンプレが1セクションしか持たない(Kigurumi001)」も
    # 「アバターが単一マテリアル(Sherbi)」も特別扱いが要らなくなり、
    # 旧2分岐(片方欠けたら複製/統合)は削除した。
    output_plan = [(0, (0, 1), sections_by_material[0])]

    # --- マテリアル別にセクションを構築(頂点再採番+境界頂点の複製) ---
    sections_data = []
    base_vertex_index = 0
    base_index = 0
    for i, (m, avatar_mats, old_sec) in enumerate(output_plan):
        sec_tris_all = [t for am in avatar_mats for t in tris_by_mat[am]]
        used_globals = sorted({gi for t in sec_tris_all for gi in t})
        local_map = {g: li for li, g in enumerate(used_globals)}
        sec_verts = [verts[g] for g in used_globals]
        sec_tris_local = [[local_map[g] for g in t] for t in sec_tris_all]

        used_names = set()
        for v in sec_verts:
            for name, w in v['weights']:
                if w > 0:
                    used_names.add(name)
        unknown = used_names - set(bone_names)
        if unknown:
            raise AvatarBuildError(f"bone name(s) not present in RefSkeleton: {sorted(unknown)}")
        bone_map = sorted(bone_names.index(n) for n in used_names)
        if len(bone_map) > 65535:
            raise AvatarBuildError(f"section {i} uses more bones than the limit: {len(bone_map)}")
        name_to_local = {bone_names[gi]: li for li, gi in enumerate(bone_map)}

        sec_max_inf = max(
            (sum(1 for _, w in v['weights'] if w > 0) for v in sec_verts), default=1)
        sec_max_inf = max(sec_max_inf, 1)

        sections_data.append({
            'material': m,
            'verts': sec_verts,
            'used_globals': used_globals,
            'tris_local': sec_tris_local,
            'bone_map': bone_map,
            'name_to_local': name_to_local,
            'base_vertex_index': base_vertex_index,
            'base_index': base_index,
            'num_vertices': len(sec_verts),
            'num_triangles': len(sec_tris_local),
            'max_bone_influences_section': sec_max_inf,
            'global_strip_flags': old_sec['global_strip_flags'],
            'class_strip_flags': old_sec['class_strip_flags'],
        })
        base_vertex_index += len(sec_verts)
        base_index += len(sec_tris_local) * 3

    numv = base_vertex_index
    num_tri = sum(sec['num_triangles'] for sec in sections_data)
    # U7 T3(ストレッチ): 65,535頂点超は32bit索引(DataSize=4)へ切替。
    # UE5.1ソース調査(SkinWeightVertexBuffer.cpp/MultiSizeIndexContainer.cpp)で
    # 確認済み: bUse16BitBoneIndexはSkinWeightVertexBufferの「ボーン索引」自体の
    # 幅を制御するフラグでありIndexBuffer(頂点索引)のDataSizeとは無関係。
    # IndexBufferはDataSizeバイトを自己記述するプレーンなTArray(FMultiSizeIndexContainer)
    # であり、頂点数が65,535を超える場合にDataSize=4(uint32)で書けば
    # 読み手(vp_core._find_sk_index_buffer、UE本体とも)は無改造でそのまま読める
    idx_data_size = 4 if numv > 65535 else 2

    all_verts_in_order = []
    for sec in sections_data:
        all_verts_in_order.extend(sec['verts'])

    # --- 新規4バッファのバイト列を構築(セクション0→1の順で連結) ---
    pos_bytes = b''.join(vm.encode_position(*v['pos']) for v in all_verts_in_order)
    tang_bytes = b''.join(
        vm.encode_tangent_pair(v['normal'], v['tangent'], v['bitangent_sign'])
        for v in all_verts_in_order)
    uv_bytes = b''.join(vm.encode_uv0(*v['uv']) * numtexcoords for v in all_verts_in_order)
    sw_bytes = b''.join(
        vm.encode_skin_weight([(n, w) for n, w in v['weights']], sec['name_to_local'],
                               max_influences=max_bone_influences)
        for sec in sections_data for v in sec['verts'])
    color_bytes = (b'\xff\xff\xff\xff') * numv if color is not None else b''

    # --- セクション(2本、BaseIndex/BaseVertexIndexがセクションごとに可変) ---
    # U8-T2: セクションごとに位置一致クラスタからDVBを実測構築(重複なし固定規約から是正)
    dvb_by_section = [build_duplicated_vertices(sec['verts']) for sec in sections_data]
    section_bytes = b''.join(
        pack_section(
            global_strip=sec['global_strip_flags'], class_strip=sec['class_strip_flags'],
            material_index=sec['material'], base_index=sec['base_index'],
            num_triangles=sec['num_triangles'], base_vertex_index=sec['base_vertex_index'],
            bone_map=sec['bone_map'], num_vertices=sec['num_vertices'],
            max_bone_influences=sec['max_bone_influences_section'],
            dup_vert_data=dvb[0], dup_vert_index_data=dvb[1])
        for sec, dvb in zip(sections_data, dvb_by_section))

    # --- IndexBuffer(セクション順、値はLOD全体を通した絶対頂点索引) ---
    flat_idx = []
    for sec in sections_data:
        base = sec['base_vertex_index']
        for t in sec['tris_local']:
            flat_idx.extend(v + base for v in t)
    idx_count = len(flat_idx)
    idx_elem_fmt = 'I' if idx_data_size == 4 else 'H'
    idx_bytes = (bytes([idx_data_size]) + struct.pack('<ii', idx_data_size, idx_count)
                 + struct.pack(f'<{idx_count}{idx_elem_fmt}', *flat_idx))

    # --- Positionヘッダ+データ ---
    pos_block = struct.pack('<iiii', 12, numv, 12, numv) + pos_bytes

    # --- StaticMeshVertexBufferヘッダ(strip2B+NumTexCoords+NumVertices+bFull+bHQ)+Tangent+UV ---
    old_p = r0['position']['offset'] + r0['position']['size']
    smvb_strip = data[old_p:old_p + 2]
    bfull, bhq = struct.unpack_from('<ii', data, old_p + 10)
    smvb_header = smvb_strip + struct.pack('<ii', numtexcoords, numv) + struct.pack('<ii', bfull, bhq)
    tang_block = struct.pack('<ii', r0['tangent']['stride'], numv) + tang_bytes
    uv_block = struct.pack('<ii', r0['uv']['item_stride'], numv * numtexcoords) + uv_bytes

    # --- SkinWeightヘッダ(strip2B+bvar+maxinf+NumBones+numv+buse16)+データ ---
    # U26実測(docs\REPORT_U26_2026-07-24.md、UE5.1エンジンソース
    # Engine\Source\Runtime\Engine\Private\Rendering\SkinWeightVertexBuffer.cpp
    # SerializeMetaData()/CreateRHIBuffer_Internal()で確認): このフィールド名は
    # 「NumBones」だが実体はスキンウェイトデータバッファの総要素数
    # (=MaxBoneInfluences*NumVertices、同ファイル348行目
    # `NumBones = MaxBoneInfluences * NumVertices;`)であり、ボーン数ではない。
    # 旧実装はテンプレート側の値をverbatimコピーしていたが、注入後は頂点数が
    # テンプレートと異なるため値が実データと食い違う(T1診断
    # devtools\u26_static_check.pyでheon全60ファイル中60/60が不一致と実測)。
    # 新規頂点数に対して都度再計算する。
    old_q = r0['uv']['offset'] + r0['uv']['size']
    sw_strip = data[old_q:old_q + 2]
    bvar, _maxinf_old, _numbones_old, _numv_old, buse16 = struct.unpack_from('<iiiii', data, old_q + 2)
    if bvar or buse16:
        raise AvatarBuildError("source file uses bVariableBonesPerVertex/bUse16BitBoneIndex (unsupported format)")
    numbones = max_bone_influences * numv
    sw_header = sw_strip + struct.pack('<iiiii', bvar, max_bone_influences, numbones, numv, buse16)
    sw_block = struct.pack('<ii', 1, numv * 2 * max_bone_influences) + sw_bytes

    # --- LookupVertexBuffer(T1確定の固定パターン、元バイトをそのまま流用) ---
    lookup_block = data[lookup['start']:lookup['end']]

    # --- ColorVertexBuffer(strip2B+Stride+NumVertices+ElemSize+Count+データ) ---
    # U18実測: HasVertexColors()=falseの個体はこのSerialize呼び出し自体が
    # UE側でスキップされ、ストリームに1バイトも出現しない(parse_color_vertex_buffer
    # がcolor=Noneかつ0バイト消費で返しているのと対称)。出力側も同様に
    # 0バイトのブロックとして扱う(strip等のヘッダも一切書かない)。
    if color is not None:
        color_strip = data[color['start']:color['start'] + 2]
        color_block = (color_strip + struct.pack('<i', color['stride']) + struct.pack('<i', numv)
                       + struct.pack('<i', color['bulk_elemsize']) + struct.pack('<i', numv) + color_bytes)
    else:
        color_block = b''

    streamed_strip = data[s['streamed_strip_offset']:s['streamed_strip_offset'] + 2]
    streamed_body = (idx_bytes + pos_block + smvb_header + tang_block + uv_block
                      + sw_header + sw_block + lookup_block + color_block
                      + struct.pack('<i', 0)   # SkinWeightProfilesData count=0
                      + struct.pack('<i', 0)   # SourceRayTracingGeometry.RawData count=0
                      + struct.pack('<i', 0))  # bSerializeCompressedMorphTargets=False
    buffers_size = len(streamed_strip) + len(streamed_body)

    # --- ActiveBoneIndices: 全セクションのBoneMapの和集合(LOD全体) ---
    active_bone_set = set()
    for sec in sections_data:
        active_bone_set.update(sec['bone_map'])
    active_bone_indices = sorted(active_bone_set)
    active_bone_indices_bytes = (
        struct.pack('<i', len(active_bone_indices))
        + struct.pack(f'<{len(active_bone_indices)}H', *active_bone_indices))

    out = bytearray()
    out += data[0:s['render_sections_count_offset']]      # 不変ヘッダ全域(頭ブロック+Bounds/Materials/RefSkeleton+RequiredBones)
    out += struct.pack('<i', len(sections_data))            # RenderSections count = 2
    out += section_bytes
    out += active_bone_indices_bytes
    out += struct.pack('<I', buffers_size)
    out += streamed_strip
    out += streamed_body
    out += bytes([1, 1])                                    # NumInlinedLODs, NumNonOptionalLODs (uint8 x2)
    out += struct.pack('<i', 0)                              # DummyObjs count = 0
    out += trailing_bytes                                    # U26: 末尾補助export(あれば)をverbatim復元
    out += struct.pack('<I', 0x9E2A83C1)                      # パッケージ終端タグ(SerialSizeに含まれない)

    info = {
        'old_size': len(data), 'new_size': len(out), 'num_vertices': numv,
        'num_triangles': num_tri, 'buffers_size': buffers_size,
        'max_bone_influences': max_bone_influences,
        'index_data_size': idx_data_size,
        'trailing_bytes_len': len(trailing_bytes),
        'num_sections': len(sections_data),
        'section_material_indices': [sec['material'] for sec in sections_data],
        'section_triangle_counts': [sec['num_triangles'] for sec in sections_data],
        'section_vertex_counts': [sec['num_vertices'] for sec in sections_data],
        'section_bone_map_sizes': [len(sec['bone_map']) for sec in sections_data],
        'section_dvb_dup_vert_counts': [len(dvb[0]) for dvb in dvb_by_section],
        'active_bone_indices': active_bone_indices,
        # G2デコード検証(verify_avatar_decode_sections.py)向け: 出力頂点バッファの
        # i番目が元ダンプのどの頂点(global index)の複製かを追跡できる情報。
        'vertex_source_indices': [g for sec in sections_data for g in sec['used_globals']],
        'section_ranges': [
            {'base_vertex_index': sec['base_vertex_index'], 'num_vertices': sec['num_vertices'],
             'bone_map': sec['bone_map']}
            for sec in sections_data],
    }
    return bytes(out), info


def build_uasset_variant(uasset_path, new_uexp_size):
    """本体(SkeletalMesh)exportのSerialSizeを新しいuexpサイズに合わせて書き換える。

    U18実測: 真のバニラ衣装SK(docs\\REPORT_U18_2026-07-23.md参照)は
    UMorphTarget等の小さな補助export(bIsAsset=False)を複数持ち、ExportCount>1に
    なる(旧コーパスはExportCount=1固定という前提)。補助exportの大半は本体export
    より*前*に位置し(実測: uexpファイル先頭からprefixバイト分)、
    build_uexp_variant()側でその領域は不変(verbatimコピー)のまま出力されるため、
    prefix自体のサイズは変わらない。

    U26実測(docs\\REPORT_U26_2026-07-24.md): 一部ファイル(実測:
    SK_Player_Female_Outfit_OldCloth001)は補助exportが本体export**より後**にも
    存在する(Outer=本体、70byte)。この末尾補助export(群)は
    build_uexp_variant()が末尾にverbatim復元するため実データは保存されるが、
    本体のSerialSize計算・当該exportのSerialOffsetの両方をここで正しく
    再計算しないと、本体が大きくなった分だけ末尾exportの位置がズレる
    (=無関係なメッシュバイトを誤った位置から読む)。本体exportのSerialSizeは
    (新uexpサイズ - prefix - 末尾補助exportの合計バイト数 - 4(末尾タグ))へ、
    末尾補助export(群)のSerialOffsetは(本体の新旧SerialSize差分)だけ後方へ
    シフトして書き換える。末尾補助exportが無い旧コーパス(trailing=[])では
    trailing_len=0でno-op、既存の式と完全に一致する(後方互換)。"""
    with open(uasset_path, 'rb') as f:
        data = f.read()
    _, exports = uh.parse_uasset_exports(uasset_path)
    asset_exports = [e for e in exports if e['b_is_asset']]
    if len(asset_exports) != 1:
        raise AvatarBuildError(
            f"bIsAsset=True export is not unique: {len(asset_exports)} found "
            f"(total ExportCount={len(exports)})")
    export = asset_exports[0]
    prefix = export['serial_offset'] - len(data)
    if prefix < 0:
        raise AvatarBuildError(
            f"main export's SerialOffset ({export['serial_offset']}) is less than "
            f"the uasset size ({len(data)})")

    main_abs_end = export['serial_offset'] + export['serial_size']
    trailing = [e for e in exports if e is not export and e['serial_offset'] >= main_abs_end]
    trailing_len = sum(e['serial_size'] for e in trailing)

    new_serial_size = new_uexp_size - prefix - trailing_len - 4
    out = bytearray(data)
    struct.pack_into('<q', out, export['serial_size_offset'], new_serial_size)

    delta = new_serial_size - export['serial_size']
    for e in trailing:
        offset_field_pos = e['serial_size_offset'] + 8  # SerialOffsetはSerialSizeの直後8byte
        struct.pack_into('<q', out, offset_field_pos, e['serial_offset'] + delta)

    return bytes(out), {'new_serial_size': new_serial_size, 'prefix': prefix,
                         'trailing_export_count': len(trailing), 'trailing_len': trailing_len}


if __name__ == '__main__':
    dump_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        OUT_DIR, 't1_dump_v2', 'avatar_female.json')

    uexp = os.path.join(DATA_DIR, 'SK_Player_Female_Outfit_Bronze001.uexp')
    uasset = os.path.join(DATA_DIR, 'SK_Player_Female_Outfit_Bronze001.uasset')
    out_uexp = os.path.join(AVATAR_DIR, 'SK_Player_Female_Outfit_Bronze001.uexp')
    out_uasset = os.path.join(AVATAR_DIR, 'SK_Player_Female_Outfit_Bronze001.uasset')
    os.makedirs(AVATAR_DIR, exist_ok=True)

    dump = load_dump(dump_path)
    new_uexp, info = build_uexp_variant(uexp, uasset, dump)
    with open(out_uexp, 'wb') as f:
        f.write(new_uexp)
    new_uasset, uinfo = build_uasset_variant(uasset, len(new_uexp))
    with open(out_uasset, 'wb') as f:
        f.write(new_uasset)
    print('info', {k: v for k, v in info.items()
                   if k not in ('vertex_source_indices', 'section_ranges')})
    print('uinfo', uinfo)

    # --- 自前パーサでの検証(vp_core + parse_sk_structure + parse_sk_full) ---
    r2 = vp_core.parse_skeletalmesh_buffers(new_uexp)
    print('vp_core: numv=', r2['num_vertices'])
    s2 = sk.parse_sk_structure(out_uexp, out_uasset)
    print('parse_sk_structure: tri_match=', s2['tri_match'], 'vtx_match=', s2['vtx_match'],
          'num_sections=', s2['num_sections'])
    full2 = skf.parse_sk_full(out_uexp, out_uasset)
    print('parse_sk_full: gap_zero=', full2['gap_zero'], 'end=', full2['export_end'],
          'expected=', full2['expected_export_end'])
    print('lod0:', full2['lods'][0]['num_vertices'], full2['lods'][0]['total_triangles'])
    ok = s2['tri_match'] and s2['vtx_match'] and full2['gap_zero']
    print('=>', 'OK' if ok else 'FAIL')
    sys.exit(0 if ok else 1)
