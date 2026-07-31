# DiveToPalworld CLIオーケストレータ: VRM → MOD pak の一本道。
# 使い方:
#   pwsh -File convert.ps1 -Job <job.json>                # フル変換(noue、UE不要)
#   pwsh -File convert.ps1 -Job <job.json> -PreviewOnly   # プレビューだけ再生成(肩スライダーのループ用)
#   pwsh -File convert.ps1 -Job <job.json> -MaterialsOnly # 影の濃さだけ作り直す(フル変換済み前提。約50秒)
#   pwsh -File convert.ps1 -Job <job.json> -SkipBlender   # Blender工程を飛ばして再開
# 前提: job.json(paths.blender_exe / vrm_addon_zip 必須)
# EngineMode: noue専用(U12でUE不要パイプラインへ統合、dev#114(2026-07-29)でUEクック
#   経路自体を完全削除した)。-EngineMode / job.jsonのengine_modeに"noue"以外を
#   指定すると明確なエラーで拒否する(下記参照)。
param(
    [Parameter(Mandatory = $true)][string]$Job,
    [ValidateSet("noue")][string]$EngineMode,
    [switch]$PreviewOnly,
    [switch]$MaterialsOnly,   # 影の濃さだけ変更する高速パス(フル変換済み前提。fast_repack)
    [switch]$SkipVanilla,
    [switch]$SkipBlender,
    # dev#220(2026-07-30): 既定0=従来どおり即時判定(WaitOne(0)、非ブロッキング)。
    # 呼び出し側(relgate.py等)が正の値を渡すと、Mutex取得をOSレベルでブロッキング
    # 待機する(WaitOne($MutexWaitMs))。ポーリング(外側で固定間隔sleepしてから
    # プロセスを再起動する方式)と異なり、解放された瞬間に取得できる。
    # 既定0はGUI等の「他の変換が実行中なら即座に失敗を通知したい」呼び出し元の
    # 挙動を一切変えない(完全後方互換)。
    [int]$MutexWaitMs = 0
)
$ErrorActionPreference = "Stop"
$script:__ScriptT0 = Get-Date  # 全体の所要時間計測用(2026-07-26、失敗時ログ強化)
# GUIのログ欄はUTF-8で読む。コンソール側もUTF-8に揃えないと日本語Write-Hostや
# Blenderの出力が文字化けする(開発案「GUIログ文字化け」対応)
# 2026-07-26: 以前はこの設定が失敗しても空catchで無言で握りつぶしていた。
# LG班調査で「アプリ側の読み手はStandardOutputEncoding=UTF8を明示済みで正しい」と
# 判明したため、書き手側のこの設定が実際に反映されているかどうかが唯一の未知数。
# 失敗しても変換は止めない(方針どおり)が、成否と実値を記録し環境ヘッダで必ず出す。
$script:EnvConsoleEncodingOk = $true
$script:EnvConsoleEncodingNote = ""
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    $script:EnvConsoleEncodingOk = $false
    $script:EnvConsoleEncodingNote = $_.Exception.Message
    Write-Host "[WARN] Failed to set [Console]::OutputEncoding (conversion continues): $($_.Exception.Message)"
}
# ANSIカラーコード([7m等)を出さない。PS7のSelect-Stringはマッチ箇所を色付けし、
# GUIのログ欄では制御コードがそのまま見えてしまう。
# 2026-07-26 Windows Sandbox実試験(オーナー指揮下、SX班へ追加指示):
# $PSStyle はPowerShell 7以降のみに存在するプロパティで、配布版の実行環境
# (PowerShell 5.1)には無い。以前はバージョンを見ずに無条件でtryしていたため、
# 5.1環境では毎回ログの一番上で無害な[警告]が出ていた(本物の警告が埋もれる
# 原因になる)。5.1にはそもそもANSIエスケープを出す機能自体が無くこの設定は
# 不要なので、PS7以降でのみ試みる(5.1では「該当なし」であって「失敗」では
# ない、の区別)。
$script:EnvPSStyleOk = $true
$script:EnvPSStyleNote = ""
if ($PSVersionTable.PSVersion.Major -ge 7) {
    try { $PSStyle.OutputRendering = "PlainText" } catch {
        $script:EnvPSStyleOk = $false
        $script:EnvPSStyleNote = $_.Exception.Message
        Write-Host "[WARN] Failed to set `$PSStyle.OutputRendering (conversion continues): $($_.Exception.Message)"
    }
} else {
    $script:EnvPSStyleNote = "PowerShell $($PSVersionTable.PSVersion.Major).x has no `$PSStyle, so this is not applicable (no ANSI output capability to begin with, not an issue)"
}
$env:NO_COLOR = "1"

# 子プロセス(Blender同梱python / Blender埋め込みpython)の標準出力エンコーディングを
# 強制的にUTF-8にする。[Console]::OutputEncoding(上)はPowerShell自身がテキストを
# 整形して書き出す際にしか効かず、子プロセスがOSから受け取るハンドルの実体には
# 影響しない。GUI等からstdoutがリダイレクト/パイプされる環境(コンソールに
# 直結していない環境)では、Pythonは自分の標準出力エンコーディングを
# locale.getpreferredencoding()(Windowsでは`GetACP()`、日本語WindowsではUTF-8ベータ
# 機能を有効化していない大多数の環境で既定cp932)で決める。
# ログにem dash(—)等cp932非互換文字が1文字でも混ざると、そこでPythonプロセスが
# UnicodeEncodeErrorでクラッシュし変換全体が止まる(2026-07-26 他PCでの実行失敗、
# work\fx_cp932\fix_FX_cp932.md参照)。この2変数はconvert.ps1が起動する
# 全ての子プロセスに継承される(Run-Blenderのblender.exe、$BPythonの全呼び出し)。
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
# 失敗の瞬間のログこそ失われやすい(標準出力がブロックバッファリングされたまま
# プロセスが異常終了すると、直前の数行がディスク/パイプに届かず消える)。
# 2026-07-26: 失敗時ログ強化の一環。PYTHONUNBUFFERED=1でPython子プロセスの
# 出力を都度フラッシュさせ、クラッシュ直前の行を確実に残す(cp932対策の2変数とは
# 独立した別目的の設定。この行を消してもcp932対策には影響しないが、消さないこと)。
$env:PYTHONUNBUFFERED = "1"

# パイプライン全体の排他ロック。Blender(共有のユーザープロファイル上のVRMアドオン)は
# 同時実行に耐えない。2026-07-21に並列実行でアドオン書き換え衝突
# →インポート即死の実害を確認(flatv3事件)。プロセス終了時に自動解放される
$script:PipelineMutex = New-Object System.Threading.Mutex($false, "Global\DiveToPalworld_pipeline")
try {
    # dev#220: $MutexWaitMs=0(既定)なら従来どおりWaitOne(0)と完全に同じ挙動
    # (即時判定、非ブロッキング)。正の値を渡した呼び出し元だけがOSレベルの
    # ブロッキング待機に切り替わる(下のMutexWaitMsパラメータのコメント参照)。
    $acquired = $script:PipelineMutex.WaitOne($MutexWaitMs)
} catch [System.Threading.AbandonedMutexException] {
    # 前回の変換が中止(強制終了)された場合。放棄されたmutexは取得成立扱いでよい
    $acquired = $true
}
if (-not $acquired) {
    # u54: 検知を行番号非依存にするため、ASCII安全トークンをメッセージに含める。
    # 旧方式はWrite-Errorが自動付与する「スクリプトパス+コロン+行番号」形式の
    # 文字列に依存しており、この行より前に行を挿すだけで静かに壊れる構造的な
    # 脆さがあった(devtools\relgate.py / tests\shipcheck\dist_smoke.py が
    # 今後はこのトークンを見る)。
    Write-Error "Another conversion is already running. Please wait for it to finish and try again (concurrent runs are not supported) [D2P_MUTEX_BUSY]"
    exit 1
}

# 2026-07-26: .Path はUNCパスに対してプロバイダ修飾形("Microsoft.PowerShell.Core\FileSystem::\\...")
# を返し後段のパス操作を壊す(export_from_unity.ps1で見つかった同型の不具合)。.ProviderPathを使う。
$Job = (Resolve-Path $Job).ProviderPath
$JobDir = Split-Path $Job -Parent
$Here = $PSScriptRoot
$Pipeline = Split-Path $Here -Parent

