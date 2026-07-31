"""devtools\\deploy.py のホワイトリスト分類・overlay機構の単体テスト。

安全制約(SignPath対応WP1): deploy.pyの実同期(clone/全消去/copytree/commit/push)は
一切呼ばない。ここでテストするのはPub/実リポジトリに一切触れない純粋関数
(find_unclassified_top / find_missing_required_subpaths / overlay_relative_files /
compute_pub_sync_manifest)だけ。C:\\P\\Work\\UchinokoPub は読み書きどちらもしない。
"""
import os
import sys
from pathlib import Path

import pytest
import yaml

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import deploy  # noqa: E402


# --- 受入ゲート1/2: 実リポジトリ(DEV_ROOT)が現行の分類定義で全件分類済みであること ---

def test_dev_root_fully_classified():
    """実行コマンド相当: `python devtools\\deploy.py check`。
    Dev直下の全エントリがWHITELIST_DIRS/WHITELIST_FILES/EXCLUDE_TOPのいずれかに
    分類されていること(fail-closedの入口ゲート)。"""
    unknown = deploy.find_unclassified_top(deploy.DEV_ROOT)
    assert unknown == [], "未分類エントリがある: {}".format(unknown)


def test_dev_root_required_subpaths_present():
    missing = deploy.find_missing_required_subpaths(deploy.DEV_ROOT)
    assert missing == [], "必須パスが欠落している: {}".format(missing)


# --- 受入ゲート3: 負の対照(未分類ファイルを混ぜると検知されること) -------------------

def test_unclassified_top_negative_control(tmp_path):
    """実リポジトリを汚さず、一時ディレクトリで分類ロジックを検証する。
    既知の分類名だけで構成したツリーはクリーン判定になり、
    未知の名前を1件混ぜるとfind_unclassified_topがそれを検知することを示す
    (deploy.pyのphase1_whitelist_integrityがこの関数の結果でDeployAbortする)。"""
    known = set(deploy.WHITELIST_DIRS) | set(deploy.WHITELIST_FILES) | deploy.EXCLUDE_TOP
    for name in known:
        (tmp_path / name).write_text("placeholder", encoding="utf-8")

    # ベースライン: 既知の分類名だけなら未分類ゼロ
    assert deploy.find_unclassified_top(str(tmp_path)) == []

    # 負の対照: 分類定義に無い名前を1件混ぜる
    (tmp_path / "mystery_unclassified_file.txt").write_text("x", encoding="utf-8")
    unknown = deploy.find_unclassified_top(str(tmp_path))
    assert unknown == ["mystery_unclassified_file.txt"], (
        "未分類ファイルの混入がfind_unclassified_topで検知されなかった: {}".format(unknown))


def test_phase1_raises_deploy_abort_on_unclassified_entry(tmp_path, monkeypatch):
    """負の対照その2: phase1_whitelist_integrity自体が未分類混入でDeployAbortすることを、
    DEV_ROOTを一時ディレクトリへ差し替えて確認する(実リポジトリは変更しない)。"""
    known = set(deploy.WHITELIST_DIRS) | set(deploy.WHITELIST_FILES) | deploy.EXCLUDE_TOP
    # REQUIRED_SUBPATHSの先頭要素(例: "pipeline", "third_party")はディレクトリで
    # なければならないので、他の既知名(ファイルで十分)と作り分ける。
    required_top_dirs = {rel.split(os.sep)[0] for rel in deploy.REQUIRED_SUBPATHS}
    for name in known:
        target = tmp_path / name
        if name in required_top_dirs:
            target.mkdir(exist_ok=True)
        else:
            target.write_text("placeholder", encoding="utf-8")
    for rel in deploy.REQUIRED_SUBPATHS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(deploy, "DEV_ROOT", str(tmp_path))

    class _NullReporter:
        def log(self, text):
            pass

    # クリーンな状態ではDeployAbortしない
    deploy.phase1_whitelist_integrity(_NullReporter())

    # 未分類ファイルを混ぜるとDeployAbortする
    (tmp_path / "mystery_unclassified_file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(deploy.DeployAbort):
        deploy.phase1_whitelist_integrity(_NullReporter())


# --- 受入ゲート4: 公開用build.ymlがYAMLとしてパースでき、on/jobs/stepsを持つ -----------

def test_overlay_build_yml_is_valid_yaml():
    path = Path(deploy.OVERLAY_DIR) / ".github" / "workflows" / "build.yml"
    assert path.is_file(), "overlayにbuild.ymlが無い: {}".format(path)

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)

    # PyYAML(YAML 1.1)は素の `on:` キーを真偽値Trueとして解釈する既知の挙動があるため
    # 両方を許容する(GitHub Actions自体の解釈には影響しない)。
    assert ("on" in doc) or (True in doc), "on: キーが見つからない: {}".format(list(doc.keys()))

    assert "jobs" in doc and doc["jobs"], "jobs: が無い、または空"
    first_job = next(iter(doc["jobs"].values()))
    assert isinstance(first_job.get("steps"), list) and len(first_job["steps"]) >= 1, (
        "少なくとも1つのstepsが必要")


