# -*- coding: utf-8 -*-
"""ランチャー(DiveToPalworldLauncher、ApplyEngine静的クラス)の単体試験。

2026-07-31: 以前はランチャーのソースがbuild\\make_dist.ps1内の
ヒアストリング($LauncherSrc)として埋め込まれ、実体の.csファイルがリポジトリに
存在しなかった(SignPath Foundationの無料コード署名審査が要求する「ソースから
透明に再現されるビルド」に反するため)。app\\Launcher.cs という実ファイルへ
抽出し、build\\make_dist.ps1 はそれを読んでコンパイルするだけになった。本試験も
それに合わせ、正規表現によるヒアドキュメント抽出ではなく app\\Launcher.cs を
直接読むように更新した(ApplyEngineの検査ロジック自体は無変更)。

tests\\shipcheck\\test_self_update_cs.py(app\\DiveToPalworld.cs側)と同じ手口を踏襲し、
app\\Launcher.cs をcsc.exeで直接コンパイルし、`--check-apply-engine <outDir>` という
隠しCLIモード(画面もネットワークI/Oも実際のランチャー起動も一切使わない)で、
擬似ディレクトリツリーによる5対照を検査する:

  case1 … 正常適用(allowlist内のみ変わる・ユーザーデータ不変)
  case2 … 途中失敗(フォールト注入)-> 全か無かで復帰、staging側も何も消費されない
  case3 … Tier1自動ロールバック: 起動確認シグナル(verify_pending.json)未達 -> 次回起動で自動復帰
  case4 … Tier1: 起動確認シグナル達成 -> 復帰しない(新版のまま)
  case5 … Tier2手動ロールバック(revert:trueのpending.json)-> 前版へ復帰、再度戻せる状態になる

いずれのケースもユーザーデータ(work\\/settings_lastvrm.txt/assets\\tools\\相当のダミー)が
一切変化しないことを併せて検査する(design書6節「ユーザーデータ非破壊の総合確認」)。

pytestからも `python tests/shipcheck/test_apply_engine_cs.py` からも実行できる
(tests\\shipcheck\\test_self_update_cs.py と同じ構成)。

dev#274(2026-07-30): test_self_update_cs.pyと同型の非冪等(%TEMP%配下の固定名の
build_dir/out_dirを実行間で使い回す)がないか監査し、同じ流儀(tempfile.mkdtemp()で
実行ごとに一意なディレクトリを作り、モジュール終了時にshutil.rmtreeで片付ける)に揃えた。

追記(2026-07-31): app\\Launcher.cs(ここでコンパイル・検査
しているApplyEngine)は、ランチャーのAV誤検知が実測で判明したため配布物からは
除去された(build\\make_dist.ps1はもうこのファイルを読まない)。この試験は
「削除するか、非アクティブなまま残すか」という検討への回答として、①削除ではなく
②app\\Launcher.cs自体を温存する側を選んだことに伴い、そのまま残してある——
将来、自己更新の自己再起動化として復活する場合に、この単体表がすぐ使える
回帰試験として機能する。
**このテストがPASSしても、現在出荷される配布物にApplyEngineは含まれない**
(このファイルはapp\\Launcher.csを直接csc.exeでコンパイルしてテストしており、
build\\make_dist.ps1経由の配布物ビルドを検査していないため)。
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
LAUNCHER_CS = os.path.join(REPO_ROOT, "app", "Launcher.cs")


def _read_launcher_source():
    if not os.path.isfile(LAUNCHER_CS):
        pytest.fail("app\\Launcher.cs が見つからない(ソース抽出が"
                     "未完了、またはリグレッション)")
    with open(LAUNCHER_CS, encoding="utf-8-sig") as f:
        return f.read()


def _csc_path():
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")


@pytest.fixture(scope="module")
def launcher_exe():
    csc = _csc_path()
    if not os.path.isfile(csc):
        pytest.skip("csc.exe (.NET Framework 4.8) が見つからない環境")
    _read_launcher_source()   # 存在チェック(内容自体はcsc.exeに直接渡すので未使用)
    build_dir = tempfile.mkdtemp(prefix="d2p_apply_engine_cs_test_")
    try:
        # app\Launcher.cs は既にBOM付きUTF-8でリポジトリに保存されて
        # いるため、旧実装のような一時コピー生成(ヒアドキュメント文字列→BOM付与)は
        # 不要になった。csc.exeへ直接渡す
        src_path = LAUNCHER_CS
        out_path = os.path.join(build_dir, "Launcher_test.exe")
        proc = subprocess.run(
            [csc, "/nologo", "/target:winexe", "/out:" + out_path, "/optimize+",
             "/r:System.dll", "/r:System.Windows.Forms.dll", src_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        ok = proc.returncode == 0 and os.path.isfile(out_path)
        if not ok:
            pytest.fail("build\\make_dist.ps1 埋め込みランチャーのコンパイルに失敗した:\n"
                         "rc={}\n{}".format(proc.returncode, (proc.stdout or "") + (proc.stderr or "")))
        yield out_path
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def test_apply_engine_unit_table(launcher_exe):
    out_dir = os.path.join(os.path.dirname(launcher_exe), "out")
    proc = subprocess.run(
        [launcher_exe, "--check-apply-engine", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "apply_engine_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "ApplyEngine単体表がFAILした(rc={}):\nstdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "APPLY_ENGINE_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
