# warm_startup.py -- 起動時プリウォーム(共有キャッシュ+Blender本体プロセス)の
# Python移植(dev#532 方針A WP-A9)。
#
# 背景(WP-C5の発見、work\wp532A\C5_NOTES.md §1.1): この2機能は
# WarmSharedCacheOnStartup()/WarmBlenderProcessOnStartup()としてC#側に実装
# 済みだったが、blender_setup.py(WP-A3)が明示的にスコープ外としたため
# Track A(A1〜A6)のどのWPにも割り当てられていなかった。本WPはその割り当て
# 漏れを埋める独立モジュールとして新設する。
#
# 移植元: app\DiveToPalworld.cs
#   - WarmSharedCacheOnStartup()      L.2219-2285
#   - WarmBlenderProcessOnStartup()   L.2319-2370
#   - WarmDiagLog()                   L.2290-2301
#   - FindBlenderPython()             L.2374-2388
#   - WarmCachePakPath()              L.2393-2398 (呼び出し元へ委譲、後述)
# 検査元(ケース表): devtools\shipcheck_src\warm_startup_check.cs の
#   RunWarmStartupChecks() case1〜case4(§設計上の判断、下記参照)。
#
# 設計方針(work\wp532A\C5_NOTES.md §1.2/§1.3の推奨に従う):
#   - partial class(MainFormのインスタンスフィールド appRoot/workRoot/
#     blenderReady/runningProc を暗黙に共有する仕組み)の代替は「明示的な
#     関数引数」で足りる。本モジュールの関数はいずれも状態を持たない。
#   - case3/case4(代役blender.exeが要る負の対照)は、C5_NOTES.md推奨(b)を
#     採用し、プロセス起動そのものを`popen`引数でDI(依存性注入)する。
#     ガード判定(os.path.isfile等)は実ファイルのある/なしで検査できるため
#     ダミーファイルで足り、実プロセス起動の可否(実際にBlenderが立ち上がる
#     こと)はここでは検証しない。その検証はWSB通し試験(D1のGATE、
#     CLAUDE.md「実装したと効いているは別」)に委ねる。
#   - 合理的解釈(C#との差分、完了報告にも記載): C#のWarmSharedCacheOnStartup/
#     WarmBlenderProcessOnStartupは内部でFindBlender()/WarmCachePakPath()
#     (=PaksDirQuiet())を自前で呼んでいたが、本モジュールはblender_setup.py
#     ともpak_manager.pyとも依存関係を作らないため、解決済みの
#     `blender_exe`/`pak_path`を呼び出し元から引数で受け取る設計にした
#     (find_blender_python()だけは「blenderExeから兄弟ディレクトリを探す」
#     純粋な補助関数なのでC#と同じ位置(本モジュール内)に置いている)。
#
# ---------------------------------------------------------------------------
# D1(統合WP)への結線手順:
#   1. blender_setup.do_ensure_blender_ready() が (ok=True, ...) を返した
#      直後に呼ぶ(C#のDoEnsureBlenderReady() L.2073-2089の呼び出し順を踏襲)。
#      本モジュールの warm_startup_after_blender_ready() が「ok=True確定後に
#      呼ぶべき2機能」をまとめて呼ぶ唯一のエントリポイントなので、D1は
#      これ1つを呼べばよい:
#
#          ok, fail_message, action = blender_setup.do_ensure_blender_ready(app_root)
#          if ok:
#              blender_exe = blender_setup.find_blender(app_root)
#              paks_dir = pak_manager.paks_dir_quiet(app_root)
#              pak_path = (
#                  os.path.join(paks_dir, pak_manager.PAL_WINDOWS_PAK_NAME)
#                  if paks_dir else None
#              )
#              warm_startup.warm_startup_after_blender_ready(
#                  app_root, work_root, blender_exe, pak_path,
#                  conversion_pending=(pending_blender_ready_action is not None),
#              )
#
#   2. `conversion_pending` には、C#の`pendingBlenderReadyAction != null`
#      (D&D等で保留されていた変換がこの直後に始まる状態)を渡す。Trueなら
#      Blender本体プロセスのプリウォームだけスキップする(warm_shared_cache_
#      on_startupは常に実行する。C# L.2086-2089と同じ非対称)。
#   3. 呼び出しはワーカースレッド側(DoEnsureBlenderReady相当)で行い、UI
#      スレッドを一切ブロックしないこと(本モジュール自体は非同期実行の
#      骨組み(バックグラウンドスレッドでの完了待ち)を内包しているが、
#      呼び出し自体をUIスレッドで行うとPopen呼び出し分だけブロックする)。
#   4. 実プロセス起動確認(実際にBlenderが立ち上がりOSキャッシュが温まる
#      こと)はWSB通し試験側の責務(D1のGATE)。本WPの単体試験は
#      ガード分岐とログ配線のみを検査する(C5_NOTES.md §1.3推奨(b))。

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

