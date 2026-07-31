# -*- coding: utf-8 -*-
r"""dev#201(release.py リリース承認issueゲート)の受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実変換・
実relgate・実release.py本番実行・実GitHub API呼び出しを一切課さない(単体試験+
モックのみ)。パス不変(pak不変)の変更のため、この単体試験+負の対照で受入と
する(dev#201の依頼どおり)。

対象の負の対照(dev#201依頼「承認なし/他人の承認/closedのissueで各FAIL」):
  - 承認コメントが無いissue -> FAIL
  - 承認コメントがpandrabox以外のユーザーによるもの -> FAIL
  - issueがclosed -> FAIL
  - for:humanラベルが付いていない -> FAIL
  - GitHub API到達不可(オフライン) -> FAIL(fail-closed)

実行: python -m pytest tests\shipcheck\test_release_approval_gate.py -v
"""
import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
TESTS_RELGATE = os.path.join(REPO, "tests", "relgate")

for p in (DEVTOOLS, TESTS_RELGATE):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_release():
    return importlib.import_module("release")


class DummyReport:
    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _issue_doc(state="open", labels=("for:human",), number=201):
    return {
        "number": number,
        "state": state,
        "labels": [{"name": n} for n in labels],
    }


def _comment(login, body):
    return {"user": {"login": login}, "body": body}


# =====================================================================
# comment_is_approval: 純関数の判定基準
# =====================================================================

@pytest.mark.parametrize("login,body,expected", [
    ("pandrabox", "承認", True),
    ("pandrabox", "OK", True),
    ("pandrabox", "ok", True),
    ("pandrabox", "Ok, ship it", True),
    ("pandrabox", "承認します、進めてください", True),
    ("pandrabox", "まだです", False),
    ("pandrabox", "", False),
    ("osaki-claude[bot]", "承認", False),  # 他人(bot含む)の承認 -> 無効
    ("someone-else", "OK", False),         # 他人の承認 -> 無効
])
def test_comment_is_approval(login, body, expected):
    release = _import_release()
    assert release.comment_is_approval(_comment(login, body)) is expected


def test_comment_is_approval_handles_missing_user():
    release = _import_release()
    assert release.comment_is_approval({"body": "承認"}) is False


# =====================================================================
# evaluate_approval_issue: 3条件の純関数判定
# =====================================================================

def test_evaluate_approval_issue_ok_when_all_conditions_met():
    release = _import_release()
    issue_doc = _issue_doc()
    comments = [_comment("pandrabox", "承認")]
    ok, reason = release.evaluate_approval_issue(issue_doc, comments)
    assert ok is True
    assert "OK" in reason


def test_evaluate_approval_issue_fails_when_no_approval_comment():
    """負の対照: 承認コメントが無いissue -> FAIL"""
    release = _import_release()
    issue_doc = _issue_doc()
    comments = [_comment("pandrabox", "見てます、まだです")]
    ok, reason = release.evaluate_approval_issue(issue_doc, comments)
    assert ok is False
    assert "承認コメント" in reason


def test_evaluate_approval_issue_fails_when_approval_by_someone_else():
    """負の対照: 他人の承認 -> FAIL"""
    release = _import_release()
    issue_doc = _issue_doc()
    comments = [_comment("osaki-claude[bot]", "承認"), _comment("random-user", "OK")]
    ok, reason = release.evaluate_approval_issue(issue_doc, comments)
    assert ok is False
    assert "承認コメント" in reason


def test_evaluate_approval_issue_fails_when_issue_closed():
    """負の対照: closedのissue -> FAIL"""
    release = _import_release()
    issue_doc = _issue_doc(state="closed")
    comments = [_comment("pandrabox", "承認")]
    ok, reason = release.evaluate_approval_issue(issue_doc, comments)
    assert ok is False
    assert "open" in reason


def test_evaluate_approval_issue_fails_when_label_missing():
    release = _import_release()
    issue_doc = _issue_doc(labels=("for:ai",))
    comments = [_comment("pandrabox", "承認")]
    ok, reason = release.evaluate_approval_issue(issue_doc, comments)
    assert ok is False
    assert "for:human" in reason


def test_evaluate_approval_issue_fails_on_empty_issue_doc():
    release = _import_release()
    ok, reason = release.evaluate_approval_issue(None, [])
    assert ok is False


# =====================================================================
# fetch_approval_issue: gh api 呼び出しのネットワーク境界
# =====================================================================

def test_fetch_approval_issue_raises_gate_network_error_on_issue_api_failure():
    """負の対照: issue取得自体が失敗(オフライン相当) -> GateNetworkError"""
    release = _import_release()

    def fake_run(cmd, **kwargs):
        return FakeCompletedProcess(returncode=1, stderr="curl: (6) Could not resolve host")

    with pytest.raises(release.GateNetworkError):
        release.fetch_approval_issue(201, run_fn=fake_run)


