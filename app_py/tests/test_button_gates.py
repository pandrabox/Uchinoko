# test_button_gates.py -- dev#639/#640受入条件。
#
# 対象issue:
#   - dev#639: UpdateButtonStates()のblenderReadyゲート
#     (app\DiveToPalworld.cs L.2468-2525)未移植。Blender準備完了(blenderReady)
#     前にconvert/mats/previewボタンが押せてしまう問題を、py版
#     ui\main_window.py の _update_button_states()/_set_running_ui_state()へ
#     移植したことの単体試験。
#   - dev#640: KillBlenderSetupProcess()(同cs L.1339-1353)未移植。
#     app_py\blender_setup.py に子プロセス参照+kill APIを追加し、
#     GUI終了時(WM_DELETE_WINDOW)から黙って始末する配線ができたことの試験。
#
# 方針(共通契約どおり、tkの実ウィンドウは一切開かない):
# test_main_window_diagnostics_wiring.py と同じ「フェイクself + 束縛前
# メソッド呼び出し」方式。MainWindow.__init__は通さず、各結線メソッドを
# `mw.MainWindow._method(fake_self, ...)` の形で直接呼ぶ。
from __future__ import annotations

import os
import subprocess
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import blender_setup  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# フェイク部品
# ---------------------------------------------------------------------------


class _FakeButton:
    """tkinter.Button互換の最小フェイク(config(state=...)のみ)。"""

    def __init__(self) -> None:
        self.state: str | None = None

    def config(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]

    def __getitem__(self, key):  # busyBar["value"] = 0 相当のため
        return None

    def __setitem__(self, key, value) -> None:
        return None

    def place(self, **_kwargs) -> None:
        return None

    def place_forget(self) -> None:
        return None

    def start(self, _interval: object = None) -> None:
        # busyBarフェイクとしても使い回すための最小許容
        # (_set_busy_bar_mode()がstart/stopを呼ぶ、dev#602/#633統合後)。
        return None

    def stop(self) -> None:
        return None


class _FakeEntry:
    """tkinter.Entry互換の最小フェイク(.get()のみ)。"""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def get(self) -> str:
        return self._text


class _FakeSelfForGates:
    """MainWindow._set_running_ui_state/_update_button_statesを束縛せずに
    呼ぶための最小self。widgetsに必要な5ボタン(convert/mats/preview/
    cancel/busyBar)+vrmBoxを持つ。

    2026-08-01 #647統合(PR #635/#637マージ後): _update_button_states()が
    hasVrm/workRootFailedも見るようになったため、既定でhasVrm=True
    (実在するvrm_pathを指すvrmBox)・_work_root_failed=Falseにしておき、
    本ファイルの本来の関心事(blenderReady/busyゲート)を検査する既存テスト群が
    このガード追加で意図せず壊れないようにする(hasVrm/workRootFailed単体の
    ガードはtest_preview_freshness.py/test_guard_dialogs.pyの担当)。"""

    _update_button_states = mw.MainWindow._update_button_states
    _set_running_ui_state = mw.MainWindow._set_running_ui_state
    _refresh_convert_button_freshness = mw.MainWindow._refresh_convert_button_freshness
    _set_busy_bar_mode = mw.MainWindow._set_busy_bar_mode

    def __init__(self, *, vrm_path: str = "", fresh: bool = True) -> None:
        self._is_pipeline_running = False
        self._blender_ready = False
        self._work_root_failed = False
        self._active_handle = None
        self._fresh = fresh
        self._busy_bar_geometry = {"x": 330, "y": 46, "width": 740, "height": 12}
        self.widgets = {
            "convertButton": _FakeButton(),
            "matsButton": _FakeButton(),
            "previewButton": _FakeButton(),
            "cancelButton": _FakeButton(),
            "busyBar": _FakeButton(),
            "vrmBox": _FakeEntry(vrm_path),
            "statusLabel": _FakeButton(),
        }

    def _is_preview_fresh(self, _vrm_path: str) -> bool:
        # convertButtonの鮮度判定(_refresh_convert_button_freshness経由)を
        # 呼び出し側が制御できるようにする最小フェイク。本ファイルの関心事は
        # blenderReady/busyゲートなので既定Trueにしておき、
        # hasVrmさえ満たせばconvertButtonもnormalになるようにする。
        return self._fresh


# ===========================================================================
# dev#639: blenderReadyゲート
# ===========================================================================


