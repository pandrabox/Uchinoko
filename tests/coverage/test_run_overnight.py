# -*- coding: utf-8 -*-
r"""dev#127(夜間カバレッジの並列化): ランナーのロジック単体試験。

CLAUDE.md「受入試験はリリースゲートに任せる」節の例外条件
(「そのWPが意図的に変換結果を変える」場合のみ実変換で検証する)には
当たらない——本WPは判定ロジックそのものは変えず、実行の並べ方だけを
変える。したがってここでは**実変換・実機・Unityを一切起動せず**、
以下だけを検査する(dev#127本文の要求どおり):

  1. 検体→作業フォルダ割当の互いに素性
     (「ばらまいてよい」検体と「同じワーカーへ固定しないと事故る」検体の
     分類が、実装(xdist_group マーキング)と一致しているか)
  2. 失敗集約(report_merge: ワーカー別ファイル→正規ファイルへの集約が
     可逆・完全であること)
  3. 並列度制御(run_overnight.resolve_workers / build_phase_args)

実際に pytest-xdist を起動して静的検査(--allow-convert 無し、実変換ゼロ)を
並列実行し、直列実行と判定件数が完全一致することの実測は
`work\rdp_127\evidence\` に記録してある(本ファイルは実測の代わりではなく、
ロジックそのものの回帰検知)。
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import matrix  # noqa: E402
import report_merge  # noqa: E402
import run_overnight  # noqa: E402
import test_inputs  # noqa: E402
import test_settings  # noqa: E402
import test_prefab  # noqa: E402
import test_machine_coverage  # noqa: E402


# ---------------------------------------------------------------------------
# 1) 検体→作業フォルダ割当の互いに素性
# ---------------------------------------------------------------------------

def _module_xdist_group_names(module):
    """モジュールの pytestmark から xdist_group のグループ名集合を返す
    (pytestmark は単体の MarkDecorator の場合とリストの場合がある)。"""
    marks = getattr(module, "pytestmark", [])
    if not isinstance(marks, (list, tuple)):
        marks = [marks]
    names = set()
    for m in marks:
        if m.name == "xdist_group":
            names.add(m.args[0])
    return names


def test_settings_module_is_grouped():
    r"""test_settings.py は flip_baseline / flip_shadow_lift_0to07 という
    case_name を複数テスト関数(test_setting_flip の各パラメータ・
    test_exclusions_untouched・test_materials_only_equivalence)が
    意図的に使い回す(build() のディスクキャッシュ共有)。xdist_group で
    モジュール全体を単一ワーカーへ固定していなければ、pytest-xdist 下で
    複数プロセスが同じ作業フォルダへ同時書き込みする(CLAUDE.md「作業
    フォルダの指定を省くと競合が復活する」と同型の事故)。"""
    groups = _module_xdist_group_names(test_settings)
    assert groups, "test_settings.py に xdist_group が付いていない"


def test_prefab_module_is_grouped():
    """test_prefab.py の同名衝突ペア(prefab_flatver2_agyo/jinbe)も同じ理由で
    グルーピングが要る(--allow-unity 使用時)。"""
    groups = _module_xdist_group_names(test_prefab)
    assert groups


def test_machine_module_is_grouped():
    """test_machine_coverage.py は pytestmark がリスト
    ([pytest.mark.machine, pytest.mark.xdist_group(...)])になっている。
    machine マーカーが消えていないこと(既定除外が壊れていないこと)も
    合わせて確認する。"""
    marks = test_machine_coverage.pytestmark
    assert isinstance(marks, list), "machine + xdist_group の両方が必要"
    names = {m.name for m in marks}
    assert "machine" in names, "既定除外(-m not machine)が効かなくなる"
    assert "xdist_group" in names


def test_vrm_seed_specimen_joins_settings_group():
    r"""test_inputs.py::test_input_format[vrm_seed] は case_name="input_vrm_seed"
    を test_settings.py::test_drop_bones_seed_robo_arm と共有する
    (両者とも同じ job.json を指す)。この1検体だけは test_settings.py の
    xdist_group と**同じグループ名**に合流させる必要がある(別ワーカーに
    散ると "input_vrm_seed" の作業フォルダを2プロセスが取り合う)。

    他の検体(vrm_seed 以外)はどのグループとも case_name を共有しないので、
    無指定のまま(=自由に別ワーカーへ散ってよい)ことも合わせて確認する
    ——これが本WPの並列化効果の本体(test_input_format の8検体のうち
    7体は完全に独立して並列化できる)。
    """
    settings_groups = _module_xdist_group_names(test_settings)
    assert test_inputs._XDIST_GROUP_SHARED_WITH_SETTINGS in settings_groups, (
        "test_inputs.py が参照しているグループ名が test_settings.py の"
        "xdist_group と一致していない(名前がズレると合流しない)")

    class _FakeMetafunc:
        def __init__(self, config):
            self.config = config
            self.fixturenames = ["specimen"]
            self.captured = None

        def parametrize(self, argname, params, ids=None):
            self.captured = (argname, params, ids)

    class _FakeConfig:
        def __init__(self, specimens):
            self._specimens = specimens

        def getoption(self, name):
            assert name == "specimens"
            return self._specimens

    metafunc = _FakeMetafunc(_FakeConfig("all"))
    test_inputs.pytest_generate_tests(metafunc)
    _, params, ids = metafunc.captured
    assert list(ids) == list(matrix.SPECIMENS), "specimens=all の並びが変わった"

    grouped = {}
    for name, p in zip(ids, params):
        marks = getattr(p, "marks", ())
        xdist_marks = [m for m in marks if m.name == "xdist_group"]
        grouped[name] = {m.args[0] for m in xdist_marks}

    assert grouped["vrm_seed"] == {test_inputs._XDIST_GROUP_SHARED_WITH_SETTINGS}
    for name in matrix.SPECIMENS:
        if name == "vrm_seed":
            continue
        assert not grouped[name], (
            "{} に想定外の xdist_group が付いている"
            "(この検体は他と case_name を共有しないので無指定のはず)".format(name))


def test_case_names_within_default_nightly_modules_are_disjoint_or_declared_shared():
    r"""既定(--Machine/--Unity 無し)の夜間実行で実際に build() が走る
    case_name を洗い出し、**モジュールをまたぐ重複は既知の1件
    (input_vrm_seed)だけ**であることを確認する。想定外の重複が増えていたら
    (誰かが case_name を安易にコピペした等)、それは新たな作業フォルダ
    競合の芽なので、ここで機械的に検出する。
    """
    input_cases = {"input_{}".format(k) for k in matrix.SPECIMENS}
    settings_cases = {"flip_baseline", "input_vrm_seed", "drop_bones_seed_robo_arm",
                       "exclusions", "matonly"}
    settings_cases |= {"flip_{}".format(f["name"]) for f in matrix.SETTING_FLIPS}
    ue_cases = {"ue_free"}

    overlap_input_settings = input_cases & settings_cases
    assert overlap_input_settings == {"input_vrm_seed"}, (
        "test_inputs.py と test_settings.py の case_name 重複が既知の1件"
        "(input_vrm_seed)から変わった: {}".format(overlap_input_settings))
    assert not (input_cases & ue_cases)
    assert not (settings_cases & ue_cases)


# ---------------------------------------------------------------------------
# 2) 失敗集約(report_merge)
# ---------------------------------------------------------------------------

def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_worker_suffixed_name_roundtrips(tmp_path):
    assert report_merge.worker_suffixed_name("gates.jsonl", None) == "gates.jsonl"
    assert report_merge.worker_suffixed_name("gates.jsonl", "gw0") == "gates.gw0.jsonl"
    assert report_merge.worker_suffixed_name("progress.log", "gw1") == "progress.gw1.log"


def test_validate_run_dir_for_xdist_requires_explicit_run_dir():
    with pytest.raises(ValueError):
        report_merge.validate_run_dir_for_xdist(3, None)
    # numprocesses が無い(非xdist実行)なら run_dir 未指定でも通る(既存挙動)
    report_merge.validate_run_dir_for_xdist(None, None)
    report_merge.validate_run_dir_for_xdist(0, None)
    # run_dir さえあれば通る
    report_merge.validate_run_dir_for_xdist(3, "some/dir")


def test_merge_worker_files_concatenates_and_is_idempotent_noop_when_no_workers(tmp_path):
    run_dir = str(tmp_path)
    # 非並列実行(ワーカーファイルなし)では何もしない
    n = report_merge.merge_worker_files(run_dir)
    assert n == 0
    assert not os.path.isfile(os.path.join(run_dir, "gates.jsonl"))


def test_merge_worker_files_aggregates_all_workers_gate_rows(tmp_path):
    run_dir = str(tmp_path)
    rows_gw0 = [{"case": "a", "gate": "g1", "status": "PASS", "detail": {}}]
    rows_gw1 = [{"case": "b", "gate": "g1", "status": "FAIL", "detail": {}},
                {"case": "c", "gate": "g2", "status": "SKIP", "detail": {}}]
    _write_jsonl(os.path.join(run_dir, "gates.gw0.jsonl"), rows_gw0)
    _write_jsonl(os.path.join(run_dir, "gates.gw1.jsonl"), rows_gw1)
    _write_jsonl(os.path.join(run_dir, "tests.gw0.jsonl"), [{"nodeid": "t1"}])

    n = report_merge.merge_worker_files(run_dir)
    assert n == 2

    merged = report_merge.read_gate_rows(run_dir)
    assert len(merged) == 3
    assert {r["case"] for r in merged} == {"a", "b", "c"}

    with open(os.path.join(run_dir, "tests.jsonl"), encoding="utf-8") as f:
        assert json.loads(f.readline())["nodeid"] == "t1"


def test_read_gate_rows_skips_corrupt_lines(tmp_path):
    run_dir = str(tmp_path)
    path = os.path.join(run_dir, "gates.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"case": "ok", "status": "PASS"}) + "\n")
        f.write("{not json\n")
        f.write("\n")  # 空行
    rows = report_merge.read_gate_rows(run_dir)
    assert len(rows) == 1
    assert rows[0]["case"] == "ok"


def test_read_gate_rows_on_missing_file_returns_empty(tmp_path):
    assert report_merge.read_gate_rows(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# 3) 並列度制御
# ---------------------------------------------------------------------------

def test_resolve_workers_precedence(monkeypatch):
    monkeypatch.delenv(run_overnight.WORKERS_ENV_VAR, raising=False)
    assert run_overnight.resolve_workers(None) == run_overnight.DEFAULT_WORKERS
    assert run_overnight.resolve_workers(5) == 5

    monkeypatch.setenv(run_overnight.WORKERS_ENV_VAR, "7")
    assert run_overnight.resolve_workers(None) == 7
    assert run_overnight.resolve_workers(5) == 5, "CLI引数が環境変数より優先されること"

    monkeypatch.setenv(run_overnight.WORKERS_ENV_VAR, "not-a-number")
    assert run_overnight.resolve_workers(None) == run_overnight.DEFAULT_WORKERS

    monkeypatch.setenv(run_overnight.WORKERS_ENV_VAR, "0")
    assert run_overnight.resolve_workers(None) == run_overnight.DEFAULT_WORKERS


def test_build_phase_args_default_enables_parallel_and_splits_atlas_summary():
    phase_a, phase_b, parallel = run_overnight.build_phase_args(
        "SUITE", "RUNDIR", "all", machine=False, unity=False, workers=3)
    assert parallel is True
    assert "-n" in phase_a and phase_a[phase_a.index("-n") + 1] == "3"
    assert "--dist" in phase_a and phase_a[phase_a.index("--dist") + 1] == "loadgroup"
    m_idx = phase_a.index("-m")
    assert phase_a[m_idx + 1] == "not machine and not atlas_summary"
    assert "--allow-machine" not in phase_a
    assert "--allow-unity" not in phase_a

    assert "-n" not in phase_b, "フェーズBは常に直列(atlas_summary単独)"
    m_idx_b = phase_b.index("-m")
    assert phase_b[m_idx_b + 1] == "atlas_summary"


def test_build_phase_args_machine_disables_parallel_and_flips_marker():
    phase_a, phase_b, parallel = run_overnight.build_phase_args(
        "SUITE", "RUNDIR", "all", machine=True, unity=False, workers=3)
    assert parallel is False, "罠2(モジュール横断の共有case_name)を避けるため直列化する"
    assert "-n" not in phase_a
    m_idx = phase_a.index("-m")
    assert phase_a[m_idx + 1] == "(machine or not machine) and not atlas_summary"
    assert "--allow-machine" in phase_a
    assert "--allow-machine" in phase_b


def test_build_phase_args_unity_disables_parallel_and_adds_flag():
    phase_a, phase_b, parallel = run_overnight.build_phase_args(
        "SUITE", "RUNDIR", "all", machine=False, unity=True, workers=3)
    assert parallel is False
    assert "-n" not in phase_a
    assert "--allow-unity" in phase_a
    assert "--allow-unity" in phase_b


def test_build_phase_args_single_worker_disables_parallel():
    _, _, parallel = run_overnight.build_phase_args(
        "SUITE", "RUNDIR", "all", machine=False, unity=False, workers=1)
    assert parallel is False


def test_build_phase_args_specimens_and_run_dir_are_forwarded():
    phase_a, phase_b, _ = run_overnight.build_phase_args(
        "SUITE", "RUNDIR", "fast", machine=False, unity=False, workers=3)
    for phase in (phase_a, phase_b):
        assert phase[0] == "SUITE"
        assert "--run-dir" in phase and phase[phase.index("--run-dir") + 1] == "RUNDIR"
        assert "--specimens" in phase and phase[phase.index("--specimens") + 1] == "fast"
        assert "--allow-convert" in phase


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
