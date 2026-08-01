# test_diagnostics.py -- WP-A6受入条件: compat_check.py / path_health.py /
# update_check.py の単体試験(DESIGN.md §5.2 WP-A6行)。
#
# 既存C#セルフチェック(app\DiveToPalworld.cs、隠しCLI --check-palworld-compat /
# --check-path-health / --check-work-root-fallback)のケース表を1:1で移植した
# ものが大半(各テストのdocstring/コメントに対応するC#側のcase番号・行番号を
# 記載)。update_check.pyの版比較ロジック(IsNewerVersion系)、および起動時
# セルフチェック(path_health.check_runtime_environment、C#に前例のない
# dev#532新規要件)はWP-A6で新規に設計したためC#対応ケースは無い。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import compat_check as cc  # noqa: E402
import path_health as ph  # noqa: E402
import update_check as uc  # noqa: E402

BUNDLED_JSON = (
    '{"known_versions":[{"build_id":"111","pak_size":1000,"label":"1.0.1"}],'
    '"known_vanilla_manifest_sha256":["aaaa"]}'
)


# ===========================================================================
# compat_check.py -- CheckPalworldCompatLogic (app\DiveToPalworld.cs L.5414-5531)
# のケース1-9を移植。case10(JsonObj balanced-brace extraction)は、Python版が
# 標準jsonモジュールを使うため該当ロジックが存在せず対象外(compat_check.pyの
# モジュールdocstring参照)。
# ===========================================================================


def test_case1_known_version_no_warn():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    st = cc.evaluate(known, det, None)
    assert st.detected and st.known_version and not st.should_warn


def test_case2_remote_only_known_version_merges_additively():
    remote = '{"known_versions":[{"build_id":"222","pak_size":2000,"label":"1.0.2"}]}'
    known = cc.merge_known_good(BUNDLED_JSON, remote)
    det = cc.PalworldDetection(detected=True, build_id="222", pak_size=2000)
    st = cc.evaluate(known, det, None)
    assert st.known_version and not st.should_warn
    assert cc.is_known_version(known, "111", 1000)  # merge is additive, not replace


def test_case3_unknown_version_known_manifest_no_warn():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    st = cc.evaluate(known, det, "aaaa")
    assert st.manifest_available and st.known_manifest and not st.should_warn


def test_case4_negative_unknown_version_and_manifest_mismatch_warns():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    st = cc.evaluate(known, det, "zzzz")
    assert st.should_warn and st.manifest_available and not st.known_manifest


def test_case5_manifest_not_available_yet_warns():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    st = cc.evaluate(known, det, None)
    assert st.should_warn and not st.manifest_available


def test_case6_undetectable_no_warn():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=False)
    st = cc.evaluate(known, det, None)
    assert not st.detected and not st.should_warn


def test_case7_offline_fallback_bundled_only():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    assert len(known.versions) == 1
    assert len(known.manifest_hashes) == 1


def test_case8_negative_bundled_list_emptied_offline_warns():
    known = cc.merge_known_good('{"known_versions":[],"known_vanilla_manifest_sha256":[]}', None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    st = cc.evaluate(known, det, None)
    assert st.should_warn


def test_case9_log_line_not_found():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=False)
    st = cc.evaluate(known, det, None)
    line = cc.build_log_line(known, st)
    assert line.startswith("palworld: not found")
    assert "111" in line


def test_case9_log_line_known_version():
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    st = cc.evaluate(known, det, None)
    line = cc.build_log_line(known, st)
    assert "111" in line and "1.0.1" in line


def test_negative_control_other_pak_filename_never_leaks_and_case2_dummy_absent():
    # compat_checkの範囲外(伏字化はpak_manager.py/inquiry.pyの担当)だが、
    # merge_known_goodが元のJSON断片を素通しせず構造化データへ変換している
    # (=任意の追加フィールドが後段へ漏れない)ことの確認を兼ねる
    known = cc.merge_known_good(BUNDLED_JSON, None)
    assert cc.supported_labels_joined(known) == "1.0.1"


# ===========================================================================
# path_health.py -- CheckPathHealthLogic (app\DiveToPalworld.cs L.5678-5754)
# のケース1-7を移植。
# ===========================================================================


def test_pathhealth_case1_healthy_path_no_problem():
    f = ph.build_path_facts("install", r"C:\P\Work\DiveToPalworld", None)
    assert not ph.path_health_problem(f)
    assert not f.non_ascii
    assert not f.unc
    assert not f.under_onedrive


def test_pathhealth_case2_negative_too_long_flags_and_logs_length():
    long_path = "C:\\" + ("a" * 220)
    f = ph.build_path_facts("install", long_path, None)
    assert ph.path_health_problem(f)
    line = ph.path_health_line(f)
    assert str(len(long_path)) in line


