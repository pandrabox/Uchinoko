# -*- coding: utf-8 -*-
"""SC班: 出荷直前・約20分で回す「クリティカル部分だけの試験」ランナー。

既存の tests\\shipcheck\\test_offline.py 等(U32、実変換・実機まで含む本格スイート、
30分〜8時間級)とは別物。こちらはUnity/Palworld実機に一切触れず、pak変換も
基本的には行わない(Tier Aのみ)高速ゲート + オプションで変換を伴うケース群
(Tier B、SE班が tests\\shipcheck\\ship_convert_cases.py に実装)を束ねる。

Tier A(このファイルが直接実装。排他資源なし、目標2分以内):
    A1 権利監査      devtools\\u28_zip_audit.py(配布zipがあれば) +
                     devtools\\u45_toto_perceptual_audit.py --live
                     を実行し、パルワールド資産や配布不可個人アバター「toto」の
                     混入がゼロであることを守る。最重要ゲート(これがFAILなら配布しない)。
    A2 文書整合      README.md・README.en.md・docs\\・manual\\ 配下の公開文書に、FBXが
                     対応形式として書かれておらず、「Modular Avatar以外のNDMFプラグイン
                     非対応」の記載があることを守る(CLAUDE.md「対応スコープ」節が根拠)。
    A3 アプリ健全性  app_py\\main.py(Python/tkinter版GUI、dev#532方針A)を直接起動し
                     起動直後に落ちないこと、かつ app_py\\i18n.py の5言語辞書完全性を
                     守る(2026-08-01 dev#532 WP-C1: 旧C#/csc.exeビルド経路から切替。
                     旧経路は _gate_a3_app_build_launch_CS_LEGACY() として温存)。
    A4 パイプライン健全性  pipeline\\配下全.pyのpy_compileと、pipeline\\py\\の
                     主要モジュールが実際にimportできることを守る(壊れたコミットの検出)。
    A5 入口の静的検査  pipeline\\cli\\convert.ps1 / export_from_unity.ps1 /
                     app\\build_app.ps1 がPowerShellとして構文エラーなしであることを守る。

Tier B(SE班 ship_convert_cases.py を import して呼ぶだけ。未実装でも動く):
    from ship_convert_cases import CASES, run_case
    CASES = [{"name": str, "est_sec": int, "desc": str}, ...]  # 重要度降順
    run_case(case, work_root, shots_dir) -> {"name","ok","seconds","images","detail"}
    import失敗時はTier Bを「未接続(SKIP)」として報告し、Tier Aだけで完走する。

使い方:
    python tests\\shipcheck\\ship_smoke.py [--minutes 20] [--fast] [--work <dir>]

--fast: Tier Aのみ(目標2分以内)。
既定: Tier A -> Tier B の順。--minutes を実時間の上限として守る。Tier A完了時点の
残り時間と CASES の est_sec を見て、収まるケースだけを上から順に(重要度降順)実行する。
実行しなかったケースは必ず「SKIPPED(時間切れ)」として report.md に明記する(黙って
打ち切らない)。

出力:
    <work>\\report.md   PASS/FAIL/SKIP。1ゲート/1ケース終わるごとに追記してflushする。
    <work>\\shots\\      Tier Bが返す画像をフラットに集約(人間の官能検査用)。
                        <ケース名>_<元ファイル名> に改名してコピーする。
標準出力: 最終サマリ表。
終了コード: FAILが1件でもあれば1、全部PASS(SKIPは許容)なら0。
"""
import argparse
import datetime
import glob
import importlib.util
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
PIPELINE_DIR = os.path.join(REPO_ROOT, "pipeline")
PIPELINE_PY_DIR = os.path.join(PIPELINE_DIR, "py")
APP_DIR = os.path.join(REPO_ROOT, "app")
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")


# --- 汎用ヘルパ --------------------------------------------------------------

def _now_ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _tail(text, n):
    text = text or ""
    return text[-n:]


def _append(path, text):
    """追記して即クローズ = 即flush(逐次書き込み、停止時の消失を防ぐ)。"""
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def _no_bytecode_env():
    """pipeline\\py\\をimportするサブプロセスにPYTHONDONTWRITEBYTECODE=1を渡す。
    書き込み許可外のpipeline\\配下に__pycache__を作らせないため。"""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _find_latest_dist_zip():
    candidates = []
    for pattern in (os.path.join(REPO_ROOT, "dist", "*.zip"),
                     os.path.join(REPO_ROOT, "*.zip")):
        candidates.extend(glob.glob(pattern))
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


# --- A1: 権利監査 -------------------------------------------------------------

