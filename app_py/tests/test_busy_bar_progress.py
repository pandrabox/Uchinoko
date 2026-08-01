# test_busy_bar_progress.py -- dev#602受入条件:
#   prefab変換(Unity輸出等の進捗マーカーが来ない長区間)でbusyBarが完全静止
#   して固まって見える問題のC#版パリティ修正。
#
# 正: app\DiveToPalworld.cs
#   - RunPipeline()        L.2602-2603  busyBar.Style = Continuous; Value = 0
#   - RunUnityExport()     L.2677-2679  「実進捗マーカーが無い工程なので
#                                        マーキー表示にする」Style = Marquee;
#                                        MarqueeAnimationSpeed = 30
#   - OnUnityExportDone()  L.2686        busyBar.Style = Continuous(無条件)
#   - AppendLog()          L.2849        busyBar.Value = pct(##PROGRESS##到着時)
#
# py版の純関数(pipeline_runner.py): initial_busy_bar_mode() / busy_bar_mode_on_marker()
# の単体テストはtest_pipeline_runner.pyに、UI配線(main_window.py
# _set_busy_bar_mode/_set_running_ui_state/_on_pipeline_line)側の検証は本ファイルで行う。
#
# tkの実ウィンドウは一切開かない(tk.Tk()を呼ばない)。既存test_gui_log_robustness.py
# と同じく、フェイクウィジェット+フェイクselfに対してMainWindowの未束縛メソッドを
# 直接呼び出す。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# フェイク部品
# ---------------------------------------------------------------------------


class _FakeProgressbar:
    """ttk.Progressbar互換の最小フェイク(mode/value/config/start/stop/
    place/place_forget)。実ウィジェットは一切生成しない。"""

    def __init__(self, mode: str = "determinate") -> None:
        self._data = {"mode": mode, "value": None}
        self.start_intervals: list[object] = []
        self.stop_calls = 0
        self.placed = False
        self.place_forgotten = False

    def __setitem__(self, key: str, value: object) -> None:
        self._data[key] = value

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def config(self, **kwargs) -> None:
        self._data.update(kwargs)

    def start(self, interval: object = None) -> None:
        self.start_intervals.append(interval)

    def stop(self) -> None:
        self.stop_calls += 1

    def place(self, **_kwargs) -> None:
        self.placed = True
        self.place_forgotten = False

    def place_forget(self) -> None:
        self.place_forgotten = True


class _FakeButton:
    def __init__(self) -> None:
        self.state: str | None = None

    def config(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]


class _FakeLabel:
    def __init__(self) -> None:
        self.text: str | None = None

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeSelfForBusyBar:
    """_set_busy_bar_mode/_set_running_ui_stateを束縛せずに呼ぶための最小self。"""

    def __init__(self, busy_bar_mode: str = "determinate") -> None:
        self.widgets = {
            "busyBar": _FakeProgressbar(busy_bar_mode),
            "convertButton": _FakeButton(),
            "matsButton": _FakeButton(),
            "previewButton": _FakeButton(),
            "cancelButton": _FakeButton(),
            "statusLabel": _FakeLabel(),
        }
        self._busy_bar_geometry = dict(x=330, y=46, width=740, height=12)
        # dev#621: _set_running_ui_state()がworkRootFailedを直接参照するように
        # なった(#637マージ後)。本ファイルの関心事はbusyBarのモード遷移のみ
        # なので既定Falseで従来どおりの経路を通す
        # (work_root_failed時の恒久disabledはtest_guard_dialogs.pyの担当)。
        self._work_root_failed = False

    def _refresh_convert_button_freshness(self) -> None:
        # 2026-08-01 #635マージ後に判明: _set_running_ui_state(running=False)が
        # dev#613/#617でこのメソッドを呼ぶようになった。本ファイルの関心事は
        # busyBarのモード遷移のみ(convertButtonの鮮度判定はtest_preview_freshness.py
        # の担当)なので、呼ばれたことだけ許容するno-opにする。
        pass

    def _update_button_states(self) -> None:
        # 2026-08-01 #647統合後に判明: _set_running_ui_state()が常に
        # _update_button_states()(matsButton/previewButtonのbusy/blenderReady/
        # hasVrm/workRootFailedゲート)を呼ぶようになった。本ファイルの関心事は
        # busyBarのモード遷移のみ(ゲート判定自体はtest_button_gates.pyの担当)
        # なので、呼ばれたことだけ許容するno-opにする。
        pass

    # main_window.MainWindowの実メソッドをそのまま束縛する
    _set_busy_bar_mode = mw.MainWindow._set_busy_bar_mode
    _set_running_ui_state = mw.MainWindow._set_running_ui_state


class _FakeSelfForPipelineLine:
    """_on_pipeline_lineを束縛せずに呼ぶための最小self(マーカー分岐のみ検証、
    早期プレビュー分岐は_active_handle=Noneでスキップさせる)。"""

    def __init__(self, busy_bar_mode: str = "indeterminate") -> None:
        self.widgets = {
            "busyBar": _FakeProgressbar(busy_bar_mode),
            "statusLabel": _FakeLabel(),
        }
        self._active_handle = None
        self._early_preview_loaded_this_run = False
        self._pipeline_warnings: list[str] = []
        self.logged: list[str] = []

    def _log(self, text: str) -> None:
        self.logged.append(text)

    _set_busy_bar_mode = mw.MainWindow._set_busy_bar_mode
    _on_pipeline_line = mw.MainWindow._on_pipeline_line


# ---------------------------------------------------------------------------
# _set_busy_bar_mode
# ---------------------------------------------------------------------------


