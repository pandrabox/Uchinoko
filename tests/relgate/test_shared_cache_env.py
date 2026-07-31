# -*- coding: utf-8 -*-
"""u54 WP-B2: relgate.pyがconvert.ps1サブプロセスへD2P_SHARED_CACHEを
配線していることの単体試験。

背景: pipeline\\py\\vp_core.py(u54 WP-B)の共有キャッシュ(vanilla抽出/
live_templateをfingerprintキーで共有)は、既定では基底ディレクトリを
work_root(job_dirの親、relgateなら--workの値そのもの)配下の_shared_cacheに
取る。relgateは実行のたびに--workが変わるため、素通しでは実行を跨いだ
キャッシュ共有が効かない(work\\u54_unbundle\\wpB\\REPORT.md「積み残し・懸念」
節)。devtools\\relgate.pyの`build_convert_env()`が、convert.ps1サブプロセスの
環境にD2P_SHARED_CACHEをリポジトリ固定の絶対パスとして設定することでこれを
解消している(devtools\\relgate.py SHARED_CACHE_DIR/build_convert_env参照)。

このテストはconvert.ps1やBlenderを一切起動しない(build_convert_env()が
組み立てるdict/os.environを見るだけの純粋関数テスト)。
"""
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
if DEVTOOLS_DIR not in sys.path:
    sys.path.insert(0, DEVTOOLS_DIR)

import relgate  # noqa: E402


def test_shared_cache_dir_is_fixed_absolute_path_under_repo_work():
    expected = os.path.join(REPO_ROOT, "work", "_shared_cache")
    assert relgate.SHARED_CACHE_DIR == expected
    assert os.path.isabs(relgate.SHARED_CACHE_DIR)


def test_build_convert_env_sets_d2p_shared_cache_when_unset(monkeypatch):
    monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)
    env = relgate.build_convert_env()
    assert env.get("D2P_SHARED_CACHE") == relgate.SHARED_CACHE_DIR


def test_build_convert_env_preserves_externally_set_value(monkeypatch):
    """外部(呼び出し元シェル等)が既にD2P_SHARED_CACHEを設定していれば、
    relgate.pyはそれを尊重して上書きしない(試験・呼び出し側での意図的な
    分離指定を壊さないため)。"""
    custom = os.path.join(REPO_ROOT, "work", "_some_other_cache")
    monkeypatch.setenv("D2P_SHARED_CACHE", custom)
    env = relgate.build_convert_env()
    assert env.get("D2P_SHARED_CACHE") == custom


def test_build_convert_env_preserves_rest_of_environment(monkeypatch):
    """D2P_SHARED_CACHE以外の既存環境変数(例: PATH)がbuild_convert_env()の
    戻り値からごっそり消えていないこと(subprocess.runへ丸ごと差し替えて
    渡すため、消えると子プロセスがコマンドを見つけられなくなる)。"""
    monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)
    monkeypatch.setenv("D2P_TEST_MARKER_XYZ", "1")
    env = relgate.build_convert_env()
    assert env.get("D2P_TEST_MARKER_XYZ") == "1"
    assert "PATH" in env or "Path" in env  # Windowsは大文字小文字の揺れがある


def test_run_convert_passes_env_to_subprocess(monkeypatch):
    """run_convert()が実際にsubprocess.run呼び出しへenv=を渡していること
    (配線の実体テスト。pwsh/convert.ps1は実行しない — subprocess.runを
    モックして呼び出し引数だけを検証する)。"""
    monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)
    captured = {}

    class _FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(relgate.subprocess, "run", _fake_run)

    class _FakeReport:
        def log(self, *_args, **_kwargs):
            pass

    tmp_job_dir = os.path.join(REPO_ROOT, "work", "_test_shared_cache_env_dummy")
    tmp_job_path = os.path.join(tmp_job_dir, "job.json")
    os.makedirs(tmp_job_dir, exist_ok=True)
    try:
        rc, _elapsed = relgate.run_convert(tmp_job_path, _FakeReport(), "test")
    finally:
        shutil.rmtree(tmp_job_dir, ignore_errors=True)

    assert rc == 0
    assert "env" in captured["kwargs"], "subprocess.run呼び出しにenv=が渡されていない"
    assert captured["kwargs"]["env"].get("D2P_SHARED_CACHE") == relgate.SHARED_CACHE_DIR


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
