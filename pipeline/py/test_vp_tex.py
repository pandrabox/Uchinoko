# -*- coding: utf-8 -*-
"""dev#160受入ゲート: vp_tex.extend_opaque_color()(alpha dilation)の自動テスト。

背景(work\\rd_30\\PROPOSAL.md Phase 1): VRM/MToonの透過オーバーレイテクスチャ
(頬染め等)は透明部分のRGBが未定義/黒(0,0,0)埋めであることが多い。
vp_texinject.pyはU50-single裁定によりアルファを常に255へ強制するため、無対策
だと「本来見えないはずの黒背景」が可視化されて顔が真っ黒になる(dev#30)。
extend_opaque_color()を強制不透明化の直前に挿入し、透明画素のRGBを最寄りの
不透明画素の色で埋めることでこれを防ぐ。

G1(既存回帰なしの証明): 全画素alpha>=閾値(=既存の実質全アバター)では
    戻り値が入力とバイト単位で完全一致する(no-op)。
G2(全透明画素のno-op): 不透明画素が皆無の場合もno-op(境界条件)。
G3(負の対照・症状の再現): 意図的に「透明部=黒(0,0,0)埋め」の合成PNGを作り、
    extend_opaque_colorを挟まずに強制不透明化した場合、黒フチが残ることを確認
    (=このテストが無意味でないことの確認。CLAUDE.md「負の対照を取る」)。
G4(修正の効果): 同じ合成PNGにextend_opaque_colorを適用してから強制不透明化
    すると、黒フチが消える(最寄りの不透明画素色で埋まる)ことを確認。
G5(DXT1量子化後も効果が残る): encode_dxt1→decode_dxtのround-trip後も、
    黒(0,0,0)近傍画素の比率が修正前後で明確に減ることを確認
    (実際にpakへ入るバイト列レベルでの検証)。

実行: python test_vp_tex.py
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_tex  # noqa: E402

failures = []


def check(label, cond, detail=""):
    if cond:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} {detail}")
        failures.append(label)


# --------------------------------------------------------- テスト用合成データ

def make_pink_circle_on_black_halo(size=256, radius=64, color=(230, 150, 170)):
    """size四方のキャンバス中央に半径radiusの不透明な色付き円、円の外側は
    alpha=0かつRGB=(0,0,0)(典型的な「透明部分が黒埋め」のオーバーレイ
    テクスチャを模す)。戻り値: (rgba, outside_mask)"""
    import numpy as np
    cx = cy = size // 2
    yy, xx = np.mgrid[0:size, 0:size]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inside = dist <= radius
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[inside, 0] = color[0]
    rgba[inside, 1] = color[1]
    rgba[inside, 2] = color[2]
    rgba[inside, 3] = 255
    return rgba, ~inside


# ------------------------------------------------------------- G1/G2: no-op

def test_noop_when_fully_opaque():
    import numpy as np
    rng = np.random.default_rng(12345)
    rgba = rng.integers(0, 256, size=(32, 32, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255  # 既存の実質全アバター相当(alpha_mode==OPAQUE)
    out = vp_tex.extend_opaque_color(rgba)
    check("fully-opaque input: output bit-identical to input (no-op)",
          out.tobytes() == rgba.tobytes())


def test_noop_when_fully_transparent():
    import numpy as np
    rgba = np.zeros((16, 16, 4), dtype=np.uint8)  # alpha全0(不透明画素が皆無)
    out = vp_tex.extend_opaque_color(rgba)
    check("fully-transparent input: output bit-identical to input (no-op)",
          out.tobytes() == rgba.tobytes())


# --------------------------------------------------- G3: 負の対照(症状の再現)

def test_black_halo_reproduced_without_fix():
    rgba, outside_mask = make_pink_circle_on_black_halo()
    # 現行(修正前)vp_texinject.pyロジックの再現: rgba[:,:,3]=255 のみ適用
    broken = rgba.copy()
    broken[:, :, 3] = 255
    corner = tuple(int(c) for c in broken[0, 0, :3])
    check("negative control: unfixed forced-opaque keeps black halo at corner (0,0,0)",
          corner == (0, 0, 0), f"got {corner}")
    # 円のすぐ外側(境界+6px)も黒のまま
    near_edge = tuple(int(c) for c in broken[128, 128 + 70, :3])
    check("negative control: unfixed forced-opaque keeps black halo near circle edge",
          near_edge == (0, 0, 0), f"got {near_edge}")


# ------------------------------------------------------------- G4: 修正の効果

def test_black_halo_removed_with_fix():
    rgba, outside_mask = make_pink_circle_on_black_halo(color=(230, 150, 170))
    filled = vp_tex.extend_opaque_color(rgba)
    fixed = filled.copy()
    fixed[:, :, 3] = 255
    corner = tuple(int(c) for c in fixed[0, 0, :3])
    check("fixed: corner is no longer pure black",
          corner != (0, 0, 0), f"got {corner}")
    # このキャンバスには不透明色が(230,150,170)の1色しか存在しないため、
    # 近似最近傍フィルであっても到達先は常にこの色になる(決定論的に厳密一致)。
    check("fixed: corner exactly matches the sole opaque color (single-color canvas)",
          corner == (230, 150, 170), f"got {corner}")
    near_edge = tuple(int(c) for c in fixed[128, 128 + 70, :3])
    check("fixed: pixel near circle edge exactly matches the opaque color",
          near_edge == (230, 150, 170), f"got {near_edge}")
    # アルファは既存挙動どおり全画素255(U50-single裁定を変えない)
    check("fixed: alpha is still forced to 255 everywhere (U50-single unchanged)",
          bool((fixed[:, :, 3] == 255).all()))


# --------------------------------------------- G5: DXT1量子化後も効果が残る

def test_dxt1_roundtrip_reduces_black_pixels():
    size = 256
    rgba, outside_mask = make_pink_circle_on_black_halo(size=size)

    broken = rgba.copy()
    broken[:, :, 3] = 255
    filled = vp_tex.extend_opaque_color(rgba)
    fixed = filled.copy()
    fixed[:, :, 3] = 255

    def near_black_count(img):
        rgb = img[:, :, :3].astype(int)
        return int(((rgb < 30).all(axis=2)).sum())

    decoded_before = vp_tex.decode_dxt(vp_tex.encode_dxt1(broken), size, size, "PF_DXT1")
    decoded_after = vp_tex.decode_dxt(vp_tex.encode_dxt1(fixed), size, size, "PF_DXT1")

    before_count = near_black_count(decoded_before)
    after_count = near_black_count(decoded_after)
    check("dxt1 round-trip: near-black pixel count before-fix is large (bug reproduced at byte level)",
          before_count > 0, f"before_count={before_count}")
    check("dxt1 round-trip: near-black pixel count drops sharply after fix",
          after_count < before_count * 0.05,
          f"before={before_count} after={after_count}")


# --------------------------------------------------- dev#288: DXT1速度リファクタ検証
# _color_block()(pipeline\py\vp_tex.py)を、末尾軸reduceに揃えた
# チャンネル優先レイアウト+パレット4色ぶんのPythonループへ書き換えた
# (4096x4096実測でDXT1エンコードが約2.3倍高速化)。アルゴリズム
# (レンジフィット4色モード・距離計算・同値時idx=0)は無改変のはずだが、
# vp_tex内の実装だけで検証すると同じ勘違いを二重に埋め込むリスクがある
# ので、numpyを使わない完全に独立な素朴Python実装(ブロックごとの
# 二重forループ)を用意し、encode_dxt1のバイト列と突き合わせる。

def _pure_python_encode_dxt1(rgba):
    """vp_tex._color_block()と同じレンジフィットDXT1アルゴリズムを、
    numpyベクトル化を一切使わない素朴なPythonループで再実装したもの
    (検証専用の独立経路。本体コードとは別の書き方で同じ仕様を表現する
    ことで、ベクトル化リファクタが仕様を壊していないかを確認できる)。"""
    h, w = rgba.shape[:2]
    ph, pw = (h + 3) // 4 * 4, (w + 3) // 4 * 4
    px = rgba[:, :, :3].tolist()

    def get(y, x):
        yy = min(y, h - 1)
        xx = min(x, w - 1)
        return px[yy][xx]

    def pack565(rgb):
        r, g, b = rgb
        return (((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5
                | ((b * 31 + 127) // 255))

    def unpack565(c):
        r = (c >> 11) & 31
        g = (c >> 5) & 63
        b = c & 31
        return ((r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31)

    out = bytearray()
    for by in range(0, ph, 4):
        for bx in range(0, pw, 4):
            pixels = [get(by + ky, bx + kx) for ky in range(4) for kx in range(4)]
            mn = [min(p[c] for p in pixels) for c in range(3)]
            mx = [max(p[c] for p in pixels) for c in range(3)]
            c0 = pack565(mx)
            c1 = pack565(mn)
            if c0 < c1:
                c0, c1 = c1, c0
            p0 = unpack565(c0)
            p1 = unpack565(c1)
            p2 = tuple((2 * p0[c] + p1[c] + 1) // 3 for c in range(3))
            p3 = tuple((p0[c] + 2 * p1[c] + 1) // 3 for c in range(3))
            pal = [p0, p1, p2, p3]
            idx_bits = 0
            if c0 == c1:
                idx_bits = 0  # flat block: all indices forced to 0
            else:
                for k, p in enumerate(pixels):
                    dists = [sum((p[c] - pal[j][c]) ** 2 for c in range(3)) for j in range(4)]
                    best = dists.index(min(dists))  # first-minimum tie-break, matches np.argmin
                    idx_bits |= best << (k * 2)
            out += struct_pack_u16(c0) + struct_pack_u16(c1) + struct_pack_u32(idx_bits)
    return bytes(out)


def struct_pack_u16(v):
    import struct
    return struct.pack("<H", v)


def struct_pack_u32(v):
    import struct
    return struct.pack("<I", v)


def test_encode_dxt1_matches_pure_python_reference():
    import numpy as np
    rng = np.random.default_rng(288)
    for name, shape in [("8x8", (8, 8, 4)), ("odd_13x9", (13, 9, 4)), ("6x4", (6, 4, 4))]:
        rgba = rng.integers(0, 256, size=shape, dtype=np.uint8)
        got = vp_tex.encode_dxt1(rgba)
        want = _pure_python_encode_dxt1(rgba)
        check(f"encode_dxt1({name}) matches independent pure-Python reference",
              got == want, f"len got={len(got)} want={len(want)}")


def test_encode_dxt1_reference_is_sensitive_negative_control():
    """負の対照: 参照実装(_pure_python_encode_dxt1)が入力の変化に無反応な
    無意味なチェックでないことを確認する。1画素だけ大きく変えれば
    出力バイト列は変わるはず(=上のmatchesテストが偶然一致しているのではなく
    実際にピクセル値を見て計算していることの証拠)。"""
    import numpy as np
    rng = np.random.default_rng(289)
    rgba = rng.integers(0, 256, size=(8, 8, 4), dtype=np.uint8)
    base = _pure_python_encode_dxt1(rgba)
    mutated = rgba.copy()
    mutated[0, 0, :3] = (255 - int(mutated[0, 0, 0]),
                          255 - int(mutated[0, 0, 1]),
                          255 - int(mutated[0, 0, 2]))
    changed = _pure_python_encode_dxt1(mutated)
    check("negative control: mutating one pixel changes the reference encoder's output",
          base != changed)
    # そしてvp_tex.encode_dxt1もこの変化に追随すること(本体とreferenceが
    # 独立に同じ入力依存性を持つことの相互確認)
    check("negative control: vp_tex.encode_dxt1 also reacts to the same mutation",
          vp_tex.encode_dxt1(rgba) != vp_tex.encode_dxt1(mutated))


# --------------------------------------------------------------------------
# dev#288(atlas_bake高速化、decode_png内のPNG Average/Paeth行内逐次ループを
# numpyスカラーアクセスからPython list/bytearrayへ書き換えた際の受入テスト)
#
# 実測(work\speed_mission\atlas\decode_prof.log): Seed-san.vrmの実テクスチャ
# 7枚は行の大半がfilter 4(Paeth。例t01.png: 1024行中927行)で、その行内ループ
# だけでdecode_png全体(7枚で約16秒、cProfile込み)の9割以上を占めていた。
# 数式は一切変えていない(値を寄せる修正ではない)ので、ここでは「PNG仕様
# どおりの独立実装(forward filter、エンコード方向)で作った合成PNGを
# vp_tex.decode_png()に通すと元の画素へ厳密に戻る」ことを、filter 0〜4の
# 全種類・境界条件(1行目=prior無し、先頭bpp列=left無し)を含めて確認する。
# ここでのエンコーダはvp_tex.encode_png/decode_pngとは独立した最小実装
# (常にfilter 0しか吐かないencode_pngでは3/4のテストにならないため)。

def _png_paeth_predictor(a, b, c):
    """PNG仕様のPaeth predictor(vp_tex.decode_pngの実装とは別に独立記述)。"""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _encode_test_png(rgba, filter_types):
    """rgba(h,w,4) uint8 ndarrayを、行ごとにfilter_types[y](0..4)を明示指定して
    PNGバイト列へエンコードする独立実装(テスト専用、vp_tex非依存)。
    PNG仕様どおりのforward filterをPython intのみで素直に書いている。"""
    h, w = rgba.shape[:2]
    ch = 4
    stride = w * ch
    raw_rows = [rgba[y].tobytes() for y in range(h)]
    out = bytearray()
    prev = bytes(stride)
    for y in range(h):
        f = filter_types[y]
        cur = raw_rows[y]
        row = bytearray(stride)
        for x in range(stride):
            left = cur[x - ch] if x >= ch else 0
            up = prev[x]
            up_left = prev[x - ch] if x >= ch else 0
            v = cur[x]
            if f == 0:
                row[x] = v
            elif f == 1:
                row[x] = (v - left) & 0xFF
            elif f == 2:
                row[x] = (v - up) & 0xFF
            elif f == 3:
                row[x] = (v - ((left + up) >> 1)) & 0xFF
            elif f == 4:
                row[x] = (v - _png_paeth_predictor(left, up, up_left)) & 0xFF
            else:
                raise ValueError(f)
        out.append(f)
        out.extend(row)
        prev = bytes(cur)
    idat = zlib.compress(bytes(out), 6)

    def chunk(ctype, body):
        c = ctype + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # colortype 6 = RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def _roundtrip_check(label, rgba, filter_types, tmp_path):
    png_bytes = _encode_test_png(rgba, filter_types)
    with open(tmp_path, "wb") as f:
        f.write(png_bytes)
    w, h, decoded = vp_tex.decode_png(tmp_path)
    check(f"decode_png roundtrip ({label}): dims match",
          (w, h) == (rgba.shape[1], rgba.shape[0]))
    check(f"decode_png roundtrip ({label}): pixels bit-exact",
          decoded.tobytes() == rgba.tobytes())


def test_decode_png_all_filters_roundtrip():
    import numpy as np
    tmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "_tmp_test_decode_png_filters.png")
    try:
        rng = np.random.default_rng(288)
        h, w = 37, 29  # 4の倍数でない幅=境界条件(x<ch分岐)を必ず踏む
        rgba = rng.integers(0, 256, size=(h, w, 4), dtype=np.uint8)

        # 各フィルタ単独(全行同じfilter)
        for ftype, name in ((0, "None"), (1, "Sub"), (2, "Up"),
                             (3, "Average"), (4, "Paeth")):
            _roundtrip_check(f"all rows filter={name}", rgba, [ftype] * h, tmp_path)

        # 実テクスチャの実態に近い「行ごとに混在」(0..4を巡回)
        mixed = [y % 5 for y in range(h)]
        _roundtrip_check("mixed filters per row (0..4 cyclic)", rgba, mixed, tmp_path)

        # Seed-sanの実測で支配的だったAverage/Paeth中心の混在
        heavy = [4 if y % 3 else 3 for y in range(h)]
        _roundtrip_check("Average/Paeth-heavy mix", rgba, heavy, tmp_path)

        # 1行だけの画像(prior行が無い= filter2/3/4の"up"項が常に0になる境界条件)
        rgba1 = rgba[:1]
        for ftype, name in ((3, "Average"), (4, "Paeth")):
            _roundtrip_check(f"single-row image filter={name}", rgba1, [ftype], tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_decode_png_negative_control_mutation_detected():
    """負の対照: roundtripチェック自体が意味を持つことの確認。エンコード側の
    参照実装(_encode_test_png)が生の画素を1つ変えれば、当然decode結果も
    追随して変わる(=このテストがたまたま常にPASSする無意味な比較ではない)。"""
    import numpy as np
    tmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "_tmp_test_decode_png_negctrl.png")
    try:
        rng = np.random.default_rng(291)
        h, w = 12, 12
        rgba = rng.integers(0, 256, size=(h, w, 4), dtype=np.uint8)
        filters = [4] * h
        png_bytes = _encode_test_png(rgba, filters)
        with open(tmp_path, "wb") as f:
            f.write(png_bytes)
        _, _, decoded = vp_tex.decode_png(tmp_path)
        check("negative control setup: decoded matches original before mutation",
              decoded.tobytes() == rgba.tobytes())

        mutated = rgba.copy()
        mutated[5, 5, 1] = (int(mutated[5, 5, 1]) + 123) % 256
        mutated_png = _encode_test_png(mutated, filters)
        check("negative control: mutating one pixel changes the encoded PNG bytes",
              mutated_png != png_bytes)
        with open(tmp_path, "wb") as f:
            f.write(mutated_png)
        _, _, decoded_mut = vp_tex.decode_png(tmp_path)
        check("negative control: decode_png output tracks the mutation (not a no-op check)",
              decoded_mut.tobytes() != decoded.tobytes())
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def main():
    test_noop_when_fully_opaque()
    test_noop_when_fully_transparent()
    test_black_halo_reproduced_without_fix()
    test_black_halo_removed_with_fix()
    test_dxt1_roundtrip_reduces_black_pixels()
    test_encode_dxt1_matches_pure_python_reference()
    test_encode_dxt1_reference_is_sensitive_negative_control()
    test_decode_png_all_filters_roundtrip()
    test_decode_png_negative_control_mutation_detected()

    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
