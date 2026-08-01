// DiveToPalworld用: アバターのprefabから変換に必要な一式を書き出す
//   - 統合FBX(NDMFベイク後・activeのみを1本に書き出したもの)
//   - humanoid.json (人型ボーン対応表、ベイク後の実体から)
//   - 各メッシュ×マテリアルスロットの実テクスチャ(PNG) + material_map.json
//
// 仕様(2026-07-21ぱん裁定): prefab→palは「そのプレハブをシーンに置いた時点での
// 見た目」を持ってくる。つまり:
//   - Inactiveなオブジェクト・無効なレンダラーは持ってこない
//   - Modular Avatarで着せた服(D&D構成)はNDMFベイク後の見た目で持ってくる
// このため元FBXのコピーではなく、ベイク済み実体を com.unity.formats.fbx の
// ModelExporter で1本のFBXへ統合書き出しする(複数FBX構成もこれで自然に解決)。
//
// 使い方(GUI):
//   1. このファイルを Assets/Editor/ に入れる(FBX Exporterパッケージ必須)
//   2. Projectビューでアバターのprefabを選択(またはHierarchyでルートを選択)
//   3. メニュー Tools > DiveToPalworld > Export Avatar
//   4. 出力フォルダごと DiveToPalworld へ(中のFBXをD&D)
//
// バッチ(開発用):
//   Unity.exe -batchmode -projectPath <proj> -executeMethod DiveToPalworldExporter.ExportBatch
//     -vrm2palPrefab <Assets/....prefab> -vrm2palOut <出力フォルダ> -quit
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

public static class DiveToPalworldExporter
{
    [MenuItem("Tools/DiveToPalworld/Export Avatar")]
    static void ExportMenu()
    {
        var target = Selection.activeGameObject;
        if (target == null)
        {
            EditorUtility.DisplayDialog("DiveToPalworld",
                "アバターのprefab(またはHierarchyのルート)を選択してください", "OK");
            return;
        }
        string outDir = EditorUtility.SaveFolderPanel(
            "書き出し先フォルダ(空フォルダ推奨)", "", target.name + "_vrm2pal");
        if (string.IsNullOrEmpty(outDir)) return;
        try
        {
            Export(target, outDir);
            EditorUtility.DisplayDialog("DiveToPalworld",
                "書き出しました:\n" + outDir +
                "\n\nこのフォルダの中のFBXをDiveToPalworldへD&Dしてください", "OK");
            EditorUtility.RevealInFinder(outDir);
        }
        catch (Exception e)
        {
            EditorUtility.DisplayDialog("DiveToPalworld", "失敗: " + e.Message, "OK");
            Debug.LogException(e);
        }
    }

    // 開発・自動テスト用エントリポイント
    public static void ExportBatch()
    {
        string prefabPath = GetArg("-vrm2palPrefab");
        string outDir = GetArg("-vrm2palOut");

        // dev#518診断: prefabパス解決の構造を成功/失敗にかかわらず必ずログへ残す。
        // GUID未登録(=空文字列)ならインポート未完了を示唆、生バイトは全角/大文字
        // 小文字の混入を機械的に見分けるため(問い合わせでは実物のprefabを
        // 送ってもらえないので、ログだけで判別できる必要がある)
        string guid = AssetDatabase.AssetPathToGUID(prefabPath);
        Debug.Log("D2P: prefab解決 path=" + prefabPath +
                  " guid=" + (string.IsNullOrEmpty(guid) ? "(空=GUID未登録)" : guid) +
                  " rawBytes=" + BitConverter.ToString(Encoding.UTF8.GetBytes(prefabPath)));

        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
        {
            // 初回失敗時のみ: AssetDatabase.Refresh()で解消するかを記録して再試行する
            Debug.LogWarning("D2P: prefabの初回読み込みに失敗。AssetDatabase.Refreshで再試行します: " + prefabPath);
            AssetDatabase.Refresh();
            prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            Debug.Log("D2P: Refresh後の再試行結果: " + (prefab != null ? "成功(解消した)" : "失敗(解消しなかった)"));
        }
        if (prefab == null) throw new Exception("prefabが読めない: " + prefabPath);
        Export(prefab, outDir);
        Debug.Log("D2P_EXPORT_DONE " + outDir);
    }

