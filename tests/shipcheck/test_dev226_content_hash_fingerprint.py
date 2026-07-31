# -*- coding: utf-8 -*-
r"""dev#226(2026-07-30)の単体試験: 共有キャッシュfingerprintのmtime依存を
内容sha256へ置き換えたことの直接検証。

背景(2026-07-30実測で判明): Python標準の`zipfile.extractall()`は展開先
ファイルのmtimeをアーカイブ内タイムスタンプではなく「展開した瞬間の
時刻」にする。Windows Sandbox(WSB)は毎回まっさらな環境で配布zipを
再展開するため、`pipeline\py\extract_vanilla.py`の`build_fingerprint()`
(旧: extractor_size+extractor_mtime)や`pipeline\py\live_template.py`の
fingerprint(旧: manifest_mtime)がSandbox起動のたびに変わってしまい、
dev#226(WSBキャッシュ持ち込みゲート)の前提である「一意性の担保」が
原理的に成立しなかった。本WPでこれらを内容sha256ベース
(extractor_hash / manifest_hash)へ置き換えた。

このテストは実Palworld pakを必要としない(pak自体はstatされるだけで
中身は読まれないため、ダミーファイルで足りる)。build_live_template()/
extract_vanilla.run()本体(実際の抽出・組み立て)は一切呼ばない
(副作用ゼロのfingerprint計算/probe関数だけを見る)。

実行: python -m pytest tests\shipcheck\test_dev226_content_hash_fingerprint.py -v
"""
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
if PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_PY_DIR)

import vp_core as core  # noqa: E402
import extract_vanilla  # noqa: E402
import live_template  # noqa: E402


def _fake_job(tmp_path, pak_name="Pal-Windows.pak"):
    pak = tmp_path / pak_name
    pak.write_bytes(b"dummy pak content for fingerprint stat tests")
    job_dir = tmp_path / "job"
    job_dir.mkdir(exist_ok=True)
    return {
        "paths": {"palworld_pak": str(pak)},
        "job_dir": str(job_dir),
    }


# --------------------------------------------------------------- vp_core.sha256_file

def test_sha256_file_matches_hashlib_reference(tmp_path):
    import hashlib
    p = tmp_path / "sample.bin"
    data = b"hello dev#226" * 1000
    p.write_bytes(data)
    assert core.sha256_file(str(p)) == hashlib.sha256(data).hexdigest()


def test_sha256_file_stable_across_mtime_change(tmp_path):
    p = tmp_path / "sample.bin"
    p.write_bytes(b"stable content")
    h1 = core.sha256_file(str(p))
    os.utime(str(p), (1_600_000_000, 1_600_000_000))
    h2 = core.sha256_file(str(p))
    assert h1 == h2


# --------------------------------------------------------------- extract_vanilla.build_fingerprint

def test_build_fingerprint_uses_extractor_hash_not_mtime(tmp_path):
    job = _fake_job(tmp_path)
    fp = extract_vanilla.build_fingerprint(job)
    assert "extractor_hash" in fp, "dev#226: extractor_hash(内容sha256)が無い"
    assert "extractor_mtime" not in fp, "旧mtimeベースの鍵が残っている(WSBで安定しない)"
    assert "extractor_size" not in fp, "旧sizeベースの鍵が残っている"
    assert fp["extractor_hash"] == core.sha256_file(os.path.abspath(extract_vanilla.__file__))


def test_build_fingerprint_extractor_hash_stable_across_mtime_touch(tmp_path):
    """dev#226の核心の直接検証: extract_vanilla.py自身のmtimeを変えても
    (=WSBが毎回再展開して付け直す「今の時刻」を模す)、内容が同じなら
    build_fingerprint()の結果は完全に不変であること。"""
    job = _fake_job(tmp_path)
    real_path = os.path.abspath(extract_vanilla.__file__)
    original_stat = os.stat(real_path)
    fp_before = extract_vanilla.build_fingerprint(job)
    try:
        # WSB再展開を模した「今の時刻」への touch
        os.utime(real_path, (time.time(), time.time()))
        fp_after = extract_vanilla.build_fingerprint(job)
        assert fp_after == fp_before, (
            "extract_vanilla.pyのmtimeを変えただけでfingerprintが変わった"
            "(WSBで再展開のたびにキャッシュミスする不具合が再発している)")
    finally:
        os.utime(real_path, (original_stat.st_atime, original_stat.st_mtime))


