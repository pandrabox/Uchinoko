# -*- coding: utf-8 -*-
"""devtools/eventbus/net_watch.py の単体テスト。実ネットワーク不要
(probe_all の prober / majority_up の入力bool列を直接注入する)。"""
import sys
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
EVENTBUS_DIR = DEVTOOLS / "eventbus"
for p in (str(DEVTOOLS), str(EVENTBUS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import net_watch  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_eventbus_state_dir(tmp_path, monkeypatch):
    """queue.jsonl・ログ・ロック・ハートビートの書き込み先を隔離する。"""
    monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path / "eventbus_state"))


# ---------------------------------------------------------------------------
# 多数決(1/3ホスト失敗では寸断としない)
# ---------------------------------------------------------------------------

class TestMajorityUp:
    def test_all_up(self):
        assert net_watch.majority_up([True, True, True]) is True

    def test_single_host_failure_not_down(self):
        """3ホスト中1失敗(2生存)では『断』としない。"""
        assert net_watch.majority_up([True, True, False]) is True

    def test_majority_failure_is_down(self):
        """3ホスト中2失敗(1生存のみ)では『断』と判定する。"""
        assert net_watch.majority_up([True, False, False]) is False

    def test_all_down(self):
        assert net_watch.majority_up([False, False, False]) is False

    def test_empty_results_treated_as_up(self):
        """プローブ対象が無い(判定不能)場合は安全側でupとみなす。"""
        assert net_watch.majority_up([]) is True

    def test_probe_all_uses_injected_prober(self):
        """probe_all はproberを注入でき、実ネットワークに触れない。"""
        calls = []

        def fake_prober(host, port):
            calls.append((host, port))
            return host != "down.example.com"

        hosts = [("up1.example.com", 443), ("down.example.com", 443), ("up2.example.com", 443)]
        results = net_watch.probe_all(hosts, prober=fake_prober)
        assert results == [True, False, True]
        assert calls == hosts


# ---------------------------------------------------------------------------
# 遷移検知(断→復・復→断の即時検知、連続状態中の非重複)
# ---------------------------------------------------------------------------

class TestEvaluateTransition:
    def test_initial_baseline_establishes_silently(self):
        """起動直後(prev_status=None)は基準を確立するだけでイベントを出さない。"""
        status, down_since, ev = net_watch.evaluate_transition(None, True, "2026-08-01T10:00:00Z", None)
        assert status == "up"
        assert down_since is None
        assert ev is None

        status2, down_since2, ev2 = net_watch.evaluate_transition(None, False, "2026-08-01T10:00:00Z", None)
        assert status2 == "down"
        assert down_since2 == "2026-08-01T10:00:00Z"
        assert ev2 is None

    def test_up_to_down_transition_generates_event(self):
        """断の発生を即時検知し、イベントを1件生成する。"""
        status, down_since, ev = net_watch.evaluate_transition(
            "up", False, "2026-08-01T10:05:00Z", None)
        assert status == "down"
        assert down_since == "2026-08-01T10:05:00Z"
        assert ev is not None
        assert ev["key"] == "net_watch"
        assert ev["kind"] == "net"
        assert ev["urgent"] is True
        assert "10:05:00" in ev["summary"]
        assert "継続中" in ev["summary"]

    def test_down_to_up_transition_generates_recovery_event(self):
        """復旧を即時検知し、寸断開始〜終了の範囲を含むイベントを1件生成する。"""
        status, down_since, ev = net_watch.evaluate_transition(
            "down", True, "2026-08-01T10:10:00Z", "2026-08-01T10:05:00Z")
        assert status == "up"
        assert down_since is None
        assert ev is not None
        assert ev["key"] == "net_watch"
        assert "10:05:00" in ev["summary"]
        assert "10:10:00" in ev["summary"]
        assert "〜" in ev["summary"]

    def test_continuous_down_no_duplicate_event(self):
        """連続断中(down→down)はイベントを生成しない(重複生成禁止)。"""
        status, down_since, ev = net_watch.evaluate_transition(
            "down", False, "2026-08-01T10:06:00Z", "2026-08-01T10:05:00Z")
        assert status == "down"
        assert down_since == "2026-08-01T10:05:00Z"  # 開始時刻は据え置き
        assert ev is None

    def test_continuous_up_no_event(self):
        """連続オンライン中(up→up)もイベントを生成しない。"""
        status, down_since, ev = net_watch.evaluate_transition(
            "up", True, "2026-08-01T10:07:00Z", None)
        assert status == "up"
        assert down_since is None
        assert ev is None


# ---------------------------------------------------------------------------
# queue.jsonl 反映
# ---------------------------------------------------------------------------