# --- 受入ゲート5: dev専用ci.ymlがPub同期集合に混ざらず、公開用build.ymlは含まれる -------

def test_dev_ci_yml_excluded_from_pub_sync():
    manifest = deploy.compute_pub_sync_manifest()
    assert ".github/workflows/ci.yml" not in manifest
    assert ".github/workflows/issue-label-guard.yml" not in manifest


def test_pub_build_yml_included_in_pub_sync():
    manifest = deploy.compute_pub_sync_manifest()
    assert ".github/workflows/build.yml" in manifest


def test_pub_sync_manifest_has_no_other_github_files():
    """overlay由来の.github配下は、既知のPub専用ファイル集合(公開用ワークフロー+
    issue/PRテンプレート+dependabot.yml)以外に無いはず(万一overlayへ想定外の
    ファイルが増えても、dev専用ワークフローの取り違えではないことを保証する回帰
    チェック。2026-07-31 WP10でissue/PRテンプレートをoverlay化、同日の審査官向け
    改善WPでdependabot.ymlを追加したため集合を更新)。"""
    manifest = deploy.compute_pub_sync_manifest()
    github_entries = sorted(p for p in manifest if p.startswith(".github/"))
    expected = sorted([
        ".github/workflows/build.yml",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/dependabot.yml",
    ])
    assert github_entries == expected, github_entries


# --- 受入ゲート6(WP14): SignPath審査対策のPROVENANCE_NOUE_ASSETS.mdがPub同期集合に含まれる ---

def test_provenance_noue_assets_doc_included_in_pub_sync():
    """WP11の草案(pipeline\\py\\noue_master\\配下の.uasset/.uexpが自作アセットである旨の
    公開用来歴文書)を配線したPROVENANCE_NOUE_ASSETS.mdが、実際にPub同期集合へ含まれること。"""
    assert os.path.isfile(os.path.join(deploy.DEV_ROOT, "PROVENANCE_NOUE_ASSETS.md")), (
        "リポジトリ直下にPROVENANCE_NOUE_ASSETS.mdが存在しない")
    manifest = deploy.compute_pub_sync_manifest()
    assert "PROVENANCE_NOUE_ASSETS.md" in manifest


def test_provenance_noue_assets_doc_negative_control(monkeypatch):
    """負の対照: WHITELIST_FILESから外すと配布集合から落ちることを示す
    (ホワイトリストへの追加が実際に効いていることの確認。飾りの追加ではない)。"""
    reduced = [f for f in deploy.WHITELIST_FILES if f != "PROVENANCE_NOUE_ASSETS.md"]
    assert len(reduced) == len(deploy.WHITELIST_FILES) - 1, "WHITELIST_FILESに項目が見つからない"
    monkeypatch.setattr(deploy, "WHITELIST_FILES", reduced)
    manifest = deploy.compute_pub_sync_manifest()
    assert "PROVENANCE_NOUE_ASSETS.md" not in manifest


