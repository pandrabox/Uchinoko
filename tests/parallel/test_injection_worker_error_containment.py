# -*- coding: utf-8 -*-
"""pipeline\\py\\build_pak_from_avatar.py の並列化ワーカーの契約テスト
(rd_120: 変換パイプライン並列化)。

実行: python tests\\parallel\\test_injection_worker_error_containment.py
(stdlib unittestのみ。pytestでも収集可)

**実uexp/実Blenderには一切触れない**(worktree隔離、変換禁止の契約どおり)。
`build_and_validate`(build_avatar_variant_all.py、無改変)をmonkeypatchし、
`_injection_worker`が「例外を外へ投げず (rel_uexp, gender, ok, errs, info) を
返す」契約を守ることだけを直接呼び出しで検証する。

なぜこの契約が要るか(rd_120 PROPOSAL 5.1):
  `_injection_worker`はProcessPoolExecutorのワーカー関数として使われる。
  vp_parallel.run_pool_ordered()はexecutor.map()を使っており、map()が返す
  イテレータは**タスクの結果を取り出した時点で例外を再送出する**ため、もし
  ワーカーが例外を投げたままだと、1件の失敗で残りのタスクの結果取得が
  そこで打ち切られてしまう(=n_fail集計・ログ出力が失敗タスク以降で
  欠落する)。現行の逐次ループが持っていた
  `try: build_and_validate(...) except Exception as e: ok=False; errs=[str(e)]`
  という「失敗を握りつぶして次へ進む」挙動を、並列化後も1タスク単位で
  再現できていることがこのテストの目的(=1件の失敗が他タスクの実行・結果
  収集を止めない、という負の対照)。
"""

import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "pipeline", "py"))

import build_pak_from_avatar as bpfa  # noqa: E402


class TestInjectionWorkerErrorContainment(unittest.TestCase):

    def setUp(self):
        # 各テストでワーカーグローバルを既知の状態にリセットする
        bpfa._init_worker({"Female": {"tag": "female_dump"}, "Male": {"tag": "male_dump"}})

    def tearDown(self):
        bpfa._init_worker(None)

    def test_success_path_returns_ok_true(self):
        fake_info = {"num_vertices": 100, "num_triangles": 50}
        with mock.patch.object(bpfa, "build_and_validate",
                                return_value=(True, [], fake_info)) as m:
            task = ("u.uexp", "u.uasset", "Female", "out.uexp", "out.uasset", "rel/u.uexp")
            rel_uexp, gender, ok, errs, info = bpfa._injection_worker(task)
        m.assert_called_once_with("u.uexp", "u.uasset", {"tag": "female_dump"},
                                   "out.uexp", "out.uasset")
        self.assertEqual(rel_uexp, "rel/u.uexp")
        self.assertEqual(gender, "Female")
        self.assertTrue(ok)
        self.assertEqual(errs, [])
        self.assertEqual(info, fake_info)

    def test_validation_failure_returns_ok_false_without_raising(self):
        """build_and_validateがok=Falseを返すケース(例外ではなく通常の
        検証NG)。従来の逐次ループと同じくそのまま伝搬する。"""
        with mock.patch.object(bpfa, "build_and_validate",
                                return_value=(False, ["gap_zero=False"], {"num_vertices": 1})):
            task = ("u.uexp", "u.uasset", "Male", "out.uexp", "out.uasset", "rel/u.uexp")
            rel_uexp, gender, ok, errs, info = bpfa._injection_worker(task)
        self.assertFalse(ok)
        self.assertEqual(errs, ["gap_zero=False"])

    def test_exception_in_build_and_validate_is_contained_not_raised(self):
        """負の対照(本テストの主眼): build_and_validateが例外を投げても、
        _injection_worker自体は例外を外へ伝播させず、(ok=False, errs=[str(e)])
        という失敗結果を返す。"""
        with mock.patch.object(bpfa, "build_and_validate",
                                side_effect=RuntimeError("boom: corrupt uexp")):
            task = ("u.uexp", "u.uasset", "Female", "out.uexp", "out.uasset", "rel/u.uexp")
            try:
                rel_uexp, gender, ok, errs, info = bpfa._injection_worker(task)
            except RuntimeError:
                self.fail("_injection_worker must contain the exception, not re-raise it")
        self.assertFalse(ok)
        self.assertEqual(errs, ["boom: corrupt uexp"])
        self.assertEqual(info, {})
        self.assertEqual(rel_uexp, "rel/u.uexp")
        self.assertEqual(gender, "Female")

    def test_gender_selects_the_matching_dump(self):
        """initializerで積んだ_WORKER_DUMPSからgenderで正しいdumpが選ばれる
        (58件を並列分配してもFemale/Male混線しないことの根拠)。"""
        captured = {}

        def fake_build_and_validate(uexp, uasset, dump, out_uexp, out_uasset):
            captured["dump"] = dump
            return True, [], {}

        with mock.patch.object(bpfa, "build_and_validate", side_effect=fake_build_and_validate):
            bpfa._injection_worker(("u.uexp", "u.uasset", "Male", "o1", "o2", "rel"))
        self.assertEqual(captured["dump"], {"tag": "male_dump"})

    def test_end_to_end_through_run_pool_ordered_mixed_success_and_failure(self):
        """_injection_workerをrun_pool_ordered()(rd_120 5.1が使う実際の分配経路)
        経由で複数件流し、1件の例外が他タスクの実行・収集を止めないことを
        確認する(ThreadPoolExecutorで代替、実プロセス起動なし)。"""
        import vp_parallel
        from concurrent.futures import ThreadPoolExecutor

        def flaky_build_and_validate(uexp, uasset, dump, out_uexp, out_uasset):
            if "bad" in uexp:
                raise RuntimeError(f"simulated corruption: {uexp}")
            return True, [], {"num_vertices": 1, "num_triangles": 1}

        tasks = [
            ("good1.uexp", "good1.uasset", "Female", "o", "o", "rel/good1.uexp"),
            ("bad.uexp", "bad.uasset", "Female", "o", "o", "rel/bad.uexp"),
            ("good2.uexp", "good2.uasset", "Male", "o", "o", "rel/good2.uexp"),
        ]
        with mock.patch.object(bpfa, "build_and_validate", side_effect=flaky_build_and_validate):
            results = vp_parallel.run_pool_ordered(
                bpfa._injection_worker, tasks, n_workers=3,
                initializer=bpfa._init_worker,
                initargs=({"Female": {"tag": "female_dump"}, "Male": {"tag": "male_dump"}},),
                executor_factory=ThreadPoolExecutor)
        self.assertEqual([r[0] for r in results],
                          ["rel/good1.uexp", "rel/bad.uexp", "rel/good2.uexp"])
        oks = {r[0]: r[2] for r in results}
        self.assertTrue(oks["rel/good1.uexp"])
        self.assertFalse(oks["rel/bad.uexp"])
        self.assertTrue(oks["rel/good2.uexp"])


if __name__ == "__main__":
    unittest.main()
