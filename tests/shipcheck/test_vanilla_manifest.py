# -*- coding: utf-8 -*-
"""wp878991(dev#87/#89/#91): pipeline\\py\\extract_vanilla.py の抽出物マニフェスト
(compute_manifest/write_manifest/ensure_manifest)の単体試験。

対象は「37.7GBのバニラpakを一切読まずに、抽出済みの小さい出力ファイル集合だけから
決定論的なハッシュを作れているか」で、実機のPalworldインストールもBlenderも不要。
実物のpakを使う統合試験は tests\\shipcheck\\test_shared_cache.py 側(既存)が担う。

pytestからも `python tests/shipcheck/test_vanilla_manifest.py` からも実行できる
(tests\\shipcheck\\test_shared_cache.py と同じ構成)。
"""
import json
import os
import shutil
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
if PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_PY_DIR)

import extract_vanilla as ev  # noqa: E402


def _fresh_dir(name):
    d = os.path.join(tempfile.gettempdir(), "d2p_vanilla_manifest_test_" + name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def _write_fake_extraction(vdir, variant="a"):
    """extract_blender_stage/extract_full_stageの実際の出力を模した最小セット
    (中身の"意味"は関係なく、ファイルの存在とバイト列だけがcompute_manifestの
    入力になることを確認したい)。"""
    os.makedirs(vdir, exist_ok=True)
    files = {
        "refskel_male.json": {"Hips": [0, 0, 0]},
        "refskel_female.json": {"Hips": [0, 0, 0]},
        "common_bones.json": {"common": ["Hips"], "dropped": []},
        "sk_inventory.json": {"outfit": [], "head": [], "hair": [], "headequip": []},
    }
    for fn, obj in files.items():
        with open(os.path.join(vdir, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    for fn in ("dup_outfit_male.csv", "dup_outfit_female.csv", "dup_head_male.csv",
               "dup_head_female.csv", "dup_hair.csv", "dup_headequip.csv"):
        with open(os.path.join(vdir, fn), "w", encoding="utf-8") as f:
            f.write("Folder,Name\r\n")
    import gzip
    with gzip.GzipFile(os.path.join(vdir, "pak_entries.txt.gz"), mode="wb", mtime=0) as f:
        f.write(("entry_a.uasset\nentry_b.uasset" + variant).encode("utf-8"))


# ============================================================================
# compute_manifest / write_manifest: 決定論性と検出感度
# ============================================================================

def test_compute_manifest_is_deterministic_across_runs():
    """同じ入力から2回計算しても同じcombined_hashになること(dev#91の前提条件)。
    実運用ではpak_entries.txt.gzの列挙順が実行のたびに揺れる実測不具合が
    あったため(extract_full_stageでsorted()化して修正)、ここでは
    「同一バイト列の入力」からの決定論性だけを見る(揺れの再発防止は
    test_extract_full_stage_pak_entries_is_sorted側で見る)。"""
    d1 = _fresh_dir("det1")
    d2 = _fresh_dir("det2")
    _write_fake_extraction(d1)
    _write_fake_extraction(d2)
    m1 = ev.compute_manifest(d1)
    m2 = ev.compute_manifest(d2)
    assert m1["combined_hash"] == m2["combined_hash"], (
        "同一内容の抽出物なのにcombined_hashが変わった(決定論性が壊れている)")
    assert len(m1["combined_hash"]) == 64  # sha256 hex


def test_compute_manifest_changes_when_one_file_is_corrupted():
    """負の対照: 抽出物1ファイルを改変したら互換認定されない(dev#91の受入条件)。"""
    d = _fresh_dir("corrupt")
    _write_fake_extraction(d)
    baseline = ev.compute_manifest(d)["combined_hash"]

    with open(os.path.join(d, "dup_hair.csv"), "a", encoding="utf-8") as f:
        f.write("SomeFolder,SK_Extra_Hair999\r\n")
    mutated = ev.compute_manifest(d)["combined_hash"]

    assert mutated != baseline, "1ファイルを改変してもcombined_hashが変わらない(検出感度が無い)"


def test_compute_manifest_ignores_missing_optional_hair_file():
    """refskel_hair.jsonは必須出力でない(バニラ髪SKが取れない環境がある)。
    無くてもmanifestは作れ、他ファイルだけでcombined_hashが決まること。"""
    d = _fresh_dir("nohair")
    _write_fake_extraction(d)
    m = ev.compute_manifest(d)
    assert "refskel_hair.json" not in m["files"]
    assert m["combined_hash"]  # 空にならない


def test_write_manifest_writes_readable_json():
    d = _fresh_dir("write")
    _write_fake_extraction(d)
    m = ev.write_manifest(d)
    path = os.path.join(d, ev.MANIFEST_NAME)
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["combined_hash"] == m["combined_hash"]
    assert on_disk["algo"] == "sha256"


def test_ensure_manifest_is_idempotent_and_backward_compatible():
    """本機能導入前に作られた(=vanilla_manifest.jsonが無い)vanilla_dirでも、
    full段の出力さえ揃っていれば後追いで作れること(run()の後方互換パス)。"""
    d = _fresh_dir("ensure")
    _write_fake_extraction(d)
    path = os.path.join(d, ev.MANIFEST_NAME)
    assert not os.path.exists(path)
    ev.ensure_manifest(d, shared=False)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        first = json.load(f)["combined_hash"]

    # 既にある場合は上書きしない(呼んでも壊れない・冪等)ことだけ確認
    os.utime(path, (0, 0))
    ev.ensure_manifest(d, shared=False)
    with open(path, encoding="utf-8") as f:
        second = json.load(f)["combined_hash"]
    assert first == second


def test_ensure_manifest_noop_when_full_outputs_incomplete():
    """full段の出力が全部揃っていない(blender段だけ完了、またはまだ何も無い)
    状態では何も作らない(中途半端なmanifestを既知良好リストと誤って
    照合させないため)。"""
    d = _fresh_dir("incomplete")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "refskel_male.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    ev.ensure_manifest(d, shared=False)
    assert not os.path.exists(os.path.join(d, ev.MANIFEST_NAME))


# ============================================================================
# extract_full_stage: pak_entries.txt.gz の決定論性そのもの(実測不具合の回帰試験)
# ----------------------------------------------------------------------------
# 2026-07-29実測: core.read_pak_index()が返すentriesの並び順は同一pakでも
# 実行のたびに変わり(v1.0.1/v1.0.2の同一18.5万行集合で818行の並び差を実測)、
# 対策前はcombined_hashが実行のたびに揺れて自己判定そのものが機能しなかった。
# gzipヘッダの既定mtime埋め込みも同じ理由で問題だった。
# ============================================================================

def test_extract_full_stage_output_is_sorted_and_gzip_mtime_fixed(monkeypatch):
    d = _fresh_dir("sorted")
    os.makedirs(d, exist_ok=True)

    unsorted_entries = ["Pal/Content/Zeta.uasset", "Pal/Content/Alpha.uasset",
                        "Pal/Content/Mid.uasset"]

    def fake_read_pak_index(pak):
        return "../../../", list(unsorted_entries)  # 呼び出しごとに新しいlistを返す

    monkeypatch.setattr(ev.core, "read_pak_index", fake_read_pak_index)
    monkeypatch.setattr(ev, "gen_duplication_lists", lambda entries, vdir: None)

    job = {"paths": {"palworld_pak": "dummy.pak"}}
    ev.extract_full_stage(job, d)

    import gzip
    with gzip.open(os.path.join(d, "pak_entries.txt.gz"), "rt", encoding="utf-8") as f:
        written = f.read().split("\n")
    assert written == sorted(unsorted_entries), (
        "pak_entries.txt.gzの内容がsortedでない(実行のたびに列挙順が揺れる"
        "core.read_pak_index()の非決定性がそのままファイルへ漏れる)")

    # 同じ内容をもう一度書き込んでも、gzipバイト列自体が完全一致すること
    # (mtime埋め込みが無効化されていないと、内容が同じでも圧縮後バイト列が変わる)
    path1 = os.path.join(d, "pak_entries.txt.gz")
    with open(path1, "rb") as f:
        bytes1 = f.read()
    ev.extract_full_stage(job, d)
    with open(path1, "rb") as f:
        bytes2 = f.read()
    assert bytes1 == bytes2, "同一内容の再抽出でpak_entries.txt.gzのバイト列が変わった(gzip mtimeが固定されていない)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
