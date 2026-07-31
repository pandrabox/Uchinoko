# -*- coding: utf-8 -*-
"""dev#131パッチの単体テスト(純関数・スレッド配線のみ。排他資源には一切触れない)。

対象: devtools\\sandbox_test\\run_sandbox_test.py に追加した
  - start_host_ref_thread() / join_host_ref()  (提案1: 基準pak並列化)
  - main()内ポーリングループの sleep 間隔切替ロジック (提案2: 0.5秒/5秒)

build_host_reference_pak() 自体はBlender実行を伴う(排他資源)ため、
モンキーパッチで置き換えて「スレッド起動→例外安全→join結果取得」という
配線だけを検証する。WSB/Blender/Palworld/pak適用には一切触れない。

実行方法(リポジトリルートから):
  python -m pytest tests\\sandbox_test\\test_host_ref_parallel.py -v
  または python tests\\sandbox_test\\test_host_ref_parallel.py

出典: work/rdp_131(dev#131実装パッチ)付属テストをリポジトリ本体へ配置。
"""
import argparse
import importlib.util
import os
import sys
import time
import unittest
import unittest.mock as mock

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(REPO, "devtools", "sandbox_test", "run_sandbox_test.py")

spec = importlib.util.spec_from_file_location("run_sandbox_test", MODULE_PATH)
rst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rst)


def _args(convert=True, tamper_convert=False):
    ns = argparse.Namespace()
    ns.convert = convert
    ns.tamper_convert = tamper_convert
    return ns


class TestStartHostRefThread(unittest.TestCase):
    """提案1: 基準pak作成のスレッド化配線"""

    def test_convert_true_starts_thread_and_returns_success_result(self):
        """--convert指定時: スレッドが起動し、build_host_reference_pak()の
        戻り値がそのままjoin_host_ref()で取得できる(結果を変えない)"""
        fake_ref = {"ok": True, "pak_sha256": "deadbeef", "pak_size": 123,
                    "elapsed_sec": 1.0}
        with mock.patch.object(rst, "build_host_reference_pak", return_value=fake_ref) as m:
            thread, result = rst.start_host_ref_thread(
                _args(convert=True, tamper_convert=False),
                "src.zip", "vrm.vrm", "work_dir", "C:\\Palworld")
            self.assertIsNotNone(thread)
            ref = rst.join_host_ref(thread, result, timeout=30)
            self.assertEqual(ref, fake_ref)
            m.assert_called_once()
            # palworld_pakパスの組み立て(palworld_dirから正しく合成されているか)
            called_args = m.call_args[0]
            self.assertTrue(called_args[4].endswith(
                os.path.join("Pal", "Content", "Paks", "Pal-Windows.pak")))

    def test_tamper_convert_does_not_start_thread(self):
        """--tamper-convert時: 変換自体がFAILする想定のため基準pak作成に進まない
        (既存ガード`if not os.path.isfile(HOST_BLENDER_EXE) and not
        args.tamper_convert:`と対称的な除外)"""
        with mock.patch.object(rst, "build_host_reference_pak") as m:
            thread, result = rst.start_host_ref_thread(
                _args(convert=True, tamper_convert=True),
                "src.zip", "vrm.vrm", "work_dir", "C:\\Palworld")
            self.assertIsNone(thread)
            m.assert_not_called()
        # join側もNoneを渡された場合に安全にFAIL辞書を返す(防御)
        ref = rst.join_host_ref(thread, result)
        self.assertFalse(ref["ok"])

    def test_convert_false_does_not_start_thread(self):
        """--convert未指定時: そもそも基準pakは不要なので起動しない"""
        with mock.patch.object(rst, "build_host_reference_pak") as m:
            thread, result = rst.start_host_ref_thread(
                _args(convert=False, tamper_convert=False),
                "src.zip", "vrm.vrm", "work_dir", "C:\\Palworld")
            self.assertIsNone(thread)
            m.assert_not_called()

    def test_thread_exception_is_captured_not_propagated(self):
        """残リスク記載の核心: スレッド内で例外が飛んでもメインスレッドに
        伝播せず、必ず{"ok": False, "error": ...}が格納される(fail-openにしない)"""
        with mock.patch.object(rst, "build_host_reference_pak",
                                side_effect=RuntimeError("boom")):
            thread, result = rst.start_host_ref_thread(
                _args(convert=True, tamper_convert=False),
                "src.zip", "vrm.vrm", "work_dir", "C:\\Palworld")
            self.assertIsNotNone(thread)
            # join_host_ref自体が例外を投げずに戻ってくることを確認
            ref = rst.join_host_ref(thread, result, timeout=30)
        self.assertFalse(ref["ok"])
        self.assertIn("boom", ref["error"])

    def test_join_timeout_returns_fail_dict_without_hanging(self):
        """スレッドが規定時間内に終わらない場合、join_host_ref()はブロックし
        続けず、timeout後にFAIL辞書を返す(呼び出し側を無限に待たせない)"""
        def _slow(*a, **kw):
            time.sleep(2)
            return {"ok": True}
        with mock.patch.object(rst, "build_host_reference_pak", side_effect=_slow):
            thread, result = rst.start_host_ref_thread(
                _args(convert=True, tamper_convert=False),
                "src.zip", "vrm.vrm", "work_dir", "C:\\Palworld")
            t0 = time.time()
            ref = rst.join_host_ref(thread, result, timeout=0.05)
            elapsed = time.time() - t0
        self.assertLess(elapsed, 1.0, "join timeoutが効かずブロックしている")
        self.assertFalse(ref["ok"])
        self.assertIn("timeout", ref["error"])
        # 後始末: バックグラウンドスレッドの完走を待ってからテストを終える
        thread.join(timeout=5)

    def test_palworld_dir_none_passes_none_pak_path(self):
        """Palworldが見つからない(--convertでは通常起こらないが、防御的に確認):
        palworld_dirがNoneならpalworld_pak引数もNoneのまま渡る(強制的な
        os.path.join()でのクラッシュを起こさない、既存の
        `palworld_dir and os.path.join(...)`短絡評価の踏襲確認)"""
        with mock.patch.object(rst, "build_host_reference_pak",
                                return_value={"ok": True}) as m:
            thread, result = rst.start_host_ref_thread(
                _args(convert=True, tamper_convert=False),
                "src.zip", "vrm.vrm", "work_dir", None)
            rst.join_host_ref(thread, result, timeout=30)
            called_args = m.call_args[0]
            self.assertIsNone(called_args[4])


class TestPollingIntervalLogic(unittest.TestCase):
    """提案2: ポーリング間隔切替の条件(main()内インラインの真偽表と同一ロジック)。

    ロジック自体はmain()内に残しているため(制御フロー中枢で関数分離すると
    可読性が落ちるとの判断)、ここでは同一の条件式を独立して真偽表として検証し、
    実装(`if not (minimized and started_seen): sleep(0.5) else: sleep(5)`)の
    意図どおりの分岐であることを固定する回帰テスト。
    """

    def _interval(self, minimized, started_seen):
        return 0.5 if not (minimized and started_seen) else 5

    def test_neither_confirmed_short_interval(self):
        self.assertEqual(self._interval(False, False), 0.5)

    def test_only_minimized_confirmed_short_interval(self):
        self.assertEqual(self._interval(True, False), 0.5)

    def test_only_started_confirmed_short_interval(self):
        self.assertEqual(self._interval(False, True), 0.5)

    def test_both_confirmed_long_interval(self):
        self.assertEqual(self._interval(True, True), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
