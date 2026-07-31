# -*- coding: utf-8 -*-
"""G1-c: ゲートG(見た目AI一次照合)のPASS/FAIL/SKIP分岐と、checker_pattern_checkの
claude CLI呼び出しパース処理をモックで検証する。advisoryなのでFAILでも例外を
投げないこと自体もここで確認する(test_gate_g_*関数はGateResultを返すだけで
raiseしない設計)。
"""
import json

import gates


def test_gate_g_checker_no_pattern_is_pass():
    gr = gates.gate_g_checker("dummy.png", checker_fn=lambda p: {"checker_present": False})
    assert gr.status == "PASS"


def test_gate_g_checker_pattern_detected_is_fail():
    gr = gates.gate_g_checker("dummy.png", checker_fn=lambda p: {"checker_present": True})
    assert gr.status == "FAIL"


def test_gate_g_checker_undecidable_is_skip():
    gr = gates.gate_g_checker(
        "dummy.png", checker_fn=lambda p: {"checker_present": None, "error": "claude CLI無し"})
    assert gr.status == "SKIP"
    assert "claude CLI無し" in gr.detail["note"]


def test_gate_g_compare_both_true_is_pass(tmp_path):
    ingame = tmp_path / "crop.png"
    ref = tmp_path / "ref.png"
    ingame.write_bytes(b"x")
    ref.write_bytes(b"x")
    fn = lambda a, b: {"same_avatar": True, "looks_correct": True}
    gr = gates.gate_g_compare(str(ingame), str(ref), fn)
    assert gr.status == "PASS"


def test_gate_g_compare_different_avatar_is_fail(tmp_path):
    ingame = tmp_path / "crop.png"
    ref = tmp_path / "ref.png"
    ingame.write_bytes(b"x")
    ref.write_bytes(b"x")
    fn = lambda a, b: {"same_avatar": False, "looks_correct": True, "notes": "別デザイン"}
    gr = gates.gate_g_compare(str(ingame), str(ref), fn)
    assert gr.status == "FAIL"


def test_gate_g_compare_missing_files_is_skip_without_calling(tmp_path):
    calls = []

    def fn(a, b):
        calls.append((a, b))
        return {"same_avatar": True, "looks_correct": True}

    gr = gates.gate_g_compare(str(tmp_path / "nope_ingame.png"), str(tmp_path / "nope_ref.png"), fn)
    assert gr.status == "SKIP"
    assert calls == [], "画像が無いのにcompare_fnが呼ばれた"


def test_gate_g_compare_error_verdict_is_skip(tmp_path):
    ingame = tmp_path / "crop.png"
    ref = tmp_path / "ref.png"
    ingame.write_bytes(b"x")
    ref.write_bytes(b"x")
    fn = lambda a, b: {"error": "claude CLI失敗 rc=1", "same_avatar": None}
    gr = gates.gate_g_compare(str(ingame), str(ref), fn)
    assert gr.status == "SKIP"


# --- checker_pattern_check自体(claude CLI呼び出しの薄いラッパー)の解析検証 ---

class _FakeProc:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _cli_envelope(result_text, is_error=False):
    return json.dumps({"type": "result", "is_error": is_error, "result": result_text})


def test_checker_pattern_check_parses_valid_json(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"x")
    verdict_json = '{"checker_present": false, "confidence": 0.9, "notes": "問題なし"}'

    def fake_runner(args):
        return _FakeProc(0, _cli_envelope(verdict_json))

    result = gates.checker_pattern_check(str(img), claude_runner=fake_runner)
    assert result["checker_present"] is False
    assert result["confidence"] == 0.9


def test_checker_pattern_check_cli_error_returns_none(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"x")

    def fake_runner(args):
        return _FakeProc(1, "")

    result = gates.checker_pattern_check(str(img), claude_runner=fake_runner)
    assert result["checker_present"] is None
    assert "error" in result


def test_checker_pattern_check_is_error_envelope_returns_none(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"x")

    def fake_runner(args):
        return _FakeProc(0, _cli_envelope("", is_error=True))

    result = gates.checker_pattern_check(str(img), claude_runner=fake_runner)
    assert result["checker_present"] is None
