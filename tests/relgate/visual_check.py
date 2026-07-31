# -*- coding: utf-8 -*-
r"""リリースゲート層2: 見た目相関(NCC)チェック(WP5)。

目的: 「数値は揃っているのに実物は壊れていた」を防ぐため、Shapell固定検体を
フル変換した際に生成される固定条件レンダリング画像を、承認済みの正解画像
(baseline)とNCC(正規化相互相関)で比較する。

## 車輪の再利用について

NCC計算そのものは新規実装しない。既存の `devtools\atlas_compare.py` の
`compare()`(RGBフラット化→平均減算→相関係数、`pipeline\py\convert_noue.py`
の `_render_atlas_visual_check` とビット単位で同一の式)をそのままimportして
呼ぶだけ。本ファイルが新規に持つのは「どの画像セットを比較するか」
「baselineとの突き合わせ・fail-closed・approve」という運用ロジックのみ。

## 比較対象画像(固定4枚、job_dir=job.jsonの親ディレクトリからの相対パス)

    converted/preview_female_stand.png   … アトラス化前、女性スタンド正面
    converted/preview_male_stand.png     … アトラス化前、男性スタンド正面
    build/atlas/atlascheck_female.png    … アトラス化後(最終焼き込み)、女性
    build/atlas/atlascheck_male.png      … アトラス化後(最終焼き込み)、男性

前者2枚は import/retarget 起因の破損(素体と衣装が90度ずれる等)を、
後者2枚はテクスチャアトラス化起因の破損(テクスチャが別の絵に化ける、
UV外れで灰色になる等)を主に捉える。両工程を1セットでカバーするために
4枚とも比較する(参照: work\relgate\wp5\REPORT.md 選定理由節)。

## 閾値の根拠(実測、work\relgate\wp5\REPORT.md参照)

WP1で取得済みの「同一job.jsonで独立に2回フル変換したShapell」の出力
(work\relgate\wp1\run_shapell_1 / run_shapell_2)から上記4画像を
atlas_compare.compare()で比較したところ、4枚とも:
    global_ncc    ≈ 0.999999999999...(実質1.0、浮動小数点誤差のみ)
    tile_min_ncc  ≈ 0.999999999999...(同上)
であり、これはWP1が発見した「pak本体はSHA256完全一致(決定的)」
「PNGの画素データ(IDAT)はエンコーダのメタデータ埋め込み(パス文字列等)を
除けば決定的」という知見と整合する(=このレンダリング経路には
GPU非決定性・乱数シード等によるノイズが実質無い)。

一方、意図的に壊した画像との比較では明確に閾値を下回ることを確認済み:
    texture loss(単色化)          : global_ncc=0.0000  tile_min_ncc=0.0000
    別の画像に差し替え(男女取り違え): global_ncc=0.9943  tile_min_ncc=0.8309
    部分反転                        : global_ncc=-0.0031 tile_min_ncc=-1.0000

同一条件(~1.0)と破損ケース(0.99台以下)の間に3桁以上の桁差があるため、
「値を寄せて合わせる」ことなく安全側に倒せる:
    MIN_GLOBAL_NCC   = 0.999   (同一条件からは3桁以上の余裕)
    MIN_TILE_MIN_NCC = 0.995   (男女取り違えの0.8309を確実に落とす。
                                 タイル単位のほうが局所破損に敏感なため
                                 global側よりわずかに緩め、機材差由来の
                                 誤検知余地を残しつつ実損は必ず検出する)

## fail-closed方針

    - baseline画像ディレクトリが無い          → FAIL(SKIPにしない)
    - baseline側の4枚のいずれかが無い          → FAIL
    - 検体側(変換結果)の4枚のいずれかが無い    → FAIL
    - サイズ不一致等でNCC計算不能              → FAIL
    - approve は明示呼び出し時のみ実施。4枚すべて揃っていない状態からの
      approveは拒否する(壊れたbaselineを作らせない)
"""
import os
import shutil
import sys

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(HERE_DIR))
DEVTOOLS_DIR = os.path.join(REPO_DIR, "devtools")
if DEVTOOLS_DIR not in sys.path:
    sys.path.insert(0, DEVTOOLS_DIR)

import atlas_compare  # noqa: E402 (既存NCC実装をそのまま利用)

TAG = "relgate.layer2"

# (baseline側/検体側で使うファイル名の"幹", job_dir からの相対パス)
IMAGE_SET = [
    ("preview_female_stand", os.path.join("converted", "preview_female_stand.png")),
    ("preview_male_stand", os.path.join("converted", "preview_male_stand.png")),
    ("atlascheck_female", os.path.join("build", "atlas", "atlascheck_female.png")),
    ("atlascheck_male", os.path.join("build", "atlas", "atlascheck_male.png")),
]

MIN_GLOBAL_NCC = 0.999
MIN_TILE_MIN_NCC = 0.995


def baseline_image_path(baseline_dir, name):
    return os.path.join(baseline_dir, name + ".png")