# 2026-07-28(起票案1): job.jsonはGUIがUTF-8(BOMなし)で書く。PS5.1のGet-Contentは
# 既定がANSI(日本語Windowsではcp932)のため、非ASCIIパスを含むjob.jsonをcp932誤読
# するとエスケープ対「\\」の前半バイトがSJIS2バイト文字に食われて裸の「\」が残り、
# ConvertFrom-Jsonが「認識できないエスケープ」で必ず落ちる(独立2件の実報告)。
# job.jsonの読取は必ず -Encoding UTF8 を明示する(BOM有無どちらのUTF-8も正しく読める)。
$cfg = Get-Content $Job -Raw -Encoding UTF8 | ConvertFrom-Json
$Blender = $cfg.paths.blender_exe
# u54(2026-07-27): Blenderポータブルの同梱を廃止した。配布物(_internal\pipeline\cli
# の位置から辿るAppRoot=_internal直下にassets\がある構成)では、
# pipeline\cli\ensure_blender.ps1で初回取得/検証を試みてから再チェックする。
# 開発リポジトリ(assets\が無い構成)では従来どおり即失敗させる(挙動維持)。
#
# dev#230対策: 以前は「$Blenderのexeが存在しない」場合だけensure_blender.ps1を
# 呼んでいたため、2026-07-27より前にセットアップ済みで(マーカー概念が無い/不正な
# 状態の)Blenderキャッシュを持つ環境では、exeさえ実在すればensure_blender.ps1が
# 一度も呼ばれず、pyoozパッチの検証・再適用が永久に走らなかった
# (「no Python runtime that can import pyooz」で恒久停止、実報告2件)。
# 修正: exeの有無に関わらず、まず-CheckOnly(ダウンロードなしの軽量マーカー検証、
# ensure_blender.ps1のTest-D2PMarkerValidをそのまま使う。判定基準は同スクリプト側に
# 一元化し、ここでは重複実装しない)を必ず通す。有効なら即0で返るので通常運用での
# 追加コストはファイルI/O数回程度。無効な場合のみフル実行(取得/再パッチ)へ進む。
$EnsureBlenderPs1 = Join-Path $Here "ensure_blender.ps1"
$CandidateAppRoot = Split-Path $Pipeline -Parent
if ((Test-Path $EnsureBlenderPs1) -and (Test-Path (Join-Path $CandidateAppRoot "assets"))) {
    # 現在このconvert.ps1を動かしているのと同じPowerShellエンジン(pwsh/powershell.exe)を
    # 別プロセスとして起動する。ensure_blender.ps1は内部でexitするため、
    # &での直接呼び出し(同一プロセス内実行)だとconvert.ps1ごと終了してしまう
    # (PowerShellの既知の挙動: スクリプト内のexitは呼び出し元プロセスも終了させる)。
    $CurrentShellExe = (Get-Process -Id $PID).Path
    & $CurrentShellExe -NoProfile -ExecutionPolicy Bypass -File $EnsureBlenderPs1 -AppRoot $CandidateAppRoot -CheckOnly
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Blender not ready (missing, or an incomplete/invalid cache was found). Attempting setup (fetching/repairing from the official site)..."
        & $CurrentShellExe -NoProfile -ExecutionPolicy Bypass -File $EnsureBlenderPs1 -AppRoot $CandidateAppRoot
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Automatic Blender setup failed. Please follow the guidance above and try again."
            exit 1
        }
    }
    # 取得/検証後、job.json記載のパスが引き続き無効なら(既定の取得先と異なる場所を
    # 指していた等)、ensure_blender.ps1の既定到達先へ差し替えて再チェックする
    if (-not (Test-Path $Blender)) {
        $ExpectedBlender = Join-Path $CandidateAppRoot "assets\tools\blender-4.3.2-windows-x64\blender.exe"
        if (Test-Path $ExpectedBlender) { $Blender = $ExpectedBlender }
    }
}
if (-not (Test-Path $Blender)) { Write-Error "Blender not found: $Blender"; exit 1 }

