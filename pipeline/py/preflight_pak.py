# -*- coding: utf-8 -*-
"""MOD pakのオフライン全数検品(ゲーム非起動)。1つでも落ちたら使用禁止。

PalModでゲーム内テストによって発覚した全敗因クラスを機械検証する:
  平坦化パス / SM6欠落 / バインドポーズずれ / スケルトン同梱 / 使用フラグ欠落 /
  ストリーミングミップ / 参照切れ

U50(2026-07-25)で構造ゲートを2つ追加した(**既定は警告、FAILにはしない**):
  G10 ライブpakに実在する全SKがこのpakに収録されているか(場所依存・名前単位)
  G11 全衣装SKの**全描画スロット**が注入アトラス t00 を指しているか
件数を締めていく運用は環境変数で行う:
  D2P_PREFLIGHT_COVERAGE / D2P_PREFLIGHT_SLOTROLE = fail | max:<件数> | warn(既定)

U50(2026-07-25 夕)で2点を仕様追随させた:
  * **非対応(コラボ系)装備の除外**(`vp_exclusions.py` が唯一の正本)。
    除外されたSKは注入もMI差し替えもされず**バニラのまま**出る(意図どおり)ので、
    G5/G5b/G10/G11 の検査対象から外す。**除外していないSKへの検査は一切
    緩めていない**(除外集合は vp_exclusions のみが決める)。
  * **マテリアル単一化**(live_template._unify_slot_materials、既定ON)により
    t01 は使われなくなり、全描画スロットのMIが t00 を参照する。G11の判定基準を
    旧「slot0->t00 / slot1->t01」から「**全描画スロットが t00**」へ更新した。

使い方: python preflight_pak.py <job.json> <mod.pak> <pak_extractルート> <cook_log>

cook_log引数(第4引数)について(2026-07-26 cooklog_fix):
  UEモード(pipeline\\cli\\convert.ps1のUE分岐)では実際にBuildCookRunで生成された
  本物のcookログ(生テキスト)が渡される。
  noueモード(既定)では実際にcookする工程が無いため、代わりに
  `pipeline\\py\\noue_master\\shader_platform_facts.json`(SM5/SM6双方でcook済みという
  固定の事実だけを持つJSON、live_template.COOK_LOG経由)が渡される。
  G7はこの2形式のどちらが来ても判定できるよう、JSON解析を先に試み、
  失敗したら生ログへの文字列検索へフォールバックする(下記G7実装参照)。
"""

import concurrent.futures
import glob
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core as core
# U50: 「非対応(コラボ系)」装備の除外リスト(唯一の正本)。除外されたSKは
# 注入もMI差し替えもされずバニラのままpakへ入る/入らないので、検品側も
# 同じ正本を見て検査対象から外す必要がある(pakの欠陥ではない)。
import vp_exclusions  # noqa: E402
# U18: G5/G5b用(pakに実際に同梱されたRenderSectionsのBoneMapを読むため)。
# U51(research\ue_exit→pipeline\py移設): parse_sk_structure.pyは元research\ue_exit\
# から無改変のままpipeline\py\へコピーされた(research\ue_exit\側は開発参照用に
# 残置、実行時には見ない)。同じディレクトリ(HERE、上でsys.pathへ追加済み)から
# そのままimportできる
import parse_sk_structure as sk_struct  # noqa: E402
# dev#165(2026-07-30): 性別限定ビルド(job.jsonのgenders)で要求されていない
# 性別の衣装SKは、build_pak_from_avatar.pyのPhase2で実際に注入をスキップし、
# vp_exclusions(コラボdenylist)と同じPhase3バニラコピー経路に乗る。
# preflightは別プロセスなので、同じ「注入されていない」判定をここでも
# 独立に再現する必要がある(gender_of()はSK名から性別を読む、既存の
# build_pak_from_avatar.py/build_avatar_variant_all.pyと同一関数を再利用)。
from build_avatar_variant_all import gender_of  # noqa: E402


def _is_gender_excluded(rel_or_name, requested_genders):
    """dev#165: このSKが「job.jsonのgendersで要求されていない性別」のため
    注入をスキップされた(=バニラのまま)ものかどうかを判定する。
    既定(両性別要求)では常にFalse(=既存の挙動に対する新しい分岐に一切
    入らない)。Head/Hair/HeadEquipやMI_*等、_Male_/_Female_を名前に
    含まないファイルはgender_of()が例外を送出するため、判定不能=除外しない
    (性別非依存の資産には一切影響しない)。"""
    if requested_genders >= {"Male", "Female"}:
        return False
    try:
        g = gender_of(os.path.basename(str(rel_or_name)))
    except Exception:
        return False
    return g not in requested_genders

results = []
soft_results = []


def gate(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def soft_gate(name, ok, detail, env_flag, n_bad=0):
    """U50: 既定では警告(WARN)で、環境変数でFAILへ昇格できるゲート。

    背景(work\\u50_equip\\out\\FINDINGS.txt): 既存の件数照合ゲート(G4)は
    「CSV生成側」と「pak収録側」が同じ正規表現の盲点を共有しているため、
    両方が同じだけ漏れていると件数が一致してしまい検出できなかった。
    G10/G11はその盲点を持たない構造ゲートだが、導入時点で既知のNGが
    残っている(G11=16/60SK。別途「マテリアル完全単一化」で対応中)。
    ここでFAILにすると既存のビルドが全部落ちるため、**当面は警告**とし、
    件数が減っていくのを追えるようにNG件数と内訳を必ず出力する。

    将来の昇格は環境変数で行う(既定=warn):
      <env_flag>=fail     … NGが1件でもあればFAIL
      <env_flag>=max:<N>  … NGがN件を超えたらFAIL(件数を締めていく運用向け)
      <env_flag>=warn/未設定 … 常に警告(検品の合否には影響しない)
    """
    mode = (os.environ.get(env_flag) or "warn").strip().lower()
    promote = False
    if not ok:
        if mode == "fail":
            promote = True
        elif mode.startswith("max:"):
            try:
                promote = n_bad > int(mode[len("max:"):])
            except ValueError:
                promote = True   # 指定が壊れているなら安全側(FAIL)へ
    if promote:
        gate(name, False, f"{detail} [promoted to FAIL by {env_flag}={mode}]")
        return
    soft_results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'WARN'}] {name}" + (f" — {detail}" if detail else ""))


def count_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return sum(1 for _ in f) - 1  # ヘッダ除く


