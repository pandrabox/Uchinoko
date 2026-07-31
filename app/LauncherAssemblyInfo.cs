// Uchinoko for Palworld ランチャー(配布zipルートのUchinoko.exe。app\Launcher.cs)の
// アセンブリメタデータ。署名なしexeのSmartScreen/Defenderヒューリスティック対策。
// AssemblyVersion/AssemblyFileVersionのプレースホルダ"0.0.0.0"は
// build\make_dist.ps1がビルド時に-Version引数(app\DiveToPalworld.csのToolVersionと
// 事前に整合検証済み)から実バージョンへ文字列置換する
// (app\build_app.ps1のSupportEmailプレースホルダ差し込みと同じ手口)。
// このファイル単体をIDE等で直接コンパイルした場合はプレースホルダのまま
// (0.0.0.0)ビルドされるだけで、失敗はしない。
using System.Reflection;

[assembly: AssemblyTitle("Uchinoko for Palworld Launcher")]
[assembly: AssemblyProduct("Uchinoko for Palworld")]
[assembly: AssemblyCompany("pandrabox")]
[assembly: AssemblyCopyright("Copyright (c) 2026 pandrabox")]
[assembly: AssemblyDescription("Uchinoko for Palworld launcher (self-update + startup wrapper)")]
[assembly: AssemblyVersion("0.0.0.0")]
[assembly: AssemblyFileVersion("0.0.0.0")]
