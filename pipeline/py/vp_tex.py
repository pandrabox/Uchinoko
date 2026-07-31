# -*- coding: utf-8 -*-
"""テクスチャ処理: PNGデコード(stdlib+numpy)・ミップ生成・DXT1/DXT5エンコード/デコード。

sanitizedpakのsanitize(ピクセルハッシュ記録)とrestore(PNG→DXT注入)の共通部品。
numpyはBlender同梱Pythonのsite-packagesにあるものを使う(pip禁止の範囲内)。
復元はUE非依存が要件(docs\sanitizedpak_design.md)なので、エンコードは自前実装。
品質はレンジフィット(min/max端点)方式 — 定番エンコーダより僅かに落ちるが
色改変ユースケースには十分。受入はPSNRゲート+目視プレビューで判定する。
"""

import hashlib
import struct
import zlib


# ------------------------------------------------------------------ PNG decode

def decode_png(path):
    """PNG→(w, h, RGBA ndarray(h,w,4) uint8)。8bit・非インターレースのみ対応。
    フィルタ0/1/2は完全ベクトル化、3/4(Average/Paeth)は行内逐次(実測で許容)。"""
    import numpy as np
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"not a PNG: {path}")
    pos = 8
    w = h = colortype = None
    palette = trns = None
    idat = []
    while pos + 8 <= len(data):
        (ln,) = struct.unpack_from(">I", data, pos)
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if ctype == b"IHDR":
            w, h, bitdepth, colortype, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", body)
            if bitdepth != 8:
                raise RuntimeError(f"bitdepth {bitdepth} unsupported (8bit only): {path}")
            if interlace != 0:
                raise RuntimeError(f"interlaced PNG is unsupported: {path}")
        elif ctype == b"PLTE":
            palette = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3)
        elif ctype == b"tRNS":
            trns = np.frombuffer(body, dtype=np.uint8)
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
    if w is None:
        raise RuntimeError(f"no IHDR: {path}")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colortype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    if len(raw) != h * (stride + 1):
        raise RuntimeError(f"PNG data length mismatch: {path}")
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, stride + 1)
    filters = arr[:, 0]
    rows = arr[:, 1:].astype(np.int32)
    out = np.zeros((h, stride), dtype=np.uint8)
    zero = np.zeros(stride, np.int32)
    for y in range(h):
        f = int(filters[y])
        cur = rows[y]
        prev = out[y - 1].astype(np.int32) if y > 0 else zero
        if f == 0:
            line = cur
        elif f == 1:    # Sub: チャネル独立のcumsum(mod 256)
            line = cur.reshape(-1, ch).cumsum(axis=0, dtype=np.int64).reshape(-1)
        elif f == 2:    # Up
            line = cur + prev
        elif f == 3:    # Average(行内逐次)
            # dev#288(atlas_bake高速化): 数式は無変更、実装だけ高速化。
            # numpyのスカラー要素アクセス(line[x-ch]等)は1回ごとに
            # box化のオーバーヘッドがあり、実測でこの行内ループが
            # decode_png全体の9割以上を占めていた(Seed-san 7枚で約10秒)。
            # 純Pythonのlist/bytearrayへ一度だけ変換して同じ算術を行うと、
            # 出力バイトは1ビットも変えずに速くなる(値を寄せる修正ではない)。
            cur_l = cur.tolist()
            prev_l = prev.tolist()
            buf = bytearray(stride)
            for x in range(stride):
                a = buf[x - ch] if x >= ch else 0
                buf[x] = (cur_l[x] + ((a + prev_l[x]) >> 1)) & 0xFF
            out[y] = np.frombuffer(bytes(buf), dtype=np.uint8)
            continue
        elif f == 4:    # Paeth(行内逐次、上と同じ理由で同じ高速化)
            cur_l = cur.tolist()
            prev_l = prev.tolist()
            buf = bytearray(stride)
            for x in range(stride):
                a = buf[x - ch] if x >= ch else 0
                b = prev_l[x]
                c = prev_l[x - ch] if x >= ch else 0
                p = a + b - c
                pa = p - a if p >= a else a - p
                pb = p - b if p >= b else b - p
                pc = p - c if p >= c else c - p
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                buf[x] = (cur_l[x] + pr) & 0xFF
            out[y] = np.frombuffer(bytes(buf), dtype=np.uint8)
            continue
        else:
            raise RuntimeError(f"unknown PNG filter {f}: {path}")
        out[y] = (line & 0xFF).astype(np.uint8)

    px = out.reshape(h, w, ch)
    full = np.full((h, w, 1), 255, np.uint8)
    if colortype == 6:
        rgba = px.copy()
    elif colortype == 2:
        rgba = np.concatenate([px, full], axis=2)
    elif colortype == 0:
        rgba = np.concatenate([px, px, px, full], axis=2)
    elif colortype == 4:
        g = px[:, :, 0:1]
        rgba = np.concatenate([g, g, g, px[:, :, 1:2]], axis=2)
    else:  # 3: palette
        if palette is None:
            raise RuntimeError(f"palette PNG has no PLTE: {path}")
        idx = px[:, :, 0]
        rgb = palette[idx]
        if trns is not None:
            a = np.full(len(palette), 255, np.uint8)
            a[:len(trns)] = trns
            alpha = a[idx][:, :, None]
        else:
            alpha = full
        rgba = np.concatenate([rgb, alpha], axis=2)
    return w, h, np.ascontiguousarray(rgba)


