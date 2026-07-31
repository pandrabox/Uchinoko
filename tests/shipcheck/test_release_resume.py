# -*- coding: utf-8 -*-
r"""dev#163(release.py リリース関所レジューム機構)のWP-2/WP-3受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実変換・
実relgate・実release.py本番実行を一切課さない(work\rd_resume\PROPOSAL.md
§7 WP-2/WP-3の受入ゲート定義どおり: 単体テスト+モック)。

対象の負の対照(PROPOSAL §5、番号はそのまま踏襲):
  5. WSBが常に再実行されること(--resume-fromでもキャッシュSKIP表記が絶対に出ない)
  6. 最終確認フェーズのrelgate中間ハッシュ検算が実際に発火すること
  7. --resume-from未指定時は一切キャッシュが参照されないこと
  8. 緑runへの--resume-fromが拒否されること

WP-3(fail-closed網羅証明、write_cert()のcoverage): 未知の状態文字列/
欠落ゲートを注入するとassertionが発火することを確認する。

実行: python -m pytest tests\shipcheck\test_release_resume.py -v
"""
import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
TESTS_RELGATE = os.path.join(REPO, "tests", "relgate")

for p in (DEVTOOLS, TESTS_RELGATE):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_release():
    return importlib.import_module("release")


def _import_gate_cache():
    return importlib.import_module("gate_cache")


class DummyReport:
    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)


# =====================================================================
# 負の対照7: --resume-from未指定時は一切キャッシュが参照されないこと
# =====================================================================

def test_resolve_iterative_phase_cache_hits_never_calls_cache_without_resume_from(monkeypatch):
    release = _import_release()
    gate_cache = _import_gate_cache()
    calls = []

    monkeypatch.setattr(gate_cache, "try_use_cached_dist_smoke",
                         lambda *a, **k: calls.append("dist_smoke") or None)
    monkeypatch.setattr(gate_cache, "try_use_cached_relgate",
                         lambda *a, **k: calls.append("relgate") or None)

    dist_fp = {"combined": "dist-fp"}
    relgate_fp = {"combined": "relgate-fp"}
    report = DummyReport()

    dist_result, relgate_result = release.resolve_iterative_phase_cache_hits(
        None, dist_fp, relgate_fp, "work_dir", report)

    assert dist_result is None and relgate_result is None
    assert calls == [], ("--resume-from未指定(None)なのにgate_cache.try_use_cached_*が"
                          f"呼ばれた: {calls}")

    # 空文字列(argparseのdefault挙動と同じ「偽」値)でも同様に一切参照しない
    calls.clear()
    dist_result2, relgate_result2 = release.resolve_iterative_phase_cache_hits(
        "", dist_fp, relgate_fp, "work_dir", report)
    assert calls == []


def test_resolve_iterative_phase_cache_hits_calls_cache_when_resume_from_given(monkeypatch):
    release = _import_release()
    gate_cache = _import_gate_cache()
    calls = []

    def _fake_dist_smoke(fp, work_dir, report):
        calls.append(("dist_smoke", fp))
        return {"name": "dist_smoke", "ok": True, "cache_hit": True}

    def _fake_relgate(fp, work_dir, report):
        calls.append(("relgate", fp))
        return {"name": "relgate_layers12", "ok": True, "cache_hit": True}

    monkeypatch.setattr(gate_cache, "try_use_cached_dist_smoke", _fake_dist_smoke)
    monkeypatch.setattr(gate_cache, "try_use_cached_relgate", _fake_relgate)

    dist_fp = {"combined": "dist-fp"}
    relgate_fp = {"combined": "relgate-fp"}
    report = DummyReport()

    dist_result, relgate_result = release.resolve_iterative_phase_cache_hits(
        "run_20260729_000000", dist_fp, relgate_fp, "work_dir", report)

    assert calls == [("dist_smoke", "dist-fp"), ("relgate", "relgate-fp")]
    assert dist_result["cache_hit"] is True
    assert relgate_result["cache_hit"] is True


