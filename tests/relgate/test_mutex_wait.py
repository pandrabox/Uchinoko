# -*- coding: utf-8 -*-
"""dev#220(2026-07-30): relgateレーンの新律速だったMutex待機の粒度改善の単体試験。

背景(work\\night_20260729\\run4_analysis.md): relgateの最遅検体が
Global\\DiveToPalworld_pipeline ミューテックス競合のたびに固定45秒間隔で
convert.ps1プロセスを丸ごと再起動して待っており(devtools\\relgate.py
DEFAULT_RETRY_WAIT_SEC=45)、45秒という粒度が実際の保持時間(数秒〜数十秒)
より大幅に粗かった。

対策(方式a): convert.ps1に -MutexWaitMs パラメータを追加し、既定0
(従来どおりWaitOne(0)、非ブロッキング・即時失敗)を保ったまま、正の値を
渡した呼び出し元(devtools\\relgate.py)だけがOSレベルのブロッキング待機
(Mutex.WaitOne(timeoutMs)、解放された瞬間に取得)へ切り替わるようにした。

このテストは2部構成:
  1. devtools\\relgate.py 側の配線(run_convert()が-MutexWaitMsを正しく
     コマンドラインへ渡しているか)を subprocess.run をモックして検証する
     (test_shared_cache_env.py と同じ手法。convert.ps1やBlenderは起動しない)。
  2. pipeline\\cli\\convert.ps1 が実際に追加したのと同一の
     `New-Object System.Threading.Mutex(...).WaitOne($MutexWaitMs)` という
     .NETプリミティブの挙動そのものを、テスト専用の名前付きMutex
     (本番の"Global\\DiveToPalworld_pipeline"とは別名、ホストの実行状態に
     影響しない)を使って**実ロック**で検証する(モックでは検証できない、
     「解放された瞬間に取得できる」という主張の直接証拠)。
     - 負の対照: 保持中に $MutexWaitMs=0 で試みると取得できない(旧既定と同じ)
     - 正の対照: 保持中に $MutexWaitMs=十分な値 で試みると、解放を跨いで
       ブロックし、45秒の固定間隔を待たず(解放後 数秒以内に)取得できる
  3. 静的ガード: convert.ps1のソースが実際に $MutexWaitMs 変数を
     WaitOneへ渡すよう配線されている(将来のリファクタで元のWaitOne(0)
     ハードコードへ静かに戻っていないか)ことをテキストレベルで確認する。

変換出力には一切触れない(Layers-Affected: none)。pwshの実プロセスを
2〜3本使うが、いずれもテスト専用の名前付きMutexのみを操作し、
job.json/Blender/pak等の変換パイプラインには触れない。
"""
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
CONVERT_PS1 = os.path.join(REPO_ROOT, "pipeline", "cli", "convert.ps1")
if DEVTOOLS_DIR not in sys.path:
    sys.path.insert(0, DEVTOOLS_DIR)

import relgate  # noqa: E402


class _FakeReport:
    def __init__(self):
        self.lines = []

    def log(self, text, *_args, **_kwargs):
        self.lines.append(text)


class _FakeProc:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# =====================================================================
# 1) devtools\relgate.py 側の配線(モック、convert.ps1は起動しない)
# =====================================================================

def _run_convert_capture_cmd(**run_convert_kwargs):
    """run_convert()を1回成功で終わらせつつ、subprocess.runへ渡されたcmdを
    捕まえる共通ヘルパ。"""
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProc(returncode=0)

    tmp_job_dir = os.path.join(REPO_ROOT, "work", f"_test_mutex_wait_{uuid.uuid4().hex[:8]}")
    tmp_job_path = os.path.join(tmp_job_dir, "job.json")
    os.makedirs(tmp_job_dir, exist_ok=True)
    orig_run = relgate.subprocess.run
    relgate.subprocess.run = _fake_run
    try:
        rc, _elapsed = relgate.run_convert(tmp_job_path, _FakeReport(), "test", **run_convert_kwargs)
    finally:
        relgate.subprocess.run = orig_run
        shutil.rmtree(tmp_job_dir, ignore_errors=True)
    assert rc == 0
    return captured["cmd"]


