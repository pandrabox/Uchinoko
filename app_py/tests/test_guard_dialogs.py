# test_guard_dialogs.py -- dev#621/dev#622(レーンD、v2.3.2)の単体テスト。
#
# dev#621: workRootFailed(主系・フォールバック先とも書き込み不可)時の
#   検知・ログ記録・エラーダイアログ・変換系ボタン全面無効化
#   (DiveToPalworld.cs CheckPathHealthOnStartup L.3277-3287、
#    UpdateButtonStates L.2486-2491 `!workRootFailed`条件)。
# dev#622: 変換中に×ボタンで閉じても確認ダイアログが出ない件
#   (DiveToPalworld.cs FormClosing L.1292-1305)。
#
# 既存test_gui_log_robustness.pyと同じ流儀: tkの実ウィンドウは一切開かない
# (tk.Tk()を呼ばない)。MainWindowの各メソッドは束縛前のまま「フェイクself」
# (mw.MainWindow.__new__(mw.MainWindow)で生成し、必要な属性だけ後付けする)
# に対して直接呼び出す。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _bare_window() -> mw.MainWindow:
    """__init__を通さずMainWindowインスタンスだけ得る(既存test_dnd.py等と
    同じ手筋)。テストごとに必要な属性だけ後付けする。"""
    return mw.MainWindow.__new__(mw.MainWindow)


class _FakeButton:
    """tkinter.Button互換の最小フェイク(config(state=...)のみ)。"""

    def __init__(self) -> None:
        self.state: str | None = None

    def config(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]


class _FakeRoot:
    """tkinter.Tk互換の最小フェイク(destroy()呼び出しの記録のみ)。"""

    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _FakeEntry:
    """tkinter.Entry互換の最小フェイク(.get()のみ、dev#621(d)テスト用)。"""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def get(self) -> str:
        return self._text


class _FakeBlenderSetupHandle:
    """blender_setup.BlenderSetupProcessHandle互換の最小フェイク
    (dev#640×dev#622統合、PR #647本文の指示どおり_on_form_closing()の
    先頭に合流したkill()呼び出し用、kill_calls記録のみ)。"""

    def __init__(self) -> None:
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1


class _FakeHandle:
    """pipeline_runner.ProcessHandle互換の最小フェイク。"""

    def __init__(self, running: bool) -> None:
        self._running = running
        self.killed = False

    def is_running(self) -> bool:
        return self._running

    def kill(self) -> None:
        self.killed = True
        self._running = False


# ---------------------------------------------------------------------------
# dev#621 (a): _resolve_work_root() のworkRootFailed検知
# ---------------------------------------------------------------------------


def test_resolve_work_root_success_when_primary_writable(tmp_path):
    """主系が書き込み可能なら、フォールバック判定・失敗判定のどちらも
    立たないこと(既存の正常経路が壊れていないことの確認)。"""
    fake = _bare_window()
    fake.app_root = str(tmp_path)

    result = mw.MainWindow._resolve_work_root(fake)

    assert result == os.path.join(str(tmp_path), "work")
    assert fake._work_root_used_fallback is False
    assert fake._work_root_failed is False
    assert fake._work_root_primary_error is None


def test_resolve_work_root_falls_back_when_primary_unwritable(tmp_path, monkeypatch):
    """主系が書き込み不可・フォールバック先が書き込み可能なら、
    workRootUsedFallback=True・workRootFailed=Falseで、返り値はフォールバック
    先になること(WorkRootResolveLogic.Resolve L.6458-6469相当)。"""
    fake = _bare_window()
    app_root = tmp_path / "app_root"
    fallback_root = tmp_path / "fallback_local_appdata"
    fake.app_root = str(app_root)
    monkeypatch.setenv("LOCALAPPDATA", str(fallback_root))
    primary_path = os.path.join(str(app_root), "work")

    real_makedirs = os.makedirs

    def fake_makedirs(path, exist_ok=False):
        if os.path.abspath(path) == os.path.abspath(primary_path):
            raise OSError(13, "simulated permission denied (primary)")
        return real_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr(mw.os, "makedirs", fake_makedirs)

    result = mw.MainWindow._resolve_work_root(fake)

    assert fake._work_root_used_fallback is True
    assert fake._work_root_failed is False
    assert fake._work_root_primary_error is not None
    assert fake._work_root_fallback_error is None
    assert result == os.path.join(str(fallback_root), "Uchinoko", "work")


