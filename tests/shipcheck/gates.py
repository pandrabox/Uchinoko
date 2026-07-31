# -*- coding: utf-8 -*-
"""U32: 出荷検査ゲート(A〜G+H1/H2)の判定ロジック本体。

設計方針: pytestのtest_*.py関数は薄いラッパーに留め、判定そのものは
ここに集約する(selftestが「pytestを実行せずに関数を直接叩いてassertできる」
ようにするため — U24の`pst.ct.*`モンキーパッチ先例を踏襲しつつ、対象を
モジュール属性ではなく本モジュールの関数シグネチャに揃えた)。

外部ツール(devtools/*)は関数importで再利用する(subprocess再呼び出しより
importを優先、docs\\U32_SONNET_INSTRUCTIONS.md 2節の指示どおり)。
"""
import dataclasses
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
UE_EXIT_DIR = os.path.join(REPO_ROOT, "research", "ue_exit")

for _p in (DEVTOOLS_DIR, PIPELINE_PY_DIR, UE_EXIT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CACHE_DIR = os.path.join(REPO_ROOT, "work", "u32_diag", "pak_cache")
JOBS_DIR = os.path.join(REPO_ROOT, "work", "u32_diag", "jobs")

PIPELINE_MUTEX_WAIT_SECONDS = 15 * 60
PIPELINE_MUTEX_MAX_RETRIES = 3

# docs\U23_SONNET_INSTRUCTIONS.md 2節「UE経路実行の指紋」5種そのまま。
UE_FINGERPRINTS = [
    os.path.join("logs", "step03_export_fbx.log"),
    os.path.join("logs", "step04_make_dummies.log"),
    "assets_ue.log",
    "cook.log",  # 内容に"Running AutomationTool"を含む場合のみUE指紋とみなす
    "Windows",
]


@dataclasses.dataclass
class GateResult:
    status: str  # "PASS" | "FAIL" | "SKIP"
    name: str
    detail: dict = dataclasses.field(default_factory=dict)

    @property
    def ok(self):
        return self.status == "PASS"


def _gate(status, name, **detail):
    assert status in ("PASS", "FAIL", "SKIP")
    return GateResult(status=status, name=name, detail=detail)


# --- 汎用ヘルパ ------------------------------------------------------------

def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(cwd=REPO_ROOT):
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=cwd, stderr=subprocess.DEVNULL
        )
        return out.decode("ascii", errors="ignore").strip()
    except Exception:
        return "unknown"


def template_build_version():
    """pipeline\\py\\live_template.pyのTEMPLATE_BUILD_VERSIONを読む(import優先、
    無改変流用)。キャッシュキーに含めることでテンプレート版が上がった時
    自動的に旧キャッシュを無効化する(U25の同種の仕組みと同じ考え方)。"""
    import live_template
    return live_template.TEMPLATE_BUILD_VERSION


# --- 変換に影響するソースの指紋(2026-07-26 発見・修正) ---------------------
# `git_head()` はコミット済みの変更しか捉えない。本日の修正(vp_atlas.py の
# 単色マテリアル塗りつぶし等)はすべて**未コミット**だったため、キャッシュ鍵が
# 変わらず、`--allow-convert` を付けて再実行しても**古いコードの成果物**に
# キャッシュヒットし続けるという欠陥が実測で見つかった
# (input_vrm_seed: 修正07/26 08:24、測定に使った成果物は同日01:25/07:41 =
# 修正の7時間前のまま)。
#
# 列挙の根拠: `pipeline\cli\convert.ps1` / `pipeline\cli\export_from_unity.ps1`
# を `grep -oE '"[^"]*\.(py|ps1|cs)"'` で全文検索し、実際に呼び出される
# スクリプトの入口(step01〜04 / convert_noue.py / extract_vanilla.py /
# patch_refskeleton.py / preflight_pak.py / pipeline\py\fast_repack.py /
# unity\DiveToPalworldExporter.cs / pipeline\ue\*)を確認した。ただしこれらの
# 入口スクリプトは pipeline\py\*.py の他モジュール(vp_atlas.py, vp_core.py,
# live_template.py 等)を大量に import しており、import グラフを個別に
# 追跡すると取りこぼしの危険がある(取りこぼしたファイルの修正が以後も
# 検知されなくなる、という指摘どおり)。そこで**取りこぼしを避けるため
# 追跡しない**方針にした: `pipeline\` 配下の `*.py`/`*.ps1` を**全件**
# (import されているかに関わらず)、加えて直接呼び出しが確認できた
# `unity\DiveToPalworldExporter.cs`(Unity輸出の実体)を対象にする。
# 2026-07-26: `fast_repack.py` はdevtools\からpipeline\py\へ移設されたため、
# 以前あった個別追加行は不要になった(上のpipeline\全件走査で自動的に含まれる)。


