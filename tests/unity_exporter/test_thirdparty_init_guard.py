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
   「保護されるべき呼び出しサイト(reflectionのInvoke/SetValueを行う各静的メソッド)
   ごとに、try/catch(TargetInvocationException)がBuildInvocationFailureMessageと
   Debug.LogException(生ログ保存)の両方を呼んでいること」を関数単位で構造チェックする。
   PR #565(dev#518)でBakeNdmf/ExportUnifiedFbxの2箇所からSetFormatBinary/
   TrySetOption内の6箇所へ同パターンが正当に拡張された経緯を踏まえ、
   「捕捉パターンの全体出現数がちょうどN件」という数え上げには依存しない
   (拡張のたびに赤くなる脆い検査を避ける)。その代わり、既知の保護対象
   関数(KNOWN_PROTECTED_CALL_SITES)それぞれについて「危険な呼び出しサイトが
   存在し、かつそのサイトが漏れなく保護されている」ことを個別に検査する。

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


# --- 2) 呼び出し側の配線: 呼び出しサイト(関数)単位の構造チェック --------------------
#
# 「全体でN件」という数え上げをやめ、reflectionの危険な呼び出し
# (MethodInfo.Invoke/PropertyInfo.SetValue/FieldInfo.SetValue、変数名は本番コードの
# 命名規約に合わせ mi/m/p/f を対象とする)を1件ずつ検出し、それぞれが
# try/catch(TargetInvocationException)で囲まれ、かつcatch内でDebug.LogException(tie)と
# BuildInvocationFailureMessage(の両方を呼んでいるかを個別に判定する。

KNOWN_PROTECTED_CALL_SITES = ("BakeNdmf", "ExportUnifiedFbx", "SetFormatBinary", "TrySetOption")

_RISKY_CALL_RE = re.compile(r"\b(?:mi|m|p|f)\.(?:Invoke|SetValue)\s*\(")
_TRY_RE = re.compile(r"\btry\s*\r?\n?\s*\{")
_CATCH_RE = re.compile(r"\A\s*catch\s*\(TargetInvocationException tie\)\s*\r?\n?\s*\{")
_METHOD_SIG_RE = re.compile(
    r"\n {4}(?:internal |public |private |protected )?(?:static |readonly )*"
    r"[A-Za-z_][\w<>\[\],\.\s]*?\s+(\w+)\s*\([^)]*\)\s*\r?\n {4}\{")


def _find_matching_brace(source, open_index):
    """source[open_index]は'{'。対応する'}'のインデックスを返す。
    文字列/文字リテラル・コメント内の中括弧に惑わされないよう最低限スキップする。"""
    assert source[open_index] == "{", "呼び出し元のインデックス指定が'{'を指していない"
    depth = 0
    i = open_index
    n = len(source)
    while i < n:
        c = source[i]
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            i = source.index("\n", i)
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "*":
            i = source.index("*/", i + 2) + 2
            continue
        if c == "@" and i + 1 < n and source[i + 1] == '"':
            i += 2
            while i < n:
                if source[i] == '"' and (i + 1 >= n or source[i + 1] != '"'):
                    i += 1
                    break
                i += 2 if source[i] == '"' else 1
            continue
        if c == '"':
            i += 1
            while i < n and source[i] != '"':
                i += 2 if source[i] == "\\" else 1
            i += 1
            continue
        if c == "'":
            i += 1
            while i < n and source[i] != "'":
                i += 2 if source[i] == "\\" else 1
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError("マッチする閉じ括弧が見つからない(index={})".format(open_index))


def _extract_class_body(source, class_name):
    m = re.search(r"class\s+" + re.escape(class_name) + r"\b[^{]*\{", source)
    assert m, "クラス{}が見つからない".format(class_name)
    open_idx = m.end() - 1
    close_idx = _find_matching_brace(source, open_idx)
    return source[open_idx + 1:close_idx]