def test_resolve_work_root_fails_when_both_unwritable(tmp_path, monkeypatch):
    """dev#621本体: 主系・フォールバック先とも書き込み不可なら、
    workRootFailed=Trueが立ち、例外を外へ漏らさず(アプリをクラッシュさせず)
    フォールバック先のパス文字列を返すこと(WorkRootResolveLogic.Resolve
    L.6470-6476: Failed=trueでも下流が安全に動けるようPathは残す、の移植)。"""
    fake = _bare_window()
    app_root = tmp_path / "app_root"
    fallback_root = tmp_path / "local_appdata"
    fake.app_root = str(app_root)
    monkeypatch.setenv("LOCALAPPDATA", str(fallback_root))

    def always_fail_makedirs(path, exist_ok=False):
        raise OSError(13, "simulated permission denied (both)")

    monkeypatch.setattr(mw.os, "makedirs", always_fail_makedirs)

    result = mw.MainWindow._resolve_work_root(fake)  # 例外を投げてはならない

    assert fake._work_root_failed is True
    assert fake._work_root_used_fallback is False
    assert fake._work_root_primary_error is not None
    assert fake._work_root_fallback_error is not None
    assert result == os.path.join(str(fallback_root), "Uchinoko", "work")


# ---------------------------------------------------------------------------
# dev#621 (b): _work_root_resolution_line() -- WorkRootResolutionLine相当
# ---------------------------------------------------------------------------


def test_work_root_resolution_line_writable():
    fake = _bare_window()
    fake.work_root = "C:\\app\\work"
    fake._work_root_used_fallback = False
    fake._work_root_failed = False

    line = mw.MainWindow._work_root_resolution_line(fake)

    assert line == "work_root: C:\\app\\work (install location, writable)"


def test_work_root_resolution_line_fallback():
    fake = _bare_window()
    fake.work_root = "C:\\fallback\\work"
    fake._work_root_used_fallback = True
    fake._work_root_failed = False
    fake._work_root_primary_path = "C:\\Program Files\\Uchinoko\\work"
    fake._work_root_primary_error = "Access is denied"

    line = mw.MainWindow._work_root_resolution_line(fake)

    assert "fallback to a user-writable location" in line
    assert "C:\\Program Files\\Uchinoko\\work" in line
    assert "Access is denied" in line


def test_work_root_resolution_line_failed():
    fake = _bare_window()
    fake.work_root = "C:\\fallback\\work"
    fake._work_root_used_fallback = False
    fake._work_root_failed = True
    fake._work_root_primary_path = "C:\\Program Files\\Uchinoko\\work"
    fake._work_root_primary_error = "Access is denied"
    fake._work_root_fallback_path = "C:\\fallback\\work"
    fake._work_root_fallback_error = "Disk full"

    line = mw.MainWindow._work_root_resolution_line(fake)

    assert "neither the install location" in line
    assert "C:\\Program Files\\Uchinoko\\work" in line
    assert "Access is denied" in line
    assert "C:\\fallback\\work" in line
    assert "Disk full" in line


# ---------------------------------------------------------------------------
# dev#621 (c): _check_work_root_failed_on_startup() -- ログ・ダイアログ・
#              ボタン無効化の結線
# ---------------------------------------------------------------------------


def _fake_window_for_startup_check(*, failed: bool) -> mw.MainWindow:
    fake = _bare_window()
    fake.work_root = "C:\\app\\work"
    fake._work_root_used_fallback = False
    fake._work_root_failed = failed
    fake._work_root_primary_path = "C:\\app\\work"
    fake._work_root_fallback_path = "C:\\fallback\\work"
    fake._work_root_primary_error = "Access is denied"
    fake._work_root_fallback_error = "Access is denied (fallback)"
    fake._log_calls: list[str] = []
    fake._log = lambda text, _fake=fake: _fake._log_calls.append(text)  # type: ignore[method-assign]
    fake.widgets = {
        "convertButton": _FakeButton(),
        "matsButton": _FakeButton(),
        "previewButton": _FakeButton(),
    }
    return fake


