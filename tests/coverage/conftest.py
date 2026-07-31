# -*- coding: utf-8 -*-
r"""U53 カバレッジ検査: フィクスチャ・CLIオプション・無人運転のための記録。

安全設計(tests\shipcheck と同じ流儀):
  --allow-convert  … 指定時のみ実変換(convert.ps1)を実行する。既定は SKIP
  --allow-machine  … 指定時のみ Palworld 実機へ接触する。既定は SKIP
どちらも既定 OFF なので、素で `pytest tests\coverage` を叩いても
実変換も実機接触も一切起きない(構造的な保証)。

無人運転(一晩)の要件:
  * 結果は **1件ごとに即座にファイルへ追記**する(途中で電源が落ちても分かる)
  * 1件の FAIL で全体を止めない(pytest の既定挙動。-x を付けないこと)
  * 変換は mutex 衝突時に自動リトライ(probes.run_convert)
  * 変換は 1本 60分でタイムアウト(必ず朝までに終わる)
"""
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)

for _p in (HERE, TESTS_DIR, os.path.join(TESTS_DIR, "shipcheck"),
           os.path.join(REPO_ROOT, "devtools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import probes  # noqa: E402
import matrix  # noqa: E402
import gates as shipcheck_gates  # noqa: E402
import report_merge  # noqa: E402 dev#127: xdist環境でのレポート集約
import shared_pytest_options  # noqa: E402 dev#320: --world等の重複登録防止

# 既存スイートのキャッシュ置き場(work\u32_diag\)へは書かない。
# 本タスクの作業域は work\u53_cov\ 配下だけ。
shipcheck_gates.CACHE_DIR = os.path.join(probes.WORK_ROOT, "pak_cache")
shipcheck_gates.JOBS_DIR = os.path.join(probes.WORK_ROOT, "jobs")


def pytest_addoption(parser):
    # dev#320: --allow-convert / --allow-machine / --run-dir / --world は
    # tests\shipcheck\conftest.py と意味が完全に重複しており、両ディレクトリを
    # 跨いで収集するとオプション名の二重登録でcollection errorになっていた。
    # shared_pytest_options.add_shared_options() へ一本化済み(詳細はそちらの
    # docstring、実測はwork\issue_zero\i320\NOTES.md)。ここではcoverage固有の
    # オプションのみ追加登録する。
    shared_pytest_options.add_shared_options(parser)
    parser.addoption("--allow-unity", action="store_true", default=False,
                     help=("安全弁: 指定時のみ Unity をヘッドレス起動して "
                           ".prefab を輸出する。**他人の Unity プロジェクトへ"
                           "書き込みが起きる**(Assets\\Editor\\ への Exporter 複製、"
                           "FBX Exporter 未導入なら manifest.json 追記)ので既定 OFF"))
    parser.addoption("--specimens", default="all",
                     help="入力形式軸で回す検体(all|fast|カンマ区切り名)")


def pytest_configure(config):
    config.addinivalue_line("markers", "machine: Palworld 実機への接触を伴う(既定で除外)")
    config.addinivalue_line("markers", "slow: 実変換を伴う(--allow-convert が要る)")
    config.addinivalue_line("markers",
                            "unity: Unity ヘッドレス起動を伴う(--allow-unity が要る)")
    config.addinivalue_line(
        "markers",
        "atlas_summary: dev#127 xdist対応。test_atlas_rows_coverage 専用。"
        "全specimenの実行結果を横断集計するため、並列実行(-n)時は"
        "run_overnight.py が本体フェーズの**後**に単独プロセスで走らせる"
        "(詳細は test_inputs.py::test_atlas_rows_coverage docstring)")

    # dev#127: xdist(-n)ワーカーかどうかをここで確定させる。
    # コントローラは config.workerinput を持たない(pytest-xdist の仕様、
    # 2026-07-29 実測で確認済み)。非xdist実行(-n無し)でもこの属性は無いので
    # worker_id は None になり、以下の分岐はすべて「今までどおり」の経路を通る。
    worker_id = None
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None:
        worker_id = workerinput.get("workerid")
    config._u53_worker_id = worker_id

    numprocesses = getattr(config.option, "numprocesses", None)
    try:
        report_merge.validate_run_dir_for_xdist(numprocesses, config.getoption("run_dir"))
    except ValueError as e:
        raise pytest.UsageError(str(e))

    run_dir = config.getoption("run_dir") or os.path.join(
        probes.REPORTS_DIR, time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    config._u53_run_dir = run_dir
    config._u53_started = time.time()

    # provenance.json は「今回の実行そのもの」の情報(git HEAD 等)であって
    # テスト結果を含まないので、二重書き込みを避けてコントローラ
    # (worker_id is None、非xdist実行時は唯一のプロセスそのもの)だけが書く。
    if worker_id is None:
        prov = shipcheck_gates.provenance_dict()
        prov["suite"] = "tests/coverage (U53)"
        prov["allow_convert"] = bool(config.getoption("allow_convert"))
        prov["allow_machine"] = bool(config.getoption("allow_machine"))
        prov["allow_unity"] = bool(config.getoption("allow_unity"))
        prov["xdist_numprocesses"] = numprocesses
        prov["argv"] = list(sys.argv)
        with open(os.path.join(run_dir, "provenance.json"), "w", encoding="utf-8") as f:
            json.dump(prov, f, ensure_ascii=False, indent=2)
        _append_progress(config, "=== 開始 {} ===".format(
            time.strftime("%Y-%m-%d %H:%M:%S")))
        _append_progress(config, "run_dir: {}".format(run_dir))
        _append_progress(config, "allow_convert={} allow_machine={} allow_unity={} "
                          "xdist_numprocesses={}".format(
                              prov["allow_convert"], prov["allow_machine"],
                              prov["allow_unity"], numprocesses))
    else:
        _append_progress(config, "=== worker {} 開始 {} ===".format(
            worker_id, time.strftime("%Y-%m-%d %H:%M:%S")))


def _worker_path(config, basename):
    run_dir = getattr(config, "_u53_run_dir", None)
    if not run_dir:
        return None
    worker_id = getattr(config, "_u53_worker_id", None)
    return os.path.join(run_dir, report_merge.worker_suffixed_name(basename, worker_id))


def _append_progress(config, line):
    """進行中ログ。**1行ごとに flush + fsync** する(途中で落ちても朝に読める)。

    dev#127: xdist ワーカーは自分専用のファイル(`progress.<workerid>.log`)へ
    書く(複数プロセスが同じファイルへ同時追記する事故を構造的に避けるため。
    relgate.py の BufferedReport と同じ思想をファイル分割で実現)。
    非xdist実行時は worker_id が None なので、従来どおり `progress.log` に
    直接書く(挙動不変)。
    """
    path = _worker_path(config, report_merge.PROGRESS_BASENAME)
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass


def _append_jsonl(config, name, row):
    path = _worker_path(config, name)
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass


def pytest_runtest_logreport(report):
    """テスト1件が終わるたびに即記録する(セッション終了を待たない)。"""
    if report.when != "call" and not (report.when == "setup" and report.outcome != "passed"):
        return
    config = getattr(report, "_u53_config", None) or _CURRENT["config"]
    if config is None:
        return
    elapsed = time.time() - getattr(config, "_u53_started", time.time())
    line = "[{:>7.0f}s] {:<7} {}".format(elapsed, report.outcome.upper(), report.nodeid)
    if report.outcome == "skipped" and report.longrepr:
        try:
            line += "  ({})".format(str(report.longrepr[2])[:200])
        except Exception:
            pass
    _append_progress(config, line)
    _append_jsonl(config, report_merge.TESTS_BASENAME, {
        "nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
        "duration_sec": round(report.duration, 2), "elapsed_sec": round(elapsed, 1),
        "longrepr": str(report.longrepr)[:4000] if report.outcome != "passed" else "",
    })


_CURRENT = {"config": None}


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    _CURRENT["config"] = session.config


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    run_dir = getattr(config, "_u53_run_dir", None)
    if not run_dir:
        return
    worker_id = getattr(config, "_u53_worker_id", None)
    if worker_id is not None:
        # dev#127: xdist ワーカーはレポートを生成しない。
        # 生成をワーカーごとに行うと report.md/coverage.md への書き込みが
        # 複数プロセスで競合するうえ、各ワーカーは「自分が実行した分」しか
        # 見えていないので、そもそも生成しても不完全なレポートにしかならない
        # (この事故を構造的に防ぐのが本WPの主眼)。集約と生成は必ず
        # コントローラ側(worker_id is None)に一本化する。
        _append_progress(config, "=== worker {} 終了 exitstatus={} {} ===".format(
            worker_id, exitstatus, time.strftime("%Y-%m-%d %H:%M:%S")))
        return

    # コントローラ(非xdist実行時は唯一のプロセスそのもの)。
    # dev#127: rows は config._u53_gate_rows という「このプロセスが直接
    # 記録した分」のプロセスローカル変数からではなく、**必ずファイルから**
    # 読み直す。理由は2つ:
    #   1) xdist コントローラは1件もテストを実行しないので、そもそも
    #      プロセスローカルな記録を持ち得ない(空リストになる)。
    #   2) 非xdist実行でも「ファイルから読む」に統一しておけば、
    #      xdist の有無で分岐するコードパスが1本減る
    #      (踏まれない分岐は事故の温床、というのがこのプロジェクトの経験則)。
    n_merged = report_merge.merge_worker_files(run_dir)
    if n_merged:
        _append_progress(config, "[xdist] ワーカー{}体分の gates.jsonl/tests.jsonl/"
                          "progress.log を集約した".format(n_merged))
    rows = report_merge.read_gate_rows(run_dir)
    try:
        import cov_report
        cov_report.write_reports(run_dir, rows, exitstatus)
    except Exception as e:
        _append_progress(config, "[WARN] レポート生成に失敗: {!r}".format(e))
    _append_progress(config, "=== 終了 exitstatus={} {} ===".format(
        exitstatus, time.strftime("%Y-%m-%d %H:%M:%S")))


# --- 基本フィクスチャ ---------------------------------------------------------

@pytest.fixture(scope="session")
def allow_convert(request):
    return request.config.getoption("allow_convert")


@pytest.fixture(scope="session")
def allow_machine(request):
    return request.config.getoption("allow_machine")


@pytest.fixture(scope="session")
def allow_unity(request):
    return request.config.getoption("allow_unity")


@pytest.fixture(scope="session")
def world_name(request):
    return request.config.getoption("world")


@pytest.fixture(scope="session")
def unity_export(request):
    r"""(case_name, prefab_specimen_key) -> (rc, stdout, unity_log, out_dir)。

    Unity ヘッドレス起動は1体あたり数分〜十数分かかるので、
    **セッション内で同じケースを二度輸出しない**(build フィクスチャと同じ流儀)。

    出力先は `work\u53_cov\exports\<case_name>\` に固定する。
    `export_from_unity.ps1` の既定(`work\<prefab名>_export`)には**任せない**
    ——既定は prefab のファイル名だけで決まるため、Agyo/Jinbe の flatVer2 同士が
    衝突し、さらに既存検体 `work\flatVer2_export` を上書きしてしまう。
    """
    cache = {}

    def _export(case_name, specimen_key):
        if case_name in cache:
            return cache[case_name]
        if not request.config.getoption("allow_unity"):
            pytest.skip("Unity ヘッドレス起動は --allow-unity 指定時のみ"
                        "(他人の Unity プロジェクトへ書き込みが起きるため)")
        spec = matrix.PREFAB_SPECIMENS[specimen_key]
        if not os.path.isfile(spec["path"]):
            pytest.skip("prefab 検体が無い: {}".format(spec["path"]))
        out_dir = os.path.join(probes.EXPORTS_DIR, case_name)
        _append_progress(request.config,
                         "    -> Unity 輸出開始 {} ({})".format(case_name, spec["path"]))
        t0 = time.time()
        rc, stdout, unity_log = probes.run_unity_export(spec["path"], out_dir)
        _append_progress(request.config, "    -> Unity 輸出終了 {} rc={} {:.0f}s".format(
            case_name, rc, time.time() - t0))
        cache[case_name] = (rc, stdout, unity_log, out_dir)
        return cache[case_name]

    return _export


@pytest.fixture(scope="session")
def run_dir(request):
    return request.config._u53_run_dir


class _Recorder:
    """ゲート判定を1件ずつ記録する。**判定と同時に**ファイルへ落とす。"""

    def __init__(self, config):
        self._config = config

    def record(self, gate_result, case=None, axis=None, extra=None):
        row = {
            "ts": time.strftime("%H:%M:%S"),
            "axis": axis,
            "case": case,
            "gate": gate_result.name,
            "status": gate_result.status,
            "detail": gate_result.detail,
        }
        if extra:
            row.update(extra)
        # dev#127: config._u53_gate_rows というプロセスローカルな二重保持は
        # 廃止した(gates.jsonl が唯一の正本。理由は pytest_sessionfinish の
        # コメント参照)。
        _append_jsonl(self._config, report_merge.GATES_BASENAME, row)
        _append_progress(self._config, "    -> {:<5} {} [{}]".format(
            gate_result.status, gate_result.name, case or ""))
        return gate_result


@pytest.fixture(scope="session")
def recorder(request):
    return _Recorder(request.config)


@pytest.fixture(scope="session")
def gate(recorder):
    """ゲート結果を記録し、FAIL なら assert で落とす薄いヘルパ。

    SKIP は pytest.skip に落とす(判定不能を PASS と混ぜない)。
    """
    def _check(gate_result, case=None, axis=None, hard=True):
        recorder.record(gate_result, case=case, axis=axis)
        if gate_result.status == "SKIP":
            pytest.skip("{}: {}".format(gate_result.name,
                                        gate_result.detail.get("note", "判定不能")))
        if hard:
            assert gate_result.status == "PASS", "{} FAIL: {}".format(
                gate_result.name,
                json.dumps(gate_result.detail, ensure_ascii=False, default=str)[:2000])
        return gate_result
    return _check


# --- job.json の生成(検体 × override → 独立した作業域) ------------------------
# 本体は matrix.make_job(テストモジュールから安全に import できるようにするため)。
make_job = matrix.make_job


@pytest.fixture(scope="session")
def build():
    """(case_name, specimen_key, overrides) -> PakBuildResult。

    shipcheck.gates.build_or_get_cached を **そのまま再利用**する
    (キャッシュ鍵 = job内容 + TEMPLATE_BUILD_VERSION + git HEAD)。
    変換の実体だけ probes.run_convert(mutex リトライ + タイムアウト)へ差し替える。
    セッション内は同じケースを二度ビルドしない。
    """
    cache = {}

    def _build(case_name, specimen_key, overrides=None, allow_convert=False,
               extra_args=(),
               path_override=None, humanoid_override=None):
        key = (case_name, json.dumps(overrides or {}, sort_keys=True),
               tuple(extra_args), path_override)
        if key in cache:
            return cache[key]
        # prefab 検体は Unity 輸出で生えた FBX(path_override)が本体なので、
        # 検体表の path(=.prefab)の存在確認はそちらに委ねる。
        spec = matrix.SPECIMENS.get(specimen_key) or matrix.PREFAB_SPECIMENS[specimen_key]
        src = path_override or spec["path"]
        if not os.path.isfile(src):
            pytest.skip("検体が無い: {}".format(src))
        job_path = make_job(case_name, specimen_key, overrides,
                            path_override=path_override,
                            humanoid_override=humanoid_override)
        import functools
        runner = functools.partial(probes.run_convert, extra_args=extra_args)
        try:
            res = shipcheck_gates.build_or_get_cached(
                case_name, job_path, overrides=None,
                allow_convert=allow_convert, run_conversion=runner)
        except shipcheck_gates.ConversionSkipped as e:
            pytest.skip(str(e))
        # 穴1修復(2026-07-26): build_or_get_cached が組み立てる log_path は
        # 実際に probes.run_convert が書く場所とズレており、2回目以降の
        # cache hit で log_text が空になり log 依存ゲートが黙って SKIP する
        # (詳細は probes.fix_stale_log_path のdocstring)。
        res = probes.fix_stale_log_path(res, case_name)
        cache[key] = res
        return res

    return _build