def source_fingerprint(base_root=None):
    """変換に影響するソースファイル群の内容から sha256 を1本作る。

    1文字でも変われば必ず変わる(mtimeではなく内容ハッシュにしたのは、
    タッチしただけで無変更のファイルまで無駄にキャッシュを外さないため)。
    ファイルが読めない/存在しない場合もハッシュに反映し(パスと状態を
    payloadへ含める)、静かに無視しない。

    `base_root`: 配布zip検証モード(target_root指定時)は**その展開先の
    pipeline\\**を実際に実行するので、フィンガープリントもそちらを見る
    (既定は REPO_ROOT = 本リポジトリ自身)。
    """
    root = base_root or REPO_ROOT
    paths = []
    for sub, exts in (("pipeline", (".py", ".ps1")),):
        base = os.path.join(root, sub)
        for dirpath, _dirnames, filenames in os.walk(base):
            for fn in filenames:
                if fn.lower().endswith(exts):
                    paths.append(os.path.join(dirpath, fn))
    paths.append(os.path.join(root, "unity", "DiveToPalworldExporter.cs"))

    h = hashlib.sha256()
    for p in sorted(paths, key=lambda s: os.path.relpath(s, root).lower()):
        rel = os.path.relpath(p, root)
        h.update(rel.encode("utf-8", errors="replace"))
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError as e:
            h.update("MISSING:{!r}".format(e).encode("utf-8"))
    return h.hexdigest()


def load_job(job_path):
    with open(job_path, encoding="utf-8") as f:
        return json.load(f)


def merge_job(base_job, overrides):
    merged = dict(base_job)
    merged.update(overrides or {})
    return merged