def test_check_work_root_failed_on_startup_noop_when_not_failed(monkeypatch):
    """workRootFailedでない(通常/フォールバック済み)場合は、解決結果の1行を
    ログへ残すのみで、エラーダイアログもボタン無効化も起きないこと
    (正常系がこのdev#621実装で壊れていないことの確認)。"""
    fake = _fake_window_for_startup_check(failed=False)
    dialog_calls: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: dialog_calls.append(a))

    mw.MainWindow._check_work_root_failed_on_startup(fake)

    assert len(fake._log_calls) == 1
    assert fake._log_calls[0].startswith("work_root: ")
    assert dialog_calls == []
    for key in ("convertButton", "matsButton", "previewButton"):
        assert fake.widgets[key].state is None  # 触られていない


def test_check_work_root_failed_on_startup_disables_and_alerts_when_failed(monkeypatch):
    """dev#621本体: workRootFailed時は①解決結果ログ+②失敗タイトルのログ
    ③エラーダイアログ(primary/fallbackパスを含む)④変換系3ボタンの
    全面無効化、の4点が揃うこと。"""
    fake = _fake_window_for_startup_check(failed=True)
    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        mw.messagebox, "showerror", lambda title, msg: dialog_calls.append((title, msg))
    )

    mw.MainWindow._check_work_root_failed_on_startup(fake)

    assert len(fake._log_calls) == 2
    assert fake._log_calls[0].startswith("work_root: ")
    assert i18n.S("TitleWorkRootUnwritable") in fake._log_calls[1]

    assert len(dialog_calls) == 1
    title, msg = dialog_calls[0]
    assert title == i18n.S("TitleWorkRootUnwritable")
    assert "C:\\app\\work" in msg
    assert "C:\\fallback\\work" in msg

    for key in ("convertButton", "matsButton", "previewButton"):
        assert fake.widgets[key].state == "disabled"


# ---------------------------------------------------------------------------
# dev#621 (d): _set_running_ui_state() -- workRootFailed中は再有効化しない
# ---------------------------------------------------------------------------


