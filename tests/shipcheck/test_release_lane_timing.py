# -*- coding: utf-8 -*-
r"""dev#220(release_profile.md §4「計測ログの追加提案」)の単体試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、実release.py実行・
実relgate実行・実WSB実行は一切課さない(純関数+write_cert()の入出力確認のみ)。

対象:
  - release.build_parallel_lane_timing() / format_parallel_lane_timing_summary()
    (§4.1: 並列レーン(dist_smoke/relgate/WSB)の壁時計時間+レーン全体maxを
    cert/ログへ残す)
  - release.write_cert() が parallel_lane_timing を cert JSON へ書くこと
  - release.format_relgate_skip_summary()
    (§4.3: relgateの中間ハッシュスキップ機構(dev#27)のhit/miss要約)

負の対照(このWPの受入条件):
  - タイマー出力が全部欠けたレポート(all None)でも0秒と偽らずNoneのまま返す
  - サマリ文字列は3レーン名を常に列挙する(値が無いレーンを黙って省略しない)
  - スキップ判定を1件も試みていない(全検体disabled/not_attempted)場合、
    「hit/miss無し」を明示する専用メッセージになり、hit扱いに丸め込まれない

実行: python -m pytest tests\shipcheck\test_release_lane_timing.py -v
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_release():
    return importlib.import_module("release")


class DummyReport:
    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)


# =====================================================================
# §4.1: build_parallel_lane_timing() / format_parallel_lane_timing_summary()
# =====================================================================

def test_build_parallel_lane_timing_all_present_takes_max():
    release = _import_release()
    timing = release.build_parallel_lane_timing(
        {"dist_smoke": 372.5, "relgate_layers12": 398.2, "wsb_convert": 517.9})
    assert timing["lane_wall_sec_max"] == 517.9
    assert timing["lanes"] == {"dist_smoke": 372.5, "relgate_layers12": 398.2,
                                "wsb_convert": 517.9}


def test_build_parallel_lane_timing_ignores_none_lanes_for_max():
    """--resume-from経由のキャッシュ参照でsubmitされなかったレーン(None)は、
    壁時計時間0として最大値計算に混ざってはならない(0は「一瞬で終わった」に
    見えてしまうため、単に無視する)。"""
    release = _import_release()
    timing = release.build_parallel_lane_timing(
        {"dist_smoke": None, "relgate_layers12": None, "wsb_convert": 506.1})
    assert timing["lane_wall_sec_max"] == 506.1
    assert timing["lanes"]["dist_smoke"] is None


def test_build_parallel_lane_timing_all_none_does_not_fabricate_zero():
    """負の対照: タイマー出力が全部欠けたレポート(理論上到達しないはずだが、
    fail-safeとして)でも、lane_wall_sec_maxを0にしない(Noneのまま返す)。
    「計測できなかった」と「0秒だった」を区別できなければ、後から見て
    誤読される穴になる。"""
    release = _import_release()
    timing = release.build_parallel_lane_timing(
        {"dist_smoke": None, "relgate_layers12": None, "wsb_convert": None})
    assert timing["lane_wall_sec_max"] is None


def test_format_parallel_lane_timing_summary_always_lists_all_three_lanes():
    """負の対照: 値が無い(None)レーンでもサマリ文字列から名前ごと消えては
    ならない(「欠けたレポート」を機械的に検出できるようにするための表示)。"""
    release = _import_release()
    timing = release.build_parallel_lane_timing(
        {"dist_smoke": None, "relgate_layers12": 398.2, "wsb_convert": 506.1})
    summary = release.format_parallel_lane_timing_summary(timing)
    assert "dist_smoke" in summary
    assert "relgate_layers12" in summary
    assert "wsb_convert" in summary
    assert "skipped(cache)" in summary, "Noneのレーンは明示的にskipped(cache)と表示すべき"
    assert "506.1" in summary


def test_format_parallel_lane_timing_summary_reports_unmeasurable_max():
    release = _import_release()
    timing = release.build_parallel_lane_timing(
        {"dist_smoke": None, "relgate_layers12": None, "wsb_convert": None})
    summary = release.format_parallel_lane_timing_summary(timing)
    assert "計測不能" in summary


# =====================================================================
# write_cert() が parallel_lane_timing を記録すること
# =====================================================================

def test_write_cert_records_parallel_lane_timing(tmp_path, monkeypatch):
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))
    zip_path = tmp_path / "dummy.zip"
    zip_path.write_bytes(b"zip-bytes")
    report = DummyReport()

    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    timing = release.build_parallel_lane_timing(
        {"dist_smoke": 100.0, "relgate_layers12": 150.0, "wsb_convert": 500.0})
    path = release.write_cert(
        "deadbeefcafebabe", "deadbee", [{"name": "x", "ok": True}],
        {"zip_path": str(zip_path)}, [], report, gates_by_mode=gates_by_mode,
        parallel_lane_timing=timing)

    with open(path, encoding="utf-8") as f:
        cert = json.load(f)
    assert cert["parallel_lane_timing"]["lane_wall_sec_max"] == 500.0
    assert cert["parallel_lane_timing"]["lanes"]["wsb_convert"] == 500.0


def test_write_cert_parallel_lane_timing_defaults_to_none_for_back_compat(tmp_path, monkeypatch):
    """呼び出し側がparallel_lane_timingを渡さない(既存の呼び出し元・過去の
    テスト)場合でも write_cert() は落ちず、フィールドはNoneのまま記録される
    (後方互換)。"""
    release = _import_release()
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))
    zip_path = tmp_path / "dummy.zip"
    zip_path.write_bytes(b"zip-bytes")
    report = DummyReport()

    gates_by_mode = {g: "executed" for g in release.COVERAGE_GATES_TOTAL}
    path = release.write_cert(
        "deadbeefcafebabe", "deadbee", [{"name": "x", "ok": True}],
        {"zip_path": str(zip_path)}, [], report, gates_by_mode=gates_by_mode)

    with open(path, encoding="utf-8") as f:
        cert = json.load(f)
    assert cert["parallel_lane_timing"] is None


# =====================================================================
# §4.3: format_relgate_skip_summary()
# =====================================================================

def test_format_relgate_skip_summary_reports_hit_and_miss():
    release = _import_release()
    results_doc = {
        "avatars": {
            "vrm0_kate": {"skip_decision": "hit", "skip_reason": "中間ハッシュ一致(pak継承): abc123…"},
            "vrm1_seedsan": {"skip_decision": "miss", "skip_reason": "中間ハッシュ不一致(意図的変更または上流の退行)"},
            "prefab_flatapron": {"skip_decision": "miss", "skip_reason": "記録にこの検体のエントリが無い"},
        }
    }
    summary = release.format_relgate_skip_summary(results_doc)
    assert "vrm0_kate=hit" in summary
    assert "vrm1_seedsan=miss" in summary
    assert "prefab_flatapron=miss" in summary


def test_format_relgate_skip_summary_none_results_doc():
    release = _import_release()
    summary = release.format_relgate_skip_summary(None)
    assert "要約不能" in summary


def test_format_relgate_skip_summary_no_attempts_is_not_reported_as_hit():
    """負の対照: 全検体がdisabled/not_attempted(判定を1件も試みていない)の
    ときに、hit/missどちらの体裁にも丸め込まれず「該当なし」と明示すること。
    ここを間違えると、スキップ機構が実は死んでいるのに何か効いているように
    誤読されるレポートになる(release_profile.md §2-3が指摘した実際の障害
    ——記録がv2.0.0時点のままでv2.1.0/v2.2.0では機能していない——を、この
    要約が正しく「該当なし」として映すことの確認)。"""
    release = _import_release()
    results_doc = {
        "avatars": {
            "vrm0_kate": {"skip_decision": "disabled", "skip_reason": "スキップ機構が無効"},
            "vrm1_seedsan": {"skip_decision": "not_attempted", "skip_reason": "baseline未整備"},
        }
    }
    summary = release.format_relgate_skip_summary(results_doc)
    assert "該当なし" in summary
    # ヘッダ文言自体の"hit/miss"表記は許容するが、"=hit"/"=miss"という
    # 検体別の実測結果としては1件も出てはならない
    assert "=hit" not in summary
    assert "=miss" not in summary


def test_format_relgate_skip_summary_empty_avatars():
    release = _import_release()
    summary = release.format_relgate_skip_summary({"avatars": {}})
    assert "該当なし" in summary


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
