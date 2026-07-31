# prefab指定 → Unityをヘッドレス起動してアバター一式を自動輸出する
# 使い方: pwsh -File export_from_unity.ps1 -Prefab "C:\...\Assets\...\avatar.prefab" [-Out <出力フォルダ>]
#         pwsh -File export_from_unity.ps1 -ResolveUnityOnly   # Unity発見だけ検証(診断用、dev#22)
# 出力: FBXコピー + humanoid.json + 実テクスチャPNG + material_map.json
# 対象: Unity 2022.3.x(VRChat想定)。プロジェクトを開いたままだと起動できない
#       (その場合はUnityのメニュー Tools > DiveToPalworld > Export Avatar で手動輸出)
param(
    [string]$Prefab = "",
    [string]$Out = "",
    [switch]$ResolveUnityOnly
)
$ErrorActionPreference = "Stop"
# 2026-07-26: 以前はこの設定が失敗しても空catchで無言で握りつぶしていた
# (pipeline\cli\convert.ps1で同じ形を解消したのと同じ処置)。失敗しても
# 輸出は続行する(方針どおり、挙動は変えない)が、成否と設定試行後の実値を
# 記録し、失敗時はWrite-Hostで理由を出す。Unity起動を伴うため実行検証は
# 未実施(構文解析のみで確認、報告書に明記)。
$__consoleEncodingOk = $true
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    $__consoleEncodingOk = $false
    Write-Host "[警告] [Console]::OutputEncodingの設定に失敗しました(エクスポートは続行します): $($_.Exception.Message)"
}
$__consoleEncodingActual = try { [Console]::OutputEncoding.WebName } catch { "(取得失敗)" }
Write-Host ("Console.OutputEncoding(設定試行後の実値): $__consoleEncodingActual / 設定成功=$__consoleEncodingOk")

# ---------------------------------------------------------------------------
# Unityエディタの解決(dev#22: 「Unity 2022.3インストール済みなのに見つからない」対策)
#
# 探索ロジックの正本は pipeline\py\dep_resolver.py(外部依存の共通resolver。
# dev#23設計確定)。**本ps1は探索を一切実装しない殻**であり、Pythonで
# dep_resolver.py を呼んでマーカー "D2P_RESOLVED: " / "D2P_RESOLVE_FAILED" を
# 読むだけ(dev#21の方針: ps1に新しいロジックを書かない。PS5.1互換地雷のため。
# 当初ここに置いたPowerShell版の鏡実装は、検証でJoin-PathのDriveNotFound即死・
# Get-Contentの既定CP932誤読など地雷3件が実証され、撤去した — work\wp_resolver\VERIFY.md)。
#
# 優先順位・戦略(手動指定 settings_unityeditor.txt / D2P_UNITY_EDITOR →
# UnityHub台帳 → 既知パス、2022.3.xの範囲一致)は全て dep_resolver.py 側を参照。
# 探索した全候補と判定はresolverがtrailとして出力し、そのまま画面(=GUIのログ
# ボックス)へ流れる。
#
# Pythonは通常必ず存在する: GUIは起動直後の EnsureBlenderReadyOnStartup() で
# Blender同梱Pythonを取得済みにしてからでないとprefab投入に到達しない。
# Pythonが見つからない=Blenderセットアップ未完了の縮退状態(変換自体が不可能)
# なので、探索せず静的な案内を出して止める。
# 環境変数 D2P_RESOLVER_NO_PYTHON=1 でその縮退経路を強制できる(試験用)。
# ---------------------------------------------------------------------------
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$UnitySettingsFile = Join-Path $Root "settings_unityeditor.txt"

# このツールが検証済みなのはUnity 2022.3.x系のみ(根拠は下の対応バージョン確認の
# コメント参照)。resolverの範囲一致もこの系列で行う。
$SupportedFamily = "2022.3"

function Find-D2PPython {
    # Blender同梱Python(配布: assets\tools\、開発: tools\)→ システムpython の順。
    # WindowsApps直下のpython.exeはMicrosoft Storeへ誘導するスタブなので除外する。
    foreach ($pat in @("assets\tools\*\*\python\bin\python.exe",
                       "tools\*\*\python\bin\python.exe")) {
        $hit = Get-ChildItem (Join-Path $Root $pat) -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch "WindowsApps")) { return $cmd.Source }
    return $null
}