# EngineMode解決: 明示パラメータ > job.json > 既定noue(U12)。
# dev#114(2026-07-29): UEクック経路を完全削除したため、"noue"以外が解決されたら
# ここで明確なエラーとして拒否する(-EngineMode自体はValidateSetでnoueしか
# 受け付けないため既にPowerShell側で弾かれるが、job.jsonのengine_modeキー経由
# (過去にUEモードで書かれた旧job.jsonの復元・引き継ぎ等)はValidateSetの外なので
# ここで明示的に検査する。負の対照: 旧仕様のengine_mode="ue"を持つjob.jsonは
# ここで必ず止まる)。
$Mode = if ($EngineMode) { $EngineMode } elseif ($cfg.engine_mode) { $cfg.engine_mode } else { "noue" }
if ($Mode -ne "noue") {
    Write-Error ("EngineMode '$Mode' is no longer supported. The UE (Unreal Engine) cook " +
        "pipeline was removed (dev#114); this tool now supports only 'noue'. " +
        "If this came from an old job.json, remove or fix its `"engine_mode`" field. [D2P_UE_MODE_REMOVED]")
    exit 1
}
Write-Host "=== EngineMode: $Mode ==="
# U51(2026-07-25): -MaterialsOnly は pipeline\py\fast_repack.py で中間成果を
# 再利用し pak だけ作り直す(このすぐ下の分岐)。

# Python工程はBlender同梱Pythonで実行(システムPython不要)
$BPython = Get-ChildItem (Join-Path (Split-Path $Blender) "*\python\bin\python.exe") | Select-Object -First 1
if (-not $BPython) { Write-Error "Blender-bundled Python not found"; exit 1 }
$BPython = $BPython.FullName
$Genders = if ($cfg.genders) { $cfg.genders } else { @("Male", "Female") }
$Avatar = if ($cfg.avatar_name) { $cfg.avatar_name } else { "Avatar" }

$LogDir = Join-Path $JobDir "build\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

# =====================================================================
# 失敗時ログ強化(2026-07-26、FL班)。ここから下の関数群は「記録の追加」のみで
# 変換の挙動そのものは変えない。目的はただ1つ:
# 「オーナーがこれから行う手動試験(大崎商会PC/Windows Sandbox)で何か起きたとき、
#  検体アバターを送ってもらわなくても、このログだけで原因を特定できるか」
# (この基準はオーナー自身の問い「どういうログがあればアバターを貰わなくても
#  診断できましたか?」に由来する、実際の受入条件)。
# 収集自体の失敗で変換を止めてはならないため、個々の項目をGet-SafeValueで
# 独立に保護し、1項目の失敗が他を道連れにしない。
# =====================================================================
function Get-SafeValue([scriptblock]$Block, [string]$Fallback = "(failed to retrieve)") {
    try { $r = & $Block; if ($null -eq $r -or "$r".Trim() -eq "") { return $Fallback }; return "$r" }
    catch { return "${Fallback}: $($_.Exception.Message)" }
}

# 2026-07-26 Windows Sandbox実試験(オーナー指揮下)で判明した追加課題への対応。
# 空きディスク容量の取得に Get-PSDrive を使っていたが、Sandbox環境(マウント/
# 共有フォルダ経由のドライブ)で実際には空きがあるのに毎回「0 GB」という
# 明確に誤った値を返していた(実測: C:ドライブでもPalworldのドライブでも0)。
# 「間違った診断情報は、無いより悪い」(指揮者裁定)ため、より頑健な
# [System.IO.DriveInfo] へ切り替える。それでも取れない場合は0 GBのような
# それらしい嘘の値を出さず、「取得できず」と明示する。
function Get-FreeSpaceGB([string]$Path) {
    try {
        if (-not $Path) { return $null }
        $qualifier = Split-Path $Path -Qualifier -ErrorAction Stop
        $driveLetter = $qualifier.TrimEnd(':')
        if ($driveLetter.Length -ne 1) { return $null }  # UNC等、ドライブレターでない場合は非対応
        $di = New-Object System.IO.DriveInfo($driveLetter)
        if (-not $di.IsReady) { return $null }
        return [math]::Round($di.AvailableFreeSpace / 1GB, 1)
    } catch {
        return $null
    }
}

function Format-FreeSpaceGB([string]$Path) {
    $v = Get-FreeSpaceGB $Path
    if ($null -eq $v) { return "unavailable" }
    return "$v GB"
}

# マスクで潰れる情報を、個人を特定しない派生事実として残す。CLAUDE.mdが挙げる
# 「他PCでだけ起きる」典型要因(非ASCII/空白/OneDrive配下/UNC/パス長)そのもの
function Get-PathFacts([string]$P) {
    if (-not $P) { return "(no path)" }
    $nonAscii = ($P.ToCharArray() | Where-Object { [int]$_ -gt 127 }).Count -gt 0
    $hasSpace = $P.Contains(" ")
    $isUnc = $P.StartsWith("\\")
    $oneDrive = Get-SafeValue { $env:OneDrive } ""
    $underOneDrive = ($oneDrive -and $oneDrive -ne "(failed to retrieve)" -and $P.StartsWith($oneDrive, [System.StringComparison]::OrdinalIgnoreCase))
    return "len=$($P.Length) nonAscii=$nonAscii hasSpace=$hasSpace UNC=$isUnc underOneDrive=$underOneDrive"
}

# dev#7: 旧`Mask-Path`(%USERPROFILE%の完全一致プレフィックスしか扱えなかった)を引退。
# 実ユーザー報告4AL4M4GT(非%USERPROFILE%ドライブの絶対パスがUnity/VCC・インストール先・
# Steamライブラリでそのまま漏れた)を受け、%USERPROFILE%配下以外は生パスを一切出さず
# ファイル名+Get-PathFactsの事実だけを返すよう一般化した(三段構成の「各所factify」、
# 詳細はwork\issue_zero\i7\NOTES.md)。%USERPROFILE%配下はこれまでどおりトークン化して
# 表示する(このリテラル自体はユーザー名を含まず、開発上有用なため)。
# 外部プロセス呼び出しは一切しない(この関数はBlender同梱Pythonが起動できるかどうかを
# これから診断する箇所でも使われるため。NOTES.md 2節参照)。
function Format-DiagPath([string]$P) {
    if (-not $P) { return $P }
    try {
        $up = [Environment]::GetFolderPath("UserProfile")
        if ($up -and $P.StartsWith($up, [System.StringComparison]::OrdinalIgnoreCase)) {
            return "%USERPROFILE%" + $P.Substring($up.Length)
        }
    } catch {}
    $name = $null
    try { $name = Split-Path $P -Leaf } catch {}
    if (-not $name) { $name = "(name unavailable)" }
    return "$name (path masked; " + (Get-PathFacts $P) + ")"
}

# 失敗の瞬間にまとめて出す「読む場所」を1つ作る(事例2: `FAIL: 変換 rc=1`しか
# 残っておらず再変換しないと何も分からなかった教訓)。既存のWrite-Errorの直前に
# 呼ぶだけの追記で、exitするかどうか等の制御フローは呼び出し側が従来通り決める。
# $LogPath指定時は、そのファイルの中身を丸ごとここに転記する
# (子プロセスのstderr/stdoutを"上位ログ"へ確実に合流させるため。
#  Select-Stringの正規表現フィルタに漏れなく全文を出すのが狙い)
function Report-PhaseFailure([string]$Phase, $ExitCode, [string]$LogPath, [datetime]$PhaseStart) {
    $elapsed = if ($PhaseStart) { [math]::Round(((Get-Date) - $PhaseStart).TotalSeconds, 1) } else { "?" }
    Write-Host ""
    Write-Host "=== Failure summary ==="
    Write-Host "Phase: $Phase"
    Write-Host "Exit code: $ExitCode"
    Write-Host "Elapsed: ${elapsed}s"
    Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    if ($LogPath -and (Test-Path $LogPath)) {
        Write-Host "--- Full detail log ($LogPath) ---"
        try { Get-Content -Path $LogPath -ErrorAction Stop | ForEach-Object { Write-Host $_ } }
        catch { Write-Host "(Failed to read detail log: $($_.Exception.Message))" }
        Write-Host "--- End of detail log ---"
    } elseif ($LogPath) {
        Write-Host "Detail log (not found): $LogPath"
    }
    Write-Host "==================="
    Write-Host ""
    # 失敗の瞬間の出力こそ失われやすいため、ここで明示的にフラッシュする
    try { [Console]::Out.Flush(); [Console]::Error.Flush() } catch {}
}

# --- 構造ダンプ(2026-07-26 追加任務3): アバター読み込み(step01)失敗時、
# 「0頂点メッシュ」「メッシュデータの共有(multi-user)」「親をたどった階層パス」を
# 出す。pipeline\blender\step01_import_vrm.py はMU班の担当につき編集禁止のため、
# ここでは同ファイルを一切呼ばず、convert.ps1が独立に生成する診断専用スクリプトで
# 同じ入力ファイルをBlender組み込みインポータ(gltf/fbx)へ読み直すだけに留める。
# 目的は「実際の変換結果」ではなく「オブジェクト構造の名前と個数」の可視化のみ
# (ジオメトリ・テクスチャ本体は出力しないため権利・プライバシー上も安全)。
# 失敗時にしか呼ばれないので通常の変換速度には一切影響しない。
$script:DiagDumpPySource = @'
import sys
try:
    import bpy
    sep = sys.argv.index("--")
    path = sys.argv[sep + 1]
    out_path = sys.argv[sep + 2]
    lines = []
    def log(s):
        lines.append(s)
        print(s)
    try:
        if path.lower().endswith(".fbx"):
            bpy.ops.import_scene.fbx(filepath=path)
        else:
            # VRMはglTFベースなので組み込みgltfインポータで構造だけ読める
            # (VRM拡張アドオン非依存。ヒューマノイド変換の正しさは問わない、
            # オブジェクト構造の診断が目的)
            bpy.ops.import_scene.gltf(filepath=path)
    except Exception as e:
        log("[diag] import itself failed: %s: %s" % (type(e).__name__, e))

    def parent_chain(o):
        chain = []
        p = o
        seen = set()
        while p is not None and id(p) not in seen:
            seen.add(id(p))
            chain.append(p.name)
            p = p.parent
        return " / ".join(reversed(chain))

    objs = list(bpy.data.objects)
    log("[diag] total objects: %d" % len(objs))

    suspects = []
    for o in objs:
        if o.type == "MESH" and o.data is not None:
            vcount = len(o.data.vertices)
            users = o.data.users
            if vcount == 0 or users > 1:
                suspects.append((o, vcount, users))

    log("[diag] suspicious objects (0 verts or shared mesh): %d" % len(suspects))
    for o, vcount, users in suspects:
        log("  - name=%s type=%s verts=%d data_name=%s data.users=%d hierarchy=%s" % (
            o.name, o.type, vcount, o.data.name, users, parent_chain(o)))

    log("[diag] all objects:")
    for o in objs:
        if o.type == "MESH" and o.data is not None:
            log("  - name=%s type=%s verts=%d data.users=%d hierarchy=%s" % (
                o.name, o.type, len(o.data.vertices), o.data.users, parent_chain(o)))
        else:
            log("  - name=%s type=%s hierarchy=%s" % (o.name, o.type, parent_chain(o)))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
except Exception as e:
    print("[diag] diagnostic script itself failed: %s: %s" % (type(e).__name__, e))
'@

function Invoke-ImportFailureDiag([string]$AvatarPath) {
    # 呼び出し側でtry/catch必須(この関数自体は例外を投げうる)。
    # 失敗時のみ呼ばれる想定で、通常の変換速度には影響しない
    if (-not $AvatarPath -or -not (Test-Path $AvatarPath)) {
        Write-Host "[diag] Structure dump: skipped because input file could not be resolved ($AvatarPath)"
        return
    }
    Write-Host "[diag] Attempting import structure dump (so diagnosis is possible without the avatar file; takes a few to ~10 seconds)"
    $diagT0 = Get-Date
    $diagScript = Join-Path $LogDir "_diag_dump.py"
    $diagOut = Join-Path $LogDir "_diag_structure.log"
    $diagRunLog = Join-Path $LogDir "_diag_dump_run.log"
    Remove-Item $diagOut -Force -ErrorAction SilentlyContinue
    Set-Content -Path $diagScript -Value $script:DiagDumpPySource -Encoding UTF8
    & $Blender --background --factory-startup --python-exit-code 0 --python $diagScript -- $AvatarPath $diagOut 2>&1 |
        Tee-Object $diagRunLog | Out-Null
    $elapsed = [math]::Round(((Get-Date) - $diagT0).TotalSeconds, 1)
    Write-Host "--- Structure dump (failure diagnostics only: names/counts/hierarchy, no geometry data) ---"
    if (Test-Path $diagOut) {
        # _diag_structure.logは診断Python(上の$script:DiagDumpPySource)がencoding="utf-8"で
        # 書く。既定(ANSI/cp932)で読むと日本語見出しが「[diag] 繧ｪ...」にmojibake化し
        # 診断価値を失う(No.20実報告)。UTF-8明示で読む
        Get-Content $diagOut -Encoding UTF8 | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "(Failed to generate structure dump. Raw log: $diagRunLog)"
        if (Test-Path $diagRunLog) { Get-Content $diagRunLog | Select-Object -Last 20 | ForEach-Object { Write-Host $_ } }
    }
    Write-Host "--- End of structure dump (took ${elapsed}s) ---"
}

# --- Unity輸出ログの橋渡し(2026-07-26 追加任務3): export_from_unity.ps1が
# FBXと同じフォルダへ書く unity_export.log には「どのコンポーネントを何個所から
# 除去したか(PreBake/PostBakeサニタイズ)」が全パス付きで残っている。しかし
# それはUnity輸出という別工程・別スクリプト(FL班の担当外)の成果物であり、
# convert.ps1が読むFBX/VRMの隣にあっても自動的にはconvert.ps1側のログへ
# 合流しない。ここではexport_from_unity.ps1を一切変更せず、convert.ps1側から
# 「読みに行くだけ」で橋渡しする(書き込み許可ファイル外には一切触れない)。
function Write-UnityExportSanitizeHint([string]$AvatarPath) {
    if (-not $AvatarPath) { return }
    try {
        $sibling = Join-Path (Split-Path $AvatarPath -Parent) "unity_export.log"
        if (-not (Test-Path $sibling)) {
            Write-Host "[diag] Unity export log (unity_export.log) not found in the same folder (direct VRM input, or the export folder may have been moved)"
            return
        }
        # unity_export.logはUTF-8。PS5.1のSelect-String -Pathは-Encoding指定ができず
        # 既定解釈に依存するため、日本語パターンはcp932誤読で構造的に不一致になる。
        # Get-Content -Encoding UTF8 を経由してから照合する(MatchInfo.Lineの利用は不変)
        $sanitizeLines = Get-Content -Path $sibling -Encoding UTF8 -ErrorAction SilentlyContinue |
            Select-String -Pattern "サニタイズ"
        if (-not $sanitizeLines) {
            Write-Host "[diag] Unity export log found, but no sanitize-related lines were found: $(Format-DiagPath $sibling)"
            return
        }
        Write-Host "--- Unity export sanitize record (which components were removed from where. Excerpt from $(Format-DiagPath $sibling)) ---"
        $sanitizeLines | ForEach-Object { Write-Host $_.Line }
        Write-Host "--- End of sanitize record ---"
    } catch {
        Write-Host "[diag] Failed to relay Unity export log (does not affect the main build): $($_.Exception.Message)"
    }
}

$script:BPythonVersionOk = $false  # 既定は失敗扱い(下のtry内で到達できなければ安全側)
$script:BPythonVersionRaw = ""
try {
    Write-Host "=== Environment info (diagnostic, added 2026-07-26) ==="
    Write-Host ("pwsh: " + $PSVersionTable.PSVersion.ToString() + " / " + $PSVersionTable.PSEdition)
    Write-Host ("OS: " + (Get-SafeValue { [System.Environment]::OSVersion.VersionString }) +
        " / build " + (Get-SafeValue { (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -ErrorAction Stop).CurrentBuildNumber }))
    Write-Host ("ACP (default code page): " + (Get-SafeValue { [System.Text.Encoding]::Default.CodePage }))
    Write-Host ("Console.OutputEncoding (actual value after set attempt): " + (Get-SafeValue { [Console]::OutputEncoding.WebName }) +
        " / OutputEncoding set succeeded=" + $script:EnvConsoleEncodingOk +
        $(if (-not $script:EnvConsoleEncodingOk) { " (" + $script:EnvConsoleEncodingNote + ")" } else { "" }) +
        " / PSStyle set succeeded=" + $script:EnvPSStyleOk +
        $(if ($script:EnvPSStyleNote) { " (" + $script:EnvPSStyleNote + ")" } else { "" }))
    Write-Host ("PYTHONIOENCODING=$($env:PYTHONIOENCODING) PYTHONUTF8=$($env:PYTHONUTF8) PYTHONUNBUFFERED=$($env:PYTHONUNBUFFERED)")
    Write-Host ("Blender executable: " + (Format-DiagPath $Blender))
    Write-Host ("Blender version: " + (Get-SafeValue { (& $Blender --version 2>&1 | Select-Object -First 1) }))
    Write-Host ("BlenderPython executable: " + (Format-DiagPath $BPython))
    # 2026-07-26 Windows Sandbox実試験(オーナー指揮下)で判明: このバージョン
    # 取得の失敗は「ログの1行が(取得失敗)になるだけの些細な話」ではなく、
    # 「Blender同梱pythonがそもそも起動できない」という致命的な兆候だった
    # (実例: STATUS_DLL_NOT_FOUNDでPhase 0が0秒で即死。原因はVC++再頒布可能
    # パッケージ不足の疑いとDL班が特定)。下のブロックで致命的エラーとして
    # 早期に止める(Get-SafeValueの「空でなければOK」に頼らない。エラー
    # メッセージ自体が空でないので、それだけでは失敗を見逃す)。
    #
    # 実装注記(2026-07-26、実機検証で判明): 当初$LASTEXITCODEで成否判定
    # していたが、`... | Select-Object -First 1`と組み合わせると、
    # -Firstによるパイプラインの早期終了で外部プロセスの真の終了コードが
    # $LASTEXITCODEに反映されないことがあり(実測: 正常起動しバージョン文字列
    # "Python 3.11.9"を正しく取れているのに$LASTEXITCODEが0でなく誤って
    # 失敗と判定された)、変換が必ず成功する環境でも致命的エラーで
    # 止まってしまう欠陥があった。$LASTEXITCODEには依存せず、出力が
    # "Python X.Y"の形を持つかどうかだけで判定する(Select-Object -First 1も
    # 使わない。パイプラインを単純にして早期終了の余地を無くす)。
    $script:BPythonVersionOk = $false
    $script:BPythonVersionRaw = ""
    try {
        $out = & $BPython --version 2>&1
        $script:BPythonVersionRaw = ($out | Out-String).Trim()
        # 2026-07-26 指揮者からの追加確認要請への対応: 先頭アンカー(^)付きの
        # 正規表現だと、バージョン文字列より前に何か1行でも出た場合
        # (空行、非致命的なstderr警告など)に誤って「失敗」判定になり、正常な
        # 環境でも変換全体を止めてしまう(単体テストで実際に再現: 空行1つ・
        # 警告1行が先頭にあるだけで検出漏れになることを確認)。全ユーザーの
        # 変換を止めうる判定なので、"Python"+バージョン番号が出力のどこかに
        # 含まれていればよい(先頭固定にしない)方向に倒す。逆方向の誤り
        # (本当に壊れているのに"成功"と誤判定する)のリスクは、DLL欠落時の
        # 実際の失敗パターン(0秒での即死、Python側のコードが一切実行されず
        # 出力がほぼ空になる)には当たらないことを確認済み(単体テストで
        # 「Pythonという語だけ含む無関係な文字列」「バージョン番号の無い
        # トレースバック」はいずれも不一致=失敗判定のままであることを確認)
        if ($script:BPythonVersionRaw -match 'Python\s+\d+\.\d+') {
            $script:BPythonVersionOk = $true
        }
    } catch {
        $script:BPythonVersionRaw = $_.Exception.Message
    }
    Write-Host ("BlenderPython version: " + $(if ($script:BPythonVersionOk) { $script:BPythonVersionRaw } else { "(failed to retrieve: $script:BPythonVersionRaw)" }))
    # job.jsonに未指定の場合、pipeline\py\vp_core.pyのDEFAULT_PALWORLD_PAKと
    # 同じ既定値にフォールバックする(実際に使われる値と一致させる)
    $palworldPak = if ($cfg.paths.palworld_pak) { $cfg.paths.palworld_pak } else {
        "C:\Program Files (x86)\Steam\steamapps\common\Palworld\Pal\Content\Paks\Pal-Windows.pak"
    }
    $palworldPaksDir = Get-SafeValue { Split-Path $palworldPak -Parent }
    Write-Host ("Palworld pak directory: " + (Format-DiagPath $palworldPaksDir))
    Write-Host ("  Free space: " + (Format-FreeSpaceGB $palworldPaksDir))
    Write-Host ("  Characteristics: " + (Get-PathFacts $palworldPaksDir))
    Write-Host ("Output destination (JobDir) free space: " + (Format-FreeSpaceGB $JobDir))
    $avatarPath = $cfg.vrm_path
    if ($avatarPath -and (Test-Path $avatarPath)) {
        $fi = Get-Item $avatarPath
        Write-Host ("Input avatar: extension=$($fi.Extension) size=$([math]::Round($fi.Length/1MB,2))MB")
    } else {
        Write-Host ("Input avatar: (path could not be resolved: " + (Format-DiagPath $avatarPath) + ")")
    }
    Write-Host ("Input path characteristics: " + (Get-PathFacts $avatarPath))
    Write-Host ("JobDir characteristics: " + (Get-PathFacts $JobDir))
    Write-Host ("Execution mode (EngineMode): $Mode")
    $gitHash = Get-SafeValue { $repoRootForHeader = Split-Path $Pipeline -Parent; (& git -C $repoRootForHeader rev-parse --short HEAD 2>&1 | Select-Object -First 1) } "(no git / distribution build)"
    Write-Host ("git commit: $gitHash")
    Write-Host "======================="
} catch {
    Write-Host "[WARN] Error while collecting environment info (conversion continues): $($_.Exception.Message)"
}

# 2026-07-26 Windows Sandbox実試験(オーナー指揮下、DL班特定+指揮者からの
# 追加指示)への対応: 「Blender同梱pythonが起動できない」は、この後の全工程
# (Phase 0以降、$BPythonを使うすべてのステップ)が100%失敗することが確定
# している状態。これを警告に留めて先へ進ませると、ユーザーは
# STATUS_DLL_NOT_FOUND(0xC0000135)のような読めない終了コードだけを見せられ
# 詰む(実例: Phase 0が0秒で即死)。同梱pythonの起動可否はこの1回のチェックで
# 確定できる(以降のBPython呼び出しは全て同じ実行ファイルを使うため)ので、
# ここで早期に止めて「読める失敗」に変える。
# 原因は推測で断定しない(DLL不足はDL班が今回のSandbox事例で特定した
# もっとも疑わしい説明だが、他の原因もありうるため「可能性があります」で
# 表現する)。
if (-not $script:BPythonVersionOk) {
    Write-Host ""
    Write-Host "=== Pre-flight check failed: Blender-bundled Python cannot start ==="
    Write-Host "Executable: $(Format-DiagPath $BPython)"
    Write-Host "Error detail: $script:BPythonVersionRaw"
    Write-Host ""
    Write-Host "In this state, the conversion about to start will definitely fail"
    Write-Host "(steps that use Blender-bundled Python will crash within the first few seconds)."
    Write-Host ""
    Write-Host "Possible cause: the Visual C++ Redistributable package may be missing"
    Write-Host "(other causes are possible; this is just the most common known cause)."
    Write-Host "Fix: install the latest Microsoft Visual C++ Redistributable (x64), then"
    Write-Host "      run this again."
    Write-Host "      Download: https://aka.ms/vs/17/release/vc_redist.x64.exe"
    Write-Host "==============================================="
    Write-Error "Failed to start Blender-bundled Python. Please check the message above."
    exit 1
}

# GUIの進捗バー用マーカー(##PROGRESS## <0-100> <表示ラベル>)。GUIはこれを拾って
# バーとステータスを更新する(ログ欄には出さない)。工程の区間割当+クック実測
function Progress($pct, $label) { Write-Host "##PROGRESS## $pct $label" }
Progress 2 "Preparing"

# dev#288 WP-UXIMPL(2026-07-30、提案1): 55%→96%ブロック(Phase 2-6=noue一気通貫
# ビルド、convert_noue.py呼び出し1本)は温状態で全体の53〜74%を占めるのに
# バー・ラベルが一切動かない「見かけ上の停滞」区間(分析: work\speed_mission\ux\PROPOSAL.md)。
# convert_noue.py/build_pak_from_avatar.pyはdev#220で既に軽量な工程境界print
# (`[TAG] === NoueSubphase: <name> start/done ===` 等)を仕込み済みなので、
# それを検出して55〜96の範囲へリスケールした##PROGRESS##として中継するだけ
# (新しい計測ロジックは書かない、実処理・出力バイトは無変更)。
# %の刻みはSPEED_THEORY.md §3の実測配分を参考にした固定値(検体ごとの厳密な
# 比例は不要、WP-UXIMPL.md「設計上の要求1」)。虚偽の進捗(時間ベースの演出)は
# 一切含まない — 実際にconvert_noue.pyが出した工程境界行だけを反映する。
# マッチは先勝ち(-like のワイルドカード部分一致)。$script:LastNoueProgressPctで
# 単調非減少を保証する(想定外の順序で行が来ても後退しない=負の対照でテスト)。
$script:NoueSubphaseMarkers = @(
    @{ Match = '*NoueSubphase: template_prep done*';              Pct = 58; Label = 'Preparing template assets' }
    @{ Match = '*NoueSubphase: atlas_bake done*';                  Pct = 61; Label = 'Baking texture atlas' }
    @{ Match = '*NoueSubphase: material_override done*';           Pct = 63; Label = 'Preparing material overrides' }
    @{ Match = '*Phase1Subphase: avatar_dump done*';                Pct = 65; Label = 'Reading avatar data' }
    @{ Match = '*Phase 2: injecting real avatar into outfit SKs*'; Pct = 66; Label = 'Injecting avatar into outfit items' }
    @{ Match = '*Phase2Subphase: overrides start*';                 Pct = 78; Label = 'Compressing textures' }
    @{ Match = '*Phase 3: building pak*';                           Pct = 90; Label = 'Building pak file' }
    @{ Match = '*Phase 4: preflight_pak.py*';                       Pct = 94; Label = 'Running preflight checks' }
)
$script:LastNoueProgressPct = 0

function Relay-NoueSubphaseProgress($line) {
    if ([string]::IsNullOrEmpty($line)) { return }
    foreach ($m in $script:NoueSubphaseMarkers) {
        if ($line -like $m.Match) {
            # 単調非減少の保証(受入ゲート「負の対照: 逆行しない」の実体)
            if ($m.Pct -gt $script:LastNoueProgressPct) {
                $script:LastNoueProgressPct = $m.Pct
                Progress $m.Pct $m.Label
            }
            return
        }
    }
}

# === -MaterialsOnly(noue、U51): 影の濃さだけ作り直す高速パス ===
# フル変換の中間成果(build\live_template と build\noue_work\variant)を再利用し、
# pak だけ作り直す。2026-07-25 実測(Seed-san / 742MBのpak、work\u51_seed):
#   フル変換 364秒 → 影のみ更新 50〜55秒(pak書き出し約35秒 + preflight 約17秒)。
# 鮮度ゲートで止まる場合は2秒で返る。
# 本体は pipeline\py\fast_repack.py(鮮度ゲート内蔵: 影の濃さ/影なし以外の設定が
# 変わっていたら止まる)。ここではその失敗理由をエンドユーザーの言葉に翻訳する。
if ($MaterialsOnly) {
    # 以降はネイティブコマンド中心。EAP=Stopのままだとpython側のstderr1行目で即死する
    # (下のPhase 0以降と同じ理由。flatv3事件その3)
    $ErrorActionPreference = "Continue"
    $PSNativeCommandUseErrorActionPreference = $false

    Write-Host "=== Materials-only update (noue): reuse previous intermediate results and rebuild only the MOD ==="
    # 2026-07-26: devtools\ から pipeline\py\ へ移設(devtools\は非公開のため、
    # 出荷物側の実行時コンポーネントを置けない)。他のpipeline\py\スクリプトと
    # 同じ$Pipeline基準に揃える
    $Repack = Join-Path $Pipeline "py\fast_repack.py"
    if (-not (Test-Path $Repack)) {
        Write-Error "Script required for `"materials-only update`" not found: $Repack (`"full conversion`" still works)"
        exit 1
    }
    $Out = Join-Path $JobDir "build"
    $ModPak = Join-Path $Out "${Avatar}_PlayerSwap_P.pak"
    # 失敗したときに前回の正常なpakを失わないよう、書き換える前に退避する
    # (拡張子が変わるのでGUIの一覧 "*_PlayerSwap_P.pak" には出ない)。
    # コピーではなくリネームなので735MBでも一瞬
    $PrevPak = "$ModPak.prev"
    Remove-Item $PrevPak -Force -ErrorAction SilentlyContinue
    if (Test-Path $ModPak) { Move-Item $ModPak $PrevPak -Force -ErrorAction SilentlyContinue }

    Progress 8 "Checking previous conversion results"
    $__t0 = Get-Date
    $repackLines = New-Object System.Collections.ArrayList
    & $BPython $Repack --job $Job --out $ModPak --preflight 2>&1 | ForEach-Object {
        $line = $_.ToString()
        [void]$repackLines.Add($line)
        # -like は使わない([repack] の角かっこがワイルドカードの文字クラスとして
        # 解釈され、絶対に一致しなくなる)
        if ($line.Contains("[repack] replacing:")) { Progress 40 "Generating MOD files" }
        elseif ($line.Contains("[repack] pak generated:")) { Progress 80 "Final check" }
        Write-Host $line
    }
    $repackExit = $LASTEXITCODE
    $repackText = ($repackLines -join "`n")
    $repackLogPath = Join-Path $LogDir "materials_only.log"
    try {
        Set-Content $repackLogPath $repackText -Encoding UTF8
    } catch {
        # 2026-07-26: 以前はここも空catchで無言だった。保存に失敗しても処理は続けるが
        # (この失敗自体は致命的ではない)、黙って握りつぶさず記録する
        Write-Host "[WARN] Failed to save materials_only.log (conversion continues): $($_.Exception.Message)"
    }

    if ($repackExit -ne 0) {
        Report-PhaseFailure "Materials-only update (noue, fast_repack.py)" $repackExit $repackLogPath $__t0
        # 前回の正常なpakを戻す(壊れた/古いpakを一覧に残さない)
        Remove-Item $ModPak -Force -ErrorAction SilentlyContinue
        if (Test-Path $PrevPak) { Move-Item $PrevPak $ModPak -Force -ErrorAction SilentlyContinue }
        Write-Host ""
        # マーカーの定義は pipeline\py\fast_repack.py 冒頭(ERR_*)。片方だけ変えないこと
        if ($repackText -match '##REPACK_ERROR## STALE') {
            Write-Error ("There are changes that `"materials-only update`" cannot apply " +
                "(a setting other than shadow strength, or the avatar file, has changed). " +
                "Please run `"full conversion`" instead. The name of the changed setting is shown in the log just above.")
        } elseif ($repackText -match '##REPACK_ERROR## NO_FULL_BUILD') {
            Write-Error ("This avatar has not been fully converted yet (no previous conversion result found). " +
                "Please run `"full conversion`" first.")
        } elseif ($repackText -match '##REPACK_ERROR## PREFLIGHT_FAIL') {
            Write-Error "Final check FAILED — do not use this MOD (the previous MOD has been left untouched)"
        } else {
            Write-Error "`"Materials-only update`" failed — see the log above"
        }
        exit 1
    }
    Remove-Item $PrevPak -Force -ErrorAction SilentlyContinue

    Progress 100 "Done"
    Write-Host ""
    Write-Host ("[materials-only update] OK (" + [math]::Round(((Get-Date) - $__t0).TotalSeconds, 1) + "s)")
    Write-Host "=== Complete (materials-only update) ==="
    Write-Host "pak: $ModPak"
    Write-Host "Install location: copy directly into <Palworld>\Pal\Content\Paks\ (while the game is closed)"
    Write-Host "Uninstall: just delete the copied pak file"
    exit 0
}

function Run-Blender($script, $extraArgs, [switch]$NonFatal) {
    # $NonFatal(2026-07-26、PV班): 失敗しても変換全体を止めず $false を返すだけに
    # したい工程(=プレビュー画像生成)向け。既定は従来どおり致命的(exit 1)。
    # 「診断情報を減らさない」の原則は維持: Report-PhaseFailureは$NonFatalでも
    # 必ず呼ぶ(詳細ログ全文の転記は失敗時ログ強化の主目的そのものであり、
    # 非致命化はそれを削る理由にならない)。
    $__t0 = Get-Date
    $logPath = Join-Path $LogDir "$($script -replace '\.py$','').log"
    # 2026-07-26(PV班): Select-Stringの一致結果をパイプラインへ流しっぱなしにせず
    # Write-Hostへ明示転記する。理由: この関数は下で $true/$false を返すように
    # なった(-NonFatal対応)。パイプライン出力を放置すると、それが関数の戻り値
    # ストリームに混入し、①戻り値を受け取らない既存の全呼び出しで無意味な
    # "True"がログに漏れる、②戻り値を受け取る呼び出し($previewOk = ...)では
    # 戻り値が「一致行のMatchInfo + $true/$false」の配列になってしまい、
    # PowerShellの配列の真偽判定(要素数>0なら常に$true)により
    # `-not $previewOk` が常に$falseになる(失敗を検出できない実害あり、
    # 負の対照で発覚)。Write-Hostは戻り値ストリームを汚さないため、
    # 表示内容は変えずにこの2つの実害を断つ。
    # --factory-startup(2026-07-28、dev issue #24 / 公開issue #14): ユーザーの
    # userpref.blend(日本語UI+「新規データ名を翻訳」等)を読み込むと、新規
    # データブロックが「マテリアル」等の翻訳名で作られKeyErrorで工程が落ちる。
    # 全Blender起動を工場出荷状態に固定し、必要なアドオンはスクリプト側で
    # 毎回明示enableする(pipeline\blender\vp_bl.py::ensure_vrm_addon)
    # dev issue #150(2026-07-29): `2>&1`でBlenderのstderrをパイプへ合流させると、
    # PowerShellはstderrの各行を素の文字列ではなく[ErrorRecord]でラップする。
    # Windows PowerShell 5.1(pwsh未検出時のフォールバック実行環境。上のコメント
    # 群参照)では、連続するエラーの先頭行が"At <script>:<line>"/"+ CategoryInfo"/
    # "+ FullyQualifiedErrorId"を伴う複数行の"NativeCommandError"整形ブロックに
    # 置き換わり(コンソール幅で折り返しまで入る)、Tee-Objectはこの整形済み
    # 文字列をそのまま$logPathへ書き込む。つまりSelect-Stringの表示フィルタ以前に、
    # **保存ログファイル自体がPythonの本来のトレースバック1行目を失う**
    # (実測: probe_out51.log、KeyError: d2p_skeleton_root報告の再現)。
    # ここで[ErrorRecord]を.Exception.Messageの生テキストへ即座に還元してから
    # Tee-Objectへ渡すことで、保存ログ側は常にBlenderが実際に出力した行を
    # 一字一句のまま残す(表示側のSelect-Stringフィルタは従来どおり進捗表示用
    # に間引いてよい。全文はReport-PhaseFailureがこのログファイルから読み戻す)。
    & $Blender --background --factory-startup --python-exit-code 1 --python (Join-Path $Pipeline "blender\$script") -- $Job @extraArgs 2>&1 |
        ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ }
        } |
        Tee-Object $logPath |
        Select-String -Pattern "\[(step|preview|vp_bl|validate)|FATAL|Error" |
        ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        # 失敗の瞬間の情報をここで使い切る(2026-07-26、失敗時ログ強化)。
        # 上のSelect-Stringフィルタは"Error"部分文字列に依存した偶然の一致に頼って
        # いたため、ここでログ全文を確実に上位ログへ転記する(Report-PhaseFailure)
        Report-PhaseFailure $script $LASTEXITCODE $logPath $__t0
        if ($script -eq "step01_import_vrm.py") {
            # アバター読み込み失敗はflatver101_sunao事例(multi-userメッシュ)の
            # ような「検体固有のリグ構成」由来が多く、検体そのものを貰わずに
            # 診断できるかが受入条件(オーナー: 「どういうログがあればアバターを
            # 貰わなくても診断できましたか?」)。構造ダンプとUnity輸出時の
            # サニタイズ記録を追加でここに合流させる
            try { Invoke-ImportFailureDiag $cfg.vrm_path } catch { Write-Host "[diag] Structure dump itself failed to run (the main failure report continues): $($_.Exception.Message)" }
            try { Write-UnityExportSanitizeHint $cfg.vrm_path } catch { Write-Host "[diag] Failed to relay Unity export log (the main failure report continues): $($_.Exception.Message)" }
        }
        if ($NonFatal) {
            # 2026-07-26(PV班、オーナー裁定): プレビュー画像はサムネイル用の
            # 添え物であり、これが無いことと「MODが作れない」ことでは被害の
            # 大きさが違う(GPU/OpenGLが無い環境=Windows Sandbox実測で
            # WGL_ARB_extensions_string欠落→EXCEPTION_ACCESS_VIOLATIONを確認)。
            # 無言で握りつぶすのは禁止なので、はっきり警告として出したうえで
            # 変換本体は続行させる(呼び出し側が判定できるよう$falseを返す)。
            Write-Host ""
            Write-Host "[WARN] Preview image could not be created, but conversion continues"
            Write-Host "        ($script failed. Possible cause: no GPU/OpenGL available in this environment, or it is broken."
            Write-Host "         Detail log: $(Format-DiagPath $logPath))"
            Write-Host ""
            return $false
        }
        Write-Error "$script failed — see logs"; exit 1
    }
    $elapsed = [math]::Round(((Get-Date) - $__t0).TotalSeconds, 1)
    Write-Host "[$script] OK (${elapsed}s)"
    return $true
}