def test_buttons_disabled_when_blender_not_ready_and_not_running():
    # 2026-08-01 #647統合: _update_button_states()はmatsButton/previewButton
    # のみを担当(convertButtonは_refresh_convert_button_freshness()側、
    # 鮮度判定が絡むため分離済み。同メソッドのblenderReadyゲートは
    # test_convert_button_freshness_respects_blender_ready_gate群で検査)。
    fake_self = _FakeSelfForGates()
    fake_self._blender_ready = False
    fake_self._is_pipeline_running = False
    mw.MainWindow._update_button_states(fake_self)
    for key in ("matsButton", "previewButton"):
        assert fake_self.widgets[key].state == "disabled", key


def test_buttons_enabled_when_blender_ready_and_not_running():
    fake_self = _FakeSelfForGates(vrm_path="dummy_but_unused_for_this_gate.vrm")
    fake_self._blender_ready = True
    fake_self._is_pipeline_running = False
    mw.MainWindow._update_button_states(fake_self)
    for key in ("matsButton", "previewButton"):
        assert fake_self.widgets[key].state == "disabled", (
            key,
            "hasVrmを満たしていないので依然disabledのはず(dev#639統合でhasVrmゲートも追加された)",
        )


def test_buttons_enabled_when_blender_ready_has_vrm_and_not_running(tmp_path):
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake_self = _FakeSelfForGates(vrm_path=str(vrm))
    fake_self._blender_ready = True
    fake_self._is_pipeline_running = False
    mw.MainWindow._update_button_states(fake_self)
    for key in ("matsButton", "previewButton"):
        assert fake_self.widgets[key].state == "normal", key


def test_buttons_disabled_when_running_even_if_blender_ready(tmp_path):
    # 負の対照: blenderReady=True・hasVrm=Trueでも実行中(busy)なら押させない
    # (C#版 `!busy && ... && blenderReady` の busy側が効くケース)。
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake_self = _FakeSelfForGates(vrm_path=str(vrm))
    fake_self._blender_ready = True
    fake_self._is_pipeline_running = True
    mw.MainWindow._update_button_states(fake_self)
    for key in ("matsButton", "previewButton"):
        assert fake_self.widgets[key].state == "disabled", key


def test_convert_button_freshness_respects_blender_ready_gate():
    # dev#639×dev#617統合: convertButtonはblenderReady=Falseなら
    # hasVrm/freshに関わらずdisabledのまま
    # (_refresh_convert_button_freshness()側に追加したガード)。
    fake_self = _FakeSelfForGates(vrm_path="", fresh=True)
    fake_self._blender_ready = False
    mw.MainWindow._refresh_convert_button_freshness(fake_self)
    assert fake_self.widgets["convertButton"].state == "disabled"


def test_set_running_ui_state_true_disables_regardless_of_blender_ready():
    # dev#639導入前の既存挙動(実行中は問答無用でdisabled)が壊れていないこと
    # の負の対照。
    fake_self = _FakeSelfForGates()
    fake_self._blender_ready = True
    mw.MainWindow._set_running_ui_state(fake_self, True)
    for key in ("convertButton", "matsButton", "previewButton"):
        assert fake_self.widgets[key].state == "disabled", key
    assert fake_self.widgets["cancelButton"].state == "normal"
    assert fake_self._is_pipeline_running is True


def test_set_running_ui_state_false_respects_blender_ready_gate():
    # dev#639の本体: running=Falseに戻っても、blenderReadyがまだFalseなら
    # (Blender準備中に一度も成功していない状態)ボタンは有効化されない。
    fake_self = _FakeSelfForGates()
    fake_self._blender_ready = False
    mw.MainWindow._set_running_ui_state(fake_self, False)
    for key in ("convertButton", "matsButton", "previewButton"):
        assert fake_self.widgets[key].state == "disabled", key
    assert fake_self.widgets["cancelButton"].state == "disabled"
    assert fake_self._is_pipeline_running is False


def test_set_running_ui_state_false_enables_when_blender_ready(tmp_path):
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake_self = _FakeSelfForGates(vrm_path=str(vrm))
    fake_self._blender_ready = True
    mw.MainWindow._set_running_ui_state(fake_self, False)
    for key in ("convertButton", "matsButton", "previewButton"):
        assert fake_self.widgets[key].state == "normal", key


# ===========================================================================
# dev#640: Blenderセットアップ子プロセスのサイレントkill
# ===========================================================================


class _FakePopen:
    """subprocess.Popen互換の最小フェイク(pidのみ)。"""

    def __init__(self, pid: int) -> None:
        self.pid = pid


def test_blender_setup_process_handle_kill_calls_taskkill(monkeypatch):
    handle = blender_setup.BlenderSetupProcessHandle()
    handle.proc = _FakePopen(pid=4242)

    calls = []

    def _fake_run(args, **kwargs):
        calls.append(args)

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    handle.kill()

    assert len(calls) == 1
    assert calls[0] == ["taskkill", "/T", "/F", "/PID", "4242"]