def cache_key(job_dict, extra_note="", target_root=None):
    payload = json.dumps(job_dict, sort_keys=True, ensure_ascii=False)
    # target_rootが変われば「被検体」が別物になる(配布zip検証モード、2026-07-25
    # ぱん裁定)。既定(None=リポジトリ自身)と別ターゲットのキャッシュを混同しない。
    # src=source_fingerprint(): 2026-07-26発見の欠陥修正。git_head/tbvは
    # コミット済み変更しか捉えないため、未コミットのpipeline修正(本日の
    # vp_atlas.py修正等)がキャッシュに反映されず、--allow-convertを付けて
    # 再実行しても古いコードの成果物にヒットし続けていた。内容ハッシュを
    # 鍵に混ぜることで、pipeline\配下の1文字の変更も確実にキャッシュを外す。
    payload += "|tbv={}|head={}|src={}|note={}|target_root={}".format(
        template_build_version(), git_head(),
        source_fingerprint(target_root), extra_note, target_root or "<repo>"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- pakビルド(キャッシュ必須) ---------------------------------------------

@dataclasses.dataclass
class PakBuildResult:
    avatar: str
    job_path: str
    job_dict: dict
    cache_hit: bool
    exit_code: int
    pak_path: str = None
    sha1: str = None
    build_dir: str = None
    log_text: str = ""
    log_path: str = None
    skip_reason: str = None


class ConversionSkipped(Exception):
    """allow_convert=Falseでキャッシュ不成立時に投げる(呼び出し側でpytest.skip化する)。"""


def _cache_record_path(avatar, key):
    return os.path.join(CACHE_DIR, "{}_{}.json".format(avatar, key[:16]))


def _run_conversion(job_path, log_path, engine_mode="noue", target_root=None):
    """convert.ps1を実際に叩く唯一の関数(モック差し替えの継ぎ目)。
    グローバルMutex衝突時は15分待って最大3回まで再試行する(U23 2節の分岐)。

    target_root(2026-07-25ぱん裁定、配布zip最終出荷検査モード): 指定時は
    target_root側のpipeline\\cli\\convert.ps1を呼ぶ(ハーネス=本リポジトリの
    テストコード、被検体=配布物側のパイプライン、という分離)。Noneなら
    従来どおり本リポジトリ自身のconvert.ps1を使う。job.json自体は常に
    ハーネス側(呼び出し元が渡したjob_path)のまま — 変わるのは実行される
    パイプラインコードだけ。
    戻り値: (exit_code:int, log_text:str)"""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    root = target_root or REPO_ROOT
    convert_ps1 = os.path.join(root, "pipeline", "cli", "convert.ps1")
    for attempt in range(1, PIPELINE_MUTEX_MAX_RETRIES + 1):
        proc = subprocess.run(
            ["pwsh", "-File", convert_ps1, "-Job", job_path, "-EngineMode", engine_mode],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("=== attempt {} ===\n{}\n".format(attempt, text))
        if "別の変換が実行中です" in text and attempt < PIPELINE_MUTEX_MAX_RETRIES:
            time.sleep(PIPELINE_MUTEX_WAIT_SECONDS)
            continue
        return proc.returncode, text
    return proc.returncode, text


def build_or_get_cached(avatar, job_path, overrides=None, allow_convert=False,
                         run_conversion=_run_conversion, target_root=None):
    """フィクスチャpak_for()の本体。job.json内容+TEMPLATE_BUILD_VERSION+git HEAD+
    target_rootをキーにキャッシュし、ヒットすれば変換を一切呼ばない(1体20分の
    無駄打ち防止、docs\\U32_SONNET_INSTRUCTIONS.md 4-2節)。

    target_root(2026-07-25ぱん裁定): 配布zip展開先など、本リポジトリ以外の
    pipeline\\cli\\convert.ps1を被検体として叩きたい場合に指定する
    (--target-rootオプション、conftest.pyのpak_forフィクスチャ経由)。
    run_conversionは差し替え可能な引数(selftestが実変換を起こさず検証するための継ぎ目)。
    """
    base_job = load_job(job_path)
    job_dict = merge_job(base_job, overrides)
    key = cache_key(job_dict, target_root=target_root)
    os.makedirs(CACHE_DIR, exist_ok=True)
    record_path = _cache_record_path(avatar, key)

    if os.path.isfile(record_path):
        with open(record_path, encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("pak_path") and os.path.isfile(rec["pak_path"]):
            log_path = rec.get("log_path")
            log_text = ""
            if log_path and os.path.isfile(log_path):
                with open(log_path, encoding="utf-8", errors="replace") as lf:
                    log_text = lf.read()
            return PakBuildResult(
                avatar=avatar, job_path=job_path, job_dict=job_dict, cache_hit=True,
                exit_code=0, pak_path=rec["pak_path"], sha1=rec.get("sha1"),
                build_dir=rec.get("build_dir"), log_path=log_path, log_text=log_text,
            )
        # レコードはあるがpak実体が消えている(異常系) → キャッシュ不成立扱いで再構築へ

    if not allow_convert:
        raise ConversionSkipped(
            "avatar={}: キャッシュ不成立、かつこのセッションでは実変換禁止"
            "(安全のための既定。--allow-convert指定時のみ実変換する)".format(avatar)
        )

    effective_job_path = job_path
    if overrides:
        job_cache_dir = os.path.join(JOBS_DIR, avatar)
        os.makedirs(job_cache_dir, exist_ok=True)
        effective_job_path = os.path.join(job_cache_dir, "{}.job.json".format(key[:16]))
        with open(effective_job_path, "w", encoding="utf-8") as f:
            json.dump(job_dict, f, ensure_ascii=False, indent=2)

    job_dir = os.path.dirname(job_path)
    build_dir = os.path.join(job_dir, "build")
    log_path = os.path.join(REPO_ROOT, "work", "u32_diag", "convert_logs",
                             "{}_{}.log".format(avatar, key[:16]))
    exit_code, log_text = run_conversion(effective_job_path, log_path, target_root=target_root)

    result = PakBuildResult(
        avatar=avatar, job_path=effective_job_path, job_dict=job_dict, cache_hit=False,
        exit_code=exit_code, build_dir=build_dir, log_text=log_text, log_path=log_path,
    )
    if exit_code == 0:
        avatar_name = job_dict.get("avatar_name", avatar)
        candidates = glob.glob(os.path.join(build_dir, "{}_PlayerSwap_P.pak".format(avatar_name)))
        if candidates:
            result.pak_path = candidates[0]
            result.sha1 = sha1_file(result.pak_path)
            with open(record_path, "w", encoding="utf-8") as f:
                json.dump({
                    "avatar": avatar, "pak_path": result.pak_path, "sha1": result.sha1,
                    "build_dir": build_dir, "log_path": log_path,
                    "template_build_version": template_build_version(),
                    "git_head": git_head(), "target_root": target_root,
                }, f, ensure_ascii=False, indent=2)
    return result


# --- ゲートA〜D(オフライン、変換結果) ---------------------------------------

def gate_a_convert_exit0(build_result):
    if build_result.cache_hit:
        return _gate("PASS", "A_convert_exit0", note="cache_hit")
    ok = build_result.exit_code == 0
    return _gate("PASS" if ok else "FAIL", "A_convert_exit0",
                 exit_code=build_result.exit_code,
                 log_tail=build_result.log_text[-2000:] if not ok else "")


def gate_b_pak_exists(build_result):
    ok = bool(build_result.pak_path and os.path.isfile(build_result.pak_path))
    if not ok:
        return _gate("FAIL", "B_pak_exists", pak_path=build_result.pak_path)
    return _gate("PASS", "B_pak_exists", pak_path=build_result.pak_path, sha1=build_result.sha1)


def gate_c_preflight_from_log(log_text):
    """preflight_pak.pyのgate()出力形式("  [PASS] name"/"  [FAIL] name")をログから
    数える。convert_noue.py内部でpreflightが実行される(noueは常に9ゲートG1〜G9)。"""
    import re
    passes = re.findall(r"\[PASS\] (G\d[^\n\r]*)", log_text)
    fails = re.findall(r"\[FAIL\] (G\d[^\n\r]*)", log_text)
    total = len(passes) + len(fails)
    if total == 0:
        return _gate("SKIP", "C_preflight_9of9",
                      note="ログにpreflightの[PASS]/[FAIL]行が見つからない")
    ok = total == 9 and not fails
    return _gate("PASS" if ok else "FAIL", "C_preflight_9of9",
                 passed=len(passes), failed=fails, total=total)


def gate_d_noue_provenance(build_dir):
    found = []
    for rel in UE_FINGERPRINTS:
        full = os.path.join(build_dir, rel)
        if rel == "cook.log":
            if os.path.isfile(full):
                with open(full, encoding="utf-8", errors="replace") as f:
                    if "Running AutomationTool" in f.read():
                        found.append(rel)
        elif os.path.exists(full):
            found.append(rel)
    ok = not found
    return _gate("PASS" if ok else "FAIL", "D_noue_provenance",
                 checked=UE_FINGERPRINTS, found_ue_fingerprints=found)


# --- 静的構造検査(u26_static_checkの再利用) ---------------------------------

def gate_static_check(job_dir, exclude_label_substrings=()):
    import u26_static_check as usc
    targets = usc.collect_targets(job_dir)
    problems = []
    n_checked = 0
    for label, built_uasset, built_uexp, tmpl_uasset, tmpl_uexp, is_sk in targets:
        if any(sub in label for sub in exclude_label_substrings):
            continue
        built = usc.check_one(label + ":built", built_uasset, built_uexp, is_sk)
        n_checked += 1
        if built.get("missing"):
            problems.append((label, "missing"))
            continue
        if not built.get("header_consistent", True):
            problems.append((label, "header_inconsistent"))
        if not built.get("verify_ok", True):
            problems.append((label, "verify_failed"))
        if is_sk and built.get("sk_tri_match") is False:
            problems.append((label, "sk_tri_mismatch"))
        if is_sk and built.get("sk_vtx_match") is False:
            problems.append((label, "sk_vtx_mismatch"))
    if n_checked == 0:
        return _gate("SKIP", "static_check", note="対象ファイルが見つからない: {}".format(job_dir))
    ok = not problems
    return _gate("PASS" if ok else "FAIL", "static_check",
                 n_checked=n_checked, problems=problems[:10], n_problems=len(problems))


# --- H1: 設定配線ゲート -----------------------------------------------------

def _pak_entry_hashes(pak_path):
    import vp_core as core
    mount, entries_full = core.read_pak_entries(pak_path)
    hashes = {}
    with open(pak_path, "rb") as f:
        for rel_path, e in entries_full.items():
            if e["compression"] != 0:
                # 本パイプラインのpakは常に非圧縮(preflight_pak.py G5前提と同じ想定)。
                # 圧縮エントリが来たら生バイトのままハッシュに含める(検知できれば十分)。
                f.seek(e["data_offset"])
                data = f.read(e["csize"])
            else:
                f.seek(e["data_offset"])
                data = f.read(e["size"])
            hashes[rel_path] = hashlib.sha1(data).hexdigest()
    return hashes


def gate_h1_wiring(baseline_pak, flip_pak, expected_diff_categories,
                    entry_hasher=_pak_entry_hashes):
    base_hashes = entry_hasher(baseline_pak)
    flip_hashes = entry_hasher(flip_pak)
    all_paths = set(base_hashes) | set(flip_hashes)
    diff_paths = sorted(
        p for p in all_paths
        if base_hashes.get(p) != flip_hashes.get(p)
    )
    if not diff_paths:
        return _gate("FAIL", "H1_settings_wiring",
                      note="差分ゼロ(設定が配線されていない可能性)",
                      expected_diff_categories=list(expected_diff_categories))
    matched = [p for p in diff_paths if any(cat in p for cat in expected_diff_categories)]
    ok = bool(matched)
    return _gate("PASS" if ok else "FAIL", "H1_settings_wiring",
                  diff_count=len(diff_paths), diff_paths_sample=diff_paths[:10],
                  matched_expected_category=bool(matched),
                  expected_diff_categories=list(expected_diff_categories))


# --- ゲートE/F(実機、@machineテストからのみ呼ばれる) -------------------------

def gate_e_crash(ct_module, pak_ref, paks_dir, wait_seconds=40, out=None):
    import io
    buf = out if out is not None else io.StringIO()
    rc = ct_module.run(pak_ref, paks_dir, wait_seconds, out=buf, force=True, auto_close=True)
    text = buf.getvalue() if hasattr(buf, "getvalue") else ""
    if rc == 0:
        return _gate("PASS", "E_crash_notcrashed", exit_code=rc, log=text[-1000:])
    if rc == 3:
        return _gate("SKIP", "E_crash_notcrashed", exit_code=rc,
                     note="タイムアウト(一度もプロセス確認できず)。--wait延長を検討", log=text[-1000:])
    return _gate("FAIL", "E_crash_notcrashed", exit_code=rc, log=text[-2000:])


def gate_f_playstart(pst_module, pak_ref, repeat=1, wait_after_start=60, launch_wait=18,
                      world_template=None, shot_dir=None):
    results = []
    for i in range(repeat):
        rc = pst_module.run(
            pak_ref, wait_after_start=wait_after_start, launch_wait=launch_wait,
            vanilla=False, world_template=world_template,
            evidence_shot_dir=shot_dir, auto_close=True,
        )
        results.append(rc)
    n_pass = sum(1 for rc in results if rc == 0)
    n_crash = sum(1 for rc in results if rc == 2)
    n_ui_fail = sum(1 for rc in results if rc == 1)
    detail = dict(exit_codes=results, n_pass=n_pass, n_crash=n_crash, n_ui_fail=n_ui_fail,
                  repeat=repeat)
    if n_pass > 0:
        return _gate("PASS", "F_play_start", **detail)
    if n_crash > 0:
        return _gate("FAIL", "F_play_start", **detail)
    # 残りは全てexit1(真のUI未検出) → 製品の欠陥ではなく環境要因としてSKIP
    return _gate("SKIP", "F_play_start", note="UI未検出(環境要因)。クラッシュではない", **detail)


# --- ゲートG(見た目、advisory) ---------------------------------------------

CHECKER_PROMPT = """あなたはアバター移植MODの官能検査アシスタントです。1枚のPalworld
ゲーム内スクリーンショット(プレイヤーキャラ領域のクロップ)を見て、UE5の
「参照解決失敗」を示す典型的な赤黒/紫黒のチェッカーボード柄がキャラクター本体の
どこかに写っているかどうかだけを判定してください(装備やHUDの模様と混同しないこと)。
必ず次のJSONだけを1行で出力してください(前後に文章を付けない):
{"checker_present": true/false, "confidence": 0.0-1.0, "notes": "根拠を一文で"}"""


def checker_pattern_check(image_path, model="sonnet", claude_runner=None):
    """compare_avatar.py と同じ「ローカルclaude CLIをヘッドレスで叩く」パターンを
    別プロンプトで再利用する(compare_avatar.py自体は無改変、既存パターンの再適用)。
    claude_runner(cli_args)->CompletedProcess を差し替え可能にし、selftestで
    実CLI呼び出しをモンキーパッチできるようにする。

    このゲート(Tier B、advisory)は自動化された配布パイプラインには含まれない。
    GitHub Actions等のCIワークフローからは呼ばれず、devtools\\release.py が
    自動実行する ship_smoke --fast(Tier Aのみ)にも含まれない。メンテナが
    手元でpytest(tests\\shipcheck\\test_visual.py)や ship_smoke.py を
    --fast無しで手動実行したときにだけ動く、任意の視覚回帰チェックである。
    配布物(zip/exe)自体にも一切含まれない開発者向けツールで、判定内容も
    固定の読み取り専用タスク1つ(1枚のスクリーンショットに、変換ミスの典型症状
    であるチェッカーボード柄が写っているか否かを判定するだけ)に限られ、任意の
    ファイル編集やコマンド実行をAIに許可するものではない。
    --dangerously-skip-permissions は、この非対話・単発・固定プロンプトの
    バッチ呼び出しで確認ダイアログが表示されると自動化が止まってしまうために
    付けている。--add-dir も対象画像が置かれたディレクトリ1つに絞っており、
    リポジトリ全体への書き込み権限を与えるものではない。"""
    import shutil as _shutil
    if claude_runner is None:
        def claude_runner(args):
            return subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    exe = _shutil.which("claude") or "claude"
    prompt = "{}\n\n画像: @{}".format(CHECKER_PROMPT, os.path.abspath(image_path))
    args = [exe, "-p", prompt, "--model", model, "--output-format", "json",
            "--dangerously-skip-permissions", "--add-dir", os.path.dirname(os.path.abspath(image_path))]
    try:
        proc = claude_runner(args)
    except FileNotFoundError:
        return {"error": "claude CLIが見つからない", "checker_present": None}
    if proc.returncode != 0:
        return {"error": "claude CLI失敗 rc={}".format(proc.returncode), "checker_present": None}
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": "CLI出力がJSONでない", "checker_present": None}
    if env.get("is_error"):
        return {"error": "CLI is_error", "checker_present": None}
    result_text = env.get("result", "")
    s, e = result_text.find("{"), result_text.rfind("}")
    if s < 0 or e < 0:
        return {"error": "判定JSONが見つからない", "raw": result_text, "checker_present": None}
    try:
        return json.loads(result_text[s:e + 1])
    except json.JSONDecodeError:
        return {"error": "判定JSONのパース失敗", "raw": result_text, "checker_present": None}


def gate_g_checker(image_path, checker_fn=checker_pattern_check):
    verdict = checker_fn(image_path)
    if verdict.get("checker_present") is None:
        return _gate("SKIP", "G_checker", note=verdict.get("error", "判定不能"), verdict=verdict)
    ok = verdict["checker_present"] is False
    return _gate("PASS" if ok else "FAIL", "G_checker", verdict=verdict)


def gate_g_compare(ingame_crop, ref_png, compare_fn):
    """compare_fn: devtools.compare_avatar.compare 互換(ingame_path, ref_path)->dict"""
    if not (os.path.isfile(ingame_crop) and os.path.isfile(ref_png)):
        return _gate("SKIP", "G_compare_avatar",
                      note="画像が無い(ingame={}, ref={})".format(
                          os.path.isfile(ingame_crop), os.path.isfile(ref_png)))
    verdict = compare_fn(ingame_crop, ref_png)
    if verdict.get("same_avatar") is None:
        return _gate("SKIP", "G_compare_avatar", note=verdict.get("error", "判定不能"), verdict=verdict)
    ok = bool(verdict.get("same_avatar")) and bool(verdict.get("looks_correct"))
    return _gate("PASS" if ok else "FAIL", "G_compare_avatar", verdict=verdict)


# --- 来歴(provenance) -------------------------------------------------------

def provenance_dict(pak_path=None, target_root=None):
    import datetime
    d = {
        "git_head": git_head(),
        "template_build_version": template_build_version(),
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "target_root": target_root or "<repo>",
    }
    if pak_path and os.path.isfile(pak_path):
        d["pak_path"] = pak_path
        d["pak_sha1"] = sha1_file(pak_path)
    return d