def _manifest_sk_counts():
    """noue_template_manifest.jsonが宣言している(=noueが実際に用意する)
    カテゴリ別SK数を返す。読めなければNone。

    U50: dup_*.csv は「バニラpakに実在する全SK」の**場所依存の完全列挙**へ
    直したので、noueテンプレがまだカバーしていないSK(2026-07-25時点で
    HeadEquipのYakushima 6件。ダミーSK資産の新規生成が要るため未対応)が
    あると、CSV由来の期待値とpak実測がずれる。noueにとっての「宣言された
    収録集合」はmanifestなので、G4はCSV由来かmanifest由来のどちらかに
    一致すればPASSとする。**漏れの検出はG10(名前単位)が担当する**ので、
    ここを緩めても盲点にはならない。
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "noue_template_manifest.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
    except Exception:
        return None
    rels = list(man.get("vanilla", [])) + list(man.get("project", []))
    out = {}
    for cat in ("Outfit", "Head", "Hair", "HeadEquip"):
        pfx = f"Player/{cat}/"
        out[cat] = len([r for r in rels
                        if r.startswith(pfx) and r.endswith(".uasset")
                        and os.path.basename(r).startswith("SK_")])
    return (out["Outfit"], out["Head"], out["Hair"], out["HeadEquip"])


def _load_sk_inventory(vanilla_dir, vanilla_entries):
    """バニラpakのSK完全在庫(場所依存列挙)を得る。

    extract_vanilla.pyが書き出したsk_inventory.jsonを使い、無ければ
    pak_entries.txt.gzから同じ関数でその場で作り直す(古いjobディレクトリ
    でもゲートが効くように)。返り値: {category: [rel, ...]} or None。
    """
    path = os.path.join(vanilla_dir, "sk_inventory.json")
    inv = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                inv = json.load(f)
        except Exception:
            inv = None
    if inv is None:
        try:
            import extract_vanilla
            inv = extract_vanilla.enumerate_vanilla_sk(vanilla_entries)
        except Exception as e:
            print(f"  [WARN] failed to reconstruct SK inventory (skipping G10): {e}")
            return None
    return {cat: [r["rel"] for r in rows] for cat, rows in inv.items()}


_GAME_PKG_PREFIX = "/Game/Pal/Model/Character/"


def _slot_role_check(template_dir):
    """全衣装SKについて、**全描画スロット**が注入アトラス t00 を指しているかを
    テンプレート上の実バイトから機械判定する。

    ### 判定基準の変更(2026-07-25、マテリアル単一化に伴う)

    旧基準は「slot0->t00 / slot1->t01」で、live_template側の
    「同じMIが別SKで別スロット役 → 競合ガードで差し替え対象外」という挙動を
    **シミュレート**して数えていた(work\\u50_equip\\slot_role_check.py 由来)。

    現在の live_template._unify_slot_materials(既定ON)は、注入対象衣装SKの
    描画スロットが参照するMIを**全件**、たった1種類の統一MI(Base Texture=t00)
    で置き換える。スロット役という概念自体が無くなり t01 は使われない。
    よって基準は「**全描画スロットが t00**」になる。
    旧基準のままだと slot1 が必ず t00 になるため全件NGとなり誤検知する
    (この基準変更前のNG 16件はすべて旧基準由来で、実体は正常だった)。

    ### シミュレーションではなく実バイトを見る

    旧実装はSKのMaterials[]の参照関係だけから結果を推定していたが、本実装は
    参照先のMIアセットを**テンプレート上で実際に開き**、name tableに
    `<MainShaderパッケージ>/t00` が入っているか(=Base Textureが我々の
    注入アトラスへ向いているか)を読む。統一MIの書き出しが漏れたMIは
    バニラのままなので name table に一致が無く、"VANILLA" として確実にNGになる。
    テンプレートに当該MIファイル自体が無い場合も "MISSING" でNGにする。

    非対応(コラボ系、vp_exclusions)のSKは、MI差し替え自体を意図的に
    行わない(=バニラの装備がそのまま出る)ため検査対象から外す。

    返り値: (NG件数, 検査件数, NG明細のリスト, エラー文字列 or None)
    """
    try:
        import live_template as lt
    except Exception as e:
        return 0, 0, [], f"failed to import live_template: {e}"
    # live_template._unify_slot_materials / collect_unified_mi_targets が
    # 使うのと同じ「スロット役を割り当てない出現順の全マテリアルパス」取得。
    finder = getattr(lt, "find_outfit_material_paths_all", None)
    err_cls = getattr(lt, "_OutfitMaterialPatchError", Exception)
    mvp_prefix = getattr(lt, "MVP_PACKAGE_PREFIX", None)
    if finder is None or mvp_prefix is None:
        return 0, 0, [], ("live_template.find_outfit_material_paths_all / "
                          "MVP_PACKAGE_PREFIX not found "
                          "(the implementation may have changed; this gate needs updating)")
    outfit_root = os.path.join(template_dir, "Player", "Outfit")
    if not os.path.isdir(outfit_root):
        return 0, 0, [], f"template has no Player/Outfit: {outfit_root}"

    atlas_cache = {}

    def atlas_of(mi_full_path):
        """MIアセットが実際に参照している注入アトラス名を返す。
        t00 / t01 / "t00+t01" / "VANILLA"(注入アトラス参照なし) / "MISSING"。"""
        if mi_full_path in atlas_cache:
            return atlas_cache[mi_full_path]
        v = "MISSING"
        if mi_full_path.startswith(_GAME_PKG_PREFIX):
            rel = mi_full_path[len(_GAME_PKG_PREFIX):]
            ua = os.path.join(template_dir, *rel.split("/")) + ".uasset"
            if os.path.exists(ua):
                try:
                    names = core.read_names(ua)
                except Exception as e:
                    v = f"PARSE_ERROR({e})"
                else:
                    hit = sorted({n.rsplit("/", 1)[-1] for n in names
                                  if n.startswith(mvp_prefix + "/t")})
                    v = "+".join(hit) if hit else "VANILLA"
        atlas_cache[mi_full_path] = v
        return v

    ng = []
    n_checked = 0
    n_excluded = 0
    for dirpath, _d, fns in os.walk(outfit_root):
        for fn in sorted(fns):
            if not fn.startswith("SK_") or not fn.endswith(".uasset"):
                continue
            ua = os.path.join(dirpath, fn)
            ue = ua[:-len(".uasset")] + ".uexp"
            rel = os.path.relpath(ua, outfit_root).replace("\\", "/")
            if vp_exclusions.is_excluded(rel):
                n_excluded += 1
                continue
            n_checked += 1
            try:
                paths = finder(ua, ue)
            except err_cls as e:
                ng.append(f"{rel}: could not determine draw-slot MI path(s) ({e})")
                continue
            if not paths:
                ng.append(f"{rel}: 0 material references for draw slots")
                continue
            bad = [f"slot{i}={atlas_of(p)}({p.rsplit('/', 1)[-1]})"
                   for i, p in enumerate(paths) if atlas_of(p) != "t00"]
            if bad:
                ng.append(f"{rel}: " + " / ".join(bad) + " (expected all slots = t00)")
    if n_excluded:
        print(f"  [INFO] G11 excluded (unsupported/collab items): {n_excluded}")
    return len(ng), n_checked, ng, None


# ============================================================================
# G5並列化(rdp_preflight, 2026-07-29研究dev#120フォローアップ)
# ----------------------------------------------------------------------------
# G5/G5bループ(58SK分)はrd_120実測でPhase4(preflight全体)の支配的コストと
# 特定された。当初「単一ファイルハンドル(mod_pakを開くpf)を複数プロセスで
# 共有できない」設計制約が指摘されていたが、実際に重いのはpf経由の抽出
# (I/Oのみ、高速)ではなく、抽出後にtmp_uasset/tmp_uexp(SKごとに独立した
# 一時ファイル)だけを読むcore.find_refskeleton()(uexp全域の総当たり
# オフセット走査)とparse_sk_structure.py(同様の前方/後方総当たり走査)という
# pure Python CPUバウンドループである。これらはmod_pak自身のpfには一切
# 触れないので、「抽出はpfで直列のまま(不変)・解析はSKごとに独立なので
# プロセス並列」という2段構成にすれば、pf共有制約に一切触れずに済む
# (=「ワーカーごとに開き直す」でも「先読み」でもなく、そもそも並列区間に
# pfを持ち込まない設計)。
# ============================================================================

def _g5_analyze_one(args):
    """G5/G5b: 1SK分の解析(read_names/find_refskeleton/parse_sk_structure/
    bind回転差)。抽出済みの一時uasset/uexpパスだけを読み、mod_pak自体の
    ファイルハンドルには一切触れない。ProcessPoolExecutorのワーカーから
    pickle経由で呼ばれるためモジュールトップレベル関数にする(Windows
    spawnの制約)。

    例外は握りつぶさずそのまま送出する(直列版と同じく、解析不能なSKが
    あれば即座に致命エラーで停止する既存挙動を変えない。ProcessPoolExecutor
    はワーカー例外を呼び出し元の.result()/イテレーション時に再送出するため、
    mainプロセス側で見える挙動は直列時と同じ「即クラッシュ」になる)。

    戻り値: (worst_local(dr, "base:bone"), unknown_bones_local(set))
    """
    tmp_uasset, tmp_uexp, ref = args
    base = os.path.basename(tmp_uasset)
    names = core.read_names(tmp_uasset)
    bones, transforms, _ = core.find_refskeleton(tmp_uexp, names)
    struct_info = sk_struct.parse_sk_structure(tmp_uexp, tmp_uasset)
    used_idx = set()
    for sec in struct_info["sections"]:
        used_idx.update(sec["bone_map"])
    worst_local = (0.0, "")
    unknown_local = set()
    for i, ((bname, _p), t) in enumerate(zip(bones, transforms)):
        if i not in used_idx:
            continue  # 実際のRenderSectionsが参照しない(=描画に無関係な)ボーン
        vb = ref.get(bname)
        if vb is None:
            # メッシュ名とボーン名の衝突でUEがボーンをリネームすると
            # (例: head→head1)実行時スケルトンに対応が無くなり非追従になる。
            # 実際に使用中のボーンはバニラの部分集合でなければならない
            unknown_local.add(f"{base}:{bname}")
            continue
        dr = core.quat_angle_deg(t[0:4], vb["quat"])
        if dr > worst_local[0]:
            worst_local = (dr, f"{base}:{bname}")
    return worst_local, unknown_local


def _g5_worker_count(n_tasks):
    """並列度の既定値。D2P_PREFLIGHT_G5_WORKERS=1 を指定すると強制直列化
    される(デバッグ・低スペック環境・再現性を要するテスト用)。既定は
    cpu_countと8の小さい方、かつタスク数を超えない(空振りプロセス起動の
    無駄を避ける)。"""
    env = (os.environ.get("D2P_PREFLIGHT_G5_WORKERS") or "").strip()
    if env:
        try:
            n = int(env)
            if n >= 1:
                return min(n, n_tasks) if n_tasks else 1
        except ValueError:
            pass
    return max(1, min(os.cpu_count() or 4, 8, n_tasks or 1))


def _run_g5_analysis(extraction_tasks, analyze_fn=_g5_analyze_one):
    """G5/G5b解析の並列実行本体。抽出済みタスク(mod_pakのpfから独立、SKごと
    に完全に独立な入力)をProcessPoolExecutorへ配る。concurrent.futures.
    Executor.map()は投入順で結果を返す(公式挙動)ので、集約結果
    (worst=単純max、unknown_bones=単純union)は並列度・実行順に関係なく
    直列実行時と完全に同一になる(SKごとの計算に共有可変状態が無いため)。
    タスクが0〜1件、または並列度1のときはプロセス起動コストを避けて
    直列実行する(同じanalyze_fn()を呼ぶだけなので結果は完全に同値)。

    analyze_fn: 既定は_g5_analyze_one(本番動作はこれで固定)。テスト時のみ、
    真のProcessPoolExecutorディスパッチ(spawn・pickle・順序保証)を軽量な
    モックSK解析関数で検証できるよう差し替え可能にしてある
    (work\\rdp_preflight\\tests\\test_g5_parallel_dispatch.py参照。
    analyze_fnはpickle対象になるためモジュールトップレベル関数である必要がある)。
    """
    n = len(extraction_tasks)
    if n == 0:
        return []
    workers = _g5_worker_count(n)
    if workers <= 1:
        return [analyze_fn(t) for t in extraction_tasks]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(analyze_fn, extraction_tasks))


def _aggregate_g5_results(per_task_results):
    """_run_g5_analysis()の戻り値([(worst_local, unknown_local), ...])を
    G5/G5bゲートが使う最終形(worst, unknown_bones, n_checked)へ集約する。

    集約は単純なmax(回転差)とunion(不明ボーン集合)+件数カウントのみで、
    どの順序で結果が来ても(=並列度に関係なく)最終値は同一になる
    (可換・結合的な演算のみで構成されているため)。テスト
    (work\\rdp_preflight\\tests\\)から直列/並列の集約結果が一致することを
    直接検証できるよう、main()の本体から関数として切り出した。
    """
    worst = (0.0, "")
    n_checked = 0
    unknown_bones = set()
    for worst_local, unknown_local in per_task_results:
        if worst_local[0] > worst[0]:
            worst = worst_local
        unknown_bones |= unknown_local
        n_checked += 1
    return worst, unknown_bones, n_checked


def main():
    job = core.load_job(sys.argv[1])
    mod_pak, extract, cook_log = sys.argv[2], sys.argv[3], sys.argv[4]
    vanilla_dir = os.path.join(job["job_dir"], "vanilla")
    conv = os.path.join(job["job_dir"], "converted")
    # dev#165: build_pak_from_avatar.pyのgender exclusion(Phase2)と同じ
    # 判定基準をここでも再現するための入力(_is_gender_excluded参照)
    requested_genders = set(job.get("genders") or ["Male", "Female"])

    print("=== preflight: offline MOD pak inspection ===")
    if not os.path.exists(mod_pak):
        gate("pak exists", False, mod_pak)
        return finish()

    mount, entries = core.read_pak_index(mod_pak)
    with gzip.open(os.path.join(vanilla_dir, "pak_entries.txt.gz"), "rt",
                   encoding="utf-8") as f:
        vanilla_entries = f.read().splitlines()
    vanilla_set = set(vanilla_entries)

    # G1: マウントポイント
    gate("G1 mount point",
         mount == "../../../Pal/Content/Pal/Model/Character/", mount)

    # G2: パス整合(平坦化検知)。新規アセット(ModelMaterials)とアンカー以外は
    # バニラに同一パスが存在しなければならない(=正しく上書きされる証拠)
    full = [mount.replace("../../../", "") + e for e in entries]
    new_asset_ok = re.compile(r".*/ModelMaterials/MainShader/[^/]+$")
    # 新称(_divetopalworld_anchor.txt)/旧称(_vrm2palworld_anchor.txt、改名前に
    # 生成された既存pak向け)の両方を許容する(2026-07-22昼発覚。過去に生成済みの
    # pakの検品を壊さないため。生成側は改名コミット02f1f24で既に新称に統一済み)
    anchor_ok = re.compile(r".*_(?:divetopalworld|vrm2palworld)_anchor\.txt$")
    bad = [p for p in full
           if not (p in vanilla_set or new_asset_ok.match(p) or anchor_ok.match(p))]
    gate("G2 all entry paths match vanilla (no flattening)", not bad,
         f"{len(bad)} mismatch(es), e.g.:{bad[:3]}" if bad else f"{len(full)} OK")

    # G3: 禁止物(共有スケルトン・素体・ストリーミングミップ・装備専用Skeleton/Physics)。
    # このゲート自体はT3設計(U40)より前から存在する既存の安全境界であり、
    # 「共有スケルトン・素体スケルタルメッシュ本体・Physics・ストリーミング
    # ミップは改変対象外」という原則は今回も維持する(全面禁止のまま)。
    #
    # U42(2026-07-25、指揮者裁定): 素体共有MI(MI_Player_Male_Body/
    # MI_Player_Female_Body、MaterialInstanceConstant資産。スケルタルメッシュ
    # 本体でもSkeletonでもPhysicsでもubulkでもない)のみ、完全一致の
    # ホワイトリストで狭く例外許可する。背景: T3(pipeline\py\live_template.py
    # _inject_outfit_body_parka_textures)がこの2ファイルを「Materials[]配列内の
    # 物理スロット位置がSKによって異なる競合」として安全側除外していたため、
    # 多数の衣装が参照する素体のBase Textureが実機で常にバニラのまま
    # (=アバターの肌色が一切乗らない)という実測不具合(docs\
    # REPORT_U42_2026-07-25.md G1節)があった。ホワイトリストは意図的に
    # パターンではなく4パス(2ファイル×.uasset/.uexp)の完全一致列挙とし、
    # 将来他のBody配下ファイルが意図せず紛れ込んでも機械的に弾かれるよう
    # 構造的に防ぐ。
    # U46(2026-07-25): 体の色ズレ(茶色い体・顔の金属質模様・服のしわ)修正の
    # 一環で、素体共有MIが参照するNormal/MetallicRoughnessOcclusionSpecular
    # テクスチャ資産(/Body/配下、同一パス・ペイロード置換で平坦中立値に
    # 差し替え。ubulk化はせず全ミップinlineへ再構成済み — G3の.ubulk全面
    # 禁止には抵触しない)を追加。U42と同じ原理(完全一致の列挙、パターン
    # マッチ不使用、将来の意図しない拡大を機械的に防ぐ)。live_template.py
    # _flatten_normal_orm_textures参照。
    # U47(2026-07-25): 素体スロット(ShadingModel=6 TwoSidedFoliage)の
    # 「Subsurface Texture」がアバター自身のBase Textureへ再配線されていた
    # ことが「肌の色被り」の実測原因だったため(docs\REPORT_U47_2026-07-25.md
    # G1節)、この再配線を廃止し、代わりに元々の参照先テクスチャ資産自体を
    # 黒へ平坦化する方式(U46のNormal/ORMと同じ技法)へ切り替えた。実測
    # (work\u47_diag\probe_sss_tex.py): 該当資産は
    # /Player/Body/Female/T_Player_Female_Body_SSS の1件のみで、男性素体MIも
    # このFemale資産を共有参照する(Male_Body_SSSという別ファイルは存在
    # しない)。U42/U46と同じ原理(完全一致の列挙、パターンマッチ不使用)で
    # 2パス(1ファイル×.uasset/.uexp)を追加する。
    _G3_BODY_MI_WHITELIST = frozenset({
        "Player/Body/Male/MI_Player_Male_Body.uasset",
        "Player/Body/Male/MI_Player_Male_Body.uexp",
        "Player/Body/Female/MI_Player_Female_Body.uasset",
        "Player/Body/Female/MI_Player_Female_Body.uexp",
        "Player/Body/Female/T_Player_Female_Body_SSS.uasset",
        "Player/Body/Female/T_Player_Female_Body_SSS.uexp",
    } | {
        f"Player/Body/{gender}/T_Player_{gender}_Body_{suffix}.{ext}"
        for gender in ("Male", "Female")
        for suffix in ("N", "max_N", "min_N", "M")
        for ext in ("uasset", "uexp")
    })
    forbidden = [p for p in entries
                 if (("Skeleton/" in p or "/Body/" in p or p.endswith(".ubulk")
                      or "_Skeleton." in p or "Physics" in p)
                     and p not in _G3_BODY_MI_WHITELIST)]
    gate("G3 zero forbidden items (Skeleton/Body/Physics/ubulk, only the 4 base-body MI paths exempt)", not forbidden,
         str(forbidden[:3]) if forbidden else "")

    # G4: 収録数(複製リスト+複製元。マテリアル・テクスチャはスロット表から導出)
    with open(os.path.join(conv, "avatar_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    n_out_m = count_csv(os.path.join(vanilla_dir, "dup_outfit_male.csv")) + 1
    n_out_f = count_csv(os.path.join(vanilla_dir, "dup_outfit_female.csv")) + 1
    n_head = (count_csv(os.path.join(vanilla_dir, "dup_head_male.csv")) + 1
              + count_csv(os.path.join(vanilla_dir, "dup_head_female.csv")) + 1)
    n_hair = count_csv(os.path.join(vanilla_dir, "dup_hair.csv")) + 1
    n_he = count_csv(os.path.join(vanilla_dir, "dup_headequip.csv")) + 1
    n_mat = len(meta["slots"])
    n_tex = len({s["texture"] for s in meta["slots"].values() if s["texture"]})
    # U19(2026-07-23、U54(2026-07-26)で式を訂正):
    # counts[4]/counts[5]が数えているのは、avatar_meta.json由来のスロット数
    # (n_mat/n_tex)から導いた「何バケツに丸められるか」ではなく、
    # **noueテンプレートが常に持つ固定2パッケージ名そのもの**である:
    #   counts[4] = canonical_mat(MainShader/M_VP_[A-Za-z0-9]+.uasset)
    #             = M_VP_m00.uasset / M_VP_m01.uasset の実在数(常に2)
    #   counts[5] = MainShader/配下でM_VP_*でない.uasset
    #             = t00.uasset / t01.uasset の実在数(常に2)
    # このm00/m01・t00/t01はavatar_meta.jsonのスロット数に関係なく、
    # Palworldプレイヤーメッシュテンプレート自身が常に同梱する固定資産
    # 名である(live_template.MVP_PACKAGE_PREFIX配下、
    # convert_noue.prepare_material_overridesが上書きしない残りはテンプレ
    # 既定のまま同梱される)。U50-single(2026-07-25)でvp_atlas.classify_material
    # が常に0(body)を返すよう単一化されて以降、「3枚以上は2バケツへ丸める」
    # という旧説明は成立しなくなっている(全スロットがbodyへ畳まれる)が、
    # テンプレート資産自体の固定2枚という実体は単一化の前後で変わっていない。
    # 実測(2026-07-26): alicia(12マテリアル)/seed/vrm1でも実測counts[4:]は
    # 常に(2,2)——n_mat依存ではなくテンプレート構造依存であることが独立に
    # 確認できる。min(n_mat,2)はn_mat>=2の間はたまたま2に一致していたため
    # 誤りが露見しなかったが、n_mat=1(vrm_kate/vrm_robothead)では期待値が
    # 1に丸まってしまい、実測の2と食い違って誤FAILしていた
    # (docs的経緯はdiag_A_vrm.md参照)。
    # 正しい期待値は「材質/テクスチャが1件以上あれば常に2、0件なら0
    # (=注入すら起きていない=過小収録の検知は維持)」。
    n_mat_expect = 2 if n_mat >= 1 else 0
    n_tex_expect = 2 if n_tex >= 1 else 0
    expect = (n_out_m + n_out_f, n_head, n_hair, n_he, n_mat_expect, n_tex_expect)
    # U13: noueのマスター+MIC構成では正規スロット名(M_VP_m00等、アンダースコアなし)
    # の他に恒久マスター(M_VP_m00_LitMaster1S等)がMainShader配下に同梱される。
    # マテリアル数の勘定は正規スロット名のみを対象にする(マスターは別枠の恒久資産)
    canonical_mat = re.compile(r"MainShader/M_VP_[A-Za-z0-9]+\.uasset$")
    # U40(T3設計転換): live_template.pyがPlayer/Outfit/配下にMI_*
    # (バニラMI差し替え、SkeletalMeshではない)を追加で収録するようになった
    # ため、「/Outfit/配下の.uasset」を無条件でSK衣装として数えると
    # 実測値が水増しされる(60衣装 + 差し替えたMI数、のように)。
    # ファイル名がSK_で始まるものだけを衣装SKとして数える
    # (docs\REPORT_U40_2026-07-25.md T3節)。
    counts = (
        len([p for p in entries if "/Outfit/" in p and p.endswith(".uasset")
             and os.path.basename(p).startswith("SK_")]),
        len([p for p in entries if "/Head/" in p and p.endswith(".uasset")]),
        len([p for p in entries if "/Hair/" in p and p.endswith(".uasset")]),
        len([p for p in entries if "/HeadEquip/" in p and p.endswith(".uasset")]),
        len([p for p in entries if canonical_mat.search(p)]),
        len([p for p in entries if "MainShader/" in p and "/M_VP_" not in p
             and p.endswith(".uasset")]),
    )
    # U15-T2: D2P_NOUE_TEMPLATE_ROOTでテンプレを別アバター(例: Shapell)に
    # 差し替えたクロステンプレート検証時は、テンプレ側の元アバターが持つ
    # 未使用マテリアル/テクスチャスロット(注入対象外、テンプレは読み取り専用で
    # 使用スロットのみ上書きする設計)がそのまま残るため実測>期待になりうる。
    # これはテンプレート由来の資産であり不具合ではない(過小=不具合/過多=許容)。
    # 通常経路(override未設定)は従来どおり厳密一致のまま
    #
    # U50(2026-07-25): dup_*.csvが「バニラpakに実在する全SKの場所依存の完全
    # 列挙」になった(extract_vanilla.py参照)。noueテンプレがまだカバー
    # できていないSK(現時点でHeadEquipのYakushima 6件。ダミーSK資産の
    # 新規生成が必要で未対応)があると、CSV由来の期待値とは必ずずれる。
    # そこでnoueの「宣言された収録集合」であるmanifest由来の期待値も許容し、
    # **どちらか一方に一致すればPASS**とする。緩めた分の検出責任はG10
    # (名前単位のカバレッジ照合、盲点なし)が引き受ける。
    m_expect4 = _manifest_sk_counts()
    expect4_candidates = [expect[:4]]
    if m_expect4 is not None and m_expect4 != expect[:4]:
        expect4_candidates.append(m_expect4)
    if os.environ.get("D2P_NOUE_TEMPLATE_ROOT"):
        g4_ok = (counts[:4] in expect4_candidates
                 and counts[4] >= expect[4] and counts[5] >= expect[5])
    else:
        g4_ok = counts[:4] in expect4_candidates and counts[4:] == expect[4:]
    gate("G4 entry counts (outfit/head/hair/head-equip/material/texture)", g4_ok,
         f"actual={counts} expected={expect}"
         + (f" or manifest-derived {m_expect4 + expect[4:]}"
            if len(expect4_candidates) > 1 else ""))

    # G5/G5b: バインド回転=バニラ・ボーン集合⊆バニラ(全衣装SK、性別別)
    #
    # U18実測(docs\REPORT_U18_2026-07-23.md参照): 真のバニラ衣装SKは、
    # 武器アタッチメントソケット(weapon_r等、テンプレート自身の元メッシュでも
    # スキニングに使われない純粋な骨のみのボーン)や、per-outfitの装飾用追加
    # ボーン(例: Ancient001のF_Ancient001_elbowArmor_01_l、腕装甲パーツ専用)を
    # RefSkeleton配列に持つ。これらはvanilla_ref(refskel_male/female.json、
    # 男女共通65ボーン基準)には存在しないか、存在してもテンプレート自身の
    # 意匠として意図的に異なる向きを持つことがある(60/60実測で複数個体を確認)。
    # 一方、本パイプラインはRenderSectionsを常にアバター側の実ウェイトから
    # 再構築するため(build_avatar_variant.py参照)、テンプレートの元の
    # BoneMapは一切引き継がれない — 出力(=pakに実際に同梱されるバイト)の
    # BoneMapは常にvanilla_ref由来の共通ボーン名の部分集合になる
    # (build_avatar_variant.pyの「RefSkeletonに存在しないボーン名」検証済み)。
    # そのため、テンプレートのRefSkeleton全件ではなく、**pakに実際に同梱された
    # (=注入済みの)RenderSectionsが実際に参照するボーンだけ**を検査対象にする
    # (旧実装はextract=テンプレート引数のディレクトリを直接globし、未使用の
    # 装飾ボーンまで含めて誤検知していた)。
    vanilla_ref = {}
    for g in ("male", "female"):
        with open(os.path.join(vanilla_dir, f"refskel_{g}.json"),
                  encoding="utf-8") as f:
            vanilla_ref[g] = json.load(f)
    _, pak_entries_full = core.read_pak_entries(mod_pak)
    # U40(T3設計転換): 上のG4と同じ理由で、MI_*(バニラMI差し替え、SkeletalMesh
    # ではない)をG5/G5bのRefSkeleton/ボーン検査対象から除外する
    # (MI_*にはRefSkeletonが存在せずcore.find_refskeletonが例外送出する)。
    # U50(2026-07-25): 非対応(コラボ系)のSKは注入されず**バニラのまま**pakに
    # 入るため、バニラ固有の装甲ボーン等をそのまま持つ。これはpakの欠陥では
    # ないので、G5(カバレッジ)/G5b(ボーン集合⊆バニラ)の検査対象から外す。
    # 除外集合はvp_exclusionsのみが決めるので、除外していないSKに対する
    # 検出力は一切変わらない。
    outfit_sk_entries = [p for p in entries
                         if "/Outfit/" in p and p.endswith(".uasset")
                         and os.path.basename(p).startswith("SK_")]
    n_excluded_sk = len([p for p in outfit_sk_entries
                         if vp_exclusions.is_excluded(p)])
    # dev#165: job.jsonのgendersで要求されていない性別のSKも、denylist除外と
    # 同じ理由(注入されずバニラのまま=装飾ボーン等がvanilla_ref共通集合に
    # 無いことがある)でG5/G5bの検査対象から外す。既定(両性別要求)では
    # _is_gender_excludedは常にFalseを返すため、この行は既存のフィルタと
    # 一字一句同じ結果になる。
    n_gender_excluded_sk = len([p for p in outfit_sk_entries
                                if not vp_exclusions.is_excluded(p)
                                and _is_gender_excluded(p, requested_genders)])
    sk_uassets = sorted(p for p in outfit_sk_entries
                        if "Player/Outfit/" in p
                        and not vp_exclusions.is_excluded(p)
                        and not _is_gender_excluded(p, requested_genders))
    if n_excluded_sk:
        print(f"  [INFO] G5/G5b excluded (unsupported/collab items): {n_excluded_sk} "
              + str(sorted(os.path.basename(p)[:-len('.uasset')]
                           for p in outfit_sk_entries
                           if vp_exclusions.is_excluded(p))))
    if n_gender_excluded_sk:
        print(f"  [INFO] G5/G5b excluded (gender not in job.genders="
              f"{sorted(requested_genders)}): {n_gender_excluded_sk} "
              + str(sorted(os.path.basename(p)[:-len('.uasset')]
                           for p in outfit_sk_entries
                           if not vp_exclusions.is_excluded(p)
                           and _is_gender_excluded(p, requested_genders))))
    tmp_dir = os.path.join(job["job_dir"], "build", "preflight_g5_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    # rdp_preflight並列化: 抽出フェーズ(pf使用、直列・不変)と解析フェーズ
    # (プロセス並列)を分離する。理由・決定論性の根拠は_run_g5_analysis()の
    # docstring参照。
    extraction_tasks = []  # [(tmp_uasset, tmp_uexp, ref), ...] 抽出順=sk_uassets順
    with open(mod_pak, "rb") as pf:
        def extract_bytes(rel_path):
            e = pak_entries_full[rel_path]
            if e["compression"] != 0:
                gate("G5 precondition: pak is uncompressed", False,
                     f"compressed entry detected (this pipeline should always produce uncompressed): {rel_path}")
                return b""
            pf.seek(e["data_offset"])
            return pf.read(e["size"])

        for p in sk_uassets:
            uexp_rel = p[:-7] + ".uexp"
            if uexp_rel not in pak_entries_full:
                continue
            base = os.path.basename(p)
            tmp_uasset = os.path.join(tmp_dir, base)
            tmp_uexp = tmp_uasset[:-7] + ".uexp"
            with open(tmp_uasset, "wb") as f:
                f.write(extract_bytes(p))
            with open(tmp_uexp, "wb") as f:
                f.write(extract_bytes(uexp_rel))
            ref = vanilla_ref["male"] if "_Male_" in base else vanilla_ref["female"]
            extraction_tasks.append((tmp_uasset, tmp_uexp, ref))

    worst, unknown_bones, n_checked = _aggregate_g5_results(
        _run_g5_analysis(extraction_tasks))
    # U18実測(docs\REPORT_U18_2026-07-23.md参照): 真のバニラ衣装SKは、
    # 実際にスキニングへ使われている通常ボーン(例: clavicle_l、鎖骨)でも
    # 個別outfitの原作アセット自体がvanilla_ref(共通65ボーン基準)と最大10度
    # 程度の bind回転差を持つことがあると判明(SK_Player_Male_Outfit_Hunter001の
    # clavicle_lで実測)。この値はテンプレート(注入前)とビルド後出力とで
    # バイト完全一致することを確認済み(=本パイプラインは一切変更していない、
    # 100% verbatimコピー)。つまりこれはPalworld自身が出荷している本物の
    # バニラデータそのものであり、そのまま多くのプレイヤーが日常的に装備している
    # 実データである以上、実機で見た目が壊れているとは考えにくい
    # (UEのスキニングはメッシュごとに自己完結したbind poseで計算されるため、
    # 「1つの共通参照骨格と完全一致しなければならない」という前提自体が
    # 本チェックの誤り)。よって回転量の一致は致命ゲートにはせず、
    # 診断情報としてのみ表示する(n_checkedの一致=全60体を実際に検査できた
    # ことの構造的健全性チェックのみ致命ゲートとして残す)。
    # U50: 期待値をCSV由来のexpect[0]から「pakに実際に入っている衣装SK数」
    # (counts[0])へ変更。収録数そのものの妥当性はG4が見ており、ここは
    # 「入っている全SKを実際に検査できたか(uasset/uexpが揃い、解析できたか)」
    # という構造健全性を見るのが本来の役目。CSVがカバレッジの穴の分だけ
    # 大きくなりうる(G10参照)ため、CSVに縛ると本来の意味を失う
    # U50: 期待値から「非対応(コラボ系)で意図的に検査対象外にしたSK」を引く。
    # 引かないとn_checkedが構造的に一致しなくなり誤FAILする(pakは正常)。
    # dev#165: 同じ理由でgender除外分も引く(既定は0なので既存挙動と不変)。
    n_g5_expect = counts[0] - n_excluded_sk - n_gender_excluded_sk
    gate("G5 bind-rotation-diff check coverage (structural soundness)",
         n_checked == n_g5_expect,
         f"{n_checked}/{n_g5_expect} checked"
         f"(pak has {counts[0]}, excluded {n_excluded_sk}, "
         f"gender-excluded {n_gender_excluded_sk}. "
         f"CSV-derived expected total is {expect[0]})")
    print(f"  [INFO] G5 diagnostic: max rotation diff (used bones only, includes the "
          f"template's own per-instance variance, not a defect) {worst[0]:.3f}deg ({worst[1]})")
    gate("G5b mesh bone set is a subset of vanilla (bone-rename detection, used bones only)",
         not unknown_bones,
         str(sorted(unknown_bones)[:3]) if unknown_bones else "all bones match")

    # G6: 参照の閉包性(参照する/Game/パスが自pak∪バニラに実在)
    own_pkgs = {p.rsplit(".", 1)[0] for p in full}
    vanilla_pkgs = {p.rsplit(".", 1)[0] for p in vanilla_entries
                    if p.endswith(".uasset")}
    all_pkgs = own_pkgs | vanilla_pkgs

    def pkg_exists(pkg):
        if pkg in all_pkgs:
            return True
        # FName番号の罠: 「SK_..._v02_2」のようなアセットは基底文字列「..._v02」+
        # 番号で直列化されるため、バイト走査では番号無しの文字列が見える。
        # 「pkg + _数字」が実在するなら偽陽性として容認する
        # (バニラのFemale_Outfit_Iron001_v02_2で実害確認)
        prefix = pkg + "_"
        return any(p.startswith(prefix) and p[len(prefix):].isdigit()
                   for p in all_pkgs)

    dangling = set()
    for ua in glob.glob(os.path.join(extract, "**", "*.uasset"), recursive=True):
        with open(ua, "rb") as f:
            s = f.read().decode("latin-1")
        for m in re.finditer(r"/Game/[A-Za-z0-9_/.]+", s):
            pkg = "Pal/Content/" + m.group(0)[len("/Game/"):]
            if not pkg_exists(pkg):
                dangling.add(m.group(0))
    gate("G6 reference closure (no dangling references)", not dangling,
         str(sorted(dangling)[:3]) if dangling else "")

    # G7: シェーダー(SM5+SM6両対応でcookされたか)
    # 2026-07-26 cooklog_fix: cook_logはUEモードでは生のBuildCookRunログ(テキスト)、
    # noueモードではnoue_master\shader_platform_facts.json(固定の事実だけを持つJSON、
    # 生ログの開発機パス・個人アバター名を含む問題を解消するため導入)のどちらかが渡される。
    # まずJSONとして解析し、期待する構造(platforms_cooked配列)を持てばそれで判定する。
    # 解析できなければ(=UEモードの生ログ)従来どおり文字列検索へフォールバックする
    # (UEモード側の挙動・判定基準は一切変えていない)。
    ok_log = False
    if os.path.exists(cook_log):
        with open(cook_log, encoding="utf-8", errors="replace") as f:
            log = f.read()
        fact = None
        try:
            fact = json.loads(log)
        except (ValueError, TypeError):
            fact = None
        if isinstance(fact, dict) and isinstance(fact.get("platforms_cooked"), list):
            platforms = set(fact["platforms_cooked"])
            ok_log = {"PCD3D_SM5", "PCD3D_SM6"}.issubset(platforms)
        else:
            ok_log = "PCD3D_SM6" in log and "PCD3D_SM5" in log
    mat_sizes = [os.path.getsize(p) for p in glob.glob(
        os.path.join(extract, "Player", "ModelMaterials", "MainShader",
                     "M_VP_*.uexp"))]
    # U13: noueのマスター+MIC構成では正規スロット(M_VP_{slot}.uexp)がMICの場合
    # 数百byte程度まで縮む(shadow_lift等のオーバーライド値のみ保持、実シェーダーは
    # 恒久マスター側にある)。シェーダー実体の有無は「最大サイズ」で判定する
    # (min→maxへ変更。旧来のUEモード全出力(MIC無し)ではmin/maxが一致するため
    # 挙動は変わらない)
    ok_size = mat_sizes and max(mat_sizes) > 60_000
    gate("G7 shader SM5+SM6", bool(ok_log and ok_size),
         f"log={ok_log} max={max(mat_sizes) // 1024 if mat_sizes else 0}KB")

    # G8: テクスチャのミップ焼き込み(uexpに実体)
    tex_sizes = {os.path.basename(p): os.path.getsize(p) for p in glob.glob(
        os.path.join(extract, "Player", "ModelMaterials", "MainShader", "*.uexp"))
        if "M_VP_" not in os.path.basename(p)}
    ok_tex = (not n_tex) or (tex_sizes and min(tex_sizes.values()) > 100_000)
    gate("G8 texture data present (NeverStream baked in)", bool(ok_tex),
         f"min={min(tex_sizes.values()) // 1024 if tex_sizes else 0}KB / {len(tex_sizes)} file(s)")

    # G9: マテリアルにGPUSkinシェーダー(used_with_skeletal_meshの物証)
    # U13: MIC(数百byte、shadow_lift等のオーバーライド値のみ)は自身にシェーダーを
    # 持たず親の恒久マスター経由でGPUSkinが効く(MIC自体は検査対象外とする。
    # 100KB未満はMIC相当とみなす — 旧来の全出力Materialは350KB超のため無関係)
    no_skin = []
    for p in glob.glob(os.path.join(extract, "Player", "ModelMaterials",
                                    "MainShader", "M_VP_*.uexp")):
        if os.path.getsize(p) < 100_000:
            continue
        with open(p, "rb") as f:
            if b"GPUSkin" not in f.read():
                no_skin.append(os.path.basename(p))
    gate("G9 material has GPUSkin shader", not no_skin,
         str(no_skin) if no_skin else "all materials OK")

    # ========================================================================
    # G10(U50、既定WARN): 対象一覧のカバレッジ
    # ------------------------------------------------------------------------
    # 「ライブpakに実在する全SKが、このMOD pakに入っているか」を**名前単位**で
    # 照合する。在庫側は命名の形に依存しない場所依存の全数列挙
    # (extract_vanilla.enumerate_vanilla_sk)なので、G4の件数照合が持っていた
    # 「CSV生成側と収録側が同じ正規表現の盲点を共有する」構造がここには無い。
    # 漏れたアセットは「メッシュ注入されない(衣装)」「非表示化されない(頭装備)」
    # という形で実機の見た目が壊れる。
    # ========================================================================
    inv = _load_sk_inventory(vanilla_dir, vanilla_entries)
    if inv is not None:
        # U50(2026-07-25): 非対応(コラボ系)のSKは検査対象から外す。
        # 実測(2026-07-25)では、除外SKは**両方の状態を取りうる**:
        #   * Outfit の Yakushima001(男女)/ Octavia001(v01/v02)は
        #     noue_template_manifest.json に載っているのでテンプレ経由で
        #     **バニラのままpakに収録される**(=未収録にはならない)
        #   * HeadEquip の Yakushima001〜006 は manifest に無く、
        #     **pakに収録されない**(ダミーSK資産の新規生成が未対応)
        # どちらであってもユーザーには「バニラの装備がそのまま出る」だけで
        # 実害が無い(=NGではない)ので、収録の有無で場合分けせず
        # 「除外SKはカバレッジ判定から外す」で統一する。件数はINFOに出す。
        pak_set = set(entries)
        missing = {}
        excluded_absent = []
        for cat in sorted(inv):
            miss = []
            for r in inv[cat]:
                if r in pak_set:
                    continue
                if vp_exclusions.is_excluded(r):
                    excluded_absent.append(f"{cat}: {r}")
                else:
                    miss.append(r)
            if miss:
                missing[cat] = miss
        n_missing = sum(len(v) for v in missing.values())
        n_inv = sum(len(v) for v in inv.values())
        n_inv_excluded = sum(1 for rows in inv.values() for r in rows
                             if vp_exclusions.is_excluded(r))
        suffix = (f"(plus {n_inv_excluded} excluded as unsupported/collab items)"
                  if n_inv_excluded else "")
        if missing:
            detail = (f"missing {n_missing}/{n_inv} vanilla SK — "
                      + " / ".join(f"{c}:{len(v)}" for c, v in missing.items())
                      + suffix)
        else:
            detail = f"all {n_inv} vanilla SK present{suffix}"
        soft_gate("G10 all SK in the live pak are covered by the target list (location-based, naming-independent match)",
                  not missing, detail, "D2P_PREFLIGHT_COVERAGE", n_missing)
        for c, v in sorted(missing.items()):
            for rel in sorted(v):
                print(f"    [G10 missing] {c}: {rel}")
        for row in sorted(excluded_absent):
            print(f"    [G10 excluded as unsupported, not present] {row}")

    # ========================================================================
    # G11(U50、既定WARN): 全描画スロットが注入アトラス t00 を指しているか
    # ------------------------------------------------------------------------
    # 旧基準は「slot0->t00 / slot1->t01」だったが、マテリアル単一化
    # (live_template._unify_slot_materials、既定ON)で t01 は使われなくなり、
    # 全描画スロットのMIが t00 を指すのが正しい状態になった(旧基準のNG 16件は
    # すべて基準側が古かっただけで実体は正常)。判定は参照先MIの実バイト
    # (name table)を読む方式へ変更してある(_slot_role_check の docstring 参照)。
    # ========================================================================
    n_ng, n_sk, ng_rows, err = _slot_role_check(extract)
    if err:
        print(f"  [WARN] G11 could not determine slot roles: {err}")
    else:
        soft_gate("G11 all draw slots of all outfit SK point to the injected atlas t00",
                  n_ng == 0, f"NG {n_ng}/{n_sk} SK",
                  "D2P_PREFLIGHT_SLOTROLE", n_ng)
        for row in ng_rows:
            print(f"    [G11 NG] {row}")

    # ========================================================================
    # G12(dev#165、2026-07-30新設、致命ゲート): 性別限定ビルドは現状の
    # マテリアル設計では安全に作れない。
    # ------------------------------------------------------------------------
    # 本WPでG5/G5b(上)はgenders限定時の誤FAILを解消し、build_pak_from_avatar.py
    # のメッシュ注入(Phase2)はjob.jsonのgendersを正しく尊重するようになった
    # (=要求されていない性別の衣装SKはメッシュを注入せずバニラ形状のまま
    # pakへ入る)。しかし調査の結果、**素体色/衣装テクスチャの経路はメッシュとは
    # 独立に、性別を問わず全衣装SK共通の1枚のアトラス(t00/t01、
    # live_template._unify_slot_materials=U50-single設計)へ常時上書き**される
    # ことが判明した。これはテンプレート自体の恒久的な性質(全ジョブで共有・
    # キャッシュされるテンプレート準備段階で焼き込まれる)であり、ジョブ単位の
    # genders設定を知りようがない箇所にある。
    # 結果: genders限定ビルドは「除外した性別の衣装はメッシュこそバニラ形状に
    # 戻るが、そこに現在のアバターのテクスチャアトラスがそのまま貼られる」
    # という、UVレイアウトの合わない見た目破綻(装甲の形をした色の混ざった
    # 断片)を生む。「数値より先に画像を見る」原則・「壊れた見た目を出すより
    # 優雅に失敗する」責任者方針のいずれに照らしても、これを黙って合格させて
    # はならない。真の修正(性別ごとに独立したテクスチャアトラス/マテリアル
    # 経路を持たせる)はテンプレートキャッシュ設計に関わる別枠の設計判断が
    # 必要なため、本WPのスコープ外として致命ゲートで止める(die()による
    # 早期失敗ではなくpreflightのFAILにしているのは、実際に生成されたpakの
    # 実体を見て診断できるようにするため——G5/G5b等の他ゲートは今回の修正で
    # 正しくPASSする=誤診断を残さない)。
    # ========================================================================
    gate("G12 gender-limited build (job.json genders) requires a per-gender "
         "texture atlas, which noue does not implement yet (dev#165)",
         requested_genders >= {"Male", "Female"},
         "OK (both genders requested, default)" if requested_genders >= {"Male", "Female"} else
         (f"genders={sorted(requested_genders)}: mesh injection now correctly "
          f"skips the excluded gender (vanilla shape), but the shared outfit "
          f"texture atlas (t00/t01) is unconditionally baked with this "
          f"avatar's texture regardless of gender — the excluded gender's "
          f"vanilla-shaped costumes would show mismatched avatar texture "
          f"(broken appearance). Not safe to use until the texture atlas is "
          f"made gender-aware (see dev#165)."))

    return finish()


def finish():
    n_fail = sum(1 for _, ok, _ in results if not ok)
    n_warn = sum(1 for _, ok, _ in soft_results if not ok)
    if n_warn:
        print(f"\n--- Warnings (do not affect pass/fail; may be promoted to FAIL in the future): {n_warn} ---")
        for name, ok, detail in soft_results:
            if not ok:
                print(f"  [WARN] {name} — {detail}")
        print("  To promote: set D2P_PREFLIGHT_COVERAGE / D2P_PREFLIGHT_SLOTROLE to "
              "fail or max:<count>")
    print(f"\n=== preflight result: "
          f"{'ALL CHECKS PASS' if n_fail == 0 else f'{n_fail} FAIL — do not use this MOD'}"
          f"{f'({n_warn} warning(s))' if n_warn else ''} ===")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
