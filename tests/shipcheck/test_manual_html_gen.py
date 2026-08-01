# -*- coding: utf-8 -*-
"""dev#444: manual\\manual*.md -> manual\\manual*.html 生成配線の単体表+負の対照。

背景: 配布zipに同梱される唯一の手引き書 manual\\manual.html は、これまで手打ちの
静的ファイルで、manual\\manual.md からの自動生成経路が存在しなかった。
manual.md をいくら修正しても配布物には一切反映されない、という構造的欠陥が
あった(実例: 2026-07-31に追記したWindows Defender誤検知についての開示節が、
一度もユーザーへ届いていなかった)。

本ファイルは devtools\\gen_manual_html.py の変換ロジックを検証する。
  1. 純関数の単体表(inline記法・リスト・HTMLコメント除去・画像埋め込み)。
  2. 負の対照: manual.md の内容を書き換えると、生成されるhtmlの内容も
     追随して変わること(「生成が実際に効いている」ことの証明。
     生成器がキャッシュや固定テンプレートに固着していないかを確認する)。
  3. 実ファイル(現行の manual\\manual.md)を実際に変換し、2026-07-31に
     追記されたAV開示節の文言が生成物に含まれることを確認する
     (この検査が無ければ、次に誰かが manual.md を直しても再び配布物に
     届かない、という同じ穴が再発し得る)。

実行: python -m pytest tests\\shipcheck\\test_manual_html_gen.py -q
"""
import os
import tempfile

import pytest

import gen_manual_html as gm

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
MANUAL_DIR = os.path.join(REPO_ROOT, "manual")


# ---------------------------------------------------------------------------
# 1. inline記法(render_inline)
# ---------------------------------------------------------------------------

def test_render_inline_escapes_raw_html_special_chars():
    assert gm.render_inline("A < B & C > D") == "A &lt; B &amp; C &gt; D"


def test_render_inline_renders_bold():
    assert gm.render_inline("**Unityを終了**します") == "<strong>Unityを終了</strong>します"


def test_render_inline_renders_link():
    out = gm.render_inline("[SECURITY.md](../SECURITY.md) を参照")
    assert out == '<a href="../SECURITY.md">SECURITY.md</a> を参照'


def test_render_inline_renders_italic_without_double_star_conflict():
    out = gm.render_inline("*[English](manual.en.md) | [한국어](manual.ko.md)*")
    assert out.startswith("<em>")
    assert out.endswith("</em>")
    # 言語切替リンクは公開URL(dl.osakishokai.com)へ張り替えられる(下記の
    # test_render_inline_rewrites_language_links_to_public_urls参照)
    assert '<a href="https://dl.osakishokai.com/manual/en">English</a>' in out
    assert "<strong>" not in out  # 単独の*は太字と誤認しないこと


def test_render_inline_rewrites_language_links_to_public_urls():
    """公開ページのR2キーは "manual"/"manual/en" のみ。相対mdファイル名のままだと
    公開HTML上で言語切替リンクが全部404になる(2026-08-01 オーナー実バグ報告)。"""
    out = gm.render_inline("[日本語](manual.md) / [English](manual.en.md)")
    assert '<a href="https://dl.osakishokai.com/manual">日本語</a>' in out
    assert '<a href="https://dl.osakishokai.com/manual/en">English</a>' in out
    # 負の対照: マップ外のリンク先は書き換えない(test_render_inline_renders_linkの
    # 相対リンク素通しと対になる)
    assert gm._resolve_link_target("https://example.com/x") == "https://example.com/x"
    assert gm._resolve_link_target("img/1.webp") == "img/1.webp"


def test_render_inline_bold_and_italic_do_not_cross_contaminate():
    # 太字を含む文中に単独の*が残らないこと(斜体の誤爆防止の負の対照)
    out = gm.render_inline("**初回起動時のみ**、自動的にダウンロードします")
    assert out == "<strong>初回起動時のみ</strong>、自動的にダウンロードします"
    assert "<em>" not in out


# ---------------------------------------------------------------------------
# 2. HTMLコメント除去(開発者向けTODOメモの漏洩防止)
# ---------------------------------------------------------------------------

def test_strip_html_comments_removes_dev_todo_note():
    src = "本文A<!-- TODO: 後で直す -->本文B"
    assert gm.strip_html_comments(src) == "本文A本文B"