# dev#7: 診断ログへUnityプロジェクトパス・Unityインストール先の生フルパスを無加工で
# 出していた穴の修正(TRIAGE指摘: 本ファイルはマスク処理ゼロ。実ユーザー報告4AL4M4GTで
# 実証)。伏字化ロジック本体は pipeline\py\path_privacy.py に置き(dev#21の方針:
# 探索・変換ロジックをPS側に再実装しない。上のFind-D2PPython/Resolve-D2PUnityEditorと
# 同じ「殻」の考え方)、ここでは1回呼ぶだけ。呼び出しに失敗した場合(python不在等)は
# ファイル名のみを返す安全側のフォールバックへ倒す(生パスは絶対に出さない)。
$script:D2PPythonForDiag = $null
$script:D2PPythonForDiagResolved = $false
function Format-DiagPath([string]$P) {
    if (-not $P) { return $P }
    if (-not $script:D2PPythonForDiagResolved) {
        $script:D2PPythonForDiag = Find-D2PPython
        $script:D2PPythonForDiagResolved = $true
    }
    if ($script:D2PPythonForDiag) {
        try {
            $privacyPy = Join-Path $Root "pipeline\py\path_privacy.py"
            if (Test-Path $privacyPy -PathType Leaf) {
                # EAP=Stopのままだとネイティブコマンドのstderr出力で即死しうる(既知事象、
                # Resolve-D2PUnityEditorと同じ回避)
                $prevEAP = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                $argsList = @($privacyPy, "factify", $P, "--base", $Root)
                $out = & $script:D2PPythonForDiag @argsList 2>$null
                $code = $LASTEXITCODE
                $ErrorActionPreference = $prevEAP
                if ($code -eq 0 -and $out) { return (@($out) | Select-Object -Last 1) }
            }
        } catch {}
    }
    $name = $null
    try { $name = Split-Path $P -Leaf } catch {}
    if (-not $name) { $name = "(masked)" }
    return "$name (path masked; python resolver unavailable for facts)"
}

function Resolve-D2PUnityEditor([string]$ProjectVersion, [string]$Family) {
    # 返り値: Unity.exeのフルパス。見つからなければ $null(trail+案内は出力済み)。
    if ($env:D2P_RESOLVER_NO_PYTHON -ne "1") {
        $py = Find-D2PPython
        if ($py) {
            $resolverPy = Join-Path $Root "pipeline\py\dep_resolver.py"
            if (Test-Path $resolverPy -PathType Leaf) {
                Write-Host "依存解決: pipeline\py\dep_resolver.py を使用 (python: $py)"
                # EAP=Stopのままだとネイティブコマンドのstderr出力で即死しうる(convert.ps1の既知事象)
                $prevEAP = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                $prevIO = $env:PYTHONIOENCODING; $prevU8 = $env:PYTHONUTF8
                $env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"
                $argsList = @($resolverPy, "unity_editor", "--approot", $Root)
                if ($ProjectVersion) { $argsList += @("--project-version", $ProjectVersion) }
                $out = & $py @argsList 2>&1 | ForEach-Object { "$_" }
                $code = $LASTEXITCODE
                $env:PYTHONIOENCODING = $prevIO; $env:PYTHONUTF8 = $prevU8
                $ErrorActionPreference = $prevEAP
                foreach ($line in $out) { Write-Host $line }
                if ($code -eq 0) {
                    $hit = $out | Where-Object { $_ -like "D2P_RESOLVED: *" } | Select-Object -Last 1
                    if ($hit) { return $hit.Substring("D2P_RESOLVED: ".Length).Trim() }
                }
                if ($out -match "D2P_RESOLVE_FAILED") {
                    return $null  # trail+手動指定案内はresolverが出力済み
                }
                Write-Host "dep_resolver.py did not produce a result (exit=$code)."
            }
        }
    }
    # ここに来る=Pythonが1つも無い(またはresolverが起動すらできない)。
    # これはBlenderセットアップ未完了の縮退状態で、この先の変換も一切できないため、
    # 探索のPowerShell再実装はせず(dev#21)、静的な案内だけ出して止める。
    Write-Host ""
    Write-Host "[dep_resolver] ERROR: could not run the Python resolver (pipeline\py\dep_resolver.py)."
    Write-Host "[dep_resolver] No usable Python was found (searched: $Root\assets\tools, $Root\tools, system PATH), or it failed to start."
    Write-Host "Blenderの初回セットアップがまだ完了していないため、Unityの探索を実行できません。"
    Write-Host "先にDiveToPalworldアプリを起動してBlenderの初回セットアップ(自動ダウンロード)を"
    Write-Host "完了させてから、もう一度お試しください(セットアップ後はこの探索も変換も動きます)。"
    Write-Host "それでも解決しない場合は、次のファイルにお使いの Unity.exe のフルパスを1行だけ"
    Write-Host "書いて保存すると、手動指定として最優先で使われます:"
    Write-Host "  $UnitySettingsFile"
    Write-Host "書き方の例: C:\Program Files\Unity\Hub\Editor\2022.3.22f1\Editor\Unity.exe"
    return $null
}