# --- 受入ゲート7(Privacy Policy WP): PRIVACY.md / PRIVACY.en.md がPub同期集合に含まれる ---
#
# 問い合わせ機能(app\DiveToPalworld.cs の BuildReportPayloadJson/SendReportPayload)が
# report.osakishokai.com へ送信するデータを開示する文書。SignPath申請フォームの
# Privacy Policy URL 欄に充てるため、実際にPub公開集合へ届くことを実装から確認する
# (「集合を計算する関数を呼ぶだけ」で、実同期=clone/copytree/commit/pushは一切行わない)。

def test_privacy_policy_docs_included_in_pub_sync():
    for name in ("PRIVACY.md", "PRIVACY.en.md"):
        assert os.path.isfile(os.path.join(deploy.DEV_ROOT, name)), (
            "リポジトリ直下に{}が存在しない".format(name))
    manifest = deploy.compute_pub_sync_manifest()
    assert "PRIVACY.md" in manifest
    assert "PRIVACY.en.md" in manifest


def test_privacy_policy_docs_negative_control(monkeypatch):
    """負の対照: WHITELIST_FILESから外すと配布集合から落ちることを示す
    (ホワイトリストへの追加が実際に効いていることの確認。飾りの追加ではない)。"""
    reduced = [f for f in deploy.WHITELIST_FILES
               if f not in ("PRIVACY.md", "PRIVACY.en.md")]
    assert len(reduced) == len(deploy.WHITELIST_FILES) - 2, "WHITELIST_FILESに項目が見つからない"
    monkeypatch.setattr(deploy, "WHITELIST_FILES", reduced)
    manifest = deploy.compute_pub_sync_manifest()
    assert "PRIVACY.md" not in manifest
    assert "PRIVACY.en.md" not in manifest


# --- 受入ゲート8(FIX29): verify_noue_asset_provenance.pyがPub同期集合に含まれ、---
# --- devtools全体は公開しない(overlayによる単独ファイル配信) -------------------------
#
# 背景: PROVENANCE_NOUE_ASSETS.md は「誰でも(SignPathの審査官を含め)自分で検証できる」
# と謳い devtools/verify_noue_asset_provenance.py を案内するが、devtoolsはEXCLUDE_TOPで
# 丸ごと非公開のため、この主張は2026-07-31時点で実行不能だった(R2-05の再評価で発覚)。
# overlay機構(devtools/pub_overlay/devtools/verify_noue_asset_provenance.py)を使い、
# このファイル1本だけをPubへ個別に届ける。devtools全体を公開する変更ではないことを
# find_overlay_unexpected_files/EXCLUDE_TOP検査が引き続き保証する
# (test_current_real_overlay_passes_unexpected_files_check、既存)。

def test_verify_noue_asset_provenance_overlay_file_exists():
    path = os.path.join(deploy.OVERLAY_DIR, "devtools", "verify_noue_asset_provenance.py")
    assert os.path.isfile(path), "overlayにverify_noue_asset_provenance.pyが無い: {}".format(path)


def test_verify_noue_asset_provenance_overlay_matches_source():
    """overlayコピー(公開されるPub専用ファイルの実体)が、dev側の正本
    devtools\\verify_noue_asset_provenance.py とバイト一致していること(ドリフト防止)。
    正本を更新してoverlay側の更新を忘れると、公開版だけが古いまま取り残される事故に
    なるため、この不一致は明示的に検知する。"""
    real = os.path.join(deploy.DEV_ROOT, "devtools", "verify_noue_asset_provenance.py")
    overlay_copy = os.path.join(deploy.OVERLAY_DIR, "devtools", "verify_noue_asset_provenance.py")
    assert os.path.isfile(real)
    assert os.path.isfile(overlay_copy)
    with open(real, "rb") as f:
        real_bytes = f.read()
    with open(overlay_copy, "rb") as f:
        overlay_bytes = f.read()
    assert real_bytes == overlay_bytes, (
        "devtools\\verify_noue_asset_provenance.py を更新したら、"
        "devtools\\pub_overlay\\devtools\\verify_noue_asset_provenance.py も"
        "同じ内容へ更新すること。")


