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


def _ev(key, urgent=False, delivered=False, first_seen="2026-07-31T09:00:00Z", summary=None,
        kind="canary"):
    """汎用(非issue_human)イベントのテスト用ファクトリ。

    dev#531でissue_humanは専用フォーマット(規則行+初回詳細/以降ID)へ切り出された
    ため、従来の「ダイジェスト行に[緊急]/[ダイジェスト]としてそのまま出る」挙動を
    確認するテストは既定でkind="canary"(issue_human以外)を使う。issue_human自体の
    新フォーマットは _issue_ev / TestIssueHumanSection 系で別途検証する。
    """
    return common.Event(
        key=key, kind=kind, urgent=urgent, pan=False, issue_number=1,
        fingerprint="fp", summary=summary or f"summary for {key}",
        first_seen=first_seen, last_seen=first_seen, delivered=delivered,
    )


def _issue_ev(key, issue_number, fingerprint="fp1", urgent=False,
              title="タイトル", actor="external_user", excerpt="",
              first_seen="2026-07-31T09:00:00Z"):
    """dev#531 issue_human 専用イベントのテスト用ファクトリ。"""
    return common.Event(
        key=key, kind="issue_human", urgent=urgent, pan=False, issue_number=issue_number,
        fingerprint=fingerprint, summary=f"summary for {key}",
        first_seen=first_seen, last_seen=first_seen, delivered=False,
        title=title, actor=actor, excerpt=excerpt,
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
# dev#531: issue_human 専用フォーマット(規則行+初回詳細/以降ID方式)
# ---------------------------------------------------------------------------

RULE_PREFIX = "ルール『issuesにおいてユーザーが最終発言の場合、botは速やかに確認・処置・返信を行う"


def _run_user_prompt_submit(monkeypatch, capsys):
    stdin = json.dumps({"hook_event_name": "UserPromptSubmit"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    out = capsys.readouterr().out
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""
    return rc, ctx


def test_issue_human_first_delivery_shows_rule_line_and_detail(monkeypatch, capsys):
    """ケース①-初回: 規則行+詳細行(番号+タイトル30字截断+最終発言者+抜粋)が出る。"""
    long_title = "あ" * 40  # 30字超で截断されることも確認する
    _write_queue([_issue_ev("issue:380", 380, fingerprint="fp1", title=long_title,
                             actor="some_external_user", excerpt="最新コメントの抜粋です")])
    rc, ctx = _run_user_prompt_submit(monkeypatch, capsys)
    assert rc == 0
    assert f"{RULE_PREFIX} 該当ID: 380』" in ctx
    assert "#380" in ctx
    assert ("あ" * 30 + "…") in ctx  # 30字截断+省略記号
    assert ("あ" * 31) not in ctx  # 截断されていること
    assert "最終発言者=some_external_user" in ctx
    assert "最新コメントの抜粋です" in ctx


def test_issue_human_second_delivery_shows_only_id_no_detail(monkeypatch, capsys):
    """ケース②-2回目: 同一fingerprintの再配達では詳細行が省略され、規則行のID列挙のみ。"""
    _write_queue([_issue_ev("issue:380", 380, fingerprint="fp1", title="タイトルX",
                             actor="some_external_user", excerpt="抜粋X")])
    _run_user_prompt_submit(monkeypatch, capsys)  # 1回目(詳細行が出る) → delivered.jsonlへ記録

    rc, ctx = _run_user_prompt_submit(monkeypatch, capsys)  # 2回目
    assert rc == 0
    assert f"{RULE_PREFIX} 該当ID: 380』" in ctx
    assert "タイトルX" not in ctx
    assert "抜粋X" not in ctx
    assert "最終発言者=" not in ctx


def test_issue_human_fingerprint_change_reverts_to_detail(monkeypatch, capsys):
    """ケース③-fingerprint変化: 新しい活動があれば詳細行が復活する。"""
    _write_queue([_issue_ev("issue:380", 380, fingerprint="fp1", title="旧タイトル",
                             actor="userA", excerpt="旧抜粋")])
    _run_user_prompt_submit(monkeypatch, capsys)  # 1回目: fp1を初配達として記録
    _run_user_prompt_submit(monkeypatch, capsys)  # 2回目: fp1はID列挙のみ

    # 新しい活動でfingerprintが変わる(sweep.pyの再検知を模す)
    _write_queue([_issue_ev("issue:380", 380, fingerprint="fp2", title="新タイトル",
                             actor="userB", excerpt="新抜粋")])
    rc, ctx = _run_user_prompt_submit(monkeypatch, capsys)  # 3回目: fp2は初配達扱いに戻る
    assert rc == 0
    assert "新タイトル" in ctx
    assert "新抜粋" in ctx
    assert "最終発言者=userB" in ctx


def test_issue_human_multiple_ids_listed_together(monkeypatch, capsys):
    """複数issueが同時に対象のとき、該当IDがすべて列挙される。"""
    _write_queue([
        _issue_ev("issue:380", 380, fingerprint="fp1"),
        _issue_ev("issue:463", 463, fingerprint="fp1"),
    ])
    rc, ctx = _run_user_prompt_submit(monkeypatch, capsys)
    assert rc == 0
    assert "該当ID: 380, 463』" in ctx


def test_issue_human_session_start_also_includes_rule_line(monkeypatch, capsys):
    """SessionStartでもissue_humanの規則行が(鮮度証明と併記で)出ること。"""
    _write_queue([_issue_ev("issue:380", 380, fingerprint="fp1")])
    stdin = json.dumps({"hook_event_name": "SessionStart"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    rc = inject.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "イベントバス: " in ctx
    assert f"{RULE_PREFIX} 該当ID: 380』" in ctx


# ---------------------------------------------------------------------------
# dev#556: 配達履歴(delivered.jsonl)
# ---------------------------------------------------------------------------

class TestDeliveredHistoryLog:
    def test_delivered_jsonl_grows_on_each_injection_even_when_empty(self, monkeypatch, capsys):
        """負の対照込み: キューが空でも呼び出しごとに1行増える(空注入を明示)。"""
        assert not common.delivered_path().exists()
        _run_user_prompt_submit(monkeypatch, capsys)
        lines1 = common.delivered_path().read_text(encoding="utf-8").splitlines()
        assert len(lines1) == 1
        entry1 = json.loads(lines1[0])
        assert entry1["empty"] is True
        assert entry1["items"] == []
        assert entry1["hook"] == "UserPromptSubmit"

        _run_user_prompt_submit(monkeypatch, capsys)
        lines2 = common.delivered_path().read_text(encoding="utf-8").splitlines()
        assert len(lines2) == 2  # 呼び出しごとに増える

    def test_delivered_jsonl_records_injected_items(self, monkeypatch, capsys):
        _write_queue([_issue_ev("issue:380", 380, fingerprint="fp1")])
        _run_user_prompt_submit(monkeypatch, capsys)
        lines = common.delivered_path().read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["empty"] is False
        assert {"key": "issue:380", "fingerprint": "fp1"} in entry["items"]

    def test_delivered_jsonl_used_for_first_vs_repeat_decision(self, monkeypatch, capsys):
        """delivered.jsonl自体が「配達済みfingerprint」の記録として使われている
        ことを、履歴を手動で仕込んで検証する(実装がdelivered.jsonlに依存している
        ことの直接確認)。"""
        _write_queue([_issue_ev("issue:380", 380, fingerprint="fp1", title="タイトルY",
                                 actor="userY", excerpt="抜粋Y")])
        # 事前にdelivered.jsonlへ同一fingerprintの配達履歴を仕込んでおく
        common.append_delivered({
            "ts": "2026-08-01T00:00:00Z", "hook": "UserPromptSubmit",
            "items": [{"key": "issue:380", "fingerprint": "fp1"}], "empty": False,
        })
        rc, ctx = _run_user_prompt_submit(monkeypatch, capsys)
        assert rc == 0
        assert "タイトルY" not in ctx  # 履歴に既にあるので詳細行は出ない(2回目扱い)
        assert "該当ID: 380』" in ctx


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
