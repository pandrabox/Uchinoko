# -*- coding: utf-8 -*-
"""pipeline\\py\\dep_resolver.py のユニットテスト(dev#22 / WP resolver)。

実行: python tests\\resolver\\test_dep_resolver.py  (stdlib unittestのみ。pytestでも収集可)

受入ゲート対応:
  - 偽のeditors-v2.json(標準外ドライブ相当のパス+複数パッチ版)からの発見
  - 手動指定(設定ファイル/環境変数)の最優先
  - 台帳なし時に探索trailを含む失敗情報が返ること
  - 負の対照: どの戦略にも該当しない環境で「探した場所一覧+手動指定案内」が出ること
  - 実機: このマシンの実Unityが発見されること(環境依存クラス、無い環境ではskip)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "pipeline", "py"))

import dep_resolver  # noqa: E402
from dep_resolver import (  # noqa: E402
    DependencyNotFoundError, resolve, resolve_unity_editor)

RESOLVER_PY = os.path.join(_REPO, "pipeline", "py", "dep_resolver.py")


def _make_fake_editor(root, version):
    """<root>\\<version>\\Editor\\Unity.exe のダミーを作り、exeパスを返す。"""
    exe = os.path.join(root, version, "Editor", "Unity.exe")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    with open(exe, "wb") as f:
        f.write(b"MZ fake")
    return exe


class _TmpEnvCase(unittest.TestCase):
    """一時領域に偽の appdata / hubルート / settings を組み立てる土台。

    実環境(本物の%APPDATA%等)を一切見ないよう、env={} を注入し、
    appdata / hub_roots / settings_path を必ず明示指定する。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="d2p_resolver_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # 「標準外ドライブ(D:\相当)」: C:\Program Files系ともHub既定とも無関係な場所
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
        """entries: [(version, exe_path)] → editors-v2.json(dataが配列の形状)"""
        data = {"schema_version": "2",
                "data": [{"version": v, "location": [p], "manual": False}
                         for v, p in entries]}
        with open(os.path.join(self.hubdir, "editors-v2.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f)

    def write_editors_json_map(self, entries):
        """entries: [(version, exe_path)] → editors.json(バージョンをキーにしたmap形状)"""
        data = {v: {"version": v, "location": p, "manual": True} for v, p in entries}
        with open(os.path.join(self.hubdir, "editors.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f)


class TestLedgerDiscovery(_TmpEnvCase):

    def test_editors_v2_nonstandard_drive_newest_patch(self):
        """受入: 標準外ドライブ相当+複数パッチ版 → family内最新パッチが選ばれる。"""
        old = _make_fake_editor(self.fake_drive, "2022.3.5f1")
        new = _make_fake_editor(self.fake_drive, "2022.3.40f1")
        self.write_editors_v2([("2022.3.5f1", old), ("2022.3.40f1", new)])
        res = resolve_unity_editor(project_version="2022.3.22f1", **self.kwargs())
        self.assertEqual(res.path, os.path.normpath(new))
        self.assertEqual(res.version, "2022.3.40f1")
        self.assertEqual(res.strategy, "hub-ledger")
        # 成功時もtrailに全候補が残る
        joined = "\n".join(dep_resolver.format_trail(res.trail))
        self.assertIn("2022.3.5f1", joined)
        self.assertIn("2022.3.40f1", joined)

    def test_exact_project_version_preferred(self):
        older = _make_fake_editor(self.fake_drive, "2022.3.22f1")
        newer = _make_fake_editor(self.fake_drive, "2022.3.40f1")
        self.write_editors_v2([("2022.3.22f1", older), ("2022.3.40f1", newer)])
        res = resolve_unity_editor(project_version="2022.3.22f1", **self.kwargs())
        self.assertEqual(res.path, os.path.normpath(older))
        self.assertEqual(res.version, "2022.3.22f1")

    def test_old_map_shape_editors_json(self):
        exe = _make_fake_editor(self.fake_drive, "2022.3.10f1")
        self.write_editors_json_map([("2022.3.10f1", exe)])
        res = resolve_unity_editor(project_version=None, **self.kwargs())
        self.assertEqual(res.path, os.path.normpath(exe))

    def test_out_of_family_rejected_with_verdict(self):
        exe = _make_fake_editor(self.fake_drive, "2019.4.31f1")
        self.write_editors_v2([("2019.4.31f1", exe)])
        with self.assertRaises(DependencyNotFoundError) as ctx:
            resolve_unity_editor(project_version="2022.3.22f1", **self.kwargs())
        msg = str(ctx.exception)
        self.assertIn("2019.4.31f1", msg)
        self.assertIn("not in supported family 2022.3.x", msg)

    def test_listed_but_missing_on_disk_skipped(self):
        """台帳に載っているがexe実体が無い(移動/アンインストール済み)は候補にしない。"""
        ghost = os.path.join(self.fake_drive, "2022.3.9f1", "Editor", "Unity.exe")
        real = _make_fake_editor(self.fake_drive, "2022.3.8f1")
        self.write_editors_v2([("2022.3.9f1", ghost), ("2022.3.8f1", real)])
        res = resolve_unity_editor(project_version=None, **self.kwargs())
        self.assertEqual(res.path, os.path.normpath(real))
        joined = "\n".join(dep_resolver.format_trail(res.trail))
        self.assertIn("missing on disk", joined)

    def test_hub_root_env_override(self):
        """D2P_UNITY_HUB_ROOT で既知パス走査ルートを上書きできる(hub_roots未指定時)。"""
        exe = _make_fake_editor(self.fake_drive, "2022.3.12f1")
        res = resolve_unity_editor(
            **self.kwargs(hub_roots=None,
                          env={"D2P_UNITY_HUB_ROOT": self.fake_drive}))
        self.assertEqual(res.path, os.path.normpath(exe))
        self.assertEqual(res.strategy, "known-paths")

    def test_secondary_install_path(self):
        sec_root = os.path.join(self.tmp, "SecondaryInstalls")
        exe = _make_fake_editor(sec_root, "2022.3.15f1")
        with open(os.path.join(self.hubdir, "secondaryInstallPath.json"), "w",
                  encoding="utf-8") as f:
            json.dump(sec_root, f)
        res = resolve_unity_editor(project_version=None, **self.kwargs())
        self.assertEqual(res.path, os.path.normpath(exe))
        self.assertEqual(res.strategy, "hub-secondary")


class TestManualOverride(_TmpEnvCase):

    def test_settings_file_wins_over_ledger(self):
        """受入: 手動指定(設定ファイル)が台帳より最優先。"""
        ledger_exe = _make_fake_editor(self.fake_drive, "2022.3.40f1")
        self.write_editors_v2([("2022.3.40f1", ledger_exe)])
        manual_exe = _make_fake_editor(os.path.join(self.tmp, "Manual"), "2022.3.1f1")
        with open(self.settings, "w", encoding="utf-8") as f:
            f.write(manual_exe + "\n")
        res = resolve_unity_editor(project_version="2022.3.40f1", **self.kwargs())
        self.assertEqual(res.path, os.path.normpath(manual_exe))
        self.assertEqual(res.strategy, "manual-settings")

    def test_settings_accepts_editor_root_dir(self):
        exe = _make_fake_editor(os.path.join(self.tmp, "Manual"), "2022.3.2f1")
        root_dir = os.path.dirname(os.path.dirname(exe))  # <...>\2022.3.2f1
        with open(self.settings, "w", encoding="utf-8") as f:
            f.write(root_dir + "\n")
        res = resolve_unity_editor(**self.kwargs())
        self.assertEqual(res.path, os.path.normpath(exe))

    def test_env_var_wins_over_ledger(self):
        ledger_exe = _make_fake_editor(self.fake_drive, "2022.3.40f1")
        self.write_editors_v2([("2022.3.40f1", ledger_exe)])
        manual_exe = _make_fake_editor(os.path.join(self.tmp, "EnvManual"), "2022.3.3f1")
        res = resolve_unity_editor(
            **self.kwargs(env={"D2P_UNITY_EDITOR": manual_exe}))
        self.assertEqual(res.path, os.path.normpath(manual_exe))
        self.assertEqual(res.strategy, "manual-env")

    def test_broken_settings_falls_through_with_verdict(self):
        """設定ファイルの指すパスが無い → 自動発見へ進み、判定はtrailに残る。"""
        with open(self.settings, "w", encoding="utf-8") as f:
            f.write(r"X:\no\such\Unity.exe" + "\n")
        exe = _make_fake_editor(self.fake_drive, "2022.3.7f1")
        self.write_editors_v2([("2022.3.7f1", exe)])
        res = resolve_unity_editor(**self.kwargs())
        self.assertEqual(res.path, os.path.normpath(exe))
        joined = "\n".join(dep_resolver.format_trail(res.trail))
        self.assertIn("but Unity.exe not found there", joined)


class TestNotFound(_TmpEnvCase):

    def test_no_ledger_failure_carries_trail(self):
        """受入: 台帳なし → 探索trailを含む構造化された失敗情報。"""
        with self.assertRaises(DependencyNotFoundError) as ctx:
            resolve_unity_editor(project_version="2022.3.22f1", **self.kwargs())
        e = ctx.exception
        self.assertTrue(e.trail, "trailが空")
        sources = {c.source for c in e.trail}
        # 全戦略が試行されたことがtrailから機械判定できる
        for expected in ("manual-settings", "hub-ledger", "hub-secondary", "known-paths"):
            self.assertIn(expected, sources)

    def test_negative_control_message_lists_places_and_manual_howto(self):
        """負の対照: 行き止まりエラーではなく「探した場所一覧+手動指定案内」。

        dev#325: trail(探索履歴)は生パスではなくpath_privacy.factify済みで
        出るようになった(tmpの実体パスはユーザー環境のuser profile配下相当
        なので、そのままだと個人情報漏洩になる)。「探した場所が分かる」という
        本来の検証意図はファイル名ベースの照合に置き換え、かつ生パスの
        プレフィックス(self.tmp)が一切出ないことを合わせて確認する
        (=これ自体がdev#325の赤→緑を兼ねる)。"""
        with self.assertRaises(DependencyNotFoundError) as ctx:
            resolve_unity_editor(project_version="2022.3.22f1", **self.kwargs())
        msg = str(ctx.exception)
        # 探した場所が(ファイル名として)列挙されている
        self.assertIn("editors-v2.json", msg)
        self.assertIn("editors.json", msg)
        self.assertIn(os.path.basename(self.empty_hub_root), msg)
        # dev#325: 生の一時ディレクトリパス(個人環境のuser profile配下相当)は
        # trail部分(探索履歴の各行)に一切出ない。guidance文言(末尾の手動指定案内)は
        # settings_pathの実パスを案内する必要があるため対象外(下記で別途検証)。
        self.assertNotIn(self.hubdir, msg)
        self.assertNotIn(self.empty_hub_root, msg)
        # 手動指定の方法(設定ファイルのフルパス+書き方の例+環境変数)が案内されている。
        # settings_pathはguidance文言側(Candidate.format()を経由しない別経路)が
        # 案内するために必要な生パスなので、こちらは引き続き非マスクのまま。
        self.assertIn(self.settings, msg)
        self.assertIn("settings_unityeditor", msg)
        self.assertIn("D2P_UNITY_EDITOR", msg)
        self.assertIn("Editor\\Unity.exe", msg)  # 書き方の例

    def test_unknown_dependency_name(self):
        with self.assertRaises(ValueError):
            resolve("no_such_dependency")


class TestCli(_TmpEnvCase):
    """export_from_unity.ps1 が読むCLIマーカー(D2P_RESOLVED / D2P_RESOLVE_FAILED)。"""

    def _run(self, *extra):
        cmd = [sys.executable, RESOLVER_PY, "unity_editor",
               "--appdata", self.appdata,
               "--hub-root", self.empty_hub_root,
               "--settings", self.settings] + list(extra)
        env = dict(os.environ)
        env.pop("D2P_UNITY_EDITOR", None)
        env.pop("D2P_UNITY_HUB_ROOT", None)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)

    def test_cli_success_marker(self):
        exe = _make_fake_editor(self.fake_drive, "2022.3.30f1")
        self.write_editors_v2([("2022.3.30f1", exe)])
        p = self._run("--project-version", "2022.3.30f1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        lines = [l for l in p.stdout.splitlines() if l.startswith("D2P_RESOLVED: ")]
        self.assertEqual(len(lines), 1, p.stdout)
        self.assertEqual(lines[0][len("D2P_RESOLVED: "):],
                         os.path.normpath(exe))

    def test_cli_failure_marker_and_trail(self):
        p = self._run("--project-version", "2022.3.22f1")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("D2P_RESOLVE_FAILED", p.stdout)
        self.assertIn("[dep_resolver]", p.stdout)
        self.assertNotIn("D2P_RESOLVED: ", p.stdout)


_REAL_HUB = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         "Unity", "Hub", "Editor")
_REAL_LEDGER = os.path.join(os.environ.get("APPDATA", ""), "UnityHub")


@unittest.skipUnless(os.path.isdir(_REAL_HUB) or os.path.isdir(_REAL_LEDGER),
                     "この環境にUnity Hubの痕跡が無い")
class TestRealMachine(unittest.TestCase):
    """受入: 実機でこのマシンの実Unity(2022.3系)が発見されること。"""

    def test_real_unity_found(self):
        res = resolve_unity_editor(project_version="2022.3.22f1")
        self.assertTrue(os.path.isfile(res.path), res.path)
        self.assertTrue(res.path.lower().endswith("unity.exe"), res.path)
        self.assertTrue((res.version or "").startswith("2022.3."), res.version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
