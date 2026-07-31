# -*- coding: utf-8 -*-
r"""WP-CANARY-W3: devtools\canary\pub_canary.py の単体試験。

実Windows Defender・実ネットワーク(GitHub API/VirusTotal)には一切触れない。
判定ロジック(classify_verdict)は純関数として分離してあるので、それを中心に
GREEN/RED/INCONCLUSIVEの3分岐+負の対照(検知データを与えたらREDになる)を検証する。

負の対照はdevtools\av_scan_gate.py(dev#388)のテスト流儀を踏襲し、run_fnを
差し替えてDefenderスキャンをシミュレートする(スキャン前後のファイル存在で
「検出」を表現する一次観測、tests\shipcheck\test_av_scan_gate.pyと同じ手法)。

実行: python -m pytest tests\canary\test_pub_canary.py -v
"""
import glob
import importlib
import json
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
CANARY_DIR = os.path.join(DEVTOOLS, "canary")

for p in (DEVTOOLS, CANARY_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_pub_canary():
    return importlib.import_module("pub_canary")


# =====================================================================
# classify_verdict: 3分岐の核心ロジック(純関数、Defender/ネットワーク非依存)
# =====================================================================

def test_classify_verdict_green_when_all_clean_and_control_ok():
    pc = _import_pub_canary()
    results = [
        {"asset": "a.zip", "findings": [], "control_detected": True},
        {"asset": "b.zip", "findings": [], "control_detected": True},
    ]
    verdict, reason = pc.classify_verdict(results)
    assert verdict == pc.VERDICT_GREEN


def test_classify_verdict_red_when_any_asset_has_findings():
    """負の対照(受入条件): 検知データを与えたらREDになる。"""
    pc = _import_pub_canary()
    results = [
        {"asset": "a.zip", "findings": [{"file": "Uchinoko.exe", "detected": True}],
         "control_detected": True},
        {"asset": "b.zip", "findings": [], "control_detected": True},
    ]
    verdict, reason = pc.classify_verdict(results)
    assert verdict == pc.VERDICT_RED
    assert "a.zip" in reason


def test_classify_verdict_inconclusive_when_control_not_detected():
    pc = _import_pub_canary()
    results = [
        {"asset": "a.zip", "findings": [], "control_detected": False},
    ]
    verdict, reason = pc.classify_verdict(results)
    assert verdict == pc.VERDICT_INCONCLUSIVE
    assert "a.zip" in reason


def test_classify_verdict_inconclusive_when_control_key_missing():
    """av_scan_gate.run_av_scan_gate() が早期return(環境確認NG等)した場合、
    戻り値dictに control_detected キー自体が存在しない。これも「検査不能」
    として INCONCLUSIVE に倒す(キーが無い=Trueではない、を正しく扱う)。"""
    pc = _import_pub_canary()
    results = [
        {"asset": "a.zip", "findings": [], "detail": "MpCmdRun.exeが見つからない"},
    ]
    verdict, reason = pc.classify_verdict(results)
    assert verdict == pc.VERDICT_INCONCLUSIVE


def test_classify_verdict_red_takes_priority_over_inconclusive():
    """検出があり、かつ陽性対照も機能しなかった場合でも、最優先の通知理由はRED
    (実害の兆候がある以上、検査不能の理屈より先に知らせる)。"""
    pc = _import_pub_canary()
    results = [
        {"asset": "a.zip", "findings": [{"file": "x.exe", "detected": True}],
         "control_detected": False},
    ]
    verdict, reason = pc.classify_verdict(results)
    assert verdict == pc.VERDICT_RED


def test_classify_verdict_inconclusive_when_no_assets_at_all():
    """資産を1件も取得できなかった(ダウンロード失敗等) -> INCONCLUSIVE。
    GREENに倒れてはならない(空リストが誤ってGREEN扱いになる回帰を防ぐ)。"""
    pc = _import_pub_canary()
    verdict, reason = pc.classify_verdict([])
    assert verdict == pc.VERDICT_INCONCLUSIVE


# =====================================================================
# decide_issue_action: 重複起票防止
# =====================================================================

def test_decide_issue_action_create_when_no_existing_issue():
    pc = _import_pub_canary()
    assert pc.decide_issue_action(None) == "create"


def test_decide_issue_action_comment_when_existing_issue():
    pc = _import_pub_canary()
    assert pc.decide_issue_action(123) == "comment"


# =====================================================================
# vt_lookup_hash: GET専用、アップロードしない
# =====================================================================

def test_vt_lookup_hash_skipped_when_no_api_key():
    pc = _import_pub_canary()
    result = pc.vt_lookup_hash("deadbeef", api_key=None)
    assert result["status"] == "skipped"


def test_vt_lookup_hash_unknown_on_404():
    pc = _import_pub_canary()

    def fake_fetch(url, api_key):
        assert api_key == "dummy-key"
        assert url.endswith("/files/deadbeef")
        return 404, ""

    result = pc.vt_lookup_hash("deadbeef", api_key="dummy-key", fetch_fn=fake_fetch)
    assert result["status"] == "unknown"


def test_vt_lookup_hash_found_parses_stats_and_microsoft_verdict():
    pc = _import_pub_canary()

    def fake_fetch(url, api_key):
        body = json.dumps({
            "data": {"attributes": {
                "last_analysis_stats": {"malicious": 0, "harmless": 70},
                "last_analysis_results": {"Microsoft": {"category": "undetected", "result": None}},
            }}
        })
        return 200, body

    result = pc.vt_lookup_hash("deadbeef", api_key="dummy-key", fetch_fn=fake_fetch)
    assert result["status"] == "found"
    assert result["stats"]["malicious"] == 0
    assert result["microsoft_category"] == "undetected"


def test_vt_lookup_hash_error_on_unexpected_status():
    pc = _import_pub_canary()

    def fake_fetch(url, api_key):
        return 500, "server error"

    result = pc.vt_lookup_hash("deadbeef", api_key="dummy-key", fetch_fn=fake_fetch)
    assert result["status"] == "error"


def test_vt_lookup_hash_never_calls_post_or_upload_endpoint():
    """絶対制約の確認: fetch_fnに渡るURLが常にGET専用の files/{hash} 参照であり、
    アップロード系エンドポイント(/files への POST)を指すことがないことを確認する。"""
    pc = _import_pub_canary()
    seen_urls = []

    def fake_fetch(url, api_key):
        seen_urls.append(url)
        return 200, json.dumps({"data": {"attributes": {}}})

    pc.vt_lookup_hash("abc123", api_key="dummy-key", fetch_fn=fake_fetch)
    assert seen_urls == ["https://www.virustotal.com/api/v3/files/abc123"]
    assert all("/files/" in u and u.rstrip("/").split("/")[-1] != "files" for u in seen_urls)


# =====================================================================
# 恒常記録(.devonly\canary\相当。テストではtmp_pathへ差し替え)
# =====================================================================

def test_build_result_document_shape():
    pc = _import_pub_canary()
    doc = pc.build_result_document(
        "pandrabox/Uchinoko", "v2.2.12",
        [{"asset": "a.zip", "n_targets": 2, "findings": [], "control_detected": True,
          "detail": "ok"}],
        pc.VERDICT_GREEN, "reason", {"a.zip": {"status": "skipped"}},
        "2026-07-31T00:00:00Z", "2026-07-31T00:05:00Z")
    assert doc["verdict"] == pc.VERDICT_GREEN
    assert doc["tag"] == "v2.2.12"
    assert len(doc["assets"]) == 1
    assert doc["assets"][0]["vt"]["status"] == "skipped"


def test_write_result_json_and_append_log_line(tmp_path):
    pc = _import_pub_canary()
    doc = pc.build_result_document(
        "pandrabox/Uchinoko", "v2.2.12", [], pc.VERDICT_INCONCLUSIVE, "no assets",
        {}, "2026-07-31T00:00:00Z", "2026-07-31T00:05:00Z")
    results_dir = str(tmp_path / "results")
    json_path = pc.write_result_json(doc, results_dir=results_dir)
    assert os.path.isfile(json_path)
    with open(json_path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["verdict"] == pc.VERDICT_INCONCLUSIVE

    log_path = str(tmp_path / "CANARY_LOG.md")
    pc.append_log_line(doc, log_path=log_path)
    pc.append_log_line(doc, log_path=log_path)  # 2回目もヘッダは重複しない
    with open(log_path, encoding="utf-8") as f:
        content = f.read()
    assert content.count("# Uchinoko公開物カナリア") == 1
    assert content.count("verdict=INCONCLUSIVE") == 2


# =====================================================================
# build_issue_body: 文面に必要情報が含まれるか
# =====================================================================

def test_build_issue_body_contains_verdict_and_assets():
    pc = _import_pub_canary()
    doc = pc.build_result_document(
        "pandrabox/Uchinoko", "v2.2.12",
        [{"asset": "Uchinoko_for_Palworld_v2.2.12_full.zip", "n_targets": 2,
          "findings": [{"file": "Uchinoko.exe", "detected": True}],
          "control_detected": True, "detail": "1件検出"}],
        pc.VERDICT_RED, "検出された資産: Uchinoko_for_Palworld_v2.2.12_full.zip",
        {"Uchinoko_for_Palworld_v2.2.12_full.zip": {"status": "unknown"}},
        "2026-07-31T00:00:00Z", "2026-07-31T00:05:00Z")
    body = pc.build_issue_body(doc)
    assert "RED" in body
    assert "Uchinoko_for_Palworld_v2.2.12_full.zip" in body
    assert "pub_canary.py" in body


# =====================================================================
# scan_release_assets + classify_verdict: 統合の負の対照
# (av_scan_gate.py 本体のfake run_fnをここでも再現し、実Defender非依存で
#  「実際に検知されたらRED」を通しで確認する)
# =====================================================================

class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_fake_av_run_fn(detect_sample=False, detect_control=True):
    def fake_run(cmd, **kwargs):
        joined = " ".join(str(c) for c in cmd)
        if "Get-MpComputerStatus" in joined:
            return _FakeCompletedProcess(returncode=0,
                                          stdout=json.dumps({"AMServiceEnabled": True}))
        if "Set-Content" in joined:
            return _FakeCompletedProcess(returncode=0)
        if "-Scan" in cmd:
            target = cmd[cmd.index("-File") + 1]
            should_detect = (
                (detect_sample and os.path.basename(target) == "sample") or
                (detect_control and os.path.basename(target) == "control")
            )
            if should_detect:
                for f in glob.glob(os.path.join(target, "**", "*"), recursive=True):
                    if os.path.isfile(f):
                        os.remove(f)
            return _FakeCompletedProcess(returncode=0)
        return _FakeCompletedProcess(returncode=0)
    return fake_run


def _make_release_zip(zip_path):
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Uchinoko_for_Palworld/Uchinoko.exe", b"MZ-fake-launcher-bytes")
        zf.writestr("Uchinoko_for_Palworld/README.md", b"not an executable")


def test_scan_release_assets_and_classify_green_on_clean_scan(tmp_path):
    pc = _import_pub_canary()
    zip_path = str(tmp_path / "Uchinoko_for_Palworld_v9.9.9_full.zip")
    _make_release_zip(zip_path)
    scan_root = str(tmp_path / "scan")
    mpcmdrun = tmp_path / "MpCmdRun.exe"
    mpcmdrun.write_bytes(b"dummy")

    fake_run = _make_fake_av_run_fn(detect_sample=False, detect_control=True)
    results = pc.scan_release_assets([zip_path], scan_root, run_fn=fake_run,
                                      mpcmdrun_path=str(mpcmdrun))
    verdict, reason = pc.classify_verdict(results)

    assert verdict == pc.VERDICT_GREEN
    assert results[0]["asset"] == os.path.basename(zip_path)


def test_scan_release_assets_and_classify_red_on_detected_scan(tmp_path):
    """負の対照(受入条件の核心): 配布資産内のexeが検出されたら、通しでREDになる。"""
    pc = _import_pub_canary()
    zip_path = str(tmp_path / "Uchinoko_for_Palworld_v9.9.9_full.zip")
    _make_release_zip(zip_path)
    scan_root = str(tmp_path / "scan")
    mpcmdrun = tmp_path / "MpCmdRun.exe"
    mpcmdrun.write_bytes(b"dummy")

    fake_run = _make_fake_av_run_fn(detect_sample=True, detect_control=True)
    results = pc.scan_release_assets([zip_path], scan_root, run_fn=fake_run,
                                      mpcmdrun_path=str(mpcmdrun))
    verdict, reason = pc.classify_verdict(results)

    assert verdict == pc.VERDICT_RED
    assert os.path.basename(zip_path) in reason


def test_scan_release_assets_and_classify_inconclusive_when_control_fails(tmp_path):
    pc = _import_pub_canary()
    zip_path = str(tmp_path / "Uchinoko_for_Palworld_v9.9.9_full.zip")
    _make_release_zip(zip_path)
    scan_root = str(tmp_path / "scan")
    mpcmdrun = tmp_path / "MpCmdRun.exe"
    mpcmdrun.write_bytes(b"dummy")

    fake_run = _make_fake_av_run_fn(detect_sample=False, detect_control=False)
    results = pc.scan_release_assets([zip_path], scan_root, run_fn=fake_run,
                                      mpcmdrun_path=str(mpcmdrun))
    verdict, reason = pc.classify_verdict(results)

    assert verdict == pc.VERDICT_INCONCLUSIVE


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# =====================================================================
# cleanup_work_dir: 検査後のDL物削除(dev#446 work肥大とディスク配慮)
# =====================================================================

class TestCleanupWorkDir:
    def test_deletes_work_dir_recursively(self, tmp_path):
        pc = _import_pub_canary()
        wd = tmp_path / "canary_run" / "20260731T000000Z"
        (wd / "download").mkdir(parents=True)
        (wd / "download" / "asset.zip").write_bytes(b"x" * 128)
        pc.cleanup_work_dir(str(wd))
        assert not wd.exists()

    def test_keep_flag_retains_downloads(self, tmp_path):
        pc = _import_pub_canary()
        wd = tmp_path / "run"
        wd.mkdir()
        (wd / "asset.zip").write_bytes(b"x")
        pc.cleanup_work_dir(str(wd), keep=True)
        assert (wd / "asset.zip").exists()

    def test_readonly_file_is_removed(self, tmp_path):
        # 負の対照の裏返し: dev#431と同型のPermissionError(読み取り専用)でも消し切る
        import stat as _stat
        pc = _import_pub_canary()
        wd = tmp_path / "run"
        wd.mkdir()
        ro = wd / "readonly.bin"
        ro.write_bytes(b"x")
        os.chmod(ro, _stat.S_IREAD)
        pc.cleanup_work_dir(str(wd))
        assert not wd.exists()

    def test_missing_dir_is_noop(self, tmp_path):
        pc = _import_pub_canary()
        pc.cleanup_work_dir(str(tmp_path / "never_created"))  # 例外を出さないこと
