# -*- coding: utf-8 -*-
"""ゲートA〜D(変換・pak存在・preflight 9/9・noue出自)+静的構造検査+H1(設定配線)。

実機・変換には触れない(pak_forフィクスチャがキャッシュ必須。--allow-convert
指定時のみ実変換する。既定はキャッシュ不成立でSKIP — docs\\U32_SONNET_
INSTRUCTIONS.md 並列注意節)。
"""
import os

import pytest

import cases
import gates


@pytest.fixture
def build_result(pak_for, avatar, job_path):
    return pak_for(avatar, job_path)


def test_gate_a_convert_exit0(build_result, avatar, recorder):
    gr = recorder.record(gates.gate_a_convert_exit0(build_result), avatar=avatar, case="offline")
    if gr.status == "SKIP":
        pytest.skip(str(gr.detail))
    assert gr.ok, gr.detail


def test_gate_b_pak_exists(build_result, avatar, recorder):
    gr = recorder.record(gates.gate_b_pak_exists(build_result), avatar=avatar, case="offline")
    assert gr.ok, gr.detail


def test_gate_c_preflight_9of9(build_result, avatar, recorder):
    gr = recorder.record(gates.gate_c_preflight_from_log(build_result.log_text),
                          avatar=avatar, case="offline")
    if gr.status == "SKIP":
        pytest.skip(str(gr.detail))
    assert gr.ok, gr.detail


def test_gate_d_noue_provenance(build_result, avatar, recorder):
    if not build_result.build_dir or not os.path.isdir(build_result.build_dir):
        pytest.skip("build_dirが無い(pak未生成)")
    gr = recorder.record(gates.gate_d_noue_provenance(build_result.build_dir),
                          avatar=avatar, case="offline")
    assert gr.ok, gr.detail


def test_gate_static_check(build_result, avatar, recorder):
    if not build_result.build_dir or not os.path.isdir(build_result.build_dir):
        pytest.skip("build_dirが無い(pak未生成)")
    # u26_static_check.collect_targets(job_dir)は内部でjob_dir/buildを自分で組み立てる
    # (devtools\u26_static_check.py参照)。build_dir自体ではなくその親(job_dir)を渡す。
    job_dir = os.path.dirname(build_result.build_dir)
    gr = recorder.record(gates.gate_static_check(job_dir),
                          avatar=avatar, case="offline")
    if gr.status == "SKIP":
        pytest.skip(str(gr.detail))
    assert gr.ok, gr.detail


# --- H1: 設定配線ゲート(settings wiring) -------------------------------------
# ベースライン(toto)と各設定フリップを比較する。avatarパラメトライズとは独立
# (常にSETTINGS_BASELINE_AVATARを基準に取るため、avatarフィクスチャは使わない)。

@pytest.fixture(params=cases.SETTINGS_FLIPS, ids=[f["name"] for f in cases.SETTINGS_FLIPS])
def settings_flip(request):
    return request.param


def test_gate_h1_settings_wiring(pak_for, settings_flip, recorder):
    baseline_avatar = cases.SETTINGS_BASELINE_AVATAR
    job_path_ = os.path.join(gates.REPO_ROOT, "work", baseline_avatar, "job.json")
    if not os.path.isfile(job_path_):
        pytest.skip("ベースラインjob.jsonが無い: {}".format(job_path_))

    baseline = pak_for(baseline_avatar, job_path_)
    flipped = pak_for(baseline_avatar + "_cfg_" + settings_flip["name"], job_path_,
                       overrides=settings_flip["overrides"])

    if not (baseline.pak_path and flipped.pak_path):
        pytest.skip("baseline/flip いずれかのpakが無い(未変換)")

    gr = recorder.record(
        gates.gate_h1_wiring(baseline.pak_path, flipped.pak_path,
                              settings_flip["expected_diff_categories"]),
        avatar=baseline_avatar, case="settings:" + settings_flip["name"],
    )
    assert gr.ok, gr.detail
