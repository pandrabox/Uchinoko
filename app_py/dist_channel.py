# dist_channel.py -- NormalizeDistChannel/ReadDistChannelFromFile 相当
# (旧 app\DiveToPalworld.cs L.3985-4038, DESIGN.md §5.2 未割当だった機能。
# dev#532 方針A WP-A11(dev#549)で新設)。
#
# 背景(WP-A7調査、dev#549 issue本文参照): 配布チャネル判定ロジックは
# app_py配下のどのファイルにも移植先が明示されていなかった(inquiry.py/
# support_dialog.pyは呼び出し側から渡された channel 文字列をそのまま使うだけ)。
# devtools\stamp_channel.py が配布zipのステージングフォルダ直下へ書き込む
# channel.txt(トップレベル、_internal\ ではない)を読む契約はそのまま踏襲する。
#
# 設計(移植元コメントどおり): channel.txtが無い(=旧zip・スタンプ忘れ・
# 非対応の入手経路)場合はfail-closedで"unknown"に倒す(誤ったチャネルを
# 断定するより安全)。既知の語彙に無い値・複数行に壊れた内容も同様にunknownへ
# 倒れる(部分一致で誤採用しない)。

from __future__ import annotations

import os
from typing import Optional

KNOWN_DIST_CHANNELS = ("booth", "itch", "github", "dev")
UNKNOWN_DIST_CHANNEL = "unknown"


def normalize_dist_channel(raw: Optional[str]) -> str:
    """NormalizeDistChannel() L.4006-4015相当。純粋関数(I/Oなし)。
    trimして完全一致でのみ既知チャネルとして採用する(部分一致はしない)。"""
    if not raw:
        return UNKNOWN_DIST_CHANNEL
    trimmed = raw.strip().lower()
    for known in KNOWN_DIST_CHANNELS:
        if trimmed == known:
            return known
    return UNKNOWN_DIST_CHANNEL


def read_dist_channel_from_file(file_path: str) -> str:
    """ReadDistChannelFromFile() L.4020-4031相当。読み取り失敗
    (ファイル無し・権限エラー等)は例外を握りつぶしてunknownへ倒す。"""
    try:
        if not os.path.isfile(file_path):
            return UNKNOWN_DIST_CHANNEL
        with open(file_path, "r", encoding="utf-8") as f:
            return normalize_dist_channel(f.read())
    except OSError:
        return UNKNOWN_DIST_CHANNEL


def read_dist_channel(app_root: str) -> str:
    """ReadDistChannel() L.4036-4039相当。appRoot直下のchannel.txtを読む
    (devtools\\stamp_channel.py がパッケージング時にのみ書く読み取り専用の
    マーカー、アプリは一切書き込まない)。

    dev#532 D1追記: 旧C#配布物はappRoot(=exeの実体があるフォルダ)がzipの
    ステージングフォルダ直下そのものだったため、stamp_channel.pyが書く
    「ステージングフォルダ直下のchannel.txt」==「appRoot直下のchannel.txt」
    で一致していた。py版配布物(dev#532 WP-B1、DESIGN.md §4.1)はレイアウトが
    変わり、appRoot(=main.pyから見た`os.path.dirname(app_py)`)が`res\\`に
    あたる一方、stamp_channel.pyは相変わらず「zip内の最初の実体エントリの
    ステージングフォルダ直下」==`res\\`の1つ上(Uchinoko.bat/README.txtと同じ
    階層)へ書く(stamp_channel.py自体は変更不要、C5_NOTES.md §2.2で確認済み
    のとおりzip構造非依存)。そのため両者の間に1階層のズレが生じる。
    まずappRoot直下を試し、無ければ1つ上の階層(py版ステージングフォルダの
    実際の書き込み先)もフォールバックとして見る(見つからなければ従来どおり
    unknownへ倒れるだけなので、安全側の拡張)。"""
    direct = read_dist_channel_from_file(os.path.join(app_root, "channel.txt"))
    if direct != UNKNOWN_DIST_CHANNEL:
        return direct
    parent = os.path.dirname(os.path.normpath(app_root))
    if not parent or parent == os.path.normpath(app_root):
        return direct
    return read_dist_channel_from_file(os.path.join(parent, "channel.txt"))
