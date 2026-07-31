# -*- coding: utf-8 -*-
"""U6-T2: step02.blend → pak 一気通貫CLI(UE非依存パイプラインの本統合)。

1コマンドで以下を実行する(UnrealPak.exe不使用。同梱Blender+numpyのみ):
  1) 同梱Blender headlessで --step02-female/--step02-male を実アバターメッシュへ
     ダンプ(`research\\ue_exit\\dump_avatar_mesh.py`、無改変・そのまま呼び出し)
  2) 衣装SK 60体へ性別別に実アバターを注入
     (`research\\ue_exit\\build_avatar_variant_all.py`の
     `collect_targets`/`gender_of`/`build_and_validate`をimport再利用、無改変)
  3) 残り375件(スタブ153+マテリアル+テクスチャ+アンカー等)は
     --template からそのままコピー
  4) `vp_pakwrite.py`(U6-T1、本ファイルと同じpipeline\\py配下、新規)でpak化
     (UnrealPak不使用)
  5) `preflight_pak.py`を自動実行して結果を表示

既存ファイル(vp_core.py/vp_meshrestore.py/preflight_pak.py/
research\\ue_exit\\build_avatar_variant*.py/dump_avatar_mesh.py)は一切変更しない。
本ファイルはそれらをimport/subprocessで呼び出すだけの新規オーケストレータ
(pipeline\\py\\restore_full.pyと同じ設計方針)。

実行例:
  python build_pak_from_avatar.py \\
      --step02-female work\\toto\\converted\\step02_female.blend \\
      --step02-male   work\\alicia\\converted\\step02_male.blend \\
      --template work\\toto\\build\\pak_extract \\
      --out out\\avatar.pak
  (--job-jsonの既定値はwork\\toto系。他jobで使う場合は明示指定。
   --cook-logの既定値はpipeline\\py\\noue_master\\shader_platform_facts.json
   (noueモード共通の固定事実ファイル、2026-07-26 cooklog_fix)。UEモードの実cookログを
   使いたい場合のみ明示指定する)
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))       # pipeline\py
PIPELINE_DIR = os.path.dirname(HERE)                     # pipeline\
REPO_DIR = os.path.dirname(PIPELINE_DIR)                 # リポジトリルート

sys.path.insert(0, HERE)
import vp_exclusions  # noqa: E402
import vp_pakwrite  # noqa: E402
import vp_texinject  # noqa: E402
import vp_parallel  # noqa: E402 (rd_120: Phase1/Phase2並列化の共有ヘルパー)
# U51(research\ue_exit→pipeline\py移設): build_avatar_variant*.py/dump_avatar_mesh.py
# は元research\ue_exit\から無改変のままpipeline\py\へコピーされ、以降はHEREから
# 直接import/参照する(research\ue_exit\側は開発参照用に残置、実行時には見ない)
from build_avatar_variant import load_dump  # noqa: E402
from build_avatar_variant_all import (  # noqa: E402
    build_and_validate, collect_targets, gender_of,
)

TAG = "build_pak_from_avatar"

DEFAULT_BLENDER_EXE = (
    r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe")
DEFAULT_DUMP_SCRIPT = os.path.join(HERE, "dump_avatar_mesh.py")
DEFAULT_PREFLIGHT = os.path.join(HERE, "preflight_pak.py")
DEFAULT_JOB_JSON = os.path.join(REPO_DIR, "work", "toto", "job.json")
# 2026-07-26 cooklog_fix: 旧既定値 work\toto\build\logs\cook.log は開発機にしか無い上
# 個人アバター名"toto"を含んでいた。noueモードでpreflightが本来参照すべきは
# pipeline\py\noue_master\shader_platform_facts.json(SM5/SM6双方でcook済みという
# 固定の事実、live_template.COOK_LOGと同じ実体)であり、これはリポジトリにも配布物にも
# 常に存在するため、スタンドアロン実行時の既定値として妥当(convert_noue.py経由の
# 通常実行では--cook-logが明示的に上書きされるため、この既定値は直接呼び出し時のみ使う)。
DEFAULT_COOK_LOG = os.path.join(HERE, "noue_master", "shader_platform_facts.json")

# U6-T3(ストレッチ): avatar_meta.json実測(m00=body/t00.png, m01=parka/t01.png、
# docs\REPORT_U5_2026-07-23.md T1b節参照)固定のテクスチャスロット対応
TEX_SLOT_REL = {
    "body": "Player/ModelMaterials/MainShader/t00.uexp",
    "parka": "Player/ModelMaterials/MainShader/t01.uexp",
}


def die(msg):
    print(f"[{TAG}][FATAL] {msg}")
    sys.exit(1)


def run(cmd, log_path):
    """subprocessを実行し、ログをファイルへ保存する。失敗したら末尾を出して停止する。
    (restore_full.py の run() と同じ流儀)"""
    print(f"[{TAG}] $ {' '.join(cmd)}")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        tail = ""
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-3000:]
        except OSError:
            pass
        die(f"command failed exit={r.returncode} (log: {log_path})\n"
            f"--- log tail ---\n{tail}")
    print(f"[{TAG}]   -> OK (log: {log_path})")


# === rd_120 5.3: Female/Maleダンプの並列化 ==================================
# vp_parallel.run_pair_parallel()(ThreadPoolExecutor、subprocess.run()待ちが
# 大半でCPUを食わないI/Oバウンド処理なのでスレッドで十分)へ委譲する。
# ダンプ本体はrun()をそのまま呼ぶ(die()を含む既存の失敗時挙動を変えない)。
# die()がワーカースレッド内で呼ばれても、run_pair_parallel()のcontext manager
# がもう片方のダンプの完了を待ってから例外を伝播する(vp_parallel.pyの
# モジュールdocstring参照)ので、Female/Male両方の診断ログが必ず残る。
def _dump_gender(args):
    gender, blend, blender_exe, dump_blender_args, out_json, log_path, max_influences = args
    print(f"[{TAG}] === Phase 1: {gender} dump ===")
    run([blender_exe, "--background", "--factory-startup", *dump_blender_args,
         "--python-exit-code", "1", "--python",
         DEFAULT_DUMP_SCRIPT, "--", blend, gender, out_json, str(max_influences)],
        log_path)
    if not os.path.exists(out_json):
        die(f"{gender} dump produced no output: {out_json}")
    return gender, out_json


# === rd_120 5.1: Phase2 SK注入ループのプロセス並列化 =========================
# `dump`辞書(gender別、数百KB)をタスク引数として58回渡すと再pickleコストが
# 乗るため、initializer(_init_worker)でワーカープロセスごとに1回だけ
# モジュールグローバルへ積む(PROPOSAL 5.1節)。タスク引数は軽量タプルのみ。
_WORKER_DUMPS = None


def _init_worker(dumps):
    global _WORKER_DUMPS
    _WORKER_DUMPS = dumps


def _injection_worker(task):
    """1件のSK注入をワーカープロセスで実行する。現行の
    `try: build_and_validate(...) except Exception as e: ...`をそのまま踏襲し、
    **例外を外へ投げず** (rel_uexp, gender, ok, errs, info) を返す
    (=1件の失敗が他タスクの実行・結果収集を止めない。tests\\parallel\\
    test_pak_parallel.pyの負の対照テスト参照)。"""
    uexp_path, uasset_path, gender, out_uexp, out_uasset, rel_uexp = task
    dump = _WORKER_DUMPS[gender]
    try:
        ok, errs, info = build_and_validate(uexp_path, uasset_path, dump, out_uexp, out_uasset)
    except Exception as e:
        ok, errs, info = False, [str(e)], {}
    return rel_uexp, gender, ok, errs, info


def _default_injection_workers():
    """既定ワーカー数=max(1, cpu_count-2)。D2P_INJECT_WORKERS環境変数で上書き可
    (rd_120 PROPOSAL 8節論点1)。"""
    return vp_parallel.default_worker_count("D2P_INJECT_WORKERS", floor=2)


# === dev#288(L2/L2b重畳): Phase 2(sk_injection)とPhase 2b/2c/2d(overrides) ===
# NOTES.md(work\speed_mission\l2l2b\NOTES.md)の入出力独立性の列挙どおり、
# 書き込み先(sk_injection: variant_dir配下 Player/Outfit/... / overrides:
# tex_dir配下 Player/ModelMaterials/MainShader/... とメモリ上のdict)は互いに
# 素で、共有可変状態も無い。ロジック自体は無変更、元main()の該当ブロックを
# そのまま関数へ切り出しただけ(die()呼び出し・print文・変数名も同一)。
def _run_sk_injection(template, requested_genders, variant_dir, dumps):
    """Phase 2: 衣装SK 60体へ性別別に実アバターを注入する。戻り値: targets_rel
    (注入に成功したSKのtemplate相対パス列、Phase 3のreplace_map構築に使う)。"""
    print(f"[{TAG}] === Phase 2: injecting real avatar into outfit SKs ===")
    outfit_root = os.path.join(template, "Player", "Outfit")
    pairs = collect_targets(outfit_root)
    # U40(T3設計転換): live_template.pyがPlayer/Outfit/配下にMI_*(バニラMI
    # 差し替え、SkeletalMeshではない)を追加で置くようになったため、
    # collect_targets(拡張子のみでの機械的な.uexp/.uassetペア収集、
    # research\ue_exit\build_avatar_variant_all.py、無改変維持)がそれも
    # 「衣装SK」として拾ってしまう。MI_*はメッシュではなくindex bufferを
    # 持たないため実アバター注入は必ず失敗する(意図通り、対象外)。
    # ファイル名がSK_で始まるものだけを注入対象とし、MI_*はここで除外して
    # Phase 3の「残りはテンプレートのままコピー」経路に委ねる
    # (=T3パッチ済みのバイト列がそのまま最終pakへ入る)。
    before_filter = len(pairs)
    pairs = [(u, a) for u, a in pairs if os.path.basename(u).startswith("SK_")]
    n_excluded_mi = before_filter - len(pairs)
    if n_excluded_mi:
        print(f"[{TAG}] T3: excluding {n_excluded_mi} MI_* (vanilla MI replacement, "
              f"non-mesh) from real-avatar injection targets (included in the pak as-is from the template)")
    # U50(2026-07-25、責任者裁定「コラボ系アイテムは非対応です」):
    # 除外対象のSKには実アバターを注入しない。注入しなければ Phase 3 の
    # 「残りはテンプレートのままコピー」経路に乗り、**バニラの装備がそのまま
    # 出る**(方針「失敗するにしても優雅に失敗する」)。
    # 正本は pipeline\py\vp_exclusions.py(そこへ足せば全経路に効く)。
    kept = []
    excluded = []
    # dev#165(2026-07-30): 「--gendersで要求されていない性別のSK」を、
    # 既存のdenylist除外(コラボ衣装)と全く同じPhase3バニラコピー経路に
    # 乗せる。新しいフォールバック機構を作らず、preflight_pak.py G3/G4/G5が
    # 既に許容している「注入されずバニラのままpakに入る」経路を再利用する
    # ことで最小の変更にとどめる。既定(genders未指定=Male,Female両方要求)
    # ではgender_of(...)の結果は必ずrequested_gendersに含まれるため、この
    # 分岐には一切入らず、既存のkept/excluded列と一字一句同じになる。
    gender_excluded = []
    for u, a in pairs:
        if vp_exclusions.is_excluded(u):
            excluded.append(u)
        elif gender_of(os.path.basename(u)) not in requested_genders:
            gender_excluded.append(u)
        else:
            kept.append((u, a))
    pairs = kept
    if excluded:
        print(f"[{TAG}] {len(excluded)} SK(s) not injected (unsupported/collab items) "
              f"= vanilla equipment will appear as-is:")
        for u in excluded:
            print(f"[{TAG}]   - {os.path.basename(u)} "
                  f"({vp_exclusions.excluded_reason(u)})")
    if gender_excluded:
        print(f"[{TAG}] {len(gender_excluded)} SK(s) not injected "
              f"(gender not in --genders={sorted(requested_genders)}) "
              f"= vanilla equipment will appear as-is:")
        for u in gender_excluded:
            print(f"[{TAG}]   - {os.path.basename(u)}")
    print(f"[{TAG}] target SK: {len(pairs)}")
    # rd_120 5.1: ProcessPoolExecutorでpairsを並列注入する。
    # 順序非依存の根拠(PROPOSAL 3節、build_and_validate()自体は無改変):
    #   各SKの入力(uexp_path/uasset_path/dump)は互いに独立、出力(out_uexp/
    #   out_uasset)も他SKのファイルに一切触れないSK専用パス。並列化後の
    #   出力を束ねるPhase 3(下記)は`targets_rel`の"集合"だけを見て
    #   replace_mapを作り、実ファイル列挙順はテンプレート側のディレクトリ順
    #   (vp_pakwrite.collect_files)であって注入ループの実行順ではないため、
    #   Phase2をどんな順序・並行度で実行しても最終pakはバイト完全一致する。
    #   vp_parallel.run_pool_ordered()はexecutor.map()を使い、結果を**入力順
    #   (=pairsの列挙順)**で返すため、下のprint順・n_fail集計・targets_rel
    #   構築順は逐次実行時と1文字も変わらない。
    tasks = []
    for uexp_path, uasset_path in pairs:
        rel_uexp = os.path.relpath(uexp_path, template).replace("\\", "/")
        gender = gender_of(os.path.basename(uexp_path))
        out_uexp = os.path.join(variant_dir, rel_uexp)
        out_uasset = out_uexp[:-5] + ".uasset"
        tasks.append((uexp_path, uasset_path, gender, out_uexp, out_uasset, rel_uexp))

    n_workers = _default_injection_workers()
    print(f"[{TAG}] injecting {len(tasks)} SK(s) with {n_workers} worker process(es) "
          f"(override via D2P_INJECT_WORKERS)")
    injection_results = vp_parallel.run_pool_ordered(
        _injection_worker, tasks, n_workers, initializer=_init_worker, initargs=(dumps,))

    targets_rel = []
    n_fail = 0
    gender_counts = {"Male": 0, "Female": 0}
    for rel_uexp, gender, ok, errs, info in injection_results:
        gender_counts[gender] += 1
        status = "OK" if ok else "FAIL"
        print(f"[{TAG}] [{status}] {rel_uexp} gender={gender} "
              f"numv={info.get('num_vertices')} tri={info.get('num_triangles')}" +
              (f" errs={errs}" if errs else ""))
        if not ok:
            n_fail += 1
        else:
            targets_rel.append(rel_uexp)
    if n_fail:
        die(f"outfit SK injection failed for {n_fail} (see log above for details)")
    print(f"[{TAG}] outfit SK injection: {len(targets_rel)}/{len(pairs)} succeeded "
          f"(gender_counts={gender_counts})")
    print(f"[{TAG}] === Phase2Subphase: sk_injection done ===")
    return targets_rel


def _run_overrides(args, template, work):
    """Phase 2b/2c/2d: テクスチャ/マテリアル/シャドウリフトMIの差し替えを
    準備する。戻り値: (tex_replace, mat_override, mi_override)(いずれも
    {pak内相対パス: 差し替え元ファイルパス} のdict、Phase 3のreplace_map
    構築に使う)。"""
    print(f"[{TAG}] === Phase2Subphase: overrides start ===")
    # === Phase 2b(U6-T3ストレッチ): テクスチャ注入 ===
    tex_dir = os.path.join(work, "tex")
    tex_args = {"body": args.tex_body, "parka": args.tex_parka}
    tex_alpha_coverage = {"body": args.tex_body_alpha_coverage,
                           "parka": args.tex_parka_alpha_coverage}
    tex_replace = {}
    for slot, png_path in tex_args.items():
        if not png_path:
            continue
        png_path = os.path.abspath(png_path)
        if not os.path.exists(png_path):
            die(f"--tex-{slot} does not exist: {png_path}")
        rel = TEX_SLOT_REL[slot]
        template_uexp = os.path.join(template, *rel.split("/"))
        out_uexp = os.path.join(tex_dir, rel)
        print(f"[{TAG}] === Phase 2b: texture injection ({slot}: {png_path}) ===")
        info = vp_texinject.inject_texture_file(
            template_uexp, png_path, out_uexp,
            alpha_coverage=tex_alpha_coverage[slot], gain=args.tex_gain)
        print(f"[{TAG}]   {rel}: {info['pixel_format']} {info['size_x']}x{info['size_y']} "
              f"PSNR={info['psnr']:.2f}dB gain={info['gain']:.4f}"
              f"(version={info['gain_version']})")
        tex_replace[rel] = out_uexp

    # === Phase 2c(U13): マテリアル差し替え(バリアント選択+shadow_liftパッチ済み) ===
    mat_override = {}
    if args.mat_override_dir:
        mo_dir = os.path.abspath(args.mat_override_dir)
        for fn in sorted(os.listdir(mo_dir)):
            rel = f"Player/ModelMaterials/MainShader/{fn}"
            mat_override[rel] = os.path.join(mo_dir, fn)
        print(f"[{TAG}] material replacement: {len(mat_override)} ({mo_dir})")

    # === Phase 2d(U50-fast): 影の濃さ(shadow_lift)を焼き込んだ統一MIの差し替え ===
    # Phase 2c と同じ「後段でMIファイルを差し替える」形。違いは木構造で置かれて
    # いる点だけ(相対パスがそのままpak内パスになる)。これにより shadow_lift は
    # ライブテンプレート(879ファイル/約700MB)の再構築を必要としない。
    mi_override = {}
    if args.mi_override_dir:
        mi_dir = os.path.abspath(args.mi_override_dir)
        for dirpath, _d, filenames in os.walk(mi_dir):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, mi_dir).replace("\\", "/")
                mi_override[rel] = p
        print(f"[{TAG}] shadow-lift MI replacement: {len(mi_override)} ({mi_dir})")
    print(f"[{TAG}] === Phase2Subphase: overrides done ===")
    return tex_replace, mat_override, mi_override


def _run_phase2_overlap(template, requested_genders, variant_dir, dumps, args, work):
    """dev#288(L2/L2b重畳): Phase 2(sk_injection)とPhase 2b/2c/2d(overrides)を
    `vp_parallel.run_pair_parallel()`で並列実行する。戻り値:
    (targets_rel, (tex_replace, mat_override, mi_override))。

    独立性の根拠はNOTES.md(work\\speed_mission\\l2l2b\\NOTES.md)参照:
    書き込み先(variant_dir配下 Player/Outfit/... と tex_dir配下
    Player/ModelMaterials/MainShader/...)が互いに素で、共有可変状態も無い。

    run_pair_parallel()はThreadPoolExecutorのcontext managerがshutdown(wait=True)
    するため、片方が例外(die()のSystemExit含む)を投げてももう片方の処理は
    最後まで走り切ってから例外が呼び出し元(このtry無しの呼び出しならmain())へ
    伝播する(rd_120と同じ既存trade-off)。例外メッセージは元のdie()呼び出しを
    そのまま使うため、失敗内容が他方のものと誤認されることはない。"""
    sk_fn = lambda: _run_sk_injection(  # noqa: E731
        template, requested_genders, variant_dir, dumps)
    ov_fn = lambda: _run_overrides(args, template, work)  # noqa: E731
    targets_rel, overrides_result = vp_parallel.run_pair_parallel(
        lambda f: f(), [sk_fn, ov_fn])
    return targets_rel, overrides_result


def main():
    ap = argparse.ArgumentParser(
        description="step02_{gender}.blend + テンプレpak_extract から "
                     "ゲームに入れられるpakを1コマンドで生成する(UnrealPak不使用)")
    ap.add_argument("--step02-female", default=None,
                    help="--genders にFemaleが含まれる場合は必須")
    ap.add_argument("--step02-male", default=None,
                    help="--genders にMaleが含まれる場合は必須")
    ap.add_argument("--genders", default="Male,Female",
                    help="dev#165(2026-07-30): カンマ区切りでMale/Femaleの"
                         "部分集合を指定。既定はMale,Female(=従来どおり両方に"
                         "実アバターを注入)。指定から漏れた性別の衣装SKは"
                         "注入せずテンプレート(バニラ)のままpakへ入れる"
                         "(vp_exclusions denylist除外と同じPhase3経路)")
    ap.add_argument("--template", required=True,
                    help="pak_extractディレクトリ(435ファイル、性別衣装SK込み)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--blender", default=DEFAULT_BLENDER_EXE, help="Blender本体exe")
    ap.add_argument("--work", default=None,
                    help="作業ディレクトリ(ダンプ/中間生成物の置き場所)。"
                         "省略時は一時ディレクトリを新規作成する")
    ap.add_argument("--max-influences", type=int, default=8)
    ap.add_argument("--job-json", default=DEFAULT_JOB_JSON,
                    help="preflight_pak.py用job.json")
    ap.add_argument("--cook-log", default=DEFAULT_COOK_LOG,
                    help="preflight_pak.py用cook_log(UEモード:実cookログ / "
                         "noueモード:noue_master\\shader_platform_facts.json)")
    ap.add_argument("--skip-preflight", action="store_true")
    ap.add_argument("--tex-body", default=None,
                    help="U6-T3(ストレッチ): body(t00)スロットへ注入するPNG。"
                         "テンプレートと異なる解像度は自動リサイズ(ニアレストネイバー)")
    ap.add_argument("--tex-parka", default=None,
                    help="U6-T3(ストレッチ): parka(t01)スロットへ注入するPNG")
    ap.add_argument("--tex-body-alpha-coverage", action="store_true",
                    help="FIX2(2026-07-24): bodyテクスチャのミップ生成で"
                         "アルファカバレッジを保存する(avatar_meta.jsonの"
                         "alpha_mode==MASKスロット向け)")
    ap.add_argument("--tex-parka-alpha-coverage", action="store_true",
                    help="FIX2(2026-07-24): parkaテクスチャのミップ生成で"
                         "アルファカバレッジを保存する")
    ap.add_argument("--tex-gain", type=float, default=1.0,
                    help="U49(2026-07-25): 注入テクスチャ(body/parka共通)へ"
                         "掛ける明度ゲイン(shadow_lift接続、"
                         "vp_texinject.shadow_lift_gain()参照)。既定1.0=無補正"
                         "(従来どおりのピクセル列、convert_noue.pyがjob.jsonの"
                         "shadow_liftから計算して渡す)")
    ap.add_argument("--mat-override-dir", default=None,
                    help="U13: スロット別マテリアル(M_VP_{slot}.uasset/uexp)の"
                         "差し替え元ディレクトリ。convert_noue.pyがバリアント選択+"
                         "shadow_liftバイトパッチ済みのファイルを置く")
    ap.add_argument("--uniform-scale", type=float, default=1.0,
                    help="dev#157 / WP-I157(2026-07-30): サイズ可変。全ボーンの"
                         "ローカルTranslationをk倍(root不動点、"
                         "build_avatar_variant.apply_uniform_scale参照)。"
                         "既定1.0は完全no-op(pakバイト不変)。隠し設定"
                         "(GUI未露出、job.json手書き/本引数の直接指定専用)")
    ap.add_argument("--mi-override-dir", default=None,
                    help="U50-fast(2026-07-26): 影の濃さ(shadow_lift)を焼き込んだ"
                         "統一MIの差し替え元ディレクトリ。--mat-override-dirと違い"
                         "**pak内相対パスと同じ木構造**で置かれている"
                         "(Player/Outfit/.../MI_*.uasset 等)。"
                         "live_template.build_shadow_mi_overrides()が生成し、"
                         "convert_noue.pyが渡す。k=0(影の濃さ0)のときは1件も"
                         "生成されず、この引数自体が渡らない")
    args = ap.parse_args()

    # dev#165(2026-07-30): --genders で要求された性別だけがstep02パスを
    # 必須とする。既定"Male,Female"では従来どおり両方必須(挙動不変)。
    _valid_genders = {"Male", "Female"}
    requested_genders = {g.strip() for g in args.genders.split(",") if g.strip()}
    if not requested_genders or not requested_genders <= _valid_genders:
        die(f"--genders must be a non-empty comma-separated subset of "
            f"{sorted(_valid_genders)}: {args.genders!r}")

    step02_female = os.path.abspath(args.step02_female) if args.step02_female else None
    step02_male = os.path.abspath(args.step02_male) if args.step02_male else None
    step02_by_gender = {"Female": step02_female, "Male": step02_male}
    for g in sorted(requested_genders):
        if not step02_by_gender[g]:
            die(f"--genders includes {g} but --step02-{g.lower()} was not given")
    template = os.path.abspath(args.template)
    out_pak = os.path.abspath(args.out)
    blender_exe = os.path.abspath(args.blender)

    for p, label in ((step02_female, "--step02-female"), (step02_male, "--step02-male"),
                     (template, "--template"), (blender_exe, "--blender")):
        if p is not None and not os.path.exists(p):
            die(f"{label} does not exist: {p}")

    work = os.path.abspath(args.work) if args.work else tempfile.mkdtemp(
        prefix="d2p_build_pak_from_avatar_")
    os.makedirs(work, exist_ok=True)
    log_dir = os.path.join(work, "logs")
    dump_dir = os.path.join(work, "dump")
    variant_dir = os.path.join(work, "variant")
    os.makedirs(dump_dir, exist_ok=True)
    print(f"[{TAG}] work directory: {work}")

    # === Phase 1: Blender headlessで両性別をダンプ ===
    # WP-B3(2026-07-28): dump_avatar_mesh.py内のmesh.calc_tangents()
    # (Blender内蔵mikktspace)がBlenderのタスクスケジューラ(BLI_task)の
    # マルチスレッド評価に起因して実行のたびに1e-6オーダーで結果がブレる
    # ことを実測で確認した(同一.blend・同一スクリプトを単独プロセスで
    # 逐次2回実行しても、特定頂点のtangent成分だけが最終桁で相違。
    # pos/normal/uv/weightsは常に完全一致)。この揺れがbuild_avatar_variant.py
    # のencode_tangent_pair()での8bit量子化の境界をたまたま跨ぐと、
    # Outfit衣装SKのuexpが1バイトだけ変化し、pakのSHA256が実行ごとに
    # non-deterministicになる(release.py v1.1.4試行 run_20260728_054403で
    # 実際に発生、prefab_flatapronのOutfit系uexp 29件が変更ありでFAIL)。
    # `-t 1`(Blender CLIオプション、BLI_taskのスレッド数を1に固定)を
    # 付けた場合のみ、同一検証手順で3回連続バイト完全一致を確認済み。
    # calc_tangents()を呼ぶBlender起動はこのdump_avatar_mesh.py呼び出し
    # 1箇所だけ(pipeline全体をgrep済み、他のBlender工程は呼んでいない)
    # なので、ここにだけ限定して付与する(全Blender工程に付けると遅くなる)。
    dump_blender_args = ["-t", "1"]
    dumps = {}
    # rd_120 5.3: Female/Maleダンプ(Blenderヘッドレス2本)を並列実行する。
    # 唯一の制約(適用手順どおり厳守): dump_blender_args=["-t", "1"](上記の
    # WP-B3コメント参照)はプロセスごとの引数なので、2プロセスを並列に起動
    # しても各プロセス内部は引き続き-t 1のまま——この引数は変更しない。
    # この並列化はBlenderプロセスの起動本数を増やすだけで、各プロセス内部の
    # 決定性には一切触れない(=pakのSHA256決定性は不変、PROPOSAL 1節7項)。
    # dev#165(2026-07-30): --gendersで要求されていない性別はダンプしない
    # (該当step02パスがそもそも渡されていないためNoneであり得る)。
    # 既定"Male,Female"ではrequested_gendersが両方を含むため、この
    # フィルタは従来のタプルと一字一句同じ列を作り、既存挙動と不変。
    dump_tasks = [
        (gender, blend, blender_exe, dump_blender_args,
         os.path.join(dump_dir, f"avatar_{gender.lower()}.json"),
         os.path.join(log_dir, f"dump_{gender}.log"), args.max_influences)
        for gender, blend in (("Female", step02_female), ("Male", step02_male))
        if gender in requested_genders
    ]
    # dev#220追加計装(2026-07-30): 旧"variant_inject_sec"ラベルがPhase1(この
    # ダンプ)とPhase2(SK注入、下)を1つに束ねていたため、どちらが実際に
    # 支配的かを区別できなかった。開始/終了printだけの軽量観測(計算・出力に
    # 一切影響しない)。
    print(f"[{TAG}] === Phase1Subphase: avatar_dump start ===")
    dump_results = vp_parallel.run_pair_parallel(_dump_gender, dump_tasks)
    for gender, out_json in dump_results:
        dumps[gender] = load_dump(out_json)
        # U21: RefSkeletonバインドポーズ位置パッチ(build_avatar_variant.py
        # load_chibi_bone_world_head参照)向けに、真のjob_dir/convertedの
        # 場所を明示的に渡す。dump['source_blend']はUVアトラス焼き込み後の
        # blend(work/<job>/build/atlas/step02_{gender}_atlas.blend)を指して
        # おり、pipeline/blender/step02_retarget.pyがchibi_bone_world_head_
        # {gender}.jsonを書き出す本来のconvertedディレクトリ
        # (work/<job>/converted/)とは別の場所になる(U21初回実装で発覚した
        # バグ: source_blendのdirnameから逆算すると見つからず、パッチが
        # 常にサイレントno-opになっていた)。job.jsonの場所から直接
        # job_dir/convertedを解決する方が確実なので、こちらを明示的に渡す。
        dumps[gender]['_job_converted_dir'] = os.path.join(
            os.path.dirname(os.path.abspath(args.job_json)), "converted")
        # dev#157 / WP-I157: サイズ可変。build_avatar_variant.build_uexp_variant()が
        # dump.get('uniform_scale', 1.0)を読む(apply_uniform_scale参照)。
        dumps[gender]['uniform_scale'] = args.uniform_scale
    print(f"[{TAG}] === Phase1Subphase: avatar_dump done ===")

    # === Phase 2(sk_injection, L2) と Phase 2b/2c/2d(overrides, L2b)を重畳 ===
    # dev#288: 独立性の根拠はNOTES.md(work\speed_mission\l2l2b\NOTES.md)参照。
    targets_rel, (tex_replace, mat_override, mi_override) = _run_phase2_overlap(
        template, requested_genders, variant_dir, dumps, args, work)

    # === Phase 3: pak化(残り375件はテンプレートのまま、vp_pakwriteでpak化) ===
    print(f"[{TAG}] === Phase 3: building pak (mount={vp_pakwrite.DEFAULT_MOUNT}) ===")
    all_files = vp_pakwrite.collect_files(template)
    replace_map = dict(tex_replace)
    replace_map.update(mat_override)
    replace_map.update(mi_override)
    for rel_uexp in targets_rel:
        rel_uasset = rel_uexp[:-5] + ".uasset"
        replace_map[rel_uexp] = os.path.join(variant_dir, rel_uexp)
        replace_map[rel_uasset] = os.path.join(variant_dir, rel_uasset)

    final_files = []
    n_replaced = 0
    for src, rel in all_files:
        if rel in replace_map:
            final_files.append((replace_map[rel], rel))
            n_replaced += 1
        else:
            final_files.append((src, rel))
    if n_replaced != len(replace_map):
        die(f"only {n_replaced}/{len(replace_map)} replacement target(s) matched")

    os.makedirs(os.path.dirname(out_pak) or ".", exist_ok=True)
    info = vp_pakwrite.build_pak(final_files, out_pak)
    print(f"[{TAG}] pak generated: {out_pak} "
          f"(total entries {info['n_entries']}, replaced {n_replaced}, size={info['size']})")

    # === Phase 4: preflight_pak.py 自動実行 ===
    if args.skip_preflight:
        print(f"[{TAG}] --skip-preflight specified, skipping preflight")
    else:
        job_json = os.path.abspath(args.job_json)
        cook_log = os.path.abspath(args.cook_log)
        if not (os.path.exists(job_json) and os.path.exists(cook_log)):
            print(f"[{TAG}] job.json/cook.log not found, skipping preflight "
                  f"(job_json={job_json} cook_log={cook_log}. "
                  "Specify explicitly with --job-json/--cook-log)")
        else:
            print(f"[{TAG}] === Phase 4: preflight_pak.py ===")
            r = subprocess.run([sys.executable, DEFAULT_PREFLIGHT, job_json,
                                out_pak, template, cook_log])
            if r.returncode != 0:
                die(f"preflight_pak.py exited with {r.returncode} (see output above)")

    print(f"[{TAG}] done: {out_pak}")
    print(f"[{TAG}] work directory (dump/intermediates/logs): {work}")


if __name__ == "__main__":
    main()
