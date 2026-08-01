# -*- coding: utf-8 -*-
"""devtools/eventbus/common.py の delivered.jsonl(dev#556 配達履歴)関連の単体テスト。"""
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


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENTBUS_STATE_DIR", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------------------
# append_delivered / load_delivered_history
# ---------------------------------------------------------------------------

def test_append_delivered_creates_file_and_appends_lines():
    common.append_delivered({"ts": "t1", "hook": "SessionStart", "items": [], "empty": True})
    common.append_delivered({"ts": "t2", "hook": "UserPromptSubmit", "items": [], "empty": True})
    lines = common.delivered_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["ts"] == "t1"
    assert json.loads(lines[1])["ts"] == "t2"


def test_load_delivered_history_collects_key_fingerprint_pairs():
    common.append_delivered({
        "ts": "t1", "hook": "SessionStart",
        "items": [{"key": "issue:1", "fingerprint": "fp1"}], "empty": False,
    })
    history = common.load_delivered_history()
    assert ("issue:1", "fp1") in history


def test_load_delivered_history_empty_when_file_missing():
    assert common.load_delivered_history() == set()


def test_load_delivered_history_ignores_empty_items_entries():
    common.append_delivered({"ts": "t1", "hook": "UserPromptSubmit", "items": [], "empty": True})
    assert common.load_delivered_history() == set()


def test_load_delivered_history_skips_corrupted_lines():
    """壊れた行があっても、後続の正常行は読める(履歴破損で通知本体を止めない)。"""
    path = common.delivered_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    good_line = json.dumps({"items": [{"key": "a", "fingerprint": "f"}]}, ensure_ascii=False)
    path.write_text("{not valid json\n" + good_line + "\n", encoding="utf-8")
    history = common.load_delivered_history()
    assert ("a", "f") in history


# ---------------------------------------------------------------------------
# ローテーション(1MB超で世代切り)
# ---------------------------------------------------------------------------

def test_rotation_moves_oversized_file_to_generation_1(monkeypatch):
    monkeypatch.setattr(common, "DELIVERED_ROTATE_BYTES", 10)  # 極小閾値で強制発火させる
    common.append_delivered({"ts": "t1", "hook": "SessionStart", "items": [], "empty": True})
    # この時点でファイルは10バイトを超えているはず(次のappendでローテーション判定される)
    assert common.delivered_path().stat().st_size > 10

    common.append_delivered({"ts": "t2", "hook": "SessionStart", "items": [], "empty": True})

    rotated = common.delivered_path().with_name(common.delivered_path().name + ".1")
    assert rotated.exists()
    rotated_lines = rotated.read_text(encoding="utf-8").splitlines()
    assert len(rotated_lines) == 1
    assert json.loads(rotated_lines[0])["ts"] == "t1"

    current_lines = common.delivered_path().read_text(encoding="utf-8").splitlines()
    assert len(current_lines) == 1
    assert json.loads(current_lines[0])["ts"] == "t2"


def test_rotation_does_not_trigger_below_threshold():
    common.append_delivered({"ts": "t1", "hook": "SessionStart", "items": [], "empty": True})
    common.append_delivered({"ts": "t2", "hook": "SessionStart", "items": [], "empty": True})
    rotated = common.delivered_path().with_name(common.delivered_path().name + ".1")
    assert not rotated.exists()
    lines = common.delivered_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_rotation_overwrites_existing_generation_1(monkeypatch):
    """複数回ローテーションが起きても.1は最新の退避内容で上書きされる(世代は1つだけ保持)。"""
    monkeypatch.setattr(common, "DELIVERED_ROTATE_BYTES", 10)
    common.append_delivered({"ts": "t1", "hook": "SessionStart", "items": [], "empty": True})
    common.append_delivered({"ts": "t2", "hook": "SessionStart", "items": [], "empty": True})  # t1が.1へ
    common.append_delivered({"ts": "t3", "hook": "SessionStart", "items": [], "empty": True})  # t2が.1へ

    rotated = common.delivered_path().with_name(common.delivered_path().name + ".1")
    rotated_lines = rotated.read_text(encoding="utf-8").splitlines()
    assert len(rotated_lines) == 1
    assert json.loads(rotated_lines[0])["ts"] == "t2"  # 最新の退避分に置き換わっている
