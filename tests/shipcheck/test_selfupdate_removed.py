# -*- coding: utf-8 -*-
"""2026-07-31(SignPath申請準備)の受入ゲート: 不活性だった自己更新の
ダウンロード・検証・展開・pending.json書き込み経路が復活しないことを検査する
回帰試験。

背景(詳細は開発側の記録を参照): 「今すぐ更新」ボタンは
CDN→GitHub Releasesの順でzipをダウンロードし、SHA256+サイズ検証、展開、
install_root\\_update\\pending.json への書き込みまでを行っていた。ところが
それを読んで実際にファイルを入れ替える適用エンジン(旧app\\Launcher.csの
ApplyEngine)は、2026-07-31のランチャー廃止で配布物から
既に除去されていた。つまり「ダウンロードして、検証して、ファイルを書いて、
何もしない」という不活性なコード(app\\DiveToPalworld.csのSelfUpdate静的クラス、
UpdateReleaseInfo/UpdateStageResult、HttpDownloadFile、ClearVerifyPendingSignal、
StartRevertUpdate等)だけが残っていた。これらを丸ごと削除し、
「今すぐ更新」ボタンはupdateLabelと同じく配布ページを開くだけに変更した。

この試験は2段構え:
  1) ソースの識別子スキャン(即座に終わる、ビルド不要)。
  2) ビルド済みexeのバイナリ文字列走査(ASCII/UTF-16LE)。.NETはメタデータヒープに
     型名・メソッド名をプレーンテキストで埋め込むため、`strings`相当の単純な
     走査で検知できる(FIX36の切り分け実験が使ったのと同じ手口)。

負の対照: 削除した識別子を一時的に含む文字列を検知ヘルパーへ与え、実際に
検知できることを確認する(スキャンロジック自体が壊れて何もかも見逃す事故を防ぐ)。
正の対照: 削除してはいけない機能(起動時のバージョン確認)の識別子が
ソース・バイナリの両方に残っていることを確認する。

Layers-Affected: none(変換出力には一切触れない、GUIのみ)。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_DIR = os.path.join(REPO_ROOT, "app")
SOURCE_PATH = os.path.join(APP_DIR, "DiveToPalworld.cs")

# FIX38で削除した、不活性化していた自己更新ダウンロード経路の識別子。
# 1つでも見つかったら「削除漏れ」または「復活」を意味する。
FORBIDDEN_IDENTIFIERS = [
    "StageUpdate",
    "DownloadWithFallback",
    "ExtractAndHealthCheck",
    "WritePendingJson",
    "HttpDownloadFile",
    "ClearVerifyPendingSignal",
    "StartRevertUpdate",
    "UpdateReleaseInfo",
    "UpdateStageResult",
]

# 残すべき機能(起動時のバージョン確認、versions.jsonをGETするだけの通知)。
# 一緒に消えていないことの正の対照。
RETAINED_IDENTIFIERS = [
    "CheckForUpdateOnStartup",
    "IsNewerVersion",
    "OpenUpdateDownloadPage",
]


def _strip_comments(src):
    """C#の// / * * /コメントを除去する(FIX38の削除経緯を説明する開発メモの
    コメント文には、削除した識別子の名前がそのまま書かれている。それを
    「復活した実コード」と誤検知しないよう、コードだけを対象にスキャンする)。
    "//"は行頭または直前が空白の時だけコメント開始とみなす(URLリテラル
    "https://..." の"//"には直前に空白が無いため保護される)。"""
    no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"(?:(?<=\s)|^)//[^\n]*", "", no_block, flags=re.MULTILINE)


def _read_source_code_only():
    with open(SOURCE_PATH, encoding="utf-8") as f:
        return _strip_comments(f.read())


def _find_hits(text, identifiers):
    return [name for name in identifiers if name in text]


def test_source_has_no_inert_download_path():
    source = _read_source_code_only()
    hits = _find_hits(source, FORBIDDEN_IDENTIFIERS)
    assert not hits, (
        "FIX38で削除したはずの自己更新ダウンロード経路の識別子が、コメントを除いた"
        "実コードに残っている(削除漏れ、または復活): " + ", ".join(hits))


def test_source_still_has_update_check():
    source = _read_source_code_only()
    hits = _find_hits(source, RETAINED_IDENTIFIERS)
    missing = [name for name in RETAINED_IDENTIFIERS if name not in hits]
    assert not missing, (
        "残すべき機能(起動時バージョン確認)の識別子が一緒に消えている: "
        + ", ".join(missing))


def test_scan_helper_detects_reintroduction_negative_control():
    """_find_hits(+コメント除去)が実際に検知できることの負の対照
    (この試験自体の健全性チェック)。不活性コードを模した断片(コメント混じり)を
    与えて、コメントは無視しつつ実コードは素通りしないことを確認する。"""
    poisoned = (
        "// この行はコメントなのでStageUpdateやExtractAndHealthCheckと書いても無視されるべき\n"
        "internal static class SelfUpdate {\n"
        "    internal static UpdateStageResult StageUpdate() { return UpdateStageResult.Success; }\n"
        "}\n"
    )
    hits = set(_find_hits(_strip_comments(poisoned), FORBIDDEN_IDENTIFIERS))
    assert hits == {"StageUpdate", "UpdateStageResult"}, (
        "検知ロジックが機能していない(負の対照が赤くならなかった、"
        "またはコメント除去で見逃した): " + str(hits))
    # コメント除去自体が過剰に効いて実コードまで消していないことの確認
    assert "ExtractAndHealthCheck" not in _strip_comments(poisoned), (
        "コメント除去のテストデータが想定と食い違っている(テスト自体の不備)")


def _build_exe(build_dir):
    build_ps1 = os.path.join(APP_DIR, "build_app.ps1")
    out_exe = os.path.join(build_dir, "Uchinoko_selfupdate_removed_check.exe")
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
def built_exe():
    build_dir = tempfile.mkdtemp(prefix="d2p_selfupdate_removed_test_")
    try:
        ok, exe_path, detail = _build_exe(build_dir)
        if not ok:
            pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\n" + detail)
        yield exe_path
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def _extract_strings(data, min_len=6):
    """.NETバイナリのメタデータヒープはUTF-8(実質ASCII)で、文字列リテラルは
    UTF-16LEでそれぞれプレーンに埋め込まれる。両方を単純な正規表現で拾う
    (FIX36の切り分け実験が使ったのと同じ、外部strings.exe非依存の手口)。"""
    ascii_strs = set(re.findall(rb"[\x20-\x7e]{%d,}" % min_len, data))
    utf16_pat = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % min_len)
    utf16_hits = {m.group().decode("utf-16-le") for m in utf16_pat.finditer(data)}
    decoded_ascii = {s.decode("ascii") for s in ascii_strs}
    return decoded_ascii | utf16_hits


def test_binary_has_no_download_markers(built_exe):
    with open(built_exe, "rb") as f:
        data = f.read()
    strings_found = _extract_strings(data)
    hits = [name for name in FORBIDDEN_IDENTIFIERS if any(name in s for s in strings_found)]
    assert not hits, (
        "ビルド済みexeのバイナリ文字列走査(ASCII/UTF-16LE)で、削除したはずの"
        "自己更新識別子が見つかった: " + ", ".join(hits))
    # 正の対照: 残すべき機能の識別子はメタデータに残っていること
    # (この走査手法自体が何かを見逃していないことの確認)
    retained_hits = [name for name in RETAINED_IDENTIFIERS if any(name in s for s in strings_found)]
    missing = [name for name in RETAINED_IDENTIFIERS if name not in retained_hits]
    assert not missing, (
        "残すべき機能の識別子がビルド済みexeのバイナリ文字列走査から消えている"
        "(走査手法自体の異常の可能性): " + ", ".join(missing))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