def test_render_document_does_not_leak_html_comment_as_visible_text(tmp_path):
    """負の対照: HTMLコメントが除去されずにそのまま出力されると
    `&lt;!-- ... --&gt;`という可視テキストとしてユーザーに見えてしまう
    (実際に本WPの開発中に発生した不具合の再現)。"""
    _write_minimal_manual(tmp_path, extra_paragraph="<!-- TODO: 内部メモ、消し忘れ厳禁 -->")
    html_out = gm.render_document(
        _read(tmp_path / "manual.md"), str(tmp_path), "ja", "目次"
    )
    assert "TODO" not in html_out
    assert "内部メモ" not in html_out
    assert "&lt;!--" not in html_out


# ---------------------------------------------------------------------------
# 3. リスト(順序付き/順序無し、1段ネスト)
# ---------------------------------------------------------------------------

def test_render_list_lines_nested_ordered_list():
    lines = [
        "1. まず確認する",
        "2. それでもだめなら",
        "   1. 手順A",
        "   2. 手順B",
    ]
    html_out, next_pos = gm._render_list_lines(lines, 0, 0)
    assert next_pos == 4
    assert html_out == (
        "<ol><li>まず確認する</li>"
        "<li>それでもだめなら<ol><li>手順A</li><li>手順B</li></ol></li></ol>"
    )


def test_render_list_lines_nested_unordered_list():
    lines = [
        "- トップ項目1",
        "- トップ項目2、子あり",
        "  - 子1",
        "  - 子2",
    ]
    html_out, next_pos = gm._render_list_lines(lines, 0, 0)
    assert next_pos == 4
    assert html_out == (
        "<ul><li>トップ項目1</li>"
        "<li>トップ項目2、子あり<ul><li>子1</li><li>子2</li></ul></li></ul>"
    )


def test_render_list_lines_flat_list_has_no_spurious_nesting():
    lines = ["- A", "- B", "- C"]
    html_out, next_pos = gm._render_list_lines(lines, 0, 0)
    assert next_pos == 3
    assert html_out == "<ul><li>A</li><li>B</li><li>C</li></ul>"
    assert "<ul><li>" not in html_out[len("<ul><li>A</li>"):]  # ネストが混入していない


# ---------------------------------------------------------------------------
# 4. 画像埋め込み(base64)
# ---------------------------------------------------------------------------

def test_embed_image_produces_correct_mime_and_roundtrips(tmp_path):
    import base64
    img_bytes = b"FAKEWEBPBYTES_1234567890"
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "1.webp").write_bytes(img_bytes)
    data_uri = gm._embed_image("img/1.webp", str(tmp_path))
    assert data_uri.startswith("data:image/webp;base64,")
    b64_part = data_uri.split(",", 1)[1]
    assert base64.b64decode(b64_part) == img_bytes


def test_embed_image_raises_when_file_missing(tmp_path):
    with pytest.raises(gm.ManualGenError):
        gm._embed_image("img/does_not_exist.webp", str(tmp_path))


# ---------------------------------------------------------------------------
# 5. render_document 全体(見出し・TOC・段落)
# ---------------------------------------------------------------------------

def _write_minimal_manual(tmp_path, extra_paragraph=None):
    (tmp_path / "img").mkdir(exist_ok=True)
    (tmp_path / "img" / "1.webp").write_bytes(b"IMGBYTES")
    body = [
        "# テストマニュアル",
        "",
        "## セクション1",
        "本文1です",
        "![](img/1.webp)",
        "",
        "## セクション2",
        "本文2です",
    ]
    if extra_paragraph:
        body.insert(1, extra_paragraph)
    (tmp_path / "manual.md").write_text("\n".join(body) + "\n", encoding="utf-8")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_render_document_builds_toc_from_h2_headings_only(tmp_path):
    _write_minimal_manual(tmp_path)
    html_out = gm.render_document(_read(tmp_path / "manual.md"), str(tmp_path), "ja", "目次")
    assert '<nav class="toc"><h2>目次</h2>' in html_out
    assert '<a href="#section-1">セクション1</a>' in html_out
    assert '<a href="#section-2">セクション2</a>' in html_out
    # h1(タイトル)はTOCに含まれない(本文の重複h1も1回しか出ない)
    assert html_out.count("<h1>テストマニュアル</h1>") == 1
    assert '<html lang="ja">' in html_out
    assert "<title>テストマニュアル</title>" in html_out


