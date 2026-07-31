# -*- coding: utf-8 -*-
r"""dev#231(release.py 共有フォルダ配置、2026-07-30オーナー指示)の受入試験。

オーナー指示: 「(\\osaki-shoukai\C\OsakiShoukai\Uchinoko に配布物を)置くのを
release.pyのバッチ処理に組み込んでおく」。CLAUDE.md「受入試験はリリースゲート
に任せる」原則により、この変更はpak不変(Layers-Affected: none)のため、
本試験は単体テスト+負の対照のみで受入とする(実共有フォルダへは一切
書き込まない。すべて一時ディレクトリで代替する)。

対象の負の対照(コーディネータ指示どおり3点):
  1. 存在する宛先 -> 配布zip・BOOTH草稿の2ファイルを配置し、共有上の
     BOOTH_PASTE.txt(人間校正の正本)を上書きしない
  2. 宛先不在(到達不能) -> WARNのみでリリースのrcには影響しない構造
     (run_share_copy自体は例外を投げず、ok=Falseを返すだけ)
  3. --no-share-copy指定 -> 共有配置ステップ自体をスキップする(ログに残す)

追加の負の対照(2026-07-30 コーディネータ追加指示「古いzip削除」):
  4. コピー失敗時は古いzipを削除しない(コピー成功確認後にのみ削除する)

実行: python -m pytest tests\shipcheck\test_release_share_copy.py -v
"""
import importlib
import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
TESTS_RELGATE = os.path.join(REPO, "tests", "relgate")

for p in (DEVTOOLS, TESTS_RELGATE):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_release():
    return importlib.import_module("release")


class DummyReport:
    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)

    def joined(self):
        return "\n".join(self.lines)


def _make_zip(path, content=b"dummy-zip-bytes"):
    with open(path, "wb") as f:
        f.write(content)
    return path


# =====================================================================
# resolve_share_dir: 優先順位(CLI > 環境変数 > 既定値)
# =====================================================================

def test_resolve_share_dir_uses_cli_value_when_given(monkeypatch):
    release = _import_release()
    monkeypatch.delenv("D2P_SHARE_DIR", raising=False)
    assert release.resolve_share_dir(r"\\cli\share") == r"\\cli\share"


def test_resolve_share_dir_falls_back_to_env_var(monkeypatch):
    release = _import_release()
    monkeypatch.setenv("D2P_SHARE_DIR", r"\\env\share")
    assert release.resolve_share_dir(None) == r"\\env\share"


def test_resolve_share_dir_falls_back_to_hardcoded_default(monkeypatch):
    release = _import_release()
    monkeypatch.delenv("D2P_SHARE_DIR", raising=False)
    assert release.resolve_share_dir(None) == release.SHARE_DIR_DEFAULT


# =====================================================================
# share_copy_disabled: --no-share-copy / D2P_NO_SHARE_COPY のどちらでも無効化
# =====================================================================

def test_share_copy_disabled_by_cli_flag(monkeypatch):
    release = _import_release()
    monkeypatch.delenv("D2P_NO_SHARE_COPY", raising=False)
    assert release.share_copy_disabled(True) is True


def test_share_copy_disabled_by_env_var(monkeypatch):
    release = _import_release()
    monkeypatch.setenv("D2P_NO_SHARE_COPY", "1")
    assert release.share_copy_disabled(False) is True


def test_share_copy_enabled_by_default(monkeypatch):
    release = _import_release()
    monkeypatch.delenv("D2P_NO_SHARE_COPY", raising=False)
    assert release.share_copy_disabled(False) is False


# =====================================================================
# find_stale_share_zips: zip以外・現行版は対象外
# =====================================================================

def test_find_stale_share_zips_excludes_current_and_non_zip(tmp_path):
    release = _import_release()
    (tmp_path / "Uchinoko_for_Palworld_v1.0.0_full.zip").write_bytes(b"old1")
    (tmp_path / "Uchinoko_for_Palworld_v2.0.0_full.zip").write_bytes(b"old2")
    (tmp_path / "Uchinoko_for_Palworld_v9.9.9_full.zip").write_bytes(b"current")
    (tmp_path / "BOOTH_PASTE.txt").write_text("master", encoding="utf-8")
    (tmp_path / "BOOTH_PASTE_v9.9.9_draft.txt").write_text("draft", encoding="utf-8")
    (tmp_path / "screenshot.png").write_bytes(b"\x89PNG")

    stale = release.find_stale_share_zips(str(tmp_path), "Uchinoko_for_Palworld_v9.9.9_full.zip")
    stale_names = sorted(os.path.basename(p) for p in stale)
    assert stale_names == [
        "Uchinoko_for_Palworld_v1.0.0_full.zip",
        "Uchinoko_for_Palworld_v2.0.0_full.zip",
    ]


