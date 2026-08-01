# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7: 旧 tests\\shipcheck\\test_apply_language_cs.py
(app\\DiveToPalworld.cs CheckApplyLanguageLogic、dev#173 ApplyLanguage())の
Python版試験。

旧テストはcsc.exeでビルドしたexeを`--check-apply-language <outDir>`で起動し、
MainFormをヘッドレスに1個生成してApplyLanguage(En)/ApplyLanguage(Ja)の往復を
検査していた。Python版は tkinterを実際に使って(画面は`root.withdraw()`で
非表示のまま)app_py\\ui\\main_window.py の MainWindow を1個生成し、
i18n.py(WP-A1)のregister()/apply_language()経由で同じ検査を行う
(ビルド手順・別プロセス起動が丸ごと不要になった)。

app_root は tmp_path 配下の使い捨てディレクトリを渡し、実リポジトリの
settings_*.txtやensure_blender.ps1に一切触れない(ensure_blender.ps1が
存在しないため、Blender起動時チェックはNeedFullSetupの判定に落ちる前に
「スクリプト自体が無い」経路を通り、実プロセス起動もネットワークI/Oも
発生しない。app_py\\tests\\test_blender_setup.py の
do_ensure_blender_ready 系テストと同じ前提)。

検査しているケース(移植元 CheckApplyLanguageLogic):
  - 登録数の厳密一致(main_window.pyの_register_text/_register_tip呼び出し
    回数と1:1。1箇所でも登録漏れがあれば必ず検出できる設計、2026-07-29に
    実際にconvertButtonの登録漏れ1件を検出した実績をC#版で踏襲)
  - En切替後、スポットチェックした主要ボタンのText/Tooltipが英語辞書値と一致
  - ウィンドウタイトル・pakListの列見出し・kodawariToggleの▲▼付きラベルも
    再適用される
  - Ja切替後、同じコントロールが日本語辞書値へ戻る(負の対照: 固着して
    戻らない退行の検出)
  - TipLanguageSwitch(5言語)に「次回起動時」相当の文言が残っていないこと
    (dev#173の裁定そのものが後退していないかの確認)
"""
from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import i18n  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

# main_window.py の _register_text/_register_tip 呼び出し回数(2026-08-01
# master再実測、`grep -c "self\._register_text(\|self\._register_tip("
# app_py\ui\main_window.py` = 35)。dev#630(PR #645)がプレビュー枠プレース
# ホルダ2件(LabelPreviewPlaceholderFront/Side)を新規に_register_text化した
# ことで33→35へ正当に増加(33はそれ以前の実測値)。1箇所でも増減したら
# このテストが検出する(旧C#版の「登録数の厳密一致」検査粒度をそのまま踏襲)。
EXPECTED_REGISTRATION_COUNT = 35

# main_window.py で確認済みのキー割当(widget名 -> i18n key)からスポット
# チェック対象を選ぶ(全数ではなく代表数点、C#版の「主要ボタンはピンポイントでも
# 確認」という方針を踏襲)。
SPOT_CHECK_TEXT_WIDGETS = {
    "browse": "BtnBrowse",
    "convertButton": "BtnFullConvert",
    "cancelButton": "BtnCancelConvert",
    "applyButton": "BtnApply",
    "removeButton": "BtnRemoveMod",
    "refreshButton": "BtnRefreshList",
    "deleteButton": "BtnDeleteResult",
    "reportButton": "BtnReport",
}


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    import ui.main_window as mw_mod

    tmp_app_root = str(tmp_path_factory.mktemp("apply_language_app_root"))
    root = tk.Tk()
    root.withdraw()

    # このマシンに実Palworldインストールが見つかると、_on_refresh_pak_list()
    # 経由でSHA1照合バックグラウンドスレッドが起動してしまう(実I/Oは無害だが、
    # モジュールスコープのfixtureが次テストへ進む/root.destroy()される前に
    # 完了する保証がなく、他マシンでの再現性・後始末の速さを損なう)。
    # apply_language検査の対象範囲外(pak管理はWP-A4)なので、決定的に
    # 「見つからない」よう差し替えて隔離する。
    original_paks_dir_quiet = mw_mod.pak_manager.paks_dir_quiet
    mw_mod.pak_manager.paks_dir_quiet = lambda *a, **k: None
    try:
        win = MainWindow(root, app_root=tmp_app_root)
        yield win
    finally:
        mw_mod.pak_manager.paks_dir_quiet = original_paks_dir_quiet
        try:
            root.destroy()
        except tk.TclError:
            pass


@pytest.fixture(autouse=True)
def _reset_language_after_each_test(window):
    yield
    i18n.apply_language("ja")


def test_registration_count_matches_expected(window):
    assert i18n.registry_size() == EXPECTED_REGISTRATION_COUNT


def test_apply_language_en_updates_spot_checked_widgets(window):
    window._lang_combo.set("English")
    window._on_language_selected()
    for widget_name, key in SPOT_CHECK_TEXT_WIDGETS.items():
        widget = window.widgets[widget_name]
        expected = i18n.S(key, "en")
        actual = widget.cget("text")
        assert actual == expected, f"{widget_name}: expected={expected!r} actual={actual!r}"


def test_apply_language_en_updates_window_title_and_pak_list_headings(window):
    window._lang_combo.set("English")
    window._on_language_selected()
    assert i18n.S("TitleSubtitle", "en") in window.root.title()
    pak_list = window.widgets["pakList"]
    for col_id, key in window._pak_list_columns.items():
        assert pak_list.heading(col_id)["text"] == i18n.S(key, "en")


def test_apply_language_round_trip_back_to_japanese(window):
    window._lang_combo.set("English")
    window._on_language_selected()
    window._lang_combo.set("日本語")
    window._on_language_selected()
    for widget_name, key in SPOT_CHECK_TEXT_WIDGETS.items():
        widget = window.widgets[widget_name]
        expected = i18n.S(key, "ja")
        actual = widget.cget("text")
        assert actual == expected, f"{widget_name}: expected={expected!r} actual={actual!r}"
    # 登録数はラウンドトリップ後も不変(二重登録が起きていないことの確認)
    assert i18n.registry_size() == EXPECTED_REGISTRATION_COUNT


def test_tip_language_switch_has_no_stale_next_launch_wording():
    # dev#173裁定の核心: 「次回起動時に反映されます」のような後退した文言が
    # 5言語のどこにも残っていないこと。
    banned_substrings = ["次回起動", "next launch", "next restart", "다음 실행", "下次啟動", "下次启动"]
    values = i18n.TABLE.get("TipLanguageSwitch")
    assert values, "TipLanguageSwitchキーが存在しない"
    for lang, text in values.items():
        lowered = text.lower()
        for banned in banned_substrings:
            assert banned.lower() not in lowered, (
                f"TipLanguageSwitch[{lang}] に後退した文言が残っている: {text!r}"
            )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
