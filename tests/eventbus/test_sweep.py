# -*- coding: utf-8 -*-
"""devtools/eventbus/sweep.py の単体テスト。実ネットワーク・実DBなし。"""
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
EVENTBUS_DIR = DEVTOOLS / "eventbus"
for p in (str(DEVTOOLS), str(EVENTBUS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import sweep  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_eventbus_state_dir(tmp_path, monkeypatch):
    """このファイル全体でhook_error.log等の書き込み先を隔離する。

    dev#504/#507のサポート系テストは意図的な失敗パスで common.log_hook_error を
    経由するため、EVENTBUS_STATE_DIR未設定だと実リポジトリの
    .devonly\\state\\eventbus\\hook_error.log を汚してしまう。個別クラスが独自の
    isolated_state フィクスチャで上書きする場合もあるが、それらも同じ趣旨で
    tmp_path配下を指すため無害に重複するだけ。"""
    monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path / "eventbus_state"))


def _comment(issue_url, login, created_at, body=""):
    return {
        "issue_url": issue_url,
        "user": {"login": login},
        "created_at": created_at,
        "body": body,
    }


def _issue(number, title="title", login="pandrabox", created_at="2026-07-01T00:00:00Z", body=""):
    return {
        "number": number,
        "title": title,
        "user": {"login": login},
        "created_at": created_at,
        "body": body,
    }


ISSUE_URL = "https://api.github.com/repos/pandrabox/DiveToPalworld-dev/issues/{}"


# ---------------------------------------------------------------------------
# 最終コメント者述語
# ---------------------------------------------------------------------------

class TestLastActorPredicate:
    def test_bot_last_comment_excluded(self):
        """最終コメントがosaki-claude[bot]なら検知対象から除外される。"""
        issues = [_issue(1, login="pandrabox")]
        comments = [
            _comment(ISSUE_URL.format(1), "pandrabox", "2026-07-01T01:00:00Z"),
            _comment(ISSUE_URL.format(1), "osaki-claude[bot]", "2026-07-01T02:00:00Z"),
        ]
        result = sweep._last_human_activity(issues, comments)
        assert result == []

    def test_human_last_comment_included(self):
        """最終コメントが人間(bot以外)なら検知対象に含まれる。"""
        issues = [_issue(2, login="pandrabox")]
        comments = [
            _comment(ISSUE_URL.format(2), "osaki-claude[bot]", "2026-07-01T01:00:00Z"),
            _comment(ISSUE_URL.format(2), "some_external_user", "2026-07-01T02:00:00Z"),
        ]
        result = sweep._last_human_activity(issues, comments)
        assert len(result) == 1
        assert result[0]["number"] == 2
        assert result[0]["actor"] == "some_external_user"

    def test_pandrabox_last_comment_flagged_pan(self):
        """actor=pandraboxはpan=Trueで最優先扱い(dev#452追補1)。"""
        issues = [_issue(3, login="pandrabox")]
        comments = [
            _comment(ISSUE_URL.format(3), "osaki-claude[bot]", "2026-07-01T01:00:00Z"),
            _comment(ISSUE_URL.format(3), "pandrabox", "2026-07-01T02:00:00Z"),
        ]
        events = sweep.detect_issue_events(issues, comments, Path("nonexistent.db"),
                                            datetime(2026, 7, 1, 3, tzinfo=timezone.utc))
        assert len(events) == 1
        assert events[0]["pan"] is True
        assert events[0]["urgent"] is True  # panは即urgent

    def test_zero_comments_pandrabox_body_author_included(self):
        """コメント0件でissue本文の起票者がpandraboxなら検知対象。"""
        issues = [_issue(4, login="pandrabox", created_at="2026-07-01T00:00:00Z")]
        comments = []
        result = sweep._last_human_activity(issues, comments)
        assert len(result) == 1
        assert result[0]["actor"] == "pandrabox"

    def test_zero_comments_bot_body_author_excluded(self):
        """コメント0件でissue本文の起票者がAIなら除外(通常起票しない想定だが念のため)。"""
        issues = [_issue(5, login="osaki-claude[bot]")]
        comments = []
        result = sweep._last_human_activity(issues, comments)
        assert result == []

    def test_unread_count_unknown_when_db_missing(self):
        """gh-inbox DBが読めない場合は偽値で埋めず'unknown'を返す。"""
        count = sweep._unread_count_for_issue(Path("C:\\definitely\\not\\exist\\state.db"), 123)
        assert count == "unknown"


# ---------------------------------------------------------------------------
# 重複更新(同一ソースの連続検知は1件に集約・更新)
# ---------------------------------------------------------------------------

