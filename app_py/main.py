# main.py -- dev#532 方針A Python版GUIのエントリポイント(WP-A1)。
#
# `python app_py\main.py` で直接実行できることが受入条件①
# (DESIGN.md §5.2 WP-A1行)。旧app\build_app.ps1/DiveToPalworld.csの
# Main()(L.6077以降)の「画面ありモード」相当だが、隠しCLI自己診断フラグ
# (--check-*等)はここでは移植していない(WP-A7の担当、DESIGN.md §2.4)。
from __future__ import annotations

import os
import sys

# dev#593: Uchinoko.bat が `start ""` で pythonw.exe を非同期起動するように
# 変わり(batが即returnしてコンソール窓を閉じるため)、従来batが担っていた
# `> res\logs\launch.log 2>&1` のログ取りをここへ移管する。他のアプリ
# import(faulthandler/tkinter/ui.main_window)より前、起動最早期に行うこと
# (それらのimport自体がstdout/stderrに触れる可能性を考慮)。
_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)


class _NullWriter:
    """dev#592/dev#593 stdio硬化の最終フォールバック。launch.logが開けない
    場合(権限等)や、素のpythonw起動で有効なストリームが得られない場合に、
    GUIの動作をログ書き込みの成否に依存させないための、何もしない
    ダミーライター(TextIO互換の最小実装)。"""

    def write(self, _s: object) -> int:
        return 0

    def flush(self) -> None:
        return None


def _resolve_app_root() -> str:
    """appRoot決定の簡略版(DiveToPalworld.cs L.905-912相当)。
    このスクリプト(app_py/main.py)の親ディレクトリをappRootとする
    (app_py/がappRoot直下に置かれるDESIGN.md §4.1のディレクトリ構成どおり)。"""
    return os.path.dirname(_APP_PY_DIR)


def _stream_is_usable(stream: object) -> bool:
    """開発時に `python.exe app_py\\main.py` を直叩きした場合など、既に
    有効なコンソールに繋がったstdout/stderrがあるときはそれをそのまま使う
    (KISS、dev#593指示書の推奨どおり)。配布形態(pythonw.exe + `start ""`)
    では常にNoneになるため、この分岐は事実上開発時専用。"""
    return stream is not None


def _setup_launch_log() -> None:
    """dev#593三重防御の層1(ログ設置)。他のimportより前、起動最早期に呼ぶ
    (このモジュールの他の`import`より上に置いてある)。res\\logs\\launch.log を
    自分で開いてsys.stdout/sys.stderrに据える(従来のbat側 `>` リダイレクト
    と同じ上書き挙動)。
    - 有効なコンソールが既にある(開発時のpython.exe直叩き)なら何もしない
    - 無い/None(配布形態=pythonw.exe + `start ""` では常にこちら)のときだけ
      ファイルへ切り替える: "w"(上書き)・UTF-8・errors="backslashreplace"
      (非ASCII行でのUnicodeEncodeErrorを防ぐ)・buffering=1(行バッファ、
      クラッシュ時も直前までの行を確実に残す)
    - ファイルが開けない場合(権限等)は例外を握ってNullWriterへ
      フォールバックする(GUIの動作をログ書き込み成否に依存させない)
    """
    if _stream_is_usable(sys.stdout) and _stream_is_usable(sys.stderr):
        return
    try:
        log_dir = os.path.join(_resolve_app_root(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(
            os.path.join(log_dir, "launch.log"),
            "w",
            encoding="utf-8",
            errors="backslashreplace",
            buffering=1,
        )
    except OSError:
        sys.stdout = _NullWriter()
        sys.stderr = _NullWriter()
        return
    if not _stream_is_usable(sys.stdout):
        sys.stdout = log_file
    if not _stream_is_usable(sys.stderr):
        sys.stderr = log_file


def _harden_stdio() -> None:
    """dev#592三重防御の層2(stdio硬化)。_setup_launch_log()の直後、他の
    importより前に呼ぶ。dev#593でbat側の`>`リダイレクトが無くなり
    pythonw起動時は常にNoneだったsys.stdout/sys.stderrを、上の
    _setup_launch_log()が先にログファイル/NullWriterへ差し替え済みのはず
    だが、万一それでもNoneが残っていた場合の保険と、開発時の素の
    コンソール(既に有効なストリーム)に対するUnicodeEncodeError対策
    (errors="backslashreplace"へのreconfigure)を両方担う。
    - sys.stdout/sys.stderrがNoneならまだ_NullWriterに差し替える(保険)
    - reconfigureを持つなら errors="backslashreplace" を指定し、ロケール
      (cp932/cp437/EUC-KR等)で表現できない文字を書き込み失敗させず
      \\uXXXX表記へ落とす(encodingそのものは変えない=既存の出力先の
      内容と混在させない)
    - reconfigureが無い/失敗しても例外を握って続行する(この層が失敗しても
      層3の生存防御(_log/poll側のtry/except)が残るため起動を止めない)。"""
    for _name in ("stdout", "stderr"):
        try:
            stream = getattr(sys, _name)
            if stream is None:
                setattr(sys, _name, _NullWriter())
                continue
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is None:
                continue
            try:
                reconfigure(errors="backslashreplace")
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass


_setup_launch_log()
_harden_stdio()

import faulthandler  # noqa: E402
import tkinter as tk  # noqa: E402

from ui.main_window import MainWindow  # noqa: E402


def _enable_faulthandler(app_root: str) -> None:
    """dev#532 D1(環境隔離4層、拘束条件): pythonw.exe配布ではコンソールが
    隠れているため、ネイティブクラッシュ(tkinter/Tcl-Tk側のセグフォルト等、
    Python例外として捕まらない類)が起きると手がかりなしで無言終了しうる。
    faulthandlerを起動時に有効化し、appRoot直下のwork\\フォルダ(書き込み
    権限が既に確認済みの場所、settings.py §2.8と同じappRoot直下規約)へ
    クラッシュダンプ(Cレベルのトレースバック)を残す。失敗しても起動を
    止めない(この保険機構自体が起動を妨げてはならない)。"""
    try:
        log_dir = os.path.join(app_root, "logs")
        os.makedirs(log_dir, exist_ok=True)
        f = open(os.path.join(log_dir, "faulthandler.log"), "a", encoding="utf-8")
        faulthandler.enable(file=f)
    except OSError:
        pass


def main() -> None:
    app_root = _resolve_app_root()
    _enable_faulthandler(app_root)
    root = tk.Tk()
    MainWindow(root, app_root=app_root)
    root.mainloop()


if __name__ == "__main__":
    main()
