# pak_manager.py -- PaksDir/ApplySelected/RemoveApplied/DeleteSelected/
# UpdateAppliedStatus 相当(旧 app\DiveToPalworld.cs、DESIGN.md §2.3。
# dev#532 方針A WP-A4)。
#
# 移植元: app\DiveToPalworld.cs
#   - PaksDirHasPak/DistinctPreserveOrder/SteamRootCandidates/SteamLibraryRoots/
#     AutoDiscoverPaksDir/PaksDir/PaksDirQuiet (L.2987-3115, L.3328-3341)
#   - CountOtherPaks (L.3160-3178)
#   - UpdateAppliedStatus/IdentifyAppliedPak/Sha1File (L.3669-3739, L.3624-3632)
#   - ApplySelected/RemoveApplied (L.3791-3827, L.4778-4812)
#   - BuiltPaks/RefreshPakList (L.3634-3661)
#   - DeleteSelected (L.3829-3903)
#
# 設計方針(CLAUDE.md「外部依存パスの原則」= ①自動発見 → ②失敗時に手動指定
# フォールバック(+保存) → ③探索した場所と判定を全部ログへ、の三点セット):
#   本モジュールはtkinter/i18nに依存しない(GUIフレームワーク非依存・
#   pytestでモックFS単体試験できるようにするため)。そのため:
#   - 手動指定フォールバックは `ask_manual: () -> str|None` という関数を
#     呼び出し元(main_window.py)から注入してもらう形にした(実際の
#     FolderBrowserDialog相当・i18n文言はGUI側の責務)。
#   - 「見つからなかった」「無効な場所を選んだ」等の診断情報は `log: str -> None`
#     というコールバックへ渡す(既定は無視する_noop_log)。呼び出し側が
#     ログ欄・セッションログへ流し込める。
#   - ShowApplyFailure()相当の「例外種別→原因/対処メッセージ」への翻訳は
#     i18nデータを伴うためmain_window.py側に置く(本モジュールは生の例外を
#     そのまま伝播させるだけに留める)。
#
# job.jsonのパース(DeleteSelected用のue_project参照)はDESIGN.md §2.1が
# 明示的に許容している通り、C#側の正規表現JsonStr()ではなくjson.loadsへ
# 置き換えている(「同一契約なら破壊的変更ではない」、DESIGN.md §2.5と同じ判断)。

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import settings  # noqa: E402

# ---------------------------------------------------------------------------
# 定数(DiveToPalworld.cs L.700-703, L.2985)
# ---------------------------------------------------------------------------

INSTALL_NAME = "Uchinoko_P.pak"
LEGACY_INSTALL_NAMES: Tuple[str, ...] = ("DiveToPalworld_P.pak", "VRM2Palworld_P.pak")
PAL_WINDOWS_PAK_NAME = "Pal-Windows.pak"
# devtools\apply_test_pak.py の GAME_PROCESS_NAME と同一値(2026-07-23修正済み、
# tasklistのIMAGENAME列25文字切り詰め対策でCSV出力を使う点も踏襲)
GAME_PROCESS_NAME = "Palworld-Win64-Shipping.exe"

LogFn = Callable[[str], None]
AskManualFn = Callable[[], Optional[str]]
OnInvalidFn = Callable[[str], None]


def _noop_log(_msg: str) -> None:
    pass


# ---------------------------------------------------------------------------
# 基礎ヘルパー (PaksDirHasPak/DistinctPreserveOrder L.2987-3004)
# ---------------------------------------------------------------------------

def paks_dir_has_pak(dir_path: Optional[str]) -> bool:
    """PaksDirHasPak(L.2987)相当。"""
    return bool(dir_path) and os.path.isdir(dir_path) \
        and os.path.isfile(os.path.join(dir_path, PAL_WINDOWS_PAK_NAME))


def distinct_preserve_order(items: Iterable[str]) -> List[str]:
    """DistinctPreserveOrder(L.2993-3004)相当。末尾の\\/を落として
    大文字小文字を無視した重複除去(順序は初出優先で保持)。"""
    seen = set()
    out: List[str] = []
    for it in items:
        if not it:
            continue
        norm = it.rstrip("\\/")
        key = norm.lower()
        if key not in seen:
            seen.add(key)
            out.append(norm)
    return out


