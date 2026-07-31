# -*- coding: utf-8 -*-
"""dev#236: app\\DiveToPalworld.cs の DecideBlenderSetupAction() 単体試験。

背景: dev#236(オーナー裁定)「初回セットアップ(Blender等の取得)は起動時
バックグラウンドで実行し、ポップアップ・モーダルを出さない」に伴い、
BlenderSetupDialog(モーダル)を撤去し、EnsureBlenderReadyOnStartup()を
バックグラウンド化した。その際、「exeがあるか」「取得スクリプト
(ensure_blender.ps1)自体があるか」「-CheckOnlyの結果(マーカー有効性)」の
3つのbool入力から「何をすべきか」を決める分岐を、ファイルI/O・プロセス起動を
一切含まない純関数 DecideBlenderSetupAction() へ切り出した。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)
なので、既存の --check-i18n / --check-apply-language と同じ手口を踏襲する:
ビルド済みexeに `--check-blender-setup-decision <outDir>` という隠しCLIモードを
仕込み(画面は一切出さない)、全8通り(2^3)の入力組み合わせを総当たりして
期待値と突き合わせる。実Blender・実ネットワークは一切不要、数秒で終わる。

検査しているケース(app\\DiveToPalworld.cs の CheckBlenderSetupDecisionLogic()参照):
  - ensurePs1が無い(開発チェックアウト等) -> exeの有無だけで決まる
    (checkOnlyValidの値に関わらず結果が変わらないことも2ケースずつで確認)
  - ensurePs1がありexeもありcheckOnlyValid=true -> ReadyNoAction(即使える)
  - dev#230の核心にあたる負の対照: ensurePs1があり**exeはあるがcheckOnlyValid=false**
    (マーカー無効) -> NeedFullSetup(「exeがあるだけ」で即readyにしてはならない、
    という2026-07-27の退行修正がここで壊れていないことを確認する)
  - ensurePs1があってもexe自体が無ければ常にNeedFullSetup

pytestからも `python tests/shipcheck/test_blender_setup_decision_cs.py` からも
実行できる(tests\\shipcheck\\test_apply_language_cs.py と同じ構成)。
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
    out_exe = os.path.join(build_dir, "Uchinoko_blender_setup_decision_check.exe")
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
def decision_exe():
    build_dir = os.path.join(tempfile.gettempdir(), "d2p_blender_setup_decision_cs_test")
    ok, exe_path, detail = _build_exe(build_dir)
    if not ok:
        pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
    return exe_path


def test_blender_setup_decision_unit_table(decision_exe):
    out_dir = os.path.join(tempfile.gettempdir(), "d2p_blender_setup_decision_cs_test", "out")
    proc = subprocess.run(
        [decision_exe, "--check-blender-setup-decision", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "blender_setup_decision_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "DecideBlenderSetupAction単体表がFAILした(rc={}):\nstdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "BLENDER_SETUP_DECISION_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
