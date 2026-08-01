# test_log_i18n_dev596.py -- dev#596残り(prefab変換時にGUIログ欄へ日本語行が
# 多数出る)の受入試験。
#
# 対応した2つの仕組みを検証する:
#   (1) MainWindow._log(text, gui=False) は log_box への表示を抑制する
#       (開発向け詳細行の「抑制」。ファイル/コンソールへの print() は維持)。
#       _stub() ハンドラ(pakList選択変更のたびに発火する高頻度ノイズ)が
#       これを使っていること。
#   (2) pipeline\cli\export_from_unity.ps1(prefab入力時のみ通るUnity輸出、
#       LU層)のWrite-Host/Write-Errorが日本語を含まないこと(convert.ps1の
#       既存の英語文言慣習に合わせた「出す側の英語化」)。
#
# tkの実ウィンドウは一切開かない。既存test_gui_log_robustness.pyと同じく
# フェイクself経由でMainWindow._log/_stubを未束縛メソッドとして直接呼ぶ。
from __future__ import annotations

import os
import re
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_PY_DIR = os.path.dirname(_TESTS_DIR)
_REPO_ROOT = os.path.dirname(_APP_PY_DIR)
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import main_window as mw  # noqa: E402

_JAPANESE_RE = re.compile(r"[぀-ヿ㐀-鿿]")


class _FakeLogBox:
    def __init__(self) -> None:
        self.inserted: list[str] = []

    def configure(self, **_kwargs) -> None:
        return None

    def insert(self, _index: str, text: str) -> None:
        self.inserted.append(text)

    def see(self, _index: str) -> None:
        return None


class _FakeSelfForLog:
    """MainWindow._log/_stubを未束縛メソッドとして直接呼ぶための最小self。
    _stub()が返すhandler内で`self._log(...)`を呼ぶため、本物の
    MainWindow._log をそのまま束縛しておく(test_gui_log_robustness.pyの
    _FakeSelfForPollと同じ手法)。"""

    _log = mw.MainWindow._log

    def __init__(self) -> None:
        self.log_box = _FakeLogBox()


# ---------------------------------------------------------------------------
# (1) _log(gui=False) がlog_box表示を抑制すること
# ---------------------------------------------------------------------------


def test_log_default_gui_true_still_shows_in_log_box():
    """負の対照: gui引数を省略した従来どおりの呼び出しは、これまでどおり
    log_boxへ反映されること(抑制がデフォルト挙動を壊していないこと)。"""
    fake_self = _FakeSelfForLog()
    mw.MainWindow._log(fake_self, "hello world")
    assert fake_self.log_box.inserted == ["hello world\n"]


def test_log_gui_false_suppresses_log_box_display():
    fake_self = _FakeSelfForLog()
    mw.MainWindow._log(fake_self, "[stub] PakListSelectedIndexChanged: not implemented", gui=False)
    assert fake_self.log_box.inserted == [], (
        "gui=Falseで呼んだのにlog_boxへ表示されている(抑制が効いていない)"
    )


def test_log_gui_false_still_prints_to_console(capsys):
    """抑制はGUI表示のみで、print()経由のコンソール/launch.log出力は
    維持されること(診断可能性を落とさない)。"""
    fake_self = _FakeSelfForLog()
    mw.MainWindow._log(fake_self, "dev-only diagnostic line", gui=False)
    captured = capsys.readouterr()
    assert "dev-only diagnostic line" in captured.out


# ---------------------------------------------------------------------------
# (2) _stub() ハンドラがgui=Falseで抑制済みの英語文言を出すこと
# ---------------------------------------------------------------------------


def test_stub_handler_suppresses_gui_and_uses_english():
    fake_self = _FakeSelfForLog()
    handler = mw.MainWindow._stub(fake_self, "PakListSelectedIndexChanged")
    handler()
    assert fake_self.log_box.inserted == [], (
        "dev#596b: _stub()の[stub]行はpakList選択のたびに発火する高頻度ノイズであり、"
        "GUIログ欄には出さない設計のはず"
    )


def test_stub_handler_negative_control_no_japanese_leftover():
    """負の対照: 過去の直書き文言「未実装」が復活していないことを、
    抑制を使わない生のprint()出力からも確認する。"""
    import io
    import contextlib

    fake_self = _FakeSelfForLog()
    handler = mw.MainWindow._stub(fake_self, "PakListSelectedIndexChanged")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        handler()
    assert not _JAPANESE_RE.search(buf.getvalue()), (
        f"[stub]の出力に日本語が残っている: {buf.getvalue()!r}"
    )
    assert "not implemented" in buf.getvalue()


# ---------------------------------------------------------------------------
# (3) main_window.py の他の直書きログ行(dev#596で残っていた5箇所)が
#     英語化されていること(静的スキャン、負の対照つき)
# ---------------------------------------------------------------------------


def _scan_log_call_lines_for_japanese(path: str) -> list[str]:
    """self._log(...) を呼んでいる行(コメント除く)のうち日本語を含むものを
    列挙する。"""
    hits = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "self._log(" in stripped and _JAPANESE_RE.search(stripped):
                hits.append(stripped)
    return hits


def test_main_window_log_calls_have_no_japanese_literal():
    main_window_path = os.path.join(_APP_PY_DIR, "ui", "main_window.py")
    hits = _scan_log_call_lines_for_japanese(main_window_path)
    assert hits == [], f"main_window.pyのself._log()呼び出しに日本語直書きが残っている: {hits}"


def test_scan_helper_negative_control_detects_injected_japanese(tmp_path):
    """負の対照: スキャン関数自体が日本語を検出できることを、意図的に
    日本語を含むダミーファイルで確認する(検査そのものが壊れていないこと)。"""
    dummy = tmp_path / "dummy_main_window.py"
    dummy.write_text(
        'def handler():\n    self._log(f"[stub] X: 未実装")\n',
        encoding="utf-8",
    )
    hits = _scan_log_call_lines_for_japanese(str(dummy))
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# (4) export_from_unity.ps1 (prefab専用のUnity輸出、LU層) のWrite-Host/
#     Write-Errorが日本語を含まないこと
# ---------------------------------------------------------------------------

_PS1_PATH = os.path.join(_REPO_ROOT, "pipeline", "cli", "export_from_unity.ps1")


def _scan_ps1_write_lines_for_japanese(path: str) -> list[str]:
    hits = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ("Write-Host" in stripped or "Write-Error" in stripped) and _JAPANESE_RE.search(
                stripped
            ):
                hits.append(stripped)
    return hits


def test_export_from_unity_ps1_write_lines_have_no_japanese():
    assert os.path.isfile(_PS1_PATH), f"not found: {_PS1_PATH}"
    hits = _scan_ps1_write_lines_for_japanese(_PS1_PATH)
    assert hits == [], (
        "export_from_unity.ps1のWrite-Host/Write-Errorに日本語が残っている"
        f"(prefab入力時にGUIログ欄へ混じるdev#596の再発): {hits}"
    )


def test_scan_ps1_helper_negative_control_detects_injected_japanese(tmp_path):
    """負の対照: ps1用スキャン関数もダミーファイルで検出できることを確認する。"""
    dummy = tmp_path / "dummy_export.ps1"
    dummy.write_text('Write-Host "プロジェクト: $proj"\n', encoding="utf-8")
    hits = _scan_ps1_write_lines_for_japanese(str(dummy))
    assert len(hits) == 1
