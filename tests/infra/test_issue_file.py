# devtools\issue_file.py の単体テスト。
#
# オーナー構想(2026-08-01)の核心:
#   haiku: 似たのあるかな? あるな、よしコメントに書こう / ないな、よし新規起票しよう
#   py:    カテゴリがないからだめです / 担当がないからだめです
#
# ここでは「py側」の検証ロジック(cat:/for:両ラベル必須+署名必須)を、
# 負の対照(欠落・不正値は拒否される)込みで確認する。実GitHubへは一切出ない
# (api_create_issue/api_comment_issue/get_gh_tokenはmonkeypatchで差し替える)。

import sys
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parents[2] / "devtools"
if str(DEVTOOLS) not in sys.path:
    sys.path.insert(0, str(DEVTOOLS))

import issue_file  # noqa: E402

VALID_CAT = "開発基盤"
VALID_ASSIGNEE = "for:ai"
VALID_SIGNATURE_BODY = "本文の内容です。\n\n— Claude(実装者)"


def write_body(tmp_path, text):
    p = tmp_path / "body.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# validate_cat / validate_assignee: 欠落・不正値の拒否(負の対照)
# ---------------------------------------------------------------------------

def test_validate_cat_rejects_missing():
    err = issue_file.validate_cat(None)
    assert err is not None
    assert "カテゴリがないためだめです" in err


def test_validate_cat_rejects_empty_string():
    err = issue_file.validate_cat("")
    assert err is not None
    assert "カテゴリがないためだめです" in err


def test_validate_cat_rejects_unknown_value():
    err = issue_file.validate_cat("存在しないカテゴリ")
    assert err is not None
    assert "カテゴリがないためだめです" in err


@pytest.mark.parametrize("cat", issue_file.CATEGORIES)
def test_validate_cat_accepts_all_eight(cat):
    assert issue_file.validate_cat(cat) is None


def test_validate_assignee_rejects_missing():
    err = issue_file.validate_assignee(None)
    assert err is not None
    assert "担当がないためだめです" in err


def test_validate_assignee_rejects_unknown_value():
    err = issue_file.validate_assignee("for:someone")
    assert err is not None
    assert "担当がないためだめです" in err


@pytest.mark.parametrize("label", issue_file.ASSIGNEE_LABELS)
def test_validate_assignee_accepts_both(label):
    assert issue_file.validate_assignee(label) is None


# ---------------------------------------------------------------------------
# 署名行の検証
# ---------------------------------------------------------------------------

def test_validate_signature_rejects_missing():
    err = issue_file.validate_signature("本文だけで署名がありません。")
    assert err is not None
    assert "署名がないためだめです" in err


def test_validate_signature_rejects_signature_not_at_end():
    """負の対照: 本文中に「Claude」の語があっても、最終行でなければ拒否する。"""
    body = "— Claude(実装者) という署名スタイルを紹介する文書です。\n\n以上、詳細は省略。"
    err = issue_file.validate_signature(body)
    assert err is not None


def test_validate_signature_accepts_role_style():
    assert issue_file.validate_signature("本文です。\n\n— Claude(実装者)") is None


def test_validate_signature_accepts_kito_style():
    assert issue_file.validate_signature("本文です。\n\n— 起票: Claude(指揮者)") is None


def test_validate_signature_accepts_trailing_blank_lines():
    """末尾に空行が続いても、最後の非空行を署名として認識する。"""
    assert issue_file.validate_signature("本文です。\n\n— Claude(実装者)\n\n\n") is None


def test_validate_signature_rejects_empty_body():
    assert issue_file.validate_signature("") is not None
    assert issue_file.validate_signature(None) is not None


# ---------------------------------------------------------------------------
# validate_create_args: 集約(複数欠落は複数エラー)
# ---------------------------------------------------------------------------

def test_validate_create_args_all_valid_returns_no_errors():
    errors = issue_file.validate_create_args("title", VALID_SIGNATURE_BODY, VALID_CAT, VALID_ASSIGNEE)
    assert errors == []


def test_validate_create_args_reports_all_missing_fields():
    errors = issue_file.validate_create_args("", "本文のみ", None, None)
    assert len(errors) == 4  # title, cat, assignee, signature 全部NG
    joined = "\n".join(errors)
    assert "タイトルがないためだめです" in joined
    assert "カテゴリがないためだめです" in joined
    assert "担当がないためだめです" in joined
    assert "署名がないためだめです" in joined