# WarmBlenderProcessOnStartup() L.2329 と同一の起動引数
# (--background --factory-startup --python-exit-code 0 --python-expr "pass")。
_BLENDER_PREWARM_ARGS = [
    "--background",
    "--factory-startup",
    "--python-exit-code",
    "0",
    "--python-expr",
    "pass",
]

# subprocess.Popen互換の呼び出し可能オブジェクト。DI差し替え用の型エイリアス。
PopenFactory = Callable[..., Any]

# warm_startup.logは呼び出し元スレッド(started記録)と_pump_and_wait用の
# バックグラウンドスレッド(exited記録)から同時に追記されうる。C#版は
# File.AppendAllTextを都度呼ぶだけで明示ロックを持たないが、それは.NETの
# File.AppendAllTextが内部でファイルを都度開いて閉じるだけで多重書き込みの
# 直列化を保証しないのと同様、Python側でも素朴な複数open("a")は非同期タイミング
# 次第で書き込みが行単位で交錯し、ログが破損しうる(実測: 完了が一瞬で返る
# フェイクプロセスを使った単体試験で、行の途中から別の行が割り込む破損を確認)。
# 実運用のBlender起動では完了まで数秒かかり交錯はまず起きないが、単体試験の
# 再現性を守るため、このモジュール内の全書き込みをプロセス内ロックで直列化する
# (C#の挙動を変えるものではない。あくまでPython側の複数スレッド書き込みを
# 安全にするための実装上の補強)。
_LOG_LOCK = threading.Lock()


