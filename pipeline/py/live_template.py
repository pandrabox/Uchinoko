# -*- coding: utf-8 -*-
"""U18: noueテンプレ(旧pak_extract相当、443ファイル)をUE非依存・事前cook不要で
その場組み立てる。

`noue_template_manifest.json`(このファイルと同じディレクトリ、426件vanilla+
17件project)に従い:
  - vanilla分(Palworld本体由来、426件)は`pak_live_extract.py`(U17)経由で
    ユーザー自身のPalworldインストールのpakからその場抽出する(著作物を
    配布物に含めない)
  - project分(DiveToPalworld独自資産、17件。マテリアル/テクスチャの
    「恒久マスター」+マウントアンカー)は同梱済み`noue_master\\pak_extract_extra\\`
    からコピーする(Palworld著作物ではないため同梱に問題なし)

組み立て結果は旧`work\\toto\\build\\pak_extract\\`と相対パス完全一致の構造になり、
`build_pak_from_avatar.py --template`にそのまま渡せる(ゲートT2で検証済み)。

`noue_variants\\`(マテリアルバリアント4種×スロット別)と`shader_platform_facts.json`
(preflight_pak.py G7が参照する「SM5/SM6双方でcook済み」固定の事実ファイル。生のUE cookログ
ではない — 2026-07-26 cooklog_fix。旧cook.logは開発機の絶対パス・個人アバター名を含み
配布不可だったため、必要な事実だけを抽出したこの新ファイルに置き換えた)も同じく
project資産としてnoue_master配下に同梱済み。こちらはコピー不要でそのまま参照する
(convert_noue.pyが読み取り専用で使うだけのため)。

使い方:
    import live_template
    template_dir = live_template.build_live_template(job)
    # -> job配下 build/live_template/ に443ファイル相当を組み立てて返す
"""
import hashlib
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
# U51(research\ue_exit→pipeline\py移設): parse_sk_structure.py/parse_uasset_header.py
# は元research\ue_exit\から無改変のままpipeline\py\へコピーされ、以降はHEREから
# 直接import/参照する(research\ue_exit\側は開発参照用に残置、実行時には見ない)
import pak_live_extract  # noqa: E402
import vp_core as core  # noqa: E402
import parse_sk_structure as sks  # noqa: E402
import parse_uasset_header as puh  # noqa: E402
import stub_skeletal_mesh  # noqa: E402  (dev#26: SKスタブの実行時生成)

TAG = "live_template"

# テンプレの組み立て方が変わった場合にキャッシュ(fingerprint)を強制的に
# 無効化するためのバージョン印。U22でOutfit SKのMaterials[]正規化を追加(2)、
# ExportMap SerialOffsetのシフト漏れ修正(3)、実機で起動直後クラッシュが
# 確定したため正規化を無効化(4)。U25でAssetRegistryDataOffset/
# BulkDataStartOffset/PreloadDependencyOffsetのシフト漏れ(即時クラッシュの
# 確定原因、docs\REPORT_U25_2026-07-24.md T1節)を修正し正規化を再有効化(5)。
# U31でPreloadDependencies配列自体への新規Material import未登録
# (チェッカー柄の確定原因、docs\REPORT_U31_2026-07-25.md T1節)を修正(6)。
# U39でM_VP_m00/m01用に追記するMaterial importのClassNameが実際の型
# (UMaterialInstanceConstant)と食い違っていた誤り(H1修正後も実機で
# チェッカー柄が残存した件の追加原因候補、docs\REPORT_U39_2026-07-25.md
# T1節)を修正(7)。
# U40: H1+H2両適用後も実機チェッカー柄が再現(docs\REPORT_U39_2026-07-25.md
# G3節)。T3設計転換(docs\REPORT_U40_2026-07-25.md): SK側へのM_VP_m00/m01
# 新規import追記(_patch_outfit_sk_materials)を廃止し、SKは完全バニラの
# まま残す。代わりにSKが元々参照するバニラMI資産を同一パス・同一名で
# 差し替え、Base Textureパラメータだけをt00/t01へ向け直す
# (_inject_outfit_body_parka_textures)。新規import・新規パスがゼロになり、
# H1/H2の温床だったPreloadDependencies/ClassName問題が構造的に消滅する(8)。
# U42: 実機の色がBlenderプレビューと一致しない件(docs\REPORT_U42_2026-07-25.md)。
# G1実測: T3はBase Texture(_B)のみを差し替え、バニラMIの他パラメータは
# 無改変のまま残る。実測(devtools\u42_*.py、7サンプル: 素体2種+衣装専用5種、
# 金属鎧系の複雑なMIも含む)により、FMaterialInstanceBasePropertyOverrides内の
# OpacityMaskClipValue既定値(0x3EAAA64C=0.3333、バイト列4C A6 AA 3E)が
# 全ファイルで一意に出現し、その直後(+4)にSubsurfaceProfile参照(FPackageIndex)、
# さらに直後(+8)にShadingModelオーバーライド値(int32 enum)が続くという固定
# レイアウトを確認した。ShadingModelは2(Subsurface)/6(TwoSidedFoliage、素体
# MI_Player_{Gender}_Body系)または5(SubsurfaceProfile、衣装専用MI系)が
# 設定されており、いずれもUE Subsurface Scattering相当のシェーディングを
# 有効化する。これらのSSS的シェーディング(バニラ人間肌向けの暖色/赤み
# トーンを付加する)がBlenderプレビュー(SSSなしの単純シェーディング)には
# 存在しないため、実機でだけ顔・耳・手など地肌部分が暗い赤茶/マルーン色に
# 見える差の実測原因である(_disable_subsurface_shading関数参照)。
# U42-v9(廃案): ShadingModel自体をMSM_DefaultLit(1)へ上書きする初版は実機で
# EXCEPTION_ACCESS_VIOLATION即クラッシュ(work\u42_diag\g3_trial1.log、
# reporter=True dump有りの真クラッシュ)。Shippingビルドにはこのマテリアル
# 系統のDefaultLit用シェーダーpermutationがcookされていないためと推定
# (_disable_subsurface_shading関数コメント参照)。
# U42-v10: ShadingModelは変更せず、ShadingModel=5(MSM_SubsurfaceProfile)の
# 場合のみSubsurfaceProfile参照をNoneへ上書きする(新規permutationを要求
# しない、より保守的な修正)。あわせて「Subsurface Texture」パラメータ
# (ShadingModel=6/TwoSidedFoliage、素体MI_Player_{Gender}_Body系)もBase
# Textureと同じt00/t01へ再配線した。実機検証: クラッシュ無し、しかし
# 見た目が一切変化しなかった(work\u42_diag\g3_trial2/3の各shots参照)。
# U42-v11(廃案): v10の実機無変化を受けてビルドログを精査した結果、
# MI_Player_Male_Body/MI_Player_Female_Body自体がT3の競合検出ガード
# (U40由来、Materials[]配列内の物理スロット位置がSKによって異なる場合は
# 安全側で差し替え対象から除外)に該当し、Base Texture含め一切パッチ
# されずバニラのまま残っていたことが判明(真因、G1確定。ぱんの「元々の
# プレイヤーカラーのまま」という指摘と完全一致)。これが実機で見た目が
# 変化しなかった理由(SSS系パラメータをいくら調整しても、そもそもパッチが
# 素体に一切当たっていなかった)。名前ベースの明示的例外でこの2ファイルに
# 限り強制的にbody(t00)へ解決する修正を試したが、preflight_pak.pyのG3
# (禁止物ゼロ: Skeleton/Body/Physics/ubulk、T3設計以前からの既存安全
# ゲート)にFAILしたため破棄(revert)した。
# U42-v12(中間、破棄): v11の変更を一旦全てrevertし、v10の状態(素体共有MIは
# 非対象のまま)へ戻した安全確認用ビルド。
# U42-v13(最終、指揮者裁定2026-07-25): v11のforced_body_paths(素体共有MIを
# body/t00へ強制解決)を再採用。同時にpreflight_pak.pyのG3を「素体共有MI
# (MI_Player_{Male,Female}_Body、4パス完全一致)のみ例外許可」へ指揮者権限で
# 変更した(pipeline\py\preflight_pak.py参照)。
# U46: v13実機NG(docs\REPORT_U42_2026-07-25.md後のぱん目視)の3点を解消:
# ①体が茶色い ②顔に金属質の模様 ③服がしわしわ。
# G1実測(devtools\u46_enumerate_mi_params.py、20件のバニラMIを対象に
# uasset Name Table中の全候補名についてFMaterialParameterInfoヘッダの
# 一意出現位置をper-name探索。work\u46_diag\findings.md参照)で判明した
# 実際のパラメータ構成:
#   - "Normal Map"(Texture、PF_BC5、全MI共通) + 素体のみ"Override Normal
#     Map 1/2"(Texture、PF_BC5)。"Override Normal Mask 1/2/3"は2つの
#     Normalをブレンドするマスクなので、両Normal自体を平坦化すれば
#     マスク値に関わらず結果は平坦になる(マスク自体は無改変でよい)。
#   - "MetallicRoughnessOcclusionSpecularTexture"(Texture、PF_DXT1、
#     全MI共通)。実データ復号(work\u46_diag\tex_probe\body_M_mip5.png、
#     素体スキンのmip5(64x64)実測)でR channel=常に0・G channel≈0.41
#     (105/255)・B channel≈0.9(230/255、局所的に下がる)を確認し、
#     R=Metallic(常に非金属)・G=Roughness・B=Occlusionの並びを実測確定
#     (名前の並び順とも整合)。"Specular"は別スカラーパラメータで、この
#     テクスチャ(DXT1、アルファ無し)には含まれない。
#   - "Subsurface Color"(Vector、FLinearColor)。Hunter001/Platinum001系で
#     (0.79,0.54,0.26)という非グレーの暖色(素肌色寄り)を実測、Cloth001/
#     Yakushima001系はグレー等値((0.5,0.5,0.5)等)で無害。ShadingModel問わず
#     存在すれば白(1,1,1,1)へ中和する。
#   - 素体共有MI(ShadingModel=6)はSubsurfaceProfile参照(fpi)が
#     v13時点で無改変のまま残っていた(_disable_subsurface_shadingが
#     ShadingModel==5の場合のみNone化していたため)。U46でShadingModel==6も
#     対象に追加(ShadingModel自体は不変、参照Noneのみ。v13で実機実証済みの
#     操作カテゴリの範囲内)。
# 対処方式(絶対禁止=ShadingModel/親Material本体の上書きは今回も一切行わない):
#   - Normal/ORM: 参照先テクスチャ資産(uexp+ubulk)のペイロードを同一パスの
#     まま平坦色で上書き(V8哲学: 新規パッケージ禁止)。DXT1/BC5とも
#     4x4ブロックの符号化サイズは内容非依存(w,h,formatのみで決まる)ため、
#     ヘッダ・オフセット類は一切変更せず、ミップ実体バイトのみ書き換える
#     (ubulkストリームミップも同じ手法でその場上書き、ファイル構造変更なし)。
#   - Subsurface Color/SubsurfaceProfile: 既存のMIバイトパッチ機構
#     (_disable_subsurface_shading系)を拡張、新規パッケージ・新規import
#     ゼロのまま値のみ上書き。
# U47: U46後も残る「肌の色被り」の根絶。実機SS(work\u46_diag\shots_v14c)を
# UE版リファレンス(同一シーン・同一job.json設定でビルド、work\u46_diag\
# shots_ue_ref)と直接見比べた結果、体の白いローブ部分はほぼ一致するのに
# 顔・耳・手など「素体(Body)スロットが描画する地肌」だけが暗い灰紫色に
# 沈んでいることを確認した(U46がBase Texture/Normal/ORM/Subsurface Color
# Vectorを全て中和済みにもかかわらず残る)。G1実測(work\u46_diag\
# g1_enum_all.log)で素体MI(MI_Player_{Male,Female}_Body、ShadingModel=6
# TwoSidedFoliage)自身のパラメータ一覧を洗い直したところ、"Subsurface
# Color"(Vector)のオーバーライドは素体MIに存在せず(U46で中和した対象は
# 衣装専用MI側のみ)、素体側は"Subsurface Texture"(Texture)だけが
# TwoSidedFoliageのサブサーフェス寄与を担っていることを確認した。この
# パラメータはU42で「Base Textureと同じ対象(t00/t01=アバター自身の実写
# テクスチャ)」へ再配線されており、フルカラーのアバター肌テクスチャが
# そのままサブサーフェス散乱の色としても加算される構造になっていた
# (ShadingModelを変えずにTwoSidedFoliageの見た目だけを変える安全な手立てが
# 無かったU42当時はこれが「無改変よりマシ」な暫定処置だったが、結果として
# 「地肌の色が二重に乗る(色被り)」原因になっていたと判断)。
# 対処: Subsurface Textureの参照先(t00/t01への再配線)を廃止し、代わりに
# 元々の参照先である素体専用テクスチャ資産(/Player/Body/Female/
# T_Player_Female_Body_SSS、実測: 男性素体MIも同一資産を共有参照。
# work\u47_diag\probe_sss_tex.py実測: PF_DXT1 2048x2048)を、Normal/ORMと
# 同じ「参照先テクスチャの同一パス・ペイロード平坦化」技法(_flatten_
# normal_orm_textures、U46確立)で黒(0,0,0)へ平坦化する。TwoSidedFoliageの
# サブサーフェス寄与を実質ゼロへ抑え込み、UE版リファレンス(サブサーフェス
# スキャッタリングを一切使わないM_VP独自マテリアル)の見た目に近づける
# (ShadingModel/親Material本体は今回も一切変更しない)。
#
# U47攻め筋2(shadow_lift/force_two_sided/unlit): job.json設定はU13で
# M_VP_{slot}独自マテリアル(convert_noue.py prepare_material_overrides→
# build_pak_from_avatar.py --mat-override-dir、Player/ModelMaterials/
# MainShader/M_VP_m00.uasset等)に実装されたものだが、U40のT3設計転換で
# 衣装SK自身のMaterials[]は完全にバニラのまま(M_VP_*を一切参照しない)へ
# 変わったため、M_VP_{slot}へのshadow_liftバイトパッチは実機では一切
# 参照されないデッドコードになっていることを実測で確認した
# (_find_outfit_slot_material_paths、SKのMaterials[]は常にバニラMI_*の
# フルパッケージパスを返す)。素体MI(ShadingModel=6)は"Emissive Texture"/
# "Emissive Texture Intensity"という、M_VP側のBaseColor×(1-k)+Emissive×k
# 分割に相当するパラメータのオーバーライド自体を最初から持たない
# (G1実測: work\u46_diag\g1_enum_all.log、素体MIの全パラメータ一覧に
# Emissive系は登場しない)。本コードベースのMIバイトパッチ機構は既存の
# シリアライズ済み値を上書きするだけで、シリアライズされていない新規
# パラメータオーバーライドをMIのParameterOverrides配列へ追加すること
# (TArrayの要素数増加+FPropertyTagサイズ更新を要する)には未対応であり、
# 今回はその実装(新規リスク)を見送った。よってshadow_lift/force_two_sided
# の素体スロットへの再配線は本バージョンでは未達のまま(誠実な失敗として
# 報告書へ記録、次サイクルの課題)。
# U50 Phase1(2026-07-25、案B、docs\U50_PHASE1_INSTRUCTIONS.md): 上記の
# 「バニラMIを持ってきて悪いパラメータを1つずつ無害化する」方式(U40〜U49、
# _patch_mi_base_texture)をやめ、素体MI 2件(MI_Player_{Male,Female}_Body)
# だけ「バニラMIを持ってこない」方式へ切り替えた。pakへ既に同梱されている
# 自前cook済みMIC(noue_variants/Lit2S/M_VP_m00.uasset、親は
# M_VP_m00_LitMaster2S)を同一パッケージパスへ複製して置く
# (_clone_mvp_mic_as、work\u50_diag\p0b\clone_mic_proto.py::clone_mic()を
# 移植)。M_VP_m00はNormal/ORM/Subsurface/ShadingModel overrideを最初から
# 持たないため、無害化すべきものが無い。残り74件の衣装MIは従来どおり
# _patch_mi_base_texture(バニラMI差し替え+Base Texture再配線)のまま
# (Phase 2以降で展開予定)。
# U50 Phase1-B実験(2026-07-25、指揮者からの口頭指示によるA/B切り分け実験。
# 専用の指示書ファイルはなし、docs\U50_PHASE1_REPORT.mdへの追記報告のみ):
# Phase1実機で素体2件が「UEのマテリアルエラー」(肌/耳/手がテクスチャ無し
# のっぺり)になった。(甲)クローン・改名機構が原因 か (乙)M_VP資産自体が
# 原因 かを切り分けるため、D2P_U50_EXP_VANILLA_CLONE=1で「バニラの素体MI
# 自身」を_clone_mvp_mic_as(force_rename_insert=True)へ通して同名複製する
# 実験モードを追加した。既定OFF、Phase1本体(U50-S0で既定OFFへ反転済み)の
# 挙動には影響しない。
# U50 単体Material実験(2026-07-25、指揮者からの口頭指示。専用指示書なし):
# A/B実験でクローン・改名機構自体は無罪と判明(バニラMIバイトを同機構へ
# 通しても正常描画)。一方Phase1本体(M_VP_m00 = MIC、親は別パッケージの
# M_VP_m00_LitMaster2S という2段の間接参照)は実機でマテリアルエラーに
# なった。残った仮説は「MIC→別パッケージ親Materialという2段の間接参照が
# Palworldのmod pak環境で解決されない」。これを検証するため、
# D2P_U50_SINGLE_MATERIAL=1で、UEモードが本日このマシンでcookした
# 「単体Material(自己完結、t00を直接import、親を持たない)」
# (work\u50_diag\mvp\alive\M_VP_m00.uasset/.uexp)を、既存のクローン・改名
# 機構(_clone_mvp_mic_as、force_rename_insert=False)へそのまま通して
# 素体2件のパスへ複製する。ShadowLiftはこの単体Materialでは定数として
# 焼かれておりMIC用のスカラーパッチ機構が使えないため、パッチを一切
# 適用しない(値はcook時点のまま)。Phase1本体・Phase1-B実験のどちらより
# 優先する(3つの環境変数が同時にONの場合、この単体Materialモードが勝つ)。
# 既定OFF、他の2モードの挙動には影響しない。
# U50-S0(2026-07-25): Phase1本体クローン(素体2件のMICクローン)を既定OFFへ
# 反転(D2P_U50_P1_ENABLE_BODY_MIC_CLONE=1で明示的にONにしたときのみ有効)。
# これによりビルド結果はU50以前のV8(バニラMIのBase Texture向け替え+
# 平板Normal/ORM/Subsurface Texture)へ戻る。他の2実験モード
# (D2P_U50_EXP_VANILLA_CLONE / D2P_U50_SINGLE_MATERIAL)は元々既定OFFで変更なし。
# U50-unify(2026-07-25、既定ON): スロット対象MI全件を1つのバニラ衣装MIから
# 派生した統一MIで置き換え、shadow_lift を BaseColor/Emissive 分割
# (UEのM_VPと同じ式)で実装した。詳細は _U50_UNIFY_DISABLE 付近のコメント。
# テンプレート内容が変わるためバージョンを上げる。
# U50-single(2026-07-25): マテリアル完全単一化(描画スロット参照MIを全件
# 1種類へ)、t00の4096化、単一アトラス、アルファ255、ORM Roughness=最大、
# Specular=0、コラボ系装備の除外。テンプレート内容が大きく変わるため更新。
# U50-single 修正2(2026-07-25、実機NG2): 非対応(コラボ系)SKのMIを従来の
# T3ループからも除外(バニラのMIのまま残す)。テンプレート内容が変わるため更新。
# dev#26 案B(2026-07-28): SKスタブ306件を同梱コピーから実行時生成へ切替
# (stub_skeletal_mesh.build_stub_files)。uassetはバイト完全一致、uexpは
# bind pose等をライブ抽出バニラ値へ置換(旧同梱比 約2.2KBの差、
# work\wp_stub\REPORT.md参照)。テンプレート内容が変わるため更新。
TEMPLATE_BUILD_VERSION = 24

