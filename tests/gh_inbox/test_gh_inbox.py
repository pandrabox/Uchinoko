"""gh_inbox.py の単体テスト。gh api 呼び出しはフィクスチャJSONに差し替える
(実ネットワークへは一切出ない)。"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import gh_inbox  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def conn(tmp_path):
    c = gh_inbox.connect(tmp_path / "state.db")
    yield c
    c.close()


def test_new_issue_and_new_comment_detection(conn):
    """初回sync相当: 新規issue検出 → 2回目sync: 新規コメント検出。"""
    detected = gh_inbox.now_gh_str()
    r1 = gh_inbox.apply_sync(conn, [load("issue_1_v1.json")], [], detected, record_unread=True)
    assert r1.new_issue == 1
    assert r1.comment == 0

    r2 = gh_inbox.apply_sync(
        conn,
        [load("issue_1_v1.json")],
        [load("comment_pandrabox_1.json"), load("comment_bot_1.json")],
        detected,
        record_unread=True,
    )
    assert r2.comment == 2
    assert r2.body_edit == 0
    assert r2.state_change == 0

    unread = conn.execute("SELECT * FROM unread WHERE kind='comment'").fetchall()
    assert len(unread) == 2
    authors = {row["author"] for row in unread}
    assert authors == {"pandrabox", "osaki-claude[bot]"}


def test_comment_edit_detection(conn):
    detected = gh_inbox.now_gh_str()
    gh_inbox.apply_sync(conn, [load("issue_1_v1.json")], [load("comment_pandrabox_1.json")], detected)
    r2 = gh_inbox.apply_sync(
        conn, [load("issue_1_v1.json")], [load("comment_pandrabox_1_edited.json")], detected
    )
    assert r2.comment == 0
    assert r2.comment_edit == 1


def test_body_edit_detection(conn):
    detected = gh_inbox.now_gh_str()
    gh_inbox.apply_sync(conn, [load("issue_1_v1.json")], [], detected)
    r2 = gh_inbox.apply_sync(conn, [load("issue_1_v2_body_edited.json")], [], detected)
    assert r2.body_edit == 1
    assert r2.state_change == 0
    # 本文が変わっていないさらなるsyncでは重複検出しない
    r3 = gh_inbox.apply_sync(conn, [load("issue_1_v2_body_edited.json")], [], detected)
    assert r3.body_edit == 0


def test_state_change_detection(conn):
    detected = gh_inbox.now_gh_str()
    gh_inbox.apply_sync(conn, [load("issue_1_v1.json")], [], detected)
    gh_inbox.apply_sync(conn, [load("issue_1_v2_body_edited.json")], [], detected)
    r3 = gh_inbox.apply_sync(conn, [load("issue_1_v3_closed.json")], [], detected)
    assert r3.state_change == 1
    row = conn.execute("SELECT state FROM issues WHERE number=1").fetchone()
    assert row["state"] == "closed"


def test_baseline_creates_no_unread(conn):
    detected = gh_inbox.now_gh_str()
    result = gh_inbox.apply_sync(
        conn,
        [load("issue_1_v1.json")],
        [load("comment_pandrabox_1.json")],
        detected,
        record_unread=False,
    )
    # 内部カウンタはインクリメントされない(record_unread=False)
    assert result.total == 0
    unread = conn.execute("SELECT COUNT(*) c FROM unread").fetchone()["c"]
    assert unread == 0
    # だがissues/comments_seenは埋まっている(以後のsyncが差分検出できる)
    assert conn.execute("SELECT COUNT(*) c FROM issues").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM comments_seen").fetchone()["c"] == 1


def test_ack_specific_issue(conn):
    detected = gh_inbox.now_gh_str()
    gh_inbox.apply_sync(conn, [load("issue_1_v1.json")], [], detected)
    unread_before = conn.execute("SELECT COUNT(*) c FROM unread WHERE acked=0").fetchone()["c"]
    assert unread_before == 1
    gh_inbox.cmd_ack(conn, [1], False)
    unread_after = conn.execute("SELECT COUNT(*) c FROM unread WHERE acked=0").fetchone()["c"]
    assert unread_after == 0


def test_ack_all(conn):
    detected = gh_inbox.now_gh_str()
    gh_inbox.apply_sync(conn, [load("issue_1_v1.json")], [load("comment_pandrabox_1.json")], detected)
    assert conn.execute("SELECT COUNT(*) c FROM unread WHERE acked=0").fetchone()["c"] == 2
    gh_inbox.cmd_ack(conn, [], True)
    assert conn.execute("SELECT COUNT(*) c FROM unread WHERE acked=0").fetchone()["c"] == 0


def test_status_counts_pandrabox_separately(conn, capsys):
    detected = gh_inbox.now_gh_str()
    gh_inbox.apply_sync(conn, [load("issue_1_v1.json")], [load("comment_pandrabox_1.json"), load("comment_bot_1.json")], detected)
    gh_inbox.cmd_status(conn)
    out = capsys.readouterr().out
    assert "未読3件" in out
    assert "ぱん1件" in out


def test_pandrabox_marked_and_sorted_first(conn):
    """★ぱんマーク付与+並び順(pandrabox優先)の確認。"""
    detected = gh_inbox.now_gh_str()
    gh_inbox.apply_sync(
        conn,
        [load("issue_1_v1.json")],
        [load("comment_bot_1.json"), load("comment_pandrabox_1.json")],
        detected,
    )
    report = gh_inbox.format_unread_report(conn)
    lines = report.splitlines()
    pandrabox_lines = [l for l in lines if "★ぱん" in l]
    assert len(pandrabox_lines) == 1
    # pandraboxの行が非pandrabox行より前に来ている
    assert lines.index(pandrabox_lines[0]) < len(lines) - 1
    non_pandrabox = [l for l in lines if "★ぱん" not in l and l != "未読なし"]
    if non_pandrabox:
        assert lines.index(pandrabox_lines[0]) < lines.index(non_pandrabox[0])


def test_recent_pandrabox_activity_24h_window():
    now = datetime.now(timezone.utc)
    recent_time = (now - timedelta(hours=1)).strftime(gh_inbox.GH_TIME_FMT)
    old_time = (now - timedelta(hours=48)).strftime(gh_inbox.GH_TIME_FMT)

    comments = [
        {
            "id": 1,
            "issue_url": "https://api.github.com/repos/pandrabox/DiveToPalworld-dev/issues/5",
            "user": {"login": "pandrabox"},
            "created_at": recent_time,
            "updated_at": recent_time,
            "body": "recent comment",
        },
        {
            "id": 2,
            "issue_url": "https://api.github.com/repos/pandrabox/DiveToPalworld-dev/issues/6",
            "user": {"login": "pandrabox"},
            "created_at": old_time,
            "updated_at": old_time,
            "body": "old comment, should be excluded",
        },
        {
            "id": 3,
            "issue_url": "https://api.github.com/repos/pandrabox/DiveToPalworld-dev/issues/7",
            "user": {"login": "osaki-claude[bot]"},
            "created_at": recent_time,
            "updated_at": recent_time,
            "body": "not pandrabox, should be excluded",
        },
    ]
    items = gh_inbox.recent_pandrabox_activity([], comments, hours=24)
    assert len(items) == 1
    assert items[0]["issue_number"] == 5


def test_pull_requests_are_excluded(conn):
    detected = gh_inbox.now_gh_str()
    pr = dict(load("issue_1_v1.json"))
    pr["number"] = 99
    pr["pull_request"] = {"url": "https://api.github.com/repos/pandrabox/DiveToPalworld-dev/pulls/99"}
    result = gh_inbox.apply_sync(conn, [pr], [], detected)
    assert result.new_issue == 0
    assert conn.execute("SELECT COUNT(*) c FROM issues WHERE number=99").fetchone()["c"] == 0


def test_sync_wiring_uses_since_from_meta(conn, monkeypatch):
    """cmd_syncがmeta.last_sync_sinceを正しく読み書きし、fetch関数へ渡すことを確認。"""
    calls = {}

    def fake_fetch_issues(since):
        calls["issues_since"] = since
        return [load("issue_1_v1.json")]

    def fake_fetch_comments(since):
        calls["comments_since"] = since
        return []

    monkeypatch.setattr(gh_inbox, "fetch_updated_issues", fake_fetch_issues)
    monkeypatch.setattr(gh_inbox, "fetch_updated_comments", fake_fetch_comments)

    gh_inbox.cmd_sync(conn)
    assert calls["issues_since"] is None  # 初回はsinceなし
    saved = gh_inbox.get_meta(conn, "last_sync_since")
    assert saved is not None

    gh_inbox.cmd_sync(conn)
    assert calls["issues_since"] == saved  # 2回目は前回の watermark を使う
