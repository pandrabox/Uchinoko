# enforce-issue-label.js(PreToolUseフック)のテスト。
#
# 2026-08-01改訂: 「cat:/for:ラベルの検査」から「生の起票コマンドの全面禁止」へ
# 方針変更(オーナー指摘「将来の指揮者がHaikuに委託するコンセンサスは維持され
# ない」への構造的対策)。ラベルが揃っていようがいまいが、Bashツール経由の
# `gh issue create` / `gh api …/issues -f title=…` は無条件でdenyし、
# devtools\issue_file.py の使用を案内する。cat:/for:規律の検証と重複検索は
# issue_file.py側(tests\infra\test_issue_file.py)に一元化した。
#
# 負の対照: 生の起票コマンドは、ラベルの有無・正誤に関わらずブロック(deny)される。
# 正の対照: ①起票以外のghコマンド ②python devtools\issue_file.py create 経由
#          (PreToolUseのcommand文字列に "gh issue create" 等が現れないため
#          正規表現にマッチせず素通りする)は、いずれも素通りする。

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "enforce-issue-label.js"

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


# ---- 負の対照: 生の起票コマンドはラベルの有無に関わらず常にブロックされる ----

def test_deny_create_without_any_label():
    deny, _ = run_hook('gh issue create --title "t" --body "b"')
    assert deny


def test_deny_create_even_with_correct_cat_and_state_labels():
    """方針転換の核心: ラベルが規律どおり(cat:1個+for:1個)揃っていても、
    生の `gh issue create` は今や無条件でdenyされる。"""
    deny, data = run_hook(
        'gh issue create --title "t" --label "cat:運営自動化" --label for:ai'
    )
    assert deny
    assert "issue_file.py" in data["hookSpecificOutput"]["permissionDecisionReason"]


def test_deny_create_with_comma_separated_labels():
    deny, _ = run_hook('gh issue create --title "t" -l "cat:内部不具合,for:human"')
    assert deny


def test_deny_rest_create_without_labels():
    deny, _ = run_hook(
        'GH_TOKEN=$(python devtools/claude_bot/gh_app_token.py) '
        'gh api repos/pandrabox/DiveToPalworld-dev/issues -f title="t" -f body="b"'
    )
    assert deny


def test_deny_rest_create_even_with_correct_labels():
    """方針転換の核心(REST版): ラベルが規律どおりでも生のREST起票はdenyされる。"""
    deny, data = run_hook(
        'gh api repos/pandrabox/DiveToPalworld-dev/issues '
        '-f title="t" -f body="b" -f "labels[]=cat:リリース配布" -f "labels[]=for:ai"'
    )
    assert deny
    assert "issue_file.py" in data["hookSpecificOutput"]["permissionDecisionReason"]


def test_deny_powershell_tool_too():
    deny, _ = run_hook('gh issue create --title "t"', tool_name="PowerShell")
    assert deny


# ---- 正の対照①: 起票以外のghコマンド・無関係ツールは素通りする ----

def test_allow_rest_issue_list_readonly():
    # title=フィールドの無い /issues 叩きは一覧取得等の読み取り。対象外
    deny, _ = run_hook("gh api repos/pandrabox/DiveToPalworld-dev/issues")
    assert not deny


def test_allow_rest_issue_comment():
    # コメントは /issues/<番号>/comments。起票ではないので対象外
    deny, _ = run_hook(
        'gh api repos/pandrabox/DiveToPalworld-dev/issues/450/comments -f body="c"'
    )
    assert not deny


def test_allow_issue_edit_and_comment_subcommands():
    for cmd in (
        "gh issue edit 450 --add-label cat:性能",
        'gh issue comment 450 --body "c"',
        "gh issue close 450",
        "gh issue list --state open",
    ):
        deny, _ = run_hook(cmd)
        assert not deny, cmd


def test_allow_other_tools_ignored():
    deny, _ = run_hook('gh issue create --title "t"', tool_name="Read")
    assert not deny


# ---- 正の対照②(2026-08-01追加): issue_file.py経由のcreateコマンド文字列は
#      このフックの正規表現に一切マッチしないため素通りする。実際の規律検査
#      (cat:/for:必須+署名必須)と重複検索はissue_file.py内部で行われる
#      (tests\infra\test_issue_file.py)。この「素通り」自体が設計どおりの
#      挙動であることをここで確認する ----

def test_allow_issue_file_py_create_command_string():
    deny, _ = run_hook(
        'python devtools/issue_file.py create --title "[test] t" '
        '--body-file body.md --cat 開発基盤 --assignee-label for:ai'
    )
    assert not deny


def test_allow_issue_file_py_create_command_string_windows_path():
    deny, _ = run_hook(
        r'python devtools\issue_file.py create --title "t" --body-file body.md '
        r'--cat 開発基盤 --assignee-label for:ai --force-new'
    )
    assert not deny


def test_allow_issue_file_py_create_from_powershell_tool_too():
    deny, _ = run_hook(
        'python devtools/issue_file.py create --title "t" --body-file body.md '
        '--cat 開発基盤 --assignee-label for:ai',
        tool_name="PowerShell",
    )
    assert not deny


def test_allow_issue_file_py_search_and_comment_subcommands():
    for cmd in (
        'python devtools/issue_file.py search --cat 開発基盤 --keywords foo bar',
        'python devtools/issue_file.py comment --issue 578 --body-file body.md',
    ):
        deny, _ = run_hook(cmd)
        assert not deny, cmd


def test_fail_open_on_garbage_stdin():
    proc = subprocess.run(
        [NODE, str(HOOK)], input=b"not-json", capture_output=True, timeout=30
    )
    assert proc.stdout.decode("utf-8", errors="replace").strip() == ""
