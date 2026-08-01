# blender_setup.py -- Blender準備契約(DESIGN.md §2.2)のPython移植。
#
# dev#532 方針A WP-A3: DESIGN.md(C:\P\Work\DiveToPalworld\work\wp532A\DESIGN.md)
# §2.2「Blender準備契約」の移植先。任務の契約範囲は
#   DoEnsureBlenderReady・ensure_blender.ps1呼び出し・進捗中継・失敗時リトライ
# の4点(指示書より)。
#
# 移植元: app\DiveToPalworld.cs
#   - AssetSubDir()                    L.1752-1757
#   - FindBlender()                    L.1836-1860 (MAX_PATH短縮ジャンクション
#                                        TryGetShortBlenderPathは対象外、後述)
#   - BlenderSetupAction enum          L.2012-2017
#   - DecideBlenderSetupAction()       L.2019-2030 (純関数。CheckBlenderSetupDecisionLogic
#                                        L.5055-5083 のケース表がそのまま受入試験)
#   - DoEnsureBlenderReady()           L.2037-2098
#   - RunEnsureBlenderSetupProcess()   L.2107-2169
#   - RunEnsureBlenderCheckOnly()      L.2177-2205
#   - FindPwsh()                       L.2721-2739
#
# 合理的解釈(スコープの線引き、完了報告にも記載):
#   - FindPwsh()は本来pipeline_runner.py(WP-A2、DESIGN.md §4.1)の担当だが、
#     A2は本WP時点で未着手・未マージのため、blender_setup.py内に最小限の
#     private実装(_find_pwsh)を置く。WP-A2完了後の重複解消は別WPの課題とする。
#   - TryGetShortBlenderPath(dev#149、MAX_PATH超過対策のNTFSジャンクション)は
#     「Blender準備契約」の中核4点に含まれない付随最適化のため、本WPでは移植
#     しない(find_blenderは常に実体パスを返す。動作は変わらないが深い
#     インストール先でのdev#149相当の問題は本WPでは未対策のまま)。
#   - WarmSharedCacheOnStartup/WarmBlenderProcessOnStartup(DoEnsureBlenderReady
#     成功後に続けて呼ばれる別機能。convert_noue.py起動・pak解決(A4領域)に
#     依存し、契約4点にも含まれない)は本WPのスコープ外。

from __future__ import annotations

import enum
import os
import re
import subprocess
from typing import Callable, List, Optional, Tuple

# AppendLog()のProgressMark定数(L.2829-2836)と同じ正規表現。
PROGRESS_MARK = re.compile(r"##PROGRESS##\s*(\d+)\s*(.*)")

# RunEnsureBlenderSetupProcess()が失敗時の案内文を切り出す境界マーカー。
FAIL_MARKER = "[D2P_BLENDER_SETUP_FAIL]"

# FindBlender() L.1840の開発機決め打ちフォールバック。既存債務としてそのまま
# 移植する(CLAUDE.md「外部依存パスの原則」の是正は本WPのスコープ外)。
_DEV_FALLBACK_BLENDER_DIR = r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64"


class BlenderSetupAction(enum.Enum):
    """DecideBlenderSetupAction()の戻り値(C# enum L.2012-2017の1:1移植)。"""

    READY_NO_ACTION = "ReadyNoAction"          # 既にBlenderが使える。何もしなくてよい
    NEED_FULL_SETUP = "NeedFullSetup"          # ensure_blender.ps1のフル実行が必要
    DEV_NOT_FOUND_NO_SCRIPT = "DevNotFoundNoScript"  # 開発チェックアウト等でスクリプトもexeも無い


def asset_sub_dir(app_root: str, name: str) -> str:
    """AssetSubDir() L.1752-1757相当。配布物では assets\\<name>、開発ツリーでは
    直下\\<name> に置かれる二重構成を吸収する。"""
    dist = os.path.join(app_root, "assets", name)
    if os.path.isdir(dist):
        return dist
    return os.path.join(app_root, name)


def find_blender(app_root: str) -> str:
    """FindBlender() L.1836-1860の移植(MAX_PATH短縮ジャンクションを除く、
    上記の合理的解釈を参照)。候補が1つも実在しなければC#と同じく
    "blender.exe"(PATH解決に委ねる文字列)を返す。"""
    tools_dir = asset_sub_dir(app_root, "tools")
    candidates: List[str] = []
    if os.path.isdir(tools_dir):
        for entry in sorted(os.listdir(tools_dir)):
            if entry.startswith("blender-") and entry.endswith("-windows-x64"):
                candidates.append(os.path.join(tools_dir, entry))
    candidates.append(_DEV_FALLBACK_BLENDER_DIR)
    for c in candidates:
        exe = os.path.join(c, "blender.exe")
        if os.path.isfile(exe):
            return exe
    return "blender.exe"


def ensure_blender_ps1_path(app_root: str) -> str:
    """DoEnsureBlenderReady() L.2040相当のパス組み立てのみを切り出したもの。"""
    return os.path.join(app_root, "pipeline", "cli", "ensure_blender.ps1")


def _find_pwsh() -> str:
    """FindPwsh() L.2721-2739の移植。PATHからpwsh.exe(PowerShell 7)を探し、
    無ければ<ProgramFiles>\\PowerShell\\7\\pwsh.exe、それも無ければ
    "powershell.exe"(Windows PowerShell 5.1、convert.ps1/ensure_blender.ps1は
    5.1互換で書かれている前提)。"""
    path_env = os.environ.get("PATH", "")
    for d in path_env.split(os.pathsep):
        try:
            cand = os.path.join(d.strip(), "pwsh.exe")
            if os.path.isfile(cand):
                return cand
        except OSError:
            continue
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    pwsh = os.path.join(program_files, "PowerShell", "7", "pwsh.exe")
    if os.path.isfile(pwsh):
        return pwsh
    return "powershell.exe"


