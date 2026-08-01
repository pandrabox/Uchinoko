# dnd.py -- Windows ドラッグ&ドロップ受信(dev#532 方針A WP-A8)。
#
# 指揮者裁定: 外部バイナリ(tkinterdnd2等のネイティブdll)の同梱は禁止。
# 本モジュールは ctypes + Win32 API(DragAcceptFiles + WM_DROPFILES の
# ウィンドウプロシージャ・サブクラス化)のみで実装する(追加の同梱物ゼロ)。
#
# 移植元: app\DiveToPalworld.cs L.946-948(AllowDrop=true; DragEnter/DragDrop
# ハンドラ登録)、L.1401-1431(OnDragEnter/OnDragDrop本体)。
#
# C#版の挙動(そのまま踏襲、DESIGN.md §1.1-#4 / タスク指示「受理拡張子・
# 複数ファイル時の挙動を一致させる」):
#   - 受理拡張子は `.vrm` / `.fbx` / `.prefab`(大小文字を区別しない)。
#   - 複数ファイルが同時にドロップされても **先頭の1件(files[0])だけ**を
#     見る。2件目以降は存在確認すら行わない(C#の `files[0]` そのまま)。
#     したがって「1件目が拒否対象・2件目が有効」という組み合わせでも
#     採用されるのは1件目の判定結果(=不採用)。
#   - 空のドロップ(理論上稀)は不採用として扱う。
#   - 拡張子不一致時はダイアログ表示(`MsgDropVrmOrPrefab`)のみ行い、
#     何も採用しない。ダイアログ表示自体はUI層(main_window.py)の責務とし、
#     本モジュールは判定ロジックのみを持つ(on_rejectedコールバック経由)。
#   - 採用時、.prefabならUnity輸出経路、それ以外は通常のSetVrm経路へ渡す
#     (どちらへ振り分けるかもUI層の責務。本モジュールは「採用された1パス」を
#     返すだけ)。
#
# Blender未セットアップ時のpendingBlenderReadyAction機構(C# L.1422-1446)は
# 本WPのスコープ外(タスク指示「受理拡張子・複数ファイル時の挙動を一致させる」
# の範囲に限定、convertButton等の既存ハンドラも同種のゲートを持たない現状の
# main_window.pyと整合させる〈合理的解釈〉。導入する場合は別WPでconvertButton
# 等と合わせて設計するのが妥当)。

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable, Optional

ACCEPTED_EXTENSIONS = (".vrm", ".fbx", ".prefab")

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


def is_supported() -> bool:
    """このモジュールのWin32連携部分が使える環境かどうか。
    プロジェクトはWindows専用だが、pytest等をLinux/macOS上のCIで走らせる
    可能性を潰さないための単純なガード(§受入テストはこのフラグに依存しない
    純粋ロジック関数のみを対象にする)。"""
    return sys.platform == "win32"


def pick_dropped_path(file_paths: list[str]) -> Optional[str]:
    """OnDragDrop() L.1406-1416相当の判定ロジック(Win32非依存の純粋関数)。

    C#の `var files = ...; string path = files.Length > 0 ? files[0] : "";`
    をそのまま踏襲: 見るのは先頭の1件だけ。2件目以降がどんな内容でも結果に
    影響しない。拡張子は大小文字を区別しない。

    採用なら絶対パス文字列(渡された文字列そのまま、加工しない)、
    不採用ならNoneを返す。
    """
    path = file_paths[0] if file_paths else ""
    if not path:
        return None
    if not path.lower().endswith(ACCEPTED_EXTENSIONS):
        return None
    return path


def is_prefab_path(path: str) -> bool:
    """OnDragDrop() L.1416相当(`bool isPrefab = f.EndsWith(".prefab")`)。"""
    return path.lower().endswith(".prefab")


