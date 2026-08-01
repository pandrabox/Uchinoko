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
import time
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


# =====================================================================
# dev#624: msgbox必須・検出確認の照会方式化・後始末
# =====================================================================
#
# 背景(dev#624): 陽性対照(EICAR)の検出通知がぱんの画面に「重大な脅威
# (アクティブ)」として滞留し誤認を招いた。オーナー裁定3点:
#   1. 陽性対照の実行前に非ブロッキングmsgbox表示(本文はオーナー正本、
#      一字一句改変禁止)。承認は待たない。
#   2. 検出確認をGet-MpThreatDetection(検出履歴)照会でも成立するように
#      する(既存の「スキャン前後のファイル存在」判定とOR)。陰性化しない
#      ことを負の対照で保証する。
#   3. 測定完了後、対照ファイルを自前で削除する後始末。


def _make_fake_run_fn_dev624(work_dir, defender_ok=True, motw_ok=True,
                              detect_sample=False,
                              detect_control_by_existence=False,
                              detect_control_by_history=False,
                              lingering_after_cleanup=False):
    """dev#624の3経路(msgbox起動/検出履歴照会/現在の脅威照会)を追加でモック化
    する、既存 _make_fake_run_fn の薄いラッパー。既存のcmd分岐
    (Get-MpComputerStatus/Set-Content/-Scan)はそのまま委譲する。"""
    control_path = os.path.join(work_dir, "av_scan", "control", "eicar_control.com")
    base_fake = _make_fake_run_fn(defender_ok=defender_ok, motw_ok=motw_ok,
                                   detect_sample=detect_sample,
                                   detect_control=detect_control_by_existence)

    def fake_run(cmd, **kwargs):
        joined = " ".join(str(c) for c in cmd)
        if "Get-MpThreatDetection" in joined:
            payload = ([{"Resources": [f"file:_{control_path}"]}]
                       if detect_control_by_history else [])
            return FakeCompletedProcess(returncode=0, stdout=json.dumps(payload))
        if "Get-MpThreat" in joined:
            payload = ([{"Resources": [f"file:_{control_path}"]}]
                       if lingering_after_cleanup else [])
            return FakeCompletedProcess(returncode=0, stdout=json.dumps(payload))
        if "eicar_notice_win.py" in joined:
            return FakeCompletedProcess(returncode=0)
        return base_fake(cmd, **kwargs)
    return fake_run


# --- (1) msgbox必須: 本文の不変性・非ブロッキング起動 ------------------------------

def test_positive_control_notice_message_is_owner_verbatim_text():
    """オーナー正本の一字一句を確認する(brief記載の文言と完全一致)。この定数
    はいかなる補助情報の合成でも変更してはならない。"""
    av = _import_av_scan_gate()
    assert av.POSITIVE_CONTROL_NOTICE_MESSAGE == (
        "わざとウイルス検出させる試験をしました。セキュリティの警告がでるかもしれません")


def test_build_positive_control_notice_text_keeps_owner_message_verbatim():
    """補助情報(実行主体・run ID)を追記しても、オーナー正本の文言そのものは
    一字一句変更されず本文に含まれること。"""
    av = _import_av_scan_gate()
    text = av.build_positive_control_notice_text("release", "20260801T090001Z")
    assert av.POSITIVE_CONTROL_NOTICE_MESSAGE in text
    assert text.startswith(av.POSITIVE_CONTROL_NOTICE_MESSAGE)
    assert "release" in text
    assert "20260801T090001Z" in text


def test_find_notice_python_executable_returns_nonempty_string():
    """自動発見(pythonw.exe)→sys.executable→"python"の三段フォールバック。
    実行環境依存の値になるため、ここでは「何かしら実行可能そうな文字列を
    返す」ことだけを確認する(手動指定フォールバック原則: 行き止まりに
    しない)。"""
    av = _import_av_scan_gate()
    exe = av.find_notice_python_executable()
    assert isinstance(exe, str) and exe


