# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A7/WP-A11(dev#549): 旧 tests\\shipcheck\\test_progress_relay_cs.py
(app\\DiveToPalworld.cs RunProgressRelayChecks、dev#288 WP-UXIMPL提案2/3
「Phase1完了=39%到達時の早期プレビュー反映」「96%ラベルの事後表示向け文言」)
のPython版試験。

dev#532方針A WP-A11(dev#549)で以下を移植・結線した:
  - 早期プレビュー反映(dev#288提案2): pipeline_runner.should_load_early_preview()
    (pct>=39到達の判定を純関数化)+ pipeline_runner.load_previews()
    (プレビューファイル解決)を新設し、app_py\\ui\\main_window.py の
    _on_pipeline_line() から結線した(実画像デコード・表示(Pillow/ImageTk)は
    B1完了後のWPが担う既存方針のため、本WPではプレースホルダLabelの文言更新
    までを「効いていることの可視化」とした)。
  - 96%ラベル(dev#288提案3、"Packaging complete, verifying result"):
    実は app_py\\i18n_data.json の _progress_labels に**既に**5言語分の
    翻訳エントリが存在していた(WP-A1で移植済み。WP-A7調査時の「キー名に
    "96"という数字が含まれるか」という検査方法が実際のキー設計(進捗文言の
    原文をキーにする方式、数字を含まない)と噛み合わずFALSE NEGATIVEに
    なっていた)。本ファイルではpipeline\\cli\\convert.ps1が実際に発行する
    マーカー("##PROGRESS## 96 Packaging complete, verifying result")を
    基準に、辞書・パース・書式化が一貫して機能することを確認する。

一方、この機能が依存する下位ロジック(##PROGRESS##マーカーのパース、
parse_progress_marker)自体はWP-A2で移植・app_py\\tests\\test_pipeline_runner.py
で検査済み(case1相当: 基本パース、pctの0-100クランプ、非マッチ時None、
ANSIエスケープ除去)。
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
import pipeline_runner as pr  # noqa: E402


def test_progress_marker_parsing_foundation_is_wired():
    """早期プレビュー反映の土台となる##PROGRESS##マーカー解析
    (parse_progress_marker、WP-A2移植済み)が生きていることの確認。"""
    assert pr.parse_progress_marker("##PROGRESS## 39 Retargeting skeleton") == (
        39,
        "Retargeting skeleton",
    )
    assert pr.parse_progress_marker("##PROGRESS## 38 Retargeting skeleton") == (
        38,
        "Retargeting skeleton",
    )


def test_early_preview_reveal():
    """case1/2/3相当(RunProgressRelayChecks L.5144-5172): pct>=39到達時の
    早期LoadPreviews()・1回だけの実行・pct=38境界での非実行、を検査する。
    dev#532方針A WP-A11(dev#549)で pipeline_runner.should_load_early_preview()/
    load_previews() として移植した。"""
    assert hasattr(pr, "load_previews")
    assert hasattr(pr, "should_load_early_preview")

    # ---- case3(負の対照①、境界): pct=38(39未満)ではまだ読み込まない ----
    assert pr.should_load_early_preview(38, already_loaded=False) is False
    # ---- case1(正): pct=39到達で読み込む ----
    assert pr.should_load_early_preview(39, already_loaded=False) is True
    # ---- case2(正、1回だけ): 一度読み込んだ後は別のpct(58)が来ても再度読まない ----
    assert pr.should_load_early_preview(58, already_loaded=True) is False

    # main_window.py が実際にこの判定+load_previews()を結線していることの確認
    # (「実装した」だけでなく「効いている」ことの可視化、CLAUDE.md方針)。
    src_path = os.path.join(APP_PY_DIR, "ui", "main_window.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "should_load_early_preview" in src
    assert "load_previews" in src.lower()


def test_early_preview_reveal_resolves_existing_preview_files(tmp_path):
    """load_previews()自体の単体検査(LoadPreviews L.2957-2963のファイル解決
    部分): 存在するファイルはパスを返し、無ければNoneを返す。"""
    job_dir = tmp_path / "job1"
    converted_dir = job_dir / "converted"
    converted_dir.mkdir(parents=True)
    front = converted_dir / "preview_male_stand.png"
    side = converted_dir / "preview_male_stand_side.png"
    front.write_bytes(b"\x00")
    side.write_bytes(b"\x00")

    result = pr.load_previews(str(job_dir))
    assert result["front"] == str(front)
    assert result["side"] == str(side)

    # 負の対照: どちらも無ければどちらもNone
    empty_job_dir = tmp_path / "job2"
    (empty_job_dir / "converted").mkdir(parents=True)
    empty_result = pr.load_previews(str(empty_job_dir))
    assert empty_result["front"] is None
    assert empty_result["side"] is None


def test_status_96_percent_relabel():
    """case5相当(RunProgressRelayChecks L.5189-5206): 96%到達時の新ラベル
    ("Packaging complete, verifying result"、pipeline\\cli\\convert.ps1:1057が
    実際に発行する文言)が辞書に存在し、パース・翻訳・書式化が一貫して
    期待どおりに機能することを確認する。"""
    label_key = "Packaging complete, verifying result"

    # 辞書完全性(WP-A1で既に移植済みだったことの再確認)
    assert label_key in i18n.PROGRESS_LABELS
    assert i18n.translate_progress_label(label_key, "en") == label_key
    assert i18n.translate_progress_label(label_key, "ja") == "パッケージ化完了、結果を確認中"

    # マーカー解析(convert.ps1が実際に出す行そのもの)
    marker = pr.parse_progress_marker("##PROGRESS## 96 " + label_key)
    assert marker == (96, label_key)
    pct, raw_label = marker

    # main_window._on_pipeline_line()と同じ書式化(label... (pct%))
    label = pr.translate_progress_label_dynamic(raw_label, "en")
    status = "{}... ({}%)".format(label, pct)
    assert status == "Packaging complete, verifying result... (96%)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