def test_verify_noue_asset_provenance_overlay_drift_negative_control(tmp_path, monkeypatch):
    """負の対照: overlayコピーが正本と異なる内容なら、drift検知ロジック相当の
    バイト比較が確実に不一致を返すことを確認する(検査そのものが常にPASSする
    壊れたテストになっていないことの証明)。"""
    real = os.path.join(deploy.DEV_ROOT, "devtools", "verify_noue_asset_provenance.py")
    fake_overlay_copy = tmp_path / "verify_noue_asset_provenance.py"
    fake_overlay_copy.write_bytes(b"# deliberately different content\n")
    with open(real, "rb") as f:
        real_bytes = f.read()
    assert real_bytes != fake_overlay_copy.read_bytes()


def test_verify_noue_asset_provenance_included_in_pub_sync():
    """このスクリプトが実際にPub同期集合(overlay経由)へ含まれること。"""
    manifest = deploy.compute_pub_sync_manifest()
    assert "devtools/verify_noue_asset_provenance.py" in manifest


def test_verify_noue_asset_provenance_in_overlay_allowed_files():
    assert "devtools/verify_noue_asset_provenance.py" in deploy.OVERLAY_ALLOWED_FILES


def test_verify_noue_asset_provenance_only_devtools_file_published():
    """devtools全体を公開する変更にしていないことの確認: overlay/公開集合の中で
    'devtools/' 配下に存在するのは verify_noue_asset_provenance.py 1本だけであること
    (『必要最小限だけを届ける』というBRIEFINGの制約を機械的に保証する)。"""
    manifest = deploy.compute_pub_sync_manifest()
    devtools_entries = sorted(p for p in manifest if p.startswith("devtools/"))
    assert devtools_entries == ["devtools/verify_noue_asset_provenance.py"], devtools_entries


# --- 受入ゲート9(内部リーク是正): tests\autonomy\* が公開集合に含まれないこと -----------
#
# 背景: 内製AI自律運転システム(devtools\autonomy\、EXCLUDE_TOPで非公開)向けの
# 単体テスト tests\autonomy\*.py が、tests\ 丸ごと公開という粗い分類(WHITELIST_DIRS)
# に連れられて公開リポジトリへ漏出していた(実装が無いのにテストだけ存在する=
# import不能な状態で公開されていた)。Claude Code CLIの安全確認バイパスフラグ
# (deploy.BYPASS_MARKERS参照)等の内部運用情報も含んでいた。
# WHITELIST_DIR_SUBPATH_EXCLUDES による対処が実際に効いている
# ことを、正の対照(現状クリーン)と負の対照(除外を外すと再現する)の両方で示す。

def test_tests_autonomy_excluded_from_pub_sync():
    """正の対照: 現在の分類定義では tests\\autonomy\\ 配下は公開集合に一切含まれない。"""
    manifest = deploy.compute_pub_sync_manifest()
    autonomy_entries = sorted(p for p in manifest if p.startswith("tests/autonomy/"))
    assert autonomy_entries == [], (
        "tests/autonomy/ 配下が公開集合に漏出している(2026-07-31に発覚した事故の"
        "再発): {}".format(autonomy_entries))


def test_tests_autonomy_dir_actually_exists_in_dev():
    """上のテストが「元々存在しないから当然含まれない」という空振りでないことの
    前提確認: dev側には実際に tests\\autonomy\\*.py が存在する。"""
    autonomy_dir = os.path.join(deploy.DEV_ROOT, "tests", "autonomy")
    assert os.path.isdir(autonomy_dir), "tests\\autonomy\\ が無い(前提が崩れている)"
    py_files = [f for f in os.listdir(autonomy_dir) if f.endswith(".py")]
    assert len(py_files) > 0, "tests\\autonomy\\ 配下に.pyファイルが無い(前提が崩れている)"


def test_tests_autonomy_exclusion_negative_control(monkeypatch):
    """負の対照: WHITELIST_DIR_SUBPATH_EXCLUDESを空にすると、tests\\autonomy\\*.pyが
    実際に公開集合へ再出現することを示す(除外リストが実際に効いていることの確認。
    「たまたま今は何も引っかかっていないだけ」ではない)。"""
    monkeypatch.setattr(deploy, "WHITELIST_DIR_SUBPATH_EXCLUDES", frozenset())
    manifest = deploy.compute_pub_sync_manifest()
    autonomy_entries = sorted(p for p in manifest if p.startswith("tests/autonomy/"))
    assert autonomy_entries != [], (
        "除外リストを空にしても tests/autonomy/ が公開集合に現れない"
        "(compute_whitelist_only_manifestが実際にはWHITELIST_DIR_SUBPATH_EXCLUDESを"
        "参照していない疑い)")
    assert "tests/autonomy/test_watchdog.py" in autonomy_entries


