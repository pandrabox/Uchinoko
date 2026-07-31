# 収集VRMの一括スモークテスト(プレビューまで)
# 使い方:
#   pwsh -File pipeline\cli\smoke_all.ps1                    # test\vrm\collected を全部
#   pwsh -File pipeline\cli\smoke_all.ps1 -VrmDir <フォルダ> # 任意フォルダ
# 出力: test\smoke_report\report.md(結果表)+ 各プレビューPNGのギャラリー
# 寝る前に回す想定。1体あたり2〜4分、失敗しても止まらず次へ進む
param(
    [string]$VrmDir = "",
    [switch]$Full   # 指定するとプレビューだけでなくフル変換まで回す(通常は使わない)
)
$ErrorActionPreference = "Continue"
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$Here = $PSScriptRoot
$Root = Split-Path (Split-Path $Here -Parent) -Parent
if (-not $VrmDir) { $VrmDir = Join-Path $Root "test\vrm\collected" }
if (-not (Test-Path $VrmDir)) { Write-Error "VRMフォルダが無い: $VrmDir"; exit 1 }

$ReportDir = Join-Path $Root "test\smoke_report"
New-Item -ItemType Directory -Force $ReportDir | Out-Null
$Report = Join-Path $ReportDir "report.md"

# パス類はGUIと同じ規約で自動解決
$Blender = @(
    (Get-ChildItem (Join-Path $Root "tools\blender-*-windows-x64\blender.exe") -ErrorAction SilentlyContinue | Select-Object -First 1).FullName,
    "C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$AddonZip = (Get-ChildItem (Join-Path $Root "third_party\VRM_Addon_for_Blender-Extension*.zip") | Select-Object -First 1).FullName

$vrms = Get-ChildItem $VrmDir -Filter "*.vrm" | Sort-Object Name
"# DiveToPalworld 一括スモーク結果`n" | Set-Content $Report -Encoding utf8
"実行日時: $(Get-Date -Format 'yyyy-MM-dd HH:mm') / 対象: $($vrms.Count)体 / モード: $(if ($Full) {'フル変換'} else {'プレビューのみ'})`n" | Add-Content $Report -Encoding utf8
"| # | VRM | 結果 | 時間 | メモ |" | Add-Content $Report -Encoding utf8
"|---|---|---|---|---|" | Add-Content $Report -Encoding utf8

$i = 0
$okCount = 0
foreach ($vrm in $vrms) {
    $i++
    $name = "smoke_" + ($vrm.BaseName -replace '[^A-Za-z0-9]', '')
    if ($name -eq "smoke_") { $name = "smoke_vrm$i" }
    $jobDir = Join-Path $Root "work\$name"
    New-Item -ItemType Directory -Force $jobDir | Out-Null
    $jobJson = Join-Path $jobDir "job.json"
    # スモークは規約確認済み扱い(テスト目的のローカル変換のみ。配布はしない)
    @{
        vrm_path = $vrm.FullName
        avatar_name = $name
        shoulder_offset_deg = 0
        merge_fingers = $false
        unlit = $false
        shadow_lift = 0
        drop_bones = @()
        license_confirmed = $true
        paths = @{
            blender_exe = $Blender
            vrm_addon_zip = $AddonZip
        }
    } | ConvertTo-Json -Depth 5 | Set-Content $jobJson -Encoding utf8

    Write-Host "=== [$i/$($vrms.Count)] $($vrm.Name) ==="
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $mode = if ($Full) { @() } else { @("-PreviewOnly") }
    & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Here "convert.ps1") -Job $jobJson @mode *> (Join-Path $jobDir "smoke_log.txt")
    $exit = $LASTEXITCODE
    $sw.Stop()
    $elapsed = "{0:mm\:ss}" -f $sw.Elapsed

    $note = ""
    if ($exit -eq 0) {
        $okCount++
        $result = "✅ OK"
        # プレビューをギャラリーへコピー
        $prev = Join-Path $jobDir "converted\preview_male_stand.png"
        if (Test-Path $prev) { Copy-Item $prev (Join-Path $ReportDir "$name.png") -Force }
        # 警告を拾う
        $meta = Join-Path $jobDir "converted\avatar_meta.json"
        if (Test-Path $meta) {
            $m = Get-Content $meta -Raw -Encoding utf8 | ConvertFrom-Json
            if ($m.warnings.Count -gt 0) { $note = ($m.warnings -join " / ") -replace '\|', '/' }
        }
    } else {
        $result = "❌ FAIL(exit=$exit)"
        # 失敗の手がかり(ログ末尾のFATAL/Error行)
        $tail = Get-Content (Join-Path $jobDir "smoke_log.txt") -Encoding utf8 -ErrorAction SilentlyContinue |
            Select-String "FATAL|Error" | Select-Object -Last 2
        if ($tail) { $note = (($tail | ForEach-Object { $_.Line.Trim() }) -join " / ") -replace '\|', '/' }
    }
    "| $i | $($vrm.Name) | $result | $elapsed | $note |" | Add-Content $Report -Encoding utf8
}

"`n合計: $okCount / $($vrms.Count) OK。プレビュー画像は本フォルダの *.png(目視ギャラリー)" | Add-Content $Report -Encoding utf8
Write-Host ""
Write-Host "=== スモーク完了: $okCount / $($vrms.Count) OK ==="
Write-Host "レポート: $Report"
