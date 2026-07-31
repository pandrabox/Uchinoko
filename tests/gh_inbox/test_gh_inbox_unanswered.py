"""gh_inbox.py `unanswered` サブコマンドの単体テスト(dev#334)。

「全issueの最終コメント著者は必ずAI」ルール違反の検出ロジックを、
APIをモックせず純粋関数(find_unanswered / is_ai_authored)へ直接
フィクスチャ(inline dict)を渡して検証する。ネットワークへは一切出ない。
"""
import sys
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import gh_inbox  # noqa: E402


def make_issue(number, title="Test issue", state="open", author="pandrabox",
                updated_at="2026-07-30T00:00:00Z"):
    return {
        "number": number,
        "title": title,
        "state": state,
        "body": "body",
        "user": {"login": author},
        "created_at": updated_at,
        "updated_at": updated_at,
    }


def make_comment(cid, issue_number, author, body="", created_at="2026-07-30T01:00:00Z"):
    return {
        "id": cid,
        "issue_url": f"https://api.github.com/repos/pandrabox/DiveToPalworld-dev/issues/{issue_number}",
        "user": {"login": author},
        "created_at": created_at,
        "updated_at": created_at,
        "body": body,
    }


# ---------------------------------------------------------------------------
# ケース①: 最終コメント著者がpandrabox → 検出
# ---------------------------------------------------------------------------

def test_last_comment_pandrabox_is_detected():
    issues = [make_issue(1)]
    comments = [
        make_comment(101, 1, "osaki-claude[bot]", "回答しました", "2026-07-29T00:00:00Z"),
        make_comment(102, 1, "pandrabox", "ありがとう、追加で質問です", "2026-07-30T00:00:00Z"),
    ]
    items = gh_inbox.find_unanswered(issues, comments)
    assert [it["number"] for it in items] == [1]


# ---------------------------------------------------------------------------
# ケース②: 最終コメント著者がbot → 非検出
# ---------------------------------------------------------------------------

def test_last_comment_bot_is_not_detected():
    issues = [make_issue(1)]
    comments = [
        make_comment(101, 1, "pandrabox", "質問です", "2026-07-29T00:00:00Z"),
        make_comment(102, 1, "osaki-claude[bot]", "回答しました", "2026-07-30T00:00:00Z"),
    ]
    items = gh_inbox.find_unanswered(issues, comments)
    assert items == []


# ---------------------------------------------------------------------------
# ケース③: 最終コメントがpandrabox認証だがClaude署名あり → 非検出(#326代替)
# ---------------------------------------------------------------------------

def test_last_comment_pandrabox_authenticated_with_claude_signature_is_not_detected():
    issues = [make_issue(1)]
    comments = [
        make_comment(101, 1, "pandrabox", "質問です", "2026-07-29T00:00:00Z"),
        make_comment(
            102, 1, "pandrabox",
            "botが403だったためpandrabox認証で代打回答します。\n— Claude(実装者)",
            "2026-07-30T00:00:00Z",
        ),
    ]
    items = gh_inbox.find_unanswered(issues, comments)
    assert items == []


# ---------------------------------------------------------------------------
# ケース④: コメント0件・body著者がpandrabox → 検出
# ---------------------------------------------------------------------------

def test_zero_comments_body_author_pandrabox_is_detected():
    issues = [make_issue(1, author="pandrabox")]
    comments = []
    items = gh_inbox.find_unanswered(issues, comments)
    assert [it["number"] for it in items] == [1]


def test_zero_comments_body_author_bot_is_not_detected():
    issues = [make_issue(1, author="osaki-claude[bot]")]
    comments = []
    items = gh_inbox.find_unanswered(issues, comments)
    assert items == []


# ---------------------------------------------------------------------------
# PR除外・複数issue・整形
# ---------------------------------------------------------------------------

def test_pull_requests_are_excluded():
    pr = make_issue(99, author="pandrabox")
    pr["pull_request"] = {"url": "https://api.github.com/repos/pandrabox/DiveToPalworld-dev/pulls/99"}
    items = gh_inbox.find_unanswered([pr], [])
    assert items == []


def test_format_unanswered_report_empty():
    assert gh_inbox.format_unanswered_report([]) == "未応答なし"


def test_format_unanswered_report_lists_number_title_updated_at():
    items = [{"number": 5, "title": "テスト題名", "updated_at": "2026-07-30T00:00:00Z"}]
    out = gh_inbox.format_unanswered_report(items)
    assert out == "#5 テスト題名 2026-07-30T00:00:00Z"


def test_multiple_issues_sorted_by_number():
    issues = [make_issue(3, author="pandrabox"), make_issue(1, author="pandrabox")]
    items = gh_inbox.find_unanswered(issues, [])
    assert [it["number"] for it in items] == [1, 3]


# ---------------------------------------------------------------------------
# 負の対照: is_ai_authored を意図的に壊すとFAILすることを確認してから復元する
# ---------------------------------------------------------------------------

def test_negative_control_broken_is_ai_authored_flips_case2_to_fail(monkeypatch):
    """判定関数を「常にFalse」に壊すと、ケース②(bot最終コメント)が
    誤って未応答扱いされ、本来のアサーションが破綻することを確認する。
    (このテスト自体はpytest.raisesでAssertionErrorを捕まえてPASSする =
    検出ロジックが本当に is_ai_authored に依存していることの証明)
    """
    monkeypatch.setattr(gh_inbox, "is_ai_authored", lambda login, body: False)
    issues = [make_issue(1)]
    comments = [
        make_comment(101, 1, "pandrabox", "質問です", "2026-07-29T00:00:00Z"),
        make_comment(102, 1, "osaki-claude[bot]", "回答しました", "2026-07-30T00:00:00Z"),
    ]
    items = gh_inbox.find_unanswered(issues, comments)
    with pytest.raises(AssertionError):
        assert items == []  # 壊れているのでここは通らない(誤検出される)
    # 実際には誤って検出されてしまうことを確認
    assert [it["number"] for it in items] == [1]