MVP_PACKAGE_PREFIX = "/Game/Pal/Model/Character/Player/ModelMaterials/MainShader"
_MATERIAL_CLASS_NAMES = ('Material', 'MaterialInstanceConstant')
_MATERIALS_ARRAY_STRIDE = 40
_MATERIALS_ARRAY_SEARCH_WINDOW = 2000


class _OutfitMaterialPatchError(RuntimeError):
    pass


class _HeaderInfo:
    pass


def _encode_name(s):
    b = s.encode("ascii") + b"\x00"
    return struct.pack("<i", len(b)) + b + struct.pack("<HH", 0, 0)


def _parse_header_with_offsets(data):
    """uassetヘッダを前方パースし、各カウント/オフセット整数フィールド自身の
    ファイル内バイト位置を記録する(末尾追記パッチ用。既存バイトは読むだけ)。
    U22診断(devtools\\u22_patch_outfit_materials.py)で複数ファイル実測検証済み。

    U25: DependsOffsetより後ろに続く追加のオフセットフィールド
    (SoftPackageReferencesOffset/SearchableNamesOffset/ThumbnailTableOffset/
    AssetRegistryDataOffset/BulkDataStartOffset/WorldTileInfoDataOffset/
    PreloadDependencyOffset/PayloadTocOffset)もU22挿入点より後ろに位置し、
    挿入バイト数だけシフトしないとロード時に無関係なバイト列を読むことに
    なる(PreloadDependencyOffsetは`FLinkerLoad::SerializePreloadDependencies`
    が直接Seekして読み、EDL依存グラフ経由でFAsyncLoadingThreadに渡る —
    U22の即時クラッシュの確定原因。根拠: docs\\REPORT_U25_2026-07-24.md T1節、
    出典はEngine\\Source\\Runtime\\CoreUObject\\Private\\UObject\\
    PackageFileSummary.cpp/LinkerLoad.cpp)。これらも前方パースして記録する。"""
    if struct.unpack_from("<I", data, 0)[0] != 0x9E2A83C1:
        raise _OutfitMaterialPatchError("uasset magic mismatch")
    off = 4

    def i32():
        nonlocal off
        v = struct.unpack_from("<i", data, off)[0]
        off += 4
        return v

    def i64():
        nonlocal off
        v = struct.unpack_from("<q", data, off)[0]
        off += 8
        return v

    def u16():
        nonlocal off
        v = struct.unpack_from("<H", data, off)[0]
        off += 2
        return v

    def u32():
        nonlocal off
        v = struct.unpack_from("<I", data, off)[0]
        off += 4
        return v

    def fstring():
        nonlocal off
        slen = i32()
        if slen == 0:
            return ""
        if slen > 0:
            s = data[off:off + slen - 1].decode("ascii", errors="replace")
            off += slen
        else:
            n = -slen * 2
            s = data[off:off + n - 2].decode("utf-16-le", errors="replace")
            off += n
        return s

    def engine_version():
        u16(); u16(); u16(); u32()  # Major, Minor, Patch, Changelist
        fstring()  # Branch

    h = _HeaderInfo()
    legacy_ver = i32()
    if legacy_ver != -4:
        i32()
    i32()  # file_version_ue4
    if legacy_ver <= -8:
        i32()  # file_version_ue5
    i32()  # file_version_licensee
    cv_count = i32()
    if not (0 <= cv_count <= 200):
        raise _OutfitMaterialPatchError(f"CustomVersion count implausible: {cv_count}")
    off += cv_count * 20

    h.total_header_size_off = off
    i32()
    fstring()  # package_name

    h.package_flags_off = off
    package_flags = u32()
    filter_editor_only = bool(package_flags & 0x80000000)
    if not filter_editor_only:
        raise _OutfitMaterialPatchError("filter_editor_only=False is unsupported (unexpected input)")

    h.name_count_off = off
    name_count = i32()
    h.name_offset_off = off
    name_offset = i32()

    h.soft_object_paths_count_off = off
    i32()
    h.soft_object_paths_offset_off = off
    soft_object_paths_offset = i32()

    # filter_editor_only=True前提なのでLocalizationIdはスキップ(既存コード同様)

    h.gatherable_text_count_off = off
    gatherable_text_count = i32()
    h.gatherable_text_offset_off = off
    i32()

    h.export_count_off = off
    export_count = i32()
    h.export_offset_off = off
    export_offset = i32()

    h.import_count_off = off
    import_count = i32()
    h.import_offset_off = off
    import_offset = i32()

    h.depends_offset_off = off
    depends_offset = i32()

    h.name_count = name_count
    h.name_offset = name_offset
    h.export_count = export_count
    h.export_offset = export_offset
    h.import_count = import_count
    h.import_offset = import_offset
    h.depends_offset = depends_offset

    if soft_object_paths_offset != import_offset:
        raise _OutfitMaterialPatchError(
            f"unexpected layout (soft={soft_object_paths_offset} import={import_offset})")
    if gatherable_text_count != 0:
        raise _OutfitMaterialPatchError(f"gatherable_text_count={gatherable_text_count} (only 0 is supported)")

    # --- U25: DependsOffsetより後ろの追加オフセットフィールド ---
    h.soft_package_references_count_off = off
    i32()
    h.soft_package_references_offset_off = off
    h.soft_package_references_offset = i32()

    h.searchable_names_offset_off = off
    h.searchable_names_offset = i32()

    h.thumbnail_table_offset_off = off
    h.thumbnail_table_offset = i32()

    off += 16  # Guid(FGuid、filter_editor_only=TrueなのでPersistentGuid等は無し)

    gen_count = i32()
    off += gen_count * 8  # FGenerationInfo: ExportCount(i32)+NameCount(i32)

    engine_version()  # SavedByEngineVersion
    engine_version()  # CompatibleWithEngineVersion

    u32()  # CompressionFlags

    cc_count = i32()
    if cc_count != 0:
        raise _OutfitMaterialPatchError(f"CompressedChunks count != 0: {cc_count} (unexpected)")

    u32()  # PackageSource

    apc_count = i32()
    for _ in range(apc_count):
        fstring()  # AdditionalPackagesToCook(想定: 通常0件)

    if legacy_ver > -7:
        i32()  # NumTextureAllocations(legacy_ver=-8前提では出現しないはず)

    h.asset_registry_data_offset_off = off
    h.asset_registry_data_offset = i32()

    h.bulk_data_start_offset_off = off
    h.bulk_data_start_offset = i64()

    h.world_tile_info_data_offset_off = off
    h.world_tile_info_data_offset = i32()

    chunk_count = i32()
    off += chunk_count * 4  # ChunkIDs(想定: 通常0件)

    h.preload_dependency_count_off = off
    i32()
    h.preload_dependency_offset_off = off
    h.preload_dependency_offset = i32()

    off += 4  # NamesReferencedFromExportDataCount(シフト不要、カウント値のみ)

    h.payload_toc_offset_off = off
    h.payload_toc_offset = i64()

    return h


def _read_name_table(data, name_offset, name_count):
    names = []
    off = name_offset
    for _ in range(name_count):
        slen = struct.unpack_from("<i", data, off)[0]
        off += 4
        if slen > 0:
            s = data[off:off + slen - 1].decode("ascii", errors="replace")
            off += slen
        elif slen < 0:
            n = -slen * 2
            s = data[off:off + n - 2].decode("utf-16-le", errors="replace")
            off += n
        else:
            s = ""
        off += 4
        names.append(s)
    return names, off


def _parse_import(data, off):
    start = off
    cp = struct.unpack_from("<i", data, off)[0]; off += 8
    cn = struct.unpack_from("<i", data, off)[0]; off += 8
    outer = struct.unpack_from("<i", data, off)[0]; off += 4
    on = struct.unpack_from("<i", data, off)[0]; off += 8
    bopt = struct.unpack_from("<i", data, off)[0]; off += 4
    return dict(class_package_idx=cp, class_name_idx=cn, outer_index=outer,
                object_name_idx=on, b_import_optional=bopt, start=start, end=off), off


def _encode_import(class_package_idx, class_name_idx, outer_index, object_name_idx, b_import_optional=0):
    return (struct.pack("<ii", class_package_idx, 0) +
            struct.pack("<ii", class_name_idx, 0) +
            struct.pack("<i", outer_index) +
            struct.pack("<ii", object_name_idx, 0) +
            struct.pack("<i", b_import_optional))


def _read_export_dep_fields(data, export_start):
    """FObjectExportのclass_index/FirstExportDependency/4カウントを読む
    (U31: PreloadDependencies配列パッチ用)。UE5.1エンジンソース
    (`ObjectResource.h`のFObjectExport、`ObjectResource.cpp`の
    operator<<(FStructuredArchive::FSlot, FObjectExport&))通りの
    フィールド順序で、export先頭からの固定オフセット(96byteストライド中、
    class_index@0、FirstExportDependency@76)で直接読む。"""
    class_index = struct.unpack_from("<i", data, export_start)[0]
    fed_off = export_start + 76
    fed, c1, c2, c3, c4 = struct.unpack_from("<iiiii", data, fed_off)
    return {
        "class_index": class_index, "fed_off": fed_off,
        "fed": fed, "c1": c1, "c2": c2, "c3": c3, "c4": c4,
    }


def _find_material_slot_offsets(uexp_data, material_import_indices, search_end):
    limit = min(search_end, _MATERIALS_ARRAY_SEARCH_WINDOW, len(uexp_data))
    hits = []
    for off in range(0, limit - 4):
        v = struct.unpack_from("<i", uexp_data, off)[0]
        if v in material_import_indices:
            hits.append((off, v))
    hits.sort(key=lambda x: x[0])
    n = len(material_import_indices)
    for start_i in range(0, len(hits) - n + 1):
        run = hits[start_i:start_i + n]
        if all(run[i + 1][0] - run[i][0] == _MATERIALS_ARRAY_STRIDE for i in range(len(run) - 1)):
            return run
    return hits