def test_set_running_ui_state_reenables_normally_when_not_failed(tmp_path):
    """負の対照: workRootFailedでない通常時は、running=Falseで従来どおり
    normalへ戻ること(このガードが正常系を壊していないことの確認)。

    2026-08-01 #635/#647マージ後: convertButton/matsButton/previewButtonは
    それぞれ_refresh_convert_button_freshness()/_update_button_states()に
    委ねられ、単純な`normal`固定ではなくhasVrm/blenderReady判定も絡む
    ようになった。ここでは実在するVRMパス+blenderReady=Trueのfakeを使い、
    workRootFailedに邪魔されず「hasVrm/blenderReady判定を満たせば通常どおり
    normalになる」ことを確認する(hasVrm=False等の個別ゲートは
    test_preview_freshness.py/test_button_gates.pyの担当)。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _bare_window()
    fake._work_root_failed = False
    fake._blender_ready = True
    fake._active_handle = None
    fake._is_preview_fresh = lambda _vrm_path: True
    fake.widgets = {
        "vrmBox": _FakeEntry(str(vrm)),
        "convertButton": _FakeButton(),
        "matsButton": _FakeButton(),
        "previewButton": _FakeButton(),
        "cancelButton": _FakeButton(),
        "statusLabel": _FakeButton(),
        "busyBar": _DictLikeBusyBar(),
    }

    mw.MainWindow._set_running_ui_state(fake, False)

    for key in ("convertButton", "matsButton", "previewButton"):
        assert fake.widgets[key].state == "normal"


def test_set_running_ui_state_stays_disabled_when_work_root_failed():
    """dev#621本体: workRootFailed中は、running=Falseへ戻ってきても
    convert/mats/previewがdisabledのまま(UpdateButtonStatesの
    `!workRootFailed`条件相当が、継続的なループを持たないpy版でも
    恒久的に効いていること)。convertButtonは_refresh_convert_button_freshness()
    側のworkRootFailedガード(hasVrm/freshより優先)経由でdisabledになる。
    blenderReady=Trueにしても(=blenderReady側は満たしていても)workRootFailed
    単体で強制disabledになることを示す、より強い負の対照。"""
    fake = _bare_window()
    fake._work_root_failed = True
    fake._blender_ready = True
    fake._active_handle = None
    fake.widgets = {
        "vrmBox": _FakeEntry(""),
        "convertButton": _FakeButton(),
        "matsButton": _FakeButton(),
        "previewButton": _FakeButton(),
        "cancelButton": _FakeButton(),
        "busyBar": _DictLikeBusyBar(),
    }

    mw.MainWindow._set_running_ui_state(fake, False)

    for key in ("convertButton", "matsButton", "previewButton"):
        assert fake.widgets[key].state == "disabled"


class _DictLikeBusyBar(_FakeButton):
    """busyBar["value"]=0代入とplace()/place_forget()呼び出しを許容する
    最小フェイク(ttk.Progressbar互換)。"""

    def __setitem__(self, _key, _value) -> None:
        return None

    def place(self, **_kwargs) -> None:
        return None

    def place_forget(self) -> None:
        return None

    def start(self, _interval: object = None) -> None:
        # dev#602/#633統合後: _set_running_ui_state()のelse分岐が
        # _set_busy_bar_mode()経由でstart/stopを呼ぶようになったための
        # 最小許容(値の記録はtest_busy_bar_progress.py側の担当)。
        return None

    def stop(self) -> None:
        return None


# ---------------------------------------------------------------------------
# dev#622: _on_form_closing() -- FormClosing相当
# ---------------------------------------------------------------------------


def test_on_form_closing_no_active_pipeline_closes_immediately(monkeypatch):
    """パイプライン非実行中は、確認なしに即座に閉じること
    (runningProc==nullならFormClosingが何もせず終わる=既定のClose継続、
    L.1299相当)。

    2026-08-01 #647統合: KillBlenderSetupProcess()相当
    (_blender_setup_process_handle.kill())がC#版FormClosing L.1298と同じく
    実行中判定より先に無条件で呼ばれることも合わせて確認する。"""
    fake = _bare_window()
    fake._active_handle = None
    fake.root = _FakeRoot()
    fake._blender_setup_process_handle = _FakeBlenderSetupHandle()
    asked: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: asked.append(a) or True)

    mw.MainWindow._on_form_closing(fake)

    assert asked == []
    assert fake.root.destroyed is True
    assert fake._blender_setup_process_handle.kill_calls == 1


def test_on_form_closing_handle_not_running_closes_immediately(monkeypatch):
    """負の対照: handleが存在してもis_running()==Falseなら実行中扱いしない
    (完了済み変換の後始末中に閉じても確認を出さない)。"""
    fake = _bare_window()
    fake._active_handle = _FakeHandle(running=False)
    fake.root = _FakeRoot()
    fake._blender_setup_process_handle = _FakeBlenderSetupHandle()
    asked: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: asked.append(a) or True)

    mw.MainWindow._on_form_closing(fake)

    assert asked == []
    assert fake.root.destroyed is True


def test_on_form_closing_running_and_user_declines_stays_open(monkeypatch):
    """dev#622本体(No分岐): 変換実行中に確認でNoを選んだら、killせず・
    ウィンドウも閉じないこと(`e.Cancel = true`相当、L.1303)。

    KillBlenderSetupProcess()相当は、C#版と同じく実行中確認の結果に
    かかわらず既に呼ばれている(先頭で無条件実行のため)。"""
    fake = _bare_window()
    handle = _FakeHandle(running=True)
    fake._active_handle = handle
    fake.root = _FakeRoot()
    fake._blender_setup_process_handle = _FakeBlenderSetupHandle()
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: False)

    mw.MainWindow._on_form_closing(fake)

    assert handle.killed is False
    assert fake.root.destroyed is False
    assert fake._blender_setup_process_handle.kill_calls == 1


def test_on_form_closing_running_and_user_confirms_kills_and_closes(monkeypatch):
    """dev#622本体(Yes分岐): 変換実行中に確認でYesを選んだら、
    KillConversion()相当(handle.kill())を呼んでからウィンドウを閉じること
    (L.1304-1305)。"""
    fake = _bare_window()
    handle = _FakeHandle(running=True)
    fake._active_handle = handle
    fake.root = _FakeRoot()
    fake._blender_setup_process_handle = _FakeBlenderSetupHandle()
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a: True)

    mw.MainWindow._on_form_closing(fake)

    assert handle.killed is True
    assert fake.root.destroyed is True
