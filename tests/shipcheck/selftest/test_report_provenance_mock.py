# -*- coding: utf-8 -*-
"""G1-e: provenance(来歴)がレポートに載ることを検証する。実行ごとにgit HEAD・
TEMPLATE_BUILD_VERSION・日時・pak SHA1をレポートへ自動記録する設計
(docs\\U32_SONNET_INSTRUCTIONS.md 4-2節、FRESH_QAレビュー3位の恒久対策)。
"""
import json
import os

import gates
import report as report_mod


def test_provenance_dict_has_required_keys(monkeypatch):
    monkeypatch.setattr(gates, "git_head", lambda cwd=None: "abc1234")
    monkeypatch.setattr(gates, "template_build_version", lambda: 5)
    prov = gates.provenance_dict()
    assert prov["git_head"] == "abc1234"
    assert prov["template_build_version"] == 5
    assert "timestamp" in prov


def test_provenance_dict_includes_pak_sha1_when_pak_given(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "git_head", lambda cwd=None: "abc1234")
    monkeypatch.setattr(gates, "template_build_version", lambda: 5)
    pak = tmp_path / "Avatar_PlayerSwap_P.pak"
    pak.write_bytes(b"content")
    prov = gates.provenance_dict(pak_path=str(pak))
    assert prov["pak_sha1"] == gates.sha1_file(str(pak))


def test_report_md_contains_provenance_fields(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    provenance = {"git_head": "deadbeef1234", "template_build_version": 5,
                  "timestamp": "2026-07-25T00:00:00"}
    with open(run_dir / "provenance.json", "w", encoding="utf-8") as f:
        json.dump(provenance, f)
    rows = [
        {"status": "PASS", "gate": "A_convert_exit0", "avatar": "toto", "case": "offline", "detail": {}},
        {"status": "FAIL", "gate": "E_crash_notcrashed", "avatar": "heon", "case": "machine",
         "detail": {"exit_code": 2}},
    ]
    with open(run_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    paths = report_mod.generate(str(run_dir))

    with open(paths["report_md"], encoding="utf-8") as f:
        md = f.read()
    assert "deadbeef1234" in md
    assert "template_build_version" in md
    assert "PASS 1" in md and "FAIL 1" in md

    with open(paths["junit"], encoding="utf-8") as f:
        junit = f.read()
    assert 'tests="2"' in junit
    assert 'failures="1"' in junit
    assert "toto::A_convert_exit0" in junit

    assert os.path.isfile(paths["contact_sheet"])


def test_contact_sheet_lists_avatar_with_crop_shot(tmp_path):
    run_dir = tmp_path / "run"
    shots = run_dir / "shots" / "toto"
    shots.mkdir(parents=True)
    (shots / "toto_20260725_120000_crop.png").write_bytes(b"x")
    with open(run_dir / "provenance.json", "w", encoding="utf-8") as f:
        json.dump({"git_head": "x"}, f)
    rows = [{"status": "PASS", "gate": "G_compare_avatar", "avatar": "toto", "case": "visual",
             "detail": {"verdict": {"same_avatar": True, "looks_correct": True}}}]
    with open(run_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    paths = report_mod.generate(str(run_dir))
    with open(paths["contact_sheet"], encoding="utf-8") as f:
        sheet = f.read()
    assert "toto" in sheet
    assert "_crop.png" in sheet