def _patch_outfit_sk_materials(uasset_path, uexp_path, out_uasset_path, out_uexp_path):
    """U22: 衣装SKのMaterials[]配列スロット0/1(アバター注入器が
    material_index=0(body)/1(parka)として参照する箇所)が、真バニラ材質
    ではなくM_VP_m00/M_VP_m01(アバター用マテリアル差し替え先の固定パス)を
    参照するよう、uasset Name/Import Tableへの末尾追記のみで正規化する
    (既存バイトは一切上書きしない)。詳細根拠: docs\\REPORT_U22_2026-07-24.md。

    戻り値dictに'skipped'=Trueがあれば、Materials[]配列に材質参照が2件
    未満(単一マテリアル衣装、例: Kigurumi001)で本方式では正規化できない
    ことを示す(呼び出し元は無改変のままコピーする)。"""
    with open(uasset_path, "rb") as f:
        data = f.read()
    with open(uexp_path, "rb") as f:
        uexp_data = bytearray(f.read())

    h = _parse_header_with_offsets(data)
    names, names_end = _read_name_table(data, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        raise _OutfitMaterialPatchError(f"name table end ({names_end}) != import_offset ({h.import_offset})")

    off = h.import_offset
    imports = []
    for _ in range(h.import_count):
        imp, off = _parse_import(data, off)
        imports.append(imp)
    if off != h.export_offset:
        raise _OutfitMaterialPatchError(f"import table end ({off}) != export_offset ({h.export_offset})")

    name_index = {s: i for i, s in enumerate(names)}

    material_imports = {}
    for i, imp in enumerate(imports):
        cn = names[imp["class_name_idx"]] if 0 <= imp["class_name_idx"] < len(names) else None
        if cn in _MATERIAL_CLASS_NAMES:
            material_imports[-(i + 1)] = names[imp["object_name_idx"]]

    if len(material_imports) < 2:
        return {"skipped": True, "reason": f"only {len(material_imports)} Material-class import(s)"}

    s = sks.parse_sk_structure(uexp_path, uasset_path)
    hits = _find_material_slot_offsets(uexp_data, material_imports, s["render_sections_count_offset"])
    if len(hits) != len(material_imports):
        raise _OutfitMaterialPatchError(
            f"slot occurrence count ({len(hits)}) != Material import count ({len(material_imports)}): {hits}")
    hits.sort(key=lambda x: x[0])
    slot0_off, _ = hits[0]
    slot1_off, _ = hits[1]

    needed_common = ["/Script/CoreUObject", "/Script/Engine", "MaterialInstanceConstant", "Package"]
    new_names = []
    resolved = {}

    def resolve(s_):
        if s_ in name_index:
            resolved[s_] = name_index[s_]
        elif s_ not in resolved:
            resolved[s_] = h.name_count + len(new_names)
            new_names.append(s_)

    for s_ in needed_common:
        resolve(s_)
    m00_short, m01_short = "M_VP_m00", "M_VP_m01"
    m00_full = f"{MVP_PACKAGE_PREFIX}/{m00_short}"
    m01_full = f"{MVP_PACKAGE_PREFIX}/{m01_short}"
    for s_ in (m00_short, m01_short, m00_full, m01_full):
        resolve(s_)

    name_insert_bytes = b"".join(_encode_name(s_) for s_ in new_names)

    core_uobject = resolved["/Script/CoreUObject"]
    engine = resolved["/Script/Engine"]
    # U39実測(docs\REPORT_U39_2026-07-25.md T1節): M_VP_m00/m01.uasset自身の
    # exportは実際にはUMaterialInstanceConstant(親Materialへの参照を持つ
    # インスタンス)であり、UMaterialではない。真バニラのOutfit SK自身が
    # 既に参照するMI_*系importも例外なくClassName=MaterialInstanceConstantで
    # 登録されている(実測、work\u31_diag\vanilla_raw\SK_Player_Female_
    # Outfit_Ancient001.uasset他)。旧実装はここをClassName="Material"
    # (UMaterial)で誤登録しており、実際の型と食い違うImport Tableエントリに
    # なっていた(UE5.1エンジンソースFindImportFast→StaticFindObjectFast
    # (ExactClass=false=IsA判定)は、UMaterialInstanceConstantがUMaterialの
    # 派生型ではない(共にUMaterialInterfaceの兄弟派生)ため不一致となり、
    # 既にロード済みのインポートを再解決する経路(高速パス)で解決失敗しうる)。
    material_cls = resolved["MaterialInstanceConstant"]
    package_cls = resolved["Package"]

    old_import_count = h.import_count
    idx_pkg_m00 = old_import_count + 1
    idx_pkg_m01 = old_import_count + 2
    idx_mat_m00 = old_import_count + 3
    idx_mat_m01 = old_import_count + 4

    import_insert_bytes = b"".join([
        _encode_import(core_uobject, package_cls, 0, resolved[m00_full]),
        _encode_import(core_uobject, package_cls, 0, resolved[m01_full]),
        _encode_import(engine, material_cls, -idx_pkg_m00, resolved[m00_short]),
        _encode_import(engine, material_cls, -idx_pkg_m01, resolved[m01_short]),
    ])

    # --- U31: PreloadDependencies配列への新規Material import登録の準備 ---
    # H1実測確定(docs\REPORT_U31_2026-07-25.md T1節、複数ファイルで対照済み):
    # 真バニラでは、Materials[]が参照するマテリアルimportは本体SkeletalMesh
    # exportの「CreateBeforeSerializationDependencies」カテゴリとして
    # PreloadDependencies配列に含まれる。U22/U25/U26のいずれもこの配列の中身を
    # 書き換えておらず、新規追記したM_VP_m00/m01がEDL
    # (`FLinkerLoad::SerializePreloadDependencies`)の依存解決から漏れ、
    # 実機でチェッカーマテリアルへフォールバックする確定原因(T0実機で目視確認)。
    # ここで新規importを同じカテゴリへ正しく登録する。
    off_e = h.export_offset
    export_starts = []
    for _ in range(h.export_count):
        entry, off_e = puh.parse_export_entry(data, off_e)
        export_starts.append(entry["start"])

    def _class_name_of(class_index):
        if class_index < 0:
            i = -class_index - 1
            if 0 <= i < len(imports):
                return names[imports[i]["object_name_idx"]]
        return None

    target_index = None
    target_dep = None
    for i, start in enumerate(export_starts):
        dep = _read_export_dep_fields(data, start)
        if _class_name_of(dep["class_index"]) == "SkeletalMesh":
            target_index = i
            target_dep = dep
            break
    if target_index is None:
        raise _OutfitMaterialPatchError(
            "SkeletalMesh export not found (PreloadDependencies fix precondition broken)")

    preload_count = struct.unpack_from("<i", data, h.preload_dependency_count_off)[0]
    insertion_array_index = target_dep["fed"] + target_dep["c1"] + target_dep["c2"]
    orig_insert_pos = h.preload_dependency_offset + insertion_array_index * 4
    preload_insert_bytes = struct.pack("<ii", -idx_mat_m00, -idx_mat_m01)

    P1 = h.import_offset
    P2 = h.export_offset
    new_data = bytearray(
        data[:P1] + name_insert_bytes + data[P1:P2] + import_insert_bytes +
        data[P2:orig_insert_pos] + preload_insert_bytes + data[orig_insert_pos:])

    def patch_i32(field_off, new_val):
        struct.pack_into("<i", new_data, field_off, new_val)

    def patch_i64(field_off, new_val):
        struct.pack_into("<q", new_data, field_off, new_val)

    name_delta = len(name_insert_bytes)
    import_delta = len(import_insert_bytes)
    # header_delta: Import/Name Table追記のみに起因するシフト量。Export Table・
    # Depends Table・SoftPackageReferences等、PreloadDependencies配列より前に
    # 位置するテーブルへのポインタはこちらでシフトする。
    header_delta = name_delta + import_delta
    # total_delta: 上記に加えPreloadDependencies配列への8byte追記(新規2件)も
    # 含めた、uasset全体の肥大化分。TotalHeaderSize/BulkDataStartOffset
    # (uasset+uexp全体サイズの番兵値)・ExportMapのSerialOffset
    # (同じく全体サイズ基準の仮想絶対オフセット)はこちらを使う。
    total_delta = header_delta + len(preload_insert_bytes)

    patch_i32(h.total_header_size_off, len(new_data))
    patch_i32(h.name_count_off, h.name_count + len(new_names))
    patch_i32(h.soft_object_paths_offset_off, P1 + name_delta)
    patch_i32(h.import_offset_off, P1 + name_delta)
    patch_i32(h.import_count_off, old_import_count + 4)
    patch_i32(h.export_offset_off, P2 + header_delta)
    patch_i32(h.depends_offset_off, h.depends_offset + header_delta)

    # U25: DependsOffsetより後ろに続く追加のオフセットフィールドも、挿入点
    # (P1/P2)より後ろに位置するため同様にheader_delta分シフトが必要
    # (根拠: docs\REPORT_U25_2026-07-24.md T1節。U22はここを未シフトのまま
    # 放置しており、PreloadDependencyOffsetの不整合が実機即クラッシュの
    # 確定原因だった)。0/-1は「未使用」を示す番兵値なので、その場合は
    # シフトせずそのまま維持する(該当フィールドは対象60ファイルで実測上
    # 常に0だが、将来別アセット種別で非0になっても安全なよう条件分岐する)。
    # これらのターゲットはPreloadDependencies配列(挿入点orig_insert_pos)より
    # 前に位置するため、header_deltaのみでよい(total_deltaだと8byte過剰)。
    if h.soft_package_references_offset != 0:
        patch_i32(h.soft_package_references_offset_off, h.soft_package_references_offset + header_delta)
    if h.searchable_names_offset != 0:
        patch_i32(h.searchable_names_offset_off, h.searchable_names_offset + header_delta)
    if h.thumbnail_table_offset != 0:
        patch_i32(h.thumbnail_table_offset_off, h.thumbnail_table_offset + header_delta)
    if h.asset_registry_data_offset != 0:
        patch_i32(h.asset_registry_data_offset_off, h.asset_registry_data_offset + header_delta)
    # BulkDataStartOffsetはExportMapのSerialOffsetと同じ「uasset+uexp仮想絶対
    # オフセット」規約(実測: 常にuasset_size+uexp_size-4と一致=バルクデータ
    # 無しの番兵値)なので、0であっても常にシフトする(SerialOffsetと同様の扱い)。
    # uasset全体の肥大化分(PreloadDependencies追記込み)を反映するtotal_deltaを使う。
    patch_i64(h.bulk_data_start_offset_off, h.bulk_data_start_offset + total_delta)
    if h.world_tile_info_data_offset != 0:
        patch_i32(h.world_tile_info_data_offset_off, h.world_tile_info_data_offset + header_delta)
    if h.preload_dependency_offset != 0:
        patch_i32(h.preload_dependency_offset_off, h.preload_dependency_offset + header_delta)
    if h.payload_toc_offset != -1:
        patch_i64(h.payload_toc_offset_off, h.payload_toc_offset + header_delta)

    # U31: PreloadDependencyCountを+2(新規2件)。
    patch_i32(h.preload_dependency_count_off, preload_count + 2)

    # ExportMapの各エントリのSerialOffsetは「uasset+uexpを1本の仮想バイナリと
    # 見なした絶対オフセット」(= 旧total_header_size + uexp内オフセット)であり、
    # uassetが追記で肥大化した分(total_delta)だけ全件シフトが必要(実測で発覚:
    # これをしないとbuild_avatar_variant.py側の「SerialOffsetがuassetサイズ未満」
    # 整合性チェックに引っかかる)。中身(SerialSize)は変更しないので個数は不変。
    # 同じループでU31: 対象(SkeletalMesh)exportのCreateBeforeSerialization
    # カウントを+2、挿入点より後ろにブロックを持つ他exportのFirstExportDependency
    # を+2する(配列内の"インデックス"のシフトであり、バイトオフセットではない
    # ため、header_delta/total_deltaのバイト系シフトとは独立)。
    new_export_offset = P2 + header_delta
    eoff = new_export_offset
    for i in range(h.export_count):
        entry, eoff = puh.parse_export_entry(new_data, eoff)
        old_serial_offset = struct.unpack_from("<q", new_data, entry["serial_size_offset"] + 8)[0]
        struct.pack_into("<q", new_data, entry["serial_size_offset"] + 8, old_serial_offset + total_delta)

        dep = _read_export_dep_fields(new_data, entry["start"])
        if i == target_index:
            struct.pack_into("<i", new_data, dep["fed_off"] + 8, dep["c2"] + 2)  # c2 = CreateBeforeSerialization
        elif dep["fed"] >= insertion_array_index:
            struct.pack_into("<i", new_data, dep["fed_off"], dep["fed"] + 2)

    struct.pack_into("<i", uexp_data, slot0_off, -idx_mat_m00)
    struct.pack_into("<i", uexp_data, slot1_off, -idx_mat_m01)

    if out_uasset_path != uasset_path or out_uexp_path != uexp_path:
        os.makedirs(os.path.dirname(out_uasset_path) or ".", exist_ok=True)
    with open(out_uasset_path, "wb") as f:
        f.write(new_data)
    with open(out_uexp_path, "wb") as f:
        f.write(uexp_data)
    return {"skipped": False}


def _normalize_outfit_materials(dst_dir):
    """組み立て済みlive_template内の全Outfit SKについて、Materials[]配列を
    M_VP_m00/m01参照へ正規化する(U22: 色ズレの確定原因への対処、
    docs\\REPORT_U22_2026-07-24.md参照)。in-place上書き。"""
    outfit_root = os.path.join(dst_dir, "Player", "Outfit")
    pairs = []
    for dirpath, _, fns in os.walk(outfit_root):
        for fn in sorted(fns):
            if not fn.lower().endswith(".uexp"):
                continue
            uexp = os.path.join(dirpath, fn)
            uasset = uexp[:-5] + ".uasset"
            if os.path.exists(uasset):
                pairs.append((uexp, uasset))
    n_ok = 0
    n_skip = 0
    skipped_files = []
    for uexp_path, uasset_path in sorted(pairs):
        info = _patch_outfit_sk_materials(uasset_path, uexp_path, uasset_path, uexp_path)
        if info.get("skipped"):
            n_skip += 1
            skipped_files.append(os.path.relpath(uexp_path, dst_dir))
        else:
            n_ok += 1
    print(f"[{TAG}] Outfit Materials[] normalization (U22): {n_ok} succeeded, {n_skip} skipped "
          f"(single-material outfit, unchanged)")
    if skipped_files:
        print(f"[{TAG}]   skip breakdown: {skipped_files}")


# ============================================================================
# T3(U40設計転換、docs\REPORT_U40_2026-07-25.md): チェッカー柄の真因が
# 「SK側のMaterials[]に追記した新規Material import(M_VP_m00/m01)自体が
# 実機で解決できない」可能性(H2修正後も実機で再現、複数仮説を実測で
# 却下)に対する構造的な保険。SK自体は一切変更せず完全バニラのまま残し、
# 代わりにSKが元々参照しているバニラMI(MaterialInstanceConstant)資産を
# 同一パッケージパス・同一名のままpak内で差し替え、そのBase Texture
# パラメータだけを注入済みT_VP系(t00/t01)へ向け直す。新規import・新規
# パスはゼロ(SK側のPreloadDependencies/ClassName問題が構造的に消滅する)。
# 実行時にBP/DataTable側が別経路でマテリアルを再割当していても(H6)、
# 再割当先=同じMIパスなので正しく反映される想定。
# ============================================================================

def _find_outfit_slot_material_paths(uasset_path, uexp_path):
    """衣装SKのMaterials[]配列スロット0/1(body/parka)が実際に参照する
    バニラMIのフルパッケージパスを、SK自身は一切変更せず読み取り専用で
    特定する。_patch_outfit_sk_materials(旧設計、SK側へM_VP_m00/m01への
    新規importを追記する方式)の前段(スロット検出ロジック)のみを流用し、
    SK本体への書き込みは一切行わない。

    戻り値: {0: full_path, 1: full_path}。単一マテリアル衣装等でスロットが
    2件未満の場合は空dict({})。"""
    with open(uasset_path, "rb") as f:
        data = f.read()
    with open(uexp_path, "rb") as f:
        uexp_data = bytearray(f.read())

    h = _parse_header_with_offsets(data)
    names, names_end = _read_name_table(data, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        raise _OutfitMaterialPatchError(f"name table end ({names_end}) != import_offset ({h.import_offset})")

    off = h.import_offset
    imports = []
    for _ in range(h.import_count):
        imp, off = _parse_import(data, off)
        imports.append(imp)
    if off != h.export_offset:
        raise _OutfitMaterialPatchError(f"import table end ({off}) != export_offset ({h.export_offset})")

    material_imports = {}
    for i, imp in enumerate(imports):
        cn = names[imp["class_name_idx"]] if 0 <= imp["class_name_idx"] < len(names) else None
        if cn in _MATERIAL_CLASS_NAMES:
            material_imports[-(i + 1)] = names[imp["object_name_idx"]]

    if len(material_imports) < 2:
        return {}

    s = sks.parse_sk_structure(uexp_path, uasset_path)
    hits = _find_material_slot_offsets(uexp_data, material_imports, s["render_sections_count_offset"])
    if len(hits) != len(material_imports):
        raise _OutfitMaterialPatchError(
            f"slot occurrence count ({len(hits)}) != Material import count ({len(material_imports)}): {hits}")
    hits.sort(key=lambda x: x[0])

    def full_path_of(fpi):
        i = -fpi - 1
        imp = imports[i]
        outer_fpi = imp["outer_index"]
        if outer_fpi >= 0:
            raise _OutfitMaterialPatchError(f"unexpected: material import's outer is not an import: {outer_fpi}")
        outer_imp = imports[-outer_fpi - 1]
        return names[outer_imp["object_name_idx"]]

    return {0: full_path_of(hits[0][1]), 1: full_path_of(hits[1][1])}


def find_outfit_material_paths_all(uasset_path, uexp_path, limit=2):
    """U50-single: 衣装SKの Materials[] が参照するバニラMIのフルパッケージ
    パスを**出現順のリスト**で返す(スロット役=t00/t01 の割り当てをしない)。

    `_find_outfit_slot_material_paths` との違い:
      - マテリアルが1件しかないSK(Kigurumi001)も普通に扱える
        (あちらは `len(material_imports) < 2` で空dictを返して脱落していた)
      - 「同じMIが別のSKでは別スロット役」という競合が**起こりえない**
        (役が無いため)。競合ガードで今まで一度もpakに入らなかった
        Plastic001 の M01 4件と Kigurumi001 の MI 1件も対象になる

    limit: 先頭何スロットまでを対象にするか。`build_avatar_variant.py` は
      MaterialIndex 0/1 のセクションしか作らない(=2番目以降のマテリアル
      スロットは描画されない)ため既定2。0以下で全スロット。
    """
    with open(uasset_path, "rb") as f:
        data = f.read()
    with open(uexp_path, "rb") as f:
        uexp_data = bytearray(f.read())

    h = _parse_header_with_offsets(data)
    names, names_end = _read_name_table(data, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        raise _OutfitMaterialPatchError(
            f"name table end ({names_end}) != import_offset ({h.import_offset})")
    off = h.import_offset
    imports = []
    for _ in range(h.import_count):
        imp, off = _parse_import(data, off)
        imports.append(imp)
    if off != h.export_offset:
        raise _OutfitMaterialPatchError(
            f"import table end ({off}) != export_offset ({h.export_offset})")

    material_imports = {}
    for i, imp in enumerate(imports):
        cn = names[imp["class_name_idx"]] if 0 <= imp["class_name_idx"] < len(names) else None
        if cn in _MATERIAL_CLASS_NAMES:
            material_imports[-(i + 1)] = names[imp["object_name_idx"]]
    if not material_imports:
        return []

    s = sks.parse_sk_structure(uexp_path, uasset_path)
    hits = _find_material_slot_offsets(uexp_data, material_imports,
                                       s["render_sections_count_offset"])
    if len(hits) != len(material_imports):
        raise _OutfitMaterialPatchError(
            f"slot occurrence count ({len(hits)}) != Material import count ({len(material_imports)}): {hits}")
    hits.sort(key=lambda x: x[0])

    def full_path_of(fpi):
        imp = imports[-fpi - 1]
        outer_fpi = imp["outer_index"]
        if outer_fpi >= 0:
            raise _OutfitMaterialPatchError(
                f"unexpected: material import's outer is not an import: {outer_fpi}")
        return names[imports[-outer_fpi - 1]["object_name_idx"]]

    paths = [full_path_of(fpi) for _o, fpi in hits]
    return paths if limit <= 0 else paths[:limit]


# U42: OpacityMaskClipValue既定値(0.3333)のfloatバイト列。
# FMaterialInstanceBasePropertyOverrides内で一意に出現するアンカーとして使う
# (モジュールdocstring/TEMPLATE_BUILD_VERSIONコメント参照、7サンプル実測済み)。
_OPACITY_MASK_CLIP_ANCHOR = bytes.fromhex("4ca6aa3e")
# UE EMaterialShadingModel: 5=SubsurfaceProfile、6=TwoSidedFoliage(素体
# MI_Player_{Gender}_Body系)。U42時点では5のみNone化していたが、U46実測
# (docs\REPORT_U46_2026-07-25.md、素体MIのSubsurfaceProfile fpiがv13でも
# 非0のまま残存していたことを確認)により6もNone化対象に追加する
# (ShadingModel自体は不変のまま、参照だけをNoneにする単純上書きであり、
# U42でShadingModel=5に対して実機実証済みの操作と同じカテゴリ)。
_SHADING_MODELS_TO_NULL_SSP = (5, 6)

# U42-attempt1(廃案、実機EXCEPTION_ACCESS_VIOLATIONで即クラッシュ確定、
# work\u42_diag\g3_trial1.log): ShadingModelそのものをMSM_DefaultLit(1)へ
# 上書きする案は、Shippingビルドが当該マテリアルのDefaultLit用シェーダー
# permutationをcook時に一切含んでいない(バニラでは常にSubsurfaceProfile/
# TwoSidedFoliageとしてのみ使われるため)ために実機で確実にクラッシュする
# ことを実測で確認した(誠実な失敗、8節へ記録)。UE非依存(cook不要)という
# 本プロジェクトの前提上、新規シェーダーpermutationを要求する変更は
# 構造的に不可能。よってShadingModel自体は変更しない。


def _disable_subsurface_shading(uexp_bytes):
    """U42(G1実測): バニラMIのFMaterialInstanceBasePropertyOverrides内、
    OpacityMaskClipValue(既定0.3333、_OPACITY_MASK_CLIP_ANCHOR)の直後(+4)に
    SubsurfaceProfile参照(FPackageIndex, int32)、その直後(+8)にShadingModel
    オーバーライド値(int32 enum)が続く固定レイアウトを7サンプル
    (素体2種+衣装専用5種、金属鎧系の複雑なMIも含む)全件で実測確認済み。

    ShadingModelが_SHADING_MODELS_TO_NULL_SSPに含まれる場合のみ、
    SubsurfaceProfile参照を0(None)へ上書きする(ShadingModel自体は変更
    しない — 上記コメント参照、シェーダーpermutation要求を避けるため)。
    SubsurfaceProfile=NoneはUEの標準的なフォールバック経路(エンジン既定
    プロファイルを使う、多くのバニラアセットでも普通に起こる状態)であり、
    新規permutationを要求しない想定。

    アンカーが一意でない、またはShadingModelが対象外の場合は無改変のまま
    返す(既存コードベースの「構造不一致時は安全側へスキップ」方針を踏襲)。

    戻り値: (patched_bytes, info)。infoは{"patched": bool, ...}。"""
    hits = [i for i in range(len(uexp_bytes) - 12)
            if uexp_bytes[i:i + 4] == _OPACITY_MASK_CLIP_ANCHOR]
    if len(hits) != 1:
        return bytes(uexp_bytes), {"patched": False, "reason": f"{len(hits)} anchor(s) (not exactly 1)"}
    anchor_off = hits[0]
    ssp_off = anchor_off + 4
    sm_off = anchor_off + 8
    shading_model = struct.unpack_from("<i", uexp_bytes, sm_off)[0]
    if shading_model not in _SHADING_MODELS_TO_NULL_SSP:
        return bytes(uexp_bytes), {"patched": False, "reason": f"ShadingModel={shading_model} (not applicable)"}
    data = bytearray(uexp_bytes)
    struct.pack_into("<i", data, ssp_off, 0)
    return bytes(data), {"patched": True, "old_shading_model": shading_model}


# U46: 「Subsurface Color」(FVectorParameterValue、FLinearColor)を白
# (1,1,1,1)へ中和する。G1実測(work\u46_diag\param_json\*.json)で
# Hunter001/Platinum001系のバニラ値が(0.79,0.54,0.26)という非グレーの
# 暖色(素肌色寄り)であることを確認しており、SubsurfaceProfile=None化
# だけでは消えない色付きティントの実体候補(体が茶色い症状の追加要因)。
_VECPARAM_MARKER_OFF = 9   # _TEXPARAM_MARKER_OFFと同じ(FName+assoc直後のIndex位置)
_VECPARAM_VALUE_OFF = 13   # FLinearColor(16byte, RGBA各float)の開始位置


def _neutralize_named_vector_param(uexp_bytes, names, param_name, rgba=(1.0, 1.0, 1.0, 1.0)):
    """uexp内で'param_name'という名前のVectorParameterValueエントリを
    _find_named_texture_param_fpiと同じ一意性チェック方式で探し、その
    FLinearColorペイロード(16byte)をrgbaへ上書きする。見つからない/
    一意でない場合は無改変のまま返す(安全側スキップ)。
    戻り値: (patched_bytes, info)。"""
    if param_name not in names:
        return bytes(uexp_bytes), {"patched": False, "reason": "parameter name not in NameTable"}
    name_idx = names.index(param_name)
    candidates = []
    for i in range(0, len(uexp_bytes) - (_VECPARAM_VALUE_OFF + 16)):
        idx_val = struct.unpack_from("<i", uexp_bytes, i)[0]
        if idx_val != name_idx:
            continue
        num_val = struct.unpack_from("<i", uexp_bytes, i + 4)[0]
        if num_val != 0:
            continue
        marker = struct.unpack_from("<i", uexp_bytes, i + _VECPARAM_MARKER_OFF)[0]
        if marker != -1:
            continue
        candidates.append(i)
    if len(candidates) != 1:
        return bytes(uexp_bytes), {"patched": False, "reason": f"{len(candidates)} candidate(s) (not exactly 1)"}
    pos = candidates[0]
    old = struct.unpack_from("<ffff", uexp_bytes, pos + _VECPARAM_VALUE_OFF)
    data = bytearray(uexp_bytes)
    struct.pack_into("<ffff", data, pos + _VECPARAM_VALUE_OFF, *rgba)
    return bytes(data), {"patched": True, "old_rgba": [round(x, 4) for x in old]}


# U42: TextureParameterValue(Vector/Scalarと同型のFMaterialParameterInfoヘッダ)
# のレイアウト定数。FName(8byte, idx+number=0) + assoc_type(1byte) +
# Index=-1マーカー(4byte) + テクスチャ参照(FPackageIndex, 4byte、ここが
# 差し替え対象) + ExpressionGUID(16byte、未使用)。_disable_subsurface_shading
# のScalar版パターン(OpacityMaskClipValueアンカー)と同系統の構造。
_TEXPARAM_MARKER_OFF = 9    # FName(8byte)直後、Index=-1マーカー開始位置
_TEXPARAM_VALUE_OFF = 13    # FName(8byte)直後、テクスチャ参照(fpi)の開始位置


def _find_named_texture_param_fpi(uexp_bytes, names, param_name):
    """U42: uexp内で'param_name'という名前のTextureParameterValueエントリを
    一意に探し、その値(テクスチャ参照、FPackageIndex)を返す。

    見つからない(パラメータ名自体がこのMIに無い)場合は(None, None)。
    一意に決まらない場合(複数候補や偽陽性の疑い)も安全側でスキップする
    ((None, None))。戻り値: (name_fname_offset, fpi) または (None, None)。"""
    if param_name not in names:
        return None, None
    name_idx = names.index(param_name)
    candidates = []
    for i in range(0, len(uexp_bytes) - (_TEXPARAM_VALUE_OFF + 4)):
        idx_val = struct.unpack_from("<i", uexp_bytes, i)[0]
        if idx_val != name_idx:
            continue
        num_val = struct.unpack_from("<i", uexp_bytes, i + 4)[0]
        if num_val != 0:
            continue
        marker = struct.unpack_from("<i", uexp_bytes, i + _TEXPARAM_MARKER_OFF)[0]
        if marker != -1:
            continue
        fpi = struct.unpack_from("<i", uexp_bytes, i + _TEXPARAM_VALUE_OFF)[0]
        candidates.append((i, fpi))
    if len(candidates) != 1:
        return None, None
    return candidates[0]


def _patch_mi_base_texture(uasset_path, uexp_path, out_uasset_path, out_uexp_path,
                            target_full_path, target_short_name):
    """バニラMI(MaterialInstanceConstant)資産を同一パッケージパス・同一名の
    まま差し替える。実測(work\\u40_diag\\vanilla_mi、複数サンプル)により、
    バニラMIは常にBase/Emissive/MetallicRoughness.../Normalの4枚の
    Texture2D importを持ち、Base Textureは常にObjectNameが"_B"で終わる
    importである(その宣言順も最初=uexp内の出現オフセットが最小)ことを
    確認済み。このBase Texture importと、そのouter(Package import、
    フルパッケージパス文字列を持つ)のObjectNameだけを、注入済みT_VP系
    (t00/t01)へ差し替える。

    U42-attempt3(docs\\REPORT_U42_2026-07-25.md、U47で廃止): 当初は
    ShadingModel=6(TwoSidedFoliage、素体MI_Player_{Gender}_Body系)の
    「Subsurface Texture」パラメータもBase Textureと同じ対象(t00/t01)へ
    再配線していたが、これがフルカラーのアバター肌テクスチャをサブサーフェス
    散乱の色としても加算する形になり「地肌の色被り」の実測上の原因と
    判明した(U47、TEMPLATE_BUILD_VERSIONコメント参照)。U47でこの再配線は
    廃止し、代わりに「Subsurface Texture」が参照する元々のバニラテクスチャ
    資産自体を黒へ平坦化する方式(_collect_flatten_targets/
    _flatten_normal_orm_textures、Normal/ORMと同じ技法)へ置き換えた。
    このためBase Texture importの差し替えのみを行う(Subsurface Textureの
    import自体には一切触れない)。

    import数・export数・PreloadDependencies配列は一切変更しない(名前
    テーブルへの追記+既存importのObjectNameインデックス差し替えのみ)。
    _patch_outfit_sk_materials(旧設計、新規import追記+PreloadDependencies
    再配線)より構造的に単純。

    U42: uexpは「無改変コピー」ではなく、_disable_subsurface_shading()を
    通した結果を書き出す(SSS系ShadingModelの無効化、G1実測根拠は
    TEMPLATE_BUILD_VERSIONコメント参照)。アンカー不一致等で無改変判定の
    場合はバイト内容が実質コピーと同じになるため、既存の「uexpはそのまま
    コピー」という設計意図は実効的に保たれる。"""
    with open(uasset_path, "rb") as f:
        data = f.read()
    with open(uexp_path, "rb") as f:
        uexp_bytes_orig = f.read()

    h = _parse_header_with_offsets(data)
    names, names_end = _read_name_table(data, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        raise _OutfitMaterialPatchError(f"name table end ({names_end}) != import_offset ({h.import_offset})")

    off = h.import_offset
    imports = []
    for _ in range(h.import_count):
        imp, off = _parse_import(data, off)
        imports.append(imp)
    if off != h.export_offset:
        raise _OutfitMaterialPatchError(f"import table end ({off}) != export_offset ({h.export_offset})")

    name_index = {s: i for i, s in enumerate(names)}

    base_tex_i = None
    for i, imp in enumerate(imports):
        cn = names[imp["class_name_idx"]] if 0 <= imp["class_name_idx"] < len(names) else None
        on = names[imp["object_name_idx"]] if 0 <= imp["object_name_idx"] < len(names) else None
        if cn == "Texture2D" and on and on.endswith("_B"):
            base_tex_i = i
            break
    if base_tex_i is None:
        raise _OutfitMaterialPatchError("Base Texture import (Texture2D with ObjectName ending in _B) not found")

    base_imp = imports[base_tex_i]
    outer_fpi = base_imp["outer_index"]
    if outer_fpi >= 0:
        raise _OutfitMaterialPatchError(f"unexpected: Base Texture import's outer is not an import: {outer_fpi}")
    pkg_i = -outer_fpi - 1
    pkg_imp = imports[pkg_i]
    if names[pkg_imp["class_name_idx"]] != "Package":
        raise _OutfitMaterialPatchError("Base Texture import's outer is not a Package (unexpected structure)")

    # U47: 「Subsurface Texture」importの再配線は廃止(上記docstring参照)。
    # importテーブル自体は一切触れず、参照先資産の中身だけを別途平坦化する
    # (_collect_flatten_targets/_flatten_normal_orm_textures)。

    new_names = []
    resolved = {}

    def resolve(s_):
        if s_ in name_index:
            resolved[s_] = name_index[s_]
        elif s_ not in resolved:
            resolved[s_] = h.name_count + len(new_names)
            new_names.append(s_)

    resolve(target_full_path)
    resolve(target_short_name)
    name_insert_bytes = b"".join(_encode_name(s_) for s_ in new_names)

    P1 = h.import_offset  # == names_end
    name_delta = len(name_insert_bytes)
    new_data = bytearray(data[:P1] + name_insert_bytes + data[P1:])

    def patch_i32(field_off, new_val):
        struct.pack_into("<i", new_data, field_off, new_val)

    def patch_i64(field_off, new_val):
        struct.pack_into("<q", new_data, field_off, new_val)

    # 既存import 2件(Package/Texture2D)のObjectNameだけを差し替える。
    # import構造体レイアウトは_parse_import/_encode_import通り(32byte):
    # class_package_idx(4)+pad(4)[0..8) / class_name_idx(4)+pad(4)[8..16) /
    # outer_index(4)[16..20) / object_name_idx(4)+pad(4)[20..28) /
    # b_import_optional(4)[28..32)。よってobject_name_idxはstart+20。
    # 挿入点(P1)より後ろにあるのでname_delta分シフトする。
    patch_i32(pkg_imp["start"] + name_delta + 20, resolved[target_full_path])
    patch_i32(base_imp["start"] + name_delta + 20, resolved[target_short_name])

    patch_i32(h.total_header_size_off, len(new_data))
    patch_i32(h.name_count_off, h.name_count + len(new_names))
    patch_i32(h.soft_object_paths_offset_off, P1 + name_delta)
    patch_i32(h.import_offset_off, P1 + name_delta)
    # import_count/export_countの値そのものは不変(新規importを追加しない
    # ため)。ただしdepends_offset等、挿入点より後ろに位置するテーブルへの
    # ポインタ(バイトオフセット)自体はname_delta分シフトが必要。
    patch_i32(h.export_offset_off, h.export_offset + name_delta)
    patch_i32(h.depends_offset_off, h.depends_offset + name_delta)

    if h.soft_package_references_offset != 0:
        patch_i32(h.soft_package_references_offset_off, h.soft_package_references_offset + name_delta)
    if h.searchable_names_offset != 0:
        patch_i32(h.searchable_names_offset_off, h.searchable_names_offset + name_delta)
    if h.thumbnail_table_offset != 0:
        patch_i32(h.thumbnail_table_offset_off, h.thumbnail_table_offset + name_delta)
    if h.asset_registry_data_offset != 0:
        patch_i32(h.asset_registry_data_offset_off, h.asset_registry_data_offset + name_delta)
    # BulkDataStartOffset/ExportMap SerialOffsetは「uasset+uexp仮想絶対
    # オフセット」規約(_patch_outfit_sk_materialsと同じ)。今回はuexpの
    # サイズを一切変えない(PreloadDependencies配列もexportも無改変)ため、
    # シフト量はuasset肥大化分(name_delta)のみでよい。
    patch_i64(h.bulk_data_start_offset_off, h.bulk_data_start_offset + name_delta)
    if h.world_tile_info_data_offset != 0:
        patch_i32(h.world_tile_info_data_offset_off, h.world_tile_info_data_offset + name_delta)
    if h.preload_dependency_offset != 0:
        patch_i32(h.preload_dependency_offset_off, h.preload_dependency_offset + name_delta)
    if h.payload_toc_offset != -1:
        patch_i64(h.payload_toc_offset_off, h.payload_toc_offset + name_delta)

    new_export_offset = h.export_offset + name_delta
    eoff = new_export_offset
    for _ in range(h.export_count):
        entry, eoff = puh.parse_export_entry(new_data, eoff)
        old_serial_offset = struct.unpack_from("<q", new_data, entry["serial_size_offset"] + 8)[0]
        struct.pack_into("<q", new_data, entry["serial_size_offset"] + 8, old_serial_offset + name_delta)

    if out_uasset_path != uasset_path:
        os.makedirs(os.path.dirname(out_uasset_path) or ".", exist_ok=True)
    with open(out_uasset_path, "wb") as f:
        f.write(new_data)

    # ShadingModel系のSubsurfaceProfile無効化(_disable_subsurface_shading)と、
    # U46: Subsurface Color(Vector)の白中和はuexpへ適用する
    # (Subsurface Textureのimport自体はU47で不変化、上記docstring参照)。
    patched_uexp, sm_sss_info = _disable_subsurface_shading(uexp_bytes_orig)
    patched_uexp, sc_info = _neutralize_named_vector_param(patched_uexp, names, "Subsurface Color")
    if out_uexp_path != uexp_path:
        os.makedirs(os.path.dirname(out_uexp_path) or ".", exist_ok=True)
    with open(out_uexp_path, "wb") as f:
        f.write(patched_uexp)
    sss_info = dict(sm_sss_info)
    sss_info["subsurface_color_neutralized"] = sc_info
    return {"skipped": False, "sss": sss_info}


# ============================================================================
# U46: Normal Map / MetallicRoughnessOcclusionSpecularTexture(ORM)を
# 参照先テクスチャ資産の同一パス・ペイロード置換で平坦な中立値へ差し替える。
# MI側(import table)は一切変更しない — 参照パス自体は元のバニラと同じ
# ままで、そのパスが指すテクスチャ資産の中身(pak内)だけをpak内で上書きする
# (V8哲学: 新規パッケージ禁止・同一パス差し替え)。
#
# G1実測(TEMPLATE_BUILD_VERSION手前のコメント参照)で、DXT1/BC5とも4x4
# ブロックの符号化バイト数は(w,h,pixel_format)のみで決まり内容非依存と
# 確定しているため、mipごとのヘッダ(オフセット/サイズ/inlineフラグ)は
# 一切変更せず、ミップ実体バイトだけを同じ長さの「平坦値」ブロックで
# 上書きする。ストリームミップ(.ubulk)も同じ操作をubulk側バイト列に
# 対して行うだけで、ファイル構造の変更(見出し・分割の作り直し)は不要。
# ============================================================================

_TEX_BLOCK_SIZE = {"PF_DXT1": 8, "PF_BC5": 16}


def _encode_flat_dxt1_block(r, g, b):
    """DXT1不透明ブロック(8byte)。color0==color1にすると補間先も同一色に
    なるため、index bitは全0で構わない(定数色ブロック)。"""
    def pack565(r, g, b):
        return ((r * 31 // 255) << 11) | ((g * 63 // 255) << 5) | (b * 31 // 255)
    c = pack565(r, g, b)
    return struct.pack("<HH", c, c) + b"\x00\x00\x00\x00"


def _encode_flat_bc5_block(r, g):
    """BC5(2チャンネル、Red block+Green blockの2×8byte=16byte)。各chは
    DXT5アルファブロックと同型: a0=a1=vにするとindex bitは全0で定数値になる
    (6値/8値モードの区別が無関係になる)。"""
    def flat_channel(v):
        return struct.pack("<BB", v, v) + b"\x00" * 6
    return flat_channel(r) + flat_channel(g)


def _flat_mip_bytes(pixel_format, w, h, value):
    """(w,h)のミップ全体を平坦値valueで埋めたエンコード済みバイト列を返す。
    value: PF_DXT1なら(r,g,b) 0-255タプル、PF_BC5なら(r,g) 0-255タプル。"""
    nbx, nby = (w + 3) // 4, (h + 3) // 4
    n_blocks = nbx * nby
    if pixel_format == "PF_DXT1":
        block = _encode_flat_dxt1_block(*value)
    elif pixel_format == "PF_BC5":
        block = _encode_flat_bc5_block(*value)
    else:
        raise _OutfitMaterialPatchError(f"unsupported pixel_format: {pixel_format}")
    return block * n_blocks


def _parse_texture_mips_lenient(uexp_bytes):
    """vp_core.parse_texture2dの緩和版: ストリームミップ(BULKDATA_
    ForceInlinePayload無し、実体は.ubulk側)も許容し、各ミップについて
    inline有無・(uexpローカル or ubulk絶対)オフセット・サイズ・w/hを返す。
    実測(work\\u46_diag、T_Player_Male_Body_M/N)により、非inlineミップの
    abs_offはubulkファイル先頭からの直接バイトオフセットであることを確認済み。
    戻り値: {"pixel_format","size_x","size_y","mips":[{"inline","offset","size","w","h"}]}"""
    data = uexp_bytes
    pf_off = -1
    i = data.find(b"PF_")
    while i >= 0:
        end = data.find(b"\x00", i)
        if i >= 4 and end > i:
            (slen,) = struct.unpack_from("<i", data, i - 4)
            if slen == end - i + 1:
                pf_off = i
                break
        i = data.find(b"PF_", end)
    if pf_off < 0:
        raise _OutfitMaterialPatchError("PF_ string not found (not a Texture2D uexp?)")
    pf = data[pf_off:data.find(b"\x00", pf_off)].decode("ascii")
    size_x, size_y = struct.unpack_from("<ii", data, pf_off - 16)

    pos = data.find(b"\x00", pf_off) + 1
    first_mip, num_mips = struct.unpack_from("<ii", data, pos)
    pos += 8
    if not (0 <= first_mip <= 16 and 1 <= num_mips <= 20):
        raise _OutfitMaterialPatchError(f"invalid mip count: first={first_mip} num={num_mips}")

    mips = []
    for mi in range(num_mips):
        (flags,) = struct.unpack_from("<I", data, pos)
        pos += 4
        if flags & 0x2000:
            count, size_on_disk = struct.unpack_from("<qq", data, pos)
            pos += 16
        else:
            count, size_on_disk = struct.unpack_from("<ii", data, pos)
            pos += 8
        (abs_off,) = struct.unpack_from("<q", data, pos)
        pos += 8
        inline = bool(flags & 0x40)
        if inline:
            local = pos
            pos += count
            w, h, z = struct.unpack_from("<iii", data, pos)
            pos += 12
            mips.append({"inline": True, "offset": local, "size": count, "w": w, "h": h})
        else:
            w, h, z = struct.unpack_from("<iii", data, pos)
            pos += 12
            mips.append({"inline": False, "offset": abs_off, "size": count, "w": w, "h": h})
        if z != 1:
            raise _OutfitMaterialPatchError(f"mip{mi}: invalid dimensions z={z}")
    return {"pixel_format": pf, "size_x": size_x, "size_y": size_y, "mips": mips}


def _flatten_cooked_texture(uexp_bytes, value, uasset_size):
    """uexpの全ミップを平坦値valueへ書き換え、かつ全ミップを
    BULKDATA_ForceInlinePayload(inline)へ強制変換した新uexpを返す
    (.ubulk不要化)。

    背景(U46): 元のバニラテクスチャ(2048解像度)は上位数ミップが.ubulkへ
    ストリーム格納されているが、preflight_pak.pyのG3は".ubulk"拡張子を
    カテゴリ的に全面禁止している(本プロジェクトのNeverStream方針、
    G8"テクスチャ実体(NeverStream焼き込み)"と同じ思想)。値が定数(平坦色)
    のため、そもそも高解像度ミップの実体差(ストリーミングの意義)が無く、
    全ミップをt00/t01同様の完全inlineへ再構成しても情報の損失は無い。

    DXT1/BC5とも4x4ブロックの符号化バイト数(count)は(w,h,format)のみで
    決まり内容非依存なので、countフィールド自体は変更不要。ただしabs_off
    (FPackageIndex的な絶対オフセット)は実測(vp_core.parse_texture2dの
    整合チェック、work\\u46_diag)により「uasset_size + uexp内local
    オフセット」で全ミップ一貫している(uasset+uexpを1本の仮想バイナリと
    見なす、本プロジェクト他所のSerialOffset規約と同型)ことを確認済みで、
    ubulk格納だったミップは全く別のアドレス体系(ubulkファイル内オフセット)
    だったため、inline化にあたり新しいlocalオフセットに基づき正しく
    再計算しないとvp_core.parse_texture2dの整合チェックに落ちる(ロード時に
    実際に使われるかは不明だが、本プロジェクト他所のSerialOffset同様
    ロード経路が参照する可能性がある値のため、安全側で正しく計算する)。
    ミップ毎のエントリを「flags=0x48(純粋にinlineのみ、後述) +
    count/size_on_disk(不変) + abs_off(新規計算) + ペイロード(平坦値、
    count byte) + w/h/z
    (不変)」として丸ごと再構築する(元が非inlineだったミップだけpayloadが
    新規追加されるため、後続バイト列は結果として後ろへずれるが、ミップ
    リストの外側(ヘッダ前半・末尾のPACKAGE_FILE_TAG等)は一切パースし直さず、
    区間コピーするだけで良い)。"""
    data = uexp_bytes
    pf_off = -1
    i = data.find(b"PF_")
    while i >= 0:
        end = data.find(b"\x00", i)
        if i >= 4 and end > i:
            (slen,) = struct.unpack_from("<i", data, i - 4)
            if slen == end - i + 1:
                pf_off = i
                break
        i = data.find(b"PF_", end)
    if pf_off < 0:
        raise _OutfitMaterialPatchError("PF_ string not found (not a Texture2D uexp?)")
    pf = data[pf_off:data.find(b"\x00", pf_off)].decode("ascii")

    pos = data.find(b"\x00", pf_off) + 1
    first_mip, num_mips = struct.unpack_from("<ii", data, pos)
    pos += 8
    if not (0 <= first_mip <= 16 and 1 <= num_mips <= 20):
        raise _OutfitMaterialPatchError(f"invalid mip count: first={first_mip} num={num_mips}")

    header_end = pos
    new_mips = bytearray()
    running_pos = header_end  # 再構築後uexp内での現在位置(新エントリのサイズを積算)
    for mi in range(num_mips):
        (flags,) = struct.unpack_from("<I", data, pos)
        pos += 4
        size64 = bool(flags & 0x2000)
        if size64:
            count, size_on_disk = struct.unpack_from("<qq", data, pos)
            pos += 16
        else:
            count, size_on_disk = struct.unpack_from("<ii", data, pos)
            pos += 8
        pos += 8  # 元abs_off(再計算するため読み捨て)
        inline = bool(flags & 0x40)
        if inline:
            pos += count  # 元payloadは読み飛ばす(新payloadで置き換えるため中身は不要)
        w, h, z = struct.unpack_from("<iii", data, pos)
        pos += 12
        if z != 1:
            raise _OutfitMaterialPatchError(f"mip{mi}: invalid dimensions z={z}")

        blob = _flat_mip_bytes(pf, w, h, value)
        if len(blob) != count:
            raise _OutfitMaterialPatchError(
                f"flat block size mismatch {w}x{h} {pf}: {len(blob)} != {count}")
        # U46実機クラッシュ(LowLevelFatalError AsyncLoading.cpp:3558 "Serial
        # size mismatch")の実測原因: 元の非inlineミップはflags=0x10501
        # (BULKDATA_PayloadAtEndOfFile|PayloadInSeperateFile|
        # Force_NOT_InlinePayload|NoOffsetFixUp)を持ち、単純に`flags|0x40`
        # (ForceInlinePayload)しただけではFORCE_NOT_InlinePayload等の
        # 矛盾するフラグが残ったままになり、ローダがinlineとして読まず
        # SerializeがTellを進めない(=Got側が小さくなる)。既存の元々inline
        # だったミップの実測フラグ(0x48 = BULKDATA_SingleUse|
        # ForceInlinePayload、他ビット無し)をそのまま採用し、由来を問わず
        # 全ミップに同一の「純粋にinlineのみ」フラグを与える(既にこの
        # ファイル内の別ミップで実機実証済みの値)。
        new_flags = 0x48
        count_field_size = 16 if size64 else 8
        new_local = running_pos + 4 + count_field_size + 8  # payload開始位置(新local)
        new_abs_off = uasset_size + new_local
        new_mips += struct.pack("<I", new_flags)
        if size64:
            new_mips += struct.pack("<qq", count, size_on_disk)
        else:
            new_mips += struct.pack("<ii", count, size_on_disk)
        new_mips += struct.pack("<q", new_abs_off)
        new_mips += blob
        new_mips += struct.pack("<iii", w, h, z)
        running_pos = new_local + count + 12

    tail = data[pos:]  # ミップリスト後(末尾フィールド+PACKAGE_FILE_TAG)は無改変で区間コピー
    new_data = data[:header_end] + bytes(new_mips) + tail
    (tag,) = struct.unpack_from("<I", new_data, len(new_data) - 4)
    if tag != 0x9E2A83C1:
        raise _OutfitMaterialPatchError("rebuilt uexp tail is not PACKAGE_FILE_TAG (range copy may be misaligned)")
    return bytes(new_data)


# U46: 平坦化する対象パラメータ名と中立値。G1実測(TEMPLATE_BUILD_VERSION
# 手前コメント参照)による: BC5法線は(128,128)でタンジェント空間の
# 直立法線(0,0,1相当)。ORMは R=Metallic=0 ・ **G=Roughness=最大(完全マット)** ・
# B=Occlusion=満値(未加工)。"Override Normal Mask 1/2/3"はNormal Map 1/2を
# ブレンドするマスクなので、両方のNormalを平坦化すればマスク値に関わらず
# 結果は平坦(マスク自体は無改変のままでよい、non-goal)。
#
# 【Roughness=最大の根拠】責任者裁定(2026-07-25):
#   「マテリアルを standard 相当とみなし、アバターのほとんどはテカるべきでは
#    ないから最大のラフネスにする」。
#   U50-single までは 140(≒0.55、中庸)が入っており、これは**仕様との
#   食い違い**だった。実機で「なんかてかてかしてますね」と指摘され発覚
#   (布は通常 0.8〜0.9、140 は金属寄りのツルツロ)。255 = 完全マット。
_NORMAL_PARAM_NAMES = ("Normal Map", "Override Normal Map 1", "Override Normal Map 2")
_NORMAL_FLAT_VALUE = (128, 128)          # PF_BC5 (R,G)
_ORM_PARAM_NAMES = ("MetallicRoughnessOcclusionSpecularTexture",)
_ORM_FLAT_VALUE = (0, 255, 255)          # PF_DXT1 (R=Metallic=0, G=Roughness=最大, B=Occlusion=255)

# U47: "Subsurface Texture"(素体MI_Player_{Gender}_Body系のみが持つ
# オーバーライド、実測: 男女とも/Player/Body/Female/T_Player_Female_Body_SSS
# を共有参照、PF_DXT1 2048x2048)を黒(0,0,0)へ平坦化し、TwoSidedFoliageの
# サブサーフェス寄与を実質ゼロへ抑える(TEMPLATE_BUILD_VERSION手前コメント
# 参照)。以前(U42)はこのパラメータの参照先をt00/t01(Base Textureと同じ
# アバター実写テクスチャ)へ再配線していたが、それが「地肌の色被り」の
# 実測上の原因だったため、U47でこの平坦化方式へ置き換えた
# (_patch_mi_base_textureのSSS再配線ロジックは削除済み)。
_SSS_PARAM_NAMES = ("Subsurface Texture",)
_SSS_FLAT_VALUE = (0, 0, 0)              # PF_DXT1 (R,G,B) = 黒(サブサーフェス寄与を最小化)
# U50-S1: 既定ON。切り分け用に環境変数D2P_U50_DISABLE_SSS_FLATTEN=1で
# Subsurface Textureの平坦化のみを無効化できる(Normal/ORMには影響しない)。
_SSS_FLATTEN_DISABLE = os.environ.get("D2P_U50_DISABLE_SSS_FLATTEN") == "1"


def _read_header_and_tables_for_flatten(uasset_path):
    """_collect_flatten_targets向けの最小限のuasset読み取り(name table+
    import table)。_find_outfit_slot_material_paths等の既存パース手順と同型。"""
    with open(uasset_path, "rb") as f:
        data = f.read()
    h = _parse_header_with_offsets(data)
    names, names_end = _read_name_table(data, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        raise _OutfitMaterialPatchError(f"name table end mismatch: {names_end} != {h.import_offset}")
    off = h.import_offset
    imports = []
    for _ in range(h.import_count):
        imp, off = _parse_import(data, off)
        imports.append(imp)
    if off != h.export_offset:
        raise _OutfitMaterialPatchError(f"import table end mismatch: {off} != {h.export_offset}")
    return h, names, imports


def _collect_flatten_targets(uexp_bytes, names, imports):
    """Normal/ORM/Subsurface Texture(U47)対象パラメータ名それぞれについて、
    _find_named_texture_param_fpiで参照先テクスチャの完全パッケージパスを
    特定し、{full_path: value}を返す(見つからない/一意でないものは無視、
    安全側スキップ)。"""
    targets = {}

    def resolve(param_name, value):
        _, fpi = _find_named_texture_param_fpi(uexp_bytes, names, param_name)
        if fpi is None or fpi >= 0:
            return
        i = -fpi - 1
        if not (0 <= i < len(imports)):
            return
        imp = imports[i]
        cn = names[imp["class_name_idx"]] if 0 <= imp["class_name_idx"] < len(names) else None
        if cn not in ("Texture2D", "Texture"):
            return
        outer_fpi = imp["outer_index"]
        if outer_fpi >= 0:
            return
        oi = -outer_fpi - 1
        if not (0 <= oi < len(imports)):
            return
        pkg_imp = imports[oi]
        if names[pkg_imp["class_name_idx"]] != "Package":
            return
        full_path = names[pkg_imp["object_name_idx"]]
        targets[full_path] = value

    for nm in _NORMAL_PARAM_NAMES:
        resolve(nm, _NORMAL_FLAT_VALUE)
    for nm in _ORM_PARAM_NAMES:
        resolve(nm, _ORM_FLAT_VALUE)
    if not _SSS_FLATTEN_DISABLE:
        for nm in _SSS_PARAM_NAMES:
            resolve(nm, _SSS_FLAT_VALUE)
    return targets


def _patch_texture_uasset_serial_size(uasset_bytes, new_uexp_size):
    """Texture2D uasset(export 1件前提)のExport TableエントリのSerialSize、
    およびBulkDataStartOffset(番兵値)を新uexpサイズへ更新する。

    U46実機クラッシュ(real=True dump有り、G3実機trial1)の実測原因:
    _flatten_cooked_textureでuexpを大きく(ストリームミップをinline化)
    しても、uassetのExport TableのSerialSize(実測: 元uexpサイズ-4=
    PACKAGE_FILE_TAG分を除いた値、work\\u46_diag\\tex_probe参照)を無改変の
    まま残すと、ロード時に期待サイズと実サイズが食い違いクラッシュする。
    BulkDataStartOffsetも実測でuasset_size+uexp_size-4と一致する番兵値
    (_patch_mi_base_textureのコメント参照、同一パターン)であり、同様に
    更新する。SerialOffset(uasset+uexp仮想絶対オフセット)はuasset自体の
    サイズを変えないため不変のままでよい。"""
    h = _parse_header_with_offsets(uasset_bytes)
    if h.export_count != 1:
        raise _OutfitMaterialPatchError(
            f"Texture2D uasset export count is not 1 (unexpected): {h.export_count}")
    off = h.export_offset
    entry, _ = puh.parse_export_entry(uasset_bytes, off)
    new_serial_size = new_uexp_size - 4  # 末尾PACKAGE_FILE_TAG(4byte)を除く(実測確認済み)
    new_bulk_data_start_offset = len(uasset_bytes) + new_uexp_size - 4
    data = bytearray(uasset_bytes)
    struct.pack_into("<q", data, entry["serial_size_offset"], new_serial_size)
    struct.pack_into("<q", data, h.bulk_data_start_offset_off, new_bulk_data_start_offset)
    return bytes(data)


def _flatten_normal_orm_textures(dst_dir, pak, flatten_targets):
    """flatten_targets({full_path: value})の各テクスチャ資産を、pakから
    その場抽出(uasset+uexp。.ubulkは抽出しない)し、uexpの全ミップを平坦値・
    完全inlineへ再構築してdst_dir内の同一相対パスへ書く(同一パス差し替え
    でMI側のimportは一切変更不要)。uasset自体はExport TableのSerialSize
    フィールドのみ新uexpサイズに合わせて更新する(_patch_texture_uasset_
    serial_size、実機クラッシュの実測原因への対処)。.ubulkは出力しない
    (全ミップinline化によりストリーム分割自体が不要になるため。
    preflight_pak.pyのG3は.ubulk拡張子を全面禁止しており、これを回避する
    設計でもある)。"""
    def game_path_to_pak_rel(full_path):
        prefix = "/Game/Pal/Model/Character/"
        if not full_path.startswith(prefix):
            raise _OutfitMaterialPatchError(f"unexpected package path: {full_path}")
        return full_path[len(prefix):]

    pak_paths = []
    rel_of = {}
    for full_path in flatten_targets:
        rel = game_path_to_pak_rel(full_path)
        rel_of[full_path] = rel
        pak_paths.append(PAK_PREFIX + rel + ".uasset")
        pak_paths.append(PAK_PREFIX + rel + ".uexp")

    extracted = pak_live_extract.extract_files(pak, pak_paths)

    n_ok = 0
    for full_path, value in sorted(flatten_targets.items()):
        rel = rel_of[full_path]
        p_uasset = PAK_PREFIX + rel + ".uasset"
        p_uexp = PAK_PREFIX + rel + ".uexp"
        if p_uasset not in extracted or p_uexp not in extracted:
            raise _OutfitMaterialPatchError(f"texture not found in vanilla pak: {full_path}")
        new_uexp = _flatten_cooked_texture(extracted[p_uexp], value, len(extracted[p_uasset]))
        new_uasset = _patch_texture_uasset_serial_size(extracted[p_uasset], len(new_uexp))
        out_path = os.path.join(dst_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path + ".uasset", "wb") as f:
            f.write(new_uasset)
        with open(out_path + ".uexp", "wb") as f:
            f.write(new_uexp)
        n_ok += 1
    print(f"[{TAG}] U46/U47: replaced Normal/ORM/Subsurface textures with flat-value, fully-inline "
          f"versions (.ubulk unused): {n_ok}")
    return n_ok


# ============================================================================
# U50 Phase1(案B、docs\U50_PHASE1_INSTRUCTIONS.md): 素体MI 2件
# (MI_Player_{Male,Female}_Body)を、バニラMI差し替え(_patch_mi_base_texture)
# ではなく、pakへ同梱済みの自前cook済みMIC(noue_variants/Lit2S/M_VP_m00、
# 親はM_VP_m00_LitMaster2S)を同一パッケージパスへ複製して置く方式へ切り替える。
# ロジックはwork\u50_diag\p0b\clone_mic_proto.py::clone_mic()で3パス
# 実機外検証済み(import全件フルパス一致・新規importゼロ・PreloadDependencies
# 生バイト完全一致・全オフセット整合・uexp無改変)であり、ここではそのロジックを
# そのまま移植する(P1-1、作り直さない)。
# ============================================================================

# U50-S0(2026-07-25、docs\U50_PHASE1_INSTRUCTIONS.md後継の診断タスク):
# Phase1のMICクローンは実機で「UEのマテリアルエラー」(肌/耳/手がテクスチャ
# 無しののっぺり状態)を引き起こすことが確認されており、既定ONのままでは
# 壊れた素体マテリアルが出る。よって既定OFFへ反転し、切り分け実験時のみ
# 環境変数D2P_U50_P1_ENABLE_BODY_MIC_CLONE=1で明示的にONにする形へ変更した
# (コードは残す。旧DISABLE変数も後方互換のため残置するが、既定OFF化により
# 通常は無意味)。
_U50_P1_BODY_MIC_CLONE_ENABLE = os.environ.get("D2P_U50_P1_ENABLE_BODY_MIC_CLONE") == "1"
_U50_P1_BODY_MIC_CLONE_DISABLE = os.environ.get("D2P_U50_P1_DISABLE_BODY_MIC_CLONE") == "1"

# U50 Phase1-B実験(2026-07-25、指揮者の口頭指示によるA/B切り分け実験):
# Phase1で素体2件が「UEのマテリアルエラー」(肌/耳/手がテクスチャ無しの
# のっぺり状態)になった原因が (甲)クローン・改名機構 と (乙)M_VP資産 の
# どちらかを切り分けるための実験モード。既定OFF(Phase1の挙動に一切影響
# しない)。D2P_U50_EXP_VANILLA_CLONE=1 を設定すると、素体2件について
# M_VP_m00ではなく「バニラの素体MI自身」のバイトを _clone_mvp_mic_as
# (force_rename_insert=True)へ通し、同じパッケージパス・同じ名前へ
# 複製し直す。中身(親マテリアル・パラメータ)は一切変えず、ShadowLiftの
# 焼き込みも行わない(交絡変数ゼロ、変わるのは「クローン機構を通過した
# かどうか」だけ)。Phase1のM_VP_m00クローン経路(p1_body_mic_clone_eligible)
# より優先する。
_U50_EXP_VANILLA_CLONE = os.environ.get("D2P_U50_EXP_VANILLA_CLONE") == "1"

# U50 単体Material実験(モジュールdocstring/TEMPLATE_BUILD_VERSIONコメント
# 参照)。既定OFF。ONの場合、素体2件について「UEモードが本日このマシンで
# cookした自己完結Material」のバイトを_clone_mvp_mic_as(force_rename_insert
# =False、Phase1本体と同じ既定)へ通して複製する。Phase1本体・Phase1-B
# 実験のいずれよりも優先される最上位の分岐。
_U50_SINGLE_MATERIAL = os.environ.get("D2P_U50_SINGLE_MATERIAL") == "1"
_U50_SINGLE_MATERIAL_SRC_DIR = os.path.join(HERE, "..", "..", "work", "u50_diag", "mvp", "alive")

# ---------------------------------------------------------------------------
# U50-unify(2026-07-25、既定ON): 素体スロット(t00)と衣装スロット(t01)の
# マテリアルを構造的に統一する。
#
# 背景: U40〜U49の「各衣装のバニラMIを持ってきてBase Textureだけ向け直す」
# 方式では、素体スロットが参照するMI(MI_Player_{Male,Female}_Body、
# ShadingModel=6 TwoSidedFoliage、親も別)と衣装スロットのMIとで
# シェーディングモデル・パラメータがまるごと違うため、同じテクスチャを
# 貼っても素体だけ暗く沈む。値を寄せて合わせにいくのではなく、
# 「両スロットに同じ親・同じ全パラメータのMIを割り当て、違うのは
# Base Texture(t00/t01)だけ」にすることで構造的に解消する
# (work\u50_unify\SHADOW_REPORT.md、実機官能検査合格)。
#
# 実装: 1つのバニラ衣装MI(UNIFY_SRC_GAME_PATH)を
#   _patch_mi_base_texture(→t00 / →t01) → vp_matparam(パラメータ調整)
#   → _clone_mvp_mic_as(→各対象パッケージパス)
# という同一の処理系に通し、スロット対象MIパス全件へ書き戻す。
#
# shadow_lift(k)の実装: UEのM_VPが持つ式そのまま
#   BaseColor = A×(1-k) / Emissive Texture Intensity = A×k
#   (A = UNIFY_BASECOLOR_A = 0.598958 = このバニラMIのBaseColor)
# で、Emissive Texture には Base Texture と同一のオブジェクト(t00/t01)を
# 挿入する。**k=0 のときは ops が空になり、MIバイトは一切変更されない**
# (=統一のみ適用した状態と完全にバイト一致する)。
# k=1.0 で実機の環境光被りが R/G=1.0000 まで消える(真のunlit)ことは
# work\u50_unify\shadow_metrics.txt で実測済み。
#
# D2P_U50_DISABLE_UNIFY=1 で従来挙動(統一なし)へ戻せる(切り分け用)。
_U50_UNIFY_DISABLE = os.environ.get("D2P_U50_DISABLE_UNIFY") == "1"
UNIFY_SRC_GAME_PATH = ("/Game/Pal/Model/Character/Player/Outfit/"
                       "SK_Player_Female_Outfit_OldCloth001/v01/"
                       "MI_Player_Female_Outfit_OldCloth001_v01_M02")
# このバニラMIのBaseColor(実測、work\u50_unify\SHADOW_REPORT.md §2)。
# 2026-07-25: 0.598958 はバニラ衣装マテリアルが持っていた減光。
# 1.0 = テクスチャそのまま。
UNIFY_BASECOLOR_A = 1.0

# ---------------------------------------------------------------------------
# U50-single: UE版マテリアル仕様「マット化Lit(Roughness=1 / Specular=0)」の移植。
#
# 正本は `pipeline\py\ue_archive\vp_ue_mat.py`(dev#114でpipeline\ueから移設)の
# make_material():
#     rough = Constant(1.0) -> MP_ROUGHNESS
#     spec  = Constant(0.0) -> MP_SPECULAR
# (docstring も「マット化Lit(Roughness=1/Specular=0)」と明記している)
#
# noue 側への対応:
#   Roughness=1.0 -> ORM テクスチャの G チャンネルを 255 へ平坦化
#                    (_ORM_FLAT_VALUE。U50-single で 140 から修正)
#   Specular=0.0  -> **テクスチャでは表現できない**。ORM は PF_DXT1 であり
#                    アルファチャンネルを持たない = デコード時 A=1.0 に
#                    なるため、マスターが ORM.A を Specular に使っている場合
#                    Specular は常に 1.0(UE仕様 0.0 の正反対)になる。
#                    そこで **MI のスカラーパラメータ "Specular" を 0.0 で
#                    上書きする**(バニラにも Ancient001 系が 0.2 を設定して
#                    いる実在のパラメータであることを実測確認済み)。
# D2P_U50_NO_SPECULAR_ZERO=1 でこの上書きだけを止められる(切り分け用)。
_U50_NO_SPECULAR_ZERO = os.environ.get("D2P_U50_NO_SPECULAR_ZERO") == "1"
UNIFY_SPECULAR = 0.0


def unify_shadow_ops(shadow_lift, unlit=False):
    """shadow_lift(0.0-1.0)から vp_matparam 用の編集opsを作る。

    k=0 なら**空リスト**を返す = MIバイトを一切変更しない。
    これが「shadow_lift=0 は従来と完全に同一」を構造的に保証している。

    **unlit=True は k=1.0 として扱う**(2026-07-26 責任者裁定)。
    `unlit` は元々 UEモードで マスターを MSM_UNLIT へ切り替えるための設定だった。
    noue ではシェーディングモデルを差し替えられないが、Emissive 100%(k=1.0)が
    その等価物である —— 実測で k=1.0 のとき白い襟の R/G が 1.0000 になり、
    環境光の被りが完全に消える(= 真の unlit)ことを確認済み
    (work\\u50_unify\\shadow_metrics.txt)。
    したがって unlit=true の古い job.json は「影なしで作られたアバター」として
    影なしのまま再現される。**unlit は「触らない側(k=0)」ではなく
    「触る側(k=1.0)」に落ちる。**shadow_lift の値は無視する(unlit が優先)。

    (旧実装は unlit を k=0 扱いにしていた。UE版M_VP の
     `k = 0.0 if C.UNLIT else C.SHADOW_LIFT` と vp_texinject.shadow_lift_gain()
     に揃えたものだったが、あれは「UE側でシェーディングモデルを変えるので
     k は不要」という前提の式であり、noue では影が消えないという逆の結果になる)"""
    if unlit:
        k = 1.0
    else:
        k = max(0.0, min(1.0, float(shadow_lift or 0.0)))
    if k <= 0.0:
        return [], 0.0
    base = UNIFY_BASECOLOR_A * (1.0 - k)
    emis = UNIFY_BASECOLOR_A * k
    return ([("vector", "BaseColor", (base, base, base, 1.0)),
             ("emissive_from_base",),
             ("scalar", "Emissive Texture Intensity", emis)], k)


def collect_unified_mi_targets(dst_dir, manifest, limit=2):
    """U50-single: 注入対象の衣装SKが描画スロットで参照するバニラMIパスを
    全部集める(重複排除・順序安定)。スロット役の割り当ても競合ガードも無い。"""
    import vp_exclusions
    targets = []
    seen = set()
    skipped = []
    excluded = []
    outfit_uassets = sorted(
        rel for rel in manifest["vanilla"]
        if rel.startswith("Player/Outfit/") and rel.endswith(".uasset"))
    for rel in outfit_uassets:
        # U50: 非対応(コラボ系)のSKはMIも差し替えない=バニラの装備がそのまま出る
        if vp_exclusions.is_excluded(rel):
            excluded.append(rel)
            continue
        ua = os.path.join(dst_dir, *rel.split("/"))
        ue = ua[:-len(".uasset")] + ".uexp"
        try:
            paths = find_outfit_material_paths_all(ua, ue, limit=limit)
        except _OutfitMaterialPatchError as e:
            skipped.append(f"{rel} ({e})")
            continue
        for p in paths:
            if p not in seen:
                seen.add(p)
                targets.append(p)
    if excluded:
        print(f"[{TAG}] U50: excluded from MI replacement (unsupported/collab items): {len(excluded)}: "
              f"{[os.path.basename(r) for r in excluded]}")
    return targets, skipped


def _mi_targets_cache_path(dst_dir):
    """テンプレート本体を汚さないよう、フィンガープリントと同じく**兄弟ファイル**
    に置く(dst_dir内に置くとpakへ1件混入してpreflight G2が落ちる。U18実測)。"""
    return dst_dir.rstrip("\\/") + ".mi_targets.json"


def collect_unified_mi_targets_cached(dst_dir, manifest, limit=2):
    """U50-fast(2026-07-26): collect_unified_mi_targets の結果を使い回す。

    この関数はテンプレート内の衣装SK 58件を実際に開いて参照MIパスを読むため
    [実測] 約14秒かかる。影の濃さ(shadow_lift)を振るたびに払うには高すぎる。
    結果は**テンプレートの内容だけ**で決まるので、テンプレートの
    フィンガープリント(pak/manifest/版)をそのまま鍵にしてキャッシュできる。

    フィンガープリントが無い(=ライブ抽出でないテンプレート)ときは
    キャッシュを使わず毎回計算する(鍵が作れないため。安全側)。
    """
    fp_path = dst_dir.rstrip("\\/") + ".fingerprint.json"
    key = None
    if os.path.exists(fp_path):
        with open(fp_path, encoding="utf-8") as f:
            key = f.read()
    cache_path = _mi_targets_cache_path(dst_dir)
    if key is not None and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fingerprint") == key:
                print(f"[{TAG}] U50-fast: reusing {len(cached['targets'])} MI replacement target(s) "
                      f"from cache (template unchanged) -> {cache_path}")
                return list(cached["targets"]), list(cached["skipped"])
        except (ValueError, KeyError, OSError) as e:
            print(f"[{TAG}][WARN] could not read MI target cache ({e}). Rebuilding")
    targets, skipped = collect_unified_mi_targets(dst_dir, manifest, limit=limit)
    if key is not None:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"fingerprint": key, "targets": targets,
                           "skipped": skipped}, f, ensure_ascii=False)
        except OSError as e:
            print(f"[{TAG}][WARN] could not write MI target cache ({e}). Will rebuild next time too")
    return targets, skipped


def unify_base_ops():
    """統一MIに**常に**掛ける、shadow_liftに依存しない編集op。

    UE版仕様(`pipeline\\py\\ue_archive\\vp_ue_mat.py`「マット化Lit(Roughness=1/Specular=0)」)
    の Specular 側。Roughness側はORMテクスチャの平坦化で実現している。"""
    if _U50_NO_SPECULAR_ZERO:
        return []
    return [("scalar", "Specular", UNIFY_SPECULAR)]


def build_unified_mi_variant(pak, ops, tmp_dir):
    """統一MIの元バイト(t00向き + ops適用済み)を1つ作って返す。

    SRC(バニラ衣装MI)→ _patch_mi_base_texture(t00)→ vp_matparam(ops)
    という、テンプレート側と高速差し替え側で**完全に同じ**手順。"""
    import vp_matparam
    src_rel = UNIFY_SRC_GAME_PATH[len("/Game/Pal/Model/Character/"):]
    keys = [PAK_PREFIX + src_rel + ".uasset", PAK_PREFIX + src_rel + ".uexp"]
    got = pak_live_extract.extract_files(pak, keys)
    if keys[0] not in got or keys[1] not in got:
        raise _OutfitMaterialPatchError(
            f"the vanilla MI used as the unification base is not in the pak: {UNIFY_SRC_GAME_PATH}")
    os.makedirs(tmp_dir, exist_ok=True)
    src_ua = os.path.join(tmp_dir, "src.uasset")
    src_ue = os.path.join(tmp_dir, "src.uexp")
    with open(src_ua, "wb") as f:
        f.write(got[keys[0]])
    with open(src_ue, "wb") as f:
        f.write(got[keys[1]])
    out_ua = os.path.join(tmp_dir, "patched_t00.uasset")
    out_ue = os.path.join(tmp_dir, "patched_t00.uexp")
    _patch_mi_base_texture(src_ua, src_ue, out_ua, out_ue,
                           MVP_PACKAGE_PREFIX + "/t00", "t00")
    with open(out_ua, "rb") as f:
        va = f.read()
    with open(out_ue, "rb") as f:
        ve = f.read()
    oplog = []
    if ops:
        va, ve, oplog = vp_matparam.edit_material_instance(va, ve, ops)
    return va, ve, oplog


def write_unified_mis(targets, va, ve, out_root):
    """統一MIの元バイトを、各対象パッケージパスへ改名複製して書き出す。"""
    n = 0
    for full_path in targets:
        new_uasset, new_uexp = _clone_mvp_mic_as(va, ve, full_path)
        rel = full_path[len("/Game/Pal/Model/Character/"):]
        out_path = os.path.join(out_root, *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path + ".uasset", "wb") as f:
            f.write(new_uasset)
        with open(out_path + ".uexp", "wb") as f:
            f.write(new_uexp)
        n += 1
    return n


def _unify_slot_materials(dst_dir, pak, manifest, job):
    """U50-single(2026-07-25、責任者裁定): 注入対象衣装SKの**描画スロットが
    参照するMIを全件**、1つのバニラ衣装MI(UNIFY_SRC_GAME_PATH)から派生した
    **たった1種類**のMIで置き換える。Base Texture は全件 t00。

    これにより:
      - 「同じMIが別SKで別スロット役」という競合が起こりえない
        → 競合ガードで今までpakに入らなかったMI(Plastic001のM01 4件と
          Kigurumi001のMI 1件)も収録され、実測NG 16件が 0件になる
          (work\\u50_equip\\out\\FINDINGS2.txt 5節)
      - 素体MIの名前ベース強制解決(_FORCED_BODY_MI_SUFFIXES)も不要

    _inject_outfit_body_parka_textures の従来ループ(+Normal/ORM平坦化)の
    **後**に呼ぶ。平坦化対象の収集はバニラMIから行う必要があるため順序は
    変えられない(work\\u50_unify\\ で実機検証したときと同じ順序)。

    **U50-fast(2026-07-26): ここでは shadow_lift を焼き込まない。**
    影の濃さはエンドユーザーがほぼ唯一いじる項目なので、パイプライン中
    もっとも重いテンプレート再構築(879ファイル/約700MB)に載せてはいけない。
    k依存の差し替えは `build_shadow_mi_overrides()` が pak 化直前に行う
    (build_pak_from_avatar の --mi-override-dir、mat_override_dir と同じ形)。
    その結果**テンプレートは shadow_lift に依存しない**ので、
    フィンガープリントからも外せる。"""
    ops = unify_base_ops()
    targets, skipped = collect_unified_mi_targets(dst_dir, manifest)
    if skipped:
        print(f"[{TAG}] U50-single: SK where MI path detection failed: {len(skipped)}: {skipped}")
    if not targets:
        raise _OutfitMaterialPatchError("no MI path found to unify")

    tmp_dir = dst_dir.rstrip("\\/") + "_unify_tmp"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    va, ve, oplog = build_unified_mi_variant(pak, ops, tmp_dir)
    for line in oplog:
        print(f"[{TAG}] U50-single   {line}")
    n = write_unified_mis(targets, va, ve, dst_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"[{TAG}] U50-single: replaced {n} draw-slot-referenced MI with **one** unified MI (SRC="
          f"{UNIFY_SRC_GAME_PATH.rsplit('/', 1)[-1]}, Base Texture=t00) "
          f"(shadow_lift-independent. Shadow depth is patched right before pak generation)")
    print(f"[{TAG}] U50-single:   variant uexp sha1={hashlib.sha1(ve).hexdigest()}")


def build_shadow_mi_overrides(job, dst_dir, out_dir, pak=None, manifest=None):
    """U50-fast(2026-07-26): shadow_lift(k)を焼き込んだ統一MIだけを
    `out_dir` へ書き出す(**テンプレートには触らない**)。

    返り値: (out_dir or None, n_files, info)
      k=0(または unlit)なら **(None, 0, ...)** を返し、1バイトも書かない。
      → テンプレートのMI(k非依存)がそのまま使われる。
      「k=0 のときMIを一切触らない」という構造的保証はここで維持されている。

    速度: バニラpakからMI 2ファイルを抽出 → パッチ → 79件へ改名複製、だけ。
    実測1秒未満。テンプレート再構築(数分)は不要になる。

    **out_dir は毎回まず空にする。**k を 0.7 → 0.0 へ戻したときに前回の
    差し替えファイルが残っていると「値を戻したのに効かない」という、
    テンプレート再利用と同じ形のバグになるため(k=0 の早期returnより前に
    消す必要がある)。
    """
    k_ops, k = unify_shadow_ops(job.get("shadow_lift", 0.0),
                                unlit=bool(job.get("unlit", False)))
    info = {"k": k, "n": 0, "uexp_sha1": None}
    tmp_dir = out_dir.rstrip("\\/") + "_tmp"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    if _U50_UNIFY_DISABLE:
        # 統一を切っているテンプレートへ統一MIだけ差し込むと、切り分けの
        # 意図(統一なしの絵を見る)を無言で壊す。何もしない。
        print(f"[{TAG}] U50-fast: D2P_U50_DISABLE_UNIFY=1, skipping shadow-depth "
              f"MI replacement (using the old path)")
        return None, 0, info
    if not k_ops:
        print(f"[{TAG}] U50-fast: shadow_lift k={k:.4f} -> no MI replacement needed "
              f"(using the template's unified MI as-is)")
        return None, 0, info
    if pak is None:
        pak = job["paths"]["palworld_pak"]
    if manifest is None:
        manifest = _load_manifest()
    targets, _skipped = collect_unified_mi_targets_cached(dst_dir, manifest)
    if not targets:
        raise _OutfitMaterialPatchError("no MI path found to unify")

    ops = unify_base_ops() + k_ops
    os.makedirs(out_dir, exist_ok=True)
    va, ve, oplog = build_unified_mi_variant(pak, ops, tmp_dir)
    for line in oplog:
        print(f"[{TAG}] U50-fast   {line}")
    n = write_unified_mis(targets, va, ve, out_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    info["n"] = n
    info["uexp_sha1"] = hashlib.sha1(ve).hexdigest()
    print(f"[{TAG}] U50-fast: baked shadow depth k={k:.4f} into {n} unified MI "
          f"(BaseColor={UNIFY_BASECOLOR_A * (1 - k):.6f} / "
          f"Emissive={UNIFY_BASECOLOR_A * k:.6f}) -> {out_dir}")
    print(f"[{TAG}] U50-fast:   variant uexp sha1={info['uexp_sha1']}")
    return out_dir, n, info


def _mic_clone_encode_fstring_ascii(s):
    """FPackageFileSummary.PackageNameのような素のFString(NameMapのFName
    エントリと異なりハッシュ4byte suffixを持たない)をエンコードする。
    clone_mic_proto.py::_encode_fstring_asciiと同一ロジック(移植のみ)。"""
    b = s.encode("ascii") + b"\x00"
    return struct.pack("<i", len(b)) + b


def _mic_clone_patch_package_name(data, new_package_path):
    """FPackageFileSummary.PackageNameフィールド(TotalHeaderSize直後、
    NameMapより前方に位置する素のFString)をnew_package_pathへ書き換え、
    後続の全オフセットフィールド(位置shift+値shift)をパッチする。
    clone_mic_proto.py::_patch_package_nameと同一ロジック(移植のみ)。"""
    h = _parse_header_with_offsets(data)

    P1 = h.total_header_size_off + 4  # TotalHeaderSize(i32)直後 = package_name fstring開始位置
    old_slen = struct.unpack_from("<i", data, P1)[0]
    if old_slen <= 0:
        raise _OutfitMaterialPatchError(
            f"unexpected package_name encoding (slen={old_slen}): non-ASCII/empty strings are out of scope for this port")
    old_encoded_len = 4 + old_slen
    old_end = P1 + old_encoded_len
    old_value = data[P1 + 4:P1 + old_encoded_len - 1].decode("ascii", errors="replace")

    new_encoded = _mic_clone_encode_fstring_ascii(new_package_path)
    delta = len(new_encoded) - old_encoded_len

    new_data = bytearray(data[:P1] + new_encoded + data[old_end:])

    old_ths = struct.unpack_from("<i", new_data, h.total_header_size_off)[0]
    struct.pack_into("<i", new_data, h.total_header_size_off, old_ths + delta)

    def patch_i32_value(old_off, add):
        new_off = old_off + delta
        old_val = struct.unpack_from("<i", new_data, new_off)[0]
        struct.pack_into("<i", new_data, new_off, old_val + add)

    def patch_i64_value(old_off, add):
        new_off = old_off + delta
        old_val = struct.unpack_from("<q", new_data, new_off)[0]
        struct.pack_into("<q", new_data, new_off, old_val + add)

    patch_i32_value(h.name_offset_off, delta)
    patch_i32_value(h.soft_object_paths_offset_off, delta)
    patch_i32_value(h.export_offset_off, delta)
    patch_i32_value(h.import_offset_off, delta)
    patch_i32_value(h.depends_offset_off, delta)
    if h.soft_package_references_offset != 0:
        patch_i32_value(h.soft_package_references_offset_off, delta)
    if h.searchable_names_offset != 0:
        patch_i32_value(h.searchable_names_offset_off, delta)
    if h.thumbnail_table_offset != 0:
        patch_i32_value(h.thumbnail_table_offset_off, delta)
    if h.asset_registry_data_offset != 0:
        patch_i32_value(h.asset_registry_data_offset_off, delta)
    patch_i64_value(h.bulk_data_start_offset_off, delta)
    if h.world_tile_info_data_offset != 0:
        patch_i32_value(h.world_tile_info_data_offset_off, delta)
    if h.preload_dependency_offset != 0:
        patch_i32_value(h.preload_dependency_offset_off, delta)
    if h.payload_toc_offset != -1:
        patch_i64_value(h.payload_toc_offset_off, delta)

    # export table: 各エントリのSerialOffset(絶対仮想オフセット)をdelta分シフト
    new_export_offset = h.export_offset + delta
    eoff = new_export_offset
    for _ in range(h.export_count):
        entry, eoff = puh.parse_export_entry(new_data, eoff)
        old_so = struct.unpack_from("<q", new_data, entry["serial_size_offset"] + 8)[0]
        struct.pack_into("<q", new_data, entry["serial_size_offset"] + 8, old_so + delta)

    return new_data, old_value, delta


def _mic_clone_rename_export0(data, new_name, force_insert=False):
    """export[0].ObjectNameをnew_nameへ付け替える(NameMap末尾追記+
    import_offset以降のオフセットシフト)。clone_mic_proto.py::
    _rename_export0と同一ロジック(移植のみ)。

    force_insert: U50 Phase1-B実験専用(既定False、Phase1本体の挙動は不変)。
    Trueにすると、new_nameが既にNameMapに存在していても「既存インデックス
    流用で何もしない」早期リターンを取らず、常にNameMap末尾へ新規追記して
    export[0]のインデックスをそちらへ張り替える。同名へ改名する場合でも
    NameMap追記+package_name書き換え+全オフセットシフトの機構を実際に
    実行させ、内容は変えずに「機構を通したかどうか」だけを切り分けるための
    フラグ(U50 Phase1-B実験、docs\\U50_PHASE1_REPORT.md追記参照)。"""
    h = _parse_header_with_offsets(data)
    names, names_end = _read_name_table(data, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        raise _OutfitMaterialPatchError(f"name table end ({names_end}) != import_offset ({h.import_offset})")

    name_index = {s: i for i, s in enumerate(names)}
    if new_name in name_index and not force_insert:
        new_name_idx = name_index[new_name]
        name_insert_bytes = b""
    else:
        new_name_idx = h.name_count
        name_insert_bytes = _encode_name(new_name)
    name_delta = len(name_insert_bytes)

    P1 = h.import_offset
    new_data = bytearray(data[:P1] + name_insert_bytes + data[P1:])

    def patch_i32(field_off, new_val):
        struct.pack_into("<i", new_data, field_off, new_val)

    def patch_i64(field_off, new_val):
        struct.pack_into("<q", new_data, field_off, new_val)

    patch_i32(h.total_header_size_off, len(new_data))
    patch_i32(h.name_count_off, h.name_count + (1 if name_insert_bytes else 0))
    patch_i32(h.soft_object_paths_offset_off, P1 + name_delta)
    patch_i32(h.import_offset_off, P1 + name_delta)
    patch_i32(h.export_offset_off, h.export_offset + name_delta)
    patch_i32(h.depends_offset_off, h.depends_offset + name_delta)
    if h.soft_package_references_offset != 0:
        patch_i32(h.soft_package_references_offset_off, h.soft_package_references_offset + name_delta)
    if h.searchable_names_offset != 0:
        patch_i32(h.searchable_names_offset_off, h.searchable_names_offset + name_delta)
    if h.thumbnail_table_offset != 0:
        patch_i32(h.thumbnail_table_offset_off, h.thumbnail_table_offset + name_delta)
    if h.asset_registry_data_offset != 0:
        patch_i32(h.asset_registry_data_offset_off, h.asset_registry_data_offset + name_delta)
    patch_i64(h.bulk_data_start_offset_off, h.bulk_data_start_offset + name_delta)
    if h.world_tile_info_data_offset != 0:
        patch_i32(h.world_tile_info_data_offset_off, h.world_tile_info_data_offset + name_delta)
    if h.preload_dependency_offset != 0:
        patch_i32(h.preload_dependency_offset_off, h.preload_dependency_offset + name_delta)
    if h.payload_toc_offset != -1:
        patch_i64(h.payload_toc_offset_off, h.payload_toc_offset + name_delta)

    new_export_offset = h.export_offset + name_delta
    eoff = new_export_offset
    for i in range(h.export_count):
        entry, eoff = puh.parse_export_entry(new_data, eoff)
        old_serial_offset = struct.unpack_from("<q", new_data, entry["serial_size_offset"] + 8)[0]
        struct.pack_into("<q", new_data, entry["serial_size_offset"] + 8, old_serial_offset + name_delta)
        if i == 0:
            struct.pack_into("<i", new_data, entry["start"] + 16, new_name_idx)

    return new_data


def _clone_mvp_mic_as(src_uasset_bytes, src_uexp_bytes, target_package_path, force_rename_insert=False):
    """M_VP_m00(Lit2S)のcook済みMICバイトを、別パッケージパスへ複製する
    (P1-1)。export[0].ObjectNameの付け替え+FPackageFileSummary.PackageName
    の書き換えのみを行う。import/PreloadDependencies/uexpは無改変
    (検証済み、work\\u50_diag\\p0b\\clone_mic_proto.py::clone_mic参照。
    新規importゼロ・PreloadDependencies生バイト完全一致)。
    戻り値: (uasset_bytes, uexp_bytes)。uexp_bytesはsrc_uexp_bytesと同一
    (このレベルでは無加工。ShadowLiftの焼き込みは呼び出し側の責務、
    _mic_patch_shadow_lift参照、P1-2)。

    force_rename_insert: U50 Phase1-B実験専用(既定False)。Trueにすると
    _mic_clone_rename_export0のforce_insertへそのまま渡り、target_package_path
    のobject_nameがsrc側と同名(=同じ名前へ改名)でもNameMap追記/
    package_name書き換え/オフセットシフトの機構を実際に実行させる
    (「同名だから早期リターンで素通り」を防ぐ)。"""
    object_name = target_package_path.rsplit("/", 1)[-1]
    v1, _old_package_name, _delta = _mic_clone_patch_package_name(src_uasset_bytes, target_package_path)
    v2 = _mic_clone_rename_export0(bytes(v1), object_name, force_insert=force_rename_insert)
    return bytes(v2), src_uexp_bytes


# P1-2(案i採用): ShadowLiftをここで複製元uexpへ直接焼き込む。既存の
# convert_noue.py:find_shadow_lift_offset/patch_shadow_lift(328-361行)と
# 同一ロジックだが、convert_noue.pyはモジュールトップレベルでlive_template
# をimportしているため、逆方向のimport(live_template -> convert_noue)は
# 循環importになり不可能。そのためここに複製する。
# 案iを選んだ理由: build_live_template()はconvert_noue.pyのPhase2c
# (--mat-override-dirによるPlayer/ModelMaterials/MainShader/M_VP_m00.uasset
# 差し替え)より前に走る「上に、mat-override-dirが差し替えるのは
# MainShader/M_VP_m00という別パッケージパスであり、素体MI複製先
# (Body/Female/MI_Player_Female_Body等)には一切効かない。よって複製する
# その場でShadowLiftを焼き込む以外に整合を取る方法が無い(案iiは
# build_pak_from_avatar.py側への設計の寄せ替えを要し、Phase1の最小実装
# 方針に反すると判断した)。
def _mic_find_shadow_lift_offset(data):
    """clone_mic_proto.py/convert_noue.pyのfind_shadow_lift_offsetと
    同一ロジック(移植のみ)。FMaterialParameterInfoのIndex(-1、4byteの
    0xFFFFFFFF)直後の4byteがShadowLiftスカラー値。"""
    candidates = [i + 4 for i in range(len(data) - 4)
                  if data[i:i + 4] == b"\xff\xff\xff\xff"
                  and i + 4 + 4 + 16 <= len(data)]
    if len(candidates) != 1:
        raise _OutfitMaterialPatchError(
            f"ShadowLift offset is not unique: {len(candidates)} found {candidates}")
    return candidates[0]


def _mic_patch_shadow_lift(uexp_bytes, value):
    data = bytearray(uexp_bytes)
    off = _mic_find_shadow_lift_offset(bytes(data))
    struct.pack_into("<f", data, off, float(value))
    return bytes(data)


def _inject_outfit_body_parka_textures(dst_dir, pak, manifest, job=None):
    """T3(U40): 衣装SK自体は無改変のまま、Materials[]スロット0(body)/
    1(parka)が参照するバニラMIだけを同一パス・同一名で差し替え、その
    Base Textureを注入済みt00/t01へ向け直す。_normalize_outfit_materials
    (旧設計、SK側へM_VP_m00/m01の新規importを追記)の後継。
    詳細: docs\\REPORT_U40_2026-07-25.md T3節。"""
    outfit_uassets = sorted(
        rel for rel in manifest["vanilla"]
        if rel.startswith("Player/Outfit/") and rel.endswith(".uasset"))

    slot_target = {0: (MVP_PACKAGE_PREFIX + "/t00", "t00"),
                   1: (MVP_PACKAGE_PREFIX + "/t01", "t01")}

    # 検出フェーズ: 1つのMIパスに対し複数SKから異なるスロット(target)が
    # 割り当てられる場合がある(実測発覚、U40: MI_Player_Female_Bodyのような
    # 汎用素体マテリアルが、SKによってMaterials[]配列内の並び順が異なり
    # slot0/1どちらの位置にも出現しうる)。これは「body/parka」という意味論的
    # スロットとMaterials[]配列の物理インデックスが必ずしも1:1対応しない
    # ことを示す。安全側に倒し、競合したMIパスは一切差し替えない
    # (該当箇所はバニラのまま=チェッカーにはならないが、その1スロットだけ
    # アバターのテクスチャが乗らない、という限定的な劣化に留める)。
    # U50(2026-07-25、実機NG2の修正): 非対応(コラボ系)のSKは**この従来ループ
    # からも外す**。SKへのメッシュ注入を止めるだけでは不十分で、そのSKが参照する
    # MIをここで _patch_mi_base_texture してしまうと Base Texture が我々の t00 へ
    # 向き、「バニラの見た目で出る」という除外の目的が達成できない
    # (責任者指摘「v1のマテリアルが差替えモデルのマテリアルになってしまっている」)。
    # 実測(work\u50_purepy\analyze_excluded_mi.py): 除外SKが参照するMI 6件は
    # **どれも非除外SKと共有されていない**ため、外しても他の統一に影響しない。
    import vp_exclusions
    _n_excluded_sk = 0
    for rel in list(outfit_uassets):
        if vp_exclusions.is_excluded(rel):
            outfit_uassets.remove(rel)
            _n_excluded_sk += 1
    if _n_excluded_sk:
        print(f"[{TAG}] U50: {_n_excluded_sk} unsupported (collab) SK excluded from "
              f"MI replacement targets (included in the pak with the vanilla MI unchanged)")

    path_targets = {}
    n_skip = 0
    skip_list = []
    for rel in outfit_uassets:
        uasset_path = os.path.join(dst_dir, *rel.split("/"))
        uexp_path = uasset_path[:-len(".uasset")] + ".uexp"
        try:
            slots = _find_outfit_slot_material_paths(uasset_path, uexp_path)
        except _OutfitMaterialPatchError as e:
            n_skip += 1
            skip_list.append(f"{rel} (detection failed: {e})")
            continue
        if not slots:
            n_skip += 1
            skip_list.append(f"{rel} (single-material outfit)")
            continue
        for slot_idx, full_path in slots.items():
            target = slot_target[slot_idx]
            path_targets.setdefault(full_path, set()).add(target)

    conflict_paths = {p: t for p, t in path_targets.items() if len(t) > 1}
    mi_target_for_path = {
        p: next(iter(t)) for p, t in path_targets.items() if len(t) == 1
    }

    # U42-attempt4(再採用、指揮者裁定2026-07-25、docs\REPORT_U42_2026-07-25.md
    # G1節): 素体共有MI(MI_Player_Male_Body/MI_Player_Female_Body)がT3の
    # 競合検出ガードによりBase Texture含め一切パッチされずバニラのまま
    # 残っていることが実機色ズレの実測上の主因と判明した(SSS系パラメータ
    # 調整では実機で見た目が一切変化しなかったことから判明、attempt2/3参照。
    # ぱんの「元々のプレイヤーカラーのまま」という指摘と完全一致)。
    # アセット名自体が「Body」であり意味論的に常にbodyスロット(t00)である
    # ことが自明なため、この既知の2ファイルに限り名前ベースの明示的な例外で
    # 強制的にbody(t00)ターゲットへ解決する(他のOutfit専用MIの競合検出
    # ロジックには一切影響しない)。初版はpreflight_pak.pyのG3(禁止物ゼロ:
    # Skeleton/Body/Physics/ubulk)にFAILしたため、指揮者裁定によりG3側へ
    # この2ファイル(4パス、拡張子.uasset/.uexp)に限定した完全一致
    # ホワイトリストを追加した(pipeline\py\preflight_pak.py、G3節コメント
    # 参照。パターンではなく完全一致列挙で将来の意図しない拡大を防ぐ)。
    _FORCED_BODY_MI_SUFFIXES = ("/MI_Player_Male_Body", "/MI_Player_Female_Body")
    forced_body_paths = {}
    for p in list(conflict_paths.keys()):
        if any(p.endswith(suf) for suf in _FORCED_BODY_MI_SUFFIXES):
            forced_body_paths[p] = slot_target[0]
            del conflict_paths[p]
    mi_target_for_path.update(forced_body_paths)

    print(f"[{TAG}] T3: detected {len(mi_target_for_path)} MI replacement target(s) from "
          f"{len(outfit_uassets)} Outfit SK "
          f"(skipped {n_skip}, excluded due to conflict {len(conflict_paths)})")
    if skip_list:
        print(f"[{TAG}]   skip breakdown: {skip_list}")
    if forced_body_paths:
        print(f"[{TAG}] U42: force-resolved shared body MI conflict by name (body/t00): {list(forced_body_paths)}")
    if conflict_paths:
        print(f"[{TAG}]   conflicts (excluded from replacement, left vanilla): {conflict_paths}")

    def game_path_to_pak_rel(full_path):
        prefix = "/Game/Pal/Model/Character/"
        if not full_path.startswith(prefix):
            raise _OutfitMaterialPatchError(f"unexpected package path (prefix mismatch): {full_path}")
        return full_path[len(prefix):]

    # U50 Phase1(P1-3): 素体2件(_FORCED_BODY_MI_SUFFIXES)だけをMICクローン
    # (_clone_mvp_mic_as)へ切り替える適用可否を判定する。U50-S0で既定OFFへ
    # 反転済み(実機でマテリアルエラー確認のため)。環境変数
    # D2P_U50_P1_ENABLE_BODY_MIC_CLONE=1を明示的に設定したときのみ有効化する。
    # Phase1はLit2S(job.jsonのforce_two_sided既定True)のみを対象
    # とし(指示書1.5.3節: Unlit系はMICではなくフルMaterialのため複製方式が
    # 使えない)、それ以外(unlit=True または force_two_sided=False)は
    # 安全側で旧挙動へフォールバックする(スコープを勝手に広げない)。
    job = job or {}
    _p1_unlit = bool(job.get("unlit", False))
    _p1_two_sided = bool(job.get("force_two_sided", True))
    _p1_shadow_lift = max(0.0, min(1.0, float(job.get("shadow_lift", 0.0))))
    _p1_src_uasset = os.path.join(VARIANTS_DIR, "Lit2S", "M_VP_m00.uasset")
    _p1_src_uexp = os.path.join(VARIANTS_DIR, "Lit2S", "M_VP_m00.uexp")
    _p1_src_exists = os.path.exists(_p1_src_uasset) and os.path.exists(_p1_src_uexp)
    p1_body_mic_clone_eligible = (
        _U50_P1_BODY_MIC_CLONE_ENABLE and not _U50_P1_BODY_MIC_CLONE_DISABLE
        and not _p1_unlit and _p1_two_sided and _p1_src_exists)
    if not _U50_P1_BODY_MIC_CLONE_ENABLE:
        print(f"[{TAG}] U50-P1: default OFF (D2P_U50_P1_ENABLE_BODY_MIC_CLONE not set), "
              f"the 2 body materials use the old behavior (_patch_mi_base_texture)")
    elif _U50_P1_BODY_MIC_CLONE_DISABLE:
        print(f"[{TAG}] U50-P1: D2P_U50_P1_DISABLE_BODY_MIC_CLONE=1, "
              f"the 2 body materials also use the old behavior (_patch_mi_base_texture)")
    elif not p1_body_mic_clone_eligible:
        print(f"[{TAG}] U50-P1: MIC clone conditions not met (unlit={_p1_unlit} "
              f"force_two_sided={_p1_two_sided} src_exists={_p1_src_exists}), "
              f"the 2 body materials also use the old behavior (_patch_mi_base_texture)")
    else:
        print(f"[{TAG}] U50-P1: cloning the 2 body materials via MIC clone (plan B) "
              f"(shadow_lift={_p1_shadow_lift})")
    if _U50_EXP_VANILLA_CLONE:
        print(f"[{TAG}] U50-P1B-EXPERIMENT: D2P_U50_EXP_VANILLA_CLONE=1, the 2 body materials "
              f"are cloned from the vanilla MI's own bytes (not M_VP_m00) via the clone "
              f"mechanism (force_rename_insert=True) (content unchanged, ShadowLift patch also "
              f"not applied). This takes priority over the Phase1 M_VP_m00 clone path.")
    _u50_single_material_src_uasset = os.path.join(_U50_SINGLE_MATERIAL_SRC_DIR, "M_VP_m00.uasset")
    _u50_single_material_src_uexp = os.path.join(_U50_SINGLE_MATERIAL_SRC_DIR, "M_VP_m00.uexp")
    _u50_single_material_src_exists = (
        os.path.exists(_u50_single_material_src_uasset) and os.path.exists(_u50_single_material_src_uexp))
    if _U50_SINGLE_MATERIAL:
        if not _u50_single_material_src_exists:
            raise _OutfitMaterialPatchError(
                f"D2P_U50_SINGLE_MATERIAL=1 but the single-Material asset was not found: "
                f"{_u50_single_material_src_uasset}")
        print(f"[{TAG}] U50-SINGLE-MATERIAL-EXPERIMENT: D2P_U50_SINGLE_MATERIAL=1, the 2 body "
              f"materials are cloned via the clone mechanism (force_rename_insert=False) from "
              f"today's UE-mode-cooked single Material (self-contained, no parent, direct t00 "
              f"import). The ShadowLift patch is not applied (already baked as a constant). "
              f"This takes priority over the Phase1 main path and the Phase1-B experiment.")

    pak_paths = []
    for full_path in mi_target_for_path:
        rel = game_path_to_pak_rel(full_path)
        pak_paths.append(PAK_PREFIX + rel + ".uasset")
        pak_paths.append(PAK_PREFIX + rel + ".uexp")

    extracted = pak_live_extract.extract_files(pak, pak_paths)

    tmp_dir = dst_dir.rstrip("\\/") + "_mi_tmp_src"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)

    n_ok = 0
    n_ssp_patched = 0
    n_ssp_skipped = 0
    ssp_skip_reasons = {}
    n_sc_neutralized = 0
    n_mic_cloned = 0
    flatten_targets = {}  # U46/U47: full_path(バニラNormal/ORM/Subsurfaceテクスチャ) -> value
    for full_path, (target_full, target_short) in mi_target_for_path.items():
        rel = game_path_to_pak_rel(full_path)

        # U50 Phase1(P1-3): 素体2件はMICクローン(_clone_mvp_mic_as)で処理し、
        # 従来の「バニラMI抽出+_patch_mi_base_texture」経路を丸ごとスキップする
        # (バニラMIのimport/exportを一切経由しないため、_patch_mi_base_texture
        # が無害化していたNormal/ORM/Subsurface/ShadingModel系パラメータ自体が
        # 複製先に最初から存在しない)。
        is_forced_body = any(full_path.endswith(suf) for suf in _FORCED_BODY_MI_SUFFIXES)

        # U50 単体Material実験(D2P_U50_SINGLE_MATERIAL=1、他の2モードより
        # 最優先): UEモードが本日このマシンでcookした自己完結Material
        # (work\u50_diag\mvp\alive\M_VP_m00.uasset/.uexp)を、既存のクローン・
        # 改名機構(_clone_mvp_mic_as、force_rename_insert=False。Phase1本体と
        # 同じ既定)へそのまま通して素体2件のパスへ複製する。ShadowLiftの
        # バイトパッチは行わない(単体Materialは定数として焼かれておりMIC用の
        # スカラーパッチ機構が適用できない・する必要もない)。
        if is_forced_body and _U50_SINGLE_MATERIAL:
            with open(_u50_single_material_src_uasset, "rb") as f:
                _sm_src_uasset_bytes = f.read()
            with open(_u50_single_material_src_uexp, "rb") as f:
                _sm_src_uexp_bytes = f.read()
            _new_uasset, _new_uexp = _clone_mvp_mic_as(
                _sm_src_uasset_bytes, _sm_src_uexp_bytes, full_path)
            out_path = os.path.join(dst_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path + ".uasset", "wb") as f:
                f.write(_new_uasset)
            with open(out_path + ".uexp", "wb") as f:
                f.write(_new_uexp)
            n_ok += 1
            n_mic_cloned += 1
            continue

        # U50 Phase1-B実験(D2P_U50_EXP_VANILLA_CLONE=1、Phase1のM_VP_m00クローン
        # 経路より優先): バニラの素体MI自身のバイトを、_clone_mvp_mic_as
        # (force_rename_insert=True)へ通し、同一パッケージパス・同一名へ
        # 複製し直す。内容(親マテリアル・全パラメータ)は一切変えず、
        # ShadowLiftパッチも適用しない(交絡変数ゼロ)。変わるのは
        # 「クローン・改名機構を通過したかどうか」だけ。
        if is_forced_body and _U50_EXP_VANILLA_CLONE:
            src_uasset_pak = PAK_PREFIX + rel + ".uasset"
            src_uexp_pak = PAK_PREFIX + rel + ".uexp"
            if src_uasset_pak not in extracted or src_uexp_pak not in extracted:
                raise _OutfitMaterialPatchError(
                    f"MI not found in vanilla pak (EXP_VANILLA_CLONE): {full_path}")
            _exp_src_uasset_bytes = extracted[src_uasset_pak]
            _exp_src_uexp_bytes = extracted[src_uexp_pak]
            _new_uasset, _new_uexp = _clone_mvp_mic_as(
                _exp_src_uasset_bytes, _exp_src_uexp_bytes, full_path, force_rename_insert=True)
            out_path = os.path.join(dst_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path + ".uasset", "wb") as f:
                f.write(_new_uasset)
            with open(out_path + ".uexp", "wb") as f:
                f.write(_new_uexp)
            n_ok += 1
            n_mic_cloned += 1
            continue

        if is_forced_body and p1_body_mic_clone_eligible:
            with open(_p1_src_uasset, "rb") as f:
                _src_uasset_bytes = f.read()
            with open(_p1_src_uexp, "rb") as f:
                _src_uexp_bytes = f.read()
            # P1-2: ShadowLiftをここで焼き込む(案i、複製元uexpへ直接適用)。
            _src_uexp_bytes = _mic_patch_shadow_lift(_src_uexp_bytes, _p1_shadow_lift)
            _new_uasset, _new_uexp = _clone_mvp_mic_as(_src_uasset_bytes, _src_uexp_bytes, full_path)
            out_path = os.path.join(dst_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path + ".uasset", "wb") as f:
                f.write(_new_uasset)
            with open(out_path + ".uexp", "wb") as f:
                f.write(_new_uexp)
            n_ok += 1
            n_mic_cloned += 1
            continue

        src_uasset_pak = PAK_PREFIX + rel + ".uasset"
        src_uexp_pak = PAK_PREFIX + rel + ".uexp"
        if src_uasset_pak not in extracted or src_uexp_pak not in extracted:
            raise _OutfitMaterialPatchError(f"MI not found in vanilla pak: {full_path}")
        safe = rel.replace("/", "_")
        tmp_uasset = os.path.join(tmp_dir, safe + ".uasset")
        tmp_uexp = os.path.join(tmp_dir, safe + ".uexp")
        with open(tmp_uasset, "wb") as f:
            f.write(extracted[src_uasset_pak])
        with open(tmp_uexp, "wb") as f:
            f.write(extracted[src_uexp_pak])

        # U46: Normal/ORM対象の収集(パッチ前のバニラ状態から読み取り専用で検出。
        # MI側のimport table自体はこの後も一切変更しない — 参照先テクスチャの
        # 中身だけを別途差し替える)
        try:
            mi_h, mi_names, mi_imports = _read_header_and_tables_for_flatten(tmp_uasset)
            with open(tmp_uexp, "rb") as f:
                mi_uexp_bytes = f.read()
            flatten_targets.update(_collect_flatten_targets(mi_uexp_bytes, mi_names, mi_imports))
        except _OutfitMaterialPatchError:
            pass  # 検出失敗は安全側スキップ(Normal/ORM中和は対象外、他の処理は継続)

        out_path = os.path.join(dst_dir, *rel.split("/"))
        info = _patch_mi_base_texture(tmp_uasset, tmp_uexp,
                                       out_path + ".uasset", out_path + ".uexp",
                                       target_full, target_short)
        n_ok += 1
        sss_info = info.get("sss", {})
        if sss_info.get("patched"):
            n_ssp_patched += 1
        else:
            n_ssp_skipped += 1
            reason = sss_info.get("reason", "unknown")
            ssp_skip_reasons[reason] = ssp_skip_reasons.get(reason, 0) + 1
        if sss_info.get("subsurface_color_neutralized", {}).get("patched"):
            n_sc_neutralized += 1

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"[{TAG}] T3: replaced {n_ok} MI (body->t00 / parka->t01, "
          f"of which {n_mic_cloned} via U50-P1 MIC clone)")
    print(f"[{TAG}] U42: applied SubsurfaceProfile->None (ShadingModel=5 only) to {n_ssp_patched}, "
          f"skipped {n_ssp_skipped}")
    if ssp_skip_reasons:
        print(f"[{TAG}]   skip reason breakdown: {ssp_skip_reasons}")
    print(f"[{TAG}] U46: neutralized Subsurface Color (Vector) to white for {n_sc_neutralized}")
    if flatten_targets:
        _flatten_normal_orm_textures(dst_dir, pak, flatten_targets)

    # U50-unify(既定ON): 上のループで書いたMIを、1つのバニラ衣装MIから
    # 派生した統一MIで上書きする。平坦化(_flatten_normal_orm_textures)は
    # バニラMIから収集した対象に対して行う必要があるため、必ずこの後に置く
    # (work\u50_unify\ の実機検証と同じ順序: フルビルド → MI上書き)。
    if _U50_UNIFY_DISABLE:
        print(f"[{TAG}] U50-single: D2P_U50_DISABLE_UNIFY=1, skipping material unification "
              f"(pre-U49 behavior: body slots keep the body MI = dark)")
    else:
        _unify_slot_materials(dst_dir, pak, manifest, job)


# read_pak_entries/extract_filesの座標系(mountを除いた絶対パス、U17実測)
PAK_PREFIX = "Pal/Content/Pal/Model/Character/"

MANIFEST_PATH = os.path.join(HERE, "noue_template_manifest.json")
NOUE_MASTER_DIR = os.path.join(HERE, "noue_master")
PROJECT_ASSET_DIR = os.path.join(NOUE_MASTER_DIR, "pak_extract_extra")
# NOTE(2026-07-26 cooklog_fix): このパスが指す実体は生のUE cookログではない。
# preflight_pak.py G7が必要とする「SM5/SM6双方でcook済み」という固定の事実だけを
# 持つshader_platform_facts.json。シンボル名COOK_LOGは外部参照(pipeline\py\fast_repack.py、
# 書き込み許可対象外)との互換のため維持している。中身の詳細はshader_platform_facts.json
# 自体のprovenanceフィールド、旧cook.log(開発機パス・個人アバター名を含み配布不可)は
# .trush\cooklog_fix_20260726\へ退避済み。
VARIANTS_DIR = os.path.join(NOUE_MASTER_DIR, "noue_variants")
COOK_LOG = os.path.join(NOUE_MASTER_DIR, "shader_platform_facts.json")


def _load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        core.die(TAG, f"template manifest not found: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _live_template_fingerprint(pak, manifest, job):
    """build_live_template()のfingerprint計算部分だけを取り出したもの
    (probe_live_template()と共有するため、dev#226で分離)。副作用なし。

    U50-fast(2026-07-26): shadow_lift/unlit は**テンプレートに焼き込まない**
    (_unify_slot_materials は unify_base_ops() だけを適用する)。影の濃さは
    pak化直前に build_shadow_mi_overrides() が統一MI 79件だけを作り直して
    差し替える。よってテンプレートは k に依存せず、フィンガープリントからも
    外せる = 影の濃さを変えても 879ファイル/約700MB を組み立て直さない。

    **例外**: 切り分け用の環境変数を立てたときだけテンプレートが k に依存する。
      - D2P_U50_DISABLE_UNIFY=1: 統一が無効。build_shadow_mi_overrides も
        何もしないので、k の反映経路は旧経路(テンプレート側)しかない
      - D2P_U50_P1_ENABLE_BODY_MIC_CLONE=1: 素体2件を MICクローンで作り、
        その中へ _mic_patch_shadow_lift() で k を焼き込む(既定OFF)
    このときだけ従来どおり鍵に含める。**外し忘れると「値を変えても効かない」**
    という最悪のバグに戻るので、経路を増やすときは必ずここも見直すこと。
    (U54注記: この例外が有効な環境変数下では job.shadow_lift/unlit が
     fingerprintに乗るため、共有キャッシュのパス自体(フィンガープリントの
     ハッシュ)がアバターごとに変わる=誤って共有されることはない)

    dev#226: manifestの識別子はmtimeでなく内容sha256(manifest_hash)。
    配布zipを毎回まっさらなWindows Sandboxへ展開すると、展開先ファイルの
    mtimeは「展開した瞬間の時刻」になり(Python zipfile.extractall()の
    挙動、2026-07-30実測)、mtimeベースの識別子は同一内容でもSandbox起動
    のたびに変わってしまう。内容sha256は展開位置・タイミングに依存しない。
    """
    fingerprint = {
        "pak_mtime": os.path.getmtime(pak),
        "pak_size": os.path.getsize(pak),
        "manifest_hash": core.sha256_file(MANIFEST_PATH),
        "template_build_version": TEMPLATE_BUILD_VERSION,
        "unify_disabled": _U50_UNIFY_DISABLE,
    }
    if _U50_UNIFY_DISABLE or _U50_P1_BODY_MIC_CLONE_ENABLE:
        fingerprint["shadow_lift"] = round(float(job.get("shadow_lift", 0.0) or 0.0), 6)
        fingerprint["unlit"] = bool(job.get("unlit", False))
    return fingerprint


def probe_live_template(job):
    """build_live_template()と同じfingerprint計算+新鮮判定だけを、ロック
    取得・ディスク書き込み一切なしで行う副作用ゼロプローブ(dev#226 WSB
    キャッシュ持ち込みゲート用)。

    WSBのようなread-onlyマウント越しに共有キャッシュを持ち込む場合、
    「_reuse_if_fresh()が実際にヒットするか」を確認する前にbuild_live_template()
    をそのまま呼ぶと、ミス時にロック取得(=マウント直下への書き込み)を
    試みてread-onlyマウントに対する書き込みエラーで落ちる恐れがある。
    このプローブは読むだけなので、read-onlyマウント越しでも常に安全に呼べる。

    戻り値: {"fingerprint": {...}, "cache_dir": <dst_dir>,
             "marker_path": <marker_path>, "fresh": bool}
    """
    pak = job["paths"]["palworld_pak"]
    manifest = _load_manifest()
    fingerprint = _live_template_fingerprint(pak, manifest, job)
    work_root = core.job_work_root(job)
    dst_dir = core.shared_cache_dir(work_root, "live_template", fingerprint)
    marker_path = dst_dir.rstrip("\\/") + ".fingerprint.json"
    fresh = False
    if os.path.exists(marker_path):
        try:
            with open(marker_path, encoding="utf-8") as f:
                old = json.load(f)
            fresh = (old == fingerprint)
        except (OSError, ValueError):
            fresh = False
    return {"fingerprint": fingerprint, "cache_dir": dst_dir,
            "marker_path": marker_path, "fresh": fresh}


def build_live_template(job, dst_dir=None):
    """job["paths"]["palworld_pak"]からpak_extract相当のディレクトリを組み立てて
    そのパスを返す(--template引数にそのまま使える)。同一pak(mtime+size)+
    同一manifestであれば前回組み立て結果を再利用する(フィンガープリント判定)。

    U54 WP-B(2026-07-27): dst_dir省略時(通常経路)はマシン共有キャッシュ
    (vp_core.shared_cache_dir、既定 work\\_shared_cache\\live_template\\<fp12>\\、
    env D2P_SHARED_CACHEで基底上書き可)に組み立てる。**完全にアバター非依存**
    (t00/t01は固定の一般名スロットで、実アバターのピクセルはbuild_pak_from_avatar.py
    のPhase 2b以降がworkディレクトリ側にだけ書く。テンプレート自体は読み取り専用の
    まま最後まで使われる — 4.3の書き手調査参照)なので、複数アバター間で
    まるごと共有できる。dst_dirを明示指定した場合(テスト/デバッグ用途)は
    従来どおり共有キャッシュ機構を経由せず直接その場所へ組み立てる。"""
    pak = job["paths"]["palworld_pak"]
    if not os.path.exists(pak):
        core.die(TAG, f"Palworld's pak was not found: {pak}\n"
                 "Please set paths.palworld_pak in job.json")
    if not os.path.isdir(PROJECT_ASSET_DIR):
        core.die(TAG, f"project-specific assets (should be bundled) not found: {PROJECT_ASSET_DIR}")

    manifest = _load_manifest()
    fingerprint = _live_template_fingerprint(pak, manifest, job)

    explicit_dst = dst_dir is not None
    if not explicit_dst:
        work_root = core.job_work_root(job)
        dst_dir = core.shared_cache_dir(work_root, "live_template", fingerprint)

    # U18実測(preflight G2で発覚): マーカーをdst_dir内に置くと、dst_dirを
    # そのまま--templateとして丸ごと梱包するbuild_pak_from_avatar.py側の
    # ウォークに拾われ、pak内にこのファイルが1件だけ混入してG2(パス整合)が
    # 落ちる。dst_dirの外(兄弟ファイル)に置き、テンプレート本体の444ファイル
    # 構成(旧pak_extractと相対パス完全一致)を汚さないようにする
    marker_path = dst_dir.rstrip("\\/") + ".fingerprint.json"

    def _reuse_if_fresh(note):
        if not os.path.exists(marker_path):
            return False
        with open(marker_path, encoding="utf-8") as f:
            old = json.load(f)
        if old != fingerprint:
            return False
        print(f"[{TAG}] live template: reusing existing (pak/manifest unchanged{note}) "
              f"-> {dst_dir}")
        return True

    if _reuse_if_fresh(""):
        return dst_dir

    if explicit_dst:
        # dst_dir明示指定(テスト/デバッグ用途): 共有キャッシュ機構(ロック/
        # 一時ディレクトリ/read-only施錠)を経由せず、従来どおり直接組み立てる。
        _assemble_live_template(dst_dir, dst_dir, pak, manifest, job)
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(fingerprint, f)
        n_total = len(manifest["vanilla"]) + len(manifest["project"])
        print(f"[{TAG}] live template assembly complete: {n_total} file(s) -> {dst_dir}")
        return dst_dir

    # 共有キャッシュ経路: クロスプロセスロックを取ってから構築する
    # (GUIのwarmと変換の同時実行、relgate並列複数検体の同時実行への対処)
    lock = core.acquire_cache_lock(dst_dir)
    try:
        if _reuse_if_fresh(", another process finished it while waiting for the lock"):
            return dst_dir
        print(f"[{TAG}] starting live template assembly (shared cache): "
              f"vanilla={len(manifest['vanilla'])} (extracted in-place from pak) "
              f"project={len(manifest['project'])} (bundled asset copy) -> {dst_dir}")
        # Phase A: 重いIO(vanilla抽出+project資産コピー)は一時ディレクトリで
        # 完成させ、アトミックにdst_dirへ設置する(4.4: 未完成な状態を他プロセスに
        # 晒さない)。_inject_outfit_body_parka_textures(Phase B)は
        # collect_unified_mi_targets_cached()がdst_dir**そのものの絶対パス**を
        # 鍵にした兄弟キャッシュファイルを読み書きするため、必ずdst_dirが
        # 最終位置に設置された後で実行する(この関数はロック保持下でのみ
        # dst_dirを触るため、他プロセスが未完成の中身を見ることはない)。
        tmp_dir = core.cache_tmp_dir(dst_dir)
        try:
            _assemble_live_template(tmp_dir, dst_dir, pak, manifest, job, phase_b=False)
            core.replace_dir_atomic(tmp_dir, dst_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        # Phase B: dst_dir(最終位置)に対して直接作用する(T3のMI差し替え+統一)
        _inject_outfit_body_parka_textures(dst_dir, pak, manifest, job)
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(fingerprint, f)
        core.lock_cache_dir_readonly(dst_dir)
        n_total = len(manifest["vanilla"]) + len(manifest["project"])
        print(f"[{TAG}] live template assembly complete (shared cache, read-only locked): "
              f"{n_total} file(s) -> {dst_dir}")
    finally:
        core.release_cache_lock(lock)
    return dst_dir


def _assemble_live_template(build_dir, final_dst_dir, pak, manifest, job, phase_b=True):
    """live_templateの中身をbuild_dirへ組み立てる(vanilla抽出+project資産コピー、
    必要ならPhase B=T3のMI差し替え+統一まで)。

    build_dirとfinal_dst_dirを分けて受け取るのは、共有キャッシュ経路が
    Phase Aを一時ディレクトリ(build_dir)で完成させてからdst_dir(final_dst_dir)
    へアトミックrenameするため(4.4)。dst_dir明示指定の従来経路では
    build_dir==final_dst_dirで、Phase Aも直接その場所へ組み立てる
    (共有キャッシュを経由しないので一時ディレクトリは不要)。"""
    if os.path.isdir(build_dir) and build_dir == final_dst_dir:
        shutil.rmtree(build_dir)
    os.makedirs(build_dir, exist_ok=True)

    pak_paths = [PAK_PREFIX + rel for rel in manifest["vanilla"]]
    extracted = pak_live_extract.extract_files(pak, pak_paths)
    for rel, pak_path in zip(manifest["vanilla"], pak_paths):
        out_path = os.path.join(build_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(extracted[pak_path])

    # dev#26 案B(2026-07-28): project区分のうちSK系スタブ306件は同梱をやめ、
    # ここで実行時生成する(uasset=バイト完全一致の完全生成、uexp=ライブ抽出した
    # バニラRefBonePose等の注入。生成器と根拠: pipeline\py\stub_skeletal_mesh.py、
    # 検証: work\wp_stub\verify_optionB.py)。残り(M_VP_*/t00/t01/anchor等の
    # 自作資産)は従来どおり同梱コピー。
    sk_rels = [rel for rel in manifest["project"] if "/SK_" in rel.replace("\\", "/")]
    for rel in manifest["project"]:
        if rel in sk_rels:
            continue
        src = os.path.join(PROJECT_ASSET_DIR, *rel.split("/"))
        if not os.path.exists(src):
            core.die(TAG, f"project-specific asset not found: {src}")
        out_path = os.path.join(build_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        shutil.copy2(src, out_path)
    if sk_rels:
        print(f"[{TAG}] generating {len(sk_rels)} SK stub(s) at runtime (dev#26: no longer bundled, "
              f"skeleton info is live-extracted from the user's Palworld)")
        stub_files = stub_skeletal_mesh.build_stub_files(pak, sk_rels)
        for rel, data in stub_files.items():
            out_path = os.path.join(build_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(data)

    if not phase_b:
        return

    # U22〜U39: Materials[]正規化パッチ(_normalize_outfit_materials、SK側へ
    # M_VP_m00/m01の新規importを追記する方式)はオフライン検証(G2)を毎回
    # 通過していたが、H1(U31)+H2(U39)の両修正を適用した最終ビルドでも
    # 実機チェッカー柄が再現した(docs\REPORT_U39_2026-07-25.md G3節)。
    # U40でT3設計転換に切り替え: SKは完全バニラのまま残し、SKが元々参照する
    # バニラMI資産を同一パス・同一名で差し替えてBase Textureだけをt00/t01へ
    # 向け直す(詳細: docs\REPORT_U40_2026-07-25.md)。
    _inject_outfit_body_parka_textures(build_dir, pak, manifest, job)