# =====================================================================
# run_share_copy: 正の対照(存在する宛先) -- 2ファイル配置・正本非上書き・
# 古いzip掃除
# =====================================================================

def test_run_share_copy_places_zip_and_booth_draft_without_touching_master(tmp_path, monkeypatch):
    release = _import_release()

    # 配布zip(コピー元)
    src_zip_dir = tmp_path / "dist_src"
    src_zip_dir.mkdir()
    src_zip = _make_zip(str(src_zip_dir / "Uchinoko_for_Palworld_v9.9.9_full.zip"), b"real-zip")

    # BOOTH原稿(コピー元)を
    # booth_notes_path()が指す実パスへ差し替える(REPO_ROOTを汚さないため
    # booth_notes_path自体をmonkeypatchする)。
    notes_src = tmp_path / "v9.9.9_booth.txt"
    notes_src.write_text("BOOTH原稿の中身", encoding="utf-8")
    monkeypatch.setattr(release, "booth_notes_path", lambda version: str(notes_src))

    # 共有先(存在する宛先)。事前に正本と古いzipを置いておく。
    share_dir = tmp_path / "share"
    share_dir.mkdir()
    master = share_dir / release.BOOTH_PASTE_MASTER_FILENAME
    master.write_text("人間校正済みの正本、絶対に変わらない", encoding="utf-8")
    master_mtime_before = master.stat().st_mtime_ns
    stale_zip = share_dir / "Uchinoko_for_Palworld_v1.0.0_full.zip"
    stale_zip.write_bytes(b"old")

    report = DummyReport()
    result = release.run_share_copy(src_zip, "v9.9.9", str(share_dir), report)

    # 1. 配布zipが配置された
    dest_zip = share_dir / "Uchinoko_for_Palworld_v9.9.9_full.zip"
    assert dest_zip.is_file()
    assert dest_zip.read_bytes() == b"real-zip"
    assert result["zip_copy"]["ok"] is True

    # 2. BOOTH草稿が別名で配置された
    dest_draft = share_dir / "BOOTH_PASTE_v9.9.9_draft.txt"
    assert dest_draft.is_file()
    assert dest_draft.read_text(encoding="utf-8") == "BOOTH原稿の中身"
    assert result["booth_copy"]["ok"] is True

    # 3. 正本(BOOTH_PASTE.txt)は一切変更されていない
    assert master.read_text(encoding="utf-8") == "人間校正済みの正本、絶対に変わらない"
    assert master.stat().st_mtime_ns == master_mtime_before

    # 4. 古いzipはコピー成功後に削除された
    assert not stale_zip.exists()
    assert str(stale_zip) in result["stale_zip_cleanup"]["removed"]

    # 三点セット(試行・成否・コピー先)がログに残っている
    joined = report.joined()
    assert str(dest_zip) in joined
    assert str(dest_draft) in joined
    assert str(stale_zip) in joined


def test_run_share_copy_skips_booth_draft_when_notes_file_missing(tmp_path, monkeypatch):
    release = _import_release()
    src_zip = _make_zip(str(tmp_path / "Uchinoko_for_Palworld_v9.9.9_full.zip"))
    monkeypatch.setattr(release, "booth_notes_path",
                         lambda version: str(tmp_path / "does_not_exist_booth.txt"))
    share_dir = tmp_path / "share2"
    share_dir.mkdir()

    report = DummyReport()
    result = release.run_share_copy(src_zip, "v9.9.9", str(share_dir), report)

    assert result["zip_copy"]["ok"] is True
    assert result["booth_copy"]["attempted"] is False
    assert result["booth_copy"]["ok"] is False
    assert not (share_dir / "BOOTH_PASTE_v9.9.9_draft.txt").exists()


# =====================================================================
# run_share_copy: 負の対照(宛先不在/到達不能) -- WARNのみ、例外を投げない、
# 古いzipも削除されない
# =====================================================================