if ($ResolveUnityOnly) {
    # 診断モード(dev#22): prefab不要でUnity発見だけを検証する(サポート・試験用)。
    $found = Resolve-D2PUnityEditor -ProjectVersion "" -Family $SupportedFamily
    if ($found) {
        Write-Host "Unity: $(Format-DiagPath $found)"
        exit 0
    }
    Write-Error "Unityエディタが見つかりませんでした(上記の探索結果と案内を確認してください) [D2P_UNITY_NOT_FOUND]"
    exit 1
}
if (-not $Prefab) {
    Write-Error "prefabファイルを指定してください(使い方: -Prefab `"C:\...\Assets\...\avatar.prefab`")"
    exit 1
}

# 2026-07-26: .Path はUNCパス(\\server\share\...)に対して
# "Microsoft.PowerShell.Core\FileSystem::\\server\share\..." というプロバイダ修飾形を返し、
# 後段のJoin-Path等で壊れたパスになる(大崎商会PCでの`ReadAllBytes`失敗の実因)。
# .ProviderPath はプロバイダ接頭辞なしの素のファイルシステムパスを返すのでこちらを使う。
$Prefab = (Resolve-Path $Prefab).ProviderPath
if (-not $Prefab.ToLower().EndsWith(".prefab")) { Write-Error "prefabファイルを指定してください"; exit 1 }

# 1) prefabパスからUnityプロジェクトルートを逆算(Assets/ の親)
$dir = Split-Path $Prefab -Parent
$proj = $null
while ($dir) {
    if ((Split-Path $dir -Leaf) -eq "Assets") { $proj = Split-Path $dir -Parent; break }
    $parent = Split-Path $dir -Parent
    if ($parent -eq $dir) { break }
    $dir = $parent
}
if (-not $proj -or -not (Test-Path (Join-Path $proj "ProjectSettings\ProjectVersion.txt"))) {
    Write-Error "Unityプロジェクトが特定できない(prefabはAssets配下にありますか?)"; exit 1
}
$assetRel = $Prefab.Substring($proj.Length + 1).Replace("\", "/")
# dev#7: $proj(Unityプロジェクトルート)はユーザーが既に知っている場所への案内では
# なく純粋な診断表示のため伏字化する。$assetRel はプロジェクト相対パスで個人フォルダ名を
# 含まないためそのまま出す(既存どおり)。
Write-Host "プロジェクト: $(Format-DiagPath $proj)"
Write-Host "アセット: $assetRel"

# 2) プロジェクトのUnityバージョンが対応系列(2022.3.x)かを確認してから、エディタを探す
$verLine = (Get-Content (Join-Path $proj "ProjectSettings\ProjectVersion.txt") | Select-String "m_EditorVersion:").Line
$projVer = ($verLine -split "\s+")[1]
$family = ($projVer -split "\.")[0..1] -join "."

# 2026-07-26: 対応外バージョンでも今までは検出さえできればそのまま先へ進み、
# 後段の無関係な場所(manifest.json操作やUnity起動後)で意味不明なエラーになっていた
# (大崎商会PCでUnity 2019.4.31f1のプロジェクトを渡した実例)。
# このツールが検証済みなのはUnity 2022.3.x系のみ:
#   - このスクリプト冒頭のコメント「対象: Unity 2022.3.x(VRChat想定)」
#   - manual\manual.md「自分のアバターのUnityProjectを開きます(Unity 2022.3.22f1で動作します)」
#   - tests\coverage\README.md「検体4体(いずれも Unity 2022.3.22f1、MA + NDMF 導入済み)」
# のいずれも2022.3.22f1を前提にしている。古い/新しい問わずそれ以外は動作未検証であり、
# 「警告だけ出して通す」ことは今回のような分かりにくい失敗を将来また生むため、
# ここで理由と対処法を示して確実に止める。($SupportedFamilyの定義は冒頭のresolver節)
if ($family -ne $SupportedFamily) {
    $msg = @"
対応していないUnityバージョンのプロジェクトです。

このツールが対応しているUnity: $SupportedFamily 系(例: 2022.3.22f1)
検出されたプロジェクトのUnity: $projVer
プロジェクト: $(Format-DiagPath $proj)

どうすればよいですか:
  1. お使いのアバターのプロジェクトを、VRChat向けの Unity $SupportedFamily 系で開き直してください
     (VRChat Creator Companion(VCC)で対象プロジェクトのUnityバージョンを変更する、
      または $SupportedFamily 系の新規プロジェクトを作ってアバター一式を移行してください)
  2. 開き直した後のプロジェクト内のprefabを指定して、このコマンドをもう一度実行してください
"@
    Write-Error $msg
    exit 1
}

# dev#22: 旧実装(C:\Program Files\Unity\Hub\Editor 決め打ち+ディレクトリ名走査のみ)は
# Hubのインストール先変更・別ドライブ・Hub非経由に不可視だった。共通resolver
# (冒頭のresolver節。正本 pipeline\py\dep_resolver.py)で解決する。
$editor = Resolve-D2PUnityEditor -ProjectVersion $projVer -Family $SupportedFamily
if (-not $editor -or -not (Test-Path $editor)) {
    Write-Error ("プロジェクトに合うUnity($projVer / $SupportedFamily 系)が見つかりませんでした。`n" +
        "上記の探索結果(trail)と手動指定の案内を確認してください。 [D2P_UNITY_NOT_FOUND]")
    exit 1
}
Write-Host "Unity: $(Format-DiagPath $editor) (project=$projVer)"

