# -*- coding: utf-8 -*-
r"""dev#250(オーナー裁定2026-07-30、実報告Z8XBKJBC)の単体試験。

対象: unity\DiveToPalworldExporter.cs の ExportHumanoid系
仕様出典: dev#250本文、CLAUDE.md「検証の作法」節(負の対照を取る)、
    「値を寄せて合わせる修正は却下」節。

背景: prefab→Unity輸出は成功したのに、Rig設定(Configure Avatar)で必須
HumanBone(例: Left Foot)が未割当のまま保存されたアバターが実在し
(isHuman==trueでも起こりうる、dev#233実測)、従来はhumanoid.jsonに
当該キーが載らないまま素通りしてBlender側のFATALで初めて発覚していた。

オーナー裁定: 「こちらの側で名前からサジェストして対応する機能をつくるべき。
humanoid取得は名前を取るだけの話」。さらに実装中の追加裁定: 「曖昧なら
止まってユーザーに聞く、がこのプロジェクトの原則。『既知の問題だからエラー
出せばOK』は通らない」。曖昧(候補複数)・候補ゼロのいずれも自動選択せず、
対話できる経路(Unity Editorのメニュー実行)ではダイアログで選ばせ、
対話できない経路(バッチ実行)では候補+bone_overrides.jsonでの明示指定方法を
提示して停止する。

Unity無しでこの環境からは実行できない(GameObject等はUnityEngine型)ため、
dev#194のtest_thirdparty_init_guard.pyと同じ2段構えで検証する:

1. test_pure_logic_four_controls:
   判定ロジック(SuggestBoneName/FindNearMisses/ResolveRequiredBone/
   BuildUnresolvedHeadlessMessage)はSystem/System.Text.RegularExpressions
   非依存(Unity型もRegexも使わない、文字列・コレクションのみ)の純粋関数として
   実装されている。これを本番ソースからマーカーコメント
   (D2P_BONESUGGEST_PURE_BEGIN/END)でそのまま抽出し、dotnetで実際に
   コンパイル・実行して振る舞いを検証する。4つの対照:
   ① 全必須ボーン割当済み → Source="already_assigned"(無変更)
   ② 未割当+名前から一意候補 → Source="suggested"で自動推定成功
   ③ 未割当+候補ゼロ → 自動選択せず Status=NotFound で足踏み
   ④ 未割当+候補複数(曖昧) → 自動選択せず Status=Ambiguous で足踏み
   加えて bone_overrides.json 相当(Dictionary指定)の正常系・不正値系、
   命名規約辞書がMixamo/VRoid/Blender式/日本語をカバーすることも確認する。

2. test_structural_wiring:
   ExportHumanoidがApplyBoneNameSuggestionsを呼ぶこと、
   ApplyBoneNameSuggestionsがApplication.isBatchModeで分岐し、headless時は
   BuildUnresolvedHeadlessMessageで例外にする一方、interactive時は
   BoneChoiceWindow(ユーザー起点の対話)を使うことを構造チェックする
   (「曖昧なら勝手に選ばず聞く」が両経路に配線されていることの担保)。

実行:
    python -m pytest tests\unity_exporter\test_bone_name_suggest.py
    python tests\unity_exporter\test_bone_name_suggest.py
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

PURE_BEGIN = "// D2P_BONESUGGEST_PURE_BEGIN"
PURE_END = "// D2P_BONESUGGEST_PURE_END"


def _read_exporter_source():
    assert os.path.isfile(EXPORTER_CS), "unity\\DiveToPalworldExporter.cs が無い: " + EXPORTER_CS
    with open(EXPORTER_CS, encoding="utf-8") as f:
        return f.read()


def _extract_pure_block(source):
    begin_count = source.count(PURE_BEGIN)
    end_count = source.count(PURE_END)
    assert begin_count == 1 and end_count == 1, (
        "抽出マーカーが想定と違う(begin={}, end={})。"
        "unity\\DiveToPalworldExporter.cs のdev#250ボーン推定ロジックの構造が"
        "変わっていないか確認。".format(begin_count, end_count))
    start = source.index(PURE_BEGIN) + len(PURE_BEGIN)
    end = source.index(PURE_END)
    assert start < end
    return source[start:end]


def _dotnet_available():
    return shutil.which("dotnet") is not None


# --- 1) 純粋ロジックの振る舞い(4対照+override+辞書網羅) -----------------------

_HARNESS_PROGRAM_TEMPLATE = r"""
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