# ---------------------------------------------------------------------------
# 自動発見 (SteamRootCandidates/SteamLibraryRoots/AutoDiscoverPaksDir
# L.3007-3076)
# ---------------------------------------------------------------------------

def steam_root_candidates() -> List[str]:
    """SteamRootCandidates(L.3007-3037)相当。レジストリ優先、既定パスは保険。
    非Windows環境(pytest実行等)ではレジストリ探索は静かにスキップする。"""
    roots: List[str] = []
    try:
        import winreg  # Windows専用モジュール
    except ImportError:
        winreg = None  # type: ignore[assignment]

    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                for name in ("SteamPath", "InstallPath"):
                    try:
                        v, _ = winreg.QueryValueEx(key, name)
                        if v:
                            roots.append(str(v))
                            break
                    except FileNotFoundError:
                        continue
        except (FileNotFoundError, OSError):
            pass
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"
            ) as key:
                try:
                    v, _ = winreg.QueryValueEx(key, "InstallPath")
                    if v:
                        roots.append(str(v))
                except FileNotFoundError:
                    pass
        except (FileNotFoundError, OSError):
            pass

    roots.append(r"C:\Program Files (x86)\Steam")
    roots.append(r"C:\Program Files\Steam")
    return distinct_preserve_order(roots)


_VDF_PATH_RE = re.compile(r'"path"\s*"([^"]*)"')


def steam_library_roots(steam_root: Optional[str]) -> List[str]:
    """SteamLibraryRoots(L.3042-3062)相当。steamRoot配下のlibraryfolders.vdfから
    登録済み全ライブラリの"path"を正規表現で拾う(完全なKeyValuesパーサは持たない、
    実在確認はファイルシステム側に任せる設計を踏襲)。"""
    libs: List[str] = []
    if not steam_root:
        return libs
    libs.append(steam_root)
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for m in _VDF_PATH_RE.finditer(text):
                p = m.group(1).replace("\\\\", "\\")
                if p:
                    libs.append(p)
        except OSError:
            pass
    return distinct_preserve_order(libs)


def auto_discover_paks_dir(log: LogFn = _noop_log) -> Optional[str]:
    """AutoDiscoverPaksDir(L.3065-3076)相当。ダイアログなしの自動探索。
    探索した候補は全てlogへ渡す(CLAUDE.md「外部依存パスの原則」③)。"""
    for steam_root in steam_root_candidates():
        for lib in steam_library_roots(steam_root):
            paks = os.path.join(lib, "steamapps", "common", "Palworld", "Pal", "Content", "Paks")
            log(f"[pak_manager] auto-discover candidate: {paks}")
            if paks_dir_has_pak(paks):
                log(f"[pak_manager] auto-discover found: {paks}")
                return paks
    log("[pak_manager] auto-discover: not found")
    return None


# ---------------------------------------------------------------------------
# 解決(PaksDir/PaksDirQuiet L.3078-3115, L.3328-3341)
# ---------------------------------------------------------------------------

def paks_dir_quiet(app_root: str, cache: Optional[str] = None, log: LogFn = _noop_log) -> Optional[str]:
    """PaksDirQuiet(L.3328-3341)相当。ダイアログを出さない版
    (起動時の受動的な状態表示など、ユーザー操作の起点ではない場面で使う)。
    見つかっても settings_paksdir.txt への保存はしない(C#の PaksDirQuiet も
    書き込みは行わない。書き込みは resolve_paks_dir 側の役目)。"""
    if paks_dir_has_pak(cache):
        return cache
    saved = settings.load_paksdir(app_root)
    if paks_dir_has_pak(saved):
        log(f"[pak_manager] using cached settings_paksdir.txt: {saved}")
        return saved
    return auto_discover_paks_dir(log)


