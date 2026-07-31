# -*- coding: utf-8 -*-
r"""dev#273(release.py 事後承認の仮リリース、--provisional / --confirm-provisional)
の受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実変換・
実relgate・実release.py本番実行・実GitHub API呼び出し・実Palworld実機・実tkinter
GUIを一切課さない(単体試験+モックのみ)。パス不変(pak不変)の変更のため、この
単体試験+負の対照で受入とする。

対象の負の対照(指揮者依頼の5点+コーディネータ訂正の⑥):
  ① --provisional と --approval-issue の併用 -> エラー
  ② --provisional実行でissue起票内容が3部構成(zip関連PRのみ)
  ③ --confirm-provisional: 承認コメントあり -> confirmed+close / なし -> rc!=0
  ④ 否認コメント -> rc!=0で指揮者向けメッセージ
  ⑤ 既定(フラグ無し)は従来の--approval-issue必須挙動が完全不変
  ⑥ confirm前の版が「公開可」と判定されないこと(is_release_publishable)

実行: python -m pytest tests\shipcheck\test_release_provisional.py -v
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


def _issue_doc(state="open", labels=("for:human",), number=273):
    return {
        "number": number,
        "state": state,
        "labels": [{"name": n} for n in labels],
    }


def _comment(login, body):
    return {"user": {"login": login}, "body": body}


# =====================================================================
# ① --provisional と --approval-issue の併用 -> エラー(引数検証段階)
# =====================================================================

def test_validate_release_mode_args_rejects_provisional_with_approval_issue():
    release = _import_release()
    args = release.build_arg_parser().parse_args(
        ["--bump", "patch", "--pak", "none", "--provisional", "--approval-issue", "201"])
    ok, reason = release.validate_release_mode_args(args)
    assert ok is False
    assert "併用" in reason


def test_main_rejects_provisional_with_approval_issue_before_any_side_effect(tmp_path, monkeypatch):
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))
    called = {"get_head_full": False}
    monkeypatch.setattr(release, "get_head_full", lambda: called.__setitem__("get_head_full", True))

    rc = release.main(["--bump", "patch", "--pak", "none",
                        "--provisional", "--approval-issue", "201"])

    assert rc == 1
    assert called["get_head_full"] is False, (
        "--provisional/--approval-issue併用は、disk_guard/git tree確認より前の"
        "引数検証段階で即FAILしなければならない")


def test_validate_release_mode_args_confirm_provisional_rejects_other_flags():
    """負の対照: --confirm-provisionalは単独実行のみ(他フラグとの同時指定は拒否)"""
    release = _import_release()
    args = release.build_arg_parser().parse_args(
        ["--confirm-provisional", "273", "--bump", "patch"])
    ok, reason = release.validate_release_mode_args(args)
    assert ok is False
    assert "--bump" in reason


def test_validate_release_mode_args_confirm_provisional_alone_ok():
    release = _import_release()
    args = release.build_arg_parser().parse_args(["--confirm-provisional", "273"])
    ok, reason = release.validate_release_mode_args(args)
    assert ok is True


# =====================================================================
# ⑤ 既定(フラグ無し)は従来の--approval-issue必須挙動が完全不変
# =====================================================================

def test_validate_release_mode_args_requires_approval_issue_or_provisional_by_default():
    """負の対照: --provisionalも--approval-issueも無ければFAIL(従来の
    --approval-issue必須挙動が変わっていないことの確認)。"""
    release = _import_release()
    args = release.build_arg_parser().parse_args(["--bump", "patch", "--pak", "none"])
    ok, reason = release.validate_release_mode_args(args)
    assert ok is False
    assert "--approval-issue" in reason


def test_validate_release_mode_args_ok_with_approval_issue_only():
    """正の対照: --approval-issueだけ指定(--provisional無し)は従来どおりOK"""
    release = _import_release()
    args = release.build_arg_parser().parse_args(
        ["--bump", "patch", "--pak", "none", "--approval-issue", "201"])
    ok, reason = release.validate_release_mode_args(args)
    assert ok is True


def test_validate_release_mode_args_ok_with_provisional_only():
    """正の対照: --provisionalだけ指定(--approval-issue無し)もOK"""
    release = _import_release()
    args = release.build_arg_parser().parse_args(
        ["--bump", "patch", "--pak", "none", "--provisional"])
    ok, reason = release.validate_release_mode_args(args)
    assert ok is True


def test_main_still_requires_bump_and_pak_without_confirm_provisional():
    release = _import_release()
    args = release.build_arg_parser().parse_args(["--approval-issue", "201"])
    ok, reason = release.validate_release_mode_args(args)
    assert ok is False
    assert "--bump" in reason


# =====================================================================
# ② --provisional実行でissue起票内容が3部構成(zip関連PRのみ)
# =====================================================================

def test_list_ship_scope_prs_since_filters_non_ship_scope_prs():
    """出荷スコープ(app/pipeline/unity/...)のファイルを触っていないPRは除外される"""
    release = _import_release()
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if cmd[:2] == ["git", "log"]:
            return FakeCompletedProcess(returncode=0, stdout=(
                "aaa1111\tMerge pull request #100 from pandrabox/pr/ship-thing\n"
                "bbb2222\tMerge pull request #101 from pandrabox/pr/docs-only\n"
            ))
        # diff-tree呼び出し(コミットハッシュで分岐)
        if "aaa1111" in cmd:
            return FakeCompletedProcess(returncode=0, stdout="pipeline/py/convert_noue.py\n")
        if "bbb2222" in cmd:
            return FakeCompletedProcess(returncode=0, stdout="work/scratch/notes.md\n")
        return FakeCompletedProcess(returncode=1)

    prs = release.list_ship_scope_prs_since("v2.2.7", run_fn=fake_run)
    assert [p["number"] for p in prs] == [100]
    assert "docs-only" not in [p["subject"] for p in prs]


def test_list_ship_scope_prs_since_returns_empty_on_git_failure():
    """負の対照: git呼び出し失敗でも例外を出さず空リスト(issue起票自体は止めない)"""
    release = _import_release()

    def fake_run(cmd, **kwargs):
        return FakeCompletedProcess(returncode=1, stderr="not a git repo")

    prs = release.list_ship_scope_prs_since("v2.2.7", run_fn=fake_run)
    assert prs == []


def test_build_provisional_issue_body_has_three_sections_and_ship_scope_prs_only():
    release = _import_release()
    ship_scope_prs = [{"number": 100, "subject": "Merge pull request #100 from x/ship-thing",
                        "files": ["pipeline/py/convert_noue.py"]}]
    body = release.build_provisional_issue_body(
        "v2.3.0", ship_scope_prs, "expected",
        ["vrm1_seedsan"], {"vrm1_seedsan": [r"C:\work\shots\vrm1_seedsan\01.png"]})

    assert "## 1. こういうPRをマージしました" in body
    assert "## 2. このリリースでの実際の変更" in body
    assert "## 3. ユーザー向け説明" in body
    assert "#100" in body
    assert r"C:\work\shots\vrm1_seedsan\01.png" in body
    assert "そのほか細かな不具合修正・内部改善" in body
    assert "公開できません" in body


def test_build_provisional_issue_body_pak_none_has_no_pending_avatars():
    release = _import_release()
    body = release.build_provisional_issue_body("v2.3.0", [], "none", [], {})
    assert "pak変更なし" in body
    assert "SS承認" not in body  # pak none ならSS検収の案内自体が出ない


# =====================================================================
# ③ --confirm-provisional: 承認コメントあり->confirmed+close / なし->rc!=0
# =====================================================================

def _write_provisional_cert(cert_dir, issue_number, pending_avatar_keys, commit_short="deadbee"):
    os.makedirs(cert_dir, exist_ok=True)
    path = os.path.join(cert_dir, f"cert_{commit_short}.json")
    cert = {
        "commit_short": commit_short,
        "issued_at": "2026-07-30T00:00:00",
        "provisional": {
            "mode": "provisional",
            "issue_number": issue_number,
            "status": "pending",
            "pending_avatar_keys": pending_avatar_keys,
            "screenshots_by_avatar": {},
            "filed_at": "2026-07-30T00:00:00",
            "error": None,
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cert, f, ensure_ascii=False, indent=2)
    return path, cert


def test_confirm_provisional_confirms_and_closes_when_approval_comment_present(tmp_path):
    release = _import_release()
    cert_path, _ = _write_provisional_cert(str(tmp_path), 273, [])

    def fake_fetch(issue_number):
        assert issue_number == 273
        return _issue_doc(), [_comment("pandrabox", "承認")]

    closed = {"called": False}

    def fake_close(issue_number, run_fn=None, repo=release.APPROVAL_ISSUE_REPO):
        closed["called"] = True
        return True, "OK"

    report = DummyReport()
    rc, message = release.run_confirm_provisional_flow(
        273, report, fetch_fn=fake_fetch,
        cert_lookup_fn=lambda n: release.find_provisional_cert_by_issue(n, cert_dir=str(tmp_path)),
        close_fn=fake_close)

    assert rc == 0
    assert closed["called"] is True
    with open(cert_path, encoding="utf-8") as f:
        updated = json.load(f)
    assert updated["provisional"]["status"] == "confirmed"


def test_confirm_provisional_fails_when_no_approval_comment(tmp_path):
    """負の対照: 承認コメントが無い -> rc!=0、certは更新されない"""
    release = _import_release()
    cert_path, _ = _write_provisional_cert(str(tmp_path), 273, [])

    def fake_fetch(issue_number):
        return _issue_doc(), [_comment("pandrabox", "見てます、まだです")]

    report = DummyReport()
    rc, message = release.run_confirm_provisional_flow(
        273, report, fetch_fn=fake_fetch,
        cert_lookup_fn=lambda n: release.find_provisional_cert_by_issue(n, cert_dir=str(tmp_path)),
        close_fn=lambda *a, **k: (True, "OK"))

    assert rc != 0
    with open(cert_path, encoding="utf-8") as f:
        unchanged = json.load(f)
    assert unchanged["provisional"]["status"] == "pending"


def test_confirm_provisional_requires_ss_approval_when_pak_changed(tmp_path):
    """pak変更を伴う仮リリースは、通常の承認コメントだけではconfirmedにならない
    (SS検収の承認コメントも必要)"""
    release = _import_release()
    _write_provisional_cert(str(tmp_path), 273, ["vrm1_seedsan"])

    def fake_fetch(issue_number):
        return _issue_doc(), [_comment("pandrabox", "承認")]  # SS承認コメント無し

    report = DummyReport()
    rc, message = release.run_confirm_provisional_flow(
        273, report, fetch_fn=fake_fetch,
        cert_lookup_fn=lambda n: release.find_provisional_cert_by_issue(n, cert_dir=str(tmp_path)),
        close_fn=lambda *a, **k: (True, "OK"))

    assert rc != 0
    assert "SS" in message


def test_confirm_provisional_confirms_when_both_approval_and_ss_approval_present(tmp_path):
    release = _import_release()
    cert_path, _ = _write_provisional_cert(str(tmp_path), 273, ["vrm1_seedsan", "vrm0_kate"])

    def fake_fetch(issue_number):
        return _issue_doc(), [
            _comment("pandrabox", "承認"),
            _comment("pandrabox", "SS承認 vrm1_seedsan vrm0_kate 両方OK"),
        ]

    report = DummyReport()
    rc, message = release.run_confirm_provisional_flow(
        273, report, fetch_fn=fake_fetch,
        cert_lookup_fn=lambda n: release.find_provisional_cert_by_issue(n, cert_dir=str(tmp_path)),
        close_fn=lambda *a, **k: (True, "OK"))

    assert rc == 0
    with open(cert_path, encoding="utf-8") as f:
        updated = json.load(f)
    assert updated["provisional"]["status"] == "confirmed"


def test_confirm_provisional_fails_when_cert_not_found(tmp_path):
    release = _import_release()
    report = DummyReport()
    rc, message = release.run_confirm_provisional_flow(
        999, report,
        fetch_fn=lambda n: (_ for _ in ()).throw(AssertionError("fetchすべきでない")),
        cert_lookup_fn=lambda n: release.find_provisional_cert_by_issue(n, cert_dir=str(tmp_path)),
        close_fn=lambda *a, **k: (True, "OK"))
    assert rc != 0
    assert "見つからない" in message


# =====================================================================
# ④ 否認コメント -> rc!=0で指揮者向けメッセージ
# =====================================================================

def test_confirm_provisional_rejected_by_rejection_comment(tmp_path):
    release = _import_release()
    cert_path, _ = _write_provisional_cert(str(tmp_path), 273, [])

    def fake_fetch(issue_number):
        return _issue_doc(), [_comment("pandrabox", "否認")]

    closed = {"called": False}

    report = DummyReport()
    rc, message = release.run_confirm_provisional_flow(
        273, report, fetch_fn=fake_fetch,
        cert_lookup_fn=lambda n: release.find_provisional_cert_by_issue(n, cert_dir=str(tmp_path)),
        close_fn=lambda *a, **k: closed.__setitem__("called", True) or (True, "OK"))

    assert rc != 0
    assert "revert" in message and "指揮者" in message
    assert closed["called"] is False, "否認時はissueをcloseしてはならない"
    with open(cert_path, encoding="utf-8") as f:
        unchanged = json.load(f)
    assert unchanged["provisional"]["status"] == "pending"


def test_confirm_provisional_rejection_wins_over_approval_comment(tmp_path):
    """否認コメントは承認コメントより優先される(両方あっても否認扱い、
    fail-closedの向きを間違えない)"""
    release = _import_release()
    _write_provisional_cert(str(tmp_path), 273, [])

    def fake_fetch(issue_number):
        return _issue_doc(), [_comment("pandrabox", "承認"), _comment("pandrabox", "やっぱり否認")]

    report = DummyReport()
    rc, message = release.run_confirm_provisional_flow(
        273, report, fetch_fn=fake_fetch,
        cert_lookup_fn=lambda n: release.find_provisional_cert_by_issue(n, cert_dir=str(tmp_path)),
        close_fn=lambda *a, **k: (True, "OK"))

    assert rc != 0
    assert "revert" in message


def test_evaluate_provisional_confirmation_pure_function_matrix():
    release = _import_release()
    issue_doc = _issue_doc()

    result, _ = release.evaluate_provisional_confirmation(issue_doc, [], [])
    assert result == "pending"

    result, _ = release.evaluate_provisional_confirmation(
        issue_doc, [_comment("someone-else", "承認")], [])
    assert result == "pending", "他人の承認コメントは無効"

    result, _ = release.evaluate_provisional_confirmation(
        issue_doc, [_comment("pandrabox", "OK")], [])
    assert result == "confirmed"

    result, _ = release.evaluate_provisional_confirmation(
        issue_doc, [_comment("pandrabox", "NG")], [])
    assert result == "rejected"


# =====================================================================
# ⑥ confirm前の版が「公開可」と判定されないこと(is_release_publishable)
# =====================================================================

def test_is_release_publishable_true_for_normal_release_without_provisional_key():
    release = _import_release()
    cert = {"commit_short": "abc1234"}  # provisionalキー自体が無い(通常リリース)
    assert release.is_release_publishable(cert) is True


def test_is_release_publishable_false_before_confirm():
    """負の対照(コーディネータ訂正⑥): 仮リリース直後(status=pending)は公開不可"""
    release = _import_release()
    cert = {"provisional": {"status": "pending", "issue_number": 273}}
    assert release.is_release_publishable(cert) is False


def test_is_release_publishable_false_when_rejected():
    release = _import_release()
    cert = {"provisional": {"status": "rejected", "issue_number": 273}}
    assert release.is_release_publishable(cert) is False


def test_is_release_publishable_true_after_confirmed():
    release = _import_release()
    cert = {"provisional": {"status": "confirmed", "issue_number": 273}}
    assert release.is_release_publishable(cert) is True


# =====================================================================
# main()統合: --provisionalは承認issueゲート自体をスキップして先へ進む
# =====================================================================

def test_main_provisional_skips_approval_gate_and_proceeds(tmp_path, monkeypatch):
    """正の対照: --provisional指定時は run_approval_gate を一切呼ばずに
    git tree確認まで進む(承認issueゲートが確実にスキップされていることの確認)。"""
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))

    called = {"run_approval_gate": False, "get_head_full": False}
    monkeypatch.setattr(
        release, "run_approval_gate",
        lambda issue_number, report: called.__setitem__("run_approval_gate", True) or (True, "dummy"))

    def fake_get_head_full():
        called["get_head_full"] = True
        return "deadbeef"

    monkeypatch.setattr(release, "get_head_full", fake_get_head_full)
    monkeypatch.setattr(release, "get_head_short", lambda: "deadbee")
    # working treeをdirty扱いにして、それ以降には進ませずrc=1で早期終了させる
    # (このテストの関心はrun_approval_gateが呼ばれないことと、get_head_fullまで
    # 到達することだけ)。
    monkeypatch.setattr(
        release, "check_tree_clean_with_allow_dirty",
        lambda allow_dirty_norm: (False, "M some_file.py\n", ["M some_file.py"], set()))

    rc = release.main(["--bump", "patch", "--pak", "none", "--provisional"])

    assert rc == 1
    assert called["run_approval_gate"] is False, "--provisional指定時はrun_approval_gateを呼んではならない"
    assert called["get_head_full"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
