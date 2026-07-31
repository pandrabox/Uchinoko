# -*- coding: utf-8 -*-
"""U6-T1: 自前pakライター(最後のUE依存の排除)。

ディレクトリツリー(または(絶対パス, マウント相対パス)のリスト)から
Palworld互換pak(UE5.1 pak version 11、非圧縮・非暗号化)をUnrealPak.exe無しで
生成する。stdlib のみ使用(pip禁止)。

フォーマットは `research\\ue_exit\\_analyze_pak_format.py` による実物
(UnrealPak.exe生成のvariant_avatar_all.pak、435エントリ)のバイト解剖で実測確定
(docs\\REPORT_U6_*.md 参照)。読み取り側の実装(`vp_core.read_pak_entries`/
`read_pak_index`、Phase1・無改変)を仕様書として突き合わせ済み。

pakレイアウト(先頭からEOFまで、パディング無しで連続):
  [Entry0: LocalHeader(53B) + RawData] [Entry1: ...] ... [EntryN-1: ...]
  [Index blob]
  [FullDirectoryIndex blob]
  [FPakInfo footer(221B)]

LocalHeader(53バイト、非圧縮固定、restore_pak.pyのhoff=offset+28と整合):
  Offset:i64 CompressedSize:i64(=UncompressedSize) UncompressedSize:i64
  CompressionMethodIndex:i32(=0) Hash:20B(data のSHA1) bEncrypted:u8(=0)
  CompressionBlockSize:u32(=0)

Index blob:
  MountPoint:FString NumEntries:i32 PathHashSeed:u64(=0)
  bHasPathHashIndex:i32(=0、本ライターは常にPathHashIndex省略)
  bHasFullDirectoryIndex:i32(=1) FDIOffset:i64 FDISize:i64 FDIHash:20B(SHA1)
  EncodedPakEntries: i32(バイト数) + 生バイト(エントリ毎12B:
      Flags:u32(=0xE0000000、32bit安全offset+32bit安全usize+comp_method=0)
      Offset:u32 UncompressedSize:u32)
  Files(legacy、常に空): i32(=0)

FullDirectoryIndex blob:
  NumDirs:i32
  各ディレクトリ(ソート順、root="/"): DirName:FString NumFiles:i32
    各直下ファイル(ソート順): FileName:FString EncodedOffset:i32
      (EncodedPakEntries内の該当12Bレコードのバイトオフセット)

FPakInfo footer(221バイト、EOF直前):
  bEncryptedIndex:u8(=0) EncryptionKeyGuid:16B(=0) Magic:u32(0x5A6F12E1)
  Version:u32(=11) IndexOffset:i64 IndexSize:i64 IndexHash:20B(SHA1)
  CompressionMethods: 5x32B(=0、本ライターは圧縮方式未使用)

既知の制約(v1):
  - 非圧縮エントリのみ(既存pakが全数非圧縮のため対応不要)
  - PathHashIndexは省略(bHasPathHashIndex=0)。UnrealPak.exeの-List/-Extract
    はFullDirectoryIndexのみで動作することを実測確認(docs\\REPORT_U6_*.md)
  - オフセット/サイズは全エントリ32bit範囲内(<4GB)前提(флаги固定0xE0000000)
"""
import hashlib
import io
import os
import struct

PAK_MAGIC = 0x5A6F12E1
PAK_VERSION = 11
DEFAULT_MOUNT = "../../../Pal/Content/Pal/Model/Character/"


def _fstring(s):
    """ASCII FString: i32 length(含む末尾\\0) + bytes + \\0"""
    b = s.encode("ascii") + b"\x00"
    return struct.pack("<i", len(b)) + b


def _split_rel(rel):
    """'a/b/c.txt' -> ('a/b/', 'c.txt')。'root.txt' -> ('/', 'root.txt')"""
    rel = rel.replace("\\", "/")
    if rel.startswith("/"):
        rel = rel[1:]
    if "/" in rel:
        d, fn = rel.rsplit("/", 1)
        return d + "/", fn
    return "/", rel


def collect_files(root):
    """root配下を再帰的に走査し、(絶対パス, root相対パス(フォワードスラッシュ))
    のリストをソート済みで返す。"""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            out.append((full, rel))
    out.sort(key=lambda t: t[1])
    return out