    static string GetArg(string name)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == name) return args[i + 1];
        throw new Exception("引数が無い: " + name);
    }

    static void Export(GameObject target, string outDir)
    {
        Directory.CreateDirectory(outDir);
        // NDMFベイクとinactive除去で破壊的に変更するため、常に複製を処理する
        GameObject instance;
        if (target.scene.IsValid())
        {
            instance = UnityEngine.Object.Instantiate(target);
            instance.name = target.name;  // "(Clone)"を除去
        }
        else
        {
            instance = (GameObject)PrefabUtility.InstantiatePrefab(target);
            // 子の削除を許すため完全アンパック
            PrefabUtility.UnpackPrefabInstance(instance,
                PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        }
        try
        {
            instance.SetActive(true);
            instance.transform.localPosition = Vector3.zero;      // 出力座標系を安定させる
            instance.transform.localRotation = Quaternion.identity;
            instance.transform.localScale = Vector3.one;
            D2PDiagDump(instance, "00 before StripNonWhitelistedPreBake");
            D2PDiagShot(instance, outDir, "00_front", "front");
            D2PDiagShot(instance, outDir, "00_side", "side");
            D2PDiagShot(instance, outDir, "00_isolated_beret_ribbon", "front", new[] { "Beret", "Ribbon", "Body" });
            StripNonWhitelistedPreBake(instance);                 // ①-a 第1段: VRC/MA/NDMF本体+必須5型以外を除去(BakeNdmfの直前必須)
            D2PDiagDump(instance, "01 after StripNonWhitelistedPreBake / before BakeNdmf");
            BakeNdmf(instance);                                   // ① MA等を適用
            D2PDiagDump(instance, "02 after BakeNdmf");
            D2PDiagShot(instance, outDir, "02_front", "front");
            D2PDiagShot(instance, outDir, "02_side", "side");
            D2PDiagShot(instance, outDir, "02_isolated_beret_ribbon", "front", new[] { "Beret", "Ribbon", "Body" });
            StripConstraints(instance);                           // ①' Constraint除去(輸出専用複製のみ)
            D2PDiagDump(instance, "03 after StripConstraints");
            StripInactive(instance);                              // ② 見えない物を除去
            D2PDiagDump(instance, "04 after StripInactive");
            D2PDiagShot(instance, outDir, "04_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            ConvertStaticMeshesToSkinned(instance);               // ②-a 非スキンメッシュをSkinnedMeshRenderer化(以降の全工程を一様化)
            D2PDiagDump(instance, "04b after ConvertStaticMeshesToSkinned");
            D2PDiagShot(instance, outDir, "04b_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            FlattenSkinnedMeshes(instance);                       // ②' 頂点をバインド時ワールドへ
            D2PDiagDump(instance, "05 after FlattenSkinnedMeshes");
            D2PDiagShot(instance, outDir, "05_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            BakeUniformScale(instance.transform, 1f);             // ②'' 階層スケール除去
            D2PDiagDump(instance, "06 after BakeUniformScale");
            D2PDiagShot(instance, outDir, "06_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            RebindToCurrent(instance);                            // ②''' bindposes再計算
            D2PDiagDump(instance, "07 after RebindToCurrent");
            D2PDiagShot(instance, outDir, "07_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            CollapseNestedArmatureContainers(instance);           // ②'''' wisker等ネストarmature対策(検証中)
            D2PDiagDump(instance, "08 after CollapseNestedArmatureContainers");
            D2PDiagShot(instance, outDir, "08_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            var skeletonRootDummy = InsertSkeletonRootDummy(instance); // ②''''' eRoot対策(Hipsの上にダミー)
            D2PDiagDump(instance, "09 after InsertSkeletonRootDummy");
            D2PDiagShot(instance, outDir, "09_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            RedirectRootBonesAwayFromSelf(instance, skeletonRootDummy); // ②'''''' eRoot対策(rootBone退避、汎用、dev#150で単一ダミーへ統一)
            D2PDiagDump(instance, "10 after RedirectRootBonesAwayFromSelf");
            D2PDiagShot(instance, outDir, "10_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            StripNonEssentialPostBake(instance);                  // ④-a 第2段: 必須5型以外を除去(ExportHumanoidの直前)
            D2PDiagDump(instance, "11 after StripNonEssentialPostBake");
            D2PDiagShot(instance, outDir, "11_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            EnsureUniqueTransformNames(instance);                 // ④-b dev#300: 輸出直前に名前重複を解消(ExportHumanoid/ExportUnifiedFbx/ExportMaterials全ての手前が必須)
            ExportHumanoid(instance, outDir);                     // ③ ベイク後実体から
            string fbxName = ExportUnifiedFbx(instance, outDir);  // ④ 統合FBX
            ExportMaterials(instance, outDir, fbxName);           // ⑤ 実テクスチャ
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(instance);
        }
    }

    // ---- 一時診断(HZ班、位置バグ再調査用。原因特定後に削除する) ----
    static void D2PDiagDump(GameObject root, string label)
    {
        string[] names = { "Beret", "Ribbon", "SRB_AG1", "GameObject", "Head" };
        foreach (var n in names)
        {
            var matches = new List<Transform>();
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                if (t.name == n) matches.Add(t);
            if (matches.Count == 0)
            {
                Debug.Log($"D2PDIAG2[{label}] {n}: NOT FOUND (0 matches)");
                continue;
            }
            if (matches.Count > 1)
                Debug.Log($"D2PDIAG2[{label}] {n}: {matches.Count} MATCHES(!)");
            foreach (var found in matches)
            {
                var mabp = found.GetComponent("ModularAvatarBoneProxy");
                Debug.Log($"D2PDIAG2[{label}] {n} @ {GetHierarchyPath(found)}: "
                    + $"active={found.gameObject.activeInHierarchy} "
                    + $"parent={found.parent?.name} localPos={found.localPosition:F5} "
                    + $"localScale={found.localScale:F5} worldPos={found.position:F5} "
                    + $"lossyScale={found.lossyScale:F5} hasBoneProxy={mabp != null}");
            }
        }
    }
    // カメラで撮影しPNG保存(比較用、目視確認目的)。dir: "front"/"back"/"side"
    // isolateNames!=null なら、その名前のRendererだけ見せて他は隠す(位置の一意特定用)
    static void D2PDiagShot(GameObject root, string outDir, string name, string dir = "back",
                             string[] isolateNames = null)
    {
        var renderers = root.GetComponentsInChildren<Renderer>(false);
        if (renderers.Length == 0) { Debug.Log("D2PDIAG2SHOT: no renderers"); return; }
        var savedEnabled = new List<(Renderer, bool)>();
        if (isolateNames != null)
        {
            foreach (var r in renderers)
            {
                savedEnabled.Add((r, r.enabled));
                r.enabled = Array.IndexOf(isolateNames, r.gameObject.name) >= 0;
            }
        }
        Bounds b = default; bool has = false;
        foreach (var r in renderers)
        {
            if (!r.enabled) continue;
            if (!has) { b = r.bounds; has = true; } else b.Encapsulate(r.bounds);
        }
        if (!has) { Debug.Log("D2PDIAG2SHOT: no visible renderers for " + name); goto restore; }

        {
            var camGo = new GameObject("D2PDiagCam");
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.6f, 0.6f, 0.6f, 1f);
            float dist = Mathf.Max(b.extents.magnitude * 2.2f, 1f);
            Vector3 offset = dir == "front" ? new Vector3(0, 0, dist)
                            : dir == "side" ? new Vector3(dist, 0, 0)
                            : new Vector3(0, 0, -dist);
            camGo.transform.position = b.center + offset;
            camGo.transform.LookAt(b.center, Vector3.up);
            cam.nearClipPlane = 0.01f;
            cam.farClipPlane = dist * 4f;

            int w = 512, h = 768;
            var rt = new RenderTexture(w, h, 24);
            cam.targetTexture = rt;
            cam.Render();
            var prevActive = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
            tex.Apply();
            RenderTexture.active = prevActive;
            cam.targetTexture = null;
            rt.Release();

            var bytes = tex.EncodeToPNG();
            var path = Path.Combine(outDir, "d2pdiag_" + name + ".png");
            File.WriteAllBytes(path, bytes);
            Debug.Log("D2PDIAG2SHOT saved: " + path);

            UnityEngine.Object.DestroyImmediate(tex);
            UnityEngine.Object.DestroyImmediate(camGo);
        }
        restore:
        if (isolateNames != null)
            foreach (var (r, en) in savedEnabled) r.enabled = en;
    }
    // ---- 診断ここまで ----

    static Type FindType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            var t = asm.GetType(fullName);
            if (t != null) return t;
        }
        return null;
    }

    // 型がVRC公式(com.vrchat.*)/Modular Avatar/NDMF本体、または必須5型
    // (Transform/Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)かどうかを
    // 判定する。名前空間のプレフィックス一致にすることで、SDK更新で型が増えても
    // 個別列挙なしに自動対応する。
    // 注意: Modular Avatarはパッケージ名がハイフン(nadena.dev.modular-avatar)だが
    // C#名前空間はアンダースコア(nadena.dev.modular_avatar)。ここを間違えると
    // MAコンポーネントを丸ごと消してベイクが壊れるため厳重に注意すること
    static bool IsWhitelistedComponentType(Type t)
    {
        if (t == typeof(Transform) || t == typeof(Animator)
            || t == typeof(SkinnedMeshRenderer) || t == typeof(MeshRenderer)
            || t == typeof(MeshFilter))
            return true;
        var ns = t.Namespace ?? "";
        return ns == "VRC" || ns.StartsWith("VRC.")
            || ns == "nadena.dev.modular_avatar" || ns.StartsWith("nadena.dev.modular_avatar.")
            || ns == "nadena.dev.ndmf" || ns.StartsWith("nadena.dev.ndmf.");
    }

    // ログ用: ルートからのHierarchyパス(Transform名を"/"で連結)
    static string GetHierarchyPath(Transform t)
    {
        var sb = new StringBuilder(t.name);
        for (var p = t.parent; p != null; p = p.parent)
            sb.Insert(0, p.name + "/");
        return sb.ToString();
    }

    // 第1段(ベイク前)ホワイトリスト。オーナー裁定「MA以外のNDMFプラグインは非対応」
    // を受け、VRC公式/Modular Avatar/NDMF本体/必須5型以外の**コンポーネントのみ**を
    // 全除去する(GameObjectそのものは消さない)。
    // 呼び出し位置は必ずBakeNdmfの"前"であること: NDMFのTransformingフェーズは
    // プラグインのマーカーコンポーネント(例: PoseClipperInstaller)をベイク実行時に
    // その場でスキャンするため(実データ確認済み)、BakeNdmfの後に置くと
    // 既にプラグインが実行済みになってしまい無効化の意味が無くなる。
    // 削除した型名+パスを1件ずつログに残す(取りこぼしの追跡・ユーザー問い合わせ対応用)
    static void StripNonWhitelistedPreBake(GameObject root)
    {
        int n = 0;
        foreach (var c in root.GetComponentsInChildren<Component>(true))
        {
            if (c == null) continue;  // missing script等
            var t = c.GetType();
            if (IsWhitelistedComponentType(t)) continue;
            string typeName = t.FullName;
            string path = GetHierarchyPath(c.transform);
            try
            {
                UnityEngine.Object.DestroyImmediate(c);
                n++;
                Debug.Log("D2P: [PreBakeサニタイズ] 除去: " + typeName + " @ " + path);
            }
            catch (Exception e)
            {
                Debug.LogWarning("D2P: [PreBakeサニタイズ] 除去失敗: " + typeName + " @ " + path
                                  + " (" + e.Message + ")");
            }
        }
        Debug.Log("D2P: PreBakeサニタイズ完了、" + n + "件除去"
                   + "(VRC公式/ModularAvatar/NDMF本体+Transform/Animator/SkinnedMeshRenderer/"
                   + "MeshRenderer/MeshFilter以外はすべて対象)");
    }

    // D2P_COLLAPSE455_ESSENTIAL_BEGIN
    // FBX輸出とhumanoid.json生成に真に必要な5型(Transform/Animator/
    // SkinnedMeshRenderer/MeshRenderer/MeshFilter)かどうかの判定。
    // StripNonEssentialPostBake(除去)とCollapseNestedArmatureContainers
    // (収縮可否判定)の両方がこの1箇所を参照する(dev#455: 二重定義していた
    // ことで、収縮判定側だけ古い「Transform以外禁止」基準のまま取り残され、
    // Merge Armatureが生成するPhysBone付きアンカーノードがcollapse対象から
    // 漏れてFBXに残存し、BlenderのFBXインポータでKeyErrorになっていた)。
    static bool IsEssentialComponentType(Type t)
    {
        return t == typeof(Transform) || t == typeof(Animator)
            || t == typeof(SkinnedMeshRenderer) || t == typeof(MeshRenderer)
            || t == typeof(MeshFilter);
    }

    // 対象Transformが、Transform以外の「実データを保持する」必須型
    // (Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)を1つでも
    // 持っているかどうか。GameObjectごと破棄する収縮(Collapse)では、
    // こうしたデータ保持コンポーネントを道連れに失ってはならない。
    // 一方、それ以外の型(VRCPhysBone/Collider/Constraint等)は
    // StripNonEssentialPostBakeでどうせ後から除去される「使い捨て」
    // コンポーネントなので、これを理由に収縮を諦める必要はない
    // (dev#455の修正趣旨: 「どうせ後で消えるコンポーネント」を理由に
    // 収縮を諦めない)。
    static bool HasEssentialNonTransformComponent(Transform t)
    {
        foreach (var c in t.GetComponents<Component>())
        {
            if (c == null) continue;  // missing script等は道連れにしてよい(実データではない)
            var ct = c.GetType();
            if (ct == typeof(Transform)) continue;
            if (IsEssentialComponentType(ct)) return true;
        }
        return false;
    }
    // D2P_COLLAPSE455_ESSENTIAL_END

    // 第2段(ベイク後)ホワイトリスト。ベイク・各種ボーン処理が全て終わった後、
    // FBX輸出とhumanoid.json生成に必要な5型(Transform/Animator/
    // SkinnedMeshRenderer/MeshRenderer/MeshFilter)以外のコンポーネントを
    // 全除去する(GameObjectそのものは消さない)。
    // 呼び出し位置は必ずExportHumanoidの"前"であること。
    // 既存StripConstraints(IConstraint一括除去)とは独立で重複除去になるが、
    // 既存の安定した処理を壊さないため両方残す(実害なし)。
    // 削除した型名+パスを1件ずつログに残す
    static void StripNonEssentialPostBake(GameObject root)
    {
        int n = 0;
        foreach (var c in root.GetComponentsInChildren<Component>(true))
        {
            if (c == null) continue;
            var t = c.GetType();
            if (IsEssentialComponentType(t))
                continue;
            string typeName = t.FullName;
            string path = GetHierarchyPath(c.transform);
            try
            {
                UnityEngine.Object.DestroyImmediate(c);
                n++;
                Debug.Log("D2P: [PostBakeサニタイズ] 除去: " + typeName + " @ " + path);
            }
            catch (Exception e)
            {
                Debug.LogWarning("D2P: [PostBakeサニタイズ] 除去失敗: " + typeName + " @ " + path
                                  + " (" + e.Message + ")");
            }
        }
        Debug.Log("D2P: PostBakeサニタイズ完了、" + n + "件除去"
                   + "(Transform/Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilterのみ残す)");
    }

    // dev#194(実報告SE48AGFP): 同居NDMFプラグイン(実例: Light Limit Changer/
    // io.github.azukimochi.Utils)のアセンブリ静的初期化子(static constructor)が
    // 一度失敗すると、.NETは同一AppDomain内でその型への以後のアクセスを全て
    // 即座に TypeInitializationException で返す(BeforeFieldInit失敗のキャッシュ、
    // プロセス/Editorセッションが終わるまで解除されない)。reflection経由の
    // MethodInfo.Invokeはこれを更に TargetInvocationException で包んで返すため、
    // 生の"Exception has been thrown by the target of an invocation."だけでは
    // 原因のパッケージ・型がまったく特定できず、ユーザーもDiveToPalworld側も
    // 対処できない。
    // ここでは特定パッケージ名をコードに一切書かず(サードパーティ製アセットに
    // 特別対応しない裁定と同じ「入口で正規化、特別扱いを積まない」原則)、
    // 例外チェーンを実際に辿って
    // 壊れた型の名前を抽出し、"どの第三者パッケージが原因でも通用する"汎用の
    // 診断メッセージへ変換する。型初期化失敗はAppDomain内で恒久的(Editor再起動
    // までは同じ失敗を必ず再発する)なので、ここで自動リトライ/フォールバック
    // 経路を試みても同じ壊れた型に触れば再度失敗するだけであり、成功したかの
    // ように振る舞うことは「効いていないのに直った」を偽装する害の方が大きい。
    // よって選んだ方針は「輸出を止めるが、原因と対処が一目でわかる1行に変換する」。
    // Unity非依存の純粋関数として実装し、Unity無しの環境からも本番コードその
    // ものを抽出してdotnetでコンパイル・実行できるようにする
    // (tests\unity_exporter\test_thirdparty_init_guard.py)。
    // D2P_INITGUARD_PURE_BEGIN
    internal static string FindBrokenTypeInitializerName(Exception e)
    {
        for (var cur = e; cur != null; cur = cur.InnerException)
        {
            var tie = cur as TypeInitializationException;
            if (tie != null) return tie.TypeName;
        }
        return null;
    }

    internal static Exception RootCause(Exception e)
    {
        var cur = e;
        while (cur.InnerException != null) cur = cur.InnerException;
        return cur;
    }

    internal static string BuildInvocationFailureMessage(string stepName, Exception e)
    {
        string brokenType = FindBrokenTypeInitializerName(e);
        if (brokenType != null)
        {
            return stepName + ": サードパーティパッケージ内の型 '" + brokenType + "' の" +
                "静的初期化が失敗しており、このUnity Editorセッション内では以後同じ失敗が" +
                "再発します(.NETの仕様で型初期化の失敗はプロセスが終わるまでキャッシュ" +
                "されるため)。対処: 1) Unity Editorを再起動する、または 2) 原因パッケージ" +
                "(Package Managerで確認できます)を一時的に無効化・削除してから" +
                "エクスポートをやり直してください。";
        }
        var root = RootCause(e);
        return stepName + "で失敗: " + root.GetType().Name + ": " + root.Message;
    }
    // D2P_INITGUARD_PURE_END

    // NDMF(Modular Avatar等の非破壊改変基盤)のベイクを実体へ適用する。
    // パッケージ参照を増やさないためreflectionで呼ぶ。未導入ならスキップ
    static void BakeNdmf(GameObject root)
    {
        var t = FindType("nadena.dev.ndmf.AvatarProcessor");
        if (t == null)
        {
            Debug.Log("D2P: NDMF未導入のためベイクをスキップ");
            return;
        }
        var mi = t.GetMethod("ProcessAvatar",
            BindingFlags.Public | BindingFlags.Static,
            null, new[] { typeof(GameObject) }, null);
        if (mi == null)
            throw new Exception("AvatarProcessor.ProcessAvatarが見つからない(NDMFのバージョン非互換)");
        try
        {
            mi.Invoke(null, new object[] { root });
        }
        catch (TargetInvocationException tie)
        {
            // NDMF本体は通常このtry内で個々のプラグインの失敗を握りつぶすため、ここに
            // 来るのは想定外(NDMFの将来バージョンでの挙動変化等)の防御的対応。
            Debug.LogException(tie);
            throw new Exception(BuildInvocationFailureMessage("NDMFベイク", tie));
        }
        Debug.Log("D2P: NDMFベイク完了");
    }

    // Unity公式FBX Exporter(com.unity.formats.fbx@4.2.1)の
    // ModelExporter.ExportConstraints は特定の構成(2026-07-26実測: FaceEmo等
    // MA以外のNDMFプラグインが同居するsha-ta検体)で例外を投げ、輸出全体が失敗する。
    // Unityの制約コンポーネント(ParentConstraint/PositionConstraint/RotationConstraint/
    // ScaleConstraint/AimConstraint/LookAtConstraint、すべてIConstraint実装)は
    // 「Is Activeな間、毎フレーム計算結果を自身のTransformのローカル値へ直接
    // 上書きする」方式であり、コンポーネント自体は最終姿勢とは別の独立した
    // ポーズ情報を保持しない。つまりprefab保存時点でIs Activeなら、その時点の
    // Transformのローカル値は既に制約適用後の姿勢そのものであり、以降このメソッド内で
    // コンポーネントを消してもTransformの値自体はそのまま(このメソッドは
    // Transformの値を書き換えない)。この呼び出しはBakeNdmf直後・
    // FlattenSkinnedMeshes/BakeUniformScale/RebindToCurrent(いずれもボーンの
    // "現在の"ワールド行列を読むだけで、コンポーネントの有無を見ない)より前に
    // 置いているが、後続処理はTransformの現在値のみを参照するため順序に依存しない。
    // 除去は輸出用の一時複製(instance)に対してのみ行う——StripInactive等と同じ流儀
    static void StripConstraints(GameObject root)
    {
        int n = 0;
        foreach (var c in root.GetComponentsInChildren<UnityEngine.Animations.IConstraint>(true))
        {
            var comp = c as Component;
            if (comp == null) continue;
            UnityEngine.Object.DestroyImmediate(comp);
            n++;
        }
        if (n > 0)
            Debug.Log("D2P: Constraintコンポーネントを" + n + "件除去(Transform値は変更しない、エクスポート用複製のみ)");
    }

    // シーンに置いた時点で見えていない物(inactiveオブジェクト・無効レンダラー)を
    // 実体から除去する。ただしactiveなスキンメッシュが参照するボーンの階層は残す
    static void StripInactive(GameObject root)
    {
        var needed = new HashSet<Transform>();
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            if (!r.enabled) continue;
            foreach (var b in r.bones)
                for (var t = b; t != null; t = t.parent) needed.Add(t);
            for (var t = r.rootBone; t != null; t = t.parent) needed.Add(t);
        }
        StripWalk(root.transform, needed);
    }

    static void StripWalk(Transform t, HashSet<Transform> needed)
    {
        var children = new List<Transform>();
        foreach (Transform c in t) children.Add(c);
        foreach (var c in children)
        {
            if (!c.gameObject.activeSelf)
            {
                if (ContainsAny(c, needed))
                {
                    // ボーンとして必要なので階層は残し、見た目だけ除去
                    foreach (var r in c.GetComponentsInChildren<Renderer>(true))
                        UnityEngine.Object.DestroyImmediate(r);
                    foreach (var mf in c.GetComponentsInChildren<MeshFilter>(true))
                        UnityEngine.Object.DestroyImmediate(mf);
                }
                else
                {
                    UnityEngine.Object.DestroyImmediate(c.gameObject);
                }
                continue;
            }
            var rend = c.GetComponent<Renderer>();
            if (rend != null && !rend.enabled)
            {
                UnityEngine.Object.DestroyImmediate(rend);
                var mf2 = c.GetComponent<MeshFilter>();
                if (mf2 != null) UnityEngine.Object.DestroyImmediate(mf2);
            }
            StripWalk(c, needed);
        }
    }

    static bool ContainsAny(Transform t, HashSet<Transform> set)
    {
        if (set.Contains(t)) return true;
        foreach (Transform c in t)
            if (ContainsAny(c, set)) return true;
        return false;
    }

    // スケール正規化後のボーンワールドで全SMRのbindposesを取り直す
    // (FlattenSkinnedMeshes→BakeUniformScaleの後に呼ぶ。メッシュ頂点は
    //  ワールド座標・ノードは恒等なので bindpose = worldToLocal で整合する)
    static void RebindToCurrent(GameObject root)
    {
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            if (r.sharedMesh == null || r.bones == null || r.bones.Length == 0)
                continue;
            var bp = new Matrix4x4[r.bones.Length];
            for (int b = 0; b < r.bones.Length; b++)
                bp[b] = r.bones[b] != null
                    ? r.bones[b].worldToLocalMatrix : Matrix4x4.identity;
            r.sharedMesh.bindposes = bp;
        }
    }

    // 階層の一様スケール(VRChatリグのArmature=0.458等)をボーン位置へ焼き込み、
    // 全ノードをscale=1にする。ワールド位置は不変。回転は一様スケールなら不変。
    // 非一様スケールは対象外(警告のみ)
    static void BakeUniformScale(Transform t, float acc)
    {
        var ls = t.localScale;
        float s = (ls.x + ls.y + ls.z) / 3f;
        if (Mathf.Abs(ls.x - ls.y) > 1e-4f * Mathf.Abs(s)
            || Mathf.Abs(ls.x - ls.z) > 1e-4f * Mathf.Abs(s))
        {
            Debug.LogWarning("D2P: 非一様スケールは正規化できない: " + t.name
                             + " " + ls);
            return;  // この枝はそのまま(以降の子も触らない)
        }
        t.localPosition = t.localPosition * acc;
        float acc2 = acc * s;
        t.localScale = Vector3.one;

        // 非スキンメッシュ(MeshFilter直付け、帽子・リボン等のBone Proxyアクセサリ)対策
        // (2026-07-26実測、shapell_Osaki帽子/リボン位置バグの根本原因):
        // このメソッドは「ノード原点のワールド位置」を保つよう親のスケールを
        // 子のlocalPositionへ焼き込むが、メッシュ自身の頂点データ(原点から離れた
        // 位置にあることが多い。今回のケースでは累積1.43倍)へは何もしない。
        // SkinnedMeshRendererはFlattenSkinnedMeshes()で既にルート直下・恒等姿勢
        // (acc=1)へ変換済みなのでこの分岐に来ないが、非スキンのMeshFilterは
        // 素通りしてここへ来る。ノードのlocalScaleを1へ強制する代わりに、
        // 除去する分の累積スケール(acc2)をメッシュの頂点自体へ焼き込むことで、
        // 「ノード原点は同じ位置・頂点の実寸も同じ見た目」を両立する
        // (Unity上のRenderer.boundsで正しく見えている実際の見た目を、
        // スケール除去後も再現する)。
        var mf = t.GetComponent<MeshFilter>();
        if (mf != null && mf.sharedMesh != null && Mathf.Abs(acc2 - 1f) > 1e-6f)
        {
            var mesh = UnityEngine.Object.Instantiate(mf.sharedMesh);
            mesh.name = mf.sharedMesh.name;
            var verts = mesh.vertices;
            for (int i = 0; i < verts.Length; i++) verts[i] *= acc2;
            mesh.vertices = verts;
            mesh.RecalculateBounds();
            mf.sharedMesh = mesh;
            Debug.Log("D2P: BakeUniformScale: 非スキンメッシュへ累積スケール "
                       + acc2.ToString("F4") + " を頂点焼き込み: " + GetHierarchyPath(t));
        }

        foreach (Transform c in t)
            BakeUniformScale(c, acc2);
    }

    // 非スキンメッシュ(MeshFilter+MeshRenderer。帽子・リボン等、ボーンへ
    // Transform直付けする一般的なVRChatアクセサリ構成)を、その所属ボーンへ
    // 100%ウェイトのSkinnedMeshRendererへ変換する。
    // 狙い: 以降の全工程(FlattenSkinnedMeshes/BakeUniformScaleの頂点焼き込み/
    // chibi-fit/RebindToCurrent等)はSkinnedMeshRendererを前提に動くため、
    // 非スキンメッシュだけがそこから取り残され、体だけ変形して装飾品が
    // 置いていかれる(2026-07-26実測、shapell_Osakiのベレー帽・リボン)。
    // ここで一律SkinnedMeshRenderer化しておけば、後続処理が全メッシュへ
    // 一様に効く。
    // 所属ボーンはTransformの親をたどって特定する(NDMFベイク・
    // StripInactive後の階層は、アクセサリがボーンへ直接ぶら下がる構成に
    // なっている——Unity側は階層がそのままボーン構造を持つ)。
    // 親が無い(ルート直下)等で所属ボーンが特定できない場合は変換せず
    // そのまま残し、警告のみ出す(以降はBakeUniformScaleの頂点焼き込み
    // フォールバックに任せる)。
    // sharedMeshは複製してから加工し、元アセットには触らない。
    // 呼び出し位置はBakeNdmf後・FlattenSkinnedMeshes前が必須:
    // FlattenSkinnedMeshes以降の全処理はSkinnedMeshRendererのみを走査するため、
    // 変換はそれより前でなければ意味が無い。StripInactiveの後に置くことで、
    // 実際に書き出されるメッシュだけを変換対象へ絞れる。
    // 元からSkinnedMeshRendererのものには触らない
    // (SkinnedMeshRendererはMeshRendererを継承しないため、
    //  GetComponentsInChildren<MeshRenderer>では列挙されず自然に対象外になる)。
    static void ConvertStaticMeshesToSkinned(GameObject root)
    {
        // 変換中にコンポーネント構成を変えるため、対象を先に列挙してから処理する
        var targets = new List<MeshRenderer>(root.GetComponentsInChildren<MeshRenderer>(false));
        int n = 0, skipped = 0;
        foreach (var mr in targets)
        {
            var t = mr.transform;
            var mf = t.GetComponent<MeshFilter>();
            if (mf == null || mf.sharedMesh == null) continue;

            var bone = t.parent;
            if (bone == null)
            {
                Debug.LogWarning("D2P: [非スキン化] 所属ボーンが特定できない(親が無い): "
                                  + GetHierarchyPath(t) + "。変換せず残す");
                skipped++;
                continue;
            }

            var srcMesh = mf.sharedMesh;
            var mesh = UnityEngine.Object.Instantiate(srcMesh);
            mesh.name = srcMesh.name;

            var weights = new BoneWeight[mesh.vertexCount];
            for (int i = 0; i < weights.Length; i++)
                weights[i] = new BoneWeight { boneIndex0 = 0, weight0 = 1f };
            mesh.boneWeights = weights;
            // bindpose: 変換前と同じ見た目になるよう、
            // bone.localToWorld * bindpose == t.localToWorld を満たす行列を選ぶ
            // (非スキン時と同じワールド座標を、単一ボーンのスキニングで再現する)
            mesh.bindposes = new[] { bone.worldToLocalMatrix * t.localToWorldMatrix };

            var mats = mr.sharedMaterials;
            var wasEnabled = mr.enabled;

            UnityEngine.Object.DestroyImmediate(mr);
            UnityEngine.Object.DestroyImmediate(mf);

            var smr = t.gameObject.AddComponent<SkinnedMeshRenderer>();
            smr.sharedMesh = mesh;
            smr.bones = new[] { bone };
            smr.rootBone = bone;
            smr.sharedMaterials = mats;
            smr.enabled = wasEnabled;

            n++;
            Debug.Log("D2P: [非スキン化] MeshRenderer→SkinnedMeshRenderer変換(所属ボーン="
                       + bone.name + "): " + GetHierarchyPath(t));
        }
        if (n > 0 || skipped > 0)
            Debug.Log("D2P: 非スキンメッシュのSkinnedMeshRenderer変換完了、" + n + "件変換、"
                       + skipped + "件スキップ(所属ボーン特定不可)");
    }

    // Unityのスキニングはノード変換を無視してバインド行列で解決するが、Blenderの
    // FBXインポータはスキンメッシュをアーマチュア配下へローカル行列ごと付け替える
    // ため、ノード変換とバインドが食い違うリグ(Armatureスケール等)は
    // メッシュとスケルトンの大きさ・向きが合わなくなる(2026-07-22実測)。
    // → 頂点をバインド時ワールド座標へ変換した複製メッシュを作り、bindposesも
    //   現在のボーンワールドから再計算、ノードはルート直下の恒等に置く。
    //   これで「どの行列を信じるインポータ」でも同じ配置になる
    static void FlattenSkinnedMeshes(GameObject root)
    {
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            if (r.sharedMesh == null || r.bones == null || r.bones.Length == 0)
                continue;
            var src = r.sharedMesh;
            var bp = src.bindposes;
            if (bp == null || bp.Length == 0 || r.bones[0] == null) continue;
            Matrix4x4 m = r.bones[0].localToWorldMatrix * bp[0];
            // 検算: 全ボーンで boneWorld×bindpose が一致するはず(未ポーズのrig)
            for (int b = 1; b < r.bones.Length && b < bp.Length; b++)
            {
                if (r.bones[b] == null) continue;
                Matrix4x4 mb = r.bones[b].localToWorldMatrix * bp[b];
                if ((mb.GetColumn(3) - m.GetColumn(3)).magnitude > 0.001f)
                {
                    Debug.LogWarning("D2P: バインド行列が不一致(ポーズ済みrig?): "
                                     + r.name + " bone " + b);
                    break;
                }
            }
            var mesh = UnityEngine.Object.Instantiate(src);
            mesh.name = src.name;
            var verts = mesh.vertices;
            var normals = mesh.normals;
            bool hasNormals = normals != null && normals.Length == verts.Length;

            // シーンで設定された現在のブレンドシェイプ値を頂点へ焼き込む。
            // MA構成では服をアバター体型に合わせるシェイプがシーン側で
            // 設定されていることが多い(toto実測: 未焼き込みだと服が体型に合わない)
            int baked = 0;
            for (int s = 0; s < mesh.blendShapeCount; s++)
            {
                float w = r.GetBlendShapeWeight(s);
                if (Mathf.Abs(w) < 1e-4f) continue;
                int frame = mesh.GetBlendShapeFrameCount(s) - 1;
                float fw = mesh.GetBlendShapeFrameWeight(s, frame);
                float k = fw > 1e-4f ? w / fw : w / 100f;
                var dv = new Vector3[verts.Length];
                var dn = new Vector3[verts.Length];
                mesh.GetBlendShapeFrameVertices(s, frame, dv, dn, null);
                for (int i = 0; i < verts.Length; i++)
                    verts[i] += dv[i] * k;
                if (hasNormals)
                    for (int i = 0; i < normals.Length; i++)
                        normals[i] += dn[i] * k;
                baked++;
            }
            if (baked > 0)
            {
                mesh.ClearBlendShapes();  // 焼き込み済み+deltasは座標変換しないため破棄
                Debug.Log("D2P: ブレンドシェイプ焼き込み: " + r.name + " " + baked + "件");
            }

            for (int i = 0; i < verts.Length; i++)
                verts[i] = m.MultiplyPoint3x4(verts[i]);
            mesh.vertices = verts;
            if (hasNormals)
            {
                Matrix4x4 nm = m.inverse.transpose;
                for (int i = 0; i < normals.Length; i++)
                    normals[i] = nm.MultiplyVector(normals[i]).normalized;
                mesh.normals = normals;
            }
            var newBp = new Matrix4x4[bp.Length];
            for (int b = 0; b < bp.Length; b++)
                newBp[b] = (b < r.bones.Length && r.bones[b] != null)
                    ? r.bones[b].worldToLocalMatrix : Matrix4x4.identity;
            mesh.bindposes = newBp;
            mesh.RecalculateBounds();
            r.sharedMesh = mesh;
            var t = r.transform;
            t.SetParent(root.transform, false);
            t.localPosition = Vector3.zero;
            t.localRotation = Quaternion.identity;
            t.localScale = Vector3.one;
        }
    }

    // FBX ExporterはスケルトンルートをeRootで書き、BlenderのFBXインポータは
    // eRootをアーマチュアオブジェクト化するためルートボーン(Hips)が消える
    // (2026-07-21実測)。Hipsの上に恒等ダミーを挟み、eRootをダミーへ吸わせる。
    // 戻り値: 挿入したダミーのTransform(非ヒューマノイド等で未挿入ならnull)。
    // RedirectRootBonesAwayFromSelfが全rootBoneの退避先をこの1点に統一するために使う
    // (dev#150、詳細は同メソッドのコメント参照)
    static Transform InsertSkeletonRootDummy(GameObject root)
    {
        var animator = root.GetComponentInChildren<Animator>();
        if (animator == null || animator.avatar == null || !animator.avatar.isHuman)
            return null;
        var hips = animator.GetBoneTransform(HumanBodyBones.Hips);
        if (hips == null || hips.parent == null) return null;
        var dummy = new GameObject("d2p_skeleton_root");
        dummy.transform.SetParent(hips.parent, false);
        dummy.transform.localPosition = Vector3.zero;
        dummy.transform.localRotation = Quaternion.identity;
        dummy.transform.localScale = Vector3.one;
        dummy.transform.SetSiblingIndex(hips.GetSiblingIndex());
        hips.SetParent(dummy.transform, true);
        return dummy.transform;
    }

    // 2026-07-26実測(FbxExporter.cs 3133-3155行): あるSkinnedMeshRendererの
    // rootBoneが「そのメッシュ自身のボーン」かつ「そのメッシュのbones[]に
    // 含まれる子ボーンを持つ」場合、そのボーンのFbxSkeletonはeRoot型で
    // 書き出される。BlenderのFBXインポータ(import_fbx.py find_armatures)は
    // eRoot型ノードを見つけるたびに独立したarmatureオブジェクトへ変換する
    // 仕様のため、Hipsだけでなく「各パーツ固有のrootBone」(実測: wiskerの
    // Head、PannAcc装飾品のBone等)でも同一の症状が起き、対応する
    // armature_setupエントリが無いままKeyErrorになる(InsertSkeletonRootDummy
    // でHipsの上にダミーを挟むだけでは、Hips自身のFbxSkeleton型は変わらず
    // 効かない。かつHips以外のrootBoneには元々対策していなかった)。
    //
    // dev#150(2026-07-30): 退避先を「rootBoneの直接の親」にする実装は誤り
    // だった。rootBoneがHipsそのものならparent=d2p_skeleton_root(非ボーンの
    // 安全な着地点)になるので問題無いが、rootBoneが骨格の途中にある
    // パーツ固有ボーン(実測41件中の一部)の場合、parentは大抵また別の
    // 「実ボーン」でしかない。その実ボーンへeRootを付け替えると、今度は
    // そのボーン自身が「祖先にも子孫にもボーンがいる非ボーン扱いの
    // ノード」というCollapseNestedArmatureContainers対象そのものの構造を
    // 新規に作ってしまう——だが同メソッドは本処理より前(この関数の前段)
    // にしか実行されないため、この新規発生分は誰にも解消されない。
    // Blender io_scene_fbx の find_armatures() はis_boneの子への探索しか
    // 行わない(非ボーンの子孫を再帰的に見つけに行かない)ため、この
    // 新設ノードは armature 化されないままcollect_skeleton_meshesの
    // 素通し集計だけがメッシュを外側のarmature(=d2p_skeleton_root)へ
    // 誤帰属させ、mesh.armature_setup[self]がKeyErrorになる
    // (2026-07-30、Blender単体でのFBX往復再現で確認済み: work\wp150\)。
    //
    // 修正: rootBoneの退避先を「その場その場の直接の親」ではなく、
    // InsertSkeletonRootDummyが挿した単一の恒等ダミー(skeletonRootDummy)
    // へ常に統一する。rootBoneは境界ボックス計算等にのみ使われスキニング
    // 結果には影響しないため(既存実測どおり)、どのメッシュも同じ1つの
    // 安全な非ボーン祖先を指すようにすれば、新規のeRootノードは
    // d2p_skeleton_root以外に一切発生しなくなる(dummyが無い=非ヒューマノイド
    // 等の場合のみ、次善としてrb.parentへフォールバック)
    static void RedirectRootBonesAwayFromSelf(GameObject root, Transform skeletonRootDummy)
    {
        int n = 0;
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            var rb = r.rootBone;
            if (rb == null || r.bones == null || rb.parent == null) continue;
            bool hasChildBoneInThisMesh = false;
            foreach (Transform c in rb)
            {
                if (Array.IndexOf(r.bones, c) >= 0) { hasChildBoneInThisMesh = true; break; }
            }
            if (!hasChildBoneInThisMesh) continue;
            r.rootBone = skeletonRootDummy != null ? skeletonRootDummy : rb.parent;
            n++;
        }
        if (n > 0)
            Debug.Log("D2P: rootBoneを" + n + "件、"
                + (skeletonRootDummy != null ? "共通ダミーへ退避" : "自身の親へ退避")
                + "(eRoot回避): ");
    }

    // Blenderのfind_armatures()は「ボーンではないNull/Root祖先」を見つけるたびに
    // 独立armatureへ変換するが、既にボーンチェーンの内部にネストされた非ボーン
    // コンテナ(子孫にボーンを持つNull)はこの走査経路(ボーン境界を跨がない
    // トップダウン探索)から構造的に外れてしまい、collect_armature_meshesの
    // 既知の集計漏れ(import_fbx.py内 "See T70244" コメント)でメッシュだけが
    // 親armatureのmeshes一覧に混入し、対応するarmature_setupが無いままKeyError
    // になる(2026-07-26実測、PanWisker/Armature/Head(内側)/WiskerParent_L…で発生)。
    // 該当コンテナ(自身はボーンではないが子孫にボーンを持ち、かつ祖先にも
    // ボーンがいる=ネストされたarmatureルート)を検出し、子を1段上へ直結して
    // コンテナ自体を消すことでボーンチェーンを途切れさせない。
    // ワールド座標は不変(worldPositionStays:trueで再親化するため見た目は無変化)。
    // 収縮可否の基準はStripNonEssentialPostBakeと同一の必須5型リストを参照する
    // HasEssentialNonTransformComponentに統一する(dev#455)。この判定が走る時点
    // (BakeNdmf後・StripNonEssentialPostBake前)では、Merge Armatureが揺れ物
    // (PhysBone)付き装飾品のために生成するアンカーノードがまだVRCPhysBone等の
    // コンポーネントを持ったままのため、「Transform以外は一切禁止」という
    // 旧基準(コンポーネント数==1)では収縮対象から漏れ、FBXへ残存してBlender側で
    // KeyErrorになっていた。新基準はTransform以外の実データ保持型(Animator/
    // SkinnedMeshRenderer/MeshRenderer/MeshFilter)だけを収縮不可の理由にし、
    // どうせ140行目のStripNonEssentialPostBakeで除去される型(PhysBone等)は
    // 収縮を妨げない。
    // D2P_COLLAPSE455_ALGO_BEGIN
    static void CollapseNestedArmatureContainers(GameObject root)
    {
        var bones = new HashSet<Transform>();
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (r.bones == null) continue;
            foreach (var b in r.bones)
                if (b != null) bones.Add(b);
        }
        if (bones.Count == 0) return;

        var all = new List<Transform>();
        CollectAllTransforms(root.transform, all);

        int n = 0;
        // 深い側(子)から処理するため末尾から辿る(親を先に潰すと判定がずれるため)
        for (int i = all.Count - 1; i >= 0; i--)
        {
            var t = all[i];
            if (t == root.transform) continue;
            if (bones.Contains(t)) continue;                   // 自身がボーンなら対象外
            if (HasEssentialNonTransformComponent(t)) continue; // 実データ保持型(Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)を持つなら触らない
            if (!HasAncestorBone(t, bones)) continue;          // ボーンチェーンの内部でなければ対象外
            if (!HasDescendantBone(t, bones)) continue;        // 子孫にボーンが無ければ対象外

            var parent = t.parent;
            var children = new List<Transform>();
            foreach (Transform c in t) children.Add(c);
            foreach (var c in children)
                c.SetParent(parent, true);                     // ワールド座標維持で1段上へ
            UnityEngine.Object.DestroyImmediate(t.gameObject);
            n++;
        }
        if (n > 0)
            Debug.Log("D2P: ネストされたarmatureコンテナを" + n + "件解消(ボーンチェーン直結)");
    }

    static void CollectAllTransforms(Transform t, List<Transform> outList)
    {
        outList.Add(t);
        foreach (Transform c in t) CollectAllTransforms(c, outList);
    }

    static bool HasAncestorBone(Transform t, HashSet<Transform> bones)
    {
        for (var p = t.parent; p != null; p = p.parent)
            if (bones.Contains(p)) return true;
        return false;
    }

    static bool HasDescendantBone(Transform t, HashSet<Transform> bones)
    {
        foreach (Transform c in t)
        {
            if (bones.Contains(c)) return true;
            if (HasDescendantBone(c, bones)) return true;
        }
        return false;
    }
    // D2P_COLLAPSE455_ALGO_END

    // com.unity.formats.fbx の ModelExporter でベイク後の実体を1本のFBXへ。
    // パッケージ参照を増やさないためreflectionで呼ぶ。
    // 重要: 既定のExportObject(string,Object)はASCII FBXを吐き、BlenderはASCII FBXを
    // 読めない(2026-07-21実測)。必ずBinary指定のオプションを組んで渡す
    static string ExportUnifiedFbx(GameObject go, string outDir)
    {
        var t = FindType("UnityEditor.Formats.Fbx.Exporter.ModelExporter");
        if (t == null)
            throw new Exception(
                "FBX Exporter(com.unity.formats.fbx)が未導入です。" +
                "export_from_unity.ps1経由で実行するか、Package Managerで追加してください");
        var safe = new StringBuilder();
        foreach (var ch in go.name)
            safe.Append(Array.IndexOf(Path.GetInvalidFileNameChars(), ch) >= 0 ? '_' : ch);
        string fbxName = safe + ".fbx";
        string path = Path.Combine(outDir, fbxName).Replace("\\", "/");

        // Binary指定オプション(4.x: 内部ExportModelSettingsSerialize / 5.x: 公開ExportModelOptions)
        object opts = null;
        foreach (var typeName in new[] {
            "UnityEditor.Formats.Fbx.Exporter.ExportModelOptions",
            "UnityEditor.Formats.Fbx.Exporter.ExportModelSettingsSerialize" })
        {
            var ot = t.Assembly.GetType(typeName);
            if (ot == null) continue;
            var candidate = Activator.CreateInstance(ot, true);
            if (SetFormatBinary(candidate)) { opts = candidate; break; }
        }
        if (opts == null)
            throw new Exception("FBX ExporterのBinary出力オプションを構築できない(バージョン非互換)");
        // Maya互換命名(スペースや.を_へ変換)を無効化。humanoid.jsonや製品FBXと
        // ボーン名が食い違う事故の元(2026-07-21実測: "Upper Leg.L"→"Upper_Leg_L")
        if (!TrySetOption(opts, "SetUseMayaCompatibleNames", "UseMayaCompatibleNames",
                          "mayaCompatibleNaming", false))
            Debug.LogWarning("D2P: Maya互換命名を無効化できなかった(ボーン名が変換される可能性)");

        // (string, 対象, ..., オプション, ...) を受けるExportObject/ExportObjectsを探して呼ぶ
        string result = null;
        bool invoked = false;
        foreach (var mi in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
        {
            if (mi.Name != "ExportObject" && mi.Name != "ExportObjects") continue;
            var ps = mi.GetParameters();
            if (ps.Length < 3 || ps[0].ParameterType != typeof(string)) continue;
            int optIdx = -1;
            for (int i = 2; i < ps.Length; i++)
                if (ps[i].ParameterType.IsAssignableFrom(opts.GetType())) { optIdx = i; break; }
            if (optIdx < 0) continue;
            var args = new object[ps.Length];
            args[0] = path;
            if (ps[1].ParameterType == typeof(UnityEngine.Object[]))
                args[1] = new UnityEngine.Object[] { go };
            else if (ps[1].ParameterType.IsAssignableFrom(typeof(GameObject)))
                args[1] = go;
            else
                continue;
            args[optIdx] = opts;  // 残りの引数はnull(省略可能なDictionary等)
            try
            {
                result = mi.Invoke(null, args) as string;
            }
            catch (TargetInvocationException tie)
            {
                // dev#194(SE48AGFP): 同居NDMFプラグインの静的初期化失敗がここで
                // TargetInvocationExceptionとして再発する実例を確認済み。
                // BuildInvocationFailureMessageの説明はBakeNdmf直前のコメント参照
                Debug.LogException(tie);
                throw new Exception(BuildInvocationFailureMessage("統合FBX書き出し", tie));
            }
            invoked = true;
            break;
        }
        if (!invoked)
            throw new Exception("ModelExporterのオプション付きExportが見つからない(バージョン非互換)");
        if (result == null || !File.Exists(path))
            throw new Exception("統合FBXの書き出しに失敗: " + path);
        // ASCIIで出ていないか検品(バイナリFBXは "Kaydara FBX Binary" マジックで始まる)
        var head = new byte[20];
        using (var fs = File.OpenRead(path)) fs.Read(head, 0, head.Length);
        if (Encoding.ASCII.GetString(head).IndexOf("Kaydara FBX Binary", StringComparison.Ordinal) != 0)
            throw new Exception("FBXがバイナリ形式になっていない(Blenderが読めないため中断)");
        return fbxName;
    }

    // オプションオブジェクトのExportFormatをBinaryへ(4.x/5.xの実装差をまとめて吸収)
    // dev#518: 生のreflection呼び出しをtry/catch無しで行うと内部でNREが起きた際に
    // 無言のTargetInvocationExceptionとして落ち、診断不能になる(BakeNdmf/
    // ExportUnifiedFbxのExportObject呼び出しと同じ轍)。同ファイル既存の
    // catch (TargetInvocationException tie) パターンで保護する
    static bool SetFormatBinary(object opts)
    {
        const BindingFlags F = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        for (var t = opts.GetType(); t != null; t = t.BaseType)
        {
            var m = t.GetMethod("SetExportFormat", F);
            if (m != null && m.GetParameters().Length == 1)
            {
                try
                {
                    m.Invoke(opts, new[] { EnumBinary(m.GetParameters()[0].ParameterType) });
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("Binary出力オプション設定(SetExportFormat)", tie));
                }
                return true;
            }
            var p = t.GetProperty("ExportFormat", F);
            if (p != null && p.CanWrite && p.PropertyType.IsEnum)
            {
                try
                {
                    p.SetValue(opts, EnumBinary(p.PropertyType), null);
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("Binary出力オプション設定(ExportFormatプロパティ)", tie));
                }
                return true;
            }
            var f = t.GetField("exportFormat", F);
            if (f != null && f.FieldType.IsEnum)
            {
                try
                {
                    f.SetValue(opts, EnumBinary(f.FieldType));
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("Binary出力オプション設定(exportFormatフィールド)", tie));
                }
                return true;
            }
        }
        return false;
    }

    // オプションオブジェクトの任意設定をsetterメソッド/プロパティ/フィールドの順で試す
    // dev#518: SetFormatBinaryと同様の理由でTargetInvocationExceptionを保護する
    static bool TrySetOption(object opts, string setterName, string propName,
                             string fieldName, object value)
    {
        const BindingFlags F = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        for (var t = opts.GetType(); t != null; t = t.BaseType)
        {
            var m = t.GetMethod(setterName, F);
            if (m != null && m.GetParameters().Length == 1)
            {
                try
                {
                    m.Invoke(opts, new[] { value });
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("オプション設定(" + setterName + ")", tie));
                }
                return true;
            }
            var p = t.GetProperty(propName, F);
            if (p != null && p.CanWrite)
            {
                try
                {
                    p.SetValue(opts, value, null);
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("オプション設定(" + propName + ")", tie));
                }
                return true;
            }
            var f = t.GetField(fieldName, F);
            if (f != null)
            {
                try
                {
                    f.SetValue(opts, value);
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("オプション設定(" + fieldName + ")", tie));
                }
                return true;
            }
        }
        return false;
    }

    static object EnumBinary(Type enumType)
    {
        try { return Enum.Parse(enumType, "Binary"); }
        catch { return Enum.ToObject(enumType, 1); }  // ExportFormat { ASCII=0, Binary=1 }
    }

    // dev#250(オーナー裁定2026-07-30、実報告Z8XBKJBC): prefab→Unity輸出だけは
    // 成功したのに、Rig設定(Configure Avatar)で必須HumanBoneが未割当のまま保存
    // されたアバターが実在する(isHuman==trueでも起こりうる、dev#233実測)。
    // 従来はhumanoid.jsonに当該キーが載らないまま素通りし、Blender側
    // (step01_import_vrm.py)の内部pal名FATALで初めて発覚していた
    // (dev#233が対応するのはそのメッセージの改善で、本機能が拾いきれなかった
    // 場合の最終フォールバックという関係になる)。
    // ここではUnity輸出の時点で、未割当の必須ボーンを実スケルトンの
    // Transform名から「命名規約辞書」で名前ベース推定して補完する
    // (オーナー指示: "humanoid取得は名前を取るだけの話")。
    // 追加裁定(2026-07-30): 「曖昧なら止まってユーザーに聞く」。候補が複数
    // (曖昧)・ゼロの場合は自動選択せず、対話できる経路(Unity Editorの
    // Export Avatarメニュー実行)ではダイアログで選ばせ、対話できない経路
    // (バッチ実行)では候補+対処法(bone_overrides.json)を提示して停止する。
    // 誤割当のまま黙って変換するより安全側に倒す方針。
    // 判定ロジック(SuggestBoneName/FindNearMisses/ResolveRequiredBone)は
    // Unity非依存(GameObject等を使わない)の純粋関数として実装し、
    // dotnetでコンパイル・実行して検証できるようにする
    // (tests\unity_exporter\test_bone_name_suggest.py)。
    // D2P_BONESUGGEST_PURE_BEGIN
    internal enum BoneSuggestStatus { Matched, Ambiguous, NotFound }

    internal struct BoneSuggestResult
    {
        public BoneSuggestStatus Status;
        public string BoneName;
        public List<string> Candidates;
    }

    // ResolveRequiredBoneの決定結果。Sourceは "already_assigned"(既に割当済み・
    // 無変更)/ "override"(bone_overrides.json指定)/ "suggested"(名前から自動推定)/
    // "override_invalid"(overrides指定がこのアバターに存在しない)/
    // "unresolved"(自動では決められない。呼び出し側がユーザーに聞く)
    internal struct BoneAssignmentDecision
    {
        public bool Assigned;
        public string BoneName;
        public string Source;
        public BoneSuggestStatus Status;
        public List<string> Candidates;
    }

    // Unity標準humanName(HumanTrait.BoneName相当)→ 各流儀での代表的な別名。
    // 大文字小文字・区切り文字(_ . : - 空白)のゆらぎはNormalizeBoneTokenで
    // 吸収するため、ここでは代表形を1つずつ書けば十分(Unityの自動マッピング
    // 相当の素直な実装。過剰なパターン網羅はしない)。対象は必須11ボーン
    // (pipeline\blender\step01_import_vrm.pyの必須チェック対象と一致させる)
    internal static readonly Dictionary<string, string[]> RequiredHumanBoneAliases =
        new Dictionary<string, string[]>
    {
        { "Hips", new[] { "Hips", "J_Bip_C_Hips", "Pelvis", "腰", "骨盤" } },
        { "Spine", new[] { "Spine", "J_Bip_C_Spine", "Spine1", "背骨" } },
        { "Head", new[] { "Head", "J_Bip_C_Head", "頭" } },
        { "LeftUpperArm", new[] { "LeftUpperArm", "UpperArm.L", "UpperArm_L",
            "LeftArm", "mixamorig:LeftArm", "J_Bip_L_UpperArm", "左腕", "左上腕" } },
        { "RightUpperArm", new[] { "RightUpperArm", "UpperArm.R", "UpperArm_R",
            "RightArm", "mixamorig:RightArm", "J_Bip_R_UpperArm", "右腕", "右上腕" } },
        { "LeftHand", new[] { "LeftHand", "Hand.L", "Hand_L", "mixamorig:LeftHand",
            "J_Bip_L_Hand", "左手" } },
        { "RightHand", new[] { "RightHand", "Hand.R", "Hand_R", "mixamorig:RightHand",
            "J_Bip_R_Hand", "右手" } },
        { "LeftUpperLeg", new[] { "LeftUpperLeg", "UpperLeg.L", "UpperLeg_L",
            "LeftUpLeg", "mixamorig:LeftUpLeg", "J_Bip_L_UpperLeg", "左太もも", "左腿" } },
        { "RightUpperLeg", new[] { "RightUpperLeg", "UpperLeg.R", "UpperLeg_R",
            "RightUpLeg", "mixamorig:RightUpLeg", "J_Bip_R_UpperLeg", "右太もも", "右腿" } },
        { "LeftFoot", new[] { "LeftFoot", "Foot.L", "Foot_L", "mixamorig:LeftFoot",
            "J_Bip_L_Foot", "左足首", "左足" } },
        { "RightFoot", new[] { "RightFoot", "Foot.R", "Foot_R", "mixamorig:RightFoot",
            "J_Bip_R_Foot", "右足首", "右足" } },
    };

    // エラー・ダイアログ表示用の日本語併記ラベル(dev#233と同じ方向性:
    // Unity側の人間可読名を出す)
    internal static readonly Dictionary<string, string> RequiredHumanBoneJaLabel =
        new Dictionary<string, string>
    {
        { "Hips", "Hips(腰/骨盤)" },
        { "Spine", "Spine(背骨)" },
        { "Head", "Head(頭)" },
        { "LeftUpperArm", "Left Upper Arm(左上腕)" },
        { "RightUpperArm", "Right Upper Arm(右上腕)" },
        { "LeftHand", "Left Hand(左手)" },
        { "RightHand", "Right Hand(右手)" },
        { "LeftUpperLeg", "Left Upper Leg(左太もも)" },
        { "RightUpperLeg", "Right Upper Leg(右太もも)" },
        { "LeftFoot", "Left Foot(左足)" },
        { "RightFoot", "Right Foot(右足)" },
    };

    // 区切り文字(_ . : - 空白)を除去し小文字化する。Mixamo("mixamorig:LeftFoot")・
    // Blender式("Foot.L"/"Foot_L")・VRoid("J_Bip_L_Foot")の表記ゆれを1つの
    // 比較形へ正規化する(日本語はそのまま、大文字小文字も区切りも無いため無害)
    internal static string NormalizeBoneToken(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        var sb = new StringBuilder(s.Length);
        foreach (var ch in s)
        {
            if (ch == '_' || ch == '.' || ch == ':' || ch == '-' || ch == ' ') continue;
            sb.Append(char.ToLowerInvariant(ch));
        }
        return sb.ToString();
    }

    // humanName(Unity標準表記、例"LeftFoot")に対し、実スケルトンのボーン名
    // 一覧から名前ベースで候補を探す。0件=NotFound、2件以上(異なる実名が
    // 別名辞書に一致)=Ambiguous、1件のみ=Matched。同一名の重複出現は1件と数える
    internal static BoneSuggestResult SuggestBoneName(string humanName,
        IEnumerable<string> actualBoneNames)
    {
        string[] aliases;
        if (!RequiredHumanBoneAliases.TryGetValue(humanName, out aliases))
            return new BoneSuggestResult
            { Status = BoneSuggestStatus.NotFound, Candidates = new List<string>() };

        var normalizedAliases = new HashSet<string>();
        normalizedAliases.Add(NormalizeBoneToken(humanName));
        foreach (var a in aliases) normalizedAliases.Add(NormalizeBoneToken(a));

        var matches = new List<string>();
        foreach (var actual in actualBoneNames)
        {
            if (string.IsNullOrEmpty(actual)) continue;
            if (normalizedAliases.Contains(NormalizeBoneToken(actual)) && !matches.Contains(actual))
                matches.Add(actual);
        }
        if (matches.Count == 0)
            return new BoneSuggestResult { Status = BoneSuggestStatus.NotFound, Candidates = matches };
        if (matches.Count > 1)
            return new BoneSuggestResult { Status = BoneSuggestStatus.Ambiguous, Candidates = matches };
        return new BoneSuggestResult
        { Status = BoneSuggestStatus.Matched, BoneName = matches[0], Candidates = matches };
    }

    // 文字列編集距離(Levenshtein)。候補ゼロ時の「近い名前」ヒント計算に使う
    internal static int LevenshteinDistance(string a, string b)
    {
        int n = a.Length, m = b.Length;
        var d = new int[n + 1, m + 1];
        for (int i = 0; i <= n; i++) d[i, 0] = i;
        for (int j = 0; j <= m; j++) d[0, j] = j;
        for (int i = 1; i <= n; i++)
            for (int j = 1; j <= m; j++)
            {
                int cost = a[i - 1] == b[j - 1] ? 0 : 1;
                d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1), d[i - 1, j - 1] + cost);
            }
        return d[n, m];
    }

    // 完全一致候補がゼロのときの参考表示専用(自動選択には使わない)。
    // 正規化後のLevenshtein距離が近いボーン名を最大maxResults件、近い順に返す
    internal static List<string> FindNearMisses(string humanName,
        IEnumerable<string> actualBoneNames, int maxResults = 5)
    {
        string[] aliases;
        if (!RequiredHumanBoneAliases.TryGetValue(humanName, out aliases))
            aliases = new string[0];
        var normAliases = new List<string> { NormalizeBoneToken(humanName) };
        foreach (var a in aliases) normAliases.Add(NormalizeBoneToken(a));

        var scored = new List<KeyValuePair<int, string>>();
        var seen = new HashSet<string>();
        foreach (var actual in actualBoneNames)
        {
            if (string.IsNullOrEmpty(actual) || !seen.Add(actual)) continue;
            var normActual = NormalizeBoneToken(actual);
            if (normActual.Length == 0) continue;
            int best = int.MaxValue;
            int bestAliasLen = 0;
            foreach (var na in normAliases)
            {
                if (na.Length == 0) continue;
                int d = LevenshteinDistance(na, normActual);
                if (d < best) { best = d; bestAliasLen = na.Length; }
            }
            if (best == int.MaxValue) continue;
            int longer = Math.Max(bestAliasLen, normActual.Length);
            int threshold = Math.Max(2, longer / 2);
            if (best <= threshold)
                scored.Add(new KeyValuePair<int, string>(best, actual));
        }
        scored.Sort((x, y) => x.Key.CompareTo(y.Key));
        var outList = new List<string>();
        for (int i = 0; i < scored.Count && i < maxResults; i++)
            outList.Add(scored[i].Value);
        return outList;
    }

    // 必須ボーン1個分の割当を決定する(Unity型に依存しない純粋ロジック)。
    // 優先順: ①既に割当済みならそれを尊重(無変更) ②bone_overrides.json指定が
    // あればそれを検証のうえ採用 ③名前から一意に推定できればそれを採用
    // ④それ以外(曖昧/候補ゼロ/override指定が実在しない)は自動で決めず、
    // 呼び出し側(Unity依存の配線)がheadlessならエラー、interactiveなら
    // ユーザーに選ばせる
    internal static BoneAssignmentDecision ResolveRequiredBone(string humanName,
        string existingBoneName, Dictionary<string, string> overrides,
        IEnumerable<string> actualBoneNames)
    {
        if (!string.IsNullOrEmpty(existingBoneName))
            return new BoneAssignmentDecision
            { Assigned = true, BoneName = existingBoneName, Source = "already_assigned" };

        string overrideName;
        if (overrides != null && overrides.TryGetValue(humanName, out overrideName)
            && !string.IsNullOrEmpty(overrideName))
        {
            bool exists = false;
            foreach (var n in actualBoneNames)
                if (n == overrideName) { exists = true; break; }
            if (exists)
                return new BoneAssignmentDecision
                { Assigned = true, BoneName = overrideName, Source = "override" };
            return new BoneAssignmentDecision
            {
                Assigned = false, Source = "override_invalid",
                Candidates = new List<string> { overrideName }
            };
        }

        var result = SuggestBoneName(humanName, actualBoneNames);
        if (result.Status == BoneSuggestStatus.Matched)
            return new BoneAssignmentDecision
            { Assigned = true, BoneName = result.BoneName, Source = "suggested" };

        var candidates = result.Status == BoneSuggestStatus.Ambiguous
            ? result.Candidates
            : FindNearMisses(humanName, actualBoneNames, 5);
        return new BoneAssignmentDecision
        {
            Assigned = false, Source = "unresolved",
            Status = result.Status, Candidates = candidates
        };
    }

    // headless(バッチ実行、聞く経路が構造的に無い)向けの停止メッセージ。
    // dev#233と同じ方向性(Unity側の人間可読名+対処手順)を踏襲する
    internal static string BuildUnresolvedHeadlessMessage(string humanName,
        BoneAssignmentDecision decision, string outDir)
    {
        string label;
        if (!RequiredHumanBoneJaLabel.TryGetValue(humanName, out label)) label = humanName;
        var sb = new StringBuilder();
        sb.Append("必須Humanoidボーン '" + label + "' が未割当です。");
        if (decision.Source == "override_invalid")
        {
            sb.Append("bone_overrides.jsonで指定された '" + decision.Candidates[0]
                + "' はこのアバターのボーン一覧に見つかりません。exact名で指定し直してください。");
        }
        else if (decision.Status == BoneSuggestStatus.Ambiguous)
        {
            sb.Append("名前からの候補が複数あり自動選択できません" +
                "(誤割当を避けるため停止します)。候補: "
                + string.Join(", ", decision.Candidates) + "。");
        }
        else
        {
            sb.Append("名前から一致するボーンが見つかりませんでした。");
            if (decision.Candidates != null && decision.Candidates.Count > 0)
                sb.Append("近い名前の候補: " + string.Join(", ", decision.Candidates) + "。");
        }
        sb.Append("対処: 1) 元のUnityプロジェクトでこのアバターを選択し、Rigタブ > " +
            "Configure Avatar から " + label + " を手動で割り当てて再輸出する、または " +
            "2) 出力フォルダ(" + outDir + ")に bone_overrides.json を作成し " +
            "{\"" + humanName + "\": \"<正しいボーン名>\"} のように指定してもう一度実行してください。");
        return sb.ToString();
    }
    // D2P_BONESUGGEST_PURE_END

    static readonly string[] RequiredHumanBoneNames = {
        "Hips", "Spine", "Head",
        "LeftUpperArm", "RightUpperArm", "LeftHand", "RightHand",
        "LeftUpperLeg", "RightUpperLeg", "LeftFoot", "RightFoot"
    };

    static string GetJaLabel(string humanName)
    {
        string label;
        return RequiredHumanBoneJaLabel.TryGetValue(humanName, out label) ? label : humanName;
    }

    // <outDir>\bone_overrides.json (任意、無ければ空扱い) を読む。
    // ユーザーが名前推定を待たず/推定に失敗した後で明示指定するための、
    // このツール専用の単純なフラット文字列マップ({"HumanName": "実ボーン名"})。
    // 形式を完全に自前で決められるため、外部JSONライブラリを増やさず
    // 正規表現で素直に読む(他所でJSON読込に使っている前例が無いため合わせて追加しない)
    static Dictionary<string, string> LoadBoneOverrides(string outDir)
    {
        var result = new Dictionary<string, string>();
        string path = Path.Combine(outDir, "bone_overrides.json");
        if (!File.Exists(path)) return result;
        string text = File.ReadAllText(path, Encoding.UTF8);
        foreach (Match m in Regex.Matches(text,
            "\"((?:[^\"\\\\]|\\\\.)*)\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\""))
        {
            result[UnescapeJsonString(m.Groups[1].Value)] = UnescapeJsonString(m.Groups[2].Value);
        }
        if (result.Count > 0)
            Debug.Log("D2P: bone_overrides.json を読み込み: " + result.Count + "件 (" + path + ")");
        return result;
    }

    static string UnescapeJsonString(string s)
    {
        return s.Replace("\\\"", "\"").Replace("\\\\", "\\");
    }

    // 必須HumanBoneのうち未割当のものを、既存割当尊重→bone_overrides.json→
    // 名前推定→(headlessならエラー/interactiveならダイアログ)の順に解決する。
    // humanは呼び出し側が用意したAvatar.humanDescription.humanの複製リストで、
    // ここで直接書き換える(実Avatarアセットには一切触れない)
    static void ApplyBoneNameSuggestions(GameObject go, List<HumanBone> human, string outDir)
    {
        var overrides = LoadBoneOverrides(outDir);
        List<Transform> actualBoneTransforms = null;
        List<string> actualBoneNames = null;

        foreach (var req in RequiredHumanBoneNames)
        {
            int idx = human.FindIndex(hb => hb.humanName == req);
            string existing = idx >= 0 ? human[idx].boneName : null;

            if (actualBoneNames == null)
            {
                actualBoneTransforms = new List<Transform>(go.GetComponentsInChildren<Transform>(true));
                actualBoneNames = actualBoneTransforms.ConvertAll(t => t.name);
            }

            var decision = ResolveRequiredBone(req, existing, overrides, actualBoneNames);
            string resolvedName;

            if (decision.Assigned)
            {
                if (decision.Source == "already_assigned") continue;  // 無変更(出力不変を担保)
                resolvedName = decision.BoneName;
                Debug.Log("D2P: " + req + (decision.Source == "override"
                    ? " をbone_overrides.jsonの指定で割当: " : " を名前から自動割当: ")
                    + resolvedName);
            }
            else if (decision.Source == "override_invalid")
            {
                throw new Exception(BuildUnresolvedHeadlessMessage(req, decision, outDir));
            }
            else if (UnityEngine.Application.isBatchMode)
            {
                // headless(バッチ実行): 誤割当のまま黙って進めるより、候補と
                // 対処法を提示して止める(オーナー裁定2026-07-30: 「曖昧なら
                // 止まってユーザーに聞く」。バッチには直接聞く経路が構造的に
                // 無いため、bone_overrides.jsonでの再指定を提示する)
                throw new Exception(BuildUnresolvedHeadlessMessage(req, decision, outDir));
            }
            else
            {
                // interactive(Unity EditorのExport Avatarメニュー実行): 勝手に
                // 選ばず、ユーザーに選ばせる(dev#236と同じ「ユーザー起点の対話
                // なら可」の扱い。起動時セットアップの押し付けモーダルとは異なる)
                resolvedName = BoneChoiceWindow.PickBone(GetJaLabel(req), decision.Status,
                    decision.Candidates ?? new List<string>(), actualBoneTransforms);
                if (resolvedName == null)
                    throw new Exception("D2P: " + GetJaLabel(req)
                        + " の割当がキャンセルされたため輸出を中止しました。");
                Debug.Log("D2P: " + req + " をユーザー選択で割当: " + resolvedName);
            }

            if (idx >= 0)
            {
                var hb = human[idx];
                hb.boneName = resolvedName;
                human[idx] = hb;
            }
            else
            {
                human.Add(new HumanBone
                {
                    humanName = req,
                    boneName = resolvedName,
                    limit = new HumanLimit { useDefaultValues = true }
                });
            }
        }
    }

    static void ExportHumanoid(GameObject go, string outDir)
    {
        var animator = go.GetComponentInChildren<Animator>();
        if (animator == null || animator.avatar == null || !animator.avatar.isHuman)
            throw new Exception("Humanoid設定されたAvatarが見つかりません");
        var human = new List<HumanBone>(animator.avatar.humanDescription.human);
        ApplyBoneNameSuggestions(go, human, outDir);
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-humanoid-1\",\n");
        // D2P平坦化済みの印: step01がメッシュ行列=アーマチュア行列の固定を行う
        sb.Append("  \"d2p_flattened\": true,\n");
        // ルートボーン復元のフォールバック用: Hipsのルート基準位置(Unity座標・m)
        var hipsT = animator.GetBoneTransform(HumanBodyBones.Hips);
        if (hipsT != null)
        {
            var p = go.transform.InverseTransformPoint(hipsT.position);
            sb.AppendFormat(System.Globalization.CultureInfo.InvariantCulture,
                "  \"hips_local\": [{0}, {1}, {2}],\n", p.x, p.y, p.z);
        }
        sb.Append("  \"humanoid\": {\n");
        bool first = true;
        foreach (var hb in human)
        {
            if (string.IsNullOrEmpty(hb.boneName)) continue;
            if (!first) sb.Append(",\n");
            first = false;
            sb.AppendFormat("    \"{0}\": \"{1}\"", J(hb.humanName), J(hb.boneName));
        }
        sb.Append("\n  }\n}\n");
        File.WriteAllText(Path.Combine(outDir, "humanoid.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    // dev#300(実報告VLGQR7ES): Unity純正FBXエクスポータ(com.unity.formats.fbx)は、
    // 書き出し対象の階層内に同名のTransformが複数存在すると、内部で連番サフィックス
    // (例: "Tail"→"Tail_3")を付けて一意化してしまう。ExportHumanoid/ExportMaterialsは
    // このFBXエクスポータ内部のリネームを一切知らず、輸出前のUnity上の名前
    // (Transform.name)をキーにhumanoid.json/material_map.jsonを書くため、輸出対象の
    // 階層に重複名が存在すると、輸出後のFBX実体の名前とズレて参照が外れる
    // (VRM/VRChatアバターの尻尾・耳等のボーンチェーンは同一名の連続が一般的で、
    // その末端に同名の非スキンアクセサリメッシュが付く構成もよくある。
    // ExportMaterials側のseenNamesチェック(重複時に先勝ちで無視)はRenderer同士の
    // 重複しか見ておらず、Renderer名がボーン等の非Renderer Transformと重複する
    // ケースは検知できない――実報告のログに重複警告が出ていなかった事実と整合)。
    //
    // 対策(症状別の特別扱いではなく入口で正規化): 輸出直前にここで階層全体の
    // Transform名を一括して一意化してしまえば、Unity FBXエクスポータが独自に
    // リネームする余地そのものが無くなり、以降の全出力
    // (humanoid.json/統合FBX/material_map.json)が同じ名前で揃う。
    // 呼び出し位置は、これより後に階層(GameObject/Transform)を追加・改名する
    // 処理を置かないこと(置くと再びズレが復活する)。
    static void EnsureUniqueTransformNames(GameObject root)
    {
        var all = new List<Transform>();
        CollectAllTransforms(root.transform, all);
        var names = new List<string>(all.Count);
        foreach (var t in all) names.Add(t.name);
        var uniqueNames = ResolveUniqueNames(names);
        int renamed = 0;
        for (int i = 0; i < all.Count; i++)
        {
            if (uniqueNames[i] == names[i]) continue;
            Debug.Log("D2P: [名前重複解消] " + GetHierarchyPath(all[i]) + " -> \"" + uniqueNames[i] + "\"");
            all[i].name = uniqueNames[i];
            renamed++;
        }
        if (renamed > 0)
            Debug.Log("D2P: 名前重複解消完了、" + renamed + "件リネーム(輸出階層の名前を一意化)");
    }

    // D2P_UNIQUENAME_PURE_BEGIN
    // 名前列(輸出階層をたどった順)の重複を解消し、全体で一意な名前列を返す
    // 純粋関数。UnityEngine型に一切依存しない(文字列・コレクションのみ)ため、
    // Unity無しでdotnet単体でも振る舞いを検証できる
    // (tests\unity_exporter\test_material_map_dup_rename.py参照)。
    // 初出の名前はそのまま、2回目以降は "_2", "_3", ... を付けて一意化する。
    // 付与候補が既存の名前(元から"_2"等が使われているケースを含む)と衝突する
    // 場合はさらに数字を進めて衝突しない名前を探す(値を寄せて合わせる場当たり
    // 実装にしない――既存の"Tail_2"を上書きしてしまうような実装は不可)。
    internal static List<string> ResolveUniqueNames(List<string> namesInOrder)
    {
        var used = new HashSet<string>();
        var result = new List<string>(namesInOrder.Count);
        foreach (var original in namesInOrder)
        {
            string candidate = original;
            if (!used.Add(candidate))
            {
                int n = 1;
                do
                {
                    n++;
                    candidate = original + "_" + n;
                } while (!used.Add(candidate));
            }
            result.Add(candidate);
        }
        return result;
    }
    // D2P_UNIQUENAME_PURE_END

    static void ExportMaterials(GameObject go, string outDir, string fbxName)
    {
        var texFiles = new Dictionary<Texture, string>();
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-materials-1\",\n");
        sb.AppendFormat("  \"fbx\": \"{0}\",\n  \"meshes\": {{\n", J(fbxName));
        bool firstMesh = true;
        // SkinnedMeshRenderer(体・服等スキン済み)に加え、MeshRenderer(帽子・
        // リボン等、ボーンへTransform直付けの非スキンアクセサリ。PhysBone/
        // Constraintで動かす構成でVRChatアバターにごく一般的)も走査対象に
        // 含める。従来SkinnedMeshRendererのみだったため、非スキンメッシュは
        // material_map.jsonに載らず、step01_import_vrm.pyの
        // extract_materials_from_unity_map()が単色フォールバックにしていた
        // (2026-07-26実測: shapell_Osakiのベレー帽・リボンが灰色化)。
        // 出力名はどちらもRenderer.name(=GameObject名)で揃える。Blender側は
        // orig_names(FBXインポート時の元オブジェクト名)をキーに
        // mesh_map.get(orig)で引くため、SkinnedMeshRendererと同じ命名規則で
        // 揃える必要がある。
        var seenNames = new HashSet<string>();
        var renderers = new List<Renderer>();
        renderers.AddRange(go.GetComponentsInChildren<SkinnedMeshRenderer>(false));
        renderers.AddRange(go.GetComponentsInChildren<MeshRenderer>(false));
        foreach (var r in renderers)
        {
            Mesh sharedMesh;
            var smr = r as SkinnedMeshRenderer;
            if (smr != null)
                sharedMesh = smr.sharedMesh;
            else
            {
                var mf = r.GetComponent<MeshFilter>();
                sharedMesh = mf != null ? mf.sharedMesh : null;
            }
            if (sharedMesh == null || !r.enabled) continue;
            if (!seenNames.Add(r.name))
            {
                Debug.LogWarning("D2P: material_map.jsonでメッシュ名が重複: " + r.name
                                  + "(先勝ちで無視)");
                continue;
            }
            if (!firstMesh) sb.Append(",\n");
            firstMesh = false;
            sb.AppendFormat("    \"{0}\": [\n", J(r.name));
            var mats = r.sharedMaterials;
            for (int i = 0; i < mats.Length; i++)
            {
                var m = mats[i];
                string tex = null;
                float[] col = { 1, 1, 1, 1 };
                bool twoSided = false;
                string matName = m != null ? m.name : "";
                if (m != null)
                {
                    if (m.mainTexture != null)
                        tex = SaveTexture(m.mainTexture, outDir, texFiles);
                    if (m.HasProperty("_Color"))
                    {
                        var c = m.color;
                        col = new[] { c.r, c.g, c.b, c.a };
                    }
                    // lilToon等: _Cull 0=両面
                    if (m.HasProperty("_Cull"))
                        twoSided = m.GetFloat("_Cull") < 0.5f;
                }
                sb.AppendFormat(
                    "      {{\"material_name\": \"{0}\", \"texture\": {1}, " +
                    "\"color\": [{2}], \"double_sided\": {3}}}{4}\n",
                    J(matName),
                    tex == null ? "null" : "\"" + J(tex) + "\"",
                    string.Join(", ", Array.ConvertAll(col,
                        v => v.ToString(System.Globalization.CultureInfo.InvariantCulture))),
                    twoSided ? "true" : "false",
                    i < mats.Length - 1 ? "," : "");
            }
            sb.Append("    ]");
        }
        sb.Append("\n  }\n}\n");
        File.WriteAllText(Path.Combine(outDir, "material_map.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    static string SaveTexture(Texture tex, string outDir, Dictionary<Texture, string> cache)
    {
        string cached;
        if (cache.TryGetValue(tex, out cached)) return cached;
        // どんな圧縮形式でもRenderTexture経由で読めるPNGにする
        var rt = RenderTexture.GetTemporary(tex.width, tex.height, 0,
            RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
        Graphics.Blit(tex, rt);
        var prev = RenderTexture.active;
        RenderTexture.active = rt;
        var read = new Texture2D(tex.width, tex.height, TextureFormat.RGBA32, false);
        read.ReadPixels(new Rect(0, 0, tex.width, tex.height), 0, 0);
        read.Apply();
        RenderTexture.active = prev;
        RenderTexture.ReleaseTemporary(rt);
        string file = string.Format("tex_{0:00}.png", cache.Count);
        File.WriteAllBytes(Path.Combine(outDir, file), read.EncodeToPNG());
        UnityEngine.Object.DestroyImmediate(read);
        cache[tex] = file;
        return file;
    }

    static string J(string s)
    {
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}

// dev#250: 必須Humanoidボーンが未割当で、名前からの自動推定も曖昧/該当なし
// だったときに、Unity Editor上のExport Avatarメニュー実行(ユーザーがその場に
// いる対話的な操作)に限って表示する候補選択ダイアログ。バッチ実行では
// 使わない(DiveToPalworldExporter.ApplyBoneNameSuggestionsがApplication.
// isBatchModeで分岐する)。dev#236が禁じた「起動時セットアップの押し付け
// モーダル」とは異なり、ユーザーが選んだExportという操作の延長で出す
// ユーザー起点の対話なので許容される。
internal class BoneChoiceWindow : EditorWindow
{
    string humanLabel;
    DiveToPalworldExporter.BoneSuggestStatus status;
    List<string> candidateNames;
    List<string> candidateDescriptions;
    string result;
    bool done;

    public static string PickBone(string humanLabel,
        DiveToPalworldExporter.BoneSuggestStatus status,
        List<string> candidateNames, List<Transform> allTransforms)
    {
        var window = ScriptableObject.CreateInstance<BoneChoiceWindow>();
        window.titleContent = new GUIContent("DiveToPalworld: ボーン割当の確認");
        window.humanLabel = humanLabel;
        window.status = status;
        window.candidateNames = candidateNames;
        window.candidateDescriptions = new List<string>();
        foreach (var n in candidateNames)
        {
            string path = n;
            foreach (var t in allTransforms)
            {
                if (t != null && t.name == n)
                {
                    path = BuildHierarchyPathForDialog(t);
                    break;
                }
            }
            window.candidateDescriptions.Add(n + "  (" + path + ")");
        }
        window.minSize = new Vector2(520, 220);
        window.result = null;
        window.done = false;
        window.ShowModal();
        return window.done ? window.result : null;
    }

    static string BuildHierarchyPathForDialog(Transform t)
    {
        var sb = new StringBuilder(t.name);
        for (var p = t.parent; p != null; p = p.parent)
            sb.Insert(0, p.name + "/");
        return sb.ToString();
    }

    void OnGUI()
    {
        EditorGUILayout.LabelField(
            "必須Humanoidボーン '" + humanLabel + "' が未割当です。",
            EditorStyles.wordWrappedLabel);
        string hint = status == DiveToPalworldExporter.BoneSuggestStatus.Ambiguous
            ? "名前から複数の候補が見つかりました。正しいものを選択してください:"
            : "名前から一致する候補が見つかりませんでした。近い候補から選ぶか、" +
              "キャンセルしてUnity側(Rigタブ > Configure Avatar)で割り当ててください:";
        EditorGUILayout.LabelField(hint, EditorStyles.wordWrappedLabel);
        EditorGUILayout.Space();
        for (int i = 0; i < candidateDescriptions.Count; i++)
        {
            if (GUILayout.Button(candidateDescriptions[i]))
            {
                result = candidateNames[i];
                done = true;
                Close();
                return;
            }
        }
        EditorGUILayout.Space();
        if (GUILayout.Button("キャンセル(このアバターの輸出を中止する)"))
        {
            done = false;
            Close();
        }
    }
}
