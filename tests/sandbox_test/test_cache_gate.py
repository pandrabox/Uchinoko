# -*- coding: utf-8 -*-
r"""dev#226(2026-07-30、オーナー裁定)の単体試験。

対象: devtools\sandbox_test\cache_gate.py
    「バニラ処理層(L0)の実行ファイルhashが変わらず、かつWSBでの成功実績が
    あるならキャッシュ持ち込みを許可する」というオーナー裁定の条件を
    機械的に判定する純関数群。

このテストはWindows Sandbox・実Blender・実Palworldのいずれも起動しない
(zipファイル操作とtmp_pathのみ、CLAUDE.md安全制約)。要求された4つの負の
対照をすべて含む:
  ①指紋一致+実績あり             -> 持ち込み判定
  ②コード1バイト変更で指紋不一致 -> コールド判定
  ③実績なし                       -> コールド判定
  ④キャッシュ欠損(warm失敗)     -> コールド判定

実行: python -m pytest tests\sandbox_test\test_cache_gate.py -v
"""
import json
import os
import sys
import zipfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SANDBOX_TEST_DIR = os.path.join(REPO, "devtools", "sandbox_test")
if SANDBOX_TEST_DIR not in sys.path:
    sys.path.insert(0, SANDBOX_TEST_DIR)

import cache_gate  # noqa: E402


# --------------------------------------------------------------- ヘルパ

STAGE = "Uchinoko_for_Palworld"


