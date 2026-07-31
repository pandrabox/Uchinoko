# -*- coding: utf-8 -*-
r"""dev#300(実報告VLGQR7ES)の単体試験。

対象: unity\DiveToPalworldExporter.cs の EnsureUniqueTransformNames / ResolveUniqueNames

背景: 非スキンメッシュ(帽子・尻尾等のアクセサリ)がmaterial_map.jsonに載らず
ソリッドカラー化する残存ケース。原因分析(dev#300本文+work\issue_zero\i300\NOTES.md):
Unity純正FBXエクスポータ(com.unity.formats.fbx)は、書き出し対象の階層内に
同名のTransformが複数存在すると、内部で連番サフィックス(例: "Tail"→"Tail_3")を
付けて一意化してしまう。ExportHumanoid/ExportMaterialsはこのリネームを知らず、
輸出前のUnity上の名前(Transform.name)をキーにhumanoid.json/material_map.jsonを
書くため、輸出対象の階層に重複名が存在すると輸出後のFBX実体の名前とズレて
参照が外れる(VRM/VRChatアバターの尻尾・耳等のボーンチェーンは同一名の連続が
一般的で、その末端に同名の非スキンアクセサリメッシュが付く構成もよくある)。

修正: 輸出直前(ExportHumanoid/ExportUnifiedFbx/ExportMaterialsのいずれよりも
前)に階層全体のTransform名を一括して一意化することで、Unity FBXエクスポータが
独自にリネームする余地そのものを無くす(入口で正規化。症状別の特別扱いを
増やさない)。

Unity無しでこの環境からは実行できない(GameObject/Transform等はUnityEngine型)
ため、dev#194のtest_thirdparty_init_guard.py / dev#250のtest_bone_name_suggest.py
と同じ2段構えで検証する:

1. test_pure_logic_controls:
   判定ロジック(ResolveUniqueNames)はUnityEngine型に一切依存しない(文字列・
   コレクションのみ)純粋関数として実装されている。これを本番ソースから
   マーカーコメント(D2P_UNIQUENAME_PURE_BEGIN/END)でそのまま抽出し、dotnetで
   実際にコンパイル・実行して振る舞いを検証する。対照:
   ① 重複なし → 全て無変更(正の対照。無関係な変更を混入させない)
   ② 実報告と同型: 同名Transformが4つ連続("Tail"→"Tail"→"Tail"→"Tail",
      3番目=ボーン扱い、4番目=非スキンメッシュ相当) → 2件目以降が
      "Tail_2"→"Tail_3"→"Tail_4"に一意化される
      (dev#300ログ実例 "mesh renamed: 'Tail_3' -> geo_04" と整合する連番)
   ③ 衝突回避(負の対照): 元から"Tail_2"という名前が別枠で存在する状態で
      "Tail"が重複した場合、単純な"_2"付与だと"Tail_2"を上書き(衝突)してしまう。
      衝突を避けてさらに数字を進めた名前になることを確認する
      (「値を寄せて合わせる」場当たり実装ではないことの担保)
   ④ Renderer-Renderer間だけでなくRenderer-非Renderer間(ボーン等)の重複も
      解消対象になることを確認する(ExportMaterials既存のseenNamesチェックが
      検知できなかった経路の直接的な対照)

2. test_structural_wiring:
   Export()がEnsureUniqueTransformNamesを、ExportHumanoid/ExportUnifiedFbx/
   ExportMaterialsの**いずれよりも前**に呼んでいることを構造チェックする
   (これより後に置くと再びズレが復活するため、配線順序そのものが仕様)。

実行:
    python -m pytest tests\unity_exporter\test_material_map_dup_rename.py
    python tests\unity_exporter\test_material_map_dup_rename.py
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

PURE_BEGIN = "// D2P_UNIQUENAME_PURE_BEGIN"
PURE_END = "// D2P_UNIQUENAME_PURE_END"


def _read_exporter_source():
    assert os.path.isfile(EXPORTER_CS), "unity\\DiveToPalworldExporter.cs が無い: " + EXPORTER_CS
    with open(EXPORTER_CS, encoding="utf-8") as f:
        return f.read()


def _extract_pure_block(source):
    begin_count = source.count(PURE_BEGIN)
    end_count = source.count(PURE_END)
    assert begin_count == 1 and end_count == 1, (
        "抽出マーカーが想定と違う(begin={}, end={})。"
        "unity\\DiveToPalworldExporter.cs のdev#300名前重複解消ロジックの構造が"
        "変わっていないか確認。".format(begin_count, end_count))
    start = source.index(PURE_BEGIN) + len(PURE_BEGIN)
    end = source.index(PURE_END)
    assert start < end
    return source[start:end]


def _dotnet_available():
    return shutil.which("dotnet") is not None


# --- 1) 純粋ロジックの振る舞い(4対照) -----------------------------------------

_HARNESS_PROGRAM_TEMPLATE = r"""
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