def decide_blender_setup_action(
    ensure_ps1_exists: bool, blender_exe_exists: bool, check_only_valid: bool
) -> BlenderSetupAction:
    """DecideBlenderSetupAction() L.2019-2030の1:1移植。ファイルI/O・プロセス
    起動を一切含まない純関数(3つのboolだけで判定)。

    根拠(CheckBlenderSetupDecisionLogic L.5048-5054のコメントより):
      - ensurePs1が無い(開発チェックアウト等)場合、checkOnlyValidの値に関わらず
        exeの有無だけで決まる(マーカー検証はensurePs1側の責務なので、その
        スクリプト自体が無ければ検証しようがない)。
      - ensurePs1がある場合、exeがあってcheckOnlyValid(Test-D2PMarkerValid相当)が
        Trueの時だけREADY_NO_ACTION。それ以外(exe無し、またはマーカー無効)は
        NEED_FULL_SETUP(dev#230対策: 「exeがあるだけ」でreadyにしない、が核心)。
    """
    if not ensure_ps1_exists:
        return (
            BlenderSetupAction.READY_NO_ACTION
            if blender_exe_exists
            else BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
        )
    if blender_exe_exists and check_only_valid:
        return BlenderSetupAction.READY_NO_ACTION
    return BlenderSetupAction.NEED_FULL_SETUP


def run_ensure_blender_check_only(
    ensure_ps1: str, app_root: str, timeout_sec: float = 10.0
) -> bool:
    """RunEnsureBlenderCheckOnly() L.2177-2205の移植。
    `ensure_blender.ps1 -CheckOnly` を同期・非表示で実行し、
    Test-D2PMarkerValid(exe実在+マーカー実在+version/sha256/patched一致)の
    結果を終了コードで受け取る。終了コード0=有効、それ以外/タイムアウト/例外は
    False(フル実行へフォールバック、安全側)。"""
    try:
        args = [
            _find_pwsh(), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ensure_ps1, "-AppRoot", app_root, "-CheckOnly",
        ]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False

    try:
        proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.communicate()
        except OSError:
            pass
        return False
    return proc.returncode == 0


def run_ensure_blender_setup_process(
    ensure_ps1: str,
    app_root: str,
    on_progress: Optional[Callable[[int, str], None]] = None,
) -> Tuple[bool, Optional[str]]:
    """RunEnsureBlenderSetupProcess() L.2107-2169の移植。
    ensure_blender.ps1をフル実行(取得/再パッチ)し、標準出力/エラーの
    ##PROGRESS##行を on_progress(pct, phase) へ中継する(進捗中継)。
    失敗時は[D2P_BLENDER_SETUP_FAIL]以降の案内文をfail_messageとして返す
    (見つからなければ全出力、それも空ならNone)。
    呼び出し元が再度この関数を呼べば失敗時リトライになる(C#版のリトライボタンと
    同じ設計: このモジュール自体は再試行ループを持たず、UI側の明示操作に委ねる)。"""
    try:
        args = [
            _find_pwsh(), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ensure_ps1, "-AppRoot", app_root,
        ]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as ex:
        return False, f"ensure_blender.ps1の起動に失敗しました: {ex}"

    lines: List[str] = []
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            lines.append(line)
            m = PROGRESS_MARK.match(line)
            if m and on_progress is not None:
                try:
                    pct = max(0, min(100, int(m.group(1))))
                except ValueError:
                    continue
                phase = m.group(2).strip()
                on_progress(pct, phase)
    finally:
        proc.wait()

    if proc.returncode == 0:
        return True, None

    full_output = "\n".join(lines)
    idx = full_output.find(FAIL_MARKER)
    fail_message = full_output[idx:].strip() if idx >= 0 else full_output.strip()
    return False, (fail_message or None)


def do_ensure_blender_ready(
    app_root: str,
    on_progress: Optional[Callable[[int, str], None]] = None,
) -> Tuple[bool, Optional[str], BlenderSetupAction]:
    """DoEnsureBlenderReady() L.2037-2098の移植。ワーカースレッドで呼ぶ想定で
    あり、ここではUIに一切触れない(呼び出し元がスレッド分離とPostToUi相当の
    中継を担う、DESIGN.md §4.3)。

    戻り値: (ok, fail_message, action)。

    WarmSharedCacheOnStartup/WarmBlenderProcessOnStartup相当の後続処理
    (成功後にバニラ準備等をバックグラウンドで撃つ最適化)は本WPのスコープ外
    (ファイル冒頭コメント参照)。"""
    blender = find_blender(app_root)
    ensure_ps1 = ensure_blender_ps1_path(app_root)
    ensure_ps1_exists = os.path.isfile(ensure_ps1)
    blender_exe_exists = os.path.isfile(blender)
    # -CheckOnlyはensurePs1が無ければ意味を持たない(遅延評価、L.2043-2046と同じ)
    check_only_valid = (
        ensure_ps1_exists
        and blender_exe_exists
        and run_ensure_blender_check_only(ensure_ps1, app_root)
    )

    action = decide_blender_setup_action(ensure_ps1_exists, blender_exe_exists, check_only_valid)

    if action is BlenderSetupAction.READY_NO_ACTION:
        return True, None, action
    if action is BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT:
        return False, f"Blenderが見つかりません(開発環境): {blender}", action
    # NEED_FULL_SETUP
    ok, fail_message = run_ensure_blender_setup_process(
        ensure_ps1, app_root, on_progress=on_progress
    )
    return ok, fail_message, action
