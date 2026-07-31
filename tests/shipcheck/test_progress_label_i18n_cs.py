# -*- coding: utf-8 -*-
"""dev#304 裁定A(2026-07-30、WP-LABELI18N)の単体試験: 進捗ラベル(GUI下部
statusLabel、`##PROGRESS##`由来)の多言語化。

設計の先行検討: work\\speed_mission\\ux\\PROPOSAL.md §3提案4・§4。要点:
convert.ps1のハードコード英語文字列がstatusLabelへそのまま表示されていた
(GUI多言語化(dev#29)の対象から漏れていた)ため、Strings.ProgressLabels/
ProgressLabelTemplates という新しい辞書(Strings.Tableとは別、キーはラベル
文字列そのもの)を追加し、AppendLog()の##PROGRESS##処理でTranslateProgressLabel()
を通すようにした。未知ラベル(辞書に無いもの)は原文のまま表示するフォールバック
(ホワイトリストで無表示を作らない、ブラックリスト方式)。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)
なので、既存の --check-progress-relay(PR#307)と同じ手口を踏襲する:
ビルド済みexeに `--check-progress-label-i18n <outDir>` という隠しCLIモードを
仕込み(画面もネットワークI/Oも実プロセス起動も一切使わない)、
app\\DiveToPalworld.cs内の RunProgressLabelI18nChecks() が次のケースを実行して
期待値と突き合わせる:

  case1(完全性): ProgressLabels/ProgressLabelTemplatesの全エントリが5言語とも
    非空であること。
  case2(正): 既知ラベルが5言語それぞれで翻訳されること(enは原文と同一)。
  case3(正、動的テンプレート): 性別名などの可変部を含むラベルで、可変部は
    そのまま・静的部分だけ翻訳されること。
  case4(負の対照①): 辞書に無いラベルは原文のままフォールバックすること。
  case5(負の対照②): 辞書エントリを意図的に破壊(全言語空/短い配列/0要素配列)
    しても例外を投げず原文へフォールバックすること(検査自体がフォールバックの
    機能を検出できることの証明)。
  case6/7(統合): AppendLog()経由でstatusLabel.Textが実際に翻訳される
    (「実装した」と「効いている」の区別。既知ラベルは翻訳・未知ラベルは原文)。

pytestからも `python tests/shipcheck/test_progress_label_i18n_cs.py` からも
実行できる(tests\\shipcheck\\test_progress_relay_cs.py と同じ構成、
dev#274のmkdtemp流儀で実行ごとに一意なディレクトリを使う)。

進捗ラベルは画面表示のみで変換出力(pak本体)には一切触れない。
Layers-Affected: none。
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
    out_exe = os.path.join(build_dir, "Uchinoko_progress_label_i18n_check.exe")
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
def progress_label_i18n_exe():
    build_dir = tempfile.mkdtemp(prefix="d2p_progress_label_i18n_cs_test_")
    try:
        ok, exe_path, detail = _build_exe(build_dir)
        if not ok:
            pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
        yield exe_path
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def test_progress_label_i18n_wiring_and_negative_control(progress_label_i18n_exe):
    out_dir = os.path.join(os.path.dirname(progress_label_i18n_exe), "out")
    proc = subprocess.run(
        [progress_label_i18n_exe, "--check-progress-label-i18n", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "progress_label_i18n_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "進捗ラベル辞書化の単体表がFAILした(rc={}):\n"
        "stdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "PROGRESS_LABEL_I18N_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail
    # 受入ゲート「辞書化したラベル数」の記録確認(0件で通ってしまう検査の空洞化を防ぐ)
    assert "progress_label_count=19" in detail, (
        "辞書化ラベル数が期待(19)と異なる:\n" + detail)
    assert "progress_label_template_count=3" in detail, (
        "動的テンプレート数が期待(3)と異なる:\n" + detail)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
