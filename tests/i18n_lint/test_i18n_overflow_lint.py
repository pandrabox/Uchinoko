# -*- coding: utf-8 -*-
r"""dev#133: devtools\i18n_overflow_lint.py の単体試験。

実変換・実機・排他資源には一切触れない(app\DiveToPalworld.cs は別WP(wp_gui2、
ボタン動的幅対応)が並行編集中のため、パーサ/判定ロジック自体の正当性は
このファイル内で完結する合成(synthetic)C#断片で検証する。実ファイルに対する
チェックは「壊れずに走ってwell-formedな結果を返す」ことだけを見る軽量スモーク
(test_real_file_smoke)にとどめ、実ファイルの現在の内容(既存の検出件数等)には
依存しない — wp_gui2がこの後 cancelButton 等を直しても本テストは壊れない。

受入条件(dev#133)に対応するテスト:
  - 正の対照: test_overflow_detection_positive_and_negative_control
    (意図的に長い文字列を注入した言語だけがオーバーフロー検出される)
  - 負の対照: 同上のbaseline部分、および test_no_false_positive_generous_width
    (既存の正常な文字列セットでは誤検知しない)

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


# --- 合成C#断片(実ファイルに依存しない) ---------------------------------------

def _make_cs_text(control_decl, table_entries):
    """Strings.Table + 1個のコントロール宣言だけを持つ最小限のC#断片を作る。
    parse_strings_table/parse_controls が実ファイルで前提にしている構文
    (Dictionary<string, string[]> Table = new Dictionary<string, string[]> { ... };
     と `name = new <Type> { ..., Text = T("Key"), ... }`)をそのまま再現する。"""
    entries_src = "\n".join(
        '            {{ "{}", new[] {{ {} }} }},'.format(
            key, ", ".join('"{}"'.format(v) for v in vals))
        for key, vals in table_entries.items()
    )
    return """
namespace DiveToPalworld
{
    internal static class Strings
    {
        internal static readonly Dictionary<string, string[]> Table = new Dictionary<string, string[]> {
""" + entries_src + """
        };
    }

