# -*- coding: utf-8 -*-
r"""dev#226(2026-07-30)の単体試験: devtools\sandbox_test\run_sandbox_test.py
の`resolve_cache_gate_extra_mapped()`(ホスト側、WSB起動前のキャッシュ
持ち込み判定とtemplate.wsb用マウント片の組み立て)。

cache_gate.prepare_cache_bring_in()自体はcache_gate.py側で既に単体試験済み
(tests\sandbox_test\test_cache_gate.py)なので、ここではmonkeypatchで
差し替え、「呼ぶかどうかの分岐」「戻り値からXML片を正しく組み立てるか」
だけを検証する。Windows Sandbox・実zip・実Palworldは一切起動しない。

実行: python -m pytest tests\sandbox_test\test_run_sandbox_test_cache_gate.py -v
"""
import argparse
import importlib.util
import os
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(REPO, "devtools", "sandbox_test", "run_sandbox_test.py")

spec = importlib.util.spec_from_file_location("run_sandbox_test_cache_gate_test", MODULE_PATH)
rst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rst)


def _args(convert=True, tamper_convert=False):
    ns = argparse.Namespace()
    ns.convert = convert
    ns.tamper_convert = tamper_convert
    return ns


def _bring_in_result(fingerprint="fp_abc"):
    return {"eligible": True, "bring_in": True, "reason": "ok",
            "gate_fingerprint": fingerprint, "host_cache_ready": True, "detail": {}}


def _cold_result(reason="no record"):
    return {"eligible": True, "bring_in": False, "reason": reason,
            "gate_fingerprint": "fp_xyz", "host_cache_ready": False, "detail": {}}


def test_not_convert_skips_prepare_cache_bring_in_entirely(monkeypatch):
    called = {"value": False}
    monkeypatch.setattr(rst.cache_gate, "prepare_cache_bring_in",
                         lambda *a, **kw: called.__setitem__("value", True))

    extra, info = rst.resolve_cache_gate_extra_mapped(
        _args(convert=False), "z.zip", "C:\\palworld", "C:\\work")

    assert extra == ""
    assert info["bring_in"] is False
    assert called["value"] is False


def test_tamper_convert_skips_prepare_cache_bring_in_entirely(monkeypatch):
    """負の対照相当: tamper-convert(検体VRM破損)はどうせ変換が早期に
    失敗するので、キャッシュ持ち込みを検討しない(host_ref threadと同じ条件)。"""
    called = {"value": False}
    monkeypatch.setattr(rst.cache_gate, "prepare_cache_bring_in",
                         lambda *a, **kw: called.__setitem__("value", True))

    extra, info = rst.resolve_cache_gate_extra_mapped(
        _args(convert=True, tamper_convert=True), "z.zip", "C:\\palworld", "C:\\work")

    assert extra == ""
    assert called["value"] is False


def test_bring_in_true_produces_mapped_folder_xml_fragment(monkeypatch):
    """負の対照①相当: 持ち込み判定Trueなら、HOST_SHARED_CACHE_DIRを
    SANDBOX_SHARED_CACHE_DIRへReadOnlyでマップするXML片が組み立てられる。"""
    monkeypatch.setattr(rst.cache_gate, "prepare_cache_bring_in",
                         lambda *a, **kw: _bring_in_result())

    extra, info = rst.resolve_cache_gate_extra_mapped(
        _args(), "z.zip", "C:\\palworld", "C:\\work")

    assert info["bring_in"] is True
    assert "<MappedFolder>" in extra
    assert rst.HOST_SHARED_CACHE_DIR in extra
    assert rst.SANDBOX_SHARED_CACHE_DIR in extra
    assert "<ReadOnly>true</ReadOnly>" in extra


def test_bring_in_false_produces_empty_fragment(monkeypatch):
    """負の対照③相当: 実績なし等でbring_in=Falseならマウント片は空文字
    (=EXTRA_MAPPEDへ何も追加されない、コールド実行のまま)。"""
    monkeypatch.setattr(rst.cache_gate, "prepare_cache_bring_in",
                         lambda *a, **kw: _cold_result())

    extra, info = rst.resolve_cache_gate_extra_mapped(
        _args(), "z.zip", "C:\\palworld", "C:\\work")

    assert extra == ""
    assert info["bring_in"] is False


def test_prepare_cache_bring_in_exception_falls_back_to_cold_without_raising(monkeypatch):
    """疑わしきはコールド: cache_gate.prepare_cache_bring_in()が例外を
    投げても、resolve_cache_gate_extra_mapped()自体は例外を伝播せず
    コールド相当の結果を返す(WSB起動自体を巻き添えで落とさない)。"""
    def _boom(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(rst.cache_gate, "prepare_cache_bring_in", _boom)

    extra, info = rst.resolve_cache_gate_extra_mapped(
        _args(), "z.zip", "C:\\palworld", "C:\\work")

    assert extra == ""
    assert info["bring_in"] is False
    assert "例外" in info["reason"]


def test_palworld_pak_path_passed_to_prepare_cache_bring_in(monkeypatch):
    captured = {}

    def _fake_prepare(zip_path, pak_path, shared_cache_dir, work_root, **kw):
        captured["zip_path"] = zip_path
        captured["pak_path"] = pak_path
        captured["shared_cache_dir"] = shared_cache_dir
        return _cold_result()

    monkeypatch.setattr(rst.cache_gate, "prepare_cache_bring_in", _fake_prepare)

    rst.resolve_cache_gate_extra_mapped(
        _args(), "z.zip", "C:\\palworld_root", "C:\\work")

    assert captured["zip_path"] == "z.zip"
    assert captured["pak_path"] == os.path.join(
        "C:\\palworld_root", "Pal", "Content", "Paks", "Pal-Windows.pak")
    assert captured["shared_cache_dir"] == rst.HOST_SHARED_CACHE_DIR


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
