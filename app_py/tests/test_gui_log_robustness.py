# test_gui_log_robustness.py -- dev#592受入条件:
#   v2.3.0(py版GUI)で「Fetching game data... (3%)」凍結(進捗・プレビュー・
#   完了通知が全滅)を起こしていた根本原因の再発防止。
#
# 真因(work\briefs\wp_592_brief.md背景節):
#   1. main_window.py _log() の素の print(text) が、配布形態
#      (pythonw.exe > res\logs\launch.log 2>&1、cp932既定)でU+2014等を
#      UnicodeEncodeErrorにする
#   2. その例外が _on_pipeline_line -> PipelineHandle.poll() -> tkinterの
#      _poll_active_handle へ伝播し、root.after()による再スケジュール前に
#      コールバックが死んでポーリングが恒久停止する
#
# 三重防御(brief §仕様):
#   1. build.py: BAT_TEMPLATE_HIDDENのpythonw呼び出しに -X utf8 追加
#   2. main.py: 起動最早期のstdio硬化(None->ダミーライター、
#      reconfigure(errors="backslashreplace"))
#   3. main_window.py _log()/_poll_active_handle() と
#      pipeline_runner.py PipelineHandle.poll() の例外絶縁
#
# tkの実ウィンドウは一切開かない(tk.Tk()を呼ばない)。MainWindow._log/
# _poll_active_handleは束縛前のメソッドとして「フェイクself」に対して直接
# 呼び出す(既存test_dnd.py/test_pipeline_runner.pyと同じくスタブ経由)。
from __future__ import annotations

import io
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import main as app_main  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402

EM_DASH_TEXT = "preflight: skipped — no addon found"  # U+2014、preflightログに頻出


# ---------------------------------------------------------------------------
# フェイク部品
# ---------------------------------------------------------------------------


class _FakeLogBox:
    """tkinter.Text互換の最小フェイク(configure/insert/see)。実ウィジェットは
    一切生成しない。"""

    def __init__(self) -> None:
        self.inserted: list[str] = []

    def configure(self, **_kwargs) -> None:
        return None

    def insert(self, _index: str, text: str) -> None:
        self.inserted.append(text)

    def see(self, _index: str) -> None:
        return None


class _FakeSelfForLog:
    """MainWindow._logを束縛せずに呼ぶための最小self(log_boxのみ持つ)。"""

    def __init__(self) -> None:
        self.log_box = _FakeLogBox()


def _cp932_text_stream() -> io.TextIOWrapper:
    """launch.logの配布時挙動(pythonw.exe > ... 2>&1、ロケール既定cp932)を
    再現する書き込み専用ストリーム。BytesIOをcp932でラップする。"""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp932", newline="\n")


class _AlwaysRaisingStream:
    """write()が常に例外を投げる、壊れたストリーム(パイプ切断・ディスク
    フルなど任意の書き込み失敗を汎化して再現する)。"""

    def write(self, _s: object) -> int:
        raise OSError("simulated broken stream: write always fails")

    def flush(self) -> None:
        raise OSError("simulated broken stream: flush always fails")


# ---------------------------------------------------------------------------
# (e) 負の対照: 素のprintが実際にUnicodeEncodeErrorを出すことの証明
#     (バグの再現性そのものを示す。このテストは「直っていないこと」の確認)
# ---------------------------------------------------------------------------


def test_e_negative_control_bare_print_raises_unicode_encode_error(monkeypatch):
    stream = _cp932_text_stream()
    monkeypatch.setattr(sys, "stdout", stream)
    try:
        import builtins

        raised = False
        try:
            builtins.print(EM_DASH_TEXT)
        except UnicodeEncodeError:
            raised = True
        assert raised, (
            "負の対照が成立しない: 素のprint()がcp932ストリームへU+2014を"
            "書いてもUnicodeEncodeErrorを出さなかった(このテストが崩れる"
            "ならバグの前提=再現条件自体が変わっている)"
        )
    finally:
        stream.close()


# ---------------------------------------------------------------------------
# (a) cp932ストリーム + U+2014 を _log 相当経路に流しても例外が出ないこと
# ---------------------------------------------------------------------------


def test_a_log_survives_cp932_stdout_with_em_dash(monkeypatch):
    stream = _cp932_text_stream()
    monkeypatch.setattr(sys, "stdout", stream)
    fake_self = _FakeSelfForLog()
    try:
        # 例外を投げないことそのものが受入条件(投げれば pytest が失敗させる)。
        mw.MainWindow._log(fake_self, EM_DASH_TEXT)
    finally:
        stream.close()
    # 生存防御は「例外を出さない」ことが主眼であり、ログ欄への反映は
    # print()の成否に関わらず先に試みられているはず。
    assert fake_self.log_box.inserted == [EM_DASH_TEXT + "\n"]


# ---------------------------------------------------------------------------
# (b) sys.stdout/sys.stderr が None の状態でstdio硬化ヘルパーを通すと、
#     以後のprint/writeが例外を出さないこと
# ---------------------------------------------------------------------------


def test_b_harden_stdio_replaces_none_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    app_main._harden_stdio()

    assert sys.stdout is not None
    assert sys.stderr is not None
    # 差し替え後は書き込みが例外を出さない(pythonw素起動相当)。
    sys.stdout.write("hello")
    sys.stdout.flush()
    sys.stderr.write("world")
    sys.stderr.flush()
    import builtins

    builtins.print("no crash even without a real console")