def test_build_fingerprint_extractor_hash_changes_on_content_change(tmp_path, monkeypatch):
    """負の対照: 内容が実際に変われば(=別ファイルに差し替えれば)
    extractor_hashは必ず変わる(すり替えて検知できないという事故がないこと)。"""
    job = _fake_job(tmp_path)
    fp_before = extract_vanilla.build_fingerprint(job)

    decoy = tmp_path / "decoy_extract_vanilla.py"
    decoy.write_text("# decoy content, not the real extract_vanilla.py\n", encoding="utf-8")
    monkeypatch.setattr(extract_vanilla, "__file__", str(decoy))
    fp_after = extract_vanilla.build_fingerprint(job)

    assert fp_after["extractor_hash"] != fp_before["extractor_hash"]


# --------------------------------------------------------------- live_template fingerprint

def test_live_template_fingerprint_uses_manifest_hash_not_mtime(tmp_path):
    job = _fake_job(tmp_path)
    probe = live_template.probe_live_template(job)
    fp = probe["fingerprint"]
    assert "manifest_hash" in fp, "dev#226: manifest_hash(内容sha256)が無い"
    assert "manifest_mtime" not in fp, "旧mtimeベースの鍵が残っている(WSBで安定しない)"
    assert fp["manifest_hash"] == core.sha256_file(live_template.MANIFEST_PATH)


def test_live_template_fingerprint_stable_across_manifest_mtime_touch(tmp_path):
    """dev#226の核心の直接検証(live_template版): manifestファイルのmtimeを
    「今の時刻」へ変えても、probe_live_template()のfingerprintは不変。"""
    job = _fake_job(tmp_path)
    manifest_path = live_template.MANIFEST_PATH
    original_stat = os.stat(manifest_path)
    fp_before = live_template.probe_live_template(job)["fingerprint"]
    try:
        os.utime(manifest_path, (time.time(), time.time()))
        fp_after = live_template.probe_live_template(job)["fingerprint"]
        assert fp_after == fp_before, (
            "noue_template_manifest.jsonのmtimeを変えただけでfingerprintが"
            "変わった(WSBで再展開のたびにキャッシュミスする不具合が再発している)")
    finally:
        os.utime(manifest_path, (original_stat.st_atime, original_stat.st_mtime))


def test_probe_live_template_reports_not_fresh_when_marker_absent(tmp_path):
    """まだ一度もbuild_live_template()を実行していない(共有キャッシュが
    空の)work_rootに対しては、必ずfresh=Falseであること
    (「疑わしきはコールド」の最も基本的な形)。"""
    job = _fake_job(tmp_path)
    probe = live_template.probe_live_template(job)
    assert probe["fresh"] is False
    assert not os.path.exists(probe["marker_path"])


def test_probe_live_template_does_not_write_anything(tmp_path):
    """probe_live_template()は副作用ゼロ(呼び出し前後でcache_dir/マーカーの
    いずれも作られない)こと——read-onlyマウント越しに安全に呼べる根拠。"""
    job = _fake_job(tmp_path)
    probe = live_template.probe_live_template(job)
    assert not os.path.exists(probe["cache_dir"])
    assert not os.path.exists(probe["marker_path"])
    # 呼び出し後も、work_root配下に新規ファイルが一切増えていないこと
    work_root = core.job_work_root(job)
    shared_cache_root = core.shared_cache_root(work_root)
    assert not os.path.exists(shared_cache_root), (
        "probe_live_template()が共有キャッシュのディレクトリ自体を"
        "作ってしまっている(副作用ゼロの前提が崩れている)")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
