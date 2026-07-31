# -*- coding: utf-8 -*-
"""G1-b/c: ゲートE(crash_test)・F(play_start_test)のPASS/FAIL/SKIP分岐をモックで
検証する。実機は一切起動しない — crash_test.run/play_start_test.runに相当する
偽モジュールを注入するだけ(U24 work\\u24_diag\\test_ui_fail.pyのモンキーパッチ
方式を踏襲。ここではpytestのmonkeypatchフィクスチャで安全に行う)。
"""
import gates


class _FakeCrashTestModule:
    def __init__(self, rc):
        self.rc = rc
        self.calls = []

    def run(self, selector, paks_dir, wait_seconds, out=None, force=False, auto_close=False):
        self.calls.append((selector, paks_dir, wait_seconds, force, auto_close))
        if out is not None:
            out.write("fake crash_test run rc={}\n".format(self.rc))
        return self.rc


def test_gate_e_not_crashed_is_pass():
    ct = _FakeCrashTestModule(0)
    gr = gates.gate_e_crash(ct, "dummy.pak", r"C:\fake\Paks")
    assert gr.status == "PASS"
    assert ct.calls[0][3] is True and ct.calls[0][4] is True  # force/auto_close


def test_gate_e_crashed_is_fail():
    ct = _FakeCrashTestModule(2)
    gr = gates.gate_e_crash(ct, "dummy.pak", r"C:\fake\Paks")
    assert gr.status == "FAIL"
    assert gr.detail["exit_code"] == 2


def test_gate_e_config_error_is_fail():
    ct = _FakeCrashTestModule(1)
    gr = gates.gate_e_crash(ct, "dummy.pak", r"C:\fake\Paks")
    assert gr.status == "FAIL"


def test_gate_e_unknown_timeout_is_skip():
    ct = _FakeCrashTestModule(3)
    gr = gates.gate_e_crash(ct, "dummy.pak", r"C:\fake\Paks")
    assert gr.status == "SKIP"


class _FakePlayStartModule:
    def __init__(self, rc_sequence):
        self.rc_sequence = list(rc_sequence)
        self.calls = []

    def run(self, pak_ref, wait_after_start=60, launch_wait=18, paks_dir=None, vanilla=False,
            evidence_shot_dir=None, auto_close=True, world_click_xy=None, world_template=None,
            step_shot_dir=None, face_camera=True, face_hold=0.6):
        self.calls.append(pak_ref)
        return self.rc_sequence.pop(0)


def test_gate_f_single_success_is_pass():
    pst = _FakePlayStartModule([0])
    gr = gates.gate_f_playstart(pst, "dummy.pak", repeat=1)
    assert gr.status == "PASS"
    assert gr.detail["n_pass"] == 1


def test_gate_f_single_crash_is_fail():
    pst = _FakePlayStartModule([2])
    gr = gates.gate_f_playstart(pst, "dummy.pak", repeat=1)
    assert gr.status == "FAIL"
    assert gr.detail["n_crash"] == 1


def test_gate_f_single_ui_not_found_is_skip_not_fail():
    """exit 1(真のUI未検出)は製品の欠陥ではないためFAILにしない、が
    docs\\U32_SONNET_INSTRUCTIONS.md 4-3節の明示要件。"""
    pst = _FakePlayStartModule([1])
    gr = gates.gate_f_playstart(pst, "dummy.pak", repeat=1)
    assert gr.status == "SKIP"
    assert "UI未検出" in gr.detail["note"]


def test_gate_f_repeat_one_success_among_crashes_is_pass_with_crash_count():
    pst = _FakePlayStartModule([2, 2, 0])
    gr = gates.gate_f_playstart(pst, "dummy.pak", repeat=3)
    assert gr.status == "PASS"
    assert gr.detail["n_crash"] == 2
    assert gr.detail["n_pass"] == 1
    assert len(pst.calls) == 3


def test_gate_f_repeat_all_crash_is_fail():
    pst = _FakePlayStartModule([2, 2, 2])
    gr = gates.gate_f_playstart(pst, "dummy.pak", repeat=3)
    assert gr.status == "FAIL"
    assert gr.detail["n_crash"] == 3


def test_gate_f_repeat_all_ui_fail_is_skip():
    pst = _FakePlayStartModule([1, 1])
    gr = gates.gate_f_playstart(pst, "dummy.pak", repeat=2)
    assert gr.status == "SKIP"
