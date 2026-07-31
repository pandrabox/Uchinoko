# -*- coding: utf-8 -*-
r"""dev#388(出荷前AV検出試験ゲート)の受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実変換・
実release.py本番実行を課さない。だが本ゲート自体は「配布物がWindows Defender
に検出されないか」というリリース結果を直接左右する検査ロジックであり、
CLAUDE.md「唯一の例外: そのWPが意図的に変換結果を変える」には該当しない
(pak/変換結果には一切触れない、ゲートのロジック自体の単体試験)。

実Windows Defenderへの依存は排除し、`run_fn`差し替え(devtools\release.py の
fetch_approval_issue等と同じ流儀)でスキャン結果をシミュレートする。
「Defenderが実際にファイルを検疫すると、スキャン対象フォルダから当該ファイルが
消える」という一次観測(RECON_AV.md 1-3節で実測済み)を、フェイクのrun_fnが
ファイル削除で再現することでモック化している。

対象の負の対照(dev#388受入条件):
  - 実行ファイルが検出された場合 -> ゲートFAIL
  - 陽性対照(EICAR)が検出されない場合 -> 「検査不能」としてゲートFAIL
    (「スキャナが黙っていた」を「安全」と読み替えない)
  - Defenderが利用不能(MpCmdRun不在・サービス無効)な場合 -> ゲートFAIL

正の対照:
  - 実行ファイルが検出されず、陽性対照は正常に検出された場合 -> ゲートPASS

実行: python -m pytest tests\shipcheck\test_av_scan_gate.py -v
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

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_av_scan_gate():
    return importlib.import_module("av_scan_gate")


class DummyReport:
    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_fake_run_fn(defender_ok=True, motw_ok=True,
                       detect_sample=False, detect_control=False):
    """cmd列の中身だけを見て分岐する薄いフェイク(devtools\\av_scan_gate.py の
    どの関数がどんなcmdを組み立てるかにのみ依存する。実プロセス・実Defenderは
    一切呼ばない)。「検出」は、スキャン対象フォルダ内のファイルを削除すること
    でシミュレートする(evaluate_detection_by_existence と対になる)。"""
    def fake_run(cmd, **kwargs):
        joined = " ".join(str(c) for c in cmd)
        if "Get-MpComputerStatus" in joined:
            if not defender_ok:
                return FakeCompletedProcess(returncode=1, stderr="offline")
            return FakeCompletedProcess(
                returncode=0, stdout=json.dumps({"AMServiceEnabled": True}))
        if "Set-Content" in joined:
            return FakeCompletedProcess(returncode=0 if motw_ok else 1)
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
            return FakeCompletedProcess(returncode=0)
        return FakeCompletedProcess(returncode=0)
    return fake_run


def _make_zip_with_exe(zip_path):
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Uchinoko_for_Palworld/Uchinoko.exe", b"MZ-fake-launcher-bytes")
        zf.writestr("Uchinoko_for_Palworld/_internal/Uchinoko.exe", b"MZ-fake-body-bytes")
        zf.writestr("Uchinoko_for_Palworld/README.md", b"not an executable")


# =====================================================================
# eicar_bytes: 陽性対照の中身(生の文字列をソースに常駐させていないことの確認)
# =====================================================================

def test_eicar_bytes_matches_known_standard_string():
    av = _import_av_scan_gate()
    data = av.eicar_bytes()
    assert len(data) == 68
    assert data.startswith(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE")


def test_eicar_string_literal_not_present_in_source():
    """このソースファイル自体にEICARの生文字列が常駐していないことを確認する
    (多くのAV製品はEICAR文字列を含むファイルそれ自体を検出するため)。"""
    av = _import_av_scan_gate()
    src_path = av.__file__
    with open(src_path, "rb") as f:
        content = f.read()
    assert b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" not in content


# =====================================================================
# find_mpcmdrun: 手動指定フォールバック原則(CLAUDE.md)の実装確認
# =====================================================================

def test_find_mpcmdrun_returns_path_when_present(tmp_path):
    av = _import_av_scan_gate()
    defender_dir = tmp_path / "Windows Defender"
    defender_dir.mkdir()
    exe = defender_dir / "MpCmdRun.exe"
    exe.write_bytes(b"fake")
    found = av.find_mpcmdrun(env={"ProgramFiles": str(tmp_path)})
    assert found == str(exe)


def test_find_mpcmdrun_returns_none_when_absent(tmp_path):
    av = _import_av_scan_gate()
    found = av.find_mpcmdrun(env={"ProgramFiles": str(tmp_path)})
    assert found is None


def test_find_mpcmdrun_returns_none_when_env_var_missing():
    av = _import_av_scan_gate()
    assert av.find_mpcmdrun(env={}) is None


# =====================================================================
# evaluate_defender_availability: 判定不能の握り潰し禁止
# =====================================================================

def _dummy_mpcmdrun(tmp_path):
    """os.path.isfileチェックを通すための実在ダミーファイル(中身は無意味)。"""
    p = tmp_path / "MpCmdRun.exe"
    p.write_bytes(b"dummy")
    return str(p)


def test_evaluate_defender_availability_ok(tmp_path):
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_defender_availability(
        _dummy_mpcmdrun(tmp_path), {"AMServiceEnabled": True})
    assert ok is True


def test_evaluate_defender_availability_fails_when_mpcmdrun_missing():
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_defender_availability(None, {"AMServiceEnabled": True})
    assert ok is False
    assert "MpCmdRun" in reason


def test_evaluate_defender_availability_fails_when_mpcmdrun_path_does_not_exist():
    """負の対照(コーディネータ指摘 2026-07-31、実機フォローアップ): 呼び出し側が
    実在しないMpCmdRun.exeパスを明示指定した場合も「検査不能」としてFAILに
    倒す(truthyチェックだけでは、値はあるが実在しないパスをすり抜けさせて
    しまう)。"""
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_defender_availability(
        r"C:\this\path\does\not\exist\MpCmdRun.exe", {"AMServiceEnabled": True})
    assert ok is False
    assert "MpCmdRun" in reason


def test_evaluate_defender_availability_fails_when_status_unavailable(tmp_path):
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_defender_availability(_dummy_mpcmdrun(tmp_path), None)
    assert ok is False
    assert "検査不能" in reason


def test_evaluate_defender_availability_fails_when_service_disabled(tmp_path):
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_defender_availability(
        _dummy_mpcmdrun(tmp_path), {"AMServiceEnabled": False})
    assert ok is False
    assert "AMServiceEnabled" in reason


# =====================================================================
# evaluate_detection_by_existence: 一次証跡(スキャン前後のファイル存在)
# =====================================================================

@pytest.mark.parametrize("before,after,expected", [
    (True, False, True),   # 消えた = 検疫された = 検出
    (True, True, False),   # 残っている = 検出なし
    (False, False, False), # 元から無かった(対象外)
])
def test_evaluate_detection_by_existence(before, after, expected):
    av = _import_av_scan_gate()
    assert av.evaluate_detection_by_existence(before, after) is expected


# =====================================================================
# evaluate_av_scan_result: 純関数の合否判定(受入条件の核心)
# =====================================================================

def test_evaluate_av_scan_result_pass_when_clean_and_control_detected():
    """正の対照: 検出なし、陽性対照は機能 -> PASS"""
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_av_scan_result(control_detected=True, findings=[])
    assert ok is True


def test_evaluate_av_scan_result_fails_when_target_detected():
    """負の対照(受入条件①): 検出があったらFAIL"""
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_av_scan_result(
        control_detected=True,
        findings=[{"file": "Uchinoko_for_Palworld/Uchinoko.exe", "detected": True}])
    assert ok is False
    assert "検出された" in reason


def test_evaluate_av_scan_result_fails_when_control_not_detected_even_if_clean():
    """負の対照(受入条件②): 陽性対照が効かないとき、実ファイルが綺麗でも
    「検査不能」としてFAIL(「スキャナが黙っていた」を「安全」と読み替えない)。"""
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_av_scan_result(control_detected=False, findings=[])
    assert ok is False
    assert "陽性対照" in reason
    assert "検査不能" in reason


def test_evaluate_av_scan_result_fails_when_control_not_detected_and_target_detected():
    """陽性対照無効の判定が、実ファイル検出の判定より優先される
    (どちらの理由であれ最終的にFAILだが、報告文言は陽性対照無効を優先する)。"""
    av = _import_av_scan_gate()
    ok, reason = av.evaluate_av_scan_result(
        control_detected=False,
        findings=[{"file": "a.exe", "detected": True}])
    assert ok is False
    assert "陽性対照" in reason


# =====================================================================
# run_av_scan_gate: ゲート本体の統合試験(run_fn差し替えでDefender非依存)
# =====================================================================

def test_run_av_scan_gate_passes_on_clean_scan_with_working_control(tmp_path):
    """正の対照: 検出なし、陽性対照は機能 -> ゲートPASS"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn(detect_sample=False, detect_control=True)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["ok"] is True
    assert result["name"] == "av_scan"
    assert result["n_targets"] == 2  # Uchinoko.exe x2 (README.mdは対象外)
    assert result["findings"] == []
    assert os.path.isfile(result["json_path"])