def test_show_positive_control_notice_writes_payload_and_launches_python_script(tmp_path):
    """非ブロッキング起動(detached Popen相当、ここではrun_fn差し替えで検証)を
    試み、応答を待たずに戻ること。PowerShellスクリプトは一切生成せず、
    `devtools\\eicar_notice_win.py` をPython実行系経由で起動する形になっている
    ことを確認する(2026-08-01 Masterライターレビュー指摘: ps1言語方針違反の
    是正)。JSONペイロードにオーナー正本の文言が一字一句含まれることも確認する。"""
    av = _import_av_scan_gate()
    work_dir = str(tmp_path / "notice_work")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeCompletedProcess(returncode=0)

    ok, detail = av.show_positive_control_notice(
        "release", "RUN123", work_dir, run_fn=fake_run)

    assert ok is True
    assert len(calls) == 1
    cmd = calls[0]
    joined = " ".join(str(c) for c in cmd)
    # PS1を一切生成・実行しないことの確認
    assert ".ps1" not in joined
    assert "powershell" not in joined.lower()
    assert "Start-Process" not in joined
    assert "eicar_notice_win.py" in joined

    payload_path = os.path.join(work_dir, "eicar_notice_payload.json")
    assert os.path.isfile(payload_path)
    assert payload_path in cmd
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    assert av.POSITIVE_CONTROL_NOTICE_MESSAGE in payload["message"]
    assert "release" in payload["message"]
    assert "RUN123" in payload["message"]
    assert payload["timeout_ms"] == av.POSITIVE_CONTROL_NOTICE_TIMEOUT_MS


def test_launch_notice_process_does_not_block_and_reports_success(tmp_path):
    """既定launcher(`_launch_notice_process`、run_fn未指定時に使われる実体)が
    detached子プロセスとして起動し、即座に(msgboxの表示・クローズを待たずに)
    戻ることを確認する。**実際にeicar_notice_win.pyは起動しない**——ホスト画面に
    何も表示しない、無害なコマンド(`python -c "pass"`)で代用する
    (2026-08-01オーナー緊急裁定「ホスト画面への一切の干渉禁止」を守るため)。"""
    av = _import_av_scan_gate()
    harmless_cmd = [sys.executable, "-c", "pass"]
    started = time.monotonic()
    result = av._launch_notice_process(harmless_cmd)
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    # detached起動なので、子プロセスの終了を待たず即座に戻ってくるはず
    assert elapsed < 5.0


def test_show_positive_control_notice_does_not_raise_when_run_fn_fails(tmp_path):
    """表示失敗(GUI不能環境等)でも例外を外へ漏らさず、okをFalseで返すのみ
    (呼び出し側=run_av_scan_gateが本処理を継続できるようにするため)。"""
    av = _import_av_scan_gate()
    work_dir = str(tmp_path / "notice_work_fail")

    def failing_run(cmd, **kwargs):
        raise OSError("no display")

    ok, detail = av.show_positive_control_notice(
        "release", "RUN123", work_dir, run_fn=failing_run)
    assert ok is False
    assert "継続" in detail or "不能" in detail


def test_show_positive_control_notice_reports_failure_on_nonzero_returncode(tmp_path):
    av = _import_av_scan_gate()
    work_dir = str(tmp_path / "notice_work_rc")

    def fake_run(cmd, **kwargs):
        return FakeCompletedProcess(returncode=1, stderr="boom")

    ok, detail = av.show_positive_control_notice(
        "release", "RUN123", work_dir, run_fn=fake_run)
    assert ok is False


# --- (2) 検出確認の照会方式化: evaluate_detection_by_history -----------------------

def test_evaluate_detection_by_history_true_when_resource_matches():
    av = _import_av_scan_gate()
    target = r"C:\work\av_scan\control\eicar_control.com"
    detections = [{"Resources": [f"file:_{target}"]}]
    assert av.evaluate_detection_by_history(detections, target) is True


def test_evaluate_detection_by_history_false_when_no_match():
    """負の対照: 検出履歴に対照パスへの言及が無い場合はFalse
    (陰性化しないことの裏返し: 無関係な履歴で誤ってTrueにしない)。"""
    av = _import_av_scan_gate()
    target = r"C:\work\av_scan\control\eicar_control.com"
    detections = [{"Resources": [r"file:_C:\other\unrelated.exe"]}]
    assert av.evaluate_detection_by_history(detections, target) is False


@pytest.mark.parametrize("detections", [None, [], [{"Resources": None}], [{"NoResources": True}]])
def test_evaluate_detection_by_history_false_when_detections_empty_or_missing(detections):
    """負の対照: 検出履歴の取得自体が失敗/空でもFalseに倒す(fail-closedは
    既存のevaluate_detection_by_existence側が担うため、ここは安全側=Falseでよい)。"""
    av = _import_av_scan_gate()
    target = r"C:\work\av_scan\control\eicar_control.com"
    assert av.evaluate_detection_by_history(detections, target) is False


def test_evaluate_detection_by_history_false_when_target_path_missing():
    av = _import_av_scan_gate()
    detections = [{"Resources": ["file:_C:\\work\\control\\eicar_control.com"]}]
    assert av.evaluate_detection_by_history(detections, None) is False


# --- (3) 後始末: cleanup_positive_control / evaluate_lingering_threat -------------

