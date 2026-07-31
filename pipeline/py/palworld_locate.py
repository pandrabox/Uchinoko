# -*- coding: utf-8 -*-
"""Palworldインストール先の探索(公開issue #8対応)。

背景: これまで「バニラ抽出」「Mod適用」の双方が
C:\\Program Files (x86)\\Steam\\steamapps\\common\\Palworld という決め打ちパスに
依存しており、Palworldが別ドライブのSteamライブラリへインストールされている
環境では変換前の時点で失敗していた(無言でC:相当へフォールバックする箇所も
あり、真因と無関係な内部パスのエラーになるケースもあった)。

本モジュールは「Palworldがどこにあるか」を解決する**唯一の場所**にする
(入口で正規化、特別扱いを積まない方針)。優先順位:

  1. 明示指定(呼び出し側が持つ既存の設定: job.jsonのpaths.palworld_pak /
     GUIのsettings_paksdir.txt / 環境変数など)。本モジュールへは呼び出し側が
     `explicit_*` 引数として渡す。ここが最優先。
  2. Steamレジストリ(HKCU\\Software\\Valve\\Steam の SteamPath/InstallPath、
     見つからなければHKLM側)からSteamのインストールルートを特定し、
     `<root>\\steamapps\\libraryfolders.vdf` を読んで登録済み全ライブラリを
     列挙、各ライブラリの `steamapps\\common\\Palworld` を確認する。
  3. 既定パス(従来の決め打ち値)を最後の保険として試す。

どこにも見つからなければ `PalworldNotFoundError` を送出する。**無言で
どれかのパスにフォールバックすることはしない** — 呼び出し側が
「探した場所」を含む文言をそのままユーザーに見せられるようにする
(問い合わせ対応は「ログをコピー」の中身だけが頼りのため)。

標準ライブラリのみ使用(pip禁止。Blender同梱PythonでもシステムPythonでも
動かすため。vp_core.pyと同じ制約)。
"""

import os
import re

APP_ID = "1623730"  # SteamのPalworld appid
INSTALL_SUBPATH = os.path.join("steamapps", "common", "Palworld")
PAK_REL = os.path.join("Pal", "Content", "Paks", "Pal-Windows.pak")
PAKS_DIR_REL = os.path.join("Pal", "Content", "Paks")

# 従来からの決め打ち値。レジストリ/vdf探索が失敗したときの最後の保険として
# 引き続き候補に含める(Steamが無いだけの環境や、探索が使えない場合の後方互換)。
DEFAULT_STEAM_ROOTS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
)


class PalworldNotFoundError(RuntimeError):
    """Palworldのインストール先(またはpak本体)がどこにも見つからなかった。

    .searched に「探した場所」の一覧を保持する。メッセージ自体も
    「ログをコピー」だけで遠隔診断できる文言にしてある。
    """

    def __init__(self, searched, note=None):
        self.searched = list(searched)
        lines = ["Palworld was not found. Locations searched:"]
        lines.extend("  - " + s for s in self.searched)
        if note:
            lines.append(note)
        super().__init__("\n".join(lines))


def _normalize(path):
    return os.path.normpath(path) if path else path


def registry_steam_roots():
    """レジストリからSteamのインストールルート候補を探す。

    Windows以外(winregが無い)・レジストリキーが無い・値が読めない、
    いずれの場合も例外を投げず空リストを返す(探索の一段に過ぎないため)。
    """
    roots = []
    try:
        import winreg
    except ImportError:
        return roots

    candidates = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam",
         ("SteamPath", "InstallPath")),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam",
         ("InstallPath",)),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam",
         ("InstallPath",)),
    )
    for hive, subkey, value_names in candidates:
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            continue
        try:
            for name in value_names:
                try:
                    val, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if val:
                    roots.append(_normalize(val))
        finally:
            key.Close()
    return roots


