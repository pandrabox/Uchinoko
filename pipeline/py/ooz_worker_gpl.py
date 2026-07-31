# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""GPL境界: Oodle互換解凍ライブラリooz(Kraken/Mermaid/Selkie/Leviathan)の
Pythonバインディング`pyooz`(PyPI, GPLv3+)を呼ぶ、単独で完結した別プロセス実行体。

=== ライセンス ===
このファイルはGPLv3(pyoozおよび元のoozライブラリのライセンスを継承する)。
DiveToPalworld本体(MITライセンス)とは別個のプログラムとして扱う。
本体からはsubprocess経由でのみ起動され、importもリンクもされない
(ffmpeg.exe等、GPL/LGPLの外部実行ファイルをMITツールがsubprocessで
呼ぶのと同じ「mere aggregation」構成)。呼び出し側: pak_live_extract.py。
GPLv3全文: https://www.gnu.org/licenses/gpl-3.0.txt
pyooz: https://pypi.org/project/pyooz/ (https://github.com/zao/pyooz)

=== プロトコル(標準入出力、バイナリ、リクエストはEOFまで繰り返し) ===
標準入力(1リクエストにつき):
  uint32 LE  compressed_len
  bytes      compressed_len バイトの圧縮データ
  uint32 LE  expected_decompressed_len
標準出力(入力と同じ順序で1件ずつ):
  uint8      status (0=成功, 1=エラー)
  uint32 LE  payload_len
  bytes      payload_len バイト(成功時は解凍結果、失敗時はUTF-8エラー文字列)
"""
import struct
import sys

import ooz


def _read_exact(f, n):
    data = f.read(n)
    if len(data) != n:
        raise EOFError("unexpected EOF while reading request")
    return data


def main():
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        head = stdin.read(4)
        if len(head) == 0:
            break  # 正常終了(EOF)
        if len(head) != 4:
            raise EOFError("truncated request header")
        (clen,) = struct.unpack("<I", head)
        comp = _read_exact(stdin, clen)
        (dlen,) = struct.unpack("<I", _read_exact(stdin, 4))
        try:
            result = ooz.decompress(comp, dlen)
            stdout.write(struct.pack("<BI", 0, len(result)))
            stdout.write(result)
        except Exception as e:
            msg = str(e).encode("utf-8")
            stdout.write(struct.pack("<BI", 1, len(msg)))
            stdout.write(msg)
    stdout.flush()


if __name__ == "__main__":
    main()
