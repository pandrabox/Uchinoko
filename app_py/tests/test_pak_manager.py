# test_pak_manager.py -- WP-A4受入条件の単体試験(dev#532 方針A、
# DESIGN.md §5.2 WP-A4行 / §2.3)。
#
# ①自動発見→手動フォールバック→保存の三点セットがモックFSで確認できること
# ②SHA1照合ロジック(identify_applied_pak)の単体試験がPASSすること
# を中心に、pak_manager.py の各関数を実ファイルシステム(tmp_path)のみで
# (実Palworld/実Steam非依存で)検証する。実Palworldへのpak適用はここでは
# 検証しない(CLAUDE.md「受入試験はリリースゲートに任せる」、実機はrelease.py側)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pak_manager  # noqa: E402
import settings  # noqa: E402


def _make_paks_dir(tmp_path, name="Paks", with_vanilla=True):
    d = tmp_path / name
    d.mkdir()
    if with_vanilla:
        (d / pak_manager.PAL_WINDOWS_PAK_NAME).write_bytes(b"vanilla")
    return str(d)


# ---------------------------------------------------------------------------
# 基礎ヘルパー
# ---------------------------------------------------------------------------

def test_paks_dir_has_pak_true(tmp_path):
    d = _make_paks_dir(tmp_path)
    assert pak_manager.paks_dir_has_pak(d) is True


def test_paks_dir_has_pak_false_when_missing_pak(tmp_path):
    d = _make_paks_dir(tmp_path, with_vanilla=False)
    assert pak_manager.paks_dir_has_pak(d) is False


def test_paks_dir_has_pak_false_when_none_or_nonexistent(tmp_path):
    assert pak_manager.paks_dir_has_pak(None) is False
    assert pak_manager.paks_dir_has_pak(str(tmp_path / "nope")) is False


def test_distinct_preserve_order_dedups_case_and_trailing_slash():
    items = [r"C:\A\B\\", r"c:\a\b", r"C:\A\B/", r"C:\C", "", None]
    assert pak_manager.distinct_preserve_order(items) == [r"C:\A\B", r"C:\C"]


# ---------------------------------------------------------------------------
# 自動発見: SteamLibraryRoots (libraryfolders.vdf 解析)
# ---------------------------------------------------------------------------

def test_steam_library_roots_parses_vdf_paths(tmp_path):
    steam_root = tmp_path / "Steam"
    (steam_root / "steamapps").mkdir(parents=True)
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    vdf.write_text(
        '"libraryfolders"\n{\n'
        '\t"0"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n'
        '\t"1"\n\t{\n\t\t"path"\t\t"E:\\\\Games\\\\Steam"\n\t}\n'
        "}\n",
        encoding="utf-8",
    )
    roots = pak_manager.steam_library_roots(str(steam_root))
    assert str(steam_root) in roots
    assert r"D:\SteamLibrary" in roots
    assert r"E:\Games\Steam" in roots


def test_steam_library_roots_empty_for_missing_root():
    assert pak_manager.steam_library_roots(None) == []
    assert pak_manager.steam_library_roots("") == []


def test_steam_library_roots_ignores_missing_vdf(tmp_path):
    steam_root = tmp_path / "Steam2"
    steam_root.mkdir()
    assert pak_manager.steam_library_roots(str(steam_root)) == [str(steam_root)]


# ---------------------------------------------------------------------------
# ①自動発見→手動フォールバック→保存の三点セット
# ---------------------------------------------------------------------------

def test_auto_discover_paks_dir_finds_via_steam_layout(tmp_path, monkeypatch):
    lib = tmp_path / "MyLib"
    paks = lib / "steamapps" / "common" / "Palworld" / "Pal" / "Content" / "Paks"
    paks.mkdir(parents=True)
    (paks / pak_manager.PAL_WINDOWS_PAK_NAME).write_bytes(b"v")

    monkeypatch.setattr(pak_manager, "steam_root_candidates", lambda: [str(lib)])
    logs = []
    found = pak_manager.auto_discover_paks_dir(log=logs.append)
    assert found == str(paks)
    assert any("found" in line for line in logs)