def test_validate_create_args_missing_cat_only():
    errors = issue_file.validate_create_args("title", VALID_SIGNATURE_BODY, None, VALID_ASSIGNEE)
    assert len(errors) == 1
    assert "カテゴリがないためだめです" in errors[0]


def test_validate_create_args_missing_assignee_only():
    errors = issue_file.validate_create_args("title", VALID_SIGNATURE_BODY, VALID_CAT, None)
    assert len(errors) == 1
    assert "担当がないためだめです" in errors[0]


# ---------------------------------------------------------------------------
# validate_comment_args / validate_search_args
# ---------------------------------------------------------------------------

def test_validate_comment_args_rejects_missing_issue_number():
    errors = issue_file.validate_comment_args(None, "本文")
    assert any("issue番号" in e for e in errors)


def test_validate_comment_args_rejects_empty_body():
    errors = issue_file.validate_comment_args(123, "   ")
    assert any("本文がないためだめです" in e for e in errors)


def test_validate_comment_args_accepts_valid():
    assert issue_file.validate_comment_args(123, "コメント本文") == []


def test_validate_search_args_rejects_unknown_cat():
    errors = issue_file.validate_search_args("存在しないカテゴリ", ["kw"])
    assert any("カテゴリがないためだめです" in e for e in errors)


def test_validate_search_args_rejects_empty_keywords():
    errors = issue_file.validate_search_args(VALID_CAT, [])
    assert any("キーワードがないためだめです" in e for e in errors)


# ---------------------------------------------------------------------------
# 除外語(誤検知対策、2026-08-01実測: 重複精査39ペア中38件が「同じ親issueや
# 研究正本を参照しているだけ」の誤検知。真の重複は1件のみだった)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kw",
    ["PROPOSAL", "proposal", "README", "readme", "CLAUDE.md", "claude.md",
     "release.py", "RELEASE.PY", "rd_79", "rd_135", "dev#531", "DEV#1"],
)
def test_is_excluded_keyword_covers_generic_tokens(kw):
    assert issue_file.is_excluded_keyword(kw), kw


@pytest.mark.parametrize(
    "kw",
    ["issue_file.py", "起票スキル", "AbC12345", "TypeError: xyz",
     "gh_app_token.py", "rd_79の派生語ではない普通の語"],
)
def test_is_excluded_keyword_allows_specific_tokens(kw):
    assert not issue_file.is_excluded_keyword(kw), kw


def test_is_excluded_keyword_rejects_empty():
    assert issue_file.is_excluded_keyword("") is True
    assert issue_file.is_excluded_keyword(None) is True


def test_keyword_match_ignores_excluded_tokens_even_when_present():
    issue = {"number": 1, "title": "何か", "body": "PROPOSAL rd_79 dev#531 CLAUDE.md release.py"}
    assert issue_file.keyword_match(issue, ["PROPOSAL", "rd_79", "dev#531", "CLAUDE.md", "release.py"]) == []


def test_keyword_match_ignores_proposal_only_shared_similarity():
    """負の対照(コーディネーター指示、2026-08-01): PROPOSALだけを共有する2件は
    類似と判定してはならない。同じ親研究文書(rd_79)への言及だけの2issueを模す。"""
    issue_a = {"number": 1, "title": "rd_79派生issue A", "body": "PROPOSAL: 方式Aの提案です。dev#79参照。"}
    issue_b = {"number": 2, "title": "rd_79派生issue B", "body": "PROPOSAL: 方式Bの提案です。dev#79参照。"}
    keywords = ["PROPOSAL", "rd_79", "dev#79"]
    assert issue_file.keyword_match(issue_a, keywords) == []
    assert issue_file.keyword_match(issue_b, keywords) == []


def test_keyword_match_still_detects_true_duplicate_via_specific_token():
    """正の対照: 除外語以外の固有トークン(エラー文言)が一致すれば検出できる。"""
    issue = {"number": 3, "title": "帽子が足元に落ちる", "body": "PROPOSAL参照。remap: geo_00 -> 0 pal groups"}
    keywords = ["PROPOSAL", "remap: geo_00 -> 0 pal groups"]
    matched = issue_file.keyword_match(issue, keywords)
    assert matched == ["remap: geo_00 -> 0 pal groups"]


