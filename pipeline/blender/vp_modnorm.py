# -*- coding: utf-8 -*-
"""Armatureモディファイアの有効フラグ正規化(公開issue #18、dev#299)。

アバター制作者が編集中にArmatureモディファイアの表示(show_viewport等)を
切ったまま保存したファイルは、step02の bake_pose_into_meshes で
bpy.ops.object.modifier_apply がBlender自身のエラー
(日本語UIで `RuntimeError: モディファイアーはOFFです`)を出して変換が停止する。

設計判断(2026-07-28確定): このフラグは制作者の編集時表示の名残にすぎず、
束縛の実体は「モディファイアの存在」と「頂点グループ」。したがって
エラーにせず**入口で強制ONに正規化して進む**。ユーザーにBlenderで
直させる方向の対応は禁止。

dev#299: show_viewport/show_render が両方Trueでも `modifier_apply` が
"Modifier is disabled, skipping apply" で失敗するケースがある。Blenderの
Armatureモディファイアは、ターゲット(`mod.object`)が無い(None)場合も
表示フラグと無関係に「無効」と判定される(is_disabled callback)。
ターゲット参照は、step01が複数Armature入力から主アーマチュアを1つ選び
残りを破棄する際(`bpy.data.objects.remove(..., do_unlink=True)`)、その
破棄されたArmatureを指していた別モディファイア(装飾小物に付いた2本目の
Armatureモディファイア等、名前は "Armature_1" のような形になりやすい)で
自動的にNoneへクリアされる。ターゲットが無いモディファイアは束縛先が
存在しないので適用しても変形に寄与せず、安全に取り除ける。よってこの
モジュールは表示フラグの正規化に加え、ターゲット参照が壊れている
Armatureモディファイアの除去も行う(どちらも「apply直前に、実際には
効いていないArmatureモディファイアで変換を止めない」という同じ目的)。

このモジュールは意図的にbpy非依存(ダックタイピング)にしてあり、
Blender外のユニットテスト(tests/coverage/selftest)から直接検証できる。
対象は `type == "ARMATURE"` のモディファイアのみ。モディファイアを
持たないメッシュ(真の非スキンメッシュ等)には一切触れない。
"""

# 正規化対象の有効フラグ。modifier_applyが直接見るのはビューポート評価だが、
# レンダリング側も残すと「見た目検査(render)と変換結果が食い違う」ので両方ONにする。
_ENABLE_FLAGS = ("show_viewport", "show_render")

# ターゲット参照切れ(mod.object is None)を表す理由タプルの中身。
# 表示フラグ名(show_viewport/show_render)とは別名にして、呼び出し側が
# 「フラグを強制ONにした」のか「モディファイア自体を除去した」のかを
# 区別できるようにする。
ORPHAN_TARGET_REASON = ("object",)


def normalize_armature_modifiers(mesh_objs, tag="vp_modnorm", log=print):
    """Armatureモディファイアを、apply可能な状態へ正規化する。

    2種類の正規化を行う:
    1. 無効フラグ(show_viewport/show_render=False)を強制ONにする
       (公開issue #18)。
    2. ターゲット(`mod.object`)が無い(None)モディファイアを除去する
       (dev#299)。表示フラグがTrueでもBlenderは「無効」と判定して
       modifier_applyを拒否するが、束縛先が無い以上、除去しても
       変形結果は変わらない(何も変形していなかったのと同じ)。

    mesh_objs: `.name` と `.modifiers`(各要素が `.type` `.name` `.object` と
        _ENABLE_FLAGS 属性を持つ)を備えたオブジェクトの列。bpyのObjectで
        そのまま動くが、bpyには依存しない。`.modifiers` は `.remove(mod)`
        (bpyのModifiersコレクション、または通常のlist)をサポートすること。
    tag: ログ行の先頭タグ([step01] 等)。
    log: ログ出力関数(既定print。テストでは記録用に差し替え可)。

    返り値: 正規化した (mesh名, modifier名, 理由タプル) のリスト。理由タプルは
    ("show_viewport", "show_render") のような無効だったフラグ名の組、
    またはターゲット除去の場合は ("object",) 固定値。
    もともと全フラグONかつターゲットありのモディファイア・ARMATURE以外の
    モディファイアは触らず、リストにも載せない。
    """
    normalized = []
    for obj in mesh_objs:
        # 除去(list.remove/Modifiers.remove)がイテレーション中に安全に
        # 行えるよう、先にリスト化してからループする。
        for mod in list(getattr(obj, "modifiers", ())):
            if mod.type != "ARMATURE":
                continue
            if getattr(mod, "object", None) is None:
                # 名前はremove()でRNA構造体が無効化される前に確保しておく
                # (bpyのModifiers.remove()後はmod.nameへのアクセスが
                # ReferenceErrorになる。2026-07-30実測)。
                mod_name = mod.name
                obj.modifiers.remove(mod)
                normalized.append((obj.name, mod_name, ORPHAN_TARGET_REASON))
                log(f"[{tag}] normalized: armature modifier '{mod_name}' on "
                    f"mesh '{obj.name}' had no target armature (object=None, "
                    f"likely a discarded duplicate/extra Armature from "
                    f"import) -> removed (no target = no deformation to "
                    f"preserve; Blender treats this as disabled regardless "
                    f"of show_viewport/show_render)")
                continue
            disabled = tuple(f for f in _ENABLE_FLAGS
                             if not getattr(mod, f, True))
            if not disabled:
                continue
            for f in disabled:
                setattr(mod, f, True)
            normalized.append((obj.name, mod.name, disabled))
            # 英語ログ(配布版ログから診断できるよう成功時にも構造を残す)
            log(f"[{tag}] normalized: armature modifier '{mod.name}' on mesh "
                f"'{obj.name}' was disabled ({', '.join(disabled)}=False) "
                f"-> forced ON and continuing (author-time display leftover; "
                f"binding is defined by the modifier + vertex groups)")
    return normalized