def test_auto_discover_paks_dir_returns_none_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(pak_manager, "steam_root_candidates", lambda: [str(tmp_path / "nothing")])
    logs = []
    assert pak_manager.auto_discover_paks_dir(log=logs.append) is None
    assert any("not found" in line for line in logs)


def test_resolve_paks_dir_uses_cache_first(tmp_path):
    d = _make_paks_dir(tmp_path)
    # settingsファイルもauto_discoverも参照されないことを、明らかに無効な
    # app_rootを渡して確認する(cacheヒットならそもそも読みに行かないはず)
    result = pak_manager.resolve_paks_dir(str(tmp_path / "no_such_app_root"), cache=d)
    assert result == d


def test_resolve_paks_dir_uses_saved_settings(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir()
    d = _make_paks_dir(tmp_path, name="SavedPaks")
    settings.save_paksdir(str(app_root), d)
    monkeypatch.setattr(pak_manager, "auto_discover_paks_dir", lambda log=pak_manager._noop_log: (_ for _ in ()).throw(AssertionError("auto_discover should not be called")))
    result = pak_manager.resolve_paks_dir(str(app_root))
    assert result == d


def test_resolve_paks_dir_auto_discovers_and_saves(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir()
    d = _make_paks_dir(tmp_path, name="AutoPaks")
    monkeypatch.setattr(pak_manager, "auto_discover_paks_dir", lambda log=pak_manager._noop_log: d)
    result = pak_manager.resolve_paks_dir(str(app_root))
    assert result == d
    # 三点セット③: 保存されている(次回はauto_discoverを介さず読める)
    assert settings.load_paksdir(str(app_root)) == d


def test_resolve_paks_dir_falls_back_to_manual_and_saves(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir()
    monkeypatch.setattr(pak_manager, "auto_discover_paks_dir", lambda log=pak_manager._noop_log: None)
    good = _make_paks_dir(tmp_path, name="ManualPaks")
    result = pak_manager.resolve_paks_dir(str(app_root), ask_manual=lambda: good)
    assert result == good
    assert settings.load_paksdir(str(app_root)) == good


def test_resolve_paks_dir_rejects_invalid_manual_choice_and_retries(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir()
    monkeypatch.setattr(pak_manager, "auto_discover_paks_dir", lambda log=pak_manager._noop_log: None)
    bad = str(tmp_path / "empty_folder")
    os.makedirs(bad)
    good = _make_paks_dir(tmp_path, name="GoodPaks")
    choices = iter([bad, good])
    invalid_seen = []
    result = pak_manager.resolve_paks_dir(
        str(app_root),
        ask_manual=lambda: next(choices),
        on_invalid=invalid_seen.append,
    )
    assert result == good
    assert invalid_seen == [bad]


def test_resolve_paks_dir_manual_cancel_returns_none(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir()
    monkeypatch.setattr(pak_manager, "auto_discover_paks_dir", lambda log=pak_manager._noop_log: None)
    result = pak_manager.resolve_paks_dir(str(app_root), ask_manual=lambda: None)
    assert result is None
    assert settings.load_paksdir(str(app_root)) is None


def test_resolve_paks_dir_none_when_no_manual_fallback_given(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir()
    monkeypatch.setattr(pak_manager, "auto_discover_paks_dir", lambda log=pak_manager._noop_log: None)
    assert pak_manager.resolve_paks_dir(str(app_root)) is None


def test_paks_dir_quiet_does_not_persist_auto_discovery(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    app_root.mkdir()
    d = _make_paks_dir(tmp_path, name="QuietPaks")
    monkeypatch.setattr(pak_manager, "auto_discover_paks_dir", lambda log=pak_manager._noop_log: d)
    result = pak_manager.paks_dir_quiet(str(app_root))
    assert result == d
    assert settings.load_paksdir(str(app_root)) is None  # 書き込まれない


# ---------------------------------------------------------------------------
# ②SHA1照合ロジック
# ---------------------------------------------------------------------------

def test_sha1_file_matches_hashlib_reference(tmp_path):
    import hashlib

    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world" * 1000)
    expected = hashlib.sha1(p.read_bytes()).hexdigest()
    assert pak_manager.sha1_file(str(p)) == expected


def test_identify_applied_pak_finds_matching_candidate(tmp_path):
    target = tmp_path / "target.pak"
    target.write_bytes(b"same-content-xyz")
    match = tmp_path / "match.pak"
    match.write_bytes(b"same-content-xyz")
    other = tmp_path / "other.pak"
    other.write_bytes(b"different-content!!")

    candidates = [(str(other), "OtherAvatar"), (str(match), "MatchAvatar")]
    result = pak_manager.identify_applied_pak(
        str(target), os.path.getsize(str(target)), candidates
    )
    assert result == "MatchAvatar"


def test_identify_applied_pak_returns_none_when_no_size_match(tmp_path):
    target = tmp_path / "target.pak"
    target.write_bytes(b"12345")
    other = tmp_path / "other.pak"
    other.write_bytes(b"1234567890")
    result = pak_manager.identify_applied_pak(
        str(target), os.path.getsize(str(target)), [(str(other), "X")]
    )
    assert result is None


def test_identify_applied_pak_returns_none_when_same_size_different_hash(tmp_path):
    target = tmp_path / "target.pak"
    target.write_bytes(b"AAAAA")
    other = tmp_path / "other.pak"
    other.write_bytes(b"BBBBB")
    result = pak_manager.identify_applied_pak(
        str(target), os.path.getsize(str(target)), [(str(other), "X")]
    )
    assert result is None


def test_identify_applied_pak_skips_missing_candidate_file(tmp_path):
    target = tmp_path / "target.pak"
    target.write_bytes(b"AAAAA")
    missing = str(tmp_path / "gone.pak")
    result = pak_manager.identify_applied_pak(
        str(target), os.path.getsize(str(target)), [(missing, "X")]
    )
    assert result is None


# ---------------------------------------------------------------------------
# count_other_paks
# ---------------------------------------------------------------------------

def test_count_other_paks_excludes_self_and_vanilla_and_legacy(tmp_path):
    d = _make_paks_dir(tmp_path)
    (tmp_path / "Paks" / pak_manager.INSTALL_NAME).write_bytes(b"")
    (tmp_path / "Paks" / pak_manager.LEGACY_INSTALL_NAMES[0]).write_bytes(b"")
    (tmp_path / "Paks" / "SomeOtherMod_P.pak").write_bytes(b"")
    (tmp_path / "Paks" / "AnotherMod_P.pak").write_bytes(b"")
    assert pak_manager.count_other_paks(d) == 2


def test_count_other_paks_none_for_missing_dir(tmp_path):
    assert pak_manager.count_other_paks(str(tmp_path / "nope")) is None
    assert pak_manager.count_other_paks(None) is None


def test_count_other_paks_zero_when_only_self_present(tmp_path):
    d = _make_paks_dir(tmp_path)
    (tmp_path / "Paks" / pak_manager.INSTALL_NAME).write_bytes(b"")
    assert pak_manager.count_other_paks(d) == 0


# ---------------------------------------------------------------------------
# resolve_applied_target (legacy移行)
# ---------------------------------------------------------------------------

def test_resolve_applied_target_migrates_legacy_name(tmp_path):
    d = _make_paks_dir(tmp_path)
    legacy = os.path.join(d, pak_manager.LEGACY_INSTALL_NAMES[0])
    with open(legacy, "wb") as f:
        f.write(b"legacy-content")
    result = pak_manager.resolve_applied_target(d)
    assert result["exists"] is True
    assert result["target"] == os.path.join(d, pak_manager.INSTALL_NAME)
    assert os.path.isfile(result["target"])
    assert not os.path.isfile(legacy)
    assert result["remove_enabled"] is True


def test_resolve_applied_target_none_applied(tmp_path):
    d = _make_paks_dir(tmp_path)
    result = pak_manager.resolve_applied_target(d)
    assert result["exists"] is False
    assert result["remove_enabled"] is False


# ---------------------------------------------------------------------------
# apply_pak / remove_applied
# ---------------------------------------------------------------------------

def test_apply_pak_copies_and_removes_legacy_remnants(tmp_path):
    d = _make_paks_dir(tmp_path)
    src = tmp_path / "MyAvatar_PlayerSwap_P.pak"
    src.write_bytes(b"content")
    legacy = os.path.join(d, pak_manager.LEGACY_INSTALL_NAMES[1])
    with open(legacy, "wb") as f:
        f.write(b"old")

    target = pak_manager.apply_pak(d, str(src))
    assert target == os.path.join(d, pak_manager.INSTALL_NAME)
    assert os.path.isfile(target)
    with open(target, "rb") as f:
        assert f.read() == b"content"
    assert not os.path.isfile(legacy)


def test_apply_pak_raises_filenotfound_for_missing_src(tmp_path):
    d = _make_paks_dir(tmp_path)
    try:
        pak_manager.apply_pak(d, str(tmp_path / "missing.pak"))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_remove_applied_returns_false_when_nothing_applied(tmp_path):
    d = _make_paks_dir(tmp_path)
    assert pak_manager.remove_applied(d) is False


def test_remove_applied_removes_current_and_legacy(tmp_path):
    d = _make_paks_dir(tmp_path)
    with open(os.path.join(d, pak_manager.INSTALL_NAME), "wb") as f:
        f.write(b"x")
    with open(os.path.join(d, pak_manager.LEGACY_INSTALL_NAMES[0]), "wb") as f:
        f.write(b"y")
    assert pak_manager.remove_applied(d) is True
    assert not os.path.isfile(os.path.join(d, pak_manager.INSTALL_NAME))
    assert not os.path.isfile(os.path.join(d, pak_manager.LEGACY_INSTALL_NAMES[0]))


# ---------------------------------------------------------------------------
# list_built_paks
# ---------------------------------------------------------------------------

def test_list_built_paks_finds_playerswap_paks(tmp_path):
    work_root = tmp_path / "work"
    build_dir = work_root / "Alicia" / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "Alicia_PlayerSwap_P.pak").write_bytes(b"p")
    (build_dir / "ignored.txt").write_text("no")
    other_dir = work_root / "NoBuild"
    other_dir.mkdir()

    result = pak_manager.list_built_paks(str(work_root))
    assert len(result) == 1
    assert result[0][1] == "Alicia"
    assert result[0][0].endswith("Alicia_PlayerSwap_P.pak")


def test_list_built_paks_empty_for_missing_work_root(tmp_path):
    assert pak_manager.list_built_paks(str(tmp_path / "nope")) == []


# ---------------------------------------------------------------------------
# 削除系 (sanitize_name/resolve_delete_targets/delete_avatar_artifacts)
# ---------------------------------------------------------------------------

def test_sanitize_name_strips_non_alnum_ascii():
    assert pak_manager.sanitize_name("My Avatar_02!!") == "MyAvatar02"


def test_sanitize_name_empty_falls_back_to_avatar():
    assert pak_manager.sanitize_name("!!!") == "Avatar"
    assert pak_manager.sanitize_name("") == "Avatar"


def test_resolve_delete_targets_without_job_json(tmp_path):
    work_root = tmp_path / "work"
    build_dir = work_root / "Alicia" / "build"
    build_dir.mkdir(parents=True)
    pak = build_dir / "Alicia_PlayerSwap_P.pak"
    pak.write_bytes(b"p")

    result = pak_manager.resolve_delete_targets(str(work_root), str(tmp_path / "app"), str(pak))
    assert result["job_dir"] == str(work_root / "Alicia")
    assert result["ue_project_dir"] is None


def test_resolve_delete_targets_with_ue_project_inside_tool(tmp_path):
    app_root = tmp_path / "app"
    work_root = tmp_path / "work"
    job_dir = work_root / "Alicia"
    build_dir = job_dir / "build"
    build_dir.mkdir(parents=True)
    pak = build_dir / "Alicia_PlayerSwap_P.pak"
    pak.write_bytes(b"p")

    ue_project_avatar_dir = app_root / "ue_project" / "Alicia"
    ue_pal_dir = ue_project_avatar_dir / "Pal"
    ue_pal_dir.mkdir(parents=True)
    job_json = job_dir / "job.json"
    job_json.write_text(
        json.dumps({"ue_project": str(ue_pal_dir / "Alicia.uproject")}), encoding="utf-8"
    )

    result = pak_manager.resolve_delete_targets(str(work_root), str(app_root), str(pak))
    assert result["job_dir"] == str(job_dir)
    assert result["ue_project_dir"] == str(ue_project_avatar_dir)


def test_resolve_delete_targets_ignores_ue_project_outside_tool_root(tmp_path):
    app_root = tmp_path / "app"
    work_root = tmp_path / "work"
    job_dir = work_root / "Alicia"
    build_dir = job_dir / "build"
    build_dir.mkdir(parents=True)
    pak = build_dir / "Alicia_PlayerSwap_P.pak"
    pak.write_bytes(b"p")

    outside_dir = tmp_path / "SomewhereElse" / "Alicia" / "Pal"
    outside_dir.mkdir(parents=True)
    job_json = job_dir / "job.json"
    job_json.write_text(
        json.dumps({"ue_project": str(outside_dir / "Alicia.uproject")}), encoding="utf-8"
    )

    result = pak_manager.resolve_delete_targets(str(work_root), str(app_root), str(pak))
    assert result["ue_project_dir"] is None


def test_resolve_delete_targets_tolerates_malformed_job_json(tmp_path):
    app_root = tmp_path / "app"
    work_root = tmp_path / "work"
    job_dir = work_root / "Alicia"
    build_dir = job_dir / "build"
    build_dir.mkdir(parents=True)
    pak = build_dir / "Alicia_PlayerSwap_P.pak"
    pak.write_bytes(b"p")
    (job_dir / "job.json").write_text("{not valid json", encoding="utf-8")

    result = pak_manager.resolve_delete_targets(str(work_root), str(app_root), str(pak))
    assert result["ue_project_dir"] is None


def test_delete_avatar_artifacts_removes_job_and_ue_project_dirs(tmp_path):
    job_dir = tmp_path / "work" / "Alicia"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text("{}", encoding="utf-8")
    ue_dir = tmp_path / "ue_project" / "Alicia"
    ue_dir.mkdir(parents=True)

    pak_manager.delete_avatar_artifacts(str(job_dir), str(ue_dir))
    assert not os.path.isdir(job_dir)
    assert not os.path.isdir(ue_dir)


def test_delete_avatar_artifacts_ignores_missing_dirs(tmp_path):
    # 例外を投げずに終わることだけを確認(冪等性)
    pak_manager.delete_avatar_artifacts(str(tmp_path / "nope"), str(tmp_path / "nope2"))


# ---------------------------------------------------------------------------
# is_game_running (実プロセス依存部分は例外握りつぶしのみ確認)
# ---------------------------------------------------------------------------

def test_is_game_running_returns_bool_and_does_not_raise():
    # 実行環境にPalworldが起動しているとは限らないため、型と非例外のみ検証する
    assert isinstance(pak_manager.is_game_running(), bool)
