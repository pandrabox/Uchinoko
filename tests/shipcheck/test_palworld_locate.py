# -*- coding: utf-8 -*-
"""単体テスト: palworld_locate.py(公開issue #8 WP16)。

一時ディレクトリに模擬Steamライブラリ構成(C:相当のライブラリ+別ドライブ相当の
追加ライブラリ、libraryfolders.vdf付き)を作り、探索ロジックが正しく解決できる
ことを確認する。**負の対照**として、
  - C:相当には無く別ライブラリ側にだけある構成でも正しく解決できること
  - どこにも無い構成では明示エラー(PalworldNotFoundError)になり、
    無言でフォールバックしないこと
の両方を確認する。

実レジストリ・実Steamには一切触れない(steam_roots引数で差し替える)。
pytestからも `python tests/shipcheck/test_palworld_locate.py` からも
実行できるよう、フィクスチャに依存せず素朴なtempfileで書く。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
if PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_PY_DIR)

import palworld_locate as pl  # noqa: E402


def _make_library(root, with_palworld, folder_only=False):
    """<root>を1つのSteamライブラリとして作る。

    with_palworld=True かつ folder_only=True: Palworldのフォルダ構造(Paksまで)は
    あるが本体pak(Pal-Windows.pak)は無い(移動済み/壊れたインストールの模擬。
    2026-07-27コーディネータ追加要件の負の対照用)。
    """
    os.makedirs(root, exist_ok=True)
    if with_palworld:
        paks = os.path.join(root, "steamapps", "common", "Palworld",
                             "Pal", "Content", "Paks")
        os.makedirs(paks, exist_ok=True)
        if not folder_only:
            with open(os.path.join(paks, "Pal-Windows.pak"), "wb") as f:
                f.write(b"dummy")
    else:
        os.makedirs(os.path.join(root, "steamapps"), exist_ok=True)


def _write_libraryfolders_vdf(steam_root, extra_library_paths):
    """steam_root配下にlibraryfolders.vdfを書く(extra_library_pathsを"path"として列挙)。
    実際のフォーマットを簡略化しているが、本モジュールのパーサは"path"の値だけを
    正規表現で拾う設計なので、これで十分な模擬になる。"""
    vdf_dir = os.path.join(steam_root, "steamapps")
    os.makedirs(vdf_dir, exist_ok=True)
    lines = ['"libraryfolders"', "{"]
    for i, p in enumerate(extra_library_paths):
        escaped = p.replace("\\", "\\\\")
        lines.append('\t"{}"'.format(i))
        lines.append("\t{")
        lines.append('\t\t"path"\t\t"{}"'.format(escaped))
        lines.append('\t\t"apps"')
        lines.append("\t\t{")
        lines.append('\t\t\t"{}"\t\t"1"'.format(pl.APP_ID))
        lines.append("\t\t}")
        lines.append("\t}")
    lines.append("}")
    with open(os.path.join(vdf_dir, "libraryfolders.vdf"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def test_found_in_default_c_library():
    """C:相当のライブラリ直下にPalworldがある通常構成。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")
        _make_library(c_root, with_palworld=True)
        _write_libraryfolders_vdf(c_root, [c_root])

        install_dir = pl.find_palworld_install_dir(steam_roots=[c_root])
        assert install_dir.lower() == os.path.normpath(
            os.path.join(c_root, "steamapps", "common", "Palworld")).lower()

        pak = pl.find_palworld_pak(steam_roots=[c_root])
        assert os.path.isfile(pak)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_negative_found_only_in_other_drive_library():
    """負の対照その1: C:相当には無く、別ドライブ相当のライブラリにだけある構成。
    libraryfolders.vdf経由で解決できることを確認する(単純にデフォルトパスへ
    フォールバックするだけの実装だと、この対照は失敗するはず)。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")            # Palworld無し
        d_root = os.path.join(tmp, "D_SteamLibrary")      # Palworldあり(別ドライブ相当)
        _make_library(c_root, with_palworld=False)
        _make_library(d_root, with_palworld=True)
        _write_libraryfolders_vdf(c_root, [c_root, d_root])

        install_dir = pl.find_palworld_install_dir(steam_roots=[c_root])
        assert install_dir.lower() == os.path.normpath(
            os.path.join(d_root, "steamapps", "common", "Palworld")).lower()

        pak = pl.find_palworld_pak(steam_roots=[c_root])
        assert os.path.isfile(pak)
        assert d_root.lower() in pak.lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_negative_not_found_anywhere_raises_explicit_error():
    """負の対照その2: どこにも無い構成では、無言でフォールバックせず
    PalworldNotFoundError(探した場所つき)を送出すること。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")
        d_root = os.path.join(tmp, "D_SteamLibrary")
        _make_library(c_root, with_palworld=False)
        _make_library(d_root, with_palworld=False)
        _write_libraryfolders_vdf(c_root, [c_root, d_root])

        raised = False
        try:
            pl.find_palworld_install_dir(steam_roots=[c_root])
        except pl.PalworldNotFoundError as e:
            raised = True
            assert len(e.searched) >= 2
            assert "Palworld was not found" in str(e)
        assert raised, "PalworldNotFoundErrorが送出されなかった(無言フォールバックの疑い)"

        raised = False
        try:
            pl.find_palworld_pak(steam_roots=[c_root])
        except pl.PalworldNotFoundError:
            raised = True
        assert raised
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_folder_exists_but_pak_missing_is_unresolved():
    """2026-07-27追加要件: 「フォルダが見つかった」だけでは解決済みにしない。
    C:相当にはPalworldのフォルダ構造だけあってpak本体が無く(移動済み/壊れた
    インストールの模擬)、別ドライブ相当にだけ本物のpakがある構成で、
    ちゃんと別ドライブ側まで探しに行って解決できることを確認する。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")             # フォルダはあるがpak無し
        d_root = os.path.join(tmp, "D_SteamLibrary")       # 本物のpakあり
        _make_library(c_root, with_palworld=True, folder_only=True)
        _make_library(d_root, with_palworld=True)
        _write_libraryfolders_vdf(c_root, [c_root, d_root])

        install_dir = pl.find_palworld_install_dir(steam_roots=[c_root])
        assert install_dir.lower() == os.path.normpath(
            os.path.join(d_root, "steamapps", "common", "Palworld")).lower()

        pak = pl.find_palworld_pak(steam_roots=[c_root])
        assert os.path.isfile(pak)
        assert d_root.lower() in pak.lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_folder_exists_everywhere_but_pak_missing_raises():
    """フォルダはあるがpakがどこにも無い構成では、フォルダの実在だけで
    解決済みと誤認せず、明示エラーを送出すること。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")
        _make_library(c_root, with_palworld=True, folder_only=True)
        _write_libraryfolders_vdf(c_root, [c_root])

        raised = False
        try:
            pl.find_palworld_install_dir(steam_roots=[c_root])
        except pl.PalworldNotFoundError:
            raised = True
        assert raised, "フォルダだけの存在で誤って解決済み扱いになっている"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_explicit_override_takes_priority():
    """明示指定(explicit)がpakまで実在すれば、Steam探索より優先されること。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")
        _make_library(c_root, with_palworld=True)  # 探索側にも別の実在install
        override_dir = os.path.join(tmp, "custom_palworld_install")
        override_paks = os.path.join(override_dir, "Pal", "Content", "Paks")
        os.makedirs(override_paks, exist_ok=True)
        with open(os.path.join(override_paks, "Pal-Windows.pak"), "wb") as f:
            f.write(b"dummy")

        install_dir = pl.find_palworld_install_dir(
            explicit=override_dir, steam_roots=[c_root])
        assert install_dir.lower() == os.path.normpath(override_dir).lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_explicit_override_without_pak_falls_through_to_search():
    """明示指定(explicit)のフォルダにpakが無ければ、それだけで解決済みに
    せず、Steam探索側へフォールバックすること(2026-07-27追加要件)。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")
        _make_library(c_root, with_palworld=True)
        override_dir = os.path.join(tmp, "custom_palworld_install_empty")
        os.makedirs(override_dir, exist_ok=True)  # フォルダのみ、pak無し

        install_dir = pl.find_palworld_install_dir(
            explicit=override_dir, steam_roots=[c_root])
        assert install_dir.lower() == os.path.normpath(
            os.path.join(c_root, "steamapps", "common", "Palworld")).lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_explicit_pak_missing_falls_through_to_search():
    """明示pakパスが実在しない場合は、探索側にフォールバックすること
    (job.jsonの明示指定が古くなっている/未設定のケースを想定)。"""
    tmp = tempfile.mkdtemp(prefix="d2p_locate_")
    try:
        c_root = os.path.join(tmp, "C_Steam")
        _make_library(c_root, with_palworld=True)
        missing_explicit = os.path.join(tmp, "does_not_exist", "Pal-Windows.pak")

        pak = pl.find_palworld_pak(explicit=missing_explicit, steam_roots=[c_root])
        assert os.path.isfile(pak)
        assert missing_explicit.lower() not in pak.lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_TESTS = [
    test_found_in_default_c_library,
    test_negative_found_only_in_other_drive_library,
    test_negative_not_found_anywhere_raises_explicit_error,
    test_folder_exists_but_pak_missing_is_unresolved,
    test_folder_exists_everywhere_but_pak_missing_raises,
    test_explicit_override_takes_priority,
    test_explicit_override_without_pak_falls_through_to_search,
    test_explicit_pak_missing_falls_through_to_search,
]


if __name__ == "__main__":
    failures = []
    for t in _TESTS:
        try:
            t()
            print("PASS: {}".format(t.__name__))
        except Exception as e:  # noqa: BLE001
            failures.append(t.__name__)
            print("FAIL: {}: {}".format(t.__name__, e))
    if failures:
        print("\n{} failed: {}".format(len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall {} tests passed".format(len(_TESTS)))
