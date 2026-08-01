# -*- coding: utf-8 -*-
r"""dev#133/dev#532(WP-C3): devtools\i18n_overflow_lint.py の単体試験(tkinter版)。

2026-08-01 dev#532方針A WP-C3で対象がC#(WinForms, app\DiveToPalworld.cs)から
Python(tkinter, app_py\ui\main_window.py)へ全面書換されたことに伴い、本ファイルも
新しい契約(ast + tkinter.font.Font.measure)に合わせて全面書き換える
(旧C#合成断片・parse_strings_table/parse_controls(cs_text)形式のテストはもう
成立しない。work\wp532A\DESIGN.md §5.2 WP-C3参照)。

実変換・実機・排他資源には一切触れない。パーサ/判定ロジック自体の正当性は
このファイル内で完結する合成(synthetic)Pythonソース断片で検証する。実ファイルに
対するチェックは「壊れずに走ってwell-formedな結果を返す」ことだけを見る軽量スモーク
(test_real_file_smoke)にとどめ、実ファイルの現在の内容(検出件数の増減)には
依存しない。

受入条件(dev#532 WP-C3)に対応するテスト:
  - ①現状のapp_pyに対して実行でき、結果が出る: test_real_file_smoke /
    test_cli_json_smoke
  - ②負の対照(dev#106のcancelButton英語オーバーフロー相当を模した注入):
    test_overflow_detection_positive_and_negative_control /
    test_cli_fail_on_overflow_exit_code
    (リポジトリ本体を汚さない一時コピー方式の実行ログは、本WPのPR本文・
    完了報告に別途添付する。それとは独立に、本ファイル自身も合成テキストで
    同じ契約を検証する)

実行:
    python -m pytest tests\i18n_lint
    python tests\i18n_lint\test_i18n_overflow_lint.py
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
if DEVTOOLS_DIR not in sys.path:
    sys.path.insert(0, DEVTOOLS_DIR)

import i18n_overflow_lint as lint_mod  # noqa: E402


# --- 合成Pythonソース断片(実ファイルに依存しない) ------------------------------

def _make_py_text(control_decl, place_decl=None):
    """main_window.py の `_build_widgets` 相当の最小限の断片を作る。
    parse_controls が実ファイルで前提にしている構文
    (`name = tk.Button/Label/Checkbutton(..., text=<i18n式>, ...)` と、任意で
    `name.place(..., width=N, ...)`)をそのまま再現する。"""
    body = "        " + control_decl
    if place_decl:
        body += "\n        " + place_decl
    return (
        "import tkinter as tk\n"
        "import i18n\n"
        "\n"
        "\n"
        "def build(root):\n"
        + body + "\n"
    )


TABLE = {
    "TestKey": {"ja": "テスト", "en": "Test", "ko": "테스트", "zhTW": "測試", "zhCN": "测试"},
}


# --- load_i18n_table -----------------------------------------------------------

def test_load_i18n_table_strips_progress_labels(tmp_path):
    data = dict(TABLE)
    data["_progress_labels"] = {"raw": {"ja": "x", "en": "x", "ko": "x", "zhTW": "x", "zhCN": "x"}}
    p = tmp_path / "i18n_data.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    table = lint_mod.load_i18n_table(str(p))
    assert "_progress_labels" not in table
    assert table["TestKey"] == TABLE["TestKey"]


# --- parse_controls --------------------------------------------------------------

def test_parse_controls_finds_button_with_width_and_key():
    py_text = _make_py_text(
        'cancel_button = tk.Button(root, text=i18n.S("TestKey"), state="disabled")',
        "cancel_button.place(x=220, y=44, width=100, height=36)",
    )
    controls = lint_mod.parse_controls(py_text)
    assert len(controls) == 1
    c = controls[0]
    assert c["type"] == "Button"
    assert c["name"] == "cancel_button"
    assert c["width"] == 100
    assert c["key"] == "TestKey"
    assert c["extra_literal"] == ""


def test_parse_controls_finds_label_and_checkbutton():
    py_text = _make_py_text(
        'lbl = tk.Label(root, text=i18n.S("TestKey"))',
        "lbl.place(x=0, y=0, width=70)",
    ) + (
        "\n"
        "def build2(root):\n"
        '    chk = tk.Checkbutton(root, text=i18n.S("TestKey"))\n'
        "    chk.place(x=0, y=0, width=200, height=20)\n"
    )
    controls = lint_mod.parse_controls(py_text)
    types = sorted(c["type"] for c in controls)
    assert types == ["Checkbutton", "Label"]


def test_parse_controls_skips_missing_place_call():
    # place()自体が無い(=tkinterの自動サイズ挙動に任せている)ものは対象外
    # (C#版のAutoSize=trueスキップと同じ発想)
    py_text = _make_py_text('lbl = tk.Label(root, text=i18n.S("TestKey"))')
    controls = lint_mod.parse_controls(py_text)
    assert controls == []


def test_parse_controls_skips_place_without_width():
    py_text = _make_py_text(
        'lbl = tk.Label(root, text=i18n.S("TestKey"))',
        "lbl.place(x=0, y=0)",  # widthを渡していない
    )
    controls = lint_mod.parse_controls(py_text)
    assert controls == []


def test_parse_controls_skips_non_i18n_text():
    # 静的リテラルのみ(i18n.S(...)呼び出しが無い)のTextはi18n対象外なので無視する
    py_text = _make_py_text(
        'shadow_label = tk.Label(root, text="30%")',
        "shadow_label.place(x=0, y=0, width=50)",
    )
    controls = lint_mod.parse_controls(py_text)
    assert controls == []


def test_parse_controls_captures_literal_prefix_concat():
    # kodawariToggle実例の再現: "▼ " + i18n.S("Key") のような文字列連結
    py_text = _make_py_text(
        'kodawari_toggle = tk.Button(root, text="▼ " + i18n.S("TestKey"))',
        "kodawari_toggle.place(x=12, y=88, width=150, height=26)",
    )
    controls = lint_mod.parse_controls(py_text)
    assert len(controls) == 1
    assert controls[0]["extra_literal"] == "▼ "
    assert controls[0]["key"] == "TestKey"


def test_parse_controls_skips_non_target_widget_types():
    # Entry/Frame等はスコープ外(CONTROL_TYPESに無い)
    py_text = _make_py_text(
        'entry = tk.Entry(root)',
        "entry.place(x=0, y=0, width=400)",
    )
    controls = lint_mod.parse_controls(py_text)
    assert controls == []


# --- measure_text_px / measure_padding_px ---------------------------------------

def test_measure_text_px_empty_is_zero():
    assert lint_mod.measure_text_px("") == 0


def test_measure_text_px_monotonic_with_length():
    short = lint_mod.measure_text_px("A")
    long_ = lint_mod.measure_text_px("A" * 20)
    assert long_ > short


def test_measure_text_px_cjk_is_nonzero():
    # TkDefaultFontがCJKグリフを描画できるフォントへ解決できていない場合、
    # 幅0や極端な過小評価が起きうる(=CJK文字列だけ検出が効かなくなる致命的な回帰)。
    # ここで確実に非ゼロかつ妥当な範囲であることをガードする
    w = lint_mod.measure_text_px("変換を中止")
    assert w > 20  # 5文字の日本語が20px未満のはずがない


def test_measure_padding_px_positive_and_cached():
    for widget_type in ("Button", "Label", "Checkbutton"):
        pad = lint_mod.measure_padding_px(widget_type)
        assert pad > 0
        # 2回目はキャッシュから返るだけで値は変わらない
        assert lint_mod.measure_padding_px(widget_type) == pad


# --- check_overflow: 正の対照 / 負の対照 ----------------------------------------

def test_overflow_detection_positive_and_negative_control():
    """負の対照: 元の短い文字列では誤検知しない。
    正の対照: 意図的に長い文字列へ差し替えた言語だけがオーバーフロー検出される
    (dev#106のcancelButton英語オーバーフロー事件と同じ形の注入)。"""
    py_text = _make_py_text(
        'test_button = tk.Button(root, text=i18n.S("TestKey"))',
        "test_button.place(x=0, y=0, width=70)",
    )
    controls = lint_mod.parse_controls(py_text)
    assert len(controls) == 1

    # 負の対照: 現状の短い文字列(ja/en/ko/zhTW/zhCNいずれも数文字)は幅70の
    # ボタンに余裕で収まるはずで、何も検出されない
    baseline = lint_mod.check_overflow(controls, TABLE)
    assert baseline == [], "既存の短い文字列セットで誤検知した: {}".format(baseline)

    # 正の対照: enだけを意図的に長い文字列へ差し替える
    injected_table = {"TestKey": dict(TABLE["TestKey"])}
    injected_table["TestKey"]["en"] = (
        "This is a deliberately very long English string injected to overflow the button")
    overflow = lint_mod.check_overflow(controls, injected_table)

    assert len(overflow) == 1, "注入した長い文字列がオーバーフローとして検出されなかった: {}".format(overflow)
    finding = overflow[0]
    assert finding["name"] == "test_button"
    assert finding["lang"] == "en"
    assert finding["overshoot"] > 0
    # 注入していない他言語は引き続き検出されない
    assert all(f["lang"] == "en" for f in overflow)


def test_no_false_positive_generous_width():
    """負の対照: 十分に幅の広いコントロールでは、多少長い文字列でも誤検知しない。"""
    table = {
        "Wide": {
            "ja": "変換を中止するかどうかを確認するダイアログのラベルです",
            "en": "Confirm whether to cancel the running conversion process",
            "ko": "실행 중인 변환을 취소할지 확인하는 대화 상자 레이블입니다",
            "zhTW": "確認是否要取消正在執行的轉換處理的對話方塊標籤",
            "zhCN": "确认是否要取消正在进行的转换处理的对话框标签",
        },
    }
    py_text = _make_py_text(
        'wide_label = tk.Label(root, text=i18n.S("Wide"))',
        "wide_label.place(x=0, y=0, width=900)",
    )
    controls = lint_mod.parse_controls(py_text)
    overflow = lint_mod.check_overflow(controls, table)
    assert overflow == []


def test_multiline_value_excluded_from_overflow_check():
    """スコープ外: いずれかの言語で改行を含む(複数行ダイアログ本文)値は、
    折り返し前提のため横方向のオーバーフロー判定から除外される。"""
    table = {
        "Multiline": {
            "ja": "1行目\n" + ("あ" * 100),  # 幅だけ見れば大幅にあふれる長さだが対象外
            "en": "line1\n" + ("a" * 100),
            "ko": "1\n" + ("가" * 100),
            "zhTW": "1\n" + ("測" * 100),
            "zhCN": "1\n" + ("测" * 100),
        },
    }
    py_text = _make_py_text(
        'body = tk.Label(root, text=i18n.S("Multiline"))',
        "body.place(x=0, y=0, width=100)",
    )
    controls = lint_mod.parse_controls(py_text)
    assert len(controls) == 1
    overflow = lint_mod.check_overflow(controls, table)
    assert overflow == [], "複数行キーはスコープ外として除外されるべき: {}".format(overflow)


def test_missing_key_is_ignored():
    # i18nキーがtableに無い(完全性検査側の責務)場合は例外にせず無視する
    py_text = _make_py_text(
        'b = tk.Button(root, text=i18n.S("NoSuchKey"))',
        "b.place(x=0, y=0, width=10)",
    )
    controls = lint_mod.parse_controls(py_text)
    overflow = lint_mod.check_overflow(controls, TABLE)
    assert overflow == []


# --- 実ファイルに対する軽量スモーク(内容には依存しない) ---------------------------

def test_real_file_smoke():
    """app_py\\ui\\main_window.py + app_py\\i18n_data.json に対して例外なく走り、
    well-formedな結果を返すことだけを見る。件数は並行編集で変わりうるので
    固定値をアサートしない(dev#532 WP-C3受入条件①)。"""
    report = lint_mod.lint()
    assert report["table_size"] > 50
    assert report["control_count"] > 0
    assert isinstance(report["overflow"], list)
    for o in report["overflow"]:
        for field in ("type", "name", "line", "key", "lang", "width", "avail",
                      "measured", "overshoot", "text"):
            assert field in o


# --- CLI ------------------------------------------------------------------------

def _run_cli(args):
    return subprocess.run(
        [sys.executable, os.path.join(DEVTOOLS_DIR, "i18n_overflow_lint.py")] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)


def test_cli_json_smoke():
    proc = _run_cli(["--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["table_size"] > 50
    assert "overflow" in data


def test_cli_fail_on_overflow_exit_code():
    # 合成断片(main_window.py + i18n_data.json)を一時ファイルへ書き出し、
    # --fail-on-overflow で終了コード1になることを確認する(正の対照)。
    # 同じファイルを--fail-on-overflow無しで実行すると終了コード0のまま
    # (既定は検出のみ)であることも確認する(負の対照)。
    table = {
        "TestKey": {
            "ja": "OK",
            "en": "This is a deliberately very long English string to force an overflow",
            "ko": "OK", "zhTW": "OK", "zhCN": "OK",
        },
    }
    py_text = _make_py_text(
        'test_button = tk.Button(root, text=i18n.S("TestKey"))',
        "test_button.place(x=0, y=0, width=60)",
    )
    tmp_dir = tempfile.mkdtemp()
    try:
        source_path = os.path.join(tmp_dir, "main_window.py")
        i18n_path = os.path.join(tmp_dir, "i18n_data.json")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(py_text)
        with open(i18n_path, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False)

        proc_default = _run_cli(["--source-file", source_path, "--i18n-file", i18n_path])
        assert proc_default.returncode == 0, proc_default.stderr
        assert "overflow findings: 1" in proc_default.stdout

        proc_fail = _run_cli([
            "--source-file", source_path, "--i18n-file", i18n_path, "--fail-on-overflow",
        ])
        assert proc_fail.returncode == 1
    finally:
        for name in ("main_window.py", "i18n_data.json"):
            try:
                os.remove(os.path.join(tmp_dir, name))
            except OSError:
                pass
        os.rmdir(tmp_dir)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
