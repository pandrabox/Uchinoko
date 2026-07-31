# -*- coding: utf-8 -*-
"""G1-d: pak_forキャッシュ機構の検証。キャッシュヒット時に変換(_run_conversion相当)
が一切呼ばれないこと、allow_convert=False時はConversionSkippedになること、
job.json内容やTEMPLATE_BUILD_VERSIONが変わればキャッシュキーが変わり再構築される
こと、をモックで確認する(実変換・実pakは一切使わない)。
"""
import json
import os

import pytest

import gates


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "pak_cache"
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(gates, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(gates, "JOBS_DIR", str(jobs_dir))
    monkeypatch.setattr(gates, "template_build_version", lambda: 999)
    monkeypatch.setattr(gates, "git_head", lambda cwd=None: "deadbeef")
    return tmp_path


def _make_job(tmp_path, avatar="fakeavatar", extra=None):
    job_dir = tmp_path / "work" / avatar
    job_dir.mkdir(parents=True)
    job = {"avatar_name": avatar, "shoulder_offset_deg": 0.0}
    if extra:
        job.update(extra)
    job_path = job_dir / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    return str(job_path)


def _make_fake_run_conversion(call_log):
    def _fake(job_path, log_path, target_root=None):
        call_log.append((job_path, target_root))
        job = json.load(open(job_path, encoding="utf-8"))
        build_dir = os.path.join(os.path.dirname(job_path), "build")
        os.makedirs(build_dir, exist_ok=True)
        pak_path = os.path.join(build_dir, "{}_PlayerSwap_P.pak".format(job["avatar_name"]))
        with open(pak_path, "wb") as f:
            f.write(b"fake pak bytes")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("  [PASS] G1 dummy\n" * 9)
        return 0, "  [PASS] G1 dummy\n" * 9
    return _fake


def test_allow_convert_false_and_no_cache_raises_skip(isolated_cache):
    job_path = _make_job(isolated_cache)
    with pytest.raises(gates.ConversionSkipped):
        gates.build_or_get_cached("fakeavatar", job_path, allow_convert=False)


def test_cache_miss_then_hit_does_not_reconvert(isolated_cache):
    job_path = _make_job(isolated_cache)
    calls = []
    fake_run = _make_fake_run_conversion(calls)

    r1 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True, run_conversion=fake_run)
    assert r1.cache_hit is False
    assert r1.exit_code == 0
    assert r1.pak_path and os.path.isfile(r1.pak_path)
    assert len(calls) == 1

    r2 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True, run_conversion=fake_run)
    assert r2.cache_hit is True
    assert r2.pak_path == r1.pak_path
    assert len(calls) == 1, "キャッシュヒットのはずなのに変換が再度呼ばれた"

    # allow_convert=Falseでもキャッシュヒットなら例外にならない(ヒット優先)
    r3 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=False, run_conversion=fake_run)
    assert r3.cache_hit is True
    assert len(calls) == 1


def test_changing_overrides_busts_cache(isolated_cache):
    job_path = _make_job(isolated_cache)
    calls = []
    fake_run = _make_fake_run_conversion(calls)

    gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True, run_conversion=fake_run)
    assert len(calls) == 1

    gates.build_or_get_cached("fakeavatar", job_path, overrides={"unlit": True},
                               allow_convert=True, run_conversion=fake_run)
    assert len(calls) == 2, "job設定を変えたのにキャッシュキーが変わっていない"


def test_changing_template_build_version_busts_cache(isolated_cache, monkeypatch):
    job_path = _make_job(isolated_cache)
    calls = []
    fake_run = _make_fake_run_conversion(calls)

    gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True, run_conversion=fake_run)
    assert len(calls) == 1

    monkeypatch.setattr(gates, "template_build_version", lambda: 1000)
    gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True, run_conversion=fake_run)
    assert len(calls) == 2, "TEMPLATE_BUILD_VERSIONが変わったのにキャッシュが再利用された"


def test_missing_pak_on_disk_forces_rebuild(isolated_cache):
    job_path = _make_job(isolated_cache)
    calls = []
    fake_run = _make_fake_run_conversion(calls)

    r1 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True, run_conversion=fake_run)
    os.remove(r1.pak_path)

    r2 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True, run_conversion=fake_run)
    assert len(calls) == 2, "pak実体が消えているのに再構築されなかった"
    assert r2.cache_hit is False


# --- target_root(2026-07-25 ぱん裁定: 配布zip最終出荷検査モード) -------------
# ハーネス(テストコード・job.json)は本リポジトリのまま、被検体(実行される
# pipeline\cli\convert.ps1)だけ隔離ディレクトリ側に切り替えられることを検証する。

def test_target_root_switch_busts_cache_and_is_forwarded(isolated_cache):
    job_path = _make_job(isolated_cache)
    calls = []
    fake_run = _make_fake_run_conversion(calls)

    r1 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True,
                                    run_conversion=fake_run, target_root=None)
    assert r1.cache_hit is False
    assert len(calls) == 1
    assert calls[0][1] is None

    # target_rootを指定 → 別の被検体とみなしキャッシュキーが変わり再構築される
    dist_root = str(isolated_cache / "dist_test")
    r2 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True,
                                    run_conversion=fake_run, target_root=dist_root)
    assert len(calls) == 2, "target_rootを変えたのにキャッシュキーが変わっていない"
    assert calls[1][1] == dist_root, "target_rootがrun_conversionへ転送されていない"
    assert r2.cache_hit is False

    # 同じtarget_rootを再度指定 → 今度はキャッシュヒット(再変換されない)
    r3 = gates.build_or_get_cached("fakeavatar", job_path, allow_convert=True,
                                    run_conversion=fake_run, target_root=dist_root)
    assert r3.cache_hit is True
    assert len(calls) == 2, "同一target_rootなのに再変換された"


def test_run_conversion_uses_target_root_convert_ps1_path(monkeypatch, tmp_path):
    """_run_conversion自体(モック差し替えの継ぎ目の中身)が、target_root指定時に
    そちら側のpipeline\\cli\\convert.ps1を呼ぶことを、subprocess.runへ渡る実引数から
    確認する(実プロセスは起動しない — subprocess.run自体をmonkeypatch)。"""
    captured = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "  [PASS] G1 dummy\n" * 9
        stderr = ""

    def fake_subprocess_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs.get("cwd")
        return _FakeCompleted()

    monkeypatch.setattr(gates.subprocess, "run", fake_subprocess_run)

    log_path = str(tmp_path / "log.txt")
    dist_root = str(tmp_path / "d2p_dist_test")
    gates._run_conversion(str(tmp_path / "job.json"), log_path, target_root=dist_root)

    expected_ps1 = os.path.join(dist_root, "pipeline", "cli", "convert.ps1")
    assert captured["args"][2] == expected_ps1
    assert captured["cwd"] == dist_root


def test_run_conversion_defaults_to_repo_root_convert_ps1(monkeypatch, tmp_path):
    captured = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "  [PASS] G1 dummy\n" * 9
        stderr = ""

    def fake_subprocess_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs.get("cwd")
        return _FakeCompleted()

    monkeypatch.setattr(gates.subprocess, "run", fake_subprocess_run)

    log_path = str(tmp_path / "log.txt")
    gates._run_conversion(str(tmp_path / "job.json"), log_path)

    expected_ps1 = os.path.join(gates.REPO_ROOT, "pipeline", "cli", "convert.ps1")
    assert captured["args"][2] == expected_ps1
    assert captured["cwd"] == gates.REPO_ROOT
