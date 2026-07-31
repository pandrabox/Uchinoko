"""U5 T1: 60体横展開 — 男女で別アバターを注入(Female<-toto, Male<-alicia)。

`build_avatar_variant.py`(U4-T2)の`build_uexp_variant`/`build_uasset_variant`は
どちらも(uexp_path, uasset_path, dump)を引数に取る汎用設計だったため、本スクリプトは
**両関数をそのままimportして再利用する**(build_avatar_variant.py自体は無改変。
Bronze001単体モード(`python build_avatar_variant.py`)の動作もそのまま維持される)。

60体(`work\\toto\\build\\pak_extract\\Player\\Outfit\\`配下)を全数走査し、
ファイル名の`_Male_`/`_Female_`でダンプを使い分けて注入する:
  - Female系(30体): toto実アバターダンプ(`out/t1_dump/avatar_female.json`、U4で作成済み)
  - Male系(30体): alicia実アバターダンプ(`out/t1_dump/avatar_male.json`、本セッションT1で新規作成)

各SKは自分自身のcookedバイトからテンプレート値(opaque head bytes/
MaxBoneInfluences/MaterialIndex/RequiredBones等)を読み取る
(`build_uexp_variant`が元ファイルから都度読み取る設計のため、SKごとの
テンプレート差異への追加対応コードは不要——1体用ロジックがそのまま60体に
一般化できることの実証でもある)。

テクスチャ/マテリアルはtotoテンプレート流用のまま(pak自体は無変更)なので、
Male側(alicia注入)の見た目の質感は本タスクの範囲外(T1bで扱う)。

実行: python build_avatar_variant_all.py [--skip-pak]
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_sk_structure as sk  # noqa: E402
import parse_sk_full as skf  # noqa: E402

from build_avatar_variant import (  # noqa: E402
    AvatarBuildError, build_uasset_variant, build_uexp_variant, load_dump,
)

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, 'out')
ALL_DIR = os.path.join(OUT_DIR, 'avatar_all')
ROOT = r"C:\P\Work\DiveToPalworld\work\toto\build\pak_extract\Player\Outfit"

DEFAULT_UNREALPAK = (r"C:\Program Files\Epic Games\UE_5.1"
                      r"\Engine\Binaries\Win64\UnrealPak.exe")
MOUNT_PREFIX = "..\\..\\..\\Pal\\Content\\Pal\\Model\\Character\\"


class AllBuildError(RuntimeError):
    pass


def collect_targets(root=ROOT):
    pairs = []
    for dirpath, _, fns in os.walk(root):
        for fn in sorted(fns):
            if not fn.lower().endswith('.uexp'):
                continue
            uexp = os.path.join(dirpath, fn)
            uasset = uexp[:-5] + '.uasset'
            if not os.path.exists(uasset):
                continue
            pairs.append((uexp, uasset))
    return sorted(pairs)


def gender_of(fn):
    if '_Male_' in fn:
        return 'Male'
    if '_Female_' in fn:
        return 'Female'
    raise AllBuildError(f"cannot determine gender from filename (no _Male_/_Female_): {fn}")


def build_and_validate(uexp_path, uasset_path, dump, out_uexp, out_uasset):
    new_uexp, info = build_uexp_variant(uexp_path, uasset_path, dump)
    os.makedirs(os.path.dirname(out_uexp), exist_ok=True)
    with open(out_uexp, 'wb') as f:
        f.write(new_uexp)
    new_uasset, uinfo = build_uasset_variant(uasset_path, len(new_uexp))
    with open(out_uasset, 'wb') as f:
        f.write(new_uasset)

    errs = []
    full2 = None
    try:
        full2 = skf.parse_sk_full(out_uexp, out_uasset)
    except Exception as e:
        return False, [f"parse_sk_full failed: {e}"], info

    ok = True
    if not full2['gap_zero']:
        ok = False
        errs.append(f"gap_zero=False end={full2['export_end']} expected={full2['expected_export_end']}")
    # U7 T2: 2セクション化で境界頂点が複製されうるため、期待頂点数はダンプの
    # ユニーク頂点数(len(dump['vertices']))ではなく、ビルダーが実際に構築した
    # 複製込みの総数(info['num_vertices'])を使う
    expected_numv = info['num_vertices']
    # U16実測(Sherbi等、アバター側が単一マテリアルでmaterial=1の三角形が
    # ゼロになるケース): build_avatar_variant.pyがmaterial=0の三角形を
    # material=1側にも複製する救済を行うため、出力側の総三角形数は
    # ダンプの生の三角形数(len(dump['triangles']))と一致しなくなる
    # (複製時はちょうど2倍)。ここも上のnum_verticesと同じ理由で、外部の
    # decree値ではなくビルダー自身が報告した総数(info['num_triangles'])との
    # 自己整合性を検証する形にする
    expected_tri = info['num_triangles']
    if full2['lods'][0]['num_vertices'] != expected_numv:
        ok = False
        errs.append(f"num_vertices={full2['lods'][0]['num_vertices']} expected={expected_numv}")
    if full2['lods'][0]['total_triangles'] != expected_tri:
        ok = False
        errs.append(f"total_triangles={full2['lods'][0]['total_triangles']} expected={expected_tri}")

    # U18実測: 真のバニラ衣装SK(docs\REPORT_U18_2026-07-23.md参照)には、body(0)/
    # parka(1)以外の追加マテリアルは無視する(sections 2件のまま)個体と、
    # parka(1)自体が無く単一セクション(material 0のみ、Kigurumi001等)へ統合する
    # 個体があり、出力のセクション構成はビルダーが実際に決めた
    # info['section_material_indices']次第で変わる。従来の「常に2、常に[0,1]」の
    # 決め打ちではなく、build_uexp_variant()が返したinfo(=ビルダー自身の意図)との
    # 自己整合性を検証する形に変更(ビルダー本体の判断ロジックはbuild_avatar_variant.py
    # 側にあり、本関数は「意図通りに出力されたか」だけを見る)。
    expected_mat_indices = info['section_material_indices']
    s2 = sk.parse_sk_structure(out_uexp, out_uasset)
    if not (s2['tri_match'] and s2['vtx_match']):
        ok = False
        errs.append(f"tri_match={s2['tri_match']} vtx_match={s2['vtx_match']}")
    if s2['num_sections'] != len(expected_mat_indices):
        ok = False
        errs.append(f"num_sections={s2['num_sections']} expected={len(expected_mat_indices)}")
    else:
        mat_indices = [sec['material_index'] for sec in s2['sections']]
        if mat_indices != expected_mat_indices:
            ok = False
            errs.append(f"section material_index order={mat_indices} expected={expected_mat_indices}")
        sec_tris = [sec['num_triangles'] for sec in s2['sections']]
        if sec_tris != info['section_triangle_counts']:
            ok = False
            errs.append(f"section num_triangles={sec_tris} expected={info['section_triangle_counts']}")

    return ok, errs, info


def build_pak(unrealpak, extract_root, all_dir, pak_path, rsp_path, targets):
    replace_map = {}
    for uexp_rel in targets:
        rel_base = uexp_rel[:-5]
        u1 = os.path.abspath(os.path.join(all_dir, uexp_rel))
        u2 = os.path.abspath(os.path.join(all_dir, rel_base + '.uasset'))
        if not (os.path.exists(u1) and os.path.exists(u2)):
            raise AllBuildError(f"variant not found: {u1} / {u2}")
        replace_map[rel_base + '.uexp'] = u1
        replace_map[rel_base + '.uasset'] = u2

    lines = []
    n_replaced = 0
    for dirpath, _, files in sorted(os.walk(extract_root)):
        for fn in sorted(files):
            full = os.path.abspath(os.path.join(dirpath, fn))
            rel = os.path.relpath(full, extract_root)
            if rel in replace_map:
                full = replace_map[rel]
                n_replaced += 1
            lines.append(f'"{full}" "{MOUNT_PREFIX}{rel}"')
    if n_replaced != len(replace_map):
        raise AllBuildError(f"expected {len(replace_map)} replacement target(s), found {n_replaced}")

    os.makedirs(os.path.dirname(rsp_path), exist_ok=True)
    with open(rsp_path, "w", encoding="ascii") as f:
        f.write("\n".join(lines))

    r = subprocess.run([unrealpak, os.path.abspath(pak_path), f"-Create={os.path.abspath(rsp_path)}"],
                        capture_output=True, text=True)
    if r.returncode != 0:
        raise AllBuildError(f"UnrealPak failed exit={r.returncode}\n{(r.stdout or '')[-3000:]}\n{(r.stderr or '')[-1000:]}")
    return len(lines), n_replaced


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--extract-root", default=os.path.dirname(os.path.dirname(ROOT)))
    ap.add_argument("--all-dir", default=ALL_DIR)
    ap.add_argument("--dump-female", default=os.path.join(OUT_DIR, 't1_dump', 'avatar_female.json'))
    ap.add_argument("--dump-male", default=os.path.join(OUT_DIR, 't1_dump', 'avatar_male.json'))
    ap.add_argument("--pak-out", default=os.path.join(OUT_DIR, "variant_avatar_all.pak"))
    ap.add_argument("--unrealpak", default=DEFAULT_UNREALPAK)
    ap.add_argument("--skip-pak", action="store_true")
    args = ap.parse_args()

    dump_f = load_dump(args.dump_female)
    dump_m = load_dump(args.dump_male)

    pairs = collect_targets(args.root)
    print(f"target SK: {len(pairs)}")

    all_ok = True
    n_fail = 0
    targets = []
    gender_counts = {'Male': 0, 'Female': 0}
    material_indices = {}
    max_bone_influences_seen = set()

    for uexp_path, uasset_path in pairs:
        rel_uexp = os.path.relpath(uexp_path, args.extract_root)
        fn = os.path.basename(uexp_path)
        gender = gender_of(fn)
        dump = dump_f if gender == 'Female' else dump_m
        gender_counts[gender] += 1

        out_uexp = os.path.join(args.all_dir, rel_uexp)
        out_uasset = out_uexp[:-5] + '.uasset'

        try:
            ok, errs, info = build_and_validate(uexp_path, uasset_path, dump, out_uexp, out_uasset)
        except Exception as e:
            ok = False
            errs = [str(e)]
            info = {}

        if info.get('max_bone_influences') is not None:
            max_bone_influences_seen.add(info['max_bone_influences'])

        status = 'OK' if ok else 'FAIL'
        print(f"[{status}] {rel_uexp}: gender={gender} numv={info.get('num_vertices')} "
              f"tri={info.get('num_triangles')} "
              f"sec_tris={info.get('section_triangle_counts')} "
              f"sec_bones={info.get('section_bone_map_sizes')}" +
              (f" errs={errs}" if errs else ""))
        if not ok:
            all_ok = False
            n_fail += 1
        else:
            targets.append(rel_uexp)

    print(f"\nVariant build+validate: {len(pairs)} sample(s), "
          f"{'ALL PASS' if all_ok else f'{n_fail} FAIL'} "
          f"(gender_counts={gender_counts}, max_bone_influences_seen={sorted(max_bone_influences_seen)})")
    if not all_ok:
        sys.exit(1)

    if args.skip_pak:
        sys.exit(0)

    rsp_path = os.path.join(os.path.dirname(args.pak_out), "variant_avatar_all_repack.rsp")
    n_lines, n_replaced = build_pak(args.unrealpak, args.extract_root,
                                     args.all_dir, args.pak_out, rsp_path, targets)
    print(f"pak generated: {args.pak_out} (total entries {n_lines}, replaced {n_replaced})")


if __name__ == '__main__':
    main()
