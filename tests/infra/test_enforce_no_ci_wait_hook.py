# enforce-no-ci-wait.js(PreToolUseフック)のテスト。
#
# オーナー要望「CI待ちポーリングをフックで禁止できる?」(2026-08-01)への実装。
# `gh run watch` は無条件でdeny。加えて `Start-Sleep`/`sleep` と `gh run ...` が
# 同一コマンド文字列に共存する手書きポーリングパターンもdenyする(watch以外の
# サブコマンドを含む。素朴なポーリングの主経路を塞ぐのが目的で、完全網羅はしない)。
#
# 負の対照: `gh run watch` は引数の有無・ツール種別を問わずブロックされる。
#          sleep+gh run の共存も同様にブロックされる。
# 正の対照: `gh run list`/`gh run view` 単独、`gh run watch`を含まない無関係コマンド、
#          `gh run`を伴わない単独sleepはいずれも素通りする。

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "enforce-no-ci-wait.js"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


def run_hook(command: str, tool_name: str = "Bash"):
    """フックにPreToolUse入力を与え、(deny判定, 出力dict or None) を返す。"""
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    proc = subprocess.run(
        [NODE, str(HOOK)],
        input=payload.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        return False, None
    data = json.loads(out)
    deny = data.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    return deny, data


# ---- 負の対照①: gh run watch は無条件でブロックされる ----

def test_deny_gh_run_watch_with_id():
    deny, data = run_hook("gh run watch 123456789")
    assert deny
    assert "CI完了待ち" in data["hookSpecificOutput"]["permissionDecisionReason"]


def test_deny_gh_run_watch_without_id():
    deny, _ = run_hook("gh run watch")
    assert deny


def test_deny_gh_run_watch_with_flags():
    deny, _ = run_hook("gh run watch 123 --exit-status")
    assert deny


def test_deny_gh_run_watch_powershell_tool_too():
    deny, _ = run_hook("gh run watch 123", tool_name="PowerShell")
    assert deny


# ---- 負の対照②: sleep系コマンドと gh run の共存(手書きポーリングループ) ----

def test_deny_start_sleep_and_gh_run_list_powershell():
    deny, data = run_hook(
        "Start-Sleep -Seconds 30; gh run list --limit 1", tool_name="PowerShell"
    )
    assert deny
    assert "CI完了待ち" in data["hookSpecificOutput"]["permissionDecisionReason"]


def test_deny_bash_sleep_and_gh_run_list():
    deny, _ = run_hook("sleep 30 && gh run list --limit 1")
    assert deny


def test_deny_gh_run_view_then_sleep():
    # 順序を問わず共存を検出する(単純化のための設計判断)
    deny, _ = run_hook("gh run view 123; Start-Sleep -Seconds 5")
    assert deny


def test_deny_sleep_and_gh_run_loop_style():
    deny, _ = run_hook(
        'while ($true) { gh run list --limit 1; Start-Sleep -Seconds 10 }',
        tool_name="PowerShell",
    )
    assert deny


# ---- 正の対照①: gh run単独サブコマンド(1回確認)は素通りする ----

def test_allow_gh_run_list_alone():
    deny, _ = run_hook("gh run list")
    assert not deny


def test_allow_gh_run_view_alone():
    deny, _ = run_hook("gh run view 123")
    assert not deny


def test_allow_gh_run_rerun():
    deny, _ = run_hook("gh run rerun 123 --failed")
    assert not deny


def test_allow_gh_workflow_run():
    # `gh run` ではなく `gh workflow run` は対象外
    deny, _ = run_hook("gh workflow run release.yml")
    assert not deny


# ---- 正の対照②: gh runを伴わない単独sleepは素通りする(一般用途まで巻き込まない) ----

def test_allow_start_sleep_alone():
    deny, _ = run_hook("Start-Sleep -Seconds 5", tool_name="PowerShell")
    assert not deny


def test_allow_bash_sleep_alone():
    deny, _ = run_hook("sleep 2 && python devtools/foo.py")
    assert not deny


def test_allow_unrelated_commands():
    deny, _ = run_hook("git status")
    assert not deny


def test_allow_other_tools_ignored():
    deny, _ = run_hook("gh run watch 123", tool_name="Read")
    assert not deny


def test_fail_open_on_garbage_stdin():
    proc = subprocess.run(
        [NODE, str(HOOK)], input=b"not-json", capture_output=True, timeout=30
    )
    assert proc.stdout.decode("utf-8", errors="replace").strip() == ""