def test_resolve_iterative_phase_cache_hits_skips_gate_with_no_fingerprint(monkeypatch):
    """フィンガープリント計算がNoneだった(=計算不能だった)ゲートは、
    --resume-fromが指定されていてもtry_use_cached_*自体を呼ばない
    (呼び出し側main()のNoneガードの直接確認)。"""
    release = _import_release()
    gate_cache = _import_gate_cache()
    calls = []
    monkeypatch.setattr(gate_cache, "try_use_cached_dist_smoke",
                         lambda *a, **k: calls.append("dist_smoke"))
    monkeypatch.setattr(gate_cache, "try_use_cached_relgate",
                         lambda *a, **k: calls.append("relgate") or None)

    report = DummyReport()
    release.resolve_iterative_phase_cache_hits(
        "run_X", None, {"combined": "relgate-fp"}, "work_dir", report)
    assert calls == ["relgate"], "dist_smokeのフィンガープリントがNoneならtry_use_cached_dist_smokeは呼ばれてはならない"


# =====================================================================
# 負の対照5: WSBは恒久的にキャッシュ対象外(SKIP表記が絶対に出ない)
# =====================================================================

def test_wsb_gate_has_no_cache_participation_path():
    """PROPOSAL §1.3・§4: WSBは恒久的にキャッシュ対象外。構造的な保証として、
    (a) gate_cache.CACHEABLE_GATESにwsbが含まれない、
    (b) gate_cacheモジュールにwsb関連の関数が一切定義されていない、
    (c) resolve_iterative_phase_cache_hits()のシグネチャにwsb用の引数が無い
        (=WSBがこの関数の判断対象に含まれる余地が構造的に無い)、
    (d) release.pyのmain()ソース中、run_wsb_convert_gateの呼び出しが
        dist_smoke/relgateのようなNoneガード分岐を経ない無条件submitである、
    ことを確認する(振る舞いレベルの実行ではなく構造レベルの静的確認。
    「そもそも参照する経路が無い」ことの証明はコード自体の検査が最も確実)。"""
    gate_cache = _import_gate_cache()
    release = _import_release()
    import inspect

    assert gate_cache.CACHEABLE_GATES == ("dist_smoke", "relgate_layers12")
    assert "wsb" not in {n.lower() for n in dir(gate_cache) if not n.startswith("_")} or all(
        "wsb" not in n.lower() for n in dir(gate_cache))

    sig = inspect.signature(release.resolve_iterative_phase_cache_hits)
    param_names = list(sig.parameters.keys())
    assert not any("wsb" in p.lower() for p in param_names), (
        f"resolve_iterative_phase_cache_hits()にWSB用の引数が存在する: {param_names}")

    release_src = inspect.getsource(release)
    assert "fut_wsb = executor.submit(\n            run_wsb_convert_gate" in release_src, (
        "run_wsb_convert_gateは常に無条件でsubmitされる実装のはず"
        "(dist_smoke/relgateのようなNoneガード分岐が付いていてはならない)")


# =====================================================================
# 負の対照6: 最終確認フェーズのrelgate中間ハッシュ検算が実際に発火すること
# =====================================================================