class TestMergeDedup:
    def test_duplicate_detection_does_not_duplicate_entry(self):
        now1 = "2026-07-31T10:00:00Z"
        detected = [{
            "key": "issue:99", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 99, "fingerprint": "fp1", "summary": "summary v1",
        }]
        q1 = sweep.merge_into_queue({}, detected, {}, now1)
        assert len(q1) == 1
        assert q1["issue:99"].first_seen == now1

        now2 = "2026-07-31T10:05:00Z"
        detected2 = [{
            "key": "issue:99", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 99, "fingerprint": "fp1", "summary": "summary v1",
        }]
        q2 = sweep.merge_into_queue(q1, detected2, {}, now2)
        assert len(q2) == 1  # 重複追加されない
        assert q2["issue:99"].first_seen == now1  # first_seenは引き継がれる
        assert q2["issue:99"].last_seen == now2

    def test_fingerprint_change_resets_delivered(self):
        """新しい活動(fingerprint変化)があれば delivered をリセットして再表示する。"""
        now1 = "2026-07-31T10:00:00Z"
        detected = [{
            "key": "issue:100", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 100, "fingerprint": "fp1", "summary": "v1",
        }]
        q1 = sweep.merge_into_queue({}, detected, {}, now1)
        q1["issue:100"].delivered = True  # 配達済みにしておく

        now2 = "2026-07-31T11:00:00Z"
        detected2 = [{
            "key": "issue:100", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 100, "fingerprint": "fp2", "summary": "v2",
        }]
        q2 = sweep.merge_into_queue(q1, detected2, {}, now2)
        assert q2["issue:100"].delivered is False
        assert q2["issue:100"].summary == "v2"

    def test_acked_unchanged_fingerprint_is_suppressed(self):
        """ack済み・かつ変化なし(fingerprint一致)なら自己修復的に再表示しない。"""
        detected = [{
            "key": "issue:101", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 101, "fingerprint": "fp1", "summary": "v1",
        }]
        acked_fp = {"issue:101": "fp1"}
        q = sweep.merge_into_queue({}, detected, acked_fp, "2026-07-31T10:00:00Z")
        assert q == {}

    def test_acked_but_new_fingerprint_reappears(self):
        """ack後に新しい活動(fingerprint変化)があれば再度キューへ現れる。"""
        detected = [{
            "key": "issue:102", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 102, "fingerprint": "fp2", "summary": "v2",
        }]
        acked_fp = {"issue:102": "fp1"}  # 古いfingerprintでack済み
        q = sweep.merge_into_queue({}, detected, acked_fp, "2026-07-31T10:00:00Z")
        assert "issue:102" in q


# ---------------------------------------------------------------------------
# 4時間昇格
# ---------------------------------------------------------------------------

class TestPromotion:
    def test_promotes_after_4_hours(self):
        first_seen = "2026-07-31T06:00:00Z"  # now(10:00)から4時間前
        old_queue = {
            "issue:200": common.Event(
                key="issue:200", kind="issue_human", urgent=False, pan=False,
                issue_number=200, fingerprint="fp1", summary="v1",
                first_seen=first_seen, last_seen=first_seen, delivered=True,
            )
        }
        detected = [{
            "key": "issue:200", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 200, "fingerprint": "fp1", "summary": "v1",
        }]
        now = "2026-07-31T10:00:00Z"
        q = sweep.merge_into_queue(old_queue, detected, {}, now)
        assert q["issue:200"].urgent is True
        assert q["issue:200"].delivered is False  # 昇格は再度目立たせる

    def test_not_promoted_before_4_hours(self):
        first_seen = "2026-07-31T07:00:00Z"  # now(10:00)から3時間前
        old_queue = {
            "issue:201": common.Event(
                key="issue:201", kind="issue_human", urgent=False, pan=False,
                issue_number=201, fingerprint="fp1", summary="v1",
                first_seen=first_seen, last_seen=first_seen, delivered=True,
            )
        }
        detected = [{
            "key": "issue:201", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 201, "fingerprint": "fp1", "summary": "v1",
        }]
        now = "2026-07-31T10:00:00Z"
        q = sweep.merge_into_queue(old_queue, detected, {}, now)
        assert q["issue:201"].urgent is False
        assert q["issue:201"].delivered is True

    def test_pan_event_urgent_immediately_no_wait(self):
        """pan=Trueは初回検知から即urgent(4時間を待たない)。"""
        detected = [{
            "key": "issue:202", "kind": "issue_human", "urgent": True, "pan": True,
            "issue_number": 202, "fingerprint": "fp1", "summary": "v1",
        }]
        q = sweep.merge_into_queue({}, detected, {}, "2026-07-31T10:00:00Z")
        assert q["issue:202"].urgent is True


# ---------------------------------------------------------------------------
# B4/B5/B6 純関数
# ---------------------------------------------------------------------------

