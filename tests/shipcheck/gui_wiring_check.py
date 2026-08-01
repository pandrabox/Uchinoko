# -*- coding: utf-8 -*-
"""WP11(2026-07-27)発, dev#532 方針A WP-C2(2026-08-01)で全面書換: GUI配線契約テスト。

## 背景(WP11時点、旧版)
リリースゲート群(devtools\\release.py / ship_smoke.py)は完成しているが、
GUIの「フル変換」ボタンが実際に行う
    job.json生成(WriteJob) -> convert.ps1起動(BuildConvertScriptPath/BuildConvertArgs/FindPwsh)
という配線そのものは誰も検証していなかった。ship_smoke.pyのA3は「GUIが起動して
3.5秒落ちない」ことしか見ておらず、job.jsonの中身やconvert.ps1の起動コマンドは
一切見ていない。2026-07-26のcp932事故はまさにこの「GUI経由の起動」が引き金だった
(GUIがconvert.ps1をリダイレクト付きで起動する状況特有の不具合)。

旧版はクリック自動化が使えない制約から、C#実装(app\\DiveToPalworld.cs)に
`--emit-wiring`隠しCLIを追加し、csc.exeでビルドしたexeを起動して結果をファイルへ
書き出させる方式を取っていた。

## dev#532 方針A(GUI本体をtkinter/Pythonへ全面移植)後のこの版
GUI本体が `app_py\\pipeline_runner.py`(WP-A2、dev#532)へ移植されたことで、
「実際にGUIが呼ぶのと同じ関数」を**ビルドもCLI起動も経由せず直接import**して
呼べるようになった(DESIGN.md §0-1「Pythonへ移植すれば、ビルド→exe起動という
手順自体が丸ごと不要になる。これは移行のコストではなくボーナス」のとおり)。
検査対象は `pipeline_runner.write_job()` / `build_convert_script_path()` /
`build_convert_args()` / `find_pwsh()`(§2.1相当)。

## このスクリプトが検査すること
  a. job.jsonのスキーマ・必須キー(REQUIRED_TOP_KEYS / REQUIRED_PATHS_KEYS、根拠は
     下記「必須キーの根拠」)が欠けていないこと(値は検体依存で可)。
  a2. `engine_mode` が明示的に `"noue"` であること(dev#532 A2発進指示での裁定の
      固定化。旧C#実装のWriteJob()にはこのキーが無く、convert.ps1側のデフォルト
      採用で実害を吸収していたドリフトだったが〈DESIGN.md §2.1/§6-1〉、
      Python移植版(pipeline_runner.ENGINE_MODE)では明示的に書くと決まった)。
  b. 起動コマンドが実在する pipeline\\cli\\convert.ps1 を正しい絶対パスで指し、
     -File / -Job 引数が正しく渡っていること。
  c. 環境変数契約(PYTHONIOENCODING=utf-8 / PYTHONUTF8=1): `pipeline_runner.py`が
     これらの変数をos.environ経由で明示的にセット/上書きしていない(=convert.ps1
     の自己設定を阻害していない)こと、`subprocess.Popen`が`env=None`(親環境を
     そのまま継承)で子プロセスを起動する契約を保っていること、かつconvert.ps1側が
     実際にこの2行を無条件(コメントアウトされていない)で持っていること。
     責務分担の根拠は `check_env_contract()` のdocstring参照。

## 必須キーの根拠
- `pipeline\\cli\\convert.ps1` 冒頭のコメント(8行目):
      "前提: job.json(paths.blender_exe / vrm_addon_zip 必須)"
  さらに実装 (`$Blender = $cfg.paths.blender_exe` の直後で `Test-Path` チェックし
  無ければ即 `Write-Error` して `exit 1`) でも裏付けられている。
- `pipeline\\blender\\vp_bl.py::ensure_vrm_addon()` が
  `job["paths"].get("vrm_addon_zip")` を読む(VRMアドオン導入に必須)。
- `avatar_name` はconvert.ps1側にフォールバック既定があるが
  (`$Avatar = if ($cfg.avatar_name) {...} else {"Avatar"}`)、GUI(pipeline_runner.
  write_job)が常に明示出力する設計になっているため、GUIの契約としては必須キー
  として扱う(欠落=write_job()の退行を示すため)。
- dev#114(2026-07-29): UEパイプライン完全削除に伴い `paths.ue_project` /
  `paths.ue_root` はGUIが書かなくなった(convert.ps1は常にnoue専用)。
  `engine_mode`自体はdev#532 A2裁定で明示キーへ復活したためa2で別途検査する
  (REQUIRED_TOP_KEYSには含めない。値の中身まで固定するのはa2の役割にする設計
  分離)。
- `pipeline\\job.example.json`(CLI直接利用者向けの公式サンプル)も同じ
  `vrm_path` / `avatar_name` / `paths.blender_exe` / `paths.vrm_addon_zip` の
  組を必須級として提示している。

## mutation test(負の対照)の方式変更
旧版はC#ソース一式をコピーしてcsc.exeで再ビルドしていたが、Python移植後は
ビルド手順自体が不要になった(上記docstring参照)。本版は
`app_py\\pipeline_runner.py`(+同居する`i18n.py`/`i18n_data.json`/`settings.py`、
importに要る依存のみ)を一時ディレクトリへコピーし、コピーしたソースへ文字列
置換で変異を注入したうえで `importlib` 経由でモジュールとしてimportする。
**リポジトリ本体(`app_py\\`配下)は一切書き換えない。**

## 使い方
    python tests\\shipcheck\\gui_wiring_check.py [--work <dir>]
    python tests\\shipcheck\\gui_wiring_check.py --mutate missing_key   # 負の対照
    python tests\\shipcheck\\gui_wiring_check.py --mutate broken_path   # 負の対照

--work省略時は `work\\relgate\\wp11\\gui_wiring_check_<timestamp>\\`
(ship_smoke.py組み込み時(gate_a8_gui_wiring)もこの既定を使い、ship_smoke.py自身の
--workは無視する——detail参照。この呼び出しインターフェース(`run_check(work_dir,
mutation_key=None)`が`.ok`/`.render()`を持つResultを返す、`default_work_root()`)は
WP-C1(ship_smoke.py)側の依存契約なので変更していない)。

終了コード: 全項目PASSなら0、1つでもFAILなら1。fail-closed
(import失敗・emit失敗・キー欠落は全て赤)。
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")
CONVERT_PS1_REL = os.path.join("pipeline", "cli", "convert.ps1")

REQUIRED_TOP_KEYS = ["vrm_path", "avatar_name", "paths"]
REQUIRED_PATHS_KEYS = ["blender_exe", "vrm_addon_zip"]
EXPECTED_ENGINE_MODE = "noue"

# importのために一緒にコピーする必要がある同居モジュール(pipeline_runner.py
# 自身のsys.path.insert(0, 自分のディレクトリ)がこれらを解決する対象)。
_SIDECAR_FILES = ("i18n.py", "i18n_data.json", "settings.py")

# 負の対照用の変異定義。app_py\pipeline_runner.py本体は変異させず、work配下に
# コピーしたファイルに対してのみ適用する(禁則: 本体ソースの変異)。
MUTATIONS = {
    "missing_key": {
        "desc": "job.jsonの必須キー(avatar_name)を書かせない変異(write_job内の1行を削除)",
        "find": '        "avatar_name": name,\n',
        "replace": "",
    },
    "broken_path": {
        "desc": "convert.ps1のパスを壊す変異(build_convert_script_pathが別ファイル名を指すようにする)",
        "find": (
            '    return os.path.join(app_root, "pipeline", "cli", "convert.ps1")\n'
        ),
        "replace": (
            '    return os.path.join(app_root, "pipeline", "cli", '
            '"convert_BROKEN_PATH_NEGATIVE_CONTROL.ps1")\n'
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


# --- pipeline_runnerモジュールの用意(通常/負の対照) -----------------------------

def _load_pipeline_runner(work_dir, mutation_key=None):
    """検査対象の pipeline_runner モジュールをロードして返す。

    mutation_key が None なら app_py\\pipeline_runner.py を直接import(変異なし)。
    mutation_key が指定されていれば、work_dir\\src_under_test_<key>\\ へ
    pipeline_runner.py + 同居モジュール一式をコピーし、pipeline_runner.py にだけ
    文字列置換で変異を適用してから importlib 経由でロードする。app_py\\本体は
    一切書き換えない。
    戻り値: (module, note)
    """
    if mutation_key is None:
        if APP_PY_DIR not in sys.path:
            sys.path.insert(0, APP_PY_DIR)
        import pipeline_runner  # type: ignore
        return pipeline_runner, "本体(app_py\\pipeline_runner.py)を直接import(変異なし)"

    if mutation_key not in MUTATIONS:
        raise ValueError("未知のmutation_key: {}".format(mutation_key))

    src_root = os.path.join(work_dir, "src_under_test_" + mutation_key)
    if os.path.isdir(src_root):
        shutil.rmtree(src_root)
    os.makedirs(src_root, exist_ok=True)

    for fn in _SIDECAR_FILES:
        shutil.copy2(os.path.join(APP_PY_DIR, fn), os.path.join(src_root, fn))

    pr_src_path = os.path.join(APP_PY_DIR, "pipeline_runner.py")
    with open(pr_src_path, encoding="utf-8") as f:
        pr_text = f.read()
    mut = MUTATIONS[mutation_key]
    if mut["find"] not in pr_text:
        raise RuntimeError(
            "変異対象の文字列が現行ソースに見つからない(ソース側の変更で"
            "ズレた可能性): {!r}".format(mut["find"][:120]))
    mutated_text = pr_text.replace(mut["find"], mut["replace"], 1)
    if mutated_text == pr_text:
        raise RuntimeError("変異が適用されなかった(置換前後で同一)")

    mutated_path = os.path.join(src_root, "pipeline_runner.py")
    with open(mutated_path, "w", encoding="utf-8") as f:
        f.write(mutated_text)

    mod_name = "gui_wiring_check_mutant_{}_{}".format(mutation_key, id(work_dir))
    spec = importlib.util.spec_from_file_location(mod_name, mutated_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module, "変異適用: {} ({})".format(mutation_key, mut["desc"])


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


def check_engine_mode(job):
    """dev#532 A2裁定の固定化: engine_modeが明示的に'noue'であること。
    戻り値: (ok, detail)"""
    value = job.get("engine_mode")
    ok = value == EXPECTED_ENGINE_MODE
    detail = ("OK: engine_mode={!r}".format(value) if ok else
              "engine_modeが期待値と不一致(欠落含む): 実際={!r} 期待={!r}".format(
                  value, EXPECTED_ENGINE_MODE))
    return ok, detail


# --- (b) 起動コマンド検査 -------------------------------------------------------

_ARGS_RE = re.compile(
    r'^-NoProfile -ExecutionPolicy Bypass -File "([^"]+)" -Job "([^"]+)"'
)


def check_launch_command(script, shell, args, expected_convert_ps1, job_json_path):
    """起動コマンドが実在するconvert.ps1を正しいパスで指し、-File/-Jobが
    正しく渡っていることを検査する。戻り値: (ok, detail)

    expected_convert_ps1は検査対象モジュールを一切経由せず、このテスト自身が
    REPO_ROOTから独立に組み立てた期待値(build_convert_script_pathの結果を
    そのまま期待値に使うと、broken_path変異のような自己欺瞞的なPASSを生む)。
    """
    problems = []

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
_OS_ENVIRON_ASSIGN_RE = re.compile(
    r'os\.environ\[\s*["\'](PYTHONIOENCODING|PYTHONUTF8)["\']\s*\]\s*='
)


def check_env_contract(pipeline_runner_path, convert_ps1_path):
    """PYTHONIOENCODING=utf-8 / PYTHONUTF8=1 の責務分担契約を検査する。

    設計: convert.ps1が自分の子プロセス全部に効くよう冒頭で無条件に
    `$env:PYTHONIOENCODING = "utf-8"` / `$env:PYTHONUTF8 = "1"` を設定する
    (2026-07-26 cp932事故の修正、ship_smoke.py A6が実行時の効果を別途検証済み)。
    pipeline_runner.py(旧GUI側)はconvert.ps1を子プロセスとして起動する側であり、
    `subprocess.Popen(..., env=None)`で親プロセスの環境をそのまま継承させるだけで、
    convert.ps1がその後自分のプロセス内で`$env:...=`する値を上書き・阻害する
    余地が構造的に無い設計(旧C#実装のProcessStartInfo.EnvironmentVariables
    無操作方針を1:1で踏襲)。したがってこのゲートが守るのは
    「pipeline_runner.py側がこの2変数をos.environ経由で明示指定して
    convert.ps1の自己設定と競合する上書きをしていないこと」+
    「Popen呼び出しがenv=Noneで契約どおり親環境を継承していること」+
    「convert.ps1側が実際にこの2行を(コメントアウトせず)持っていること」の
    三点。どれか1つが崩れても検出できる。
    戻り値: (ok, detail)
    """
    problems = []
    try:
        with open(pipeline_runner_path, encoding="utf-8") as f:
            py_text = f.read()
    except Exception as e:
        return False, "pipeline_runner.py読み込み失敗: {}".format(e)

    if _OS_ENVIRON_ASSIGN_RE.search(py_text):
        problems.append(
            "pipeline_runner.py側がos.environ[...]でPYTHONIOENCODING/PYTHONUTF8を"
            "明示操作している形跡がある。convert.ps1の自己設定と食い違う値で"
            "上書きしていないか個別に確認すること(現行設計は無関与のはずで、"
            "これが出たら退行の疑い)。")
    if "env=None" not in py_text:
        problems.append(
            "subprocess.Popen(..., env=None)相当の記述が見当たらない"
            "(親環境をそのまま継承する契約が崩れている可能性)。")

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
        module, note = _load_pipeline_runner(work_dir, mutation_key)
        r.add("0_module_loaded", True, note)
    except Exception:
        r.add("0_module_loaded", False, traceback.format_exc())
        return r

    emit_dir = os.path.join(work_dir, "emit_out")
    if os.path.isdir(emit_dir):
        shutil.rmtree(emit_dir)
    os.makedirs(emit_dir, exist_ok=True)
    work_root = os.path.join(emit_dir, "work")
    os.makedirs(work_root, exist_ok=True)

    # write_job()はファイル実在を要求しない(ファイル名からavatar_nameを作る
    # だけ)ため、空ファイルのフィクスチャで足りる。
    fixture_vrm = os.path.join(emit_dir, "FixtureAvatar.vrm")
    with open(fixture_vrm, "wb"):
        pass

    try:
        job_json_path = module.write_job(REPO_ROOT, work_root, fixture_vrm)
        r.add("1_write_job", True, "job.json: {}".format(job_json_path))
    except Exception:
        r.add("1_write_job", False, traceback.format_exc())
        return r

    try:
        with open(job_json_path, encoding="utf-8") as f:
            job = json.load(f)
        r.add("2_job_json_readable", True)
    except Exception:
        r.add("2_job_json_readable", False, traceback.format_exc())
        return r

    ok, detail = check_job_schema(job)
    r.add("a_job_schema", ok, detail)

    ok, detail = check_engine_mode(job)
    r.add("a2_engine_mode_noue", ok, detail)

    try:
        script = module.build_convert_script_path(REPO_ROOT)
        args = module.build_convert_args(script, job_json_path)
        shell = module.find_pwsh()
        r.add("3_build_launch_command", True,
              "script={} shell={} args={}".format(script, shell, args))
    except Exception:
        r.add("3_build_launch_command", False, traceback.format_exc())
        return r

    expected_convert_ps1 = os.path.join(REPO_ROOT, CONVERT_PS1_REL)
    ok, detail = check_launch_command(script, shell, args, expected_convert_ps1, job_json_path)
    r.add("b_launch_command", ok, detail)

    ok, detail = check_env_contract(module.__file__, expected_convert_ps1)
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
