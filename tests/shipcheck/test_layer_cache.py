# -*- coding: utf-8 -*-
r"""dev#79(層分離キャッシュ、devtools\layer_cache.py)の受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実変換を
一切課さない(pak不変の構造変更であり、既定D2P_LAYER_CACHE=0=無効のため)。
フィンガープリント計算・設定スライス帰属・キャッシュI/O・run_cachedの
定型フローを、tmp_pathで隔離した小さな入力で検証する。

実行: python -m pytest tests\shipcheck\test_layer_cache.py -v
"""
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_layer_cache():
    return importlib.reload(importlib.import_module("layer_cache"))


# --- is_enabled() / 既定は無効 ------------------------------------------------

def test_is_enabled_defaults_to_false(monkeypatch):
    lc = _import_layer_cache()
    monkeypatch.delenv("D2P_LAYER_CACHE", raising=False)
    assert lc.is_enabled() is False


def test_is_enabled_requires_exact_value_1(monkeypatch):
    lc = _import_layer_cache()
    monkeypatch.setenv("D2P_LAYER_CACHE", "true")  # "1"以外は無効側(fail-safe)
    assert lc.is_enabled() is False
    monkeypatch.setenv("D2P_LAYER_CACHE", "1")
    assert lc.is_enabled() is True


# --- 設定スライス帰属(#79「未宣言キーは全層帰属の安全側」) ------------------------

def test_config_slice_unknown_key_belongs_to_every_layer():
    lc = _import_layer_cache()
    job_config = {"totally_unregistered_key": 42}
    for layer in lc.LAYERS:
        sl = lc.config_slice_for_layer(job_config, layer)
        assert sl == {"totally_unregistered_key": 42}, (
            f"未宣言キーは全層({layer})に帰属しなければならない(安全側)")


def test_config_slice_declared_key_scoped_to_owning_layers_only():
    lc = _import_layer_cache()
    assert "shadow_lift" in lc.LAYER_CONFIG_OWNERSHIP
    owners = lc.LAYER_CONFIG_OWNERSHIP["shadow_lift"]
    job_config = {"shadow_lift": 0.5}
    for layer in lc.LAYERS:
        sl = lc.config_slice_for_layer(job_config, layer)
        if layer in owners:
            assert sl == {"shadow_lift": 0.5}
        else:
            assert sl == {}, (
                f"shadow_liftは{owners}にのみ帰属するはずなのに{layer}のスライスに"
                "漏れている(層の分離が機能していない)")


def test_config_slice_for_layer_rejects_unknown_layer():
    lc = _import_layer_cache()
    with pytest.raises(lc.LayerCacheError):
        lc.config_slice_for_layer({}, "L99")


# --- compute_layer_fingerprint: 入力の各要素が指紋へ効くこと ----------------------

def test_fingerprint_changes_on_input_dir_byte_change(tmp_path):
    lc = _import_layer_cache()
    d = tmp_path / "input_dir"
    d.mkdir()
    (d / "a.txt").write_text("v1", encoding="utf-8")

    fp_before = lc.compute_layer_fingerprint("L2", [str(d)], {}, [])
    (d / "a.txt").write_text("v2-one-byte-different", encoding="utf-8")
    fp_after = lc.compute_layer_fingerprint("L2", [str(d)], {}, [])

    assert fp_before != fp_after


def test_fingerprint_changes_on_owned_config_change(tmp_path):
    lc = _import_layer_cache()
    d = tmp_path / "input_dir"
    d.mkdir()
    (d / "a.txt").write_text("v1", encoding="utf-8")

    fp_a = lc.compute_layer_fingerprint("L2", [str(d)], {"shadow_lift": 0.0}, [])
    fp_b = lc.compute_layer_fingerprint("L2", [str(d)], {"shadow_lift": 0.5}, [])
    assert fp_a != fp_b, "L2に帰属するshadow_liftの変化はL2のfingerprintに効かねばならない"