def _iter_top_level_methods(source):
    """DiveToPalworldExporterクラス直下(4スペースインデント)の各メソッドを
    (関数名, 本体文字列)で列挙する。8スペース以上ネストしたローカル関数は対象外
    (シグネチャを厳密に4スペースインデントに固定しているため)。"""
    body = _extract_class_body(source, "DiveToPalworldExporter")
    for m in _METHOD_SIG_RE.finditer(body):
        name = m.group(1)
        brace_idx = m.end() - 1
        end_idx = _find_matching_brace(body, brace_idx)
        yield name, body[brace_idx:end_idx + 1]


def _guarded_risky_call_sites(body):
    """body内の危険な呼び出し(mi/m/p/fのInvoke/SetValue)ごとに、それを囲む
    tryブロック直後のcatch(TargetInvocationException tie)がDebug.LogException(tie)と
    BuildInvocationFailureMessage(の両方を呼ぶかどうかを判定する。
    戻り値: [(呼び出しテキスト, 保護されているか), ...]"""
    results = []
    for call_m in _RISKY_CALL_RE.finditer(body):
        call_pos = call_m.start()
        try_m = None
        for tm in _TRY_RE.finditer(body, 0, call_pos):
            try_m = tm  # 呼び出し直前(=直近)のtryを採用
        if try_m is None:
            results.append((call_m.group(0), False))
            continue
        try_open = try_m.end() - 1
        try_close = _find_matching_brace(body, try_open)
        if not (try_open < call_pos < try_close):
            # 直近のtryが実際にこの呼び出しを囲んでいない(想定外の構造)
            results.append((call_m.group(0), False))
            continue
        after = body[try_close + 1:]
        catch_m = _CATCH_RE.match(after)
        if not catch_m:
            results.append((call_m.group(0), False))
            continue
        catch_open = try_close + 1 + catch_m.end() - 1
        catch_close = _find_matching_brace(body, catch_open)
        catch_body = body[catch_open + 1:catch_close]
        guarded = ("Debug.LogException(tie)" in catch_body
                   and "BuildInvocationFailureMessage(" in catch_body)
        results.append((call_m.group(0), guarded))
    return results


def test_structural_wiring():
    source = _read_exporter_source()
    functions = dict(_iter_top_level_methods(source))

    sites_by_function = {}
    for name, body in functions.items():
        sites = _guarded_risky_call_sites(body)
        if sites:
            sites_by_function[name] = sites

    # 既知の保護対象(dev#194/dev#518: BakeNdmf/ExportUnifiedFbx/SetFormatBinary/
    # TrySetOption)が今も危険な呼び出しサイトとして存在すること(関数の削除・
    # リネームで検査が骨抜きにならないための最低ライン)
    missing_functions = [n for n in KNOWN_PROTECTED_CALL_SITES if n not in sites_by_function]
    assert not missing_functions, (
        "以下の関数に危険なreflection呼び出し(mi/m/p/f.Invoke|SetValue)が"
        "見当たらない(関数名変更・削除の可能性): " + ", ".join(missing_functions))

    # 呼び出しサイトごと(関数を問わず全件)にガードが効いていること。
    # これがdev#194/dev#518ガードの本体チェック(全体件数には依存しない)
    unguarded = []
    for name, sites in sites_by_function.items():
        for call_text, guarded in sites:
            if not guarded:
                unguarded.append("{}: {}".format(name, call_text))
    assert not unguarded, (
        "以下の呼び出しサイトがTargetInvocationException捕捉+Debug.LogException+"
        "BuildInvocationFailureMessageで保護されていない:\n"
        + "\n".join("- " + u for u in unguarded))

    # 既知の各関数について、保護済みの呼び出しサイトが1件以上あること
    for name in KNOWN_PROTECTED_CALL_SITES:
        assert any(guarded for _, guarded in sites_by_function[name]), (
            "{}に危険な呼び出しはあるが、保護済みの呼び出しサイトが1件も無い".format(name))


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
