# -*- coding: utf-8 -*-
"""SignPath対応(2026-07-31): ランチャーC#ソースのヒアドキュメント抽出の静的検査。

背景: SignPath Foundationの無料コード署名の審査は「ソースから透明に再現される
ビルド」を要求する。従来 build\\make_dist.ps1 は配布zipルート用ランチャー
(Uchinoko.exe)のソースをヒアドキュメント文字列($LauncherSrc)として埋め込み、
その場でcsc.exeへ渡してコンパイルしていた(実体の.csファイルがリポジトリに
存在しない)。ソースを app\\Launcher.cs という実ファイルへ抽出し、
build\\make_dist.ps1 はそのファイルを読んでコンパイルするだけにした。

この試験は「抽出後も元の設計・ロジックが失われていないか」を、実行を伴わず
(exe化しない)ソーステキストの構造だけで検査する。ApplyEngineの挙動そのもの
(5対照の単体表)は tests\\shipcheck\\test_apply_engine_cs.py が別途カバーする
(そちらはapp\\Launcher.csを直接コンパイルする形に更新済み)。

追記(2026-07-31): ランチャーのAV誤検知(実測、
Mark-of-the-Web付与済みビルドで白黒くじ引き)が判明し、ランチャーそのものを
配布物から除去した(build\\make_dist.ps1はもうapp\\Launcher.csを読まない・
コンパイルしない)。app\\Launcher.cs / app\\LauncherAssemblyInfo.cs のソースは
将来のC案(自己更新の自己再起動化)復活に備えてリポジトリに温存しているため、
「ソースファイルとしての構造」を検査する試験群(以下)はそのまま有効。
「build\\make_dist.ps1がこれをビルド対象に含んでいること」を検査していた
test_make_dist_references_launcher_source_file は前提が逆転したため、
「もう含まれていないこと」を検査する形に更新した(下記参照)。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
MAKE_DIST_PS1 = os.path.join(REPO_ROOT, "build", "make_dist.ps1")
LAUNCHER_CS = os.path.join(REPO_ROOT, "app", "Launcher.cs")
LAUNCHER_ASSEMBLY_INFO_CS = os.path.join(REPO_ROOT, "app", "LauncherAssemblyInfo.cs")


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def test_make_dist_no_longer_embeds_heredoc_source():
    """build\\make_dist.ps1 にランチャーソースのヒアドキュメントが残っていないこと
    (抽出前は "$LauncherSrc = @'" ... "'@" という形で埋め込まれていた)。"""
    content = _read(MAKE_DIST_PS1)
    assert "$LauncherSrc = @'" not in content, (
        "build\\make_dist.ps1 にランチャーのヒアドキュメント埋め込みがまだ残っている"
        "(app\\Launcher.cs への抽出が未完了、またはリグレッション)")
    # ApplyEngine等の実装本体もmake_dist.ps1のテキストからは消えているはず
    # (app\\Launcher.cs側にのみ存在する)
    assert "internal static class ApplyEngine" not in content, (
        "ApplyEngineの実装がbuild\\make_dist.ps1に直接埋め込まれたままになっている")


def test_make_dist_no_longer_builds_launcher():
    """2026-07-31: build\\make_dist.ps1 はもうランチャーを
    ビルドしない(app\\Launcher.csを読まない・csc.exeでコンパイルしない・配布zipに
    含めない)。以前はこの逆(ビルドすること)を検査していたが、ランチャーの
    AV誤検知が実測で判明したため配布物から除去した。app\\Launcher.cs自体は
    将来のC案復活に備えてソースとして温存されているため、このファイルの存在は
    別の試験(test_launcher_source_file_exists_with_expected_structure)が検査する。

    「app\\Launcher.csという文字列そのものが本文に一切現れない」ことは要求しない
    (廃止の経緯を説明するコメントで言及すること自体は自然で、むしろ望ましい)。
    ここで検査するのは、実際にファイルを読み込んで変数に代入する・コンパイル対象に
    含める、という**機能的な参照**が無いこと。"""
    content = _read(MAKE_DIST_PS1)
    assert 'Join-Path $Root "app\\Launcher.cs"' not in content, (
        "build\\make_dist.ps1 がまだ app\\Launcher.cs を機能的に読み込んでいる"
        "(ランチャー廃止のリグレッション)")
    assert "$LauncherCs" not in content
    assert "$LauncherOut" not in content
    assert "ランチャーのコンパイル失敗" not in content


def test_launcher_source_file_exists_with_expected_structure():
    """app\\Launcher.cs が実在し、抽出前と同じ主要な型・メソッドを保持していること
    (中身の欠落・破損の検出)。"""
    assert os.path.isfile(LAUNCHER_CS), "app\\Launcher.cs が存在しない"
    content = _read(LAUNCHER_CS)
    for marker in (
        "static class DiveToPalworldLauncher",
        "internal static class ApplyEngine",
        "internal static class ApplyEngineSelfTest",
        "internal static void RunStartupStateMachine(",
        "internal static bool ApplyItems(",
        "--check-apply-engine",
    ):
        assert marker in content, "app\\Launcher.cs から期待した構造が失われている: " + marker


def test_launcher_source_file_has_no_stray_heredoc_delimiters():
    """抽出時にPowerShellのヒアドキュメント境界('@ / @')の残骸が
    誤って本文へ混入していないこと(抽出ミスの検出)。"""
    content = _read(LAUNCHER_CS)
    lines = content.splitlines()
    assert lines[0].strip().startswith("// Uchinoko for Palworld"), (
        "app\\Launcher.cs の先頭行が想定と異なる: " + repr(lines[0]))
    assert lines[-1].strip() == "}", (
        "app\\Launcher.cs の末尾行が想定(クラスの閉じ括弧)と異なる: " + repr(lines[-1]))
    assert "'@" not in content and "@'" not in content, (
        "app\\Launcher.cs にPowerShellヒアドキュメントの境界記号が残っている(抽出ミス)")


def test_launcher_assembly_info_file_exists():
    """アセンブリメタデータ用ソースが実在すること(メタデータ試験の前提)。
    中身の詳細検査は test_signpath_assembly_metadata.py 側で行う。"""
    assert os.path.isfile(LAUNCHER_ASSEMBLY_INFO_CS), "app\\LauncherAssemblyInfo.cs が存在しない"


if __name__ == "__main__":
    import sys
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
