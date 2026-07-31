# -*- coding: utf-8 -*-
r"""公開FAQページ(`infra\cloudflare\d2p-faq\src\index.js`、faq.osakishokai.com)が、
SignPath Foundationへの申請状況について事実と異なる断定(「申請中」等、既に
申請済みであるかのような表現)をしていないことを検査する(dev signpath WP: FIX23)。

背景: README.md / manual\manual.md 側は既に是正済み(FIX20、
tests\oss_docs\test_accurate_signpath_status.py が守っている)だが、
公開FAQページ(Cloudflare Worker)は書き込み許可の範囲外だったため、
2026-07-31時点で「SignPath Foundation...によるコード署名を申請中です」/
"we are applying for code signing through SignPath Foundation" という同種の
虚偽が取り残されていた(FIX20記録の「6. 他に見つかった同種の露出」参照)。
申請行為そのものはオーナーの手番として残っており、この文書作成時点では
まだSignPathへの実際の申請(オンラインフォーム送信)は行われていない。

また同時に、Defender誤検知の説明として「実際に検出されるのは配布物内の
小さな起動用ファイル(ランチャー)のみ」という現在形の断定があったが、
2026-07-31にビルド側でランチャーを配布物から除去する変更が入ったため、
現在形のまま残すと「配布物内に今もランチャーがある」という含意が事実と
食い違う恐れがあった。本テストは、この断定が除去され、経緯として
説明する表現(過去形+「以降のビルドでは取り除いている」)に置き換わって
いることも合わせて検査する。

実行: python -m pytest tests\infra\test_faq_signpath_status_accurate.py -q
"""
import os
import re
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_FAQ_SRC = os.path.join(_REPO, "infra", "cloudflare", "d2p-faq", "src", "index.js")

# 「既に申請済み・審査中である」と断定する特徴的な文(独立した主張として現れる形)。
# tests\oss_docs\test_accurate_signpath_status.py の FORBIDDEN_ASSERTION_SENTENCES と
# 同種だが、FAQページ固有の文言(「根本的な対策として」等)を追加している。
FORBIDDEN_ASSERTION_SENTENCES = [
    "によるコード署名を申請中",
    "コード署名を申請中です",
    "無償のコード署名を申請中",
    "we are applying for code signing through signpath foundation",
    "currently under review",
    "application in progress",
]

# Defender節の「配布物内に今もランチャーがある」ことを現在形で断定する文言。
# ランチャー廃止(build側)が進んでいる以上、この現在形の断定は再混入させない。
FORBIDDEN_PRESENT_TENSE_LAUNCHER_CLAIMS = [
    "実際に検出されるのは配布物内の小さな起動用ファイル(ランチャー)のみで",
    "in practice, only the small launcher file inside the distributed package has ever been flagged",
]


def _read_faq_source():
    with open(_FAQ_SRC, "r", encoding="utf-8") as f:
        return f.read()


def find_forbidden_assertions(text):
    """text中に含まれる禁止断定フレーズのリストを返す(大小文字を区別しない部分一致、
    空白類は改行含めて単一スペースへ正規化してから照合する)。"""
    normalized = re.sub(r"\s+", " ", text).lower()
    return [p for p in FORBIDDEN_ASSERTION_SENTENCES if re.sub(r"\s+", " ", p.lower()) in normalized]


def find_forbidden_launcher_claims(text):
    normalized = re.sub(r"\s+", " ", text).lower()
    return [p for p in FORBIDDEN_PRESENT_TENSE_LAUNCHER_CLAIMS if re.sub(r"\s+", " ", p.lower()) in normalized]


class TestFaqSourceExists(unittest.TestCase):
    def test_faq_source_present(self):
        self.assertTrue(os.path.isfile(_FAQ_SRC), "d2p-faq/src/index.js が見つからない")