class DropTarget:
    """1つのTk実ウィンドウ(HWND)にWin32 D&Dを配線するオブジェクト。

    `on_path(path)` は採用された1パスで呼ばれる。`on_rejected()` は
    ドロップはされたが拡張子不一致/空だった場合に呼ばれる(C#の
    `MessageBox.Show(T("MsgDropVrmOrPrefab"))`相当、実表示はUI層の責務)。

    実装: DragAcceptFiles(hwnd, True) でOS側にD&D受理を宣言し、
    SetWindowLongPtrW(GWLP_WNDPROC)でウィンドウプロシージャを差し替えて
    WM_DROPFILESだけを横取りする(それ以外のメッセージは元のプロシージャへ
    CallWindowProcWで素通しする、いわゆるサブクラス化)。追加DLLは一切使わない。
    """

    def __init__(
        self,
        hwnd: int,
        on_path: Callable[[str], None],
        on_rejected: Optional[Callable[[], None]] = None,
    ) -> None:
        if not is_supported():
            raise RuntimeError("dnd.DropTarget requires Windows (win32 ctypes API)")
        self._hwnd = wintypes.HWND(hwnd)
        self._on_path = on_path
        self._on_rejected = on_rejected
        self._user32 = ctypes.windll.user32
        self._shell32 = ctypes.windll.shell32
        self._wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_long, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
        )
        self._new_proc = self._wndproc_type(self._wnd_proc)
        self._orig_proc = None
        self._configure_bindings()

        set_fn, get_fn = self._resolve_setget_functions()
        get_fn.restype = ctypes.c_void_p
        get_fn.argtypes = [wintypes.HWND, ctypes.c_int]
        set_fn.restype = ctypes.c_void_p
        set_fn.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

        # DragAcceptFiles/DragQueryFileW/DragFinishはいずれもshell32.dll側の
        # export(user32.dllではない、shellapi.h宣言)。
        self._shell32.DragAcceptFiles(self._hwnd, wintypes.BOOL(True))
        new_proc_ptr = ctypes.cast(self._new_proc, ctypes.c_void_p)
        self._orig_proc = set_fn(self._hwnd, GWLP_WNDPROC, new_proc_ptr)

    def _configure_bindings(self) -> None:
        """全関数のargtypes/restypeを明示する。既定(未指定)のctypesは
        引数をc_int(32bit)とみなすため、64bit環境のポインタ/ハンドル値
        (SetWindowLongPtrWの戻り値やGlobalAlloc由来のHDROP)を渡すと
        `OverflowError: int too long to convert`で毎回失敗する
        (2026-08-02実測: CallWindowProcWの引数型未指定により、D&D以外の
        通常ウィンドウメッセージも含め**全メッセージ**が例外→無視され、
        ウィンドウがフリーズする重大バグとして発現した。手動確認で発見)。"""
        self._shell32.DragAcceptFiles.restype = None
        self._shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

        self._shell32.DragQueryFileW.restype = wintypes.UINT
        self._shell32.DragQueryFileW.argtypes = [
            wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT,
        ]

        self._shell32.DragFinish.restype = None
        self._shell32.DragFinish.argtypes = [wintypes.HANDLE]

        self._user32.CallWindowProcW.restype = ctypes.c_long
        self._user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
        ]

    def _resolve_setget_functions(self):
        # 64bit環境ではSetWindowLongPtrW/GetWindowLongPtrWを使う必要がある
        # (SetWindowLongWはLONG(32bit)切り詰めでポインタを壊す)。
        # 32bit Python(稀)ではSetWindowLongPtrW自体が存在しないため
        # SetWindowLongWへフォールバックする。
        if hasattr(self._user32, "SetWindowLongPtrW"):
            return self._user32.SetWindowLongPtrW, self._user32.GetWindowLongPtrW
        return self._user32.SetWindowLongW, self._user32.GetWindowLongW

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                self._handle_drop(wparam)
            except Exception:  # noqa: BLE001 -- D&D1回の失敗でウィンドウを壊さない
                pass
            return 0
        return self._user32.CallWindowProcW(self._orig_proc, hwnd, msg, wparam, lparam)

    def _handle_drop(self, hdrop) -> None:
        paths = self._query_dropped_files(hdrop)
        self._shell32.DragFinish(hdrop)
        path = pick_dropped_path(paths)
        if path is not None:
            self._on_path(path)
        elif self._on_rejected is not None:
            self._on_rejected()

    def _query_dropped_files(self, hdrop) -> list[str]:
        """DragQueryFileW(shell32)でドロップされた全ファイルパスを取り出す。
        pick_dropped_pathが先頭しか見なくても、C#の`(string[])e.Data.GetData(...)`
        相当を忠実に再現するため全件取得しておく(将来の拡張・デバッグログ用)。"""
        count = self._shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        paths: list[str] = []
        for i in range(count):
            needed = self._shell32.DragQueryFileW(hdrop, i, None, 0)
            buf = ctypes.create_unicode_buffer(needed + 1)
            self._shell32.DragQueryFileW(hdrop, i, buf, needed + 1)
            paths.append(buf.value)
        return paths

    def close(self) -> None:
        """後始末: サブクラス化を解除する(ウィンドウ破棄前に呼ぶのが望ましいが、
        Tkのウィンドウ破棄時にHWND自体が無効化されるため必須ではない)。"""
        if self._orig_proc is None:
            return
        set_fn, _get_fn = self._resolve_setget_functions()
        set_fn.restype = ctypes.c_void_p
        set_fn.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        try:
            set_fn(self._hwnd, GWLP_WNDPROC, self._orig_proc)
        except OSError:
            pass
        self._orig_proc = None


def install(
    widget,
    on_path: Callable[[str], None],
    on_rejected: Optional[Callable[[], None]] = None,
) -> Optional[DropTarget]:
    """tkinterウィジェット(通常はroot/Toplevel)へD&Dを配線するヘルパー。
    非Windows環境ではNoneを返すだけで何もしない(呼び出し側は戻り値がNoneの
    ときD&D無効として扱ってよい)。"""
    if not is_supported():
        return None
    hwnd = widget.winfo_id()
    return DropTarget(hwnd, on_path, on_rejected)