def parse_libraryfolders_vdf(vdf_path):
    """Steamの`libraryfolders.vdf`から各ライブラリの"path"値を素朴に抜き出す。

    KeyValues形式の完全パーサは不要(pathの値さえ拾えれば、実在確認は
    ファイルシステム側に委ねられるため)。ファイルが無い/読めない場合は
    空リストを返す(致命的エラーにしない)。
    """
    if not vdf_path or not os.path.isfile(vdf_path):
        return []
    try:
        with open(vdf_path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return []
    raw_paths = re.findall(r'"path"\s*"([^"]*)"', text)
    out = []
    for p in raw_paths:
        p = p.replace("\\\\", "\\")
        if p:
            out.append(_normalize(p))
    return out


def _dedup_preserve_order(items):
    seen = set()
    out = []
    for item in items:
        if not item:
            continue
        key = os.path.normcase(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def steam_library_roots(steam_roots):
    """Steamルート群から、そのライブラリ(vdf記載分+ルート自身)を集める。"""
    libs = []
    for root in steam_roots:
        if not root:
            continue
        libs.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        libs.extend(parse_libraryfolders_vdf(vdf))
    return _dedup_preserve_order(libs)


def _install_dir_has_pak(install_dir):
    """フォルダの実在だけでなく、バニラ抽出が実際に読む本体pak
    (Pal\\Content\\Paks\\Pal-Windows.pak)まで実在するかを確認する。

    2026-07-27 コーディネータ追加要件: 「フォルダが見つかった」で解決済み
    扱いにすると、移動済み/アンインストール後の空フォルダや、途中までしか
    無い壊れたインストールに乗ってしまい、結局そのあとの工程で失敗する。
    フォルダはあるがpakが無い場合も「未解決」として扱い、次の候補を探す。
    """
    if not install_dir or not os.path.isdir(install_dir):
        return False
    return os.path.isfile(os.path.join(install_dir, PAK_REL))


def find_palworld_install_dir(explicit=None, steam_roots=None):
    """Palworldのインストールディレクトリ(末尾が...\\Palworldなフォルダ)を解決する。

    「フォルダの実在」だけでなく、本体pak(Pal\\Content\\Paks\\Pal-Windows.pak)の
    実在まで確認できて初めて解決済みとする(フォルダだけあってpakが無い場合は
    次の候補へ進む。それでも無ければ未解決としてエラーにする)。

    explicit: 呼び出し側が既に持っている明示指定(pakまで実在すれば最優先で採用)。
    steam_roots: Noneなら実環境からレジストリ+既定値で組み立てる。
                 テストではここに模擬ライブラリ群を渡して差し替える。

    見つからなければ PalworldNotFoundError(探した場所つき)を送出する。
    """
    searched = []

    if explicit:
        searched.append(_normalize(explicit))
        if _install_dir_has_pak(explicit):
            return _normalize(explicit)

    roots = steam_roots
    if roots is None:
        roots = registry_steam_roots() + list(DEFAULT_STEAM_ROOTS)
    roots = _dedup_preserve_order(roots)

    for lib in steam_library_roots(roots):
        cand = os.path.join(lib, INSTALL_SUBPATH)
        searched.append(cand)
        if _install_dir_has_pak(cand):
            return _normalize(cand)

    raise PalworldNotFoundError(searched)


def find_palworld_pak(explicit=None, explicit_install_dir=None, steam_roots=None):
    """Pal-Windows.pak本体のフルパスを解決する(バニラ抽出用)。

    explicit: pak本体への明示指定パス(job.jsonのpaths.palworld_pak相当)。
              存在すれば最優先。
    explicit_install_dir: インストールディレクトリの明示指定(explicitが
              無いとき、探索よりこちらを優先する)。
    """
    searched = []

    if explicit:
        searched.append(_normalize(explicit))
        if os.path.isfile(explicit):
            return _normalize(explicit)

    try:
        install_dir = find_palworld_install_dir(
            explicit=explicit_install_dir, steam_roots=steam_roots)
    except PalworldNotFoundError as e:
        searched.extend(e.searched)
        raise PalworldNotFoundError(searched)

    pak = os.path.join(install_dir, PAK_REL)
    searched.append(pak)
    if os.path.isfile(pak):
        return _normalize(pak)
    raise PalworldNotFoundError(searched)


def find_palworld_paks_dir(explicit=None, steam_roots=None):
    """適用先のPaksフォルダ(<Palworld>\\Pal\\Content\\Paks)を解決する(Mod適用用)。

    explicit: Paksフォルダそのものの明示指定(GUIのsettings_paksdir.txt相当)。
              存在すれば最優先。
    """
    searched = []
    if explicit:
        searched.append(_normalize(explicit))
        if os.path.isdir(explicit):
            return _normalize(explicit)

    try:
        install_dir = find_palworld_install_dir(steam_roots=steam_roots)
    except PalworldNotFoundError as e:
        searched.extend(e.searched)
        raise PalworldNotFoundError(searched)

    paks = os.path.join(install_dir, PAKS_DIR_REL)
    searched.append(paks)
    if os.path.isdir(paks):
        return _normalize(paks)
    raise PalworldNotFoundError(searched)


if __name__ == "__main__":
    # 手動確認用: python palworld_locate.py
    try:
        print("install_dir:", find_palworld_install_dir())
    except PalworldNotFoundError as e:
        print(e)
    try:
        print("pak:", find_palworld_pak())
    except PalworldNotFoundError as e:
        print(e)
    try:
        print("paks_dir:", find_palworld_paks_dir())
    except PalworldNotFoundError as e:
        print(e)
