# -*- coding: utf-8 -*-
r"""U53 カバレッジ検査を無人で一晩回す(dev#127: 並列化版)。

`run_overnight.ps1` から呼ばれる本体(ps1側は薄い殻。CLAUDE.md言語方針
「新規コードは迷ったらPython」に従い、ロジックはこちらへ移した)。

## 並列化の設計(dev#127)

`tests\coverage` の実変換テスト(15本前後)は検体ごとに独立した作業フォルダ
(`work\u53_cov\cases\<case_name>\`、matrix.make_job 参照)を持つため、
理論上は pytest-xdist(`-n`)で並列に流せる(relgate.py WP15 が同じ構造で
3検体直列12分→並列約6分を実測済み)。ただし調査(work\rd_121\PROPOSAL.md、
dev#127本体の実装で追加調査)の結果、2つの構造的な罠が見つかっている:

  1. **test_atlas_rows_coverage は「全specimenの横断集計」**であり、
     specimen群の実行が終わるまで正しい答えが出せない
     (test_inputs.py 側 docstring 参照)。
  2. **一部のテストはモジュールをまたいで case_name(作業フォルダ)を
     意図的に共有している**(test_settings.py の flip_baseline 系、
     test_inputs.py::test_input_format[vrm_seed] との共有、
     test_prefab.py の同名衝突ペア等)。素の pytest-xdist は個々の
     テスト関数/パラメータをワーカーへ自由に振り分けるため、共有元が
     別ワーカーに散ると**同じ作業フォルダへ複数プロセスが同時に書き込む**
     (CLAUDE.md「作業フォルダの指定を省くと競合が復活する」と同型の事故)。

対策として、tests\coverage 側に以下を実装済み:

  * 罠1 → `atlas_summary` マーカーを新設し、本体フェーズ(フェーズA)から
    除外。**フェーズAの完走後に単独プロセスとして再実行**する(フェーズB)。
  * 罠2 → 衝突しうるテスト群を `xdist_group` マーカーで同一ワーカーへ固定
    (test_settings.py / test_prefab.py / test_machine_coverage.py の
    モジュール冒頭コメント参照)。衝突しない検体(test_input_format の
    vrm_seed 以外の7体等)は無指定のまま=自由に並列化される。

--Machine / --Unity 指定時は、machine/prefab 系テストが**モジュールを
またいで** case_name を共有しており(test_machine_coverage.py 冒頭コメント
参照)、xdist_group ではモジュール間の競合までは防げないため、
**並列そのものを無効化**する(常に直列。安全側に倒す)。
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)

DEFAULT_WORKERS = 3
WORKERS_ENV_VAR = "D2P_COVERAGE_WORKERS"


def resolve_workers(cli_workers):
    r"""並列度を決める。優先順位: CLI引数 > 環境変数 > 既定値3。

    (dev#127「並列度は既定 -n 3 相当+環境変数上書き」)
    不正な環境変数値(数字でない/0以下)は既定値へフォールバックする
    (無人運転が起動時の設定ミスで落ちないように)。
    """
    if cli_workers is not None:
        return cli_workers
    v = os.environ.get(WORKERS_ENV_VAR)
    if v:
        try:
            n = int(v)
            if n > 0:
                return n
        except ValueError:
            pass
    return DEFAULT_WORKERS


def xdist_available():
    try:
        import xdist  # noqa: F401
    except ImportError:
        return False
    return True


def marker_expr_phase_a(machine):
    r"""フェーズA(本体)の `-m` 式。既存 addopts の `-m "not machine"` を
    後勝ちで上書きしつつ、常に atlas_summary(罠1)を除外する。"""
    base = "(machine or not machine)" if machine else "not machine"
    return "{} and not atlas_summary".format(base)


def build_phase_args(suite_dir, run_dir, specimens, machine, unity, workers):
    r"""(phase_a_args, phase_b_args, parallel_enabled) を組み立てる。

    **サブプロセスを一切呼ばない純粋関数**(テストしやすくするため実行本体
    `_run_pytest_phase`/`main` から分離してある)。
    """
    common = [suite_dir, "--run-dir", run_dir, "-v",
              "--allow-convert", "--specimens", specimens]
    if unity:
        common = common + ["--allow-unity"]

    # dev#127: 罠2(モジュールをまたぐ case_name 共有)への安全策として、
    # --Machine/--Unity 指定時は並列を無効化する(test_machine_coverage.py
    # 冒頭コメント参照)。既定(どちらも無し)のときだけ並列化する。
    parallel = bool(workers) and workers > 1 and not machine and not unity

    phase_a = list(common) + ["-m", marker_expr_phase_a(machine)]
    if machine:
        phase_a += ["--allow-machine"]
    if parallel:
        phase_a += ["-n", str(workers), "--dist", "loadgroup"]

    # フェーズB: 罠1対策。atlas_summary 単独、常に直列(-n 無し)。
    # フェーズAの pytest_sessionfinish(conftest.py)が gates.jsonl を
    # 既に集約済みなので、フェーズBはただそれを読むだけで正しい答えが出る。
    phase_b = list(common) + ["-m", "atlas_summary"]
    if machine:
        phase_b += ["--allow-machine"]

    return phase_a, phase_b, parallel


def _run_pytest_phase(pyargs, stdout_path, mode):
    r"""`python -m pytest <pyargs>` をサブプロセスで実行し、標準出力を
    コンソールへ流しつつ stdout_path へも書く(ps1版の Tee-Object と同じ
    役割)。戻り値: returncode。"""
    cmd = [sys.executable, "-m", "pytest"] + pyargs
    print("cmd     : {}".format(" ".join(cmd)))
    with open(stdout_path, mode, encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        for line in proc.stdout:
            print(line, end="")
            logf.write(line)
        proc.wait()
        return proc.returncode


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="U53 カバレッジ検査を無人で一晩回す(dev#127並列化版)")
    parser.add_argument("--machine", action="store_true",
                        help="実機ゲート(E: クラッシュ / F: プレイ開始)も回す。既定OFF")
    parser.add_argument("--unity", action="store_true",
                        help="prefab検体をUnityヘッドレスで輸出して端から端まで通す。既定OFF")
    parser.add_argument("--specimens", default="all",
                        help="入力形式軸で回す検体(all|fast|カンマ区切り、既定all)")
    parser.add_argument("--selftest-only", action="store_true",
                        help="負の対照(モック自己検証)だけを回す")
    parser.add_argument("--workers", type=int, default=None,
                        help="並列度(既定: 環境変数{}、無指定なら{})".format(
                            WORKERS_ENV_VAR, DEFAULT_WORKERS))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    suite_dir = HERE
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(REPO_ROOT, "work", "u53_cov", "reports", stamp)
    os.makedirs(run_dir, exist_ok=True)
    stdout_path = os.path.join(run_dir, "pytest_stdout.log")

    print("=== U53 カバレッジ検査(dev#127並列化版) ===")
    print("run_dir : {}".format(run_dir))
    print("")
    print("進行は次のファイルで追える(別ウィンドウで):")
    print("  Get-Content -Wait '{}'".format(os.path.join(run_dir, "progress.log")))
    print("  (並列実行中はワーカーごとに progress.<workerid>.log にも出る)")
    print("")

    if args.selftest_only:
        pyargs = [os.path.join(suite_dir, "selftest"), "--run-dir", run_dir, "-v"]
        code = _run_pytest_phase(pyargs, stdout_path, mode="w")
        print("\n=== 終了 (pytest exit={}) ===".format(code))
        return code

    workers = resolve_workers(args.workers)
    if workers > 1 and not args.machine and not args.unity and not xdist_available():
        print("[WARN] pytest-xdist が見つからないため並列化を無効化する"
              "(`pip install pytest-xdist` で有効化できる)。直列で続行する。")
        workers = 1

    phase_a, phase_b, parallel = build_phase_args(
        suite_dir, run_dir, args.specimens, args.machine, args.unity, workers)

    print("実機接触: {}".format("**あり**" if args.machine else "なし(既定)"))
    print("Unity起動: {}".format("**あり**(prefab 4体。プロジェクトを閉じておくこと)"
                                 if args.unity else "なし(既定)"))
    print("並列度  : {}".format(
        "{}並列(-n {} --dist loadgroup)".format(workers, workers) if parallel
        else "直列(--machine/--unity指定 または workers<=1)"))
    print("")

    t0 = time.time()
    code_a = _run_pytest_phase(phase_a, stdout_path, mode="w")
    print("\n--- フェーズA終了 exit={} ({:.0f}秒)。"
          "フェーズB(atlas_rows_coverage集計)へ ---\n".format(code_a, time.time() - t0))
    code_b = _run_pytest_phase(phase_b, stdout_path, mode="a")

    code = code_a if code_a != 0 else code_b
    print("\n=== 終了 (phaseA={} phaseB={} 総合={}, {:.0f}秒) ===".format(
        code_a, code_b, code, time.time() - t0))
    print("レポート: {}".format(os.path.join(run_dir, "report.md")))
    print("カバー表: {}".format(os.path.join(run_dir, "coverage.md")))
    return code


if __name__ == "__main__":
    sys.exit(main())
