# preview_freshness.py -- IsPreviewFresh/BuildPreviewSig/SigFile/SavePreviewSig
# 相当(旧 app\DiveToPalworld.cs L.2400-2431)。dev#613/#617。
#
# 背景: dev#611(自動プレビュー結線、PR #612)実装時点で、C#版が持つ
# 「前回と同じ入力・設定ならプレビューを再生成しない」鮮度判定(IsPreviewFresh)
# がpy版に未移植のまま残っていた(main_window.py _maybe_auto_preview()の
# 旧docstring参照)。dev#613: 未変更のアバター再選択でも毎回Blenderが起動する
# 性能ギャップ。dev#617: Full Convertボタン側にも鮮度ゲートが無く、古い
# プレビューのまま気づかず変換できてしまうUXギャップ。両方の根っこは同じ
# BuildPreviewSig/IsPreviewFresh未移植であり、ここへ1本化して両issueから使う。
#
# 移植元(app\DiveToPalworld.cs):
#   - BuildPreviewSig()  L.2402-2408
#   - SigFile()          L.2410-2414
#   - IsPreviewFresh()   L.2416-2425
#   - SavePreviewSig()   L.2427-2430
#
# 忠実移植の方針(指示書: 「C#版の署名方式の忠実移植が正、近似設計禁止」):
#   BuildPreviewSig()のコメント(L.2404)どおり、署名の構成要素はプレビューの
#   見た目(Blenderレンダリング)に影響する4つだけに絞られている:
#     vrmBox.Text.Trim() / shoulderBar.Value.ToString() /
#     mergeFingersCheck.Checked.ToString() / dropBonesBox.Text.Trim()
#   shadowBar(影の濃さ)・unlit・force_two_sidedはBlenderプレビューには出ない
#   (Palworld側のシェーディングにのみ効く)ため、意図的に含まれていない。
#   本モジュールもこの4要素だけを使い、値を寄せたり閾値で近似したりしない。
#
#   C#のbool.ToString()は"True"/"False"(先頭大文字)を返す。Pythonの
#   str(bool(x))も同じ表記("True"/"False")を返すため、ここは近似ではなく
#   表記が偶然完全一致する(str()を使う限り追加のフォーマットは不要)。
#
# py版のUI状態: shoulderBar(肩オフセット)・mergeFingersCheck(指の結合)は
# WP-A1骨格(main_window.py)にまだ対応する可視ウィジェットが無く、内部の
# 隠しフィールド(_shoulder_offset_deg/_merge_fingers、既定値のみ)として
# 存在する(DiveToPalworld.cs L.1042-1046「内部互換性のためにフィールドを
# 初期化(UIには表示しない)」と同じ状態)。呼び出し側(main_window.py)は
# その内部フィールド値をそのまま渡せばよく、本モジュール自体はtkinterは
# もちろんmain_window.pyにも依存しない(pipeline_runner.py同様、pytestで
# ヘッドレスに単体試験できる設計を踏襲)。
#
# 依存: pipeline_runner.sanitize_name()(SanitizeName L.1734-1742と同じ実装、
# 二重実装を避けてそのまま再利用する)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner  # noqa: E402

SIG_FILE_NAME = "preview_sig.txt"


def build_preview_sig(
    vrm_path: str,
    shoulder_offset_deg: int,
    merge_fingers: bool,
    drop_bones_text: str,
) -> str:
    """BuildPreviewSig() L.2402-2408相当。"|"区切りで4要素を結合するだけの
    純関数(ファイルI/Oなし)。"""
    return "|".join(
        [
            vrm_path.strip(),
            str(int(shoulder_offset_deg)),
            str(bool(merge_fingers)),
            drop_bones_text.strip(),
        ]
    )


def sig_file_path(work_root: str, vrm_path: str) -> str:
    """SigFile() L.2410-2414相当。workRoot/<SanitizeName(拡張子抜きファイル名)>/
    preview_sig.txt。"""
    name = pipeline_runner.sanitize_name(
        os.path.splitext(os.path.basename(vrm_path))[0]
    )
    return os.path.join(work_root, name, SIG_FILE_NAME)


def is_preview_fresh(
    work_root: str,
    vrm_path: str,
    shoulder_offset_deg: int,
    merge_fingers: bool,
    drop_bones_text: str,
) -> bool:
    """IsPreviewFresh() L.2416-2425相当。ファイル無し・読み取り失敗はFalse
    (=stale扱い、C#のtry/catchでfalseを返す分岐と同じ)。"""
    f = sig_file_path(work_root, vrm_path)
    try:
        with open(f, "r", encoding="utf-8") as fh:
            saved = fh.read()
    except OSError:
        return False
    return saved == build_preview_sig(
        vrm_path, shoulder_offset_deg, merge_fingers, drop_bones_text
    )


def save_preview_sig(
    work_root: str,
    vrm_path: str,
    shoulder_offset_deg: int,
    merge_fingers: bool,
    drop_bones_text: str,
) -> None:
    """SavePreviewSig() L.2427-2430相当。File.WriteAllText(f, sig,
    new UTF8Encoding(false))と同じくBOM無しUTF-8・末尾改行を追加しない。
    C#と同じくtry/exceptで書き込み失敗(ディレクトリ未作成など)を握りつぶす
    (呼び出し前提: workRoot/<name>/はpipeline_runner.write_job()が変換開始時に
    既に作成済みのため、通常はここで失敗しない)。"""
    f = sig_file_path(work_root, vrm_path)
    try:
        with open(f, "w", encoding="utf-8", newline="") as fh:
            fh.write(
                build_preview_sig(
                    vrm_path, shoulder_offset_deg, merge_fingers, drop_bones_text
                )
            )
    except OSError:
        pass