def test_pathhealth_case3_boundary_length_not_flagged():
    at_threshold = "C:\\" + ("a" * (ph.PATH_LENGTH_WARN_THRESHOLD - 4))
    f = ph.build_path_facts("boundary", at_threshold, None)
    assert not ph.path_health_problem(f)


def test_pathhealth_case4_unc_always_problem():
    f = ph.build_path_facts("unc", r"\\server\share\short", None)
    assert ph.path_health_problem(f)


def test_pathhealth_case5_onedrive_detection_and_negative_controls():
    onedrive = r"C:\Users\someone\OneDrive"
    under = ph.build_path_facts("work", onedrive + r"\DiveToPalworld\work", onedrive)
    assert ph.path_health_problem(under)

    outside = ph.build_path_facts("work", r"C:\DiveToPalworld\work", onedrive)
    assert not ph.path_health_problem(outside)

    no_root_known = ph.build_path_facts("work", onedrive + r"\DiveToPalworld\work", None)
    assert not ph.path_health_problem(no_root_known)


def test_pathhealth_case6_non_ascii_noted_but_not_a_problem():
    f = ph.build_path_facts("install", "C:\\Users\\\u3071\u3093\\DiveToPalworld", None)
    assert f.non_ascii
    assert not ph.path_health_problem(f)
    assert "non-ASCII" in ph.path_health_line(f)


def test_pathhealth_case7_empty_path_is_safe():
    f = ph.build_path_facts("install", None, None)
    assert not ph.path_health_problem(f)
    assert f.length == 0


# ===========================================================================
# path_health.py -- CheckWorkRootFallbackLogic (app\DiveToPalworld.cs
# L.5804-5873) のケース1-5を移植。
# ===========================================================================


def test_workroot_case1_primary_writable_fallback_not_probed():
    probed = {"fallback": False}

    def probe(p):
        if p == "C:\\fallback":
            probed["fallback"] = True
        return None

    res = ph.resolve_work_root("C:\\primary", "C:\\fallback", probe)
    assert not res.used_fallback
    assert not res.failed
    assert res.path == "C:\\primary"
    assert not probed["fallback"]


def test_workroot_case2_negative_primary_unwritable_falls_back():
    def probe(p):
        return (
            "UnauthorizedAccessException: Access to the path is denied."
            if p.startswith("C:\\Program Files")
            else None
        )

    res = ph.resolve_work_root(
        "C:\\Program Files\\Uchinoko_for_Palworld\\work", "C:\\fallback", probe
    )
    assert res.used_fallback
    assert not res.failed
    assert res.path == "C:\\fallback"
    assert res.primary_error is not None and "denied" in res.primary_error.lower()


def test_workroot_case3_negative_both_unwritable_fails_safely():
    res = ph.resolve_work_root("C:\\primary", "C:\\fallback", lambda p: "Access is denied")
    assert res.failed
    assert res.primary_error is not None
    assert res.fallback_error is not None
    assert res.path  # never empty/None even on failure


def test_workroot_case4_real_io_writable_dir_self_cleans(tmp_path):
    real_dir = tmp_path / "real_writable_probe"
    err = ph.probe_work_root_writable(str(real_dir))
    assert err is None
    assert real_dir.is_dir()
    assert list(real_dir.iterdir()) == []  # probe must not leave stray files


def test_workroot_case5_negative_nonexistent_drive_fails(tmp_path):
    if os.path.exists("Z:\\"):
        return  # 実在するドライブだと偽陽性になるので実在しない時だけ検査(C#側と同じ)
    err = ph.probe_work_root_writable("Z:\\__d2p_nonexistent_drive_probe__\\work")
    assert err is not None


# ===========================================================================
# update_check.py -- IsNewerVersion/ParseVersion (app\DiveToPalworld.cs
# L.3552-3586) のロジックを移植。C#に単体表(隠しCLI)は無いため、コメントで
# 明記されている実測仕様(vプレフィックス吸収・足りない桁は0扱い・プレ
# リリース表記考慮不要)をケース化した。
# ===========================================================================


def test_version_latest_newer_with_v_prefix_mismatch():
    # "latest"はvプレフィックス無し、ToolVersionはプレフィックス有り(実測差、L.3548)
    assert uc.is_newer_version("2.2.14", "v2.2.13")


def test_version_same_is_not_newer():
    assert not uc.is_newer_version("2.2.13", "v2.2.13")


def test_version_older_is_not_newer():
    assert not uc.is_newer_version("2.2.12", "v2.2.13")


def test_version_missing_minor_digits_treated_as_zero():
    assert uc.is_newer_version("v3", "v2.9.9")
    assert not uc.is_newer_version("v2", "v2.0.1")


def test_version_unparseable_is_never_newer():
    assert not uc.is_newer_version("not-a-version", "v2.2.13")
    assert not uc.is_newer_version("v2.2.13", "not-a-version")
    assert not uc.is_newer_version(None, "v2.2.13")


