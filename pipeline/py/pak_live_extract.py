# -*- coding: utf-8 -*-
"""工程0補助(U17): Palworld本体のpakから、UnrealPak.exe/UEを使わずその場で
ファイルを抽出する。標準ライブラリのみ使用(MIT)。

圧縮方式Oodle(実測: Pal-Windows.pak圧縮コード1、docs\\REPORT_U17_2026-07-23.md
参照)の解凍だけは、GPLv3ライブラリ(ooz/pyooz)への依存を本体から隔離するため、
別プロセス(ooz_worker_gpl.py、GPLv3)にsubprocess経由で委譲する。本体は
そのプロセスをimportもリンクもしない(mere aggregation)。

使い方:
    from pak_live_extract import extract_files
    files = extract_files(pak_path, ["Pal/Content/.../Foo.uasset", ...])
    # -> {path: bytes}
"""
import os
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core as core

TAG = "pak_live_extract"
_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ooz_worker_gpl.py")
_OOZ_PYTHON_CACHE = None  # 解決済みコマンド([exe, ...args])をプロセス内でキャッシュ


def _resolve_ooz_python():
    """ooz_worker_gpl.py(pyoozをimportする)を実行できるPythonコマンドを解決する。

    注意: 候補③のpyランチャーは、Windowsの「アプリ実行エイリアス」スタブを
    掴まないこと(_is_app_execution_alias)。実行するとMicrosoft Storeが開く。

    U18実測: convert.ps1経由の実運用ではconvert_noue.py自体がBlender同梱Python
    (`sys.executable`)で動く。ところがBlender 4.3.2同梱Pythonにpip installした
    pyoozは`ImportError: DLL load failed`で読み込めない(同一pyoozホイール
    ・同一Pythonマイナーバージョン3.11でも、素のpython.org配布3.11では正常動作
    することを確認済み — Blenderが埋め込む縮小版CPython配布に起因すると推測、
    詳細未解明。docs\\REPORT_U18_2026-07-23.md参照)。
    このため「呼び出し元と同じインタプリタ」を無条件には使わず、実際にooz
    importが通るものを探して使う: ①環境変数D2P_OOZ_PYTHON(明示指定、配布時は
    ここでBlender外の実行系を指すことを想定) → ②sys.executable(素のPythonから
    直接呼ばれる場合や開発時はこれで足りる) → ③pyランチャー(`py -3.11`/`py -3`)。
    見つかった結果はプロセス内でキャッシュする(pak_live_extract.extract_files()は
    1回の変換で複数回呼ばれうるため、毎回probeし直さない)。"""
    global _OOZ_PYTHON_CACHE
    if _OOZ_PYTHON_CACHE is not None:
        return _OOZ_PYTHON_CACHE

    candidates = []
    override = os.environ.get("D2P_OOZ_PYTHON")
    if override:
        candidates.append([override])
    candidates.append([sys.executable])
    py_launcher = shutil.which("py")
    # 2026-07-26: Windowsの「アプリ実行エイリアス」スタブを候補にしない。
    # Pythonが入っていない環境では shutil.which("py") が
    # %LOCALAPPDATA%\\Microsoft\\WindowsApps\\py.exe (0バイトの再解析ポイント)を返し、
    # これを実行すると**Microsoft StoreのPython Install Managerが開く**。
    # capture_output=Trueでも画面には出るため、エンドユーザーの変換中に
    # 身に覚えのないインストーラが立ち上がり、さらにtimeout=30秒ぶん固まる。
    # 候補③に到達するのは②(同梱Blender Python)でooz importが失敗した環境
    # ——つまり元々うまく動いていない人——だけなので、最も出てはいけない場面で出る。
    if py_launcher and _is_app_execution_alias(py_launcher):
        print(f"[{TAG}] py launcher is a Windows App Execution Alias "
              f"(no real binary), excluding from candidates: {py_launcher}")
        py_launcher = None
    if py_launcher:
        candidates.append([py_launcher, "-3.11"])
        candidates.append([py_launcher, "-3"])

    for cmd in candidates:
        try:
            r = subprocess.run(cmd + ["-c", "import ooz"],
                                capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            _OOZ_PYTHON_CACHE = cmd
            return cmd
    core.die(TAG, "no Python runtime that can import pyooz was found. "
             "Set it explicitly via the D2P_OOZ_PYTHON environment variable, or "
             "run `pip install pyooz` against that Python "
             "(see docs\\REPORT_U18_2026-07-23.md)")


def _is_app_execution_alias(path):
    """Windowsの「アプリ実行エイリアス」スタブか判定する。

    スタブは %LOCALAPPDATA%\\Microsoft\\WindowsApps\\ 配下に置かれた0バイトの
    再解析ポイントで、実行するとMicrosoft Storeのインストールページが開く。
    エンドユーザーの環境で身に覚えのないインストーラを出さないため、
    Pythonの実行系候補として採用してはならない。

    判定は2条件の**or**にしている(片方だけだと取りこぼす):
      - パスが WindowsApps 配下にある(既定の置き場)
      - サイズが0バイト(再解析ポイントの実体。別の場所に置かれても効く)
    """
    try:
        norm = os.path.normcase(os.path.abspath(path))
        if os.path.normcase("Microsoft\\WindowsApps") in norm:
            return True
        return os.path.getsize(path) == 0
    except OSError:
        # 判定できないものは「安全側」= 使わない。
        # ここで例外を握りつぶして候補に残すと、まさに防ぎたい実行が起きる
        return True


def _decompress_batch(requests):
    """requests: [(compressed_bytes, expected_size), ...] -> [bytes, ...]
    ooz_worker_gpl.pyへの1回のsubprocess呼び出しにまとめて処理させる
    (ファイル数・ブロック数が多くてもプロセス起動は1回だけ)。"""
    if not requests:
        return []
    payload = bytearray()
    for comp, dlen in requests:
        payload += struct.pack("<I", len(comp))
        payload += comp
        payload += struct.pack("<I", dlen)
    ooz_python = _resolve_ooz_python()
    proc = subprocess.run(
        ooz_python + [_WORKER], input=bytes(payload),
        capture_output=True, check=False)
    if proc.returncode != 0:
        core.die(TAG, f"ooz_worker_gpl.py exited abnormally (code={proc.returncode}): "
                 f"{proc.stderr[-2000:].decode('utf-8', errors='replace')}")
    out = proc.stdout
    pos = 0
    results = []
    for _ in requests:
        status, plen = struct.unpack_from("<BI", out, pos)
        pos += 5
        payload_bytes = out[pos:pos + plen]
        pos += plen
        if status != 0:
            core.die(TAG, f"ooz decompression error: {payload_bytes.decode('utf-8', errors='replace')}")
        results.append(payload_bytes)
    if len(results) != len(requests):
        core.die(TAG, "ooz_worker_gpl.py returned a different number of responses than requested")
    return results


def extract_files(pak_path, rel_paths):
    """pak_path中のrel_pathsを解凍済みの生バイトで返す({path: bytes})。
    rel_pathsはread_pak_index/read_pak_entriesと同じ座標系(mount除いた
    パス、例 "Pal/Content/Pal/Model/Character/Player/.../Foo.uasset")。"""
    mount, entries = core.read_pak_entries(pak_path)
    methods = core.read_pak_compression_methods(pak_path)

    missing = [p for p in rel_paths if p not in entries]
    if missing:
        extra = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
        core.die(TAG, f"path(s) not found in pak: {missing[:5]}{extra}")

    block_requests = []   # [(comp_bytes, expected_chunk_size), ...]
    block_owner = []      # 各リクエストがどのpath由来か(ブロック順を保って追記)
    raw_or_pending = {}   # path -> bytes (非圧縮は即値、圧縮はNoneで後埋め)

    with open(pak_path, "rb") as f:
        for p in rel_paths:
            entry = entries[p]
            if entry["encrypted"]:
                core.die(TAG, f"encrypted entries are unsupported: {p}")
            if entry["compression"] == 0:
                f.seek(entry["data_offset"])
                raw_or_pending[p] = f.read(entry["size"])
                continue
            method_name = methods.get(entry["compression"])
            if method_name != "Oodle":
                core.die(TAG, f"unsupported compression method: {p} "
                         f"code={entry['compression']} name={method_name}")
            off = entry["offset"]
            block_size = entry["block_size"]
            usize = entry["size"]
            produced = 0
            for bstart, bend in entry["blocks"]:
                f.seek(off + bstart)
                comp = f.read(bend - bstart)
                remain = usize - produced
                chunk = min(block_size, remain)
                produced += chunk
                block_requests.append((comp, chunk))
                block_owner.append(p)
            raw_or_pending[p] = None

    if block_requests:
        decompressed_blocks = _decompress_batch(block_requests)
        per_file_chunks = {}
        for p, data in zip(block_owner, decompressed_blocks):
            per_file_chunks.setdefault(p, []).append(data)
        for p, chunks in per_file_chunks.items():
            raw_or_pending[p] = b"".join(chunks)

    result = {}
    for p in rel_paths:
        data = raw_or_pending[p]
        expected = entries[p]["size"]
        if data is None or len(data) != expected:
            got = 0 if data is None else len(data)
            core.die(TAG, f"decompressed size mismatch: {p} got={got} expected={expected}")
        result[p] = data
    return result
