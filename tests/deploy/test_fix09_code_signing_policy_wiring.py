# -*- coding: utf-8 -*-
"""FIX09(SignPath対応、CODE_SIGNING_POLICY.md新設)受入ゲート5の検査。

背景: devtools\\deploy.py の WHITELIST_FILES に CODE_SIGNING_POLICY.md を追加した
(項目追加のみ、構造は変更していない)。本テストは、追加が実際に配布集合の計算
(compute_pub_sync_manifest)へ届いていることを、tests\\deploy\\test_wp10_pub_manifest.py
と同じ手法(実同期は一切呼ばない純粋関数の戻り値を見る)で検証する。負の対照
(ホワイトリストから外すとその1件だけ集合から消える)も併記し、検査自体が
空振りしていないことを示す。

安全制約: deploy.pyの実同期(clone/全消去/copytree/commit/push)は一切呼ばない。
compute_pub_sync_manifest() は副作用のない純粋関数であり、Pub実体
(C:\\P\\Work\\UchinokoPub)には一切触れない。

実行: python -m pytest tests\\deploy\\test_fix09_code_signing_policy_wiring.py -q
"""
import os
import sys
from pathlib import Path

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import deploy  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent.parent


def test_file_exists_on_disk():
    """配布集合の計算対象であるCODE_SIGNING_POLICY.md自体がdev直下に存在すること。"""
    assert (_REPO / "CODE_SIGNING_POLICY.md").is_file(), (
        "CODE_SIGNING_POLICY.mdがリポジトリ直下に見つからない")


def test_listed_in_whitelist_files():
    assert "CODE_SIGNING_POLICY.md" in deploy.WHITELIST_FILES, (
        "CODE_SIGNING_POLICY.mdがWHITELIST_FILESに未収載(配線切れ)")


def test_reaches_pub_sync_manifest():
    manifest = deploy.compute_pub_sync_manifest()
    assert "CODE_SIGNING_POLICY.md" in manifest, (
        "CODE_SIGNING_POLICY.mdがPub同期集合に無い(配線切れ)")


def test_negative_control_removing_from_whitelist_drops_it(monkeypatch):
    """ホワイトリストから外すと、その1件だけが集合から消えることを確認する
    負の対照(検査が実際にWHITELIST_FILESを参照していることの裏付け)。"""
    before = deploy.compute_pub_sync_manifest()
    assert "CODE_SIGNING_POLICY.md" in before, "前提条件が崩れている(最初から集合に無い)"
    assert "SECURITY.md" in before, "前提条件が崩れている(比較対象のSECURITY.mdが無い)"

    reduced = [f for f in deploy.WHITELIST_FILES if f != "CODE_SIGNING_POLICY.md"]
    monkeypatch.setattr(deploy, "WHITELIST_FILES", reduced)
    after = deploy.compute_pub_sync_manifest()

    assert "CODE_SIGNING_POLICY.md" not in after, (
        "WHITELIST_FILESから外したのにCODE_SIGNING_POLICY.mdがまだ集合に残っている"
        "(compute_pub_sync_manifestがWHITELIST_FILESを実際には参照していない疑い)")
    # 他のファイルは巻き添えで消えていないこと
    assert "SECURITY.md" in after


def test_dev_only_signpath_docs_not_whitelisted():
    """.devonly配下(SignPath対応の調査メモ等)はdev専用であり、
    誤ってPubへ公開されてはならない。WHITELIST_FILESに一切含まれないことを確認する。"""
    for f in deploy.WHITELIST_FILES:
        assert not f.startswith(".devonly"), (
            ".devonly配下のファイルがWHITELIST_FILESに混入している: {}".format(f))