class TestCanaryAndCiAndFreshness:
    def test_canary_red_detected(self):
        latest = {"filename": "20260731T100000Z.json", "data": {"verdict": "RED", "reason": "検出"}}
        ev = sweep.detect_canary_event(latest)
        assert ev is not None
        assert ev["urgent"] is True
        assert ev["key"] == "canary"

    def test_canary_green_not_detected(self):
        latest = {"filename": "20260731T100000Z.json", "data": {"verdict": "GREEN"}}
        assert sweep.detect_canary_event(latest) is None

    def test_canary_none_not_detected(self):
        assert sweep.detect_canary_event(None) is None

    def test_master_ci_failure_detected(self):
        run = {"status": "completed", "conclusion": "failure", "id": 42, "html_url": "https://x"}
        ev = sweep.detect_master_ci_event(run)
        assert ev is not None
        assert ev["fingerprint"] == "42"

    def test_master_ci_success_not_detected(self):
        run = {"status": "completed", "conclusion": "success", "id": 42}
        assert sweep.detect_master_ci_event(run) is None

    def test_master_ci_in_progress_not_detected(self):
        run = {"status": "in_progress", "conclusion": None, "id": 42}
        assert sweep.detect_master_ci_event(run) is None

    def test_canary_staleness_detected(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        latest = {"filename": "20260730T090000Z.json", "data": {}}  # 27時間前
        events = sweep.detect_freshness_events(now, latest, disk_free_gb=200, last_sweep_at=None)
        keys = [e["key"] for e in events]
        assert "freshness:canary_stale" in keys

    def test_canary_not_stale_within_threshold(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        latest = {"filename": "20260731T000000Z.json", "data": {}}  # 12時間前
        events = sweep.detect_freshness_events(now, latest, disk_free_gb=200, last_sweep_at=None)
        keys = [e["key"] for e in events]
        assert "freshness:canary_stale" not in keys

    def test_disk_low_detected(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        events = sweep.detect_freshness_events(now, None, disk_free_gb=10, last_sweep_at=None)
        keys = [e["key"] for e in events]
        assert "freshness:disk" in keys

    def test_disk_ok_not_detected(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        events = sweep.detect_freshness_events(now, None, disk_free_gb=200, last_sweep_at=None)
        keys = [e["key"] for e in events]
        assert "freshness:disk" not in keys

    def test_sweep_gap_detected(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        last_sweep_at = "2026-07-31T11:00:00Z"  # 60分前 > 15分閾値
        events = sweep.detect_freshness_events(now, None, disk_free_gb=200, last_sweep_at=last_sweep_at)
        keys = [e["key"] for e in events]
        assert "freshness:sweep_gap" in keys

    def test_sweep_gap_not_detected_within_threshold(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        last_sweep_at = "2026-07-31T11:57:00Z"  # 3分前
        events = sweep.detect_freshness_events(now, None, disk_free_gb=200, last_sweep_at=last_sweep_at)
        keys = [e["key"] for e in events]
        assert "freshness:sweep_gap" not in keys


# ---------------------------------------------------------------------------
# dev#570: net_watch 見張りの見張り(ハートビート停止検知)
# ---------------------------------------------------------------------------

class TestNetWatchStoppedDetection:
    def test_stale_heartbeat_detected(self):
        """ハートビートがしきい値超過して古ければ『見張り停止』イベントを返す。"""
        now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        heartbeat_iso = "2026-08-01T11:58:00Z"  # 120秒前 > 60秒しきい値
        ev = sweep.detect_net_watch_stopped_event(now, heartbeat_iso, stale_seconds=60)
        assert ev is not None
        assert ev["key"] == "freshness:net_watch_stopped"
        assert ev["urgent"] is True

    def test_fresh_heartbeat_not_detected(self):
        """負の対照: 正常稼働中(しきい値以内)はイベントを生成しない。"""
        now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        heartbeat_iso = "2026-08-01T11:59:30Z"  # 30秒前 <= 60秒しきい値
        ev = sweep.detect_net_watch_stopped_event(now, heartbeat_iso, stale_seconds=60)
        assert ev is None

    def test_missing_heartbeat_not_detected(self):
        """ハートビートファイルが存在しない(デーモン未起動)場合は検知しない
        (常駐の起動登録はオーナー承認後の任意運用のため、未起動を停止として
        警告し続けるのは誤検知)。"""
        now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev = sweep.detect_net_watch_stopped_event(now, None, stale_seconds=60)
        assert ev is None

    def test_malformed_heartbeat_not_detected(self):
        """壊れたタイムスタンプは安全側で検知しない(通知本体の生成を止めない)。"""
        now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev = sweep.detect_net_watch_stopped_event(now, "not-a-timestamp", stale_seconds=60)
        assert ev is None

    def test_real_read_heartbeat_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path / "eventbus_state"))
        assert sweep._real_read_net_watch_heartbeat() is None

    def test_real_read_heartbeat_present_returns_content(self, tmp_path, monkeypatch):
        state_dir = tmp_path / "eventbus_state"
        monkeypatch.setenv("EVENTBUS_STATE_DIR", str(state_dir))
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "net_watch_heartbeat.txt").write_text("2026-08-01T12:00:00Z", encoding="utf-8")
        assert sweep._real_read_net_watch_heartbeat() == "2026-08-01T12:00:00Z"


# ---------------------------------------------------------------------------
# dev#504: ぱん声スニペット配達(最終発言者=pandraboxのとき本文冒頭80字を同梱)
# ---------------------------------------------------------------------------

class TestPanSnippet:
    def test_pan_comment_snippet_included_in_summary(self):
        issues = [_issue(300, login="pandrabox")]
        comments = [
            _comment(ISSUE_URL.format(300), "osaki-claude[bot]", "2026-07-01T01:00:00Z"),
            _comment(ISSUE_URL.format(300), "pandrabox", "2026-07-01T02:00:00Z",
                     body="やまびこ\n2行目は含まれないはず"),
        ]
        events = sweep.detect_issue_events(issues, comments, Path("nonexistent.db"),
                                            datetime(2026, 7, 1, 3, tzinfo=timezone.utc))
        assert len(events) == 1
        assert "やまびこ" in events[0]["summary"]
        assert "2行目" not in events[0]["summary"]

    def test_pan_snippet_truncated_to_80_chars(self):
        long_body = "あ" * 100
        issues = [_issue(301, login="pandrabox")]
        comments = [_comment(ISSUE_URL.format(301), "pandrabox", "2026-07-01T02:00:00Z", body=long_body)]
        events = sweep.detect_issue_events(issues, comments, Path("nonexistent.db"),
                                            datetime(2026, 7, 1, 3, tzinfo=timezone.utc))
        snippet = events[0]["summary"].rsplit("— ", 1)[-1]
        assert len(snippet) == 80

    def test_non_pan_comment_has_no_snippet_appended(self):
        issues = [_issue(302, login="pandrabox")]
        comments = [_comment(ISSUE_URL.format(302), "some_external_user",
                              "2026-07-01T02:00:00Z", body="hello there")]
        events = sweep.detect_issue_events(issues, comments, Path("nonexistent.db"),
                                            datetime(2026, 7, 1, 3, tzinfo=timezone.utc))
        assert len(events) == 1
        assert "hello there" not in events[0]["summary"]

    def test_pan_empty_body_appends_no_snippet(self):
        issues = [_issue(303, login="pandrabox")]
        comments = [_comment(ISSUE_URL.format(303), "pandrabox", "2026-07-01T02:00:00Z", body="")]
        events = sweep.detect_issue_events(issues, comments, Path("nonexistent.db"),
                                            datetime(2026, 7, 1, 3, tzinfo=timezone.utc))
        assert "— " not in events[0]["summary"]


# ---------------------------------------------------------------------------
# dev#531: 通知の詳細行(初回配達のみ)の材料(title/actor/excerpt)
# ---------------------------------------------------------------------------

class TestIssueHumanDetailFields:
    def test_detect_issue_events_includes_title_actor_excerpt_for_non_pan(self):
        """非panでも title/actor/excerpt は常に格納される(summaryへの抜粋付与は
        pan限定のまま——dev#531の詳細行はsummaryと独立した材料を使うため)。"""
        issues = [_issue(310, title="タイトルです", login="pandrabox")]
        comments = [_comment(ISSUE_URL.format(310), "some_external_user",
                              "2026-07-01T02:00:00Z", body="非pan本文の抜粋テスト\n2行目")]
        events = sweep.detect_issue_events(issues, comments, Path("nonexistent.db"),
                                            datetime(2026, 7, 1, 3, tzinfo=timezone.utc))
        assert events[0]["title"] == "タイトルです"
        assert events[0]["actor"] == "some_external_user"
        assert events[0]["excerpt"] == "非pan本文の抜粋テスト"
        assert "非pan本文の抜粋テスト" not in events[0]["summary"]  # summaryは従来どおり不変

    def test_detect_issue_events_pan_excerpt_matches_summary_snippet(self):
        issues = [_issue(311, title="T", login="pandrabox")]
        comments = [_comment(ISSUE_URL.format(311), "pandrabox", "2026-07-01T02:00:00Z",
                              body="ぱんの発言抜粋")]
        events = sweep.detect_issue_events(issues, comments, Path("nonexistent.db"),
                                            datetime(2026, 7, 1, 3, tzinfo=timezone.utc))
        assert events[0]["excerpt"] == "ぱんの発言抜粋"
        assert "ぱんの発言抜粋" in events[0]["summary"]  # pan時はsummaryにも従来どおり含む

    def test_merge_into_queue_carries_title_actor_excerpt_into_event(self):
        detected = [{
            "key": "issue:399", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 399, "fingerprint": "fp1", "summary": "v1",
            "title": "T399", "actor": "A399", "excerpt": "E399",
        }]
        q = sweep.merge_into_queue({}, detected, {}, "2026-07-31T10:00:00Z")
        assert q["issue:399"].title == "T399"
        assert q["issue:399"].actor == "A399"
        assert q["issue:399"].excerpt == "E399"

    def test_merge_into_queue_defaults_missing_detail_fields_to_none(self):
        """title/actor/excerptを持たない検出辞書(他kindや旧形式)でも例外にならず
        Noneのままマージされる(後方互換)。"""
        detected = [{
            "key": "issue:400", "kind": "issue_human", "urgent": False, "pan": False,
            "issue_number": 400, "fingerprint": "fp1", "summary": "v1",
        }]
        q = sweep.merge_into_queue({}, detected, {}, "2026-07-31T10:00:00Z")
        assert q["issue:400"].title is None
        assert q["issue:400"].actor is None
        assert q["issue:400"].excerpt is None


# ---------------------------------------------------------------------------
# dev#504: gh-inbox 未読カウンタ偽0の修正(sweep自身がDBを最新化する)
# ---------------------------------------------------------------------------

class TestGhInboxDbSync:
    def test_new_pandrabox_comment_becomes_unread_after_sweep_sync(self, tmp_path):
        """やまびこ/ふうせん再現: 既知issueへの新規pandraboxコメントは、sweepが
        DBを同期するまでは未読0(旧バグ)、同期後は未読>=1になる。"""
        db_path = tmp_path / "state.db"
        issue_number = 491
        issues = [_issue(issue_number, login="pandrabox", created_at="2026-07-01T00:00:00Z")]
        old_comment = _comment(ISSUE_URL.format(issue_number), "osaki-claude[bot]",
                                "2026-07-01T01:00:00Z", body="past reply")
        old_comment["id"] = 1001  # apply_syncはcomments_seenのキーにcomment idを使う

        # baseline: 既存の会話(AIの返信まで)を既読として初期化しておく
        conn = sweep.gh_inbox.connect(db_path)
        sweep.gh_inbox.apply_sync(conn, issues, [old_comment], "2026-07-01T02:00:00Z",
                                   record_unread=False)
        conn.commit()
        conn.close()

        # 負の対照(旧バグの再現): DB同期を挟まなければ、ぱんの新規コメントが
        # 実在しても未読は0のまま
        assert sweep._unread_count_for_issue(db_path, issue_number) == 0

        new_comment = _comment(ISSUE_URL.format(issue_number), "pandrabox",
                                "2026-08-01T05:00:00Z", body="やまびこ")
        new_comment["id"] = 1002
        comments = [old_comment, new_comment]

        sweep._sync_gh_inbox_db(issues, comments, db_path, "2026-08-01T05:05:00Z")
        assert sweep._unread_count_for_issue(db_path, issue_number) >= 1

        # 同一内容で再度syncしても二重計上しない(冪等性)
        count_after_first = sweep._unread_count_for_issue(db_path, issue_number)
        sweep._sync_gh_inbox_db(issues, comments, db_path, "2026-08-01T05:10:00Z")
        assert sweep._unread_count_for_issue(db_path, issue_number) == count_after_first

    def test_sync_failure_is_best_effort_and_does_not_raise(self, tmp_path, monkeypatch):
        """DB書き込みが失敗しても(例: 壊れたパス)sweep全体を落とさない。"""
        def boom(*a, **kw):
            raise sqlite3.OperationalError("simulated failure")
        monkeypatch.setattr(sweep.gh_inbox, "connect", boom)
        # 例外を送出しないことだけを確認する(戻り値はNone)
        sweep._sync_gh_inbox_db([], [], tmp_path / "unreachable.db", "2026-08-01T00:00:00Z")


# ---------------------------------------------------------------------------
# dev#507: サポートinbox新着検知(4時間未満は例外なく対象外というぱん裁定込み)
# ---------------------------------------------------------------------------

class TestSupportNewDetection:
    def test_detects_item_past_4h_threshold(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        items = [{"id": "ABCD1234", "status": "new", "lastAt": "2026-08-01T07:00:00Z",
                  "preview": "困っています"}]
        events = sweep.detect_support_new_events(items, now)
        assert len(events) == 1
        assert events[0]["key"] == "support:ABCD1234"
        assert events[0]["kind"] == "support_new"
        assert events[0]["urgent"] is True  # dev#507: 最上位区分
        assert "サポート新着: ABCD1234" in events[0]["summary"]
        assert "困っています" in events[0]["summary"]

    def test_negative_control_under_4h_not_detected(self):
        """ぱん裁定(2026-08-01追補): 最終ユーザー発言から4時間未満は例外なく検知対象外。"""
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        items = [{"id": "FRESH001", "status": "new", "lastAt": "2026-08-01T09:00:00Z",
                  "preview": "たった今来た"}]
        events = sweep.detect_support_new_events(items, now)
        assert events == []

    def test_exactly_4h_boundary_is_detected(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        items = [{"id": "EDGE0001", "status": "new", "lastAt": "2026-08-01T08:00:00Z"}]
        events = sweep.detect_support_new_events(items, now)
        assert len(events) == 1

    def test_summary_preview_truncated_to_20_chars(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        long_preview = "あ" * 50
        items = [{"id": "LONGPRE1", "status": "new", "lastAt": "2026-08-01T00:00:00Z",
                  "preview": long_preview}]
        events = sweep.detect_support_new_events(items, now)
        preview_part = events[0]["summary"].split("LONGPRE1 ", 1)[-1]
        assert len(preview_part) == 20

    def test_missing_id_is_skipped(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        items = [{"status": "new", "lastAt": "2026-08-01T00:00:00Z"}]
        assert sweep.detect_support_new_events(items, now) == []

    def test_malformed_lastAt_is_skipped_safely(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        items = [{"id": "BADTIME1", "status": "new", "lastAt": "not-a-timestamp"}]
        assert sweep.detect_support_new_events(items, now) == []

    def test_missing_lastAt_is_skipped_safely(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        items = [{"id": "NOTIME001", "status": "new"}]
        assert sweep.detect_support_new_events(items, now) == []


class TestSupportSayShouldFire:
    def test_fires_for_brand_new_item(self):
        detected = [{"key": "support:X1", "fingerprint": "fp1"}]
        assert sweep.support_say_should_fire(detected, {}, {}) is True

    def test_does_not_fire_for_unchanged_existing_item(self):
        existing_queue = {"support:X1": common.Event(
            key="support:X1", kind="support_new", urgent=True, fingerprint="fp1",
            summary="s", first_seen="t", last_seen="t")}
        detected = [{"key": "support:X1", "fingerprint": "fp1"}]
        assert sweep.support_say_should_fire(detected, existing_queue, {}) is False

    def test_fires_when_fingerprint_changes(self):
        existing_queue = {"support:X1": common.Event(
            key="support:X1", kind="support_new", urgent=True, fingerprint="fp1",
            summary="s", first_seen="t", last_seen="t")}
        detected = [{"key": "support:X1", "fingerprint": "fp2"}]
        assert sweep.support_say_should_fire(detected, existing_queue, {}) is True

    def test_does_not_fire_when_acked_and_unchanged(self):
        detected = [{"key": "support:X1", "fingerprint": "fp1"}]
        acked_fp = {"support:X1": "fp1"}
        assert sweep.support_say_should_fire(detected, {}, acked_fp) is False

    def test_no_items_no_fire(self):
        assert sweep.support_say_should_fire([], {}, {}) is False


class TestRealFetchSupportUnanswered:
    def test_calls_with_4h_threshold_and_extracts_preview(self, monkeypatch):
        calls = []

        def fake_api(method, path, params=None, body=None):
            calls.append((method, path, params))
            if path == "/admin/unanswered":
                return {"items": [{"id": "ITEM0001", "status": "new",
                                    "lastAt": "2026-08-01T00:00:00Z"}]}
            if path == "/admin/item":
                return {"messages": [
                    {"sender": "support", "body": "support側の返信は無視", "created_at": "2026-07-31T00:00:00Z"},
                    {"sender": "user", "body": "本文冒頭\n2行目は使わない", "created_at": "2026-08-01T00:00:00Z"},
                ]}
            raise AssertionError(f"unexpected path {path}")

        monkeypatch.setattr(sweep.support_client, "api", fake_api)
        items = sweep._real_fetch_support_unanswered()
        assert calls[0] == ("GET", "/admin/unanswered", {"hours": sweep.SUPPORT_MIN_UNANSWERED_HOURS})
        assert items[0]["preview"] == "本文冒頭"

    def test_returns_empty_list_on_api_failure(self, monkeypatch):
        def fake_api(*a, **kw):
            raise SystemExit("boom")
        monkeypatch.setattr(sweep.support_client, "api", fake_api)
        assert sweep._real_fetch_support_unanswered() == []

    def test_item_detail_failure_falls_back_to_empty_preview(self, monkeypatch):
        def fake_api(method, path, params=None, body=None):
            if path == "/admin/unanswered":
                return {"items": [{"id": "ITEM0002", "status": "new",
                                    "lastAt": "2026-08-01T00:00:00Z"}]}
            raise SystemExit("item detail unavailable")
        monkeypatch.setattr(sweep.support_client, "api", fake_api)
        items = sweep._real_fetch_support_unanswered()
        assert items[0]["preview"] == ""


class TestFireSupportSay:
    def test_invokes_say_notice_with_no_window(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
        monkeypatch.setattr(sweep.subprocess, "run", fake_run)
        sweep._fire_support_say()
        assert len(calls) == 1
        cmd, kwargs = calls[0]
        assert cmd[1] == str(sweep.SAY_PY)
        assert cmd[2] == "notice"
        assert kwargs.get("creationflags") == sweep._NO_WINDOW

    def test_failure_is_swallowed(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise OSError("no powershell")
        monkeypatch.setattr(sweep.subprocess, "run", fake_run)
        sweep._fire_support_say()  # 例外を送出しないことだけを確認


# ---------------------------------------------------------------------------
# run_sweep() 統合(全ての_real_fetch_*をモックし、実ネットワーク・実DBなし)
# ---------------------------------------------------------------------------

class TestRunSweepSupportIntegration:
    @pytest.fixture(autouse=True)
    def isolated_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path / "eventbus"))
        monkeypatch.setenv("EVENTBUS_GH_INBOX_DB", str(tmp_path / "gh_inbox" / "state.db"))
        yield tmp_path

    def _patch_non_support_fetches(self, monkeypatch):
        monkeypatch.setattr(sweep, "_real_fetch_issues_and_comments", lambda: ([], []))
        monkeypatch.setattr(sweep, "_real_fetch_canary_results", lambda d: [])
        monkeypatch.setattr(sweep, "_real_fetch_master_ci_run", lambda: None)
        monkeypatch.setattr(sweep, "_real_disk_free_gb", lambda p: 200.0)

    def test_support_new_item_queued_and_say_fires_once_then_suppressed(self, monkeypatch):
        self._patch_non_support_fetches(monkeypatch)
        say_calls = []
        monkeypatch.setattr(sweep, "_fire_support_say", lambda: say_calls.append(1))
        support_item = {"id": "S0000001", "status": "new", "lastAt": "2026-08-01T00:00:00Z",
                         "preview": "困っています"}
        monkeypatch.setattr(sweep, "_real_fetch_support_unanswered", lambda: [support_item])
        # lastAtから6時間後(4h閾値を超過)に固定する
        monkeypatch.setattr(common, "now_iso", lambda: "2026-08-01T06:00:00Z")

        summary = sweep.run_sweep()
        assert summary["urgent"] == 1
        assert len(say_calls) == 1

        queue = common.load_queue()
        assert "support:S0000001" in queue
        assert queue["support:S0000001"].urgent is True
        assert "困っています" in queue["support:S0000001"].summary

        # 2回目の掃引: 内容が変化していないので再発火しない(dev#507「5分ごとに繰り返さない」)
        summary2 = sweep.run_sweep()
        assert len(say_calls) == 1

    def test_support_item_under_4h_negative_control(self, monkeypatch):
        """負の対照: 4時間未満の模擬新着は検知・キュー投入・say通知いずれもされない。"""
        self._patch_non_support_fetches(monkeypatch)
        say_calls = []
        monkeypatch.setattr(sweep, "_fire_support_say", lambda: say_calls.append(1))
        support_item = {"id": "FRESH001", "status": "new", "lastAt": "2026-08-01T05:30:00Z",
                         "preview": "たった今"}
        monkeypatch.setattr(sweep, "_real_fetch_support_unanswered", lambda: [support_item])
        # lastAtから30分後(4h未満)に固定する
        monkeypatch.setattr(common, "now_iso", lambda: "2026-08-01T06:00:00Z")

        summary = sweep.run_sweep()
        assert summary["urgent"] == 0
        assert say_calls == []
        queue = common.load_queue()
        assert "support:FRESH001" not in queue


# ---------------------------------------------------------------------------
# 否認キュー(2026-08-01、ぱん直命): 2026-07-30から2件放置事故の再発防止。
# 実在の否認2件(Z8XBKJBC/VLGQR7ES)を模したフィクスチャで検証する。
# ---------------------------------------------------------------------------

DENIED_ITEM_Z8XBKJBC = {
    "id": "Z8XBKJBC", "source": "tool", "status": "triaged", "contact": None,
    "draft": "旧ドラフト本文",
    "draft_denied_at": "2026-07-30T02:00:00.000Z",
    "draft_denied_reason": "非公開githubのissuesを貼ってはいけない(1件目)",
}
DENIED_ITEM_VLGQR7ES = {
    "id": "VLGQR7ES", "source": "tool", "status": "triaged", "contact": None,
    "draft": "Thank you for using Uchinoko for Palworld.",
    "draft_denied_at": "2026-07-30T04:17:27.590Z",
    "draft_denied_reason": "非公開githubのissuesを貼ってはいけない",
}


class TestDeniedDetection:
    def test_two_real_denied_items_detected_as_single_aggregate_event(self):
        """実在の否認2件(Z8XBKJBC/VLGQR7ES)相当のフィクスチャが1件の集約イベントに
        まとまり、件数・IDが正しく反映されること。"""
        events = sweep.detect_denied_events([DENIED_ITEM_Z8XBKJBC, DENIED_ITEM_VLGQR7ES])
        assert len(events) == 1
        ev = events[0]
        assert ev["key"] == "denied_queue"
        assert ev["kind"] == "denied"
        assert ev["urgent"] is True  # 最上位区分
        assert ev["count"] == 2
        assert "否認キュー: 2件書き直し待ち" in ev["summary"]
        # 代表は draft_denied_at が最も古い方(Z8XBKJBC)
        assert "Z8XBKJBC" in ev["summary"]
        assert "非公開githubのissuesを貼ってはいけない(1件目)"[:30] in ev["summary"]

    def test_negative_control_zero_denied_no_event(self):
        """負の対照: 否認ゼロならイベントが1件も出ない。"""
        assert sweep.detect_denied_events([]) == []

    def test_reason_snippet_truncated_to_30_chars(self):
        long_reason = "あ" * 50
        item = {"id": "LONGR001", "draft_denied_at": "2026-07-30T00:00:00Z",
                "draft_denied_reason": long_reason}
        events = sweep.detect_denied_events([item])
        summary = events[0]["summary"]
        snippet = summary.split("LONGR001: ", 1)[-1].rsplit("...", 1)[0]
        assert len(snippet) == 30

    def test_no_4h_aging_filter_immediate_visibility(self):
        """否認はぱん自身の操作なので沈殿不要: たった今否認された1件でも即検知される
        (support_newと違い、時刻フィルタが一切かからないことの確認)。"""
        item = {"id": "JUSTNOW1", "draft_denied_at": "2026-08-01T11:59:59Z",
                "draft_denied_reason": "たった今否認"}
        events = sweep.detect_denied_events([item])
        assert len(events) == 1
        assert events[0]["count"] == 1

    def test_fingerprint_changes_when_count_changes(self):
        fp1 = sweep.detect_denied_events([DENIED_ITEM_VLGQR7ES])[0]["fingerprint"]
        fp2 = sweep.detect_denied_events([DENIED_ITEM_Z8XBKJBC, DENIED_ITEM_VLGQR7ES])[0]["fingerprint"]
        assert fp1 != fp2


class TestDeniedSayShouldFire:
    def test_fires_on_first_detection(self):
        detected = sweep.detect_denied_events([DENIED_ITEM_VLGQR7ES])
        assert sweep.denied_say_should_fire(detected, {}) is True

    def test_does_not_fire_when_count_unchanged(self):
        detected = sweep.detect_denied_events([DENIED_ITEM_VLGQR7ES])
        old_queue = {"denied_queue": common.Event(
            key="denied_queue", kind="denied", urgent=True,
            fingerprint=detected[0]["fingerprint"], summary="既存", first_seen="t", last_seen="t")}
        assert sweep.denied_say_should_fire(detected, old_queue) is False

    def test_fires_when_count_increases(self):
        old_detected = sweep.detect_denied_events([DENIED_ITEM_VLGQR7ES])
        old_queue = {"denied_queue": common.Event(
            key="denied_queue", kind="denied", urgent=True,
            fingerprint=old_detected[0]["fingerprint"], summary="既存", first_seen="t", last_seen="t")}
        new_detected = sweep.detect_denied_events([DENIED_ITEM_Z8XBKJBC, DENIED_ITEM_VLGQR7ES])
        assert sweep.denied_say_should_fire(new_detected, old_queue) is True

    def test_does_not_fire_when_count_decreases(self):
        """件数減少(1件解消)では鳴らさない(見落とし耐性が目的であり、解消の通知は不要)。"""
        old_detected = sweep.detect_denied_events([DENIED_ITEM_Z8XBKJBC, DENIED_ITEM_VLGQR7ES])
        old_queue = {"denied_queue": common.Event(
            key="denied_queue", kind="denied", urgent=True,
            fingerprint=old_detected[0]["fingerprint"], summary="既存", first_seen="t", last_seen="t")}
        new_detected = sweep.detect_denied_events([DENIED_ITEM_VLGQR7ES])
        assert sweep.denied_say_should_fire(new_detected, old_queue) is False

    def test_no_items_no_fire(self):
        assert sweep.denied_say_should_fire([], {}) is False


class TestRealFetchDenied:
    def test_calls_admin_denied_with_limit(self, monkeypatch):
        calls = []

        def fake_api(method, path, params=None, body=None):
            calls.append((method, path, params))
            return {"items": [DENIED_ITEM_VLGQR7ES]}
        monkeypatch.setattr(sweep.support_client, "api", fake_api)
        items = sweep._real_fetch_denied()
        assert calls[0] == ("GET", "/admin/denied", {"limit": sweep.DENIED_FETCH_LIMIT})
        assert items == [DENIED_ITEM_VLGQR7ES]

    def test_returns_empty_list_on_api_failure(self, monkeypatch):
        def fake_api(*a, **kw):
            raise SystemExit("boom")
        monkeypatch.setattr(sweep.support_client, "api", fake_api)
        assert sweep._real_fetch_denied() == []


class TestFireDeniedSay:
    def test_invokes_say_notice_with_no_window(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
        monkeypatch.setattr(sweep.subprocess, "run", fake_run)
        sweep._fire_denied_say(2)
        assert len(calls) == 1
        cmd, kwargs = calls[0]
        assert cmd[1] == str(sweep.SAY_PY)
        assert cmd[2] == "notice"
        assert "2" in cmd[3]
        assert kwargs.get("creationflags") == sweep._NO_WINDOW

    def test_failure_is_swallowed(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise OSError("no powershell")
        monkeypatch.setattr(sweep.subprocess, "run", fake_run)
        sweep._fire_denied_say(1)  # 例外を送出しないことだけを確認


class TestRunSweepDeniedIntegration:
    """run_sweep()統合: 実キュー・実state・実スレッドに一切触れない
    (isolated_state で EVENTBUS_STATE_DIR / EVENTBUS_GH_INBOX_DB をtmp_pathへ隔離)。"""

    @pytest.fixture(autouse=True)
    def isolated_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path / "eventbus"))
        monkeypatch.setenv("EVENTBUS_GH_INBOX_DB", str(tmp_path / "gh_inbox" / "state.db"))
        yield tmp_path

    def _patch_non_denied_fetches(self, monkeypatch):
        monkeypatch.setattr(sweep, "_real_fetch_issues_and_comments", lambda: ([], []))
        monkeypatch.setattr(sweep, "_real_fetch_canary_results", lambda d: [])
        monkeypatch.setattr(sweep, "_real_fetch_master_ci_run", lambda: None)
        monkeypatch.setattr(sweep, "_real_disk_free_gb", lambda p: 200.0)
        monkeypatch.setattr(sweep, "_real_fetch_support_unanswered", lambda: [])

    def test_two_denied_items_queued_every_sweep_say_fires_once(self, monkeypatch):
        """実在2件相当のフィクスチャが検知され、キューエントリが生成されること。
        2回連続掃引で毎回エントリが出続け(新着検知との挙動差)、say発火は初回のみ。"""
        self._patch_non_denied_fetches(monkeypatch)
        say_calls = []
        monkeypatch.setattr(sweep, "_fire_denied_say", lambda n: say_calls.append(n))
        monkeypatch.setattr(sweep, "_real_fetch_denied",
                             lambda: [DENIED_ITEM_Z8XBKJBC, DENIED_ITEM_VLGQR7ES])

        summary1 = sweep.run_sweep()
        assert summary1["urgent"] >= 1
        queue1 = common.load_queue()
        assert "denied_queue" in queue1
        assert queue1["denied_queue"].urgent is True
        assert "2件書き直し待ち" in queue1["denied_queue"].summary
        assert say_calls == [2]

        # 2回目の掃引: 内容が変化していなくても、否認キューは毎回配達され続ける
        # (新着検知support_newと違い、初回だけでゼロになるわけではない)。
        summary2 = sweep.run_sweep()
        queue2 = common.load_queue()
        assert "denied_queue" in queue2
        assert say_calls == [2]  # say再発火なし(件数不変)

    def test_negative_control_zero_denied_no_entry(self, monkeypatch):
        """負の対照: 否認ゼロの模擬状態ではdenied_queueエントリが出ない。"""
        self._patch_non_denied_fetches(monkeypatch)
        say_calls = []
        monkeypatch.setattr(sweep, "_fire_denied_say", lambda n: say_calls.append(n))
        monkeypatch.setattr(sweep, "_real_fetch_denied", lambda: [])

        summary = sweep.run_sweep()
        queue = common.load_queue()
        assert "denied_queue" not in queue
        assert say_calls == []

    def test_say_fires_again_when_count_increases_across_sweeps(self, monkeypatch):
        """1件目で掃引(say発火)、続けて2件目が増えた掃引でも再度say発火する。"""
        self._patch_non_denied_fetches(monkeypatch)
        say_calls = []
        monkeypatch.setattr(sweep, "_fire_denied_say", lambda n: say_calls.append(n))

        monkeypatch.setattr(sweep, "_real_fetch_denied", lambda: [DENIED_ITEM_VLGQR7ES])
        sweep.run_sweep()
        assert say_calls == [1]

        monkeypatch.setattr(sweep, "_real_fetch_denied",
                             lambda: [DENIED_ITEM_Z8XBKJBC, DENIED_ITEM_VLGQR7ES])
        sweep.run_sweep()
        assert say_calls == [1, 2]