def test_update_check_json_mocked_has_update():
    result = uc.evaluate_update_json('{"latest":"2.2.14"}', "v2.2.13")
    assert result.has_update
    assert result.latest_version == "2.2.14"
    assert result.display_version == "v2.2.14"


def test_update_check_json_mocked_no_update_when_same_version():
    result = uc.evaluate_update_json('{"latest":"2.2.13"}', "v2.2.13")
    assert not result.has_update


def test_update_check_json_extracts_palworld_known_good_independent_of_latest():
    # dev#89: "latest"が無い/更新なしでも"palworld_known_good"は独立に拾える
    # (compat_check.merge_known_good へそのまま渡せるJSON文字列になっている)
    json_text = (
        '{"latest":"2.2.13","palworld_known_good":{"known_versions":'
        '[{"build_id":"1","pak_size":1,"label":"a"},'
        '{"build_id":"2","pak_size":2,"label":"b"}],'
        '"known_vanilla_manifest_sha256":["h1","h2"]}}'
    )
    result = uc.evaluate_update_json(json_text, "v2.2.13")
    assert not result.has_update  # same version, no notice
    assert result.remote_known_good_json is not None
    known = cc.merge_known_good(BUNDLED_JSON, result.remote_known_good_json)
    # 同梱1件+リモート2件が重複なく足し込まれる(nested object extraction、旧case10の趣旨)
    assert len(known.versions) == 3
    assert len(known.manifest_hashes) == 3


def test_update_check_malformed_json_is_silent_no_update():
    assert not uc.evaluate_update_json("not json at all", "v2.2.13").has_update
    assert not uc.evaluate_update_json("", "v2.2.13").has_update
    assert not uc.evaluate_update_json(None, "v2.2.13").has_update


def test_check_for_update_uses_injected_fetch_no_network():
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return '{"latest":"9.9.9"}'

    result = uc.check_for_update("v1.0.0", fetch=fake_fetch)
    assert result.has_update
    assert result.display_version == "v9.9.9"
    assert calls["n"] == 1


def test_check_for_update_fetch_failure_is_silent():
    def failing_fetch():
        raise OSError("offline")

    result = uc.check_for_update("v1.0.0", fetch=failing_fetch)
    assert not result.has_update


# ===========================================================================
# path_health.py -- 起動時セルフチェック(dev#532「環境隔離4層」の④、
# C#に前例なし・WP-A6新規設計)。sys.executableがアプリ配下か+同梱バージョン
# 一致かを検査し、不一致ならUchinoko.bat経由の起動を促す。
# ===========================================================================


def test_runtime_env_ok_when_executable_under_app_root_and_version_matches():
    app_root = r"C:\Uchinoko"
    status = ph.check_runtime_environment(
        sys_executable=r"C:\Uchinoko\python_embed\python.exe",
        app_root=app_root,
        bundled_version="v2.2.14",
        expected_version="v2.2.14",
    )
    assert status.ok
    assert ph.runtime_environment_message(status) is None


def test_runtime_env_negative_executable_outside_app_root():
    status = ph.check_runtime_environment(
        sys_executable=r"C:\Python313\python.exe",
        app_root=r"C:\Uchinoko",
        bundled_version="v2.2.14",
        expected_version="v2.2.14",
    )
    assert not status.executable_ok
    assert not status.ok
    assert ph.runtime_environment_message(status) == ph.MSG_LAUNCH_VIA_BAT


def test_runtime_env_negative_version_mismatch():
    status = ph.check_runtime_environment(
        sys_executable=r"C:\Uchinoko\python_embed\python.exe",
        app_root=r"C:\Uchinoko",
        bundled_version="v2.2.13",
        expected_version="v2.2.14",
    )
    assert status.executable_ok
    assert not status.version_ok
    assert not status.ok


def test_runtime_env_similar_prefix_is_not_falsely_treated_as_under_app_root():
    # "C:\Uchinoko2" は "C:\Uchinoko" の文字列プレフィックスだが別ディレクトリ
    # なので、区切り文字を跨がない誤検知が無いことを確認する
    status = ph.check_runtime_environment(
        sys_executable=r"C:\Uchinoko2\python.exe",
        app_root=r"C:\Uchinoko",
    )
    assert not status.executable_ok


def test_runtime_env_missing_info_fails_open():
    # 判定不能(情報が渡ってこない)なら黙って動く(PathHealthLogic case6/7と
    # 同じ安全側の方針)。バージョン情報が片方だけ無い場合も同様
    assert ph.check_runtime_environment(None, None).ok
    status = ph.check_runtime_environment(
        r"C:\Uchinoko\python_embed\python.exe", r"C:\Uchinoko", bundled_version=None,
        expected_version="v2.2.14",
    )
    assert status.version_ok
