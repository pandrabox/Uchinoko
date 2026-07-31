# -*- coding: utf-8 -*-
"""dev#260: app\\DiveToPalworld.cs 側の配布チャネル判定ロジックの単体試験。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)なので、
既存の --check-i18n / --check-palworld-compat と同じ手口を踏襲する: ビルド済みexeに
`--check-dist-channel <outDir>` という隠しCLIモードを仕込み(画面は一切出さない)、
NormalizeDistChannel() / ReadDistChannelFromFile() の単体表を検査させる。

検査しているケース(app\\DiveToPalworld.cs の CheckDistChannelLogic()参照):
  case1-4 … 既知チャネル(booth/itch/github/dev)の正規化、大小文字・前後空白を許容
  case5/6 … 空文字・null -> unknown(負の対照)
  case7   … 語彙に無い値(steam等)を断定しない(負の対照、誤ラベル防止)
  case8   … 壊れたマーカー内容(複数行)の部分一致を防ぐ(負の対照)
  case9   … 実ファイル読み取り経由の正の対照
  case10  … マーカーファイルが存在しない(=従来のcanonical zip)場合はunknown
             (受入条件の核心: 「マーカー無しzip=従来挙動でunknown表示」)

pytestからも `python tests/shipcheck/test_dist_channel_cs.py` からも実行できる
(tests\\shipcheck\\test_palworld_compat_cs.py と同じ構成)。
"""
import os
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_DIR = os.path.join(REPO_ROOT, "app")


def _build_exe(build_dir):
    build_ps1 = os.path.join(APP_DIR, "build_app.ps1")
    out_exe = os.path.join(build_dir, "Uchinoko_dist_channel_check.exe")
    os.makedirs(build_dir, exist_ok=True)
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-File", build_ps1, "-Out", out_exe],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120,
    )
    ok = proc.returncode == 0 and os.path.isfile(out_exe)
    detail = "rc={}\n{}".format(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
    return ok, out_exe, detail


@pytest.fixture(scope="module")
def dist_channel_exe():
    build_dir = os.path.join(tempfile.gettempdir(), "d2p_dist_channel_cs_test")
    ok, exe_path, detail = _build_exe(build_dir)
    if not ok:
        pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
    return exe_path


def test_dist_channel_logic_unit_table(dist_channel_exe):
    out_dir = os.path.join(tempfile.gettempdir(), "d2p_dist_channel_cs_test", "out")
    proc = subprocess.run(
        [dist_channel_exe, "--check-dist-channel", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "dist_channel_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "配布チャネル判定単体表がFAILした(rc={}):\nstdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "DIST_CHANNEL_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
