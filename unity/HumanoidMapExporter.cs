// DiveToPalworld用: Unityのヒューマノイド設定(人型ボーン対応表)をJSONに書き出す
//
// 使い方:
//   1. このファイルをUnityプロジェクトの Assets/Editor/ フォルダに入れる
//   2. HierarchyでアバターのルートGameObject(Animator付き)を選択
//   3. メニュー Tools > DiveToPalworld > Export Humanoid Map
//   4. 保存した humanoid.json を、FBXと同じフォルダに置いてDiveToPalworldへ
//
// 出力はボーン名の対応表だけ(モデルデータは含まれません)
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

public static class HumanoidMapExporter
{
    [MenuItem("Tools/DiveToPalworld/Export Humanoid Map")]
    static void Export()
    {
        var go = Selection.activeGameObject;
        if (go == null)
        {
            EditorUtility.DisplayDialog("DiveToPalworld",
                "アバターのルート(Animator付きGameObject)を選択してください", "OK");
            return;
        }
        var animator = go.GetComponentInChildren<Animator>();
        if (animator == null || animator.avatar == null || !animator.avatar.isHuman)
        {
            EditorUtility.DisplayDialog("DiveToPalworld",
                "Humanoid設定されたAvatarを持つAnimatorが見つかりません", "OK");
            return;
        }

        var human = animator.avatar.humanDescription.human;
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-humanoid-1\",\n  \"humanoid\": {\n");
        bool first = true;
        foreach (var hb in human)
        {
            if (string.IsNullOrEmpty(hb.boneName)) continue;
            if (!first) sb.Append(",\n");
            first = false;
            sb.AppendFormat("    \"{0}\": \"{1}\"",
                Escape(hb.humanName), Escape(hb.boneName));
        }
        sb.Append("\n  }\n}\n");

        string path = EditorUtility.SaveFilePanel(
            "humanoid.json を保存(FBXと同じフォルダ推奨)",
            "", "humanoid", "json");
        if (string.IsNullOrEmpty(path)) return;
        File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
        EditorUtility.DisplayDialog("DiveToPalworld",
            "書き出しました:\n" + path +
            "\n\nFBXと同じフォルダに置いて、FBXをDiveToPalworldへD&Dしてください", "OK");
    }

    static string Escape(string s)
    {
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}