def resolve_paks_dir(
    app_root: str,
    cache: Optional[str] = None,
    ask_manual: Optional[AskManualFn] = None,
    on_invalid: Optional[OnInvalidFn] = None,
    log: LogFn = _noop_log,
) -> Optional[str]:
    """PaksDir(L.3078-3115)相当。CLAUDE.md「外部依存パスの原則」の三点セット
    そのもの: ①キャッシュ→設定ファイル→自動探索(見つかれば即保存) ②失敗時のみ
    `ask_manual` を繰り返し呼ぶ(無効な場所を選んだら`on_invalid`で理由を伝え、
    無言で受理しない=WP16の踏襲) ③各段階をlogへ記録。

    `ask_manual` がNone、または呼んでも None(キャンセル)を返せばNoneを返す。
    """
    if paks_dir_has_pak(cache):
        return cache
    saved = settings.load_paksdir(app_root)
    if paks_dir_has_pak(saved):
        log(f"[pak_manager] using cached settings_paksdir.txt: {saved}")
        return saved
    auto = auto_discover_paks_dir(log)
    if auto is not None:
        settings.save_paksdir(app_root, auto)
        log(f"[pak_manager] auto-discovered and saved: {auto}")
        return auto
    if ask_manual is None:
        log("[pak_manager] not found and no manual fallback provided")
        return None
    while True:
        chosen = ask_manual()
        if not chosen:
            log("[pak_manager] manual selection cancelled")
            return None
        if paks_dir_has_pak(chosen):
            settings.save_paksdir(app_root, chosen)
            log(f"[pak_manager] manual selection saved: {chosen}")
            return chosen
        log(f"[pak_manager] manual selection invalid (no {PAL_WINDOWS_PAK_NAME}): {chosen}")
        if on_invalid is not None:
            on_invalid(chosen)


# ---------------------------------------------------------------------------
# ゲーム起動判定 (IsGameRunning L.3117-3120)
# ---------------------------------------------------------------------------

def is_game_running() -> bool:
    """IsGameRunning(L.3117-3120)相当。devtools\\apply_test_pak.py の
    is_game_running() と同じtasklist呼び出し方式(CSV出力、IMAGENAME列の
    25文字切り詰め対策済み、2026-07-23実測修正の踏襲)。"""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq " + GAME_PROCESS_NAME, "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL,
        ).decode("mbcs", errors="ignore")
    except Exception:
        return False
    return GAME_PROCESS_NAME.lower() in out.lower()


# ---------------------------------------------------------------------------
# 適用中判定 (UpdateAppliedStatus/IdentifyAppliedPak/Sha1File/CountOtherPaks
# L.3151-3186, L.3624-3739)
# ---------------------------------------------------------------------------

def resolve_applied_target(paks_dir: str) -> dict:
    """UpdateAppliedStatus(L.3669-3724)の即時確定部分(SHA1照合の前まで)。
    旧名(LEGACY_INSTALL_NAMES)が残っていれば新名へ移行する(改名の移行措置、
    L.3675-3683)。戻り値: {"target": str, "exists": bool, "remove_enabled": bool}
    """
    target = os.path.join(paks_dir, INSTALL_NAME)
    for legacy_name in LEGACY_INSTALL_NAMES:
        legacy = os.path.join(paks_dir, legacy_name)
        if not os.path.isfile(target) and os.path.isfile(legacy):
            try:
                os.replace(legacy, target)
            except OSError:
                target = legacy
    any_legacy_left = any(
        os.path.isfile(os.path.join(paks_dir, legacy_name))
        for legacy_name in LEGACY_INSTALL_NAMES
    )
    exists = os.path.isfile(target)
    return {"target": target, "exists": exists, "remove_enabled": exists or any_legacy_left}


