# -*- coding: utf-8 -*-
r"""tests\coverage と tests\shipcheck が共有するCLIオプション定義(dev#320)。

背景: 両ディレクトリの `conftest.py` は、それぞれ独立に
`--world` / `--allow-convert` / `--allow-machine` / `--run-dir` を
(値・choices・action・defaultが完全に同一のまま)登録していた。
pytest が両ディレクトリを同一セッションで収集すると(例: `pytest tests\`)、
後から読み込まれた側の `parser.addoption()` が
`ValueError: option names {'--world'} already added` を送出し、
`tests/shipcheck` 全体が collection error になっていた
(実測: `work\issue_zero\i320\NOTES.md`)。

なぜ「共通祖先の tests\conftest.py に一本化」ではなくこの形なのか:
`tests\coverage\pytest.ini` が存在するため、`pytest tests\coverage` を
単独実行するとそのディレクトリ自体が rootdir になり、`tests\conftest.py`
(祖先ディレクトリ)は読み込まれない(実測で確認済み)。そのため
「両方のconftest.pyが明示的にimportして呼ぶ、通常のPythonモジュール」
として共有する。

各 `pytest_addoption` からの呼び出しは1回ずつ独立して行われる
(単独実行なら1回だけ、`tests\` 全体を跨ぐ実行なら2回)。2回目の
`parser.addoption()` は pytest 内部で重複登録エラーになるが、
定義(値・意味)が完全に同一なので黙って無視してよい
(`ValueError` をここで握りつぶす)。
"""


def add_shared_options(parser):
    """--world / --allow-convert / --allow-machine / --run-dir を登録する。

    tests\\coverage\\conftest.py と tests\\shipcheck\\conftest.py の双方から
    呼ばれる。もう一方が同一セッションで先に登録済みなら no-op。
    """
    try:
        parser.addoption("--world", default="modtest", choices=["modtest", "panworld"],
                          help="実機ゲート/実プレイで使うワールド(既定modtest。"
                               "panworldはsave_guard必須)")
    except ValueError:
        pass
    try:
        parser.addoption("--allow-convert", action="store_true", default=False,
                          help="安全弁: 指定時のみ実変換(convert.ps1)を許可する"
                               "(既定は禁止でSKIP)")
    except ValueError:
        pass
    try:
        parser.addoption("--allow-machine", action="store_true", default=False,
                          help="安全弁: 指定時のみ Palworld 実機への接触を許可する"
                               "(既定は禁止でSKIP)")
    except ValueError:
        pass
    try:
        parser.addoption("--run-dir", default=None,
                          help="レポート出力先の上書き(既定は各スイートごとの"
                               "既定タイムスタンプディレクトリ)")
    except ValueError:
        pass
