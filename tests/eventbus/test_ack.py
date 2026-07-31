# -*- coding: utf-8 -*-
"""devtools/eventbus/ack.py の単体テスト。"""
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
import ack  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path))
    yield tmp_path


def _ev(key, first_seen="2026-07-31T09:00:00Z"):
    return common.Event(
        key=key, kind="issue_human", urgent=False, pan=False, issue_number=1,
        fingerprint="fp-" + key, summary=f"summary {key}",
        first_seen=first_seen, last_seen=first_seen, delivered=True,
    )


def test_ack_all_moves_everything_to_acked_jsonl(capsys):
    common.save_queue({"a": _ev("a"), "b": _ev("b")})
    rc = ack.main(["--all"])
    assert rc == 0
    assert common.load_queue() == {}
    acked = common.load_acked_fingerprints()
    assert set(acked.keys()) == {"a", "b"}
    assert acked["a"] == "fp-a"


def test_ack_by_ids_moves_only_specified(capsys):
    common.save_queue({"a": _ev("a"), "b": _ev("b"), "c": _ev("c")})
    rc = ack.main(["--ids", "a,c"])
    assert rc == 0
    remaining = common.load_queue()
    assert set(remaining.keys()) == {"b"}
    acked = common.load_acked_fingerprints()
    assert set(acked.keys()) == {"a", "c"}


def test_ack_unknown_id_is_ignored_with_warning(capsys):
    common.save_queue({"a": _ev("a")})
    rc = ack.main(["--ids", "a,nonexistent"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "nonexistent" in err
    assert common.load_queue() == {}


def test_ack_until_acks_only_older_or_equal(capsys):
    common.save_queue({
        "old": _ev("old", first_seen="2026-07-31T08:00:00Z"),
        "new": _ev("new", first_seen="2026-07-31T11:00:00Z"),
    })
    rc = ack.main(["--until", "2026-07-31T09:00:00Z"])
    assert rc == 0
    remaining = common.load_queue()
    assert set(remaining.keys()) == {"new"}
    acked = common.load_acked_fingerprints()
    assert set(acked.keys()) == {"old"}


def test_ack_empty_queue_is_noop(capsys):
    rc = ack.main(["--all"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ありません" in out


def test_ack_appends_to_existing_acked_file_without_clobbering(capsys):
    common.save_queue({"a": _ev("a")})
    ack.main(["--ids", "a"])
    common.save_queue({"b": _ev("b")})
    ack.main(["--ids", "b"])
    acked = common.load_acked_fingerprints()
    assert set(acked.keys()) == {"a", "b"}
