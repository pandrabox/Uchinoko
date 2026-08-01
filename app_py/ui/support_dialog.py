# support_dialog.py -- 問い合わせダイアログ(旧 ShowSupportDialog、独立Toplevel)。
#
# 移植元: app\DiveToPalworld.cs ShowSupportDialog() (L.4462-4661)。
# 3段状態遷移(第1段=説明/第2段=編集可能な送信内容確認/第3段=送信済み)+
# 再送ロジック(dev#42b、inquiry.normalize_log_for_comparisonでの比較)を
# そのまま踏襲する(DESIGN.md §2.5)。
#
# 依存の分離(WP-A5のスコープが inquiry.py + support_dialog.py のみで
# main_window.py に触れられないため): C#版はMainFormのフィールド
# (vrmBox/statusLabel/reportId/reportViewUrl/lastSentBaseLog)に直接アクセス
# していたが、Python版は下記2つに分離した:
#   - SupportContext: 呼び出し元(将来のMainWindow)が提供する値・コールバック
#     (§2.5契約の材料一式。読むだけで書き換えない)
#   - SupportDialogState: reportId/reportViewUrl/lastSentBaseLog相当の可変状態。
#     アプリ実行中はダイアログを閉じても引き継がれるべき値なので、呼び出し元が
#     1個だけ保持してshow_support_dialog()へ毎回渡す想定
# main_window.pyへのボタン結線(reportButton.Click)自体は統合WPで行う
# (このWPは支援ダイアログ単体の完成まで)。
#
# 非同期送信は DESIGN.md §4.3 の推奨どおり threading.Thread + ポーリング
# (Tkの`after()`)方式(C#のThreadPoolExecutor+BeginInvokeに相当)。
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field
from typing import Callable, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import inquiry  # noqa: E402


@dataclass
class SupportDialogState:
    """MainFormのreportId/reportViewUrl/lastSentBaseLogフィールド (L.4613-4619等)
    相当。アプリ実行中は引き継がれる可変状態なので、呼び出し元が1個保持する。"""

    report_id: Optional[str] = None
    report_view_url: Optional[str] = None
    last_sent_base_log: Optional[str] = None


@dataclass
class SupportContext:
    """呼び出し元が提供する値・コールバック(§2.5契約の材料一式+副作用の委譲)。
    tool_version/lang/channelはUI状態から都度計算する軽い値のため、C#同様
    呼び出し時点の値をそのまま渡す設計(ダイアログ内で変化を追跡しない)。"""

    tool_version: str
    lang: str  # 契約の"lang"フィールド値(ja|en|ko|zh-TW|zh-CN)
    channel: str  # booth|itch|github|dev|unknown
    get_os_description: Callable[[], str]
    get_avatar_name: Callable[[], str]
    get_status_text: Callable[[], str]
    build_diagnostics_text: Callable[[], str]
    append_log: Callable[[str], None] = field(default=lambda msg: None)
    copy_to_clipboard: Optional[Callable[[str], None]] = None
    open_url: Callable[[str], None] = field(default=webbrowser.open)
    base_url: Optional[str] = None  # テスト/オフライン縮退用のD2P_REPORT_BASEURL相当
    transport: Optional[inquiry.Transport] = None  # 送信レイヤのモック差し替え(実送信禁止の試験用)


def _resolve_log_font() -> tuple:
    """ResolveLogFont (L.611-642) の簡略版。tkinter既定の等幅フォントで足りるため
    GDIグリフ存在判定のような特別なフォールバックは行わない(§1.1-#16の難度表
    どおり、ここはtkinter標準APIで済む部分)。"""
    return ("Consolas", 9)


