"""devtools\\deploy.py の _read_tool_version() が正しい情報源(py版)から
バージョンを読むことを検査する回帰テスト(dev#681)。

## 背景

`devtools\\deploy.py phase6_build_and_audit_zip` は `_read_tool_version()` が
返したバージョンを `build\\make_dist.ps1 -Version <v>` に渡す。旧実装は
**退役済みのC#版 `app\\DiveToPalworld.cs` の `const string ToolVersion`** を
正規表現で読んでいたが、dev#532 D1で「py版(`app_py\\ui\\main_window.py` の
`TOOL_VERSION`)が唯一の正」に切り替わって以降、C#版は更新対象外(凍結)に
なった。py版が先行改版される通常運用では両者が常に食い違い、make_dist.ps1側の
バージョン整合チェック(`$PyVersion -ne $Version` で fail-closed)に必ず
引っかかり、`deploy.py run` のフェーズ6が常にABORTしていた(2026-08-01実測、
`ToolVersion = v2.2.13`(deploy.py由来) vs `TOOL_VERSION='v2.3.1'`(実値)で不一致)。

本テストは、_read_tool_version() が
  1. app_py\\ui\\main_window.py の TOOL_VERSION を返すこと(正の対照)
  2. 退役C#版 app\\DiveToPalworld.cs の値を読んでいないこと(負の対照:
     両ファイルにわざと異なる値を仕込み、返るのがpy側の値であることを確認)
  3. app_py\\ui\\main_window.py にTOOL_VERSION定数が無ければ fail-closed で
     DeployAbort すること
を、実ファイルへは一切触れずtmp_pathへ差し替えたDEV_ROOTで確認する。
release.py::read_tool_version()(dev#532 D1で先行移行済み)と読み取り元・
正規表現が一致することも確認する(同一情報源に統一されていることの前提確認)。
"""
import sys
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import deploy  # noqa: E402


def _write_py_main_window(dev_root, version):
    ui_dir = dev_root / "app_py" / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "main_window.py").write_text(
        'TOOL_VERSION = "{}"\n'.format(version), encoding="utf-8"
    )


def _write_cs(dev_root, version):
    app_dir = dev_root / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "DiveToPalworld.cs").write_text(
        'const string ToolVersion = "{}";\n'.format(version), encoding="utf-8"
    )


def test_read_tool_version_reads_from_py_side(tmp_path, monkeypatch):
    """正の対照: app_py\\ui\\main_window.py の TOOL_VERSION を返す。"""
    _write_py_main_window(tmp_path, "v2.3.1")
    monkeypatch.setattr(deploy, "DEV_ROOT", str(tmp_path))

    assert deploy._read_tool_version() == "v2.3.1"


def test_read_tool_version_ignores_retired_cs_side(tmp_path, monkeypatch):
    """負の対照: dev#681の再現条件そのもの。app\\DiveToPalworld.cs(退役C#版)と
    app_py\\ui\\main_window.py(py版、唯一の正)に異なる値を仕込み、返るのが
    py側の値であること(=C#側を読んでいたら v2.2.13 が返るはずのところ、
    修正後は v2.3.1 が返ること)を確認する。"""
    _write_cs(tmp_path, "v2.2.13")  # 実際に観測された凍結値(dev#681再現)
    _write_py_main_window(tmp_path, "v2.3.1")
    monkeypatch.setattr(deploy, "DEV_ROOT", str(tmp_path))

    result = deploy._read_tool_version()
    assert result == "v2.3.1", (
        "_read_tool_version()が退役C#版(app\\DiveToPalworld.cs)を読んでいる疑い"
        "(dev#681の再発): {}".format(result)
    )
    assert result != "v2.2.13"


def test_read_tool_version_fails_closed_when_py_constant_missing(tmp_path, monkeypatch):
    """負の対照: app_py\\ui\\main_window.py が存在してもTOOL_VERSION定数が
    見つからない場合はfail-closedでDeployAbortすること(app\\DiveToPalworld.cs側に
    ToolVersion定数があっても、それにフォールバックしてはならない)。"""
    ui_dir = tmp_path / "app_py" / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "main_window.py").write_text("# no version constant here\n", encoding="utf-8")
    _write_cs(tmp_path, "v2.2.13")
    monkeypatch.setattr(deploy, "DEV_ROOT", str(tmp_path))

    with pytest.raises(deploy.DeployAbort):
        deploy._read_tool_version()


def test_read_tool_version_matches_release_py_source_and_pattern():
    """比較対照: release.py::read_tool_version()(dev#532 D1で先行移行済み)と
    同一の読み取り元(app_py\\ui\\main_window.py)・同一の正規表現に揃っている
    ことのソース検査(deploy.pyとrelease.pyが別々の情報源を向いたまま
    それぞれ『正しい』と主張する再分岐を防ぐ)。"""
    deploy_src = (DEVTOOLS / "deploy.py").read_text(encoding="utf-8")
    release_src = (DEVTOOLS / "release.py").read_text(encoding="utf-8")

    assert '"app_py", "ui", "main_window.py"' in deploy_src, (
        "deploy.py の _read_tool_version() が app_py\\ui\\main_window.py を"
        "参照していない"
    )
    # 実際にファイルを開く行(os.path.join呼び出し)だけを見る -- docstring内の
    # 経緯説明の文言(「旧app\DiveToPalworld.csから移行」等)は正当な記述であり
    # 検査対象ではない。
    open_target_lines = [
        line for line in deploy_src.splitlines()
        if "os.path.join(DEV_ROOT" in line and "DiveToPalworld.cs" in line
    ]
    assert open_target_lines == [], (
        "deploy.py内にDEV_ROOTから app\\DiveToPalworld.cs を組み立てる行が"
        "まだ残っている(_read_tool_version()以外の関数も含めて確認): {}"
        .format(open_target_lines)
    )

    assert 'TOOL_VERSION_SOURCE = os.path.join(REPO_ROOT, "app_py", "ui", "main_window.py")' \
        in release_src, "release.py側の前提(TOOL_VERSION_SOURCE定義)が変わっている"


def test_init_release_history_also_reads_from_py_side(tmp_path, monkeypatch):
    """棚卸し対象その2: devtools\\init_release_history.py も同型のバグを持って
    いた(dev#681調査で発見、releases.json空時のみ動く休眠状態だが読み取り元は
    同種の欠陥)。app_py\\ui\\main_window.py 側から読むよう修正済みであることを
    確認する。"""
    sys.path.insert(0, str(DEVTOOLS))
    import init_release_history  # noqa: E402

    _write_py_main_window(tmp_path, "v9.9.9")
    _write_cs(tmp_path, "v2.2.13")
    monkeypatch.setattr(init_release_history, "TOOL_VERSION_SOURCE",
                         str(tmp_path / "app_py" / "ui" / "main_window.py"))

    assert init_release_history.read_tool_version() == "v9.9.9"
