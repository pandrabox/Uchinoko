# -*- coding: utf-8 -*-
r"""dev#455: CollapseNestedArmatureContainersの収縮判定基準を
StripNonEssentialPostBakeと統一したことの単体試験。

対象: unity\DiveToPalworldExporter.cs
仕様出典: dev#455コメント列(2026-08-01再現成功報告+修正方針)。

背景(根本原因): NDMF/Modular AvatarのMerge Armatureが揺れ物(PhysBone)付き
装飾品のために生成する`Foo$<GUID>`形式のアンカーノードは、
CollapseNestedArmatureContainersが走る時点(BakeNdmf後・StripNonEssentialPostBake前)
ではまだVRCPhysBone/VRCPhysBoneCollider/VRCRotationConstraint等のコンポーネントを
持ったままである(これらは9行後のStripNonEssentialPostBakeで初めて除去される)。
旧実装は「Transform以外のコンポーネントを1つでも持てば収縮しない」
(`GetComponents<Component>().Length > 1`)という基準だったため、このアンカーノードは
コンポーネントを持っているという理由だけで収縮対象から除外され、そのままFBXへ
書き出される。BlenderのFBXインポータ(find_armatures())はボーンの子孫方向にしか
探索しないため、この生き残ったノードは発見されず、配下のメッシュが外側armatureへ
誤帰属して`KeyError: <外側armature名>`になる。

修正: 収縮可否の基準を「Transform以外の“実データを保持する”必須型
(Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)を持つか」に変更した
(HasEssentialNonTransformComponent、StripNonEssentialPostBakeが除去する/しないの
判定基準IsEssentialComponentTypeを共有)。これにより、どうせ後で除去される
「使い捨て」コンポーネント(PhysBone等)は収縮を妨げなくなり、実データを保持する
ノード(メッシュ/アニメーターを持つノード)だけが安全のため収縮対象から除外される。

Unity無しでこの環境からは実行できない(GameObject/Transform等はUnityEngine型)ため、
本番ソースからマーカーコメント(D2P_COLLAPSE455_ESSENTIAL_BEGIN/END,
D2P_COLLAPSE455_ALGO_BEGIN/END)でロジックをそのまま抽出し、UnityEngine型の
最小スタブ(GameObject/Transform/Component等)を用意してdotnetで実際にコンパイル・
実行して振る舞いを検証する(コピー保守ではなく本番コードそのものを動かす)。

検証シナリオ(いずれもHips/Spine/Chest/Head本体ボーン+Head直下の非ボーン
アンカー+その下の独立ジグルボーンAccBone_L、というdev#455の実欠陥構造):

1. test_disposable_anchor_now_collapses (正の対照、赤→緑):
   アンカーがVRCPhysBone等の代役(FakeDisposableComponent、非必須型)だけを
   持つ場合、旧基準(コンポーネント数==1)ならアンカーは収縮されず取り残される
   ことを確認した上で(OldBasisWouldSkipで再現)、新基準では実際に収縮され、
   AccBone_LがHeadへ直結されることを確認する。

2. test_data_bearing_anchor_still_protected (負の対照、無退行):
   アンカーが実データ保持型(SkinnedMeshRenderer)を持つ場合は、新基準でも
   引き続き収縮されない(メッシュデータを道連れに失わない)ことを確認する。

3. test_bare_anchor_still_collapses (回帰ガード):
   アンカーが何も余計なコンポーネントを持たない場合(旧基準でも収縮していた
   既存の正常系)は、新基準でも引き続き収縮されることを確認する。

実行:
    python -m pytest tests\unity_exporter
    python tests\unity_exporter\test_collapse_essential_basis.py
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

ESSENTIAL_BEGIN = "// D2P_COLLAPSE455_ESSENTIAL_BEGIN"
ESSENTIAL_END = "// D2P_COLLAPSE455_ESSENTIAL_END"
ALGO_BEGIN = "// D2P_COLLAPSE455_ALGO_BEGIN"
ALGO_END = "// D2P_COLLAPSE455_ALGO_END"


def _read_exporter_source():
    assert os.path.isfile(EXPORTER_CS), "unity\\DiveToPalworldExporter.cs が無い: " + EXPORTER_CS
    with open(EXPORTER_CS, encoding="utf-8") as f:
        return f.read()


def _extract_block(source, begin_marker, end_marker):
    """マーカー間の本番コードをそのまま抜き出す。マーカーが無い/複数あるのは
    実装が変わって抽出前提が壊れたということなので、SKIPではなくFAILさせる。"""
    begin_count = source.count(begin_marker)
    end_count = source.count(end_marker)
    assert begin_count == 1 and end_count == 1, (
        "抽出マーカーが想定と違う({}: begin={}, end={})。"
        "unity\\DiveToPalworldExporter.cs のdev#455 collapse判定の構造が変わっていないか確認。"
        .format(begin_marker, begin_count, end_count))
    start = source.index(begin_marker) + len(begin_marker)
    end = source.index(end_marker)
    assert start < end
    return source[start:end]


def _make_methods_cross_class_visible(block):
    """抽出ブロックはTestRunner(別クラス)から呼ぶ必要があるが、本番コードの
    トップレベルstaticメソッドは既定でprivate(同一クラス内からしかアクセス
    不可)。ロジック本体には一切触れず、アクセス修飾子だけ`internal`へ底上げ
    する(既存のFindBrokenTypeInitializerName等と同じ、テスト可能にするための
    可視性拡張パターン)。"""
    return re.sub(r"(?m)^(\s*)static\b", r"\1internal static", block)


def _dotnet_available():
    return shutil.which("dotnet") is not None


# ---- UnityEngine型の最小スタブ + 抽出ロジックを埋め込んだハーネス ----
_HARNESS_PROGRAM_TEMPLATE = r"""
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace UnityEngine
{{
    public class Component
    {{
        public GameObject gameObject;
        public Transform transform {{ get {{ return gameObject.transform; }} }}
    }}

    public class Transform : Component, IEnumerable
    {{
        public Transform parent;
        public List<Transform> ChildrenList = new List<Transform>();

        public Component[] GetComponents<T>() where T : Component
        {{
            return gameObject.components.ToArray();
        }}

        public void SetParent(Transform newParent, bool worldPositionStays)
        {{
            if (parent != null) parent.ChildrenList.Remove(this);
            parent = newParent;
            if (newParent != null) newParent.ChildrenList.Add(this);
        }}

        public IEnumerator GetEnumerator() {{ return ChildrenList.GetEnumerator(); }}
    }}

    public class Animator : Component {{ }}
    public class MeshRenderer : Component {{ }}
    public class MeshFilter : Component {{ }}
    public class SkinnedMeshRenderer : Component {{ public Transform[] bones; }}

    // VRCPhysBone/VRCPhysBoneCollider/VRCRotationConstraint等、
    // StripNonEssentialPostBakeでどうせ後から除去される「使い捨て」型の代役
    public class FakeDisposableComponent : Component {{ }}

    public class GameObject
    {{
        public string name;
        public Transform transform;
        public List<Component> components = new List<Component>();

        public GameObject(string name)
        {{
            this.name = name;
            transform = new Transform();
            transform.gameObject = this;
            components.Add(transform);
        }}

        public T[] GetComponentsInChildren<T>(bool includeInactive) where T : Component
        {{
            var result = new List<T>();
            Action<Transform> walk = null;
            walk = (t) =>
            {{
                foreach (var c in t.gameObject.components) if (c is T tc) result.Add(tc);
                foreach (var child in t.ChildrenList) walk(child);
            }};
            walk(transform);
            return result.ToArray();
        }}
    }}

    public static class Object
    {{
        public static void DestroyImmediate(GameObject go)
        {{
            if (go.transform.parent != null) go.transform.parent.ChildrenList.Remove(go.transform);
            go.components.Clear();
        }}
    }}

    public static class Debug
    {{
        public static void Log(string s) {{ }}
        public static void LogWarning(string s) {{ }}
    }}
}}