    public class MainForm
    {
        void Build()
        {
""" + "            " + control_decl + """
        }
    }
}
"""


BASE_TABLE = {
    "TestKey": ["テスト", "Test", "테스트", "測試", "测试"],
}


# --- parse_strings_table ------------------------------------------------------

def test_parse_strings_table_basic():
    cs_text = _make_cs_text(
        'var testButton = new Button { Left = 0, Top = 0, Width = 60, Text = T("TestKey") };',
        BASE_TABLE)
    table = lint_mod.parse_strings_table(cs_text)
    assert table["TestKey"] == ["テスト", "Test", "테스트", "測試", "测试"]


def test_parse_strings_table_unescapes_quotes_and_newlines():
    table_entries = {"Esc": ['a\\"b', "line1\\nline2", "同じ", "同じ", "同じ"]}
    cs_text = _make_cs_text(
        'var x = new Label { Width = 400, Text = T("Esc") };', table_entries)
    table = lint_mod.parse_strings_table(cs_text)
    assert table["Esc"][0] == 'a"b'
    assert table["Esc"][1] == "line1\nline2"


# --- parse_controls ------------------------------------------------------------

def test_parse_controls_finds_button_with_width_and_key():
    cs_text = _make_cs_text(
        'cancelButton = new Button { Left = 220, Top = 44, Width = 100, Height = 36, '
        'Text = T("TestKey"), Enabled = false };',
        BASE_TABLE)
    controls = lint_mod.parse_controls(cs_text)
    assert len(controls) == 1
    c = controls[0]
    assert c["type"] == "Button"
    assert c["name"] == "cancelButton"
    assert c["width"] == 100
    assert c["key"] == "TestKey"
    assert c["extra_literal"] == ""


def test_parse_controls_skips_autosize_true():
    cs_text = _make_cs_text(
        'var b = new Button { Width = 60, Text = T("TestKey"), AutoSize = true };',
        BASE_TABLE)
    controls = lint_mod.parse_controls(cs_text)
    assert controls == []


def test_parse_controls_skips_non_i18n_text():
    # 静的リテラルのみ(T(...)呼び出しが無い)のTextはi18n対象外なので無視する
    cs_text = _make_cs_text(
        'var shadowLabel = new Label { Width = 50, Text = "30%" };',
        BASE_TABLE)
    controls = lint_mod.parse_controls(cs_text)
    assert controls == []


def test_parse_controls_skips_missing_width():
    cs_text = _make_cs_text(
        'var l = new Label { Text = T("TestKey") };', BASE_TABLE)
    controls = lint_mod.parse_controls(cs_text)
    assert controls == []


def test_parse_controls_captures_literal_prefix_concat():
    # kodawariToggle実例の再現: "▼ " + T("Key") のような文字列連結
    cs_text = _make_cs_text(
        'kodawariToggle = new Button { Width = 150, Height = 26, '
        'Text = "▼ " + T("TestKey") };',
        BASE_TABLE)
    controls = lint_mod.parse_controls(cs_text)
    assert len(controls) == 1
    assert controls[0]["extra_literal"] == "▼ "
    assert controls[0]["key"] == "TestKey"


# --- measure_text_px -----------------------------------------------------------

def test_measure_text_px_empty_is_zero():
    assert lint_mod.measure_text_px("") == 0


def test_measure_text_px_monotonic_with_length():
    short = lint_mod.measure_text_px("A")
    long_ = lint_mod.measure_text_px("A" * 20)
    assert long_ > short


def test_measure_text_px_cjk_is_nonzero():
    # フォントリンクが機能していない/フォント名が解決できない場合、幅0や
    # 極端な過小評価が起きうる(=CJK文字列だけ検出が効かなくなる致命的な回帰)。
    # ここで確実に非ゼロかつ妥当な範囲であることをガードする
    w = lint_mod.measure_text_px("変換を中止")
    assert w > 20  # 5文字の日本語が20px未満のはずがない(8.25pt想定)


# --- check_overflow: 正の対照 / 負の対照 ----------------------------------------

def test_overflow_detection_positive_and_negative_control():
    """負の対照: 元の短い文字列では誤検知しない。
    正の対照: 意図的に長い文字列へ差し替えた言語だけがオーバーフロー検出される。"""
    cs_text = _make_cs_text(
        'testButton = new Button { Left = 0, Top = 0, Width = 70, Text = T("TestKey") };',
        BASE_TABLE)
    table = lint_mod.parse_strings_table(cs_text)
    controls = lint_mod.parse_controls(cs_text)
    assert len(controls) == 1

    # 負の対照: 現状の短い文字列(ja/en/ko/zhTW/zhCNいずれも数文字)は幅70の
    # ボタンに余裕で収まるはずで、何も検出されない
    baseline = lint_mod.check_overflow(controls, table)
    assert baseline == [], "既存の短い文字列セットで誤検知した: {}".format(baseline)

    # 正の対照: en(インデックス1)だけを意図的に長い文字列へ差し替える
    injected_table = {"TestKey": list(table["TestKey"])}
    injected_table["TestKey"][1] = (
        "This is a deliberately very long English string injected to overflow the button")
    overflow = lint_mod.check_overflow(controls, injected_table)

    assert len(overflow) == 1, "注入した長い文字列がオーバーフローとして検出されなかった: {}".format(overflow)
    finding = overflow[0]
    assert finding["name"] == "testButton"
    assert finding["lang"] == "en"
    assert finding["overshoot"] > 0
    # 注入していない他言語は引き続き検出されない
    assert all(f["lang"] == "en" for f in overflow)


def test_no_false_positive_generous_width():
    """負の対照: 十分に幅の広いコントロールでは、多少長い文字列でも誤検知しない。"""
    table_entries = {
        "Wide": [
            "変換を中止するかどうかを確認するダイアログのラベルです",
            "Confirm whether to cancel the running conversion process",
            "실행 중인 변환을 취소할지 확인하는 대화 상자 레이블입니다",
            "確認是否要取消正在執行的轉換處理的對話方塊標籤",
            "确认是否要取消正在进行的转换处理的对话框标签",
        ],
    }
    cs_text = _make_cs_text(
        'var wideLabel = new Label { Width = 900, Text = T("Wide") };', table_entries)
    table = lint_mod.parse_strings_table(cs_text)
    controls = lint_mod.parse_controls(cs_text)
    overflow = lint_mod.check_overflow(controls, table)
    assert overflow == []


def test_multiline_key_excluded_from_overflow_check():
    """スコープ外: いずれかの言語で\\nを含む(複数行ダイアログ本文)キーは、
    折り返し前提のため横方向のオーバーフロー判定から除外される。"""
    table_entries = {
        "Multiline": [
            "1行目\\n" + ("あ" * 100),  # 幅だけ見れば大幅にあふれる長さだが対象外
            "line1\\n" + ("a" * 100),
            "1\\n" + ("가" * 100),
            "1\\n" + ("測" * 100),
            "1\\n" + ("测" * 100),
        ],
    }
    cs_text = _make_cs_text(
        'var body = new Label { Width = 100, Text = T("Multiline") };', table_entries)
    table = lint_mod.parse_strings_table(cs_text)
    controls = lint_mod.parse_controls(cs_text)
    assert len(controls) == 1
    overflow = lint_mod.check_overflow(controls, table)
    assert overflow == [], "複数行キーはスコープ外として除外されるべき: {}".format(overflow)


# --- 実ファイルに対する軽量スモーク(内容には依存しない) ---------------------------

def test_real_file_smoke():
    """app\\DiveToPalworld.cs に対して例外なく走り、well-formedな結果を返すことだけ
    を見る。件数は wp_gui2 等の並行編集で変わりうるので固定値をアサートしない。"""
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
    # 注入済みの断片を一時ファイルへ書き出し、--fail-on-overflow で終了コード1に
    # なることを確認する(正の対照)。同じファイルを--fail-on-overflow無しで
    # 実行すると終了コード0のまま(既定は検出のみ)であることも確認する(負の対照)。
    table_entries = {
        "TestKey": [
            "OK", "This is a deliberately very long English string to force an overflow",
            "OK", "OK", "OK",
        ],
    }
    cs_text = _make_cs_text(
        'testButton = new Button { Width = 60, Text = T("TestKey") };', table_entries)
    fd, path = tempfile.mkstemp(suffix=".cs")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cs_text)

        proc_default = _run_cli(["--cs-file", path])
        assert proc_default.returncode == 0
        assert "overflow findings: 1" in proc_default.stdout

        proc_fail = _run_cli(["--cs-file", path, "--fail-on-overflow"])
        assert proc_fail.returncode == 1
    finally:
        os.remove(path)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
