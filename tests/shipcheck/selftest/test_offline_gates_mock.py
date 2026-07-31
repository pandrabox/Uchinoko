# -*- coding: utf-8 -*-
"""G1-a: ゲートA〜D+static_checkのPASS/FAILシナリオをモックで検証する。
実機・変換・実pak不要(gates.pyの関数を直接呼ぶだけ)。
"""
import os

import gates


def _fake_build_result(cache_hit=False, exit_code=0, pak_path=None, log_text=""):
    return gates.PakBuildResult(
        avatar="fake", job_path="fake/job.json", job_dict={}, cache_hit=cache_hit,
        exit_code=exit_code, pak_path=pak_path, log_text=log_text,
    )


# --- ゲートA ---

def test_gate_a_cache_hit_is_pass():
    r = _fake_build_result(cache_hit=True, exit_code=None)
    gr = gates.gate_a_convert_exit0(r)
    assert gr.status == "PASS"


def test_gate_a_exit0_is_pass():
    r = _fake_build_result(exit_code=0)
    assert gates.gate_a_convert_exit0(r).status == "PASS"


def test_gate_a_nonzero_exit_is_fail():
    r = _fake_build_result(exit_code=1, log_text="Write-Error: 何か失敗した")
    gr = gates.gate_a_convert_exit0(r)
    assert gr.status == "FAIL"
    assert "何か失敗した" in gr.detail["log_tail"]


# --- ゲートB ---

def test_gate_b_pak_exists_pass(tmp_path):
    pak = tmp_path / "Avatar_PlayerSwap_P.pak"
    pak.write_bytes(b"dummy")
    r = _fake_build_result(pak_path=str(pak))
    gr = gates.gate_b_pak_exists(r)
    assert gr.status == "PASS"
    assert gr.detail["sha1"] is None or isinstance(gr.detail.get("sha1"), (str, type(None)))


def test_gate_b_pak_missing_is_fail():
    r = _fake_build_result(pak_path=None)
    assert gates.gate_b_pak_exists(r).status == "FAIL"


def test_gate_b_pak_path_recorded_but_deleted_is_fail(tmp_path):
    pak = tmp_path / "gone.pak"
    r = _fake_build_result(pak_path=str(pak))  # 作らない = 存在しない
    assert gates.gate_b_pak_exists(r).status == "FAIL"


# --- ゲートC(preflight 9/9) ---

def _preflight_log(fail_gates=()):
    lines = []
    for i in range(1, 10):
        name = "G{}".format(i)
        if name in fail_gates:
            lines.append("  [FAIL] {} 何かの検査 — 詳細".format(name))
        else:
            lines.append("  [PASS] {} 何かの検査".format(name))
    return "\n".join(lines)


def test_gate_c_all_9_pass():
    gr = gates.gate_c_preflight_from_log(_preflight_log())
    assert gr.status == "PASS"
    assert gr.detail["passed"] == 9


def test_gate_c_one_fail_is_fail():
    gr = gates.gate_c_preflight_from_log(_preflight_log(fail_gates=("G4",)))
    assert gr.status == "FAIL"
    assert "G4" in "".join(gr.detail["failed"])


def test_gate_c_no_log_lines_is_skip():
    gr = gates.gate_c_preflight_from_log("何も関係ないログ本文")
    assert gr.status == "SKIP"


# --- ゲートD(noue出自証跡) ---

def test_gate_d_no_fingerprints_is_pass(tmp_path):
    build_dir = tmp_path / "build"
    (build_dir / "logs").mkdir(parents=True)
    # 何もUE指紋を置かない
    gr = gates.gate_d_noue_provenance(str(build_dir))
    assert gr.status == "PASS"


def test_gate_d_step03_log_present_is_fail(tmp_path):
    build_dir = tmp_path / "build"
    (build_dir / "logs").mkdir(parents=True)
    (build_dir / "logs" / "step03_export_fbx.log").write_text("dummy", encoding="utf-8")
    gr = gates.gate_d_noue_provenance(str(build_dir))
    assert gr.status == "FAIL"
    assert os.path.join("logs", "step03_export_fbx.log") in gr.detail["found_ue_fingerprints"]


def test_gate_d_cook_log_without_automationtool_is_pass(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "cook.log").write_text("普通のnoueビルドログ、UE要素なし", encoding="utf-8")
    gr = gates.gate_d_noue_provenance(str(build_dir))
    assert gr.status == "PASS"


def test_gate_d_cook_log_with_automationtool_is_fail(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "cook.log").write_text("... Running AutomationTool ...", encoding="utf-8")
    gr = gates.gate_d_noue_provenance(str(build_dir))
    assert gr.status == "FAIL"
    assert "cook.log" in gr.detail["found_ue_fingerprints"]


