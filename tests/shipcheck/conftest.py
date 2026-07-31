# -*- coding: utf-8 -*-
"""U32出荷検査スイート: フィクスチャとCLIオプション。

安全設計(2026-07-25、U31との並列制約に対応): 実変換(--allow-convert)・
実機接触(--allow-machine)はいずれも既定OFF。指定しない限り、変換キャッシュが
無ければ該当ケースはSKIPし、@machineテストは理由付きでSKIPする。これは
本タスク自身の「実機・変換に触れない」制約を、コード側でも構造的に保証する。
"""
import contextlib
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
if DEVTOOLS_DIR not in sys.path:
    sys.path.insert(0, DEVTOOLS_DIR)

for _p in (HERE, TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import gates  # noqa: E402
import cases  # noqa: E402
import shared_pytest_options  # noqa: E402 dev#320: --world等の重複登録防止


def pytest_addoption(parser):
    # dev#320: --world / --allow-convert / --allow-machine / --run-dir は
    # tests\coverage\conftest.py と意味が完全に重複しており、両ディレクトリを
    # 跨いで収集するとオプション名の二重登録でcollection errorになっていた。
    # shared_pytest_options.add_shared_options() へ一本化済み(詳細はそちらの
    # docstring、実測はwork\issue_zero\i320\NOTES.md)。ここではshipcheck固有の
    # オプションのみ追加登録する。
    shared_pytest_options.add_shared_options(parser)
    parser.addoption("--avatars", default="smoke",
                      help="smoke|all|corpus|カンマ区切り名前リスト(既定smoke=toto1体)")
    parser.addoption("--repeat", type=int, default=1,
                      help="statsプロファイル用: ゲートFの繰り返し回数(既定1)")
    parser.addoption("--shots-dir", default=None, help="SS保存先(既定: 実行レポートディレクトリ配下)")
    parser.addoption("--target-root", default=None,
                      help="配布zip展開先など、本リポジトリ以外のpipeline\\cli\\convert.ps1を"
                           "被検体として叩く場合のルートパス(2026-07-25ぱん裁定: 最終出荷検査は"
                           "このオプションで隔離ディレクトリを指定するのが本番運用。既定None=本リポジトリ自身。"
                           "ハーネス〈テストコード・job.json〉は常に本リポジトリのまま)")


def pytest_configure(config):
    config.addinivalue_line("markers", "machine: 実機(Palworld)への接触を伴うゲート(E/F)")
    config.addinivalue_line("markers", "visual: 見た目の一次判定(advisory、G)。FAILでもスイートは止めない")

    run_dir = config.getoption("run_dir")
    if not run_dir:
        # 書き込み許可(docs\U32_SONNET_INSTRUCTIONS.md 3節)がwork\u32_diag\配下に
        # 限定されているため、既定のレポート出力先もそこへ収める(枠内判断。
        # 4節仕様書の例示パスwork\shipcheck_reportsそのものを使いたい場合は
        # --run-dirで明示指定すればよい)
        ts = time.strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(REPO_ROOT, "work", "u32_diag", "shipcheck_reports", ts)
    os.makedirs(run_dir, exist_ok=True)
    config._shipcheck_run_dir = run_dir
    config._shipcheck_results = []

    prov = gates.provenance_dict(target_root=config.getoption("target_root"))
    with open(os.path.join(run_dir, "provenance.json"), "w", encoding="utf-8") as f:
        json.dump(prov, f, ensure_ascii=False, indent=2)


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    run_dir = getattr(config, "_shipcheck_run_dir", None)
    results = getattr(config, "_shipcheck_results", [])
    if not run_dir:
        return
    results_path = os.path.join(run_dir, "results.jsonl")
    with open(results_path, "w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    import report as report_mod
    try:
        report_mod.generate(run_dir)
    except Exception as e:  # レポート生成の失敗でテスト結果自体を握り潰さない
        print("[shipcheck] report.generate failed: {}".format(e), file=sys.stderr)


# --- CLIオプション読み出し用フィクスチャ -------------------------------------

@pytest.fixture(scope="session")
def target_root(request):
    return request.config.getoption("target_root")


@pytest.fixture(scope="session")
def allow_convert(request):
    return request.config.getoption("allow_convert")


@pytest.fixture(scope="session")
def allow_machine(request):
    return request.config.getoption("allow_machine")


@pytest.fixture(scope="session")
def repeat_count(request):
    return request.config.getoption("repeat")


@pytest.fixture(scope="session")
def world_name(request):
    return request.config.getoption("world")


@pytest.fixture(scope="session")
def run_dir(request):
    return request.config._shipcheck_run_dir


@pytest.fixture(scope="session")
def shots_dir(request, run_dir):
    opt = request.config.getoption("shots_dir")
    d = opt or os.path.join(run_dir, "shots")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def provenance(target_root):
    return gates.provenance_dict(target_root=target_root)


class _Recorder:
    def __init__(self, config):
        self._config = config

    def record(self, gate_result, avatar=None, case=None, extra=None):
        row = {
            "status": gate_result.status,
            "gate": gate_result.name,
            "avatar": avatar,
            "case": case,
            "detail": gate_result.detail,
        }
        if extra:
            row.update(extra)
        self._config._shipcheck_results.append(row)
        return gate_result


@pytest.fixture(scope="session")
def recorder(request):
    return _Recorder(request.config)


# --- アバター選択(データ駆動の中心) -----------------------------------------

def _resolve_avatar_names(spec):
    if not spec or spec == "smoke":
        return list(cases.SMOKE_AVATARS)
    if spec == "all":
        return list(cases.FULL_AVATARS)
    if spec == "corpus":
        return [cases.corpus_case_name(f) for f in cases.corpus_vrm_files()]
    return [s.strip() for s in spec.split(",") if s.strip()]


def pytest_generate_tests(metafunc):
    if "avatar" in metafunc.fixturenames:
        spec = metafunc.config.getoption("avatars")
        names = _resolve_avatar_names(spec)
        if not names:
            names = ["_no_avatar_selected"]
        metafunc.parametrize("avatar", names, ids=names)


@pytest.fixture
def job_path(avatar):
    """avatar名からjob.jsonパスを解決する。corpus由来(corpus_接頭辞)は
    devtools\\assets_tmpl相当の自動生成ヘルパでu32_diag配下に作る(U27統合分)。"""
    if avatar.startswith("corpus_"):
        return _ensure_corpus_job(avatar)
    p = os.path.join(REPO_ROOT, "work", avatar, "job.json")
    if not os.path.isfile(p):
        pytest.skip("job.jsonが無い: {}".format(p))
    return p


def _default_blender_exe():
    import glob
    hits = glob.glob(os.path.join(REPO_ROOT, "tools", "blender-*-windows-x64", "blender.exe"))
    if hits:
        return hits[0]
    fallback = r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe"
    return fallback if os.path.isfile(fallback) else None


def _default_addon_zip():
    import glob
    hits = glob.glob(os.path.join(REPO_ROOT, "third_party", "VRM_Addon_for_Blender-Extension*.zip"))
    return hits[0] if hits else None


def _ensure_corpus_job(case_name):
    """test\\vrm\\collected 由来のcorpusケース用に、最小限のjob.jsonを組み立てる
    (pipeline\\cli\\smoke_all.ps1のjob辞書パターンをPython側で再現。docs\\TODO.md
    「U27起票予定→U32のcorpusプロファイルへ統合」で要求された自動生成ヘルパ)。"""
    vrm_files = {cases.corpus_case_name(f): f for f in cases.corpus_vrm_files()}
    if case_name not in vrm_files:
        pytest.skip("corpusケースが見つからない: {}".format(case_name))
    vrm_filename = vrm_files[case_name]
    job_dir = os.path.join(REPO_ROOT, "work", "u32_diag", "corpus_jobs", case_name)
    os.makedirs(job_dir, exist_ok=True)
    job_path_ = os.path.join(job_dir, "job.json")
    blender_exe = _default_blender_exe()
    addon_zip = _default_addon_zip()
    if os.path.isfile(job_path_):
        return job_path_
    job = {
        "vrm_path": os.path.join(cases.CORPUS_DIR, vrm_filename),
        "avatar_name": case_name,
        "shoulder_offset_deg": 0.0,
        "merge_fingers": False,
        "unlit": False,
        "shadow_lift": 0.0,
        "force_two_sided": True,
        "license_confirmed": True,
        "paths": {
            "blender_exe": blender_exe,
            "vrm_addon_zip": addon_zip,
        },
    }
    with open(job_path_, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    return job_path_


# --- pakビルド(キャッシュ必須フィクスチャ) -----------------------------------

@pytest.fixture
def pak_for(allow_convert, target_root):
    def _factory(avatar, job_path_, overrides=None):
        try:
            return gates.build_or_get_cached(avatar, job_path_, overrides=overrides,
                                              allow_convert=allow_convert,
                                              target_root=target_root)
        except gates.ConversionSkipped as e:
            pytest.skip(str(e))
    return _factory


# --- 実機フィクスチャ(gameの適用/撤去を保証するcontext) -----------------------

@pytest.fixture
def game(allow_machine):
    """pak適用→(withブロック内でテスト)→撤去、を例外時も保証するcontext manager。
    apply_test_pak.pyの既存apply/remove処理をそのまま再利用する(無改変)。"""
    import apply_test_pak as atp

    @contextlib.contextmanager
    def _cm(pak_path, paks_dir=None):
        if not allow_machine:
            pytest.skip("実機接触には--allow-machineが必要(既定は禁止、安全のため)")
        paks_dir = paks_dir or atp.default_paks_dir()  # WP16: 決め打ちC:でなく自動探索
        candidates = atp.find_candidates()
        rc = atp.cmd_apply(paks_dir, candidates, pak_path)
        if rc != 0:
            pytest.fail("pak適用に失敗しました: {}".format(pak_path))
        try:
            yield pak_path
        finally:
            atp.cmd_remove(paks_dir)

    return _cm


# --- save_guard(実プレイセーブ保護。ModTestはno-op) ---------------------------

@pytest.fixture
def save_guard(world_name):
    """実プレイセーブ(「ぱんわーるど」等)使用時のバックアップ→整合検証→リストアを
    保証するcontext manager。ModTest(既定)ではno-op(U31指示書の聖域4手順の
    コード化。バックアップ先はwork\\u32_diag\\save_backups\\)。"""
    @contextlib.contextmanager
    def _cm():
        if world_name == "modtest":
            yield
            return
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            pytest.skip("LOCALAPPDATAが取得できずsave_guardを構成できない")
        save_root = os.path.join(local_appdata, "Pal", "Saved", "SaveGames")
        if not os.path.isdir(save_root):
            pytest.skip("セーブフォルダが無い: {}".format(save_root))
        backup_root = os.path.join(REPO_ROOT, "work", "u32_diag", "save_backups",
                                    time.strftime("%Y%m%d_%H%M%S"))
        import shutil
        shutil.copytree(save_root, backup_root)
        n_before = sum(len(files) for _, _, files in os.walk(backup_root))
        try:
            yield
        finally:
            n_after = sum(len(files) for _, _, files in os.walk(save_root))
            shutil.rmtree(save_root, ignore_errors=True)
            shutil.copytree(backup_root, save_root)
            if n_after < n_before:
                print("[shipcheck] save_guard: リストア前にファイル数減少を検知"
                      "({} -> {})。リストア実行済み".format(n_before, n_after), file=sys.stderr)
    return _cm
