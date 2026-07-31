# -*- coding: utf-8 -*-
r"""dev#79「宣言突合」ツール(devtools\check_layers_affected.py)の受入試験。

実git操作・実変換は課さない。parse_declared/diff_report(純粋関数)と
compute_snapshot(tmp_pathの疑似job_dir)だけを検証する。

実行: python -m pytest tests\shipcheck\test_check_layers_affected.py -v
"""
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import():
    return importlib.reload(importlib.import_module("check_layers_affected"))


# --- parse_declared -----------------------------------------------------------

def test_parse_declared_none_is_empty_set():
    m = _import()
    assert m.parse_declared("none") == frozenset()
    assert m.parse_declared("") == frozenset()
    assert m.parse_declared("None") == frozenset()


def test_parse_declared_comma_and_space_separated():
    m = _import()
    assert m.parse_declared("L1b,L2") == frozenset({"L1b", "L2"})
    assert m.parse_declared("L1b L2") == frozenset({"L1b", "L2"})
    assert m.parse_declared(" L1b , L2 ") == frozenset({"L1b", "L2"})


def test_parse_declared_rejects_unknown_layer_code():
    m = _import()
    with pytest.raises(ValueError):
        m.parse_declared("L99")


# --- diff_report: FAIL/WARN/OK の3方向判定 --------------------------------------

def test_diff_report_fail_on_undeclared_change():
    m = _import()
    before = {"L1": "aaa", "L1b": "bbb", "L2": "ccc", "L3": "ddd"}
    after = {"L1": "aaa", "L1b": "bbb-CHANGED", "L2": "ccc", "L3": "ddd"}
    ok, lines = m.diff_report(before, after, declared=frozenset())  # 宣言はnone
    assert ok is False
    assert any("FAIL" in line and "L1b" in line for line in lines)


def test_diff_report_ok_on_declared_change():
    m = _import()
    before = {"L1": "aaa", "L1b": "bbb", "L2": "ccc", "L3": "ddd"}
    after = {"L1": "aaa", "L1b": "bbb-CHANGED", "L2": "ccc", "L3": "ddd"}
    ok, lines = m.diff_report(before, after, declared=frozenset({"L1b"}))
    assert ok is True
    assert any(line.startswith("[L1b] OK") for line in lines)


def test_diff_report_warn_on_declared_but_unchanged():
    m = _import()
    before = {"L1": "aaa", "L1b": "bbb", "L2": "ccc", "L3": "ddd"}
    after = dict(before)  # 何も変わっていない
    ok, lines = m.diff_report(before, after, declared=frozenset({"L1b"}))
    assert ok is True, "WARNはokに影響しない(#79裁定: 警告運用)"
    assert any(line.startswith("[L1b] WARN") for line in lines)


def test_diff_report_ok_on_none_declared_and_none_changed():
    m = _import()
    before = {"L1": "aaa", "L1b": "bbb", "L2": "ccc", "L3": "ddd"}
    after = dict(before)
    ok, lines = m.diff_report(before, after, declared=frozenset())
    assert ok is True
    assert all("FAIL" not in line and "WARN" not in line for line in lines)


# --- compute_snapshot: job_dir配下の層別出力を実際にハッシュできること ------------

def _make_fake_job_dir(tmp_path):
    job_dir = tmp_path / "avatar_job"
    (job_dir / "converted").mkdir(parents=True)
    (job_dir / "converted" / "step02_female.blend").write_bytes(b"fake-blend-f")
    (job_dir / "build" / "atlas").mkdir(parents=True)
    (job_dir / "build" / "atlas" / "atlas_body.png").write_bytes(b"fake-png")
    (job_dir / "build" / "noue_mat_override").mkdir(parents=True)
    (job_dir / "build" / "noue_mat_override" / "M_VP_00.uasset").write_bytes(b"fake-mat")
    (job_dir / "build" / "noue_mi_override").mkdir(parents=True)
    return str(job_dir)


def test_compute_snapshot_covers_all_tracked_layers(tmp_path):
    m = _import()
    job_dir = _make_fake_job_dir(tmp_path)
    snap = m.compute_snapshot(job_dir)
    assert set(snap.keys()) == set(m.TRACKED_LAYERS)
    for digest in snap.values():
        assert isinstance(digest, str) and len(digest) == 64


def test_compute_snapshot_changes_when_layer_output_changes(tmp_path):
    m = _import()
    job_dir = _make_fake_job_dir(tmp_path)
    snap_before = m.compute_snapshot(job_dir)

    with open(os.path.join(job_dir, "build", "atlas", "atlas_body.png"), "wb") as f:
        f.write(b"fake-png-CHANGED")
    snap_after = m.compute_snapshot(job_dir)

    assert snap_after["L1b"] != snap_before["L1b"]
    # 他の層は無関係なので不変(L1b以外に波及してはならない)
    assert snap_after["L1"] == snap_before["L1"]
    assert snap_after["L2"] == snap_before["L2"]
    assert snap_after["L3"] != snap_before["L3"], (
        "L3はbuild\\全体のバルクなのでatlasの変化にも反応する(L1bはL3の入力配下、"
        "既存配置のネストどおり)")


# --- CLI往復(snapshot -> diff) --------------------------------------------------

def test_cli_snapshot_then_diff_roundtrip(tmp_path, capsys):
    m = _import()
    job_dir = _make_fake_job_dir(tmp_path)

    before_json = str(tmp_path / "before.json")
    args_before = m.argparse.Namespace(job_dir=job_dir, out=before_json)
    assert m.cmd_snapshot(args_before) == 0

    with open(os.path.join(job_dir, "build", "atlas", "atlas_body.png"), "wb") as f:
        f.write(b"fake-png-CHANGED-for-diff")
    after_json = str(tmp_path / "after.json")
    args_after = m.argparse.Namespace(job_dir=job_dir, out=after_json)
    assert m.cmd_snapshot(args_after) == 0

    # 宣言 = L1b のみ(このケースはL1bとL3が両方変化するが、L3は既存配置上
    # L1bを内包するバルクなので、宣言はL1bとL3の両方が必要になる。
    # ここでは「宣言漏れが正しくFAILすること」を確認する目的でL1bのみ宣言する)
    args_diff = m.argparse.Namespace(before=before_json, after=after_json,
                                      commit="HEAD", declared="L1b")
    rc = m.cmd_diff(args_diff)
    captured = capsys.readouterr()
    assert rc == 1, "L3が未宣言のまま変化しているのでFAILしなければならない"
    assert "L3" in captured.out and "FAIL" in captured.out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
