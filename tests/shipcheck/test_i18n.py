# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7/WP-A11(dev#549): 旧 `--check-i18n` 隠しCLI(app\\DiveToPalworld.cs
CheckDictionaryCompleteness L.4921、DetectLangFromCulture L.766)のPython版試験。

旧 test_*_cs.py との違い: `--check-i18n` にはこれまで tests\\shipcheck\\ 配下の
専用ラッパー(test_i18n_cs.py 相当)が存在しなかった(ship_smoke.py が exe を
直接 `--check-i18n` で叩いていただけ)。Python化でその exe 起動手順自体が丸ごと
不要になったため、ここでは app_py\\i18n.py を直接importして同じ検査を行う。

検査しているケース(移植元 CheckDictionaryCompleteness/CheckI18nCli):
  1) Strings.Table 相当(i18n.TABLE)の全キーが5言語とも非空であること
     (app_py\\tests\\test_i18n_keys.py の受入検査と同じ検査対象。二重管理を
     避けるため、ここでは同じロジックを最小限で再確認するだけに留める)。
  2) Strings.ProgressLabels 相当(i18n.PROGRESS_LABELS)も同様。
  3) DetectLangFromCulture(CultureInfo名から表示言語を判定、7ケース)は
     dev#532方針A WP-A11(dev#549)で i18n.detect_lang_from_culture() として
     移植済み。main_window.py の起動時言語判定にも結線した(設定ファイルが
     無い場合のフォールバックとして、OSのUI言語から判定する)。
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import i18n  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]


def test_dictionary_completeness_table():
    """CheckDictionaryCompleteness 相当 その1: Strings.Table(i18n.TABLE)。"""
    missing = []
    for key, values in i18n.TABLE.items():
        for lang in EXPECTED_LANGS:
            if not values.get(lang):
                missing.append((key, lang))
    assert not missing, "i18n.TABLE: 空の訳文 {} (計{}件)".format(missing[:20], len(missing))


def test_dictionary_completeness_progress_labels():
    """CheckDictionaryCompleteness 相当 その2: Strings.ProgressLabels
    (i18n.PROGRESS_LABELS)。"""
    missing = []
    for key, values in i18n.PROGRESS_LABELS.items():
        for lang in EXPECTED_LANGS:
            if not values.get(lang):
                missing.append((key, lang))
    assert not missing, (
        "i18n.PROGRESS_LABELS: 空の訳文 {} (計{}件)".format(missing[:20], len(missing))
    )


def test_dictionary_has_meaningful_size():
    # 2026-08-01時点実測(app_py/tests/test_i18n_keys.py と同じ下限、退行検知用)
    assert len(i18n.TABLE) >= 100
    assert len(i18n.PROGRESS_LABELS) >= 10


def test_detect_lang_from_culture():
    """DetectLangFromCulture 相当(7ケース: ja/ko/zh-TW/zh-CN/en/その他/不正)。
    CheckI18nCli(app\\DiveToPalworld.cs L.4954-4970)の単体表と同じ入力・
    期待値をそのまま踏襲する。"""
    cases = [
        ("ja-JP", "ja"),
        ("ko-KR", "ko"),
        ("zh-TW", "zhTW"),
        ("zh-CN", "zhCN"),
        ("en-US", "en"),
        ("fr-FR", "en"),
        (None, "en"),
    ]
    problems = []
    for culture_name, expected in cases:
        actual = i18n.detect_lang_from_culture(culture_name)
        if actual != expected:
            problems.append(
                "input={!r} expected={!r} actual={!r}".format(culture_name, expected, actual)
            )
    assert not problems, "DetectLangFromCulture単体表がFAILした:\n" + "\n".join(problems)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
