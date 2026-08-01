"""devtools\\deploy.py の phase5_ship_smoke が --zip-audit defer を使うことの検証(dev#675)。

背景: phase5_ship_smoke(devtools\\deploy.py)はフェーズ6(zip生成)より前に実行される
ため、dist\\にあるのは常に「前回リリースの旧zip」。これをship_smoke.py --fastの既定
(--zip-audit auto)でu28鮮度照合すると、直前の正当なコード修正が毎回不一致検出される
構造的偽陽性になる(release.pyがcommit 353a336で先行対処した同型問題、2026-07-27)。
本WPはdeploy.pyのcmd組み立てにrelease.pyと同じ`--zip-audit defer`を追加した。

このファイルはPub実体・実サブプロセス(ship_smoke.py本体・u45/u28)には一切触れず、
以下を機械的に検証する:
  1. phase5_ship_smoke()が組み立てるコマンド行に --zip-audit defer が含まれること
     (構造的偽陽性の原因=旧zip鮮度照合サブチェックがdeferで回避されることの確認)
  2. 負の対照: deferを追加しても、ship_smoke.py本体が非ゼロで終了した場合
     (u45等、本物の権利問題を模す)はphase5_ship_smokeが従来どおりDeployAbortする
     こと(権利監査の検証意図そのものは弱めていないことの確認)
  3. release.pyの先行実装(commit 353a336)が同じ --zip-audit defer を使っている
     ことの前提確認(本WPが接ぎ木した「実績ある方式」の実在確認)

ship_smoke.py側の実装(gate_a1_rights_audit のzip_audit_mode分岐、u45は
zip_audit_modeに関わらず必ず実行される)は tests\\shipcheck\\ship_smoke.py 本体に
既に定義済み(release.py用にWP17で導入済み)。dev#675は呼び出し側のdeploy.pyだけを
合わせる変更であり、ship_smoke.py自体は変更していない。
"""
import os
import sys
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import deploy  # noqa: E402


class _NullReporter:
    def log(self, text):
        pass


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_phase5_cmd_includes_zip_audit_defer(tmp_path, monkeypatch):
    """正の対照: phase5_ship_smokeが組み立てるコマンドに --zip-audit defer が含まれる。"""
    captured = {}

    def _fake_run(cmd, cwd=None, timeout=None, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _FakeCompleted(returncode=0, stdout="ship_smoke --fast: 全PASS(SKIPは許容)\n")

    monkeypatch.setattr(deploy, "_run", _fake_run)

    work_dir = str(tmp_path)
    result = deploy.phase5_ship_smoke(_NullReporter(), work_dir)

    cmd = captured["cmd"]
    assert "--zip-audit" in cmd, "phase5_ship_smokeが--zip-auditを渡していない: {}".format(cmd)
    idx = cmd.index("--zip-audit")
    assert cmd[idx + 1] == "defer", (
        "phase5_ship_smokeの--zip-auditが'defer'でない(release.pyのcommit 353a336と"
        "同型の対処が入っていない): {}".format(cmd))
    assert "--fast" in cmd
    assert captured["cwd"] == deploy.DEV_ROOT
    assert result == os.path.join(work_dir, "ship_smoke")


def test_phase5_cmd_omits_zip_audit_negative_control(tmp_path, monkeypatch):
    """負の対照その1: このテスト自身の検査ロジックが空振りでないことの確認。
    仮にphase5_ship_smokeが--zip-auditを渡さない実装だったとしたら、上のテストの
    `"--zip-audit" in cmd` は失敗するはず、という前提を独立に検証する
    (=検査対象の文字列がcmdに実在しない場合はassertが確実に落ちることの確認)。"""
    fake_cmd_without_defer = [deploy.PYTHON, "ship_smoke.py", "--fast", "--work", "x"]
    assert "--zip-audit" not in fake_cmd_without_defer


def test_phase5_negative_control_real_failure_still_aborts(tmp_path, monkeypatch):
    """負の対照その2: --zip-audit deferを追加しても、ship_smoke.py本体が非ゼロ終了した
    場合(u45等、本物の権利問題を模する)はphase5_ship_smokeが従来どおり
    DeployAbortすること。deferはu28の旧zip鮮度サブチェックだけを回避するもので
    あり、権利監査(u45)自体のFAIL伝播を握りつぶすものではないことの確認。"""
    def _fake_run(cmd, cwd=None, timeout=None, env=None):
        return _FakeCompleted(
            returncode=1,
            stdout="[u45_toto_perceptual_audit.py --live] rc=1 -> FAIL\n",
        )

    monkeypatch.setattr(deploy, "_run", _fake_run)

    with pytest.raises(deploy.DeployAbort):
        deploy.phase5_ship_smoke(_NullReporter(), str(tmp_path))


def test_phase5_raises_if_run_itself_raises(tmp_path, monkeypatch):
    """負の対照その3: サブプロセス起動自体が例外を投げた場合もfail-closedで
    DeployAbortすること(deferオプション追加が例外処理経路を壊していないことの確認)。"""
    def _fake_run(cmd, cwd=None, timeout=None, env=None):
        raise OSError("simulated launch failure")

    monkeypatch.setattr(deploy, "_run", _fake_run)

    with pytest.raises(deploy.DeployAbort):
        deploy.phase5_ship_smoke(_NullReporter(), str(tmp_path))


def test_release_py_precedent_uses_same_defer_flag():
    """比較対照: release.pyのrun_ship_smoke()が同じ --zip-audit defer を使っている
    こと(本WPが接ぎ木した『実績ある方式』の実在確認。release.py側は既に
    2026-07-27のcommit 353a336でこの対処が入っている前提)。"""
    release_py = DEVTOOLS / "release.py"
    content = release_py.read_text(encoding="utf-8")
    assert "--zip-audit" in content, "release.pyから--zip-auditの記述が消えている(前提崩壊)"
    assert '"defer"' in content, "release.pyの--zip-audit指定値が'defer'でない(前提崩壊)"


def test_ship_smoke_py_supports_zip_audit_defer_option():
    """前提確認: ship_smoke.py自体が --zip-audit defer を受理する実装を持つこと
    (dev#675はdeploy.py側の呼び出しを合わせるだけで、ship_smoke.py本体は
    変更していない。この前提が崩れていたらdeploy.py側の変更は無意味になる)。"""
    ship_smoke_py = (
        Path(__file__).resolve().parent.parent.parent
        / "tests" / "shipcheck" / "ship_smoke.py"
    )
    content = ship_smoke_py.read_text(encoding="utf-8")
    assert '"--zip-audit"' in content
    assert 'choices=["auto", "defer"]' in content