class TestWriteEvent:
    def test_write_event_persists_to_queue(self):
        ev = {
            "key": "net_watch", "kind": "net", "urgent": True, "pan": False,
            "issue_number": None, "fingerprint": "down:2026-08-01T10:05:00Z",
            "summary": "ネット寸断検知: 10:05:00〜(継続中)",
            "first_seen": "2026-08-01T10:05:00Z", "last_seen": "2026-08-01T10:05:00Z",
        }
        net_watch.write_event(ev)
        queue = common.load_queue()
        assert "net_watch" in queue
        assert queue["net_watch"].summary == ev["summary"]
        assert queue["net_watch"].delivered is False

    def test_write_event_overwrites_previous_state(self):
        """同一key(net_watch)は上書きされ、queueに複数件残らない。"""
        down_ev = {
            "key": "net_watch", "kind": "net", "urgent": True, "pan": False,
            "issue_number": None, "fingerprint": "down:2026-08-01T10:05:00Z",
            "summary": "ネット寸断検知: 10:05:00〜(継続中)",
            "first_seen": "2026-08-01T10:05:00Z", "last_seen": "2026-08-01T10:05:00Z",
        }
        recovered_ev = {
            "key": "net_watch", "kind": "net", "urgent": True, "pan": False,
            "issue_number": None, "fingerprint": "recovered:2026-08-01T10:05:00Z:2026-08-01T10:10:00Z",
            "summary": "ネット寸断: 10:05:00〜10:10:00",
            "first_seen": "2026-08-01T10:05:00Z", "last_seen": "2026-08-01T10:10:00Z",
        }
        net_watch.write_event(down_ev)
        net_watch.write_event(recovered_ev)
        queue = common.load_queue()
        assert len(queue) == 1
        assert queue["net_watch"].summary == recovered_ev["summary"]


# ---------------------------------------------------------------------------
# ハートビート
# ---------------------------------------------------------------------------

class TestHeartbeat:
    def test_write_heartbeat_creates_file_with_iso_timestamp(self):
        net_watch.write_heartbeat()
        path = net_watch.heartbeat_path()
        assert path.exists()
        content = path.read_text(encoding="utf-8").strip()
        # parse_iso が例外を出さなければ正しいISO8601形式
        common.parse_iso(content)


# ---------------------------------------------------------------------------
# 多重起動防止(pidベースロック)
# ---------------------------------------------------------------------------

class TestLock:
    def test_acquire_lock_succeeds_first_time(self):
        assert net_watch.acquire_lock() is True
        net_watch.release_lock()

    def test_second_acquire_blocked_while_first_alive(self):
        """自分自身のpidは常に生きているので、2回目の取得はブロックされる。"""
        assert net_watch.acquire_lock() is True
        assert net_watch.acquire_lock() is False
        net_watch.release_lock()

    def test_lock_reusable_after_release(self):
        assert net_watch.acquire_lock() is True
        net_watch.release_lock()
        assert net_watch.acquire_lock() is True
        net_watch.release_lock()

    def test_stale_lock_reclaimed(self):
        """存在しないpidが書かれたロックファイル(stale)は回収して取得できる。"""
        path = net_watch.lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pid=999999999 started=2020-01-01T00:00:00Z\n", encoding="utf-8")
        assert net_watch.acquire_lock() is True
        net_watch.release_lock()


# ---------------------------------------------------------------------------
# run_forever 統合(実ネットワーク不要、prober注入+stop_afterで有限回に制限)
# ---------------------------------------------------------------------------

class TestRunForeverIntegration:
    def test_run_forever_writes_heartbeat_and_transition_event(self):
        """常に成功するproberでrun_foreverを2周走らせ、ハートビートが書かれ、
        遷移イベントが(基準確立のみで)発生しないことを確認する。"""
        def always_up(host, port):
            return True

        net_watch.run_forever(interval=0, hosts=[("dummy", 443)], prober=always_up, stop_after=2)
        assert net_watch.heartbeat_path().exists()
        queue = common.load_queue()
        assert "net_watch" not in queue  # 状態変化なし(オンライン継続)なのでイベント無し

    def test_run_forever_detects_down_then_up(self):
        """1周目down・2周目upのproberで、復旧イベントが1件だけ生成される
        (連続生成にならないことも同時に確認)。"""
        call_count = {"n": 0}

        def flaky(host, port):
            call_count["n"] += 1
            return call_count["n"] > 1  # 1回目(1周目)は失敗、以降成功

        net_watch.run_forever(interval=0, hosts=[("dummy", 443)], prober=flaky, stop_after=3)
        queue = common.load_queue()
        assert "net_watch" in queue
        ev = queue["net_watch"]
        assert "〜" in ev.summary
        assert "継続中" not in ev.summary  # 復旧済みなので「継続中」ではなく確定範囲表示