def test_validate_search_args_rejects_all_excluded_keywords():
    errors = issue_file.validate_search_args(VALID_CAT, ["PROPOSAL", "dev#531", "rd_79"])
    assert any("除外語" in e for e in errors)


def test_validate_search_args_accepts_mixed_with_at_least_one_specific_keyword():
    errors = issue_file.validate_search_args(VALID_CAT, ["PROPOSAL", "issue_file.py"])
    assert errors == []


# ---------------------------------------------------------------------------
# cmd_create: バリデーション失敗時はネットワークに一切出ない
# ---------------------------------------------------------------------------

class _CallRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"number": 999, "html_url": "https://example.invalid/999"}


def _make_args(command, **kwargs):
    defaults = {
        "dry_run": False,
        "force_new": False,
    }
    defaults.update(kwargs)
    ns = argparse_namespace(command=command, **defaults)
    return ns


def argparse_namespace(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


def test_cmd_create_rejects_invalid_input_without_calling_api(tmp_path, monkeypatch, capsys):
    recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_create_issue", recorder)
    body_file = write_body(tmp_path, VALID_SIGNATURE_BODY)
    args = _make_args("create", title="t", body_file=body_file, cat=None, assignee_label=VALID_ASSIGNEE)

    rc = issue_file.cmd_create(args)

    assert rc == 2
    assert recorder.calls == []
    err = capsys.readouterr().err
    assert "カテゴリがないためだめです" in err


def test_cmd_create_dry_run_does_not_touch_network(tmp_path, monkeypatch, capsys):
    def _boom(*a, **k):
        raise AssertionError("dry-runなのにネットワーク呼び出しが発生した")

    monkeypatch.setattr(issue_file, "api_create_issue", _boom)
    monkeypatch.setattr(issue_file, "get_gh_token", _boom)
    body_file = write_body(tmp_path, VALID_SIGNATURE_BODY)
    args = _make_args(
        "create", title="[test] dry", body_file=body_file, cat=VALID_CAT,
        assignee_label=VALID_ASSIGNEE, dry_run=True,
    )

    rc = issue_file.cmd_create(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert f"cat:{VALID_CAT}" in out
    assert VALID_ASSIGNEE in out


def test_cmd_create_calls_api_with_both_labels_when_valid(tmp_path, monkeypatch, capsys):
    recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_create_issue", recorder)
    # 重複検索そのものは別テストの対象。ここでは「候補なし」を固定して素通りさせる。
    monkeypatch.setattr(issue_file, "find_duplicate_candidates", lambda *a, **k: ([], ["ok"]))
    body_file = write_body(tmp_path, VALID_SIGNATURE_BODY)
    args = _make_args(
        "create", title="[test] ok", body_file=body_file, cat=VALID_CAT,
        assignee_label=VALID_ASSIGNEE,
    )

    rc = issue_file.cmd_create(args)

    assert rc == 0
    assert len(recorder.calls) == 1
    call_args, _ = recorder.calls[0]
    title, body, labels = call_args[0], call_args[1], call_args[2]
    assert title == "[test] ok"
    assert labels == [f"cat:{VALID_CAT}", VALID_ASSIGNEE]
    out = capsys.readouterr().out
    assert "#999" in out


# ---------------------------------------------------------------------------
# derive_title_keywords / find_duplicate_candidates: createの内蔵重複検索
# ---------------------------------------------------------------------------

def test_derive_title_keywords_splits_on_brackets_and_space():
    keywords = issue_file.derive_title_keywords("[test] issue_file.py の起票スキル")
    assert "test" in keywords
    assert "issue_file.py" in keywords
    assert "の" not in keywords  # 1文字トークンは捨てる


def test_derive_title_keywords_drops_excluded_tokens():
    keywords = issue_file.derive_title_keywords("PROPOSAL rd_79 dev#531 の続き")
    assert "PROPOSAL" not in keywords
    assert "rd_79" not in keywords
    assert "dev#531" not in keywords


def test_derive_title_keywords_empty_title():
    assert issue_file.derive_title_keywords("") == []
    assert issue_file.derive_title_keywords(None) == []


def test_find_duplicate_candidates_skips_api_when_no_usable_keywords(monkeypatch):
    recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_search_issues", recorder)

    candidates, keywords = issue_file.find_duplicate_candidates("PROPOSAL", VALID_CAT)

    assert candidates == []
    assert keywords == []
    assert recorder.calls == []  # 除外語しか無いのでAPIすら呼ばない


def test_find_duplicate_candidates_reports_matching_open_issues(monkeypatch):
    fake_issues = [
        {"number": 42, "title": "起票スキル動作確認", "body": "既存の詳細"},
        {"number": 43, "title": "無関係のissue", "body": "別の話題"},
    ]
    monkeypatch.setattr(issue_file, "api_search_issues", lambda *a, **k: fake_issues)

    candidates, keywords = issue_file.find_duplicate_candidates("[test] 起票スキル動作確認", VALID_CAT)

    assert keywords  # 除外語以外が残っている
    assert [c["number"] for c in candidates] == [42]


# ---------------------------------------------------------------------------
# cmd_create: 内蔵重複検索(2026-08-01追加要件、①負の対照/②--force-newで通過)
# ---------------------------------------------------------------------------

def test_cmd_create_rejects_when_duplicate_candidate_found(tmp_path, monkeypatch, capsys):
    """負の対照①: 重複候補が1件でもあればcreateはAPIを呼ばず拒否する。"""
    create_recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_create_issue", create_recorder)
    monkeypatch.setattr(
        issue_file, "find_duplicate_candidates",
        lambda *a, **k: ([{"number": 42, "title": "既存issue", "matched": ["起票スキル"]}], ["起票スキル"]),
    )
    body_file = write_body(tmp_path, VALID_SIGNATURE_BODY)
    args = _make_args(
        "create", title="[test] 起票スキル動作確認", body_file=body_file, cat=VALID_CAT,
        assignee_label=VALID_ASSIGNEE,
    )

    rc = issue_file.cmd_create(args)

    assert rc == 3
    assert create_recorder.calls == []
    err = capsys.readouterr().err
    assert "重複の可能性があります" in err
    assert "#42" in err
    assert "--force-new" in err


def test_cmd_create_force_new_bypasses_duplicate_check(tmp_path, monkeypatch, capsys):
    """正の対照②: --force-new を付ければ重複検索自体をスキップして起票できる。"""
    create_recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_create_issue", create_recorder)

    def _boom(*a, **k):
        raise AssertionError("--force-newなのに重複検索(find_duplicate_candidates)が呼ばれた")

    monkeypatch.setattr(issue_file, "find_duplicate_candidates", _boom)
    body_file = write_body(tmp_path, VALID_SIGNATURE_BODY)
    args = _make_args(
        "create", title="[test] 起票スキル動作確認", body_file=body_file, cat=VALID_CAT,
        assignee_label=VALID_ASSIGNEE, force_new=True,
    )

    rc = issue_file.cmd_create(args)

    assert rc == 0
    assert len(create_recorder.calls) == 1
    out = capsys.readouterr().out
    assert "#999" in out


def test_cmd_create_no_duplicate_candidates_creates_normally(tmp_path, monkeypatch, capsys):
    """正の対照: 重複検索は実行されるが候補0件なら通常どおり起票する。"""
    create_recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_create_issue", create_recorder)
    search_recorder = _CallRecorder()
    search_recorder.calls = []

    def fake_find_duplicates(title, cat, **kwargs):
        search_recorder.calls.append((title, cat))
        return [], ["起票スキル"]

    monkeypatch.setattr(issue_file, "find_duplicate_candidates", fake_find_duplicates)
    body_file = write_body(tmp_path, VALID_SIGNATURE_BODY)
    args = _make_args(
        "create", title="[test] 完全に新規のissue", body_file=body_file, cat=VALID_CAT,
        assignee_label=VALID_ASSIGNEE,
    )

    rc = issue_file.cmd_create(args)

    assert rc == 0
    assert len(search_recorder.calls) == 1
    assert len(create_recorder.calls) == 1


# ---------------------------------------------------------------------------
# cmd_comment
# ---------------------------------------------------------------------------

def test_cmd_comment_rejects_invalid_input_without_calling_api(tmp_path, monkeypatch, capsys):
    recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_comment_issue", recorder)
    body_file = write_body(tmp_path, "   ")
    args = _make_args("comment", issue=1, body_file=body_file)

    rc = issue_file.cmd_comment(args)

    assert rc == 2
    assert recorder.calls == []


def test_cmd_comment_dry_run_does_not_touch_network(tmp_path, monkeypatch, capsys):
    def _boom(*a, **k):
        raise AssertionError("dry-runなのにネットワーク呼び出しが発生した")

    monkeypatch.setattr(issue_file, "api_comment_issue", _boom)
    monkeypatch.setattr(issue_file, "get_gh_token", _boom)
    body_file = write_body(tmp_path, "似ているissueへの追記コメントです。")
    args = _make_args("comment", issue=450, body_file=body_file, dry_run=True)

    rc = issue_file.cmd_comment(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "#450" in out


def test_cmd_comment_calls_api_when_valid(tmp_path, monkeypatch, capsys):
    recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_comment_issue", recorder)
    body_file = write_body(tmp_path, "追記コメントです。")
    args = _make_args("comment", issue=450, body_file=body_file)

    rc = issue_file.cmd_comment(args)

    assert rc == 0
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# cmd_search
# ---------------------------------------------------------------------------

def test_cmd_search_rejects_invalid_cat_without_calling_api(monkeypatch, capsys):
    recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_search_issues", recorder)
    args = _make_args("search", cat="存在しないカテゴリ", keywords=["kw"])

    rc = issue_file.cmd_search(args)

    assert rc == 2
    assert recorder.calls == []


def test_cmd_search_dry_run_does_not_touch_network(monkeypatch, capsys):
    def _boom(*a, **k):
        raise AssertionError("dry-runなのにネットワーク呼び出しが発生した")

    monkeypatch.setattr(issue_file, "api_search_issues", _boom)
    monkeypatch.setattr(issue_file, "get_gh_token", _boom)
    args = _make_args("search", cat=VALID_CAT, keywords=["issue_file", "起票"], dry_run=True)

    rc = issue_file.cmd_search(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert VALID_CAT in out


def test_cmd_search_rejects_all_excluded_keywords_without_calling_api(monkeypatch, capsys):
    recorder = _CallRecorder()
    monkeypatch.setattr(issue_file, "api_search_issues", recorder)
    args = _make_args("search", cat=VALID_CAT, keywords=["PROPOSAL", "dev#531"])

    rc = issue_file.cmd_search(args)

    assert rc == 2
    assert recorder.calls == []
    err = capsys.readouterr().err
    assert "除外語" in err


def test_cmd_search_does_not_flag_proposal_only_sharing_as_match(monkeypatch, capsys):
    """負の対照: PROPOSAL/rd_/dev#しか共有していないissueは一致として報告しない。"""
    fake_issues = [
        {"number": 10, "title": "rd_79派生issue", "body": "PROPOSAL: 別方式の提案。dev#79参照。"},
    ]
    monkeypatch.setattr(issue_file, "api_search_issues", lambda *a, **k: fake_issues)
    args = _make_args("search", cat=VALID_CAT, keywords=["PROPOSAL", "issue_file.py"])

    rc = issue_file.cmd_search(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "#10" not in out
    assert "一致なし" in out


def test_cmd_search_reports_keyword_matches(monkeypatch, capsys):
    fake_issues = [
        {"number": 1, "title": "起票スキルを作る", "body": "issue_file.pyの設計メモ"},
        {"number": 2, "title": "無関係のissue", "body": "別の話題"},
        {"number": 3, "title": "PRです", "body": "本文", "pull_request": {}},
    ]
    monkeypatch.setattr(issue_file, "api_search_issues", lambda *a, **k: fake_issues)
    args = _make_args("search", cat=VALID_CAT, keywords=["issue_file"])

    rc = issue_file.cmd_search(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "#1" in out
    assert "#2" not in out
    assert "#3" not in out  # PRは除外される


# ---------------------------------------------------------------------------
# build_parser: CLI引数の受理(スモーク)
# ---------------------------------------------------------------------------

def test_build_parser_parses_all_three_subcommands(tmp_path):
    parser = issue_file.build_parser()
    body_file = write_body(tmp_path, VALID_SIGNATURE_BODY)

    a1 = parser.parse_args(["search", "--cat", VALID_CAT, "--keywords", "a", "b", "--dry-run"])
    assert a1.command == "search"
    assert a1.keywords == ["a", "b"]

    a2 = parser.parse_args([
        "create", "--title", "t", "--body-file", body_file,
        "--cat", VALID_CAT, "--assignee-label", VALID_ASSIGNEE, "--dry-run",
    ])
    assert a2.command == "create"

    a3 = parser.parse_args(["comment", "--issue", "450", "--body-file", body_file, "--dry-run"])
    assert a3.command == "comment"
    assert a3.issue == 450
