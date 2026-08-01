# -*- coding: utf-8 -*-
"""dev#532 方針A WP-A11(dev#549): 旧 tests\\shipcheck\\test_dist_channel_cs.py
(app\\DiveToPalworld.cs CheckDistChannelLogic、NormalizeDistChannel()/
ReadDistChannelFromFile())のPython版試験。

移植先: app_py\\dist_channel.py(dev#549で新設。WP-A7調査時点では未移植
だったため本ファイルはpytest.skipで不在を可視化していたが、WP-A11で
移植が完了したため、旧 tests\\shipcheck\\test_dist_channel_cs.py の
10ケース(case1-10)をここへ1:1移植した)。

検査しているケース(app\\DiveToPalworld.cs CheckDistChannelLogic L.4041-4082):
  case1-4 … 既知チャネル(booth/itch/github/dev)の正規化、大小文字・前後空白を許容
  case5/6 … 空文字・null -> unknown(負の対照)
  case7   … 語彙に無い値(steam等)を断定しない(負の対照、誤ラベル防止)
  case8   … 壊れたマーカー内容(複数行)の部分一致を防ぐ(負の対照)
  case9   … 実ファイル読み取り経由の正の対照
  case10  … マーカーファイルが存在しない(=従来のcanonical zip)場合はunknown
             (受入条件の核心: 「マーカー無しzip=従来挙動でunknown表示」)
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import dist_channel as dc  # noqa: E402


def test_case1_to_4_known_channels_normalize():
    assert dc.normalize_dist_channel("booth") == "booth"
    assert dc.normalize_dist_channel("  ITCH  \r\n") == "itch"
    assert dc.normalize_dist_channel("GitHub") == "github"
    assert dc.normalize_dist_channel("dev") == "dev"


def test_case5_6_empty_and_none_are_unknown():
    assert dc.normalize_dist_channel("") == dc.UNKNOWN_DIST_CHANNEL
    assert dc.normalize_dist_channel(None) == dc.UNKNOWN_DIST_CHANNEL


def test_case7_unknown_vocabulary_is_not_passed_through():
    assert dc.normalize_dist_channel("steam") == dc.UNKNOWN_DIST_CHANNEL


def test_case8_corrupted_multiline_content_does_not_partial_match():
    assert dc.normalize_dist_channel("booth\nextra garbage") == dc.UNKNOWN_DIST_CHANNEL


def test_case9_real_file_read_reflects_content(tmp_path):
    tmp_file = tmp_path / ("d2p_channel_check_" + uuid.uuid4().hex + ".txt")
    tmp_file.write_text("itch", encoding="utf-8")
    assert dc.read_dist_channel_from_file(str(tmp_file)) == "itch"


def test_case10_marker_file_absent_is_unknown(tmp_path):
    missing_file = tmp_path / ("d2p_channel_missing_" + uuid.uuid4().hex + ".txt")
    assert dc.read_dist_channel_from_file(str(missing_file)) == dc.UNKNOWN_DIST_CHANNEL


def test_read_dist_channel_uses_app_root_channel_txt(tmp_path):
    """ReadDistChannel() L.4036-4039相当: appRoot直下のchannel.txtを読む。"""
    (tmp_path / "channel.txt").write_text("github", encoding="utf-8")
    assert dc.read_dist_channel(str(tmp_path)) == "github"


def test_read_dist_channel_falls_back_to_parent_for_py_layout(tmp_path):
    """dev#532 D1: py版配布物ではappRoot(=`res\\`)がstamp_channel.pyの書き込み先
    (ステージングフォルダ直下、`res\\`の1つ上)より1階層深い。appRoot直下に
    channel.txtが無い場合、1つ上の階層(実際にstamp_channel.pyが書く場所)も
    フォールバックとして読む。"""
    staging = tmp_path / "Uchinoko_for_Palworld"
    res_dir = staging / "res"
    res_dir.mkdir(parents=True)
    (staging / "channel.txt").write_text("itch", encoding="utf-8")
    assert dc.read_dist_channel(str(res_dir)) == "itch"


def test_read_dist_channel_direct_takes_priority_over_parent(tmp_path):
    """appRoot直下に有効なマーカーがあれば、親階層は見に行かず優先する
    (旧C#配布物のappRoot==ステージングフォルダ直下という前提を壊さない)。"""
    staging = tmp_path / "Uchinoko_for_Palworld"
    staging.mkdir(parents=True)
    (staging / "channel.txt").write_text("booth", encoding="utf-8")
    assert dc.read_dist_channel(str(staging)) == "booth"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