internal static class CollapseExtracted
{{
{essential_block}

{algo_block}
}}

internal static class TestHelpers
{{
    public static GameObject NewChild(GameObject parentGo, string name)
    {{
        var go = new GameObject(name);
        go.transform.SetParent(parentGo.transform, true);
        return go;
    }}

    public static void AddComponent(GameObject go, Component c)
    {{
        c.gameObject = go;
        go.components.Add(c);
    }}
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

    // 実装が変わって旧基準に戻っていないかの対照用(現在の本番コードには
    // もう存在しない、dev#455修正前の判定式をここに独立コピーする)
    static bool OldBasisWouldSkip(Transform t)
    {{
        return t.GetComponents<Component>().Length > 1;
    }}

    // dev#455の実欠陥構造を最小構築する:
    // Hips-Spine-Chest-Head(本体ボーン)+Head直下の非ボーンアンカー
    // (anchorExtra指定のコンポーネント付き)+その下の独立ジグルボーンAccBone_L。
    static void BuildScenario(Component anchorExtra,
        out GameObject root, out Transform anchor, out Transform head, out Transform accBone)
    {{
        root = new GameObject("Avatar");
        var hips = TestHelpers.NewChild(root, "Hips");
        var spine = TestHelpers.NewChild(hips, "Spine");
        var chest = TestHelpers.NewChild(spine, "Chest");
        var headGo = TestHelpers.NewChild(chest, "Head");
        var anchorGo = TestHelpers.NewChild(headGo, "AccRoot$guid");
        var accBoneGo = TestHelpers.NewChild(anchorGo, "AccBone_L");

        if (anchorExtra != null)
            TestHelpers.AddComponent(anchorGo, anchorExtra);

        var bodyGo = TestHelpers.NewChild(root, "Body");
        var bodySmr = new SkinnedMeshRenderer();
        bodySmr.bones = new[] {{ hips.transform, spine.transform, chest.transform, headGo.transform }};
        TestHelpers.AddComponent(bodyGo, bodySmr);

        var accMeshGo = TestHelpers.NewChild(accBoneGo, "AccessoryMesh");
        var accSmr = new SkinnedMeshRenderer();
        accSmr.bones = new[] {{ accBoneGo.transform }};
        TestHelpers.AddComponent(accMeshGo, accSmr);

        anchor = anchorGo.transform;
        head = headGo.transform;
        accBone = accBoneGo.transform;
    }}

    static int Main()
    {{
        // ---- 1) 正の対照(赤→緑): disposableコンポーネント付きアンカー ----
        {{
            GameObject root; Transform anchor; Transform head; Transform accBone;
            BuildScenario(new FakeDisposableComponent(), out root, out anchor, out head, out accBone);

            Check(OldBasisWouldSkip(anchor),
                "対照: 旧基準(コンポーネント数==1)ならdisposable付きアンカーは収縮されずbugを再現するはず");

            CollapseExtracted.CollapseNestedArmatureContainers(root);

            Check(!head.ChildrenList.Contains(anchor),
                "修正後: disposableコンポーネント付きアンカーはHeadの子から除去される(収縮された)");
            Check(accBone.parent == head,
                "修正後: AccBone_LがHeadへ直結される(アンカーを飛び越えて再親化)");
        }}

        // ---- 2) 負の対照(無退行): 実データ保持型(SkinnedMeshRenderer)付きアンカー ----
        {{
            GameObject root; Transform anchor; Transform head; Transform accBone;
            BuildScenario(new SkinnedMeshRenderer(), out root, out anchor, out head, out accBone);

            CollapseExtracted.CollapseNestedArmatureContainers(root);

            Check(head.ChildrenList.Contains(anchor),
                "無退行: 実データ(SkinnedMeshRenderer)を持つアンカーは収縮されず、Headの子のまま残る");
            Check(accBone.parent == anchor,
                "無退行: AccBone_Lの親はアンカーのまま変わらない(データノードを道連れに破棄していない)");
        }}

        // ---- 3) 回帰ガード: 何も余計なコンポーネントを持たない素のアンカー ----
        {{
            GameObject root; Transform anchor; Transform head; Transform accBone;
            BuildScenario(null, out root, out anchor, out head, out accBone);

            CollapseExtracted.CollapseNestedArmatureContainers(root);

            Check(!head.ChildrenList.Contains(anchor),
                "回帰ガード: 素のアンカー(旧基準でも収縮対象だった正常系)は引き続き収縮される");
            Check(accBone.parent == head,
                "回帰ガード: AccBone_Lは引き続きHeadへ直結される");
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
    <AssemblyName>Collapse455Harness</AssemblyName>
  </PropertyGroup>
</Project>
"""


@pytest.mark.skipif(not _dotnet_available(), reason="dotnet SDKが無い環境")
def test_disposable_anchor_now_collapses_and_data_anchor_stays_protected():
    source = _read_exporter_source()
    essential_block = _extract_block(source, ESSENTIAL_BEGIN, ESSENTIAL_END)
    algo_block = _extract_block(source, ALGO_BEGIN, ALGO_END)

    for needle in ("IsEssentialComponentType", "HasEssentialNonTransformComponent"):
        assert needle in essential_block, "抽出ブロック(essential)に{}が無い(実装が変わった?)".format(needle)
    for needle in ("CollapseNestedArmatureContainers", "HasAncestorBone", "HasDescendantBone"):
        assert needle in algo_block, "抽出ブロック(algo)に{}が無い(実装が変わった?)".format(needle)

    essential_block = _make_methods_cross_class_visible(essential_block)
    algo_block = _make_methods_cross_class_visible(algo_block)

    program_cs = _HARNESS_PROGRAM_TEMPLATE.format(
        essential_block=essential_block, algo_block=algo_block)

    tmpdir = tempfile.mkdtemp(prefix="collapse455_pure_harness_")
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
            "dev#455 collapse判定ロジック(本番ソースから抽出)が期待どおりに動かなかった:\n"
            + output)
        assert proc.returncode == 0, "dotnet実行が非0終了:\n" + output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