def images_present_in_run(run_dir, image_set=IMAGE_SET):
    """WP6 T5: 検体側(run_dir)に実在する画像だけを抽出したimage_setを返す。
    Shapell(既定)は4枚とも常に生成されるが、テクスチャが1枚しかない軽量な
    VRM検体(例: 100Avatars_038_Kate)はアトラス化(複数テクスチャの統合)が
    構造的に不要なため`pipeline\\py\\convert_noue.py`の
    `_render_atlas_visual_check`自体が実行されず、atlascheck_*.pngが
    最初から生成されない(バグではなく「合成するものが無いので合成しない」
    という設計どおりの挙動、2026-07-27実測)。この関数はcheck()/approve()の
    既定引数(IMAGE_SET全4枚)を変えずに、呼び出し側が検体ごとに実在する
    画像だけへ絞り込めるようにするためのヘルパ。"""
    return [(name, rel) for name, rel in image_set if os.path.isfile(os.path.join(run_dir, rel))]


def check(run_dir, baseline_dir, patch=64, image_set=None):
    """検体(run_dir=job_dirの画像)をbaseline_dirの画像とNCC比較する。
    image_set省略時はShapell向けの既定4枚(IMAGE_SET、下位互換)。
    戻り値: {"status": "PASS"|"FAIL", "detail": {name: {...}}, "log_lines": [...]}
    fail-closed: baseline/検体いずれかの画像が欠けている、または比較不能なら
    そのペアはFAILとして扱う(SKIPしない)。"""
    if image_set is None:
        image_set = IMAGE_SET
    log = []
    if not os.path.isdir(baseline_dir):
        log.append(f"[{TAG}][FAIL] baseline画像ディレクトリが無い(fail-closed): {baseline_dir}")
        return {"status": "FAIL", "reason": "baseline_dir missing", "detail": {}, "log_lines": log}

    detail = {}
    all_pass = True
    for name, rel in image_set:
        test_path = os.path.join(run_dir, rel)
        base_path = baseline_image_path(baseline_dir, name)
        if not os.path.isfile(base_path):
            log.append(f"[{TAG}][FAIL] {name}: baseline画像が無い(fail-closed): {base_path}")
            detail[name] = {"status": "FAIL", "reason": "no baseline image"}
            all_pass = False
            continue
        if not os.path.isfile(test_path):
            log.append(f"[{TAG}][FAIL] {name}: 検体側の画像が生成されていない(fail-closed): {test_path}")
            detail[name] = {"status": "FAIL", "reason": "no test image"}
            all_pass = False
            continue
        r = atlas_compare.compare(base_path, test_path, patch=patch)
        if not r.get("comparable", False):
            log.append(f"[{TAG}][FAIL] {name}: 比較不能({r.get('reason')})")
            detail[name] = {"status": "FAIL", "reason": r.get("reason")}
            all_pass = False
            continue
        gncc = r["global_ncc"]
        tmin = r["tile_min_ncc"] if r["tile_min_ncc"] is not None else -1.0
        ok = (gncc >= MIN_GLOBAL_NCC) and (tmin >= MIN_TILE_MIN_NCC)
        status = "PASS" if ok else "FAIL"
        log.append(
            f"[{TAG}][{status}] {name}: global_ncc={gncc:.6f}(閾値>={MIN_GLOBAL_NCC}) "
            f"tile_min_ncc={tmin:.6f}(閾値>={MIN_TILE_MIN_NCC})"
            + ("" if ok else f"  worst_tile={r.get('worst_tile')}")
        )
        detail[name] = {"status": status, "global_ncc": gncc, "tile_min_ncc": tmin}
        if not ok:
            all_pass = False

    return {"status": "PASS" if all_pass else "FAIL", "detail": detail, "log_lines": log}


def approve(run_dir, baseline_dir, image_set=None):
    """run_dir(job_dir)の画像をbaseline_dirへ明示的にコピーする(承認操作)。
    image_set省略時はShapell向けの既定4枚(IMAGE_SET、下位互換)。指定分の
    うち1枚でも欠けていれば拒否する(壊れたbaselineを作らせない)。
    実運用では、このコピーを実行する前に人間が画像を目視確認すること
    (RELGATE.md参照)。"""
    if image_set is None:
        image_set = IMAGE_SET
    log = []
    missing = []
    for name, rel in image_set:
        src = os.path.join(run_dir, rel)
        if not os.path.isfile(src):
            missing.append(src)
    if missing:
        log.append(f"[{TAG}][approve][FAIL] 検体側画像が{len(missing)}枚欠けているため承認を拒否: {missing}")
        return {"status": "FAIL", "reason": "missing source image(s)", "log_lines": log}

    os.makedirs(baseline_dir, exist_ok=True)
    for name, rel in image_set:
        src = os.path.join(run_dir, rel)
        dst = baseline_image_path(baseline_dir, name)
        tmp = dst + ".tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        log.append(f"[{TAG}][approve] baseline更新: {dst} <- {src}")
    return {"status": "APPROVED", "log_lines": log}
