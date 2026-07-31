# -*- coding: utf-8 -*-
r"""dev#223(relgateスキップ記録の自動昇格をrelease.pyの最終合格ブロックへ配線)
の受入試験。

背景: relgateの中間ハッシュスキップ機構(dev#27、
devtools\relgate_skip_record.json)は、検体ごとのPhase 0-1だけを実行し、
正規化後中間生成物のダイジェストが前回リリースの記録と一致すれば
noue工程(Phase 2-6、全体の9割超)を省略できる仕組みだが、記録更新
(`relgate.py --promote-skip-record`)がrelease.py本体に一切配線されておらず、
v2.0.0直後の1回を最後に更新されないまま放置されていた(v2.1.0・v2.2.0の
2回連続で忘れられた)。本issueはpromote_relgate_baselines()(dev#61)と
同じ「全ゲート+コミット/タグ確定という完全合格の直後にだけ呼ぶ、失敗しても
リリース自体は取り消さない」流儀で自動配線する。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、この変更は
pak不変(Layers-Affected: none、呼び出し配線のみでrelgate.py本体の意味論は
変えない)のため、本試験は単体テスト+負の対照のみで受入とする(実際の
relgate.py実行・実pak変換は一切行わない。promote_fn/report経由の全差し替え)。

対象の負の対照(指示書どおり3点):
  1. 正の対照: PASS時(relgate_result非cache_hit)に昇格が呼ばれる
  2. 負の対照: FAIL(main()の早期リターン)時は昇格が一切呼ばれない
  3. 負の対照: 昇格(promote_fn)が失敗/例外を送出しても、呼び出し元へは
     例外が伝播せず、ok=Falseを返すだけ(release.py全体のrcを変えない)

実行: python -m pytest tests\shipcheck\test_release_relgate_skip_promotion.py -v
"""
import argparse
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
TESTS_RELGATE = os.path.join(REPO, "tests", "relgate")

for p in (DEVTOOLS, TESTS_RELGATE):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_release():
    return importlib.import_module("release")


def _import_relgate():
    return importlib.import_module("relgate")


class DummyReport:
    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)

    def joined(self):
        return "\n".join(self.lines)


# =====================================================================
# promote_relgate_skip_record(): relgate.promote_skip_record()への配線
# =====================================================================

def test_promote_relgate_skip_record_calls_promote_fn_with_cli_default_args(tmp_path):
    """release.pyから呼んだときの引数が、relgate.pyのCLI既定値
    (--skip-record/--pak-cache-dir/--promote-allow-unreleased)と完全一致する
    こと -- 手動で`relgate.py --promote-skip-record`を叩いた場合と同じ挙動に
    なることの直接の証拠。"""
    release = _import_release()
    relgate_mod = _import_relgate()
    captured = {}

    def fake_promote_fn(args, work_dir, report):
        captured["args"] = args
        captured["work_dir"] = work_dir
        captured["report"] = report
        return 0

    report = DummyReport()
    relgate_work = str(tmp_path / "relgate_work")
    ok, detail = release.promote_relgate_skip_record(relgate_work, report, promote_fn=fake_promote_fn)

    assert ok is True
    assert "rc=0" in detail
    assert captured["work_dir"] == relgate_work
    assert captured["report"] is report
    args = captured["args"]
    assert isinstance(args, argparse.Namespace)
    assert args.skip_record == relgate_mod.intermediate_hash.DEFAULT_RECORD_PATH
    assert args.pak_cache_dir == relgate_mod.intermediate_hash.DEFAULT_PAK_CACHE_DIR
    assert args.promote_allow_unreleased is False


def test_promote_relgate_skip_record_returns_not_ok_on_nonzero_rc():
    release = _import_release()
    report = DummyReport()

    def fake_promote_fn(args, work_dir, report):
        return 1

    ok, detail = release.promote_relgate_skip_record("dummy_work", report, promote_fn=fake_promote_fn)
    assert ok is False
    assert "rc=1" in detail


def test_promote_relgate_skip_record_negative_control_exception_does_not_propagate():
    """負の対照3: promote_fn自体が未捕捉の例外を送出しても、
    promote_relgate_skip_record()はここで吸収し、例外を外へ伝播させない
    (release.py全体のrcには一切影響させない構造的保証)。"""
    release = _import_release()
    report = DummyReport()

    def boom(args, work_dir, report):
        raise RuntimeError("disk full (simulated)")

    ok, detail = release.promote_relgate_skip_record("dummy_work", report, promote_fn=boom)

    assert ok is False
    assert "disk full" in detail
    assert any("WARN" in line for line in report.lines)


