# -*- coding: utf-8 -*-
r"""dev#220(release_profile.md §4.3「relgateスキップ機構のhit/miss要約が
release.py側に出ていない」)の単体試験。

対象: devtools\relgate.py の classify_skip_decision()
  (run_avatar_layers12()内のneeds_conv/skip_outから、hit/miss/disabled/
  not_attemptedの4値を導く純関数。release.pyのformat_relgate_skip_summary()
  が読むresults.jsonの"skip_decision"/"skip_reason"フィールドの実体)。

実変換・実Blender・実relgate実行は一切課さない(純関数の入出力のみ)。

実行: python -m pytest tests\shipcheck\test_relgate_skip_classification.py -v
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_relgate():
    return importlib.import_module("relgate")


def test_not_attempted_when_needs_conv_false():
    relgate = _import_relgate()
    decision, reason = relgate.classify_skip_decision(False, None)
    assert decision == "not_attempted"
    assert "baseline" in reason


def test_not_attempted_wins_even_if_skip_out_present():
    """needs_conv=Falseなら変換自体が行われていないので、万一skip_outが
    (呼び出し側の誤りで)渡っていても not_attempted を優先する
    (fail-safe: needs_convが最優先の判定材料)。"""
    relgate = _import_relgate()
    decision, _ = relgate.classify_skip_decision(
        False, {"decision": "skip", "digest": {"combined": "deadbeef"}})
    assert decision == "not_attempted"


def test_disabled_when_skip_out_is_none():
    relgate = _import_relgate()
    decision, reason = relgate.classify_skip_decision(True, None)
    assert decision == "disabled"
    assert "無効" in reason


def test_hit_when_skip_out_decision_is_skip():
    relgate = _import_relgate()
    skip_out = {"decision": "skip", "digest": {"combined": "abcdef1234567890"}}
    decision, reason = relgate.classify_skip_decision(True, skip_out)
    assert decision == "hit"
    assert "abcdef1234567890"[:16] in reason


def test_miss_when_skip_out_decision_is_full():
    relgate = _import_relgate()
    skip_out = {"decision": "full", "reason": "中間ハッシュ不一致(意図的変更または上流の退行)"}
    decision, reason = relgate.classify_skip_decision(True, skip_out)
    assert decision == "miss"
    assert reason == "中間ハッシュ不一致(意図的変更または上流の退行)"


def test_miss_when_skip_out_decision_is_fail():
    """負の対照: Phase 0-1自体が失敗した場合(decision="fail")も、
    "hit"に紛れ込ませず"miss"として扱う(hitを過大報告しない)。"""
    relgate = _import_relgate()
    skip_out = {"decision": "fail", "reason": "Phase 0-1(バニラ準備+Blender工程)が失敗(fail-closed)"}
    decision, reason = relgate.classify_skip_decision(True, skip_out)
    assert decision == "miss"
    assert "Phase 0-1" in reason


def test_miss_reason_falls_back_when_reason_missing():
    """負の対照: reasonキー自体が無い(理論上到達しないはずの防御ケース)場合、
    空文字列や欠落キーで例外を出さず、プレースホルダ文字列を返す。"""
    relgate = _import_relgate()
    decision, reason = relgate.classify_skip_decision(True, {"decision": "full"})
    assert decision == "miss"
    assert reason == "(理由不明)"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