def sha1_file(path: str, chunk_size: int = 1 << 20) -> str:
    """Sha1File(L.3624-3632)相当。戻り値の書式はC#(ダッシュ区切り大文字16進)と
    異なりPythonの標準的な小文字16進(hexdigest)だが、内部比較にのみ使う値であり
    ユーザー表示・外部契約には出ないため書式差は実害が無い(§2.5のJSON parse
    置き換えと同種の判断)。"""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def identify_applied_pak(
    target: str, target_len: int, candidates: Sequence[Tuple[str, str]]
) -> Optional[str]:
    """IdentifyAppliedPak(L.3726-3739)相当。candidatesは(pakパス, アバター名)の
    タプル列。サイズが一致する候補だけハッシュを取り、targetのハッシュは
    必要になった時に一度だけ計算する(元のロジックと同一の遅延評価)。"""
    target_hash: Optional[str] = None
    for src_path, avatar_name in candidates:
        try:
            if os.path.getsize(src_path) != target_len:
                continue
        except OSError:
            continue
        if target_hash is None:
            target_hash = sha1_file(target)
        if sha1_file(src_path) == target_hash:
            return avatar_name
    return None


def count_other_paks(paks_dir: Optional[str]) -> Optional[int]:
    """CountOtherPaks(L.3160-3178)相当。自分自身(InstallName/レガシー名)と
    バニラ本体を除いた他の.pak件数。判定不能ならNone。"""
    if not paks_dir or not os.path.isdir(paks_dir):
        return None
    exclude = {INSTALL_NAME.lower(), PAL_WINDOWS_PAK_NAME.lower()}
    exclude.update(name.lower() for name in LEGACY_INSTALL_NAMES)
    try:
        count = 0
        for entry in os.listdir(paks_dir):
            if not entry.lower().endswith(".pak"):
                continue
            if entry.lower() not in exclude:
                count += 1
        return count
    except OSError:
        return None


def summarize_other_paks(n: Optional[int]) -> str:
    """SummarizeOtherPaks(L.3181-3186)相当。dev#532方針A WP-A11(dev#549)で移植。
    診断ログ用の1行に整形する。dev#103裁定どおりファイル名は一切出さない
    (count_other_paks()自体がint|Noneしか返さない設計のため、この関数も
    構造的にファイル名を持ち得ない)。"""
    if n is None:
        return "other_paks: unknown (paks dir not found)"
    if n == 0:
        return "other_paks: none"
    return "other_paks: " + str(n) + " (.pak)"


# ---------------------------------------------------------------------------
# 一覧 (BuiltPaks/RefreshPakList L.3634-3661)
# ---------------------------------------------------------------------------

def list_built_paks(work_root: str) -> List[Tuple[str, str]]:
    """BuiltPaks(L.3634-3646)相当。<workRoot>\\<jobDir>\\build\\*_PlayerSwap_P.pak
    を列挙し、(pakパス, アバター名=jobDir名) のタプル列を返す。"""
    result: List[Tuple[str, str]] = []
    if not os.path.isdir(work_root):
        return result
    for entry in sorted(os.listdir(work_root)):
        job_dir = os.path.join(work_root, entry)
        if not os.path.isdir(job_dir):
            continue
        build_dir = os.path.join(job_dir, "build")
        if not os.path.isdir(build_dir):
            continue
        for f in sorted(os.listdir(build_dir)):
            if f.endswith("_PlayerSwap_P.pak"):
                result.append((os.path.join(build_dir, f), entry))
    return result


# ---------------------------------------------------------------------------
# 適用/解除 (ApplySelected/RemoveApplied L.3791-3827, L.4778-4812)
# ---------------------------------------------------------------------------

def apply_pak(paks_dir: str, src_pak_path: str) -> str:
    """ApplySelected(L.3791-3827)の中核(コピー+旧名残骸削除のみ)。
    「未選択」「ゲーム起動中」等のi18n文言を伴う事前チェックはmain_window.py側が
    担う。src_pak_pathが無ければFileNotFoundError、コピー/削除の失敗はOSError
    (サブクラス含む)をそのまま伝播させる(原因分類・ユーザー向けメッセージ整形=
    旧ShowApplyFailure相当はmain_window.py側の責務)。戻り値: 適用先の絶対パス。
    """
    if not os.path.isfile(src_pak_path):
        raise FileNotFoundError(src_pak_path)
    apply_target = os.path.join(paks_dir, INSTALL_NAME)
    shutil.copyfile(src_pak_path, apply_target)
    # 旧名の残骸があれば二重適用にならないよう消す(旧2世代とも、L.3811-3816)
    for legacy_name in LEGACY_INSTALL_NAMES:
        legacy = os.path.join(paks_dir, legacy_name)
        if os.path.isfile(legacy):
            os.remove(legacy)
    return apply_target


