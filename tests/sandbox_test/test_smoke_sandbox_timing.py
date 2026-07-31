# -*- coding: utf-8 -*-
r"""dev#220(release_profile.md §4.2「WSB内部のフェーズ別タイマーが無い」)の単体試験。

対象: devtools\sandbox_test\smoke_sandbox.py に追加した
  - run_step_timed()              : extract/gui_launch/cli_env/convertの
    4大ステップへ開始・終了時刻+壁時計所要秒を付与するラッパ
  - derive_convert_phase_durations() / CONVERT_PHASE_MARKERS
    : convert.ps1/build_pak_from_avatar.py(pipeline側、無改変)が既に出す
      進捗テキストから、Blender/衣装注入/pak組み立て/preflightの内訳を導く

いずれも純関数寄り(実Sandbox・実Blender・実Palworldには一切触れない)。
pipeline\配下のコードは読むだけで一切変更していない(CLAUDE.md安全制約)。

実行: python -m pytest tests\sandbox_test\test_smoke_sandbox_timing.py -v
   または python tests\sandbox_test\test_smoke_sandbox_timing.py
"""
import importlib.util
import os
import sys
import time
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(REPO, "devtools", "sandbox_test", "smoke_sandbox.py")

spec = importlib.util.spec_from_file_location("smoke_sandbox", MODULE_PATH)
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class _FakeRes(object):
    """Resultクラスの薄い代役。実ファイルI/O(flush)には触れず、
    steps配列とflush呼び出し回数だけを追跡する。"""

    def __init__(self):
        self.data = {"steps": []}
        self.flush_calls = 0

    def step(self, name, ok, details):
        self.data["steps"].append({"name": name, "ok": bool(ok), "details": details})

    def flush(self):
        self.flush_calls += 1


class TestRunStepTimed(unittest.TestCase):
    """run_step_timed(): 4大ステップの開始・終了時刻+壁時計所要秒の付与"""

    def test_attaches_timing_to_matching_step_entry(self):
        res = _FakeRes()

        def fake_step_extract(r, in_dir, work_dir):
            time.sleep(0.05)
            r.step("extract", True, {"zip": "dummy.zip"})
            return "/fake/root"

        result = ss.run_step_timed(res, "extract", fake_step_extract, res, "in", "work")

        self.assertEqual(result, "/fake/root")
        self.assertEqual(len(res.data["steps"]), 1)
        timing = res.data["steps"][0].get("timing")
        self.assertIsNotNone(timing, "timingが付与されていない")
        self.assertIn("started_at", timing)
        self.assertIn("finished_at", timing)
        self.assertGreaterEqual(timing["wall_elapsed_sec"], 0.0)
        self.assertGreaterEqual(res.flush_calls, 1, "timing付与後にflush()が呼ばれるべき")

    def test_elapsed_sec_reflects_actual_sleep(self):
        res = _FakeRes()

        def fake_step(r):
            time.sleep(0.2)
            r.step("gui_launch", True, {})

        ss.run_step_timed(res, "gui_launch", fake_step, res)
        elapsed = res.data["steps"][0]["timing"]["wall_elapsed_sec"]
        self.assertGreaterEqual(elapsed, 0.15, "実測のsleep時間より大幅に短い値は計測ミス")

    def test_does_not_attach_timing_when_step_name_mismatches(self):
        """負の対照: fnが実際に書いたstep名と呼び出し側が期待した名前が
        食い違う場合、timingを付与してはならない(誤ったエントリへの
        上書きを避けるfail-safe)。"""
        res = _FakeRes()

        def fake_step_wrong_name(r):
            r.step("unexpected_name", True, {})

        ss.run_step_timed(res, "extract", fake_step_wrong_name, res)
        self.assertNotIn("timing", res.data["steps"][0])

    def test_returns_fn_result_unmodified(self):
        res = _FakeRes()

        def fake_step(r):
            r.step("cli_env", False, {"error": "boom"})
            return {"custom": "value"}

        result = ss.run_step_timed(res, "cli_env", fake_step, res)
        self.assertEqual(result, {"custom": "value"})

    def test_does_not_crash_when_fn_records_no_step(self):
        """fnが何らかの理由でres.step()を1度も呼ばなかった場合でも
        (本来の4関数では起きないが防御的に)、run_step_timedはIndexError等
        で落ちてはならない。"""
        res = _FakeRes()

        def fake_step_no_call(r):
            return None

        result = ss.run_step_timed(res, "extract", fake_step_no_call, res)
        self.assertIsNone(result)
        self.assertEqual(res.data["steps"], [])


