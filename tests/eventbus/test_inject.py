# -*- coding: utf-8 -*-
"""devtools/eventbus/inject.py の単体テスト。実ネットワークなし・状態はtmp_pathへ隔離。"""
import io
import json
import sys
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
EVENTBUS_DIR = DEVTOOLS / "eventbus"
for p in (str(DEVTOOLS), str(EVENTBUS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import inject  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """common.*_path() が tmp_path 配下を指すようにする(実状態を汚さない)。"""
    monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path))
    yield tmp_path


def _write_queue(events: list):
    common.save_queue({e.key: e for e in events})


def _ev(key, urgent=False, delivered=False, first_seen="2026-07-31T09:00:00Z", summary=None):
    return common.Event(
        key=key, kind="issue_human", urgent=urgent, pan=False, issue_number=1,
        fingerprint="fp", summary=summary or f"summary for {key}",
        first_seen=first_seen, last_seen=first_seen, delivered=delivered,
    )


# ---------------------------------------------------------------------------
# サブエージェントには配らない
# ---------------------------------------------------------------------------

def test_subagent_gets_nothing(monkeypatch, capsys):
    _write_queue([_ev("issue:1", urgent=True)])
    stdin = json.dumps({"hook_event_name": "SessionStart", "agent_id": "abc123"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_agent_type_field_also_blocks_delivery(monkeypatch, capsys):
    _write_queue([_ev("issue:1", urgent=True)])
    stdin = json.dumps({"hook_event_name": "UserPromptSubmit", "agent_type": "general-purpose"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


# ---------------------------------------------------------------------------
# 鮮度証明と掃引停滞の文言(SessionStart)
# ---------------------------------------------------------------------------

def test_session_start_freshness_line_present(monkeypatch, capsys):
    common.write_last_sweep("2026-07-31T09:58:00Z")
    _write_queue([_ev("issue:1", urgent=True), _ev("issue:2", urgent=False)])
    stdin = json.dumps({"hook_event_name": "SessionStart"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    monkeypatch.setattr(common, "now_iso", lambda: "2026-07-31T10:00:00Z")
    rc = inject.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "イベントバス: 最終掃引 09:58 / 未配達2件(緊急1件)" in ctx
    assert "掃引停滞中" not in ctx


def test_session_start_reports_sweep_stall(monkeypatch, capsys):
    common.write_last_sweep("2026-07-31T09:00:00Z")  # 60分前 > 15分閾値
    _write_queue([])
    stdin = json.dumps({"hook_event_name": "SessionStart"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    monkeypatch.setattr(common, "now_iso", lambda: "2026-07-31T10:00:00Z")
    rc = inject.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "掃引停滞中" in ctx


def test_session_start_no_last_sweep_file_reports_stall(monkeypatch, capsys):
    # last_sweep.txtが存在しない(sweepが一度も起動していない=外側の故障寄りの兆候)
    stdin = json.dumps({"hook_event_name": "SessionStart"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "掃引停滞中" in ctx
    assert "未実施" in ctx


# ---------------------------------------------------------------------------
# 配達の集約と上限
# ---------------------------------------------------------------------------

def test_digest_capped_at_5_with_overflow_line(monkeypatch, capsys):
    events = [_ev(f"issue:{i}", urgent=False, delivered=False) for i in range(7)]
    _write_queue(events)
    stdin = json.dumps({"hook_event_name": "UserPromptSubmit"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    lines = [l for l in ctx.splitlines() if l.startswith("- ")]
    assert len(lines) == 6  # 5件 + 「他2件」
    assert lines[-1] == "- 他2件"


def test_digest_marks_delivered_and_not_reshown(monkeypatch, capsys):
    events = [_ev(f"issue:{i}", urgent=False, delivered=False) for i in range(3)]
    _write_queue(events)
    stdin = json.dumps({"hook_event_name": "UserPromptSubmit"})

    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    inject.main()
    capsys.readouterr()

    # 2回目呼び出し: 全部delivered済みのはずなので何も出ない
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


def test_urgent_always_reshown_even_if_delivered(monkeypatch, capsys):
    _write_queue([_ev("issue:urgent1", urgent=True, delivered=True)])
    stdin = json.dumps({"hook_event_name": "UserPromptSubmit"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "summary for issue:urgent1" in ctx  # delivered=True済みでもurgentは常に再表示


def test_user_prompt_submit_silent_when_nothing_undelivered(monkeypatch, capsys):
    _write_queue([_ev("issue:1", urgent=False, delivered=True)])
    stdin = json.dumps({"hook_event_name": "UserPromptSubmit"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


# ---------------------------------------------------------------------------
# 内側故障の負の対照(静的文字列を出し、例外を漏らさない)
# ---------------------------------------------------------------------------

def test_corrupted_queue_emits_static_fault_string(monkeypatch, capsys):
    common.queue_path().parent.mkdir(parents=True, exist_ok=True)
    common.queue_path().write_text("{not valid json\n", encoding="utf-8")
    stdin = json.dumps({"hook_event_name": "SessionStart"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0  # セッションを壊さない(exit 0のまま)
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert ctx == common.FAULT_MESSAGE
    assert common.hook_error_log_path().exists()


def test_unexpected_exception_emits_static_fault_string(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("想定外の例外")
    monkeypatch.setattr(common, "load_queue", lambda *a, **kw: _boom())
    stdin = json.dumps({"hook_event_name": "UserPromptSubmit"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert ctx == common.FAULT_MESSAGE


def test_fault_message_is_static_hardcoded_string():
    """故障通知文自体が動的処理を含まない固定文字列であることの確認。"""
    assert common.FAULT_MESSAGE == "[イベントバス] 故障中(詳細: .devonly\\state\\eventbus\\hook_error.log)"


def test_malformed_hook_input_fails_open_silently(monkeypatch, capsys):
    """フックJSON自体が壊れている場合はハーネス側異常として静かに抜ける
    (イベントバス自身の故障ではないためFAULT_MESSAGEは出さない)。"""
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    rc = inject.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""
