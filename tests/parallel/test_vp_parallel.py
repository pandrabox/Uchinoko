# -*- coding: utf-8 -*-
"""pipeline\\py\\vp_parallel.py のユニットテスト(rd_120: 変換パイプライン並列化)。

実行: python tests\\parallel\\test_vp_parallel.py  (stdlib unittestのみ。pytestでも収集可)

このスイートは**実Blender・実pak変換を一切行わない**(worktree隔離、変換禁止の
契約どおり)。検証対象はrd_120 PROPOSAL 3節/8節が要求する2つの不変条件のみ:
  1. 順序非依存: executor.map()ベースのヘルパーは、**入力順**で結果を返す
     (完了順ではない)。並列度・実行順が変わっても最終pakのreplace_mapへ渡す
     集合が変わらないことの土台(PROPOSAL 3節)。
  2. 失敗非伝播(負の対照): 1件が失敗/例外を投げても、他タスクの実行・結果収集は
     止まらない。特にrun_pair_parallel()は「片方が例外を投げても、context
     managerがもう片方の完了を待ってから例外を伝播する」設計
     (build_pak_from_avatar.py Phase1ダンプ/convert_noue.pyアトラス焼き込みが
     依拠する挙動、PROPOSAL 8節論点2)。

build_pak_from_avatar.py/convert_noue.py本体側の個々のワーカー関数
(_injection_worker/_dump_gender/_atlas_bake_one)は実uexp/実Blenderに依存する
ため、ここではなく tests\\parallel\\test_injection_worker_error_containment.py で
「例外を外へ投げず失敗結果を返す」契約だけを直接呼び出しで検証する。
"""

import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "pipeline", "py"))

import vp_parallel  # noqa: E402


def _mp_square(x):
    """run_pool_ordered()の既定executor(ProcessPoolExecutor)向けの
    モジュールレベル関数(pickle可能である必要があるため、クロージャや
    ラムダではなくここに置く)。実プロセス起動でのpickling/spawn自体を
    検証するためだけの純関数(Blender/pak/実変換は一切関与しない)。"""
    return x * x


class TestRunPoolOrderedRealProcessPool(unittest.TestCase):
    """既定のexecutor_factory(ProcessPoolExecutor)を差し替えずに使う経路の
    スモークテスト。build_pak_from_avatar.pyの本番呼び出し
    (executor_factory省略=ProcessPoolExecutor既定)がWindows spawnで
    実際にpickle・起動できることを、実データ非依存の最小関数で確認する。"""

    def test_default_executor_is_process_pool_and_preserves_order(self):
        tasks = [4, 1, 9, 2, 5]
        results = vp_parallel.run_pool_ordered(_mp_square, tasks, n_workers=2)
        self.assertEqual(results, [16, 1, 81, 4, 25])


class TestRunPairParallel(unittest.TestCase):
    """vp_parallel.run_pair_parallel()(rd_120 5.2/5.3が使う2要素並列ヘルパー)。"""

    def test_preserves_input_order_not_completion_order(self):
        """1件目をわざと遅くしても、結果は入力順(1件目, 2件目)で返る
        (=呼び出し元のprint順・辞書構築順が並列度に依存しない、という
        Phase1ダンプ/アトラス焼き込みの前提の根拠)。"""
        def worker(item):
            name, delay = item
            time.sleep(delay)
            return name

        items = [("first_but_slow", 0.25), ("second_but_fast", 0.01)]
        results = vp_parallel.run_pair_parallel(worker, items)
        self.assertEqual(results, ["first_but_slow", "second_but_fast"])

    def test_negative_control_both_complete_even_if_one_raises(self):
        """負の対照: 1件目が(die()を模した)例外を早々に投げても、2件目の処理は
        最後まで走り切ってから例外が呼び出し元へ伝播する
        (=失敗を検出したときに他方の診断ログが失われない設計、PROPOSAL 8節論点2)。
        """
        completed = []
        lock = threading.Lock()

        def worker(item):
            name, delay, should_fail = item
            time.sleep(delay)
            with lock:
                completed.append(name)
            if should_fail:
                raise RuntimeError(f"{name} failed (simulated die())")
            return name

        items = [("fast_fail", 0.01, True), ("slow_ok", 0.3, False)]
        with self.assertRaises(RuntimeError):
            vp_parallel.run_pair_parallel(worker, items)
        # fast_fail が真っ先に例外を投げても、slow_ok が完了するまで
        # run_pair_parallel() 自体はブロックしているはず
        self.assertIn("fast_fail", completed)
        self.assertIn("slow_ok", completed)

    def test_empty_items_returns_empty_list(self):
        self.assertEqual(vp_parallel.run_pair_parallel(lambda x: x, []), [])

    def test_single_item(self):
        self.assertEqual(vp_parallel.run_pair_parallel(lambda x: x * 2, [21]), [42])