class TestDeriveConvertPhaseDurations(unittest.TestCase):
    """derive_convert_phase_durations(): Blender/衣装注入/pak組み立て/
    preflightの内訳を、convert.ps1(pipeline側、無改変)の進捗テキストの
    初出時刻から導く。"""

    def test_all_markers_present_computes_all_spans(self):
        phase_times = {
            "phase0_vanilla_start": 1.0,
            "phase0_vanilla_done": 3.0,
            "phase1_blender_start": 3.1,
            "phase1_blender_done": 40.0,
            "phase26_start": 40.2,
            "template_prep_start": 40.3,
            "template_prep_done": 45.0,
            "atlas_bake_start": 45.1,
            "atlas_bake_done": 50.0,
            "material_override_start": 50.1,
            "material_override_done": 51.0,
            "avatar_dump_start": 51.1,
            "avatar_dump_done": 65.0,
            "sk_injection_start": 65.1,
            "sk_injection_done": 88.0,
            "overrides_start": 88.1,
            "overrides_done": 89.0,
            "phase3_pak_start": 90.0,
            "phase3_pak_done": 125.0,
            "phase4_preflight_start": 125.1,
            "phase4_preflight_done": 142.0,
        }
        durations = ss.derive_convert_phase_durations(phase_times)
        self.assertEqual(durations["vanilla_sec"], 2.0)
        self.assertEqual(durations["blender_sec"], 36.9)
        self.assertEqual(durations["variant_inject_sec"], 49.8)
        self.assertEqual(durations["template_prep_sec"], 4.7)
        self.assertEqual(durations["atlas_bake_sec"], 4.9)
        self.assertEqual(durations["material_override_sec"], 0.9)
        self.assertEqual(durations["avatar_dump_sec"], 13.9)
        self.assertEqual(durations["sk_injection_sec"], 22.9)
        self.assertEqual(durations["overrides_sec"], 0.9)
        self.assertEqual(durations["pak_build_sec"], 35.0)
        self.assertEqual(durations["preflight_sec"], 16.9)

    def test_missing_marker_yields_none_not_fabricated(self):
        """負の対照: どちらかの端点が欠けた(タイムアウト・早期失敗・出力形式
        変化でマーカー未検出)区間は、値を捏造せずNoneのまま返す。"""
        phase_times = {k: None for k in ss.CONVERT_PHASE_MARKERS}
        phase_times["phase1_blender_start"] = 5.0
        # phase1_blender_done は検出できなかった(None のまま)
        durations = ss.derive_convert_phase_durations(phase_times)
        self.assertIsNone(durations["blender_sec"])
        self.assertIsNone(durations["vanilla_sec"])
        self.assertIsNone(durations["pak_build_sec"])
        self.assertIsNone(durations["preflight_sec"])
        # dev#220細分マーカーも同様にNone(全マーカーNone状態から書き換えていない)
        self.assertIsNone(durations["template_prep_sec"])
        self.assertIsNone(durations["atlas_bake_sec"])
        self.assertIsNone(durations["material_override_sec"])
        self.assertIsNone(durations["avatar_dump_sec"])
        self.assertIsNone(durations["sk_injection_sec"])
        self.assertIsNone(durations["overrides_sec"])

    def test_sk_injection_marker_missing_yields_none_only_for_that_span(self):
        """負の対照: sk_injection_doneだけが欠けても(FAIL/タイムアウト等で
        Phase2完了行が出ないケース)、他の既に検出済みの区間には影響しない
        (区間ごとに独立してNone判定することの確認)。"""
        phase_times = {k: None for k in ss.CONVERT_PHASE_MARKERS}
        phase_times["avatar_dump_start"] = 10.0
        phase_times["avatar_dump_done"] = 20.0
        phase_times["sk_injection_start"] = 20.1
        # sk_injection_done は検出できなかった
        durations = ss.derive_convert_phase_durations(phase_times)
        self.assertEqual(durations["avatar_dump_sec"], 10.0)
        self.assertIsNone(durations["sk_injection_sec"])

    def test_empty_phase_times_yields_all_none(self):
        durations = ss.derive_convert_phase_durations({})
        self.assertTrue(all(v is None for v in durations.values()))

    def test_convert_phase_markers_covers_expected_keys(self):
        expected = {
            "phase0_vanilla_start", "phase0_vanilla_done",
            "phase1_blender_start", "phase1_blender_done",
            "phase26_start",
            "template_prep_start", "template_prep_done",
            "atlas_bake_start", "atlas_bake_done",
            "material_override_start", "material_override_done",
            "avatar_dump_start", "avatar_dump_done",
            "sk_injection_start", "sk_injection_done",
            "overrides_start", "overrides_done",
            "phase3_pak_start", "phase3_pak_done",
            "phase4_preflight_start", "phase4_preflight_done",
        }
        self.assertEqual(set(ss.CONVERT_PHASE_MARKERS.keys()), expected)
        # マーカー文字列自体はconvert.ps1/build_pak_from_avatar.py/convert_noue.pyの
        # 実際の出力文言と一致していなければならない(ここがズレるとフェーズ検出が
        # 静かに全滅する)
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["phase3_pak_done"], "pak generated:")
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["phase4_preflight_done"], "ALL CHECKS PASS")
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["sk_injection_start"],
                          "=== Phase 2: injecting real avatar into outfit SKs ===")
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["sk_injection_done"],
                          "=== Phase2Subphase: sk_injection done ===")
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["avatar_dump_start"],
                          "=== Phase1Subphase: avatar_dump start ===")
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["template_prep_start"],
                          "=== NoueSubphase: template_prep start ===")
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["atlas_bake_start"],
                          "=== NoueSubphase: atlas_bake start ===")
        self.assertEqual(ss.CONVERT_PHASE_MARKERS["material_override_start"],
                          "=== NoueSubphase: material_override start ===")


if __name__ == "__main__":
    unittest.main(verbosity=2)
