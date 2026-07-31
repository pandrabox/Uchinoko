# -*- coding: utf-8 -*-
"""pipeline\\py\\build_pak_from_avatar.py の _run_phase2_overlap() テスト
(dev#288: sk_injection(L2)とtexture overrides(L2b)の重畳)。

実行: python tests\\parallel\\test_l2_l2b_overlap.py  (stdlib unittestのみ)

**実uexp/実Blender/実テンプレートには一切触れない**(worktree隔離、変換禁止の
契約どおり)。`_run_sk_injection`/`_run_overrides`(本WPでmain()から切り出した
関数)自体をmonkeypatchし、`_run_phase2_overlap()`が要求する2点だけを検証する:

  (a) 重畳実行で両方の成果物が揃うこと。加えて、両者に意図的な遅延を仕込み、
      壁時計が「両方の遅延の合計」より短いこと(=直列実行なら必ず超える時間)を
      確認することで、「並べて呼んでいるだけで実は直列」という見せかけの
      重畳(feedback-implemented-vs-wired.md)を機械的に弾く。
  (b) 片方(sk_injectionまたはoverrides)を意図的に失敗させたとき、全体が
      失敗し(例外が呼び出し元へ伝播する)、かつ失敗理由が失敗させた側の
      ものであること(誤報されないこと)。さらに、失敗した側の例外が
      伝播するまでの間に、もう片方の処理が最後まで走り切っていること
      (rd_120 run_pair_parallel()のtrade-off、既存test_vp_parallel.pyの
      負の対照と同型)。
"""

import os
import sys
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "pipeline", "py"))

import build_pak_from_avatar as bpfa  # noqa: E402

# 各モック側の疑似所要時間(秒)。直列なら合計以上、重畳なら合計未満になる
# ことをwall clockで判定する。CI/開発機どちらでも安定するよう、直列合計との
# マージンを大きめに取る(0.35 vs 0.5合計への余裕、下のassertion参照)。
_SK_DELAY = 0.25
_OV_DELAY = 0.25


class TestRunPhase2OverlapPositive(unittest.TestCase):
    """(a) 重畳実行で両方の成果物が揃うこと + 実際に重なっていること。"""

    def test_both_artifacts_present_and_wall_time_shorter_than_serial_sum(self):
        def fake_sk_injection(template, requested_genders, variant_dir, dumps):
            time.sleep(_SK_DELAY)
            return ["Player/Outfit/SK_fake.uexp"]

        def fake_overrides(args, template, work):
            time.sleep(_OV_DELAY)
            return ({"tex": "tex_path"}, {"mat": "mat_path"}, {"mi": "mi_path"})

        with mock.patch.object(bpfa, "_run_sk_injection", side_effect=fake_sk_injection), \
             mock.patch.object(bpfa, "_run_overrides", side_effect=fake_overrides):
            t0 = time.time()
            targets_rel, (tex_replace, mat_override, mi_override) = bpfa._run_phase2_overlap(
                template="T", requested_genders={"Male", "Female"},
                variant_dir="V", dumps={}, args=object(), work="W")
            elapsed = time.time() - t0

        # (a) 両方の成果物が揃っている
        self.assertEqual(targets_rel, ["Player/Outfit/SK_fake.uexp"])
        self.assertEqual(tex_replace, {"tex": "tex_path"})
        self.assertEqual(mat_override, {"mat": "mat_path"})
        self.assertEqual(mi_override, {"mi": "mi_path"})

        # 実際に重なっている(直列なら_SK_DELAY+_OV_DELAY=0.5秒以上かかる。
        # 重畳ならmax(0.25, 0.25)=0.25秒程度で終わるはず。0.4秒を閾値にして
        # 「直列に呼んでいるだけ」を確実に弾く)
        self.assertLess(elapsed, _SK_DELAY + _OV_DELAY - 0.1,
                         f"elapsed={elapsed:.3f}s は直列実行相当であり、重畳できていない")


class TestRunPhase2OverlapNegative(unittest.TestCase):
    """(b) 片方の失敗が全体を失敗させ、もう片方の失敗として誤報されないこと。"""

    def test_sk_injection_failure_is_reported_as_sk_injection_not_overrides(self):
        overrides_completed = []

        def failing_sk_injection(template, requested_genders, variant_dir, dumps):
            time.sleep(0.02)
            raise SystemExit(
                "[build_pak_from_avatar][FATAL] outfit SK injection failed for 1 "
                "(see log above for details)")

        def slow_ok_overrides(args, template, work):
            time.sleep(_OV_DELAY)
            overrides_completed.append(True)
            return ({}, {}, {})

        with mock.patch.object(bpfa, "_run_sk_injection", side_effect=failing_sk_injection), \
             mock.patch.object(bpfa, "_run_overrides", side_effect=slow_ok_overrides):
            with self.assertRaises(SystemExit) as ctx:
                bpfa._run_phase2_overlap(
                    template="T", requested_genders={"Male", "Female"},
                    variant_dir="V", dumps={}, args=object(), work="W")

        # 失敗理由はsk_injection側のものであり、overrides側の失敗と誤認されない
        self.assertIn("outfit SK injection failed", str(ctx.exception))
        # overrides側は遅くても最後まで完走している(結果が失われない)
        self.assertTrue(overrides_completed,
                         "sk_injection失敗時、overridesが完走前に打ち切られている")

    def test_overrides_failure_is_reported_as_overrides_not_sk_injection(self):
        sk_completed = []

        def slow_ok_sk_injection(template, requested_genders, variant_dir, dumps):
            time.sleep(_SK_DELAY)
            sk_completed.append(True)
            return ["Player/Outfit/SK_fake.uexp"]

        def failing_overrides(args, template, work):
            time.sleep(0.02)
            raise SystemExit(
                "[build_pak_from_avatar][FATAL] --tex-body does not exist: X.png")

        with mock.patch.object(bpfa, "_run_sk_injection", side_effect=slow_ok_sk_injection), \
             mock.patch.object(bpfa, "_run_overrides", side_effect=failing_overrides):
            with self.assertRaises(SystemExit) as ctx:
                bpfa._run_phase2_overlap(
                    template="T", requested_genders={"Male", "Female"},
                    variant_dir="V", dumps={}, args=object(), work="W")

        # 失敗理由はoverrides側のものであり、sk_injection側の失敗と誤認されない
        self.assertIn("--tex-body does not exist", str(ctx.exception))
        # sk_injection側は遅くても最後まで完走している(結果が失われない)
        self.assertTrue(sk_completed,
                         "overrides失敗時、sk_injectionが完走前に打ち切られている")


if __name__ == "__main__":
    unittest.main()
