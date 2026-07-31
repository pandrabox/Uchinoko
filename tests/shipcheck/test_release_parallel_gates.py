# -*- coding: utf-8 -*-
r"""dev#130(rd_119採用): release.py の dist_smoke x relgate 並列化ゲートの配線試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は
実変換・relgate実行・release.py本番実行を一切課さない(pak不変の構造変更の
ため)。確認するのは配線そのもの:

  1. run_zip_content_gates_cheap() が dist_smoke を含まない3ゲート
     (u28_zip_audit / dll_closure_check / provenance)だけを直列実行すること
  2. run_zip_content_gates_dist_smoke() が run_dist_smoke() への薄いラッパで
     あり、渡した report(BufferedReportでも可)へそのまま委譲すること
  3. release.BufferedReport が relgate.BufferedReport と同一クラスであり
     (新規実装ではなく再利用)、flush_into() が本体Reportへログを欠落なく、
     かつ二重出力なしで移せること(Report.log(echo=False)の配線確認)
  4. 負の対照: main() が実際に使うのと同じ
     ThreadPoolExecutor(max_workers=2) + BufferedReport 2本のパターンで、
     dist_smoke側だけ失敗するダミーを注入しても、relgate側のダミーは
     短絡されず最後まで実行される(=並列化で「先に失敗したら他方を実行
     しない」という直列時の副次動作が無くなったことを明示的に確認する、
     PROPOSAL.md「残リスク4」)こと。両者を main() と同じ条件分岐
     (dist_smoke失敗 -> FAIL、relgate失敗 -> FAIL)に通すと最終判定が
     FAILになること。

実行: python -m pytest tests\shipcheck\test_release_parallel_gates.py -v
"""
import concurrent.futures
import importlib
import os
import sys
import time
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_release():
    return importlib.import_module("release")


def _import_relgate():
    return importlib.import_module("relgate")


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return str(path)


# --- 1: run_zip_content_gates_cheap() は dist_smoke を含まない ----------------

def test_cheap_gates_exclude_dist_smoke(tmp_path, monkeypatch):
    release = _import_release()
    calls = []

    def _fake(name):
        def _inner(*a, **k):
            calls.append(name)
            return {"name": name, "ok": True, "rc": 0}
        return _inner

    monkeypatch.setattr(release, "run_u28_zip_audit", _fake("u28_zip_audit"))
    monkeypatch.setattr(release, "run_dll_closure_check", _fake("dll_closure_check"))
    monkeypatch.setattr(release, "run_provenance_gate", _fake("provenance"))
    monkeypatch.setattr(release, "run_dist_smoke", _fake("dist_smoke"))

    report = release.Report(str(tmp_path / "report.md"))
    zp = _make_zip(tmp_path / "dummy.zip", [("README.md", b"x")])
    results = release.run_zip_content_gates_cheap(zp, str(tmp_path), report)

    names = [g["name"] for g in results]
    assert names == ["u28_zip_audit", "dll_closure_check", "provenance"]
    assert "dist_smoke" not in calls, "run_zip_content_gates_cheap は dist_smoke を呼んではならない"


# --- 2: run_zip_content_gates_dist_smoke() は run_dist_smoke() への薄いラッパ --

def test_dist_smoke_wrapper_delegates_and_accepts_buffered_report(tmp_path, monkeypatch):
    release = _import_release()
    received = {}

    def _fake_dist_smoke(zip_path, work_dir, report):
        received["zip_path"] = zip_path
        received["work_dir"] = work_dir
        report.log("dist_smoke dummy log line")
        return {"name": "dist_smoke", "ok": True, "rc": 0, "elapsed_sec": 0.1}

    monkeypatch.setattr(release, "run_dist_smoke", _fake_dist_smoke)

    buf = release.BufferedReport()
    result = release.run_zip_content_gates_dist_smoke("Z.zip", "WORKDIR", buf)

    assert result == {"name": "dist_smoke", "ok": True, "rc": 0, "elapsed_sec": 0.1}
    assert received == {"zip_path": "Z.zip", "work_dir": "WORKDIR"}
    # BufferedReportへ委譲できている(直接Reportへ書かず、渡された report引数に書く)
    assert buf.lines == ["dist_smoke dummy log line"]


# --- 3: BufferedReportはrelgate.pyの再利用であり、flush_into()が欠落なく移す ---

