# -*- coding: utf-8 -*-
"""WP-I157受入ゲート: build_avatar_variant.apply_uniform_scale()(dev#157サイズ可変)の自動テスト。

pipeline\\py\\data\\配下の実SKサンプルは配布物に含まれず開発機依存のため、本テストは
find_refskeleton()/read_names()のフィンガープリント規約(vp_core.py参照)に厳密準拠した
**完全合成の最小uexp/uasset**を都度生成して検証する(外部アセット非依存)。

G1(no-op契約): k=1.0はバイト単位で完全no-op(丸めではなく早期return)。
G2(スケール正当性): k!=1.0はroot(parent=-1)以外の全ボームのTranslationを
   厳密にk倍し、root自身とquat/scale成分は不変。
G3(負の対照): k!=1.0は実際にバイト列を変える(「常にno-op」実装の混入を防ぐ)。

実行: python test_uniform_scale.py
"""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core  # noqa: E402
import build_avatar_variant as bav  # noqa: E402

failures = []


def check(label, cond, detail=""):
    if cond:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} {detail}")
        failures.append(label)


N_BONES = 40  # vp_core.find_refskeleton()の既定min_bones=40と同じ下限に合わせる


def _build_synthetic_uasset(names):
    """read_names()が読める最小のuasset(NameMapのみ、exports等は無し)。"""
    header = struct.pack("<i", -4)          # legacy_ver = -4 (LegacyUE3Version読み飛ばし分岐を回避)
    header += struct.pack("<i", 0)           # FileVersionUE4
    header += struct.pack("<i", 0)           # FileVersionLicenseeUE
    header += struct.pack("<i", 0)           # CustomVersions count = 0
    header += struct.pack("<i", 0)           # TotalHeaderSize
    header += struct.pack("<i", 0)           # フォルダ名文字列長 = 0(文字列無し)
    header += struct.pack("<i", 0)           # PackageFlags
    name_offset = 4 + len(header) + 8        # magic(4) + header + name_count/name_offset(8)
    header += struct.pack("<ii", len(names), name_offset)
    body = b""
    for n in names:
        raw = n.encode("ascii") + b"\x00"
        body += struct.pack("<i", len(raw)) + raw + struct.pack("<i", 0)  # + precalc hash
    return struct.pack("<I", 0x9E2A83C1) + header + body


def _build_synthetic_uexp(n_bones=N_BONES, pos_scale=1.0):
    """find_refskeleton()が拾える最小のFMeshBoneInfo配列+FTransform配列(double精度)。
    bone0=root(parent=-1)、bone1..N-1はすべてbone0の子(parent=0)。
    quat=単位クォータニオン、scale=(1,1,1)、posはボーンごとに異なる値
    (pos_scaleで基準値を振れるようにして、複数個体を作れるようにする)。"""
    body = struct.pack("<i", n_bones)
    for i in range(n_bones):
        parent = -1 if i == 0 else 0
        body += struct.pack("<iii", 0, 0, parent)  # idx=0(names[0]を指す), num=0, parent
    body += struct.pack("<i", n_bones)  # FTransform配列のcount(bone数と一致必須)
    for i in range(n_bones):
        qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
        px, py, pz = (i + 1) * pos_scale, (i + 1) * pos_scale * 2, (i + 1) * pos_scale * 3
        sx, sy, sz = 1.0, 1.0, 1.0
        body += struct.pack("<10d", qx, qy, qz, qw, px, py, pz, sx, sy, sz)
    return body


def _write_temp(data, suffix):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _make_pair():
    uasset_path = _write_temp(_build_synthetic_uasset(["Bone"]), ".uasset")
    uexp_path = _write_temp(_build_synthetic_uexp(), ".uexp")
    return uexp_path, uasset_path


def _read_positions(uexp_path, uasset_path):
    """検証用: 現在のuexpバイト列から全ボーンの(quat, pos, scale)を読み直す。"""
    names = vp_core.read_names(uasset_path)
    raw_bones, transforms, tsize, _data, tpos = vp_core.find_refskeleton(
        uexp_path, names, with_offset=True)
    return raw_bones, transforms


def test_fixture_self_consistency():
    """まず合成フィクスチャ自体がvp_core側で正しくパースできることを確認する
    (これが崩れていると以降の全テストが無意味になるため独立に検証)。"""
    uexp_path, uasset_path = _make_pair()
    try:
        raw_bones, transforms = _read_positions(uexp_path, uasset_path)
        check("fixture: bone count == N_BONES", len(raw_bones) == N_BONES, str(len(raw_bones)))
        check("fixture: bone0 is root (parent=-1)", raw_bones[0][1] == -1)
        check("fixture: bone1 parent == 0", raw_bones[1][1] == 0)
        check("fixture: transform count matches", len(transforms) == N_BONES)
        # bone1(i=1)の期待pos: ((1+1)*1.0, (1+1)*2.0, (1+1)*3.0) = (2,4,6)
        check("fixture: bone1 pos as expected", transforms[1][4:7] == (2.0, 4.0, 6.0),
              str(transforms[1][4:7]))
    finally:
        os.unlink(uexp_path)
        os.unlink(uasset_path)


