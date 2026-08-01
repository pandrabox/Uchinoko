@echo off
rem 配布用zipをさくっと作る。ダブルクリックでも、引数付きでも使える。
rem   make_dist.bat            → dist\Uchinoko_for_Palworld_v<Version>_full.zip
rem   make_dist.bat _test      → dist\Uchinoko_for_Palworld_v<Version>_full_test.zip
rem 中身の構成は make_dist.ps1 が決める(dev#532 D1、2026-08-01: Uchinoko.bat /
rem README.txt / res\ の3点、実体はapp_py\build.pyが組み立てる)。
cd /d "%~dp0"
echo === 配布zipを作ります(Blender同梱のコピーで数分かかります) ===
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_dist.ps1" -Suffix "%~1"
if errorlevel 1 (
    echo.
    echo *** 失敗しました。上のログを確認してください ***
    pause
    exit /b 1
)
echo.
echo === できました ===
dir /b /o-d "%~dp0dist\*.zip"
pause