def test_is_excluded_subpath_matches_exact_and_children():
    """_is_excluded_subpath の境界確認: 除外パスそのものと、その配下は一致するが、
    プレフィックスだけが同じ別名のディレクトリ(tests/autonomy_other等)は
    誤って巻き込まないこと。"""
    assert deploy._is_excluded_subpath("tests/autonomy")
    assert deploy._is_excluded_subpath("tests/autonomy/test_watchdog.py")
    assert deploy._is_excluded_subpath("tests/autonomy/sub/deep.py")
    assert not deploy._is_excluded_subpath("tests/autonomy_other/x.py")
    assert not deploy._is_excluded_subpath("tests/other.py")


# --- 受入ゲート10(内部リーク是正): bypass系マーカーが公開集合に紛れていないこと -----------
#
# 背景: tests\autonomy\* の漏出にはClaude Code CLIの安全確認バイパスフラグ
# (deploy.BYPASS_MARKERS参照)の文字列がそのまま含まれていた。ディレクトリ単位の除外
# (上のテスト群)だけでは「別の場所に同じ文字列が紛れ込む」将来の事故を防げないため、
# 内容そのものを見る検査を別途持つ。既知の正当な出現(tests\shipcheck\gates.py、
# CI・release.pyの自動ゲートには含まれない開発者向けadvisoryチェック)は明示的に
# 許可し、それ以外の出現は必ず検知することを正負両対照で示す。

def test_no_bypass_marker_leak_in_pub_sync_manifest():
    """正の対照: 現在の公開集合の実ファイルに、bypass系マーカーを含むものが
    既知許可(BYPASS_MARKER_ALLOWED_FILES)の外に無いこと。"""
    hits = deploy.find_bypass_marker_leaks_in_manifest()
    assert hits == [], (
        "bypass系マーカーを含むファイルが既知許可の外で公開集合に含まれている"
        "(内部運用情報の漏出の疑い): {}".format(hits))


def test_gates_py_actually_contains_bypass_marker():
    """上のテストが「マーカーを含むファイルが元々どこにも無いから当然クリーン」
    という空振りでないことの前提確認: 既知許可先のgates.py には実際に
    マーカーが含まれている。"""
    gates_py = os.path.join(deploy.DEV_ROOT, "tests", "shipcheck", "gates.py")
    with open(gates_py, encoding="utf-8") as f:
        content = f.read()
    assert deploy.BYPASS_MARKERS[0] in content, (
        "前提が崩れている: gates.pyにマーカーが無い(BYPASS_MARKER_ALLOWED_FILESの"
        "テストケースとして成立しない)")


def test_bypass_marker_negative_control_allowlist_removed_detects_gates_py(monkeypatch):
    """負の対照: gates.pyをBYPASS_MARKER_ALLOWED_FILESから外すと、実際に検知される
    ことを示す(許可リストが実際に効いていることの確認。検査ロジック自体が
    空振りしていないことの担保)。"""
    monkeypatch.setattr(deploy, "BYPASS_MARKER_ALLOWED_FILES", frozenset())
    hits = deploy.find_bypass_marker_leaks_in_manifest()
    assert "tests/shipcheck/gates.py" in hits, (
        "許可リストを空にしてもgates.pyが検知されない"
        "(find_bypass_marker_leaks_in_manifestが実際にはBYPASS_MARKER_ALLOWED_FILESを"
        "参照していない疑い): {}".format(hits))


