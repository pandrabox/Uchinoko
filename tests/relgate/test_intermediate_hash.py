# -*- coding: utf-8 -*-
r"""tests\relgate\intermediate_hash.py の単体テスト(WP-C、dev issue #27)。

Blender・実変換を一切使わない純粋部分だけを検査する(WP受入方針:
「そのWPが加えたロジック自体の単体テスト+負の対照」まで。変換を伴う検証は
relgate実走の受入ゲート側で行う)。

実行: python tests\relgate\test_intermediate_hash.py
"""
import json
import os
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intermediate_hash as ih  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def make_png(pixel_byte, extra_text_chunk=False):
    """1x1グレースケールPNGを合成する(標準ライブラリのみ)。
    extra_text_chunk=True なら tEXt(メタデータ)チャンクを差し込む。"""
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    raw = b"\x00" + bytes([pixel_byte])  # filter=0 + 1画素
    idat = chunk(b"IDAT", zlib.compress(raw))
    text = chunk(b"tEXt", b"Comment\x00C:/some/absolute/path/embedded") \
        if extra_text_chunk else b""
    iend = chunk(b"IEND", b"")
    return ih.PNG_SIG + ihdr + text + idat + iend


def main():
    tmp = tempfile.mkdtemp(prefix="ih_test_")

    # 1. canonical_json_hash: キー順・空白に非依存、値には敏感
    a = {"x": 1, "y": [1.5, 2.0], "z": {"b": 1, "a": 2}}
    b = {"z": {"a": 2, "b": 1}, "y": [1.5, 2.0], "x": 1}
    check("canonical_json_hash: キー順非依存", ih.canonical_json_hash(a) == ih.canonical_json_hash(b))
    c = dict(a)
    c["x"] = 2
    check("canonical_json_hash: 値の変化を検出(負の対照)",
          ih.canonical_json_hash(a) != ih.canonical_json_hash(c))

    # 2. png_pixel_hash: メタデータ(tEXt)チャンクに非依存、画素には敏感
    p1 = os.path.join(tmp, "a.png")
    p2 = os.path.join(tmp, "a_with_text.png")
    p3 = os.path.join(tmp, "b_other_pixel.png")
    with open(p1, "wb") as f:
        f.write(make_png(0x40))
    with open(p2, "wb") as f:
        f.write(make_png(0x40, extra_text_chunk=True))
    with open(p3, "wb") as f:
        f.write(make_png(0x41))
    check("png_pixel_hash: tEXt(パス埋め込み等メタデータ)非依存",
          ih.png_pixel_hash(p1) == ih.png_pixel_hash(p2))
    check("png_pixel_hash: 画素の変化を検出(負の対照)",
          ih.png_pixel_hash(p1) != ih.png_pixel_hash(p3))
    p4 = os.path.join(tmp, "not_png.bin")
    with open(p4, "wb") as f:
        f.write(b"not a png at all")
    check("png_pixel_hash: 非PNGはraw:フォールバック",
          ih.png_pixel_hash(p4).startswith("raw:"))

    # 3. 記録IO: roundtrip + schemaゲート
    rec_path = os.path.join(tmp, "rec.json")
    rec = {"schema": ih.SCHEMA, "avatars": {"k": {"intermediate_hash": "h"}}}
    ih.save_record(rec, rec_path)
    loaded = ih.load_record(rec_path)
    check("record roundtrip", loaded == rec)
    bad = dict(rec)
    bad["schema"] = ih.SCHEMA + 999
    ih.save_record(bad, rec_path)
    check("record: schema不一致はNone(=スキップ不可へ倒れる)(負の対照)",
          ih.load_record(rec_path) is None)
    check("record: 存在しないパスはNone",
          ih.load_record(os.path.join(tmp, "nope.json")) is None)

    # 4. pakキャッシュ: 実体化時のsha256再検証(破損キャッシュは拒否)
    cache = os.path.join(tmp, "cache")
    payload = b"fake pak payload"
    sha = ih.sha256_bytes(payload)
    src = os.path.join(tmp, "src.pak")
    with open(src, "wb") as f:
        f.write(payload)
    ih.store_pak_in_cache(src, sha, cache)
    dest = os.path.join(tmp, "out", "dest.pak")
    got = ih.materialize_cached_pak(sha, dest, cache)
    check("pakキャッシュ: 実体化+sha検証OK", os.path.isfile(got))
    # 破損させる: キャッシュ実体を別内容で置き換え(ハードリンクの可能性が
    # あるため、リンクを切ってから書き換える)
    cp = ih.pak_cache_path(sha, cache)
    os.remove(cp)
    with open(cp, "wb") as f:
        f.write(b"corrupted payload!!")
    try:
        ih.materialize_cached_pak(sha, os.path.join(tmp, "out2.pak"), cache)
        check("pakキャッシュ: 破損検出(負の対照)", False, "DigestErrorが出なかった")
    except ih.DigestError:
        check("pakキャッシュ: 破損検出(負の対照)", True)

    # 5. 下流フィンガープリント: 除外リストの適用を確認
    rels = [rel for rel, _ in ih._iter_fingerprint_files()]
    check("fingerprint: step01(上流専用)は除外",
          "pipeline/blender/step01_import_vrm.py" not in rels)
    check("fingerprint: step02(上流専用)は除外",
          "pipeline/blender/step02_retarget.py" not in rels)
    check("fingerprint: convert_noue.py(下流)は含む",
          "pipeline/py/convert_noue.py" in rels)
    check("fingerprint: convert.ps1(オーケストレータ)は含む",
          "pipeline/cli/convert.ps1" in rels)
    check("fingerprint: render_preview.py(層2比較対象の生成コード)は含む",
          "pipeline/blender/render_preview.py" in rels)
    check("fingerprint: 検査側(visual_check.py)は含む",
          "tests/relgate/visual_check.py" in rels)
    # dev#114(2026-07-29): UEクックパイプライン(pipeline/ue/)自体を削除したため、
    # 「除外される」というこの軸のテストは対象消滅につき撤去した
    # (intermediate_hash.FP_EXCLUDE_PREFIXも空タプルに変更済み)。

    # 6. 検証官F2: relgate経由のstrict視覚検査は外部環境変数で解除できない
    os.environ["D2P_STRICT_VISUAL_CHECK"] = "0"
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "..", "devtools"))
    sys.path.insert(0, os.path.join(ih.REPO_DIR, "devtools"))
    import relgate
    env = relgate.build_convert_env()
    check("F2: 外部 D2P_STRICT_VISUAL_CHECK=0 でも relgate経由は '1' に強制(負の対照)",
          env.get("D2P_STRICT_VISUAL_CHECK") == "1",
          f"actual={env.get('D2P_STRICT_VISUAL_CHECK')}")
    os.environ.pop("D2P_STRICT_VISUAL_CHECK", None)

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)}件 — {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
