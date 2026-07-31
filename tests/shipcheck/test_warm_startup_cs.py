# -*- coding: utf-8 -*-
"""dev#288(2026-07-30): 起動時warm処理(app\\DiveToPalworld.cs)の単体試験+負の対照。

追記(2026-07-31、SignPath対応): この検査(実行時C#コンパイルを含む)は出荷exe
(Uchinoko.exe)から devtools\\shipcheck_src\\warm_startup_check.cs へ移設した
(セキュリティ監査の指摘、MITRE ATT&CK T1027.004相当の能力を出荷物から除去)。このテストは
app\\build_app.ps1(出荷ビルド)ではなく devtools\\shipcheck_src\\
build_warm_startup_check.py(devtools専用ビルド、app\\DiveToPalworld.cs と
warm_startup_check.cs を一緒にコンパイルする)を使う。

背景: 指揮者ミッション「変換の最適・最高速度化」(dev#288)の一環。実測
(work\\speed_mission\\measure\\NOTES.md)でstep01(VRMインポート)の所要が同一
セッション内で3〜18秒とブレることが判明し、OSディスクキャッシュ未ウォームが
疑われた。既存の WarmSharedCacheOnStartup()(U54 WP-B)は起動時にバニラ準備+
ライブテンプレートを事前構築するが、これは純Python処理(extract_vanilla.py/
live_template.pyはbpy importなし)であり、Blender本体(blender.exe)のexe/DLL群は
一切起動しない——つまりOSディスクキャッシュのウォームには寄与しない。

このWPで追加した WarmBlenderProcessOnStartup() は、Blenderが使える状態に
なった直後、無害な最小起動(--background --python-expr "pass"、即終了)を
1回だけバックグラウンドで撃ちっぱなしにし、以後の実step01起動でOSファイル
キャッシュが効くことを狙う。既存のWarmSharedCacheOnStartup()についても、
以前は早期returnの各分岐(blenderReady=false/blender.exe未検出/pak未解決等)が
完全に無音だった("実装した"と"効いている"は別、を自己検証できなかった)ため、
このWPでwarm_startup.logへの理由ログを追加した(UIには一切出さない、既存の
「失敗は無視」要件は不変)。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)
なので、既存の --check-blender-setup-decision / --check-i18n と同じ手口を踏襲する:
ビルド済みexeに `--check-warm-startup <outDir>` という隠しCLIモードを仕込み
(画面は一切出さない、実Blender・実Palworld・実ネットワーク不要)、
devtools\\shipcheck_src\\warm_startup_check.cs 内の RunWarmStartupChecks()
(app\\DiveToPalworld.cs の partial class MainForm を拡張)が次の4ケースを実行して
期待値と突き合わせる:

  case1(無音退行の検知): blenderReady=falseの状態でWarmBlenderProcessOnStartup()/
    WarmSharedCacheOnStartup()を呼ぶと、両方ともwarm_startup.logへskip理由が
    記録され、かつ実プロセスは1つも起動しないこと(warm_blender.log/warm_cache.log
    が作られない)。
  case2(「変換中は実行しない」の直接検査): runningProc(変換本体)が非nullなら
    WarmBlenderProcessOnStartup()はlaunchせずskipすること。
  case3(正例、実配線の確認): blenderReady=true・runningProc=nullで、
    FindBlender()が実際に解決する場所に無害な代役実行ファイル
    (この検査専用にcsc.exeでその場ビルドする最小スタブ。即終了・非対話)を
    置くと、実際にプロセスが起動し、標準出力/エラーのリダイレクトを含めて
    完了ログが残ること。
  case4(負の対照: プリウォーム失敗が変換を壊さない): 代役を実行不能な不正exe
    (妥当なPEではないダミーバイト列)に差し替えると、Process.Start()自体が
    例外を投げるが、WarmBlenderProcessOnStartup()の外側try/catchで吸収され、
    例外が呼び出し元まで伝播しないこと・理由がログへ残ること・その後の
    後続warm呼び出しが正常に完了すること(=失敗が状態を壊さず伝播しない)。

pytestからも `python tests/shipcheck/test_warm_startup_cs.py` からも実行できる
(tests\\shipcheck\\test_blender_setup_decision_cs.py と同じ構成)。
"""
import os
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
BUILD_SCRIPT = os.path.join(REPO_ROOT, "devtools", "shipcheck_src", "build_warm_startup_check.py")


def _build_exe(build_dir):
    out_exe = os.path.join(build_dir, "WarmStartupCheck.exe")
    os.makedirs(build_dir, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, BUILD_SCRIPT, out_exe],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120,
    )
    ok = proc.returncode == 0 and os.path.isfile(out_exe)
    detail = "rc={}\n{}".format(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
    return ok, out_exe, detail


@pytest.fixture(scope="module")
def warm_startup_exe():
    build_dir = os.path.join(tempfile.gettempdir(), "d2p_warm_startup_cs_test")
    ok, exe_path, detail = _build_exe(build_dir)
    if not ok:
        pytest.fail("devtools\\shipcheck_src\\build_warm_startup_check.py でのビルドに失敗した:\n" + detail)
    return exe_path


def test_warm_startup_wiring_and_negative_control(warm_startup_exe):
    out_dir = os.path.join(tempfile.gettempdir(), "d2p_warm_startup_cs_test", "out")
    proc = subprocess.run(
        [warm_startup_exe, "--check-warm-startup", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    detail_path = os.path.join(out_dir, "warm_startup_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "warm-startup配線試験がFAILした(rc={}):\nstdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "WARM_STARTUP_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
