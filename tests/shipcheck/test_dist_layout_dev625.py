# -*- coding: utf-8 -*-
r"""dev#625(dist直下レイアウト整備: 最新zip1個+old\+BOOTH_PASTE.txt+
ITCH_PASTE.htmlの4構成、2026-08-01オーナー裁定)の受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、この変更は
pak不変(Layers-Affected: none)のため、本試験は単体テスト+負の対照のみで
受入とする(実dist\へは一切書き込まない、すべて一時ディレクトリで代替する)。

対象:
  1. move_old_dist_zips: 今回配布したzip以外(付随provenance.json含む)を
     dist\old\へ移動する。今回のzipは移動しない。
  2. append_booth_history: 「■更新履歴」セクション末尾へ追記する。
     既存本文には一切触れない(負の対照: 見出しが無ければ追記せずWARN)。
  3. audit_dist_layout: 4構成以外が残っていればWARN。想定外のzipは
     dist\old\へ自動退避、zip以外の未知ファイルは移動せずWARNのみ
     (負の対照2点)。
  4. extract_version_from_zip_filename: 新旧どちらの命名からもバージョンを
     復元できる。

実行: python -m pytest tests\shipcheck\test_dist_layout_dev625.py -v
"""
import importlib
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

    def joined(self):
        return "\n".join(self.lines)


def _make_file(path, content=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# =====================================================================
# move_old_dist_zips: 今回版以外(+付随provenance.json)をold\へ、今回版は残す
# =====================================================================

def test_move_old_dist_zips_moves_others_and_keeps_current(tmp_path):
    release = _import_release()
    dist = tmp_path / "dist"
    dist.mkdir()
    current = dist / "Uchinoko_v9.9.9_full.zip"
    old1 = dist / "Uchinoko_for_Palworld_v1.0.0_full.zip"
    old1_prov = dist / "Uchinoko_for_Palworld_v1.0.0_full.zip.provenance.json"
    old2 = dist / "Uchinoko_v9.9.8_full.zip"
    _make_file(current, "current")
    _make_file(old1, "old1")
    _make_file(old1_prov, "{}")
    _make_file(old2, "old2")

    report = DummyReport()
    result = release.move_old_dist_zips(str(current), dist_dir=str(dist), report=report)

    assert current.is_file(), "今回配布したzipが移動されてしまった"
    assert not old1.exists() and not old1_prov.exists() and not old2.exists()
    old_dir = dist / "old"
    assert (old_dir / "Uchinoko_for_Palworld_v1.0.0_full.zip").is_file()
    assert (old_dir / "Uchinoko_for_Palworld_v1.0.0_full.zip.provenance.json").is_file()
    assert (old_dir / "Uchinoko_v9.9.8_full.zip").is_file()
    assert len(result["moved"]) == 3
    assert result["errors"] == []


def test_move_old_dist_zips_no_op_when_only_current_present(tmp_path):
    release = _import_release()
    dist = tmp_path / "dist"
    dist.mkdir()
    current = dist / "Uchinoko_v9.9.9_full.zip"
    _make_file(current, "current")

    result = release.move_old_dist_zips(str(current), dist_dir=str(dist))
    assert result["moved"] == []
    assert current.is_file()


# =====================================================================
# append_booth_history: セクション末尾へ追記、既存本文は不変
# =====================================================================

def _sample_booth_paste():
    return (
        "商品説明の冒頭\n"
        "\n"
        "■特徴\n"
        "・なにか\n"
        "\n"
        "■更新履歴\n"
        "【v1.0.0】\n"
        "・最初のリリース\n"
        "\n"
        "※旧履歴は旧ページ参照\n"
        "\n"
        "---\n"
    )


def test_append_booth_history_appends_at_section_tail_without_touching_existing_text(tmp_path):
    release = _import_release()
    booth_path = tmp_path / "BOOTH_PASTE.txt"
    original = _sample_booth_paste()
    _make_file(booth_path, original)

    report = DummyReport()
    ok, detail = release.append_booth_history(
        "v2.0.0", ["・新機能を追加しました"], booth_paste_path=str(booth_path), report=report)

    assert ok, detail
    new_text = booth_path.read_text(encoding="utf-8")
    # 既存本文の行はすべて順序どおり残っている(削除・書き換えなし)。
    # 2026-08-01修正: 挿入位置が「※」注記の前(本文の途中)になったため、
    # 単純な部分文字列一致(rstripしたoriginal全体がnew_textにそのまま
    # 連続して現れる)では検査できなくなった。行ごとの部分列(subsequence)
    # 一致で「全行が元の順序を保ったまま残っている」ことを確認する。
    orig_lines = [ln for ln in original.splitlines()]
    new_lines = new_text.splitlines()
    it = iter(new_lines)
    for ln in orig_lines:
        assert ln in it, f"既存行が消えている、または順序が崩れている: {ln!r}"
    # 新版節が追記されている。
    assert "【v2.0.0】" in new_text
    assert "・新機能を追加しました" in new_text
    # 追記は既存本文より後ろに来る(末尾への追記)。
    assert new_text.index("【v1.0.0】") < new_text.index("【v2.0.0】")
    # 2026-08-01 Masterライター統合時修正: 新版節は「※旧履歴は旧ページ参照」
    # 注記より**前**(バージョン節の連なり末尾)に来ること。旧ロジックは
    # ■見出しのみを終端判定にしていたため、次の■が無いこのフィクスチャでは
    # ファイル末尾(=注記より後ろ)に追記してしまっていた
    # (この行が無いと前記のバグを検出できない、実際に見逃していた)。
    assert new_text.index("【v2.0.0】") < new_text.index("※旧履歴は旧ページ参照"), (
        "新版節が「※」注記より後ろに追記されている(バージョン節の連なり末尾ではない)"
    )
    # 区切りの空行が二重にならないこと(注記直前に元々あった空行1つを吸収し、
    # 新版節側の先頭空行1つだけが区切りとして残るはず)。
    assert "\n\n\n" not in new_text, "新版節と既存本文の間に空行が二重になっている"


def test_append_booth_history_warns_and_skips_when_header_missing(tmp_path):
    """負の対照: 「■更新履歴」見出しが無いファイルは追記せずWARNを返す
    (既存本文には一切触れない、fail-closedにはしない)。"""
    release = _import_release()
    booth_path = tmp_path / "BOOTH_PASTE.txt"
    original = "見出しが無い普通の説明文だけのファイル\n"
    _make_file(booth_path, original)

    report = DummyReport()
    ok, detail = release.append_booth_history(
        "v2.0.0", ["・何か"], booth_paste_path=str(booth_path), report=report)

    assert not ok
    assert booth_path.read_text(encoding="utf-8") == original, "見出しが無いのに本文が書き換わった"


def test_append_booth_history_warns_when_file_missing(tmp_path):
    release = _import_release()
    missing_path = tmp_path / "does_not_exist.txt"
    ok, detail = release.append_booth_history("v2.0.0", ["・何か"], booth_paste_path=str(missing_path))
    assert not ok
    assert not missing_path.exists()


# =====================================================================
# audit_dist_layout: 4構成のみOK、逸脱はWARN(zipは自動退避、非zipは退避しない)
# =====================================================================

def test_audit_dist_layout_ok_on_exact_four_entries(tmp_path):
    release = _import_release()
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "old").mkdir()
    current = dist / "Uchinoko_v9.9.9_full.zip"
    _make_file(current, "current")
    _make_file(dist / "BOOTH_PASTE.txt", "text")
    _make_file(dist / "ITCH_PASTE.html", "<html></html>")

    result = release.audit_dist_layout(str(current), dist_dir=str(dist))
    assert result["ok"] is True
    assert result["warnings"] == []