def test_cleanup_positive_control_removes_existing_file(tmp_path):
    av = _import_av_scan_gate()
    control_path = tmp_path / "eicar_control.com"
    control_path.write_bytes(b"dummy")
    ok, detail = av.cleanup_positive_control(str(control_path))
    assert ok is True
    assert not control_path.exists()
    assert "削除した" in detail


def test_cleanup_positive_control_is_noop_when_already_gone(tmp_path):
    """既にDefenderの検疫等で消えている場合は何もしない(no-op)。"""
    av = _import_av_scan_gate()
    control_path = tmp_path / "already_gone.com"
    ok, detail = av.cleanup_positive_control(str(control_path))
    assert ok is True
    assert "no-op" in detail or "既に存在しない" in detail


def test_evaluate_lingering_threat_true_when_resource_matches():
    av = _import_av_scan_gate()
    target = r"C:\work\av_scan\control\eicar_control.com"
    threats = [{"Resources": [f"file:_{target}"]}]
    assert av.evaluate_lingering_threat(threats, target) is True


def test_evaluate_lingering_threat_false_when_no_threats():
    av = _import_av_scan_gate()
    target = r"C:\work\av_scan\control\eicar_control.com"
    assert av.evaluate_lingering_threat([], target) is False
    assert av.evaluate_lingering_threat(None, target) is False


# --- 統合試験: run_av_scan_gate 全体での結線確認 -----------------------------------

def test_run_av_scan_gate_passes_via_history_query_when_existence_check_misses_race(tmp_path):
    """20260801T090001Z INCONCLUSIVEの機序の再現+修正確認: リアルタイム保護が
    先取りして『スキャン前後のファイル存在』判定が検出を捉えられなくても
    (detect_control_by_existence=False)、Get-MpThreatDetection照会側が検出を
    確認できれば(detect_control_by_history=True)、ORで合成されゲートはPASSする
    (実ファイルに検出が無い前提)。"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn_dev624(
        work_dir, detect_sample=False,
        detect_control_by_existence=False, detect_control_by_history=True)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["ok"] is True
    assert result["control_detected"] is True
    assert result["control_detected_by_existence"] is False
    assert result["control_detected_by_history"] is True


def test_run_av_scan_gate_still_inconclusive_when_neither_existence_nor_history_detect(tmp_path):
    """負の対照(dev#624受入条件「陰性化しないこと」): 存在判定・履歴照会の
    どちらも対照を検出しなければ、ORで合成しても依然として検査不能=FAILの
    ままであること(OR結合が誤って合否を緩めていないことの確認)。"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn_dev624(
        work_dir, detect_sample=False,
        detect_control_by_existence=False, detect_control_by_history=False)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["ok"] is False
    assert result["control_detected"] is False
    assert "陽性対照" in result["detail"]
    assert "検査不能" in result["detail"]


def test_run_av_scan_gate_cleans_up_control_file_after_history_only_detection(tmp_path):
    """後始末: 検出履歴照会のみで検出成立したケース(=ファイル自体はスキャン後も
    残っている)でも、測定完了後は自前で削除されること。"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn_dev624(
        work_dir, detect_sample=False,
        detect_control_by_existence=False, detect_control_by_history=True)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    control_path = os.path.join(work_dir, "av_scan", "control", "eicar_control.com")
    assert not os.path.isfile(control_path), "後始末で削除されているはず"
    assert result["cleanup"]["ok"] is True
    assert result["lingering_threat_after_cleanup"] is False


def test_run_av_scan_gate_records_lingering_threat_when_still_present(tmp_path):
    """診断: 後始末後もGet-MpThreatに対照パスへの言及が残っていれば
    lingering_threat_after_cleanup=Trueとして記録する(ゲートの合否には
    影響させない=診断専用)。"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn_dev624(
        work_dir, detect_sample=False,
        detect_control_by_existence=False, detect_control_by_history=True,
        lingering_after_cleanup=True)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["lingering_threat_after_cleanup"] is True
    # 診断専用: 滞留が観測されてもゲート自体の合否(ok)には影響しない
    assert result["ok"] is True


def test_run_av_scan_gate_wires_notice_result_into_output(tmp_path):
    """msgbox通知の結果がrun_av_scan_gate()の戻り値に記録されること。"""
    av = _import_av_scan_gate()
    zip_path = str(tmp_path / "dist.zip")
    _make_zip_with_exe(zip_path)
    work_dir = str(tmp_path / "work")
    report = DummyReport()

    fake_run = _make_fake_run_fn_dev624(
        work_dir, detect_control_by_existence=True)
    result = av.run_av_scan_gate(zip_path, work_dir, report, run_fn=fake_run,
                                  mpcmdrun_path=_dummy_mpcmdrun(tmp_path))

    assert result["notice"]["ok"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
