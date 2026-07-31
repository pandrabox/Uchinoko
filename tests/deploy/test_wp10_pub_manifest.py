# -*- coding: utf-8 -*-
"""WP10(SignPath対応: #390 deploy-sync と #392 oss-docs の統合)受入ゲート3の検査。

背景: 並行して作られた2本のブランチ(deploy-sync / oss-docs)は、そのままでは
oss-docsが追加した標準文書(BUILD.md等)と.github配下のissue/PRテンプレートが
deploy.pyのホワイトリスト/overlayに未収載のままで、公開リポジトリへ届かない
「配線切れ」状態だった。本テストはその配線が実際に繋がっていることを、
compute_pub_sync_manifest() が返す実際の集合で検証する(「たぶん届く」を
事実として扱わない)。

安全制約: deploy.pyの実同期(clone/全消去/copytree/commit/push)は一切呼ばない。
compute_pub_sync_manifest() は副作用のない純粋関数であり、Pub実体
(C:\\P\\Work\\UchinokoPub)には一切触れない。

実行: python -m pytest tests\\deploy\\test_wp10_pub_manifest.py -q
"""
import os
import sys
from pathlib import Path

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import deploy  # noqa: E402


# --- 受入ゲート3本体: 期待するファイルが入っている / dev専用物が入っていない -------------

def test_oss_standard_docs_included():
    manifest = deploy.compute_pub_sync_manifest()
    for f in ["BUILD.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"]:
        assert f in manifest, "{} がPub同期集合に無い(配線切れ)".format(f)


def test_public_workflow_and_templates_included():
    manifest = deploy.compute_pub_sync_manifest()
    expected = [
        ".github/workflows/build.yml",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
    ]
    for f in expected:
        assert f in manifest, "{} がPub同期集合に無い(配線切れ)".format(f)


def test_dev_only_workflow_excluded():
    manifest = deploy.compute_pub_sync_manifest()
    assert ".github/workflows/ci.yml" not in manifest, (
        "dev専用のci.ymlがPub同期集合に混入している(重大: dev専用ワークフローの漏洩)")
    assert ".github/workflows/issue-label-guard.yml" not in manifest


def test_non_public_areas_excluded():
    manifest = deploy.compute_pub_sync_manifest()
    assert not any(p.startswith(".devonly") for p in manifest), ".devonly が混入している"
    assert not any(p.startswith("work/") for p in manifest), "work/ が混入している"
    assert not any(p.startswith(".claude") for p in manifest), ".claude が混入している"


# --- 負の対照その1: ホワイトリストから1件外すと、その1件だけが集合から消えること ---------

def test_negative_control_removing_whitelist_entry_drops_it(monkeypatch):
    before = deploy.compute_pub_sync_manifest()
    assert "BUILD.md" in before, "前提条件が崩れている(BUILD.mdが最初から無い)"

    reduced = [f for f in deploy.WHITELIST_FILES if f != "BUILD.md"]
    monkeypatch.setattr(deploy, "WHITELIST_FILES", reduced)
    after = deploy.compute_pub_sync_manifest()

    assert "BUILD.md" not in after, (
        "WHITELIST_FILESから外したのにBUILD.mdがまだ集合に残っている"
        "(compute_pub_sync_manifestがWHITELIST_FILESを実際には参照していない疑い)")
    # 他のファイルは巻き添えで消えていないこと
    assert "CONTRIBUTING.md" in after


# --- 負の対照その2: dev専用ci.ymlを紛れ込ませた場合、現行の分類定義なら検知されること -----

def test_negative_control_github_dir_whitelisted_would_leak_ci_yml(monkeypatch):
    """.github が誤ってWHITELIST_DIRSに混入した場合(=EXCLUDE_TOPでの除外という
    設計判断が無効化された場合)、dev専用のci.ymlが実際にPub同期集合へ漏れることを示す。
    これは「検査自体が空振りしていないか」を確かめる負の対照であり、
    現行の実装(.github をWHITELIST_DIRSに含めない)が意図通りに機能している
    ことの裏付けでもある。実ファイルは一切変更しない(monkeypatchのみ)。"""
    assert ".github" not in deploy.WHITELIST_DIRS, (
        "前提が崩れている: 既に.githubがWHITELIST_DIRSに入っている")

    manifest_before = deploy.compute_pub_sync_manifest()
    assert ".github/workflows/ci.yml" not in manifest_before

    monkeypatch.setattr(deploy, "WHITELIST_DIRS", list(deploy.WHITELIST_DIRS) + [".github"])
    manifest_after = deploy.compute_pub_sync_manifest()

    assert ".github/workflows/ci.yml" in manifest_after, (
        "スキャナが空振りしている: .githubをホワイトリストに混ぜてもci.ymlが検出されない")
