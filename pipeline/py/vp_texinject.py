# -*- coding: utf-8 -*-
"""U6-T3(ストレッチ): テクスチャ注入(PNG→テンプレート同寸リサイズ→ミップ→
DXT1/5→uexpバイト注入)。restore_pak.py と同じ既存エンコーダ
(`vp_core.parse_texture2d`/`vp_tex.decode_png`/`make_mips`/`encode`、いずれも
無改変・import再利用)を、pakの外(平文uexpファイル)に対して適用する版。

v1制約: テンプレートと異なる解像度のPNGは自動リサイズ(ニアレストネイバー)
して同寸に合わせる(ドキュメント通りの妥協。品質はPSNR実測で報告)。

U49(2026-07-25): 注入テクスチャの明度補正(shadow_lift接続)。
docs\\REPORT_U47_2026-07-25.md 1.6節の診断: noue版はUE版M_VP
(pipeline\\py\\ue_archive\\vp_ue_mat.py make_material())が持つ
「BaseColor=tex×(1-shadow_lift) + Emissive=tex×shadow_lift」という
シーン照明非依存の底上げ(Emissive項)を持たない純Litシェーディングのため、
シーンの実効照明が暗いテスト環境では一様に45〜55%程度暗く描画される
(局所的な色ティントではなく乗算的な暗さのギャップ、U47実測)。
本セクションはこのEmissive寄与を、テクスチャ空間での明度ゲイン(乗算+
ハイライトのソフトクリップ)として近似する(案b、docs\\U49_SONNET_INSTRUCTIONS.md
2節)。gain=1.0(shadow_lift=0またはunlit)では従来のピクセル列と
完全に一致する(早期returnで無改変、既存アバターへの回帰なし)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core
import vp_tex

# U49: 注入系のバージョン痕跡(build_provenance.jsonは書き込み許可外のため、
# ビルドログ/報告書にこの文字列を残すことで機能追加を追跡できるようにする)
TEXINJECT_GAIN_VERSION = "u49v1"

# U49: gain(shadow_lift)の校正定数。
# 導出(docs\REPORT_U47_2026-07-25.md 1.6節+pipeline\py\ue_archive\vp_ue_mat.py):
#   UE版最終輝度 ≈ tex×(L + shadow_lift×(1-L))  (Lはシーンの実効照明比率)
#   noue版最終輝度(補正前) ≈ tex×L  (Emissive経路を持たないため)
#   → 補正ゲイン g(shadow_lift) = (L + shadow_lift×(1-L)) / L
#                               = 1 + shadow_lift × (1-L)/L
# L0はU47実測(work\u47_diag、flatVer2 shadow_lift=0.7時点の肌領域
# noue/ueref比 R/G/B平均r≈0.522)から L=shadow_lift*r/(1-r+shadow_lift*r)≈0.43
# を逆算した初期値(安全側に丸めて0.45)。実機反復(最大3回、
# docs\U49_SONNET_INSTRUCTIONS.md 2節)でこの定数のみ調整すればよい。
SHADOW_LIFT_GAIN_L0 = 0.45

# U49: ハイライト白飛び対策のソフトニー開始点(0-255)。ゲイン適用後この値を
# 超える領域はtanhでなめらかに255へ漸近させる(単純乗算のハードクリップを回避)。
SOFT_KNEE_START = 235.0


def shadow_lift_gain(shadow_lift, unlit=False, l0=None):
    """job.jsonのshadow_lift設定(0.0-1.0)から注入テクスチャへ掛ける
    明度ゲインを計算する(モジュールdocstring/上記コメント参照)。
    unlit=TrueならUE版M_VPもEmissive経路のみ(k=0扱い、pipeline\\py\\ue_archive\\vp_ue_mat.py
    `k = 0.0 if C.UNLIT else C.SHADOW_LIFT`)なのでgain=1.0(無補正)。
    l0: SHADOW_LIFT_GAIN_L0を一時的に上書きする場合のみ指定
    (devtools\\u49_offline_gain_sim.pyのオフライン校正専用、通常は省略)。"""
    if unlit:
        return 1.0
    k = max(0.0, min(1.0, float(shadow_lift)))
    if k <= 0.0:
        return 1.0
    l0 = SHADOW_LIFT_GAIN_L0 if l0 is None else float(l0)
    return 1.0 + k * (1.0 - l0) / l0


def apply_brightness_gain(rgba, gain, soft_knee=SOFT_KNEE_START):
    """(h,w,4) uint8 RGBAのRGBチャンネルへ乗算ゲインを適用する(U49)。
    アルファは不変(Opacity Maskに使われるためテクスチャのA値をそのまま保つ)。
    gain<=1.0+1e-6(実質無変化、既定gain=1.0を含む)なら早期returnし、
    ピクセル列を一切変更しない(既存アバター/shadow_lift=0/unlitへの
    回帰防止の根拠)。soft_knee以上の値はtanhでソフトクリップする
    (ハイライトの白飛び対策、docs\\U49_SONNET_INSTRUCTIONS.md 2節4)。"""
    import numpy as np
    if gain is None or abs(float(gain) - 1.0) < 1e-6:
        return rgba
    gain = float(gain)
    out = rgba.astype(np.float32)
    raw = out[:, :, :3] * gain
    span = 255.0 - soft_knee
    if span > 0:
        over = raw > soft_knee
        compressed = soft_knee + span * np.tanh(
            np.clip(raw - soft_knee, 0.0, None) / span)
        rgb = np.where(over, compressed, raw)
    else:
        rgb = raw
    rgb = np.clip(rgb, 0.0, 255.0)
    result = out.copy()
    result[:, :, :3] = rgb
    return result.astype(np.uint8)


def resize_nearest(rgba, new_w, new_h):
    """(h,w,4) uint8 → (new_h,new_w,4) ニアレストネイバーリサイズ"""
    import numpy as np
    h, w = rgba.shape[:2]
    if (w, h) == (new_w, new_h):
        return rgba
    ys = (np.arange(new_h) * h // new_h).clip(0, h - 1)
    xs = (np.arange(new_w) * w // new_w).clip(0, w - 1)
    return rgba[ys][:, xs]


def inject_texture_file(template_uexp_path, png_path, out_uexp_path, alpha_coverage=False,
                         gain=1.0):
    """template_uexp_path(cookedテクスチャのuexp)を読み、png_pathのピクセルを
    テンプレートと同フォーマット・同解像度(自動リサイズ)でミップ生成・
    エンコードして注入したバイト列をout_uexp_pathへ書く。
    alpha_coverage: avatar_meta.jsonのalpha_mode=="MASK"スロット向け
    (`vp_tex.make_mips`のアルファカバレッジ保存を有効化。既定False=従来どおり)。
    gain: U49、注入ピクセルのRGBへ掛ける明度ゲイン(`shadow_lift_gain()`参照)。
    既定1.0(無補正、従来どおりのピクセル列)。
    戻り値: {"pixel_format","size_x","size_y","psnr","gain","gain_version"}
    (psnr=最上位ミップのデコードround-trip、既存recolor kitの検証流儀)"""
    with open(template_uexp_path, "rb") as f:
        data = bytearray(f.read())
    layout = vp_core.parse_texture2d(bytes(data))
    pf, sx, sy = layout["pixel_format"], layout["size_x"], layout["size_y"]

    w, h, rgba = vp_tex.decode_png(png_path)
    rgba = resize_nearest(rgba, sx, sy)
    # U50-single(2026-07-25、責任者裁定「透過非対応」): 注入するピクセルの
    # アルファは常に255で埋める。
    # ここに置く理由: アトラス経路(vp_atlas.build_atlas_image)はcanvasを255で
    # 初期化した直後に元PNGのアルファで上書きしてしまい、さらに「1ラベル1枚」の
    # アバターはアトラス自体を通らない。**両方の経路が必ず通るのはここだけ**
    # (work\u50_equip\out\FINDINGS2.txt 3.3節)。
    # 副作用: alpha_coverage(ミップのアルファカバレッジ保存)は実質no-opになる。
    # なお t00 は PF_DXT1 でありアルファは元々1bitしか持てない(実測)。
    # dev#30(rd_30 Phase 1): 強制不透明化そのものは変えない(U50-single裁定を
    # 維持)が、その直前に透明画素のRGBを最寄りの不透明画素の色で埋める
    # (alpha dilation)。VRM/MToonのオーバーレイテクスチャ(頬染め等)は
    # 透明部分のRGBが未定義/黒(0,0,0)埋めであることが多く、無条件に255化
    # すると本来見えないはずの黒背景が可視化されて「顔が真っ黒」になる
    # (work\rd_30\PROPOSAL.md)。alpha_mode==OPAQUE(=全画素alpha=255)の
    # 既存アバターはextend_opaque_colorがno-opのためバイト単位で無変化。
    rgba = rgba.copy()
    rgba = vp_tex.extend_opaque_color(rgba)
    rgba[:, :, 3] = 255
    rgba = apply_brightness_gain(rgba, gain)

    mips = vp_tex.make_mips(rgba, len(layout["mips"]), alpha_coverage=alpha_coverage)
    for m, img in zip(layout["mips"], mips):
        blob = vp_tex.encode(img, pf)
        if len(blob) != m["size"]:
            raise RuntimeError(
                f"encoded size mismatch {m['w']}x{m['h']}: {len(blob)} != {m['size']}")
        data[m["offset"]:m["offset"] + m["size"]] = blob

    decoded0 = vp_tex.decode_dxt(vp_tex.encode(mips[0], pf), sx, sy, pf)
    psnr = vp_tex.psnr(mips[0], decoded0)

    os.makedirs(os.path.dirname(out_uexp_path) or ".", exist_ok=True)
    with open(out_uexp_path, "wb") as f:
        f.write(data)
    return {"pixel_format": pf, "size_x": sx, "size_y": sy, "psnr": psnr,
            "gain": gain, "gain_version": TEXINJECT_GAIN_VERSION}
