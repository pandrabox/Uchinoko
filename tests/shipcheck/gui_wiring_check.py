# -*- coding: utf-8 -*-
"""WP11(2026-07-27): GUI配線契約テスト。

背景: リリースゲート群(devtools\\release.py / ship_smoke.py)は完成しているが、
GUI(app\\DiveToPalworld.cs)の「フル変換」ボタンが実際に行う
    job.json生成(WriteJob) -> convert.ps1起動(BuildConvertScriptPath/BuildConvertArgs/FindPwsh)
という配線そのものは誰も検証していなかった。ship_smoke.pyのA3は「GUIが起動して
3.5秒落ちない」ことしか見ておらず、job.jsonの中身やconvert.ps1の起動コマンドは
一切見ていない。2026-07-26のcp932事故はまさにこの「GUI経由の起動」が引き金だった
(GUIがconvert.ps1をリダイレクト付きで起動する状況特有の不具合)。

クリック自動化はこの環境では実行できない(WP6 T6で確認済み)ため、
「実際にGUIが使うのと同じメソッドを、画面を出さずに直接呼んで結果をファイルへ
書き出す」ヘッドレス契約テストで代替する。

## テスト対象にした変更(app\\DiveToPalworld.cs、追加のみ)
1. `BuildConvertScriptPath()` / `BuildConvertArgs()` — RunPipeline()に元々あった
   convert.ps1のパス解決・引数組み立てのロジックをそのままメソッドへ切り出した
   (戻り値・動作は不変。RunPipeline側は切り出したメソッドを呼ぶよう2行だけ変更)。
2. `EmitWiring(outDir, repoRoot)` / `--emit-wiring <outDir> <repoRoot>` 隠しCLIモード
   — WriteJob() / BuildConvertScriptPath() / BuildConvertArgs() / FindPwsh() という
   実際にGUIが「フル変換」時に呼ぶのと同じメソッドを呼び出し、結果(job.jsonと
   起動コマンドライン)をファイルへ書き出して終了する。convert.ps1は起動しない。
   通常起動(Main()の引数なし経路)の動作は変えていない。

## このスクリプトが検査すること
  a. job.jsonのスキーマ・必須キー(REQUIRED_TOP_KEYS / REQUIRED_PATHS_KEYS、根拠は
     下記「必須キーの根拠」)が欠けていないこと(値は検体依存で可)。
  b. 起動コマンドが実在する pipeline\\cli\\convert.ps1 を正しい絶対パスで指し、
     -File / -Job 引数が正しく渡っていること。
  c. 環境変数契約(PYTHONIOENCODING=utf-8 / PYTHONUTF8=1): GUI側のソースが
     これらの変数を明示的にセット/上書きしていない(=convert.ps1の自己設定を
     阻害していない)こと、かつconvert.ps1側が実際にこの2行を無条件(コメント
     アウトされていない)で持っていること。責務分担の根拠は
     `check_env_contract()` のdocstring参照。

## 必須キーの根拠
- `pipeline\\cli\\convert.ps1` 冒頭のコメント(8行目):
      "前提: job.json(paths.blender_exe / vrm_addon_zip 必須)"
  さらに実装 (`$Blender = $cfg.paths.blender_exe` の直後で `Test-Path` チェックし
  無ければ即 `Write-Error` して `exit 1`) でも裏付けられている。
- `pipeline\\blender\\vp_bl.py::ensure_vrm_addon()` が
  `job["paths"].get("vrm_addon_zip")` を読む(VRMアドオン導入に必須)。
- `avatar_name` はconvert.ps1側にフォールバック既定があるが
  (`$Avatar = if ($cfg.avatar_name) {...} else {"Avatar"}`)、GUIが常に
  明示出力する設計になっている(`WriteJob()`)ため、GUIの契約としては必須キー
  として扱う(欠落=WriteJob()の退行を示すため)。
- dev#114(2026-07-29): UEパイプライン完全削除に伴い `engine_mode` /
  `paths.ue_project` / `paths.ue_root` はWriteJob()が書かなくなった
  (convert.ps1は常にnoue専用。job.jsonにengine_modeが無くても既定noueで動く)。
  必須キー・負の対照からもこの3キーの扱いを除去した。
- `pipeline\\job.example.json`(CLI直接利用者向けの公式サンプル)も同じ
  `vrm_path` / `avatar_name` / `paths.blender_exe` / `paths.vrm_addon_zip` の
  組を必須級として提示している。

## 使い方
    python tests\\shipcheck\\gui_wiring_check.py [--work <dir>]
    python tests\\shipcheck\\gui_wiring_check.py --mutate missing_key   # 負の対照
    python tests\\shipcheck\\gui_wiring_check.py --mutate broken_path   # 負の対照

--work省略時は `work\\relgate\\wp11\\gui_wiring_check_<timestamp>\\`
(このWPの書き込み許可域の外へは出さない設計。ship_smoke.py組み込み時
 (gate_a8_gui_wiring)もこの既定を使い、ship_smoke.py自身の--workは無視する
 ——detail参照)。

終了コード: 全項目PASSなら0、1つでもFAILなら1。fail-closed
(ビルド失敗・emit失敗・キー欠落は全て赤)。
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_DIR = os.path.join(REPO_ROOT, "app")
PIPELINE_DIR = os.path.join(REPO_ROOT, "pipeline")
CONVERT_PS1_REL = os.path.join("pipeline", "cli", "convert.ps1")

REQUIRED_TOP_KEYS = ["vrm_path", "avatar_name", "paths"]
REQUIRED_PATHS_KEYS = ["blender_exe", "vrm_addon_zip"]

# 負の対照用の変異定義。app\DiveToPalworld.cs本体は変異させず、work配下に
# コピーしたソースツリーに対してのみ適用する(禁則: 本体ソースの変異)。
MUTATIONS = {
    "missing_key": {
        "desc": "job.jsonの必須キー(avatar_name)を書かせない変異(WriteJob内の1行を削除)",
        "find": (
            '            sb.AppendFormat("  \\"avatar_name\\": \\"{0}\\",\\n", name);\n'
        ),
        "replace": "",
    },
    "broken_path": {
        "desc": "convert.ps1のパスを壊す変異(BuildConvertScriptPathが別ファイル名を指すようにする)",
        "find": (
            '            return Path.Combine(appRoot, "pipeline", "cli", "convert.ps1");\n'
        ),
        "replace": (
            '            return Path.Combine(appRoot, "pipeline", "cli", '
            '"convert_BROKEN_PATH_NEGATIVE_CONTROL.ps1");\n'
        ),
    },
}


def _tail(text, n=4000):
    text = text or ""
    return text[-n:]


def _now_ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class Result:
    def __init__(self):
        self.checks = []  # [(name, ok, detail)]

    def add(self, name, ok, detail=""):
        self.checks.append((name, ok, detail))

    @property
    def ok(self):
        return all(ok for _n, ok, _d in self.checks)

    def render(self):
        lines = []
        for name, ok, detail in self.checks:
            lines.append("[{}] {}".format("PASS" if ok else "FAIL", name))
            if detail:
                lines.append(_indent(detail))
        return "\n".join(lines)


def _indent(text, prefix="    "):
    return "\n".join(prefix + l for l in (text or "").splitlines())


# --- ソース準備(通常/負の対照) --------------------------------------------------

def _prepare_source_tree(work_dir, mutation_key=None):
    """検査対象のソース一式を work_dir\\src_under_test へ用意する。

    mutation_key が None なら本体(REPO_ROOT)をそのまま使う(コピーせず参照)。
    mutation_key が指定されていれば、必要最小限のファイル
    (app\\DiveToPalworld.cs, app\\build_app.ps1, ico\\favicon.ico(あれば),
    pipeline\\cli\\convert.ps1)だけを work_dir\\src_under_test へコピーし、
    DiveToPalworld.cs にだけ変異を適用する。本体ソース(REPO_ROOT配下)は
    一切書き換えない。
    戻り値: (source_root, note)
    """
    if mutation_key is None:
        return REPO_ROOT, "本体ソース(REPO_ROOT)を直接使用(変異なし)"

    if mutation_key not in MUTATIONS:
        raise ValueError("未知のmutation_key: {}".format(mutation_key))
    # 2026-07-31以降、app\build_app.ps1 は DiveToPalworld.cs と
    # 同じディレクトリの AssemblyInfo.cs(アセンブリメタデータ)を前提にビルドする。
    # 2026-08-01(dev#523)以降は同様に app.manifest(asInvokerマニフェスト)も
    # 前提になった(無いとbuild_app.ps1がWrite-Errorで停止する)。
    # ここで最小構成をコピーしているため、これらも一緒に持ち込まないとビルド自体が
    # 失敗する(下のコピー処理を参照)。

    src_root = os.path.join(work_dir, "src_under_test_" + mutation_key)
    if os.path.isdir(src_root):
        shutil.rmtree(src_root)
    os.makedirs(os.path.join(src_root, "app"), exist_ok=True)
    os.makedirs(os.path.join(src_root, "pipeline", "cli"), exist_ok=True)
    os.makedirs(os.path.join(src_root, "ico"), exist_ok=True)
    os.makedirs(os.path.join(src_root, "third_party"), exist_ok=True)

    cs_src = os.path.join(APP_DIR, "DiveToPalworld.cs")
    with open(cs_src, encoding="utf-8") as f:
        cs_text = f.read()
    mut = MUTATIONS[mutation_key]
    if mut["find"] not in cs_text:
        raise RuntimeError(
            "変異対象の文字列が現行ソースに見つからない(ソース側の変更で"
            "ズレた可能性): {!r}".format(mut["find"][:120]))
    mutated_text = cs_text.replace(mut["find"], mut["replace"], 1)
    if mutated_text == cs_text:
        raise RuntimeError("変異が適用されなかった(置換前後で同一)")
    with open(os.path.join(src_root, "app", "DiveToPalworld.cs"), "w", encoding="utf-8") as f:
        f.write(mutated_text)

    shutil.copy2(os.path.join(APP_DIR, "build_app.ps1"),
                 os.path.join(src_root, "app", "build_app.ps1"))
    shutil.copy2(os.path.join(APP_DIR, "AssemblyInfo.cs"),
                 os.path.join(src_root, "app", "AssemblyInfo.cs"))
    shutil.copy2(os.path.join(APP_DIR, "app.manifest"),
                 os.path.join(src_root, "app", "app.manifest"))
    icon_src = os.path.join(REPO_ROOT, "ico", "favicon.ico")
    if os.path.isfile(icon_src):
        shutil.copy2(icon_src, os.path.join(src_root, "ico", "favicon.ico"))
    shutil.copy2(os.path.join(PIPELINE_DIR, "cli", "convert.ps1"),
                 os.path.join(src_root, "pipeline", "cli", "convert.ps1"))

    # WriteJob()はVRMアドオンzipをFindFirst()で実ファイル検索し(見つからなければ
    # null)、その結果をJ()(nullを想定していない.Replace呼び出し)へそのまま渡す。
    # 変異検査の対象はmissing_key/broken_pathの2種だけであり、この副作用
    # (フィクスチャ不足によるNullReferenceException)で検査が本来見たい箇所より
    # 手前で落ちてしまわないよう、本体のVRMアドオンzipを読み取り専用でコピーする
    # (このNull安全性自体は本WPのスコープ外の既存挙動なので、ここで補うだけで
    # app\DiveToPalworld.cs側は一切変更しない)。
    for fn in os.listdir(os.path.join(REPO_ROOT, "third_party")):
        if fn.startswith("VRM_Addon_for_Blender-Extension") and fn.endswith(".zip"):
            shutil.copy2(os.path.join(REPO_ROOT, "third_party", fn),
                         os.path.join(src_root, "third_party", fn))
            break

    return src_root, "変異適用: {} ({})".format(mutation_key, mut["desc"])


# --- ビルド・emit実行 ----------------------------------------------------------

def _build_exe(source_root, build_dir):
    build_ps1 = os.path.join(source_root, "app", "build_app.ps1")
    out_exe = os.path.join(build_dir, "DiveToPalworld_wiring_check.exe")
    os.makedirs(build_dir, exist_ok=True)
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-File", build_ps1, "-Out", out_exe],
        cwd=source_root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120,
    )
    ok = proc.returncode == 0 and os.path.isfile(out_exe)
    detail = "rc={}\n{}".format(proc.returncode, _tail(proc.stdout + proc.stderr, 3000))
    return ok, out_exe, detail


def _run_emit(exe_path, out_dir, repo_root_for_app):
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    try:
        proc = subprocess.run(
            [exe_path, "--emit-wiring", out_dir, repo_root_for_app],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
    except Exception:
        return False, "実行例外:\n" + traceback.format_exc()
    ok = proc.returncode == 0 and "EMIT_WIRING_OK" in (proc.stdout or "")
    detail = "rc={} stdout={!r} stderr={!r}".format(
        proc.returncode, _tail(proc.stdout, 1000), _tail(proc.stderr, 1000))
    return ok, detail


# --- (a) job.jsonスキーマ検査 ---------------------------------------------------

def check_job_schema(job):
    """job.jsonが必須キーを備えているか(値は検体依存で可)。
    戻り値: (ok, detail)"""
    problems = []
    for k in REQUIRED_TOP_KEYS:
        if k not in job:
            problems.append("top-level必須キー欠落: {}".format(k))
    for k in ("vrm_path", "avatar_name"):
        if k in job and not (isinstance(job[k], str) and job[k].strip()):
            problems.append("{} が空/文字列でない: {!r}".format(k, job.get(k)))
    paths = job.get("paths")
    if not isinstance(paths, dict):
        problems.append("pathsがオブジェクトでない: {!r}".format(paths))
    else:
        for k in REQUIRED_PATHS_KEYS:
            if k not in paths:
                problems.append("paths必須キー欠落: {}".format(k))
            elif not (isinstance(paths[k], str) and paths[k].strip()):
                problems.append("paths.{} が空/文字列でない: {!r}".format(k, paths.get(k)))
    ok = not problems
    detail = "OK" if ok else "\n".join(problems)
    return ok, detail


# --- (b) 起動コマンド検査 -------------------------------------------------------

_ARGS_RE = re.compile(
    r'^-NoProfile -ExecutionPolicy Bypass -File "([^"]+)" -Job "([^"]+)"'
)


def check_launch_command(wiring, expected_convert_ps1, job_json_path):
    """起動コマンドが実在するconvert.ps1を正しいパスで指し、-File/-Jobが
    正しく渡っていることを検査する。戻り値: (ok, detail)"""
    problems = []
    script = wiring.get("script", "")
    shell = wiring.get("shell", "")
    args = wiring.get("args", "")

    norm_script = os.path.normcase(os.path.abspath(script))
    norm_expected = os.path.normcase(os.path.abspath(expected_convert_ps1))
    if norm_script != norm_expected:
        problems.append("scriptが期待パスと不一致: {!r} != {!r}".format(script, expected_convert_ps1))
    if not os.path.isfile(expected_convert_ps1):
        problems.append("scriptの指す先が実在しない: {!r}".format(expected_convert_ps1))

    shell_base = os.path.basename(shell).lower()
    if shell_base not in ("pwsh.exe", "powershell.exe"):
        problems.append("shellがpwsh.exe/powershell.exeではない: {!r}".format(shell))

    m = _ARGS_RE.match(args)
    if not m:
        problems.append("args形式が想定と不一致(-File/-Jobの並び): {!r}".format(args))
    else:
        file_arg, job_arg = m.group(1), m.group(2)
        if os.path.normcase(os.path.abspath(file_arg)) != norm_expected:
            problems.append("-File引数が期待パスと不一致: {!r}".format(file_arg))
        if os.path.normcase(os.path.abspath(job_arg)) != os.path.normcase(os.path.abspath(job_json_path)):
            problems.append("-Job引数がjob.jsonの実パスと不一致: {!r} != {!r}".format(
                job_arg, job_json_path))

    ok = not problems
    detail = "OK: script={} shell={} args={}".format(script, shell, args) if ok else "\n".join(problems)
    return ok, detail


# --- (c) 環境変数契約 -----------------------------------------------------------

_ENV_ASSIGN_RE = {
    "PYTHONIOENCODING": re.compile(r'\$env:PYTHONIOENCODING\s*=\s*"([^"]*)"'),
    "PYTHONUTF8": re.compile(r'\$env:PYTHONUTF8\s*=\s*"([^"]*)"'),
}


def check_env_contract(app_cs_path, convert_ps1_path):
    """PYTHONIOENCODING=utf-8 / PYTHONUTF8=1 の責務分担契約を検査する。

    設計: convert.ps1が自分の子プロセス全部に効くよう冒頭で無条件に
    `$env:PYTHONIOENCODING = "utf-8"` / `$env:PYTHONUTF8 = "1"` を設定する
    (2026-07-26 cp932事故の修正、ship_smoke.py A6が実行時の効果を別途検証済み)。
    GUI(app\\DiveToPalworld.cs)はconvert.ps1を子プロセスとして起動する側であり、
    ProcessStartInfo.EnvironmentVariablesを一切触っていない(=現在の実装は
    親プロセスの環境をそのまま継承させるだけで、convert.ps1がその後自分の
    プロセス内で`$env:...=`する値を上書き・阻害する余地が構造的に無い)。
    したがってこのゲートが守るのは「GUI側のソースがこの2変数を明示指定して
    convert.ps1の自己設定と競合する上書きをしていないこと」+「convert.ps1側が
    実際にこの2行を(コメントアウトせず)持っていること」の両輪。
    どちらか片方が崩れても検出できる。
    戻り値: (ok, detail)
    """
    problems = []
    try:
        with open(app_cs_path, encoding="utf-8") as f:
            cs_text = f.read()
    except Exception as e:
        return False, "DiveToPalworld.cs読み込み失敗: {}".format(e)

    if ".EnvironmentVariables[" in cs_text:
        problems.append(
            "GUI側がProcessStartInfo.EnvironmentVariables[...]を明示操作している形跡がある。"
            "PYTHONIOENCODING/PYTHONUTF8をconvert.ps1の設定と食い違う値で上書きしていないか"
            "個別に確認すること(現行設計は無関与のはずで、これが出たら退行の疑い)。")

    try:
        with open(convert_ps1_path, encoding="utf-8") as f:
            ps1_lines = f.readlines()
    except Exception as e:
        return False, "convert.ps1読み込み失敗: {}".format(e)

    active_text = "\n".join(ln for ln in ps1_lines if not ln.strip().startswith("#"))
    found = {}
    for key, pat in _ENV_ASSIGN_RE.items():
        m = pat.search(active_text)
        if m:
            found[key] = m.group(1)
    if found.get("PYTHONIOENCODING") != "utf-8":
        problems.append("convert.ps1にPYTHONIOENCODING=\"utf-8\"の無条件設定が見つからない: {}".format(found))
    if found.get("PYTHONUTF8") != "1":
        problems.append("convert.ps1にPYTHONUTF8=\"1\"の無条件設定が見つからない: {}".format(found))

    ok = not problems
    detail = "OK: convert.ps1設定={}".format(found) if ok else "\n".join(problems)
    return ok, detail


# --- メイン検査フロー -----------------------------------------------------------

def run_check(work_dir, mutation_key=None):
    """1回分の検査(通常 or 負の対照1種)を実行し Result を返す。"""
    r = Result()
    os.makedirs(work_dir, exist_ok=True)

    try:
        source_root, note = _prepare_source_tree(work_dir, mutation_key)
        r.add("0_source_prepared", True, note)
    except Exception:
        r.add("0_source_prepared", False, traceback.format_exc())
        return r

    build_dir = os.path.join(work_dir, "build")
    build_ok, exe_path, build_detail = _build_exe(source_root, build_dir)
    r.add("1_build", build_ok, build_detail)
    if not build_ok:
        return r

    emit_dir = os.path.join(work_dir, "emit_out")
    emit_ok, emit_detail = _run_emit(exe_path, emit_dir, source_root)
    r.add("2_emit_wiring_run", emit_ok, emit_detail)
    if not emit_ok:
        return r

    wiring_path = os.path.join(emit_dir, "wiring.json")
    job_path = os.path.join(emit_dir, "job.json")
    try:
        with open(wiring_path, encoding="utf-8") as f:
            wiring = json.load(f)
        r.add("3_wiring_json_readable", True)
    except Exception:
        r.add("3_wiring_json_readable", False, traceback.format_exc())
        return r
    try:
        with open(job_path, encoding="utf-8") as f:
            job = json.load(f)
        r.add("4_job_json_readable", True)
    except Exception:
        r.add("4_job_json_readable", False, traceback.format_exc())
        return r

    ok, detail = check_job_schema(job)
    r.add("a_job_schema", ok, detail)

    expected_convert_ps1 = os.path.join(source_root, CONVERT_PS1_REL)
    job_json_real_path = wiring.get("job_json_path", job_path)
    ok, detail = check_launch_command(wiring, expected_convert_ps1, job_json_real_path)
    r.add("b_launch_command", ok, detail)

    app_cs_path = os.path.join(source_root, "app", "DiveToPalworld.cs")
    ok, detail = check_env_contract(app_cs_path, expected_convert_ps1)
    r.add("c_env_contract", ok, detail)

    return r


def default_work_root():
    return os.path.join(REPO_ROOT, "work", "relgate", "wp11",
                         "gui_wiring_check_{}".format(_now_ts()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=None,
                     help="作業フォルダ(既定: work\\relgate\\wp11\\gui_wiring_check_<timestamp>\\)")
    ap.add_argument("--mutate", choices=sorted(MUTATIONS.keys()), default=None,
                     help="負の対照: 指定した変異を適用したソースで検査する(本体は変異しない)")
    args = ap.parse_args(argv)

    work_dir = os.path.abspath(args.work) if args.work else default_work_root()
    print("=== gui_wiring_check ===")
    print("work_dir: {}".format(work_dir))
    print("mutate: {}".format(args.mutate or "(なし・通常検査)"))

    t0 = time.time()
    result = run_check(work_dir, mutation_key=args.mutate)
    elapsed = time.time() - t0

    report_path = os.path.join(work_dir, "report.md")
    os.makedirs(work_dir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# gui_wiring_check report\n\n")
        f.write("- mutate: {}\n".format(args.mutate or "(なし)"))
        f.write("- 所要: {:.1f}秒\n\n".format(elapsed))
        f.write("```\n{}\n```\n".format(result.render()))

    print(result.render())
    print("elapsed: {:.1f}s".format(elapsed))
    print("report: {}".format(report_path))
    print("=== {} ===".format("PASS" if result.ok else "FAIL"))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
