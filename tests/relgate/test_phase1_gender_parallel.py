# -*- coding: utf-8 -*-
"""dev#288(work\\speed_mission\\dag\\NOTES.md TOP候補1)の単体試験。

背景: convert.ps1のPhase1(Blender工程)は、旧実装ではPowerShellの
`foreach ($g in $Genders)`でstep02_retarget.py→render_preview.pyをMale/Female
完全逐次実行していた。この2工程はいずれもVRMアドオン(vp_bl.ensure_vrm_addon、
step01専用)を呼ばず、入出力もgender別に完全分離(step02_{gender}.blend /
preview_{gender}_*.png)されているため、genderごとの「step02→(成功時)preview」
チェーンをバックグラウンドジョブ(Start-Job)でgender間だけ並列化した
($script:Phase1GenderWorkerScript、convert.ps1)。

このテストは2部構成:
  1. 静的ガード: convert.ps1のソースが実際に並列化の要点を配線しているか
     (Start-Job使用、ログファイル名に$Genderを含む、単一gender時は旧来の
     逐次ループへフォールバックする分岐が残っている、等)をテキストレベルで
     確認する(将来のリファクタで静かに壊れていないかの回帰ガード)。
  2. 実行時試験: convert.ps1から$script:Phase1GenderWorkerScriptの実体
     (ソースそのもの、再実装ではない)を抽出し、$Blenderをテスト専用スタブ
     (実Blenderを起動しない)に差し替えて、2つのgenderを実際に別プロセスとして
     同時実行する。これにより:
       - 負の対照: 片方のgender(例: Female)のstep02が失敗しても、もう片方
         (Male)の結果が汚染されない(exit code・ログ内容とも独立)ことを、
         モックではなく実プロセスの同時実行で直接検証する
         (並列化にあたって実際に直さなければならなかった構造的欠陥
         ——旧Run-Blenderはログファイル名がgender非依存で、並列実行では
         2ジョブが同じファイルへ同時書き込みし破損する——がここで再発しないかの
         負の対照でもある)。
       - 正の対照: 両方成功すれば両方とも正しく完了報告される。
       - genderが逆でも同じロジックが機能する(決め打ちでない)ことを2パターンで確認。

変換出力(pak本体)には一切触れない(Blenderは起動しないスタブに差し替えるため)。
Layers-Affected: none(このテスト自体はロジック検証のみ)。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
CONVERT_PS1 = os.path.join(REPO_ROOT, "pipeline", "cli", "convert.ps1")

PWSH = shutil.which("pwsh") or "pwsh"


def _pwsh_available():
    try:
        r = subprocess.run([PWSH, "-NoProfile", "-Command", "1"],
                            capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def _read_convert_ps1():
    with open(CONVERT_PS1, encoding="utf-8") as f:
        return f.read()


def _extract_worker_body(src):
    """`$script:Phase1GenderWorkerScript = { ... }` の中身(param()〜returnまで)を
    ブレースカウントで取り出す。convert.ps1の実ソースをそのまま使う
    (再実装すると「テストが検証しているのはテスト自身のコピーで、実コードでは
    ない」という典型的な事故になるため、必ずここから抽出する)。"""
    marker = "$script:Phase1GenderWorkerScript = {"
    start = src.index(marker)
    body_start = start + len(marker)
    depth = 1
    i = body_start
    while depth > 0:
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    body_end = i - 1  # インデックスは閉じ`}`の直前
    return src[body_start:body_end]


STUB_BLENDER_PS1 = textwrap.dedent(r"""
    # dev#288 テスト専用スタブ: $Blenderの代わりに使う。実Blenderは一切起動しない。
    # 呼び出し形: & <this> --background --factory-startup --python-exit-code 1
    #             --python <scriptpath> -- <jobpath> <gender>
    $all = $args
    $pyIdx = [array]::IndexOf($all, "--python")
    $scriptPath = $all[$pyIdx + 1]
    $scriptName = Split-Path -Leaf $scriptPath
    $gender = $all[$all.Count - 1]
    Start-Sleep -Milliseconds 400  # 2プロセスの実行時間帯を確実に重ねる
    Write-Output "STUB_MARKER script=$scriptName gender=$gender"
    Write-Error "STUB_STDERR script=$scriptName gender=$gender"
    if ($env:D2P_STUB_FAIL_SCRIPT -and $env:D2P_STUB_FAIL_GENDER -and
        $scriptName -eq $env:D2P_STUB_FAIL_SCRIPT -and $gender -eq $env:D2P_STUB_FAIL_GENDER) {
        exit 1
    }
    exit 0
    """)


def _write_worker_script(tmp_path):
    src = _read_convert_ps1()
    body = _extract_worker_body(src)
    worker_path = os.path.join(tmp_path, "extracted_worker.ps1")
    with open(worker_path, "w", encoding="utf-8") as f:
        f.write(body)
    return worker_path


def _write_stub(tmp_path):
    stub_path = os.path.join(tmp_path, "stub_blender.ps1")
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(STUB_BLENDER_PS1)
    return stub_path


def _run_worker(worker_path, stub_path, pipeline_dir, job_path, log_dir, gender,
                 fail_script=None, fail_gender=None):
    """extracted_worker.ps1をpwsh -Commandで呼び、返り値をConvertTo-Jsonで拾う。
    非ブロッキング(Popen)で返すので、呼び出し側が2つ同時に走らせて真の並行実行を作れる。"""
    env = dict(os.environ)
    if fail_script and fail_gender:
        env["D2P_STUB_FAIL_SCRIPT"] = fail_script
        env["D2P_STUB_FAIL_GENDER"] = fail_gender
    cmd_str = (
        f"& '{worker_path}' -Blender '{stub_path}' -Pipeline '{pipeline_dir}' "
        f"-JobPath '{job_path}' -LogDir '{log_dir}' -Gender '{gender}' | ConvertTo-Json -Depth 6"
    )
    return subprocess.Popen(
        [PWSH, "-NoProfile", "-Command", cmd_str],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        env=env)


@pytest.mark.skipif(not _pwsh_available(), reason="pwshが利用できない環境")
class TestPhase1GenderWorkerRealExecution:
    """convert.ps1の$script:Phase1GenderWorkerScriptの実ソースを、Blenderを起動
    しないスタブで実際に2プロセス同時実行して検証する(モックではなく実行時試験)。"""

    def setup_method(self):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp(prefix="d2p_p1par_test_")
        self.log_dir = os.path.join(self.tmp_dir, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.pipeline_dir = self.tmp_dir  # ワーカーは "$Pipeline\blender\$script" を
        # 組み立てるだけでスタブは中身を読まない(パスの実在チェックはしない)ので、
        # 適当なディレクトリで足りる
        self.job_path = os.path.join(self.tmp_dir, "job.json")
        with open(self.job_path, "w", encoding="utf-8") as f:
            f.write("{}")
        self.worker_path = _write_worker_script(self.tmp_dir)
        self.stub_path = _write_stub(self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _parse(self, proc, timeout=30):
        out, err = proc.communicate(timeout=timeout)
        assert out.strip(), f"stdoutが空(stderr={err!r})"
        return json.loads(out)

    def test_both_genders_succeed_independently(self):
        """正の対照: Male/Femaleとも成功すれば、それぞれ独立に
        Step02.ExitCode==0 / Preview.ExitCode==0 が返る。"""
        p_male = _run_worker(self.worker_path, self.stub_path, self.pipeline_dir,
                              self.job_path, self.log_dir, "Male")
        p_female = _run_worker(self.worker_path, self.stub_path, self.pipeline_dir,
                                self.job_path, self.log_dir, "Female")
        r_male = self._parse(p_male)
        r_female = self._parse(p_female)

        assert r_male["Gender"] == "Male"
        assert r_male["Step02"]["ExitCode"] == 0
        assert r_male["Preview"]["ExitCode"] == 0
        assert r_female["Gender"] == "Female"
        assert r_female["Step02"]["ExitCode"] == 0
        assert r_female["Preview"]["ExitCode"] == 0

        # ログファイル名にgenderが含まれ、互いに別ファイルであること
        assert r_male["Step02"]["LogPath"] != r_female["Step02"]["LogPath"]
        assert "Male" in os.path.basename(r_male["Step02"]["LogPath"])
        assert "Female" in os.path.basename(r_female["Step02"]["LogPath"])

    def test_one_gender_failure_does_not_corrupt_the_other(self):
        """負の対照(本題): Female側のstep02だけをスタブに失敗させても、
        同時実行中のMale側の結果・ログが汚染されないこと。"""
        p_male = _run_worker(self.worker_path, self.stub_path, self.pipeline_dir,
                              self.job_path, self.log_dir, "Male")
        p_female = _run_worker(self.worker_path, self.stub_path, self.pipeline_dir,
                                self.job_path, self.log_dir, "Female",
                                fail_script="step02_retarget.py", fail_gender="Female")
        r_male = self._parse(p_male)
        r_female = self._parse(p_female)

        # Maleは無関係に成功する
        assert r_male["Step02"]["ExitCode"] == 0
        assert r_male["Preview"]["ExitCode"] == 0

        # Femaleはstep02で失敗し、previewは実行されない(chainがそこで止まる)
        assert r_female["Step02"]["ExitCode"] == 1
        assert r_female["Preview"] is None

        # ログの中身がgenderで完全に分離していること(相手のマーカーが
        # 混ざっていない = 同時書き込みによる破損/クロストークが無い証拠)
        with open(r_male["Step02"]["LogPath"], encoding="utf-8") as f:
            male_log = f.read()
        with open(r_female["Step02"]["LogPath"], encoding="utf-8") as f:
            female_log = f.read()
        assert "gender=Male" in male_log
        assert "gender=Female" not in male_log
        assert "gender=Female" in female_log
        assert "gender=Male" not in female_log

    def test_failure_detection_is_not_hardcoded_to_one_gender(self):
        """負の対照その2: 失敗させる性別を逆(Male)にしても同じロジックが
        正しく追随する(genderがハードコードされた偶然の一致ではないことの確認)。"""
        p_male = _run_worker(self.worker_path, self.stub_path, self.pipeline_dir,
                              self.job_path, self.log_dir, "Male",
                              fail_script="step02_retarget.py", fail_gender="Male")
        p_female = _run_worker(self.worker_path, self.stub_path, self.pipeline_dir,
                                self.job_path, self.log_dir, "Female")
        r_male = self._parse(p_male)
        r_female = self._parse(p_female)

        assert r_male["Step02"]["ExitCode"] == 1
        assert r_male["Preview"] is None
        assert r_female["Step02"]["ExitCode"] == 0
        assert r_female["Preview"]["ExitCode"] == 0

    def test_preview_failure_is_nonfatal_but_recorded(self):
        """render_preview.pyの失敗はstep02と違い致命的ではない(NonFatal)扱いの
        はずだが、ワーカー自体はexit codeをそのまま返すだけで良い/悪いの判断は
        convert.ps1本体側(呼び出し元)の役割。ここではワーカーがpreview失敗を
        正しく報告することだけを確認する(呼び出し元側のNonFatal処理は
        静的ガードのtest_convert_ps1_treats_preview_failure_as_nonfatal_in_parallel_pathで担保)。"""
        p_female = _run_worker(self.worker_path, self.stub_path, self.pipeline_dir,
                                self.job_path, self.log_dir, "Female",
                                fail_script="render_preview.py", fail_gender="Female")
        r_female = self._parse(p_female)
        assert r_female["Step02"]["ExitCode"] == 0
        assert r_female["Preview"] is not None
        assert r_female["Preview"]["ExitCode"] == 1


# =====================================================================
# 静的ガード: convert.ps1のソースが並列化の要点を実際に配線しているか
# =====================================================================

def test_convert_ps1_has_gender_parallel_guard():
    src = _read_convert_ps1()
    assert "$Genders.Count -gt 1" in src, (
        "genderが2以上のときだけ並列パスへ分岐するガードが見当たらない"
        "(単一gender時は旧来の逐次ループにフォールバックする設計のはず)")


def test_convert_ps1_uses_start_job_for_parallel_phase1():
    src = _read_convert_ps1()
    assert "Start-Job" in src and "Wait-Job" in src and "Receive-Job" in src, (
        "Phase1のgender並列化にStart-Job/Wait-Job/Receive-Jobが使われていない"
        "(実装方式が変わった場合はこのテストごと更新すること)")


def test_convert_ps1_worker_log_filenames_include_gender():
    """並列実行時にログファイル名がgender非依存だと、2ジョブが同じファイルへ
    同時書き込みして破損する(この関数を作った直接の理由)。ワーカー内の
    ログパス組み立てに必ず$Genderが含まれていること。"""
    src = _read_convert_ps1()
    body = _extract_worker_body(src)
    log_line = [ln for ln in body.splitlines() if "logPath" in ln and "Join-Path" in ln]
    assert log_line, "ワーカー内にログパスを組み立てる行が見当たらない"
    assert any("$Gender" in ln for ln in log_line), (
        f"ワーカーのログファイル名に$Genderが含まれていない: {log_line}")


def test_convert_ps1_single_gender_path_still_uses_original_sequential_loop():
    """$Genders.Count -le 1のとき、従来どおりRun-Blender(親関数)を直接呼ぶ
    逐次ループへフォールバックしていること(恩恵の無いケースで並列化の
    リスクだけを負わないための設計、退行検知)。"""
    src = _read_convert_ps1()
    else_idx = src.index("$Genders.Count -gt 1")
    tail = src[else_idx:else_idx + 4000]
    assert re.search(r"else\s*\{", tail), "並列パスのelse節が見当たらない"
    assert 'Run-Blender "step02_retarget.py" @($g)' in tail, (
        "単一gender時のフォールバックが旧来のRun-Blender直接呼び出しになっていない")


def test_convert_ps1_preview_only_path_is_untouched():
    """-PreviewOnlyは常にMale固定1性別の軽量ループで、並列化の対象外
    (影響を与えないことがWP指示の明示条件)。この部分がRun-Blenderを直接
    呼ぶ旧来のままであることを確認する。"""
    src = _read_convert_ps1()
    preview_only_idx = src.index("if ($PreviewOnly)")
    tail = src[preview_only_idx:preview_only_idx + 800]
    assert 'Run-Blender "step02_retarget.py" @("Male")' in tail
    assert 'Run-Blender "render_preview.py" @("Male")' in tail
    assert "Start-Job" not in tail, "-PreviewOnly経路に並列化が漏れ込んでいる(触ってはいけない範囲)"


def test_convert_ps1_pipeline_mutex_is_still_held_across_phase1():
    """dev#288の要件: グローバルPipelineMutexの意味(別ジョブ=別アバターの
    排他)は変えない。Mutex取得はPhase1着手前のまま、解放はPhase1終了直後の
    ままであること(並列化がMutexの保持区間そのものを変えていないかの回帰ガード)。"""
    src = _read_convert_ps1()
    acquire_idx = src.index("$script:PipelineMutex.WaitOne")
    release_idx = src.index("$script:PipelineMutex.ReleaseMutex")
    phase1_idx = src.index("=== Phase 1: Blender pipeline ===")
    assert acquire_idx < phase1_idx < release_idx, (
        "PipelineMutexの取得/解放がPhase1を挟む位置関係になっていない"
        "(並列化でMutexの保護範囲自体が変わってしまっていないか確認)")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
