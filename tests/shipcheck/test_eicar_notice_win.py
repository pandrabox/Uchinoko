# -*- coding: utf-8 -*-
r"""devtools\eicar_notice_win.py(dev#624 msgbox通知の実体、Pure Python)の単体試験。

2026-08-01 Masterライターレビュー指摘により、当初PowerShell側にあった
Add-Type+P/Invoke+Timer+MessageBox.Showのロジックをこちらへ全面移設した
(CLAUDE.md言語方針「殻(Pythonを呼ぶだけの数行・ASCIIのみ)以外のps1を
新規に書かない」対応)。

**重要(2026-08-01オーナー緊急裁定「ホスト画面への一切の干渉禁止」)**:
このテストファイルは一度も本物の `ctypes.windll.user32` を呼ばない。
モジュール属性 `user32` を都度フェイクへ差し替え、ロジック
(引数の受け渡し・スレッド起動順序・例外の握り潰し)のみを検証する。
"""
import importlib
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)


def _import_module():
    return importlib.import_module("eicar_notice_win")


class FakeUser32:
    """実Windows APIを一切呼ばないフェイク。"""

    def __init__(self, find_result=12345):
        self.find_result = find_result
        self.message_box_calls = []
        self.find_window_calls = []
        self.post_message_calls = []

    def MessageBoxW(self, hwnd, message, title, flags):
        self.message_box_calls.append((message, title, flags))
        return 1

    def FindWindowW(self, cls, title):
        self.find_window_calls.append(title)
        return self.find_result

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.post_message_calls.append((hwnd, msg, wparam, lparam))
        return True


class RaisingUser32:
    def FindWindowW(self, cls, title):
        raise OSError("no window API in this fake")

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        raise OSError("unreachable")

    def MessageBoxW(self, hwnd, message, title, flags):
        raise OSError("unreachable")


# =====================================================================
# show_notice: MessageBoxWへの結線
# =====================================================================

def test_show_notice_calls_message_box_with_title_and_message(monkeypatch):
    """2026-08-01 CI赤で判明: show_notice()が起動する自動クローズ用の
    バックグラウンドスレッド(auto_close_after_timeout)を待たずにテストが
    終わると、monkeypatchのteardown後(=mod.user32が別の値に戻された後、
    あるいは後続テストが別のFakeUser32へ差し替えた後)にそのスレッドが
    実行され、user32(モジュールグローバル、呼び出し時点の値を都度参照)への
    呼び出しが後続テスト(同じ"タイトル"を使うtest_auto_close_after_timeout_*)
    のfakeへ紛れ込む競合が起きうる(実測: GitHub ActionsのCIで
    find_window_callsに'タイトル'が2件記録される形で顕在化)。
    test_show_notice_starts_auto_close_timer_thread と同じ手当て(Threadを
    RecordingThreadで差し替えてjoinする)をこちらにも入れ、このテストが
    戻る前にスレッドを完了させることで競合を断つ。"""
    mod = _import_module()
    fake = FakeUser32()
    monkeypatch.setattr(mod, "user32", fake)

    started_threads = []
    real_thread_cls = threading.Thread

    class RecordingThread(real_thread_cls):
        def start(self):
            started_threads.append(self)
            super().start()

    monkeypatch.setattr(threading, "Thread", RecordingThread)

    mod.show_notice("タイトル", "本文テキスト", timeout_ms=1)

    assert fake.message_box_calls == [("本文テキスト", "タイトル", mod.MB_OK)]
    assert len(started_threads) == 1
    started_threads[0].join(timeout=2)


def test_show_notice_starts_auto_close_timer_thread(monkeypatch):
    """MessageBoxWの呼び出し前に、自動クローズ用のスレッドが起動されること
    (非ブロッキング=承認を待たない自動クローズの結線確認)。"""
    mod = _import_module()
    fake = FakeUser32()
    monkeypatch.setattr(mod, "user32", fake)

    started_threads = []
    real_thread_cls = threading.Thread

    class RecordingThread(real_thread_cls):
        def start(self):
            started_threads.append(self)
            super().start()

    monkeypatch.setattr(threading, "Thread", RecordingThread)

    mod.show_notice("t", "m", timeout_ms=1)

    assert len(started_threads) == 1
    assert started_threads[0].daemon is True
    started_threads[0].join(timeout=2)


# =====================================================================
# auto_close_after_timeout: FindWindowW + PostMessageW(WM_CLOSE)
# =====================================================================

def test_auto_close_after_timeout_finds_window_and_posts_close(monkeypatch):
    mod = _import_module()
    fake = FakeUser32(find_result=999)
    monkeypatch.setattr(mod, "user32", fake)

    mod.auto_close_after_timeout("タイトル", timeout_ms=1)

    assert fake.find_window_calls == ["タイトル"]
    assert fake.post_message_calls == [(999, mod.WM_CLOSE, 0, 0)]


def test_auto_close_after_timeout_noop_when_window_not_found(monkeypatch):
    mod = _import_module()
    fake = FakeUser32(find_result=0)
    monkeypatch.setattr(mod, "user32", fake)

    mod.auto_close_after_timeout("タイトル", timeout_ms=1)

    assert fake.find_window_calls == ["タイトル"]
    assert fake.post_message_calls == []


def test_auto_close_after_timeout_swallows_exceptions(monkeypatch):
    """API呼び出し自体が失敗しても例外を外へ漏らさない(通知プロセス自身の
    都合であり、検査本体には一切影響させない設計)。"""
    mod = _import_module()
    monkeypatch.setattr(mod, "user32", RaisingUser32())

    mod.auto_close_after_timeout("タイトル", timeout_ms=1)  # 例外を送出しなければOK


# =====================================================================
# main: JSONペイロードの読み取り→show_noticeへの結線
# =====================================================================

def test_main_reads_payload_and_calls_show_notice(tmp_path, monkeypatch):
    mod = _import_module()
    calls = []
    monkeypatch.setattr(
        mod, "show_notice",
        lambda title, message, timeout_ms: calls.append((title, message, timeout_ms)))

    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps({"title": "T", "message": "M", "timeout_ms": 5000}, ensure_ascii=False),
        encoding="utf-8")

    rc = mod.main(["eicar_notice_win.py", str(payload_path)])

    assert rc == 0
    assert calls == [("T", "M", 5000)]


def test_main_returns_error_code_when_payload_arg_missing():
    mod = _import_module()
    rc = mod.main(["eicar_notice_win.py"])
    assert rc == 2
