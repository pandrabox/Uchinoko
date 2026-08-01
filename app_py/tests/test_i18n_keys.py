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


def test_status_prompt_vrm_mentions_prefab_before_vrm():
    # dev#630: 「VRMのみ言及」を修正し、prefab優先の表記にする。
    # 5言語すべてで prefab を指す語("prefab")が VRM を指す語より先に
    # 出現することを機械検査する(負の対照: 旧文言はVRMのみでprefabを含まない)。
    for key in ("StatusPromptVrm", "StatusPromptVrmDnd"):
        values = i18n.TABLE[key]
        for lang in EXPECTED_LANGS:
            text = values[lang]
            assert "prefab" in text, f"{key}/{lang}: prefabへの言及が無い: {text!r}"
            assert "VRM" in text, f"{key}/{lang}: VRMへの言及が無い: {text!r}"
            assert text.index("prefab") < text.index("VRM"), (
                f"{key}/{lang}: prefabがVRMより先に来ていない: {text!r}"
            )


def test_prefab_mentioned_before_vrm_word_form():
    # dev#646: dev#630(StatusPromptVrm系、別レーンで対応済み)の棚卸しで
    # 残っていた「VRM単独言及」キーをprefab優先の言い回しへ統一する。
    # 「prefab」「VRM」を単語として併記するキー群(拡張子ドット無し)で、
    # 5言語すべてprefabがVRMより先に出現することを機械検査する
    # (負の対照: 修正前の文言はVRMのみでprefabを含まないためassertが落ちる)。
    keys = (
        "NoteVrmNotDeleted",
        "NoteReloadVrmToRedo",
        "MsgSpecifyVrmFile",
        "StatusPreviewStale",
    )
    for key in keys:
        values = i18n.TABLE[key]
        for lang in EXPECTED_LANGS:
            text = values[lang]
            assert "prefab" in text, f"{key}/{lang}: prefabへの言及が無い: {text!r}"
            assert "VRM" in text, f"{key}/{lang}: VRMへの言及が無い: {text!r}"
            assert text.index("prefab") < text.index("VRM"), (
                f"{key}/{lang}: prefabがVRMより先に来ていない: {text!r}"
            )


def test_preview_placeholder_keys_exist_and_are_non_english_free_of_english_leak():
    # dev#630棚卸し: app_py\ui\main_window.pyのプレビュー枠プレースホルダ
    # ("(preview front)"/"(preview side)")は未ローカライズの直書き英語だった。
    # i18n辞書キー化した新規キーが5言語とも非空であることを確認する
    # (全体の非空検査はtest_table_all_keys_all_languages_non_empty で既にカバー
    # されるが、キー自体の存在をここでも明示して回帰を検知しやすくする)。
    for key in ("LabelPreviewPlaceholderFront", "LabelPreviewPlaceholderSide"):
        assert key in i18n.TABLE, f"{key} が i18n.TABLE に無い"
        for lang in EXPECTED_LANGS:
            assert i18n.TABLE[key].get(lang), f"{key}/{lang} が空"


def test_prefab_mentioned_before_vrm_extension_form():
    # dev#646: MsgDropVrmOrPrefabは拡張子ドット付き表記(".prefab"/".vrm")の
    # ため単語形式の検査対象から分離。同じくprefab優先の語順を機械検査する
    # (負の対照: 修正前は".vrm"が".prefab"より先に出現しassertが落ちる)。
    key = "MsgDropVrmOrPrefab"
    values = i18n.TABLE[key]
    for lang in EXPECTED_LANGS:
        text = values[lang]
        assert ".prefab" in text, f"{key}/{lang}: .prefabへの言及が無い: {text!r}"
        assert ".vrm" in text, f"{key}/{lang}: .vrmへの言及が無い: {text!r}"
        assert text.index(".prefab") < text.index(".vrm"), (
            f"{key}/{lang}: .prefabが.vrmより先に来ていない: {text!r}"
        )


# dev#654: v2.3.0でランチャーexe(Uchinoko.exe)は廃止され、現行の起動方法は
# Uchinoko.bat(bat+embeddable python構成)。ユーザー向け文言に廃止済みexeへの
# 言及が残ると、ユーザーが実在しないファイルを指示され従えない実害がある
# (ActionNoWritePermissionキーで実際に発生、work\pubdocs_audit_20260801.md 付記)。
# 正当な.exe言及(外部ツール名等、例: blender.exe)が将来出た場合のみ、
# キー名をここへ追記して許可する(判断はwork\wp_654_progress.mdに記録)。
EXE_MENTION_ALLOWLIST: set[str] = set()


def test_no_stale_exe_references_in_table():
    offenders = []
    for key, values in i18n.TABLE.items():
        if key in EXE_MENTION_ALLOWLIST:
            continue
        for lang in EXPECTED_LANGS:
            v = values.get(lang, "")
            if isinstance(v, str) and ".exe" in v.lower():
                offenders.append((key, lang, v))
    assert not offenders, f"Table: stale .exe references found: {offenders}"


def test_no_stale_exe_references_in_progress_labels():
    offenders = []
    for key, values in i18n.PROGRESS_LABELS.items():
        if key in EXE_MENTION_ALLOWLIST:
            continue
        for lang in EXPECTED_LANGS:
            v = values.get(lang, "")
            if isinstance(v, str) and ".exe" in v.lower():
                offenders.append((key, lang, v))
    assert not offenders, f"ProgressLabels: stale .exe references found: {offenders}"


def test_exe_reference_detection_catches_intentionally_broken_entry():
    # 負の対照: 検査ロジック自体が.exeを検出できることの証明
    i18n.TABLE["__test_exe_regression__"] = {
        "ja": "Uchinoko.exeを右クリック", "en": "right-click Uchinoko.exe",
        "ko": "x", "zhTW": "x", "zhCN": "x",
    }
    try:
        offenders = [
            (key, lang, v)
            for key, values in i18n.TABLE.items()
            if key not in EXE_MENTION_ALLOWLIST
            for lang, v in values.items()
            if lang in EXPECTED_LANGS and isinstance(v, str) and ".exe" in v.lower()
        ]
        assert ("__test_exe_regression__", "ja", "Uchinoko.exeを右クリック") in offenders
        assert ("__test_exe_regression__", "en", "right-click Uchinoko.exe") in offenders
    finally:
        del i18n.TABLE["__test_exe_regression__"]


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