def test_run_av_scan_gate_fails_when_shipped_exe_is_detected(tmp_path):
    """負の対照(受入条件①): 配布zip内のexeが検出される -> ゲートFAIL"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn(detect_sample=True, detect_control=True)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["ok"] is False
    assert len(result["findings"]) == 2
    assert "検出された" in result["detail"]


def test_run_av_scan_gate_fails_as_inconclusive_when_control_not_detected(tmp_path):
    """負の対照(受入条件②): 陽性対照が検出されない -> 検査不能としてゲートFAIL
    (実ファイルは綺麗でも緑にしない)。"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn(detect_sample=False, detect_control=False)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["ok"] is False
    assert result["findings"] == []  # 実ファイルは綺麗だったにも関わらず…
    assert "陽性対照" in result["detail"]
    assert "検査不能" in result["detail"]


def test_run_av_scan_gate_fails_when_defender_unavailable(tmp_path):
    """負の対照: Defenderのサービスが無効 -> 検査不能としてゲートFAIL"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn(defender_ok=False)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["ok"] is False
    assert result["n_targets"] == 0  # 環境確認で早期returnし、展開自体していない


def test_run_av_scan_gate_fails_when_mpcmdrun_not_found(tmp_path, monkeypatch):
    """負の対照: MpCmdRun.exe自体が見つからない -> 検査不能としてゲートFAIL。
    このホストの実環境にMpCmdRun.exeが実在しても偽陰性にならないよう、
    find_mpcmdrun自体をNoneを返すようmonkeypatchする(実行環境非依存)。"""
    av = _import_av_scan_gate()
    monkeypatch.setattr(av, "find_mpcmdrun", lambda env=None: None)
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn()
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=None)

    assert result["ok"] is False
    assert "MpCmdRun" in result["detail"]


def test_run_av_scan_gate_scans_all_exe_and_dll_not_just_launcher(tmp_path):
    """受入条件: 「主要なexeだけ」に絞らず、配布zip内の全.exe/.dllを対象にする。
    dllも対象に含めることを確認する。"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Uchinoko_for_Palworld/Uchinoko.exe", b"launcher")
        zf.writestr("Uchinoko_for_Palworld/_internal/Uchinoko.exe", b"body")
        zf.writestr("Uchinoko_for_Palworld/_internal/some_native.dll", b"native dll")
        zf.writestr("Uchinoko_for_Palworld/README.md", b"docs, not a target")
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn(detect_control=True)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["ok"] is True
    assert result["n_targets"] == 3  # 2 exe + 1 dll(READMEは対象外)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