def build_pak(files, out_path, mount_point=DEFAULT_MOUNT):
    """files: [(abs_source_path, rel_path_in_mount), ...] (rel_pathはフォワード
    スラッシュ、先頭スラッシュ無し)。out_path にpakを書き出す。
    戻り値: {"n_entries": int, "size": int}
    決定論: 入力順序に関わらず rel_path でソートしてから書くため、同一内容の
    再生成は常にバイト一致する。"""
    items = sorted(files, key=lambda t: t[1])

    with open(out_path, "wb") as out:
        encoded_records = []  # (rel_path, enc_off, byte12)
        offsets = {}  # rel -> (offset, size)
        cursor = 0
        for i, (src, rel) in enumerate(items):
            with open(src, "rb") as f:
                data = f.read()
            size = len(data)
            sha1 = hashlib.sha1(data).digest()
            header = (
                struct.pack("<qqq", cursor, size, size)
                + struct.pack("<i", 0)   # CompressionMethodIndex
                + sha1
                + b"\x00"                # bEncrypted
                + struct.pack("<I", 0)   # CompressionBlockSize
            )
            assert len(header) == 53
            out.write(header)
            out.write(data)
            offsets[rel] = (cursor, size)
            enc_off = i * 12
            flags = 0xE0000000
            rec = struct.pack("<III", flags, cursor, size)
            encoded_records.append((rel, enc_off, rec))
            cursor += 53 + size

        n_entries = len(items)

        # --- EncodedPakEntries blob ---
        enc_blob = b"".join(rec for _rel, _off, rec in encoded_records)
        enc_off_by_rel = {rel: off for rel, off, _rec in encoded_records}

        # --- FullDirectoryIndex ---
        dirs = {}  # dirname -> [filenames]
        all_dirnames = set(["/"])
        for _src, rel in items:
            d, _fn = _split_rel(rel)
            parts = d.strip("/").split("/") if d != "/" else []
            acc = ""
            all_dirnames.add("/")
            for p in parts:
                acc += p + "/"
                all_dirnames.add(acc)
        for dn in all_dirnames:
            dirs.setdefault(dn, [])
        for _src, rel in items:
            d, fn = _split_rel(rel)
            dirs[d].append(fn)
        for fnlist in dirs.values():
            fnlist.sort()

        fdi = io.BytesIO()
        fdi.write(struct.pack("<i", len(dirs)))
        for dn in sorted(dirs.keys()):
            fdi.write(_fstring(dn))
            fnlist = dirs[dn]
            fdi.write(struct.pack("<i", len(fnlist)))
            for fn in fnlist:
                full_rel = fn if dn == "/" else dn + fn
                fdi.write(_fstring(fn))
                fdi.write(struct.pack("<i", enc_off_by_rel[full_rel]))
        fdi_blob = fdi.getvalue()
        fdi_hash = hashlib.sha1(fdi_blob).digest()

        fdi_offset = cursor
        out.write(fdi_blob)
        cursor += len(fdi_blob)

        # --- Index blob (written AFTER fdi per confirmed layout order:
        #     entries data -> Index blob -> [PathHashIndex] -> FDI -> footer;
        #     but since bHasPathHashIndex=0 here, actual physical placement
        #     order does not matter as long as offsets in Index are correct.
        #     We place Index blob after FDI for simplicity.) ---
        idx = io.BytesIO()
        idx.write(_fstring(mount_point))
        idx.write(struct.pack("<i", n_entries))
        idx.write(struct.pack("<Q", 0))            # PathHashSeed
        idx.write(struct.pack("<i", 0))            # bHasPathHashIndex = 0
        idx.write(struct.pack("<i", 1))            # bHasFullDirectoryIndex = 1
        idx.write(struct.pack("<q", fdi_offset))
        idx.write(struct.pack("<q", len(fdi_blob)))
        idx.write(fdi_hash)
        idx.write(struct.pack("<i", len(enc_blob)))
        idx.write(enc_blob)
        idx.write(struct.pack("<i", 0))             # legacy Files array, empty
        index_blob = idx.getvalue()
        index_hash = hashlib.sha1(index_blob).digest()

        index_offset = cursor
        out.write(index_blob)
        cursor += len(index_blob)

        # --- FPakInfo footer (221 bytes) ---
        footer = (
            b"\x00"                              # bEncryptedIndex
            + b"\x00" * 16                        # EncryptionKeyGuid
            + struct.pack("<II", PAK_MAGIC, PAK_VERSION)
            + struct.pack("<qq", index_offset, len(index_blob))
            + index_hash
            + b"\x00" * (32 * 5)                  # CompressionMethods
        )
        assert len(footer) == 221
        out.write(footer)
        cursor += len(footer)

    return {"n_entries": n_entries, "size": cursor}


def build_pak_from_dir(root, out_path, mount_point=DEFAULT_MOUNT):
    """root配下を丸ごとpak化する簡易API(build_variant_pak.py等が個別ファイルを
    差し替える用途にはbuild_pak()を直接使う)。"""
    files = collect_files(root)
    return build_pak(files, out_path, mount_point)