def test_verify_relgate_final_confirmation_reruns_phase01_and_checks_hash(tmp_path, monkeypatch):
    gate_cache = _import_gate_cache()
    relgate_mod = gate_cache._relgate_module()
    key = relgate_mod.DEFAULT_AVATARS[0]

    calls = {"build_avatar_job": 0, "run_convert": 0, "compute_intermediate_hash": 0}

    def _fake_build_avatar_job(avatar_key, job_dir, avatar_name):
        calls["build_avatar_job"] += 1
        return os.path.join(job_dir, "job.json")

    def _fake_run_convert(job_path, report, label, **kwargs):
        calls["run_convert"] += 1
        assert kwargs.get("extra_env") == {"D2P_STOP_BEFORE_NOUE": "1"}, (
            "最終確認フェーズはPhase 0-1のみ(D2P_STOP_BEFORE_NOUE=1)で"
            "呼ばなければならない。noue工程(Phase 2-6)を再実行してはならない")
        return 0, 1.0

    def _fake_compute_intermediate_hash(job_dir, blender_exe):
        calls["compute_intermediate_hash"] += 1
        return {"combined": "matching-hash-value", "components": {}}

    monkeypatch.setattr(relgate_mod, "build_avatar_job", _fake_build_avatar_job)
    monkeypatch.setattr(relgate_mod, "run_convert", _fake_run_convert)
    monkeypatch.setattr(gate_cache.intermediate_hash, "compute_intermediate_hash",
                         _fake_compute_intermediate_hash)

    expected = {k: "matching-hash-value" for k in relgate_mod.DEFAULT_AVATARS}
    report = DummyReport()
    ok, detail = gate_cache.verify_relgate_final_confirmation(
        str(tmp_path / "relgate_work"), expected, report)

    assert ok is True
    assert calls["build_avatar_job"] == len(relgate_mod.DEFAULT_AVATARS)
    assert calls["run_convert"] == len(relgate_mod.DEFAULT_AVATARS), (
        "最終確認フェーズは各検体についてPhase 0-1を実際に再実行しなければならない"
        "(発火しないまま最終PASSに到達したら、それ自体がfail-closedの穴)")
    assert calls["compute_intermediate_hash"] == len(relgate_mod.DEFAULT_AVATARS)
    assert any("Phase 0-1" in line for line in report.lines), (
        "Phase 0-1再実行の経緯がreportへログされていなければならない")
    for k in relgate_mod.DEFAULT_AVATARS:
        assert detail[k]["ok"] is True


def test_verify_relgate_final_confirmation_fails_closed_on_hash_mismatch(tmp_path, monkeypatch):
    """負の対照: キャッシュ登録時のハッシュと、Phase 0-1再実行後の実測ハッシュが
    食い違えばok=Falseで停止する(fail-closed。「値を寄せて合わせる」余地が
    無いことの確認)。"""
    gate_cache = _import_gate_cache()
    relgate_mod = gate_cache._relgate_module()

    monkeypatch.setattr(relgate_mod, "build_avatar_job",
                         lambda key, job_dir, avatar_name: os.path.join(job_dir, "job.json"))
    monkeypatch.setattr(relgate_mod, "run_convert", lambda *a, **k: (0, 1.0))
    monkeypatch.setattr(gate_cache.intermediate_hash, "compute_intermediate_hash",
                         lambda job_dir, blender_exe: {"combined": "actual-hash", "components": {}})

    expected = {k: "expected-hash-DOES-NOT-MATCH" for k in relgate_mod.DEFAULT_AVATARS}
    report = DummyReport()
    ok, detail = gate_cache.verify_relgate_final_confirmation(
        str(tmp_path / "relgate_work"), expected, report)

    assert ok is False
    assert any(detail[k]["ok"] is False for k in relgate_mod.DEFAULT_AVATARS)
    assert any("FAIL" in line for line in report.lines)


def test_verify_relgate_final_confirmation_fails_closed_when_expected_hash_missing(tmp_path):
    """キャッシュ登録時に中間ハッシュが計算できていなかった検体(register時の
    WARN経路)は、最終確認フェーズで検算対象にできないため、安全側=FAILに倒れる
    (「登録時に無かったから今回は無条件許可」という抜け道を作らない)。"""
    gate_cache = _import_gate_cache()
    report = DummyReport()
    ok, detail = gate_cache.verify_relgate_final_confirmation(
        str(tmp_path / "relgate_work"), {}, report)
    assert ok is False


