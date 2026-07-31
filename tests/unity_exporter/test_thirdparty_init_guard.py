# -*- coding: utf-8 -*-
r"""dev#194: 同居NDMFプラグイン(実例: Light Limit Changer/SE48AGFP事案)の
アセンブリ静的初期化子失敗が reflection呼び出しの TargetInvocationException として
Unity輸出全体を落とす問題への対応、の単体試験。

対象: unity\DiveToPalworldExporter.cs
仕様出典: dev#194本文(実報告SE48AGFP)、CLAUDE.md「入口で正規化、特別扱いを積むな」
節(特定サードパーティ製品への専用対応をしない、同種の"特定パッケージ名の
特別扱いを積まない"原則)。

背景: .NETの型初期化子(static constructor)は一度失敗すると、同一AppDomain内で
その型への以後のアクセスが全て即座に TypeInitializationException を返す
(BeforeFieldInit失敗のキャッシュ、プロセス/Editorセッションが終わるまで解除
されない)。reflection経由のMethodInfo.Invokeはこれを更に TargetInvocationException
で包むため、生の"Exception has been thrown by the target of an invocation."だけ
では原因のパッケージ・型が特定できない。

対応方針: 特定パッケージ名をコードに一切書かず、例外チェーンを辿って実際に
壊れた型名を抽出し、汎用の診断メッセージへ変換する(BuildInvocationFailureMessage)。
型初期化失敗はAppDomain内で恒久的なので自動リトライ/フォールバックは無意味
(かつ「効いていないのに直った」を偽装する害の方が大きい)と判断し、
「輸出は止めるが原因と対処が一目でわかる1行に変換する」方針を採った。

Unity無しでこの環境からは実行できない(GameObject等はUnityEngine型)ため、
2段構えで検証する:

1. test_pure_logic_positive_and_negative_control:
   診断ロジック(FindBrokenTypeInitializerName/RootCause/BuildInvocationFailureMessage)
   はSystem/System.Reflectionのみに依存する純粋関数として実装されている。
   これを本番ソースからマーカーコメント(D2P_INITGUARD_PURE_BEGIN/END)で
   **そのまま抽出**し、dotnetで実際にコンパイル・実行して振る舞いを検証する
   (コピー保守ではなく本番コードそのものを動かすので、ロジック変更の
   取りこぼしが起きない)。
   - 正の対照: TargetInvocationException→TypeInitializationExceptionの
     チェーンから壊れた型名を抽出でき、メッセージに再起動/パッケージ無効化の
     対処が含まれる
   - 負の対照: TypeInitializationExceptionを含まないチェーンでは
     brokenType=null になり、メッセージは「静的初期化」という語を含まない
     (=型初期化失敗ではない別原因の例外を、型初期化失敗であるかのように
     誤診断しないこと)

2. test_structural_wiring:
   BakeNdmf/ExportUnifiedFbxの2箇所のmi.Invoke呼び出しが実際に
   try/catch(TargetInvocationException)で囲まれ、BuildInvocationFailureMessageと
   Debug.LogException(生ログ保存)の両方を呼んでいることを構造チェックする。

3. test_no_package_name_hardcoded:
   純粋ロジックのソースに特定パッケージ名(azukimochi/Light Limit Changer等)が
   一切ハードコードされていないことを確認する(「特定パッケージの特別扱いを
   積まない」原則の構造的な担保)。

実行:
    python -m pytest tests\unity_exporter
    python tests\unity_exporter\test_thirdparty_init_guard.py
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
EXPORTER_CS = os.path.join(REPO_ROOT, "unity", "DiveToPalworldExporter.cs")

PURE_BEGIN = "// D2P_INITGUARD_PURE_BEGIN"
PURE_END = "// D2P_INITGUARD_PURE_END"


def _read_exporter_source():
    assert os.path.isfile(EXPORTER_CS), "unity\\DiveToPalworldExporter.cs が無い: " + EXPORTER_CS
    with open(EXPORTER_CS, encoding="utf-8") as f:
        return f.read()


def _extract_pure_block(source):
    """マーカー間の本番コードをそのまま抜き出す。マーカーが無い/複数あるのは
    実装が変わって抽出前提が壊れたということなので、SKIPではなくFAILさせる。"""
    begin_count = source.count(PURE_BEGIN)
    end_count = source.count(PURE_END)
    assert begin_count == 1 and end_count == 1, (
        "抽出マーカーが想定と違う(begin={}, end={})。"
        "unity\\DiveToPalworldExporter.cs のdev#194診断ロジックの構造が変わっていないか確認。"
        .format(begin_count, end_count))
    start = source.index(PURE_BEGIN) + len(PURE_BEGIN)
    end = source.index(PURE_END)
    assert start < end
    return source[start:end]


def _dotnet_available():
    return shutil.which("dotnet") is not None


# --- 1) 純粋ロジックの振る舞い(正負の対照) ------------------------------------

_HARNESS_PROGRAM_TEMPLATE = r"""
using System;
using System.Reflection;