def test_k_1_0_is_byte_identical_noop():
    """G1: k=1.0は1バイトも変えない(丸めた結果一致ではなく、正真正銘のno-op)。"""
    uexp_path, uasset_path = _make_pair()
    try:
        with open(uexp_path, "rb") as f:
            original = f.read()
        out = bav.apply_uniform_scale(original, uexp_path, uasset_path, 1.0)
        check("k=1.0: return value is byte-identical to input", out == original)
        check("k=1.0: return value is the same object (early return, no bytearray alloc)",
              out is original)
    finally:
        os.unlink(uexp_path)
        os.unlink(uasset_path)


def test_k_0_8_scales_non_root_only():
    """G2: k=0.8はroot以外の全ボームのposを厳密に0.8倍する。root/quat/scaleは不変。"""
    uexp_path, uasset_path = _make_pair()
    try:
        with open(uexp_path, "rb") as f:
            original = f.read()
        _orig_bones, orig_tf = _read_positions(uexp_path, uasset_path)

        k = 0.8
        patched = bav.apply_uniform_scale(original, uexp_path, uasset_path, k)
        # apply_uniform_scale()はuexp_pathをディスクから再読込して構造を特定するだけで、
        # 返り値のpatchedバイト列自体はディスクに書いていない。読み直すため一時ファイルへ
        # patched結果を書き戻す。
        patched_path = uexp_path + ".patched"
        with open(patched_path, "wb") as f:
            f.write(patched)
        try:
            patched_bones, patched_tf = _read_positions(patched_path, uasset_path)
        finally:
            os.unlink(patched_path)

        ok_root = patched_tf[0][4:7] == orig_tf[0][4:7]
        check("k=0.8: root(bone0) pos unchanged", ok_root,
              f"orig={orig_tf[0][4:7]} patched={patched_tf[0][4:7]}")

        all_scaled_ok = True
        for i in range(1, N_BONES):
            expected = tuple(v * k for v in orig_tf[i][4:7])
            actual = patched_tf[i][4:7]
            if any(abs(a - e) > 1e-9 for a, e in zip(actual, expected)):
                all_scaled_ok = False
                check(f"k=0.8: bone{i} pos == orig*k", False,
                      f"expected={expected} actual={actual}")
        check("k=0.8: all non-root bones scaled by exactly k", all_scaled_ok)

        quat_scale_unchanged = all(
            patched_tf[i][0:4] == orig_tf[i][0:4] and patched_tf[i][7:10] == orig_tf[i][7:10]
            for i in range(N_BONES))
        check("k=0.8: quat/scale components unchanged for every bone", quat_scale_unchanged)

        check("k=0.8: output size unchanged (in-place same-size patch)",
              len(patched) == len(original))
    finally:
        os.unlink(uexp_path)
        os.unlink(uasset_path)


def test_k_neq_1_actually_changes_bytes():
    """G3(負の対照): k=1.2は実際にバイト列を変える。「常にno-opを返す」実装の
    混入を、k=1.0テストだけでは検出できないため必須(値を寄せて合わせる系の
    サイレント無効化を防ぐ)。"""
    uexp_path, uasset_path = _make_pair()
    try:
        with open(uexp_path, "rb") as f:
            original = f.read()
        patched = bav.apply_uniform_scale(original, uexp_path, uasset_path, 1.2)
        check("k=1.2: bytes actually differ from input (not a silent no-op)",
              patched != original)
    finally:
        os.unlink(uexp_path)
        os.unlink(uasset_path)


def test_job_default_uniform_scale_is_1_0():
    """vp_core.load_job()の既定値が1.0であること(既存job.jsonへの無退行の根拠)。"""
    fd, job_path = tempfile.mkstemp(suffix=".json")
    try:
        import json
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"vrm_path": "dummy.vrm"}, f)
        job = vp_core.load_job(job_path)
        check("load_job(): uniform_scale defaults to 1.0", job.get("uniform_scale") == 1.0,
              str(job.get("uniform_scale")))
    finally:
        os.unlink(job_path)


def main():
    test_fixture_self_consistency()
    test_k_1_0_is_byte_identical_noop()
    test_k_0_8_scales_non_root_only()
    test_k_neq_1_actually_changes_bytes()
    test_job_default_uniform_scale_is_1_0()

    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
