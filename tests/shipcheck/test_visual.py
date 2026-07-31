# -*- coding: utf-8 -*-
"""ゲートG(見た目AI一次照合)。advisory — FAILでもスイート全体を止めない
(docs\\U32_SONNET_INSTRUCTIONS.md 4-3節)。判定不能(参照/クロップ不在・CLI不在)
はSKIPとして記録し、判定できた場合のみPASS/FAILを記録する。FAILは
`assert`せず警告として記録するに留める(最終合否は人間がコンタクトシートで行う)。
"""
import glob
import os

import pytest

import gates

pytestmark = pytest.mark.visual


def _find_latest_crop(shot_dir, avatar):
    pattern = os.path.join(shot_dir, avatar, "*_crop.png")
    hits = sorted(glob.glob(pattern), key=os.path.getmtime)
    return hits[-1] if hits else None


def _find_reference(avatar):
    p = os.path.join(gates.REPO_ROOT, "work", avatar, "converted", "preview_male_stand.png")
    return p if os.path.isfile(p) else None


def test_gate_g_checker(avatar, shots_dir, recorder):
    crop = _find_latest_crop(shots_dir, avatar)
    if not crop:
        pytest.skip("ゲート実プレイのクロップSSが無い(ゲートF未実施)")
    gr = recorder.record(gates.gate_g_checker(crop), avatar=avatar, case="visual")
    if gr.status == "SKIP":
        pytest.skip(str(gr.detail))
    if not gr.ok:
        print("[advisory FAIL] G_checker: {}".format(gr.detail))


def test_gate_g_compare_avatar(avatar, shots_dir, recorder):
    crop = _find_latest_crop(shots_dir, avatar)
    ref = _find_reference(avatar)
    if not crop or not ref:
        pytest.skip("クロップSS({})またはBlender参照({})が無い".format(bool(crop), bool(ref)))
    import compare_avatar as ca
    gr = recorder.record(gates.gate_g_compare(crop, ref, ca.compare), avatar=avatar, case="visual")
    if gr.status == "SKIP":
        pytest.skip(str(gr.detail))
    if not gr.ok:
        print("[advisory FAIL] G_compare_avatar: {}".format(gr.detail))