internal static class InitGuardExtracted
{{
{pure_block}
}}

internal static class TestRunner
{{
    static int failures = 0;

    static void Check(bool cond, string label)
    {{
        if (!cond)
        {{
            Console.WriteLine("FAIL: " + label);
            failures++;
        }}
        else
        {{
            Console.WriteLine("PASS: " + label);
        }}
    }}

    // TargetInvocationException(TypeInitializationException(NullReferenceException))
    // という実報告(SE48AGFP)のログどおりのチェーンを組み立てる
    static TargetInvocationException BuildBrokenTypeInitChain(string typeName)
    {{
        var nre = new NullReferenceException("Object reference not set to an instance of an object");
        var tie = new TypeInitializationException(typeName, nre);
        return new TargetInvocationException(tie);
    }}

    // 型初期化失敗を経由しない、無関係な例外チェーン
    static TargetInvocationException BuildUnrelatedChain()
    {{
        var io = new InvalidOperationException("something else entirely broke");
        return new TargetInvocationException(io);
    }}

    static int Main()
    {{
        // ---- 正の対照: TypeInitializationExceptionを含むチェーンから型名を抽出できる ----
        var broken = BuildBrokenTypeInitChain("io.github.azukimochi.Utils");
        string brokenTypeName = InitGuardExtracted.FindBrokenTypeInitializerName(broken);
        Check(brokenTypeName == "io.github.azukimochi.Utils",
            "FindBrokenTypeInitializerName: 型初期化失敗チェーンから型名を抽出できる");

        string msgBroken = InitGuardExtracted.BuildInvocationFailureMessage("統合FBX書き出し", broken);
        Check(msgBroken.Contains("io.github.azukimochi.Utils"),
            "診断メッセージに実際に壊れた型名を含む(ハードコードでなく抽出値)");
        Check(msgBroken.Contains("静的初期化"), "診断メッセージが型初期化失敗である旨を説明する");
        Check(msgBroken.Contains("再起動"), "診断メッセージにUnity再起動という対処を含む");
        Check(msgBroken.Contains("統合FBX書き出し"), "診断メッセージにどの工程での失敗かを含む");

        // ---- 別の型名でも同様に(=特定パッケージ名への決め打ちでないこと) ----
        var brokenOther = BuildBrokenTypeInitChain("SomeOther.Namespace.Whatever");
        string msgOther = InitGuardExtracted.BuildInvocationFailureMessage("NDMFベイク", brokenOther);
        Check(msgOther.Contains("SomeOther.Namespace.Whatever"),
            "別の型名でも汎用に抽出・整形できる(特定パッケージへの決め打ちでない)");

        // ---- 負の対照: TypeInitializationExceptionを含まないチェーンはnull ----
        var unrelated = BuildUnrelatedChain();
        string brokenTypeNameNeg = InitGuardExtracted.FindBrokenTypeInitializerName(unrelated);
        Check(brokenTypeNameNeg == null,
            "FindBrokenTypeInitializerName: 型初期化失敗を含まないチェーンではnull");

        string msgUnrelated = InitGuardExtracted.BuildInvocationFailureMessage("NDMFベイク", unrelated);
        Check(!msgUnrelated.Contains("静的初期化"),
            "型初期化失敗でない例外を、型初期化失敗であるかのように誤診断しない");
        Check(msgUnrelated.Contains("InvalidOperationException"),
            "型初期化失敗でない場合は実際の例外の型名を伝える");
        Check(msgUnrelated.Contains("something else entirely broke"),
            "型初期化失敗でない場合は実際の例外のメッセージを伝える");

        // ---- RootCause: 多段ラップでも最内周の実例外まで辿る ----
        var root = InitGuardExtracted.RootCause(unrelated);
        Check(root is InvalidOperationException, "RootCauseが最内周の実例外まで辿る");

        Console.WriteLine(failures == 0 ? "ALL_PASS" : ("FAILURES=" + failures));
        return failures == 0 ? 0 : 1;
    }}
}}
"""

_HARNESS_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>disable</Nullable>
    <AssemblyName>InitGuardHarness</AssemblyName>
  </PropertyGroup>
</Project>
"""


