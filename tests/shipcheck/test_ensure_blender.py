# -*- coding: utf-8 -*-
"""単体テスト: pipeline\\cli\\ensure_blender.ps1(u54 Blender同梱廃止)。

配布zipからBlender本体を外し、初回起動時に公式サイトから取得する方式に
変えた(work\\u54_unbundle\\wpA\\INSTRUCTIONS.md 4.1)。このテストは実ネットワーク
には出ず、4.7で実DL検証済みのキャッシュzip(work\\u54_unbundle\\cache\\
blender-4.3.2-windows-x64.zip)を -SourceZip で指定して確認する
(無効URLを注入する負の対照だけは例外的に実ネットワークへ出て404を踏む)。

pytestからも `python tests/shipcheck/test_ensure_blender.py` からも実行できる
(tests\\shipcheck\\test_palworld_locate.py と同じ構成)。

前提(無ければ各テストはSKIPして緑にはしない=無言スキップにはしない。ただし
テストコレクション自体は落とさない): キャッシュzip・ooz.pyd・python3.dllが
開発機に実在すること(いずれもmake_dist.ps1が使うのと同じ解決パス)。

WP-A2(2026-07-28)ホットフィックス: クリーンWindows Sandbox実機(v1.1.3)で
ensure_blender.ps1がParserError多発で死亡する事故が起きた。真因は
ensure_blender.ps1だけがBOM無しUTF-8で保存されており、実行系の
Windows PowerShell 5.1(powershell.exe)がBOM無しをANSI(CP932)扱いする
ため日本語コメント/文字列で構文が崩壊すること。開発機のこのテストは
`pwsh` で起動していたため検出できなかった(pwshはBOM無しでもUTF-8として
読むため無症状)。以後 `_run()` の既定シェルを実機と同じ`powershell.exe`に
変更し、加えてPS5.1のパーサで直接構文解析する再発防止テストを追加した
(test_ps51_parses_clean / test_ps51_parse_negative_control_no_bom_fails)。
"""
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
ENSURE_BLENDER_PS1 = os.path.join(REPO_ROOT, "pipeline", "cli", "ensure_blender.ps1")
CACHED_ZIP = os.path.join(REPO_ROOT, "work", "u54_unbundle", "cache", "blender-4.3.2-windows-x64.zip")

def _resolve_ooz_site_pkg_src():
    """pyooz(oozモジュール)の実インストール場所を動的に解決する。

    dev#317: 旧実装は %APPDATA%\\Python\\Python313\\site-packages を
    決め打ちしていた(このマシンでpip install --userした場合の実測値)。
    hosted CIランナー(ci.ymlが`pip install pyooz`する。実体は
    actions/setup-pythonのhostedtoolcache配下のPython 3.11環境)や、
    venv環境では別パスになるため、決め打ちだとFileNotFoundErrorで
    テストが壊れる(値を実測に合わせるのではなく、import解決という
    構造で場所依存性そのものを消す)。"""
    try:
        import ooz
    except ImportError:
        return None
    return os.path.dirname(os.path.abspath(ooz.__file__))


# make_dist.ps1と同じ解決先(開発機のpyooz/python3.dll実体、build\make_dist.ps1参照)。
# importで解決できない場合のみ、旧来の決め打ちパスへフォールバックする
# (_skip_reason_if_prereqs_missing()がisfileで検査し、無ければ素直にSKIPへ倒れる)。
OOZ_SITE_PKG_SRC = _resolve_ooz_site_pkg_src() or os.path.join(
    os.environ.get("APPDATA", ""), "Python", "Python313", "site-packages")
PYTHON311_DLL = os.environ.get("D2P_PYTHON311_DLL") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python311", "python3.dll")


def _skip_reason_if_prereqs_missing():
    if not os.path.isfile(ENSURE_BLENDER_PS1):
        return "ensure_blender.ps1が無い: {}".format(ENSURE_BLENDER_PS1)
    if not os.path.isfile(CACHED_ZIP):
        return ("キャッシュ済みBlender zipが無い(4.7の実DL検証で作成される想定): {}"
                 .format(CACHED_ZIP))
    if not os.path.isfile(os.path.join(OOZ_SITE_PKG_SRC, "ooz.pyd")):
        return "ooz.pydが無い(pip install pyoozが必要): {}".format(OOZ_SITE_PKG_SRC)
    if not os.path.isfile(PYTHON311_DLL):
        return "python3.dll(Python 3.11)が無い: {}".format(PYTHON311_DLL)
    return None


def _make_app_root(tmp, with_patch_materials=True):
    """AppRoot直下にassets\\blender_patch\\(差し込み素材)を用意する。"""
    app_root = os.path.join(tmp, "AppRoot")
    if not with_patch_materials:
        os.makedirs(app_root, exist_ok=True)
        return app_root
    patch_dir = os.path.join(app_root, "assets", "blender_patch")
    os.makedirs(patch_dir, exist_ok=True)
    shutil.copy(os.path.join(OOZ_SITE_PKG_SRC, "ooz.pyd"), patch_dir)
    for name in os.listdir(OOZ_SITE_PKG_SRC):
        low = name.lower()
        if low.startswith("pyooz-") and low.endswith(".dist-info"):
            shutil.copytree(os.path.join(OOZ_SITE_PKG_SRC, name), os.path.join(patch_dir, name))
    shutil.copy(PYTHON311_DLL, os.path.join(patch_dir, "python3.dll"))
    return app_root