# =====================================================================
# run_relgate_skip_promotion_step(): main()から呼ぶゲーティング込みラッパ
# =====================================================================

def test_run_relgate_skip_promotion_step_positive_control_calls_promote_when_full_run(tmp_path):
    """正の対照1: relgateがこのrunでcache_hitしていない(=フル実行された、
    PASSに至る通常経路)場合、昇格が呼ばれる。"""
    release = _import_release()
    report = DummyReport()
    relgate_work = str(tmp_path / "relgate")
    relgate_result = {"ok": True, "relgate_work": relgate_work}  # cache_hitキー無し
    called = {}

    def fake_promote_fn(args, work_dir, report):
        called["work_dir"] = work_dir
        return 0

    result = release.run_relgate_skip_promotion_step(relgate_result, report, promote_fn=fake_promote_fn)

    assert called["work_dir"] == relgate_work
    assert result == {"attempted": True, "ok": True, "detail": "promote_skip_record() rc=0"}
    assert any("OK" in line for line in report.lines)


def test_run_relgate_skip_promotion_step_negative_control_skips_on_cache_hit(tmp_path):
    """負の対照2相当(cache_hit=このrunでrelgate.pyをフル実行していない):
    promote_fnが一切呼ばれないことを直接検証する(呼ばれたら即AssertionError)。"""
    release = _import_release()
    report = DummyReport()
    relgate_result = {"ok": True, "cache_hit": True,
                       "relgate_work": str(tmp_path / "relgate")}

    def boom(*a, **kw):
        raise AssertionError("cache_hit時はpromote_relgate_skip_record()を呼んではならない")

    result = release.run_relgate_skip_promotion_step(relgate_result, report, promote_fn=boom)

    assert result == {
        "attempted": False,
        "reason": "relgate cache_hit(このrunでrelgate.pyをフル実行していない、dev#223)",
    }
    assert any("スキップ" in line for line in report.lines)


def test_run_relgate_skip_promotion_step_survives_promote_failure(tmp_path):
    """負の対照3(ステップ経由): 昇格が失敗(ok=False)しても、
    run_relgate_skip_promotion_step()自体は例外を投げず結果を返すだけ。"""
    release = _import_release()
    report = DummyReport()
    relgate_result = {"ok": True, "relgate_work": str(tmp_path / "relgate")}

    def fake_promote_fn(args, work_dir, report):
        return 1  # 失敗

    result = release.run_relgate_skip_promotion_step(relgate_result, report, promote_fn=fake_promote_fn)

    assert result["attempted"] is True
    assert result["ok"] is False
    assert any("警告" in line for line in report.lines)


# =====================================================================
# main()レベルの統合確認: FAIL(早期リターン)時は一切呼ばれない
# =====================================================================

def test_main_fail_path_never_calls_relgate_skip_promotion_step(tmp_path, monkeypatch):
    """負の対照2(main()レベル): 緑(PASS)runを--resume-fromに渡すと、
    引数検証段階で即FAILする(test_release_resume.pyの
    test_main_rejects_resume_from_pass_run_before_any_side_effectと同一の
    早期FAIL経路)。この経路ではrun_relgate_skip_promotion_step()を含む
    パイプライン本体に一切到達しないため、それを直接の証拠として確認する
    (呼ばれたら即AssertionError)。"""
    release = _import_release()
    run_dir = tmp_path / "run_20260730_090909"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("...\n総合判定: PASS\n", encoding="utf-8")
    monkeypatch.setattr(release, "RELEASE_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(release, "RELEASE_CERT_LEDGER_DIR", str(tmp_path))
    monkeypatch.setattr(release, "run_approval_gate", lambda issue_number, report: (True, "OK(dummy)"))

    def boom(*a, **kw):
        raise AssertionError("FAIL経路でrun_relgate_skip_promotion_step()が呼ばれてはならない")

    monkeypatch.setattr(release, "run_relgate_skip_promotion_step", boom)

    rc = release.main(["--bump", "patch", "--pak", "none",
                        "--approval-issue", "201",
                        "--resume-from", "run_20260730_090909"])

    assert rc == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
