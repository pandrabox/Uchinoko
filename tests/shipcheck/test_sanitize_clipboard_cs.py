# -*- coding: utf-8 -*-
"""dev#7: app\\DiveToPalworld.cs 側の SanitizeForClipboard 汎用ガードの単体試験。

背景: 実ユーザー報告4AL4M4GTで、既知パターン限定の伏字化(%USERPROFILE%等の完全一致・
既知の特殊フォルダのみ)をすり抜けて、非%USERPROFILE%ドライブの絶対パス
(Unity/VCC・インストール先・Steamライブラリ)が診断ログへそのまま漏れた。
三段構成の対応(work\\issue_zero\\i7\\NOTES.md)のうち、本試験はその最終防衛段
(SanitizeForClipboardへの汎用ガード追加)を検査する。

このリポジトリのGUIはcsc.exe直接コンパイル(NuGet/xUnit等のテストランナー無し)なので、
既存の --check-dist-channel 等と同じ手口を踏襲する: ビルド済みexeに
`--check-sanitize-clipboard <outDir>` という隠しCLIモードを仕込み(画面は一切出さない)、
SanitizeForClipboard() の単体表を検査させる。フィクスチャは全て架空の値
(実在の個人情報は使わない)。

検査しているケース(app\\DiveToPalworld.cs の CheckSanitizeForClipboardLogic()参照):
  case1  … %USERPROFILE%配下は従来どおりトークン化される(正の対照、無退行)
  case2  … SteamID64は従来どおりマスクされる(正の対照、無退行)
  case3  … 単語境界に一致するアカウント名の保険置換(正の対照、無退行)
  case4  … 【核心・dev#7】非%USERPROFILE%ドライブの絶対パス(架空のUnityプロジェクト
            パス)が生のまま残らないこと。旧実装はこれを一切マスクせず素通りしていた
  case4b … 【診断可用性】マスク後も拡張子(.prefab)などの原因切り分け情報が残ること
            (「伏字化の強化が診断能力を壊さないこと」の確認)
  case5  … 【核心・dev#7】UNCパス(架空のビルドサーバー共有パス)も同様にマスクされること
  case6  … 【負の対照】パスに見えない通常の文章・URLは誤って壊されないこと(誤検知防止)
  case7  … 【負の対照】空文字列・nullを渡しても例外にならないこと

負の対照(赤→緑の実証)はNOTES.md(work\\issue_zero\\i7\\NOTES.md)に、汎用ガード
(手順5)を一時的に無効化してビルド→case4/case4b/case5がFAILすることを確認した記録
(手順・出力とも)を残してある。

pytestからも `python tests/shipcheck/test_sanitize_clipboard_cs.py` からも実行できる
(tests\\shipcheck\\test_dist_channel_cs.py と同じ構成)。
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
    out_exe = os.path.join(build_dir, "Uchinoko_sanitize_clipboard_check.exe")
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
def sanitize_clipboard_exe():
    build_dir = os.path.join(tempfile.gettempdir(), "d2p_sanitize_clipboard_cs_test")
    ok, exe_path, detail = _build_exe(build_dir)
    if not ok:
        pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
    return exe_path


def test_sanitize_clipboard_logic_unit_table(sanitize_clipboard_exe):
    out_dir = os.path.join(tempfile.gettempdir(), "d2p_sanitize_clipboard_cs_test", "out")
    proc = subprocess.run(
        [sanitize_clipboard_exe, "--check-sanitize-clipboard", out_dir],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    detail_path = os.path.join(out_dir, "sanitize_clipboard_check.txt")
    detail = ""
    if os.path.isfile(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = f.read()
    assert proc.returncode == 0, (
        "SanitizeForClipboard単体表がFAILした(rc={}):\nstdout={!r}\nstderr={!r}\n{}".format(
            proc.returncode, proc.stdout, proc.stderr, detail))
    assert "SANITIZE_CLIPBOARD_CHECK_OK" in (proc.stdout or ""), (
        "期待した成功マーカーが出力に無い: {!r}".format(proc.stdout))
    assert "result=PASS" in detail, "詳細ファイルがPASSでない:\n" + detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