# このテストファイル自身が公開集合(tests\は丸ごとWHITELIST_DIRS)に含まれるため、
# 以下のテストコード内にBYPASS_MARKERSの文字列そのものを直書きすると、この
# テストファイル自体が新たな漏出源になってしまう(test_no_bypass_marker_leak_in_
# pub_sync_manifestが検知して落ちる)。そのため deploy.BYPASS_MARKERS[0] を実行時に
# 参照する形にし、ソースコード上には連続した文字列として現れないようにする。

def test_find_bypass_marker_leaks_detects_injected_marker(tmp_path):
    """負の対照その2: find_bypass_marker_leaks(実ディレクトリを直接歩く版、
    phase3_sync_whitelistがPub実体に対して使うのと同じ関数)に、意図的に
    マーカーを仕込んだファイルを混ぜると検知することを、一時ディレクトリで確認する
    (実PUB_ROOTには一切触れない)。"""
    marker = deploy.BYPASS_MARKERS[0]
    clean_file = tmp_path / "clean.py"
    clean_file.write_text("print('hello')\n", encoding="utf-8")
    sabotaged_file = tmp_path / "sabotaged.py"
    sabotaged_file.write_text(
        "args = ['claude', '-p', 'x', {!r}]\n".format(marker), encoding="utf-8")

    hits = deploy.find_bypass_marker_leaks(str(tmp_path))
    assert hits == ["sabotaged.py"], hits


def test_find_bypass_marker_leaks_respects_allowed_files(tmp_path):
    """find_bypass_marker_leaksのallowed_files引数が実際に効いていること
    (許可リストに載せたファイルは検知対象から除かれる)。"""
    marker = deploy.BYPASS_MARKERS[0]
    sabotaged_file = tmp_path / "sabotaged.py"
    sabotaged_file.write_text("{!r}\n".format(marker), encoding="utf-8")

    hits_unfiltered = deploy.find_bypass_marker_leaks(str(tmp_path))
    assert hits_unfiltered == ["sabotaged.py"]

    hits_filtered = deploy.find_bypass_marker_leaks(
        str(tmp_path), allowed_files=frozenset(["sabotaged.py"]))
    assert hits_filtered == []


# --- 受入ゲート11(WP32): tests\oss_docs\* が公開集合に含まれないこと -----------
#
# 背景: tests\oss_docs\test_forbidden_terms.py(pre-publish audit テスト。
# Pubへ同期する“前”にDev側で生成したOSS体裁文書を検査する内部品質ゲート)が、
# tests\ 丸ごと公開という粗い分類に連れられて公開リポジトリへ漏出し、その中に
# 埋め込まれていたオーナーの仕事用ハンドルの断片(base64化されていたが、
# base64は難読化であり秘匿ではない)が公開リポジトリへ届いていた。
# tests\autonomy と同じ「ディレクトリ単位のpre-publish audit除外」で塞いだことを
# 正負両対照で示す。

def test_tests_oss_docs_excluded_from_pub_sync():
    """正の対照: 現在の分類定義では tests\\oss_docs\\ 配下は公開集合に一切含まれない。"""
    manifest = deploy.compute_pub_sync_manifest()
    oss_docs_entries = sorted(p for p in manifest if p.startswith("tests/oss_docs/"))
    assert oss_docs_entries == [], (
        "tests/oss_docs/ 配下が公開集合に漏出している(WP32が是正した事故の再発): {}".format(
            oss_docs_entries))


def test_tests_oss_docs_dir_actually_exists_in_dev():
    """上のテストが「元々存在しないから当然含まれない」という空振りでないことの
    前提確認: dev側には実際に tests\\oss_docs\\*.py が存在する。"""
    oss_docs_dir = os.path.join(deploy.DEV_ROOT, "tests", "oss_docs")
    assert os.path.isdir(oss_docs_dir), "tests\\oss_docs\\ が無い(前提が崩れている)"
    py_files = [f for f in os.listdir(oss_docs_dir) if f.endswith(".py")]
    assert len(py_files) > 0, "tests\\oss_docs\\ 配下に.pyファイルが無い(前提が崩れている)"
    assert "test_forbidden_terms.py" in py_files, (
        "前提が崩れている: 事故の直接原因だった test_forbidden_terms.py が無い")