def test_run_convert_passes_default_mutex_wait_ms():
    """既定呼び出し(mutex_wait_ms省略)は DEFAULT_MUTEX_WAIT_MS をconvert.ps1へ渡す。"""
    cmd = _run_convert_capture_cmd()
    assert "-MutexWaitMs" in cmd
    idx = cmd.index("-MutexWaitMs")
    assert cmd[idx + 1] == str(relgate.DEFAULT_MUTEX_WAIT_MS)


def test_run_convert_passes_custom_mutex_wait_ms():
    """呼び出し側が明示指定すればその値がそのままconvert.ps1へ渡る。"""
    cmd = _run_convert_capture_cmd(mutex_wait_ms=12345)
    idx = cmd.index("-MutexWaitMs")
    assert cmd[idx + 1] == "12345"


def test_default_mutex_wait_ms_has_sane_bounds():
    """run4実測(観測された単一検体Phase0-1所要の最大69.6秒)を大きく下回らず、
    かつ「保険」のPython外側リトライがまだ意味を持つ範囲に収まっていること
    (値合わせでなく、設計根拠のレンジチェック)。"""
    assert relgate.DEFAULT_MUTEX_WAIT_MS >= 70_000, (
        "観測された最大Phase0-1所要(69.6秒)より短いと、通常運用でも"
        "ブロッキング待機がタイムアウトしてしまう")
    assert relgate.DEFAULT_MUTEX_WAIT_MS <= 600_000, (
        "1回のブロッキング待機が長すぎると、Phase0-1自体が本当にハングした"
        "ケースの検知(fail-closed)が遅れすぎる")