def test_render_document_requires_h1_title(tmp_path):
    (tmp_path / "manual.md").write_text("## セクションのみ\n本文\n", encoding="utf-8")
    with pytest.raises(gm.ManualGenError):
        gm.render_document(_read(tmp_path / "manual.md"), str(tmp_path), "ja", "目次")


def test_render_document_embeds_image_referenced_in_markdown(tmp_path):
    _write_minimal_manual(tmp_path)
    html_out = gm.render_document(_read(tmp_path / "manual.md"), str(tmp_path), "ja", "目次")
    assert '<figure class="shot"><img src="data:image/webp;base64,' in html_out


# ---------------------------------------------------------------------------
# 6. 負の対照: manual.md の内容変更が生成htmlへ実際に反映されること
# ---------------------------------------------------------------------------

def test_generated_html_changes_when_source_markdown_changes(tmp_path):
    """「生成が効いている」ことの直接証明: 同じmanual.mdを2回生成しても
    同一だが、内容を変えて再生成すると差分が生成物に現れること。"""
    _write_minimal_manual(tmp_path)
    md_path = tmp_path / "manual.md"
    out_path = tmp_path / "manual.html"

    gm.generate_file(str(md_path), str(out_path))
    before = _read(out_path)
    assert "変更前後で入れ替えるユニークマーカーXYZ123" not in before

    # manual.mdへ一意なマーカー文字列を追記して再生成
    md_path.write_text(_read(md_path) + "\n変更前後で入れ替えるユニークマーカーXYZ123\n", encoding="utf-8")
    gm.generate_file(str(md_path), str(out_path))
    after = _read(out_path)
    assert "変更前後で入れ替えるユニークマーカーXYZ123" in after
    assert before != after


def test_generate_file_rejects_unknown_manual_filename(tmp_path):
    p = tmp_path / "readme_not_manual.md"
    p.write_text("# タイトル\n", encoding="utf-8")
    with pytest.raises(gm.ManualGenError):
        gm.generate_file(str(p))


# ---------------------------------------------------------------------------
# 7. 実ファイル統合テスト: 現行 manual\\manual.md / manual.en.md を実際に変換し、
#    2026-07-31に追記されたAV開示節の文言が生成物に含まれることを確認する。
# ---------------------------------------------------------------------------

# manual.md実物のAV節(2026-08-01にユーザー向け短文へ書き直し。旧・監査官向け
# 開示文とSECURITY.md等リポジトリファイル参照は全掃)に実在する文言。この検査が
# あることで、次に誰かがこの節の文言を書き換えても、配布物への配線が切れて
# いないことが機械的に保証される。
_AV_SECTION_MARKERS_JA = [
    "セキュリティソフトに警告・ブロックされる場合",
    "実行ファイル(exe)を同梱しない構成に変更",
]
_AV_SECTION_MARKERS_EN = [
    "Security software shows a warning or blocks the tool",
    "no longer contains any executable (.exe) files",
]


def test_real_manual_md_generates_html_containing_av_disclosure_section():
    md_path = os.path.join(MANUAL_DIR, "manual.md")
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "manual.html")
        gm.generate_file(md_path, out_path)
        html_out = _read(out_path)
    for marker in _AV_SECTION_MARKERS_JA:
        assert marker in html_out, "AV開示節の文言が生成htmlに見つからない: %r" % marker
    # 開発者向けTODOコメントは漏れていないこと
    assert "TODO" not in html_out


def test_real_manual_en_md_generates_html_containing_av_disclosure_section():
    md_path = os.path.join(MANUAL_DIR, "manual.en.md")
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "manual.en.html")
        gm.generate_file(md_path, out_path)
        html_out = _read(out_path)
    for marker in _AV_SECTION_MARKERS_EN:
        assert marker in html_out, "AV disclosure text missing from generated html: %r" % marker
    assert "TODO" not in html_out


def test_real_manual_md_html_has_no_encoding_mojibake():
    """文字化けしないこと: 生成物がUTF-8として問題なくデコードでき、
    日本語の代表的な語がそのまま残ること。"""
    md_path = os.path.join(MANUAL_DIR, "manual.md")
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "manual.html")
        gm.generate_file(md_path, out_path)
        with open(out_path, "rb") as f:
            raw = f.read()
    text = raw.decode("utf-8")  # 失敗したら文字化けまたは不正バイト列
    assert "�" not in text  # 置換文字(U+FFFD)が無いこと
    assert "アバターの使い方" in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
