# BOOTH配布用フルセットzipを作る
# 使い方: pwsh -File make_dist.ps1 [-Version v0.1.0] [-Suffix _NEWLAYOUT]
# 出力: dist\Uchinoko_<Version>_full<Suffix>.zip
# (v2.0.0改名: ユーザー可視面のみ Uchinoko for Palworld。ソース・内部名はDiveToPalworldのまま。
#  dev#625(2026-08-01オーナー裁定): 出力zipのファイル名を次リリースから
#  Uchinoko_for_Palworld_<Version>_full<Suffix>.zip から
#  Uchinoko_<Version>_full<Suffix>.zip へ短縮。zip内部のステージングフォルダ名
#  $Stage(Uchinoko_for_Palworld)はこの変更の対象外、従来どおり)
#
# 2026-08-01(dev#532 D1、方針A統合): C#/WinForms(app\DiveToPalworld.cs +
# app\build_app.ps1、csc.exeビルド)からPython/tkinter版(app_py\、
# app_py\build.py、embeddable Python + tkinter同梱)へ全面切替。
# dev#532コメント列の拘束条件により配布レイアウトも変わった:
#   旧: zipルート直下に Uchinoko.exe / README.md / manual.html / pipeline\ /
#       unity\ / assets\ / LICENSE / THIRD_PARTY_LICENSES.txt が並ぶ(exeが
#       唯一のエントリポイント)
#   新: zipルート直下は **Uchinoko.bat / README.txt / res\ の3点のみ**。
#       pipeline\/unity\/assets\/licenses\は全てres\配下(=appRoot、
#       app_py\main.py._resolve_app_root()がpythonランタイムの1つ上として
#       解決する場所)へ移動。マニュアルHTMLは同梱しない(オンラインURLを
#       README.txtに記載、app_py\build.py.README_TEMPLATE参照)。
# 実体のダウンロード(embeddable Python)・tkinter抽出・app_py\/pipeline\/
# unity\/assets\の梱包・ライセンス集約・bat生成・署名ゲート・レイアウトゲート
# は全て app_py\build.py 側に実装済み(dev#532 WP-B1+D1)。このps1はもう
# 「ステージングを組み立てる」役ではなく、**build.pyを呼んでzip化するだけの
# 薄い殻**になった(CLAUDE.md言語方針「新規コードは迷ったらPython」の踏襲。
# 既存ps1は動いている限り書き直さない、が今回はレイアウトそのものが
# 変わるため実質新規)。
#
# 旧C#資産(app\DiveToPalworld.cs / app\build_app.ps1)自体はリポジトリに
# 温存する(dev#532統合WP完了後に別途削除判断、本WPでは削除しない)。
#
# dev#260: -Channel は完全に省略可能(既定は何も書かない=既存zipと100%互換)。
# devtools\release.py からの呼び出しは変更しておらず、-Channelを渡さないため
# canonical zip(検証・sha256記録の対象)は従来どおりマーカー無しのまま出荷される。
# BOOTH/itch向けの実際のチャネル書き分けは devtools\stamp_channel.py が
# このcanonical zipを受け取って別名の(channel.txt入り)zipを作る後段の工程で行う。
# channel.txt はステージングフォルダ直下(=Uchinoko.bat/res\と同じ階層。
# stamp_channel.pyの書き込み先、app_py\dist_channel.pyのD1追記フォールバック参照)。
#
# W22(2026-07-31): -StageOnly/-OutDir。.devonly\HumanTest\ 等が独自ミラーを
# 持たず、本スクリプト本体に -StageOnly -OutDir <path> で委譲できるようにする。
# -StageOnly: 指定時はzip化を省略し、ステージ結果をそのまま使う(dist\には書かない)
# -OutDir: -StageOnly指定時のみ有効。ステージ結果のコピー先
param([string]$Version = "v1.0.0", [string]$Suffix = "", [ValidateSet("booth", "itch", "github", "dev")][string]$Channel = "", [switch]$StageOnly, [string]$OutDir = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Stage = Join-Path $Root "dist\stage\Uchinoko_for_Palworld"
$OutZip = Join-Path $Root "dist\Uchinoko_${Version}_full${Suffix}.zip"

# dev#532 D1: バージョン整合チェック(FRESH_QAレビュー3-9恒久対策、旧U28)。
# app_py\ui\main_window.py の TOOL_VERSION と本スクリプトの $Version が
# 食い違ったままzipを作ると、配布物内部の表示バージョンとzipファイル名/
# 呼び出し引数がズレた状態で出荷されてしまう(過去の実害はまだ無いが構造的リスク)。
Write-Host "=== バージョン整合チェック ==="
$MainWindowPyPath = Join-Path $Root "app_py\ui\main_window.py"
$MainWindowPyContent = Get-Content $MainWindowPyPath -Raw
$VersionMatch = [regex]::Match($MainWindowPyContent, 'TOOL_VERSION\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) { Write-Error "app_py\ui\main_window.py内にTOOL_VERSION定数が見つからない"; exit 1 }
$PyVersion = $VersionMatch.Groups[1].Value
# W22(2026-07-31): -StageOnly利用時、呼び出し側が-Versionを明示していない
# (既定値のままの)場合に限りTOOL_VERSIONへ自動追随する。
if ($StageOnly -and $Version -eq "v1.0.0") {
    $Version = $PyVersion
    $OutZip = Join-Path $Root "dist\Uchinoko_${Version}_full${Suffix}.zip"
}
if ($PyVersion -ne $Version) {
    Write-Error "バージョン不一致: app_py\ui\main_window.py の TOOL_VERSION='$PyVersion' に対し make_dist.ps1 の `$Version='$Version'。一致させてから再実行してください(-Version引数 または TOOL_VERSION定数を修正)"
    exit 1
}
Write-Host "  OK: TOOL_VERSION = $Version"

Write-Host "=== ステージング(app_py\build.py) ==="
Remove-Item (Join-Path $Root "dist\stage") -Recurse -Force -ErrorAction SilentlyContinue
$StageParent = Split-Path $Stage -Parent
New-Item -ItemType Directory -Force $StageParent | Out-Null

# app_py\build.pyが実ペイロード一式(python_embed+tkinter同梱+app_py本体+
# pipeline\+unity\+assets\third_party・blender_patch+res\licenses\+Uchinoko.bat+
# README.txt)を組み立てる。--fixtureは付けない(WP-A1完了済みの実app_pyを使う)。
# 署名ゲート(自作PE=0)・zipルート3点レイアウトゲート・bat環境隔離ゲート・
# ._pth内容ゲートもbuild.py内で実行され、いずれか1つでもFAILならexit 1で
# ここで打ち切られる(make_dist.ps1側で重複実装しない)。
python (Join-Path $Root "app_py\build.py") --out $Stage
if ($LASTEXITCODE -ne 0) { Write-Error "app_py\build.py が失敗した(BUILD=FAIL、上のログ参照)"; exit 1 }

# dev#260が明示された場合のみ、ステージングフォルダ直下(=Uchinoko.bat/res\と
# 同じ階層)にマーカーを書く。省略時(既定)は一切書かないため、ここから先も
# 含めてrelease.pyが呼ぶ既定経路の出力は変化しない。
if ($Channel) {
    Write-Host "=== 配布チャネルマーカーの書き込み ($Channel) ==="
    Set-Content -Encoding utf8 (Join-Path $Stage "channel.txt") $Channel
}

# W22(2026-07-31): -StageOnly指定時はここでzip化をスキップして早期終了する。
if ($StageOnly) {
    Write-Host "=== StageOnly: zip化を省略しステージ結果を配置 ==="
    if ($OutDir) {
        $Dest = Join-Path $OutDir "Uchinoko_for_Palworld"
        Remove-Item $Dest -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force $OutDir | Out-Null
        Copy-Item $Stage $Dest -Recurse
        Write-Host "OutDir = $Dest"
    }
    else {
        Write-Host "Stage = $Stage (OutDir未指定のためコピーなし)"
    }
    Remove-Item (Join-Path $Root "dist\stage") -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}

Write-Host "=== zip作成 ==="
New-Item -ItemType Directory -Force (Join-Path $Root "dist") | Out-Null
Remove-Item $OutZip -ErrorAction SilentlyContinue
Compress-Archive -Path $Stage -DestinationPath $OutZip -CompressionLevel Optimal
Remove-Item (Join-Path $Root "dist\stage") -Recurse -Force

Write-Host ""
Write-Host ("完成: {0} ({1:F0} MB)" -f $OutZip, ((Get-Item $OutZip).Length / 1MB))
Write-Host "BOOTHへアップロードしてください(1ファイル1GB上限内)"
