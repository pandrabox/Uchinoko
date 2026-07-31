# -*- coding: utf-8 -*-
r"""dev#186(2026-07-29「work\に恒常データを置かない」裁定)の単体試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、実変換・実release.py
実行・実relgate実行は一切課さない(パス定数の解決結果を確認する純粋な単体試験のみ。
pak不変=Layers-Affected: none)。

背景: Cドライブ満杯フリーズ時のwork\緊急削除で、pak承認台帳
work\u53_cov\machine_pak_records.jsonl(リリース判定の正、WP13)が巻き添え消失した
事故を受け、「work\は使い捨て。将来の実行が判定材料として読む恒常状態を置いては
ならない」という裁定が出た(dev#186)。本WPは、該当する恒常状態一式を
.devonly\state\(小さな判定台帳・DB)/ .devonly\fixtures\(手動輸出のFBX等、
再生成コストが高い一次入力)という2つの恒久領域へ移設する「パスの参照先変更」を
行う(データ実体の移動自体は本WPの範囲外。移行手順書に譲る)。

このテストが確認すること:
  1. 恒常データ(台帳・DB・手動輸出フィクスチャ)を指すモジュール定数が、
     新しい恒久領域(.devonly\state\ / .devonly\fixtures\)を指すこと。
  2. 負の対照: 同じモジュール内で「再生成可能キャッシュ」に分類したものは
     意図的にwork\のまま据え置いていること(全部を機械的に.devonly\へ
     動かしたのではなく、分類に基づいて選別したことの確認)。
  3. release.py の cert_path_for()/write_cert() が実際に新しいledger定数
     (RELEASE_CERT_LEDGER_DIR)を使って書き込み、旧来のRELEASE_CERT_DIR
     (使い捨てrun_*/gate_cacheの置き場)には副作用が漏れないこと(機能テスト)。

実行: python -m pytest tests\shipcheck\test_issue186_work_migration_paths.py -v
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
TESTS_RELGATE_DIR = os.path.join(REPO_ROOT, "tests", "relgate")
if DEVTOOLS_DIR not in sys.path:
    sys.path.insert(0, DEVTOOLS_DIR)
if TESTS_RELGATE_DIR not in sys.path:
    sys.path.insert(0, TESTS_RELGATE_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

STATE_ROOT = os.path.join(REPO_ROOT, ".devonly", "state")
FIXTURES_ROOT = os.path.join(REPO_ROOT, ".devonly", "fixtures")
WORK_ROOT = os.path.join(REPO_ROOT, "work")


def _import(name):
    return importlib.import_module(name)


# =====================================================================
# 1. 恒常データ: 新しい恒久領域(.devonly\state\)を指すこと
# =====================================================================

def test_crash_test_machine_pak_records_path_moved_to_devonly_state():
    crash_test = _import("crash_test")
    expected = os.path.join(STATE_ROOT, "machine_pak_records.jsonl")
    assert crash_test.MACHINE_PAK_RECORDS_PATH == expected
    assert "work" not in os.path.relpath(
        crash_test.MACHINE_PAK_RECORDS_PATH, REPO_ROOT).split(os.sep), (
        "承認台帳は使い捨てのwork\\配下から出ていなければならない(dev#186)")


def test_release_machine_pak_records_path_matches_crash_test():
    """release.pyとcrash_test.pyは同じ台帳を指す独立定数を持つ(既存の二重定義
    設計を踏襲)。dev#186移設後もこの2つが食い違っていないことを保証する。"""
    release = _import("release")
    crash_test = _import("crash_test")
    assert release.MACHINE_PAK_RECORDS_PATH == crash_test.MACHINE_PAK_RECORDS_PATH


def test_gh_inbox_db_path_moved_to_devonly_state():
    gh_inbox = _import("gh_inbox")
    expected = os.path.join(STATE_ROOT, "gh_inbox", "state.db")
    assert str(gh_inbox.DB_PATH) == expected


def test_support_watch_state_dir_moved_to_devonly_state():
    support_watch = _import("support_watch")
    expected = os.path.join(STATE_ROOT, "support_watch")
    assert str(support_watch.STATE_DIR) == expected
    # インボックス(判定材料そのものではなく通知イベントの出力先)は
    # dev#50時点から既に.devonly\support\inbox\にあり、本WPの移設対象外。
    assert str(support_watch.INBOX_DIR) == os.path.join(
        REPO_ROOT, ".devonly", "support", "inbox")


def test_booth_thread_map_file_moved_to_devonly_state():
    booth_thread = _import("booth_thread")
    expected = os.path.join(STATE_ROOT, "booth_mirror", "mirror_map.json")
    assert str(booth_thread.MAP_FILE) == expected


def test_release_cert_ledger_dir_is_under_devonly_state():
    release = _import("release")
    expected = os.path.join(STATE_ROOT, "release_cert")
    assert release.RELEASE_CERT_LEDGER_DIR == expected
    assert release.cert_path_for("deadbee") == os.path.join(expected, "cert_deadbee.json")


def test_relgate_fixture_paths_moved_to_devonly_fixtures():
    relgate = _import("relgate")
    assert relgate.SHAPELL_FBX == os.path.join(
        FIXTURES_ROOT, "relgate", "shapell", "shapell.fbx")
    assert relgate.SHAPELL_HUMANOID == os.path.join(
        FIXTURES_ROOT, "relgate", "shapell", "humanoid.json")
    assert relgate.FLATAPRON_FBX == os.path.join(
        FIXTURES_ROOT, "relgate", "flatapron", "flatapron.fbx")
    assert relgate.FLATAPRON_HUMANOID == os.path.join(
        FIXTURES_ROOT, "relgate", "flatapron", "humanoid.json")