def test_blender_setup_process_handle_kill_noop_when_no_process(monkeypatch):
    # 負の対照: プロセス未登録(procがNone)ならtaskkillを一切呼ばない。
    handle = blender_setup.BlenderSetupProcessHandle()
    handle.proc = None

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    handle.kill()

    assert calls == []


def test_blender_setup_process_handle_kill_swallows_exceptions(monkeypatch):
    # C#版と同じく、taskkill失敗(プロセスが既に終了している等)でも例外を
    # 外へ漏らさない(GUI終了処理を巻き込んで落とさないための必須要件)。
    handle = blender_setup.BlenderSetupProcessHandle()
    handle.proc = _FakePopen(pid=1)

    def _raise(*_a, **_k):
        raise OSError("process already gone")

    monkeypatch.setattr(subprocess, "run", _raise)
    handle.kill()  # 例外を投げなければOK


def test_run_ensure_blender_setup_process_registers_and_clears_handle(monkeypatch, tmp_path):
    # process_handleを渡すと、プロセス実行中はhandle.procにPopenが入り、
    # 終了後(成功時)は必ずNoneへ戻ることを確認する
    # (C#版 blenderSetupProc = proc; ... blenderSetupProc = null; 相当)。
    class _FakeProc:
        def __init__(self, lines, returncode, pid):
            self.stdout = iter(lines)
            self.returncode = returncode
            self.pid = pid

        def wait(self):
            return self.returncode

    fake_proc = _FakeProc(["##PROGRESS## 100 Done\n"], returncode=0, pid=999)

    def _fake_popen(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    handle = blender_setup.BlenderSetupProcessHandle()
    assert handle.proc is None

    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1", str(tmp_path), process_handle=handle
    )

    assert ok is True
    assert fail_message is None
    # 終了後は必ずNoneに戻っている(kill()が二重発火して無関係のプロセスを
    # 巻き込まないための必須条件)。
    assert handle.proc is None


def test_run_ensure_blender_setup_process_clears_handle_even_on_failure(monkeypatch, tmp_path):
    # 負の対照: 失敗終了(returncode!=0)でもhandle.procは必ずNoneへ戻る。
    class _FakeProc:
        def __init__(self, lines, returncode, pid):
            self.stdout = iter(lines)
            self.returncode = returncode
            self.pid = pid

        def wait(self):
            return self.returncode

    fake_proc = _FakeProc(
        ["[D2P_BLENDER_SETUP_FAIL] boom\n"], returncode=1, pid=555
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake_proc)

    handle = blender_setup.BlenderSetupProcessHandle()
    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1", str(tmp_path), process_handle=handle
    )

    assert ok is False
    assert fail_message is not None
    assert handle.proc is None


class _FakeRoot:
    """MainWindow._on_form_closingを試験するための最小root(destroy()の
    呼び出し記録のみ)。"""

    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _FakeSelfForClose:
    """2026-08-01 #647統合: dev#640(KillBlenderSetupProcess)は独立した
    _on_close_request()ではなく、#637の_on_form_closing()(WM_DELETE_WINDOW
    の唯一のハンドラ)へ合流させた(PR #647本文の指示どおり)。C#版
    FormClosing(L.1292-1305)もKillBlenderSetupProcess()を先頭で無条件に
    呼んでから実行中確認へ進むため、_active_handle=Noneにして確認ダイアログ
    分岐をスキップし、blender kill→destroyの経路だけを検査する。"""

    _on_form_closing = mw.MainWindow._on_form_closing

    def __init__(self) -> None:
        self.root = _FakeRoot()
        self._blender_setup_process_handle = blender_setup.BlenderSetupProcessHandle()
        self._active_handle = None


def test_on_form_closing_kills_blender_setup_process_and_destroys_root(monkeypatch):
    # dev#640の結線そのもの: _on_form_closing()がまずhandle.kill()を呼んで
    # から(runningProc==nullなら確認無しで)root.destroy()すること
    # (C#版FormClosing L.1298 KillBlenderSetupProcess()相当、確認ダイアログより先)。
    fake_self = _FakeSelfForClose()
    fake_self._blender_setup_process_handle.proc = _FakePopen(pid=77)

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(args))

    mw.MainWindow._on_form_closing(fake_self)

    assert calls == [["taskkill", "/T", "/F", "/PID", "77"]]
    assert fake_self.root.destroyed is True


def test_on_form_closing_destroys_root_even_without_blender_process(monkeypatch):
    # 負の対照: Blenderセットアップが一度も走っていない(proc=None)通常時は
    # taskkillを呼ばずにdestroy()だけ行う。
    fake_self = _FakeSelfForClose()

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(args))

    mw.MainWindow._on_form_closing(fake_self)

    assert calls == []
    assert fake_self.root.destroyed is True
