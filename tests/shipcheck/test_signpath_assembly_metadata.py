# -*- coding: utf-8 -*-
"""SignPath対応(2026-07-31): 本体exe / ランチャーexe のアセンブリメタデータ付与の検査。

背景: 署名なしexeにAssemblyTitle/Product/Company/Version/FileVersion/Copyright/
Description等のメタデータが一切無いと、レピュテーションが積み上がらず
SmartScreen/Defenderのヒューリスティックに引っかかりやすい(SignPath審査とは
独立に効く改善)。app\\AssemblyInfo.cs(本体用)/ app\\LauncherAssemblyInfo.cs
(ランチャー用)にassembly属性を追加し、ビルドスクリプト
(app\\build_app.ps1 / build\\make_dist.ps1)がバージョンのプレースホルダ
("0.0.0.0")を app\\DiveToPalworld.cs の ToolVersion 定数から実バージョンへ
差し込んでからコンパイルする。

このファイルは3段構成:
  1. 静的検査: AssemblyInfo系ソースに必要な属性がすべて揃っていること
  2. 動的検査(正の対照): app\\build_app.ps1 で実際にビルドし、生成されたexeの
     VersionInfoに必要フィールドが空でないこと
  3. 動的検査(負の対照): AssemblyInfo無しでビルドすると、同じフィールドが
     空になること(=検査が「常に緑になる検査」ではないことの証明)

pytestからも `python tests/shipcheck/test_signpath_assembly_metadata.py` からも
実行できる(tests\\shipcheck\\test_dist_channel_cs.py と同じ構成)。
"""
import json
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
BUILD_APP_PS1 = os.path.join(APP_DIR, "build_app.ps1")
MAIN_SRC = os.path.join(APP_DIR, "DiveToPalworld.cs")
ASSEMBLY_INFO_CS = os.path.join(APP_DIR, "AssemblyInfo.cs")
LAUNCHER_ASSEMBLY_INFO_CS = os.path.join(APP_DIR, "LauncherAssemblyInfo.cs")
APP_MANIFEST = os.path.join(APP_DIR, "app.manifest")
# dev#523: app.manifestのassemblyIdentity名。csc.exeは/win32manifest省略時でも
# 既定マニフェスト(name="MyApplication.app")を自動で埋め込むため
# (asInvoker自体は元から入っていた)、「既定のままではなく本プロジェクト固有の
# マニフェストが実際に採用された」ことの証跡としてこの識別名の有無で判定する。
MANIFEST_IDENTITY_NAME = "Uchinoko.for.Palworld"

REQUIRED_ATTRIBUTES = (
    "AssemblyTitle",
    "AssemblyProduct",
    "AssemblyCompany",
    "AssemblyVersion",
    "AssemblyFileVersion",
    "AssemblyCopyright",
    "AssemblyDescription",
)


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _csc_path():
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")


def _read_version_info(exe_path):
    """PowerShellの(Get-Item).VersionInfoをJSONへ変換して読み取る(このリポジトリは
    Windows専用のため、標準ライブラリのみでの取得を諦めpwsh経由に統一する)。"""
    ps_cmd = (
        "(Get-Item -LiteralPath '{}').VersionInfo | "
        "Select-Object CompanyName,ProductName,FileVersion,LegalCopyright,"
        "FileDescription,Comments | ConvertTo-Json -Compress"
    ).format(exe_path.replace("'", "''"))
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert proc.returncode == 0, "VersionInfo取得に失敗: " + (proc.stderr or proc.stdout or "")
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# 1. 静的検査
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [ASSEMBLY_INFO_CS, LAUNCHER_ASSEMBLY_INFO_CS])
def test_assembly_info_source_has_required_attributes(path):
    assert os.path.isfile(path), path + " が存在しない"
    content = _read(path)
    missing = [attr for attr in REQUIRED_ATTRIBUTES if "[assembly: " + attr not in content]
    assert not missing, "{} に必須のアセンブリ属性が欠けている: {}".format(path, missing)


def test_assembly_info_version_uses_placeholder_not_hardcoded():
    """バージョンはビルドスクリプトが差し込む前提のプレースホルダであること
    (WP要件: バージョンをAssemblyInfo.cs自体にハードコードしない)。"""
    for path in (ASSEMBLY_INFO_CS, LAUNCHER_ASSEMBLY_INFO_CS):
        content = _read(path)
        assert 'AssemblyVersion("0.0.0.0")' in content
        assert 'AssemblyFileVersion("0.0.0.0")' in content