class TestFaqSignpathStatusIsAccurate(unittest.TestCase):
    def test_no_false_application_submitted_claim(self):
        content = _read_faq_source()
        hits = find_forbidden_assertions(content)
        self.assertEqual(
            hits, [],
            "FAQページにSignPathへ既に申請済み/審査中であるかのような断定表現が"
            "見つかった: %r" % hits,
        )

    def test_makes_clear_application_not_yet_submitted(self):
        """置き換え後の文言が「まだ申請していない」ことを明示していること
        (単に断定を消しただけで、状態を説明しない文言に劣化していないかの検査)。"""
        content = _read_faq_source()
        normalized = re.sub(r"\s+", " ", content)
        ja_marker = "まだ申請していません"
        en_marker = "the application has not been submitted yet"
        self.assertIn(ja_marker, normalized, "日本語版に「まだ申請していない」ことを示す文言が無い")
        self.assertIn(en_marker, normalized, "英語版に application not submitted yet の文言が無い")

    def test_still_mentions_signpath(self):
        """SignPath言及自体(申請フォームのDownload URL欄の審査要件)は消えていないこと。"""
        content = _read_faq_source()
        self.assertIn("SignPath Foundation", content)

    def test_no_present_tense_launcher_still_in_package_claim(self):
        content = _read_faq_source()
        hits = find_forbidden_launcher_claims(content)
        self.assertEqual(
            hits, [],
            "FAQページに『配布物内に今もランチャーがある』ことを現在形で断定する"
            "表現が見つかった(ランチャー廃止後は不正確): %r" % hits,
        )

    def test_launcher_removal_mentioned_as_structural_fix(self):
        """ランチャー除去が経緯として(過去形/今後のビルドでの対処として)
        説明されていること。単に文言を消しただけで説明が失われていないかの検査。"""
        content = _read_faq_source()
        self.assertIn("以降のビルドではこの起動用ファイル", content)
        self.assertIn("subsequent builds no longer include", content)

    def test_defender_section_still_present(self):
        content = _read_faq_source()
        self.assertIn('id="defender"', content, "FAQのDefender節(id=defender)が見つからない")


class TestScannerNegativeControl(unittest.TestCase):
    """スキャナ自体が「何も検出できない壊れた検査」になっていないことを示す負の対照。"""

    def test_scanner_detects_each_forbidden_assertion(self):
        for phrase in FORBIDDEN_ASSERTION_SENTENCES:
            sample = "この案内文には %s が意図的に混入している。" % phrase
            hits = find_forbidden_assertions(sample)
            self.assertIn(phrase, hits, "スキャナが %r を検出できていない" % phrase)

    def test_scanner_flags_temp_file_reintroducing_the_removed_text(self):
        """今回除去した文面そのもの(2026-07-31時点でFAQページに実在していた
        文言)を一時ファイルへ書き込み、検査対象に含めた場合に確実に落ちることを
        示す。本物のFAQソースには一切書き込まない。"""
        removed_text_ja = (
            "根本的な対策として、SignPath Foundation"
            "(OSSプロジェクト向けの無償コード署名サービス)によるコード署名を申請中です。\n"
        )
        removed_text_en = (
            "As a structural fix, we are applying for code signing through "
            "SignPath Foundation (a free code-signing service for open-source projects).\n"
        )
        for removed_text in (removed_text_ja, removed_text_en):
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(removed_text)
                tmp_path = tmp.name
            try:
                with open(tmp_path, "r", encoding="utf-8") as f:
                    content = f.read()
                hits = find_forbidden_assertions(content)
                self.assertTrue(hits, "検査対象文言が全く検出されなかった: %r" % removed_text)
            finally:
                os.remove(tmp_path)

    def test_scanner_does_not_flag_the_replacement_wording(self):
        safe_sample_ja = (
            "根本的な対策として、SignPath Foundation"
            "(OSSプロジェクト向けの無償コード署名サービス)によるコード署名の申請を"
            "準備しています(2026-07現在、申請の準備段階であり、まだ申請していません)。"
        )
        safe_sample_en = (
            "As a structural fix, we are preparing to submit an application for code "
            "signing through SignPath Foundation (a free code-signing service for "
            "open-source projects); as of 2026-07, the application has not been "
            "submitted yet."
        )
        self.assertEqual(find_forbidden_assertions(safe_sample_ja), [])
        self.assertEqual(find_forbidden_assertions(safe_sample_en), [])

    def test_scanner_detects_present_tense_launcher_claim(self):
        sample_ja = (
            "実際に検出されるのは配布物内の小さな起動用ファイル(ランチャー)のみで、"
            "変換処理そのものを行う本体ファイルが検出された例はありません。"
        )
        sample_en = (
            "In practice, only the small launcher file inside the distributed "
            "package has ever been flagged; the main application binary that "
            "performs the actual conversion has never been flagged."
        )
        self.assertTrue(find_forbidden_launcher_claims(sample_ja))
        self.assertTrue(find_forbidden_launcher_claims(sample_en))

    def test_scanner_does_not_flag_past_tense_launcher_wording(self):
        safe_sample_ja = (
            "これまでに検出されたのは、配布物内にあった小さな起動用ファイル"
            "(ランチャー)のみで、変換処理そのものを行う本体ファイルが検出された"
            "例はありません。この構造的な原因を取り除くため、以降のビルドでは"
            "この起動用ファイル(ランチャー)自体を配布物から取り除いています。"
        )
        safe_sample_en = (
            "So far, only the small launcher file that used to be included in the "
            "distributed package has ever been flagged. To remove this structural "
            "cause, subsequent builds no longer include that separate launcher "
            "file in the distributed package."
        )
        self.assertEqual(find_forbidden_launcher_claims(safe_sample_ja), [])
        self.assertEqual(find_forbidden_launcher_claims(safe_sample_en), [])


if __name__ == "__main__":
    unittest.main()