def test_retry_backoff_still_works_when_mutex_wait_exhausted(monkeypatch):
    """負の対照: convert.ps1が-MutexWaitMs分ブロックしてもなお取れなかった
    (異常系)場合、外側のPythonリトライ(保険)が従来どおりMUTEX_BUSY_MARKER
    検知→wait_sec秒バックオフ→再試行のロジックを維持していること。"""
    calls = {"n": 0}
    sleeps = []

    def _fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeProc(returncode=1, stdout="", stderr=f"boom {relgate.MUTEX_BUSY_MARKER}")
        return _FakeProc(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(relgate.subprocess, "run", _fake_run)
    monkeypatch.setattr(relgate.time, "sleep", lambda s: sleeps.append(s))

    tmp_job_dir = os.path.join(REPO_ROOT, "work", f"_test_mutex_wait_{uuid.uuid4().hex[:8]}")
    tmp_job_path = os.path.join(tmp_job_dir, "job.json")
    os.makedirs(tmp_job_dir, exist_ok=True)
    try:
        rc, _elapsed = relgate.run_convert(tmp_job_path, _FakeReport(), "test",
                                           max_retries=5, wait_sec=7)
    finally:
        shutil.rmtree(tmp_job_dir, ignore_errors=True)

    assert rc == 0
    assert calls["n"] == 3
    assert sleeps == [7, 7], "保険のバックオフはwait_sec秒のまま機能しているべき"


# =====================================================================
# 2) pipeline\cli\convert.ps1 が使うのと同一の .NET プリミティブを、
#    テスト専用の名前付きMutexで実ロック検証する。
# =====================================================================

PWSH = shutil.which("pwsh") or "pwsh"


def _pwsh_available():
    try:
        r = subprocess.run([PWSH, "-NoProfile", "-Command", "1"],
                            capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _pwsh_available(), reason="pwshが利用できない環境")
class TestMutexWaitOneRealLock:
    """convert.ps1が追加したのと同一の
    `New-Object System.Threading.Mutex($false, <name>); $m.WaitOne($ms)`
    パターンを、テスト専用の名前(本番のGlobal\\DiveToPalworld_pipelineとは
    別)で実際に2プロセス間の排他として動かす。"""

    def setup_method(self):
        self.mutex_name = f"Global\\D2P_relgate_test_mutex_{uuid.uuid4().hex}"

    def _holder_script(self, hold_sec):
        # 保持側: Mutexを取得し、hold_sec秒後に解放して終了する
        return (
            f"$m = New-Object System.Threading.Mutex($false, '{self.mutex_name}'); "
            f"[void]$m.WaitOne(); "
            f"Write-Output 'HELD'; "
            f"Start-Sleep -Seconds {hold_sec}; "
            f"$m.ReleaseMutex(); "
            f"Write-Output 'RELEASED'"
        )

    def _waiter_script(self, wait_ms):
        # convert.ps1と全く同じ形の取得コード(既定の$MutexWaitMs=0相当を
        # 明示的に渡す形でここでも再現)
        return (
            f"$m = New-Object System.Threading.Mutex($false, '{self.mutex_name}'); "
            "try { $acquired = $m.WaitOne(" + str(wait_ms) + ") } "
            "catch [System.Threading.AbandonedMutexException] { $acquired = $true } "
            "Write-Output $acquired"
        )

    def test_wait_zero_fails_immediately_while_held(self):
        """負の対照(旧既定=$MutexWaitMs=0相当): 保持中はWaitOne(0)が
        即座にFalseを返す(convert.ps1の従来挙動、GUI等が引き続き受け取る挙動)。"""
        holder = subprocess.Popen([PWSH, "-NoProfile", "-Command", self._holder_script(4)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            # 保持が成立するまで少し待つ
            time.sleep(1.0)
            t0 = time.time()
            r = subprocess.run([PWSH, "-NoProfile", "-Command", self._waiter_script(0)],
                               capture_output=True, text=True, timeout=15)
            elapsed = time.time() - t0
            assert r.stdout.strip() == "False", (
                f"保持中はWaitOne(0)がFalseを返すべき: stdout={r.stdout!r} stderr={r.stderr!r}")
            assert elapsed < 3.0, "WaitOne(0)は非ブロッキングのはずが数秒かかっている"
        finally:
            holder.wait(timeout=15)

    def test_blocking_wait_acquires_right_after_release(self):
        """正の対照(方式a本体): 保持中でも十分な$MutexWaitMsを渡せば、
        解放を跨いでブロックし、解放直後(45秒固定ポーリングよりずっと早く)に
        取得できる。"""
        hold_sec = 4
        holder = subprocess.Popen([PWSH, "-NoProfile", "-Command", self._holder_script(hold_sec)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(1.0)  # 保持成立を待つ
            t0 = time.time()
            r = subprocess.run([PWSH, "-NoProfile", "-Command", self._waiter_script(30000)],
                               capture_output=True, text=True, timeout=30)
            elapsed = time.time() - t0
            assert r.stdout.strip() == "True", (
                f"解放後はブロッキング待機側が取得できるべき: stdout={r.stdout!r} stderr={r.stderr!r}")
            # 保持開始から約1秒後に待ち始めたので、解放(hold_sec秒後)までの
            # 残りは約 hold_sec-1 秒。45秒固定ポーリングなら最大44秒余分に
            # 待たされ得るところ、実測はその残り時間程度で取得できるはず。
            assert elapsed < (hold_sec - 1) + 5, (
                f"解放された瞬間に取得できていない(粗いポーリング相当の遅延が"
                f"残っている疑い): elapsed={elapsed:.1f}s")
        finally:
            holder.wait(timeout=15)


# =====================================================================
# 3) 静的ガード: convert.ps1のソースが $MutexWaitMs を実際に配線しているか
# =====================================================================

def test_convert_ps1_declares_mutex_wait_ms_param_with_zero_default():
    with open(CONVERT_PS1, encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"\[int\]\$MutexWaitMs\s*=\s*0", src), (
        "convert.ps1に -MutexWaitMs パラメータ(既定0=完全後方互換)が"
        "見当たらない")


def test_convert_ps1_waits_using_the_parameter_not_hardcoded_zero():
    with open(CONVERT_PS1, encoding="utf-8") as f:
        src = f.read()
    assert "WaitOne($MutexWaitMs)" in src, (
        "convert.ps1のMutex取得がWaitOne($MutexWaitMs)に配線されていない"
        "(ハードコードのWaitOne(0)へ退行していないか確認)")
    # コメント中の説明的な "WaitOne(0)" (既定値の説明)は許容し、実際の代入文
    # ($acquired = ... .WaitOne(...)) だけを見る。ここがハードコード0に
    # 戻っていたら退行(#で始まらない行のみを対象にする)。
    assignment_lines = [
        line for line in src.splitlines()
        if "$acquired" in line and ".WaitOne(" in line and not line.strip().startswith("#")
    ]
    assert assignment_lines, "$acquired への WaitOne(...) 代入行が見つからない"
    assert all("$MutexWaitMs" in line for line in assignment_lines), (
        f"$acquired への代入がパラメータ経由になっていない行がある: {assignment_lines}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
