# -*- coding: utf-8 -*-
r"""dev issue #26 / dev issue #1: u28_zip_audit.py の負の対照テスト。

負の対照①: SK系スタブ(SK_*.uasset/.uexp)入りzipはFAILすること
負の対照②: 鮮度照合の比較件数0件(fail-open)はFAILすること
正の対照  : SKスタブ無し+鮮度照合が成立するzipは(その2観点では)PASSすること

実行: python -m pytest tests\shipcheck\test_u28_zip_audit.py -v
"""
import os
import subprocess
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
AUDIT = os.path.join(REPO, "devtools", "u28_zip_audit.py")
STAGE = "Uchinoko_for_Palworld"   # v2.0.0改名(u28_zip_audit.STAGE_ROOTと一致させる)

# リポジトリ実物のpipelineファイル(鮮度照合を成立させるために同一バイトで入れる)
PIPELINE_SAMPLE_REL = "py/vp_core.py"
PIPELINE_SAMPLE_ABS = os.path.join(REPO, "pipeline", "py", "vp_core.py")

# リポジトリ実物のSKスタブ(負の対照①の混入物。まだ同梱中の実ファイルを使う。
# スタブが将来リポジトリから削除されたらダミーバイトへフォールバックする)
SK_STUB_REL = ("py/noue_master/pak_extract_extra/Player/Hair/Hair001/"
               "SK_Player_Hair001.uasset")
SK_STUB_ABS = os.path.join(REPO, "pipeline", *SK_STUB_REL.split("/"))


def _base_entries():
    """レイアウト系チェック(ルート構成)を通る最小構成。
    2026-07-31のランチャー廃止・_internal廃止後のフラット構成
    (STAGE直下に本体一式)に追随済み。"""
    with open(PIPELINE_SAMPLE_ABS, "rb") as f:
        sample = f.read()
    return [
        (STAGE + "/README.md", b"readme"),
        (STAGE + "/LICENSE", b"license"),
        (STAGE + "/pipeline/" + PIPELINE_SAMPLE_REL, sample),
    ]


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return path


def _run_audit(zip_path):
    proc = subprocess.run(
        [sys.executable, AUDIT, str(zip_path), "--repo-root", REPO,
         "--out", str(zip_path) + ".prov.json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def test_positive_control_passes(tmp_path):
    """SKスタブ無し・鮮度照合成立のzipはPASS(exit 0)。
    これが通らないと以下の負の対照が「何でもFAILする監査」の疑いになる。"""
    zp = _make_zip(tmp_path / "clean.zip", _base_entries())
    code, out = _run_audit(zp)
    assert code == 0, out


def test_negative_control_sk_stub_fails(tmp_path):
    """負の対照①: SK系スタブ入りzipはFAILし、SKスタブ検出が明示されること。"""
    if os.path.isfile(SK_STUB_ABS):
        with open(SK_STUB_ABS, "rb") as f:
            stub_bytes = f.read()
    else:  # スタブ削除後(実行時生成移行後)もこのテストが機能し続けるように
        stub_bytes = b"\x00" * 64
    entries = _base_entries() + [
        (STAGE + "/pipeline/" + SK_STUB_REL, stub_bytes),
    ]
    zp = _make_zip(tmp_path / "with_sk_stub.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "SK系スタブ" in out and "FAIL" in out, out
    assert "SK_Player_Hair001.uasset" in out, out


def test_negative_control_sk_stub_anywhere_fails(tmp_path):
    """負の対照①': 置き場所を変えたSKスタブ(pak_extract_extra外)も検知する。"""
    entries = _base_entries() + [
        (STAGE + "/assets/third_party/SK_Whatever.uexp", b"\x00" * 16),
    ]
    zp = _make_zip(tmp_path / "sk_moved.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "SK系スタブ" in out, out


def test_negative_control_zero_checked_fails(tmp_path):
    """負の対照②(dev issue #1): 鮮度照合の比較件数0件はPASSではなくFAIL。"""
    entries = [e for e in _base_entries()
               if not e[0].startswith(STAGE + "/pipeline/")]
    zp = _make_zip(tmp_path / "no_pipeline.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "比較件数0件" in out, out
