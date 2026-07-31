# -*- coding: utf-8 -*-
"""審査官向け改善WP(2026-07-31、R2_C筆頭案の実装)受入ゲートの検査。

背景: devtools\\deploy.py の WHITELIST_FILES に REVIEWER_NOTES.md / CODEOWNERS を、
OVERLAY_ALLOWED_FILES に ".github/dependabot.yml" を追加した(項目追加のみ、
構造は変更していない)。本テストは、その追加が実際に配布集合の計算
(compute_pub_sync_manifest)へ届いていることを、tests\\deploy\\test_fix09_*.py と
同じ手法(実同期は一切呼ばない純粋関数の戻り値を見る)で検証する。負の対照
(ホワイトリスト/overlay許可集合から外すとその1件だけ集合から消える)も併記し、
検査自体が空振りしていないことを示す。

さらに、REVIEWER_NOTES.md が本文中に書いた相対リンクが実在するファイルを指すこと
(リンク切れが無いこと)、および devtools\\pub_overlay\\.github\\dependabot.yml が
妥当なYAMLであることも検査する。

安全制約: deploy.pyの実同期(clone/全消去/copytree/commit/push)は一切呼ばない。
compute_pub_sync_manifest() は副作用のない純粋関数であり、Pub実体
(C:\\P\\Work\\UchinokoPub)には一切触れない。

実行: python -m pytest tests\\deploy\\test_reviewer_facing_docs_wiring.py -q
"""
import os
import re
import sys
from pathlib import Path

import yaml

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import deploy  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent.parent


# --- REVIEWER_NOTES.md / CODEOWNERS: WHITELIST_FILES経由の配線 ------------------------

def test_reviewer_notes_and_codeowners_exist_on_disk():
    assert (_REPO / "REVIEWER_NOTES.md").is_file(), (
        "REVIEWER_NOTES.mdがリポジトリ直下に見つからない")
    assert (_REPO / "CODEOWNERS").is_file(), (
        "CODEOWNERSがリポジトリ直下に見つからない")


def test_reviewer_notes_and_codeowners_listed_in_whitelist_files():
    assert "REVIEWER_NOTES.md" in deploy.WHITELIST_FILES, (
        "REVIEWER_NOTES.mdがWHITELIST_FILESに未収載(配線切れ)")
    assert "CODEOWNERS" in deploy.WHITELIST_FILES, (
        "CODEOWNERSがWHITELIST_FILESに未収載(配線切れ)")


def test_reviewer_notes_and_codeowners_reach_pub_sync_manifest():
    manifest = deploy.compute_pub_sync_manifest()
    assert "REVIEWER_NOTES.md" in manifest, "REVIEWER_NOTES.mdがPub同期集合に無い(配線切れ)"
    assert "CODEOWNERS" in manifest, "CODEOWNERSがPub同期集合に無い(配線切れ)"


def test_negative_control_removing_reviewer_notes_from_whitelist_drops_it(monkeypatch):
    before = deploy.compute_pub_sync_manifest()
    assert "REVIEWER_NOTES.md" in before, "前提条件が崩れている(最初から集合に無い)"
    assert "SECURITY.md" in before, "前提条件が崩れている(比較対象のSECURITY.mdが無い)"

    reduced = [f for f in deploy.WHITELIST_FILES if f != "REVIEWER_NOTES.md"]
    monkeypatch.setattr(deploy, "WHITELIST_FILES", reduced)
    after = deploy.compute_pub_sync_manifest()

    assert "REVIEWER_NOTES.md" not in after, (
        "WHITELIST_FILESから外したのにREVIEWER_NOTES.mdがまだ集合に残っている")
    assert "SECURITY.md" in after, "他のファイルが巻き添えで消えている"


def test_negative_control_removing_codeowners_from_whitelist_drops_it(monkeypatch):
    before = deploy.compute_pub_sync_manifest()
    assert "CODEOWNERS" in before, "前提条件が崩れている(最初から集合に無い)"

    reduced = [f for f in deploy.WHITELIST_FILES if f != "CODEOWNERS"]
    monkeypatch.setattr(deploy, "WHITELIST_FILES", reduced)
    after = deploy.compute_pub_sync_manifest()

    assert "CODEOWNERS" not in after, (
        "WHITELIST_FILESから外したのにCODEOWNERSがまだ集合に残っている")
    assert "SECURITY.md" in after, "他のファイルが巻き添えで消えている"


# --- dependabot.yml: OVERLAY_ALLOWED_FILES経由の配線 -----------------------------------

def test_dependabot_yml_exists_in_overlay():
    path = Path(deploy.OVERLAY_DIR) / ".github" / "dependabot.yml"
    assert path.is_file(), "overlayにdependabot.ymlが無い: {}".format(path)


def test_dependabot_yml_listed_in_overlay_allowed_files():
    assert ".github/dependabot.yml" in deploy.OVERLAY_ALLOWED_FILES, (
        ".github/dependabot.ymlがOVERLAY_ALLOWED_FILESに未収載"
        "(overlay_relative_files()がこの集合の部分集合でない場合、"
        "phase3_sync_whitelistがDeployAbortする設計)")


def test_dependabot_yml_reaches_pub_sync_manifest():
    manifest = deploy.compute_pub_sync_manifest()
    assert ".github/dependabot.yml" in manifest, (
        ".github/dependabot.ymlがPub同期集合に無い(配線切れ)")


def test_dependabot_yml_is_valid_yaml_with_github_actions_ecosystem():
    path = Path(deploy.OVERLAY_DIR) / ".github" / "dependabot.yml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc.get("version") == 2
    ecosystems = [u.get("package-ecosystem") for u in doc.get("updates", [])]
    assert "github-actions" in ecosystems, (
        "github-actionsエコシステムの監視設定が無い: {}".format(ecosystems))


def test_overlay_relative_files_has_no_unexpected_github_entries():
    """overlay_relative_files()(実ディスク走査)がOVERLAY_ALLOWED_FILESの部分集合で
    あること。dependabot.yml追加後もこの不変条件が壊れていないことを確認する
    (deploy.py本体のfail-closedゲートと同じ判定をここでも独立に検査する)。"""
    unexpected = deploy.find_overlay_unexpected_files()
    assert unexpected == [], "overlayに未許可のファイルがある: {}".format(unexpected)


# --- REVIEWER_NOTES.md: 相対リンクの実在確認(リンク切れ検査) --------------------------

_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _extract_relative_links(markdown_text):
    """本文中の [text](target) 形式のリンクのうち、http(s)/mailto を除いた
    相対パスだけを返す。"""
    links = []
    for target in _MD_LINK_RE.findall(markdown_text):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        links.append(target)
    return links


def test_reviewer_notes_relative_links_resolve_to_real_files():
    text = (_REPO / "REVIEWER_NOTES.md").read_text(encoding="utf-8")
    links = _extract_relative_links(text)
    assert links, "REVIEWER_NOTES.mdから相対リンクが1件も抽出できなかった(検査が空振り)"

    missing = [link for link in links if not (_REPO / link).is_file()]
    assert missing == [], "REVIEWER_NOTES.mdのリンク先が実在しない: {}".format(missing)


def test_link_checker_negative_control():
    """検査自体が空振りしていないことの負の対照: 実在しないパスを混ぜると検知される。"""
    sample = "See [nonexistent doc](THIS_FILE_DOES_NOT_EXIST_XYZ.md) for details."
    links = _extract_relative_links(sample)
    missing = [link for link in links if not (_REPO / link).is_file()]
    assert missing == ["THIS_FILE_DOES_NOT_EXIST_XYZ.md"]