def test_audit_dist_layout_warns_and_sweeps_stray_zip(tmp_path):
    """負の対照①: 想定外のzipが残っていたらWARN+dist\\old\\へ自動退避する。"""
    release = _import_release()
    dist = tmp_path / "dist"
    dist.mkdir()
    current = dist / "Uchinoko_v9.9.9_full.zip"
    stray = dist / "Uchinoko_v8.0.0_full.zip"
    _make_file(current, "current")
    _make_file(stray, "stray")
    _make_file(dist / "BOOTH_PASTE.txt", "text")
    _make_file(dist / "ITCH_PASTE.html", "<html></html>")

    result = release.audit_dist_layout(str(current), dist_dir=str(dist))
    assert result["ok"] is False
    assert not stray.exists(), "想定外のzipがdist直下に残ったまま(自動退避されていない)"
    assert (dist / "old" / "Uchinoko_v8.0.0_full.zip").is_file()
    assert len(result["swept_zips"]) == 1


def test_audit_dist_layout_warns_but_does_not_move_unknown_non_zip(tmp_path):
    """負の対照②: zip以外の未知ファイルはWARNのみ、移動しない
    (オーナー裁定「未知の非zipファイルは移動せずWARNのみ」)。"""
    release = _import_release()
    dist = tmp_path / "dist"
    dist.mkdir()
    current = dist / "Uchinoko_v9.9.9_full.zip"
    stray_doc = dist / "unexpected_notes.txt"
    _make_file(current, "current")
    _make_file(stray_doc, "note")
    _make_file(dist / "BOOTH_PASTE.txt", "text")
    _make_file(dist / "ITCH_PASTE.html", "<html></html>")

    result = release.audit_dist_layout(str(current), dist_dir=str(dist))
    assert result["ok"] is False
    assert stray_doc.is_file(), "非zipの未知ファイルが移動されてしまった"
    assert result["swept_zips"] == []
    assert any("unexpected_notes.txt" in w for w in result["warnings"])


# =====================================================================
# extract_version_from_zip_filename: 新旧どちらの命名からも復元できる
# =====================================================================

@pytest.mark.parametrize("filename,expected", [
    ("Uchinoko_v2.3.2_full.zip", "v2.3.2"),
    ("Uchinoko_for_Palworld_v2.2.12_full.zip", "v2.2.12"),
    ("Uchinoko_v2.3.2_full_layouttest.zip", "v2.3.2"),
    ("not_a_release_zip.zip", None),
])
def test_extract_version_from_zip_filename(filename, expected):
    release = _import_release()
    assert release.extract_version_from_zip_filename(filename) == expected


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
