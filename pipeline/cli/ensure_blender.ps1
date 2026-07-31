# ensure_blender.ps1 — Blenderポータブル(4.3.2 windows-x64)の取得・展開・後処理。
#
# 背景(u54 Blender同梱廃止): 配布zipの約9割がBlenderポータブル(非圧縮989MB)で
# あり、BOOTH容量・ビルド時間の主因だった。配布zipからBlender本体を外し、
# 初回起動時にこのスクリプトが公式サイト(download.blender.org)から取得する。
# 従来 build\make_dist.ps1 がビルド時にやっていた差し込み(ooz.pyd / pyooz
# dist-info / python3.dll をBlender同梱Pythonへ、VC++ランタイム3本を
# blender.crt\からpython\bin\とsite-packages\へ)は、この取得のタイミングへ
# 移した(この時点でしか「ダウンロードしたばかりのBlender」の実体がないため)。
#
# GUI(app\DiveToPalworld.cs)とCUI(pipeline\cli\convert.ps1)の両方が共用する。
# PowerShellエディション: convert.ps1と同じくWindows PowerShell 5.1互換で書く
# (配布物の実行環境はpwshが無い場合がありconvert.ps1がpowershell.exeへ
#  フォールバックするため。三項演算子・null合体演算子等のPS7専用構文は使わない)。
#
# 使い方:
#   powershell -File ensure_blender.ps1 -AppRoot <配布ルート(_internal相当)>
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -SourceZip <path>  # オフライン/試験用、DLしない
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -Force            # 既存があっても再取得
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -DownloadUrlOverride <url>
#       # 試験専用: 公式サイトの取得URLを差し替える(無効URL注入によるfail-closed確認用。
#       # tests\shipcheck\dist_smoke.py の負の対照(a)が使う。通常運用では指定しない)
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -MirrorUrlOverride <url>
#       # 試験専用: R2ミラーの取得URLを差し替える(dev#62、フォールバック経路の
#       # 単体テスト用にローカルHTTPサーバ等を指せるようにする。通常運用では指定しない)
#   powershell -File ensure_blender.ps1 -AppRoot <dir> -CheckOnly
#       # dev#230: Test-D2PMarkerValid(exe実在+マーカー実在+version/sha256/patched一致)
#       # だけを判定して即終了する(ダウンロード・展開・進捗表示は一切しない)。
#       # 呼び出し元(app\DiveToPalworld.cs / convert.ps1)が「exeが既にあるから
#       # マーカー検証を丸ごとスキップする」という死んだ修復ロジックに戻らないよう、
#       # 判定基準をこのスクリプト側に一元化するための軽量経路。終了コード0=有効、
#       # 非0=無効(exe欠落/マーカー欠落/不正/世代不一致のいずれか。理由の詳細は
#       # 返さない――呼び出し元は無効ならフル実行[-CheckOnly無し]へフォールバック
#       # すればよく、理由分岐は不要なため)
#
# dev#62(取得元フォールバック): 公式サイト(download.blender.org)への直DLが
# 一部地域でHTTP 403等になる実報告(ZC87VNQX)を受け、公式サイト取得が失敗した
# 場合のみ自動的にR2ミラー(dl.osakishokai.com、既存のd2p-dist配布基盤)へ
# フォールバックする。取得元がどちらであってもSHA256検証(下記$ExpectedSha256)は
# 必ず通す(ミラー汚染への防御。公式取得時と同一の検証コードパスを共有するため
# 整合が取れている)。両方失敗した場合は案内文(Show-D2PFailureGuidance、手動配置
# 手順込み)を出してfail-closedする。外部依存パスの三点セット原則(自動発見→
# 手動指定フォールバック→ログ)に倣い、どちらのURLを試したか・失敗理由は必ず
# stdoutへログする。
# 目標: <AppRoot>\assets\tools\blender-4.3.2-windows-x64\blender.exe が実在し、
# かつ後処理完了マーカー <同dir>\.d2p_patched.json が有効な状態にする。
#
# 終了コード: 0 = Blenderが使える状態になった。非0 = 失敗
#   (失敗時は日本語の案内を出す。案内文には機械可検出のマーカー文字列
#    [D2P_BLENDER_SETUP_FAIL] を含める)。
# 進捗: `##PROGRESS## <0-100> <phase>` 形式の行をstdoutへ逐次出力する。
#   (app\DiveToPalworld.cs の AppendLog() が既に同形式を解釈してbusyBar/
#    statusLabelへ反映する仕組みを持っているため、新規のGUI側パーサは
#    追加せずこの既存規約へ合わせた)。
param(
    [Parameter(Mandatory = $true)][string]$AppRoot,
    [string]$SourceZip,
    [switch]$Force,
    [string]$DownloadUrlOverride,
    [string]$MirrorUrlOverride,
    [switch]$CheckOnly
)
$ErrorActionPreference = "Stop"
# convert.ps1と同じ対策: GUI/subprocessからstdoutがリダイレクトされる環境では
# 既定エンコーディングがcp932になり、日本語1文字でも化けると呼び出し元の
# 文字列照合(進捗パース・案内文表示)が壊れる。明示的にUTF-8へ揃える
# (失敗しても続行だけはする。詳細な経緯はconvert.ps1側コメント参照)。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$BlenderVersion = "4.3.2"
$BlenderDirName = "blender-$BlenderVersion-windows-x64"
# 実在確認済み(https://download.blender.org/release/Blender4.3/ のディレクトリ一覧)。
$DownloadUrl = "https://download.blender.org/release/Blender4.3/blender-4.3.2-windows-x64.zip"
if ($DownloadUrlOverride) { $DownloadUrl = $DownloadUrlOverride }
# dev#62: 公式サイト取得に失敗した場合のフォールバック先(R2ミラー、d2p-dist配布基盤。
# devtools\dist_publish.py と同じバケット/Workerで配信。キーはdeps/配下、公式zipと同一物)。
$MirrorDownloadUrl = "https://dl.osakishokai.com/deps/blender-$BlenderVersion-windows-x64.zip"
if ($MirrorUrlOverride) { $MirrorDownloadUrl = $MirrorUrlOverride }
# ピン留めSHA256。取得元: https://download.blender.org/release/Blender4.3/blender-4.3.2.sha256
# (個別.sha256ではなくバージョン単位の一覧ファイル、blender-4.3.2-windows-x64.zip行)。
# 実ダウンロード物を自前でsha256sum計算した結果とも一致することを確認済み
# (work\u54_unbundle\wpA\REPORT.md 実DL検証記録参照)。
# dev#62: 取得元が公式・ミラーのどちらであっても、この同じハッシュで検証する
# (ミラー汚染への防御。下の「zip取得」ブロックの後、取得元を問わず一本の
# 検証コードパスを通る)。ミラーへ実際に置いたオブジェクトのSHA256実測は
# devtools\dist_publish.py 相当のアップロード直後読み戻し照合で確認済み。
$ExpectedSha256 = "933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6"
$RequiredFreeBytes = 2.5 * 1GB  # ダウンロードzip(~390MB)+展開後(~1GB)+作業コピー分の余裕