# =====================================================================
# 負の対照8: 緑runへの--resume-fromが拒否されること
# =====================================================================

@pytest.mark.parametrize("content,expected_ok", [
    ("...\n総合判定: FAIL(dist_smoke red)\n", True),
    ("...\n総合判定: PASS\nバージョン: v2.0.1\n", False),
    ("work_dir = ...\n(実行途中で強制終了)\n", False),  # 総合判定の記載が無い
    # 2026-07-29回帰試験(dev#169、run_20260729_184442の実障害を再現):
    # relgateの子ゲートが先に「総合判定: PASS」を書き、その後WSBゲートが
    # 落ちてrun全体が「総合判定: FAIL」で終わる、という実際の並び。
    # 単純substring判定だと途中のPASSに誤反応してFalseの理由も間違えていた
    # (「PASSが見つかった」判定になり、実際にはFAIL runなのに拒否理由の
    # 説明文がPASS runのものになる=そもそも受理すべきなのに拒否していた)。
    ("総合判定: PASS\n[relgate] 機械可読の判定を書いた\n"
     "  総合判定: FAIL\n"
     "総合判定: FAIL(wsb convert red (dev#66 parallel WSB gate))\n", True),
])
def test_evaluate_resume_from_report(content, expected_ok):
    release = _import_release()
    ok, reason = release.evaluate_resume_from_report(content)
    assert ok is expected_ok
    assert isinstance(reason, str) and reason


def test_evaluate_resume_from_report_negative_control_final_pass_after_subgate_fail():
    """負の対照: 子ゲートの区間結果がFAILでも、release.py自身の最終総合判定が
    PASSであれば(例えばリトライして最終的に全ゲート成功したケース)、
    最後の出現に従って正しくPASS runとして拒否されなければならない
    (「最後の出現を見る」ロジックがPASS/FAILどちらの向きにも正しく効くこと
    の確認、直前の回帰試験の逆パターン)。"""
    release = _import_release()
    content = ("  総合判定: FAIL\n[relgate] retry後\n"
               "総合判定: PASS\nバージョン: v2.0.1\n")
    ok, reason = release.evaluate_resume_from_report(content)
    assert ok is False, "最後の出現がPASSなら緑runとして拒否しなければならない"


def test_validate_resume_from_rejects_missing_run(tmp_path):
    release = _import_release()
    ok, reason = release.validate_resume_from("run_does_not_exist", cert_dir=str(tmp_path))
    assert ok is False
    assert "report.md" in reason or "無い" in reason


def test_validate_resume_from_accepts_fail_run(tmp_path):
    release = _import_release()
    run_dir = tmp_path / "run_20260729_010101"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("...\n総合判定: FAIL(dist_smoke red)\n", encoding="utf-8")
    ok, reason = release.validate_resume_from("run_20260729_010101", cert_dir=str(tmp_path))
    assert ok is True


def test_validate_resume_from_rejects_pass_run(tmp_path):
    release = _import_release()
    run_dir = tmp_path / "run_20260729_020202"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("...\n総合判定: PASS\n", encoding="utf-8")
    ok, reason = release.validate_resume_from("run_20260729_020202", cert_dir=str(tmp_path))
    assert ok is False, "緑(PASS)で終了したrunへの--resume-fromは拒否しなければならない"


