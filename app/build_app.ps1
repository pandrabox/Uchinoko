# GUIのビルド(Windows同梱の.NET Framework 4.8 csc.exeを使用、追加SDK不要)
# 出力: リポジトリ直下の Uchinoko.exe(v2.0.0改名。ソース・内部名はDiveToPalworldのまま)
param([string]$Out = "")  # 省略時はリポジトリ直下。梱包時はステージング先を指定
$ErrorActionPreference = "Stop"
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { Write-Error "csc.exeが無い(.NET Framework 4.8必須)"; exit 1 }
$here = $PSScriptRoot
$out = if ($Out) { $Out } else { Join-Path (Split-Path $here -Parent) "Uchinoko.exe" }
# 2026-07-29: favicon.ico(128/48/16のみ、32が抜けている)ではWindowsが32px表示箇所
# (エクスプローラー中アイコン等)で誤った拡大縮小をしうるため、ico\の各PNGから
# 16/32/48/128/256を作った ico\app.ico(work\wp_icon\build_ico.py生成)を使う。
# 無ければ従来のfavicon.icoへフォールバックする
$icon = Join-Path (Split-Path $here -Parent) "ico\app.ico"
if (-not (Test-Path $icon)) { $icon = Join-Path (Split-Path $here -Parent) "ico\favicon.ico" }
$iconArg = if (Test-Path $icon) { "/win32icon:$icon" } else { "" }

# dev#523(2026-08-01): アプリケーションマニフェスト(requestedExecutionLevel=asInvoker)
# の埋め込み。無地exeの外形改善(AV誤検知対策)の一環。app\app.manifest を
# csc.exeの/win32manifest:で直接埋め込む(挙動は変えない。既定のasInvokerを
# 明示するだけ)。ファイルが無い場合はエラーで停止する(無ければ黙って
# マニフェスト無しビルドに戻ってしまうと、外形改善の主目的が静かに欠落する)。
$manifest = Join-Path $here "app.manifest"
if (-not (Test-Path $manifest)) { Write-Error "app\app.manifest が無い(dev#523のマニフェスト埋め込みに必須)"; exit 1 }
$manifestArg = "/win32manifest:$manifest"

$srcPath = Join-Path $here "DiveToPalworld.cs"
$compileSrc = $srcPath
$src = Get-Content $srcPath -Raw

# 2026-07-27: 問い合わせ用メールアドレスをリポジトリに一切含めないための差し込み。
# app\DiveToPalworld.cs の SupportEmail は空文字のプレースホルダとして追跡されている
# (Pub=公開GitHub側にそのまま同期される)。実アドレスは devtools\support_contact.txt
# (非公開。devtools\自体がPub非同期)にだけ書いてあり、ここでコンパイル直前に
# メモリ上でのみ差し替えた一時コピーを作ってそれをコンパイルする。私有ファイルが
# 無い場合(Pubを直接cloneして自前ビルドする第三者など)は何もせず元のまま
# (=空文字、GitHub Issuesのみの案内)でビルドする。
$contactFile = Join-Path (Split-Path $here -Parent) "devtools\support_contact.txt"
if (Test-Path $contactFile) {
    $email = (Get-Content $contactFile -Raw).Trim()
    $marker = 'const string SupportEmail = "";'
    if ($src -notlike "*$marker*") {
        Write-Error "SupportEmailプレースホルダがDiveToPalworld.cs内に見つからない(文言がズレた?): $marker"
        exit 1
    }
    $patched = $src.Replace($marker, 'const string SupportEmail = "' + $email + '";')
    $compileSrc = Join-Path ([System.IO.Path]::GetTempPath()) ("D2P_build_" + [guid]::NewGuid().ToString("N") + ".cs")
    # csc.exeはBOMが無いソースをANSIコードページとして読むため日本語が化ける(make_dist.ps1と同じ対策)
    [System.IO.File]::WriteAllText($compileSrc, $patched, (New-Object System.Text.UTF8Encoding($true)))
    Write-Host "問い合わせ先メールを差し込んでビルドします(devtools\support_contact.txt)"
} else {
    Write-Host "devtools\support_contact.txt が無いため、問い合わせ先メールは空のままビルドします"
}

# 2026-07-31: アセンブリメタデータ(AssemblyTitle/Product/Company/
# Version/FileVersion/Copyright/Description)の付与。バージョン番号はハードコード
# せず、DiveToPalworld.cs の ToolVersion 定数(既存のバージョン管理の唯一の正)から
# 取る。app\AssemblyInfo.cs のプレースホルダ("0.0.0.0")をここで実バージョンへ
# 置換した一時コピーを作り、DiveToPalworld.cs(またはパッチ済み一時コピー)と
# 一緒にコンパイルする(SupportEmail差し込みと同じ「一時コピーに置換して
# コンパイル、原本は変更しない」手口)。
$versionMatch = [regex]::Match($src, 'const\s+string\s+ToolVersion\s*=\s*"v?([^"]+)"')
if (-not $versionMatch.Success) {
    Write-Error "DiveToPalworld.cs内にToolVersion定数が見つからない(アセンブリバージョンを決定できない)"
    exit 1
}
$assemblyVersion = $versionMatch.Groups[1].Value
$assemblyInfoPath = Join-Path $here "AssemblyInfo.cs"
$assemblyInfoSrc = Get-Content $assemblyInfoPath -Raw
$versionPlaceholder = '0.0.0.0'
if ($assemblyInfoSrc -notlike "*$versionPlaceholder*") {
    Write-Error "AssemblyInfo.cs内にバージョンプレースホルダ($versionPlaceholder)が見つからない"
    exit 1
}
$patchedAssemblyInfo = $assemblyInfoSrc.Replace($versionPlaceholder, $assemblyVersion)
$compileAssemblyInfo = Join-Path ([System.IO.Path]::GetTempPath()) ("D2P_asmversion_" + [guid]::NewGuid().ToString("N") + ".cs")
[System.IO.File]::WriteAllText($compileAssemblyInfo, $patchedAssemblyInfo, (New-Object System.Text.UTF8Encoding($true)))

# FIX38(2026-07-31): dev#216 WP1で追加していたSystem.IO.Compression.dll/
# System.IO.Compression.FileSystem.dllの参照(自己更新のstaging展開、
# ZipFile.ExtractToDirectory用)は、ダウンロード経路自体の削除でDiveToPalworld.cs側の
# 呼び出しが無くなったため外した。System.dllにあるGZipStream/DeflateStream
# (既存のログ圧縮送信で使用)は元々この2つの追加参照とは無関係で影響なし。
& $csc /nologo /target:winexe /out:$out /optimize+ $iconArg $manifestArg `
    /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll `
    $compileSrc $compileAssemblyInfo
$buildExit = $LASTEXITCODE
if ($compileSrc -ne $srcPath) { Remove-Item $compileSrc -Force -ErrorAction SilentlyContinue }
Remove-Item $compileAssemblyInfo -Force -ErrorAction SilentlyContinue
if ($buildExit -ne 0) { Write-Error "コンパイル失敗"; exit 1 }
Write-Host "built: $out (version=$assemblyVersion)"