def test_run_share_copy_unreachable_destination_warns_without_raising(tmp_path, monkeypatch):
    """負の対照2: 共有に到達できない(コピー自体が失敗する)場合でも、
    run_share_copy()は例外を投げずok=Falseを返すだけ(呼び出し元のrcには
    一切影響しない構造であることの直接の根拠)。"""
    release = _import_release()
    src_zip = _make_zip(str(tmp_path / "Uchinoko_for_Palworld_v9.9.9_full.zip"))

    def fail_copy2(_src, _dst):
        raise OSError(53, "The network path was not found")

    monkeypatch.setattr(release.shutil, "copy2", fail_copy2)

    # 到達不能を模すため、実際には存在しない/作れない想定の共有パス文字列を渡す
    # (copy2自体をmonkeypatchで確実に失敗させているので、os.makedirsが通っても
    # 問題ない)。
    share_dir = tmp_path / "unreachable_share"

    report = DummyReport()
    result = release.run_share_copy(src_zip, "v9.9.9", str(share_dir), report)

    assert result["zip_copy"]["ok"] is False
    assert "network path" in result["zip_copy"]["detail"].lower()
    # コピー失敗時はBOOTH草稿・古いzip削除のいずれにも到達していない
    assert result["booth_copy"]["attempted"] is False
    assert result["stale_zip_cleanup"]["attempted"] is False
    assert "WARN" in report.joined()


def test_run_share_copy_negative_copy_failure_does_not_delete_stale_zip(tmp_path, monkeypatch):
    """負の対照4(2026-07-30追加指示): コピー失敗時は既存の古いzipを一切
    削除しない。「コピー成功確認後にのみ削除する」の直接の証拠。"""
    release = _import_release()
    src_zip = _make_zip(str(tmp_path / "Uchinoko_for_Palworld_v9.9.9_full.zip"))

    share_dir = tmp_path / "share3"
    share_dir.mkdir()
    stale_zip = share_dir / "Uchinoko_for_Palworld_v1.0.0_full.zip"
    stale_zip.write_bytes(b"old-must-survive")

    def fail_copy2(_src, _dst):
        raise OSError(5, "Access is denied")

    monkeypatch.setattr(release.shutil, "copy2", fail_copy2)

    report = DummyReport()
    result = release.run_share_copy(src_zip, "v9.9.9", str(share_dir), report)

    assert result["zip_copy"]["ok"] is False
    assert result["stale_zip_cleanup"]["attempted"] is False
    assert result["stale_zip_cleanup"]["removed"] == []
    # 古いzipは物理的にまだ存在する
    assert stale_zip.is_file()
    assert stale_zip.read_bytes() == b"old-must-survive"


# =====================================================================
# run_share_copy_step: main()から呼ぶラッパ(--no-share-copy / 有効時の解決)
# =====================================================================

def test_run_share_copy_step_skips_and_logs_when_cli_flag_set(monkeypatch):
    """負の対照3: --no-share-copy指定時は run_share_copy() を一切呼ばず、
    スキップした旨をログへ残す。"""
    release = _import_release()
    monkeypatch.delenv("D2P_NO_SHARE_COPY", raising=False)

    def boom(*a, **kw):
        raise AssertionError("run_share_copy が呼ばれてはならない(--no-share-copy時)")

    monkeypatch.setattr(release, "run_share_copy", boom)

    args = SimpleNamespace(no_share_copy=True, share_dir=None)
    report = DummyReport()
    result = release.run_share_copy_step("dummy.zip", "v9.9.9", args, report)

    assert result == {"attempted": False, "reason": "disabled"}
    assert any("スキップ" in line for line in report.lines)


def test_run_share_copy_step_skips_via_env_var(monkeypatch):
    release = _import_release()
    monkeypatch.setenv("D2P_NO_SHARE_COPY", "1")

    def boom(*a, **kw):
        raise AssertionError("run_share_copy が呼ばれてはならない(env var無効化時)")

    monkeypatch.setattr(release, "run_share_copy", boom)

    args = SimpleNamespace(no_share_copy=False, share_dir=None)
    report = DummyReport()
    result = release.run_share_copy_step("dummy.zip", "v9.9.9", args, report)

    assert result == {"attempted": False, "reason": "disabled"}


def test_run_share_copy_step_calls_run_share_copy_with_resolved_dir(monkeypatch):
    """正の対照: 無効化されていなければ、resolve_share_dir()で解決した宛先で
    run_share_copy()を呼ぶ。"""
    release = _import_release()
    monkeypatch.delenv("D2P_NO_SHARE_COPY", raising=False)
    monkeypatch.delenv("D2P_SHARE_DIR", raising=False)

    captured = {}

    def fake_run_share_copy(zip_path, new_version, share_dir, report):
        captured.update(zip_path=zip_path, new_version=new_version, share_dir=share_dir)
        return {"attempted": True, "fake": True}

    monkeypatch.setattr(release, "run_share_copy", fake_run_share_copy)

    args = SimpleNamespace(no_share_copy=False, share_dir=r"\\explicit\share")
    report = DummyReport()
    result = release.run_share_copy_step("dummy.zip", "v9.9.9", args, report)

    assert result == {"attempted": True, "fake": True}
    assert captured == {
        "zip_path": "dummy.zip",
        "new_version": "v9.9.9",
        "share_dir": r"\\explicit\share",
    }


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