def test_dist_smoke_shapell_fixture_paths_match_relgate():
    """dist_smoke.pyのDEFAULT_VRM_PATH/DEFAULT_HUMANOID_JSONはdevtools\\relgate.py
    のSHAPELL_FBX/SHAPELL_HUMANOIDと同じ実体を指す独立定数(既存の二重定義設計)。
    dev#186移設後も一致していることを保証する。"""
    relgate = _import("relgate")
    dist_smoke = _import("dist_smoke")
    assert dist_smoke.DEFAULT_VRM_PATH == relgate.SHAPELL_FBX
    assert dist_smoke.DEFAULT_HUMANOID_JSON == relgate.SHAPELL_HUMANOID


# =====================================================================
# 2. 負の対照: 再生成可能キャッシュは意図的にwork\のまま(全部を機械的に
#    .devonlyへ動かしたのではないことの確認)
# =====================================================================

def test_release_cert_dir_disposable_cache_stays_in_work():
    """run_*/gate_cacheの置き場(RELEASE_CERT_DIR)は、cert_*.json台帳
    (RELEASE_CERT_LEDGER_DIR)と分離したうえで、意図的にwork\\へ残す
    (disk_guard.prune_release_cert_runs()が能動的に間引く前提の使い捨て領域
    であり、.devonly\\state\\の「小さな恒久台帳」という性質と衝突するため)。"""
    release = _import("release")
    assert release.RELEASE_CERT_DIR == os.path.join(WORK_ROOT, "release_cert")
    assert release.RELEASE_CERT_DIR != release.RELEASE_CERT_LEDGER_DIR


def test_gate_cache_root_stays_in_work():
    gate_cache = _import("gate_cache")
    assert gate_cache.GATE_CACHE_ROOT == os.path.join(
        WORK_ROOT, "release_cert", "gate_cache")


def test_relgate_shared_cache_dir_stays_in_work():
    """work\\_shared_cache(vanilla抽出・live_templateのfingerprintキャッシュ)は
    消えても自己修復する設計であることが既に確認済み(devtools\\relgate.py
    コメント参照)なので、dev#186の移設対象外(work\\のまま)。"""
    relgate = _import("relgate")
    assert relgate.SHARED_CACHE_DIR == os.path.join(WORK_ROOT, "_shared_cache")


def test_dist_smoke_blender_cache_zip_stays_in_work():
    """公式Blenderの実DL済みキャッシュzip(405MB)は、無ければ
    test_ensure_blender.py側がfail-safeにSKIPする設計であり(FAILしない)、
    再取得も可能なため恒常台帳とは分類しない。サイズも大きいため
    .devonly\\state\\へは動かさずwork\\のまま据え置く。"""
    dist_smoke = _import("dist_smoke")
    assert dist_smoke.DEFAULT_BLENDER_CACHE_ZIP == os.path.join(
        WORK_ROOT, "u54_unbundle", "cache", "blender-4.3.2-windows-x64.zip")


def test_booth_thread_parsed_dir_stays_in_work():
    """取り込み済みBOOTH生データ(parsed\\<会話ID>.json)は、D1へ全件送り込み
    済みならD1側が恒久コピーになるため、ローカルの受け皿はwork\\のままでよい
    (恒久台帳として移設したのはmirror_map.jsonの対応表だけ)。"""
    booth_thread = _import("booth_thread")
    assert str(booth_thread.PARSED_DIR) == os.path.join(
        WORK_ROOT, "booth_raw_20260729", "parsed")


# =====================================================================
# 3. 機能テスト: write_cert()/cert_path_for()が新ledger定数を実際に使い、
#    旧RELEASE_CERT_DIRには漏れないこと
# =====================================================================

def test_write_cert_writes_to_ledger_dir_not_run_dir(tmp_path, monkeypatch):
    release = _import("release")
    ledger_dir = tmp_path / "ledger"
    run_dir = tmp_path / "run_scratch"
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(ledger_dir))
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(run_dir))

    zip_path = tmp_path / "dummy.zip"
    zip_path.write_bytes(b"zip-bytes")

    class DummyReport:
        def log(self, *a, **k):
            pass

    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    path = release.write_cert(
        "deadbeefcafebabe", "deadbee", [{"name": "x", "ok": True}],
        {"zip_path": str(zip_path)}, [], DummyReport(), gates_by_mode=gates_by_mode)

    assert os.path.isfile(path), "cert.jsonがRELEASE_CERT_LEDGER_DIR配下に書かれていない"
    assert os.path.dirname(os.path.abspath(path)) == str(ledger_dir)
    assert not run_dir.exists(), (
        "write_cert()はRELEASE_CERT_DIR(run_*の使い捨て領域)へ副作用を漏らして"
        "はならない")
    with open(path, encoding="utf-8") as f:
        cert = json.load(f)
    assert cert["commit_short"] == "deadbee"


def test_remove_stale_cert_only_touches_ledger_dir(tmp_path, monkeypatch):
    release = _import("release")
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    run_dir = tmp_path / "run_scratch"
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(ledger_dir))
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(run_dir))

    stale = ledger_dir / "cert_abc1234.json"
    stale.write_text("{}", encoding="utf-8")

    class DummyReport:
        def __init__(self):
            self.lines = []

        def log(self, text, echo=True):
            self.lines.append(text)

    release.remove_stale_cert("abc1234", DummyReport())
    assert not stale.exists()
    assert not run_dir.exists()