def test_set_busy_bar_mode_indeterminate_starts_marquee_style_animation():
    """RunUnityExport() L.2678-2679相当: indeterminate指定でmode変更+start()
    (C#のMarqueeAnimationSpeed=30をintervalへそのまま踏襲)。"""
    fake_self = _FakeSelfForBusyBar()
    fake_self._set_busy_bar_mode(pr.BUSY_BAR_MODE_INDETERMINATE)
    busy_bar = fake_self.widgets["busyBar"]
    assert busy_bar["mode"] == "indeterminate"
    assert busy_bar.start_intervals == [30]


def test_set_busy_bar_mode_determinate_stops_animation_and_configures_mode():
    """OnUnityExportDone() L.2686相当: determinate指定でstop()してからmode変更。"""
    fake_self = _FakeSelfForBusyBar(busy_bar_mode="indeterminate")
    fake_self._set_busy_bar_mode(pr.BUSY_BAR_MODE_DETERMINATE)
    busy_bar = fake_self.widgets["busyBar"]
    assert busy_bar["mode"] == "determinate"
    assert busy_bar.stop_calls == 1


# ---------------------------------------------------------------------------
# _set_running_ui_state
# ---------------------------------------------------------------------------


def test_set_running_ui_state_true_unity_export_phase_is_indeterminate():
    """RunUnityExport() L.2612-2682相当の開始: phase=PHASE_UNITY_EXPORTでは
    busyBarがindeterminateになり、アニメーションが開始されること。"""
    fake_self = _FakeSelfForBusyBar()
    fake_self._set_running_ui_state(True, phase=pr.PHASE_UNITY_EXPORT)
    busy_bar = fake_self.widgets["busyBar"]
    assert busy_bar["mode"] == "indeterminate"
    assert busy_bar.start_intervals == [30]
    assert busy_bar["value"] == 0
    assert busy_bar.placed is True
    assert fake_self.widgets["cancelButton"].state == "normal"
    assert fake_self.widgets["convertButton"].state == "disabled"


def test_set_running_ui_state_true_default_phase_is_determinate():
    """RunPipeline() L.2547-2607相当の開始: phase省略時(既定=PHASE_PIPELINE)は
    determinateのまま(##PROGRESS##到着で値が動く前提、静止表示ではない)。"""
    fake_self = _FakeSelfForBusyBar()
    fake_self._set_running_ui_state(True)
    busy_bar = fake_self.widgets["busyBar"]
    assert busy_bar["mode"] == "determinate"
    assert busy_bar.start_intervals == []
    assert busy_bar["value"] == 0


def test_set_running_ui_state_false_resets_indeterminate_leftover_to_determinate():
    """dev#602の核心回帰試験: 直前がUnity輸出(indeterminate)だった場合でも、
    終了時(OnUnityExportDone() L.2686 = 無条件でContinuousへ)はdeterminateへ
    リセットされ、busyBarが次のフル変換に静止したまま持ち越されないこと。
    (負の対照: 修正前は_set_running_ui_state(False)がbusyBarモードに触れず、
    indeterminateのまま残ってしまう=このテストがfailすることで再現できる)"""
    fake_self = _FakeSelfForBusyBar(busy_bar_mode="indeterminate")
    fake_self._set_running_ui_state(False)
    busy_bar = fake_self.widgets["busyBar"]
    assert busy_bar["mode"] == "determinate", (
        "Unity輸出終了後にbusyBarがindeterminateのまま残っている"
        "(次のフル変換開始まで静止して見える)"
    )
    assert busy_bar.stop_calls == 1
    assert busy_bar.place_forgotten is True
    # 2026-08-01 #635マージにより判明: convertButtonの有効/無効はdev#613/#617で
    # matsButton/previewButtonと同じ無条件ループから外れ、鮮度判定込みの
    # _refresh_convert_button_freshness()(このfakeではno-op)へ責務が移った
    # (本物の挙動はtest_preview_freshness.pyの_refresh_convert_button_freshness
    # 系テストが担当)。このテストの関心事はbusyBarのモード遷移のみなので、
    # convertButtonの状態はここでは検証しない。


# ---------------------------------------------------------------------------
# _on_pipeline_line: ##PROGRESS##マーカー到着時のモード復帰
# ---------------------------------------------------------------------------


def test_on_pipeline_line_marker_forces_determinate_and_sets_value():
    """AppendLog() L.2843-2853相当: ##PROGRESS##到着時、busyBarがindeterminate
    (Unity輸出のMarquee相当)のまま残っていてもdeterminateへ戻し、値を反映する
    (dev#602: マーカーが来た=実進捗が分かっている状態の安全側保証)。"""
    fake_self = _FakeSelfForPipelineLine(busy_bar_mode="indeterminate")
    fake_self._on_pipeline_line("##PROGRESS## 42 retarget")
    busy_bar = fake_self.widgets["busyBar"]
    assert busy_bar["mode"] == "determinate"
    assert busy_bar["value"] == 42


def test_on_pipeline_line_non_marker_line_does_not_touch_busy_bar_mode():
    """負の対照: 通常のログ行(マーカーでない)ではbusyBarモードに一切触れない
    (indeterminate中の残り時間表示を無駄に中断させない)。"""
    fake_self = _FakeSelfForPipelineLine(busy_bar_mode="indeterminate")
    fake_self._on_pipeline_line("plain log line, not a progress marker")
    busy_bar = fake_self.widgets["busyBar"]
    assert busy_bar["mode"] == "indeterminate"
    assert busy_bar.stop_calls == 0
    assert fake_self.logged == ["plain log line, not a progress marker"]