def remove_applied(paks_dir: str) -> bool:
    """RemoveApplied(L.4778-4812)の中核。何も適用されていなければFalseを返す
    (statusLabelの文言選定=StatusNoModApplied/StatusModRemovedはmain_window.py側)。
    削除失敗はOSExceptionをそのまま伝播(ShowApplyFailure相当はGUI側)。"""
    target = os.path.join(paks_dir, INSTALL_NAME)
    legacy_targets = [
        os.path.join(paks_dir, name)
        for name in LEGACY_INSTALL_NAMES
        if os.path.isfile(os.path.join(paks_dir, name))
    ]
    if not os.path.isfile(target) and not legacy_targets:
        return False
    if os.path.isfile(target):
        os.remove(target)
    for legacy in legacy_targets:
        os.remove(legacy)
    return True


# ---------------------------------------------------------------------------
# 削除 (DeleteSelected L.3829-3903)
# ---------------------------------------------------------------------------

def sanitize_name(s: str) -> str:
    """SanitizeName(L.1734-1742)相当(英数字ASCIIのみ残す、空ならAvatar)。
    DeleteSelected()が「削除対象アバター名と現在開いているVRMが同じか」を
    比較する時にだけ使う最小複製。WriteJob()側の同名ロジックはWP-A2
    (pipeline_runner.py)が正本を持つ予定だが、A2未着手のためA4が必要とする
    分だけここに置いた(統合時に共有ヘルパーへ寄せるかは統合WP判断、合理的解釈)。
    """
    out = [c for c in s if ("a" <= c.lower() <= "z") or c.isdigit()]
    result = "".join(out)
    return result if result else "Avatar"


def resolve_delete_targets(work_root: str, app_root: str, pak_path: str) -> dict:
    """DeleteSelected(L.3829-3903)の削除先解決部分(確認ダイアログ表示前に呼ぶ、
    副作用なし)。jobDir = dirname(dirname(pak))(pakは<jobDir>\\build\\*.pak、
    L.3834)。ue_projectはjob.jsonの"ue_project"キーを読み、このツールの
    ue_project\\配下にある場合だけ削除対象にする(誤爆防止、L.3836-3850)。
    JSONパースはDESIGN.md §2.5と同じ理由でjson.loads(正規表現JsonStrの代替)。
    戻り値: {"job_dir": str, "ue_project_dir": Optional[str]}
    """
    job_dir = os.path.dirname(os.path.dirname(pak_path))
    ue_project_dir = None
    job_json = os.path.join(job_dir, "job.json")
    if os.path.isfile(job_json):
        uepro = None
        try:
            with open(job_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            uepro = data.get("ue_project")
        except (OSError, ValueError):
            uepro = None
        if uepro:
            root = os.path.join(app_root, "ue_project")
            cand = os.path.dirname(uepro)  # ...\<名前>\Pal
            if cand and os.path.normcase(cand).startswith(os.path.normcase(root)):
                ue_project_dir = os.path.dirname(cand)  # ...\<名前>
    return {"job_dir": job_dir, "ue_project_dir": ue_project_dir}


def delete_avatar_artifacts(job_dir: str, ue_project_dir: Optional[str] = None) -> None:
    """resolve_delete_targets()の結果を実際に削除する(確認ダイアログでYESの後に
    呼ぶ、L.3866-3877)。存在しないディレクトリは無視する。失敗はOSErrorを
    そのまま伝播させる(MsgDeleteFailedFormatへの整形はmain_window.py側)。
    元のVRM/FBXファイル自体はこの関数の対象外(ツールの外にあるため無傷)。
    """
    if os.path.isdir(job_dir):
        shutil.rmtree(job_dir)
    if ue_project_dir and os.path.isdir(ue_project_dir):
        shutil.rmtree(ue_project_dir)