def test_fingerprint_unaffected_by_config_owned_by_other_layer_only(tmp_path):
    lc = _import_layer_cache()
    d = tmp_path / "input_dir"
    d.mkdir()
    (d / "a.txt").write_text("v1", encoding="utf-8")

    # drop_bonesはL1にのみ帰属する(LAYER_CONFIG_OWNERSHIP)。L2のfingerprintには
    # 影響してはならない(層分離が効いていることの直接証拠)。
    fp_a = lc.compute_layer_fingerprint("L2", [str(d)], {"drop_bones": ["Hips"]}, [])
    fp_b = lc.compute_layer_fingerprint("L2", [str(d)], {"drop_bones": ["Spine"]}, [])
    assert fp_a == fp_b, (
        "drop_bonesはL1専属のはずなのにL2のfingerprintが変化した(層分離が漏れている)")


def test_fingerprint_changes_on_code_file_change(tmp_path):
    lc = _import_layer_cache()
    d = tmp_path / "input_dir"
    d.mkdir()
    code = tmp_path / "logic.py"
    code.write_text("def f(): return 1\n", encoding="utf-8")

    fp_before = lc.compute_layer_fingerprint("L2", [str(d)], {}, [str(code)])
    code.write_text("def f(): return 2\n", encoding="utf-8")
    fp_after = lc.compute_layer_fingerprint("L2", [str(d)], {}, [str(code)])
    assert fp_before != fp_after, (
        "層ロジック自体(code_files)の変更はfingerprintを無効化しなければならない")


def test_fingerprint_treats_absent_input_dir_deterministically(tmp_path):
    lc = _import_layer_cache()
    absent = str(tmp_path / "does_not_exist")
    fp1 = lc.compute_layer_fingerprint("L2", [absent], {}, [])
    fp2 = lc.compute_layer_fingerprint("L2", [absent], {}, [])
    assert fp1 == fp2, "不在ディレクトリは決定的なマーカーとして扱われなければならない"


def test_compute_layer_fingerprint_rejects_unknown_layer(tmp_path):
    lc = _import_layer_cache()
    with pytest.raises(lc.LayerCacheError):
        lc.compute_layer_fingerprint("L99", [], {}, [])


# --- try_restore / store: 復元の同一性 -----------------------------------------

def test_try_restore_misses_when_nothing_cached(tmp_path):
    lc = _import_layer_cache()
    dest = tmp_path / "dest"
    hit = lc.try_restore("L2", "deadbeef" * 8, str(tmp_path / "work"), str(dest))
    assert hit is False
    assert not dest.exists()


def test_store_then_restore_roundtrip_is_byte_identical(tmp_path):
    lc = _import_layer_cache()
    work_root = str(tmp_path / "work")
    source = tmp_path / "source"
    (source / "sub").mkdir(parents=True)
    (source / "sub" / "x.bin").write_bytes(b"\x00\x01\x02hello")
    (source / "top.txt").write_text("top-level", encoding="utf-8")

    fingerprint = "cafef00d" * 8
    lc.store("L2", fingerprint, work_root, str(source))

    dest = tmp_path / "restored"
    hit = lc.try_restore("L2", fingerprint, work_root, str(dest))
    assert hit is True
    assert (dest / "top.txt").read_text(encoding="utf-8") == "top-level"
    assert (dest / "sub" / "x.bin").read_bytes() == b"\x00\x01\x02hello"
    # 完了マーカー自体は復元先に漏れ出してはならない(利用側の成果物と混ざらない)
    assert not (dest / lc._COMPLETE_MARKER).exists()


def test_store_missing_source_dir_raises(tmp_path):
    lc = _import_layer_cache()
    with pytest.raises(lc.LayerCacheError):
        lc.store("L2", "abc123" * 10, str(tmp_path / "work"),
                  str(tmp_path / "does_not_exist"))


def test_cache_dir_respects_d2p_shared_cache_override(tmp_path, monkeypatch):
    lc = _import_layer_cache()
    override = tmp_path / "custom_shared_cache"
    monkeypatch.setenv("D2P_SHARED_CACHE", str(override))
    d = lc.cache_dir_for(str(tmp_path / "work_root_ignored"), "L2", "deadbeef" * 8)
    assert os.path.normcase(d).startswith(os.path.normcase(str(override)))