def test_build_app_ps1_derives_version_from_tool_version_constant():
    """app\\build_app.ps1 がバージョンをハードコードせず、DiveToPalworld.cs の
    ToolVersion定数から正規表現で取得していること。"""
    content = _read(BUILD_APP_PS1)
    assert "ToolVersion" in content
    assert "AssemblyInfo.cs" in content
    assert "0.0.0.0" in content, "プレースホルダ文字列への言及が無い(置換ロジック欠落の疑い)"


def test_app_manifest_source_declares_as_invoker():
    """dev#523: app\\app.manifest が存在し、requestedExecutionLevel=asInvoker を
    明示していること(静的検査)。"""
    assert os.path.isfile(APP_MANIFEST), APP_MANIFEST + " が存在しない"
    content = _read(APP_MANIFEST)
    assert 'requestedExecutionLevel level="asInvoker"' in content
    assert MANIFEST_IDENTITY_NAME in content


def test_build_app_ps1_embeds_win32_manifest():
    """dev#523: app\\build_app.ps1 が app.manifest を /win32manifest: でcsc.exeへ
    渡していること(静的検査。埋め込み自体の動的検査は
    test_built_main_exe_has_custom_manifest_identity で行う)。"""
    content = _read(BUILD_APP_PS1)
    assert "app.manifest" in content
    assert "/win32manifest:" in content


def test_make_dist_ps1_no_longer_builds_launcher():
    """2026-07-31: ランチャーのAV誤検知が実測で判明し、
    配布物からランチャーを除去した。build\\make_dist.ps1はもうLauncherAssemblyInfo.cs
    を読まない・パッチしない(この試験は以前の逆——読んでいることを検査していた
    ——を反転した)。app\\LauncherAssemblyInfo.cs自体はソースとして温存されており、
    静的検査(test_assembly_info_source_has_required_attributes等)は引き続き
    このファイルを検査する。

    「LauncherAssemblyInfo.csという文字列そのものが本文に一切現れない」ことは要求
    しない(廃止の経緯を説明するコメントでの言及は自然)。ここで検査するのは、
    実際にファイルを読み込んでパッチする・コンパイル対象に含める、という
    **機能的な参照**が無いこと。"""
    make_dist_ps1 = os.path.join(REPO_ROOT, "build", "make_dist.ps1")
    content = _read(make_dist_ps1)
    assert "$LauncherAssemblyInfoPath" not in content, (
        "build\\make_dist.ps1 がまだ LauncherAssemblyInfo.cs を機能的に読み込んでいる"
        "(ランチャー廃止のリグレッション)")
    assert "$Version.TrimStart('v')" not in content, (
        "build\\make_dist.ps1 にランチャー用バージョン抽出コードがまだ残っている")