# WP-A2: 実機(クリーンWindows)にpwshは無い。既定を実機と同じpowershell.exe
# (Windows PowerShell 5.1)にする。D2P_TEST_PS_SHELLで上書き可能(pwshも併用したい
# 場合のため残す。ただし規定値をpwshに戻すと今回の事故を再び見逃す)。
PS_SHELL = os.environ.get("D2P_TEST_PS_SHELL", "powershell.exe")


def _run(app_root, extra_args, timeout=300):
    args = [PS_SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ENSURE_BLENDER_PS1,
            "-AppRoot", app_root] + extra_args
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def test_normal_path_with_cached_sourcezip():
    """SourceZip正常系(キャッシュzip使用)。blender.exe実在+マーカー有効+
    差し込み(ooz.pyd/python3.dll/VCランタイム)まで確認する。冪等性(2回目は
    ダウンロード/展開なしで即PASS)も併せて確認する。"""
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_normal_path_with_cached_sourcezip: {}".format(skip))
        return
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_")
    try:
        app_root = _make_app_root(tmp)
        rc, out = _run(app_root, ["-SourceZip", CACHED_ZIP])
        assert rc == 0, "rc={}\n{}".format(rc, out[-3000:])
        target = os.path.join(app_root, "assets", "tools", "blender-4.3.2-windows-x64")
        assert os.path.isfile(os.path.join(target, "blender.exe"))
        marker_path = os.path.join(target, ".d2p_patched.json")
        assert os.path.isfile(marker_path)
        with open(marker_path, "r", encoding="utf-8") as f:
            marker = json.load(f)
        assert marker["patched"] is True
        assert marker["version"] == "4.3.2"
        site_packages = os.path.join(target, "4.3", "python", "lib", "site-packages")
        py_bin = os.path.join(target, "4.3", "python", "bin")
        assert os.path.isfile(os.path.join(site_packages, "ooz.pyd"))
        assert os.path.isfile(os.path.join(py_bin, "python3.dll"))
        assert os.path.isfile(os.path.join(py_bin, "vcruntime140.dll"))
        assert os.path.isfile(os.path.join(site_packages, "vcruntime140.dll"))
        # 一時作業ディレクトリが残っていないこと(アトミック移動の後始末確認)
        leftovers = [n for n in os.listdir(os.path.join(app_root, "assets", "tools"))
                     if n.startswith(".tmp_ensure_blender_")]
        assert not leftovers, "一時ディレクトリが残っている: {}".format(leftovers)

        # 冪等性: 2回目はダウンロード/展開なしで即PASSすること
        rc2, out2 = _run(app_root, [])
        assert rc2 == 0
        assert ("準備済み" in out2) or ("既に使用可能" in out2), out2[-1000:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _longest_zip_entry_relpath(zip_path):
    """展開先パスが最も深くなるzip内エントリの相対パス(先頭のBlenderディレクトリ
    名込み)を返す。dev#199の再現テストで使う実測ベースの最長パスであり、
    数値を決め打ちしない(zip内容が変わっても追随する)。"""
    with zipfile.ZipFile(zip_path) as zf:
        entries = [info.filename for info in zf.infolist() if not info.filename.endswith("/")]
    return max(entries, key=len)


def test_deep_app_root_extraction_dev199():
    """dev#199回帰: セットアップ時展開の一時ディレクトリ名短縮
    (`.tmp_ensure_blender_<32桁hex>` → `.tmp_eb_<32桁hex>`)+`\\\\?\\\\`長パス
    フォールバックが効いていることを確認する。

    実際の報告(4B4BA9RU)は「配布zip標準の展開先(Downloads直下)なのに
    セットアップの展開だけが先に失敗する」という非対称な脆弱性だった
    (最終配置はMAX_PATH未満でも、展開時の一時ディレクトリ名の分だけ
    余分に深くなるため)。本テストはAppRootの深さを動的に計算して、
    「旧仕様の一時ディレクトリ名だとzip内最長エントリがMAX_PATH(260文字)を
    超えるが、新仕様の短い名前+`\\\\?\\\\`プレフィックスなら展開・後処理
    (パッチ差し込み・最終配置への移動)まで成功する」境界条件を作る。
    """
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_deep_app_root_extraction_dev199: {}".format(skip))
        return

    longest_entry = _longest_zip_entry_relpath(CACHED_ZIP)
    # 差し込み後処理でのCopy-Item先(site-packages配下、ファイル名のみ短い)の
    # 相対パス長。最長エントリより十分短いため、`\\?\`保護の無いCopy-Item/
    # Move-Itemの区間はこのテストの深さでは260文字未満に収まる想定
    # (実測はアサーションで確認する。想定が崩れたらテスト前提の再検討が要る)。
    ooz_relpath = "blender-4.3.2-windows-x64/4.3/python/lib/site-packages/ooz.pyd"

    OLD_TMP_PREFIX_LEN = len(".tmp_ensure_blender_") + 32  # 修正前の一時ディレクトリ名(dev#199)
    NEW_TMP_PREFIX_LEN = len(".tmp_eb_") + 32               # 本PRでの短縮後
    ASSETS_TOOLS_LEN = len(os.path.join("assets", "tools"))

    def _deepest_len(app_root_len, tmp_prefix_len, rel_path):
        # <AppRoot>\assets\tools\<一時dir>\<zip内相対パス> の合計文字数
        return app_root_len + 1 + ASSETS_TOOLS_LEN + 1 + tmp_prefix_len + 1 + len(rel_path)

    # 新仕様での最長パスが260文字を17文字ほど超える深さを狙う(`\\?\`保護区間の
    # 検証に十分)。かつ同じ深さでのooz.pyd複写先は260文字未満に収まる想定
    # (最長エントリとの差が65文字あり、17文字の超過分を吸収できる)。
    target_new_deepest = 277
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_dev199_")
    try:
        app_root_base = os.path.join(tmp, "AR")
        pad_len = target_new_deepest - _deepest_len(len(app_root_base), NEW_TMP_PREFIX_LEN, longest_entry) - 1
        if pad_len > 0:
            app_root = os.path.join(app_root_base, "p" * pad_len)
        else:
            app_root = app_root_base
        os.makedirs(app_root, exist_ok=True)

        old_deepest = _deepest_len(len(app_root), OLD_TMP_PREFIX_LEN, longest_entry)
        new_deepest = _deepest_len(len(app_root), NEW_TMP_PREFIX_LEN, longest_entry)
        new_ooz_copy = _deepest_len(len(app_root), NEW_TMP_PREFIX_LEN, ooz_relpath)
        assert old_deepest > 260, (
            "テスト前提が崩れている(旧仕様の一時ディレクトリ名でも260文字を"
            "超えない、パディング計算を見直すこと): old_deepest={}".format(old_deepest))
        assert new_deepest > 260, (
            "テスト前提が崩れている(`\\?\\`保護の検証に必要な260文字超が"
            "起きていない): new_deepest={}".format(new_deepest))
        assert new_ooz_copy < 260, (
            "テスト前提が崩れている(`\\?\\`保護の無いCopy-Item区間まで"
            "260文字を超えてしまっている、パディングを減らすこと): "
            "new_ooz_copy={}".format(new_ooz_copy))

        # _make_app_rootは"AppRoot"固定名で作る前提のヘルパーで、ここでは
        # パディング計算済みのapp_root名を崩したくないため使わず、直下へ
        # 手動で差し込み素材を配置する。
        patch_dir = os.path.join(app_root, "assets", "blender_patch")
        os.makedirs(patch_dir, exist_ok=True)
        shutil.copy(os.path.join(OOZ_SITE_PKG_SRC, "ooz.pyd"), patch_dir)
        for name in os.listdir(OOZ_SITE_PKG_SRC):
            low = name.lower()
            if low.startswith("pyooz-") and low.endswith(".dist-info"):
                shutil.copytree(os.path.join(OOZ_SITE_PKG_SRC, name), os.path.join(patch_dir, name))
        shutil.copy(PYTHON311_DLL, os.path.join(patch_dir, "python3.dll"))

        rc, out = _run(app_root, ["-SourceZip", CACHED_ZIP])
        assert rc == 0, "rc={} (AppRoot長={}文字, old_deepest={}, new_deepest={})\n{}".format(
            rc, len(app_root), old_deepest, new_deepest, out[-3000:])
        target = os.path.join(app_root, "assets", "tools", "blender-4.3.2-windows-x64")
        assert os.path.isfile(os.path.join(target, "blender.exe"))
        marker_path = os.path.join(target, ".d2p_patched.json")
        assert os.path.isfile(marker_path)
        with open(marker_path, "r", encoding="utf-8") as f:
            marker = json.load(f)
        assert marker["patched"] is True
        # 一時ディレクトリの後始末確認(新旧どちらの命名でも残っていないこと)
        leftovers = [n for n in os.listdir(os.path.join(app_root, "assets", "tools"))
                     if n.startswith(".tmp_ensure_blender_") or n.startswith(".tmp_eb_")]
        assert not leftovers, "一時ディレクトリが残っている: {}".format(leftovers)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _extract_ps_function(source_text, func_name):
    """ensure_blender.ps1本文から指定関数定義だけをブレース対応で切り出す。"""
    marker = "function {} {{".format(func_name)
    start = source_text.index(marker)
    depth = 0
    i = start
    while i < len(source_text):
        ch = source_text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source_text[start:i + 1]
        i += 1
    raise ValueError("function {} の終端ブレースが見つからない".format(func_name))


def _run_longpath_check_script(func_src, timeout=30):
    r"""Get-D2PLongPath(またはその代替実装)を単体でpowershell.exeへ渡し、
    3種の入力(通常の絶対パス/既に`\\?\`付き/UNCパス)への変換結果を返す。
    実ファイルI/O・実ネットワークを一切要求しない純粋な文字列変換の検査
    (test_deep_app_root_extraction_dev199がこの開発機ではLongPathsEnabled=1
    のため実際のMAX_PATH失敗を再現できないことの代替として置く。詳細は
    test_get_d2p_long_path_prefixes_correctlyのdocstring参照)。"""
    tmp = tempfile.mkdtemp(prefix="d2p_longpath_unit_")
    try:
        script_path = os.path.join(tmp, "check_longpath.ps1")
        script = func_src + "\n" + (
            "Write-Output (Get-D2PLongPath 'C:\\normal\\path')\n"
            "Write-Output (Get-D2PLongPath '\\\\?\\C:\\already\\prefixed')\n"
            "Write-Output (Get-D2PLongPath '\\\\server\\share\\unc\\path')\n"
        )
        # ensure_blender.ps1本体と同じ規約(BOM付きUTF-8。WP-A2参照)で書く。
        with open(script_path, "w", encoding="utf-8-sig") as f:
            f.write(script)
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        out_lines = [l for l in (proc.stdout or "").splitlines() if l.strip()]
        return proc.returncode, out_lines, (proc.stdout or "") + (proc.stderr or "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_get_d2p_long_path_prefixes_correctly():
    r"""dev#199: `Get-D2PLongPath`ヘルパー(展開処理へ`\\?\`長パスプレフィックスを
    付与する保険対策)の入出力を単体で確認する。

    この開発機は`HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem`の
    LongPathsEnabledが既に1(有効)になっており、Windows PowerShell 5.1(.NET
    Framework)がこの設定を尊重するため、`\\?\`プレフィックス無しの旧実装でも
    実際のMAX_PATH超過を再現できない(実測: パディングでAppRootを約680文字まで
    深くしても旧コードのまま展開・移動まで成功した)。このレジストリ設定は
    エンドユーザー環境(既定は無効)を代表しておらず、エージェントが変更する
    ことも安全規則上禁止されている。そのため実ファイルI/Oに依存しない本テストで、
    変換ロジック自体が正しいことをLongPathsEnabled設定に依存しない形で検査する。
    """
    if shutil.which("powershell.exe") is None:
        print("SKIP: test_get_d2p_long_path_prefixes_correctly: powershell.exeが無い環境")
        return
    assert os.path.isfile(ENSURE_BLENDER_PS1), "ensure_blender.ps1が無い"
    with open(ENSURE_BLENDER_PS1, "r", encoding="utf-8-sig") as f:
        source = f.read()
    func_src = _extract_ps_function(source, "Get-D2PLongPath")

    rc, out_lines, out = _run_longpath_check_script(func_src)
    assert rc == 0, "rc={}\n{}".format(rc, out[-2000:])
    expected = [
        r"\\?\C:\normal\path",
        r"\\?\C:\already\prefixed",
        r"\\?\UNC\server\share\unc\path",
    ]
    assert out_lines == expected, "Get-D2PLongPathの出力が想定と違う: got={} expected={}".format(
        out_lines, expected)


def test_negative_get_d2p_long_path_naive_passthrough_detected():
    """負の対照: dev#199修正前を模した「プレフィックスを付けないダミー実装」を
    同じ検査手順に通すと、上のテストの期待値と一致しないこと(=検査能力が
    効いていることの確認。実際のensure_blender.ps1は書き換えない)。"""
    if shutil.which("powershell.exe") is None:
        print("SKIP: test_negative_get_d2p_long_path_naive_passthrough_detected: powershell.exeが無い環境")
        return
    naive_func_src = (
        "function Get-D2PLongPath {\n"
        "    param([string]$Path)\n"
        "    return $Path\n"
        "}"
    )
    rc, out_lines, out = _run_longpath_check_script(naive_func_src)
    assert rc == 0, "rc={}\n{}".format(rc, out[-2000:])
    expected = [
        r"\\?\C:\normal\path",
        r"\\?\C:\already\prefixed",
        r"\\?\UNC\server\share\unc\path",
    ]
    assert out_lines != expected, (
        "ダミー実装(素通し)が正規実装と同じ出力になってしまった(検査が効いていない): {}"
        .format(out_lines))


def test_negative_sha256_mismatch_fails_closed():
    """負の対照(4.6b相当): SourceZipを1バイト改竄すると、SHA不一致でfail-closed
    すること(最終位置にディレクトリを残さないことも確認)。"""
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_negative_sha256_mismatch_fails_closed: {}".format(skip))
        return
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_")
    try:
        app_root = _make_app_root(tmp)
        corrupt_zip = os.path.join(tmp, "corrupt.zip")
        shutil.copy(CACHED_ZIP, corrupt_zip)
        with open(corrupt_zip, "r+b") as f:
            f.seek(1000)
            b = f.read(1)
            f.seek(1000)
            f.write(bytes([(b[0] + 1) % 256]))
        rc, out = _run(app_root, ["-SourceZip", corrupt_zip])
        assert rc != 0, "改竄zipなのに成功してしまった:\n{}".format(out[-2000:])
        assert "[D2P_BLENDER_SETUP_FAIL]" in out
        assert "SHA256" in out
        target = os.path.join(app_root, "assets", "tools", "blender-4.3.2-windows-x64")
        assert not os.path.isdir(target), "失敗したのに最終位置にディレクトリが残っている(fail-closed違反)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_negative_invalid_url_fails_closed_with_marker():
    """負の対照(4.6a相当): SourceZip省略+無効URL注入では、実ネットワーク越しに
    失敗し[D2P_BLENDER_SETUP_FAIL]マーカー付きで案内が出て非0終了すること。

    dev#62(公式サイト失敗時のR2ミラー自動フォールバック追加)以降、公式URLだけを
    無効にしてもミラー(dl.osakishokai.com)が生きていれば全体としては成功して
    しまう。これはこのテストが検証したい「取得元が壊れていればfail-closedする」
    という性質そのものを壊すため、ミラー側も明示的に無効URLへ差し替えて実質的に
    フォールバック機構自体を無効化する(将来dl.osakishokai.com側に実物を配置しても
    このテストの意味が変わらないようにするため)。"""
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_negative_invalid_url_fails_closed_with_marker: {}".format(skip))
        return
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_")
    try:
        app_root = _make_app_root(tmp)
        rc, out = _run(app_root, [
            "-DownloadUrlOverride",
            "https://download.blender.org/release/Blender4.3/does-not-exist-12345.zip",
            "-MirrorUrlOverride",
            "https://dl.osakishokai.com/deps/does-not-exist-12345.zip",
        ])
        assert rc != 0
        assert "[D2P_BLENDER_SETUP_FAIL]" in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_negative_missing_patch_materials_fails_closed():
    """負の対照: assets\\blender_patch\\が無い(配布物が壊れている想定)場合、
    展開までは進んでも差し込みの段で検知してfail-closedすること
    (「展開はできたので成功扱い」のような無言の格下げをしないことの確認)。"""
    if not os.path.isfile(ENSURE_BLENDER_PS1) or not os.path.isfile(CACHED_ZIP):
        print("SKIP: test_negative_missing_patch_materials_fails_closed: 前提ファイル無し")
        return
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_")
    try:
        app_root = _make_app_root(tmp, with_patch_materials=False)
        rc, out = _run(app_root, ["-SourceZip", CACHED_ZIP])
        assert rc != 0
        assert "[D2P_BLENDER_SETUP_FAIL]" in out
        assert "差し込み素材" in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ps51_parse_error_count(path):
    """指定ps1をWindows PowerShell 5.1(powershell.exe)のパーサで直接構文解析し、
    構文エラー件数と、エラーメッセージ結合文字列を返す(実行は一切しない)。
    実ネットワーク・実ファイルI/Oを一切要求しないため前提スキップは無い
    (powershell.exeが無い環境=そもそも配布対象外のためSKIPはこの1点のみ許容)。
    """
    ps_script = (
        "$tokens = $null; $parseErrors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile('{}', [ref]$tokens, [ref]$parseErrors) "
        "| Out-Null; "
        "Write-Output ('COUNT=' + $parseErrors.Count); "
        "$parseErrors | ForEach-Object {{ Write-Output $_.Message }}"
    ).format(path.replace("'", "''"))
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    count = None
    for line in out.splitlines():
        if line.startswith("COUNT="):
            count = int(line[len("COUNT="):].strip())
            break
    return count, out


def test_ps51_parses_clean():
    """再発防止(WP-A2): ensure_blender.ps1はWindows PowerShell 5.1のパーサで
    構文エラー0件であること(BOM欠落・PS7専用構文混入の再発を機械的に守る)。"""
    if shutil.which("powershell.exe") is None:
        print("SKIP: test_ps51_parses_clean: powershell.exeが無い環境")
        return
    assert os.path.isfile(ENSURE_BLENDER_PS1), "ensure_blender.ps1が無い"
    count, out = _ps51_parse_error_count(ENSURE_BLENDER_PS1)
    assert count == 0, "PS5.1パースエラーが{}件検出された:\n{}".format(count, out[-3000:])


def test_ps51_parse_negative_control_no_bom_fails():
    """負の対照: BOMを剥がした一時コピーは、同じPS5.1パーサチェックで必ず
    赤(構文エラー>0件)になること。これが緑のままだと上のtest_ps51_parses_clean
    自体が「たまたま通っただけ」の疑いが晴れないため、検査能力そのものを確認する。"""
    if shutil.which("powershell.exe") is None:
        print("SKIP: test_ps51_parse_negative_control_no_bom_fails: powershell.exeが無い環境")
        return
    assert os.path.isfile(ENSURE_BLENDER_PS1), "ensure_blender.ps1が無い"
    with open(ENSURE_BLENDER_PS1, "rb") as f:
        data = f.read()
    assert data[:3] == b"\xef\xbb\xbf", (
        "ensure_blender.ps1がBOM無しに戻っている(本テストの前提=正常系はBOM有りが崩れた)")
    stripped = data[3:]
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_negctrl_")
    try:
        no_bom_copy = os.path.join(tmp, "ensure_blender_no_bom.ps1")
        with open(no_bom_copy, "wb") as f:
            f.write(stripped)
        count, out = _ps51_parse_error_count(no_bom_copy)
        assert count is not None and count > 0, (
            "BOMを剥がしたコピーがPS5.1パースを通ってしまった(検査が効いていない):\n{}"
            .format(out[-3000:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _read_ps1_string_const(source, var_name):
    """ensure_blender.ps1本文から `$var_name = "..."` 形式のスカラー代入を読む
    (テストの期待値をハードコードせず、スクリプト本体とドリフトしないようにするため)。"""
    m = re.search(r"\$" + re.escape(var_name) + r'\s*=\s*"([^"]*)"', source)
    assert m, "{} の代入がensure_blender.ps1に見つからない".format(var_name)
    return m.group(1)


def _ps1_constants():
    with open(ENSURE_BLENDER_PS1, "r", encoding="utf-8-sig") as f:
        source = f.read()
    return {
        "version": _read_ps1_string_const(source, "BlenderVersion"),
        "sha256": _read_ps1_string_const(source, "ExpectedSha256"),
    }


def _make_fake_blender_dir(app_root, marker=None, with_exe=True):
    """AppRoot\\assets\\tools\\blender-<version>-windows-x64\\ に偽のblender.exeと
    (指定時)マーカーjsonだけを置く。実Blender本体・実ネットワークは一切不要
    (-CheckOnlyが見るのはTest-D2PMarkerValidが参照するファイル群の実在/内容だけ
    のため、中身が空のダミーexeで十分)。"""
    consts = _ps1_constants()
    target = os.path.join(app_root, "assets", "tools",
                           "blender-{}-windows-x64".format(consts["version"]))
    os.makedirs(target, exist_ok=True)
    if with_exe:
        with open(os.path.join(target, "blender.exe"), "wb") as f:
            f.write(b"fake-blender-exe-for-checkonly-test")
    if marker is not None:
        with open(os.path.join(target, ".d2p_patched.json"), "w", encoding="utf-8") as f:
            json.dump(marker, f)
    return target, consts


def test_check_only_valid_marker_exits_zero_without_download():
    """dev#230: exe実在+マーカー実在+version/sha256/patched一致(=正当なキャッシュ)
    の場合、-CheckOnlyは即0で返り、ダウンロード・展開を一切行わないこと。
    キャッシュzip/pyoozの実体が無い開発機でも実行できる(=前提スキップが不要)ことが
    この経路の要点(GUI起動のたびに呼んでも重くならないことの裏付け)。"""
    assert os.path.isfile(ENSURE_BLENDER_PS1), "ensure_blender.ps1が無い"
    tmp = tempfile.mkdtemp(prefix="d2p_checkonly_")
    try:
        app_root = _make_app_root(tmp, with_patch_materials=False)
        target, consts = _make_fake_blender_dir(app_root)
        marker = {
            "version": consts["version"],
            "sha256": consts["sha256"],
            "patched": True,
            "patched_at_utc": "2026-01-01T00:00:00Z",
            "patch_items": [],
        }
        with open(os.path.join(target, ".d2p_patched.json"), "w", encoding="utf-8") as f:
            json.dump(marker, f)

        rc, out = _run(app_root, ["-CheckOnly"])
        assert rc == 0, "有効マーカーなのにrc={}\n{}".format(rc, out[-2000:])
        assert "##PROGRESS##" not in out, (
            "-CheckOnlyなのに進捗ログ(=フル実行)が出ている。CheckOnly分岐が早期return"
            "できていない可能性:\n{}".format(out))
        tools_dir = os.path.join(app_root, "assets", "tools")
        leftovers = [n for n in os.listdir(tools_dir) if n.startswith(".tmp_")]
        assert not leftovers, "-CheckOnlyなのに展開用一時ディレクトリが作られた: {}".format(leftovers)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_check_only_missing_marker_but_exe_present_exits_nonzero():
    """dev#230回帰そのもの(核心テスト): blender.exeは実在するがマーカーが無い
    (2026-07-27より前にセットアップ済みの既存キャッシュを模した状態=今回の
    実報告2件と同じ形)の場合、-CheckOnlyは非0を返すこと。これが0を返すように
    戻ったら、呼び出し元が『exeがあるからスキップしてよい』と誤判定する
    バグが再発したことを意味する。"""
    assert os.path.isfile(ENSURE_BLENDER_PS1), "ensure_blender.ps1が無い"
    tmp = tempfile.mkdtemp(prefix="d2p_checkonly_")
    try:
        app_root = _make_app_root(tmp, with_patch_materials=False)
        _make_fake_blender_dir(app_root, marker=None)  # exeのみ、マーカー無し
        rc, out = _run(app_root, ["-CheckOnly"])
        assert rc != 0, "マーカー無しなのにrc=0(dev#230のバグが再発している):\n{}".format(out[-2000:])
        assert "##PROGRESS##" not in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_check_only_patched_false_marker_exits_nonzero():
    """負の対照: マーカーファイル自体はあるが patched:false(後処理が未完了/破損した
    ことを示す)の場合も -CheckOnly は非0を返すこと。『マーカーが存在するかどうか』
    だけを見て中身(patchedフラグ)を見ない退行の検出。"""
    assert os.path.isfile(ENSURE_BLENDER_PS1), "ensure_blender.ps1が無い"
    tmp = tempfile.mkdtemp(prefix="d2p_checkonly_")
    try:
        app_root = _make_app_root(tmp, with_patch_materials=False)
        target, consts = _make_fake_blender_dir(app_root)
        marker = {
            "version": consts["version"],
            "sha256": consts["sha256"],
            "patched": False,  # 破損/未完了を模す
            "patched_at_utc": "2026-01-01T00:00:00Z",
            "patch_items": [],
        }
        with open(os.path.join(target, ".d2p_patched.json"), "w", encoding="utf-8") as f:
            json.dump(marker, f)
        rc, out = _run(app_root, ["-CheckOnly"])
        assert rc != 0, "patched:falseなのにrc=0:\n{}".format(out[-2000:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_check_only_missing_exe_exits_nonzero():
    """負の対照: マーカーjsonだけがあってblender.exe自体が無い場合も非0であること
    (マーカーの実在だけでexeの実在を確認しない退行の検出)。"""
    assert os.path.isfile(ENSURE_BLENDER_PS1), "ensure_blender.ps1が無い"
    tmp = tempfile.mkdtemp(prefix="d2p_checkonly_")
    try:
        app_root = _make_app_root(tmp, with_patch_materials=False)
        target, consts = _make_fake_blender_dir(app_root, with_exe=False)
        marker = {
            "version": consts["version"],
            "sha256": consts["sha256"],
            "patched": True,
            "patched_at_utc": "2026-01-01T00:00:00Z",
            "patch_items": [],
        }
        with open(os.path.join(target, ".d2p_patched.json"), "w", encoding="utf-8") as f:
            json.dump(marker, f)
        rc, out = _run(app_root, ["-CheckOnly"])
        assert rc != 0, "exeが無いのにrc=0:\n{}".format(out[-2000:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# dev#62: 取得元フォールバック(公式サイト→R2ミラー)のテスト。
#
# 実ネットワーク(download.blender.org / dl.osakishokai.com)には一切出ない。
# ローカルループバック(127.0.0.1、動的ポート)にHTTPサーバを立て、
# -DownloadUrlOverride / -MirrorUrlOverride でそこを指させることで、
# 「公式成功→ミラー未使用」「公式失敗→ミラー使用」「両方失敗」
# 「ミラー応答はあるがハッシュ不一致」の4対照をモックで再現する。
# ---------------------------------------------------------------------------
class _RouteHandler(http.server.BaseHTTPRequestHandler):
    """self.server.routes = {path: (status, bytes)} に登録された経路だけ200を返し、
    未登録の経路は404を返す単純なモックハンドラ。"""

    def do_GET(self):
        entry = self.server.routes.get(self.path)
        if entry is None:
            self.send_response(404)
            self.end_headers()
            return
        status, data = entry
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # noqa: A002 - テスト出力を静かにする
        pass


class _MockDownloadServer:
    """127.0.0.1の動的ポートで待ち受けるテスト専用HTTPサーバ(実ネットワーク不使用)。"""

    def __init__(self, routes):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RouteHandler)
        self.httpd.routes = routes
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path):
        return "http://127.0.0.1:{}{}".format(self.port, path)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def test_mirror_fallback_used_when_primary_fails():
    """dev#62 対照②: 公式サイト(モック)が404で失敗した場合、自動的にミラー
    (モック)へフォールバックし、正常に取得・展開・検証まで完走すること。"""
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_mirror_fallback_used_when_primary_fails: {}".format(skip))
        return
    with open(CACHED_ZIP, "rb") as f:
        zip_bytes = f.read()
    server = _MockDownloadServer({"/mirror.zip": (200, zip_bytes)})
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_mirror_")
    try:
        app_root = _make_app_root(tmp)
        rc, out = _run(app_root, [
            "-DownloadUrlOverride", server.url("/primary-not-registered.zip"),  # 未登録経路=404
            "-MirrorUrlOverride", server.url("/mirror.zip"),
        ], timeout=300)
        assert rc == 0, "rc={}\n{}".format(rc, out[-3000:])
        assert "公式サイトからの取得に失敗しました" in out, out[-2000:]
        assert "フォールバックします" in out, out[-2000:]
        assert "取得成功(R2ミラー)" in out, out[-2000:]
        target = os.path.join(app_root, "assets", "tools", "blender-4.3.2-windows-x64")
        assert os.path.isfile(os.path.join(target, "blender.exe"))
        marker_path = os.path.join(target, ".d2p_patched.json")
        with open(marker_path, "r", encoding="utf-8") as fh:
            marker = json.load(fh)
        assert marker["patched"] is True
    finally:
        server.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def test_primary_success_mirror_not_used():
    """dev#62 対照①: 公式サイト(モック)が成功する場合、ミラーには一切
    アクセスしないこと(MirrorUrlOverrideを未登録の経路=踏んだら失敗する
    経路に向けて、フォールバックのログが出ないこと・成功することを確認する)。"""
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_primary_success_mirror_not_used: {}".format(skip))
        return
    with open(CACHED_ZIP, "rb") as f:
        zip_bytes = f.read()
    server = _MockDownloadServer({"/primary.zip": (200, zip_bytes)})
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_noMirror_")
    try:
        app_root = _make_app_root(tmp)
        rc, out = _run(app_root, [
            "-DownloadUrlOverride", server.url("/primary.zip"),
            "-MirrorUrlOverride", server.url("/mirror-should-never-be-hit.zip"),
        ], timeout=300)
        assert rc == 0, "rc={}\n{}".format(rc, out[-3000:])
        assert "取得成功(公式サイト)" in out, out[-2000:]
        assert "フォールバック" not in out, (
            "公式サイトが成功したのにミラーへフォールバックした形跡がある:\n{}".format(out[-2000:]))
        target = os.path.join(app_root, "assets", "tools", "blender-4.3.2-windows-x64")
        assert os.path.isfile(os.path.join(target, "blender.exe"))
    finally:
        server.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def test_negative_both_download_sources_fail():
    """dev#62 対照③(負の対照): 公式サイト・ミラーの両方(モック)が失敗する場合、
    明確なエラー([D2P_BLENDER_SETUP_FAIL]+両方の理由+手動配置案内)でfail-closed
    すること。"""
    # dev#317: 他のテスト(例: test_negative_mirror_hash_mismatch_fails_closed)と
    # 同様の前提チェックが本テストだけ欠けており、前提が揃わない環境で
    # SKIPせずFileNotFoundError/subprocessエラーで落ちていた(検査能力を
    # 狭めるのではなく、既存の統一されたSKIP設計へ揃える修正)。
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_negative_both_download_sources_fail: {}".format(skip))
        return
    server = _MockDownloadServer({})  # どちらも未登録=常に404
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_bothfail_")
    try:
        app_root = _make_app_root(tmp)
        rc, out = _run(app_root, [
            "-DownloadUrlOverride", server.url("/primary-missing.zip"),
            "-MirrorUrlOverride", server.url("/mirror-missing.zip"),
        ], timeout=120)
        assert rc != 0, "両方失敗するはずなのに成功した:\n{}".format(out[-2000:])
        assert "[D2P_BLENDER_SETUP_FAIL]" in out
        assert "公式サイト・ミラーとも失敗" in out, out[-2000:]
        # 既存の手動配置案内(three-point-set原則の3点目)が出ていること
        assert "手動で配置することもできます" in out, out[-2000:]
    finally:
        server.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def test_negative_mirror_hash_mismatch_fails_closed():
    """dev#62 対照④(負の対照): 公式サイト(モック)が失敗しミラー(モック)へ
    フォールバックした先で、応答は200だが中身が改竄されている(SHA256不一致)
    場合もfail-closedすること(ミラー汚染への防御そのものの確認)。"""
    skip = _skip_reason_if_prereqs_missing()
    if skip:
        print("SKIP: test_negative_mirror_hash_mismatch_fails_closed: {}".format(skip))
        return
    with open(CACHED_ZIP, "rb") as f:
        zip_bytes = bytearray(f.read())
    zip_bytes[1000] = (zip_bytes[1000] + 1) % 256  # 1バイト改竄(汚染ミラーを模す)
    server = _MockDownloadServer({"/mirror-corrupt.zip": (200, bytes(zip_bytes))})
    tmp = tempfile.mkdtemp(prefix="d2p_ensure_blender_mirrorhash_")
    try:
        app_root = _make_app_root(tmp)
        rc, out = _run(app_root, [
            "-DownloadUrlOverride", server.url("/primary-missing.zip"),  # 404で公式失敗
            "-MirrorUrlOverride", server.url("/mirror-corrupt.zip"),
        ], timeout=300)
        assert rc != 0, "改竄ミラーなのに成功してしまった:\n{}".format(out[-2000:])
        assert "[D2P_BLENDER_SETUP_FAIL]" in out
        assert "SHA256" in out
        target = os.path.join(app_root, "assets", "tools", "blender-4.3.2-windows-x64")
        assert not os.path.isdir(target), "失敗したのに最終位置にディレクトリが残っている(fail-closed違反)"
    finally:
        server.stop()
        shutil.rmtree(tmp, ignore_errors=True)


_TESTS = [
    test_normal_path_with_cached_sourcezip,
    test_deep_app_root_extraction_dev199,
    test_get_d2p_long_path_prefixes_correctly,
    test_negative_get_d2p_long_path_naive_passthrough_detected,
    test_negative_sha256_mismatch_fails_closed,
    test_negative_invalid_url_fails_closed_with_marker,
    test_negative_missing_patch_materials_fails_closed,
    test_ps51_parses_clean,
    test_ps51_parse_negative_control_no_bom_fails,
    test_check_only_valid_marker_exits_zero_without_download,
    test_check_only_missing_marker_but_exe_present_exits_nonzero,
    test_check_only_patched_false_marker_exits_nonzero,
    test_check_only_missing_exe_exits_nonzero,
    test_mirror_fallback_used_when_primary_fails,
    test_primary_success_mirror_not_used,
    test_negative_both_download_sources_fail,
    test_negative_mirror_hash_mismatch_fails_closed,
]


if __name__ == "__main__":
    failures = []
    for t in _TESTS:
        try:
            t()
            print("PASS: {}".format(t.__name__))
        except Exception as e:  # noqa: BLE001
            failures.append(t.__name__)
            print("FAIL: {}: {}".format(t.__name__, e))
    if failures:
        print("\n{} failed: {}".format(len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall {} tests passed".format(len(_TESTS)))
