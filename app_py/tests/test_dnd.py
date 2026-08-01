# test_dnd.py -- WP-A8受入条件①: 拡張子フィルタ・複数ファイル選択規則の
# pytest(dev#532 方針A、DESIGN.md §1.1-#4 / §6-2)。
#
# 対象は app_py\ui\dnd.py の純粋ロジック(pick_dropped_path/is_prefab_path)と、
# Win32メッセージ層(DropTarget._handle_drop/_query_dropped_files)を
# shell32/user32呼び出しをモックして検証する部分。実際のOSドラッグ操作・
# 実ウィンドウ作成は行わない(タスク指示「Win32メッセージ層はモック」)。
#
# 期待値は app\DiveToPalworld.cs L.1401-1431(OnDragEnter/OnDragDrop)の
# 挙動と1:1: 拡張子は.vrm/.fbx/.prefab(大小文字無視)のみ、複数ファイルは
# 常に先頭の1件だけを見る(2件目以降の中身は判定に一切影響しない)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import dnd  # noqa: E402

# ---------------------------------------------------------------------------
# pick_dropped_path: 拡張子フィルタ
# ---------------------------------------------------------------------------


def test_accepts_vrm():
    assert dnd.pick_dropped_path([r"C:\a\model.vrm"]) == r"C:\a\model.vrm"


def test_accepts_fbx():
    assert dnd.pick_dropped_path([r"C:\a\model.fbx"]) == r"C:\a\model.fbx"


def test_accepts_prefab():
    assert dnd.pick_dropped_path([r"C:\a\Avatar.prefab"]) == r"C:\a\Avatar.prefab"


def test_extension_check_is_case_insensitive():
    assert dnd.pick_dropped_path([r"C:\a\MODEL.VRM"]) == r"C:\a\MODEL.VRM"
    assert dnd.pick_dropped_path([r"C:\a\Model.Prefab"]) == r"C:\a\Model.Prefab"


def test_rejects_unsupported_extension():
    assert dnd.pick_dropped_path([r"C:\a\readme.txt"]) is None
    assert dnd.pick_dropped_path([r"C:\a\model.fbxx"]) is None
    assert dnd.pick_dropped_path([r"C:\a\noext"]) is None


def test_rejects_empty_list():
    assert dnd.pick_dropped_path([]) is None


def test_rejects_empty_string_first_element():
    # C#側の `files.Length > 0 ? files[0] : ""` が空文字列を渡すケースに相当
    # (files配列自体は0要素ではないが先頭が空、という状況はshell32からは
    # 通常発生しないが、念のためC#と同じフェイルセーフ動作を確認する)
    assert dnd.pick_dropped_path([""]) is None


# ---------------------------------------------------------------------------
# 複数ファイル選択規則: 常に先頭の1件だけを見る(C#の files[0] そのまま)
# ---------------------------------------------------------------------------


def test_multiple_files_returns_only_first_when_valid():
    result = dnd.pick_dropped_path([r"C:\a\first.vrm", r"C:\a\second.vrm", r"C:\a\third.vrm"])
    assert result == r"C:\a\first.vrm"


def test_multiple_files_ignores_second_even_if_invalid():
    # 1件目が有効なら、2件目が非対応拡張子でも採用結果に影響しない
    result = dnd.pick_dropped_path([r"C:\a\first.vrm", r"C:\a\second.exe"])
    assert result == r"C:\a\first.vrm"


def test_multiple_files_rejected_when_first_invalid_even_if_second_valid():
    # C#は2件目を一切見ないため、1件目が拒否対象なら全体として不採用になる
    result = dnd.pick_dropped_path([r"C:\a\first.exe", r"C:\a\second.vrm"])
    assert result is None


# ---------------------------------------------------------------------------
# is_prefab_path
# ---------------------------------------------------------------------------


def test_is_prefab_path_true_for_prefab():
    assert dnd.is_prefab_path(r"C:\a\Avatar.prefab") is True
    assert dnd.is_prefab_path(r"C:\a\Avatar.PREFAB") is True


def test_is_prefab_path_false_for_vrm_or_fbx():
    assert dnd.is_prefab_path(r"C:\a\model.vrm") is False
    assert dnd.is_prefab_path(r"C:\a\model.fbx") is False


# ---------------------------------------------------------------------------
# Win32メッセージ層(モック): DropTarget._handle_drop / _query_dropped_files
# ---------------------------------------------------------------------------


class _FakeShell32:
    """shell32.DragQueryFileW/DragFinish の最小モック。実HWND/実ドラッグ操作
    には触れない(タスク指示「Win32メッセージ層はモック」)。"""

    def __init__(self, files: list[str]):
        self.files = files
        self.finish_called_with = None

    def DragQueryFileW(self, hdrop, index, buf, buf_size):
        if index == 0xFFFFFFFF:
            return len(self.files)
        text = self.files[index]
        if buf is None:
            return len(text)
        # ctypes.create_unicode_bufferへ書き込む実際のAPIはbuf.value代入で
        # 模擬する(本物のDragQueryFileWはbufへ直接書き込むが、テストでは
        # 呼び出し側のcreate_unicode_bufferオブジェクトを直接操作すれば足りる)
        buf.value = text
        return len(text)

    def DragFinish(self, hdrop):
        self.finish_called_with = hdrop


def _make_drop_target(files: list[str], on_rejected_calls: list | None = None):
    """__init__の実Win32呼び出し(DragAcceptFiles/SetWindowLongPtrW)を経由せず、
    _handle_drop/_query_dropped_filesだけを検証するためのテスト専用生成。"""
    target = object.__new__(dnd.DropTarget)
    target._shell32 = _FakeShell32(files)
    received: list[str] = []
    target._on_path = received.append
    if on_rejected_calls is None:
        on_rejected_calls = []
    target._on_rejected = lambda: on_rejected_calls.append(True)
    return target, received, on_rejected_calls


def test_query_dropped_files_reads_all_paths_via_dragqueryfilew():
    target, _received, _rejected = _make_drop_target([r"C:\a\one.vrm", r"C:\a\two.vrm"])
    paths = target._query_dropped_files(hdrop=1234)
    assert paths == [r"C:\a\one.vrm", r"C:\a\two.vrm"]


def test_handle_drop_calls_on_path_for_accepted_file():
    target, received, rejected = _make_drop_target([r"C:\a\model.vrm"])
    target._handle_drop(hdrop=1234)
    assert received == [r"C:\a\model.vrm"]
    assert rejected == []
    assert target._shell32.finish_called_with == 1234


def test_handle_drop_calls_on_rejected_for_unsupported_extension():
    target, received, rejected = _make_drop_target([r"C:\a\readme.txt"])
    target._handle_drop(hdrop=1234)
    assert received == []
    assert rejected == [True]


def test_handle_drop_multiple_files_uses_first_only():
    target, received, rejected = _make_drop_target([r"C:\a\first.vrm", r"C:\a\second.exe"])
    target._handle_drop(hdrop=1234)
    assert received == [r"C:\a\first.vrm"]
    assert rejected == []


def test_handle_drop_calls_dragfinish_even_on_rejection():
    target, _received, _rejected = _make_drop_target([r"C:\a\readme.txt"])
    target._handle_drop(hdrop=5678)
    assert target._shell32.finish_called_with == 5678
