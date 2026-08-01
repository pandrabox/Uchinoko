# main_window.py -- MainWindow(旧 app\DiveToPalworld.cs の MainForm 相当)の骨格。
#
# dev#532 方針A WP-A1: DESIGN.md(C:\P\Work\DiveToPalworld\work\wp532A\DESIGN.md)
# §1.1 の全25画面要素を配置するだけの「骨格」。イベントハンドラは全部stubで、
# クリックしても実処理はせず、ログ欄へ「未実装」と出すだけ(_stub()参照)。
# 実処理の結線はWP-A2〜A6が担当する(DESIGN.md §5.2)。
#
# レイアウトはDESIGN.md §4.2の方針どおり絶対座標(tkinterのplace())を踏襲する。
# 座標値はDiveToPalworld.csコンストラクタ(L.903-1306)のLeft/Top/Width実測値を
# 転記したもの(convertButton幅などC#側で実測フォント幅により動的に変わる値は
# 固定近似値へ寄せている)。指揮者裁定により本WP(基盤)では見た目の作り込みは
# 求められていない(「見た目チープ容認」)ため、pixel-perfect一致は狙っていない。
#
# 依存モジュールの解決: このファイルは `python app_py\main.py` から
# `from ui.main_window import MainWindow` の形でimportされる想定で、main.pyが
# 先に app_py ディレクトリを sys.path へ入れるため、ここでは素朴に
# `import i18n` / `import settings` の絶対importで足りる(相対importは
# main.pyを直接スクリプト実行する受入条件①と相性が悪いため使わない)。
#
# dev#532 方針A WP-A2(2026-08-01): 変換系ハンドラの結線。convertButton/
# cancelButton/matsButton/previewButtonをpipeline_runner.py(WriteJob/
# BuildConvertArgs/FindPwsh/RunPipeline相当)へ実配線する。書き込み許可
# (DESIGN.md §5.2 WP-A2行)は「main_window.pyの該当ハンドラ部分のみ」のため、
# ウィジェット生成(_build_widgets)自体はWP-A1のまま変更していない
# (コマンド差し替え1行+ハンドラメソッド追加のみ)。
# browse/D&D経由のSetVrm本体(セッションログ復元・以前のjob.json設定復元)は
# 「変換系」の外側(WP-A1の骨格が持たない未実装領域)であり、本WPでは
# 「vrmBoxへパスを入れて変換を開始できる状態にする」最小限のみ扱う
# 〈合理的解釈〉。prefab選択時のRunUnityExport起動はconvertButton系の
# 前段としてWP-A2で結線し、完了後にそのまま同じ最小SetVrmへ引き継ぐ。
#
# dev#532 方針A WP-A8(2026-08-02): D&D(#4)の実配線。ui\dnd.py(ctypes+
# Win32 API自前実装、外部バイナリ非同梱)をrootウィンドウ全体へ
# インストールする(app\DiveToPalworld.csのAllowDrop=trueがForm全体に
# 掛かっているのと同じ範囲、L.946-948)。受理拡張子・複数ファイル時の
# 挙動(先頭1件のみ判定)はdnd.pick_dropped_path()が持ち、本ファイルは
# 採用/不採用後の分岐(prefabならUnity輸出、それ以外はSetVrm)だけを持つ。

from __future__ import annotations

import json
import os
import platform
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import blender_setup  # noqa: E402
import compat_check  # noqa: E402
import dist_channel  # noqa: E402
import i18n  # noqa: E402
import inquiry  # noqa: E402
import pak_manager  # noqa: E402
import path_health  # noqa: E402
import pipeline_runner  # noqa: E402
import preview_freshness  # noqa: E402
import settings  # noqa: E402
import update_check  # noqa: E402
import warm_startup  # noqa: E402
from ui import dnd  # noqa: E402
from ui import support_dialog  # noqa: E402

# DiveToPalworld.cs L.704 (devtools\release.py がリリース時にスタンプする値。
# WP-A1の骨格では固定値で近似し、実際の版管理はB1/D1側の課題とする)
TOOL_VERSION = "v2.3.1"

# オンラインマニュアルのURL(指揮者裁定: マニュアルを開く導線があれば既定
# ブラウザで開く)。DESIGN.md §1.1の25要素にはマニュアル専用ボタンは含まれて
# いない(現行app\DiveToPalworld.csにも該当ボタンは存在しない、grep実測で
# 確認済み)ため、本WPでは新規ボタンを追加していない。URL定数だけ、他WPが
# ボタンを追加する時にすぐ使えるよう用意しておく
# (公開先: manual\manual.html / manual\manual.en.html、README.mdのリンク参照)。
MANUAL_URL = "https://pandrabox.github.io/DiveToPalworld/manual/manual.html"


