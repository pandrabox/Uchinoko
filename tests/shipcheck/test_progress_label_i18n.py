# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7: 旧 tests\\shipcheck\\test_progress_label_i18n_cs.py
(app\\DiveToPalworld.cs RunProgressLabelI18nChecks、Strings.ProgressLabels/
ProgressLabelTemplates)のPython版試験。

旧テストはcsc.exeでビルドしたexeを`--check-progress-label-i18n <outDir>`で
起動して検査していた。Python版は app_py\\i18n.py(固定辞書 PROGRESS_LABELS)と
app_py\\pipeline_runner.py(可変部テンプレート翻訳
translate_progress_label_dynamic、WP-A2の担当分。i18n.py側の設計判断は
i18n.py冒頭コメント参照)を直接importする。

検査しているケース(移植元 RunProgressLabelI18nChecks):
  case1(完全性)   … PROGRESS_LABELSの全エントリが5言語とも非空
  case2(正)       … 既知ラベルが5言語それぞれで翻訳される(enは原文と同一)
  case3(正、動的テンプレート) … 可変部を含むラベルで、可変部はそのまま・
                     静的部分だけ翻訳される
  case4(負の対照①) … 辞書に無いラベルは原文のままフォールバック
  case5(負の対照②) … 辞書エントリを意図的に破壊(空dict)しても例外を
                     投げず原文へフォールバックする
  case6/7(統合)   … main_window.py L.936-941の実配線(parse_progress_marker
                     -> translate_progress_label_dynamic -> statusLabel文字列
                     整形)と同じ呼び出し列を直接再現し、「実装した」と
                     「効いている」が一致することを確認する
  (受入ゲート)     … 辞書化したラベル数・テンプレート数の記録(0件で通って
                     しまう検査の空洞化を防ぐ、旧テストのprogress_label_count/
                     progress_label_template_count踏襲)
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]


def test_case1_progress_labels_completeness():
    missing = []
    for key, values in i18n.PROGRESS_LABELS.items():
        for lang in EXPECTED_LANGS:
            if not values.get(lang):
                missing.append((key, lang))
    assert not missing, "空の訳文 {} (計{}件)".format(missing[:20], len(missing))


def test_case2_known_label_translated_per_language_en_is_identity():
    assert i18n.translate_progress_label("Loading avatar", "ja") == "アバターを読み込み中"
    assert i18n.translate_progress_label("Loading avatar", "en") == "Loading avatar"
    assert i18n.translate_progress_label("Loading avatar", "ko") == "아바타 불러오는 중"


def test_case3_dynamic_template_variable_part_preserved():
    raw = "Retargeting skeleton (toto1)"
    ja = pr.translate_progress_label_dynamic(raw, "ja")
    en = pr.translate_progress_label_dynamic(raw, "en")
    assert "toto1" in ja
    assert ja.startswith("スケルトンをリターゲット中")
    assert en == raw  # 英語は原文と同一パターン


def test_case4_negative_unknown_label_passthrough():
    raw = "SomeBrandNewPhaseNeverSeenBefore (xyz)"
    assert pr.translate_progress_label_dynamic(raw, "ja") == raw
    assert i18n.translate_progress_label(raw, "ja") == raw


def test_case5_negative_corrupted_entry_falls_back_without_exception():
    key = "__corrupted_progress_label_test__"
    i18n.PROGRESS_LABELS[key] = {}  # 全言語空(壊れたエントリを模す)
    try:
        assert i18n.translate_progress_label(key, "ja") == key
        assert pr.translate_progress_label_dynamic(key, "ja") == key
    finally:
        del i18n.PROGRESS_LABELS[key]


def test_case6_integration_known_label_reaches_status_text():
    # main_window.py _on_pipeline_line (L.936-941) と同じ呼び出し列を再現:
    # parse_progress_marker -> translate_progress_label_dynamic -> 文字列整形
    i18n.set_language("ja")
    try:
        line = "##PROGRESS## 50 Loading avatar"
        marker = pr.parse_progress_marker(line)
        assert marker is not None
        pct, raw_label = marker
        label = pr.translate_progress_label_dynamic(raw_label)
        status_text = f"{label}... ({pct}%)"
        assert status_text == "アバターを読み込み中... (50%)"
    finally:
        i18n.set_language("ja")


def test_case7_integration_unknown_label_reaches_status_text_untranslated():
    i18n.set_language("ja")
    line = "##PROGRESS## 12 TotallyUnknownPhase"
    pct, raw_label = pr.parse_progress_marker(line)
    label = pr.translate_progress_label_dynamic(raw_label)
    status_text = f"{label}... ({pct}%)"
    assert status_text == "TotallyUnknownPhase... (12%)"


def test_acceptance_gate_label_and_template_counts():
    # 2026-08-01時点実測。旧C#版(progress_label_count=19/template_count=3、
    # tests\shipcheck\test_progress_label_i18n_cs.py)と1:1一致(移植漏れ検知)。
    assert len(i18n.PROGRESS_LABELS) == 19
    assert len(pr._PROGRESS_LABEL_TEMPLATES) == 3


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