# 3) プロジェクトが開かれていないか(二重起動はUnityが禁止)
$lock = Join-Path $proj "Temp\UnityLockfile"
if (Test-Path $lock) {
    try {
        $fs = [IO.File]::Open($lock, "Open", "ReadWrite", "None"); $fs.Close()
    } catch {
        Write-Error ("このプロジェクトはUnityで開かれています。Unityを閉じてから再実行するか、`n" +
            "Unityのメニュー Tools > DiveToPalworld > Export Avatar で手動エクスポートしてください")
        exit 1
    }
}

# 3.5) 統合FBX書き出しに必須のFBX Exporterが無ければmanifestへ追記(次回起動時にDL)
#      manifest.json / packages-lock.json は実行前に退避し、finally で必ずバイト単位で復元する
$manifestPath = Join-Path $proj "Packages\manifest.json"
$lockPath = Join-Path $proj "Packages\packages-lock.json"
$manifestBackupBytes = [IO.File]::ReadAllBytes($manifestPath)
$lockBackupBytes = $null
if (Test-Path $lockPath) { $lockBackupBytes = [IO.File]::ReadAllBytes($lockPath) }
$manifestModified = $false

# manifest.jsonはUTF-8(Unity/VCCが書く)。PS5.1の既定(ANSI/cp932)で誤読したまま
# 下でSet-Content -Encoding utf8で書き戻すと、非ASCII(ローカルパッケージのfile:パス等)を
# 含むmanifestを破壊する。読取は必ずUTF-8明示(起票案1と同族の入口正規化)
$mj = Get-Content $manifestPath -Raw -Encoding UTF8
if ($mj -notmatch '"com\.unity\.formats\.fbx"') {
    # JSONラウンドトリップ(ConvertFrom-Json/ConvertTo-Json)はファイル全体の整形を壊すため、
    # "dependencies": { の直後に1行差し込むだけの最小限のテキスト編集にする
    $insertion = "`"com.unity.formats.fbx`": `"4.2.1`","
    $newMj = [System.Text.RegularExpressions.Regex]::Replace(
        $mj,
        '("dependencies"\s*:\s*\{)',
        { param($m) $m.Groups[1].Value + "`n    " + $insertion },
        1
    )
    if ($newMj -eq $mj) {
        Write-Error "manifest.jsonの`"dependencies`"セクションが見つからず、FBX Exporterを追記できません"
        exit 1
    }
    Set-Content -Path $manifestPath -Value $newMj -Encoding utf8 -NoNewline
    $manifestModified = $true
    Write-Host "FBX Exporter(com.unity.formats.fbx 4.2.1)をmanifest.jsonへ追記しました(初回はDLで時間がかかります)"
}

# 4) エクスポータを注入(冪等)して、ヘッドレスで実行
#    専用サブフォルダに置くことで、実行後にフォルダごと確実に消せる(ユーザーの同名ファイル上書き事故も防ぐ)
# ($Rootは冒頭のresolver節で定義済み)
$editorDir = Join-Path $proj "Assets\Editor"
$editorDirPreexisting = Test-Path $editorDir
$exporterDir = Join-Path $editorDir "D2P_TempExporter"
$exporterCs = Join-Path $exporterDir "DiveToPalworldExporter.cs"

try {
    New-Item -ItemType Directory -Force $exporterDir | Out-Null
    Copy-Item (Join-Path $Root "unity\DiveToPalworldExporter.cs") $exporterCs -Force
    if (-not $Out) {
        $name = [IO.Path]::GetFileNameWithoutExtension($Prefab)
        $Out = Join-Path $Root "work\${name}_export"
    }
    New-Item -ItemType Directory -Force $Out | Out-Null
    $log = Join-Path $Out "unity_export.log"
    Write-Host "Unityをヘッドレス起動中(初回はインポートで数分かかります)..."
    & $editor -batchmode -projectPath $proj -executeMethod DiveToPalworldExporter.ExportBatch `
        -vrm2palPrefab $assetRel -vrm2palOut $Out -quit -logFile $log | Out-Null
    $done = Select-String -Path $log -Pattern "D2P_EXPORT_DONE" -Quiet
    if (-not $done) {
        # dev#235: 旧実装は先に Write-Error を呼んでいたため、冒頭の
        # $ErrorActionPreference = "Stop" によりWrite-Errorがその場でスクリプトを
        # 終了させ、直後の抜粋処理(旧: 次行のSelect-String)が実行されない
        # 死にコードになっていた(pwsh実験で実測確認: Write-Error後の行は
        # 到達不能。GUIが実際に見ていた要点はC#側 ExtractUnityExportLogHighlights
        # がunity_export.logを独立に再走査した結果だった)。
        # さらに旧パターンはマッチ行そのものだけを最大5件抜き出す実装で、
        # 例外メッセージの直後に続くUnityのスタックトレース行
        # ("... (at Assets/...:NN)" 等、"Exception"という文字列を含まない)を
        # 一切拾えていなかった(dev#150: convert.ps1側の同型欠陥と同一パターン)。
        # 抜粋は必ずWrite-Errorより前に、Write-Host(標準出力)で確実に出す。
        # dev#262: 「輸出」表記は「エクスポート」に統一する(2026-07-30)。
        Write-Host "エクスポート失敗 — ログ参照: $log"
        Write-Host "--- 失敗箇所の抜粋(前後文脈つき。全文は上記ログファイル) ---"
        $excerpt = Select-String -Path $log -Pattern "Exception|error CS" -Context 0,15 |
            Select-Object -First 5
        if ($excerpt) {
            foreach ($m in $excerpt) { Write-Host $m.ToString() }
        } else {
            Write-Host "(Exception / error CS を含む行が見つかりませんでした。ログ全文を確認してください)"
        }
        Write-Host "--- 抜粋ここまで ---"
        Write-Error "エクスポート失敗(詳細は上記抜粋とログファイルを参照)"
        exit 1
    }
    Write-Host ""
    Write-Host "エクスポート完了: $Out"
    Get-ChildItem $Out | Select-Object Name, Length | Format-Table -AutoSize
    Write-Host "この中のFBXをDiveToPalworldへD&Dしてください"
}
finally {
    # プロジェクトへの痕跡を必ず消す(Unityが失敗・タイムアウト・例外いずれでもここを通る)
    Remove-Item (Join-Path $exporterDir "DiveToPalworldExporter.cs.meta") -Force -ErrorAction SilentlyContinue
    Remove-Item $exporterCs -Force -ErrorAction SilentlyContinue
    Remove-Item $exporterDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item ($exporterDir + ".meta") -Force -ErrorAction SilentlyContinue
    if (-not $editorDirPreexisting -and (Test-Path $editorDir)) {
        $remaining = Get-ChildItem $editorDir -Force -ErrorAction SilentlyContinue
        if (-not $remaining) {
            Remove-Item $editorDir -Force -ErrorAction SilentlyContinue
            Remove-Item ($editorDir + ".meta") -Force -ErrorAction SilentlyContinue
        }
    }

    # manifest.json / packages-lock.json をバイト単位で復元(片方だけ戻すと不整合になるため両方)
    if ($manifestModified) {
        [IO.File]::WriteAllBytes($manifestPath, $manifestBackupBytes)
        if ($null -ne $lockBackupBytes) {
            [IO.File]::WriteAllBytes($lockPath, $lockBackupBytes)
        } elseif (Test-Path $lockPath) {
            Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
        }
    }
}