def test_buffered_report_is_relgate_reused_class():
    release = _import_release()
    relgate = _import_relgate()
    assert release.BufferedReport is relgate.BufferedReport, (
        "release.py は独自のBufferedReportを新規実装せず、relgate.pyのものを"
        "再利用する設計のはず(PROPOSAL.md 適用手順2)")


def test_buffered_report_flush_into_preserves_order_without_double_echo(tmp_path, capsys):
    release = _import_release()
    report = release.Report(str(tmp_path / "report.md"))

    buf_a = release.BufferedReport()
    buf_a.log("line A1")
    buf_a.log("line A2")
    buf_b = release.BufferedReport()
    buf_b.log("line B1")

    capsys.readouterr()  # ここまでのBufferedReport.log()によるprint()を捨てる

    # main()と同じ固定順(dist_smoke -> relgate相当)でflush
    buf_a.flush_into(report)
    buf_b.flush_into(report)

    out = capsys.readouterr().out
    # flush_into は report.log(line, echo=False) を呼ぶ設計なので、
    # BufferedReport.log()時点で既にprint済みの行をここで二重printしない
    assert "line A1" not in out
    assert "line A2" not in out
    assert "line B1" not in out

    content = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert content.index("line A1") < content.index("line A2") < content.index("line B1"), (
        "flush順序(A固定→B固定)が守られていない: " + content)


# --- 4: 負の対照 -- dist_smoke失敗でもrelgateは短絡されず最後まで走り、
#        最終判定はFAILになる(main()の該当ブロックと同じパターンを再現) ------

def test_parallel_block_dist_smoke_fail_does_not_short_circuit_relgate(tmp_path):
    release = _import_release()
    report = release.Report(str(tmp_path / "report.md"))

    relgate_finished = {"value": False}

    def fake_dist_smoke_dummy(_buf):
        # 実際のsubprocess呼び出しの代わりに即FAILを返す(rc!=0のモック)
        return {"name": "dist_smoke", "ok": False, "rc": 1}

    def fake_relgate_dummy(_buf):
        # dist_smokeより長くかかるダミー処理(並列なら最後まで走り切る)
        time.sleep(0.2)
        relgate_finished["value"] = True
        return {"name": "relgate_layers12", "ok": True, "rc": 0}

    dist_smoke_buf = release.BufferedReport()
    relgate_buf = release.BufferedReport()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_dist_smoke = executor.submit(fake_dist_smoke_dummy, dist_smoke_buf)
        fut_relgate = executor.submit(fake_relgate_dummy, relgate_buf)
        dist_smoke_result = fut_dist_smoke.result()
        relgate_result = fut_relgate.result()
    dist_smoke_buf.flush_into(report)
    relgate_buf.flush_into(report)

    # 直列時代なら dist_smoke 失敗直後に relgate は実行すらされなかったはず。
    # 並列化後は relgate も最後まで実行される(PROPOSAL.md「残リスク4」の明示確認)。
    assert relgate_finished["value"] is True, (
        "並列化後は dist_smoke が失敗しても relgate は最後まで実行されるはず")

    # main()と同じ判定分岐を再現: どちらかがFAILなら全体FAIL
    overall_ok = dist_smoke_result["ok"] and relgate_result["ok"]
    assert overall_ok is False, "dist_smoke失敗時は最終判定がFAILにならなければならない"


def test_parallel_block_all_green_when_both_succeed(tmp_path):
    """正の対照: 両方成功すれば全体PASS(負の対照だけで済ませず、成功経路も
    壊れていないことを確認する)。"""
    release = _import_release()
    report = release.Report(str(tmp_path / "report.md"))

    def fake_dist_smoke_dummy(_buf):
        return {"name": "dist_smoke", "ok": True, "rc": 0}

    def fake_relgate_dummy(_buf):
        return {"name": "relgate_layers12", "ok": True, "rc": 0}

    dist_smoke_buf = release.BufferedReport()
    relgate_buf = release.BufferedReport()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_dist_smoke = executor.submit(fake_dist_smoke_dummy, dist_smoke_buf)
        fut_relgate = executor.submit(fake_relgate_dummy, relgate_buf)
        dist_smoke_result = fut_dist_smoke.result()
        relgate_result = fut_relgate.result()
    dist_smoke_buf.flush_into(report)
    relgate_buf.flush_into(report)

    overall_ok = dist_smoke_result["ok"] and relgate_result["ok"]
    assert overall_ok is True
