# -*- coding: utf-8 -*-
r"""dev issue #26 / dev issue #1 / dev#532: u28_zip_audit.py の負の対照テスト。

負の対照①: SK系スタブ(SK_*.uasset/.uexp)入りzipはFAILすること
負の対照②: 鮮度照合の比較件数0件(fail-open)はFAILすること
            (dev#532: res\pipeline\ / res\unity\ / res\app\ の3セクションとも)
負の対照③: ルート直下(Uchinoko.bat/README.txt/res\の3点)に余計なエントリが
            混入したらFAILすること(dev#532 D1レイアウトゲート)
負の対照④: res\ 直下に想定外のエントリが混入したらFAILすること
正の対照  : 新レイアウト準拠+鮮度照合が成立するzipはPASSすること

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

# リポジトリ実物のファイル(鮮度照合を成立させるために同一バイトで入れる)。
# dev#532 D1: pipeline\に加えunity\とapp_py\(zipではres\app\)も照合対象。
PIPELINE_SAMPLE_REL = "py/vp_core.py"
PIPELINE_SAMPLE_ABS = os.path.join(REPO, "pipeline", "py", "vp_core.py")
UNITY_SAMPLE_REL = "DiveToPalworldExporter.cs"
UNITY_SAMPLE_ABS = os.path.join(REPO, "unity", UNITY_SAMPLE_REL)
APP_SAMPLE_REL = "main.py"
APP_SAMPLE_ABS = os.path.join(REPO, "app_py", APP_SAMPLE_REL)

# リポジトリ実物のSKスタブ(負の対照①の混入物。まだ同梱中の実ファイルを使う。
# スタブが将来リポジトリから削除されたらダミーバイトへフォールバックする)
SK_STUB_REL = ("py/noue_master/pak_extract_extra/Player/Hair/Hair001/"
               "SK_Player_Hair001.uasset")
SK_STUB_ABS = os.path.join(REPO, "pipeline", *SK_STUB_REL.split("/"))


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _base_entries():
    """レイアウト系チェック(ルート3点構成・res\\直下構成)と鮮度照合3セクションを
    通る最小構成。dev#532 D1(方針A)の新レイアウト:
    zipルート直下=Uchinoko.bat/README.txt/res\\のみ、本体一式はres\\配下。"""
    return [
        (STAGE + "/Uchinoko.bat", b"@echo off\r\nrem test entry point\r\n"),
        (STAGE + "/README.txt", b"readme"),
        (STAGE + "/res/pipeline/" + PIPELINE_SAMPLE_REL, _read(PIPELINE_SAMPLE_ABS)),
        (STAGE + "/res/unity/" + UNITY_SAMPLE_REL, _read(UNITY_SAMPLE_ABS)),
        (STAGE + "/res/app/" + APP_SAMPLE_REL, _read(APP_SAMPLE_ABS)),
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
    """新レイアウト準拠・鮮度照合成立のzipはPASS(exit 0)。
    これが通らないと以下の負の対照が「何でもFAILする監査」の疑いになる。"""
    zp = _make_zip(tmp_path / "clean.zip", _base_entries())
    code, out = _run_audit(zp)
    assert code == 0, out


def test_negative_control_sk_stub_fails(tmp_path):
    """負の対照①: SK系スタブ入りzipはFAILし、SKスタブ検出が明示されること。"""
    if os.path.isfile(SK_STUB_ABS):
        stub_bytes = _read(SK_STUB_ABS)
    else:  # スタブ削除後(実行時生成移行後)もこのテストが機能し続けるように
        stub_bytes = b"\x00" * 64
    entries = _base_entries() + [
        (STAGE + "/res/pipeline/" + SK_STUB_REL, stub_bytes),
    ]
    zp = _make_zip(tmp_path / "with_sk_stub.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "SK系スタブ" in out and "FAIL" in out, out
    assert "SK_Player_Hair001.uasset" in out, out


def test_negative_control_sk_stub_anywhere_fails(tmp_path):
    """負の対照①': 置き場所を変えたSKスタブ(pak_extract_extra外)も検知する。"""
    entries = _base_entries() + [
        (STAGE + "/res/assets/third_party/SK_Whatever.uexp", b"\x00" * 16),
    ]
    zp = _make_zip(tmp_path / "sk_moved.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "SK系スタブ" in out, out


@pytest.mark.parametrize("drop_prefix", [
    STAGE + "/res/pipeline/",
    STAGE + "/res/unity/",
    STAGE + "/res/app/",
], ids=["pipeline", "unity", "app"])
def test_negative_control_zero_checked_fails(tmp_path, drop_prefix):
    """負の対照②(dev issue #1 / dev#532): 鮮度照合の比較件数0件は、
    3セクション(res\\pipeline\\ / res\\unity\\ / res\\app\\)のどれが欠けても
    PASSではなくFAIL(鮮度照合対象の欠落=fail-openの封じ込め)。"""
    entries = [e for e in _base_entries() if not e[0].startswith(drop_prefix)]
    zp = _make_zip(tmp_path / "dropped_section.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "比較件数0件" in out, out


def test_negative_control_unexpected_root_entry_fails(tmp_path):
    """負の対照③(dev#532 D1): ルート直下(3点のみ許可)への余計なファイル混入は
    FAIL(旧レイアウト残骸・exe再混入の検知)。"""
    entries = _base_entries() + [
        (STAGE + "/Uchinoko.exe", b"MZ fake"),
    ]
    zp = _make_zip(tmp_path / "extra_root.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "想定外のトップレベルエントリ" in out, out
    assert "Uchinoko.exe" in out, out


def test_negative_control_unexpected_res_entry_fails(tmp_path):
    """負の対照④(dev#532 D1): res\\ 直下への想定外エントリ混入はFAIL
    (ルート3点許可の陰でres\\が無検査になる穴の封じ込め)。"""
    entries = _base_entries() + [
        (STAGE + "/res/tools/blender/readme.txt", b"should not be here"),
    ]
    zp = _make_zip(tmp_path / "extra_res.zip", entries)
    code, out = _run_audit(zp)
    assert code == 1, out
    assert "想定外のres直下エントリ" in out, out