def gate_a1_rights_audit(work_root, zip_audit_mode="auto"):
    """zip_audit_mode:
    - "auto"(既定): 従来どおり。dist\\の最新zipが見つかればu28_zip_audit.pyで
      鮮度照合まで行う。zip単体実行(ship_smoke.py単体呼び出し)はこのモード。
    - "defer": u28_zip_audit.pyを実行しない(理由付きでSKIP扱いにする)。
      release.pyのリリースフローでは、このゲート(ship_smoke --fast)は
      **新しい配布zipをビルドする前**に走る。そのためdist\\に置かれているのは
      常に「前回リリースの旧zip」であり、その旧zipを現HEADと鮮度照合すると、
      その間に入った正当なコード修正が全部「不一致」として検出される
      (構造的な偽陽性、2026-07-27 v1.1.1リリースのA1誤FAILで発覚)。
      本物のzip監査はrelease.py自身がビルド後の新zipに対して
      run_u28_zip_audit()で改めて実施する(devtools\\release.py 1169行目)ので、
      ここで旧zipを見る意味がない。u45(--live、リポジトリ実体を直接検査)は
      zipの鮮度に依存しないため、deferでも従来どおり必ず実行する。
    """
    t0 = time.time()
    detail_lines = []
    sub_statuses = []

    u45 = os.path.join(DEVTOOLS_DIR, "u45_toto_perceptual_audit.py")
    try:
        proc = subprocess.run(
            [sys.executable, u45, "--live"], cwd=REPO_ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env=_no_bytecode_env(),
        )
        u45_ok = proc.returncode == 0
        sub_statuses.append("PASS" if u45_ok else "FAIL")
        detail_lines.append("[u45_toto_perceptual_audit.py --live] rc={} -> {}".format(
            proc.returncode, "PASS" if u45_ok else "FAIL"))
        detail_lines.append(_tail(proc.stdout + proc.stderr, 2000))
    except Exception:
        sub_statuses.append("FAIL")
        detail_lines.append("[u45_toto_perceptual_audit.py --live] 実行例外:\n" + traceback.format_exc())

    if zip_audit_mode == "defer":
        sub_statuses.append("SKIP")
        detail_lines.append(
            "[u28_zip_audit.py] --zip-audit defer 指定のためSKIP: "
            "ビルド後の新zipに対してrelease.pyが実施(deferred)。"
            "release.pyのゲート順序ではship_smoke --fastは新zipビルド前に走るため、"
            "dist\\の旧zipを鮮度照合すると直前のコード修正が常に不一致検出される"
            "(構造的偽陽性)。真の監査はdevtools\\release.py::run_u28_zip_audit()が"
            "ビルド直後の新zipへ改めて実行する。"
        )
    else:
        zip_path = _find_latest_dist_zip()
        if zip_path is None:
            sub_statuses.append("SKIP")
            detail_lines.append(
                "[u28_zip_audit.py] zip未生成のためSKIP。配布zip作成後に必ず実行すること"
                "(dist\\*.zip またはリポジトリ直下\\*.zip が見つからなかった)。"
            )
        else:
            u28 = os.path.join(DEVTOOLS_DIR, "u28_zip_audit.py")
            out_json = os.path.join(work_root, "u28_provenance.json")
            try:
                proc = subprocess.run(
                    [sys.executable, u28, zip_path, "--out", out_json], cwd=REPO_ROOT,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=300, env=_no_bytecode_env(),
                )
                u28_ok = proc.returncode == 0
                sub_statuses.append("PASS" if u28_ok else "FAIL")
                detail_lines.append("[u28_zip_audit.py {}] rc={} -> {}".format(
                    zip_path, proc.returncode, "PASS" if u28_ok else "FAIL"))
                detail_lines.append(_tail(proc.stdout + proc.stderr, 3000))
            except Exception:
                sub_statuses.append("FAIL")
                detail_lines.append("[u28_zip_audit.py] 実行例外:\n" + traceback.format_exc())

    if "FAIL" in sub_statuses:
        overall = "FAIL"
    elif all(s == "SKIP" for s in sub_statuses):
        overall = "SKIP"
    else:
        overall = "PASS"

    return dict(
        name="A1_rights_audit", status=overall, seconds=time.time() - t0,
        what="権利監査(最重要): パルワールド資産・配布不可個人アバター「toto」の混入をゼロにする。"
             "これがFAILなら配布してはいけない。",
        detail="\n".join(detail_lines),
    )


# --- A2: 文書整合 -------------------------------------------------------------

PUBLIC_DOC_GLOBS = [
    "README.md",
    "README.en.md",
    os.path.join("docs", "**", "*.md"),
    os.path.join("docs", "**", "*.html"),
    os.path.join("manual", "**", "*.md"),
    os.path.join("manual", "**", "*.html"),
]

# 単語境界必須(manual.htmlはBlender出力のPNGをbase64埋め込みしており、
# その文字列中に"FBX"が部分一致する偶然の衝突が実測で頻発するため、\bで除外する)。
FBX_WORD_RE = re.compile(r"\bFBX\b")
RULE_B_EXCLUSIVE_RE = re.compile(r"(Modular\s*Avatar\s*以外|MA\s*以外)")
RULE_B_NDMF_RE = re.compile(r"NDMF")
RULE_B_DENY_RE = re.compile(r"非対応|取り除")


def _iter_public_doc_files(root):
    seen = set()
    for pattern in PUBLIC_DOC_GLOBS:
        for p in glob.glob(os.path.join(root, pattern), recursive=True):
            rp = os.path.abspath(p)
            if rp not in seen and os.path.isfile(rp):
                seen.add(rp)
                yield rp


def check_doc_consistency(root):
    """A2の判定本体。pytestにもCLIにも依存しない純関数(負の対照テストで
    偽の入力ディレクトリに対して直接呼べるようにするため)。

    戻り値: {"ok": bool, "files_checked": [...], "violations_a": [...],
             "rule_b_satisfied": bool, "read_errors": [...]}
    """
    files = sorted(_iter_public_doc_files(root))
    violations_a = []
    rule_b_ok = False
    read_errors = []
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception as e:
            read_errors.append((f, str(e)))
            continue
        if FBX_WORD_RE.search(text):
            violations_a.append(f)
        stripped = text.replace("**", "")
        if (RULE_B_EXCLUSIVE_RE.search(stripped) and RULE_B_NDMF_RE.search(stripped)
                and RULE_B_DENY_RE.search(stripped)):
            rule_b_ok = True
    ok = (not violations_a) and rule_b_ok and bool(files)
    return dict(ok=ok, files_checked=files, violations_a=violations_a,
                rule_b_satisfied=rule_b_ok, read_errors=read_errors)


def gate_a2_doc_consistency(work_root):
    t0 = time.time()
    result = check_doc_consistency(REPO_ROOT)
    detail_lines = []
    detail_lines.append("検査対象ファイル数: {}".format(len(result["files_checked"])))
    for f in result["files_checked"]:
        detail_lines.append("  - {}".format(os.path.relpath(f, REPO_ROOT)))
    if result["violations_a"]:
        detail_lines.append("(a)違反: FBXが単語として出現(対応形式表記の疑い):")
        for f in result["violations_a"]:
            detail_lines.append("  VIOLATION: {}".format(os.path.relpath(f, REPO_ROOT)))
    else:
        detail_lines.append("(a) FBXの単語出現: なし(OK)")
    detail_lines.append("(b) 'Modular Avatar以外のNDMFプラグイン非対応'相当の記載: {}".format(
        "あり(OK)" if result["rule_b_satisfied"] else "なし(NG)"))
    for f, e in result["read_errors"]:
        detail_lines.append("READ_ERROR: {} -> {}".format(f, e))
    status = "PASS" if result["ok"] else "FAIL"
    return dict(
        name="A2_doc_consistency", status=status, seconds=time.time() - t0,
        what="公開文書がFBXを対応形式と書かず、Modular Avatar以外のNDMF非対応を明記していることを守る",
        detail="\n".join(detail_lines),
    )


# --- A3: アプリのビルドと起動 ---------------------------------------------------
#
# dev#532 方針A WP-C1(2026-08-01): app\DiveToPalworld.cs(C#/WinForms/csc.exe)は
# app_py\(Python/tkinter, dev#532 トラックA1-A6+B1で移植・パッケージング実運用化まで
# 完了済み)へ切替中。csc.exeビルド→exe起動という手順は、Python移植によって
# 「対象の入口(app_py\main.py)を直接起動する」だけで足りるようになった
# (work\wp532A\DESIGN.md §0-1「ビルド→exe起動という手順自体が丸ごと不要になる」の
# 実例)。旧C#経路は_gate_a3_app_build_launch_CS_LEGACY()として下に温存してある
# (削除しない。C#資産自体はdev#532統合WP(D1)完了まで残る方針のため)。

