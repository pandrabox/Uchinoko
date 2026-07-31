// Uchinoko for Palworld 起動ラッパー(配布zipルート専用)
// 本体は _internal\Uchinoko.exe。ルートを exe / _internal\ / README.md の
// 3点だけに保つため、本体一式は _internal\ に畳んである(相対関係は据え置き)。
//
// dev#216 WP2(2026-07-30): 自己更新の「適用エンジン」をここに実装する。
// _internal\Uchinoko.exeは実行中の自分自身を入れ替えられないため、_internal\の外にいる
// このランチャーが、アプリ完全終了後・次回起動前のタイミングでファイル入れ替えを行う
// (詳細設計: work\night_20260729\update_design.md 3節)。
//
// app\DiveToPalworld.cs(独立してビルドされる別のexe)との契約(ファイル経由の疎結合。
// 両者は別コンパイル単位なので、これがインターフェースの全てである):
//   install_root\_update\pending.json
//     通常更新: SelfUpdate.WritePendingJson(app側)が書く。
//       {"version","from_version","staged_at","staging_internal_dir"}
//     Tier2手動ロールバック要求: GUIの「前のバージョンに戻す」ボタンが書く。
//       {"revert": true, "requested_at"}
//       (バックアップは常に1世代のみなのでsource_dir等は不要。GUI側は意思表示だけでよい)
//   install_root\_update\verify_pending.json
//     ランチャーが適用直後に書く({"version"})。新バージョンのUchinoko.exeがメイン
//     ウィンドウのShownイベントで削除する(SelfUpdate.ClearVerifyPendingSignal)。
//     次回ランチャー起動時にまだ存在していたら「画面が出る前に落ちた」と判定し
//     Tier1自動ロールバックする。
//   _internal\.update_backup\
//     直前1世代分のバックアップ(allowlist項目のみ、internal\<相対パス>/root\<相対パス>
//     のサブフォルダ構造)。常に「現在+1つ前」のみ保持する。
//   _internal\.failed_update\
//     Tier1自動ロールバック発動時、起動できなかった新版のallowlist項目を診断用に
//     退避する場所(次の正常適用が成功すると自動的に掃除される)。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

