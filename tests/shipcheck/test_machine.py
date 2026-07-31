# -*- coding: utf-8 -*-
"""ゲートE(起動NOT_CRASHED)・F(実プレイ開始)。実機接触を伴うため@machine。

既定では--allow-machineが無いと全てSKIPする(gameフィクスチャが安全弁)。
本セッション(U32構築時)はこのマーカーのテストを実行しない
(docs\\U32_SONNET_INSTRUCTIONS.md 並列注意節)。
"""
import os

import pytest

import gates

pytestmark = pytest.mark.machine

ASSETS_TMPL = os.path.join(gates.DEVTOOLS_DIR, "assets_tmpl")
WORLD_TEMPLATES = {
    "modtest": os.path.join(ASSETS_TMPL, "row_modtest.png"),
    "panworld": os.path.join(ASSETS_TMPL, "row_panwarudo2.png"),
}


@pytest.fixture
def built_pak(pak_for, avatar, job_path):
    result = pak_for(avatar, job_path)
    if not (result.pak_path and os.path.isfile(result.pak_path)):
        pytest.skip("pakが無い(offlineゲート未実施 or 変換禁止)")
    return result.pak_path


def test_gate_e_crash(built_pak, game, avatar, recorder):
    import crash_test as ct
    import apply_test_pak as atp
    with game(built_pak):
        gr = gates.gate_e_crash(ct, built_pak, atp.default_paks_dir())  # WP16: 自動探索
    recorder.record(gr, avatar=avatar, case="machine")
    if gr.status == "SKIP":
        pytest.skip(str(gr.detail))
    assert gr.ok, gr.detail


def test_gate_f_play_start(built_pak, game, avatar, recorder, repeat_count, world_name,
                            shots_dir, save_guard):
    import play_start_test as pst
    world_template = WORLD_TEMPLATES.get(world_name)
    if not world_template or not os.path.isfile(world_template):
        pytest.skip("ワールド行テンプレートが無い: {} ({})".format(world_name, world_template))
    avatar_shot_dir = os.path.join(shots_dir, avatar)
    os.makedirs(avatar_shot_dir, exist_ok=True)
    with save_guard():
        with game(built_pak):
            gr = gates.gate_f_playstart(pst, built_pak, repeat=repeat_count,
                                         world_template=world_template, shot_dir=avatar_shot_dir)
    recorder.record(gr, avatar=avatar, case="machine")
    if gr.status == "SKIP":
        pytest.skip(str(gr.detail))
    assert gr.ok, gr.detail