def test_b_harden_stdio_calls_reconfigure_with_backslashreplace(monkeypatch):
    """reconfigureを持つ既存ストリーム(pythonの標準stdout/stderr相当)には
    encodingを変えずerrors="backslashreplace"だけを指定すること
    (brief仕様: 「encodingは変えない=リダイレクト先の既存内容と混在させない」)。"""
    calls: list[dict] = []

    class _FakeReconfigurableStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

        def write(self, _s):
            return 0

        def flush(self):
            return None

    monkeypatch.setattr(sys, "stdout", _FakeReconfigurableStream())
    monkeypatch.setattr(sys, "stderr", _FakeReconfigurableStream())

    app_main._harden_stdio()

    assert len(calls) == 2
    for kwargs in calls:
        assert kwargs.get("errors") == "backslashreplace"
        assert "encoding" not in kwargs


def test_b_harden_stdio_swallows_reconfigure_failure(monkeypatch):
    """reconfigureが存在しても呼び出しに失敗する(壊れた/特殊なストリーム)
    場合でも、harden_stdio自体は例外を出さずに続行すること。"""

    class _BrokenReconfigureStream:
        def reconfigure(self, **_kwargs):
            raise RuntimeError("reconfigure not supported in this state")

    monkeypatch.setattr(sys, "stdout", _BrokenReconfigureStream())
    monkeypatch.setattr(sys, "stderr", _BrokenReconfigureStream())

    app_main._harden_stdio()  # 例外を投げなければ合格


# ---------------------------------------------------------------------------
# (c) write が常に例外を投げる壊れたストリームでも _log 相当経路が
#     例外を出さないこと
# ---------------------------------------------------------------------------


def test_c_log_survives_always_raising_stdout(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _AlwaysRaisingStream())
    fake_self = _FakeSelfForLog()

    mw.MainWindow._log(fake_self, "any text, even plain ascii")

    # printが失敗してもログ欄への反映automaticには影響しない。
    assert fake_self.log_box.inserted == ["any text, even plain ascii\n"]


# ---------------------------------------------------------------------------
# (d) _on_line が例外を投げる状況でも poll() が残りの行と exit 処理を
#     継続すること(行単位try/exceptの検証)
# ---------------------------------------------------------------------------


def test_d_poll_continues_after_on_line_raises(monkeypatch):
    handle = pr.ProcessHandle.__new__(pr.ProcessHandle)  # __init__を通さない軽量生成
    import queue as queue_mod

    handle._queue = queue_mod.Queue()
    handle._queue.put(("line", "line 1 (ok)"))
    handle._queue.put(("line", "line 2 (raises)"))
    handle._queue.put(("line", "line 3 (ok, must still be delivered)"))
    handle._queue.put(("exit", 0))

    received_lines: list[str] = []
    exit_codes: list[int] = []

    def on_line(payload: str) -> None:
        received_lines.append(payload)
        if payload == "line 2 (raises)":
            raise RuntimeError("simulated on_line failure (e.g. UnicodeEncodeError in _log)")

    def on_exit(code: int) -> None:
        exit_codes.append(code)

    handle._on_line = on_line
    handle._on_exit = on_exit

    handle.poll()  # 例外を外へ漏らしてはならない

    assert received_lines == [
        "line 1 (ok)",
        "line 2 (raises)",
        "line 3 (ok, must still be delivered)",
    ], "1行の失敗で後続行の配送が止まっている(dev#592の再発)"
    assert exit_codes == [0], "on_line失敗の後でexit処理(完了通知)が届いていない"


def test_d_poll_active_handle_reschedules_even_if_handle_poll_raises():
    """main_window.py側の二段目防御: _poll_active_handle()はhandle.poll()が
    例外を出しても(pipeline_runner側の行単位防御をすり抜けた想定外の失敗)
    再スケジュールを保証する。root.afterの呼び出し回数で確認する。"""

    after_calls: list[tuple] = []

    class _FakeRoot:
        def after(self, *args) -> None:
            after_calls.append(args)

    class _RaisingHandle:
        def poll(self) -> None:
            raise RuntimeError("simulated poll() failure")

        def is_running(self) -> bool:
            return True

    class _FakeSelfForPoll:
        _active_handle = _RaisingHandle()
        root = _FakeRoot()
        _POLL_INTERVAL_MS = 150

        def _log(self, _text: str) -> None:
            return None

        # self.root.after(ms, self._poll_active_handle) の再帰参照先として、
        # 本物のMainWindow._poll_active_handleをそのまま束縛する
        # (再スケジュール「先」が正しいメソッドであることも合わせて検証する)。
        _poll_active_handle = mw.MainWindow._poll_active_handle

    fake_self = _FakeSelfForPoll()
    mw.MainWindow._poll_active_handle(fake_self)  # 例外を外へ漏らしてはならない

    assert len(after_calls) == 1, "handle.poll()が例外を出すと再スケジュールされない(dev#592根本原因)"


# ---------------------------------------------------------------------------
# (f) build.py の bat テンプレート文字列に -X utf8 が含まれること
# ---------------------------------------------------------------------------


def test_f_bat_template_hidden_forces_utf8_mode():
    import build

    assert "-X utf8" in build.BAT_TEMPLATE_HIDDEN
    # 既存の環境隔離3点(gate_bat_isolation()が機械照合する分)は無傷であること。
    for needle in ("%~dp0", " -E ", "TCL_LIBRARY", "TK_LIBRARY"):
        assert needle in build.BAT_TEMPLATE_HIDDEN


def test_f_gate_bat_isolation_still_passes_with_utf8_flag(tmp_path):
    import build

    bat_path = tmp_path / "Uchinoko.bat"
    bat_path.write_text(build.BAT_TEMPLATE_HIDDEN, encoding="utf-8")
    ok, problems = build.gate_bat_isolation(bat_path)
    assert ok, f"utf8フラグ追加でgate_bat_isolationが壊れた: {problems}"