internal static class BoneSuggestExtracted
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
        // ---- ①正の対照: 全必須ボーン割当済み → 無変更(already_assigned) ----
        {{
            var actual = new List<string> {{ "Hips", "Spine", "Head" }};  // 中身は問わない
            var d = BoneSuggestExtracted.ResolveRequiredBone(
                "LeftFoot", "SomeAlreadyAssignedBone", null, actual);
            Check(d.Assigned && d.Source == "already_assigned" && d.BoneName == "SomeAlreadyAssignedBone",
                "①全割当済み: 既存boneNameがそのまま尊重される(無変更)");
        }}

        // ---- ②正の対照: 未割当+名前から一意候補(Mixamo表記) → 自動推定成功 ----
        {{
            var actual = new List<string> {{
                "Hips", "Spine", "Head", "mixamorig:LeftUpperArmDummy",
                "mixamorig:LeftFoot", "RightFootUnrelated"
            }};
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", null, actual);
            Check(d.Assigned && d.Source == "suggested" && d.BoneName == "mixamorig:LeftFoot",
                "②一意候補: mixamorig:LeftFootをLeftFootへ自動推定");
        }}

        // ---- ③負の対照: 未割当+候補ゼロ → 自動選択せず足踏み(誤割当禁止) ----
        {{
            var actual = new List<string> {{ "Hips", "Spine", "Head", "SomethingElseEntirely" }};
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", null, actual);
            Check(!d.Assigned && d.Status == BoneSuggestExtracted.BoneSuggestStatus.NotFound,
                "③候補ゼロ: 自動選択せずNotFoundで足踏み(勝手に選ばない)");
        }}

        // ---- ④負の対照: 未割当+候補複数(曖昧) → 自動選択せず足踏み(誤割当禁止) ----
        {{
            var actual = new List<string> {{ "Hips", "LeftFoot", "Foot.L" }};  // 2件が別名一致
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", null, actual);
            Check(!d.Assigned && d.Status == BoneSuggestExtracted.BoneSuggestStatus.Ambiguous
                && d.Candidates.Count == 2,
                "④曖昧: 複数候補で自動選択せずAmbiguousで足踏み(誤割当より安全側)");
        }}

        // ---- 同一名の重複出現は曖昧扱いしない(名前一致の実体は1つ) ----
        {{
            var actual = new List<string> {{ "LeftFoot", "LeftFoot", "Unrelated" }};
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", null, actual);
            Check(d.Assigned && d.Source == "suggested" && d.BoneName == "LeftFoot",
                "同一ボーン名の重複出現はAmbiguousと誤判定しない");
        }}

        // ---- bone_overrides.json相当(Dictionary)の正常系 ----
        {{
            var actual = new List<string> {{ "Hips", "CustomFootBoneXYZ" }};
            var overrides = new Dictionary<string, string> {{ {{ "LeftFoot", "CustomFootBoneXYZ" }} }};
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", overrides, actual);
            Check(d.Assigned && d.Source == "override" && d.BoneName == "CustomFootBoneXYZ",
                "override正常系: 指定ボーン名が実在すればそれを採用");
        }}

        // ---- bone_overrides.json相当、指定値がこのアバターに存在しない ----
        {{
            var actual = new List<string> {{ "Hips", "Spine" }};
            var overrides = new Dictionary<string, string> {{ {{ "LeftFoot", "DoesNotExist" }} }};
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", overrides, actual);
            Check(!d.Assigned && d.Source == "override_invalid",
                "override不正系: 実在しない指定は自動採用せずoverride_invalidで足踏み");
        }}

        // ---- 命名規約辞書: Unity標準/Mixamo/VRoid/Blender式/日本語をカバー ----
        {{
            string[][] cases = new[] {{
                new[] {{ "LeftFoot", "LeftFoot" }},               // Unity標準
                new[] {{ "LeftFoot", "mixamorig:LeftFoot" }},     // Mixamo
                new[] {{ "LeftFoot", "J_Bip_L_Foot" }},           // VRoid
                new[] {{ "LeftFoot", "Foot.L" }},                 // Blender式(dot)
                new[] {{ "LeftFoot", "Foot_L" }},                 // Blender式(underscore)
                new[] {{ "LeftFoot", "左足首" }},                  // 日本語
                new[] {{ "LeftUpperLeg", "mixamorig:LeftUpLeg" }},// Mixamo(UpperLeg=UpLeg)
                new[] {{ "LeftUpperArm", "mixamorig:LeftArm" }},  // Mixamo(UpperArm=Arm)
                new[] {{ "Hips", "J_Bip_C_Hips" }},               // VRoid(センター系)
                new[] {{ "RightHand", "Hand.R" }},                // 右側Blender式
            }};
            foreach (var c in cases)
            {{
                string humanName = c[0], boneName = c[1];
                var actual = new List<string> {{ "Unrelated1", "Unrelated2", boneName }};
                var d = BoneSuggestExtracted.ResolveRequiredBone(humanName, "", null, actual);
                Check(d.Assigned && d.BoneName == boneName,
                    "命名規約辞書: " + humanName + " <- " + boneName);
            }}
        }}

        // ---- 大文字小文字・区切り文字ゆらぎの吸収 ----
        {{
            var actual = new List<string> {{ "leftfoot" }};  // 全部小文字・区切りなし
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", null, actual);
            Check(d.Assigned && d.BoneName == "leftfoot",
                "大文字小文字ゆらぎ: 'leftfoot'(全小文字)もLeftFootに一致");
        }}

        // ---- 候補ゼロ時の近い名前ヒント(自動選択はしない) ----
        {{
            var actual = new List<string> {{ "LeftFotoTypo" }};  // わずかに違う綴り
            var near = BoneSuggestExtracted.FindNearMisses("LeftFoot", actual, 5);
            Check(near.Contains("LeftFotoTypo"),
                "候補ゼロでも近い綴りはヒントとして拾う(自動選択はしない)");
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", null, actual);
            Check(!d.Assigned && d.Status == BoneSuggestExtracted.BoneSuggestStatus.NotFound
                && d.Candidates.Contains("LeftFotoTypo"),
                "近い候補があっても自動選択せずNotFoundのまま(候補はヒントとして持つだけ)");
        }}

        // ---- headless向けメッセージ: dev#233方向(人間可読名+対処手順)を含む ----
        {{
            var actual = new List<string> {{ "Hips", "LeftFoot", "Foot.L" }};
            var d = BoneSuggestExtracted.ResolveRequiredBone("LeftFoot", "", null, actual);
            string msg = BoneSuggestExtracted.BuildUnresolvedHeadlessMessage("LeftFoot", d, @"C:\out");
            Check(msg.Contains("Left Foot") || msg.Contains("左足"),
                "headlessメッセージにUnity側の人間可読名を含む(dev#233方向)");
            Check(msg.Contains("Configure Avatar"),
                "headlessメッセージにUnity側の対処手順(Configure Avatar)を含む");
            Check(msg.Contains("bone_overrides.json"),
                "headlessメッセージに明示指定の方法(bone_overrides.json)を含む");
            Check(msg.Contains("LeftFoot") && msg.Contains("Foot.L"),
                "headlessメッセージに実際の候補名を(誤選択せず)列挙する");
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
    <AssemblyName>BoneSuggestHarness</AssemblyName>
  </PropertyGroup>
</Project>
"""


@pytest.mark.skipif(not _dotnet_available(), reason="dotnet SDKが無い環境")
def test_pure_logic_four_controls():
    source = _read_exporter_source()
    pure_block = _extract_pure_block(source)

    for needle in ("SuggestBoneName", "FindNearMisses", "ResolveRequiredBone",
                   "BuildUnresolvedHeadlessMessage", "RequiredHumanBoneAliases"):
        assert needle in pure_block, "抽出ブロックに{}が無い(実装が変わった?)".format(needle)

    program_cs = _HARNESS_PROGRAM_TEMPLATE.format(pure_block=pure_block)

    tmpdir = tempfile.mkdtemp(prefix="bonesuggest_pure_harness_")
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
            "dev#250ボーン名推定ロジック(本番ソースから抽出)が期待どおりに"
            "動かなかった:\n" + output)
        assert proc.returncode == 0, "dotnet実行が非0終了:\n" + output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- 2) 呼び出し側の配線(headless/interactiveの両経路)の構造チェック ------------

def test_structural_wiring():
    source = _read_exporter_source()

    checks = {
        "ExportHumanoidが必須ボーンの複製リストを作りApplyBoneNameSuggestionsを呼ぶ": (
            r"var human = new List<HumanBone>\(animator\.avatar\.humanDescription\.human\);\s*\n"
            r"\s*ApplyBoneNameSuggestions\(go, human, outDir\);"
        ),
        "ExportHumanoidのJSON出力ループが複製リスト(human)を走査する"
        "(生のavatar.humanDescription.humanを直接使わない)": (
            r"foreach \(var hb in human\)\s*\n\s*\{\s*\n\s*if \(string\.IsNullOrEmpty\(hb\.boneName\)\)"
        ),
        "既に割当済みの必須ボーンは無変更(continue)": (
            r'if \(decision\.Source == "already_assigned"\) continue;'
        ),
        "headless(バッチ実行)はApplication.isBatchModeで判定し例外で止める": (
            r"UnityEngine\.Application\.isBatchMode\s*\)\s*\n"
            r"\s*\{\s*\n"
            r"(?:\s*//[^\n]*\n)*"
            r"\s*throw new Exception\(BuildUnresolvedHeadlessMessage"
        ),
        "interactive(Editorメニュー実行)はBoneChoiceWindowでユーザーに選ばせる"
        "(勝手に選ばない)": (
            r"BoneChoiceWindow\.PickBone\("
        ),
        "interactiveでキャンセルされたら輸出を中止する(誤った既定値で進めない)": (
            r"if \(resolvedName == null\)\s*\n\s*throw new Exception\("
        ),
        "bone_overrides.jsonの不正指定(override_invalid)も自動で無視せず例外にする": (
            r'decision\.Source == "override_invalid"\s*\)\s*\n'
            r"\s*\{\s*\n\s*throw new Exception\(BuildUnresolvedHeadlessMessage"
        ),
    }

    missing = []
    for label, pattern in checks.items():
        if re.search(pattern, source) is None:
            missing.append(label)

    assert not missing, "以下の配線が見当たらない:\n" + "\n".join("- " + m for m in missing)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