$ToolsDir = Join-Path $AppRoot "assets\tools"
$TargetDir = Join-Path $ToolsDir $BlenderDirName
$MarkerFileName = ".d2p_patched.json"
$MarkerPath = Join-Path $TargetDir $MarkerFileName
# make_dist.ps1が同梱する差し込み素材(ooz.pyd / pyooz dist-info / python3.dll)。
# VC++ランタイムはここには無い(ダウンロードしたBlender自身のblender.crt\から取る)。
$PatchMaterialsDir = Join-Path $AppRoot "assets\blender_patch"

$FailMarker = "[D2P_BLENDER_SETUP_FAIL]"

function Write-D2PProgress {
    param([int]$Pct, [string]$Phase)
    Write-Host "##PROGRESS## $Pct $Phase"
}

# dev#199対策: セットアップ時展開はWindows PowerShell 5.1(.NET Framework)の
# 素のFile/Directory APIで行っており、Win32の伝統的MAX_PATH(260文字)に
# 律速される。dev#149は「展開済みBlenderを実行時に呼び出す経路」を
# NTFSジャンクションで短縮したが、それは実体が既に存在する場合のみ発動する
# 対策であり、本関数が扱う「展開そのもの」には無関係(射程外)。
# ここでは`\\?\`長パスプレフィックス(Win32のExtended-Length Path構文)を
# 付与し、レジストリのLongPathsEnabled設定に関わらずMAX_PATHを無効化する。
# .NET Framework側のFile/Directory API(本スクリプトが展開に使っている
# System.IO.Compression.ZipFileExtensions / System.IO.Directory)はこの
# プレフィックスを認識するため、呼び出し側のパス文字列だけ変換すればよい
# (PowerShellのファイルシステムプロバイダ経由のコマンドレット
# (New-Item/Copy-Item等)は`\\?\`の扱いが不安定なため対象外とし、
# 素のAPI呼び出し箇所だけに限定して適用する)。
function Get-D2PLongPath {
    param([string]$Path)
    if ($Path.StartsWith("\\?\")) { return $Path }
    if ($Path.StartsWith("\\")) { return "\\?\UNC\" + $Path.Substring(2) }
    return "\\?\" + $Path
}

function Test-D2PMarkerValid {
    param([string]$Dir, [string]$MarkerFile)
    if (-not (Test-Path (Join-Path $Dir "blender.exe"))) { return $false }
    if (-not (Test-Path $MarkerFile)) { return $false }
    try {
        # マーカーはUTF-8(BOMなし)で書かれる(下のWriteAllText)。読取もUTF-8明示
        # (現内容はASCIIのみだが、job.json読取と同じ「UTF-8で書きUTF-8で読む」規約に統一)
        $m = Get-Content $MarkerFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($m.version -ne $BlenderVersion) { return $false }
        if ($m.sha256 -ne $ExpectedSha256) { return $false }
        if ($m.patched -ne $true) { return $false }
        return $true
    } catch {
        return $false
    }
}

function Invoke-D2PDownloadWithProgress {
    param([string]$Url, [string]$Dest)
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.UserAgent = "DiveToPalworld-ensure_blender/1.0"
    $req.Timeout = 120000
    $resp = $req.GetResponse()
    try {
        $total = $resp.ContentLength
        $inStream = $resp.GetResponseStream()
        $outStream = [System.IO.File]::Create($Dest)
        try {
            $buffer = New-Object byte[] (1024 * 1024)
            $readTotal = [long]0
            $lastPct = -1
            while ($true) {
                $read = $inStream.Read($buffer, 0, $buffer.Length)
                if ($read -le 0) { break }
                $outStream.Write($buffer, 0, $read)
                $readTotal += $read
                if ($total -gt 0) {
                    # ダウンロードの進捗は全体レンジの10-60%に割り当てる
                    $pct = 10 + [int](($readTotal / [double]$total) * 50)
                    if ($pct -ne $lastPct) {
                        $mbDone = [Math]::Round($readTotal / 1MB, 1)
                        $mbTotal = [Math]::Round($total / 1MB, 1)
                        Write-D2PProgress $pct "ダウンロード中 (${mbDone}MB / ${mbTotal}MB)"
                        $lastPct = $pct
                    }
                }
            }
        } finally {
            $outStream.Close()
            $inStream.Close()
        }
    } finally {
        $resp.Close()
    }
}

function Show-D2PFailureGuidance {
    param([string]$ReasonText)
    Write-Host ""
    Write-Host "$FailMarker Blenderのセットアップに失敗しました。"
    Write-Host "理由: $ReasonText"
    Write-Host ""
    Write-Host "対処方法:"
    Write-Host "  1. インターネット接続を確認してから、もう一度「フル変換」または「プレビュー更新」を押してください。"
    Write-Host "  2. 自動取得がうまくいかない場合は、手動で配置することもできます:"
    Write-Host "       (1) https://www.blender.org/download/ から Blender $BlenderVersion の Windows x64 Portable(zip版)をダウンロード"
    Write-Host "       (2) 展開して blender.exe のあるフォルダの中身を、次の場所にそのままコピーする:"
    Write-Host "           $TargetDir"
    Write-Host ""
}

# dev#230: -CheckOnly はダウンロード・展開・進捗表示・案内文の一切を行わず、
# Test-D2PMarkerValidの結果だけを終了コードで返す(0=有効/非0=無効)。
# -Forceとの併用は無意味なので考慮しない(CheckOnlyが常に先に評価される)。
if ($CheckOnly) {
    if (Test-D2PMarkerValid $TargetDir $MarkerPath) { exit 0 }
    exit 1
}

try {
    Write-D2PProgress 0 "Blenderの状態を確認中"

    if (-not $Force -and (Test-D2PMarkerValid $TargetDir $MarkerPath)) {
        Write-D2PProgress 100 "Blenderは準備済みです"
        Write-Host "OK: Blenderは既に使用可能です ($TargetDir)"
        exit 0
    }

    New-Item -ItemType Directory -Force $ToolsDir | Out-Null

    # --- ディスク空き容量チェック ---
    Write-D2PProgress 5 "ディスク空き容量を確認中"
    $resolvedAppRoot = (Resolve-Path $AppRoot).ProviderPath
    $driveRoot = [System.IO.Path]::GetPathRoot($resolvedAppRoot)
    $drive = New-Object System.IO.DriveInfo($driveRoot)
    if ($drive.AvailableFreeSpace -lt $RequiredFreeBytes) {
        $freeGb = [Math]::Round($drive.AvailableFreeSpace / 1GB, 2)
        throw "ディスクの空き容量が不足しています($driveRoot の空き: ${freeGb}GB、必要目安: 2.5GB)。空き容量を確保してから再試行してください。"
    }

    # --- zip取得 ---
    $downloadedZip = $null
    $zipToUse = $null
    if ($SourceZip) {
        if (-not (Test-Path $SourceZip)) { throw "指定された -SourceZip が見つかりません: $SourceZip" }
        Write-D2PProgress 60 "指定zipを使用します(ダウンロードなし、試験/オフライン用)"
        $zipToUse = (Resolve-Path $SourceZip).ProviderPath
    } else {
        Write-D2PProgress 10 "Blender $BlenderVersion をダウンロード中(公式サイト、約390MB)"
        $tempZip = Join-Path ([System.IO.Path]::GetTempPath()) ("d2p_blender_$([Guid]::NewGuid().ToString('N')).zip")
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        } catch { }
        # dev#62: 取得元は「公式サイト→(失敗時のみ)R2ミラー」の順に試す。
        # どちらを試したか・失敗理由は両方ともログへ残す(三点セット原則)。
        Write-Host "  取得元候補1(公式サイト): $DownloadUrl"
        $primaryErrorMsg = $null
        try {
            Invoke-D2PDownloadWithProgress -Url $DownloadUrl -Dest $tempZip
            Write-Host "  取得成功(公式サイト)"
        } catch {
            $primaryErrorMsg = $_.Exception.Message
            Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
            Write-Host "  公式サイトからの取得に失敗しました: $primaryErrorMsg"
            Write-Host "  取得元候補2(R2ミラー)へフォールバックします: $MirrorDownloadUrl"
            Write-D2PProgress 10 "Blender $BlenderVersion をダウンロード中(ミラー、約390MB)"
            try {
                Invoke-D2PDownloadWithProgress -Url $MirrorDownloadUrl -Dest $tempZip
                Write-Host "  取得成功(R2ミラー)"
            } catch {
                $mirrorErrorMsg = $_.Exception.Message
                Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
                throw ("ダウンロードに失敗しました(公式サイト・ミラーとも失敗): " +
                       "公式=$primaryErrorMsg / ミラー=$mirrorErrorMsg")
            }
        }
        $downloadedZip = $tempZip
        $zipToUse = $tempZip
    }

    # --- SHA256照合(fail-closed。ユーザー指定のSourceZipは削除しない、自前DL分のみ削除) ---
    Write-D2PProgress 60 "整合性を確認中(SHA256)"
    $actualHash = (Get-FileHash -Path $zipToUse -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedSha256) {
        if ($downloadedZip) { Remove-Item $downloadedZip -Force -ErrorAction SilentlyContinue }
        throw "ダウンロードしたファイルのSHA256が一致しません(取得: $actualHash / 期待値: $ExpectedSha256)。ファイルが壊れているか改竄されている可能性があるため中止しました。"
    }
    Write-Host "  SHA256一致確認: $actualHash"

    # --- 展開(最終位置と同じ親ディレクトリの下に作業用の一時フォルダを作り、
    #     完成後に同一ボリューム内リネームでアトミックに配置する) ---
    # WP-rdp_wsbops(2026-07-29): Expand-Archiveは.NETのZipFile API直呼びより顕著に遅い
    # (開発機実測: 同一zip[約390MB/6292エントリ]の展開がExpand-Archive平均24.7秒 →
    # ZipFile.ExtractToDirectory一括呼び出しなら平均5.7秒。Expand-Archiveのコマンドレット層が
    # エントリごとに追加処理を挟むのが原因)。ただし一括呼び出しは展開完了まで完全に無音になり、
    # rd_126で指摘された「65%→85%が無音」を悪化させる。折衷として.NET APIをエントリ単位で
    # 呼びつつファイル数ベースで進捗を報告する方式を採る(実測: 平均15.7秒、Expand-Archive比
    # 約1.6倍高速化しつつ途中経過も出せる)。詳細な計測表はwork\rdp_wsbops\README.md参照。
    Write-D2PProgress 65 "展開中"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # dev#199対策(即効・低リスク): 一時展開ディレクトリ名を短縮する。
    # 旧名`.tmp_ensure_blender_<32桁hex>`(20+32=52文字)は最終配置には
    # 存在しない余分な深さとしてまるごと乗り、最終的な実行時パスが
    # MAX_PATH未満に収まる環境でもセットアップの展開だけが先に失敗しうる
    # 非対称な脆弱性の原因だった(dev#199)。GUID自体は衝突回避のため
    # 維持し、接頭辞のみ短縮する(52文字→40文字、12文字分の余裕を確保)。
    $tmpExtractName = ".tmp_eb_$([Guid]::NewGuid().ToString('N'))"
    $tmpExtractDir = Join-Path $ToolsDir $tmpExtractName
    [System.IO.Directory]::CreateDirectory((Get-D2PLongPath $tmpExtractDir)) | Out-Null
    try {
        $zipArchive = [System.IO.Compression.ZipFile]::OpenRead($zipToUse)
        try {
            $zipEntries = $zipArchive.Entries
            $totalEntries = $zipEntries.Count
            $doneEntries = 0
            $lastReportedPct = -1
            foreach ($zipEntry in $zipEntries) {
                $entryDestPath = Join-Path $tmpExtractDir $zipEntry.FullName
                # dev#199対策(保険): 展開先パスに`\\?\`長パスプレフィックスを
                # 付与してMAX_PATHを無効化する(Get-D2PLongPath参照)。
                # ディレクトリ作成・ファイル展開とも素の.NET API呼び出しの
                # ままなのでプレフィックスをそのまま渡せる。
                $longEntryDestPath = Get-D2PLongPath $entryDestPath
                # ディレクトリエントリ(名前が / または \ で終わる)は作成のみ
                if ($zipEntry.FullName.EndsWith("/") -or $zipEntry.FullName.EndsWith("\")) {
                    [System.IO.Directory]::CreateDirectory($longEntryDestPath) | Out-Null
                    continue
                }
                $entryDestDir = Split-Path $entryDestPath -Parent
                $longEntryDestDir = Get-D2PLongPath $entryDestDir
                if (-not ([System.IO.Directory]::Exists($longEntryDestDir))) {
                    [System.IO.Directory]::CreateDirectory($longEntryDestDir) | Out-Null
                }
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($zipEntry, $longEntryDestPath, $true)
                $doneEntries++
                if ($totalEntries -gt 0) {
                    # 展開の進捗は全体レンジの65-85%に割り当てる(ダウンロード同様の帯域規約)
                    $pct = 65 + [int](($doneEntries / [double]$totalEntries) * 20)
                    if ($pct -ne $lastReportedPct) {
                        Write-D2PProgress $pct "展開中 ($doneEntries / $totalEntries ファイル)"
                        $lastReportedPct = $pct
                    }
                }
            }
        } finally {
            $zipArchive.Dispose()
        }
    } catch {
        Remove-Item $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        throw "zipの展開に失敗しました: $($_.Exception.Message)"
    }
    $extractedRoot = Join-Path $tmpExtractDir $BlenderDirName
    if (-not (Test-Path (Join-Path $extractedRoot "blender.exe"))) {
        Remove-Item $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        throw "展開結果にblender.exeが見つかりません(zipの構造が想定と違う可能性があります)"
    }
    Write-D2PProgress 85 "展開完了"

    # --- 後処理: ooz.pyd / pyoozメタ情報 / python3.dll の差し込み ---
    # (従来 build\make_dist.ps1 がビルド時にやっていた処理と同じ内容。詳細な経緯は
    #  make_dist.ps1側のコメント参照。ここではダウンロードしたばかりのBlenderへ実行する)
    Write-D2PProgress 90 "Python環境の差し込みを実行中"
    $bpyExe = Get-ChildItem (Join-Path $extractedRoot "*\python\bin\python.exe") -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $bpyExe) {
        Remove-Item $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        throw "展開したBlender内にpython\bin\python.exeが見つかりません"
    }
    $pyRoot = Split-Path (Split-Path $bpyExe.FullName -Parent) -Parent   # <ver>\python
    $sitePackages = Join-Path $pyRoot "lib\site-packages"
    $pyBin = Join-Path $pyRoot "bin"

    if (-not (Test-Path $PatchMaterialsDir)) {
        Remove-Item $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        throw "差し込み素材が見つかりません: $PatchMaterialsDir (配布物が壊れている可能性があります)"
    }
    $oozPyd = Join-Path $PatchMaterialsDir "ooz.pyd"
    $python3Dll = Join-Path $PatchMaterialsDir "python3.dll"
    $distInfoDirs = @(Get-ChildItem $PatchMaterialsDir -Directory -Filter "pyooz-*.dist-info" -ErrorAction SilentlyContinue)
    if (-not (Test-Path $oozPyd) -or -not (Test-Path $python3Dll) -or $distInfoDirs.Count -eq 0) {
        Remove-Item $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        throw "差し込み素材が不完全です($PatchMaterialsDir 配下にooz.pyd/python3.dll/pyooz-*.dist-infoが揃っていません)"
    }
    Copy-Item $oozPyd (Join-Path $sitePackages "ooz.pyd") -Force
    foreach ($di in $distInfoDirs) {
        $destDi = Join-Path $sitePackages $di.Name
        Remove-Item $destDi -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item $di.FullName $destDi -Recurse -Force
    }
    Copy-Item $python3Dll (Join-Path $pyBin "python3.dll") -Force

    # VC++ランタイムはダウンロードしたBlender自身のblender.crt\から取る(新規追加なし。
    # STATUS_DLL_NOT_FOUND対策、詳細はmake_dist.ps1側コメント参照)
    $crtSrcDir = Join-Path $extractedRoot "blender.crt"
    $crtNeeded = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    $crtDestDirs = @($pyBin, $sitePackages)
    foreach ($dll in $crtNeeded) {
        $src = Join-Path $crtSrcDir $dll
        if (-not (Test-Path $src)) {
            Remove-Item $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue
            throw "blender.crt\に$dllが無い(Blenderポータブルの構成が変わった可能性があります)"
        }
        foreach ($destDir in $crtDestDirs) {
            Copy-Item $src (Join-Path $destDir $dll) -Force
        }
    }

    # --- マーカー書き込み(移動前、展開先の一時ディレクトリ内で完成させる) ---
    $markerObj = [ordered]@{
        version        = $BlenderVersion
        sha256         = $ExpectedSha256
        patched        = $true
        patched_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        patch_items    = @("ooz.pyd", "pyooz-dist-info", "python3.dll",
                            "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    }
    # WP-A2(2026-07-28): `Set-Content -Encoding utf8` はPowerShellエンジンにより
    # 挙動が割れる(PS5.1=BOM付きUTF-8で書く/PS7=BOM無しで書く)。このスクリプト自身は
    # 読み戻し時にGet-Content -Rawを使うためどちらでも壊れないが、余計な非決定性を
    # 残さないよう明示的にBOM無しUTF-8で統一して書く。
    $markerJson = $markerObj | ConvertTo-Json
    $markerUtf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $extractedRoot $MarkerFileName), $markerJson, $markerUtf8NoBom)

    # --- アトミックに最終位置へ移動(途中失敗で半端物を残さない) ---
    # Rename-Itemは同一親ディレクトリ内での改名しかできない(親ディレクトリを跨ぐと
    # "Cannot rename the specified target..." で失敗する。実機で確認済み)。
    # $extractedRoot(...\assets\tools\.tmp_ensure_blender_XXXX\<Blender名>)と
    # $TargetDir(...\assets\tools\<Blender名>)は親が異なるため、Move-Itemを使う
    # (同一ボリューム内であればMove-Itemの実体はMoveFileExでありRename同様アトミック)。
    Write-D2PProgress 95 "最終配置に移動中"
    if (Test-Path $TargetDir) {
        $oldName = "$TargetDir.old_$([Guid]::NewGuid().ToString('N'))"
        Rename-Item $TargetDir $oldName -Force
        Remove-Item $oldName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Move-Item -Path $extractedRoot -Destination $TargetDir -Force
    Remove-Item $tmpExtractDir -Recurse -Force -ErrorAction SilentlyContinue

    if ($downloadedZip) {
        Remove-Item $downloadedZip -Force -ErrorAction SilentlyContinue
    }

    Write-D2PProgress 100 "Blenderのセットアップ完了"
    Write-Host "OK: Blenderのセットアップが完了しました ($TargetDir)"
    exit 0
} catch {
    Show-D2PFailureGuidance $_.Exception.Message
    exit 1
}
