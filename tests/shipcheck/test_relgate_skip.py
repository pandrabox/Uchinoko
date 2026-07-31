# -*- coding: utf-8 -*-
r"""dev#128/rd_121: ship_smoke Tier B の重複変換SKIP(relgate結果参照)の試験。

研究正本: C:\P\Work\DiveToPalworld\work\rd_121\PROPOSAL.md
実装依頼: dev issue #128(pandrabox/DiveToPalworld-dev)

対象: tests\shipcheck\ship_convert_cases.py
  - decide_relgate_skip()  : 純関数(ファイルI/O・git呼び出し無し)。鮮度条件
    (relgate結果のgit HEADが現HEADと一致する場合のみSKIP可)の判定本体。
  - _try_relgate_skip()    : decide_relgate_skip() の薄いI/Oラッパ。
  - run_case()             : vrm_full_0x / drop_bone_exclusion の2ケースが
    実際にSKIP経路/フォールバック経路のどちらを通るかをモックで検証する。

受入条件(issue #128): SKIP発動時と非発動時の両方の経路が動く負の対照。
本ファイルは両方をカバーする:
  - test_run_case_*_skips_when_relgate_fresh_and_pass  (SKIP発動)
  - test_run_case_*_falls_back_when_*                  (SKIP非発動、複数原因)
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ship_convert_cases as scc  # noqa: E402


# --- decide_relgate_skip() 純関数の単体試験 ------------------------------------

def _fresh_results(head="deadbeef" * 5, avatar_key="vrm0_kate",
                    layer1="PASS", layer2="PASS"):
    return {
        "schema": 1,
        "git_head": head,
        "overall": "PASS",
        "avatars": {
            avatar_key: {
                "skipped": False,
                "layers": {
                    "1": {"status": layer1},
                    "2": {"status": layer2},
                },
            },
        },
    }


def test_decide_relgate_skip_true_when_fresh_and_pass():
    head = "deadbeef" * 5
    results = _fresh_results(head=head)
    ok, reason = scc.decide_relgate_skip(results, "vrm0_kate", head)
    assert ok is True
    assert "vrm0_kate" in reason


def test_decide_relgate_skip_false_when_results_none():
    ok, reason = scc.decide_relgate_skip(None, "vrm0_kate", "deadbeef" * 5)
    assert ok is False
    assert "results.json" in reason or "relgate結果" in reason


def test_decide_relgate_skip_false_when_results_not_dict():
    ok, reason = scc.decide_relgate_skip("not a dict", "vrm0_kate", "deadbeef" * 5)
    assert ok is False


def test_decide_relgate_skip_false_when_git_head_missing_in_results():
    results = _fresh_results()
    del results["git_head"]
    ok, reason = scc.decide_relgate_skip(results, "vrm0_kate", "deadbeef" * 5)
    assert ok is False
    assert "鮮度条件" in reason


def test_decide_relgate_skip_false_when_head_mismatch():
    results = _fresh_results(head="oldoldold" * 4)
    ok, reason = scc.decide_relgate_skip(results, "vrm0_kate", "newnewnew" * 4)
    assert ok is False
    assert "鮮度条件" in reason


def test_decide_relgate_skip_false_when_current_head_none():
    """呼び出し側のgit rev-parseが失敗した場合(current_head=None)も、
    比較不能なので必ずSKIP不可側へ倒れる(fail-closed)。"""
    head = "deadbeef" * 5
    results = _fresh_results(head=head)
    ok, reason = scc.decide_relgate_skip(results, "vrm0_kate", None)
    assert ok is False


def test_decide_relgate_skip_false_when_avatar_key_missing():
    head = "deadbeef" * 5
    results = _fresh_results(head=head, avatar_key="vrm1_seedsan")
    ok, reason = scc.decide_relgate_skip(results, "vrm0_kate", head)
    assert ok is False
    assert "vrm0_kate" in reason


@pytest.mark.parametrize("layer1,layer2", [
    ("FAIL", "PASS"),
    ("PASS", "FAIL"),
    ("PENDING_APPROVAL", "PASS"),
    ("PASS", "PENDING_APPROVAL"),
    ("FAIL", "FAIL"),
])
def test_decide_relgate_skip_false_when_any_layer_not_pass(layer1, layer2):
    head = "deadbeef" * 5
    results = _fresh_results(head=head, layer1=layer1, layer2=layer2)
    ok, reason = scc.decide_relgate_skip(results, "vrm0_kate", head)
    assert ok is False
    assert "層" in reason


def test_case_relgate_avatar_key_mapping_matches_rd_121():
    """PROPOSAL.md根拠④で重複と判定された2組のみが対象(issue #128本文どおり)。
    uv_out_of_range_warning/vrm_full_10 は目的が異なるため対象外
    (PROPOSAL.md根拠④表の評価「形式的重複のみ、残置が妥当」)。"""
    assert scc.CASE_RELGATE_AVATAR_KEY == {
        "vrm_full_0x": "vrm0_kate",
        "drop_bone_exclusion": "vrm1_seedsan",
    }


# --- _try_relgate_skip() ラッパ(I/Oをモック) ------------------------------------

def test_try_relgate_skip_false_for_unmapped_case(monkeypatch):
    ok, reason = scc._try_relgate_skip("uv_out_of_range_warning", "/fake/relgate_work")
    assert ok is False
    assert "対象外" in reason


def test_try_relgate_skip_false_when_relgate_work_none():
    ok, reason = scc._try_relgate_skip("vrm_full_0x", None)
    assert ok is False
    assert "未指定" in reason


def test_try_relgate_skip_true_when_mocked_fresh_pass(monkeypatch):
    head = "cafef00d" * 5
    monkeypatch.setattr(scc, "_current_git_head", lambda: head)
    monkeypatch.setattr(scc, "_load_relgate_results",
                        lambda work: _fresh_results(head=head))
    ok, reason = scc._try_relgate_skip("vrm_full_0x", "/fake/relgate_work")
    assert ok is True


def test_try_relgate_skip_false_when_mocked_results_missing(monkeypatch):
    monkeypatch.setattr(scc, "_current_git_head", lambda: "cafef00d" * 5)
    monkeypatch.setattr(scc, "_load_relgate_results", lambda work: None)
    ok, reason = scc._try_relgate_skip("vrm_full_0x", "/fake/relgate_work")
    assert ok is False


# --- run_case() 統合試験: SKIP発動 / 非発動の両経路(issue #128 受入条件) --------

class _ConvertCalledError(AssertionError):
    """_run_convert()が呼ばれたら即failさせる毒薬(SKIP経路が本当に実変換を
    避けていることを証明するため)。"""


def _poison_run_convert(monkeypatch):
    def _boom(*a, **kw):
        raise _ConvertCalledError("_run_convert() が呼ばれた(SKIP経路の実装ミス)")
    monkeypatch.setattr(scc, "_run_convert", _boom)


def test_run_case_vrm_full_0x_skips_when_relgate_fresh_and_pass(tmp_path, monkeypatch):
    head = "cafef00d" * 5
    monkeypatch.setattr(scc, "_current_git_head", lambda: head)
    monkeypatch.setattr(scc, "_load_relgate_results",
                        lambda work: _fresh_results(head=head, avatar_key="vrm0_kate"))
    _poison_run_convert(monkeypatch)  # 実変換に落ちたら即fail

    relgate_work = str(tmp_path / "relgate_run")
    case = {"name": "vrm_full_0x", "est_sec": 165, "relgate_work": relgate_work}
    work_root = str(tmp_path / "case_work")
    shots_dir = str(tmp_path / "shots")

    result = scc.run_case(case, work_root, shots_dir)

    assert result["ok"] is True
    detail = json.loads(result["detail"])
    assert detail["skipped_via_relgate"] is True
    assert detail["relgate_avatar_key"] == "vrm0_kate"


def test_run_case_drop_bone_exclusion_skips_when_relgate_fresh_and_pass(tmp_path, monkeypatch):
    head = "cafef00d" * 5
    monkeypatch.setattr(scc, "_current_git_head", lambda: head)
    monkeypatch.setattr(scc, "_load_relgate_results",
                        lambda work: _fresh_results(head=head, avatar_key="vrm1_seedsan"))
    _poison_run_convert(monkeypatch)

    relgate_work = str(tmp_path / "relgate_run")
    case = {"name": "drop_bone_exclusion", "est_sec": 300, "relgate_work": relgate_work}
    work_root = str(tmp_path / "case_work")
    shots_dir = str(tmp_path / "shots")

    result = scc.run_case(case, work_root, shots_dir)

    assert result["ok"] is True
    detail = json.loads(result["detail"])
    assert detail["skipped_via_relgate"] is True
    assert detail["relgate_avatar_key"] == "vrm1_seedsan"


def test_run_case_vrm_full_0x_falls_back_when_relgate_results_missing(tmp_path, monkeypatch):
    """relgate_workは指定されているが結果が読めない(古い/存在しない)場合、
    SKIPせず実変換にフォールバックすること(fail-closed)。フォールバック経路が
    実際に踏まれたことは、path_overrideのダミーファイルを介して_run_convert()
    (モック)が呼ばれたことで確認する。"""
    monkeypatch.setattr(scc, "_current_git_head", lambda: "cafef00d" * 5)
    monkeypatch.setattr(scc, "_load_relgate_results", lambda work: None)  # 結果なし

    called = {}

    def _fake_run_convert(job_path, log_path, **kw):
        called["hit"] = True
        log_text = ("=== 完成 ===\n[PASS] G1 dummy\n")
        return 0, log_text, False

    monkeypatch.setattr(scc, "_run_convert", _fake_run_convert)

    dummy_src = tmp_path / "dummy.vrm"
    dummy_src.write_bytes(b"not a real vrm, just needs to exist")

    relgate_work = str(tmp_path / "relgate_run")
    case = {"name": "vrm_full_0x", "est_sec": 165, "relgate_work": relgate_work,
            "path_override": str(dummy_src)}
    work_root = str(tmp_path / "case_work")
    shots_dir = str(tmp_path / "shots")

    result = scc.run_case(case, work_root, shots_dir)

    assert called.get("hit") is True, "フォールバック時は_run_convert()が実際に呼ばれるべき"
    detail = json.loads(result["detail"])
    assert detail["skipped_via_relgate"] is False
    assert detail["input"] == str(dummy_src)


def test_run_case_drop_bone_exclusion_falls_back_when_head_mismatch(tmp_path, monkeypatch):
    """relgate結果はあるが鮮度条件(git HEAD一致)を満たさない場合、SKIPせず
    実変換にフォールバックすること。drop_bone_exclusionはpath_overrideを
    受け付けないため、TEST_VRM_DIRをtmp_pathへ差し替えてダミー検体を置く。"""
    monkeypatch.setattr(scc, "_current_git_head", lambda: "newnewnew" * 4)
    monkeypatch.setattr(
        scc, "_load_relgate_results",
        lambda work: _fresh_results(head="oldoldold" * 4, avatar_key="vrm1_seedsan"))

    called = {}

    def _fake_run_convert(job_path, log_path, **kw):
        called["hit"] = True
        log_text = ("=== 完成 ===\n[PASS] G1 dummy\n"
                    "drop_bones: SomeMesh: 10頂点削除\n")
        return 0, log_text, False

    monkeypatch.setattr(scc, "_run_convert", _fake_run_convert)

    dummy_vrm_dir = tmp_path / "test_vrm_dir"
    dummy_vrm_dir.mkdir()
    (dummy_vrm_dir / "Seed-san.vrm").write_bytes(b"not a real vrm, just needs to exist")
    monkeypatch.setattr(scc, "TEST_VRM_DIR", str(dummy_vrm_dir))

    relgate_work = str(tmp_path / "relgate_run")
    case = {"name": "drop_bone_exclusion", "est_sec": 300, "relgate_work": relgate_work}
    work_root = str(tmp_path / "case_work")
    shots_dir = str(tmp_path / "shots")

    result = scc.run_case(case, work_root, shots_dir)

    assert called.get("hit") is True, "フォールバック時は_run_convert()が実際に呼ばれるべき"
    detail = json.loads(result["detail"])
    assert detail["skipped_via_relgate"] is False


def test_run_case_falls_back_when_relgate_work_not_provided(tmp_path, monkeypatch):
    """従来どおりの呼び出し元(relgate_workキー自体が無い、または既定Noneのまま)は
    SKIP判定に一切触れず実変換のみが走ること(後方互換の確認)。"""
    called = {}

    def _fake_run_convert(job_path, log_path, **kw):
        called["hit"] = True
        return 1, "変換失敗ダミー", False

    monkeypatch.setattr(scc, "_run_convert", _fake_run_convert)

    dummy_src = tmp_path / "dummy.vrm"
    dummy_src.write_bytes(b"dummy")

    case = {"name": "vrm_full_0x", "est_sec": 165, "path_override": str(dummy_src)}
    # relgate_work キーを意図的に付けない(既存呼び出し元の再現)
    work_root = str(tmp_path / "case_work")
    shots_dir = str(tmp_path / "shots")

    result = scc.run_case(case, work_root, shots_dir)

    assert called.get("hit") is True
    detail = json.loads(result["detail"])
    assert detail["skipped_via_relgate"] is False