def _make_zip(path, files):
    """files: {relpath(ステージングフォルダ相対、_internal/は含まない): bytes}。
    2026-07-31のランチャー廃止・_internal廃止後の実物canonical
    zip(STAGE直下にレイヤーファイルが並ぶフラット構成)を模す。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for relpath, data in files.items():
            zf.writestr(STAGE + "/" + relpath, data)


def _layer_payload(overrides=None):
    payload = {relpath: ("content of %s" % relpath).encode("utf-8")
               for relpath in cache_gate.LAYER_FILES}
    if overrides:
        payload.update(overrides)
    return payload


# --------------------------------------------------------------- code_hash

def test_compute_layer_code_hash_is_stable_for_same_content():
    reader = cache_gate.read_bytes_from_dir
    d1 = _write_dir_files(tmp_name="hashdir_a")
    h1 = cache_gate.compute_layer_code_hash(reader(d1))
    d2 = _write_dir_files(tmp_name="hashdir_b")
    h2 = cache_gate.compute_layer_code_hash(reader(d2))
    assert h1["combined_hash"] == h2["combined_hash"], (
        "同一内容の2つの独立ディレクトリでcombined_hashが一致しない")


def _write_dir_files(tmp_name):
    import tempfile
    base = os.path.join(tempfile.gettempdir(), "d2p_cache_gate_test_" + tmp_name)
    payload = _layer_payload()
    for relpath, data in payload.items():
        full = os.path.join(base, *relpath.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
    return base


def test_read_bytes_from_zip_reads_stage_prefixed_member(tmp_path):
    zpath = str(tmp_path / "a.zip")
    _make_zip(zpath, _layer_payload())
    reader = cache_gate.read_bytes_from_zip(zpath)
    one = cache_gate.LAYER_FILES[0]
    assert reader(one) == ("content of %s" % one).encode("utf-8")


def test_read_bytes_from_zip_missing_member_raises_probe_error(tmp_path):
    zpath = str(tmp_path / "broken.zip")
    payload = _layer_payload()
    del payload[cache_gate.LAYER_FILES[0]]
    _make_zip(zpath, payload)
    reader = cache_gate.read_bytes_from_zip(zpath)
    with pytest.raises(cache_gate.CacheGateProbeError):
        reader(cache_gate.LAYER_FILES[0])


# --------------------------------------------------------------- gate fingerprint

def _fake_pak(tmp_path, content=b"pak-bytes", mtime=None):
    p = tmp_path / "Pal-Windows.pak"
    p.write_bytes(content)
    if mtime is not None:
        os.utime(str(p), (mtime, mtime))
    return str(p)


def test_gate_fingerprint_matches_across_two_independent_zip_builds(tmp_path):
    """dev#226の核心: 同一内容のzipを2回独立に作っても(=mtimeが異なっても
    zip自体のbytesを読むだけなので)、gate_fingerprintは完全に一致する
    (WSB内で毎回再展開されてもfingerprintが安定することの直接の根拠)。"""
    payload = _layer_payload()
    zip_a = str(tmp_path / "a.zip")
    zip_b = str(tmp_path / "b.zip")
    _make_zip(zip_a, payload)
    _make_zip(zip_b, payload)
    pak = _fake_pak(tmp_path, mtime=1_700_000_000)

    fp_a, _ = cache_gate.compute_gate_fingerprint_from_zip(zip_a, pak)
    fp_b, _ = cache_gate.compute_gate_fingerprint_from_zip(zip_b, pak)
    assert fp_a == fp_b


def test_gate_fingerprint_changes_on_single_byte_code_change(tmp_path):
    """負の対照②: レイヤーファイル1つを1バイトだけ変えると、
    gate_fingerprintは必ず変わる。"""
    payload = _layer_payload()
    zip_a = str(tmp_path / "a.zip")
    _make_zip(zip_a, payload)
    pak = _fake_pak(tmp_path, mtime=1_700_000_000)
    fp_a, _ = cache_gate.compute_gate_fingerprint_from_zip(zip_a, pak)

    mutated = dict(payload)
    one = cache_gate.LAYER_FILES[0]
    mutated[one] = mutated[one] + b"X"  # 1バイト追加
    zip_b = str(tmp_path / "b.zip")
    _make_zip(zip_b, mutated)
    fp_b, _ = cache_gate.compute_gate_fingerprint_from_zip(zip_b, pak)

    assert fp_a != fp_b, "レイヤーファイルが1バイト変わったのにgate_fingerprintが不変"


def test_gate_fingerprint_changes_when_pak_identity_changes(tmp_path):
    payload = _layer_payload()
    zpath = str(tmp_path / "a.zip")
    _make_zip(zpath, payload)
    pak_a = _fake_pak(tmp_path, content=b"pak-bytes-a", mtime=1_700_000_000)
    fp_a, _ = cache_gate.compute_gate_fingerprint_from_zip(zpath, pak_a)

    pak_b_path = tmp_path / "Pal-Windows-2.pak"
    pak_b_path.write_bytes(b"different-size-pak")
    os.utime(str(pak_b_path), (1_700_000_000, 1_700_000_000))
    fp_b, _ = cache_gate.compute_gate_fingerprint_from_zip(zpath, str(pak_b_path))

    assert fp_a != fp_b


def test_gate_fingerprint_from_zip_missing_pak_raises_probe_error(tmp_path):
    payload = _layer_payload()
    zpath = str(tmp_path / "a.zip")
    _make_zip(zpath, payload)
    with pytest.raises(cache_gate.CacheGateProbeError):
        cache_gate.compute_gate_fingerprint_from_zip(zpath, str(tmp_path / "nope.pak"))


# --------------------------------------------------------------- 環境の適格性

@pytest.mark.parametrize("var", cache_gate._UNTRACKED_DEBUG_ENV_VARS)
def test_env_ineligible_when_untracked_debug_var_set(var):
    ok, reason = cache_gate.is_cache_gate_eligible_env({var: "1"})
    assert ok is False
    assert var in reason


def test_env_eligible_when_no_debug_vars_set():
    ok, reason = cache_gate.is_cache_gate_eligible_env({})
    assert ok is True
    assert reason == ""


# --------------------------------------------------------------- 台帳(実績)

def test_load_ledger_pass_fingerprints_missing_file_returns_empty_set(tmp_path):
    fps = cache_gate.load_ledger_pass_fingerprints(str(tmp_path / "no_such_file.jsonl"))
    assert fps == set()


def test_append_and_load_ledger_roundtrip(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    cache_gate.append_ledger_record("fp_aaa", git_head="deadbeef", zip_sha256="zzz",
                                     path=ledger)
    cache_gate.append_ledger_record("fp_bbb", git_head="deadbeef", zip_sha256="zzz",
                                     path=ledger)
    fps = cache_gate.load_ledger_pass_fingerprints(ledger)
    assert fps == {"fp_aaa", "fp_bbb"}


def test_load_ledger_skips_corrupt_lines_but_keeps_valid_ones(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")
    with open(ledger, "w", encoding="utf-8") as f:
        f.write("{ not valid json\n")
        f.write(json.dumps({"gate_fingerprint": "fp_good"}) + "\n")
        f.write("\n")  # 空行
    fps = cache_gate.load_ledger_pass_fingerprints(ledger)
    assert fps == {"fp_good"}


def test_ledger_path_is_under_devonly_state_not_work():
    r"""CLAUDE.md「workに恒常データを置かない」原則: work\配下ではなく
    .devonly\state\配下(disk_guard.pyのDISK_LOG_PATHと同じ流儀)であること。"""
    assert ".devonly" in cache_gate.LEDGER_PATH
    assert os.sep + "state" + os.sep in cache_gate.LEDGER_PATH
    assert (os.sep + "work" + os.sep) not in cache_gate.LEDGER_PATH


# --------------------------------------------------------------- decide_cache_bring_in(純粋判定)

def test_decide_bring_in_true_when_fingerprint_in_known_set():
    """負の対照①: 指紋一致+実績あり -> 持ち込み"""
    bring_in, reason = cache_gate.decide_cache_bring_in("fp_x", {"fp_x", "fp_y"})
    assert bring_in is True
    assert "持ち込む" in reason


def test_decide_bring_in_false_when_fingerprint_not_in_known_set():
    """負の対照③: 実績なし -> コールド"""
    bring_in, reason = cache_gate.decide_cache_bring_in("fp_new", {"fp_x", "fp_y"})
    assert bring_in is False
    assert "コールド" in reason


def test_decide_bring_in_false_when_known_set_empty():
    bring_in, _reason = cache_gate.decide_cache_bring_in("fp_anything", set())
    assert bring_in is False


# --------------------------------------------------------------- prepare_cache_bring_in(統合、副作用モック)

def test_prepare_cache_bring_in_full_positive_case(tmp_path, monkeypatch):
    """負の対照①の統合版: fingerprint一致+台帳に実績あり+warm_host_cache成功
    -> bring_in=True, host_cache_ready=True。"""
    payload = _layer_payload()
    zpath = str(tmp_path / "a.zip")
    _make_zip(zpath, payload)
    pak = _fake_pak(tmp_path, mtime=1_700_000_000)
    ledger = str(tmp_path / "ledger.jsonl")

    fp, _ = cache_gate.compute_gate_fingerprint_from_zip(zpath, pak)
    cache_gate.append_ledger_record(fp, path=ledger)

    monkeypatch.setattr(cache_gate, "warm_host_cache",
                         lambda *a, **kw: (True, {"returncode": 0}))

    result = cache_gate.prepare_cache_bring_in(
        zpath, pak, str(tmp_path / "shared_cache"), str(tmp_path / "work_root"),
        ledger_path=ledger)

    assert result["eligible"] is True
    assert result["bring_in"] is True
    assert result["host_cache_ready"] is True
    assert result["gate_fingerprint"] == fp


def test_prepare_cache_bring_in_no_ledger_record_is_cold(tmp_path):
    """負の対照③の統合版: 台帳が空 -> bring_in=False、warm_host_cacheは
    呼ばれない(副作用なし)ことも確認する。"""
    payload = _layer_payload()
    zpath = str(tmp_path / "a.zip")
    _make_zip(zpath, payload)
    pak = _fake_pak(tmp_path, mtime=1_700_000_000)
    ledger = str(tmp_path / "empty_ledger.jsonl")

    result = cache_gate.prepare_cache_bring_in(
        zpath, pak, str(tmp_path / "shared_cache"), str(tmp_path / "work_root"),
        ledger_path=ledger)

    assert result["bring_in"] is False
    assert result["host_cache_ready"] is False


def test_prepare_cache_bring_in_code_change_breaks_match_even_with_stale_ledger(tmp_path):
    """負の対照②の統合版: 台帳には「前のコード」のfingerprintで実績があるが、
    今のzipはレイヤーファイルが1バイト変わっている -> gate_fingerprintが
    変わり、台帳のヒットにならず結局コールド。"""
    payload = _layer_payload()
    zpath_old = str(tmp_path / "old.zip")
    _make_zip(zpath_old, payload)
    pak = _fake_pak(tmp_path, mtime=1_700_000_000)
    ledger = str(tmp_path / "ledger.jsonl")
    old_fp, _ = cache_gate.compute_gate_fingerprint_from_zip(zpath_old, pak)
    cache_gate.append_ledger_record(old_fp, path=ledger)

    mutated = dict(payload)
    one = cache_gate.LAYER_FILES[0]
    mutated[one] = mutated[one] + b"X"
    zpath_new = str(tmp_path / "new.zip")
    _make_zip(zpath_new, mutated)

    result = cache_gate.prepare_cache_bring_in(
        zpath_new, pak, str(tmp_path / "shared_cache"), str(tmp_path / "work_root"),
        ledger_path=ledger)

    assert result["bring_in"] is False
    assert result["gate_fingerprint"] != old_fp


def test_prepare_cache_bring_in_warm_host_cache_failure_falls_back_to_cold(tmp_path, monkeypatch):
    """負の対照④: fingerprint一致+実績ありでも、ホスト側キャッシュの準備
    (warm_host_cache)自体が失敗すればbring_in=Falseへ倒す(疑わしきはコールド)。"""
    payload = _layer_payload()
    zpath = str(tmp_path / "a.zip")
    _make_zip(zpath, payload)
    pak = _fake_pak(tmp_path, mtime=1_700_000_000)
    ledger = str(tmp_path / "ledger.jsonl")
    fp, _ = cache_gate.compute_gate_fingerprint_from_zip(zpath, pak)
    cache_gate.append_ledger_record(fp, path=ledger)

    monkeypatch.setattr(cache_gate, "warm_host_cache",
                         lambda *a, **kw: (False, {"error": "boom"}))

    result = cache_gate.prepare_cache_bring_in(
        zpath, pak, str(tmp_path / "shared_cache"), str(tmp_path / "work_root"),
        ledger_path=ledger)

    assert result["bring_in"] is False
    assert result["host_cache_ready"] is False


def test_prepare_cache_bring_in_ineligible_env_skips_everything(tmp_path, monkeypatch):
    payload = _layer_payload()
    zpath = str(tmp_path / "a.zip")
    _make_zip(zpath, payload)
    pak = _fake_pak(tmp_path, mtime=1_700_000_000)

    called = {"warm": False}
    monkeypatch.setattr(cache_gate, "warm_host_cache",
                         lambda *a, **kw: called.__setitem__("warm", True) or (True, {}))

    result = cache_gate.prepare_cache_bring_in(
        zpath, pak, str(tmp_path / "shared_cache"), str(tmp_path / "work_root"),
        env={"D2P_U50_DISABLE_UNIFY": "1"})

    assert result["eligible"] is False
    assert result["bring_in"] is False
    assert called["warm"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