def show_support_dialog(parent: tk.Misc, state: SupportDialogState, ctx: SupportContext) -> tk.Toplevel:
    """ShowSupportDialog (L.4462-4661) 相当。呼び出しごとにToplevelを1個作る
    (C#版もローカル変数のFormを毎回newしている)。"""
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("BtnReport"))
    dlg.resizable(False, False)
    dlg.geometry("520x340")
    dlg.transient(parent)

    # ---- 第1段: 説明 + 開始ボタン ----
    stage1 = tk.Frame(dlg, width=496, height=280)
    info_label = tk.Label(stage1, text=i18n.S("SupportStage1Info"), justify="left", anchor="nw", wraplength=464)
    info_label.place(x=8, y=8, width=464, height=90)
    open_form_btn = tk.Button(stage1, text=i18n.S("BtnOpenInquiryForm"))
    open_form_btn.place(x=8, y=106, width=240, height=34)

    # ---- 第2段: 送信内容の確認(編集可能) ----
    stage2 = tk.Frame(dlg, width=496, height=280)
    confirm_label = tk.Label(stage2, text="", justify="left", anchor="nw", wraplength=464)
    confirm_label.place(x=8, y=8, width=464, height=72)
    log_edit_box = tk.Text(stage2, wrap="word", font=_resolve_log_font())
    log_edit_box.place(x=8, y=84, width=464, height=136)
    ok_btn = tk.Button(stage2, text=i18n.S("BtnOk"))
    ok_btn.place(x=8, y=226, width=100, height=32)
    stage2_status_lbl = tk.Label(stage2, text="", anchor="w")
    stage2_status_lbl.place(x=116, y=230, width=356, height=24)

    # ---- 第3段: 送信済み(いつでも同じ場所を開ける+手動再送) ----
    stage3 = tk.Frame(dlg, width=496, height=280)
    sent_label = tk.Label(stage3, text="", justify="left", anchor="nw", wraplength=464)
    sent_label.place(x=8, y=8, width=464, height=50)
    sent_url_box = tk.Entry(stage3)
    sent_url_box.place(x=8, y=64, width=464, height=24)
    open_again_btn = tk.Button(stage3, text=i18n.S("BtnOpenSamePlace"))
    open_again_btn.place(x=8, y=100, width=200, height=32)
    resend_btn = tk.Button(stage3, text=i18n.S("BtnResendLog"))
    resend_btn.place(x=8, y=140, width=200, height=32)

    # ---- 常設(全段で表示): ログ手動コピー + 閉じる ----
    copy_log_btn = tk.Button(dlg, text=i18n.S("BtnCopyLogManually"))
    copy_log_btn.place(x=12, y=300, width=160, height=28)
    close_btn = tk.Button(dlg, text=i18n.S("BtnClose"), command=dlg.destroy)
    close_btn.place(x=396, y=300, width=112, height=28)

    def do_copy_log() -> None:
        masked = inquiry.sanitize_for_clipboard(ctx.build_diagnostics_text())
        if ctx.copy_to_clipboard is not None:
            ctx.copy_to_clipboard(masked or "")
        else:
            dlg.clipboard_clear()
            dlg.clipboard_append(masked or "")

    copy_log_btn.config(command=do_copy_log)

    def show_stage(which: tk.Frame) -> None:
        for frame in (stage1, stage2, stage3):
            frame.place_forget()
        which.place(x=12, y=12, width=496, height=280)

    def show_sent_stage(report_id: Optional[str], view_url: Optional[str]) -> None:
        sent_label.config(text=i18n.F("SupportSentLabelFormat", report_id))
        sent_url_box.delete(0, tk.END)
        sent_url_box.insert(0, view_url or "")
        show_stage(stage3)

    def show_confirm_stage(changed_notice: bool, is_append: bool) -> None:
        diag_text = ctx.build_diagnostics_text()
        log_edit_box.delete("1.0", tk.END)
        log_edit_box.insert("1.0", diag_text)
        notice = i18n.S("SupportChangedNotice") if changed_notice else ""
        body = i18n.S("SupportConfirmAppendBody") if is_append else i18n.S("SupportConfirmNewBody")
        confirm_label.config(text=notice + body)
        show_stage(stage2)
        stage2_status_lbl.config(text="")
        ok_btn.config(state="normal")
        log_edit_box.config(state="normal")

    def open_url_safe(url: str) -> None:
        try:
            ctx.open_url(url)
        except Exception as ex:  # noqa: BLE001 -- C#版も握りつぶしてログにだけ残す
            ctx.append_log("[report] ページを開けませんでした: " + str(ex))

    open_form_btn.config(command=lambda: show_confirm_stage(False, False))
    resend_btn.config(command=lambda: show_confirm_stage(False, True))
    open_again_btn.config(command=lambda: open_url_safe(sent_url_box.get()))

    def on_ok() -> None:
        edited_log = log_edit_box.get("1.0", "end-1c")
        try:
            payload, _masked_log = inquiry.build_report_payload_json(
                version=ctx.tool_version,
                lang=ctx.lang,
                os_description=ctx.get_os_description(),
                avatar_name=ctx.get_avatar_name(),
                status_text=ctx.get_status_text(),
                channel=ctx.channel,
                log_text=edited_log,
            )
        except Exception as ex:  # noqa: BLE001
            ctx.append_log("[report] 送信データの作成に失敗: " + str(ex))
            stage2_status_lbl.config(text=i18n.S("SupportSendFailedUseManualCopy"))
            return

        # dev#42b: 既にreportIdがあれば「再送=追記」、無ければ「新規」
        append_target_id = state.report_id or None
        ok_btn.config(state="disabled")
        log_edit_box.config(state="disabled")
        stage2_status_lbl.config(text=i18n.S("SupportSending"))

        result_box: list = []

        def worker() -> None:
            res = inquiry.send_report_payload(
                payload,
                append_target_id,
                base_url=ctx.base_url,
                tool_version=ctx.tool_version,
                transport=ctx.transport,
            )
            result_box.append(res)

        threading.Thread(target=worker, daemon=True).start()

        def poll() -> None:
            if not result_box:
                dlg.after(100, poll)
                return
            res = result_box[0]
            if res.ok:
                ctx.append_log(f"[report] 送信完了 報告ID: {res.id} {res.view_url}")
                state.report_id = res.id
                state.report_view_url = res.view_url
                # dev#42b: 次回の変化検出用に「その時点の素の診断文」を保存する
                # (ユーザー編集後のedited_logではなく、いま改めて生成した素の文)
                state.last_sent_base_log = ctx.build_diagnostics_text()
                show_sent_stage(res.id, res.view_url)
                open_url_safe(res.view_url or "")
            else:
                ctx.append_log("[report] 送信できませんでした: " + str(res.error))
                stage2_status_lbl.config(text=i18n.S("SupportSendFailedOffline"))
                ok_btn.config(state="normal")
                log_edit_box.config(state="normal")

        dlg.after(100, poll)

    ok_btn.config(command=on_ok)

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    # dev#42b: 未送信→第1段(既定表示) / 送信済み・ログ不変→第3段 /
    # 送信済み・ログ変化→第2段を直接表示(再送が既定)
    if state.report_view_url:
        current_log = ctx.build_diagnostics_text()
        log_changed = (
            state.last_sent_base_log is None
            or inquiry.normalize_log_for_comparison(current_log)
            != inquiry.normalize_log_for_comparison(state.last_sent_base_log)
        )
        if log_changed:
            show_confirm_stage(True, True)
        else:
            show_sent_stage(state.report_id, state.report_view_url)
    else:
        show_stage(stage1)

    return dlg