def test_gate_d_windows_folder_present_is_fail(tmp_path):
    build_dir = tmp_path / "build"
    (build_dir / "Windows").mkdir(parents=True)
    gr = gates.gate_d_noue_provenance(str(build_dir))
    assert gr.status == "FAIL"
    assert "Windows" in gr.detail["found_ue_fingerprints"]


# --- static_check(u26_static_checkのモック) ---

class _FakeRow:
    pass


def _install_fake_static_check(monkeypatch, rows):
    import u26_static_check as usc

    def fake_collect_targets(job_dir):
        return [(r["label"], "built.uasset", "built.uexp", "tmpl.uasset", "tmpl.uexp",
                  r.get("is_sk", False)) for r in rows]

    def fake_check_one(label, uasset_path, uexp_path, is_sk):
        for r in rows:
            if label.startswith(r["label"]):
                return r["built"]
        return {"missing": True}

    monkeypatch.setattr(usc, "collect_targets", fake_collect_targets)
    monkeypatch.setattr(usc, "check_one", fake_check_one)


def test_static_check_all_healthy_is_pass(monkeypatch):
    rows = [
        {"label": "outfit:a", "is_sk": True,
         "built": {"header_consistent": True, "verify_ok": True, "sk_tri_match": True, "sk_vtx_match": True}},
        {"label": "material:m0", "is_sk": False,
         "built": {"header_consistent": True, "verify_ok": True}},
    ]
    _install_fake_static_check(monkeypatch, rows)
    gr = gates.gate_static_check("dummy_job_dir")
    assert gr.status == "PASS", gr.detail


def test_static_check_header_inconsistent_is_fail(monkeypatch):
    rows = [
        {"label": "outfit:a", "is_sk": True,
         "built": {"header_consistent": False, "verify_ok": True, "sk_tri_match": True, "sk_vtx_match": True}},
    ]
    _install_fake_static_check(monkeypatch, rows)
    gr = gates.gate_static_check("dummy_job_dir")
    assert gr.status == "FAIL"
    assert gr.detail["n_problems"] == 1


def test_static_check_excluded_label_is_skipped_from_evaluation(monkeypatch):
    rows = [
        {"label": "outfit:Kigurumi001_v02", "is_sk": True,
         "built": {"header_consistent": False, "verify_ok": False}},
        {"label": "outfit:healthy", "is_sk": True,
         "built": {"header_consistent": True, "verify_ok": True, "sk_tri_match": True, "sk_vtx_match": True}},
    ]
    _install_fake_static_check(monkeypatch, rows)
    gr = gates.gate_static_check("dummy_job_dir", exclude_label_substrings=("Kigurumi001",))
    assert gr.status == "PASS", gr.detail
    assert gr.detail["n_checked"] == 1


def test_static_check_no_targets_is_skip(monkeypatch):
    _install_fake_static_check(monkeypatch, [])
    gr = gates.gate_static_check("dummy_job_dir")
    assert gr.status == "SKIP"


# --- H1: 設定配線ゲート ---

def test_h1_zero_diff_is_fail():
    same_hashes = {"a": "h1", "b": "h2"}

    def hasher(path):
        return dict(same_hashes)

    gr = gates.gate_h1_wiring("baseline.pak", "flip.pak", ["MainShader/"], entry_hasher=hasher)
    assert gr.status == "FAIL"
    assert "差分ゼロ" in gr.detail["note"]


def test_h1_diff_in_expected_category_is_pass():
    def hasher(path):
        if path == "baseline.pak":
            return {"Player/ModelMaterials/MainShader/M_VP_m00.uexp": "h1", "unrelated": "x"}
        return {"Player/ModelMaterials/MainShader/M_VP_m00.uexp": "h1_changed", "unrelated": "x"}

    gr = gates.gate_h1_wiring("baseline.pak", "flip.pak",
                               ["ModelMaterials/MainShader/"], entry_hasher=hasher)
    assert gr.status == "PASS", gr.detail
    assert gr.detail["diff_count"] == 1


def test_h1_diff_outside_expected_category_is_fail():
    def hasher(path):
        if path == "baseline.pak":
            return {"Player/Hair/SomeHair.uexp": "h1"}
        return {"Player/Hair/SomeHair.uexp": "h1_changed"}

    # 期待カテゴリはMainShaderなのに実際の差分はHairにしか出ていない
    gr = gates.gate_h1_wiring("baseline.pak", "flip.pak",
                               ["ModelMaterials/MainShader/"], entry_hasher=hasher)
    assert gr.status == "FAIL"
    assert gr.detail["matched_expected_category"] is False