# dev#288(TOP候補1、work\speed_mission\dag\NOTES.md): Phase1のgender並列化ワーカー。
# step02_retarget.pyとrender_preview.pyはいずれもVRMアドオン(vp_bl.ensure_vrm_addon、
# step01専用)を呼ばず、入出力もgender別に完全分離(step02_{gender}.blend /
# preview_{gender}_*.png)されているため、genderごとに「step02→(成功時のみ)preview」
# という逐次チェーンを、genderの数だけバックグラウンドジョブ(別プロセス)で並列に
# 走らせても安全(2026-07-21のflatv3事件はstep01のVRMインポート特有の共有ユーザー
# プロファイル汚染が原因で、ここには当てはまらない構造的根拠がある)。
# バックグラウンドジョブ(Start-Job)は新規プロセス/ランスペースで動くため、
# convert.ps1本体の関数(Run-Blender等)へは直接アクセスできない。そのため
# Run-Blenderの中核ロジック(Blender起動+2>&1のErrorRecord還元+ログファイルへの
# 書き出し、dev issue #150対策)だけをここに最小限複製する。表示用フィルタ
# (Select-String)とReport-PhaseFailureは、ジョブ完了後に親プロセス側でログ
# ファイルを読み戻して行う(ジョブの標準出力は親コンソールへ直接流れないため)。
# ログファイル名に必ず$Genderを含めること — 含めないと2ジョブが同じファイルへ
# 同時書き込みし、片方のログが失われる/破損する(この関数を作った理由そのもの)。
$script:Phase1GenderWorkerScript = {
    param($Blender, $Pipeline, $JobPath, $LogDir, $Gender)
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONUNBUFFERED = "1"
    $ErrorActionPreference = "Continue"
    $PSNativeCommandUseErrorActionPreference = $false

    function Invoke-BlenderStep([string]$ScriptName) {
        $logPath = Join-Path $LogDir "$($ScriptName -replace '\.py$','')_$Gender.log"
        & $Blender --background --factory-startup --python-exit-code 1 `
            --python (Join-Path $Pipeline "blender\$ScriptName") -- $JobPath $Gender 2>&1 |
            ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ } } |
            Tee-Object $logPath | Out-Null
        return [PSCustomObject]@{ Script = $ScriptName; ExitCode = $LASTEXITCODE; LogPath = $logPath }
    }

    $step02 = Invoke-BlenderStep "step02_retarget.py"
    $preview = $null
    if ($step02.ExitCode -eq 0) {
        $preview = Invoke-BlenderStep "render_preview.py"
    }
    return [PSCustomObject]@{ Gender = $Gender; Step02 = $step02; Preview = $preview }
}

# ここから先はネイティブコマンド中心(成否は$LASTEXITCODEで明示判定する)。
# EAP=Stopのままだと、GUIなど「stderrがリダイレクトされた環境」で
# Blenderのstderr警告がErrorRecord化されて最初の1行で即死する
# (flatv3事件その3: glTF import直後のVRMアドオン警告で毎回死んでいた真因)
$ErrorActionPreference = "Continue"
$PSNativeCommandUseErrorActionPreference = $false

# === Phase 0: バニラ情報の実行時抽出 ===
if (-not $SkipVanilla) {
    # UnrealPak.exeを使うextract_vanilla.pyは呼ばない。参照バニラデータは
    # convert_noue.pyが同梱データから自動で用意する。Blender工程(step02_retarget.py)が
    # vanilla\common_bones.json等をBlender工程の最中に直接参照するため、
    # ここ(Phase 1より前)で先に用意しておく必要がある
    # (U14クリーンルーム検証で発覚: フル変換の最後で用意するのでは遅すぎた)
    #
    # U54(2026-07-26): ここで用意するのは `--stage blender`(Blender工程が読む
    # refskel_*.json / common_bones.json)までにする。複製リストとpak全エントリは
    # pak組み立てとpreflightしか読まないので、convert_noue.pyの本体(Phase 2〜6)で
    # 揃える。これで
    #   ・-PreviewOnly が pakインデックス全走査(18万エントリ)を待たなくなる
    #   ・同じ抽出が1ビルドで2回走っていた二重呼び出しが「段の分担」で解消する
    # キャッシュ判定(再抽出するかどうか)はextract_vanilla.py側にあり、
    # Palworldのpak(mtime+size)が変わっていれば必ず作り直す。
    Write-Host "=== Phase 0: preparing reference vanilla data ==="
    Progress 3 "Fetching game data"
    $__t0 = Get-Date
    $vanillaLog = Join-Path $LogDir "vanilla_ensure.log"
    & $BPython (Join-Path $Pipeline "py\convert_noue.py") --ensure-vanilla --stage blender $Job 2>&1 | Tee-Object $vanillaLog
    if ($LASTEXITCODE -ne 0) {
        Report-PhaseFailure "Phase 0: preparing reference vanilla data" $LASTEXITCODE $vanillaLog $__t0
        Write-Error "Failed to prepare reference vanilla data"; exit 1
    }
    Write-Host ("[Phase 0] OK (" + [math]::Round(((Get-Date) - $__t0).TotalSeconds, 1) + "s)")
}

# === step01キャッシュの鮮度判定(U50: 削除ボーンがプレビューに反映されない不具合) ===
# 背景: -PreviewOnly は converted\step01_clean.blend が在るだけで step01 を丸ごと
# 飛ばしていた。ところが drop_bones(削除ボーン)は step01 の設定なので、
# 削除ボーンを変えてプレビューを作り直しても反映されず、
# 「プレビューは古いまま・フル変換だけ正しい」という食い違いが起きていた
# (フル変換は下の Progress 8 の直後で step01 を無条件実行するため常に正しい)。
#
# 鍵は「job.json 全体」から作り、step01 に効かないと分かっているキーだけを除外する
# (ホワイトリストではなくブラックリスト)。理由は漏れたときの倒れる向き:
#   ブラックリスト漏れ → 余計に step01 が走るだけ(遅いが正しい)
#   ホワイトリスト漏れ → 設定が反映されない(本不具合の再発。しかも気づけない)
# よって将来 step01 に効く設定が増えても、ここを触り忘れて壊れることはない。
$Step01IgnoredKeys = @(
    # step02_retarget.py が読む設定(step01の出力には影響しない)。
    # プレビューのループはこれらを振るためにあるので、除外は必須
    "shoulder_offset_deg", "merge_fingers", "hair_sway", "hair_bones", "sway_cloth_bones",
    # マテリアル工程(Blenderより後段)の設定
    "unlit", "shadow_lift", "force_two_sided",
    # 実行環境・出力先・GUIの記憶用。step01の出力内容を変えない
    "paths", "genders", "engine_mode", "license_confirmed"
)
$Step01SigFile = Join-Path $JobDir "converted\step01_clean.sig"

function Get-Step01Sig {
    # job.jsonはUTF-8(冒頭の$cfg読取と同じ規約。cp932誤読するとキャッシュ鍵が
    # mojibakeから作られ、鮮度判定が壊れる)
    $raw = Get-Content $Job -Raw -Encoding UTF8 | ConvertFrom-Json
    $pairs = @()
    foreach ($p in ($raw.PSObject.Properties | Sort-Object Name)) {
        if ($Step01IgnoredKeys -contains $p.Name) { continue }
        $v = if ($null -eq $p.Value) { "null" } else { ConvertTo-Json -InputObject $p.Value -Compress -Depth 20 }
        $pairs += ($p.Name + "=" + $v)
    }
    # 設定文字列が同じでも、参照している実ファイルが差し替わっていれば作り直す
    foreach ($f in @($raw.vrm_path, $raw.humanoid_json)) {
        if ($f -and (Test-Path $f)) {
            $fi = Get-Item $f
            $pairs += ("file:" + $fi.Name + "=" + $fi.Length + ":" + $fi.LastWriteTimeUtc.Ticks)
        }
    }
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $h = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes(($pairs -join "`n")))
    return ([System.BitConverter]::ToString($h) -replace '-', '')
}

function Test-Step01CacheFresh {
    if (-not (Test-Path (Join-Path $JobDir "converted\step01_clean.blend"))) { return $false }
    if (-not (Test-Path $Step01SigFile)) {
        Write-Host "[step01] Cache key missing, re-running (first time only)"
        return $false
    }
    try { $want = Get-Step01Sig } catch {
        Write-Host "[step01] Could not build cache key; re-running to be safe: $_"
        return $false
    }
    if (((Get-Content $Step01SigFile -Raw).Trim()) -ne $want) {
        Write-Host "[step01] Settings changed since last run; re-running (dropped bones/avatar, etc.)"
        return $false
    }
    return $true
}

function Save-Step01Sig {
    try {
        New-Item -ItemType Directory -Force (Split-Path $Step01SigFile -Parent) | Out-Null
        Set-Content -Path $Step01SigFile -Value (Get-Step01Sig) -Encoding ASCII -NoNewline
    } catch {
        # 保存に失敗しても変換自体は正しい。次回 step01 が余計に走るだけ
        Write-Host "[step01] Failed to save cache key (will re-run next time): $_"
    }
}

# === Phase 1: Blender工程 ===
if ($MaterialsOnly) { $SkipBlender = $true }  # マテリアルのみ: Blender工程は不要
if (-not $SkipBlender) {
    Write-Host "=== Phase 1: Blender pipeline ==="
    $__phase1T0 = Get-Date  # dev#288: Phase1全体の所要秒(並列化の効果測定用)
    if ($PreviewOnly) {
        # プレビューのループ: step01の成果は再利用し、フィット+描画だけ回す。
        # ただし step01 に効く設定が変わっていたら再利用してはならない(上記参照)
        if (-not (Test-Step01CacheFresh)) {
            Progress 10 "Loading avatar"
            Run-Blender "step01_import_vrm.py" @() | Out-Null
            Save-Step01Sig
        }
        Progress 45 "Retargeting skeleton"
        Run-Blender "step02_retarget.py" @("Male") | Out-Null
        Progress 80 "Generating preview image"
        Run-Blender "render_preview.py" @("Male") | Out-Null
        Write-Host "Preview update complete: converted\preview_male_*.png"
        exit 0
    }
    Progress 8 "Loading avatar"
    Run-Blender "step01_import_vrm.py" @() | Out-Null
    Save-Step01Sig   # 次回の -PreviewOnly がこの成果を再利用してよいかの判定材料
    $gbase = @{ Male = 15; Female = 29 }
    # 2026-07-26(PV班): プレビュー画像はサムネイル用の添え物であり、MODが
    # 作れることに比べれば被害が小さい(オーナー・指揮者裁定)。フル変換では
    # render_preview.py の失敗で全体を止めない。失敗した性別は集めておき、
    # 完了メッセージでもう一度まとめて知らせる(ログの途中埋没を避けるため)。
    # 2026-07-26追記: Run-Blenderは$true/$falseを返すようになった(-NonFatal対応)。
    # 戻り値を使わない呼び出しは必ず `| Out-Null` で明示的に捨てる
    # (捨てないと戻り値がログへ"True"として漏れる実害を確認したため)
    $script:PreviewFailedGenders = @()
    if ($Genders.Count -gt 1) {
        # dev#288(TOP候補1): step02_retarget.py/render_preview.pyはgender間で
        # 完全に独立(上のPhase1GenderWorkerScript定義のコメント参照)なので、
        # genderの数だけバックグラウンドジョブで並列に「step02→preview」の
        # 逐次チェーンを走らせる。$Genders.Count -le 1(単一gender指定の
        # job.json)の場合は下のelse節(従来どおりの逐次ループ、変更なし)を使う
        # ——並列化の恩恵が無い上、機構を増やすリスクだけを負うため。
        Progress 15 "Retargeting skeleton + preview (parallel: $($Genders -join ', '))"
        $__jobT0 = Get-Date
        $jobs = foreach ($g in $Genders) {
            Start-Job -Name "d2p_phase1_$g" -ScriptBlock $script:Phase1GenderWorkerScript `
                -ArgumentList $Blender, $Pipeline, $Job, $LogDir, $g
        }
        Wait-Job -Job $jobs | Out-Null
        foreach ($j in $jobs) {
            $r = Receive-Job -Job $j -ErrorAction Stop
            Remove-Job -Job $j -Force
            if ($r.Step02.LogPath -and (Test-Path $r.Step02.LogPath)) {
                Get-Content -Path $r.Step02.LogPath -ErrorAction SilentlyContinue |
                    Select-String -Pattern "\[(step|preview|vp_bl|validate)|FATAL|Error" |
                    ForEach-Object { Write-Host $_ }
            }
            if ($r.Step02.ExitCode -ne 0) {
                Report-PhaseFailure "step02_retarget.py ($($r.Gender))" $r.Step02.ExitCode $r.Step02.LogPath $__jobT0
                Write-Error "step02_retarget.py ($($r.Gender)) failed — see logs"; exit 1
            }
            Write-Host "[step02_retarget.py ($($r.Gender))] OK"
            if ($null -eq $r.Preview) {
                # 通常到達しない(step02失敗時は直前でexitする)が、念のための保険
                $script:PreviewFailedGenders += $r.Gender
                continue
            }
            if ($r.Preview.LogPath -and (Test-Path $r.Preview.LogPath)) {
                Get-Content -Path $r.Preview.LogPath -ErrorAction SilentlyContinue |
                    Select-String -Pattern "\[(step|preview|vp_bl|validate)|FATAL|Error" |
                    ForEach-Object { Write-Host $_ }
            }
            if ($r.Preview.ExitCode -ne 0) {
                # 2026-07-26(PV班、オーナー裁定)と同じ非致命扱い: プレビュー画像は
                # サムネイル用の添え物であり、MODが作れないこととは被害が違う
                Report-PhaseFailure "render_preview.py ($($r.Gender))" $r.Preview.ExitCode $r.Preview.LogPath $__jobT0
                $script:PreviewFailedGenders += $r.Gender
                Write-Host ""
                Write-Host "[WARN] Preview image could not be created for $($r.Gender), but conversion continues"
                Write-Host "        (render_preview.py failed. Possible cause: no GPU/OpenGL available in this environment, or it is broken."
                Write-Host "         Detail log: $(Format-DiagPath $r.Preview.LogPath))"
                Write-Host ""
            } else {
                Write-Host "[render_preview.py ($($r.Gender))] OK"
            }
        }
        Progress 39 "Skeleton + preview complete (parallel)"
    } else {
        foreach ($g in $Genders) {
            $b = if ($gbase.ContainsKey($g)) { $gbase[$g] } else { 15 }
            Progress $b "Retargeting skeleton ($g)"
            Run-Blender "step02_retarget.py" @($g) | Out-Null
            Progress ($b + 10) "Generating preview image ($g)"
            $previewOk = Run-Blender "render_preview.py" @($g) -NonFatal
            if (-not $previewOk) { $script:PreviewFailedGenders += $g }
        }
    }
    Write-Host ("[Phase 1] OK (" + [math]::Round(((Get-Date) - $__phase1T0).TotalSeconds, 1) + "s)")
    # 2026-07-26 SX班: Write-UnityExportSanitizeHintは元々「失敗時ログ強化」
    # (FL班)の一部で、Blender工程が失敗した時にしか呼ばれていなかった。
    # しかし本プロジェクトで最も多い不具合の型は「変換は成功したのに結果が
    # おかしい」(帽子が原点へ落ちる等)であり、その場合はUnity輸出時の
    # サニタイズ記録(どのコンポーネントを何個所から除去したか)こそが
    # 手がかりになりうる。関数自体は無改変(サニタイズ関連行のみ抜粋する
    # フィルタは維持、698KBの生ログを丸ごと出すことはない)。ここでは
    # 成功時にも同じ関数を呼ぶだけ。失敗時の呼び出し(Run-Blender内、
    # step01失敗時)は従来どおり残す(二重には呼ばれない: 失敗時はここへ
    # 到達する前にRun-Blenderがexit 1する)。
    try { Write-UnityExportSanitizeHint $cfg.vrm_path } catch {
        Write-Host "[diag] Failed to relay Unity export log (does not affect the main build): $($_.Exception.Message)"
    }
}

# ★ Mutex解放(PL14、2026-07-27): Phase 1(Blender工程)終了直後。以降の
# Phase 2-6(noue一気通貫ビルド)は作業フォルダが検体ごとに分離済みで
# ロック不要のため、ここでグローバルMutexを手放して他検体の変換と並列に
# 走れるようにする(docs\plan\pl14_mutex_relax.md参照)。$SkipBlenderでPhase 1
# 自体を丸ごと飛ばした場合もこの行には必ず到達するため、その場合も同様に
# ここで解放する(Blenderを使わない=最初から排他不要だったのと同義)。
# 失敗経路(Run-Blender内のexit 1等)はここに到達せずプロセスごと終了するので、
# OSがプロセス終了時に自動解放する(何もしなくてよい、PL14実装手順3)。
try { $script:PipelineMutex.ReleaseMutex() } catch {}
Write-Host "[pipeline] Mutex released after Phase 1"

$Out = Join-Path $JobDir "build"
# === Phase 2〜6(noue): build_pak_from_avatar.py 一気通貫 ===
# UnrealPak.exe/UEエディタは一切呼ばない(U12、docs\REPORT_U11_2026-07-23.mdの
# 完全UE脱却実証チェーンをGUI/CLI共通経路へ統合。dev#114でUEクック経路自体を
# 完全削除し、以降このnoue経路が唯一の実装になった)。テンプレート/参照バニラ/
# preflightはpipeline\py\convert_noue.py内部で完結する(pipeline core無改変)
Write-Host "=== Phase 2-6(noue): build_pak_from_avatar.py end-to-end build ==="
Progress 55 "Generating MOD files"
$__t0 = Get-Date
$noueLog = Join-Path $LogDir "convert_noue.log"
# dev#288 WP-UXIMPL 提案1: 上で定義したRelay-NoueSubphaseProgressをこの
# サブプロセス出力に通す。$script:LastNoueProgressPctをこのビルド開始時点で
# リセットしてから走らせる(前回ビルドの値を持ち越さない)。
# パイプ構成の意図(dev issue #150のRun-Blenderと同じ手当てを踏襲):
#   1) ErrorRecordを生テキストへ還元(stderr合流時にNativeCommandError整形で
#      ##PROGRESS##/NoueSubphase等のマーカー文字列が壊れて検出漏れするのを防ぐ、
#      かつ保存ログ($noueLog)がBlender同様に生テキストのまま残るようにする)
#   2) Relay-NoueSubphaseProgressへ渡す(側作用のみ、パイプラインには何も出さない)
#   3) $lineをそのまま次段へ流す(既存どおり全行がTee-Object経由でログ保存+
#      GUI/コンソールの標準出力へ届く。ここで行を削ると既存のログ可視性が
#      失われるため、フィルタはしない)
$script:LastNoueProgressPct = 0
& $BPython (Join-Path $Pipeline "py\convert_noue.py") $Job 2>&1 |
    ForEach-Object {
        $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ }
        Relay-NoueSubphaseProgress ([string]$line)
        $line
    } |
    Tee-Object $noueLog
if ($LASTEXITCODE -ne 0) {
    Report-PhaseFailure "Phase 2-6(noue): end-to-end build" $LASTEXITCODE $noueLog $__t0
    Write-Error "noue build failed — see log above"; exit 1
}
Write-Host ("[noue build] OK (" + [math]::Round(((Get-Date) - $__t0).TotalSeconds, 1) + "s)")
$ModPak = Join-Path $Out "${Avatar}_PlayerSwap_P.pak"
# 提案3(dev#288): 96%はpreflightが既にconvert_noue.py内部で完了済みの事後表示
# であり、旧文言「Final check (preflight already run inside convert_noue.py)」は
# 「これから最終チェックをする」という誤解を招いていた(PROPOSAL.md 2.4節)。
# 「終わった直後の後処理をしている」ことが伝わる文言へ変更(表示のみ、判定ロジック無変更)。
Progress 96 "Packaging complete, verifying result"

Write-Host ""
Write-Host "=== Done ==="
Write-Host "pak: $ModPak"
Write-Host "Install location: copy directly into <Palworld>\Pal\Content\Paks\ (while the game is closed)"
Write-Host "Uninstall: just delete the copied pak file"
if ($script:PreviewFailedGenders -and $script:PreviewFailedGenders.Count -gt 0) {
    # 2026-07-26(PV班): 完了メッセージの目立つ位置でもう一度触れる。ログの
    # 途中に出た警告は流し読みで見落とされうるため、「MODは正常に出来た。
    # ただしプレビュー画像だけ無い」ことを最後に明示する(非エンジニア向け)
    Write-Host ""
    Write-Host "[NOTE] Preview image could not be created ($($script:PreviewFailedGenders -join ', '))."
    Write-Host "       The MOD itself (pak) was created successfully. Missing the preview image does not affect usability."
}
Write-Host ("Total elapsed time: " + [math]::Round(((Get-Date) - $script:__ScriptT0).TotalSeconds, 1) + "s")
