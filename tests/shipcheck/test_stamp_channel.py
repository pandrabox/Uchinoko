# -*- coding: utf-8 -*-
r"""dev#260: devtools\stamp_channel.py の単体試験。

配布チャネル(booth/itch/github/dev)マーカーをcanonical zipへ後付けする
スタンプツールが、正しくマーカーを追加/上書きし、かつ**入力zipには一切
手を触れない**ことを確認する。

2026-07-31: ランチャー廃止で配布レイアウトから_internal\が消え、
マーカーの置き場所はステージングフォルダ直下(トップレベル)のchannel.txtへ
変わった。本テストもフラット構成の実物に合わせて追随させた。

検査しているケース:
  正の対照①: ステージングフォルダ直下にマーカーが無いcanonical zip(=現行の
             実物と同形、フラット構成)をスタンプすると、指定チャネルの内容で
             channel.txtが追加されること
  正の対照②: 既にchannel.txtが存在するzip(再スタンプ)を別チャネルでスタンプ
             すると、上書きされ2重に増えないこと
  負の対照①(受入条件の核心): 入力zip自体は一切書き換わらないこと
             (=マーカー無しのcanonical zipのまま。GUI側は
             app\DiveToPalworld.cs の CheckDistChannelLogic case10と対応する
             「マーカー無しzip=unknown表示」の前提そのもの)
  負の対照②: 未知のチャネル文字列は拒否されること(exit non-zero)
  負の対照③: zip内にステージングフォルダの階層(パス区切りを含むエントリ)が
             無い想定外の構造はエラーで停止すること

実行: python -m pytest tests\shipcheck\test_stamp_channel.py -v
"""
import os
import subprocess
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
STAMP_PY = os.path.join(REPO, "devtools", "stamp_channel.py")
STAGE = "Uchinoko_for_Palworld"


def _make_canonical_zip(path, extra_entries=None):
    """実物のcanonical zip(フラット構成、STAGE直下に各種ファイル、channel.txtは無し)を模す。"""
    entries = [
        (STAGE + "/README.md", b"readme"),
        (STAGE + "/LICENSE", b"license"),
        (STAGE + "/pipeline/py/dummy.py", b"# dummy"),
    ]
    if extra_entries:
        entries += extra_entries
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return path


def _run(args):
    proc = subprocess.run(
        [sys.executable, STAMP_PY] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def _read_marker(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.replace("\\", "/").rstrip("/") == STAGE + "/channel.txt":
                return zf.read(name).decode("utf-8").strip()
    return None


def test_stamp_adds_marker(tmp_path):
    src = _make_canonical_zip(tmp_path / "canonical.zip")
    out = tmp_path / "canonical_booth.zip"
    code, log = _run([str(src), "booth", "--out", str(out)])
    assert code == 0, log
    assert os.path.isfile(out)
    assert _read_marker(out) == "booth"


def test_stamp_does_not_mutate_input(tmp_path):
    """負の対照(受入条件の核心): 入力zipはスタンプ前後でバイト同一のままであること。
    これが崩れるとrelease.pyが記録したsha256と食い違ってしまう。"""
    src = _make_canonical_zip(tmp_path / "canonical.zip")
    before = open(src, "rb").read()
    out = tmp_path / "canonical_itch.zip"
    code, log = _run([str(src), "itch", "--out", str(out)])
    assert code == 0, log
    after = open(src, "rb").read()
    assert before == after, "入力zipのバイト列が変化した(スタンプが読み取り専用でない)"
    # 入力zip自体にはマーカーが無いまま(=従来のcanonical zipと同じ状態)
    assert _read_marker(src) is None


def test_restamp_overwrites_not_duplicates(tmp_path):
    """既にマーカー入りのzip(前段のstamp出力をさらに別チャネルでスタンプ)を
    再スタンプしても、channel.txtエントリが2重に増えたりしないこと。"""
    src = _make_canonical_zip(tmp_path / "canonical.zip")
    once = tmp_path / "once_booth.zip"
    code, log = _run([str(src), "booth", "--out", str(once)])
    assert code == 0, log
    twice = tmp_path / "twice_itch.zip"
    code, log = _run([str(once), "itch", "--out", str(twice)])
    assert code == 0, log
    with zipfile.ZipFile(twice) as zf:
        marker_entries = [n for n in zf.namelist() if n.replace("\\", "/").rstrip("/") == STAGE + "/channel.txt"]
    assert len(marker_entries) == 1, "channel.txtエントリが重複している: {}".format(marker_entries)
    assert _read_marker(twice) == "itch"


def test_unknown_channel_rejected(tmp_path):
    """負の対照: 未知のチャネル文字列(語彙に無い値)はargparseのchoicesで拒否され、
    誤ったラベルのzipが作られないこと。"""
    src = _make_canonical_zip(tmp_path / "canonical.zip")
    out = tmp_path / "canonical_steam.zip"
    code, log = _run([str(src), "steam", "--out", str(out)])
    assert code != 0, log
    assert not os.path.isfile(out)


def test_missing_stage_folder_aborts(tmp_path):
    """負の対照: ステージングフォルダの階層(パス区切りを含むエントリ)を持たない
    想定外のzip構造はfail-closedで停止すること(誤って別物のzipに書き込んで
    しまう事故を防ぐ)。"""
    bogus = tmp_path / "bogus.zip"
    with zipfile.ZipFile(bogus, "w") as zf:
        zf.writestr("just_a_file.txt", b"no stage folder here")
    out = tmp_path / "bogus_booth.zip"
    code, log = _run([str(bogus), "booth", "--out", str(out)])
    assert code != 0, log
    assert "ステージングフォルダ" in log
    assert not os.path.isfile(out)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