def pixel_sha1(rgba):
    """デコード後RGBAピクセル列のSHA1(無改変検知用。ファイル再保存に不変)"""
    return hashlib.sha1(rgba.tobytes()).hexdigest()


def encode_png(path, rgba):
    """(h,w,4) uint8 → PNG書き出し(フィルタ0固定・zlib。検証・プレビュー用)"""
    import numpy as np
    h, w = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))
    comp = zlib.compress(raw, 6)

    def chunk(ctype, body):
        c = ctype + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


# ------------------------------------------------------------- alpha dilation

def extend_opaque_color(rgba, alpha_threshold=16):
    """透明に近い画素(alpha < alpha_threshold)のRGBを、最も近い不透明画素の
    色で埋める(テクスチャ制作の定番手法=padding/dilation)。強制不透明化の
    直前に呼ぶことで「透明部分の未定義/黒背景が可視化される」事故を防ぐ
    (dev#30、work\\rd_30\\PROPOSAL.md Phase 1)。
    不透明画素が皆無、または全画素が不透明ならno-op(既存挙動を完全維持、
    バイト単位で入力をそのまま返す)。
    ステップ幅を1→2→4→...と倍加させながらnp.rollで4方向に伝搬させる
    O(log(max(h,w)))パスの近似最近傍フィル(固定半径のマジックナンバーを
    避けるため、キャンバスサイズに関わらず完全にフィルされるまで回す)。"""
    import numpy as np
    h, w = rgba.shape[:2]
    opaque = rgba[:, :, 3] >= alpha_threshold
    if opaque.all() or not opaque.any():
        return rgba
    rgb = rgba[:, :, :3].astype(np.float32).copy()
    filled = opaque.copy()
    step = 1
    max_dim = max(h, w)
    while step < max_dim:
        for dy, dx in ((step, 0), (-step, 0), (0, step), (0, -step)):
            src_filled = np.roll(filled, (dy, dx), axis=(0, 1))
            src_rgb = np.roll(rgb, (dy, dx), axis=(0, 1))
            take = (~filled) & src_filled
            rgb[take] = src_rgb[take]
            filled |= take
        step *= 2
    out = rgba.copy()
    out[:, :, :3] = rgb.astype(np.uint8)
    return out


# -------------------------------------------------------------------- mip 生成

def _rescale_alpha_coverage(mip, base_cov, threshold=128):
    """mip(h,w,4)のアルファチャンネルを、閾値threshold(既定128=0.5)での
    カバー率(alpha>=threshold の画素比率)がbase_cov(元画像=mip0のカバー率)に
    一致するようスケール補正する(alpha-to-coverage、mip単位の大域スケール版)。
    箱フィルタ後のアルファ値の降順ソートでbase_cov番目の値を求め、それが
    ちょうどthresholdに写る係数を掛けるだけの閉形式(二分探索不要)。"""
    import numpy as np
    a = mip[:, :, 3].astype(np.float64)
    n = a.size
    if n == 0:
        return mip
    target_count = max(0, min(n, int(round(base_cov * n))))
    out = mip.copy()
    if target_count <= 0:
        out[:, :, 3] = 0
        return out
    if target_count >= n:
        out[:, :, 3] = 255
        return out
    t_needed = np.sort(a.ravel())[::-1][target_count - 1]
    if t_needed <= 0:
        out[:, :, 3] = 0
        return out
    scale = threshold / t_needed
    out[:, :, 3] = np.clip(a * scale, 0, 255).astype(np.uint8)
    return out


