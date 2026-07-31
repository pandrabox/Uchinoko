# -*- coding: utf-8 -*-
r"""dev#204(2026-07-29ぱん裁定「サポート運用がリリースをブロックしない構造に
する」、同日改訂「ブラックリストを.releaseignoreへ明示ファイル化・安全側の
自己検査を追加」)の受入試験。

release.py の working tree クリーン判定を、リポジトリ直下 .releaseignore に
明示列挙されたパス(ブラックリスト方式)だけWARN扱いにするよう変更した。
未列挙のパスは既定で従来どおり即FAILする。加えて、.releaseignoreのエントリが
出荷スコープ(SHIP_SCOPE_DIR_PREFIXES/SHIP_SCOPE_FILES)と交差すると
release.py自体が起動時に即FAILする安全弁(validate_releaseignore_entries)を
検証する。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、実git操作・実
release.py本番実行は一切課さない(porcelain出力を模した文字列/一時ファイルの
.releaseignoreに対する純関数テストのみ)。

対象の負の対照:
  (a) .releaseignore に pipeline/ を書く -> 設定自体が違法(出荷スコープと
      交差)として即FAIL(validate_releaseignore_entriesが違反を返す)。
  (b) .releaseignore記載パスのみ汚れている -> ブロックせずWARN通過。
  (c) .releaseignore未記載パスの汚れ -> 従来どおりFAIL(ブラックリスト方式の
      既定=ブロック、を確認)。

実行: python -m pytest tests\shipcheck\test_release_clean_scope.py -v
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_release():
    return importlib.import_module("release")


def _line(status, path):
    return f"{status} {path}"


# =====================================================================
# validate_releaseignore_entries: 安全側の自己検査(ここが肝)
# =====================================================================

def test_releaseignore_entry_equal_to_ship_scope_dir_is_illegal_negative_control_a():
    """負の対照(a): .releaseignore に pipeline/ を書く -> 設定自体が違法。"""
    release = _import_release()
    violations = release.validate_releaseignore_entries(["pipeline/"])
    assert violations, "pipeline/ を releaseignore に書いても違反が検出されなかった"


def test_releaseignore_entry_matching_each_ship_scope_dir_is_illegal():
    """SHIP_SCOPE_DIR_PREFIXESの全項目がそれぞれ単独でも違法判定されること
    (pipeline以外の抜け漏れが無いことの網羅確認)。"""
    release = _import_release()
    for prefix in release.SHIP_SCOPE_DIR_PREFIXES:
        violations = release.validate_releaseignore_entries([prefix])
        assert violations, f"{prefix} が releaseignore で許容されてしまった"


def test_releaseignore_entry_matching_ship_scope_file_is_illegal():
    release = _import_release()
    for f in release.SHIP_SCOPE_FILES:
        violations = release.validate_releaseignore_entries([f])
        assert violations, f"{f} が releaseignore で許容されてしまった"


def test_releaseignore_entry_nested_inside_ship_scope_dir_is_illegal():
    """出荷スコープディレクトリの配下(例: pipeline/py)を指定した場合も違法。"""
    release = _import_release()
    violations = release.validate_releaseignore_entries(["pipeline/py"])
    assert violations


def test_releaseignore_entry_that_would_swallow_ship_scope_dir_is_illegal():
    """出荷スコープより上位のディレクトリ(例: devtools/ 全体、gate scriptを
    包含してしまう)を指定した場合も違法(逆方向の交差)。"""
    release = _import_release()
    violations = release.validate_releaseignore_entries(["devtools/"])
    assert violations, "devtools/ はgate scriptを包含するのに違反が出なかった"


def test_releaseignore_empty_or_root_entry_is_illegal():
    release = _import_release()
    for bad in ("", "/", "."):
        violations = release.validate_releaseignore_entries([bad])
        assert violations, f"空/ルート相当のエントリ {bad!r} が許容されてしまった"


def test_releaseignore_default_entries_are_legal():
    """本PRで .releaseignore に実際に書く既定エントリ群が、全て合法
    (出荷スコープと非交差)であることを確認する(自己矛盾していないか)。"""
    release = _import_release()
    default_entries = [".devonly/", "infra/", "work/", "docs/", ".claude/"]
    violations = release.validate_releaseignore_entries(default_entries)
    assert violations == [], f"既定の.releaseignoreエントリが違法判定された: {violations}"


def test_releaseignore_unrelated_entries_are_legal():
    release = _import_release()
    violations = release.validate_releaseignore_entries(
        ["research/", "prompts/", ".github/", "ico/"])
    assert violations == []


# =====================================================================
# load_releaseignore_entries: ファイル読み込み
# =====================================================================

def test_load_releaseignore_missing_file_returns_empty(tmp_path):
    release = _import_release()
    entries = release.load_releaseignore_entries(str(tmp_path / "no_such_file"))
    assert entries == []


def test_load_releaseignore_parses_comments_and_blank_lines(tmp_path):
    release = _import_release()
    p = tmp_path / ".releaseignore"
    p.write_text(
        "# comment\n\n.devonly/\n  infra/  \n# another comment\nwork\\\n",
        encoding="utf-8",
    )
    entries = release.load_releaseignore_entries(str(p))
    assert entries == [".devonly", "infra", "work"]


def test_releaseignore_file_in_repo_is_legal_as_committed():
    """本PRでリポジトリ直下に実際にチェックインする .releaseignore を
    load_releaseignore_entries()の既定パスで読み込み、validateを通ることを
    確認する(コミットする実ファイル自体の受入)。"""
    release = _import_release()
    assert os.path.isfile(release.RELEASEIGNORE_PATH), \
        ".releaseignore がリポジトリ直下に存在しない"
    entries = release.load_releaseignore_entries()
    assert entries, ".releaseignore が空(既定エントリが無い)"
    violations = release.validate_releaseignore_entries(entries)
    assert violations == [], f"チェックイン済み.releaseignoreが違法判定された: {violations}"


# =====================================================================
# split_dirty_lines_by_releaseignore: porcelain行の分割(ブラックリスト方式)
# =====================================================================

def test_split_empty_remaining_lines():
    release = _import_release()
    blocking, warn = release.split_dirty_lines_by_releaseignore([], [".devonly/"])
    assert blocking == [] and warn == []


def test_split_listed_path_only_is_warn_only_negative_control_b():
    """負の対照(b): .releaseignore記載パスのみ汚れている -> WARN通過。"""
    release = _import_release()
    lines = [
        _line(" M", ".devonly/support/INQUIRIES.md"),
        _line("??", ".devonly/publish/notes.md"),
    ]
    blocking, warn = release.split_dirty_lines_by_releaseignore(lines, [".devonly/"])
    assert blocking == [], f"releaseignore記載パスの汚れがblockingに入った: {blocking}"
    assert len(warn) == 2


def test_split_unlisted_path_is_blocking_negative_control_c():
    """負の対照(c): .releaseignore未記載パスの汚れ -> 従来どおりFAIL。"""
    release = _import_release()
    lines = [_line(" M", "pipeline/blender/step02_retarget.py")]
    blocking, warn = release.split_dirty_lines_by_releaseignore(
        lines, [".devonly/", "infra/"])
    assert blocking == lines
    assert warn == []


def test_split_with_empty_releaseignore_blocks_everything():
    """.releaseignoreが空(未設定)の場合、既定で全部ブロックする
    (ブラックリスト方式の既定=フェイルセーフの確認)。"""
    release = _import_release()
    lines = [_line(" M", ".devonly/support/INQUIRIES.md")]
    blocking, warn = release.split_dirty_lines_by_releaseignore(lines, [])
    assert blocking == lines
    assert warn == []


def test_split_mixed_listed_and_unlisted_separates_correctly():
    release = _import_release()
    listed_line = _line(" M", ".devonly/support/INQUIRIES.md")
    unlisted_line = _line(" M", "pipeline/py/vp_atlas.py")
    blocking, warn = release.split_dirty_lines_by_releaseignore(
        [listed_line, unlisted_line], [".devonly/", "infra/"])
    assert blocking == [unlisted_line]
    assert warn == [listed_line]


def test_split_prefix_matching_does_not_false_positive_on_similar_names():
    """'infra/'エントリが 'infrastructure_notes/' のような紛らわしい別名まで
    誤って拾わないこと(startswith誤爆の負の対照)。"""
    release = _import_release()
    lines = [_line(" M", "infrastructure_notes/readme.txt")]
    blocking, warn = release.split_dirty_lines_by_releaseignore(lines, ["infra/"])
    assert blocking == lines, "誤って別名ディレクトリまでWARN扱いにしてしまった"
    assert warn == []


def test_split_rename_line_uses_new_path():
    release = _import_release()
    line = "R  .devonly/support/old.md -> pipeline/py/new.py"
    blocking, warn = release.split_dirty_lines_by_releaseignore(
        [line], [".devonly/", "infra/"])
    assert blocking == [line], "rename後がpipeline配下なのにブロックされなかった"


# =====================================================================
# check_tree_clean_from_porcelain との組み合わせ(実際のmain()内の使用順)
# =====================================================================

def test_full_flow_devonly_dirty_passes_with_default_releaseignore():
    """main()の実使用順を模す: allow-dirty未指定でcheck_tree_clean_from_porcelain
    を通した上でreleaseignore splitへ渡しても、.devonly\\汚れはblocking無しに
    なる(既定.releaseignoreがあれば--allow-dirty指定なしでも自動でWARN扱いに
    なることの確認、dev#204の主眼)。"""
    release = _import_release()
    porcelain = " M .devonly/support/INQUIRIES.md\n?? .devonly/publish/x.md\n"
    ok, remaining, matched = release.check_tree_clean_from_porcelain(porcelain, [])
    assert ok is False
    assert len(remaining) == 2
    blocking, warn = release.split_dirty_lines_by_releaseignore(
        remaining, [".devonly/", "infra/", "work/", "docs/", ".claude/"])
    assert blocking == []
    assert len(warn) == 2


def test_full_flow_pipeline_dirty_still_blocks_with_default_releaseignore():
    release = _import_release()
    porcelain = " M pipeline/blender/step01_import_vrm.py\n"
    ok, remaining, matched = release.check_tree_clean_from_porcelain(porcelain, [])
    assert ok is False
    blocking, warn = release.split_dirty_lines_by_releaseignore(
        remaining, [".devonly/", "infra/", "work/", "docs/", ".claude/"])
    assert blocking == remaining
    assert warn == []
