# -*- coding: utf-8 -*-
"""cook済み衣装SKのRefSkeleton回転をバニラ値に補正する(性別別)。

チビ骨格方式では位置はチビ値が正、回転はバニラ一致が正。FBX往復の丸め誤差を
含めてバイナリレベルでバニラ回転に揃える安全網(PalMod実証、実質no-opゲート)。

使い方: python patch_refskeleton.py <job.json> <pak_extractルート>
  <ルート>/Player/Outfit/SK_Player_{G}_… のパスから性別を判定し、
  vanilla/refskel_{g}.json の回転へ全共通ボーンを置換する。
"""

import glob
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core as core

TAG = "patch_refskel"


def find_transform_offset(uexp_path, names):
    bones, transforms, tsize, data, tpos = core.find_refskeleton(
        uexp_path, names, with_offset=True)
    return data, [b for b, _ in bones], tpos, tsize


def patch_file(uasset_path, vanilla):
    names = core.read_names(uasset_path)
    uexp_path = uasset_path[:-7] + ".uexp"
    data, bones, tpos, tsize = find_transform_offset(uexp_path, names)
    if tsize != 80:
        core.die(TAG, f"transform is not double (80B): {uexp_path}")
    buf = bytearray(data)
    patched = 0
    for i, bone in enumerate(bones):
        vb = vanilla.get(bone)
        if vb is None:
            continue  # 追加ボーン(バニラに無い)は触らない
        # 回転のみバニラへ。位置はチビ骨格値を保持
        struct.pack_into("<4d", buf, tpos + i * 80, *vb["quat"])
        patched += 1
    if bytes(buf) != data:
        with open(uexp_path, "wb") as f:
            f.write(bytes(buf))
    print(f"[{TAG}] {os.path.basename(uexp_path)}: {patched}/{len(bones)} "
          "bones rot->vanilla (pos=chibi)")
    return patched


def main():
    job = core.load_job(sys.argv[1])
    root = sys.argv[2]
    vanilla = {}
    for g in ("male", "female"):
        p = os.path.join(job["job_dir"], "vanilla", f"refskel_{g}.json")
        with open(p, encoding="utf-8") as f:
            vanilla[g] = json.load(f)
    targets = glob.glob(os.path.join(root, "Player", "Outfit", "**",
                                     "SK_*.uasset"), recursive=True)
    if not targets:
        core.die(TAG, "no targets found")
    for t in targets:
        base = os.path.basename(t)
        if "_Male_" in base:
            ref = vanilla["male"]
        elif "_Female_" in base:
            ref = vanilla["female"]
        else:
            core.die(TAG, f"cannot determine gender: {base}")
        patch_file(t, ref)
    print(f"[{TAG}] done ({len(targets)} meshes)")


if __name__ == "__main__":
    main()