def make_mips(rgba, num_levels, alpha_coverage=False, alpha_threshold=128):
    """箱フィルタで num_levels 段のミップ列を返す(先頭=元解像度)。2の冪前提

    alpha_coverage=True の場合、各ミップのアルファチャンネルを
    「alpha_threshold(既定128=0.5)でのカバー率が元画像(mip0)と一致する」よう
    スケール補正する(alpha-to-coverage。alpha_mode=="MASK"のアルファテスト
    用途で、単純な箱フィルタがカバレッジを潰す既知の不具合パターンへの対策。
    既定False=従来どおりの単純箱フィルタ、呼び出し元を明示指定しない限り
    挙動は無変更)。RGBチャンネルは常に従来どおりの箱フィルタ。"""
    import numpy as np
    mips = [rgba]
    base_cov = None
    if alpha_coverage:
        base_cov = float((rgba[:, :, 3] >= alpha_threshold).mean())
    cur = rgba
    for _ in range(num_levels - 1):
        h, w = cur.shape[:2]
        nw, nh = max(1, w // 2), max(1, h // 2)
        c = cur.astype(np.uint16)
        if w > 1 and h > 1:
            m = (c[0::2, 0::2] + c[1::2, 0::2] + c[0::2, 1::2] + c[1::2, 1::2] + 2) >> 2
        elif w > 1:
            m = (c[:, 0::2] + c[:, 1::2] + 1) >> 1
        else:
            m = (c[0::2, :] + c[1::2, :] + 1) >> 1
        cur = m.astype(np.uint8).reshape(nh, nw, 4)
        if alpha_coverage:
            cur = _rescale_alpha_coverage(cur, base_cov, alpha_threshold)
        mips.append(cur)
    return mips


# --------------------------------------------------------------- DXT1 / DXT5

def _to_blocks(rgba):
    """(h,w,4)→(n,16,4) 4x4ブロック列(端は複製パディング)"""
    import numpy as np
    h, w = rgba.shape[:2]
    ph, pw = (h + 3) // 4 * 4, (w + 3) // 4 * 4
    if ph != h or pw != w:
        img = np.empty((ph, pw, 4), np.uint8)
        img[:h, :w] = rgba
        img[h:, :w] = rgba[h - 1:h, :]
        img[:h, w:] = img[:h, w - 1:w]
        img[h:, w:] = img[h - 1:h, w - 1:w]
    else:
        img = rgba
    nby, nbx = ph // 4, pw // 4
    return (img.reshape(nby, 4, nbx, 4, 4).transpose(0, 2, 1, 3, 4)
            .reshape(-1, 16, 4), nby, nbx)


def _pack565(rgb):
    """(n,3) int → (n,) uint16 RGB565"""
    r = (rgb[:, 0].astype("uint32") * 31 + 127) // 255
    g = (rgb[:, 1].astype("uint32") * 63 + 127) // 255
    b = (rgb[:, 2].astype("uint32") * 31 + 127) // 255
    return ((r << 11) | (g << 5) | b).astype("uint16")


def _unpack565(c):
    """(n,) uint16 → (n,3) int32(デコーダ互換の8bit展開)"""
    import numpy as np
    c = c.astype(np.uint32)
    r = (c >> 11) & 31
    g = (c >> 5) & 63
    b = c & 31
    return np.stack([(r * 255 + 15) // 31, (g * 255 + 31) // 63,
                     (b * 255 + 15) // 31], axis=1).astype(np.int32)


def _color_block(blocks_rgb):
    """(n,16,3) uint8/int → (c0,c1,idx_u32) 各(n,)。レンジフィット4色モード

    dev#288(速度): 元実装は (n,16,4,3) の距離テンソルを一括生成しており、
    4096x4096実測で圧縮の最大単一項目(10〜14秒)になっていた。原因は
    ・reduce対象軸(16ブロック内画素)が末尾軸でない= numpyの不得意な形
    ・パレット4色ぶんの距離を同時展開する巨大中間配列(約800MB)
    の2点。中間データを (n,3,16) のチャンネル優先レイアウトへ転置してから
    末尾軸reduceに揃え、パレット4色をPythonループ(4回固定・データ依存なし)
    で回して距離を都度縮約することで中間配列を桁違いに小さくした。
    アルゴリズム自体(レンジフィット4色モード・距離計算式・同値時idx=0)は
    無改変で、同一入力に対し旧実装とバイト単位で完全一致する
    (work\\speed_mission\\dxt\\NOTES.md 参照)。"""
    import numpy as np
    cm = np.ascontiguousarray(
        np.asarray(blocks_rgb, dtype=np.uint8).transpose(0, 2, 1))  # (n,3,16)
    mn = cm.min(axis=2).astype(np.int32)   # (n,3)
    mx = cm.max(axis=2).astype(np.int32)
    c0 = _pack565(mx)
    c1 = _pack565(mn)
    swap = c0 < c1
    c0s = np.where(swap, c1, c0)
    c1s = np.where(swap, c0, c1)
    p0 = _unpack565(c0s)
    p1 = _unpack565(c1s)
    pal = np.stack([p0, p1, (2 * p0 + p1 + 1) // 3, (p0 + 2 * p1 + 1) // 3],
                   axis=1)  # (n,4,3)
    r = cm[:, 0, :].astype(np.int32)   # (n,16) 各チャンネルを分離
    g = cm[:, 1, :].astype(np.int32)
    b = cm[:, 2, :].astype(np.int32)
    best_dist = None
    idx = None
    for k in range(4):
        dr = r - pal[:, k, 0:1]
        dg = g - pal[:, k, 1:2]
        db = b - pal[:, k, 2:3]
        d = dr * dr
        d += dg * dg
        d += db * db
        if k == 0:
            best_dist = d
            idx = np.zeros(d.shape, dtype=np.uint32)
        else:
            better = d < best_dist
            np.minimum(best_dist, d, out=best_dist)
            idx[better] = k
    flat = c0s == c1s                   # 等値は3色モードになるのでidx=0固定
    idx[flat] = 0
    shifts = (np.arange(16, dtype=np.uint32) * 2)[None, :]
    packed = (idx << shifts).sum(axis=1, dtype=np.uint64).astype(np.uint32)
    return c0s, c1s, packed


def encode_dxt1(rgba):
    """(h,w,4) uint8 → DXT1バイト列"""
    import numpy as np
    blocks, _, _ = _to_blocks(rgba)
    c0, c1, idx = _color_block(blocks[:, :, :3])
    n = len(c0)
    out = np.empty((n, 8), np.uint8)
    out[:, 0] = c0 & 0xFF
    out[:, 1] = c0 >> 8
    out[:, 2] = c1 & 0xFF
    out[:, 3] = c1 >> 8
    for k in range(4):
        out[:, 4 + k] = (idx >> (8 * k)) & 0xFF
    return out.tobytes()


def encode_dxt5(rgba):
    """(h,w,4) uint8 → DXT5バイト列(アルファ8補間モード+4色カラー)"""
    import numpy as np
    blocks, _, _ = _to_blocks(rgba)
    rgb = blocks[:, :, :3]
    alpha = blocks[:, :, 3].astype(np.int32)   # (n,16)
    a0 = alpha.max(axis=1)
    a1 = alpha.min(axis=1)
    # パレット: [a0, a1, 6段の補間](a0>a1の8値モード)
    ks = list(range(1, 7))
    interp = [( (7 - k) * a0 + k * a1 + 3) // 7 for k in ks]
    apal = np.stack([a0, a1] + interp, axis=1)  # (n,8)
    dist = np.abs(alpha[:, :, None] - apal[:, None, :])
    codes = dist.argmin(axis=2).astype(np.uint64)  # (n,16) 0..7
    codes[a0 == a1] = 0
    shifts = (np.arange(16, dtype=np.uint64) * 3)[None, :]
    bits = (codes << shifts).sum(axis=1)  # 48bit
    c0, c1, idx = _color_block(rgb)
    n = len(c0)
    out = np.empty((n, 16), np.uint8)
    out[:, 0] = a0
    out[:, 1] = a1
    for k in range(6):
        out[:, 2 + k] = (bits >> (8 * k)) & 0xFF
    out[:, 8] = c0 & 0xFF
    out[:, 9] = c0 >> 8
    out[:, 10] = c1 & 0xFF
    out[:, 11] = c1 >> 8
    for k in range(4):
        out[:, 12 + k] = (idx >> (8 * k)) & 0xFF
    return out.tobytes()


def encode(rgba, pixel_format):
    if pixel_format == "PF_DXT1":
        return encode_dxt1(rgba)
    if pixel_format == "PF_DXT5":
        return encode_dxt5(rgba)
    raise RuntimeError(f"unsupported format: {pixel_format}")


# ------------------------------------------------- decode(検証・プレビュー用)

def decode_dxt(data, w, h, pixel_format):
    """DXT1/DXT5 → (h,w,4) uint8。エンコード品質のPSNR検証と復元プレビュー用"""
    import numpy as np
    bs = 8 if pixel_format == "PF_DXT1" else 16
    nbx, nby = (w + 3) // 4, (h + 3) // 4
    raw = np.frombuffer(data, dtype=np.uint8).reshape(nby * nbx, bs)
    cb = raw[:, bs - 8:]
    c0 = cb[:, 0].astype(np.uint32) | (cb[:, 1].astype(np.uint32) << 8)
    c1 = cb[:, 2].astype(np.uint32) | (cb[:, 3].astype(np.uint32) << 8)
    p0 = _unpack565(c0.astype(np.uint16))
    p1 = _unpack565(c1.astype(np.uint16))
    four = c0 > c1
    p2 = np.where(four[:, None], (2 * p0 + p1 + 1) // 3, (p0 + p1) // 2)
    p3 = np.where(four[:, None], (p0 + 2 * p1 + 1) // 3, 0)
    pal = np.stack([p0, p1, p2, p3], axis=1)  # (n,4,3)
    idx_u32 = (cb[:, 4].astype(np.uint32) | (cb[:, 5].astype(np.uint32) << 8) |
               (cb[:, 6].astype(np.uint32) << 16) | (cb[:, 7].astype(np.uint32) << 24))
    shifts = (np.arange(16, dtype=np.uint32) * 2)[None, :]
    cidx = (idx_u32[:, None] >> shifts) & 3   # (n,16)
    rgb = np.take_along_axis(pal, cidx[:, :, None].astype(np.int64), axis=1)
    if bs == 16:
        a0 = raw[:, 0].astype(np.int32)
        a1 = raw[:, 1].astype(np.int32)
        bits = np.zeros(len(raw), dtype=np.uint64)
        for k in range(6):
            bits |= raw[:, 2 + k].astype(np.uint64) << (8 * k)
        sh = (np.arange(16, dtype=np.uint64) * 3)[None, :]
        codes = ((bits[:, None] >> sh) & 7).astype(np.int64)  # (n,16)
        eight = a0 > a1
        ks = np.arange(2, 8)
        i8 = np.stack([a0, a1] + [((7 - k + 1) * 0 + (8 - k) * a0 + (k - 1) * a1 + 3) // 7
                                  for k in ks], axis=1)
        # ↑ 8値モード: idx k(2..7) = ((8-k)*a0 + (k-1)*a1)/7
        i6 = np.stack([a0, a1] + [((6 - k + 1) * 0 + (6 - k) * a0 + (k - 1) * a1 + 2) // 5
                                  for k in np.arange(2, 6)] + [np.zeros_like(a0),
                                  np.full_like(a0, 255)], axis=1)
        apal = np.where(eight[:, None], i8, i6)
        aval = np.take_along_axis(apal, codes, axis=1)  # (n,16)
    else:
        opaque = ~((~four)[:, None] & (cidx == 3))
        aval = np.where(opaque, 255, 0)
    blocks = np.concatenate([rgb, aval[:, :, None]], axis=2).astype(np.uint8)
    img = (blocks.reshape(nby, nbx, 4, 4, 4).transpose(0, 2, 1, 3, 4)
           .reshape(nby * 4, nbx * 4, 4))
    return img[:h, :w]


def psnr(a, b):
    import numpy as np
    d = a.astype(np.float64) - b.astype(np.float64)
    mse = (d * d).mean()
    if mse == 0:
        return 99.0
    return 10.0 * __import__("math").log10(255.0 * 255.0 / mse)
