# -*- coding: utf-8 -*-
"""wp878991(dev#87/#89/#91): app\\DiveToPalworld.cs 側の判定ロジック
(PalworldCompat静的クラス)の単体試験。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)
なので、既存の --check-i18n / --emit-wiring と同じ手口を踏襲する: ビルド済みexeに
`--check-palworld-compat <outDir>` という隠しCLIモードを仕込み(画面は一切出さない)、
そこで PalworldCompat.Evaluate() / MergeKnownGood() / ParseKnownVersions() 等の
判定ロジックを10ケースの単体表として検査させ、結果ファイルとexit codeをpytestから
subprocessで確認する。実機のPalworldインストールもBlenderも不要、数秒で終わる。

検査しているケース(app\\DiveToPalworld.cs の CheckPalworldCompatLogic()参照):
  case1/2 … 既知バージョン一致(同梱/リモートのマージ)
  case3   … 抽出物マニフェスト一致(dev#91の核心、版番号は未知でもよい)
  case4   … 負の対照①: 未知版+抽出物マニフェストも不一致 -> 警告する
  case5   … マニフェスト未取得(null) -> 警告する側に倒れる
  case6   … 判定不能(Paksが見つからない) -> 警告しない
  case7   … dev#89のオフラインフォールバック(bundledのみ)
  case8   … 負の対照②: 同梱リストが空(改変/未知化)+オフライン -> 警告する
  case9   … 診断ログ用の1行(dev#87)が検出値・対応リストの両方を数字入りで残す
  case10  … JsonObj()の波括弧バランス抽出(dev#89のversions.json補助フィールド)

pytestからも `python tests/shipcheck/test_palworld_compat_cs.py` からも実行できる
(tests\\shipcheck\\gui_wiring_check.py と同じ構成)。
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
    out_exe = os.path.join(build_dir, "Uchinoko_palworld_compat_check.exe")
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
def compat_exe():
    build_dir = os.path.join(tempfile.gettempdir(), "d2p_palworld_compat_cs_test")
    ok, exe_path, detail = _build_exe(build_dir)
    if not ok:
        pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
    return exe_path


def test_palworld_compat_logic_unit_table(compat_exe):
    out_dir = os.path.join(tempfile.gettempdir(), "d2p_palworld_compat_cs_test", "out")
    proc = subprocess.run(
        [compat_exe, "--check-palworld-compat", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "palworld_compat_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "PalworldCompat単体表がFAILした(rc={}):\nstdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "PALWORLD_COMPAT_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
