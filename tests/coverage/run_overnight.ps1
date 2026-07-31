<#
.SYNOPSIS
  U53 カバレッジ検査を無人で一晩回す(1コマンド)。

.DESCRIPTION
  これ1本で完結する。途中で人の操作を求めない。

    pwsh -NoProfile -File tests\coverage\run_overnight.ps1

  dev#127(2026-07-29、夜間カバレッジの並列化): 本体ロジックは
  `tests\coverage\run_overnight.py` へ移した(CLAUDE.md言語方針「新規コードは
  迷ったらPython」)。このps1は引数を素通しするだけの殻。

  * 実変換は行う(--allow-convert)。既定(検体ごと独立作業フォルダ+
    pytest-xdist 並列、-n 3 既定)なら 15〜35分目安、
    --Machine/--Unity 指定時は安全のため直列(従来どおり2〜3時間目安)
  * **実機(Palworld)には一切触らない**(既定。-Machine 未指定なら
    @machine のテストごと除外される)
  * 1件 FAIL しても最後まで回る(-x を付けない)
  * 結果は work\u53_cov\reports\<timestamp>\ に残る
      progress.log   … 1件ごとの進行(実行中でも読める。並列時はワーカーごとに
                       progress.<workerid>.log にも出て、終了時に集約される)
      report.md      … 判定一覧(FAIL → SKIP → PASS 順)
      coverage.md    … カバー状況の表
      gates.jsonl / tests.jsonl / provenance.json
      pytest_stdout.log … pytest の生出力(フェーズA+B分を連結)

.PARAMETER Machine
  指定すると実機ゲート(E: クラッシュ / F: プレイ開始)も回す。
  **既定では回らない。**Palworld を起動してよい状況でだけ付けること。
  安全のため、指定すると並列化は無効化される(直列)。

.PARAMETER Unity
  指定すると .prefab 検体(C:\UnityP\ の4体)を Unity ヘッドレスで輸出し、
  MA(NDMF)ベイク込みで端から端まで通す。**既定では回らない。**
  安全のため、指定すると並列化は無効化される(直列)。

  付ける前に確認すること:
    * 対象の Unity プロジェクトを **Unity で開いていないこと**(二重起動禁止)
    * **プロジェクト側へ書き込みが起きる**ことを許容できること
      (Assets\Editor\DiveToPalworldExporter.cs の複製、
       FBX Exporter 未導入なら Packages\manifest.json への追記)
  1体あたり数分〜十数分(初回インポートを含むとさらに)。

.PARAMETER Specimens
  入力形式軸で回す検体(既定 all)。配線確認だけなら `fast`。
  ※ prefab 検体はこの指定の対象外(常に4体すべて)。

.PARAMETER SelfTestOnly
  負の対照(モック自己検証)だけを回す。実変換も実機接触も起きない。数秒で終わる。

.PARAMETER Workers
  並列度(既定3。環境変数 D2P_COVERAGE_WORKERS でも上書きできる。
  このパラメータを指定した場合はそちらが最優先)。
#>
[CmdletBinding()]
param(
    [switch]$Machine,
    [switch]$Unity,
    [string]$Specimens = "all",
    [switch]$SelfTestOnly,
    [int]$Workers
)

$ErrorActionPreference = "Continue"
$PSNativeCommandUseErrorActionPreference = $false
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$here = Split-Path $PSCommandPath -Parent
$runner = Join-Path $here "run_overnight.py"

$pyArgs = @($runner)
if ($Machine) { $pyArgs += "--machine" }
if ($Unity) { $pyArgs += "--unity" }
if ($SelfTestOnly) { $pyArgs += "--selftest-only" }
$pyArgs += @("--specimens", $Specimens)
if ($PSBoundParameters.ContainsKey("Workers")) { $pyArgs += @("--workers", $Workers) }

& python @pyArgs
exit $LASTEXITCODE
