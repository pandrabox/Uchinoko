# -*- coding: utf-8 -*-
r"""dev#190/#187(devtools\disk_guard.py)の受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実変換・
実relgate実行・実release.py本番実行を一切課さない(pak不変の構造変更のため)。
disk_guard.pyの各関数を、monkeypatch/tmp_pathで実リポジトリから隔離した
小さな入力で検証する。

受入条件(WP指示書より):
  - ユニットテスト(各関数の基本動作)
  - 負の対照(空き容量閾値未満で中断すること/プルーニングが保持対象を消さないこと)

実行: python -m pytest tests\shipcheck\test_disk_guard.py -v
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)

import disk_guard  # noqa: E402


class DummyReport:
    """release.Report/relgate.Reportと同じ log()/section() インタフェースの
    最小スタブ(実ファイルへ書かない)。"""

    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)

    def text(self):
        return "\n".join(self.lines)


class _FakeUsage:
    def __init__(self, free_gb, total_gb=1900.0):
        self.free = int(free_gb * (1024 ** 3))
        self.total = int(total_gb * (1024 ** 3))
        self.used = self.total - self.free


# --- 1. check_disk_space() -----------------------------------------------------

def test_check_disk_space_ok_when_free_well_above_thresholds(tmp_path, monkeypatch):
    """基本の疎通 + 監視ログが1行正しく書かれること。"""
    monkeypatch.setattr(disk_guard, "_get_disk_usage", lambda path: _FakeUsage(500.0))
    log_path = str(tmp_path / "diskspace_log.jsonl")
    report = DummyReport()

    ok, reason = disk_guard.check_disk_space(report, "test-caller", log_path=log_path)

    assert ok is True
    assert reason == ""
    assert "[disk_guard][FATAL]" not in report.text()
    assert "[disk_guard][WARN]" not in report.text()

    assert os.path.isfile(log_path)
    with open(log_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["caller"] == "test-caller"
    assert entry["free_bytes"] == int(500.0 * (1024 ** 3))
    assert "timestamp" in entry and "total_bytes" in entry


def test_check_disk_space_warns_but_does_not_abort_between_thresholds(tmp_path, monkeypatch):
    """警告閾値(100GB)未満・中断閾値(30GB)以上では、警告ログは出るが処理は続行できる。"""
    monkeypatch.setattr(disk_guard, "_get_disk_usage", lambda path: _FakeUsage(50.0))
    report = DummyReport()

    ok, reason = disk_guard.check_disk_space(report, "test-caller",
                                              log_path=str(tmp_path / "log.jsonl"))

    assert ok is True
    assert reason == ""
    assert "[disk_guard][WARN]" in report.text()


def test_check_disk_space_aborts_when_below_abort_threshold(tmp_path, monkeypatch):
    """負の対照1: 中断閾値(30GB)未満なら ok=False で中断すること
    (release.py/relgate.pyはこのok=Falseを受けて、処理を一切開始せず終了する)。"""
    monkeypatch.setattr(disk_guard, "_get_disk_usage", lambda path: _FakeUsage(10.0))
    report = DummyReport()

    ok, reason = disk_guard.check_disk_space(report, "test-caller",
                                              log_path=str(tmp_path / "log.jsonl"))

    assert ok is False
    assert reason  # 空でない理由文字列
    assert "[disk_guard][FATAL]" in report.text()


def test_check_disk_space_threshold_boundary_is_strict_less_than(tmp_path, monkeypatch):
    """境界値: ちょうど中断閾値(30GB)と警告閾値(100GB)では中断しない
    (「未満」判定であることの確認、負の対照2)。"""
    monkeypatch.setattr(disk_guard, "_get_disk_usage",
                         lambda path: _FakeUsage(disk_guard.ABORT_FREE_GB))
    report = DummyReport()
    ok, _ = disk_guard.check_disk_space(report, "t", log_path=str(tmp_path / "log.jsonl"))
    assert ok is True, "ちょうど中断閾値のときは中断してはならない(未満判定)"


# --- 2. prune_release_cert_runs() -----------------------------------------------

def _make_run_dir(cert_dir, name, verdict=None):
    run_dir = cert_dir / name
    run_dir.mkdir(parents=True)
    if verdict is not None:
        (run_dir / "report.md").write_text(
            f"# release.py 実行レポート\n\n総合判定: {verdict}(dummy)\n", encoding="utf-8")
    return run_dir


def test_prune_release_cert_runs_keeps_latest_n_and_latest_pass(tmp_path):
    cert_dir = tmp_path / "release_cert"
    cert_dir.mkdir()
    # 8 runs、新しい順: 08,07,06(FAIL) 05,04,03(FAIL) 02(PASS) 01(FAIL)
    _make_run_dir(cert_dir, "run_20260701_000001", verdict="FAIL")
    _make_run_dir(cert_dir, "run_20260701_000002", verdict="PASS")
    _make_run_dir(cert_dir, "run_20260701_000003", verdict="FAIL")
    _make_run_dir(cert_dir, "run_20260701_000004", verdict="FAIL")
    _make_run_dir(cert_dir, "run_20260701_000005", verdict="FAIL")
    _make_run_dir(cert_dir, "run_20260701_000006", verdict="FAIL")
    _make_run_dir(cert_dir, "run_20260701_000007", verdict="FAIL")
    _make_run_dir(cert_dir, "run_20260701_000008", verdict="FAIL")
    # プルーニングと無関係なcert_<commit>.jsonは一切触れられないことも確認する
    (cert_dir / "cert_abc1234.json").write_text("{}", encoding="utf-8")

    report = DummyReport()
    result = disk_guard.prune_release_cert_runs(report, cert_dir=str(cert_dir), keep_n=3)

    expected_kept = {"run_20260701_000006", "run_20260701_000007", "run_20260701_000008",
                      "run_20260701_000002"}  # 最新3件 + 最新PASS(範囲外でも保持)
    expected_removed = {"run_20260701_000001", "run_20260701_000003",
                         "run_20260701_000004", "run_20260701_000005"}

    assert set(result["kept"]) == expected_kept
    assert set(result["removed"]) == expected_removed

    remaining = {p.name for p in cert_dir.iterdir()}
    assert expected_kept <= remaining, "保持対象が実際にディスク上へ残っていない"
    assert not (expected_removed & remaining), "削除対象のはずのrunがディスク上へ残っている"
    assert "cert_abc1234.json" in remaining, "run_*以外のファイル(証明書json)は一切触れてはならない"


def test_prune_release_cert_runs_does_not_delete_when_within_keep_n(tmp_path):
    """負の対照3: 総run数がkeep_n以下なら何も削除しない(保持対象を消さない基本形)。"""
    cert_dir = tmp_path / "release_cert"
    cert_dir.mkdir()
    _make_run_dir(cert_dir, "run_20260701_000001", verdict="FAIL")
    _make_run_dir(cert_dir, "run_20260701_000002", verdict="PASS")

    report = DummyReport()
    result = disk_guard.prune_release_cert_runs(report, cert_dir=str(cert_dir), keep_n=5)

    assert result["removed"] == []
    remaining = {p.name for p in cert_dir.iterdir()}
    assert remaining == {"run_20260701_000001", "run_20260701_000002"}


def test_prune_release_cert_runs_missing_report_md_is_not_treated_as_pass(tmp_path):
    """report.mdが無い/判定行が無いrunはPASS扱いにしない(fail-safe、latest_passの
    誤検出防止)。"""
    cert_dir = tmp_path / "release_cert"
    cert_dir.mkdir()
    _make_run_dir(cert_dir, "run_20260701_000001", verdict=None)  # report.mdすら無い
    _make_run_dir(cert_dir, "run_20260701_000002", verdict="FAIL")

    report = DummyReport()
    result = disk_guard.prune_release_cert_runs(report, cert_dir=str(cert_dir), keep_n=1)

    # keep_n=1なので最新の000002は保持されるが、PASSが無いのでlatest_pass拡張は起きない
    assert result["kept"] == ["run_20260701_000002"]
    assert result["removed"] == ["run_20260701_000001"]


# --- 3. prune_stale_worktrees() --------------------------------------------------

def test_prune_stale_worktrees_removes_only_unregistered_dirs(tmp_path, monkeypatch):
    worktrees_dir = tmp_path / "worktrees"
    worktrees_dir.mkdir()
    active_dir = worktrees_dir / "agent-active"
    active_dir.mkdir()
    orphan_dir = worktrees_dir / "agent-orphan"
    orphan_dir.mkdir()

    class _FakeProc:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def _fake_prune(repo_root):
        return _FakeProc("")

    def _fake_list(repo_root):
        # gitは agent-active だけを worktree として認識している、という体
        return _FakeProc(f"worktree {active_dir}\nHEAD deadbeef\nbranch refs/heads/x\n\n"
                          f"worktree {repo_root}\nHEAD deadbeef\nbranch refs/heads/master\n")

    monkeypatch.setattr(disk_guard, "_git_worktree_prune", _fake_prune)
    monkeypatch.setattr(disk_guard, "_git_worktree_list", _fake_list)

    report = DummyReport()
    result = disk_guard.prune_stale_worktrees(report, worktrees_dir=str(worktrees_dir),
                                               repo_root=str(tmp_path))

    assert result["removed_orphan_dirs"] == ["agent-orphan"]
    assert active_dir.is_dir(), "gitがまだ認識している(登録済み)worktreeは絶対に消してはならない"
    assert not orphan_dir.exists(), "git未登録の孤立ディレクトリは削除されるはず"


def test_prune_stale_worktrees_keeps_dir_if_it_becomes_registered(tmp_path, monkeypatch):
    """負の対照4: 同じディレクトリでも、gitのworktree list出力に含まれていれば
    (=git未登録の孤立ディレクトリに該当しなければ)絶対に削除されないことを確認する。"""
    worktrees_dir = tmp_path / "worktrees"
    worktrees_dir.mkdir()
    still_active_dir = worktrees_dir / "agent-still-active"
    still_active_dir.mkdir()

    class _FakeProc:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    monkeypatch.setattr(disk_guard, "_git_worktree_prune", lambda repo_root: _FakeProc(""))
    monkeypatch.setattr(disk_guard, "_git_worktree_list",
                         lambda repo_root: _FakeProc(f"worktree {still_active_dir}\n"))

    report = DummyReport()
    result = disk_guard.prune_stale_worktrees(report, worktrees_dir=str(worktrees_dir),
                                               repo_root=str(tmp_path))

    assert result["removed_orphan_dirs"] == []
    assert still_active_dir.is_dir()


# --- 4. list_stale_dist_zips() / warn_log_stale_dist_zips() ---------------------

def test_list_stale_dist_zips_returns_older_ones_without_deleting(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    names = [f"Uchinoko_v0.{i}.0.zip" for i in range(1, 6)]  # 5個
    paths = []
    for i, name in enumerate(names):
        p = dist_dir / name
        p.write_bytes(b"x")
        # mtimeを名前の順に古い方から新しい方へ均等にずらす
        os.utime(p, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
        paths.append(p)

    stale = disk_guard.list_stale_dist_zips(dist_dir=str(dist_dir), keep_n=3)

    stale_names = {os.path.basename(p) for p in stale}
    assert stale_names == {"Uchinoko_v0.1.0.zip", "Uchinoko_v0.2.0.zip"}, (
        "最新3件を除いた、古い2件だけが警告対象のはず")
    # 負の対照: list_stale_dist_zips はいかなるファイルも削除しない
    for p in paths:
        assert p.is_file(), f"list_stale_dist_zips が誤ってファイルを削除した: {p}"


def test_warn_log_stale_dist_zips_logs_but_never_deletes(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    for i in range(4):
        p = dist_dir / f"old_{i}.zip"
        p.write_bytes(b"x")
        os.utime(p, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))

    report = DummyReport()
    stale = disk_guard.warn_log_stale_dist_zips(report, dist_dir=str(dist_dir), keep_n=2)

    assert len(stale) == 2
    assert "[disk_guard][WARN]" in report.text()
    remaining = {p.name for p in dist_dir.iterdir()}
    assert len(remaining) == 4, "warn_log_stale_dist_zips は削除を一切行ってはならない"


def test_warn_log_stale_dist_zips_no_warning_when_within_keep_n(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "only_one.zip").write_bytes(b"x")

    report = DummyReport()
    stale = disk_guard.warn_log_stale_dist_zips(report, dist_dir=str(dist_dir), keep_n=3)

    assert stale == []
    assert "[disk_guard][WARN]" not in report.text()
