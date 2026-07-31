# -*- coding: utf-8 -*-
r"""infra\ 配下(公開Webページのソース)に、Windows Defender等のセキュリティソフトの
除外設定・保護履歴からの復元・リアルタイム保護の無効化を案内する記述が無いことを
検査する。

背景: `infra\cloudflare\d2p-faq\src\index.js` は `faq.osakishokai.com` に
デプロイ済みの公開FAQページであり、以前は「保護の履歴」→「許可/復元」、
「除外の追加または削除」といった具体的な操作手順を日英両方で案内していた。
これはプロジェクトの絶対禁止事項(CLAUDE.mdの「絶対の禁止事項」節)に反する:

    Windows Defender の設定変更・除外追加をしない。ユーザーにも案内しない
    (マルウェアが要求する典型的手口と同じ形であり、審査の心証も最悪)

本テストは、この種の操作手順の記述が infra\ 配下のどのファイルにも
再混入しないことを継続的に守るガードレール。禁止しているのは「操作手順」
であって、「Windows Defender」「アンチウイルス」等の**言及そのもの**では
ない(誤検知の説明として言及すること自体は許容される)。

実行: python -m pytest tests\infra -q
"""
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_INFRA_DIR = os.path.join(_REPO, "infra")

# スキャン対象の拡張子(Cloudflare Workerのソース+設定+ドキュメント)。
_SCAN_EXTS = (".js", ".mjs", ".ts", ".jsonc", ".json", ".md", ".html")

# 具体的な「操作手順」を指す語句のみを禁止する(言及そのものは禁止しない)。
# 大小文字は区別しない(WPの受入基準に合わせる)。
FORBIDDEN_PHRASES = [
    # 日本語: 保護の履歴からの復元・除外設定の操作手順
    "保護の履歴",
    "除外の追加または削除",
    "除外に追加",
    "除外設定",
    "ウイルスと脅威の防止の設定",
    "リアルタイム保護を無効",
    "リアルタイム保護をオフ",
    # 英語: Protection history restore / exclusion configuration steps
    "protection history",
    "add or remove exclusions",
    "exclusion list",
    "add an exclusion",
    "disable real-time protection",
    "turn off real-time protection",
]


def _iter_scan_files():
    for root, _dirs, files in os.walk(_INFRA_DIR):
        # node_modules 等のビルド生成物・依存物は対象外(誤検知源にしかならない)
        if "node_modules" in root.split(os.sep):
            continue
        for name in files:
            if name.lower().endswith(_SCAN_EXTS):
                yield os.path.join(root, name)


def find_forbidden_phrases(text):
    """text中に含まれる禁止句のリストを返す(大小文字を区別しない部分一致)。"""
    lowered = text.lower()
    return [phrase for phrase in FORBIDDEN_PHRASES if phrase.lower() in lowered]


class TestInfraDirExists(unittest.TestCase):
    def test_infra_dir_present_and_scan_finds_files(self):
        """スキャン対象そのものが消えていない(=検査が空振りしていない)ことの前提確認。"""
        self.assertTrue(os.path.isdir(_INFRA_DIR), "infra\\ ディレクトリが見つからない")
        files = list(_iter_scan_files())
        self.assertGreater(len(files), 0, "infra\\ 配下にスキャン対象ファイルが無い")
        # 是正対象だった実ファイルがスキャン範囲に含まれていることを明示的に確認する。
        faq_src = os.path.join(_INFRA_DIR, "cloudflare", "d2p-faq", "src", "index.js")
        self.assertIn(faq_src, files, "d2p-faq/src/index.js がスキャン対象から漏れている")


class TestNoAvExclusionGuidanceInInfra(unittest.TestCase):
    def test_no_forbidden_phrases_anywhere_under_infra(self):
        offenders = {}
        for path in _iter_scan_files():
            with open(path, "r", encoding="utf-8", errors="strict") as f:
                content = f.read()
            hits = find_forbidden_phrases(content)
            if hits:
                rel = os.path.relpath(path, _REPO)
                offenders[rel] = hits
        self.assertEqual(
            offenders, {},
            "infra\\ 配下にDefender等の除外設定・保護履歴からの復元を案内する"
            "記述が見つかった(絶対禁止事項の再混入): %r" % offenders,
        )

    def test_faq_defender_section_still_present_but_gives_no_operational_steps(self):
        """Q1(Defenderに検知された場合)の節自体は残っている(ユーザーの実際の
        困りごとに答える文書は維持する)が、そこに操作手順が無いことをピンポイントで確認する。"""
        faq_src = os.path.join(_INFRA_DIR, "cloudflare", "d2p-faq", "src", "index.js")
        with open(faq_src, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('id="defender"', content, "FAQのDefender節(id=defender)が見つからない")
        start = content.index('id="defender"')
        end = content.index("</section>", start)
        section = content[start:end]
        hits = find_forbidden_phrases(section)
        self.assertEqual(hits, [], "Defender節に操作手順が残っている: %r" % hits)
        # 置き換え後の必須要素(誤検知の説明・新版は未検出・旧版の入手先・署名申請中・問い合わせ導線)
        for must_have_ja, must_have_en in [
            ("最新版のビルドでは検出されていません", "The current release has not been flagged"),
            ("SignPath", "SignPath"),
            ("GitHub Actions", "GitHub Actions"),
        ]:
            self.assertIn(must_have_ja, section)
            self.assertIn(must_have_en, section)


class TestScannerNegativeControl(unittest.TestCase):
    """スキャナ自体が「何も検出できない壊れた検査」になっていないことを示す負の対照。"""

    def test_scanner_detects_each_forbidden_phrase(self):
        for phrase in FORBIDDEN_PHRASES:
            sample = "Some surrounding text mentions %s in the middle of a sentence." % phrase
            hits = find_forbidden_phrases(sample)
            self.assertIn(phrase, hits, "スキャナが %r を検出できていない" % phrase)

    def test_scanner_detects_case_variation(self):
        hits = find_forbidden_phrases("Please review the Protection History and Add or Remove Exclusions.")
        self.assertIn("protection history", hits)
        self.assertIn("add or remove exclusions", hits)

    def test_clean_text_passes(self):
        clean = (
            "This tool bundles general-purpose executables and OSS binaries. "
            "Only the launcher has ever been flagged; the current release is clean, "
            "older releases remain on the download page, builds run via GitHub "
            "Actions, and we are applying for SignPath code signing."
        )
        self.assertEqual(find_forbidden_phrases(clean), [])

    def test_scanner_flags_temp_file_with_forbidden_phrase(self):
        """一時ファイルに禁止句を混入させ、ファイルベースの検査対象に入れた場合に
        確実に落ちることを示す(=検査が機能している)。本物のinfra\\配下には書き込まない。"""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(
                "// 意図的な負の対照: 保護の履歴 から復元してください。\n"
                "// Add or remove exclusions here.\n"
            )
            tmp_path = tmp.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            hits = find_forbidden_phrases(content)
            self.assertIn("保護の履歴", hits)
            self.assertIn("add or remove exclusions", hits)
        finally:
            os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
