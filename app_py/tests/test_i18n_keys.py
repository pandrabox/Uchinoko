# test_i18n_keys.py -- WP-A1受入条件②: i18n_data.json の全キーが5言語とも
# 非空であることを機械検査する(旧 --check-i18n / CheckDictionaryCompleteness
# L.4921 相当のPython版試験。DESIGN.md §5.2 WP-A1行)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]


def test_langs_constant_matches_expected():
    assert i18n.LANGS == EXPECTED_LANGS


def test_table_not_empty():
    # 移植元 app\DiveToPalworld.cs Strings.Table (L.39-265) は165キー実測
    # (2026-08-01時点、機械抽出。将来キーが増減しても壊れないよう下限のみ検査)
    assert len(i18n.TABLE) >= 100


def test_progress_labels_not_empty():
    # 移植元 Strings.ProgressLabels (L.314-335) は19キー実測
    assert len(i18n.PROGRESS_LABELS) >= 10


def test_table_all_keys_all_languages_non_empty():
    missing = []
    for key, values in i18n.TABLE.items():
        for lang in EXPECTED_LANGS:
            v = values.get(lang)
            if not v:
                missing.append((key, lang))
    assert not missing, f"Table: empty translations for {missing[:20]} (total {len(missing)})"


def test_progress_labels_all_keys_all_languages_non_empty():
    missing = []
    for key, values in i18n.PROGRESS_LABELS.items():
        for lang in EXPECTED_LANGS:
            v = values.get(lang)
            if not v:
                missing.append((key, lang))
    assert not missing, f"ProgressLabels: empty translations for {missing[:20]} (total {len(missing)})"


def test_s_returns_marker_for_unknown_key():
    # Strings.S(key) L.269-285: 未知キーは例外を投げず "??key??" を返す
    assert i18n.S("__no_such_key__") == "??__no_such_key__??"


def test_s_falls_back_to_ja_for_missing_language_entry():
    # PickFromArray L.296-302: 指定言語が空ならja(索引0)へフォールバック
    i18n.TABLE["__test_partial__"] = {"ja": "テスト", "en": "", "ko": "", "zhTW": "", "zhCN": ""}
    try:
        assert i18n.S("__test_partial__", lang="en") == "テスト"
    finally:
        del i18n.TABLE["__test_partial__"]


def test_f_formats_placeholders():
    i18n.TABLE["__test_format__"] = {lang: "{0}/{1}" for lang in EXPECTED_LANGS}
    try:
        assert i18n.F("__test_format__", "a", "b") == "a/b"
    finally:
        del i18n.TABLE["__test_format__"]


def test_registry_applies_on_language_change():
    class FakeWidget:
        def __init__(self):
            self.text = None

        def config(self, text):
            self.text = text

    i18n.clear_registry()
    i18n.set_language("ja")
    i18n.TABLE["__test_reg__"] = {
        "ja": "こんにちは", "en": "Hello", "ko": "안녕", "zhTW": "你好", "zhCN": "你好",
    }
    try:
        w = FakeWidget()
        i18n.register(w, "__test_reg__")
        assert w.text == "こんにちは"
        i18n.apply_language("en")
        assert w.text == "Hello"
    finally:
        del i18n.TABLE["__test_reg__"]
        i18n.clear_registry()
        i18n.set_language("ja")