def warm_diag_log(work_root: str, line: str) -> None:
    """WarmDiagLog() L.2290-2301の移植。起動時warm処理の「何が起きた/
    起きなかったか」をwork_root\\warm_startup.logへ集約する。UIには一切
    出さない(4.5の「失敗は無視」規定、ログ自体の失敗で本処理を止めない)。"""
    try:
        os.makedirs(work_root, exist_ok=True)
        path = os.path.join(work_root, "warm_startup.log")
        timestamp = datetime.now(timezone.utc).isoformat()
        with _LOG_LOCK, open(path, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {line}\n")
    except OSError:
        pass


def find_blender_python(blender_exe: str) -> Optional[str]:
    """FindBlenderPython() L.2374-2388の移植。convert.ps1の$BPython解決
    (Get-ChildItem (Split-Path $Blender)\\*\\python\\bin\\python.exe)と
    同じ規則で、blender_exeの兄弟ディレクトリからBlender同梱pythonを探す。
    見つからなければNone(例外はすべて握りつぶす、C#と同じ安全側)。"""
    try:
        blender_dir = os.path.dirname(blender_exe)
        if not blender_dir:
            return None
        for entry in sorted(os.listdir(blender_dir)):
            sub = os.path.join(blender_dir, entry)
            if not os.path.isdir(sub):
                continue
            candidate = os.path.join(sub, "python", "bin", "python.exe")
            if os.path.isfile(candidate):
                return candidate
    except OSError:
        return None
    return None


def _spawn_fire_and_forget(
    popen: PopenFactory,
    args: List[str],
    log_path: str,
    work_root: str,
    prefix: str,
) -> None:
    """プロセスを起動し、完了を待たずに戻る(撃ちっぱなし)。標準出力/エラーは
    行単位でlog_pathへ追記する(C#のOutputDataReceivedハンドラがFile.
    AppendAllTextを1行ごとに呼ぶ挙動を再現。ログファイルは実際にデータが
    来て初めて作られる=popen()自体が失敗すればログファイルは一切作られない)。
    完了は別スレッドでwait()し、warm_startup.logへ
    「<prefix>: exited code=... elapsed=...s」を記録する(Process.Exited
    ハンドラ相当)。popen()自体が投げた例外はここでは吸収せずそのまま
    呼び出し元へ伝播させる(呼び出し元の外側try/exceptが「失敗は無視」を
    担う設計、warm_shared_cache_on_startup/warm_blender_process_on_startup
    を参照)。"""
    proc = popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    t0 = time.monotonic()

    def _pump_and_wait() -> None:
        try:
            stdout = getattr(proc, "stdout", None)
            if stdout is not None:
                for raw_line in stdout:
                    line = raw_line if raw_line.endswith("\n") else raw_line + "\n"
                    try:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(line)
                    except OSError:
                        pass
            proc.wait()
            elapsed = time.monotonic() - t0
            warm_diag_log(
                work_root, f"{prefix}: exited code={proc.returncode} elapsed={elapsed:.2f}s"
            )
        except Exception:  # noqa: BLE001 -- 完了ログ用スレッドの失敗で本処理を止めない
            pass

    threading.Thread(target=_pump_and_wait, daemon=True).start()


def warm_shared_cache_on_startup(
    app_root: str,
    work_root: str,
    blender_ready: bool,
    blender_exe: str,
    pak_path: Optional[str],
    *,
    popen: PopenFactory = subprocess.Popen,
) -> None:
    """WarmSharedCacheOnStartup() L.2219-2285の移植。バニラ準備
    (extract_vanilla.py)とライブテンプレート(live_template.py)の事前計算を
    Blender本体プロセスとは別に(bpy非依存のpure-Python経路、convert_noue.py
    --warm-cache)バックグラウンドで撃ちっぱなしにする。ガード条件を1つでも
    満たさなければ理由をwarm_startup.logへ記録して即returnする(C#の
    「以前は完全に無音だった」に対するdev#288の是正をそのまま踏襲)。"""
    try:
        if not blender_ready:
            warm_diag_log(work_root, "warm-cache: skip (blenderReady=false)")
            return
        if not os.path.isfile(blender_exe):
            warm_diag_log(work_root, f"warm-cache: skip (blender.exe not found: {blender_exe})")
            return
        bpython = find_blender_python(blender_exe)
        if bpython is None or not os.path.isfile(bpython):
            warm_diag_log(
                work_root, f"warm-cache: skip (bundled python not found under {blender_exe})"
            )
            return
        if pak_path is None or not os.path.isfile(pak_path):
            warm_diag_log(
                work_root, f"warm-cache: skip (pak not resolved: {pak_path or 'null'})"
            )
            return
        script = os.path.join(app_root, "pipeline", "py", "convert_noue.py")
        if not os.path.isfile(script):
            warm_diag_log(work_root, f"warm-cache: skip (convert_noue.py not found: {script})")
            return

        os.makedirs(work_root, exist_ok=True)
        args = [bpython, script, "--warm-cache", "--pak", pak_path, "--work-root", work_root]
        log_path = os.path.join(work_root, "warm_cache.log")
        _spawn_fire_and_forget(popen, args, log_path, work_root, "warm-cache")
        warm_diag_log(work_root, f"warm-cache: started pak={pak_path}")
        # 意図的にwait()しない(撃ちっぱなし)。失敗してもUIには一切出さない
        # (ログファイルのみ、4.5の「失敗は無視」規定)。
    except Exception as ex:  # noqa: BLE001 -- C#実装(L.2279-2284)と同じ「失敗は無視」方針
        try:
            warm_diag_log(work_root, f"warm-cache: exception {ex}")
        except Exception:  # noqa: BLE001 -- ログ自体の失敗で二重に握りつぶさない対象を広げない
            pass


def warm_blender_process_on_startup(
    work_root: str,
    blender_ready: bool,
    conversion_running: bool,
    blender_exe: str,
    *,
    popen: PopenFactory = subprocess.Popen,
) -> None:
    """WarmBlenderProcessOnStartup() L.2319-2370の移植。Blender本体を
    無害な最小起動(--python-expr "pass"、即終了)で1回だけバックグラウンド
    実行し、以後の実step01起動でOSファイルキャッシュが効くことを狙う。
    blenderReady確定後にのみ、かつ変換中(conversion_running)でなければ
    実行する。"""
    try:
        if not blender_ready:
            warm_diag_log(work_root, "blender-prewarm: skip (blenderReady=false)")
            return
        if conversion_running:
            warm_diag_log(work_root, "blender-prewarm: skip (conversion already running)")
            return
        if not os.path.isfile(blender_exe):
            warm_diag_log(
                work_root, f"blender-prewarm: skip (blender.exe not found: {blender_exe})"
            )
            return

        os.makedirs(work_root, exist_ok=True)
        args = [blender_exe] + _BLENDER_PREWARM_ARGS
        log_path = os.path.join(work_root, "warm_blender.log")
        _spawn_fire_and_forget(popen, args, log_path, work_root, "blender-prewarm")
        warm_diag_log(work_root, f"blender-prewarm: started {blender_exe}")
        # 撃ちっぱなし。wait()しない(UIも他の処理も一切ブロックしない)。
    except Exception as ex:  # noqa: BLE001 -- C#実装(L.2366-2369)と同じ「失敗は無視」方針
        try:
            warm_diag_log(work_root, f"blender-prewarm: exception {ex}")
        except Exception:  # noqa: BLE001
            pass


def warm_startup_after_blender_ready(
    app_root: str,
    work_root: str,
    blender_exe: str,
    pak_path: Optional[str],
    *,
    conversion_pending: bool = False,
    popen: PopenFactory = subprocess.Popen,
) -> None:
    """DoEnsureBlenderReady() L.2073-2089の呼び出し順序(blenderReady=true
    確定直後にwarm_shared_cache_on_startup→(保留中の変換が無ければ)
    warm_blender_process_on_startupの順で呼ぶ)をそのまま再現する
    まとめ関数。D1が呼ぶべき唯一のエントリポイント(上記ファイル冒頭の
    「D1への結線手順」参照)。"""
    warm_shared_cache_on_startup(app_root, work_root, True, blender_exe, pak_path, popen=popen)
    if not conversion_pending:
        warm_blender_process_on_startup(work_root, True, False, blender_exe, popen=popen)