internal static class UniqueNameExtracted
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

    static int Main()
    {{
        // ---- ①正の対照: 重複なし → 全て無変更 ----
        {{
            var input = new List<string> {{ "Hips", "Spine", "Head", "Beret" }};
            var result = UniqueNameExtracted.ResolveUniqueNames(input);
            Check(result.SequenceEqual(input),
                "①重複なし: 無関係な名前は一切変更されない");
        }}

        // ---- ②実報告と同型: 同名Transformが4連続(尻尾ボーン3+非スキンメッシュ1) ----
        {{
            // dev#300実報告の階層を単純化: Tail(bone)->Tail(bone)->Tail(bone)->Tail(mesh)
            var input = new List<string> {{ "Hips", "Tail", "Tail", "Tail", "Tail" }};
            var result = UniqueNameExtracted.ResolveUniqueNames(input);
            Check(result[0] == "Hips", "②無関係なHipsは無変更");
            Check(result[1] == "Tail", "②最初のTailは無変更(先勝ち)");
            Check(result[2] == "Tail_2", "②2件目はTail_2");
            Check(result[3] == "Tail_3", "②3件目はTail_3(実報告ログの'Tail_3'と一致する連番)");
            Check(result[4] == "Tail_4", "②4件目(非スキンメッシュ相当)はTail_4");
            Check(result.Distinct().Count() == result.Count, "②結果は全体で一意(重複ゼロ)");
        }}

        // ---- ③負の対照: 既存の"Tail_2"と衝突しない(単純な"_2"固定付与は不可) ----
        {{
            // 元から独立した"Tail_2"という名前のオブジェクトが存在する状態で
            // "Tail"が重複した場合、素朴に"_2"を付けるとTail_2を上書き(衝突)する。
            var input = new List<string> {{ "Tail", "Tail_2", "Tail" }};
            var result = UniqueNameExtracted.ResolveUniqueNames(input);
            Check(result[0] == "Tail", "③最初のTailは無変更");
            Check(result[1] == "Tail_2", "③独立したTail_2はそのまま(誤って巻き込まない)");
            Check(result[2] != "Tail_2" && result[2] != "Tail",
                "③負の対照: 2番目のTailは衝突するTail_2を素通りせず別名になる(値を寄せる実装では無い)");
            Check(result.Distinct().Count() == result.Count, "③結果は全体で一意(衝突ゼロ)");
        }}

        // ---- ④Renderer-非Renderer間の重複も解消対象(ExportMaterials既存チェックの穴) ----
        {{
            // 実報告の核心: ExportMaterials側のseenNamesはRenderer同士の重複しか
            // 見ないため、"Ribbon"という名前がボーン(非Renderer)と衝突している
            // ケースは元の実装では検知できない。ResolveUniqueNamesは名前列だけを
            // 見るため、Rendererかどうかを問わず等しく解消する。
            var input = new List<string> {{ "Head", "Ribbon", "Ribbon" }};  // 1件目=ボーン、2件目=非スキンメッシュ、という想定
            var result = UniqueNameExtracted.ResolveUniqueNames(input);
            Check(result[1] == "Ribbon", "④1件目(ボーン相当)は無変更");
            Check(result[2] == "Ribbon_2",
                "④2件目(非スキンメッシュ相当)はRibbon_2に一意化される(Renderer同士でなくても重複を検知できることの担保)");
        }}

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
    <AssemblyName>UniqueNameHarness</AssemblyName>
  </PropertyGroup>
</Project>
"""


@pytest.mark.skipif(not _dotnet_available(), reason="dotnet SDKが無い環境")
def test_pure_logic_controls():
    source = _read_exporter_source()
    pure_block = _extract_pure_block(source)

    assert "ResolveUniqueNames" in pure_block, "抽出ブロックにResolveUniqueNamesが無い(実装が変わった?)"

    program_cs = _HARNESS_PROGRAM_TEMPLATE.format(pure_block=pure_block)

    tmpdir = tempfile.mkdtemp(prefix="uniquename_pure_harness_")
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
            "dev#300名前重複解消ロジック(本番ソースから抽出)が期待どおりに"
            "動かなかった:\n" + output)
        assert proc.returncode == 0, "dotnet実行が非0終了:\n" + output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- 2) 呼び出し側の配線(ExportHumanoid等より前に呼ばれること)の構造チェック ------

def test_structural_wiring():
    source = _read_exporter_source()

    checks = {
        "Export()がEnsureUniqueTransformNamesをExportHumanoidの直前で呼ぶ": (
            r"EnsureUniqueTransformNames\(instance\);[^\n]*\n"
            r"\s*ExportHumanoid\(instance, outDir\);"
        ),
        "EnsureUniqueTransformNamesは階層全体(CollectAllTransforms)を走査する": (
            r"static void EnsureUniqueTransformNames\(GameObject root\)\s*\n"
            r"\s*\{\s*\n"
            r"\s*var all = new List<Transform>\(\);\s*\n"
            r"\s*CollectAllTransforms\(root\.transform, all\);"
        ),
        "EnsureUniqueTransformNamesはResolveUniqueNamesの結果をTransform.nameへ反映する": (
            r"all\[i\]\.name = uniqueNames\[i\];"
        ),
    }

    missing = []
    for label, pattern in checks.items():
        if re.search(pattern, source) is None:
            missing.append(label)

    assert not missing, "以下の配線が見当たらない:\n" + "\n".join("- " + m for m in missing)

    # ExportHumanoid/ExportUnifiedFbx/ExportMaterialsの呼び出し順で
    # EnsureUniqueTransformNamesが最初に来ていること(文字列位置で確認)。
    idx_ensure = source.index("EnsureUniqueTransformNames(instance);")
    idx_humanoid = source.index("ExportHumanoid(instance, outDir);")
    idx_fbx = source.index("string fbxName = ExportUnifiedFbx(instance, outDir);")
    idx_materials = source.index("ExportMaterials(instance, outDir, fbxName);")
    assert idx_ensure < idx_humanoid < idx_fbx < idx_materials, (
        "EnsureUniqueTransformNamesはExportHumanoid/ExportUnifiedFbx/ExportMaterials"
        "の**いずれよりも前**に呼ばれる必要がある(呼び出し順序: "
        "ensure={}, humanoid={}, fbx={}, materials={})".format(
            idx_ensure, idx_humanoid, idx_fbx, idx_materials))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
