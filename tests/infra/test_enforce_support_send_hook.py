# enforce-support-send.js(PreToolUseフック)のテスト。
#
# dev#664(2026-08-01ぱん裁定「サポート返信のフラグ駆動化」): AIが `support.py reply` を
# Bash/PowerShellツール経由で直接実行してユーザーへ送信する経路を全面禁止し、
# `support.py flag <ID> --human|--unresolved|--resolved --ver X.Y.Z|--nolog` へ案内する。
#
# 負の対照: `support.py reply` の直接実行は、引数・パス区切り・ツール種別を問わずdenyされる。
# 正の対照: `support.py flag` および reply以外のsupport.pyサブコマンド(close/status/draft/
#          triage等、ユーザーへの直接送信ではない管理操作)・無関係コマンドは素通りする。

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "enforce-support-send.js"

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


# ---- 負の対照: support.py reply の直接実行は常にdenyされる ----

def test_deny_reply_windows_path():
    deny, data = run_hook(r'python devtools\support.py reply ABCD1234 --text "hello"')
    assert deny
    assert "flag" in data["hookSpecificOutput"]["permissionDecisionReason"]


def test_deny_reply_posix_path():
    deny, _ = run_hook('python devtools/support.py reply ABCD1234 --text "hello" --status closed')
    assert deny


def test_deny_reply_powershell_tool_too():
    deny, _ = run_hook(r'python devtools\support.py reply ABCD1234 --text "hi"', tool_name="PowerShell")
    assert deny


def test_deny_reply_even_with_quoted_script_path():
    deny, _ = run_hook('python "devtools/support.py" reply ABCD1234 --text "hi"')
    assert deny


# ---- 正の対照①: flag(唯一残された手段)は素通りする ----

def test_allow_flag_unresolved():
    deny, _ = run_hook("python devtools/support.py flag ABCD1234 --unresolved")
    assert not deny


def test_allow_flag_resolved_with_ver():
    deny, _ = run_hook("python devtools/support.py flag ABCD1234 --resolved --ver v2.3.2")
    assert not deny


def test_allow_flag_human_and_nolog():
    for cmd in (
        "python devtools/support.py flag ABCD1234 --human",
        "python devtools/support.py flag ABCD1234 --nolog",
    ):
        deny, _ = run_hook(cmd)
        assert not deny, cmd


# ---- 正の対照②: reply以外のsupport.pyサブコマンド(ユーザーへの直接送信ではない)は素通りする ----

def test_allow_non_reply_subcommands():
    for cmd in (
        "python devtools/support.py list --status new",
        "python devtools/support.py show ABCD1234",
        "python devtools/support.py close ABCD1234",
        "python devtools/support.py status ABCD1234 triaged",
        "python devtools/support.py draft ABCD1234 --text hello",
        "python devtools/support.py triage ABCD1234 --score 3",
        "python devtools/support.py unanswered --hours 4",
        "python devtools/support.py first-response --hours 4",
    ):
        deny, _ = run_hook(cmd)
        assert not deny, cmd


def test_allow_unrelated_commands():
    deny, _ = run_hook('git status')
    assert not deny


def test_allow_other_tools_ignored():
    deny, _ = run_hook(r'python devtools\support.py reply ABCD1234 --text "hi"', tool_name="Read")
    assert not deny


def test_fail_open_on_garbage_stdin():
    proc = subprocess.run(
        [NODE, str(HOOK)], input=b"not-json", capture_output=True, timeout=30
    )
    assert proc.stdout.decode("utf-8", errors="replace").strip() == ""