def gate_a3_app_build_launch(work_root):
    t0 = time.time()
    what = ("アプリ(GUI, app_py\\main.py版)が起動直後(数秒)に落ちないこと、かつ"
            "i18n辞書(app_py\\i18n.py, 旧--check-i18n相当)の5言語完全性を守る"
            "(dev#532 方針A WP-C1: 旧C#/csc.exeビルド経路からPython直接起動へ切替)")
    main_py = os.path.join(APP_PY_DIR, "main.py")
    detail_lines = []

    if not os.path.isfile(main_py):
        detail_lines.append("app_py\\main.py が見つからない: {}".format(main_py))
        return dict(name="A3_app_build_launch", status="FAIL", seconds=time.time() - t0,
                    what=what, detail="\n".join(detail_lines))

    proc = None
    launch_ok = False
    try:
        proc = subprocess.Popen([sys.executable, main_py], cwd=REPO_ROOT)
        time.sleep(3.5)
        launch_ok = proc.poll() is None
        detail_lines.append("起動コマンド: {} {}".format(sys.executable, main_py))
        detail_lines.append("起動後3.5秒生存: {}".format(launch_ok))
    except Exception:
        detail_lines.append("起動例外:\n" + traceback.format_exc())
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=5)
                detail_lines.append("プロセス終了処理: 完了(ゾンビ化なし)")
            except Exception:
                detail_lines.append("プロセス終了処理で例外:\n" + traceback.format_exc())

    # --- i18n辞書完全性チェック(旧 --check-i18n / CheckDictionaryCompleteness相当) ---
    # C#版は隠しCLIフラグ経由でexeを再起動して検査していたが、Python版は
    # app_py\i18n.py を直接importして辞書を検査するだけで足りる(隠しCLI迂回が
    # 丸ごと不要になる、DESIGN.md §0-1/§2.4のとおり)。sys.path汚染や他モジュールとの
    # 名前衝突を避けるため、ファイルパス指定のimportlibで独立ロードする。
    i18n_ok = False
    try:
        i18n_path = os.path.join(APP_PY_DIR, "i18n.py")
        spec = importlib.util.spec_from_file_location("_shipcheck_app_py_i18n", i18n_path)
        i18n_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(i18n_mod)

        missing = []
        for key, values in i18n_mod.TABLE.items():
            for lang in i18n_mod.LANGS:
                if not values.get(lang):
                    missing.append((key, lang))
        for key, values in i18n_mod.PROGRESS_LABELS.items():
            for lang in i18n_mod.LANGS:
                if not values.get(lang):
                    missing.append((key, lang))
        i18n_ok = not missing
        detail_lines.append("i18n完全性チェック: TABLE={}件, PROGRESS_LABELS={}件, 欠落={}件".format(
            len(i18n_mod.TABLE), len(i18n_mod.PROGRESS_LABELS), len(missing)))
        if missing:
            detail_lines.append("  欠落例: {}".format(missing[:20]))
    except Exception:
        detail_lines.append("i18n完全性チェック実行例外:\n" + traceback.format_exc())

    status = "PASS" if (launch_ok and i18n_ok) else "FAIL"
    return dict(name="A3_app_build_launch", status=status, seconds=time.time() - t0,
                what=what, detail="\n".join(detail_lines))