def test_fetch_approval_issue_raises_gate_network_error_on_comments_api_failure():
    release = _import_release()
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeCompletedProcess(returncode=0, stdout=json.dumps(_issue_doc()))
        return FakeCompletedProcess(returncode=1, stderr="network unreachable")

    with pytest.raises(release.GateNetworkError):
        release.fetch_approval_issue(201, run_fn=fake_run)


def test_fetch_approval_issue_raises_gate_network_error_on_bad_json():
    release = _import_release()

    def fake_run(cmd, **kwargs):
        return FakeCompletedProcess(returncode=0, stdout="not-json{{{")

    with pytest.raises(release.GateNetworkError):
        release.fetch_approval_issue(201, run_fn=fake_run)


def test_fetch_approval_issue_returns_issue_and_comments_on_success():
    release = _import_release()
    calls = {"n": 0}
    issue_doc = _issue_doc()
    comments = [_comment("pandrabox", "承認")]

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            assert f"repos/{release.APPROVAL_ISSUE_REPO}/issues/201" in cmd
            return FakeCompletedProcess(returncode=0, stdout=json.dumps(issue_doc))
        assert "comments" in cmd[-1]
        return FakeCompletedProcess(returncode=0, stdout=json.dumps(comments))

    got_issue, got_comments = release.fetch_approval_issue(201, run_fn=fake_run)
    assert got_issue == issue_doc
    assert got_comments == comments


def test_fetch_approval_issue_treats_empty_comments_response_as_no_comments():
    release = _import_release()
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeCompletedProcess(returncode=0, stdout=json.dumps(_issue_doc()))
        return FakeCompletedProcess(returncode=0, stdout="")

    _, comments = release.fetch_approval_issue(201, run_fn=fake_run)
    assert comments == []


# =====================================================================
# run_approval_gate: main()から呼ぶ薄いラッパ、fail-closed境界
# =====================================================================

def test_run_approval_gate_fails_closed_on_network_error():
    """負の対照: GitHub API到達不可(オフライン) -> 即FAIL(fail-closed)"""
    release = _import_release()

    def fake_fetch(issue_number):
        raise release.GateNetworkError("Could not resolve host")

    report = DummyReport()
    ok, reason = release.run_approval_gate(201, report, fetch_fn=fake_fetch)
    assert ok is False
    assert "到達できなかった" in reason


def test_run_approval_gate_ok_when_fetch_succeeds_and_conditions_met():
    release = _import_release()

    def fake_fetch(issue_number):
        assert issue_number == 201
        return _issue_doc(), [_comment("pandrabox", "承認")]

    report = DummyReport()
    ok, reason = release.run_approval_gate(201, report, fetch_fn=fake_fetch)
    assert ok is True


# =====================================================================
# main()統合: 承認issue未確認は git tree 確認より前に即FAILし、副作用ゼロ
# =====================================================================

def test_main_rejects_when_approval_gate_fails_before_any_side_effect(tmp_path, monkeypatch):
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))

    called = {"get_head_full": False}
    monkeypatch.setattr(release, "get_head_full", lambda: called.__setitem__("get_head_full", True))
    monkeypatch.setattr(
        release, "run_approval_gate",
        lambda issue_number, report: (False, "承認コメントが見つからない"))

    rc = release.main(["--bump", "patch", "--pak", "none", "--approval-issue", "201"])

    assert rc == 1
    assert called["get_head_full"] is False, (
        "承認issueゲートのFAILは、git tree確認(1節)より前の引数検証段階で"
        "即FAILしなければならない")


def test_main_proceeds_past_approval_gate_when_approved(tmp_path, monkeypatch):
    """正の対照: 承認issueゲートがOKなら、その先(git tree確認)まで進む
    (承認ゲート自体が過剰にブロックしていないことの確認)。"""
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))

    called = {"get_head_full": False}

    def fake_get_head_full():
        called["get_head_full"] = True
        return "deadbeef"

    monkeypatch.setattr(release, "get_head_full", fake_get_head_full)
    monkeypatch.setattr(release, "get_head_short", lambda: "deadbee")
    monkeypatch.setattr(
        release, "run_approval_gate",
        lambda issue_number, report: (True, "OK(dummy)"))
    # working tree dirty扱いにして、それ以降(zipビルド等)には進ませずrc=1で
    # 早期終了させる(このテストの関心はget_head_fullに到達することだけ)。
    monkeypatch.setattr(
        release, "check_tree_clean_with_allow_dirty",
        lambda allow_dirty_norm: (False, "M some_file.py\n", ["M some_file.py"], set()))

    rc = release.main(["--bump", "patch", "--pak", "none", "--approval-issue", "201"])

    assert rc == 1
    assert called["get_head_full"] is True, (
        "承認issueゲートがOKなら、git tree確認まで進まなければならない")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
