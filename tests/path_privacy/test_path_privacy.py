# -*- coding: utf-8 -*-
"""pipeline\\py\\path_privacy.py のユニットテスト(dev#7)。

背景: 実ユーザー報告4AL4M4GTで、非%USERPROFILE%ドライブの絶対パス
(Unity/VCC・インストール先・Steamライブラリ)が診断ログへそのまま漏れた。
本モジュールは pipeline\\py\\fast_repack.py の既存修正(_path_facts/_display_path)を
一般化して切り出したもので、convert.ps1・export_from_unity.ps1からも
(Pythonサブプロセス経由で)使われる(三段構成の「各所factify」、詳細は
work\\issue_zero\\i7\\NOTES.md)。

フィクスチャは全て架空の値(実在の個人情報は使わない)。

実行: python tests\\path_privacy\\test_path_privacy.py  (pytestでも収集可)
"""
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "pipeline", "py"))

import path_privacy  # noqa: E402

PATH_PRIVACY_PY = os.path.join(_REPO, "pipeline", "py", "path_privacy.py")

# 実在しない架空のユーザー名(このリポジトリ・テスト実行環境の実ユーザー名と
# 衝突しないよう、あえて非現実的な文字列にしてある)
FAKE_USER = "SampleTaro_Zzyzx9912"


class TestPathFacts(unittest.TestCase):
    def test_no_leak_of_personal_folder_name(self):
        """path_facts()の出力に、パス中の人名らしきフォルダ名が一切含まれないこと。"""
        p = r"D:\Users\%s\UnityProjects\MyAvatarProject\Assets\avatar.prefab" % FAKE_USER
        facts = path_privacy.path_facts(p)
        self.assertNotIn(FAKE_USER, facts)
        # ファイル名(personal情報を含まない末端要素)は事実として残ってよい
        self.assertIn("avatar.prefab", facts)
        self.assertIn("exists=False", facts)

    def test_empty_path(self):
        self.assertEqual(path_privacy.path_facts(""), "(no path)")
        self.assertEqual(path_privacy.path_facts(None), "(no path)")

    def test_unc_flag(self):
        p = r"\\BUILDSERVER\share\%s\avatar.vrm" % FAKE_USER
        facts = path_privacy.path_facts(p)
        self.assertNotIn(FAKE_USER, facts)
        self.assertIn("UNC=True", facts)


class TestDisplayPath(unittest.TestCase):
    def test_under_base_returns_relative(self):
        base = r"C:\P\Work\DiveToPalworld\work"
        p = r"C:\P\Work\DiveToPalworld\work\job123\build\out.pak"
        disp = path_privacy.display_path(p, (base,))
        self.assertEqual(disp, os.path.join("job123", "build", "out.pak"))

    def test_outside_all_bases_returns_basename_only(self):
        """既知の安全なbaseに属さないパスは、生パスを一切返さずファイル名のみへ落ちること
        (dev#7の核心: 非%USERPROFILE%ドライブ・任意フォルダ名でも個人情報を出さない)。"""
        p = r"D:\Users\%s\SteamLibrary\steamapps\common\Palworld\Pal-Windows.pak" % FAKE_USER
        disp = path_privacy.display_path(p, (r"C:\P\Work\DiveToPalworld\work",))
        self.assertNotIn(FAKE_USER, disp)
        self.assertNotIn("SteamLibrary", disp)
        self.assertEqual(disp, "Pal-Windows.pak")


class TestFactify(unittest.TestCase):
    def test_core_case_non_userprofile_drive_leak(self):
        """核心ケース(4AL4M4GT実証): 非UserProfileドライブの絶対パスが、
        factify()を通すと生パス・架空ユーザー名とも一切残らないこと。"""
        fake_path = r"D:\Users\%s\UnityProjects\MyAvatarProject\Assets\avatar.prefab" % FAKE_USER
        # 負の対照(フィクスチャの健全性確認): 何もしなければfake_pathそのものに
        # マーカーが含まれている、というテスト前提を明示する。この行が無くても
        # 下のassertは有効だが、「テストが本当に何かを検出できる」ことを人間が
        # 読んでわかるようにするため残す。
        self.assertIn(FAKE_USER, fake_path)

        result = path_privacy.factify(fake_path)
        self.assertNotIn(FAKE_USER, result)
        self.assertNotIn(fake_path, result)
        # 診断可用性: 拡張子は伏字化後も残ること(伏字化がデバッグ能力を壊さない確認)
        self.assertIn("avatar.prefab", result)

    def test_unc_case(self):
        fake_path = r"\\BUILDSERVER\share\%s\SteamLibrary\Palworld\Pal-Windows.pak" % FAKE_USER
        result = path_privacy.factify(fake_path)
        self.assertNotIn(FAKE_USER, result)
        self.assertNotIn(fake_path, result)

    def test_under_base_keeps_useful_relative_path(self):
        base = r"C:\P\Work\DiveToPalworld\work"
        p = r"C:\P\Work\DiveToPalworld\work\job123\build\out.pak"
        result = path_privacy.factify(p, (base,))
        self.assertEqual(result, os.path.join("job123", "build", "out.pak"))

    def test_empty(self):
        self.assertEqual(path_privacy.factify(""), "(no path)")


class TestCli(unittest.TestCase):
    """export_from_unity.ps1が実際に呼ぶ経路(subprocess経由のCLI)の統合確認。"""

    def test_factify_cli_masks_fake_username(self):
        fake_path = r"D:\Users\%s\UnityProjects\MyAvatarProject\Assets\avatar.prefab" % FAKE_USER
        proc = subprocess.run(
            [sys.executable, PATH_PRIVACY_PY, "factify", fake_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(FAKE_USER, proc.stdout)
        self.assertNotIn(fake_path, proc.stdout)
        self.assertIn("avatar.prefab", proc.stdout)

    def test_factify_cli_with_base(self):
        base = r"C:\P\Work\DiveToPalworld\work"
        p = r"C:\P\Work\DiveToPalworld\work\job123\build\out.pak"
        proc = subprocess.run(
            [sys.executable, PATH_PRIVACY_PY, "factify", p, "--base", base],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), os.path.join("job123", "build", "out.pak"))


if __name__ == "__main__":
    unittest.main()
