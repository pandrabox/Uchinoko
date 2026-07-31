# BOOTH配布用フルセットzipを作る(Blenderポータブル同梱・約390MB)
# 使い方: pwsh -File make_dist.ps1 [-Version v0.1.0] [-Suffix _NEWLAYOUT]
# 出力: dist\Uchinoko_for_Palworld_<Version>_full<Suffix>.zip
# (v2.0.0改名: ユーザー可視面のみ Uchinoko for Palworld。ソース・内部名はDiveToPalworldのまま)
#
# 2026-07-31: ランチャー廃止・配布レイアウトのフラット化。
# 旧レイアウト(zipルートを「exe / _internal\ / README.md」の3点だけにし、
# ルートのexeは_internal\Uchinoko.exeを起動するだけの小さなラッパー=ランチャー、
# だった)を廃止した。根拠: Mark-of-the-Web付与済み実測で、ランチャーだけが
# AV誤検知の白黒くじ引き(同一ソースでもビルドごとに検出/非検出が入れ替わる)を
# 起こし、本体exeは全測定で無傷だった(構造要因: 「署名なしexeが自分の隣のファイルを
# 書き換えてから別のexeをProcess.Startする」というドロッパー/ローダーの教科書的な形)。
# v2.2.11がAV誤検知で配布3チャネル全滅した事故を受け、オーナーの提案で設計・実装した。
#
# 新レイアウト: zipルート直下に本体exe一式をそのまま置く(_internal\という
# 1階層の入れ子を廃止)。本体exe(Uchinoko.exe)が配布物の唯一のexeであり、
# エントリポイントそのものになる。この構成でも app\DiveToPalworld.cs の appRoot解決
# (= Path.GetDirectoryName(Application.ExecutablePath) 直下に pipeline\ がある)
# も、pipeline\配下の $PSScriptRoot / REPO_DIR=dirname(pipeline) 相対解決も
# 従来どおりそのまま成立する(pipeline\がexeの直接の兄弟になる点は変わらないため、
# コア部分のパス解決コードの改修は不要)。
# 旧ランチャー(app\Launcher.cs、ApplyEngine)のソース自体はリポジトリに温存する
# (将来のC案=自己更新の自己再起動化、復活時にそのまま使える契約として)。
# 本スクリプトはもうそれを読み込まない・コンパイルしない・zipに含めない。
#
# dev#260: -Channel は完全に省略可能(既定は何も書かない=既存zipと100%互換)。
# devtools\release.py からの呼び出しは変更しておらず、-Channelを渡さないため
# canonical zip(検証・sha256記録の対象)は従来どおりマーカー無しのまま出荷される。
# BOOTH/itch向けの実際のチャネル書き分けは devtools\stamp_channel.py が
# このcanonical zipを受け取って別名の(channel.txt入り)zipを作る後段の工程で行う
# (release.pyのzip内容ゲートを3倍走らせずに済ませるための設計、dev#260参照)。
# ここに-Channelを残すのは、開発用に直接dev印のzipを作りたい場合の利便のためだけで、
# 通常の公開フローでは使わない。
# (注記: devtools\stamp_channel.pyはこの改修の対象外のため
# 未改修の場合がある。旧レイアウト前提のまま_internal\へchannel.txtを書き続けている
# 可能性があり、その場合は追随が必要。fail-closed設計によりチャネル不明="unknown"に
# 倒れるだけで、変換・起動自体は損なわれない)
# W22(2026-07-31): -StageOnly/-OutDir を追加。.devonly\HumanTest\ が独自ミラー
# (_tools\make_dist_humantest.ps1、2026-07-29時点の複製で7/31のランチャー廃止に
# 追随せず旧2exe構成を作り続けていた)を持っていた問題への対処。ミラー複製を廃止し、
# HumanTest道具は本スクリプト本体に -StageOnly -OutDir <path> で委譲する薄い殻へ
# 作り替える(いずれのオプションも未指定時の挙動には一切影響しない=既定動作は不変)。
# -StageOnly: 指定時はzip化を省略し、ステージ結果をそのまま使う(dist\には書かない)
# -OutDir: -StageOnly指定時のみ有効。ステージ結果のコピー先
param([string]$Version = "v1.0.0", [string]$Suffix = "", [ValidateSet("booth", "itch", "github", "dev")][string]$Channel = "", [switch]$StageOnly, [string]$OutDir = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Stage = Join-Path $Root "dist\stage\Uchinoko_for_Palworld"
$OutZip = Join-Path $Root "dist\Uchinoko_for_Palworld_${Version}_full${Suffix}.zip"

# u54(2026-07-27): Blenderポータブルの同梱を廃止した。配布zipにはBlender本体を
# 含めず、初回起動時に pipeline\cli\ensure_blender.ps1 が公式サイトから取得する
# (配布容量408MB→約9割を占めていたBlenderポータブル989MBが主因だった)。
# そのためmake_dist.ps1自体はもうBlenderポータブルの実体を必要としない
# (旧: tools\ / D2P_BLENDER_DIR からの探索+同梱処理。下の「pyooz/python3.dllの
# 差し込み素材同梱」節でensure_blender.ps1が使う小容量の差し込み素材だけを用意する)。

# U28: バージョン整合チェック(FRESH_QAレビュー3-9恒久対策)。
# app\DiveToPalworld.cs の ToolVersion と本スクリプトの $Version が食い違ったまま
# zipを作ると、配布物内部の表示バージョンとzipファイル名/呼び出し引数が
# ズレた状態で出荷されてしまう(過去の実害はまだ無いが構造的リスク)。
# 機械チェックとしてビルド前に強制検証する
Write-Host "=== バージョン整合チェック ==="
$CsPath = Join-Path $Root "app\DiveToPalworld.cs"
$CsContent = Get-Content $CsPath -Raw
$VersionMatch = [regex]::Match($CsContent, 'const\s+string\s+ToolVersion\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) { Write-Error "app\DiveToPalworld.cs内にToolVersion定数が見つからない"; exit 1 }
$CsVersion = $VersionMatch.Groups[1].Value
# W22(2026-07-31): -StageOnly利用時、呼び出し側が-Versionを明示していない
# (既定値のままの)場合に限り ToolVersion へ自動追随する。HumanTest道具は
# 「今のソースの実物」を人間が触るための道具であり、バージョン番号の一致を
# 都度手で合わせさせる理由がない。-Versionを明示指定した場合は
# 従来どおり厳密一致を要求する(既定動作=引数なし呼び出しは完全不変)。
if ($StageOnly -and $Version -eq "v1.0.0") {
    $Version = $CsVersion
}
if ($CsVersion -ne $Version) {
    Write-Error "バージョン不一致: app\DiveToPalworld.cs の ToolVersion='$CsVersion' に対し make_dist.ps1 の `$Version='$Version'。一致させてから再実行してください(-Version引数 または ToolVersion定数を修正)"
    exit 1
}
Write-Host "  OK: ToolVersion = $Version"

Write-Host "=== ステージング ==="
Remove-Item (Join-Path $Root "dist\stage") -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Stage | Out-Null

# GUIをステージング(=配布物ルート)へ直接ビルド(起動中のexeに触らない — ロック事故防止)
# exe実体はもう_internal\へ隠さず、配布物ルート直下に直接置く。
# こうすると appRoot=$Stage となり、pipeline\ / assets\ / research\ / unity\ /
# work\ / settings_*.txt の相対関係は(_internal\という1階層が無くなること以外は)
# 従来のappRoot基準の相対解決とまったく同じになる(コード改修不要)。
& pwsh -File (Join-Path $Root "app\build_app.ps1") -Out (Join-Path $Stage "Uchinoko.exe")
if ($LASTEXITCODE -ne 0) { exit 1 }

# 2026-07-31: ルート用ランチャーexeのビルドを廃止した。
# 旧: ルートのUchinoko.exe = _internal\Uchinoko.exe を起動するだけの小さな
# ラッパー(ソースはapp\Launcher.cs)をここでcsc.exeビルドしていたが、実測で
# このランチャーだけがAV誤検知の主要因(署名なしexeが隣のファイルを書き換えてから
# 別exeをProcess.Startする、というドロッパー/ローダーの教科書的な形)と判明した
# ため廃止し、本体exe自身を配布物の唯一のexe・エントリポイントにした。
# app\Launcher.cs / app\LauncherAssemblyInfo.cs のソース自体はリポジトリに温存する
# (将来、自己更新の自己再起動化として復活する可能性があり、そのときにそのまま
# 使える契約として)。このスクリプトはもうそれらを読み込まない・コンパイルしない・
# zipに含めない。
# README.md / manual.html をルートに残す(ユーザーが最初に読むもの)。
# LICENSE / THIRD_PARTY_LICENSES.txt も配布物ルート直下に同梱する
# (MIT/GPLv3ともに「配布物に添付されていること」が要件であり、ルート直下である
#  必要はない。ライセンス本文・適用範囲・third_party\の同梱内容は一切変更していない)
#
# dev#444(2026-07-31): manual\manual.html はこれまで手打ちの静的ファイルで、
# manual\manual.md からの自動生成経路が存在しなかった。そのためmanual.mdを
# 直しても配布物には一切反映されない構造的欠陥があった(実例: AV誤検知に
# ついての開示節が一度もユーザーに届いていなかった)。ここでコピー直前に
# devtools\gen_manual_html.py を実行し、manual.md/manual.en.mdの現在の内容から
# manual.html/manual.en.htmlを再生成してから同梱する(単一の出所=manual*.md、
# 以後の修正が自動的に配布物へ届く)。英語版も同じ仕組みで生成・同梱する
# (日本語を読めないユーザーにも説明が届くようにするため)。
Write-Host "=== manual.html生成(manual.mdから、dev#444) ==="
python (Join-Path $Root "devtools\gen_manual_html.py")
if ($LASTEXITCODE -ne 0) { exit 1 }
Copy-Item (Join-Path $Root "README.md") $Stage
Copy-Item (Join-Path $Root "manual\manual.html") $Stage
Copy-Item (Join-Path $Root "manual\manual.en.html") $Stage
Copy-Item (Join-Path $Root "LICENSE") $Stage
# U44: zipルート簡素化。pipeline\/unity\は直下のまま
# (根拠: pipeline\はtests\shipcheck\gates.py・README.mdのCLI手順が
#  "<配布物ルート>\pipeline\cli\convert.ps1" を固定パスで前提にしており、
#  unity\はpipeline\cli\export_from_unity.ps1の$Root相対解決
#  (このファイルも書き込み許可対象外)がpipeline\の直接の兄弟を要求する。
#  一方third_party\/tools\はjob.json経由(app\DiveToPalworld.csが解決)でしか
#  参照されないため安全に移動でき、assets\配下へ集約した(4節フォルダ→2節分削減)。
#  ico\は同梱そのものを廃止(下記参照)。詳細根拠はdocs\REPORT_U44_2026-07-25.md)
# (2026-07-31: 旧レイアウトで導入した_internal\という1階層の入れ子は廃止した。
#  pipeline\/unity\の相互の相対関係は変えず、配布物ルート直下へ直接置く)
# (U51: research\ue_exit\の実行時依存6ファイルをpipeline\py\へ移設したため、
#  research\は配布物に一切不要になった。以前はここでpipeline\/unity\と並んで
#  research\ue_exit\の一部だけを個別梱包していたが、その処理は削除した
#  — 下の「U14(廃止、U51で移設完了)」コメント参照)
foreach ($d in @("pipeline", "unity")) {
    Copy-Item (Join-Path $Root $d) (Join-Path $Stage $d) -Recurse
}

# 2026-07-25: 「影のみ更新」は convert.ps1 -MaterialsOnly → pipeline\py\fast_repack.py
# という経路で動く(noueモード)。2026-07-26: fast_repack.py はdevtools\から
# pipeline\py\へ移設済み(devtools\全体は非公開のため、出荷物側の実行時
# コンポーネントを置けない)。したがって上のforeach($d in @("pipeline","unity"))が
# pipeline\を丸ごとコピーする時点でfast_repack.pyも自動的に含まれる。
# 個別コピー・devtools\フォルダの作成はもう不要(旧実装はここで別途コピーしていた)。
New-Item -ItemType Directory -Force (Join-Path $Stage "assets") | Out-Null
Copy-Item (Join-Path $Root "third_party") (Join-Path $Stage "assets\third_party") -Recurse
# 梱包しない開発物の掃除
Remove-Item (Join-Path $Stage "pipeline\cli\smoke_all.ps1") -ErrorAction SilentlyContinue

# U14(廃止、U51で移設完了): かつてbuild_pak_from_avatar.pyがresearch\ue_exit\の
# 一部を直接import/subprocessしており、実行時に必要な6ファイル
# (dump_avatar_mesh.py/build_avatar_variant.py/build_avatar_variant_all.py/
# parse_sk_structure.py/parse_sk_full.py/parse_uasset_header.py)だけをここで
# 個別に梱包していた。U51でこれら6ファイルをpipeline\py\へ実体移設し(research\
# ue_exit\側は開発参照用に残置、無改変)、参照元(build_pak_from_avatar.py/
# live_template.py/preflight_pak.py/vp_matparam.py)もpipeline\py\の同居ファイルを
# 直接importするよう更新した。よって上のforeach(pipeline\をまるごとコピー)で
# 既にこの6ファイルも含まれており、research\ue_exit\の個別梱包は不要になった
# (=リポジトリのresearch\を配布物に一切含めなくても変換が完走する)。

# U18: 旧U14方式(開発側で一度cookしたPalworld本体由来の443ファイルテンプレを
# zipへ直接梱包)は廃止。テンプレート資産(vanilla由来)はPalworld本体
# (Pocketpair社の著作物)を含むため配布不可と判明したため(docs\ISSUES.md 2節、
# docs\REPORT_U18_2026-07-23.md参照)。既定noue経路は変換の都度ユーザー自身の
# Palworldインストールからライブ抽出する設計になり(pipeline\py\live_template.py/
# pak_live_extract.py、上のforeachで既にpipeline一式に含まれる)、事前cook済み
# テンプレフォルダの同梱は不要になった。プロジェクト独自資産(恒久マスター4種・
# noue_variants等、Palworld著作物ではない)は`pipeline\py\noue_master\`に
# 同梱済みで、pipelineディレクトリ丸ごとコピー(上のforeach)で既に含まれている

# U18: pyooz(GPLv3+、Oodle互換解凍。ooz_worker_gpl.py経由でsubprocess起動、
# 本体からimportしない)の実行環境を同梱。以下2点が無いとBlender同梱Python単独
# では`import ooz`が失敗すると判明(python3.dll不在によるDLL load failed):
#   ① ooz.pyd + 配布メタデータ(pyoozパッケージそのもの)をBlender同梱Pythonの
#      site-packagesへ配置(以後 sys.executable=Blender同梱pythonでそのままimport可能、
#      pak_live_extract.py._resolve_ooz_python()の②候補がここで解決する)
#   ② python3.dll(stable ABI用リダイレクタ。CPython公式配布物の一部、PSFライセンス、
#      ooz.pydがstable ABIビルドのため依存する。Blender同梱Pythonにはpython311.dllのみで
#      python3.dllが無いためDLL解決に失敗する。python.org公式配布のPython 3.11
#      python\bin\へ1ファイル追加するだけで解決、実機確認済み)
# 複雑なパッケージング技術(exe化等)は使わず、最も単純な形(ソース/バイナリ一式の
# ファイルコピー)に留める(0節聖域条項、指示書付録参照)
Write-Host "=== pyooz(GPLv3+、Oodle互換解凍)の同梱 ==="
$OozSitePkgSrc = "$env:APPDATA\Python\Python313\site-packages"
$OozPyd = Join-Path $OozSitePkgSrc "ooz.pyd"
if (-not (Test-Path $OozPyd)) { Write-Error "ooz.pydが見つからない: $OozPyd (pip install pyoozが必要)"; exit 1 }
# 2026-07-26: 開発機ユーザー名決め打ちパスを撤廃。$env:LOCALAPPDATAは呼び出したユーザーの
# AppData\Localへ自動解決されるため、python.orgの既定インストール先(ユーザー単位)であれば
# 誰の環境でもこの1行だけで足りる。既定と異なる場所に入れている場合は
# D2P_PYTHON311_DLL で明示指定できるようにした。
$Python3Dll = @(
    $env:D2P_PYTHON311_DLL,
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python3.dll")
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Python3Dll) {
    Write-Error (
        "python3.dll(Python 3.11版)が見つからない。`n" +
        "入手方法: https://www.python.org/downloads/release/python-3110/ (python.org公式)から" +
        "Windows installer (64-bit)を取得し、Python 3.11をインストールする" +
        "(python3.dllは同梱される)。`n" +
        "配置方法(いずれか一方):`n" +
        "  (1) 既定の場所(python.orgインストーラの既定: " +
        "%LOCALAPPDATA%\Programs\Python\Python311\python3.dll)にインストールする`n" +
        "  (2) python3.dllのフルパスを環境変数 D2P_PYTHON311_DLL に設定する`n" +
        "      例: `$env:D2P_PYTHON311_DLL = 'C:\path\to\Python311\python3.dll'"
    )
    exit 1
}

# u54(2026-07-27): Blender本体の同梱をやめ、代わりに ensure_blender.ps1 が
# 初回起動時に使う「差し込み素材」だけを小容量で同梱する。
# 旧実装(このすぐ上のコメント参照)はここでBlenderポータブル一式(989MB)を
# コピーしてから、その中のPython環境へooz.pyd/pyooz dist-info/python3.dllを
# 差し込み、続けてVC++ランタイム3本もBlender自身のblender.crt\から複製していた。
# 新実装ではBlenderの実体が無い(ダウンロードは初回起動時)ため、Blenderの
# Python環境への差し込みそのものができない。そこで「差し込む中身」だけを
# assets\blender_patch\ へ小容量(ooz.pyd + dist-info + python3.dll、
# 合計200KB弱)で同梱し、実際の差し込み(コピー先ディレクトリへの配置)は
# ensure_blender.ps1がダウンロード直後のBlenderに対して行う
# (pipeline\cli\ensure_blender.ps1 参照。VC++ランタイム3本はここでは同梱しない。
#  ダウンロードするBlender自身のblender.crt\に元々含まれているため、
#  ensure_blender.ps1がその場で複製する=新規追加なし、の方針を維持)。
Write-Host "=== blender_patch素材の同梱(ooz.pyd/pyooz dist-info/python3.dll) ==="
$BlenderPatchDir = Join-Path $Stage "assets\blender_patch"
New-Item -ItemType Directory -Force $BlenderPatchDir | Out-Null
Copy-Item $OozPyd (Join-Path $BlenderPatchDir "ooz.pyd") -Force
Get-ChildItem $BlenderPatchDir -Directory -Filter "pyooz-*.dist-info" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $OozSitePkgSrc "pyooz-*.dist-info") $BlenderPatchDir -Recurse
Copy-Item $Python3Dll (Join-Path $BlenderPatchDir "python3.dll") -Force
Write-Host "  ooz.pyd / pyooz-*.dist-info / python3.dll -> $BlenderPatchDir"

# U18: GPLv3+第三者コンポーネント(ooz_worker_gpl.py本体+pyooz)の存在とライセンスを明記
Write-Host "=== THIRD_PARTY_LICENSES.txt の作成 ==="
@"
DiveToPalworld本体は MIT License(LICENSE参照)です。

以下のコンポーネントはGPLv3+ (GNU General Public License v3 or later) であり、
本体からは常にsubprocess経由でのみ起動されます(importもリンクもしない、
"mere aggregation"構成。ffmpeg.exe等の外部実行ファイルをMITツールが
subprocessで呼ぶのと同じ扱いです)。

1. pipeline\py\ooz_worker_gpl.py
   本体からpyoozを呼び出すための単独完結した別プロセス実行体。
   ライセンス: GPLv3 (ファイル冒頭のヘッダ参照)

2. pyooz (初回起動時にダウンロードするBlenderの
   python\lib\site-packages\ooz.pyd等へ配置。差し込み素材そのものは
   assets\blender_patch\ooz.pyd に小容量で同梱)
   Oodle互換解凍ライブラリoozのPythonバインディング。
   配布元: https://pypi.org/project/pyooz/ (https://github.com/zao/pyooz)
   ライセンス: GPLv3+ (GNU General Public License v3 or later)

GPLv3全文: https://www.gnu.org/licenses/gpl-3.0.txt

Blender Portable(GPL、公式配布に GPL-3.0-or-later.txt / GPL-2.0-or-later.txt 同梱)は
この配布物(zip)には含まれません。初回起動時にツールが公式サイト
(https://www.blender.org/download/) から自動的にダウンロードし、
assets\tools\ に配置します(SHA256をピン留めして照合。
pipeline\cli\ensure_blender.ps1 参照)。

python3.dll(初回起動時にダウンロードするBlenderの
python\bin\python3.dll へ配置。差し込み素材そのものは
assets\blender_patch\python3.dll に同梱)は
CPython公式配布物の一部(PSFライセンス)です。 https://www.python.org/

vcruntime140.dll / vcruntime140_1.dll / msvcp140.dll(初回起動時にダウンロードする
Blenderのpython\bin\および python\lib\site-packages\に配置)はMicrosoft Visual
C++ Redistributableの一部です。この配布物(zip)には含まれません。新規に追加
するものではなく、初回起動時にダウンロードするBlenderポータブル本体
(blender.crt\)が元々再頒布している実体を、そのまま複製配置するだけです
(2026-07-26追加、Windows Sandboxでのpython.exe起動失敗対策。u54でBlender
本体の取得タイミングが変わった後も複製元・複製内容は不変)。
"@ | Set-Content -Encoding utf8 (Join-Path $Stage "THIRD_PARTY_LICENSES.txt")

# U28: 開発残骸の除外(FRESH_QAレビュー3-7)。pipeline\をCopy-Item -Recurseで
# 丸ごとコピーしているため開発中の*.bak系ファイルが混入する事故クラスが判明。
# (u54でBlenderポータブル本体の同梱自体を廃止したため、旧来の「梱包する
# Blenderポータブル自体に付着した__pycache__」という混入経路は無くなったが、
# pipeline\の__pycache__混入経路は変わらず残るため、本チェック自体は維持する)
# 本チェックはblender_patch素材同梱が終わった後・zip作成直前(ステージング全体が
# 揃った時点)で実行する。パターンは監査(devtools\u28_zip_audit.py)と
# 同じ根拠で選定。過剰除外を避けるため、正式に必要なファイルを指す
# パターンにはしていない(例: *.jsonのような広いパターンは使わない)
Write-Host "=== 開発残骸の除外(ステージング全体) ==="
$ResidueDirFilters = @("__pycache__", ".pytest_cache")
foreach ($filt in $ResidueDirFilters) {
    Get-ChildItem $Stage -Recurse -Directory -Filter $filt -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
# 「*_diag」で終わる作業ディレクトリ(u21_diag等、本来work\配下限定だが
# 将来pipeline\配下に迷い込む事故に備えた防御的除外)
Get-ChildItem $Stage -Recurse -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*_diag" } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$ResidueFileFilters = @("*.bak", "*.bak_*", "*.bak2_*", "*.orig", "*.log")
foreach ($filt in $ResidueFileFilters) {
    Get-ChildItem $Stage -Recurse -File -Filter $filt -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

# dev#260: -Channelが明示された場合のみ、appRoot直下(ランチャー廃止以降は
# 配布物ルート直下=$Stageそのもの。app\DiveToPalworld.csのappRootは実行exeの
# 場所と一致する)にマーカーを書く。省略時(既定)は一切書かないため、
# ここから先も含めてrelease.pyが呼ぶ既定経路の出力は変化しない。
if ($Channel) {
    Write-Host "=== 配布チャネルマーカーの書き込み ($Channel) ==="
    Set-Content -Encoding utf8 (Join-Path $Stage "channel.txt") $Channel
}

# W22(2026-07-31): -StageOnly指定時はここでzip化をスキップして早期終了する。
# -OutDir指定があればステージ結果(展開済みレイアウトそのもの)をそこへコピーする
# (dist\には一切書き込まない)。-StageOnly未指定時はこのブロックを素通りし、
# 以降の既存のzip作成処理へそのまま進む(既定動作は不変)。
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