@pytest.mark.skipif(not _dotnet_available(), reason="dotnet SDKが無い環境")
def test_pure_logic_positive_and_negative_control():
    source = _read_exporter_source()
    pure_block = _extract_pure_block(source)

    for needle in ("FindBrokenTypeInitializerName", "RootCause",
                   "BuildInvocationFailureMessage"):
        assert needle in pure_block, "抽出ブロックに{}が無い(実装が変わった?)".format(needle)

    program_cs = _HARNESS_PROGRAM_TEMPLATE.format(pure_block=pure_block)

    tmpdir = tempfile.mkdtemp(prefix="initguard_pure_harness_")
    try:
        with open(os.path.join(tmpdir, "Program.cs"), "w", encoding="utf-8") as f:
            f.write(program_cs)
        with open(os.path.join(tmpdir, "harness.csproj"), "w", encoding="utf-8") as f:
            f.write(_HARNESS_CSPROJ)

        proc = subprocess.run(
            ["dotnet", "run", "--project", tmpdir],
            cwd=tmpdir, capture_output=True, text=True, timeout=180)
        output = proc.stdout + "\n" + proc.stderr
        assert "ALL_PASS" in proc.stdout, (
            "dev#194診断ロジック(本番ソースから抽出)が期待どおりに動かなかった:\n"
            + output)
        assert proc.returncode == 0, "dotnet実行が非0終了:\n" + output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- 2) 呼び出し側の配線(2箇所のInvokeが実際にガードされている)の構造チェック ------

def test_structural_wiring():
    source = _read_exporter_source()

    checks = {
        "BakeNdmfのmi.InvokeがTargetInvocationExceptionを捕捉する": (
            r"mi\.Invoke\(null,\s*new object\[\]\s*\{\s*root\s*\}\);\s*\n\s*\}\s*\n"
            r"\s*catch\s*\(TargetInvocationException tie\)"),
        "ExportUnifiedFbxのmi.InvokeがTargetInvocationExceptionを捕捉する": (
            r"result\s*=\s*mi\.Invoke\(null,\s*args\)\s*as\s*string;\s*\n\s*\}\s*\n"
            r"\s*catch\s*\(TargetInvocationException tie\)"),
        "両方の捕捉箇所がBuildInvocationFailureMessageを呼ぶ": (
            r"throw new Exception\(BuildInvocationFailureMessage\(\"NDMF"),
        "ExportUnifiedFbx側もBuildInvocationFailureMessageを呼ぶ": (
            r"throw new Exception\(BuildInvocationFailureMessage\(\"統合FBX"),
        "両方の捕捉箇所が生の例外をDebug.LogExceptionでログに残す(調査用)": (
            r"catch\s*\(TargetInvocationException tie\)\s*\n\s*\{\s*\n"
            r"(?:\s*//[^\n]*\n)*"
            r"\s*Debug\.LogException\(tie\);"),
    }

    missing = []
    for label, pattern in checks.items():
        if re.search(pattern, source) is None:
            missing.append(label)

    assert not missing, "以下の配線が見当たらない:\n" + "\n".join("- " + m for m in missing)

    # Debug.LogExceptionを呼ぶcatchブロックが2箇所あることも数で確認
    log_count = len(re.findall(
        r"catch\s*\(TargetInvocationException tie\)\s*\n\s*\{\s*\n"
        r"(?:\s*//[^\n]*\n)*\s*Debug\.LogException\(tie\);",
        source))
    assert log_count == 2, (
        "TargetInvocationExceptionを捕捉してDebug.LogExceptionする箇所が{}件"
        "(期待値2件: BakeNdmf/ExportUnifiedFbx)。想定外の追加/削除がないか確認"
        .format(log_count))


# --- 3) 負の対照: 特定パッケージ名がハードコードされていないこと ------------------

def test_no_package_name_hardcoded():
    """「特定パッケージ名の特別扱いを積まない」原則の構造的な担保。
    診断ロジック(抽出ブロック)にazukimochi/Light Limit Changer等、実報告に出てきた
    固有のパッケージ名・作者名が直接書かれていないこと(=型名は実行時に例外チェーンから
    取り出した値であって、コード中の決め打ちではないこと)を確認する。"""
    source = _read_exporter_source()
    pure_block = _extract_pure_block(source)

    forbidden_substrings = ["azukimochi", "Light Limit Changer", "LightLimitChanger", "LLC"]
    found = [s for s in forbidden_substrings if s.lower() in pure_block.lower()]
    assert not found, (
        "診断ロジックに特定パッケージ名がハードコードされている: {}。"
        "CLAUDE.mdの「入口で正規化、特別扱いを積むな」"
        "(特定サードパーティ製品への専用対応をしない)原則に反する".format(found))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
