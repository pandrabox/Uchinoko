# -*- coding: utf-8 -*-
"""dev#288 WP-UXIMPL(2026-07-30)の単体試験: 進捗の見かけ上の停滞を解消する
提案2(フル変換パスでもPhase1完了=39%到達時にプレビューを早期反映)と
提案3(96%ラベルを実態=preflight完了済みの事後表示に合う文言へ変更)の
C#側(app\\DiveToPalworld.cs)の単体試験+負の対照。

背景: work\\speed_mission\\ux\\PROPOSAL.md 2.2節。従来は`LoadPreviews(jobDir)`が
`OnPipelineDone()`(プロセス終了=全工程完了後)からしか呼ばれておらず、
Phase1完了(39%)時点で画像は既に書き終わっているのに、フル変換パスでは
30〜59秒待たないと画面に反映されなかった。`AppendLog()`の##PROGRESS##
処理へ「pct>=39かつ未読込なら1回だけLoadPreviews()」を追加した。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)
なので、既存の --check-warm-startup 等と同じ手口を踏襲する:
ビルド済みexeに `--check-progress-relay <outDir>` という隠しCLIモードを仕込み
(画面もネットワークI/Oも実プロセス起動も一切使わない)、app\\DiveToPalworld.cs内の
RunProgressRelayChecks() が次の5ケースを実行して期待値と突き合わせる:

  case1(正): pct=39到達でLoadPreviews()が実際に呼ばれ、previewFront/Side.Imageが
    非nullになること。
  case2(正、1回だけ): pct=39到達後、別のpct(58)がもう一度来てもLoadPreviews()を
    再度呼ばない(Imageの参照が変わらないことで確認)。
  case3(負の対照①、境界): pct=38(39未満)ではLoadPreviews()を呼ばないこと
    (常時読み込みの無条件実装だと偶然パスしてしまう検査の空洞化を防ぐ)。
  case4(負の対照②、既存ガードの回帰確認): runningProc==nullなら##PROGRESS##処理
    自体が丸ごとskipされる既存仕様(2026-07-26以前)が、今回の改修後も
    壊れていないこと。
  case5(提案3): 96%の新ラベルがstatusLabelへ正しく整形されること。

pytestからも `python tests/shipcheck/test_progress_relay_cs.py` からも実行できる
(他のtests\\shipcheck\\*_cs.pyと同じ構成、dev#274のmkdtemp流儀で
実行ごとに一意なディレクトリを使う)。

変換出力(pak本体)には一切触れない。Layers-Affected: none。
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_DIR = os.path.join(REPO_ROOT, "app")


def _build_exe(build_dir):
    build_ps1 = os.path.join(APP_DIR, "build_app.ps1")
    out_exe = os.path.join(build_dir, "Uchinoko_progress_relay_check.exe")
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
def progress_relay_exe():
    build_dir = tempfile.mkdtemp(prefix="d2p_progress_relay_cs_test_")
    try:
        ok, exe_path, detail = _build_exe(build_dir)
        if not ok:
            pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
        yield exe_path
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def test_progress_relay_wiring_and_negative_control(progress_relay_exe):
    out_dir = os.path.join(os.path.dirname(progress_relay_exe), "out")
    proc = subprocess.run(
        [progress_relay_exe, "--check-progress-relay", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "progress_relay_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "進捗中間マーカー+早期プレビュー反映の単体表がFAILした(rc={}):\n"
        "stdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "PROGRESS_RELAY_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