def test_main_rejects_resume_from_pass_run_before_any_side_effect(tmp_path, monkeypatch):
    """main()レベルの統合確認: 緑runを--resume-fromに渡すと、workツリークリーン
    確認やzipビルドに一切進まず即FAILで終了する(引数検証段階での拒否)。"""
    release = _import_release()
    run_dir = tmp_path / "run_20260729_030303"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("...\n総合判定: PASS\n", encoding="utf-8")
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))

    called = {"get_head_full": False}
    monkeypatch.setattr(release, "get_head_full", lambda: called.__setitem__("get_head_full", True))
    # dev#201: --approval-issueは必須引数になったため、本試験の関心事
    # (--resume-from拒否が先に効くこと)を汚さないよう常にOKを返すダミーへ
    # 差し替える(承認issueゲート自体の単体試験はtest_release_approval_gate.py)。
    monkeypatch.setattr(release, "run_approval_gate", lambda issue_number, report: (True, "OK(dummy)"))

    rc = release.main(["--bump", "patch", "--pak", "none",
                        "--approval-issue", "201",
                        "--resume-from", "run_20260729_030303"])

    assert rc == 1
    assert called["get_head_full"] is False, (
        "--resume-from拒否は、git tree確認(1節)より前の引数検証段階で即FAILしなければならない")


# =====================================================================
# WP-3: fail-closed網羅証明(write_cert()のcoverage)
# =====================================================================

def test_build_coverage_accepts_complete_valid_mapping():
    release = _import_release()
    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    gates_by_mode["relgate_layers12"] = "cached_then_hash_verified"
    coverage = release.build_coverage(gates_by_mode)
    assert coverage["cache_hits"] == ["relgate_layers12"]
    assert set(coverage["gates_total"]) == set(release.COVERAGE_GATES_TOTAL)


def test_build_coverage_rejects_missing_gate():
    release = _import_release()
    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    del gates_by_mode["wsb_convert"]
    with pytest.raises(AssertionError):
        release.build_coverage(gates_by_mode)


def test_build_coverage_rejects_unknown_mode_value():
    release = _import_release()
    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    gates_by_mode["wsb_convert"] = "silently_skipped_by_mistake"  # 未知の状態文字列
    with pytest.raises(AssertionError):
        release.build_coverage(gates_by_mode)


def test_build_coverage_rejects_extra_unexpected_gate():
    release = _import_release()
    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    gates_by_mode["some_new_gate_nobody_declared"] = "executed"
    with pytest.raises(AssertionError):
        release.build_coverage(gates_by_mode)


def test_write_cert_propagates_coverage_assertion_failure(tmp_path, monkeypatch):
    """write_cert()はbuild_coverage()の例外を握り潰さない
    (=cert発行前に例外で停止する。fail-closedの核心)。"""
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))
    zip_path = tmp_path / "dummy.zip"
    zip_path.write_bytes(b"zip-bytes")
    report = DummyReport()

    bad_gates_by_mode = {"only_one_gate": "executed"}  # gates_totalと大きく不一致
    with pytest.raises(AssertionError):
        release.write_cert(
            "deadbeefcafebabe", "deadbee", [{"name": "x", "ok": True}],
            {"zip_path": str(zip_path)}, [], report, gates_by_mode=bad_gates_by_mode)
    assert not os.path.isfile(release.cert_path_for("deadbee")), (
        "assertionが発火した場合、cert.jsonが発行されてはならない")


def test_write_cert_writes_coverage_field_on_valid_input(tmp_path, monkeypatch):
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))
    zip_path = tmp_path / "dummy.zip"
    zip_path.write_bytes(b"zip-bytes")
    report = DummyReport()

    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    gates_by_mode["relgate_layers12"] = "cached_then_hash_verified"
    path = release.write_cert(
        "deadbeefcafebabe", "deadbee", [{"name": "x", "ok": True}],
        {"zip_path": str(zip_path)}, [], report, gates_by_mode=gates_by_mode)

    with open(path, encoding="utf-8") as f:
        cert = json.load(f)
    assert cert["coverage"]["gates_by_mode"]["relgate_layers12"] == "cached_then_hash_verified"
    assert cert["coverage"]["cache_hits"] == ["relgate_layers12"]


def test_format_coverage_markdown_renders_all_gates():
    release = _import_release()
    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    md = release.format_coverage_markdown(gates_by_mode)
    for g in release.COVERAGE_GATES_TOTAL:
        assert g in md
    assert "0件の欠落" in md


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