class TestRunPoolOrdered(unittest.TestCase):
    """vp_parallel.run_pool_ordered()(rd_120 5.1のPhase2 SK注入並列化の骨格)。

    実プロセス起動コストを避けるため、executor_factory=ThreadPoolExecutorを
    注入する(本番はProcessPoolExecutorが既定だが、検証対象の「入力順保持」
    「1件の失敗が他タスクを止めない」という不変条件はexecutor.map()の契約に
    由来し、プロセス/スレッドどちらでも同じ)。"""

    def test_preserves_input_order_regardless_of_completion_order(self):
        def worker(item):
            idx, delay = item
            time.sleep(delay)
            return idx

        # わざと先頭タスクを一番遅くする(完了順は index の昇順にならない)
        tasks = [(0, 0.2), (1, 0.01), (2, 0.15), (3, 0.02)]
        results = vp_parallel.run_pool_ordered(
            worker, tasks, n_workers=4, executor_factory=ThreadPoolExecutor)
        self.assertEqual(results, [0, 1, 2, 3])

    def test_negative_control_failures_do_not_drop_or_block_other_tasks(self):
        """負の対照: 3件おきに「失敗」を返すワーカーでも、全10件が処理され、
        失敗した番号の集合が過不足なく検出できる(rd_120 PROPOSAL 5.1の
        `_injection_worker`が採用する「例外を投げず(ok, ...)を返す」契約と
        同型)。1件の失敗が他タスクの実行・収集を止めない、という要件の検証。"""
        def worker(item):
            idx, should_fail = item
            if should_fail:
                return (idx, False, "boom")
            return (idx, True, None)

        tasks = [(i, i % 3 == 0) for i in range(10)]
        results = vp_parallel.run_pool_ordered(
            worker, tasks, n_workers=4, executor_factory=ThreadPoolExecutor)
        # 順序: 入力順のまま10件全部そろっている(欠落・重複なし)
        self.assertEqual([r[0] for r in results], list(range(10)))
        failed = [r[0] for r in results if not r[1]]
        self.assertEqual(failed, [0, 3, 6, 9])

    def test_single_worker_still_processes_all_tasks(self):
        """n_workers=1(低スペック機フォールバック相当)でも結果は同じ。"""
        def worker(item):
            return item * 10

        results = vp_parallel.run_pool_ordered(
            worker, [1, 2, 3], n_workers=1, executor_factory=ThreadPoolExecutor)
        self.assertEqual(results, [10, 20, 30])

    def test_initializer_runs_once_per_worker_and_state_is_visible(self):
        """initializer(_init_worker相当)で積んだ状態がworker_fnから見える
        (build_pak_from_avatar._init_worker/_injection_workerの前提)。"""
        state = {}

        def init(shared):
            state["shared"] = shared

        def worker(item):
            return state["shared"][item]

        results = vp_parallel.run_pool_ordered(
            worker, ["a", "b"], n_workers=2, initializer=init,
            initargs=({"a": 1, "b": 2},), executor_factory=ThreadPoolExecutor)
        self.assertEqual(results, [1, 2])


class TestDefaultWorkerCount(unittest.TestCase):
    """vp_parallel.default_worker_count()(rd_120 PROPOSAL 8節論点1: 環境変数上書き)。"""

    ENV_VAR = "D2P_TEST_WORKER_COUNT_UNITTEST"

    def tearDown(self):
        os.environ.pop(self.ENV_VAR, None)

    def test_env_override_takes_priority(self):
        os.environ[self.ENV_VAR] = "5"
        self.assertEqual(vp_parallel.default_worker_count(self.ENV_VAR), 5)

    def test_invalid_env_value_falls_back_to_cpu_based_default(self):
        os.environ[self.ENV_VAR] = "not_a_number"
        n = vp_parallel.default_worker_count(self.ENV_VAR, floor=2)
        cpu = os.cpu_count() or 4
        self.assertEqual(n, max(1, cpu - 2))

    def test_zero_or_negative_env_value_ignored(self):
        os.environ[self.ENV_VAR] = "0"
        n = vp_parallel.default_worker_count(self.ENV_VAR, floor=2)
        cpu = os.cpu_count() or 4
        self.assertEqual(n, max(1, cpu - 2))

    def test_never_goes_below_one_even_with_large_floor(self):
        os.environ.pop(self.ENV_VAR, None)
        n = vp_parallel.default_worker_count(self.ENV_VAR, floor=1000)
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
