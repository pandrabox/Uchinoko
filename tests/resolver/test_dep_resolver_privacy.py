# -*- coding: utf-8 -*-
"""pipeline\\py\\dep_resolver.py のtrail出力の生パス正規化(dev#325)専用試験。

背景: dep_resolver.py のtrail出力(`[dep_resolver] known-paths: C:\\...\\Unity.exe -> ...`
等)が呼び出し元ps1(export_from_unity.ps1)の `Write-Host $line` でそのまま中継され、
Unityインストール先が非標準ドライブ・個人フォルダ名を含む場合に生パスがログへ
残っていた(dev#7 三段防御の残存穴)。修正: dep_resolver.py自身の出力時点
(Candidate.format())で既存の pipeline\\py\\path_privacy.py(dev#7で新設、PR#324)
を通す。

受入ゲート対応:
  - 赤→緑: 標準外パス(ユーザー名相当を含むtempdir配下)を解決させ、trailに
    生パスが一切出ないことを確認(修正前はこの assertNotIn が落ちていたはず)
  - 失敗経路(DependencyNotFoundError)でも同様にtrailがマスクされることを確認
  - 負の対照: 伏字化(_factify)を無効化すると生パスが漏れる
    (= このテストが実際にマスク処理の有無を検出できることの証明)
  - 実在の個人パスは使わない(すべて架空のtempdir/fake_drive)

実行: python tests\\resolver\\test_dep_resolver_privacy.py  (stdlib unittestのみ)
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "pipeline", "py"))

import dep_resolver  # noqa: E402
from dep_resolver import DependencyNotFoundError, resolve_unity_editor  # noqa: E402


def _make_fake_editor(root, version):
    """<root>\\<version>\\Editor\\Unity.exe のダミーを作り、exeパスを返す。"""
    exe = os.path.join(root, version, "Editor", "Unity.exe")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    with open(exe, "wb") as f:
        f.write(b"MZ fake")
    return exe


class _TmpEnvCase(unittest.TestCase):
    """test_dep_resolver.py の _TmpEnvCase と同構成(実環境を一切見ない)。

    self.tmp は tempfile.mkdtemp() が返す実際の一時ディレクトリで、実運用の
    非標準ドライブ・個人フォルダ名配下のパスと同じ性質(user profile配下相当)
    を持つ。したがってこの配下の絶対パスがtrailに出ないことを確認すれば、
    「非標準パスでも生パスが漏れない」ことの実証になる。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="d2p_resolver_privacy_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake_drive = os.path.join(self.tmp, "FakeDriveD", "UnityEditors")
        self.appdata = os.path.join(self.tmp, "appdata")
        self.hubdir = os.path.join(self.appdata, "UnityHub")
        os.makedirs(self.hubdir, exist_ok=True)
        self.settings = os.path.join(self.tmp, "settings_unityeditor.txt")
        self.empty_hub_root = os.path.join(self.tmp, "no_such_hub_root")

    def kwargs(self, **over):
        kw = dict(appdata=self.appdata, hub_roots=[self.empty_hub_root],
                  settings_path=self.settings, env={})
        kw.update(over)
        return kw

    def write_editors_v2(self, entries):
        data = {"schema_version": "2",
                "data": [{"version": v, "location": [p], "manual": False}
                         for v, p in entries]}
        with open(os.path.join(self.hubdir, "editors-v2.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f)


class TestTrailPrivacySuccessPath(_TmpEnvCase):

    def test_nonstandard_path_trail_is_masked(self):
        """赤→緑: 標準外パス(tempdir配下)を解決させても、trailに生の絶対パス
        (self.tmp・self.fake_drive)が一切出ない。診断に要るファイル名・
        バージョン文字列は引き続き残る。"""
        exe = _make_fake_editor(self.fake_drive, "2022.3.9f1")
        self.write_editors_v2([("2022.3.9f1", exe)])
        res = resolve_unity_editor(project_version="2022.3.9f1", **self.kwargs())
        joined = "\n".join(dep_resolver.format_trail(res.trail))
        self.assertNotIn(self.tmp, joined)
        self.assertNotIn(self.fake_drive, joined)
        # 診断価値(ファイル名・バージョン)は失われていない
        self.assertIn("Unity.exe", joined)
        self.assertIn("2022.3.9f1", joined)
        # 選ばれた実パスそのもの(Resolution.path)は機能上不変(生パスのまま)
        self.assertEqual(res.path, os.path.normpath(exe))

    def test_approot_relative_path_still_shown(self):
        """approot配下(settings_unityeditor.txt)は相対パスとして残る
        (factifyのbases一致ケース。生の個人パスではないので隠す必要が無い)。"""
        settings_path = os.path.join(dep_resolver._APP_ROOT,
                                      dep_resolver.UNITY_SETTINGS_BASENAME)
        with self.assertRaises(DependencyNotFoundError) as ctx:
            resolve_unity_editor(project_version="2022.3.22f1",
                                 **self.kwargs(settings_path=settings_path))
        msg = str(ctx.exception)
        # settings.txtが存在しない前提のtrail行では basename が出る
        self.assertIn(dep_resolver.UNITY_SETTINGS_BASENAME, msg)


class TestTrailPrivacyFailurePath(_TmpEnvCase):

    def test_failure_message_trail_is_masked(self):
        """失敗経路(DependencyNotFoundError)でもtrailは同様にマスクされる。
        (guidance文中のsettings_pathはユーザーへの保存先案内として機能上
        必要なため対象外。ここではtrail部分のみを検証する)。"""
        with self.assertRaises(DependencyNotFoundError) as ctx:
            resolve_unity_editor(project_version="2022.3.22f1", **self.kwargs())
        msg = str(ctx.exception)
        self.assertNotIn(self.hubdir, msg)
        self.assertNotIn(self.empty_hub_root, msg)
        self.assertNotIn(os.path.join(self.appdata, "UnityHub", "editors-v2.json"), msg)


class TestNegativeControl(_TmpEnvCase):

    def test_broken_masking_is_detected(self):
        """負の対照: 伏字化(_factify)を無効化(素通しへ差し替え)すると生パスが
        漏れることを確認する。これは「本試験が実際にマスク処理の有無を検出
        できる」ことの証明であり、伏字化ロジックが将来壊れたときに
        test_nonstandard_path_trail_is_masked が確実に赤くなることの裏付け。"""
        exe = _make_fake_editor(self.fake_drive, "2022.3.9f1")
        self.write_editors_v2([("2022.3.9f1", exe)])

        original_factify = dep_resolver._factify
        dep_resolver._factify = lambda p, bases=(): p  # 伏字化を無力化(素通し)
        try:
            res = resolve_unity_editor(project_version="2022.3.9f1", **self.kwargs())
            joined = "\n".join(dep_resolver.format_trail(res.trail))
            # 壊すと生パスが漏れる = このテスト観点が有効であることの証明
            self.assertIn(self.fake_drive, joined)
        finally:
            dep_resolver._factify = original_factify

        # 元に戻した状態では再びマスクされる(後始末の確認を兼ねる)
        res2 = resolve_unity_editor(project_version="2022.3.9f1", **self.kwargs())
        joined2 = "\n".join(dep_resolver.format_trail(res2.trail))
        self.assertNotIn(self.fake_drive, joined2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