def test_tests_oss_docs_exclusion_negative_control(monkeypatch):
    """負の対照: WHITELIST_DIR_SUBPATH_EXCLUDESからtests/oss_docsを外すと、
    tests\\oss_docs\\*.py が実際に公開集合へ再出現することを示す
    (除外リストが実際に効いていることの確認)。"""
    reduced = frozenset(deploy.WHITELIST_DIR_SUBPATH_EXCLUDES) - {"tests/oss_docs"}
    monkeypatch.setattr(deploy, "WHITELIST_DIR_SUBPATH_EXCLUDES", reduced)
    manifest = deploy.compute_pub_sync_manifest()
    oss_docs_entries = sorted(p for p in manifest if p.startswith("tests/oss_docs/"))
    assert oss_docs_entries != [], (
        "除外リストから外しても tests/oss_docs/ が公開集合に現れない"
        "(compute_whitelist_only_manifestが実際にはWHITELIST_DIR_SUBPATH_EXCLUDESを"
        "参照していない疑い)")
    assert "tests/oss_docs/test_forbidden_terms.py" in oss_docs_entries


# --- 受入ゲート12(WP32): オーナーの仕事用ハンドルが(符号化されていても)
# 公開集合に紛れていないこと ---------------------------------------------------
#
# 背景: tests\oss_docs\test_forbidden_terms.py にbase64化して埋め込まれていた
# オーナーの仕事用ハンドルが、ディレクトリ単位の除外(受入ゲート11)を素通りした
# 場合でも検知されるよう、内容そのものを見る専用検査を追加した(find_bypass_marker_
# leaksと同じ流儀)。実際の値(devtools\sensitive_denylist.pyのowner_real_handle)は
# このテストファイル自体が公開集合(tests\は丸ごとWHITELIST_DIRS)に含まれるため
# 直書きしない――合成値(_FAKE_HANDLE、実在のオーナーハンドルとは無関係)を
# handle引数で明示的に渡すことで検査ロジックだけを検証する。

_FAKE_HANDLE = "zzqx_wp32_synthetic_handle_007"  # 実在のオーナーハンドルとは無関係の合成値


def test_no_handle_leak_in_pub_sync_manifest():
    """正の対照: 現在の公開集合の実ファイルに、オーナーの仕事用ハンドル
    (既定値、実値はdevtools\\sensitive_denylist.py由来)を含むものが
    既知許可(HANDLE_LEAK_ALLOWED_FILES)の外に無いこと。"""
    hits = deploy.find_handle_leaks_in_manifest()
    assert hits == [], (
        "オーナーの仕事用ハンドルを含むファイルが既知許可の外で公開集合に"
        "含まれている(個人特定情報の漏出の疑い): {}".format(hits))


def test_owner_handle_value_loads_and_is_nonempty():
    """前提確認: _owner_handle_value()がsensitive_denylist.pyから実際に非空の値を
    読み出せること(検査対象が空文字列で常にクリーン判定になる空振りを防ぐ)。"""
    value = deploy._owner_handle_value()
    assert isinstance(value, str)
    assert len(value) >= 5


def test_find_handle_leaks_detects_plaintext(tmp_path):
    """負の対照その1: 合成ハンドルの平文がそのままファイルに混入した場合に検知される。"""
    (tmp_path / "clean.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "leak_plain.py").write_text(
        "OWNER = {!r}\n".format(_FAKE_HANDLE), encoding="utf-8")

    hits = deploy.find_handle_leaks(str(tmp_path), handle=_FAKE_HANDLE)
    assert hits == ["leak_plain.py"], hits


def test_find_handle_leaks_detects_base64(tmp_path):
    """負の対照その2: 合成ハンドルのbase64エンコード(実際に使われた手口)が
    混入した場合に検知される。"""
    import base64
    encoded = base64.b64encode(_FAKE_HANDLE.encode("ascii")).decode("ascii")
    (tmp_path / "leak_b64.py").write_text(
        "import base64\nOWNER = base64.b64decode({!r}).decode('ascii')\n".format(encoded),
        encoding="utf-8")

    hits = deploy.find_handle_leaks(str(tmp_path), handle=_FAKE_HANDLE)
    assert hits == ["leak_b64.py"], hits


