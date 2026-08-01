# settings.py -- appRoot直下の平文設定ファイル4種の読み書き(DESIGN.md §2.8)。
#
# 移植元: app\DiveToPalworld.cs の以下4箇所(いずれも「appRoot直下の平テキスト、
# UTF-8 BOM無し、読み込み時Trim()」という同じ流儀。DESIGN.md §2.8表そのもの):
#   - settings_language.txt  : LanguageSettingFile/DetermineInitialLang/SaveLanguageSetting
#                               (L.809-837)
#   - settings_lastvrm.txt   : LastVrmFile (L.1464, 書き込みはL.1581)
#   - settings_autoapply.txt : AutoApplyFile/LoadAutoApply/SaveAutoApply (L.1470-1488)
#   - settings_paksdir.txt   : PaksDir内(L.3078-3115)
#
# job.json(アバターごとの変換設定、DESIGN.md §2.1のスキーマ)はここでは扱わない。
# WP-A1の書き込み許可行(DESIGN.md §5.2)が「settings.pyは§2.8の4ファイル」と
# 明示しており、job.jsonの生成はWriteJob()相当のロジック(pipeline_runner.py、
# WP-A2)側に置くのが自然なため(DESIGN.md §4.1でもpipeline_runner.pyの担当に
# WriteJobが挙げられている)。この切り分けはWP-A1側の合理的解釈である。

from __future__ import annotations

import os
from typing import Optional

_LANGUAGE_FILE = "settings_language.txt"
_LASTVRM_FILE = "settings_lastvrm.txt"
_AUTOAPPLY_FILE = "settings_autoapply.txt"
_PAKSDIR_FILE = "settings_paksdir.txt"


def _path(app_root: str, filename: str) -> str:
    return os.path.join(app_root, filename)


def _read_text(path: str) -> Optional[str]:
    """File.ReadAllText(...).Trim() 相当。存在しない/読めない場合はNone
    (C#側は例外を握りつぶして既定値へフォールバックする設計、L.819-829・
    L.1474-1480等と同じ方針をそのまま踏襲)。"""
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _write_text(path: str, text: str) -> None:
    """File.WriteAllText(path, text, new UTF8Encoding(false)) 相当
    (BOM無しUTF-8)。書き込み失敗はC#側同様に握りつぶす(設定の保存に失敗しても
    画面を止めない、というアプリ全体の設計方針、L.836・L.1487等)。"""
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# settings_language.txt (LangToCode/TryParseLangCode L.784-807)
# 保存されるコードはハイフン入り("zh-TW"/"zh-CN")。内部辞書キー(zhTW/zhCN)との
# 変換は i18n.py の FILE_LANG_CODES / FILE_CODE_TO_LANG を使う。
# ---------------------------------------------------------------------------

def language_file(app_root: str) -> str:
    return _path(app_root, _LANGUAGE_FILE)


def load_language_code(app_root: str) -> Optional[str]:
    """保存済みの言語コード(ディスク表記、例 "zh-TW")を返す。無ければNone
    (呼び出し側がOSロケール判定へフォールバックする、DetermineInitialLang
    L.817-831と同じ役割分担)。"""
    return _read_text(language_file(app_root))


def save_language_code(app_root: str, lang_code: str) -> None:
    """SaveLanguageSetting(L.833-837)相当。lang_codeはディスク表記
    (例 "ja"/"en"/"ko"/"zh-TW"/"zh-CN")をそのまま渡す。"""
    _write_text(language_file(app_root), lang_code)


# ---------------------------------------------------------------------------
# settings_lastvrm.txt (LastVrmFile L.1464, 書き込みL.1581)
# ---------------------------------------------------------------------------

def lastvrm_file(app_root: str) -> str:
    return _path(app_root, _LASTVRM_FILE)


def load_last_vrm(app_root: str) -> Optional[str]:
    return _read_text(lastvrm_file(app_root))


def save_last_vrm(app_root: str, vrm_path: str) -> None:
    _write_text(lastvrm_file(app_root), vrm_path)


# ---------------------------------------------------------------------------
# settings_autoapply.txt (AutoApplyFile/LoadAutoApply/SaveAutoApply L.1466-1488)
# 既定ON(ファイル未存在時はTrue)。中身は"true"/"false"の小文字文字列。
# 判定は「"false"と完全一致しなければON」というC#側の緩い判定
# (LoadAutoApply L.1478: `.Trim() != "false"`)をそのまま踏襲する。
# ---------------------------------------------------------------------------

def autoapply_file(app_root: str) -> str:
    return _path(app_root, _AUTOAPPLY_FILE)


def load_autoapply(app_root: str) -> bool:
    v = _read_text(autoapply_file(app_root))
    if v is None:
        return True  # 既定ON (LoadAutoApply L.1481)
    return v != "false"


def save_autoapply(app_root: str, enabled: bool) -> None:
    _write_text(autoapply_file(app_root), "true" if enabled else "false")


# ---------------------------------------------------------------------------
# settings_paksdir.txt (PaksDir L.3078-3115)
# 自動発見(SteamRootCandidates等)→手動指定ダイアログ→保存、の三点セット
# そのものはpak_manager.py(WP-A4)の役割。ここでは「解決済みパスの読み書き」
# という最小のI/Oプリミティブのみを提供する。
# ---------------------------------------------------------------------------

def paksdir_file(app_root: str) -> str:
    return _path(app_root, _PAKSDIR_FILE)


def load_paksdir(app_root: str) -> Optional[str]:
    return _read_text(paksdir_file(app_root))


def save_paksdir(app_root: str, paks_dir: str) -> None:
    _write_text(paksdir_file(app_root), paks_dir)
