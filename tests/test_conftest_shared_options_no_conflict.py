# -*- coding: utf-8 -*-
r"""dev#320 再発防止テスト。

`tests\coverage\conftest.py` と `tests\shipcheck\conftest.py` は、それぞれ
`--world` / `--allow-convert` / `--allow-machine` / `--run-dir` を必要とする
(値・意味は完全に同一)。かつては両ファイルが独立に
`parser.addoption()` を直書きしており、pytest が両ディレクトリを同一
セッションで収集すると(例: `pytest tests\`)、2つ目に読み込まれた側の
`addoption()` が `ValueError: option names {'--world'} already added` を
送出して `tests/shipcheck` の collection error になっていた
(実測・詳細: `work\issue_zero\i320\NOTES.md`)。

修正: 共有分は `tests\shared_pytest_options.add_shared_options()` へ一本化し、
各 `pytest_addoption()` の先頭からそれを呼ぶ形にした。本テストは
「両conftestの `pytest_addoption` を同一の `Parser` に対して順番に呼んでも
例外が出ない」ことを、実ファイルをそのままimportして直接確認する
(モックではなく実体のconftest.pyを読む)。
"""
import importlib.util
import os

import pytest
from _pytest.config.argparsing import Parser

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVERAGE_CONFTEST = os.path.join(REPO_ROOT, "tests", "coverage", "conftest.py")
SHIPCHECK_CONFTEST = os.path.join(REPO_ROOT, "tests", "shipcheck", "conftest.py")


def _import_module_from_path(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registered_long_opts(parser):
    """parserに登録済みの `--foo` 形式オプション名を全て集める。

    `parser._anonymous`(addgroup無しで addoption したもの)は
    `parser._groups` に自動的に含まれるため、`_groups` だけ辿れば足りる
    (実測で確認済み)。
    """
    names = set()
    for group in parser._groups:
        for opt in group.options:
            names.update(opt._long_opts)
    return names


@pytest.fixture(scope="module")
def coverage_conftest():
    return _import_module_from_path("d2p_i320_coverage_conftest", COVERAGE_CONFTEST)


@pytest.fixture(scope="module")
def shipcheck_conftest():
    return _import_module_from_path("d2p_i320_shipcheck_conftest", SHIPCHECK_CONFTEST)


class TestNoDuplicateOptionConflict:
    """正: 両conftestのpytest_addoptionを1つのParserへ順番に適用しても例外なし。"""

    def test_both_pytest_addoption_apply_without_error(self, coverage_conftest,
                                                         shipcheck_conftest):
        parser = Parser()
        # 修正前はここ(2番目のpytest_addoption呼び出し)で
        # ValueError: option names {'--world'} already added が飛んでいた。
        coverage_conftest.pytest_addoption(parser)
        shipcheck_conftest.pytest_addoption(parser)

        names = _registered_long_opts(parser)
        # 共有4オプションが(重複登録エラーなく)ちょうど1回ずつ効いていること。
        for shared_opt in ("--world", "--allow-convert", "--allow-machine", "--run-dir"):
            assert shared_opt in names, "{} が登録されていない".format(shared_opt)
        # 各スイート固有オプションも両方生きていること(片方が握りつぶされていないか)。
        for coverage_opt in ("--allow-unity", "--specimens"):
            assert coverage_opt in names, "{} が登録されていない".format(coverage_opt)
        for shipcheck_opt in ("--avatars", "--repeat", "--shots-dir", "--target-root"):
            assert shipcheck_opt in names, "{} が登録されていない".format(shipcheck_opt)

    def test_reverse_order_also_applies_without_error(self, coverage_conftest,
                                                        shipcheck_conftest):
        """読み込み順序(ディレクトリ辞書順など)に依存しないことの確認。"""
        parser = Parser()
        shipcheck_conftest.pytest_addoption(parser)
        coverage_conftest.pytest_addoption(parser)
        names = _registered_long_opts(parser)
        assert "--world" in names


class TestNegativeControlDetectsRealDuplicate:
    """負: このテスト手法自体が「本物の重複登録」をきちんと検出できることの確認。

    (=上のPositiveテストが、実は何もチェックしていないザル検査でないことの保証)
    """

    def test_manually_duplicated_option_still_raises(self):
        parser = Parser()
        parser.addoption("--world", default="modtest", choices=["modtest", "panworld"])
        with pytest.raises(ValueError, match=r"already added"):
            parser.addoption("--world", default="modtest", choices=["modtest", "panworld"])