def test_find_handle_leaks_detects_hex(tmp_path):
    """負の対照その3: 合成ハンドルのhexエンコードが混入した場合に検知される。"""
    encoded = _FAKE_HANDLE.encode("ascii").hex()
    (tmp_path / "leak_hex.py").write_text("OWNER_HEX = {!r}\n".format(encoded), encoding="utf-8")

    hits = deploy.find_handle_leaks(str(tmp_path), handle=_FAKE_HANDLE)
    assert hits == ["leak_hex.py"], hits


def test_find_handle_leaks_detects_reversed(tmp_path):
    """負の対照その4: 合成ハンドルの逆順文字列が混入した場合に検知される。"""
    reversed_value = _FAKE_HANDLE[::-1]
    (tmp_path / "leak_reversed.py").write_text(
        "OWNER_REV = {!r}\n".format(reversed_value), encoding="utf-8")

    hits = deploy.find_handle_leaks(str(tmp_path), handle=_FAKE_HANDLE)
    assert hits == ["leak_reversed.py"], hits


def test_find_handle_leaks_detects_split_concat(tmp_path):
    """負の対照その5: 合成ハンドルを区切り文字を挟んで分割結合した場合に検知される
    (例: 'zzqx_wp32_synthetic' + '_handle_007' のような文字列結合の迂回)。"""
    half = len(_FAKE_HANDLE) // 2
    concatenated_source = "OWNER = {!r} + {!r}\n".format(
        _FAKE_HANDLE[:half], _FAKE_HANDLE[half:])
    (tmp_path / "leak_concat.py").write_text(concatenated_source, encoding="utf-8")

    hits = deploy.find_handle_leaks(str(tmp_path), handle=_FAKE_HANDLE)
    assert hits == ["leak_concat.py"], hits


def test_find_handle_leaks_respects_allowed_files(tmp_path):
    """find_handle_leaksのallowed_files引数が実際に効いていること
    (許可リストに載せたファイルは検知対象から除かれる)。"""
    (tmp_path / "sabotaged.py").write_text(_FAKE_HANDLE + "\n", encoding="utf-8")

    hits_unfiltered = deploy.find_handle_leaks(str(tmp_path), handle=_FAKE_HANDLE)
    assert hits_unfiltered == ["sabotaged.py"]

    hits_filtered = deploy.find_handle_leaks(
        str(tmp_path), handle=_FAKE_HANDLE, allowed_files=frozenset(["sabotaged.py"]))
    assert hits_filtered == []


def test_find_handle_leaks_clean_tree_has_no_false_positive(tmp_path):
    """負の対照の対照: 合成ハンドルに一切関係の無い内容だけのツリーはクリーン判定
    になること(検査が広く取りすぎて無関係なファイルまで拾わないことの確認)。"""
    (tmp_path / "unrelated.py").write_text(
        "def hello():\n    return 'world'\n", encoding="utf-8")
    hits = deploy.find_handle_leaks(str(tmp_path), handle=_FAKE_HANDLE)
    assert hits == []


def test_find_handle_leaks_in_manifest_detects_injected_file(tmp_path, monkeypatch):
    """find_handle_leaks_in_manifestがcompute_pub_sync_manifest経由で実際に
    dev/overlay側の実ファイルを検査すること(実PUB_ROOTには一切触れず、
    tmp_pathを疑似dev_rootとして使う)。"""
    fake_dev_root = tmp_path / "dev"
    fake_overlay = tmp_path / "overlay"
    (fake_dev_root / "tests").mkdir(parents=True)
    (fake_dev_root / "tests" / "leak.py").write_text(
        "OWNER = {!r}\n".format(_FAKE_HANDLE), encoding="utf-8")
    fake_overlay.mkdir()

    monkeypatch.setattr(deploy, "WHITELIST_DIRS", ["tests"])
    monkeypatch.setattr(deploy, "WHITELIST_FILES", [])

    hits = deploy.find_handle_leaks_in_manifest(
        dev_root=str(fake_dev_root), overlay_dir=str(fake_overlay), handle=_FAKE_HANDLE)
    assert hits == ["tests/leak.py"], hits