static class DiveToPalworldLauncher
{
    [STAThread]
    static void Main()
    {
        string[] cmdArgs = Environment.GetCommandLineArgs();
        for (int i = 1; i < cmdArgs.Length; i++)
        {
            if (string.Equals(cmdArgs[i], "--check-apply-engine", StringComparison.OrdinalIgnoreCase)
                && i + 1 < cmdArgs.Length)
            {
                ApplyEngineSelfTest.RunCli(cmdArgs[i + 1]);
                return;
            }
        }

        string here = Application.StartupPath;

        // dev#216 WP2: 通常起動でも「--apply-update」付き起動でも、常にまずここを通す
        // (design 2節: 「常に以下を最初にチェック」)。pending.json/verify_pending.jsonが
        // 無ければ何もせず既存どおりの起動になる(全既存ユーザーへの影響ゼロ)
        string notice = null;
        try
        {
            ApplyEngine.RunStartupStateMachine(here, out notice);
        }
        catch (Exception ex)
        {
            // 適用エンジン自体の想定外エラーでアプリが二度と起動できなくなる事故を
            // 避ける(フェイルセーフ優先。何もせず従来どおりの起動を試みる)
            notice = "更新処理で予期しないエラーが発生しました(前のバージョンのまま起動します): "
                + ex.Message;
        }
        if (!string.IsNullOrEmpty(notice))
        {
            try
            {
                MessageBox.Show(notice, "Uchinoko for Palworld", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            catch (Exception) { }
        }

        string target = Path.Combine(Path.Combine(here, "_internal"), "Uchinoko.exe");
        if (!File.Exists(target))
        {
            MessageBox.Show(
                "Uchinoko for Palworld本体が見つかりません。" + Environment.NewLine + target + Environment.NewLine
                + Environment.NewLine
                + "zipを展開したフォルダの中の _internal フォルダを移動・削除していないか確認してください。",
                "Uchinoko for Palworld", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo(target);
            psi.WorkingDirectory = Path.GetDirectoryName(target);
            psi.UseShellExecute = false;
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("起動に失敗しました。" + Environment.NewLine + ex.Message,
                "Uchinoko for Palworld", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

// 極小のJSONフィールド抽出(正規表現ベース)。app\DiveToPalworld.csのJsonStr等と同じ
// 「自前生成JSON限定」の割り切りを踏襲する(このexe自身が生成したpending.json/
// verify_pending.jsonしか読まないため、汎用JSONパーサは不要)。
internal static class MiniJson
{
    internal static string GetString(string json, string key)
    {
        if (string.IsNullOrEmpty(json)) return null;
        Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
        if (!m.Success) return null;
        return m.Groups[1].Value.Replace("\\\\", "\\").Replace("\\\"", "\"");
    }

    internal static bool GetBool(string json, string key, bool defaultValue)
    {
        if (string.IsNullOrEmpty(json)) return defaultValue;
        Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(true|false)");
        if (!m.Success) return defaultValue;
        return m.Groups[1].Value == "true";
    }
}

// 入れ替え1件分(どこからどこへ、バックアップはどのキーへ退避するか)。
internal struct SwapItem
{
    internal string SourcePath;
    internal string TargetPath;
    internal string BackupKey;
}

// dev#216 WP2: ランチャー側の適用エンジン本体。allowlist方式のファイル入れ替えを
// 1本の関数(ApplyItems)に集約し、通常適用・Tier1自動ロールバック・Tier2手動ロールバックの
// 3経路すべてがこれを呼ぶ(design 3.3節「新規コードパスを増やさない」方針そのもの)。
internal static class ApplyEngine
{
    internal const string UpdateBackupDirName = ".update_backup";
    internal const string FailedUpdateDirName = ".failed_update";
    // app\DiveToPalworld.cs の SelfUpdate.DistTopFolderName と同じ前提(Compress-Archive
    // -Path $Stage で作った配布zipは展開すると必ずこのフォルダ名が1階層かぶる)
    internal const string DistTopFolderName = "Uchinoko_for_Palworld";

    // _internal\配下のallowlist項目(design 3.1節)。build\make_dist.ps1が生成する
    // 配布物のトップレベル構成そのもの。新パッケージ側に存在しない項目は触らない
    // (allowlist原則。ユーザーデータ側は存在確認すら不要)
    internal static readonly string[] InternalAllowlistRelPaths = new string[]
    {
        "Uchinoko.exe", "LICENSE", "THIRD_PARTY_LICENSES.txt", "pipeline", "unity",
        Path.Combine("assets", "third_party"), Path.Combine("assets", "blender_patch"),
    };

    // install_root直下のallowlist項目(design 3.1節手順4)。
    internal static readonly string[] RootAllowlistRelPaths = new string[] { "README.md", "manual.html" };

    // テスト専用のフォールト注入点(本番はnull)。1項目の適用が完了するたびに呼ばれ、
    // 例外を投げれば「この項目の直後で失敗した」ケースを決定的に再現できる
    // (app\DiveToPalworld.csのDownloaderデリゲート注入と同じ設計思想)。
    internal delegate void FaultHook(SwapItem item);

    internal static void SafeDeleteFile(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch (Exception) { }
    }

    internal static void SafeDeleteDir(string path)
    {
        try { if (Directory.Exists(path)) Directory.Delete(path, true); } catch (Exception) { }
    }

    static List<SwapItem> BuildItems(string sourceInternalRoot, string sourceRootDir, string installRoot)
    {
        string internalDir = Path.Combine(installRoot, "_internal");
        var items = new List<SwapItem>();
        foreach (string rel in InternalAllowlistRelPaths)
        {
            items.Add(new SwapItem
            {
                SourcePath = Path.Combine(sourceInternalRoot, rel),
                TargetPath = Path.Combine(internalDir, rel),
                BackupKey = Path.Combine("internal", rel),
            });
        }
        foreach (string rel in RootAllowlistRelPaths)
        {
            items.Add(new SwapItem
            {
                SourcePath = Path.Combine(sourceRootDir, rel),
                TargetPath = Path.Combine(installRoot, rel),
                BackupKey = Path.Combine("root", rel),
            });
        }
        return items;
    }

    // 新パッケージ(staging\Uchinoko_for_Palworld\)を適用元とする通常適用用の
    // 入れ替え項目リスト。
    internal static List<SwapItem> BuildItemsFromStagingDist(string stagingDistRoot, string installRoot)
    {
        return BuildItems(Path.Combine(stagingDistRoot, "_internal"), stagingDistRoot, installRoot);
    }

    // バックアップ(.update_backup\ / .failed_update\)を適用元とするTier1/Tier2復元用の
    // 入れ替え項目リスト。BackupKeyの構造がBuildItemsFromStagingDistと完全に同じ
    // (internal\<rel> / root\<rel>)なので、バックアップフォルダ自体をそのまま
    // 「適用元ディレクトリ」として渡せる(design 3.3節「同じ関数を再利用」の実体)。
    internal static List<SwapItem> BuildItemsFromBackup(string backupRoot, string installRoot)
    {
        return BuildItems(Path.Combine(backupRoot, "internal"), Path.Combine(backupRoot, "root"), installRoot);
    }

    // allowlist項目だけを入れ替える中核関数。既存の対応項目は全てbackupDestへ退避して
    // から、source側を正式名へ配置する。1項目でも例外が出たら、それまでに完了した項目を
    // ベストエフォートで逆順に戻す(全か無か、design 3.1節)。新パッケージ側に存在しない
    // 項目はそもそも触らない(allowlist原則。既存のユーザーデータには存在確認すら行わない)。
    internal static bool ApplyItems(List<SwapItem> items, string backupDest, FaultHook faultHook, out string error)
    {
        error = null;
        var done = new List<SwapItem>();
        try
        {
            Directory.CreateDirectory(backupDest);
            foreach (SwapItem item in items)
            {
                if (!File.Exists(item.SourcePath) && !Directory.Exists(item.SourcePath))
                    continue;
                string backupPath = Path.Combine(backupDest, item.BackupKey);
                Directory.CreateDirectory(Path.GetDirectoryName(backupPath));
                if (Directory.Exists(item.TargetPath))
                {
                    if (Directory.Exists(backupPath)) Directory.Delete(backupPath, true);
                    if (File.Exists(backupPath)) File.Delete(backupPath);
                    Directory.Move(item.TargetPath, backupPath);
                }
                else if (File.Exists(item.TargetPath))
                {
                    if (File.Exists(backupPath)) File.Delete(backupPath);
                    if (Directory.Exists(backupPath)) Directory.Delete(backupPath, true);
                    File.Move(item.TargetPath, backupPath);
                }
                Directory.CreateDirectory(Path.GetDirectoryName(item.TargetPath));
                if (Directory.Exists(item.SourcePath))
                    Directory.Move(item.SourcePath, item.TargetPath);
                else
                    File.Move(item.SourcePath, item.TargetPath);

                done.Add(item);
                if (faultHook != null) faultHook(item);
            }
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            for (int i = done.Count - 1; i >= 0; i--)
            {
                SwapItem item = done[i];
                try
                {
                    string backupPath = Path.Combine(backupDest, item.BackupKey);
                    if (Directory.Exists(item.TargetPath)) Directory.Delete(item.TargetPath, true);
                    else if (File.Exists(item.TargetPath)) File.Delete(item.TargetPath);
                    if (Directory.Exists(backupPath)) Directory.Move(backupPath, item.TargetPath);
                    else if (File.Exists(backupPath)) File.Move(backupPath, item.TargetPath);
                }
                catch (Exception) { /* ベストエフォート。これ以上はできない */ }
            }
            return false;
        }
    }

    // ランチャー起動のたびに常に最初に呼ばれる状態機械の入口(design 2節)。
    // verify_pending.json > pending.json の優先順で1つだけ処理し、最後に使い捨ての
    // download/staging(design 3.4節「恒常化しない」原則)を無条件で掃除する。
    internal static void RunStartupStateMachine(string installRoot, out string notice)
    {
        notice = null;
        string updateDir = Path.Combine(installRoot, "_update");
        string verifyPendingPath = Path.Combine(updateDir, "verify_pending.json");
        string pendingPath = Path.Combine(updateDir, "pending.json");

        try
        {
            if (File.Exists(verifyPendingPath))
            {
                notice = HandleTier1Check(installRoot, verifyPendingPath);
            }
            else if (File.Exists(pendingPath))
            {
                string json;
                try { json = File.ReadAllText(pendingPath, Encoding.UTF8); }
                catch (Exception) { json = null; }
                bool revert = MiniJson.GetBool(json, "revert", false);
                notice = revert
                    ? HandleTier2Revert(installRoot, pendingPath)
                    : HandleNormalApply(installRoot, updateDir, pendingPath, json);
            }
            SafeDeleteDir(Path.Combine(updateDir, "download"));
            SafeDeleteDir(Path.Combine(updateDir, "staging"));
        }
        catch (Exception ex)
        {
            notice = "更新処理で予期しないエラーが発生しました(前のバージョンのまま起動します): "
                + ex.Message;
        }
    }

    static string HandleNormalApply(string installRoot, string updateDir, string pendingPath, string pendingJson)
    {
        string newVersion = MiniJson.GetString(pendingJson, "version");
        string stagingInternalDir = MiniJson.GetString(pendingJson, "staging_internal_dir");
        if (string.IsNullOrEmpty(stagingInternalDir) || !Directory.Exists(stagingInternalDir))
        {
            // 壊れた/古いpending.json。安全側: 何もせず片付けて旧版起動を続ける
            SafeDeleteFile(pendingPath);
            return null;
        }
        string stagingDistRoot = Path.GetDirectoryName(
            stagingInternalDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        if (string.IsNullOrEmpty(stagingDistRoot))
        {
            SafeDeleteFile(pendingPath);
            return null;
        }

        string internalDir = Path.Combine(installRoot, "_internal");
        string tmpBackup = Path.Combine(internalDir, UpdateBackupDirName + "_tmp");
        SafeDeleteDir(tmpBackup);

        List<SwapItem> items = BuildItemsFromStagingDist(stagingDistRoot, installRoot);
        string error;
        bool ok = ApplyItems(items, tmpBackup, null, out error);
        if (!ok)
        {
            // design 3.1節: 途中失敗はApplyItems内部で既にベストエフォートロールバック
            // 済み(全か無か)。ここでは後始末だけ行い、無傷な旧版の起動を継続する
            SafeDeleteDir(tmpBackup);
            SafeDeleteFile(pendingPath);
            return "バージョン " + (newVersion ?? "?") + " への更新の適用に失敗したため、"
                + "前のバージョンのまま起動します。詳細: " + error;
        }

        string backupDest = Path.Combine(internalDir, UpdateBackupDirName);
        SafeDeleteDir(backupDest);
        Directory.Move(tmpBackup, backupDest);
        SafeDeleteDir(Path.Combine(internalDir, FailedUpdateDirName));   // 適用成功時は過去の失敗診断ゴミを掃除してよい

        File.WriteAllText(Path.Combine(updateDir, "verify_pending.json"),
            "{\n  \"version\": \"" + JsonEsc(newVersion) + "\"\n}\n", new UTF8Encoding(false));
        SafeDeleteFile(pendingPath);
        // 成功時は無音(既存の「起動時チェック失敗は完全に無音」方針を踏襲。確認は
        // Shownイベント側のverify_pending.json削除、失敗ならTier1が次回検知する)
        return null;
    }

    static string HandleTier1Check(string installRoot, string verifyPendingPath)
    {
        string failedVersion = null;
        try
        {
            string vjson = File.ReadAllText(verifyPendingPath, Encoding.UTF8);
            failedVersion = MiniJson.GetString(vjson, "version");
        }
        catch (Exception) { }

        string internalDir = Path.Combine(installRoot, "_internal");
        string backupDest = Path.Combine(internalDir, UpdateBackupDirName);
        if (!Directory.Exists(backupDest))
        {
            // バックアップが無い(想定外の状態)。これ以上何もできないので通知のみ
            SafeDeleteFile(verifyPendingPath);
            return "更新後の起動確認ができませんでしたが、復元用のバックアップが見つかりません"
                + "でした。問題があれば手動でのサポート対応が必要です。";
        }

        List<SwapItem> items = BuildItemsFromBackup(backupDest, installRoot);
        string failedDest = Path.Combine(internalDir, FailedUpdateDirName);
        SafeDeleteDir(failedDest);
        string error;
        bool ok = ApplyItems(items, failedDest, null, out error);
        SafeDeleteFile(verifyPendingPath);
        if (!ok)
        {
            return "自動復元に失敗しました。手動でのサポート対応が必要です。詳細: " + error;
        }
        // 復元元(backupDest)は今回の入れ替えで中身を使い切った(全項目がinternalDir/
        // installRootへ移動済み)。空の外殻だけが残るので削除する。次に正常な適用が
        // 起きるまでバックアップ無しの状態になるが、allowlist方式なので危険はない
        SafeDeleteDir(backupDest);

        return string.IsNullOrEmpty(failedVersion)
            ? "更新後の起動に失敗したため、自動的に前のバージョンへ戻しました。"
            : "バージョン " + failedVersion + " への更新後の起動に失敗したため、自動的に前のバージョンへ戻しました。";
    }

    static string HandleTier2Revert(string installRoot, string pendingPath)
    {
        string internalDir = Path.Combine(installRoot, "_internal");
        string backupSrc = Path.Combine(internalDir, UpdateBackupDirName);
        if (!Directory.Exists(backupSrc))
        {
            SafeDeleteFile(pendingPath);
            return "前のバージョンに戻すためのバックアップが見つかりませんでした。";
        }
        List<SwapItem> items = BuildItemsFromBackup(backupSrc, installRoot);
        string tmpNewBackup = Path.Combine(internalDir, UpdateBackupDirName + "_tmp");
        SafeDeleteDir(tmpNewBackup);
        string error;
        bool ok = ApplyItems(items, tmpNewBackup, null, out error);
        SafeDeleteFile(pendingPath);
        if (!ok)
        {
            SafeDeleteDir(tmpNewBackup);
            return "前のバージョンへの復元に失敗しました。詳細: " + error;
        }
        // 戻す直前まで生きていた版(ユーザーが嫌がって戻された側)が新しいバックアップに
        // なる。これでもう一度「進める/戻す」のどちらへも対応できる(design 3.3節)
        SafeDeleteDir(backupSrc);
        Directory.Move(tmpNewBackup, backupSrc);
        return "前のバージョンに戻しました。";
    }

    static string JsonEsc(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}

// dev#216 WP2: ApplyEngineの隠しCLI単体検査(--check-apply-engine <出力先dir>)。
// 実GUI起動・実DL・実ランチャー起動は一切行わず、擬似ディレクトリツリー(allowlist項目+
// ユーザーデータ相当のダミーファイル)だけで5対照を検査する
// (app\DiveToPalworld.csの--check-self-update等と同じ動機・同じ手口)。
//   case1: 正常適用(allowlist内のみ変わる・ユーザーデータ不変)
//   case2: 途中失敗(フォールト注入)->全か無かで復帰、staging側も何も消費されない
//   case3: Tier1シグナル未達(verify_pending.json残存)->次回起動で自動復帰
//   case4: Tier1シグナル達成(verify_pending.json削除済み)->復帰しない
//   case5: Tier2手動ロールバック(revert:trueのpending.json)->前版へ復帰、再度戻せる
internal static class ApplyEngineSelfTest
{
    internal static void RunCli(string outDir)
    {
        Directory.CreateDirectory(outDir);
        var problems = new List<string>();
        string workDir = Path.Combine(outDir, "work");
        ApplyEngine.SafeDeleteDir(workDir);
        Directory.CreateDirectory(workDir);

        RunCase1NormalApply(Path.Combine(workDir, "case1"), problems);
        RunCase2MidwayFailureRollback(Path.Combine(workDir, "case2"), problems);
        RunCase3Tier1Rollback(Path.Combine(workDir, "case3"), problems);
        RunCase4Tier1SignalAchieved(Path.Combine(workDir, "case4"), problems);
        RunCase5Tier2Revert(Path.Combine(workDir, "case5"), problems);

        bool ok = problems.Count == 0;
        var sb = new StringBuilder();
        sb.AppendLine("=== apply engine (dev#216 WP2) unit table ===");
        sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
        foreach (string p in problems) sb.AppendLine("  " + p);
        File.WriteAllText(Path.Combine(outDir, "apply_engine_check.txt"), sb.ToString(), new UTF8Encoding(false));
        Console.WriteLine(ok ? "APPLY_ENGINE_CHECK_OK" : "APPLY_ENGINE_CHECK_FAIL");
        Environment.Exit(ok ? 0 : 1);
    }

    static void WriteText(string path, string content)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllText(path, content, new UTF8Encoding(false));
    }

    static string ReadTextOrNull(string path)
    {
        try { return File.Exists(path) ? File.ReadAllText(path, Encoding.UTF8) : null; }
        catch (Exception) { return null; }
    }

    static bool IsDirItem(string rel)
    {
        return rel == "pipeline" || rel == "unity"
            || rel == Path.Combine("assets", "third_party") || rel == Path.Combine("assets", "blender_patch");
    }

    // ディレクトリ項目は中の1ファイル(marker.txt)で内容を代表させる
    static string MarkerPathFor(string baseDir, string rel)
    {
        return IsDirItem(rel) ? Path.Combine(Path.Combine(baseDir, rel), "marker.txt") : Path.Combine(baseDir, rel);
    }

    // U50配布レイアウトのinstall_rootを模したツリーを作る。allowlist項目とユーザー
    // データ(work\/settings_lastvrm.txt/assets\tools\)の両方を用意する
    static void BuildFakeInstall(string root, string tag)
    {
        string internalDir = Path.Combine(root, "_internal");
        foreach (string rel in ApplyEngine.InternalAllowlistRelPaths)
            WriteText(MarkerPathFor(internalDir, rel), "OLD:" + rel + ":" + tag);
        foreach (string rel in ApplyEngine.RootAllowlistRelPaths)
            WriteText(Path.Combine(root, rel), "OLD:" + rel + ":" + tag);
        // ユーザーデータ(allowlist対象外。全ケースで不変であることを検査する)
        WriteText(Path.Combine(internalDir, "work", "dummy.txt"), "USER_WORK_DATA");
        WriteText(Path.Combine(internalDir, "settings_lastvrm.txt"), "USER_SETTINGS");
        WriteText(Path.Combine(internalDir, "assets", "tools", "fake_blender.txt"), "USER_BLENDER_CACHE");
    }

    static void BuildFakeStagingDist(string stagingDistRoot, string tag)
    {
        string internalDir = Path.Combine(stagingDistRoot, "_internal");
        foreach (string rel in ApplyEngine.InternalAllowlistRelPaths)
            WriteText(MarkerPathFor(internalDir, rel), "NEW:" + rel + ":" + tag);
        foreach (string rel in ApplyEngine.RootAllowlistRelPaths)
            WriteText(Path.Combine(stagingDistRoot, rel), "NEW:" + rel + ":" + tag);
    }

    static void AssertAllowlistContent(string root, string expectedPrefix, string tag,
        List<string> problems, string caseLabel)
    {
        string internalDir = Path.Combine(root, "_internal");
        foreach (string rel in ApplyEngine.InternalAllowlistRelPaths)
        {
            string expected = expectedPrefix + ":" + rel + ":" + tag;
            string actual = ReadTextOrNull(MarkerPathFor(internalDir, rel));
            if (actual != expected)
                problems.Add(caseLabel + ": allowlist mismatch at internal\\" + rel
                    + " expected=" + expected + " actual=" + (actual ?? "<missing>"));
        }
        foreach (string rel in ApplyEngine.RootAllowlistRelPaths)
        {
            string expected = expectedPrefix + ":" + rel + ":" + tag;
            string actual = ReadTextOrNull(Path.Combine(root, rel));
            if (actual != expected)
                problems.Add(caseLabel + ": allowlist mismatch at root\\" + rel
                    + " expected=" + expected + " actual=" + (actual ?? "<missing>"));
        }
    }

    // .update_backup\ / .failed_update\ のどちらも同じ internal\<rel> / root\<rel>
    // 構造なので、この1関数で両方を検査できる
    static void AssertBackupStyleContent(string backupDir, string expectedPrefix, string tag,
        List<string> problems, string caseLabel)
    {
        foreach (string rel in ApplyEngine.InternalAllowlistRelPaths)
        {
            string expected = expectedPrefix + ":" + rel + ":" + tag;
            string actual = ReadTextOrNull(MarkerPathFor(Path.Combine(backupDir, "internal"), rel));
            if (actual != expected)
                problems.Add(caseLabel + ": backup mismatch at internal\\" + rel
                    + " expected=" + expected + " actual=" + (actual ?? "<missing>"));
        }
        foreach (string rel in ApplyEngine.RootAllowlistRelPaths)
        {
            string expected = expectedPrefix + ":" + rel + ":" + tag;
            string actual = ReadTextOrNull(Path.Combine(backupDir, "root", rel));
            if (actual != expected)
                problems.Add(caseLabel + ": backup mismatch at root\\" + rel
                    + " expected=" + expected + " actual=" + (actual ?? "<missing>"));
        }
    }

    static void AssertUserDataIntact(string root, List<string> problems, string caseLabel)
    {
        string internalDir = Path.Combine(root, "_internal");
        CheckEq(Path.Combine(internalDir, "work", "dummy.txt"), "USER_WORK_DATA", problems, caseLabel);
        CheckEq(Path.Combine(internalDir, "settings_lastvrm.txt"), "USER_SETTINGS", problems, caseLabel);
        CheckEq(Path.Combine(internalDir, "assets", "tools", "fake_blender.txt"), "USER_BLENDER_CACHE",
            problems, caseLabel);
    }

    static void CheckEq(string path, string expected, List<string> problems, string caseLabel)
    {
        string actual = ReadTextOrNull(path);
        if (actual != expected)
            problems.Add(caseLabel + ": user data changed at " + path
                + " expected=" + expected + " actual=" + (actual ?? "<missing>"));
    }

    static void WritePendingNormal(string updateDir, string version, string fromVersion, string stagingInternalDir)
    {
        Directory.CreateDirectory(updateDir);
        string json = "{\n"
            + "  \"version\": \"" + version + "\",\n"
            + "  \"from_version\": \"" + fromVersion + "\",\n"
            + "  \"staged_at\": \"2026-07-30T00:00:00Z\",\n"
            + "  \"staging_internal_dir\": \"" + stagingInternalDir.Replace("\\", "\\\\") + "\"\n"
            + "}\n";
        File.WriteAllText(Path.Combine(updateDir, "pending.json"), json, new UTF8Encoding(false));
    }

    static void WritePendingRevert(string updateDir)
    {
        Directory.CreateDirectory(updateDir);
        string json = "{\n  \"revert\": true,\n  \"requested_at\": \"2026-07-30T00:00:00Z\"\n}\n";
        File.WriteAllText(Path.Combine(updateDir, "pending.json"), json, new UTF8Encoding(false));
    }

    // ---- case1: 正常適用 ----
    static void RunCase1NormalApply(string root, List<string> problems)
    {
        string caseLabel = "case1(normal apply)";
        BuildFakeInstall(root, "v1");
        string updateDir = Path.Combine(root, "_update");
        string stagingDistRoot = Path.Combine(updateDir, "staging", ApplyEngine.DistTopFolderName);
        BuildFakeStagingDist(stagingDistRoot, "v2");
        WritePendingNormal(updateDir, "2.0.0", "1.0.0", Path.Combine(stagingDistRoot, "_internal"));

        string notice;
        ApplyEngine.RunStartupStateMachine(root, out notice);

        AssertAllowlistContent(root, "NEW", "v2", problems, caseLabel);
        AssertUserDataIntact(root, problems, caseLabel);
        if (File.Exists(Path.Combine(updateDir, "pending.json")))
            problems.Add(caseLabel + ": pending.json should be removed after successful apply");
        string verifyPath = Path.Combine(updateDir, "verify_pending.json");
        if (!File.Exists(verifyPath))
            problems.Add(caseLabel + ": verify_pending.json should be written after successful apply");
        else if (MiniJson.GetString(File.ReadAllText(verifyPath, Encoding.UTF8), "version") != "2.0.0")
            problems.Add(caseLabel + ": verify_pending.json version mismatch");
        if (Directory.Exists(Path.Combine(updateDir, "staging")))
            problems.Add(caseLabel + ": staging dir should be cleaned up after successful apply");
        string backupDest = Path.Combine(root, "_internal", ApplyEngine.UpdateBackupDirName);
        if (!Directory.Exists(backupDest))
            problems.Add(caseLabel + ": .update_backup should exist after successful apply");
        else
            AssertBackupStyleContent(backupDest, "OLD", "v1", problems, caseLabel);
        if (!string.IsNullOrEmpty(notice))
            problems.Add(caseLabel + ": successful apply should be silent, got notice: " + notice);
    }

    // ---- case2: 途中失敗 -> 全か無かで復帰 ----
    static void RunCase2MidwayFailureRollback(string root, List<string> problems)
    {
        string caseLabel = "case2(midway failure -> rollback)";
        BuildFakeInstall(root, "v1");
        string stagingDistRoot = Path.Combine(root, "_stage_src", ApplyEngine.DistTopFolderName);
        BuildFakeStagingDist(stagingDistRoot, "v2");

        List<SwapItem> items = ApplyEngine.BuildItemsFromStagingDist(stagingDistRoot, root);
        string tmpBackup = Path.Combine(root, "_internal", ApplyEngine.UpdateBackupDirName + "_tmp");
        int appliedCount = 0;
        ApplyEngine.FaultHook fault = delegate (SwapItem item)
        {
            appliedCount++;
            if (appliedCount == 3) throw new Exception("injected fault for test (case2)");
        };
        string error;
        bool ok = ApplyEngine.ApplyItems(items, tmpBackup, fault, out error);
        if (ok) problems.Add(caseLabel + ": expected failure (fault injected) but ApplyItems reported success");
        if (string.IsNullOrEmpty(error)) problems.Add(caseLabel + ": error message should be set on failure");

        // 全か無か: すべてのallowlist項目が元(v1)のまま残っていること(=生きている側が
        // 中途半端な混在状態にならないことが保証すべき本質。staging側は元々使い捨ての
        // スクラッチ領域で、実運用でも成否に関わらずRunStartupStateMachineが必ず削除する
        // ため、途中まで移動された新版の断片がstaging側に残らなくても実害は無い)
        AssertAllowlistContent(root, "OLD", "v1", problems, caseLabel);
        AssertUserDataIntact(root, problems, caseLabel);

        ApplyEngine.SafeDeleteDir(tmpBackup);
    }

    // ---- case3: Tier1シグナル未達 -> 次回起動で自動復帰 ----
    static void RunCase3Tier1Rollback(string root, List<string> problems)
    {
        string caseLabel = "case3(Tier1 auto-rollback: signal not achieved)";
        BuildFakeInstall(root, "v1");
        string updateDir = Path.Combine(root, "_update");
        string stagingDistRoot = Path.Combine(updateDir, "staging", ApplyEngine.DistTopFolderName);
        BuildFakeStagingDist(stagingDistRoot, "v2");
        WritePendingNormal(updateDir, "2.0.0", "1.0.0", Path.Combine(stagingDistRoot, "_internal"));

        string notice1;
        ApplyEngine.RunStartupStateMachine(root, out notice1);   // 1回目: 適用成功、verify_pending.json残る
        string verifyPath = Path.Combine(updateDir, "verify_pending.json");
        if (!File.Exists(verifyPath))
        {
            problems.Add(caseLabel + ": setup failed, verify_pending.json missing after apply");
            return;
        }
        // 「画面が出る前に落ちた」を模して verify_pending.json を消さないまま次回起動を再現
        string notice2;
        ApplyEngine.RunStartupStateMachine(root, out notice2);   // 2回目: Tier1発動

        AssertAllowlistContent(root, "OLD", "v1", problems, caseLabel);   // 前バージョンへ自動復元
        AssertUserDataIntact(root, problems, caseLabel);
        if (File.Exists(verifyPath))
            problems.Add(caseLabel + ": verify_pending.json should be removed after Tier1 rollback");
        string failedDest = Path.Combine(root, "_internal", ApplyEngine.FailedUpdateDirName);
        if (!Directory.Exists(failedDest))
            problems.Add(caseLabel + ": .failed_update should retain the broken new version for diagnosis");
        else
            AssertBackupStyleContent(failedDest, "NEW", "v2", problems, caseLabel);
        if (string.IsNullOrEmpty(notice2) || notice2.IndexOf("戻しました", StringComparison.Ordinal) < 0)
            problems.Add(caseLabel + ": expected a rollback notice mentioning \"戻しました\", got: "
                + (notice2 ?? "<null>"));
    }

    // ---- case4: Tier1シグナル達成 -> 復帰しない ----
    static void RunCase4Tier1SignalAchieved(string root, List<string> problems)
    {
        string caseLabel = "case4(Tier1 signal achieved -> no rollback)";
        BuildFakeInstall(root, "v1");
        string updateDir = Path.Combine(root, "_update");
        string stagingDistRoot = Path.Combine(updateDir, "staging", ApplyEngine.DistTopFolderName);
        BuildFakeStagingDist(stagingDistRoot, "v2");
        WritePendingNormal(updateDir, "2.0.0", "1.0.0", Path.Combine(stagingDistRoot, "_internal"));

        string notice1;
        ApplyEngine.RunStartupStateMachine(root, out notice1);
        string verifyPath = Path.Combine(updateDir, "verify_pending.json");
        if (!File.Exists(verifyPath))
        {
            problems.Add(caseLabel + ": setup failed, verify_pending.json missing after apply");
            return;
        }
        // 新版の起動確認シグナル(app側MainForm.Shownでの削除、SelfUpdate.
        // ClearVerifyPendingSignal)を模す
        ApplyEngine.SafeDeleteFile(verifyPath);

        string notice2;
        ApplyEngine.RunStartupStateMachine(root, out notice2);   // 2回目: 何も起きないはず

        AssertAllowlistContent(root, "NEW", "v2", problems, caseLabel);   // 新版のまま(復帰しない)
        AssertUserDataIntact(root, problems, caseLabel);
        string backupDest = Path.Combine(root, "_internal", ApplyEngine.UpdateBackupDirName);
        if (!Directory.Exists(backupDest))
            problems.Add(caseLabel + ": .update_backup should remain available for future Tier2");
        else
            AssertBackupStyleContent(backupDest, "OLD", "v1", problems, caseLabel);
        if (Directory.Exists(Path.Combine(root, "_internal", ApplyEngine.FailedUpdateDirName)))
            problems.Add(caseLabel + ": .failed_update should NOT be created when no rollback happened");
        if (!string.IsNullOrEmpty(notice2))
            problems.Add(caseLabel + ": no-op startup should be silent, got notice: " + notice2);
    }

    // ---- case5: Tier2手動ロールバック ----
    static void RunCase5Tier2Revert(string root, List<string> problems)
    {
        string caseLabel = "case5(Tier2 manual revert)";
        BuildFakeInstall(root, "v1");
        string updateDir = Path.Combine(root, "_update");
        string stagingDistRoot = Path.Combine(updateDir, "staging", ApplyEngine.DistTopFolderName);
        BuildFakeStagingDist(stagingDistRoot, "v2");
        WritePendingNormal(updateDir, "2.0.0", "1.0.0", Path.Combine(stagingDistRoot, "_internal"));

        string noticeApply;
        ApplyEngine.RunStartupStateMachine(root, out noticeApply);   // v1 -> v2 適用
        string verifyPath = Path.Combine(updateDir, "verify_pending.json");
        ApplyEngine.SafeDeleteFile(verifyPath);   // 起動確認シグナル達成を模す(Tier1は無関係)

        WritePendingRevert(updateDir);
        string noticeRevert;
        ApplyEngine.RunStartupStateMachine(root, out noticeRevert);   // Tier2: v2 -> v1 へ手動復元

        AssertAllowlistContent(root, "OLD", "v1", problems, caseLabel);   // 前のバージョンに戻った
        AssertUserDataIntact(root, problems, caseLabel);
        if (File.Exists(Path.Combine(updateDir, "pending.json")))
            problems.Add(caseLabel + ": pending.json should be removed after Tier2 revert");
        string backupDest = Path.Combine(root, "_internal", ApplyEngine.UpdateBackupDirName);
        if (!Directory.Exists(backupDest))
            problems.Add(caseLabel + ": .update_backup should be re-created holding the reverted-away version");
        else
            AssertBackupStyleContent(backupDest, "NEW", "v2", problems, caseLabel);   // 戻す前のv2が新バックアップに
        if (string.IsNullOrEmpty(noticeRevert) || noticeRevert.IndexOf("戻しました", StringComparison.Ordinal) < 0)
            problems.Add(caseLabel + ": expected a revert notice mentioning \"戻しました\", got: "
                + (noticeRevert ?? "<null>"));
    }
}