def _load_scaled_preview_image(path: str, max_width: int, max_height: int) -> tk.PhotoImage:
    """dev#599: previewFront/previewSide用のPNGをtk.PhotoImageで読み込み、
    表示域(max_width x max_height)に収まるよう整数間引き(subsample)で
    縮小して返す。Pillow/ImageTk等の追加依存は使わない(同梱ランタイム
    res\\python_embedにPillowが無いため、Tk 8.6ネイティブのPNGデコードのみ
    に依存する設計、C#版のLoadImageNoLock+PictureBoxSizeMode.Zoom相当を
    tkinterの手段で再現したもの)。

    失敗時(ファイル無し・壊れPNG・Tk側のTclError等)は例外をそのまま呼び出し
    元へ伝播させる(フォールバック処理は呼び出し元の責務、_set_preview_widget
    参照)。

    subsampleは整数倍率でしか縮小できない(非整数倍率や拡大はできない)ため、
    「表示域に収まる」ことを保証する最小の整数倍率を切り上げ計算で求める。
    例: 700x1000のPNGを380x360の表示域に収める場合、
    ceil(700/380)=2, ceil(1000/360)=3 → 大きい方の3を採用し233x333になる。
    """
    img = tk.PhotoImage(file=path)
    width, height = img.width(), img.height()
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid image dimensions: {width}x{height}")
    factor = 1
    if max_width > 0 and width > max_width:
        factor = max(factor, -(-width // max_width))  # ceil division
    if max_height > 0 and height > max_height:
        factor = max(factor, -(-height // max_height))  # ceil division
    if factor > 1:
        img = img.subsample(factor, factor)
    return img


class _ToolTip:
    """簡易ツールチップ(DiveToPalworld.csのToolTip.SetToolTip相当の最小実装)。
    tkinterに標準のツールチップ機構が無いための自前実装。i18n.register()の
    setter経由で言語切替時にも文言が更新される。"""

    def __init__(self, widget: tk.Widget):
        self.widget = widget
        self.text = ""
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text

    def _show(self, _event=None) -> None:
        if not self.text or self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        try:
            self._tip.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        label = tk.Label(
            self._tip, text=self.text, background="#ffffe0",
            relief="solid", borderwidth=1, padx=4, pady=2, justify="left",
        )
        label.pack()

    def _hide(self, _event=None) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class MainWindow:
    """旧MainForm相当。DESIGN.md §1.1の全25要素をplace()で配置する。

    `self.widgets` は各要素をDESIGN.md §1.1の行番号順に名前で引けるようにした
    lookup簿(受入条件③用)。C#の元フィールド名(vrmBox/convertButton等)を
    そのままキーに使い、DESIGN.mdとの対応を追いやすくしてある。
    """

    def __init__(self, root: tk.Tk, app_root: str | None = None):
        self.root = root
        self.app_root = app_root or _APP_PY_DIR
        self.work_root = self._resolve_work_root()
        self.widgets: dict[str, object] = {}
        self._tooltips: list[_ToolTip] = []

        # ---- WP-A2: 変換系の内部状態 ----
        # DiveToPalworld.cs L.1042-1046「内部互換性のためにフィールドを初期化
        # (UIには表示しない)」相当。WP-A1骨格にも対応する可視ウィジェットが
        # 無いため、pipeline_runner.write_job()の既定値と同じ初期値をここに持つ
        # (将来、以前のjob.jsonからの復元(SetVrm相当)を実装するWPがこの3つの
        # 属性を上書きすればよい設計にしてある)。
        self._shoulder_offset_deg = 0
        self._merge_fingers = False
        self._unlit = False
        self._force_two_sided = True
        # EnsureLicenseConfirmed() L.2533-2545相当のセッション内フラグ
        # (アバターごとのjob.json復元によるリセットはSetVrm側の担当、WP-A2外)
        self._license_confirmed = False
        # dev#611: silentPreview(DiveToPalworld.cs L.472/2556)相当。自動起動時
        # (アバター登録直後の自動プレビュー)はTrue、手押し(previewButton等)
        # はFalse。現時点の_on_pipeline_exit()には完了ダイアログが無い
        # (PR #610が別途追加予定)ため、このフラグは導入・設定のみ行い、
        # まだどこからも参照しない(brief item2の指示どおり)。
        self._silent_preview = False
        self._active_handle: pipeline_runner.ProcessHandle | None = None
        self._pipeline_warnings: list[str] = []
        # dev#288提案2(早期プレビュー反映)相当。実行のたびFalseへ戻す
        # (_start_pipeline側、earlyPreviewLoadedThisRun L.483相当)。
        self._early_preview_loaded_this_run = False
        # dev#599: previewFront/previewSideへ表示中のtk.PhotoImageへの参照を
        # ここに保持する(Tkの罠対策。Label.config(image=...)はTk内部では
        # 弱参照のみ持つため、Python側の変数が無くなるとGCで画像が消える)。
        self._preview_images: dict[str, tk.PhotoImage] = {}

        # pak管理系(WP-A4、DESIGN.md §2.3)の内部状態。
        # _paks_dir_cache: PaksDir()のインスタンスキャッシュ相当(paksDirCache)。
        # _pak_paths: TreeviewのiidからpakフルパスへのlookupPakList.Items[].Tag相当)。
        # _pak_candidates: identify_applied_pak()に渡す(pakパス, アバター名)列
        # (UpdateAppliedStatusがpakList走査から作る材料と同じ)。
        # _applied_status_gen: 世代番号(古い照合結果を捨てるための世代、appliedStatusGen相当)。
        self._paks_dir_cache: str | None = None
        self._pak_paths: dict[str, str] = {}
        self._pak_candidates: list[tuple[str, str]] = []
        self._applied_status_gen = 0

        # dev#618/#619結線: 起動時診断系の内部状態。
        # _remote_known_good_json: dev#89相当。update_check.check_for_update()が
        # versions.jsonから拾った"palworld_known_good"ブロック(JSON文字列)を
        # ここへキャッシュし、compat_check側の判定にも使う(C#のvolatile
        # remoteKnownGoodJsonフィールド相当。取得前/失敗時/オフライン時はNoneの
        # まま=同梱データのみで判定、安全に縮退)。
        self._remote_known_good_json: str | None = None
        # _pending_update_version: ShowUpdateNotice()のpendingUpdateVersion相当。
        # 現時点では言語切替時の再表示(dev#173相当)は本WPのスコープ外だが、
        # C#と同じ変数を保持しておく(将来の結線が迷わないよう合わせておく)。
        self._pending_update_version: str | None = None

        # Blender準備状態(DESIGN.md §2.2、WP-A3)。C#側の blenderSetupRunning/
        # blenderReady フィールド(コンストラクタ近傍で宣言)相当。
        self._blender_setup_running = False
        self._blender_ready = False
        self._blender_queue: "queue.Queue[tuple]" = queue.Queue()
        # dev#640: run_ensure_blender_setup_process()が起動する子プロセスへの
        # 参照(C#版blenderSetupProcフィールド相当)。GUI終了時に黙ってkillする
        # ため、_blender_setup_worker()からdo_ensure_blender_ready()へ渡す。
        self._blender_setup_process_handle = blender_setup.BlenderSetupProcessHandle()
        # dev#639: UpdateButtonStates()のbusy判定(running)相当。
        # _set_running_ui_state()が更新し、_update_button_states()が参照する。
        self._is_pipeline_running = False

        # 初期言語決定(DetermineInitialLang L.817-831相当。dev#532方針A
        # WP-A11/dev#549でOSロケール自動判定を結線。設定ファイルがあれば
        # 最優先、無ければ i18n.detect_lang_from_culture() でOSのUI言語から
        # 判定する。旧WP-A1骨格の「無ければja固定」簡略実装は、日本語環境
        # 以外のユーザーが初回起動時に常にja表示になる回帰リスクがあった
        # ため置き換えた〈WP-A7調査(dev#549)で発見、報告済みの解消〉)。
        code = settings.load_language_code(self.app_root)
        if code and code in i18n.FILE_CODE_TO_LANG:
            lang = i18n.FILE_CODE_TO_LANG[code]
        else:
            lang = i18n.detect_lang_from_culture(self._current_os_culture_name())
        i18n.clear_registry()
        i18n.set_language(lang)

        root.title(f"Uchinoko for Palworld {TOOL_VERSION} - {i18n.S('TitleSubtitle')}")
        root.geometry("1100x930")
        self._set_window_icon()
        # dev#622: FormClosing(DiveToPalworld.cs L.1292-1305)相当。×ボタンでの
        # 終了をtkinterのWM_DELETE_WINDOWで捕捉する(旧実装はメインウィンドウに
        # 未登録で無警告のまま閉じられていた。子ダイアログ側=support_dialog.pyの
        # 登録は元々存在し、そちらは無関係)。
        self.root.protocol("WM_DELETE_WINDOW", self._on_form_closing)

        # 問い合わせダイアログ(#21)の可変状態(SupportDialogState相当)。
        # アプリ実行中はダイアログを閉じても引き継がれる必要があるため、
        # MainWindowが1個だけ保持する(support_dialog.pyのdocstring参照)。
        self._support_state = support_dialog.SupportDialogState()

        self._build_widgets()
        self._update_window_title()
        self._drop_target: dnd.DropTarget | None = None
        self._setup_drag_and_drop()

        # dev#617/#639: UpdateButtonStates()相当を起動直後に1回反映しておく
        # (_build_widgets()はconvertButton等をstate指定なし=既定"normal"で
        # 生成するため、呼ばないとVRM未選択・Blender未準備のままボタンが
        # 押せてしまう。C#版は起動時のUpdateButtonStates()呼び出し経路で
        # hasVrm=false/blenderReady=falseのため最初からEnabled=falseになって
        # いる)。_set_running_ui_state(False)経由で、convertButton
        # (_refresh_convert_button_freshness、hasVrm/fresh/workRootFailed/
        # blenderReady判定)とmatsButton/previewButton(_update_button_states、
        # busy/blenderReady/hasVrm/workRootFailed判定)の両方が一度に初期化
        # される(#637マージ後の統合、PR #647本文の指示どおり)。
        self._set_running_ui_state(False)

        # RefreshPakList()相当(DiveToPalworld.cs L.899, L.1260)。起動直後に
        # 一覧+適用中判定を populate する(§1.2 #26/#18、WP-A4の結線対象)。
        self._on_refresh_pak_list()

        # Shownデリゲート(DiveToPalworld.cs L.1258-1271)のうち「最後に開いていた
        # VRMを復帰(設定・プレビューも一緒に戻る)」部分(dev#623)。RefreshPakList
        # の直後という順序もC#版どおり。
        self._restore_last_vrm_on_startup()

        # dev#621: workRootFailed(主系・フォールバック先とも書き込み不可)の
        # 検知・ログ・エラーダイアログ・ボタン無効化。ログ欄(self.log_box)と
        # 変換系ボタンが両方とも_build_widgets()完了後でないと存在しないため
        # ここで呼ぶ(CheckPathHealthOnStartupがShownイベント=ウィジェット
        # 生成済みの時点で呼ばれるのと同じ順序関係。C#版もRestoreLastVrm→
        # UpdateButtonStates→...→CheckPathHealthOnStartupの順でShown内に
        # 並んでおり、VRM復帰が先という順序を保つ)。
        self._check_work_root_failed_on_startup()

        # dev#532 D1: 起動時セルフチェック(path_health.py、§1.2 #31相当+
        # 「環境隔離4層」の④)。同期・軽量(ディスクI/O無しのパス比較のみ)
        # なのでUIスレッドで直接呼んでよい。
        self._run_startup_self_check()

        # dev#532 D1: 他MOD検出(CheckOtherModsOnce()相当、§1.2 #30)。
        # ディスクI/O(Paksフォルダ列挙)を伴うため専用バックグラウンドスレッドへ。
        self._check_other_mods_once()

        # dev#620: パス健全性警告(CheckPathHealthOnStartup()相当、§1.2 #31)。
        # 文字列比較のみ(ディスクI/O無し)なのでUIスレッドで直接呼んでよい
        # (_run_startup_self_checkと同じ扱い)。
        self._check_path_health_on_startup()

        # dev#618: Palworldバージョン互換チェック(CheckPalworldVersionOnce()
        # 相当、§1.2 #29)。ディスクI/O(acf読み取り・pakサイズ取得・
        # warm-cache完了待ちの最大5分ポーリング)を伴うため専用バックグラウンド
        # スレッドへ(元実装と同じ設計)。
        self._check_palworld_version_once()

        # dev#619: 起動時更新通知(CheckForUpdateOnStartup()相当、§1.2 #23)。
        # ネットワークI/O(versions.jsonのGET、タイムアウト4秒)を伴うため
        # 専用バックグラウンドスレッドへ(元実装と同じくThreadPool相当)。
        self._check_for_update_once()

        # Shownイベント相当(DESIGN.md §1.2 #28)のうちBlender準備のみ、本WPで
        # 起動直後に非同期発火する(#26/27/29-32の他の起動時処理はA4/A6等の
        # 担当、DESIGN.md §5.2参照)。tkinterのafter()でポーリングを開始してから
        # ワーカースレッドを起こす(DESIGN.md §4.3の定番パターン)。
        self.root.after(100, self._poll_blender_queue)
        self._ensure_blender_ready_on_startup()

    # -- 内部ヘルパー -----------------------------------------------------

    def _set_window_icon(self) -> None:
        """dev#594: py版GUIのウィンドウ/タスクバーアイコンがPython既定の
        ままだった件の解消。旧C#版(app\\)がbuild_app.ps1でexeへ埋め込んで
        いた製品アイコン(ぱん納品、リポジトリ直下 ico\\app.ico、
        git 5d28cda「icon: 新アイコンへ全面置き換え」)と同じ資産を、
        build.py側のres\\へのコピー処理を新設せず、既存の`_copy_app_sources()`
        (app_py\\ツリー全体をres\\app\\へそのままコピーする経路)に相乗りさせる
        形で app_py\\assets\\app.ico として同梱する。このファイル冒頭の
        `_APP_PY_DIR`(dev実行ではapp_py\\、配布実行ではres\\app\\を指す、
        既に両対応済みの定数)からの相対パスで解決するため、開発実行/配布
        実行のどちらでも同じコードで見つかる。
        `root.iconbitmap(default=...)` の `default=` はこのrootから生成される
        子Toplevel(問い合わせダイアログ等)にもアイコンを継承させるための
        指定。失敗(環境依存のTk実装差異等)しても例外を握って続行し、
        アイコンのためにGUI起動自体を止めない(仕様#3)。"""
        icon_path = os.path.join(_APP_PY_DIR, "assets", "app.ico")
        try:
            self.root.iconbitmap(default=icon_path)
        except Exception:  # noqa: BLE001 -- アイコン設定の失敗でGUIを殺さない
            pass

    def _resolve_work_root(self) -> str:
        """WorkRootResolveLogic.Resolve(DiveToPalworld.cs L.6446-6477)相当。
        appRoot\\work への書き込みを試し、失敗すれば%LOCALAPPDATA%\\Uchinoko\\work
        へフォールバックする(DESIGN.md §2.8「外部依存パスの原則」の三点セット
        のうち①②)。

        dev#621: 両方とも書き込めない(稀)場合を明示的に検知できるよう、
        C#版のworkRootFailed/workRootUsedFallback/workRootPrimaryPath/
        workRootFallbackPath/workRootPrimaryError/workRootFallbackError
        フィールド(L.691-696)相当をインスタンス属性として残す(呼び出し元は
        _check_work_root_failed_on_startup()。③探索した場所と判定を全部ログへ、
        の材料もここに揃う)。両方失敗した場合もC#と同じくフォールバック先の
        パス文字列をwork_rootとして返す(下流コードが例外で落ちないようにする
        ためだけの値で、実際には書き込めない。押しても失敗するだけの状態は
        変換系ボタンの無効化で防ぐ)。"""
        primary = os.path.join(self.app_root, "work")
        fallback = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Uchinoko", "work"
        )
        self._work_root_primary_path = primary
        self._work_root_fallback_path = fallback
        self._work_root_used_fallback = False
        self._work_root_failed = False

        def probe(path: str) -> str | None:
            """書き込み可能ならNone、不可なら理由文字列を返す
            (ProbeWorkRootWritable相当)。"""
            try:
                os.makedirs(path, exist_ok=True)
                probe_file = os.path.join(path, ".d2p_write_probe")
                with open(probe_file, "w", encoding="utf-8") as f:
                    f.write("")
                os.remove(probe_file)
                return None
            except OSError as ex:
                return str(ex)

        self._work_root_primary_error = probe(primary)
        if self._work_root_primary_error is None:
            return primary

        self._work_root_fallback_error = probe(fallback)
        if self._work_root_fallback_error is None:
            self._work_root_used_fallback = True
            return fallback

        self._work_root_failed = True
        return fallback

    def _work_root_resolution_line(self) -> str:
        """WorkRootResolutionLine() (DiveToPalworld.cs L.3255-3266) 相当。
        フォールバックが起きた/起きなかったに関わらず必ず1行を返す
        (「成功時にも構造が残らないと診断できない」CLAUDE.md方針)。"""
        if not self._work_root_used_fallback and not self._work_root_failed:
            return f"work_root: {self.work_root} (install location, writable)"
        if self._work_root_used_fallback:
            return (
                f"work_root: {self.work_root} (fallback to a user-writable location; "
                f'install location "{self._work_root_primary_path}" is not writable: '
                f"{self._work_root_primary_error})"
            )
        return (
            f'work_root: {self.work_root} [!] neither the install location ("'
            f'{self._work_root_primary_path}": {self._work_root_primary_error}) nor '
            f'the fallback ("{self._work_root_fallback_path}": '
            f"{self._work_root_fallback_error}) is writable"
        )

    def _check_work_root_failed_on_startup(self) -> None:
        """CheckPathHealthOnStartup()のworkRootFailed部分(DiveToPalworld.cs
        L.3277-3287)相当。汎用パス健全性警告(too-long/UNC/OneDrive、
        表#11・別issue・死んだコードのまま=本WPのスコープ外)とは別枠。

        主系・フォールバック先とも書き込み不可の場合のみ、①ログ記録
        ②エラーダイアログ ③変換系ボタン(convert/mats/preview)の全面無効化
        を行う(UpdateButtonStates L.2486-2491の`!workRootFailed`条件相当。
        py版は継続的なUpdateButtonStatesループを持たないため、ここで一度
        disabledにし、_set_running_ui_state()側でも再度normalへ戻さない
        ガードを入れてある)。"""
        self._log(self._work_root_resolution_line())
        if not self._work_root_failed:
            return
        self._log("[!] " + i18n.S("TitleWorkRootUnwritable"))
        for key in ("convertButton", "matsButton", "previewButton"):
            self.widgets[key].config(state="disabled")
        messagebox.showerror(
            i18n.S("TitleWorkRootUnwritable"),
            i18n.F(
                "MsgWorkRootUnwritableFormat",
                self._work_root_primary_path,
                self._work_root_fallback_path,
            ),
        )

    def _current_os_culture_name(self) -> str | None:
        """CultureInfo.CurrentUICulture.Name相当(L.830で渡される実際の値)。
        i18n.detect_lang_from_culture()は文字列入力のみに依存する純関数なので、
        「実際のOS言語をどう取得するか」という環境依存部分はここに切り出す
        (DetermineInitialLangがMainForm側でCultureInfoへ直接アクセスしていた
        のと同じ役割分担、DESIGN.md §4.4参照)。取得できなければNone
        (detect_lang_from_cultureはNone/空文字をenへ倒す設計)。"""
        try:
            import ctypes

            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                lcid = windll.kernel32.GetUserDefaultUILanguage()
                import locale as _locale

                name = _locale.windows_locale.get(lcid)
                if name:
                    return name.replace("_", "-")
        except Exception:
            pass
        try:
            import locale as _locale

            loc = _locale.getdefaultlocale()[0]
            if loc:
                return loc.replace("_", "-")
        except Exception:
            pass
        return None

    def _restore_last_vrm_on_startup(self) -> None:
        """Shownデリゲート(DiveToPalworld.cs L.1258-1271)のうち以下の部分相当
        (dev#623):
        ```
        string f = LastVrmFile();
        if (File.Exists(f)) {
            string last = File.ReadAllText(f, Encoding.UTF8).Trim();
            if (File.Exists(last)) SetVrm(last);
        }
        ```
        settings_lastvrm.txtに記録があり、かつそのファイルがまだ実在する時
        だけ、通常の_set_vrm_path経路(browse/D&Dと同じ入口)へそのまま流す
        (job.json復元・自動プレビュー判定も同じ経路で効く。C#版もSetVrm(last)
        を呼ぶだけで別処理を持たない、L.1268)。ファイルが既に無ければ何も
        しない(File.Exists(last)相当)。例外はtry/catch(Exception) L.1262/1271
        と同じくGUI起動自体を止めずに握る。"""
        try:
            last_vrm = settings.load_last_vrm(self.app_root)
            if last_vrm and os.path.isfile(last_vrm):
                self._set_vrm_path(last_vrm)
        except Exception as ex:  # noqa: BLE001 -- L.1262/1271相当、GUI起動を止めない
            self._log(f"[startup] last vrm restore failed: {ex}")

    def _run_startup_self_check(self) -> None:
        """dev#532 D1: 起動時セルフチェック(path_health.check_runtime_environment
        相当)の結線。判定対象は「実行中のPythonインタプリタが app_root 配下の
        同梱embeddable Pythonか」。

        パッケージ版(`Uchinoko.bat`経由起動、app_root配下に`python_embed\\`が
        存在する)でのみ検査を実行する。開発ソースチェックアウトでの
        `python app_py\\main.py` 直接実行(受入条件①)では`python_embed\\`が
        存在しないため何もしない(=判定対象外。path_health.pyのdocstring
        「情報が渡ってこないケースは黙って動く安全側」の精神を、パッケージ版
        かどうかの判定自体にも適用した合理的解釈。理由: app_root=リポジトリ
        直下となる開発実行では、システムPythonがapp_root配下に無いのは常態で
        あり、これを毎回「エラー」として警告するのは誤検知になる)。"""
        if not os.path.isdir(os.path.join(self.app_root, "python_embed")):
            return
        status = path_health.check_runtime_environment(sys.executable, self.app_root)
        message = path_health.runtime_environment_message(status)
        if message:
            self._log(f"[self-check] {message} (sys.executable={sys.executable})")
            messagebox.showwarning("Uchinoko for Palworld", message)

    def _check_other_mods_once(self) -> None:
        """CheckOtherModsOnce() (DiveToPalworld.cs L.3202-3224) 相当の結線。
        dev#103裁定: 他MODを検出しても変換自体はブロックしない、警告のみ。
        Paksフォルダの列挙(ディスクI/O)を伴うため専用バックグラウンドスレッドで
        実行し、起動直後のUIスレッドを固めない(元実装と同じ設計)。"""

        def worker() -> None:
            try:
                paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
                n = pak_manager.count_other_paks(paks_dir)
            except Exception:  # noqa: BLE001 -- 診断用の副処理でメインを巻き込まない
                return
            if n is None or n == 0:
                return

            def show() -> None:
                self._log("[other-mods] " + pak_manager.summarize_other_paks(n))
                messagebox.showwarning(
                    i18n.S("TitleOtherModsDetected"),
                    i18n.F("MsgOtherModsDetectedFormat", n),
                )

            self.root.after(0, show)

        threading.Thread(target=worker, daemon=True, name="OtherModsCheck").start()

    # -- dev#620: パス健全性警告 -------------------------------------------

    def _check_path_health_on_startup(self) -> None:
        """CheckPathHealthOnStartup() (DiveToPalworld.cs L.3268-3304) 相当の
        結線。path_health.build_path_facts/path_health_problem/path_health_line
        (dev#134ロジック、単体テスト完備・importゼロだったdev#620)をinstall
        (app_root)/work(work_root)の2系統について評価し、AppendLogログ+条件付き
        警告ダイアログ(Cause/Actionの箇条書き)を出す。

        workRootFailed(主系・フォールバック先ともに書き込み不可、C# L.3281-3287)
        とWorkRootResolutionLine(C# L.3255-3266)はdev#614記号F(別issue)の対象
        であり、本メソッドでは扱わない(dev#620 issue本文どおりの合理的解釈)。
        文字列比較のみでディスクI/Oを伴わないため、_run_startup_self_checkと
        同じくUIスレッドで直接呼んでよい。"""
        onedrive = os.environ.get("OneDrive")
        install = path_health.build_path_facts("install", self.app_root, onedrive)
        work = path_health.build_path_facts("work", self.work_root, onedrive)
        self._log(path_health.path_health_line(install))
        self._log(path_health.path_health_line(work))

        if not path_health.path_health_problem(install) and not path_health.path_health_problem(work):
            return

        bullets: list[str] = []
        if path_health.path_health_has_too_long(install) or path_health.path_health_has_too_long(work):
            bullets.append("- " + i18n.S("CausePathTooLong") + " / " + i18n.S("ActionPathTooLong"))
        if install.unc or work.unc:
            bullets.append("- " + i18n.S("CausePathUnc") + " / " + i18n.S("ActionPathUnc"))
        if install.under_onedrive or work.under_onedrive:
            bullets.append("- " + i18n.S("CausePathOneDrive") + " / " + i18n.S("ActionPathOneDrive"))

        detail = path_health.path_health_line(install) + "\n" + path_health.path_health_line(work)
        self._log("[!] " + i18n.S("TitlePathHealthWarning") + ": " + " / ".join(bullets))
        messagebox.showwarning(
            i18n.S("TitlePathHealthWarning"),
            i18n.F("MsgPathHealthRiskFormat", "\n".join(bullets), detail),
        )

    # -- dev#618: Palworldバージョン互換チェック ---------------------------

    def _known_good_bundled_path(self) -> str:
        """KnownGoodBundledPath() (DiveToPalworld.cs L.3380-3383) 相当。"""
        return os.path.join(self.app_root, "pipeline", "py", "known_good_palworld.json")

    def _load_known_good_palworld(self) -> compat_check.KnownGoodPalworld:
        """LoadKnownGood() (DiveToPalworld.cs L.3396-3403) 相当。同梱データが
        読めなくても(パッケージング事故)例外を投げず空リストのまま返す
        (元実装のtry/catchと同じfail-safe方針)。"""
        bundled = ""
        try:
            with open(self._known_good_bundled_path(), "r", encoding="utf-8") as f:
                bundled = f.read()
        except OSError:
            bundled = ""
        return compat_check.merge_known_good(bundled, self._remote_known_good_json)

    @staticmethod
    def _read_steam_build_id(paks_dir: str) -> Optional[str]:
        """ReadSteamBuildId() (DiveToPalworld.cs L.3344-3372) 相当。
        <...>\\steamapps\\common\\Palworld\\Pal\\Content\\Paks から5階層親へ
        上がって steamapps\\appmanifest_1623730.acf を読み、"buildid"の値
        (数字のみ)を返す。取得できなければNone(判定不能=黙って動く)。"""
        try:
            steamapps_dir = paks_dir
            for _ in range(5):  # Content, Pal, Palworld, common, steamapps
                steamapps_dir = os.path.dirname(steamapps_dir)
            acf = os.path.join(steamapps_dir, "appmanifest_1623730.acf")
            if not os.path.isfile(acf):
                return None
            with open(acf, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = re.search(r'"buildid"\s*"(\d+)"', line, re.IGNORECASE)
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return None

    def _detect_palworld_version(self) -> compat_check.PalworldDetection:
        """DetectPalworldVersion() (DiveToPalworld.cs L.3405-3419) 相当。
        Paksフォルダが見つからなければdetected=Falseのまま返す(判定不能=
        黙って動く、元実装のコメントどおり)。"""
        det = compat_check.PalworldDetection()
        paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
        if paks_dir is None:
            return det
        det.detected = True
        det.build_id = self._read_steam_build_id(paks_dir)
        try:
            pak = os.path.join(paks_dir, pak_manager.PAL_WINDOWS_PAK_NAME)
            if os.path.isfile(pak):
                det.pak_size = os.path.getsize(pak)
        except OSError:
            pass
        return det

    def _palworld_manifest_breadcrumb_path(self) -> str:
        """PalworldManifestBreadcrumbPath() (DiveToPalworld.cs L.3391-3394)
        相当。convert_noue.py _warm_job()のjob_dir固定名("_warm_dummy")と
        extract_vanilla.pyのMANIFEST_NAME("vanilla_manifest.json")に合わせた
        固定パス。"""
        return os.path.join(self.work_root, "_warm_dummy", "vanilla", "vanilla_manifest.json")

    def _read_manifest_combined_hash(self) -> Optional[str]:
        """ReadManifestCombinedHash() (DiveToPalworld.cs L.3421-3430) 相当。"""
        try:
            with open(self._palworld_manifest_breadcrumb_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            value = data.get("combined_hash") if isinstance(data, dict) else None
            return str(value) if value else None
        except (OSError, ValueError):
            return None

    def _evaluate_palworld_compat_now(self) -> tuple[compat_check.PalworldCompatStatus, compat_check.KnownGoodPalworld]:
        """EvaluateCompatNow() (DiveToPalworld.cs L.3435-3441) 相当。診断ログ
        (未結線・別途)とCheckPalworldVersionOnceの両方が使う共通経路
        (両者の判定基準を一致させるため、元実装のコメントどおり)。"""
        known = self._load_known_good_palworld()
        det = self._detect_palworld_version()
        manifest_hash = self._read_manifest_combined_hash()
        return compat_check.evaluate(known, det, manifest_hash), known

    def _resolve_palworld_compat_status(
        self, sleep_fn=time.sleep
    ) -> "tuple[compat_check.PalworldCompatStatus, compat_check.KnownGoodPalworld] | None":
        """CheckPalworldVersionOnce() (DiveToPalworld.cs L.3456-3497) の判定
        部分のみを切り出したもの(スレッド起動・警告表示はこのメソッドの外側、
        _check_palworld_version_once側の担当)。戻り値がNoneなら初回の判定
        自体に失敗した(=確認に失敗しても本体の動作は変えない、元実装の
        `catch (Exception) { return; }`と同じ)。

        dev#91: 版番号が既知と不一致でも、抽出物マニフェスト
        (vanilla_manifest.json)が既知良好と一致すれば警告しない。manifestは
        起動直後に自動で走るwarm-cache(_ensure_blender_ready_on_startup経由の
        warm_startup.py)が完了しないと手に入らないため、manifest_available で
        なければ最大5分(3秒間隔)ポーリングしてから諦める(元実装と同じ
        タイムアウト値)。`sleep_fn`はテスト時に実待機を避けるための注入点
        (既定はtime.sleep)。"""
        try:
            st, known = self._evaluate_palworld_compat_now()
        except Exception:  # noqa: BLE001 -- 確認に失敗しても本体の動作は変えない
            return None
        if not st.detected or not st.should_warn:
            return st, known

        if not st.manifest_available:
            poll_interval_s = 3.0
            timeout_s = 5 * 60.0
            waited = 0.0
            while waited < timeout_s:
                sleep_fn(poll_interval_s)
                waited += poll_interval_s
                try:
                    st, known = self._evaluate_palworld_compat_now()
                except Exception:  # noqa: BLE001
                    break
                if not st.should_warn or st.manifest_available:
                    break
        return st, known

    def _check_palworld_version_once(self) -> None:
        """CheckPalworldVersionOnce() (DiveToPalworld.cs L.3456-3497) 相当の
        結線。版が既知と不一致でも警告のみ(ブロックしない)。acfの読み取りや
        大きなpakへのアクセス、最大5分のポーリング待ちを伴うため専用
        バックグラウンドスレッドで実行する(元実装と同じ設計)。"""

        def worker() -> None:
            result = self._resolve_palworld_compat_status()
            if result is None:
                return
            st, known = result
            if not st.should_warn:
                return

            def show() -> None:
                self._log(
                    "Warning: the detected Palworld version differs from the "
                    "verified version (" + compat_check.format_detected(st)
                    + ", supported: " + compat_check.format_supported(known)
                    + ") — you can continue"
                )
                messagebox.showwarning(
                    i18n.S("TitlePalworldVersionCheck"),
                    i18n.F(
                        "MsgPalworldVersionMismatchFormat",
                        compat_check.format_supported(known),
                        compat_check.format_detected(st),
                    ),
                )

            self.root.after(0, show)

        threading.Thread(target=worker, daemon=True, name="PalworldCompatCheck").start()

    # -- dev#619: 起動時更新通知 --------------------------------------------

    def _check_for_update_once(self) -> None:
        """CheckForUpdateOnStartup() (DiveToPalworld.cs L.3505-3546) 相当の
        結線。update_check.check_for_update()(HTTP GET含む純ロジック分離済み、
        聖域: 取得失敗はいかなるエラー表示・例外にもならないこと)を専用
        バックグラウンドスレッドで呼ぶ。dev#89: 取得できた"palworld_known_good"
        ブロックはlatestの有無に関わらずキャッシュする(compat_check側が次回の
        判定で使う)。"""

        def worker() -> None:
            try:
                result = update_check.check_for_update(TOOL_VERSION)
            except Exception:  # noqa: BLE001 -- 聖域: 取得失敗は無音で諦める
                return
            if result.remote_known_good_json:
                self._remote_known_good_json = result.remote_known_good_json
            if not result.has_update or not result.display_version:
                return
            display_version = result.display_version
            self.root.after(0, lambda: self._show_update_notice(display_version))

        threading.Thread(target=worker, daemon=True, name="UpdateCheck").start()

    def _show_update_notice(self, display_version: str) -> None:
        """ShowUpdateNotice() (DiveToPalworld.cs L.3595-3607) 相当。UIスレッド
        専用。updateLabel/updateNowButton(WP-A1で骨格のみ配置・place_forget()
        済み)を表示条件付きで再表示する。"""
        self._pending_update_version = display_version
        update_label = self.widgets["updateLabel"]
        update_label.config(text=i18n.F("UpdateNoticeFormat", display_version))
        update_label.place(x=12, y=822, width=1058, height=20)
        update_now_button = self.widgets["updateNowButton"]
        update_now_button.place(x=12, y=848, width=130, height=22)

    def _on_open_update_download_page(self) -> None:
        """OpenUpdateDownloadPage() (DiveToPalworld.cs L.3613-3617) 相当。
        既定ブラウザで配布ページを開く。失敗しても無音(通知クリックの延長で
        二重にエラーダイアログを出す必要は無い、元実装のコメントどおり)。"""
        try:
            webbrowser.open(update_check.UPDATE_DOWNLOAD_PAGE_URL)
        except Exception:  # noqa: BLE001 -- 元実装と同じく無音で諦める
            pass

    def _get_os_description(self) -> str:
        """GetOsDescription() (DiveToPalworld.cs L.3939) の簡略版。
        C#はレジストリを直読みして厳密なWindowsビルド番号を得ていたが、Python版は
        標準ライブラリのplatformモジュールで足りる粒度に留める(診断ログの
        補助情報であり、この値自体がゲート判定に使われることはないため)。"""
        try:
            return f"Windows {platform.release()} ({platform.version()})"
        except Exception:  # noqa: BLE001
            return "unknown"

    def _build_diagnostics_text(self) -> str:
        """BuildReportPayloadJson前段の「診断ログ本文」組み立て(DiveToPalworld.cs
        L.4180-4219相当、§2.5)。support_dialog.SupportContext.build_diagnostics_text
        コールバックの実体。dev#98/#103のOtherPakSummaryLine(=SummarizeOtherPaks、
        WP-A11/dev#549で移植済みだったがmain_window結線が無かった)をここで
        実際に組み込む(D1の統合対象そのもの)。"""
        lines: list[str] = []
        lines.append(f"date: {datetime.now().isoformat(timespec='seconds')}")
        lines.append(f"version: {TOOL_VERSION}")
        lines.append(f"os: {self._get_os_description()}")
        file_lang = i18n.FILE_LANG_CODES.get(i18n.current_lang, i18n.current_lang)
        lines.append(f"lang: {file_lang} (ui) / {self._current_os_culture_name() or 'unknown'} (os)")
        vrm_path = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
        avatar_name = os.path.basename(vrm_path) if vrm_path else "(not selected)"
        lines.append(f"avatar: {avatar_name}")
        try:
            paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
            other_pak_line = pak_manager.summarize_other_paks(pak_manager.count_other_paks(paks_dir))
        except Exception:  # noqa: BLE001 -- 診断文の組み立て自体は失敗させない
            other_pak_line = "other_paks: unknown (paks dir not found)"
        lines.append(other_pak_line)
        status_text = self.widgets["statusLabel"].cget("text") if "statusLabel" in self.widgets else ""
        lines.append(f"status: {status_text}")
        lines.append("--- Execution Log (all work on this avatar, including across process steps) ---")
        try:
            log_text = self.log_box.get("1.0", "end-1c")
        except tk.TclError:
            log_text = ""
        lines.append(log_text)
        return "\n".join(lines)

    def _on_show_support_dialog(self) -> None:
        """reportButton.Click相当(ShowSupportDialog()呼び出し箇所)。
        dev#532 D1: WP-A5(inquiry.py/support_dialog.py)が結線権限を持たな
        かったボタンを統合WPで実配線する。"""
        channel = dist_channel.read_dist_channel(self.app_root)
        file_lang = i18n.FILE_LANG_CODES.get(i18n.current_lang, i18n.current_lang)
        ctx = support_dialog.SupportContext(
            tool_version=TOOL_VERSION,
            lang=file_lang,
            channel=channel,
            get_os_description=self._get_os_description,
            get_avatar_name=lambda: (
                os.path.basename(self.widgets["vrmBox"].get().strip())
                if self.widgets["vrmBox"].get().strip()
                else "(not selected)"
            ),
            get_status_text=lambda: self.widgets["statusLabel"].cget("text"),
            build_diagnostics_text=self._build_diagnostics_text,
            append_log=self._log,
        )
        support_dialog.show_support_dialog(self.root, self._support_state, ctx)

    def _log(self, text: str, *, gui: bool = True) -> None:
        """ログ欄への追記(旧AppendLog相当のごく簡略版)。dev#592層3(生存防御):
        ログ欄への描画・コンソール/リダイレクト先への出力のいずれも、
        GUI本体(ポーリング・進捗・完了処理)を巻き込んで死んではならない。

        dev#596b: gui=False の行はログ欄(log_box)には表示しない。ユーザーの
        判断に不要な開発向け詳細行を画面から抑制しつつ、print()経由でコンソール/
        launch.log(res\\logs\\launch.log、app_py\\main.pyがsys.stdoutをリダイレクト
        済み)には引き続き残す。診断可能性は落とさない。"""
        if gui:
            try:
                self.log_box.configure(state="normal")
                self.log_box.insert("end", text + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except tk.TclError:
                pass
        try:
            print(text)
        except Exception:  # noqa: BLE001 -- dev#592: cp932等でUnicodeEncodeError
            pass

    def _stub(self, action_name: str):
        """イベントハンドラの仮実装。押されたら「未実装」とログへ出すだけで、
        実処理は一切行わない(WP-A2以降が結線する、DESIGN.md §5.2)。

        dev#596b: 現存する唯一の呼び出し元(pakList選択変更)はユーザー操作の
        たびに毎回発火する高頻度ノイズで、「not implemented」という文言自体が
        ユーザーの判断に資さない(むしろ何か壊れているように誤解されうる)ため、
        GUIログ欄への表示は抑制する(gui=False、console/launch.logには残す)。"""

        def handler(*_args, **_kwargs):
            self._log(f"[stub] {action_name}: not implemented", gui=False)

        return handler

    def _register_text(self, widget: tk.Widget, key: str) -> None:
        i18n.register(widget, key, i18n.default_text_setter)

    def _register_tip(self, widget: tk.Widget, key: str) -> None:
        tip = _ToolTip(widget)
        self._tooltips.append(tip)
        i18n.register(tip, key, lambda w, text: w.set_text(text))

    def _update_window_title(self) -> None:
        self.root.title(
            f"Uchinoko for Palworld {TOOL_VERSION} - {i18n.S('TitleSubtitle')}"
        )

    # -- ウィジェット構築 ---------------------------------------------------

    def _build_widgets(self) -> None:
        root = self.root

        # ---- 1行目: VRM (DESIGN.md §1.1 #1-#4) ----
        lbl_vrm = tk.Label(root, text=i18n.S("LabelAvatar"))
        lbl_vrm.place(x=12, y=15, width=70)
        self._register_text(lbl_vrm, "LabelAvatar")

        vrm_box = tk.Entry(root)
        vrm_box.place(x=80, y=12, width=650, height=23)
        self.widgets["vrmBox"] = vrm_box  # #1

        browse = tk.Button(root, text=i18n.S("BtnBrowse"), command=self._on_browse)
        browse.place(x=738, y=10, width=90, height=25)
        self._register_text(browse, "BtnBrowse")
        self.widgets["browse"] = browse  # #2

        drop_hint = tk.Label(root, text=i18n.S("HintDragDrop"))
        drop_hint.place(x=900, y=15, width=176)
        self._register_text(drop_hint, "HintDragDrop")
        self.widgets["dropHint"] = drop_hint  # #3

        # #4: D&D受け皿(WP-A8で実配線。DESIGN.md §6-2)。
        # C#版はForm全体(root相当)にAllowDrop=trueを設定しているため
        # (L.946)、Python版も特定ウィジェットではなくrootウィンドウ全体へ
        # インストールする。_setup_drag_and_drop()は__init__の最後で呼ぶ
        # (root.winfo_id()がジオメトリ確定前でも有効なHWNDを返すため、
        # ここ=_build_widgets内で呼んでも問題は無いが、他の初期化と
        # 順序を揃えるため__init__側に置く)。
        self.widgets["dndTarget"] = None  # 実体はウィジェットではなくdnd.DropTarget

        # ---- 2行目: メイン操作 (#5-#9) ----
        convert_button = tk.Button(
            root, text=i18n.S("BtnFullConvert"), command=self._on_full_convert
        )
        convert_button.place(x=12, y=44, width=200, height=36)
        self._register_text(convert_button, "BtnFullConvert")
        self.widgets["convertButton"] = convert_button  # #5

        cancel_button = tk.Button(
            root, text=i18n.S("BtnCancelConvert"), state="disabled",
            command=self._on_cancel_convert,
        )
        # dev#532 WP-A10: en "Cancel Conversion" が幅100pxであふれる
        # (i18n_overflow_lint.py実測 avail=89/measured=97、over=8px)ため、
        # 訳文は変えず幅を112pxへ拡張。busy_bar/blender_retry_button側の
        # 開始x=330に接するまで(convert_buttonの終端212との間に4pxの隙間を残す)
        # 広げても、cancel_buttonが有効化されるタイミング(#7のbusy_bar表示と同時)
        # と重ならない範囲(x=216+112=328 < 330)に収めてある。
        cancel_button.place(x=216, y=44, width=112, height=36)
        self._register_text(cancel_button, "BtnCancelConvert")
        self.widgets["cancelButton"] = cancel_button  # #6

        # #7: RunPipeline() L.2602-2603相当のジオメトリを_BUSY_BAR_GEOMETRYへ
        # 憶えておき、開始/終了のたびplace()/place_forget()し直す
        # (Visible=false初期状態、L.1012)
        self._busy_bar_geometry = dict(x=330, y=46, width=740, height=12)
        busy_bar = ttk.Progressbar(root, orient="horizontal", mode="determinate", maximum=100)
        busy_bar.place(**self._busy_bar_geometry)
        busy_bar.place_forget()
        self.widgets["busyBar"] = busy_bar  # #7

        status_label = tk.Label(root, text=i18n.S("StatusPromptVrm"), anchor="w")
        status_label.place(x=330, y=62, width=740)
        self.widgets["statusLabel"] = status_label  # #8
        # StatusPromptVrmは状態依存の初期表示であり静的i18nキーではないため
        # RegisterI18nTextはしない(C#側も同様、言語切替時はUpdateButtonStates等
        # 別経路で再計算する設計。DESIGN.md §4.4の対象外)

        blender_retry_button = tk.Button(
            root, text=i18n.S("BtnBlenderRetry"),
            command=self._ensure_blender_ready_on_startup,
        )
        blender_retry_button.place(x=330, y=44, width=160, height=36)
        blender_retry_button.place_forget()  # Visible=false 初期状態(失敗時のみ表示)
        self._register_text(blender_retry_button, "BtnBlenderRetry")
        self._register_tip(blender_retry_button, "TipBlenderRetry")
        self.widgets["blenderRetryButton"] = blender_retry_button  # #9

        # ---- 3行目: こだわり設定 (#10-#14) ----
        self._kodawari_open = False
        kodawari_toggle = tk.Button(
            root, text="▼ " + i18n.S("LabelKodawari"), command=self._on_toggle_kodawari
        )
        kodawari_toggle.place(x=12, y=88, width=150, height=26)
        self.widgets["kodawariToggle"] = kodawari_toggle  # #10

        kodawari_panel = tk.Frame(root, relief="solid", borderwidth=1)
        kodawari_panel.place(x=12, y=118, width=1058, height=80)
        kodawari_panel.place_forget()  # Visible=false 初期状態(L.1051)
        self._kodawari_panel = kodawari_panel

        lbl_shadow = tk.Label(kodawari_panel, text=i18n.S("LabelShadowStrength"))
        lbl_shadow.place(x=8, y=12, width=110)
        self._register_text(lbl_shadow, "LabelShadowStrength")

        shadow_bar = tk.Scale(
            kodawari_panel, from_=0, to=100, orient="horizontal", showvalue=False,
        )
        shadow_bar.set(30)
        shadow_bar.place(x=120, y=0, width=300, height=34)
        shadow_label = tk.Label(kodawari_panel, text="30%")
        shadow_label.place(x=430, y=12, width=50)

        def _on_shadow_change(_value, bar=shadow_bar, lbl=shadow_label):
            lbl.config(text=f"{int(float(_value))}%")

        shadow_bar.config(command=_on_shadow_change)
        self._register_tip(shadow_bar, "TipShadowBar")
        self.widgets["shadowBar"] = shadow_bar  # #11

        mats_button = tk.Button(
            kodawari_panel, text=i18n.S("BtnMatsOnly"),
            command=self._on_materials_only,
        )
        mats_button.place(x=500, y=6, width=180, height=30)
        self._register_text(mats_button, "BtnMatsOnly")
        self._register_tip(mats_button, "TipMatsButton")
        self.widgets["matsButton"] = mats_button  # #12

        # dev#532 WP-A10: en "Drop Bones (Advanced):" が幅110pxであふれる
        # (i18n_overflow_lint.py実測 avail=104/measured=128、over=24px)ため、
        # 訳文は変えず幅を140pxへ拡張。同じ行に並ぶdrop_bones_box/hint/
        # preview_buttonは元の隙間(2px/10px/10px)を保ったまま+30pxぶん
        # 右へずらし、重なりが出ないようにしてある(kodawari_panel幅1058に
        # 対して余裕あり)。
        drop_bones_label = tk.Label(kodawari_panel, text=i18n.S("LabelDropBones"))
        drop_bones_label.place(x=8, y=48, width=140)
        self._register_text(drop_bones_label, "LabelDropBones")

        drop_bones_box = tk.Entry(kodawari_panel)
        drop_bones_box.place(x=150, y=44, width=400, height=23)
        self._register_tip(drop_bones_box, "TipDropBones")
        # dev#617: dropBonesBox.TextChanged (L.1256) 相当。除外ボーン欄は
        # BuildPreviewSig()の構成要素なので、書き換えのたびFull Convertボタンの
        # 鮮度判定を即再計算する(_on_drop_bones_changed参照)。
        drop_bones_box.bind("<KeyRelease>", self._on_drop_bones_changed, add="+")
        self.widgets["dropBonesBox"] = drop_bones_box  # #13

        drop_bones_hint = tk.Label(kodawari_panel, text=i18n.S("HintDropBonesEmpty"))
        drop_bones_hint.place(x=560, y=48, width=190)
        self._register_text(drop_bones_hint, "HintDropBonesEmpty")

        preview_button = tk.Button(
            kodawari_panel, text=i18n.S("BtnPreviewUpdate"),
            command=self._on_preview_only,
        )
        preview_button.place(x=760, y=44, width=150, height=28)
        self._register_text(preview_button, "BtnPreviewUpdate")
        self._register_tip(preview_button, "TipPreviewButton")
        self.widgets["previewButton"] = preview_button  # #14

        # ---- プレビュー+ログ (#15-#16) ----
        # Top値はLayoutContentArea()が開閉状態に応じて動的計算する
        # (layout_content_area()参照、#25)。ここでは初期値のみ置く。
        preview_front = tk.Label(
            root, text=i18n.S("LabelPreviewPlaceholderFront"),
            relief="solid", borderwidth=1, bg="#f0f0f0",
        )
        preview_front.place(x=12, y=210, width=380, height=360)
        self.widgets["previewFront"] = preview_front  # #15 (front)
        # LabelPreviewPlaceholderFront/Sideはimageが設定されると
        # Label既定のcompound=none挙動でtextが隠れる(表示上は無害)ため、
        # 通常の静的キーとして_register_textでも問題ない(dev#630)
        self._register_text(preview_front, "LabelPreviewPlaceholderFront")

        preview_side = tk.Label(
            root, text=i18n.S("LabelPreviewPlaceholderSide"),
            relief="solid", borderwidth=1, bg="#f0f0f0",
        )
        preview_side.place(x=400, y=210, width=380, height=360)
        self.widgets["previewSide"] = preview_side  # #15 (side)
        self._register_text(preview_side, "LabelPreviewPlaceholderSide")
        # 実画像表示(work\<名>\converted\preview_male_stand[_side].png)は
        # dev#599で実装済み(_apply_previews/_set_preview_widget参照)。
        # Pillow等の追加依存は使わずtk.PhotoImage(Tk 8.6ネイティブPNGデコード)
        # だけで完結させている。ここで生成するのは初期プレースホルダのLabelのみ

        log_box = tk.Text(root, state="disabled", wrap="word")
        log_box.place(x=790, y=210, width=280, height=360)
        self.widgets["logBox"] = log_box  # #16
        self.log_box = log_box

        # ---- 作成済みMODの一覧と適用/解除 (#17-#20) ----
        lbl_paks = tk.Label(root, text=i18n.S("LabelPakList"))
        lbl_paks.place(x=12, y=584, width=130)
        self._register_text(lbl_paks, "LabelPakList")
        self.widgets["lblPaks"] = lbl_paks  # #17

        applied_label = tk.Label(root, text=i18n.S("AppliedStatusChecking"), anchor="w")
        applied_label.place(x=150, y=584, width=920)
        self.widgets["appliedLabel"] = applied_label  # #18

        pak_list = ttk.Treeview(
            root, columns=("avatar", "file", "size", "created"), show="headings",
        )
        pak_list.heading("avatar", text=i18n.S("ColAvatar"))
        pak_list.heading("file", text=i18n.S("ColFile"))
        pak_list.heading("size", text=i18n.S("ColSize"))
        pak_list.heading("created", text=i18n.S("ColCreatedAt"))
        pak_list.column("avatar", width=200)
        pak_list.column("file", width=380)
        pak_list.column("size", width=100)
        pak_list.column("created", width=170)
        pak_list.place(x=12, y=608, width=870, height=180)
        # 選択でのプレビュー・設定復元(PakListSelectedIndexChanged、
        # DiveToPalworld.cs L.1126-1137相当)。dev#605で結線
        # (_on_pak_list_selected/_apply_restored_settings参照、dev#616 A+Iと共用)。
        pak_list.bind("<<TreeviewSelect>>", self._on_pak_list_selected)
        self.widgets["pakList"] = pak_list  # #19
        self._pak_list_columns = {
            "avatar": "ColAvatar", "file": "ColFile", "size": "ColSize", "created": "ColCreatedAt",
        }

        apply_button = tk.Button(
            root, text=i18n.S("BtnApply"), command=self._on_apply_selected
        )
        apply_button.place(x=890, y=608, width=180, height=34)
        self._register_text(apply_button, "BtnApply")
        self._register_tip(apply_button, "TipApply")
        self.widgets["applyButton"] = apply_button  # #20 (apply)

        remove_button = tk.Button(
            root, text=i18n.S("BtnRemoveMod"), command=self._on_remove_applied
        )
        remove_button.place(x=890, y=648, width=180, height=34)
        self._register_text(remove_button, "BtnRemoveMod")
        self._register_tip(remove_button, "TipRemove")
        self.widgets["removeButton"] = remove_button  # #20 (remove)

        refresh_button = tk.Button(
            root, text=i18n.S("BtnRefreshList"), command=self._on_refresh_pak_list
        )
        refresh_button.place(x=890, y=688, width=180, height=28)
        self._register_text(refresh_button, "BtnRefreshList")
        self.widgets["refreshButton"] = refresh_button  # #20 (refresh)

        delete_button = tk.Button(
            root, text=i18n.S("BtnDeleteResult"), command=self._on_delete_selected
        )
        delete_button.place(x=890, y=724, width=180, height=28)
        self._register_text(delete_button, "BtnDeleteResult")
        self._register_tip(delete_button, "TipDelete")
        self.widgets["deleteButton"] = delete_button  # #20 (delete)

        # ---- 問合せ (#21) ----
        # dev#532 D1: ShowSupportDialog()相当の実配線。support_dialog.py(WP-A5)は
        # main_window.pyへの結線権限を持たなかったため未配線のまま残っていた
        # ("main_window.pyへのボタン結線自体は統合WPで行う"、support_dialog.py
        # 冒頭コメント)。_on_show_support_dialog()参照。
        report_button = tk.Button(
            root, text=i18n.S("BtnReport"), command=self._on_show_support_dialog
        )
        report_button.place(x=890, y=760, width=180, height=28)
        self._register_text(report_button, "BtnReport")
        self._register_tip(report_button, "TipReport")
        self.widgets["reportButton"] = report_button  # #21

        # ---- 自動適用チェック (#22) ----
        auto_apply_var = tk.BooleanVar(value=settings.load_autoapply(self.app_root))
        auto_apply_check = tk.Checkbutton(
            root, text=i18n.S("CheckAutoApply"), variable=auto_apply_var,
            command=lambda: settings.save_autoapply(self.app_root, auto_apply_var.get()),
            anchor="w",
        )
        auto_apply_check.place(x=12, y=794, width=500, height=20)
        self._register_text(auto_apply_check, "CheckAutoApply")
        self._register_tip(auto_apply_check, "TipAutoApply")
        self.widgets["autoApplyCheck"] = auto_apply_check  # #22
        self._auto_apply_var = auto_apply_var

        # ---- 更新通知 (#23) ----
        # dev#619結線: OpenUpdateDownloadPage() (DiveToPalworld.cs L.1195/1213/
        # 3613-3617) 相当。クリックで既定ブラウザにupdate_check.py既存の
        # UPDATE_DOWNLOAD_PAGE_URL(=DiveToPalworld.cs L.733 UpdateDownloadPageUrl
        # をそのまま移植した定数)を開く。失敗しても無音(元実装のtry/catch通り)。
        update_label = tk.Label(
            root, text="", fg="blue", cursor="hand2", anchor="w",
        )
        update_label.place(x=12, y=822, width=1058, height=20)
        update_label.place_forget()  # Visible=false 初期状態
        update_label.bind("<Button-1>", lambda _e: self._on_open_update_download_page())
        self._register_tip(update_label, "TipUpdateLabel")
        self.widgets["updateLabel"] = update_label  # #23 (label)

        update_now_button = tk.Button(
            root, text=i18n.S("BtnUpdateNow"),
            command=self._on_open_update_download_page,
        )
        update_now_button.place(x=12, y=848, width=130, height=22)
        update_now_button.place_forget()  # Visible=false 初期状態
        self._register_text(update_now_button, "BtnUpdateNow")
        self._register_tip(update_now_button, "TipUpdateNow")
        self.widgets["updateNowButton"] = update_now_button  # #23 (button)

        # ---- 言語切替 (#24) ----
        lbl_lang = tk.Label(root, text=i18n.S("LabelLanguage"))
        lbl_lang.place(x=850, y=94, width=60)
        self._register_text(lbl_lang, "LabelLanguage")

        lang_var = tk.StringVar(value=i18n.LANG_DISPLAY_NAMES[i18n.LANGS.index(i18n.current_lang)])
        lang_combo = ttk.Combobox(
            root, textvariable=lang_var, values=i18n.LANG_DISPLAY_NAMES,
            state="readonly",
        )
        lang_combo.place(x=914, y=90, width=156, height=24)
        # dev#595 再修正(2026-08-01): PR #608の「readonly Comboboxはcurrent()を
        # 呼ばないと初期表示が空になる」という見立ては、非表示Tkルートでの実証
        # (app_py\tests\test_main_window_lang_combo.pyのrepro系テスト)で否定
        # された——current()を呼ばず、textvariableだけ渡しても、その変数を
        # 生かし続けさえすれば普通に表示される。
        #
        # 実際の原因はPythonの参照カウントGCだった: lang_varはこの関数のローカル
        # 変数で、self.widgets/self.*のどこにも保持されていなかった。ttkウィジェット
        # 側はtextvariableを「Tcl変数名の文字列」として持つだけでPythonオブジェクト
        # への参照は握らないため、_build_widgets()がreturnした時点でlang_varの
        # 参照カウントが0になりCPythonが即座に破棄する。tkinter.Variable.__del__は
        # 破棄時に対応するTcl変数をglobalunsetvarで消してしまうため、ウィジェットは
        # 存在しない変数を指すことになり表示が空欄になる(combo.get()==""、
        # combo.current()==-1で再現・確認済み)。すぐ下のauto_apply_var
        # (L.741,751: self._auto_apply_var = auto_apply_var)は同じ関数内で
        # 正しく生存参照を保持しており、lang_varだけがその慣例から漏れていた。
        #
        # 修正: lang_varをself._lang_varとして保持し、GCされないようにする
        # (.current()呼び出し自体は無害なので実害ないが根治ではないため残す)。
        self._lang_var = lang_var
        lang_combo.current(i18n.LANGS.index(i18n.current_lang))
        lang_combo.bind("<<ComboboxSelected>>", self._on_language_selected)
        self._register_tip(lang_combo, "TipLanguageSwitch")
        self.widgets["langCombo"] = lang_combo  # #24
        self._lang_combo = lang_combo

        # #25: LayoutContentArea相当(layout_content_area()メソッド、後述)。
        # 独立したWidgetではなく再配置ロジックなので、呼び出し可能なメソッド
        # 自体をlookup対象として登録する
        self.widgets["layoutContentArea"] = self.layout_content_area  # #25

    # -- イベントハンドラ(stub含む) -----------------------------------------

    def _on_browse(self) -> None:
        # browse.Click (DiveToPalworld.cs L.958-973)相当: .prefabならUnity輸出
        # (RunUnityExport)、それ以外は最小SetVrm(vrmBoxへパスを入れるだけ。
        # セッションログ復元・以前のjob.json設定復元はWP-A2の外、モジュール
        # docstring参照)。
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=i18n.S("DlgTitleChooseAvatarFile"),
            filetypes=[(i18n.S("LabelAvatar"), ("*.vrm", "*.fbx", "*.prefab"))],
        )
        if not path:
            return
        if path.lower().endswith(".prefab"):
            self._on_prefab_selected(path)
        else:
            self._set_vrm_path(path)

    def _set_vrm_path(self, path: str) -> None:
        """SetVrm()相当(DiveToPalworld.cs L.1510-1546を、py版が非同期読み込みを
        持たない実装に合わせて単純化したもの)。新しいアバターを選ぶたび
        licenseConfirmedを一旦リセットし(L.1514相当)、続けてそのアバターの
        job.jsonがあれば設定・プレビューを復元する(ApplyAvatarLoad()
        L.1571-1584相当、dev#616 A+Iで結線)。vrmBoxは直前にpathへ直接
        設定済みのため、復元側はvrm_pathで上書きしない(set_vrm_path=False。
        C#版もApplyAvatarLoadからのApplyRestoredSettings呼び出しは
        setVrmPath=falseで揃っている、L.1584)。"""
        self.widgets["vrmBox"].delete(0, tk.END)
        self.widgets["vrmBox"].insert(0, path)
        self._license_confirmed = False
        settings.save_last_vrm(self.app_root, path)
        self._log(path)
        name = pipeline_runner.sanitize_name(os.path.splitext(os.path.basename(path))[0])
        job_dir = os.path.join(self.work_root, name)
        self._apply_restored_settings(job_dir, set_vrm_path=False)
        # dev#611: ApplyAvatarLoad() L.1591-1597相当。アバター登録の全経路
        # (browse/D&D/prefabのUnity輸出完了)がこの_set_vrm_pathへ集約している
        # ため、末尾でここを呼ぶだけで3経路すべてに自動プレビューが結線される。
        self._maybe_auto_preview(path)
        # dev#613/#617: ApplyAvatarLoad() L.1598 `UpdateButtonStates();`相当
        # (RunPipeline()を試みた直後に必ず1回呼ばれる)。旧実装はここで
        # StatusReadyToConvertを無条件表示していたが、C#版はUpdateButtonStates()
        # のhasVrm/fresh判定に委ねている(自動プレビューが未生成/未実行のまま
        # 終わればStatusPreviewStaleが正しい)ため、鮮度判定込みの結線に置き換える。
        self._refresh_convert_button_freshness()

    def _apply_restored_settings(self, job_dir: str, *, set_vrm_path: bool) -> bool:
        """ApplyRestoredSettings()(DiveToPalworld.cs L.1633-1663)相当
        (dev#616 A+I)。対応するjob.jsonが無ければ何もせずFalseを返す
        (RestoreSettings() L.1621-1628の`if (!File.Exists(jobJson)) return;`
        相当)。py版WP-A1骨格にはshoulderBar/mergeFingersCheck/unlitCheck/
        twoSidedCheckに対応する可視ウィジェットが無い(C#版もUIには表示して
        いない内部フィールド、L.1041-1046「内部互換性のためにフィールドを
        初期化(UIには表示しない)」参照)。それらは_set_vrm_path冒頭で初期化
        済みの内部属性(_shoulder_offset_deg等)への反映に留め、run_pipeline
        呼び出し時にそのまま使われる(_start_pipeline参照)。dropBonesBox/
        shadowBarは両版とも可視ウィジェットなのでそのまま反映する。

        戻り値: job.jsonが見つかり反映できたか(呼び出し元は主にpak一覧選択
        ハンドラの単体テストで使う)。"""
        job_json = os.path.join(job_dir, "job.json")
        data = pipeline_runner.read_job(job_json)
        if data is None:
            return False

        if set_vrm_path:
            vrm = data.get("vrm_path")
            if vrm:
                self.widgets["vrmBox"].delete(0, tk.END)
                self.widgets["vrmBox"].insert(0, vrm)

        # shoulder_offset_deg: `JsonNum(json, "shoulder_offset_deg", shoulderBar.Value)`
        # 相当(キー欠落時は現在値を維持、L.1643-1645)。shoulderBar.Minimum/Maximum
        # は-20/20(DiveToPalworld.cs L.1042)。
        try:
            sh = float(data.get("shoulder_offset_deg", self._shoulder_offset_deg))
        except (TypeError, ValueError):
            sh = self._shoulder_offset_deg
        self._shoulder_offset_deg = max(-20, min(20, int(round(sh))))

        # shadow_lift: `JsonNum(json, "shadow_lift", -1)`相当。0以上の時だけ
        # 反映する(L.1646-1648)。shadowBarは0-100の可視ウィジェット。
        try:
            lift = float(data.get("shadow_lift", -1))
        except (TypeError, ValueError):
            lift = -1
        if lift >= 0:
            value = max(0, min(100, int(round(100 - lift * 100))))
            self.widgets["shadowBar"].set(value)

        self._merge_fingers = bool(data.get("merge_fingers", self._merge_fingers))
        self._unlit = bool(data.get("unlit", self._unlit))
        self._force_two_sided = bool(data.get("force_two_sided", self._force_two_sided))
        # license_confirmed: `JsonBool(json, "license_confirmed", false)`相当。
        # 他の項目と違い既定値は常にfalse(現在値を維持しない、L.1652)。
        self._license_confirmed = bool(data.get("license_confirmed", False))

        # drop_bones: `JsonStrArray(json, "drop_bones")`相当。キーが在れば
        # (空配列でも)dropBonesBoxへ反映する(L.1653-1654)。
        drops = data.get("drop_bones")
        if isinstance(drops, list):
            box = self.widgets["dropBonesBox"]
            box.delete(0, tk.END)
            box.insert(0, ", ".join(str(b) for b in drops))

        # LoadPreviews(jobDir)相当(L.1660。py版は非同期プリロードが無いため
        # imagesReady=falseの経路のみ、常にここでディスクから読む)。
        try:
            self._apply_previews(pipeline_runner.load_previews(job_dir))
        except Exception as ex:  # noqa: BLE001 -- プレビュー表示の失敗で復元全体を壊さない
            self._log(f"[preview] restore settings preview load failed: {ex}")
        return True

    def _maybe_auto_preview(self, path: str) -> None:
        """ApplyAvatarLoad() L.1591-1597の起動条件部分に相当:
        `if (File.Exists(r.Path) && !IsPreviewFresh() && runningProc == null
        && blenderReady) RunPipeline(true, false, true);`
        dev#613: py版にはプレビュー鮮度判定(IsPreviewFresh/BuildPreviewSig、
        DiveToPalworld.cs L.2416-2425)が未移植のままだったため(dev#611時点の
        既知のギャップ)、preview_freshness.py(本WPで新設)を使って移植する。
        4条件すべて(ファイル存在/鮮度/二重起動防止/Blender準備済み)を
        C#と同じ順序で揃えた。"""
        if not os.path.isfile(path):
            return
        if self._is_preview_fresh(path):
            return
        if self._active_handle is not None and self._active_handle.is_running():
            return
        if not self._blender_ready:
            return
        self._start_pipeline(preview_only=True, materials_only=False, auto=True)

    def _is_preview_fresh(self, vrm_path: str) -> bool:
        """IsPreviewFresh() L.2416-2425相当。呼び出し時点のdropBonesBox等の
        現在値を使うライブ判定(C#もコントロールの現在値を毎回読む。開始時点の
        スナップショットではない)。"""
        return preview_freshness.is_preview_fresh(
            self.work_root,
            vrm_path,
            self._shoulder_offset_deg,
            self._merge_fingers,
            self.widgets["dropBonesBox"].get(),
        )

    def _save_preview_sig(self, vrm_path: str) -> None:
        """SavePreviewSig() L.2427-2430相当。"""
        preview_freshness.save_preview_sig(
            self.work_root,
            vrm_path,
            self._shoulder_offset_deg,
            self._merge_fingers,
            self.widgets["dropBonesBox"].get(),
        )

    def _finalize_fresh_preview(self, vrm_path: str) -> None:
        """OnPipelineDone() L.2914-2915相当(`SavePreviewSig(); UpdateButtonStates();
        // フル変換ボタンがここで解禁される`)をまとめた結線ヘルパー。
        _on_pipeline_exit()のpreview_only成功時にだけ呼ぶ。呼び出し順序自体が
        C#と1:1対応する契約なので、テストでもこの順序を検査する。"""
        self._save_preview_sig(vrm_path)
        self._refresh_convert_button_freshness()

    def _refresh_convert_button_freshness(self) -> None:
        """UpdateButtonStates() (DiveToPalworld.cs L.2468-2525) のうち、
        Full Convertボタンの鮮度ゲート(L.2479-2480 hasVrm/fresh判定、L.2486
        convertButton.Enabled)とStatusPreviewStale/StatusReadyToConvertの
        テキスト分岐(L.2520-2523)を移植する(dev#617)。

        C#: `convertButton.Enabled = !busy && hasVrm && fresh && blenderReady
        && !workRootFailed;` のうち、matsButton/previewButtonと共有できない
        fresh判定が絡む部分だけをここへ切り出す(busy/blenderReady/
        workRootFailedの3条件は_update_button_states()と重複するが、
        convertButtonはfreshとの組み合わせでしか意味を持たないため独立させて
        いる。matsButton/previewButtonのゲートは_update_button_states()参照)。

        dev#621: workRootFailed(L.2486の`!workRootFailed`)は
        _set_running_ui_state()の3ボタン一括ガードとは別に、ここでも
        明示的に見る。このメソッドは_set_running_ui_state()を経由しない
        経路(_on_drop_bones_changed/_finalize_fresh_preview/__init__直後
        等)からも直接呼ばれるため、work_root_failed中に再度normalへ
        戻ってしまう漏れを構造的に防ぐ。

        dev#639: blenderReady(L.2486の`&& blenderReady`)も同じ理由で
        ここに明示的なガードを持つ(_update_button_states()を経由しない
        呼び出し経路があるため)。blenderReady未確定時のstatusLabel文言は
        _on_blender_setup_done()側が別途面倒を見るため、ここでは
        work_root_failedと同様にstatusLabelへ触れず早期returnするだけに
        留める。

        実行中(pipeline稼働中)はstatusLabelのテキストを変更しない
        (C#のUpdateButtonStates()も`if (!running)`の内側でのみテキストを
        書き換える、L.2504相当。実行中に呼ばれても「StatusPreviewGenerating」
        等の実行中メッセージを上書きしないための保護)。"""
        if self._work_root_failed:
            self.widgets["convertButton"].config(state="disabled")
            return
        if not self._blender_ready:
            self.widgets["convertButton"].config(state="disabled")
            return
        vrm_path = self.widgets["vrmBox"].get().strip()
        has_vrm = os.path.isfile(vrm_path)
        fresh = has_vrm and self._is_preview_fresh(vrm_path)
        self.widgets["convertButton"].config(state=("normal" if fresh else "disabled"))
        running = self._active_handle is not None and self._active_handle.is_running()
        if running or not has_vrm:
            return
        self.widgets["statusLabel"].config(
            text=i18n.S("StatusReadyToConvert") if fresh else i18n.S("StatusPreviewStale")
        )

    def _on_drop_bones_changed(self, _event=None) -> None:
        """dropBonesBox.TextChanged (DiveToPalworld.cs L.1256:
        `dropBonesBox.TextChanged += delegate { UpdateButtonStates(); };`) 相当。
        除外ボーン欄はBuildPreviewSig()の構成要素の1つなので、入力のたび
        Full Convertボタンの鮮度表示を即座に再計算する。"""
        self._refresh_convert_button_freshness()

    # -- D&D(WP-A8、DESIGN.md §1.1-#4/§6-2、ui\dnd.pyとの結線) -----------------

    def _setup_drag_and_drop(self) -> None:
        """OnDragEnter/OnDragDrop配線相当(DiveToPalworld.cs L.946-948)。
        非Windows環境ではdnd.install()がNoneを返すだけで何もしない
        (dnd.is_supported()参照、pytest等の非Windows実行環境を壊さないため)。
        失敗してもD&Dが使えなくなるだけでGUI自体は起動を続ける
        (この裁定の元ネタ: DESIGN.md冒頭『失敗しても画面を止めない』方針)。"""
        try:
            self._drop_target = dnd.install(
                self.root, on_path=self._on_dropped_path, on_rejected=self._on_drop_rejected
            )
        except Exception as ex:  # noqa: BLE001 -- D&D不可でも起動は継続する
            self._drop_target = None
            self._log(f"[dnd] failed to initialize, drag & drop disabled: {ex}")

    def _on_dropped_path(self, path: str) -> None:
        """OnDragDrop() L.1406-1421相当(拒否判定・Blenderゲート機構を除いた
        分岐部分。拡張子フィルタ・複数ファイル選択規則自体はdnd.py側の
        pick_dropped_path()が既に適用済みでここへ渡ってくる)。"""
        if dnd.is_prefab_path(path):
            self._on_prefab_selected(path)
        else:
            self._set_vrm_path(path)

    def _on_drop_rejected(self) -> None:
        """OnDragDrop() L.1411-1415相当(拡張子不一致時のMessageBox)。"""
        messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgDropVrmOrPrefab"))

    # -- pak管理系(WP-A4、DESIGN.md §2.3、pak_manager.pyとの結線) --------------

    def _work_root(self) -> str:
        """workRoot決定の暫定版。DiveToPalworld.cs L.913-932のworkRoot三点セット
        (自動→%LOCALAPPDATA%フォールバック→ログ)はWP-A6/path_health.pyの担当領域
        (DESIGN.md §4.1)。WP-A4はpak管理系の結線が主目的のため、ここでは
        既定値(appRoot\\work)のみを使う〈合理的簡略化、A6実装後に差し替え予定〉。"""
        return os.path.join(self.app_root, "work")

    def _ask_paks_dir_manual(self) -> str | None:
        """PaksDir()の手動指定フォールバック(FolderBrowserDialog相当、L.3096-3113)。
        pak_manager.resolve_paks_dir()へ注入するコールバック(pak_manager.py自体は
        tkinterに依存しない設計、DESIGN.md §5.2)。"""
        from tkinter import filedialog

        chosen = filedialog.askdirectory(title=i18n.S("DlgDescPaksFolder"))
        return chosen or None

    def _on_paks_dir_invalid(self, chosen_path: str) -> None:
        """選んだフォルダにPal-Windows.pakが無かった場合の案内(L.3110-3112、
        無言で受理しない=WP16の踏襲)。"""
        from tkinter import messagebox

        messagebox.showwarning(
            i18n.S("TitlePalworldNotFound"),
            i18n.F("MsgPaksNotFoundFormat", pak_manager.PAL_WINDOWS_PAK_NAME, chosen_path),
        )

    def _resolve_paks_dir_interactive(self) -> str | None:
        """PaksDir()(L.3078-3115)相当。自動発見に失敗すればダイアログを出す。
        ApplySelected/RemoveAppliedのように「ユーザー操作の起点」でだけ呼ぶ
        (受動的な一覧更新ではpaks_dir_quiet系を使い、ダイアログを出さない)。"""
        result = pak_manager.resolve_paks_dir(
            self.app_root,
            cache=self._paks_dir_cache,
            ask_manual=self._ask_paks_dir_manual,
            on_invalid=self._on_paks_dir_invalid,
            log=self._log,
        )
        if result:
            self._paks_dir_cache = result
        return result

    def _classify_apply_failure(self, ex: Exception) -> tuple[str, str]:
        """ShowApplyFailure(L.3754-3789)の原因分類部分の移植(cause, action)。
        WinAPIのERROR_DISK_FULL(112)/ERROR_HANDLE_DISK_FULL(39)はOSErrorの
        winerror属性で判定する(C#のHResult判定と同じ発想)。"""
        if isinstance(ex, PermissionError):
            return i18n.S("CauseNoWritePermission"), i18n.S("ActionNoWritePermission")
        if getattr(ex, "winerror", None) in (112, 39):
            return i18n.S("CauseDiskFull"), i18n.S("ActionDiskFull")
        if isinstance(ex, (FileNotFoundError, NotADirectoryError)):
            return i18n.S("CauseTargetFolderNotFound"), i18n.S("ActionTargetFolderNotFound")
        if isinstance(ex, OSError):
            return i18n.S("CauseFileInUse"), i18n.S("ActionFileInUse")
        return i18n.S("CauseUnexpected"), i18n.S("ActionUnexpected")

    def _show_apply_failure(self, action_label: str, target_path: str, ex: Exception) -> None:
        from tkinter import messagebox

        cause, action = self._classify_apply_failure(ex)
        self._log(f"[Error] {action_label} failed: {target_path} / [{type(ex).__name__}] {ex}")
        messagebox.showerror(
            i18n.F("MsgApplyFailureTitleFormat", action_label),
            i18n.F("MsgApplyFailureBodyFormat", action_label, cause, action, target_path),
        )

    def _on_refresh_pak_list(self) -> None:
        """RefreshPakList()(L.3648-3661)相当。"""
        pak_list = self.widgets["pakList"]
        pak_list.delete(*pak_list.get_children())
        self._pak_paths.clear()
        self._pak_candidates = pak_manager.list_built_paks(self._work_root())
        for pak_path, avatar_name in self._pak_candidates:
            try:
                st = os.stat(pak_path)
                size_text = f"{st.st_size / 1048576.0:.1f} MB"
                created_text = time.strftime("%Y/%m/%d %H:%M", time.localtime(st.st_mtime))
            except OSError:
                size_text = ""
                created_text = ""
            iid = pak_list.insert(
                "", "end",
                values=(avatar_name, os.path.basename(pak_path), size_text, created_text),
            )
            self._pak_paths[iid] = pak_path
        self._on_update_applied_status()

    def _on_pak_list_selected(self, _event=None) -> None:
        """PakListSelectedIndexChanged(pakList.SelectedIndexChanged、
        DiveToPalworld.cs L.1126-1137)相当(dev#605)。一覧から過去に変換した
        アバターの行を選ぶと、そのjob.jsonの設定・プレビュー画像を画面へ
        復元する(dev#616 A+I相当の復元処理を_apply_restored_settingsへ
        共通化して使う)。jobDir = dirname(dirname(pak))はC#版と同じ
        (pakは<jobDir>\\build\\*.pak、L.1134/pak_manager.resolve_delete_targets
        と同じ計算)。C#版はpy版に無い非同期アバター読み込み(SetVrmの
        バックグラウンド処理)の取り消し(CancelAvatarLoad、L.1132)も行うが、
        py版の_set_vrm_pathは同期実装で該当する保留読み込みが存在しないため
        対象外(モジュール内に類似の世代カウンタが無いことをgrepで確認済み)。"""
        pak_list = self.widgets["pakList"]
        selection = pak_list.selection()
        if not selection:
            return
        iid = selection[0]
        pak_path = self._pak_paths.get(iid)
        if not pak_path:
            return
        job_dir = os.path.dirname(os.path.dirname(pak_path))
        # LoadPreviews(jd)(L.1135)相当: job.jsonの有無に関わらずまず
        # プレビューを試みる(C#版は無条件呼び出し。job.json不在時の
        # 二重読み込みは_apply_restored_settings内部でも安全に空振りする)。
        try:
            self._apply_previews(pipeline_runner.load_previews(job_dir))
        except Exception as ex:  # noqa: BLE001 -- プレビュー表示の失敗で選択操作自体を壊さない
            self._log(f"[preview] pak list selection preview load failed: {ex}")
        # RestoreSettings(Path.Combine(jd, "job.json"), true)(L.1136)相当。
        self._apply_restored_settings(job_dir, set_vrm_path=True)

    def _on_update_applied_status(self) -> None:
        """UpdateAppliedStatus()(L.3669-3724)相当。ファイルの有無まではUIスレッドで
        即座に確定させ、時間のかかるSHA1照合だけをバックグラウンドスレッドへ出す
        (元の設計方針をそのまま踏襲、L.3665-3668のコメント参照)。"""
        self._applied_status_gen += 1
        gen = self._applied_status_gen
        applied_label = self.widgets["appliedLabel"]
        remove_button = self.widgets["removeButton"]

        paks_dir = pak_manager.paks_dir_quiet(
            self.app_root, cache=self._paks_dir_cache, log=self._log
        )
        if paks_dir is None:
            applied_label.config(text=i18n.S("AppliedStatusNoPaksDir"))
            remove_button.config(state="disabled")
            return
        self._paks_dir_cache = paks_dir

        status = pak_manager.resolve_applied_target(paks_dir)
        remove_button.config(state=("normal" if status["remove_enabled"] else "disabled"))
        if not status["exists"]:
            applied_label.config(text=i18n.S("AppliedStatusNone"))
            return

        target = status["target"]
        try:
            target_len = os.path.getsize(target)
        except OSError:
            applied_label.config(text=i18n.S("AppliedStatusUnknownMod"))
            return

        applied_label.config(text=i18n.S("AppliedStatusChecking"))
        candidates = list(self._pak_candidates)

        def worker() -> None:
            try:
                name = pak_manager.identify_applied_pak(target, target_len, candidates)
            except Exception as ex:  # noqa: BLE001 -- 照合失敗を握りつぶさず見せる(L.3702-3713)
                def on_fail() -> None:
                    if gen != self._applied_status_gen:
                        return
                    applied_label.config(text=i18n.S("AppliedStatusCheckFailed"))
                    self._log(f"[Error] failed to check applied MOD: {ex}")

                self.root.after(0, on_fail)
                return

            def on_done() -> None:
                if gen != self._applied_status_gen:
                    return
                applied_label.config(
                    text=i18n.F("AppliedStatusNamedFormat", name)
                    if name is not None
                    else i18n.S("AppliedStatusUnknownMod")
                )

            self.root.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _resolve_completed_pak_path(self, job_dir: str) -> str | None:
        """OnPipelineDone() L.2924-2936のうち、完成pakの特定部分のみの移植
        (アバター名=Path.GetFileName(jobDir)相当、C#版はここで一覧のListViewItemを
        自動選択するが、dev#606では一覧UI(dev#601領分)に触れない最小経路とする
        ため、pak_manager.list_built_paks(work_root)を直接照合してパスだけを返す)。
        見つからなければNone。"""
        avatar = os.path.basename(job_dir)
        for pak_path, avatar_name in pak_manager.list_built_paks(self._work_root()):
            if avatar_name == avatar:
                return pak_path
        return None

    def _apply_pak_path(self, src: str, avatar_name: str) -> bool:
        """ApplySelected()(L.3791-3827)の中核(ゲーム起動中警告・paksDir解決・
        コピー・失敗時ダイアログ・成功時ステータス/メッセージ)。一覧UI(pakList
        selection)に依存しない直接適用経路として dev#606(自動適用、
        _on_pipeline_exit)と手動の「Palworldに適用」ボタン(_on_apply_selected)の
        双方から共用する(二重実装しない、指示書の明示要求)。戻り値: 適用成功可否。"""
        from tkinter import messagebox

        if not src or not os.path.isfile(src):
            messagebox.showwarning(i18n.S("LabelApply"), i18n.F("MsgModFileNotFoundFormat", src or ""))
            return False
        if pak_manager.is_game_running():
            messagebox.showwarning(i18n.S("LabelApply"), i18n.S("MsgGameRunningApply"))
            return False
        paks_dir = self._resolve_paks_dir_interactive()
        if paks_dir is None:
            return False
        try:
            pak_manager.apply_pak(paks_dir, src)
        except Exception as ex:  # noqa: BLE001 -- ShowApplyFailure相当で分類して見せる
            self._show_apply_failure(
                i18n.S("LabelApply"), os.path.join(paks_dir, pak_manager.INSTALL_NAME), ex
            )
            return False
        self._on_update_applied_status()
        self.widgets["statusLabel"].config(text=i18n.F("StatusAppliedFormat", avatar_name))
        messagebox.showinfo(i18n.S("TitleApplySuccess"), i18n.F("MsgApplySuccessFormat", avatar_name))
        return True

    def _on_apply_selected(self) -> None:
        """ApplySelected()(L.3791-3827)相当。中核処理は_apply_pak_pathへ委譲
        (dev#606で自動適用と共用するため抽出、合理的解釈: 元の呼び出し順序のうち
        ゲーム起動中判定/paksDir解決は共通コアの先頭へ移動したため、pak未検出時の
        警告より後になる。ユーザー可視の分岐・文言は変えていない)。"""
        from tkinter import messagebox

        pak_list = self.widgets["pakList"]
        selection = pak_list.selection()
        if not selection:
            messagebox.showinfo(i18n.S("TitleApplySuccess"), i18n.S("MsgSelectModFromList"))
            return
        iid = selection[0]
        src = self._pak_paths.get(iid)
        avatar_name = pak_list.item(iid, "values")[0]
        if not src or not os.path.isfile(src):
            messagebox.showwarning(i18n.S("LabelApply"), i18n.F("MsgModFileNotFoundFormat", src or ""))
            self._on_refresh_pak_list()
            return
        self._apply_pak_path(src, avatar_name)

    def _on_remove_applied(self) -> None:
        """RemoveApplied()(L.4778-4812)相当。"""
        from tkinter import messagebox

        if pak_manager.is_game_running():
            messagebox.showwarning(i18n.S("LabelRemove"), i18n.S("MsgGameRunningRemove"))
            return
        paks_dir = self._resolve_paks_dir_interactive()
        if paks_dir is None:
            return
        try:
            removed = pak_manager.remove_applied(paks_dir)
        except Exception as ex:  # noqa: BLE001
            self._show_apply_failure(
                i18n.S("LabelRemove"), os.path.join(paks_dir, pak_manager.INSTALL_NAME), ex
            )
            return
        if not removed:
            self.widgets["statusLabel"].config(text=i18n.S("StatusNoModApplied"))
            self._on_update_applied_status()
            return
        self._on_update_applied_status()
        self.widgets["statusLabel"].config(text=i18n.S("StatusModRemoved"))

    def _on_delete_selected(self) -> None:
        """DeleteSelected()(L.3829-3903)相当。"""
        from tkinter import messagebox

        pak_list = self.widgets["pakList"]
        selection = pak_list.selection()
        if not selection:
            return
        iid = selection[0]
        pak_path = self._pak_paths.get(iid)
        avatar_name = pak_list.item(iid, "values")[0]
        if not pak_path:
            return

        targets = pak_manager.resolve_delete_targets(self._work_root(), self.app_root, pak_path)

        lines = [
            i18n.F("ConfirmDeleteHeaderFormat", avatar_name),
            "",
            i18n.F("LineModFileFormat", os.path.basename(pak_path)),
            i18n.F("LineWorkFolderFormat", targets["job_dir"]),
        ]
        if targets["ue_project_dir"] and os.path.isdir(targets["ue_project_dir"]):
            lines.append(i18n.F("LineUeProjectFormat", targets["ue_project_dir"]))
        lines.append("")
        lines.append(i18n.S("NoteVrmNotDeleted"))
        lines.append(i18n.S("NoteReloadVrmToRedo"))

        if not messagebox.askyesno(i18n.S("TitleConfirmDelete"), "\n".join(lines)):
            return

        try:
            pak_manager.delete_avatar_artifacts(targets["job_dir"], targets["ue_project_dir"])
        except OSError as ex:
            messagebox.showerror(i18n.S("TitleConfirmDelete"), i18n.F("MsgDeleteFailedFormat", str(ex)))

        # 「最後に開いたVRM」の記憶が削除対象と同じなら忘れる(残すと次回起動時に
        # 勝手に読み込んで作業フォルダが復活してしまう、L.3878-3890)
        last_vrm = settings.load_last_vrm(self.app_root)
        if last_vrm and pak_manager.sanitize_name(
            os.path.splitext(os.path.basename(last_vrm))[0]
        ) == avatar_name:
            try:
                os.remove(settings.lastvrm_file(self.app_root))
            except OSError:
                pass

        # 削除したのが今開いているアバターなら表示も初期化する(L.3891-3899)
        current_text = self.widgets["vrmBox"].get().strip()
        if current_text and pak_manager.sanitize_name(
            os.path.splitext(os.path.basename(current_text))[0]
        ) == avatar_name:
            self.widgets["vrmBox"].delete(0, tk.END)
            # dev#599: previewFront/previewSideに実画像が表示されている場合、
            # text=だけ書き換えても画像が残って見える(Labelはcompound=none既定で
            # imageがtextより優先表示されるため)。image=""で明示的に外し、
            # 保持していたPhotoImage参照も破棄する(L.3896-3897 previewFront.Image
            # = null相当)。
            self._preview_images.pop("previewFront", None)
            self._preview_images.pop("previewSide", None)
            self.widgets["previewFront"].config(
                image="", text=i18n.S("LabelPreviewPlaceholderFront")
            )
            self.widgets["previewSide"].config(
                image="", text=i18n.S("LabelPreviewPlaceholderSide")
            )

        self._on_refresh_pak_list()
        self.widgets["statusLabel"].config(text=i18n.F("StatusDeletedFormat", avatar_name))

    def _on_toggle_kodawari(self) -> None:
        self._kodawari_open = not self._kodawari_open
        toggle_btn = self.widgets["kodawariToggle"]
        arrow = "▲" if self._kodawari_open else "▼"
        toggle_btn.config(text=f"{arrow} {i18n.S('LabelKodawari')}")
        if self._kodawari_open:
            self._kodawari_panel.place(x=12, y=118, width=1058, height=80)
        else:
            self._kodawari_panel.place_forget()
        self.layout_content_area()

    def _on_language_selected(self, _event=None) -> None:
        idx = i18n.LANG_DISPLAY_NAMES.index(self._lang_combo.get())
        new_lang = i18n.LANGS[idx]
        i18n.apply_language(new_lang)
        settings.save_language_code(self.app_root, i18n.FILE_LANG_CODES[new_lang])
        self._update_window_title()
        pak_list = self.widgets["pakList"]
        for col_id, key in self._pak_list_columns.items():
            pak_list.heading(col_id, text=i18n.S(key))
        toggle_btn = self.widgets["kodawariToggle"]
        arrow = "▲" if self._kodawari_open else "▼"
        toggle_btn.config(text=f"{arrow} {i18n.S('LabelKodawari')}")
        # dev#596: appliedLabel(「適用中: ...」)はi18n.register()の自動再適用
        # registryに載っていない(状態(未確認/なし/内容不明/名前判明)に応じて
        # 都度動的に選ぶ複数キーのため、単一key登録では表現できない)。
        # 言語切替時に再計算しないと、切替前の言語で表示されたテキストが
        # そのまま残り続ける(例: 日本語表示中に検出された「適用中: 内容不明の
        # MODが入っています」が、英語へ切り替えても英訳に更新されない)。
        # 旧DiveToPalworld.cs ApplyLanguage() (L.874-901) がUpdateAppliedStatus()
        # を呼んでいたのと同じ配線を、Python移植で復元する。
        self._on_update_applied_status()

    # -- WP-A2: 変換系ハンドラ(pipeline_runner.py配線) ------------------------
    #
    # 非同期方式はDESIGN.md §4.3どおり: pipeline_runner.ProcessHandleが
    # threading.Thread+queue.Queueで子プロセスの出力を受け取り、ここでは
    # root.after()で定期的にhandle.poll()を呼ぶ(tkinterはメインスレッド以外
    # からのウィジェット操作を許さないため、on_line/on_exitコールバックは
    # poll()を呼んでいるスレッド=メインスレッド上で実行される)。

    _POLL_INTERVAL_MS = 80

    def _on_full_convert(self) -> None:
        self._start_pipeline(preview_only=False, materials_only=False)

    def _on_materials_only(self) -> None:
        self._start_pipeline(preview_only=False, materials_only=True)

    def _on_preview_only(self) -> None:
        self._start_pipeline(preview_only=True, materials_only=False)

    def _ensure_license_confirmed(self) -> bool:
        """EnsureLicenseConfirmed() L.2533-2545相当。"""
        if self._license_confirmed:
            return True
        yes = messagebox.askyesno(i18n.S("TitleLicenseConfirm"), i18n.S("MsgLicenseConfirmBody"))
        if yes:
            self._license_confirmed = True
            return True
        return False

    def _start_pipeline(
        self, *, preview_only: bool, materials_only: bool, auto: bool = False
    ) -> None:
        """RunPipeline() L.2547-2607相当。auto=Trueはdev#611のアバター登録時
        自動プレビュー起動(C#版 RunPipeline(previewOnly, materialsOnly, auto)の
        第3引数相当)。C#版はauto時、二重起動中/ファイル未指定の案内ダイアログも
        出さず黙って見送る(L.2549-2550の `if (!auto) MessageBox.Show(...)`)ため、
        ここでも同様にauto時はダイアログを抑止する。"""
        if self._active_handle is not None and self._active_handle.is_running():
            if not auto:
                messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgAlreadyRunning"))
            return
        vrm_path = self.widgets["vrmBox"].get().strip()
        if not os.path.isfile(vrm_path):
            if not auto:
                messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgSpecifyVrmFile"))
            return
        # MODを作る操作(プレビュー以外)はアバター規約の確認が要る(L.2552相当)。
        # auto経由は常にpreview_only=True(呼び出し元_maybe_auto_preview参照)
        # なのでここには実質来ないが、C#版の分岐順序をそのまま踏襲する。
        if not preview_only and not self._ensure_license_confirmed():
            return

        # silentPreview = auto; (L.2556相当)
        self._silent_preview = auto
        self._pipeline_warnings = []
        self._early_preview_loaded_this_run = False
        self._clear_log()
        self._set_running_ui_state(True)
        self.widgets["statusLabel"].config(
            text=i18n.S("StatusPreviewGenerating") if preview_only
            else i18n.S("StatusMaterialsApplying") if materials_only
            else i18n.S("StatusFullConverting")
        )

        drop_bones_text = self.widgets["dropBonesBox"].get()
        shadow_value = int(float(self.widgets["shadowBar"].get()))
        self._active_handle = pipeline_runner.run_pipeline(
            self.app_root, self.work_root, vrm_path,
            preview_only=preview_only, materials_only=materials_only,
            on_line=self._on_pipeline_line,
            on_exit=lambda code: self._on_pipeline_exit(code, preview_only),
            shoulder_offset_deg=self._shoulder_offset_deg,
            merge_fingers=self._merge_fingers,
            unlit=self._unlit,
            force_two_sided=self._force_two_sided,
            shadow_bar_value=shadow_value,
            drop_bones_text=drop_bones_text,
            license_confirmed=self._license_confirmed,
        )
        self.root.after(self._POLL_INTERVAL_MS, self._poll_active_handle)

    def _on_cancel_convert(self) -> None:
        """cancelButton.Click L.997-1003相当。"""
        if self._active_handle is None or not self._active_handle.is_running():
            return
        if messagebox.askyesno(i18n.S("TitleConfirm"), i18n.S("ConfirmCancelConvertBody")):
            self._active_handle.kill()

    def _on_form_closing(self) -> None:
        """FormClosing(DiveToPalworld.cs L.1292-1305)相当。dev#622:
        WM_DELETE_WINDOW(×ボタン/Alt+F4等)ハンドラとして__init__で登録される。

        dev#640統合(PR #647): C#と同じ順序で、まず
        KillBlenderSetupProcess()(L.1298、Blenderのバックグラウンド初回
        取得プロセスを孤児化させないためのサイレントkill)を**確認無し・
        無条件**で呼ぶ(L.1294-1297のコメントどおり、ユーザーが明示的に
        始めた作業ではない裏方処理のため確認しない。runningProcの有無に
        かかわらず先頭で必ず実行、C#のFormClosingデリゲート本体と同じ順序)。
        `blender_setup.BlenderSetupProcessHandle.kill()`は実行中でなければ
        no-op(dev#640、blender_setup.py参照)。

        続いて変換(またはUnity輸出)がpipeline_runner経由で実行中の場合のみ、
        C#と同じ確認ダイアログ(ConfirmExitWhileRunningBody/TitleConfirm、
        YesNo)を出す(dev#622)。Noならウィンドウを閉じない(`e.Cancel = true`
        相当、ここでは単に何もせず戻ることで同じ効果になる)。Yesなら
        KillConversion()相当(handle.kill()、taskkill /T /Fでプロセス
        ツリーごと終了、pipeline_runner.ProcessHandle.kill()参照)を呼んでから
        ウィンドウを破棄する。"""
        self._blender_setup_process_handle.kill()
        if self._active_handle is not None and self._active_handle.is_running():
            if not messagebox.askyesno(
                i18n.S("TitleConfirm"), i18n.S("ConfirmExitWhileRunningBody")
            ):
                return
            self._active_handle.kill()
        self.root.destroy()

    def _poll_active_handle(self) -> None:
        """dev#592層3(生存防御): handle.poll()がここで例外を出すと、以後
        self.root.after()による再スケジュールが行われずポーリングが恒久
        停止する(dev#592根本原因)。poll()自体はpipeline_runner側でも
        行単位try/exceptで守っているが(層3の本丸)、ここでも例外の有無に
        かかわらず再スケジュールを保証する二段構えにする。"""
        handle = self._active_handle
        if handle is None:
            return
        try:
            handle.poll()
        except Exception as ex:  # noqa: BLE001
            try:
                self._log(f"[poll] unexpected error: {ex}")
            except Exception:  # noqa: BLE001
                pass
        if handle.is_running():
            self.root.after(self._POLL_INTERVAL_MS, self._poll_active_handle)

    def _on_pipeline_line(self, line: str) -> None:
        """AppendLog() L.2838-2883相当。"""
        clean = pipeline_runner.strip_ansi(line)
        marker = pipeline_runner.parse_progress_marker(clean)
        if marker is not None:
            pct, raw_label = marker
            # dev#602: マーカー到着=実進捗が分かっている状態なので、indeterminate
            # (Unity輸出のMarquee相当)が残っていればここでdeterminateへ戻す。
            self._set_busy_bar_mode(pipeline_runner.busy_bar_mode_on_marker())
            self.widgets["busyBar"]["value"] = pct
            label = pipeline_runner.translate_progress_label_dynamic(raw_label)
            self.widgets["statusLabel"].config(text=f"{label}... ({pct}%)")
            # dev#288提案2(早期プレビュー反映、L.2854-2870相当)。dev#532方針A
            # WP-A11/dev#549で結線。1回だけ・失敗しても変換本体には影響させない
            # (try/exceptで握り、ログにだけ残す=「静かにログのみ」)。
            job_dir = self._active_handle.job_dir if self._active_handle else None
            if job_dir and pipeline_runner.should_load_early_preview(
                pct, self._early_preview_loaded_this_run
            ):
                self._early_preview_loaded_this_run = True
                try:
                    self._apply_previews(pipeline_runner.load_previews(job_dir))
                except Exception as ex:  # noqa: BLE001
                    self._log(f"[preview-early] load_previews failed at pct={pct}: {ex}")
            return
        warning = pipeline_runner.parse_avatar_warning(clean)
        if warning is not None:
            self._pipeline_warnings.append(warning)
            return
        self._log(clean)

    def _apply_previews(self, previews: dict[str, str | None]) -> None:
        """LoadPreviews() L.2957-2963相当の反映部分(dev#599で実画像表示に実装)。
        Pillow等の追加依存を使わず、Tk 8.6が標準で持つtk.PhotoImageのネイティブ
        PNGデコードのみで完結させる(同梱ランタイムres\\python_embedにPillowが
        無いため)。読み込み・表示に失敗した場合(ファイル無し・壊れPNG・Tk側の
        デコードエラー等)は例外を握り、従来どおりファイル名文字列表示へ
        フォールバックする(GUIを絶対に殺さない。dev#592の防御思想を踏襲)。"""
        front = previews.get("front")
        side = previews.get("side")
        if front:
            self._set_preview_widget("previewFront", front)
        if side:
            self._set_preview_widget("previewSide", side)

    def _set_preview_widget(self, widget_key: str, image_path: str) -> None:
        """previewFront/previewSideの1枚分の表示を担当。成功時は画像を、
        失敗時はファイル名文字列(従来のプレースホルダ挙動)を表示する。"""
        widget = self.widgets[widget_key]
        try:
            max_width, max_height = self._preview_display_size(widget)
            photo = _load_scaled_preview_image(image_path, max_width, max_height)
            # dev#599: 参照をselfへ保持する(Tkの罠。ローカル変数だけだと
            # このメソッドを抜けた時点でGCされ画像が消える)。
            self._preview_images[widget_key] = photo
            widget.config(image=photo, text="")
        except Exception as ex:  # noqa: BLE001
            self._preview_images.pop(widget_key, None)
            widget.config(image="", text=os.path.basename(image_path))
            self._log(
                f"[preview] failed to load image for {widget_key} "
                f"({os.path.basename(image_path)}): {ex}"
            )

    @staticmethod
    def _preview_display_size(widget: tk.Widget) -> tuple[int, int]:
        """previewFront/previewSideウィジェットの現在の配置(place())から
        表示域の幅・高さを読み取る(#25 layout_content_area()がこだわりパネルの
        開閉に応じてheightを動的変更するため、生成時の固定値ではなく都度
        place_info()から引く)。値が取れない・不正な場合は生成時の初期値
        (380x360、L.583/L.589相当)にフォールバックする。"""
        info = widget.place_info()
        try:
            width = int(info.get("width") or 0)
        except (TypeError, ValueError):
            width = 0
        try:
            height = int(info.get("height") or 0)
        except (TypeError, ValueError):
            height = 0
        return (width if width > 0 else 380, height if height > 0 else 360)

    def _on_pipeline_exit(self, code: int, preview_only: bool) -> None:
        """OnPipelineDone() L.2894-2954相当。dev#600(完了ダイアログ)/dev#601(pak
        一覧更新)/dev#606(MOD自動適用)/dev#611(自動プレビューのsilentPreview抑制)を
        すべて結線する。C#版と同じ順序で統合: 警告 → preview_only分岐(silentPreview
        なら完了ダイアログ抑制、L.2917相当) → (非preview_onlyのみ)一覧更新 →
        自動適用 → 自動適用済みなら完了ダイアログを出さない(autoAppliedフラグ、
        L.2944-2952相当)。"""
        self._set_running_ui_state(False)
        if code != 0:
            self.widgets["statusLabel"].config(text=i18n.S("StatusFailedOrCancelled"))
            return
        # OnPipelineDone() L.2902相当: 全工程完了後に必ず1回、最終結果で再読込する
        # (早期反映が間に合わなかった/失敗した場合の保険を兼ねる)。
        handle = self._active_handle
        if handle is not None and handle.job_dir:
            try:
                self._apply_previews(pipeline_runner.load_previews(handle.job_dir))
            except Exception as ex:  # noqa: BLE001
                self._log(f"[preview-final] load_previews failed: {ex}")
        # OnPipelineDone() L.2905-2910相当: 警告ダイアログは完了ダイアログより先
        # (どちらの分岐でも警告の存在に気付けるよう埋もれさせない)。
        if self._pipeline_warnings:
            messagebox.showwarning(
                i18n.S("TitleConvertDoneWithWarnings"),
                i18n.F("MsgConvertDoneWithWarningsFormat", "\n\n".join(self._pipeline_warnings)),
            )
        if preview_only:
            # dev#613/#617: OnPipelineDone() L.2914-2915相当
            # (`SavePreviewSig(); UpdateButtonStates(); // フル変換ボタンが
            # ここで解禁される`)。StatusPreviewDoneの明示表示より先に行う
            # (C#と同じ順序。_finalize_fresh_preview内のUpdateButtonStates
            # 相当が一時的にStatusReadyToConvert等を書いても、直後にここで
            # StatusPreviewDoneへ上書きされるのはC#と同じ挙動)。
            self._finalize_fresh_preview(self.widgets["vrmBox"].get().strip())
            self.widgets["statusLabel"].config(text=i18n.S("StatusPreviewDone"))
            # dev#600×dev#611: OnPipelineDone() L.2916-2917相当の完了ダイアログ。
            # silentPreview(dev#611、アバター登録時の自動プレビュー)がTrueの間は
            # C#版と同様に抑制する(`if (!silentPreview)`相当)。
            if not self._silent_preview:
                messagebox.showinfo(i18n.S("TitlePreviewDone"), i18n.S("MsgPreviewDoneBody"))
            return
        self.widgets["statusLabel"].config(text=i18n.S("StatusReadyToConvert"))
        # dev#601: OnPipelineDone() L.2919相当のRefreshPakList()結線
        self._on_refresh_pak_list()
        # dev#606: OnPipelineDone() L.2938-2949相当の自動適用結線。完成pakのフル
        # パスをjob_dirから直接解決し、既存の「Palworldに適用」ボタンと同じ中核
        # (_apply_pak_path)を呼ぶ。
        auto_applied = False
        if self._auto_apply_var.get() and handle is not None and handle.job_dir:
            avatar_name = os.path.basename(handle.job_dir)
            pak_path = self._resolve_completed_pak_path(handle.job_dir)
            if pak_path is None:
                self._log(f"[auto-apply] skipped, no completed pak found: {avatar_name}")
            else:
                try:
                    auto_applied = self._apply_pak_path(pak_path, avatar_name)
                except Exception as ex:  # noqa: BLE001 -- 仕様2: 例外は握ってGUIを殺さない
                    auto_applied = False
                    self._log(f"[auto-apply] unexpected exception: {ex}")
                self._log(f"[auto-apply] {'succeeded' if auto_applied else 'failed/aborted'}: {avatar_name}")
        # dev#600: OnPipelineDone() L.2950-2952相当の完了ダイアログ結線。
        # 自動適用済み(autoApplied)なら二重の完了通知を避けるため抑制する。
        if not auto_applied:
            messagebox.showinfo(i18n.S("TitleConvertDone"), i18n.S("MsgConvertDoneBody"))

    def _set_running_ui_state(
        self, running: bool, *, phase: str = pipeline_runner.PHASE_PIPELINE
    ) -> None:
        """UpdateButtonStates()の変換中/非変換中の切替部分に相当する最小版。

        dev#602: phaseは開始時のbusyBarモード決定にのみ使う
        (pipeline_runner.initial_busy_bar_mode()参照)。フル変換
        (phase=PHASE_PIPELINE、既定値)は常にdeterminateから開始する
        ——これにより、直前にUnity輸出(indeterminate)を経由していた場合でも
        残留せず必ずリセットされる(RunPipeline() L.2602/RunUnityExport()
        L.2678の両方が呼び出しのたびにStyleを明示設定するのと同じ)。
        running=False(終了時)もC#版のOnUnityExportDone() L.2686と同じく
        無条件でdeterminateへ戻す。

        dev#613/#617: idleに戻る際、convertButtonの有効化にプレビュー鮮度判定
        (_refresh_convert_button_freshness、IsPreviewFresh相当)を組み込む
        (running中は busy 側で問答無用でdisabled、C#の
        `!busy && hasVrm && fresh && ...` のうち`!busy`部分に相当)。

        dev#621: workRootFailed中は running=False で戻ってきても
        matsButton/previewButtonを再度normalへ戻さない(UpdateButtonStates
        L.2486-2491の`!workRootFailed`条件相当。恒久的な全面無効化)。
        convertButtonは_refresh_convert_button_freshness()側でも同じ
        work_root_failedガードを持つ(このメソッド以外の経路
        ——_on_drop_bones_changed等——からも呼ばれるため、ここだけの
        ガードでは漏れる)。

        dev#639: matsButton/previewButtonの有効/無効自体は
        _update_button_states()(busy/blenderReady/hasVrm/workRootFailed
        ゲート込み、PR #647統合)へ委譲する。
        """
        self._is_pipeline_running = running
        self._update_button_states()
        self.widgets["cancelButton"].config(state=("normal" if running else "disabled"))
        if running:
            self.widgets["convertButton"].config(state="disabled")
            self.widgets["busyBar"]["value"] = 0
            self.widgets["busyBar"].place(**self._busy_bar_geometry)
            self._set_busy_bar_mode(pipeline_runner.initial_busy_bar_mode(phase))
        else:
            self._set_busy_bar_mode(pipeline_runner.BUSY_BAR_MODE_DETERMINATE)
            self._refresh_convert_button_freshness()
            self.widgets["busyBar"].place_forget()

    def _set_busy_bar_mode(self, mode: str) -> None:
        """busyBarのStyle切替(RunPipeline() L.2602 Continuous / RunUnityExport()
        L.2678-2679 Marquee+MarqueeAnimationSpeed=30相当)。indeterminateでは
        ttk Progressbar.start()でアニメーションを開始し(intervalはC#の
        MarqueeAnimationSpeed=30msをそのまま踏襲)、determinateではstop()して
        値表示に戻す。"""
        busy_bar = self.widgets["busyBar"]
        if mode == pipeline_runner.BUSY_BAR_MODE_INDETERMINATE:
            busy_bar.config(mode="indeterminate")
            busy_bar.start(30)
        else:
            busy_bar.stop()
            busy_bar.config(mode="determinate")

    def _update_button_states(self) -> None:
        """UpdateButtonStates()(app\\DiveToPalworld.cs L.2468-2525)のうち、
        matsButton/previewButtonのゲート判定を移植(dev#639)。convertButtonは
        _refresh_convert_button_freshness()側が担当する(鮮度判定
        (dev#613/#617)とblenderReadyが絡むため分離、そちらもdev#639統合で
        blenderReadyゲートを追加済み)。

        C#: previewButton.Enabled = !busy && hasVrm && blenderReady && !workRootFailed;
            matsButton.Enabled    = !busy && hasVrm && blenderReady && !workRootFailed
                                     && HasNoueFullBuild();

        本WP作成時点(#647分岐元)ではhasVrm/workRootFailedの判定コードが
        まだmasterに無かったため`busy`/`blenderReady`の2条件のみで独立追加
        されていたが、#635(dev#613/#617)・#637(dev#621)のマージにより
        `_work_root_failed`判定・vrmBoxウィジェットが揃ったため、本統合
        (Masterライター、PR #647本文の指示どおり)でhasVrm/workRootFailedを
        合流させた。HasNoueFullBuild()はpy版未実装のため引き続き対象外
        (既知のギャップ、matsButton/previewButtonを同一ゲートで扱う)。"""
        vrm_path = self.widgets["vrmBox"].get().strip()
        has_vrm = os.path.isfile(vrm_path)
        enabled = (
            not self._is_pipeline_running
            and self._blender_ready
            and has_vrm
            and not self._work_root_failed
        )
        state = "normal" if enabled else "disabled"
        for key in ("matsButton", "previewButton"):
            self.widgets[key].config(state=state)

    def _clear_log(self) -> None:
        log_box = self.log_box
        log_box.configure(state="normal")
        log_box.delete("1.0", tk.END)
        log_box.configure(state="disabled")

    # -- WP-A2: Unity輸出(RunUnityExport)ハンドラ -----------------------------

    def _on_prefab_selected(self, prefab_path: str) -> None:
        """RunUnityExport() L.2612-2682相当(起動〜完了検知まで)。"""
        if self._active_handle is not None and self._active_handle.is_running():
            messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgOtherProcessRunning"))
            return
        script = pipeline_runner.build_unity_export_script_path(self.app_root)
        if not os.path.isfile(script):
            messagebox.showinfo(
                i18n.S("TitleConfirm"), i18n.F("MsgExportScriptNotFoundFormat", script)
            )
            return
        self._clear_log()
        # dev#602: Unity輸出は構造的に##PROGRESS##マーカーが来ない工程
        # (RunUnityExport() L.2677コメント)なのでindeterminate(Marquee相当)。
        self._set_running_ui_state(True, phase=pipeline_runner.PHASE_UNITY_EXPORT)
        self.widgets["statusLabel"].config(text=i18n.S("StatusUnityExporting"))
        self._active_handle = pipeline_runner.run_unity_export(
            self.app_root, self.work_root, prefab_path,
            on_line=self._on_pipeline_line,
            on_exit=self._on_unity_export_exit,
        )
        self.root.after(self._POLL_INTERVAL_MS, self._poll_active_handle)

    def _on_unity_export_exit(self, code: int) -> None:
        """OnUnityExportDone() L.2684-2718相当。"""
        self._set_running_ui_state(False)
        handle = self._active_handle
        out_dir = handle.out_dir if handle is not None else None
        if code != 0:
            self.widgets["statusLabel"].config(text=i18n.S("StatusUnityExportFailed"))
            messagebox.showerror(i18n.S("TitleUnityExportError"), i18n.S("MsgUnityExportErrorBody"))
            return
        fbx = pipeline_runner.find_exported_fbx(out_dir) if out_dir else None
        if fbx is None:
            self.widgets["statusLabel"].config(text=i18n.S("StatusUnityExportNoFbx"))
            messagebox.showinfo(
                i18n.S("TitleUnityExport"), i18n.F("MsgUnityExportNoFbxFormat", out_dir)
            )
            return
        self.widgets["statusLabel"].config(text=i18n.S("StatusUnityExportDone"))
        self._set_vrm_path(fbx)

    # -- Blender準備(DESIGN.md §2.2、WP-A3。実ロジックはblender_setup.py) --------

    def _ensure_blender_ready_on_startup(self) -> None:
        """EnsureBlenderReadyOnStartup() L.1998-2005相当。既に実行中/準備済みなら
        何もしない(二重起動防止)。それ以外はワーカースレッドへ
        blender_setup.do_ensure_blender_ready()を投げ、UIはブロックしない。
        blenderRetryButtonのクリックからも同じ経路を通る(=失敗時リトライ)。"""
        if self._blender_setup_running or self._blender_ready:
            return
        self._blender_setup_running = True
        self.widgets["blenderRetryButton"].place_forget()
        self.widgets["statusLabel"].config(text=i18n.S("StatusBlenderChecking"))
        threading.Thread(target=self._blender_setup_worker, daemon=True).start()

    def _blender_setup_worker(self) -> None:
        """ワーカースレッド側の実処理。tkinterウィジェットには一切触れず、
        すべて self._blender_queue 経由でメインスレッドへ中継する
        (DESIGN.md §4.3、DoEnsureBlenderReady()のPostToUi相当)。"""

        def on_progress(pct: int, phase: str) -> None:
            self._blender_queue.put(("progress", pct, phase))

        ok, fail_message, action = blender_setup.do_ensure_blender_ready(
            self.app_root,
            on_progress=on_progress,
            process_handle=self._blender_setup_process_handle,
        )
        self._blender_queue.put(("done", ok, fail_message, action))

    def _poll_blender_queue(self) -> None:
        """root.after()による定期ポーリング(DESIGN.md §4.3)。ワーカースレッドが
        _blender_queueへ積んだ進捗中継/完了通知をメインスレッドで消費する。"""
        try:
            while True:
                msg = self._blender_queue.get_nowait()
                if msg[0] == "progress":
                    self._on_blender_progress(msg[1], msg[2])
                elif msg[0] == "done":
                    self._on_blender_setup_done(msg[1], msg[2], msg[3])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_blender_queue)

    def _on_blender_progress(self, pct: int, phase: str) -> None:
        busy_bar = self.widgets["busyBar"]
        busy_bar.place(x=330, y=46, width=740, height=12)
        busy_bar["value"] = pct
        text = i18n.F("StatusBlenderSettingUpFormat", phase, pct)
        self.widgets["statusLabel"].config(text=text)

    def _on_blender_setup_done(
        self, ok: bool, fail_message: str | None, action: blender_setup.BlenderSetupAction
    ) -> None:
        self._blender_setup_running = False
        self._blender_ready = ok
        self.widgets["busyBar"].place_forget()
        # dev#639: blenderReady確定(成功/失敗いずれも)の直後にゲートを
        # 再計算する。失敗時は依然disabledのまま(初期状態からの変化なし)だが、
        # 「blenderReady変化のたびに必ず再計算する」という設計上の対称性を
        # 保つため、成否に関わらず呼ぶ(C#版UpdateButtonStates()もここで
        # 無条件に呼ばれる、L.2073)。
        self._update_button_states()
        if ok:
            self.widgets["statusLabel"].config(text=i18n.S("StatusPromptVrm"))
            self.widgets["blenderRetryButton"].place_forget()
            self._warm_startup_after_blender_ready()
        else:
            text = fail_message or i18n.S("MsgBlenderSetupFailedShort")
            self.widgets["statusLabel"].config(text=text)
            self.widgets["blenderRetryButton"].place(x=330, y=44, width=160, height=36)
        self._log(f"[blender_setup] action={action.value} ok={ok}")

    def _warm_startup_after_blender_ready(self) -> None:
        """dev#532 D1: warm_startup.py(WP-A9)の結線。DoEnsureBlenderReady()
        L.2073-2089の呼び出し順(blenderReady=true確定直後)を踏襲し、warm_
        startup.warm_startup_after_blender_ready()を1回だけ呼ぶ(warm_startup.py
        冒頭docstring「D1への結線手順」のとおり)。プロセス起動を伴うため
        ワーカースレッドで実行し、UIスレッドをブロックしない。"""

        def worker() -> None:
            try:
                blender_exe = blender_setup.find_blender(self.app_root)
                paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
                pak_path = (
                    os.path.join(paks_dir, "Pal-Windows.pak") if paks_dir else None
                )
                warm_startup.warm_startup_after_blender_ready(
                    self.app_root,
                    self._work_root(),
                    blender_exe,
                    pak_path,
                    conversion_pending=self._active_handle is not None,
                )
            except Exception as ex:  # noqa: BLE001 -- warm_startup自体が全例外を
                # 握りつぶす設計だが(warm_startup.py参照)、find_blender()等の
                # 呼び出し前処理の例外はここで追加防御する(起動シーケンスを
                # 絶対に止めないための最終防壁)。
                self.root.after(0, lambda: self._log(f"[warm_startup] skipped: {ex}"))

        threading.Thread(target=worker, daemon=True, name="WarmStartup").start()

    def layout_content_area(self) -> None:
        """#25: LayoutContentArea()相当。こだわりパネルの開閉に応じて
        プレビュー/ログ欄のTop位置を再計算する(DiveToPalworld.cs L.1312-1319
        の簡略移植。厳密なpixel一致はWP-A1の受入対象外)。"""
        top = 210 if not self._kodawari_open else 208
        # 開閉どちらでもほぼ同じ位置に収まるよう、パネル分の高さ(80+余白)を
        # 見込んだ固定値で近似している(本来はkodawariPanelの実高さから計算)
        top = 208 if self._kodawari_open else 190
        bottom_limit = 584 - 10
        height = max(100, bottom_limit - top)
        for key in ("previewFront", "previewSide", "logBox"):
            widget = self.widgets[key]
            x = {"previewFront": 12, "previewSide": 400, "logBox": 790}[key]
            width = {"previewFront": 380, "previewSide": 380, "logBox": 280}[key]
            widget.place(x=x, y=top, width=width, height=height)