# --- run_cached: 定型フロー ----------------------------------------------------

def test_run_cached_disabled_is_pure_passthrough(tmp_path, monkeypatch):
    """負の対照: D2P_LAYER_CACHE=0(既定/未設定)ならbuilder_fnが必ず呼ばれ、
    キャッシュディレクトリには一切何も作られない(既存の処理順序・中身が
    不変であることの直接証拠)。"""
    lc = _import_layer_cache()
    monkeypatch.delenv("D2P_LAYER_CACHE", raising=False)
    work_root = str(tmp_path / "work")
    dest = tmp_path / "dest"

    calls = []

    def builder():
        calls.append(1)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "out.txt").write_text("built", encoding="utf-8")
        return "sentinel-return-value"

    result, hit = lc.run_cached("L2", work_root, str(dest), [], {}, [], builder)
    assert calls == [1]
    assert result == "sentinel-return-value"
    assert hit is False
    assert not os.path.isdir(lc._cache_root(work_root)), (
        "無効時はキャッシュディレクトリへ一切触れてはならない")


def test_run_cached_enabled_miss_then_hit(tmp_path, monkeypatch):
    lc = _import_layer_cache()
    monkeypatch.setenv("D2P_LAYER_CACHE", "1")
    work_root = str(tmp_path / "work")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.txt").write_text("fixed-input", encoding="utf-8")
    dest = tmp_path / "dest"

    calls = []

    def builder():
        calls.append(1)
        if dest.exists():
            import shutil as _sh
            _sh.rmtree(dest)
        dest.mkdir(parents=True)
        (dest / "out.txt").write_text("built-once", encoding="utf-8")
        return "ignored-on-hit"

    # 1回目: ミス -> builder_fnが呼ばれ、キャッシュに登録される
    result1, hit1 = lc.run_cached("L2", work_root, str(dest), [str(input_dir)], {}, [], builder)
    assert calls == [1]
    assert hit1 is False
    assert result1 == "ignored-on-hit"
    assert (dest / "out.txt").read_text(encoding="utf-8") == "built-once"

    # dest を壊してから2回目を呼ぶ(復元されることを可視化するため)
    (dest / "out.txt").write_text("TAMPERED", encoding="utf-8")

    # 2回目: 同じ入力 -> ヒット -> builder_fnは呼ばれない、dest はキャッシュから復元
    result2, hit2 = lc.run_cached("L2", work_root, str(dest), [str(input_dir)], {}, [], builder)
    assert calls == [1], "キャッシュヒット時はbuilder_fnを呼んではならない"
    assert hit2 is True
    assert result2 is None, "ヒット時のresultはNone契約(#79: フォルダが主、戻り値は従)"
    assert (dest / "out.txt").read_text(encoding="utf-8") == "built-once", (
        "ヒット時はdestがキャッシュ内容へ復元されなければならない(改ざんが残ってはならない)")


def test_run_cached_enabled_input_change_forces_miss_again(tmp_path, monkeypatch):
    lc = _import_layer_cache()
    monkeypatch.setenv("D2P_LAYER_CACHE", "1")
    work_root = str(tmp_path / "work")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.txt").write_text("v1", encoding="utf-8")
    dest = tmp_path / "dest"

    calls = []

    def builder():
        calls.append(1)
        import shutil as _sh
        if dest.exists():
            _sh.rmtree(dest)
        dest.mkdir(parents=True)
        (dest / "out.txt").write_text(f"built-{len(calls)}", encoding="utf-8")

    lc.run_cached("L2", work_root, str(dest), [str(input_dir)], {}, [], builder)
    assert calls == [1]

    (input_dir / "a.txt").write_text("v2-changed", encoding="utf-8")
    lc.run_cached("L2", work_root, str(dest), [str(input_dir)], {}, [], builder)
    assert calls == [1, 1], "入力が変化すれば再度builder_fnが呼ばれなければならない(誤ヒット禁止)"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
