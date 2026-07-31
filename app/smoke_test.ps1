# GUIの起動スモークテスト(開発用)。ユーザーの画面に映り込まないよう最小化で起動する
$exe = Join-Path (Split-Path $PSScriptRoot -Parent) "Uchinoko.exe"
$p = Start-Process $exe -WindowStyle Minimized -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Error "CRASHED exit=$($p.ExitCode)"; exit 1 }
"GUI OK"
Stop-Process -Id $p.Id -Confirm:$false
