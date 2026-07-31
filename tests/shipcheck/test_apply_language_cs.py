# -*- coding: utf-8 -*-
"""dev#173: 言語切替の即時反映(ApplyLanguage)の単体試験。

背景: 以前のGUI(app\\DiveToPalworld.cs)は、言語コンボボックスを切り替えても
「設定を保存するだけ」で、実際の画面反映は次回起動時だった(dev#150系の実機テストで
発覚し、確認メッセージだけを選択直後の言語で見せる対処療法が入っていた)。
dev#173でこれを廃止し、選択した瞬間に画面そのもの(ウィンドウタイトル・
静的なText/Tooltip・ListViewの列見出し・こだわりトグルの▲▼付きラベル)を
差し替える ApplyLanguage() を実装した。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)
なので、既存の --check-i18n / --check-palworld-compat と同じ手口を踏襲する:
ビルド済みexeに `--check-apply-language <outDir>` という隠しCLIモードを仕込み
(画面は一切出さない。MainFormをヘッドレスに1個生成するだけ)、そこで
ApplyLanguage(Lang.En) / ApplyLanguage(Lang.Ja) の往復を実行し、登録済みの
全コントロール(RegisterI18nText/RegisterI18nTip経由)のText/Tooltipが実際に
Strings.Table の該当言語の値と一致することを検査する。

検査しているケース(app\\DiveToPalworld.cs の CheckApplyLanguageLogic()参照):
  - 登録数の厳密一致(1箇所でも RegisterI18nText/RegisterI18nTip の呼び出しが
    抜けると失敗する。閾値ではなく厳密一致にした理由と、2026-07-29に実際に
    convertButtonの登録漏れ1件を検出できることを確認した負の対照の記録は
    CheckApplyLanguageLogic() 内のコメント参照)
  - En切替後、登録済み全コントロールのText/Tooltipが英語辞書値と一致(正の対照)
  - 主要ボタン(convertButton等、フィールドとして直接参照できるもの)は登録簿経由の
    一般検査に加えてピンポイントでも確認(登録簿自体の取り違えの保険)
  - ウィンドウタイトル・pakListの列見出し・kodawariToggleの▲▼付きラベルも
    再適用されること
  - Ja切替後、同じコントロールが日本語辞書値へ戻ること(負の対照: 一度切り替えたら
    固着して戻らない退行の検出)
  - TipLanguageSwitch(5言語)に「次回起動時」相当の文言が残っていないこと
    (dev#173の裁定そのものが後退していないかの確認)

pytestからも `python tests/shipcheck/test_apply_language_cs.py` からも実行できる
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
    out_exe = os.path.join(build_dir, "Uchinoko_apply_language_check.exe")
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
def apply_language_exe():
    build_dir = os.path.join(tempfile.gettempdir(), "d2p_apply_language_cs_test")
    ok, exe_path, detail = _build_exe(build_dir)
    if not ok:
        pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
    return exe_path


def test_apply_language_unit_table(apply_language_exe):
    out_dir = os.path.join(tempfile.gettempdir(), "d2p_apply_language_cs_test", "out")
    # dev#317: hosted CI(windows-latest)でこの検査だけTimeoutExpiredしていた
    # (60秒/180秒どちらでも解消せず)。真因はタイムアウト不足ではなく、
    # ApplyLanguage()がUpdateAppliedStatus()経由でPaksDir()を呼び、自動探索に
    # 失敗するとFolderBrowserDialogをモーダル表示してユーザー入力を待つため
    # (app\DiveToPalworld.cs CheckApplyLanguageLogic()参照)。開発機では
    # Palworld実在/settings_paksdir.txt残存で自動探索が成功しダイアログへ
    # 到達しないが、hosted CIの新規checkoutはどちらも無くダイアログが非対話
    # プロセスを永久にブロックしていた。app\DiveToPalworld.cs側でダミー検体を
    # 用意しダイアログへ到達しないよう検査を隔離したため、他の同種チェック
    # (test_palworld_compat_cs.py/test_blender_setup_decision_cs.py)と同じ
    # 60秒予算に戻す。
    proc = subprocess.run(
        [apply_language_exe, "--check-apply-language", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "apply_language_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "ApplyLanguage単体表がFAILした(rc={}):\nstdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "APPLY_LANGUAGE_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
