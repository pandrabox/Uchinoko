# -*- coding: utf-8 -*-
"""G1: ①全ゲートPASSシナリオ、②各ゲートFAILシナリオ(A失敗/Eクラッシュ/H1差分
ゼロ/checker検出等)を一括で通し確認する統合テスト。個々の分岐の詳細は
test_offline_gates_mock.py/test_machine_gates_mock.py/test_visual_gates_mock.py
が担当するので、ここでは「一連の流れとして全部PASSになる/ならない」ことだけを見る。
"""
import gates


def _build_result_ok(tmp_path):
    build_dir = tmp_path / "build"
    (build_dir / "logs").mkdir(parents=True)
    pak = build_dir / "Fake_PlayerSwap_P.pak"
    pak.write_bytes(b"dummy pak")
    log_text = "  [PASS] G1 x\n" * 9
    return gates.PakBuildResult(
        avatar="fake", job_path="fake.job.json", job_dict={}, cache_hit=False,
        exit_code=0, pak_path=str(pak), sha1=gates.sha1_file(str(pak)),
        build_dir=str(build_dir), log_text=log_text,
    )


class _AllOkCrashTest:
    def run(self, selector, paks_dir, wait_seconds, out=None, force=False, auto_close=False):
        return 0


class _AllOkPlayStart:
    def run(self, pak_ref, **kw):
        return 0


def test_all_pass_scenario(tmp_path, monkeypatch):
    build_result = _build_result_ok(tmp_path)

    results = [
        gates.gate_a_convert_exit0(build_result),
        gates.gate_b_pak_exists(build_result),
        gates.gate_c_preflight_from_log(build_result.log_text),
        gates.gate_d_noue_provenance(build_result.build_dir),
    ]

    import u26_static_check as usc
    monkeypatch.setattr(usc, "collect_targets", lambda job_dir: [
        ("outfit:a", "u", "e", "tu", "te", True)])
    monkeypatch.setattr(usc, "check_one", lambda label, ua, ue, is_sk: {
        "header_consistent": True, "verify_ok": True, "sk_tri_match": True, "sk_vtx_match": True})
    results.append(gates.gate_static_check(build_result.build_dir))

    def same_hash_diff(path):
        if "baseline" in path:
            return {"ModelMaterials/MainShader/M_VP_m00.uexp": "a"}
        return {"ModelMaterials/MainShader/M_VP_m00.uexp": "b"}
    results.append(gates.gate_h1_wiring("baseline.pak", "flip.pak",
                                         ["ModelMaterials/MainShader/"], entry_hasher=same_hash_diff))

    results.append(gates.gate_e_crash(_AllOkCrashTest(), "dummy.pak", r"C:\fake"))
    results.append(gates.gate_f_playstart(_AllOkPlayStart(), "dummy.pak", repeat=1))
    results.append(gates.gate_g_checker("dummy.png", checker_fn=lambda p: {"checker_present": False}))
    # gate_g_compareはファイル実在チェックの分岐がありtest_visual_gates_mock.pyで
    # 個別検証済みのため、この一括シナリオでは対象外(checker系のみで代表させる)。

    for r in results:
        assert r.status == "PASS", "{}: {}".format(r.name, r.detail)


class _CrashingCrashTest:
    def run(self, selector, paks_dir, wait_seconds, out=None, force=False, auto_close=False):
        if out is not None:
            out.write("crashed, evidence saved to C:\\dummy\\dest\n")
        return 2


def test_per_gate_fail_scenario_a():
    r = gates.PakBuildResult(avatar="fake", job_path="x", job_dict={}, cache_hit=False,
                              exit_code=1, log_text="Write-Error: 変換失敗")
    gr = gates.gate_a_convert_exit0(r)
    assert gr.status == "FAIL"


def test_per_gate_fail_scenario_e_crash():
    gr = gates.gate_e_crash(_CrashingCrashTest(), "dummy.pak", r"C:\fake")
    assert gr.status == "FAIL"
    assert "crashed" in gr.detail["log"]


def test_per_gate_fail_scenario_h1_zero_diff():
    gr = gates.gate_h1_wiring("baseline.pak", "flip.pak", ["MainShader/"],
                               entry_hasher=lambda p: {"a": "same"})
    assert gr.status == "FAIL"


def test_per_gate_fail_scenario_checker_detected():
    gr = gates.gate_g_checker("dummy.png", checker_fn=lambda p: {"checker_present": True})
    assert gr.status == "FAIL"