# ---------------------------------------------------------------------------
# 2. 動的検査(正の対照): 実ビルドしてVersionInfoを確認
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built_main_exe():
    csc = _csc_path()
    if not os.path.isfile(csc):
        pytest.skip("csc.exe (.NET Framework 4.8) が見つからない環境")
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh (PowerShell 7) が見つからない環境")
    build_dir = tempfile.mkdtemp(prefix="d2p_signpath_metadata_test_")
    out_exe = os.path.join(build_dir, "Uchinoko_metadata_check.exe")
    try:
        proc = subprocess.run(
            ["pwsh", "-NoProfile", "-File", BUILD_APP_PS1, "-Out", out_exe],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
        if proc.returncode != 0 or not os.path.isfile(out_exe):
            pytest.fail("app\\build_app.ps1 でのビルドに失敗した:\nrc={}\n{}".format(
                proc.returncode, (proc.stdout or "") + (proc.stderr or "")))
        yield out_exe
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def test_built_main_exe_has_nonempty_metadata(built_main_exe):
    info = _read_version_info(built_main_exe)
    for field in ("CompanyName", "ProductName", "FileVersion", "LegalCopyright", "FileDescription"):
        assert info.get(field), "{} が空だった: {}".format(field, info)
    assert info["CompanyName"] == "pandrabox"
    assert info["ProductName"] == "Uchinoko for Palworld"
    assert info["LegalCopyright"] == "Copyright (c) 2026 pandrabox"
    # ToolVersion定数(app\DiveToPalworld.cs)の"v"を除いた値と一致すること
    src = _read(MAIN_SRC)
    m = re.search(r'const\s+string\s+ToolVersion\s*=\s*"v?([^"]+)"', src)
    assert m, "ToolVersion定数が見つからない"
    assert info["FileVersion"] == m.group(1), (
        "ビルドされたexeのFileVersionがToolVersionと一致しない: exe={} tool={}".format(
            info["FileVersion"], m.group(1)))


def test_built_main_exe_has_custom_manifest_identity(built_main_exe):
    """dev#523: 実ビルドしたexeへ、csc.exeの既定マニフェスト
    (name="MyApplication.app"、requestedExecutionLevel=asInvokerは既定でも
    元から入っている)ではなく、app\\app.manifest由来の本プロジェクト固有
    マニフェスト(MANIFEST_IDENTITY_NAME)が採用されていることを確認する
    (バイト列上のテキスト検索。マニフェストはcsc.exeにより非圧縮でPEへ
    埋め込まれるため、単純な部分文字列一致で検出できる)。"""
    with open(built_main_exe, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", errors="ignore")
    assert 'requestedExecutionLevel level="asInvoker"' in text, (
        "ビルドしたexeにasInvokerマニフェストが見つからない")
    assert MANIFEST_IDENTITY_NAME in text, (
        "ビルドしたexeにapp.manifest由来の識別名({})が見つからない"
        "(csc.exeの既定マニフェストのままになっている疑い)".format(MANIFEST_IDENTITY_NAME))


# ---------------------------------------------------------------------------
# 3. 動的検査(負の対照): メタデータ無しでビルドすると空になること
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built_main_exe_without_assembly_info():
    """負の対照: app\\AssemblyInfo.cs を渡さずにDiveToPalworld.csだけをコンパイルする。
    メタデータ付与の仕組みを外した状態を模し、検査が本当に効いていることを示す
    (WP受入ゲート4「常に緑になる検査でないことの証明」)。"""
    csc = _csc_path()
    if not os.path.isfile(csc):
        pytest.skip("csc.exe (.NET Framework 4.8) が見つからない環境")
    build_dir = tempfile.mkdtemp(prefix="d2p_signpath_metadata_negcontrol_")
    out_exe = os.path.join(build_dir, "Uchinoko_no_metadata.exe")
    try:
        proc = subprocess.run(
            [csc, "/nologo", "/target:winexe", "/out:" + out_exe, "/optimize+",
             "/r:System.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll",
             "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll",
             MAIN_SRC],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if proc.returncode != 0 or not os.path.isfile(out_exe):
            pytest.fail("負の対照用ビルドに失敗した:\nrc={}\n{}".format(
                proc.returncode, (proc.stdout or "") + (proc.stderr or "")))
        yield out_exe
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def test_negative_control_exe_without_assembly_info_has_empty_metadata(
        built_main_exe_without_assembly_info):
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh (PowerShell 7) が見つからない環境")
    info = _read_version_info(built_main_exe_without_assembly_info)
    for field in ("CompanyName", "ProductName", "LegalCopyright", "FileDescription"):
        assert not (info.get(field) or "").strip(), (
            "AssemblyInfo無しでビルドしたのに{}が空でない(検査が常に緑になっている疑い): {}".format(
                field, info))
    # FileVersionはcsc.exeの既定値"0.0.0.0"になる(属性が無い場合の.NET既定挙動)
    assert info.get("FileVersion") in (None, "", "0.0.0.0"), (
        "AssemblyInfo無しなのにFileVersionが既定値でない: " + repr(info.get("FileVersion")))


def test_negative_control_exe_without_manifest_arg_lacks_custom_identity(
        built_main_exe_without_assembly_info):
    """dev#523の負の対照: /win32manifest:を渡さずにビルドすると、csc.exeの既定
    マニフェスト(name="MyApplication.app")が入るだけで、本プロジェクト固有の
    識別名(MANIFEST_IDENTITY_NAME)は入らないことを確認する。

    注意: csc.exeは/win32manifest省略時でも既定でrequestedExecutionLevel=
    asInvokerを含むマニフェストを自動生成するため(「asInvokerが無い」ことは
    起こらない)、この負の対照は「asInvokerの有無」ではなく「本プロジェクト
    固有の識別名の有無」で判定する(そうしないと常に緑になる検査になってしまう、
    WP受入ゲート4の趣旨)。"""
    with open(built_main_exe_without_assembly_info, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", errors="ignore")
    assert MANIFEST_IDENTITY_NAME not in text, (
        "/win32manifest無しでビルドしたのに本プロジェクト固有の識別名が"
        "含まれている(検査が常に緑になっている疑い)")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