def _gate_a3_app_build_launch_CS_LEGACY(work_root):
    """退役予定(dev#532統合WP D1でC#資産(app\\DiveToPalworld.cs / build_app.ps1)
    自体を削除する段になったら、この関数も一緒に削除してよい。TIER_A_GATESからは
    既に外されており、通常の実行経路からは呼ばれない(参考保存のみ)。"""
    t0 = time.time()
    what = ("アプリ(GUI)がコンパイルでき、起動直後(数秒)に落ちないこと、かつ"
            "隠しCLI --check-i18n(5言語辞書の完全性自己検査)がOKを返すことを守る"
            "(dev#105)")
    build_ps1 = os.path.join(APP_DIR, "build_app.ps1")
    out_exe = os.path.join(work_root, "build", "DiveToPalworld_shipcheck.exe")
    os.makedirs(os.path.dirname(out_exe), exist_ok=True)
    detail_lines = []

    try:
        proc = subprocess.run(
            ["pwsh", "-NoProfile", "-File", build_ps1, "-Out", out_exe],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
        detail_lines.append("build_app.ps1 -> rc={}".format(proc.returncode))
        detail_lines.append(_tail(proc.stdout + proc.stderr, 2000))
    except Exception:
        detail_lines.append("ビルド実行例外:\n" + traceback.format_exc())
        return dict(name="A3_app_build_launch", status="FAIL", seconds=time.time() - t0,
                    what=what, detail="\n".join(detail_lines))

    if proc.returncode != 0 or not os.path.isfile(out_exe):
        return dict(name="A3_app_build_launch", status="FAIL", seconds=time.time() - t0,
                    what=what, detail="\n".join(detail_lines))

    proc2 = None
    launch_ok = False
    try:
        proc2 = subprocess.Popen([out_exe], cwd=os.path.dirname(out_exe))
        time.sleep(3.5)
        launch_ok = proc2.poll() is None
        detail_lines.append("起動後3.5秒生存: {}".format(launch_ok))
    except Exception:
        detail_lines.append("起動例外:\n" + traceback.format_exc())
    finally:
        if proc2 is not None and proc2.poll() is None:
            try:
                proc2.terminate()
                try:
                    proc2.wait(timeout=5)
                except Exception:
                    proc2.kill()
                    proc2.wait(timeout=5)
                detail_lines.append("プロセス終了処理: 完了(ゾンビ化なし)")
            except Exception:
                detail_lines.append("プロセス終了処理で例外:\n" + traceback.format_exc())

    # --- i18n辞書自己検査(dev#105/rd_93: 実装済みなのに未接続だった--check-i18nを接続) ---
    # ヘッドレスCLI(GUIを開かずCheckI18nCli()->Environment.Exitで終わる、A8のgui_wiring_check.py
    # と同じ隠しCLIパターン)。A3が既に作った out_exe をそのまま再利用するので新規ビルド不要。
    i18n_ok = False
    i18n_out_dir = os.path.join(work_root, "i18n_check")
    try:
        proc3 = subprocess.run(
            [out_exe, "--check-i18n", i18n_out_dir],
            cwd=os.path.dirname(out_exe), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        i18n_ok = proc3.returncode == 0 and "I18N_CHECK_OK" in (proc3.stdout or "")
        detail_lines.append("--check-i18n -> rc={} stdout={}".format(
            proc3.returncode, (proc3.stdout or "").strip()))
    except Exception:
        detail_lines.append("--check-i18n 実行例外:\n" + traceback.format_exc())

    status = "PASS" if (launch_ok and i18n_ok) else "FAIL"
    return dict(name="A3_app_build_launch", status=status, seconds=time.time() - t0,
                what=what, detail="\n".join(detail_lines))


# --- A4: パイプライン健全性 -----------------------------------------------------

_IMPORT_PROBE_SCRIPT = r"""
import sys, os, glob, json, re
sys.path.insert(0, sys.argv[1])
skip_re = re.compile(r"^\s*(import\s+bpy\b|from\s+bpy\b|import\s+bmesh\b|from\s+bmesh\b)", re.M)
files = sorted(glob.glob(os.path.join(sys.argv[1], "*.py")))
result = {"ok": [], "fail": [], "skip": []}
for f in files:
    name = os.path.basename(f)
    mod = name[:-3]
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            full = fh.read()
    except Exception:
        full = ""
    if skip_re.search(full):
        result["skip"].append(name)
        continue
    try:
        __import__(mod)
        result["ok"].append(name)
    except Exception as e:
        result["fail"].append([name, repr(e)])
print(json.dumps(result))
"""


def gate_a4_pipeline_health(work_root):
    import json as _json
    t0 = time.time()
    what = "壊れたコミットの検出: pipeline\\配下の構文エラー・import失敗をゼロにする"
    detail_lines = []

    # py_compileの既定はソースの隣に__pycache__を作る。pipeline\は書き込み許可外
    # なので、コンパイル結果(.pyc)は work_root配下の使い捨て置き場へ逃がす
    # (中身は使わない。doraise=Trueで構文エラーだけ検出できればよい)。
    pycache_out = os.path.join(work_root, "pycache_scratch")
    os.makedirs(pycache_out, exist_ok=True)
    py_files = []
    for dirpath, _dirnames, filenames in os.walk(PIPELINE_DIR):
        for fn in filenames:
            if fn.endswith(".py"):
                py_files.append(os.path.join(dirpath, fn))
    compile_fails = []
    for i, f in enumerate(py_files):
        cfile = os.path.join(pycache_out, "{}_{}.pyc".format(i, os.path.basename(f)))
        try:
            py_compile.compile(f, cfile=cfile, doraise=True, quiet=2)
        except Exception as e:
            compile_fails.append((f, str(e)))
    detail_lines.append("py_compile対象: {}件, 失敗: {}件".format(len(py_files), len(compile_fails)))
    for f, e in compile_fails[:20]:
        detail_lines.append("  COMPILE_FAIL {}: {}".format(os.path.relpath(f, REPO_ROOT), e))

    import_fails = []
    try:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # importでpipeline\py\__pycache__を汚さない
        proc = subprocess.run(
            [sys.executable, "-c", _IMPORT_PROBE_SCRIPT, PIPELINE_PY_DIR],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, env=env,
        )
        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        result = _json.loads(lines[-1]) if lines else {}
        import_ok = result.get("ok", [])
        import_fails = result.get("fail", [])
        import_skips = result.get("skip", [])
        detail_lines.append(
            "import対象(pipeline\\py, bpy依存除く): OK {}件 / FAIL {}件 / SKIP(bpy依存) {}件".format(
                len(import_ok), len(import_fails), len(import_skips)))
        if proc.returncode != 0 and not lines:
            detail_lines.append("import probe stderr:\n" + _tail(proc.stderr, 2000))
    except Exception:
        import_fails = [["<subprocess>", traceback.format_exc()]]
        detail_lines.append("import probe実行例外:\n" + traceback.format_exc())
    for name, err in import_fails[:20]:
        detail_lines.append("  IMPORT_FAIL {}: {}".format(name, err))

    ok = (not compile_fails) and (not import_fails)
    return dict(name="A4_pipeline_health", status="PASS" if ok else "FAIL",
                seconds=time.time() - t0, what=what, detail="\n".join(detail_lines))


# --- A5: 変換入口の静的検査 -----------------------------------------------------

def gate_a5_ps1_syntax(work_root):
    t0 = time.time()
    # WP-A2(2026-07-28)ホットフィックス: pwshだけでの構文パースは、BOM無しUTF-8を
    # ANSI(CP932)扱いしてしまうWindows PowerShell 5.1固有の崩壊を検出できない
    # (pwsh/PS Coreは既定でBOM無しファイルもUTF-8として読むため無症状)。
    # クリーンWindows実機ではensure_blender.ps1がpowershell.exe(5.1)経由で
    # 起動され、BOM無しUTF-8がCP932として誤読されParserErrorで死亡した実例が
    # あった(work\u54_unbundle\wpA2\REPORT.md参照)。以後は両方のエンジンで
    # パースし、どちらかが壊れていればFAILにする。ensure_blender.ps1も対象へ追加。
    what = ("変換入口(convert.ps1等)がPowerShellとして構文エラーなしであることを守る"
            "(実行はしない。pwsh/powershell.exe(PS5.1)の両方でパースする)")
    targets = [
        os.path.join(PIPELINE_DIR, "cli", "convert.ps1"),
        os.path.join(PIPELINE_DIR, "cli", "export_from_unity.ps1"),
        os.path.join(PIPELINE_DIR, "cli", "ensure_blender.ps1"),
        os.path.join(APP_DIR, "build_app.ps1"),
    ]
    shells = ["pwsh", "powershell.exe"]
    detail_lines = []
    fails = []
    for t in targets:
        if not os.path.isfile(t):
            fails.append(t)
            detail_lines.append("FAIL(存在しない): {}".format(t))
            continue
        ps_script = (
            "$parseErrors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile('{}', [ref]$null, [ref]$parseErrors) "
            "| Out-Null; "
            "if ($parseErrors.Count -gt 0) {{ $parseErrors | ForEach-Object {{ Write-Output $_.ToString() }}; "
            "exit 1 }} else {{ exit 0 }}"
        ).format(t.replace("'", "''"))
        for shell in shells:
            try:
                proc = subprocess.run(
                    [shell, "-NoProfile", "-Command", ps_script],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                )
                if proc.returncode == 0:
                    detail_lines.append("OK({}): {}".format(shell, os.path.relpath(t, REPO_ROOT)))
                else:
                    fails.append((t, shell))
                    detail_lines.append("FAIL({}): {}\n{}".format(
                        shell, os.path.relpath(t, REPO_ROOT), _tail(proc.stdout + proc.stderr, 1000)))
            except Exception:
                fails.append((t, shell))
                detail_lines.append("例外({}): {} ->\n{}".format(shell, t, traceback.format_exc()))

    return dict(name="A5_ps1_syntax", status="PASS" if not fails else "FAIL",
                seconds=time.time() - t0, what=what, detail="\n".join(detail_lines))


# --- A6: cp932環境でのサブプロセス出力安全性 -------------------------------------
# 背景(2026-07-26 他PCでの実行失敗、work\fx_cp932\fix_FX_cp932.md参照):
#   日本語Windowsの既定(「ベータ: Unicode UTF-8」未有効)では、convert.ps1が起動する
#   Python子プロセスの標準出力がリダイレクト/パイプされている場合(GUIがログを
#   キャプチャする状況)、Pythonはエンコーディングをシステムのcp932にフォールバック
#   する。ログにem dash(—)等cp932非互換文字が1文字でも混ざると、その時点で
#   UnicodeEncodeErrorでクラッシュし変換全体が止まる。
#
#   このゲートは「emダッシュという文字が無いこと」を静的にスキャンするのではない
#   (それは対症療法で、次に別の非ASCII記号が入るたびに再発する)。
#   検査するのは「cp932しか使えない環境下でも、実際に子プロセスがクラッシュしない
#   こと」という**実行時の振る舞い**であり、かつ判定はconvert.ps1の**現在の実体**
#   (pipeline\cli\convert.ps1のPYTHONIOENCODING/PYTHONUTF8設定行)から動的に読み取る。
#   convert.ps1からこの2行を外すとA6は実際にFAILする(負の対照、SHIPCHECK.md参照)。

_CONVERT_PS1_ENV_RE = {
    "PYTHONIOENCODING": re.compile(r'\$env:PYTHONIOENCODING\s*=\s*"([^"]*)"'),
    "PYTHONUTF8": re.compile(r'\$env:PYTHONUTF8\s*=\s*"([^"]*)"'),
}

# cp932非互換の代表として必ず含めるカナリア文字列(実際にconvert_noue.pyで
# クラッシュを起こしたのと同じ文字を含む)。将来ソース側からem dashが全部
# 除去されても、このゲート自体が無意味化しない(常に何か1つはcp932非互換
# 文字列をテストする)ための床(フロア)。
_A6_CANARY = "SHIP_SMOKE_A6_CANARY — em dash canary (U+2014)"

_STRING_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")


def _harvest_risky_strings(limit=12):
    """pipeline\\py・pipeline\\blender配下の.pyから、cp932でエンコードできない
    文字列リテラルを実際に動的スキャンして集める(em dash専用ではない汎用判定)。
    OS班報告書の66箇所調査と同じ対象範囲。返り値: [(相対パス, 行番号, 文字列), ...]
    """
    found = []
    targets_dirs = [PIPELINE_PY_DIR, os.path.join(PIPELINE_DIR, "blender")]
    for d in targets_dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            fpath = os.path.join(d, fn)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                for m in _STRING_LITERAL_RE.finditer(line):
                    s = m.group(1) if m.group(1) is not None else m.group(2)
                    if not s:
                        continue
                    s_clean = _PLACEHOLDER_RE.sub("X", s)
                    try:
                        s_clean.encode("cp932")
                    except UnicodeEncodeError:
                        found.append((os.path.relpath(fpath, REPO_ROOT), i, s_clean))
                        if len(found) >= limit:
                            return found
    return found


def _build_cp932_hostile_env():
    """『他PCで起きたこと』を環境変数レベルで再現する基底環境を作る。

    この開発機自身のユーザー環境変数(PYTHONUTF8=1がHKCU\\Environmentに
    永続化済み、fix_FX_cp932.md 0節参照)がテストをマスクしないよう、まず
    PYTHONUTF8/PYTHONIOENCODINGを完全に取り除いた上で、PYTHONIOENCODING=cp932を
    明示指定する。レジストリのACP実値(このホストのシステム既定)に依存せず、
    どのホストで走らせても同じ条件を再現できる(移植性のため、素の変数除去だけに
    頼らない)。"""
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    env["PYTHONIOENCODING"] = "cp932"
    return env


def _apply_convert_ps1_overlay(env):
    """convert.ps1の実体から現在のPYTHONIOENCODING/PYTHONUTF8設定行を読み取り、
    見つかった値をenvへ上書きする(convert.ps1本体を実行せず、実際の設定行だけを
    動的に反映する。ミューテックス排他や実変換を避けつつ、convert.ps1の現在の
    中身に判定が追従する)。見つからなければ何もしない(=hostile環境のまま)。
    戻り値: (適用したキーのdict, convert.ps1が読めたか)
    """
    ps1_path = os.path.join(PIPELINE_DIR, "cli", "convert.ps1")
    applied = {}
    try:
        with open(ps1_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return applied, False
    # コメント行(PowerShellの#、行頭の空白を除いた最初の非空文字が#)は対象外にする。
    # そうしないと「行を#でコメントアウトして無効化した」負の対照が検出できず、
    # テキストとして残っているだけで合格してしまう(実装した≠効いている、を見逃す)。
    active_text = "\n".join(
        ln for ln in lines if not ln.strip().startswith("#")
    )
    for key, pat in _CONVERT_PS1_ENV_RE.items():
        m = pat.search(active_text)
        if m:
            env[key] = m.group(1)
            applied[key] = m.group(1)
    return applied, True


_A6_SUBPROCESS_SCRIPT = r"""
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    strings = json.load(f)
for s in strings:
    print(s)
sys.stdout.flush()
print("A6_ALL_PRINTED_OK")
"""


def gate_a6_cp932_subprocess_safety(work_root):
    t0 = time.time()
    what = ("convert.ps1が設定するPYTHONIOENCODING/PYTHONUTF8が、cp932しか使えない"
            "環境(日本語Windows既定・UTF-8ベータ未有効)でも子プロセスの標準出力が"
            "クラッシュしないことを実際に守っていることを検査する"
            "(2026-07-26 他PCでの実行失敗の再発防止、work\\fx_cp932\\fix_FX_cp932.md)")
    detail_lines = []

    harvested = _harvest_risky_strings()
    risky_strings = [_A6_CANARY] + [s for _f, _l, s in harvested]
    detail_lines.append("カナリア文字列: 1件(常時)")
    detail_lines.append("ソースから動的検出したcp932非互換文字列: {}件".format(len(harvested)))
    for f, ln, s in harvested[:12]:
        detail_lines.append("  {}:{}: {!r}".format(f, ln, s))

    hostile_env = _build_cp932_hostile_env()
    applied, ps1_readable = _apply_convert_ps1_overlay(hostile_env)
    detail_lines.append("hostile base: PYTHONIOENCODING=cp932 (PYTHONUTF8/PYTHONIOENCODING継承分は除去)")
    detail_lines.append("convert.ps1読み取り: {}".format("OK" if ps1_readable else "FAIL(ファイルなし?)"))
    detail_lines.append("convert.ps1から検出した上書き設定: {}".format(applied if applied else "(無し = 修正が外れている)"))

    strings_path = os.path.join(work_root, "a6_strings.json")
    os.makedirs(work_root, exist_ok=True)
    with open(strings_path, "w", encoding="utf-8") as f:
        json.dump(risky_strings, f, ensure_ascii=False)

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _A6_SUBPROCESS_SCRIPT, strings_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, env=hostile_env,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        crashed = ("UnicodeEncodeError" in out) or ("A6_ALL_PRINTED_OK" not in out) or proc.returncode != 0
        detail_lines.append("subprocess rc={}".format(proc.returncode))
        detail_lines.append(_tail(out, 2000))
    except Exception:
        crashed = True
        detail_lines.append("subprocess実行例外:\n" + traceback.format_exc())

    ok = (not crashed) and bool(applied)  # convert.ps1側の設定が見つからない場合も不合格
    if not applied:
        detail_lines.append("判定: convert.ps1にPYTHONIOENCODING/PYTHONUTF8の設定が"
                             "見つからないためFAIL(修正が外れている)")
    status = "PASS" if ok else "FAIL"
    return dict(name="A6_cp932_subprocess_safety", status=status, seconds=time.time() - t0,
                what=what, detail="\n".join(detail_lines))


# --- A7: 機微情報スキャン ------------------------------------------------------
# 2026-07-26発見: 配布zipに開発機の絶対パスと再配布不可の第三者アバター名
# (「toto」)が入っていたが、文字列ベースの機微情報検査は1つも存在しなかった
# (A1権利監査は画像の知覚照合でテキストは見ていない)。この穴を塞ぐゲート。
# 実体は devtools\sensitive_scan.py(denylistはdevtools\sensitive_denylist.py、
# devtools\は非公開なので実値が公開される矛盾を構造的に回避している)。
# 層1(身元)・層2(他人のもの)の検知がFAIL条件、層3(開発機パス等・環境の構造)は
# WARNのみでこのゲートをFAILにしない(work\sensitive_gate\INSTRUCTION.md 4節、
# オーナー裁定どおり)。

def gate_a7_sensitive_scan(work_root):
    t0 = time.time()
    what = ("配布zipに機微情報(層1: 仕事用メール等の身元、層2: 再配布不可の"
            "第三者アバター名等)が混入していないことを守る。開発機パス等(層3)は"
            "WARNのみで、このゲートをFAILにはしない"
            "(2026-07-26 発見、sensitive_scan.pyで機械検査化)。")
    detail_lines = []

    zip_path = _find_latest_dist_zip()
    if zip_path is None:
        return dict(name="A7_sensitive_scan", status="SKIP", seconds=time.time() - t0,
                    what=what, detail="zip未生成のためSKIP。配布zip作成後に必ず実行すること"
                                       "(dist\\*.zip またはリポジトリ直下\\*.zip が見つからなかった)。")

    scanner = os.path.join(DEVTOOLS_DIR, "sensitive_scan.py")
    out_json = os.path.join(work_root, "a7_sensitive_scan.json")
    try:
        proc = subprocess.run(
            [sys.executable, scanner, "--zip", zip_path, "--json", out_json],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, env=_no_bytecode_env(),
        )
        ok = proc.returncode == 0
        detail_lines.append("[sensitive_scan.py --zip {}] rc={} -> {}".format(
            zip_path, proc.returncode, "PASS" if ok else "FAIL"))
        detail_lines.append(_tail(proc.stdout + proc.stderr, 4000))
    except Exception:
        ok = False
        detail_lines.append("実行例外:\n" + traceback.format_exc())

    status = "PASS" if ok else "FAIL"
    return dict(name="A7_sensitive_scan", status=status, seconds=time.time() - t0,
                what=what, detail="\n".join(detail_lines))


# --- A8: GUI配線契約(WP11、2026-07-27) ------------------------------------------
# 背景: A3は「GUIが起動して3.5秒落ちない」ことしか見ておらず、「フル変換」ボタンが
# 実際に行う job.json生成 -> convert.ps1起動 の配線(2026-07-26のcp932事故はまさに
# この経路が引き金だった)は誰も検証していなかった。クリック自動化はこの環境では
# 使えない(WP6 T6で確認済み)ため、tests\shipcheck\gui_wiring_check.py が
# app\DiveToPalworld.cs に追加したヘッドレスCLIモード(--emit-wiring、GUIの実際の
# メソッドWriteJob/BuildConvertScriptPath/BuildConvertArgs/FindPwshをそのまま呼ぶ)
# を使って、job.jsonのスキーマ・起動コマンド・環境変数責務分担を検査する。
# 詳細・必須キーの根拠・負の対照の実測記録はgui_wiring_check.pyのdocstringと
# 本ファイル(SHIPCHECK.md)のA8節を参照。

def gate_a8_gui_wiring(work_root):
    t0 = time.time()
    what = ("GUI(app\\DiveToPalworld.cs)の「フル変換」が行うjob.json生成→convert.ps1起動の"
            "配線が壊れていないこと(2026-07-26 cp932事故のクラスの再発防止、WP11)")
    detail_lines = []
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import gui_wiring_check as gwc
        # WP11の書き込み許可域はwork\relgate\wp11\**に限定されているため、
        # ship_smoke.py呼び出し元が指定した work_root(他WPの領域と衝突しうる)は
        # 使わず、常にgui_wiring_check.py既定の固定サブツリー配下へ出す。
        gwc_work_root = gwc.default_work_root()
        result = gwc.run_check(gwc_work_root, mutation_key=None)
        ok = result.ok
        detail_lines.append("gui_wiring_check work_dir: {}".format(gwc_work_root))
        detail_lines.append(result.render())
    except Exception:
        ok = False
        detail_lines.append("実行例外:\n" + traceback.format_exc())

    return dict(name="A8_gui_wiring", status="PASS" if ok else "FAIL",
                seconds=time.time() - t0, what=what, detail="\n".join(detail_lines))


# --- A9: 外部依存resolverのユニット試験(dev#22 / WP resolver、2026-07-28追加)----

def gate_a9_dep_resolver_unit(work_root):
    """外部依存resolver(pipeline\\py\\dep_resolver.py)のユニット試験を丸ごと回す。

    A4はpy_compile+importまでしか見ないため、resolverの挙動退行(台帳発見・
    手動指定の最優先・失敗時のtrail+案内)はここで守る。テスト自体は
    tests\\resolver\\test_*.py(stdlib unittest、偽台帳フィクスチャは
    tempfileに自作するので排他資源なし・数秒で終わる)。負の対照
    (どの戦略にも該当しない環境で「探した場所一覧+手動指定案内」が返ること)を含む。

    dev#346: 以前はここで tests\\resolver\\test_dep_resolver.py だけをファイル名
    べた書きで実行していた。そのため dev#325 で新設された
    test_dep_resolver_privacy.py(trail出力の生パス漏洩を守る試験)が「リポジトリに
    存在するのに、どのゲートからも一度も実行されない」状態になっていた
    (= 試験はあるが効いていない)。単一ファイル指定をやめ、ディレクトリ配下の
    test_*.py を全て走査する方式へ変更する。今後 tests\\resolver\\ に足された試験も
    自動的にこのゲートの対象になり、同じ穴が再発しない。
    """
    t0 = time.time()
    what = ("外部依存resolver(pipeline\\py\\dep_resolver.py, dev#22/#23)のユニット試験が"
            "全て緑であることを守る(tests\\resolver\\test_*.py を全件実行。"
            "trail出力のprivacy回帰 dev#325/#346 を含む)")
    detail_lines = []
    resolver_dir = os.path.join(REPO_ROOT, "tests", "resolver")
    test_files = sorted(glob.glob(os.path.join(resolver_dir, "test_*.py")))
    if not test_files:
        return dict(name="A9_dep_resolver_unit", status="FAIL", seconds=time.time() - t0,
                    what=what,
                    detail="テストファイルが1件も見つからない: " +
                           os.path.join(resolver_dir, "test_*.py"))
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # 実行機に設定されたresolverの手動指定系が漏れて偽PASS/偽FAILに
    # ならないよう明示的に除去する(テスト側もenv注入で隔離しているが二重防御)
    for k in ("D2P_UNITY_EDITOR", "D2P_UNITY_HUB_ROOT", "D2P_RESOLVER_NO_PYTHON"):
        env.pop(k, None)
    ok = True
    detail_lines.append("対象 {} 件: {}".format(
        len(test_files), ", ".join(os.path.basename(p) for p in test_files)))
    for test_py in test_files:
        base = os.path.basename(test_py)
        try:
            proc = subprocess.run(
                [sys.executable, test_py], cwd=REPO_ROOT, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=120, env=env)
            if proc.returncode != 0:
                ok = False
            detail_lines.append("--- {} rc={} ---".format(base, proc.returncode))
            detail_lines.append(_tail(proc.stdout + proc.stderr, 3000))
        except Exception:
            ok = False
            detail_lines.append("--- {} 実行例外 ---\n".format(base) +
                                traceback.format_exc())
    return dict(name="A9_dep_resolver_unit", status="PASS" if ok else "FAIL",
                seconds=time.time() - t0, what=what, detail="\n".join(detail_lines))


TIER_A_GATES = [
    gate_a1_rights_audit,
    gate_a2_doc_consistency,
    gate_a3_app_build_launch,
    gate_a4_pipeline_health,
    gate_a5_ps1_syntax,
    gate_a6_cp932_subprocess_safety,
    gate_a7_sensitive_scan,
    gate_a8_gui_wiring,
    gate_a9_dep_resolver_unit,
]


# --- Tier B 接続(SE班 ship_convert_cases.py) -----------------------------------

def _try_import_convert_cases():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import ship_convert_cases as scc  # noqa
        if not hasattr(scc, "CASES") or not hasattr(scc, "run_case"):
            return None, "ship_convert_cases.py はあるが CASES/run_case が無い(契約不一致)"
        return scc, None
    except Exception:
        return None, "import失敗:\n" + traceback.format_exc()


def _copy_case_images(result, shots_dir):
    name = result.get("name", "case")
    copied = []
    for img in (result.get("images") or []):
        try:
            base = os.path.basename(img)
            dest = os.path.join(shots_dir, "{}_{}".format(name, base))
            shutil.copy2(img, dest)
            copied.append(dest)
        except Exception:
            pass
    return copied


# --- レポート出力 --------------------------------------------------------------

def _report_init(path, mode, work_root):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = "# ship_smoke report\n\n"
    text += "- 開始: {}\n".format(datetime.datetime.now().isoformat(timespec="seconds"))
    text += "- モード: {}\n".format(mode)
    text += "- 作業フォルダ: {}\n".format(work_root)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _report_append_gate(path, r):
    marker = "\U0001F534 " if r["name"].startswith("A1_") else ""
    text = "\n## {}{} — {}\n\n".format(marker, r["name"], r["status"])
    text += "- 守っているもの: {}\n".format(r.get("what", ""))
    text += "- 所要: {:.1f}秒\n\n".format(r.get("seconds", 0.0))
    text += "```\n{}\n```\n".format((r.get("detail") or "").strip())
    _append(path, text)


def _report_append_case(path, r, status):
    text = "\n## TierB: {} — {}\n\n".format(r.get("name"), status)
    text += "- 所要: {:.1f}秒\n".format(r.get("seconds", 0.0))
    imgs = r.get("images") or []
    if imgs:
        text += "- 画像: {}\n".format(", ".join(os.path.basename(p) for p in imgs))
    text += "\n```\n{}\n```\n".format((r.get("detail") or "").strip())
    _append(path, text)


def _case_status_label(r):
    """dev#128/rd_121: TierBケースがrelgate結果参照でSKIPされた場合、report.md/
    標準出力の一覧で一目でわかるようラベルへ反映する(detail は
    ship_convert_cases.py::_finish() がjson.dumpsした文字列なので、ここで
    緩く復元する。パース失敗時は従来どおりPASS/FAILのみ表示=fail-safe)。"""
    base = "PASS" if r.get("ok") else "FAIL"
    try:
        parsed = json.loads(r.get("detail") or "{}")
        if isinstance(parsed, dict) and parsed.get("skipped_via_relgate") is True:
            return base + "(SKIP:relgate参照)"
    except (ValueError, TypeError):
        pass
    return base


def _report_append_skip_time(path, case, remaining):
    text = "\n## TierB: {} — SKIPPED(時間切れ)\n\n".format(case.get("name"))
    text += "見積 {}秒 > 残り時間 {:.0f}秒\n".format(case.get("est_sec", "?"), remaining)
    _append(path, text)


def _report_append_note(path, text):
    _append(path, text)


def _report_finalize(path, tier_a_results, tier_b_results, tier_b_skipped, total_elapsed):
    lines = ["\n---\n\n## サマリ\n\n"]
    lines.append("| ゲート/ケース | 種別 | status | 秒数 |\n")
    lines.append("|---|---|---|---|\n")
    for r in tier_a_results:
        lines.append("| {} | TierA | {} | {:.1f} |\n".format(r["name"], r["status"], r["seconds"]))
    for r in tier_b_results:
        status = _case_status_label(r)
        lines.append("| {} | TierB | {} | {:.1f} |\n".format(r.get("name"), status, r.get("seconds", 0.0)))
    for c in tier_b_skipped:
        lines.append("| {} | TierB | SKIP(時間切れ) | - |\n".format(c.get("name")))
    lines.append("\n合計所要時間: {:.1f}秒\n".format(total_elapsed))
    _append(path, "".join(lines))


# --- メイン -------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=int, default=20, help="実時間の上限(分)。既定20")
    ap.add_argument("--fast", action="store_true", help="Tier Aのみ(目標2分以内)")
    ap.add_argument("--work", default=None, help="作業フォルダ(既定: work\\shipcheck_<timestamp>\\)")
    ap.add_argument(
        "--relgate-work", default=None,
        help="直近に実行したrelgate(devtools\\relgate.py --layers 12)の--work"
             "ディレクトリ。指定すると、Tier Bの vrm_full_0x / drop_bone_exclusion "
             "の2ケースが、そのrelgate結果(results.json)を参照して実変換を"
             "SKIPできるか判定する(dev#128/rd_121: relgateの既定検体"
             "vrm0_kate/vrm1_seedsanと検体・設定が重複しているため)。鮮度条件"
             "(relgate結果のgit HEADが現HEADと一致)を満たさない場合は必ず"
             "実変換にフォールバックする(fail-closed)。未指定(既定)なら"
             "従来どおり全ケースを実変換する。",
    )
    ap.add_argument(
        "--zip-audit", choices=["auto", "defer"], default="auto",
        help="A1のu28_zip_audit.py実行方針。auto(既定): dist\\の最新zipがあれば鮮度照合まで"
             "実行する(単体実行向け、従来どおりの挙動)。defer: u28_zip_audit.pyを実行せず"
             "「ビルド後の新zipに対してrelease.pyが実施(deferred)」と明記してSKIPする"
             "(release.pyのようにship_smoke --fastが新zipビルド前に走るフロー向け。旧zipとの"
             "鮮度不一致による構造的偽陽性を避ける)。u45(--live)はどちらでも必ず実行する。",
    )
    args = ap.parse_args(argv)

    work_root = os.path.abspath(args.work) if args.work else os.path.join(
        REPO_ROOT, "work", "shipcheck_{}".format(_now_ts()))
    shots_dir = os.path.join(work_root, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    report_path = os.path.join(work_root, "report.md")

    mode = "--fast (Tier Aのみ)" if args.fast else "Tier A -> Tier B (上限{}分)".format(args.minutes)
    _report_init(report_path, mode, work_root)
    print("=== ship_smoke ===")
    print("work_root: {}".format(work_root))
    print("mode: {}".format(mode))

    start = time.time()
    deadline = start + args.minutes * 60

    tier_a_results = []
    for gate_fn in TIER_A_GATES:
        try:
            if gate_fn is gate_a1_rights_audit:
                r = gate_fn(work_root, zip_audit_mode=args.zip_audit)
            else:
                r = gate_fn(work_root)
        except Exception:
            r = dict(name=getattr(gate_fn, "__name__", "unknown_gate"), status="FAIL", seconds=0.0,
                      what="(ゲート実装内の想定外例外。ship_smoke.py自体のバグの可能性)",
                      detail=traceback.format_exc())
        tier_a_results.append(r)
        _report_append_gate(report_path, r)
        print("[{}] {} ({:.1f}s)".format(r["status"], r["name"], r["seconds"]))

    tier_b_results = []
    tier_b_skipped = []
    if args.fast:
        _report_append_note(report_path, "\n## Tier B\n\n--fast指定のためスキップ(Tier Aのみ)\n")
        print("[SKIP] Tier B (--fast)")
    else:
        scc, err = _try_import_convert_cases()
        if scc is None:
            _report_append_note(
                report_path,
                "\n## Tier B\n\n未接続(SKIP): tests\\shipcheck\\ship_convert_cases.py が"
                "未実装またはimport失敗。\n\n```\n{}\n```\n".format(err or ""))
            print("[SKIP] Tier B 未接続: {}".format((err or "").splitlines()[-1] if err else ""))
        else:
            for case in scc.CASES:
                remaining = deadline - time.time()
                est = case.get("est_sec", 0)
                if est > remaining:
                    tier_b_skipped.append(case)
                    _report_append_skip_time(report_path, case, remaining)
                    print("[SKIP] {} 時間切れ(見積{}秒 > 残り{:.0f}秒)".format(
                        case.get("name"), est, remaining))
                    continue
                case_work_root = os.path.join(work_root, "tierb", str(case.get("name")))
                # dev#128/rd_121: relgate結果参照SKIPの契約(CASES自体は
                # relgate_workキーを持たない。呼び出し直前にコピーへ足すことで
                # ship_convert_cases.py側の契約(モジュール docstring参照)を守る)。
                case_to_run = dict(case)
                case_to_run["relgate_work"] = args.relgate_work
                try:
                    r = scc.run_case(case_to_run, case_work_root, shots_dir)
                except Exception:
                    r = dict(name=case.get("name"), ok=False, seconds=0.0, images=[],
                              detail="run_case()が例外を投げた(契約違反、SE班側の実装バグ):\n"
                                     + traceback.format_exc())
                tier_b_results.append(r)
                _copy_case_images(r, shots_dir)
                status = _case_status_label(r)
                _report_append_case(report_path, r, status)
                print("[{}] {} ({:.1f}s)".format(status, r.get("name"), r.get("seconds", 0.0)))

    total_elapsed = time.time() - start
    _report_finalize(report_path, tier_a_results, tier_b_results, tier_b_skipped, total_elapsed)

    print("\n=== SUMMARY ===")
    for r in tier_a_results:
        print("  [{:4s}] TierA {} ({:.1f}s)".format(r["status"], r["name"], r["seconds"]))
    for r in tier_b_results:
        print("  [{:4s}] TierB {} ({:.1f}s)".format("PASS" if r.get("ok") else "FAIL",
                                                      r.get("name"), r.get("seconds", 0.0)))
    for c in tier_b_skipped:
        print("  [SKIP] TierB {} (時間切れ)".format(c.get("name")))
    print("report: {}".format(report_path))
    print("total elapsed: {:.1f}s".format(total_elapsed))

    fail = any(r["status"] == "FAIL" for r in tier_a_results) or any(
        not r.get("ok") for r in tier_b_results)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
