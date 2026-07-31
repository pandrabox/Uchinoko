# -*- coding: utf-8 -*-
"""WP19: `pipeline\\py\\noue_master\\` 配下の .uasset/.uexp (34ファイル/17ペア)が
自作資産であることを検証する。

背景: これらはUnreal Engineのcooked native binary asset形式(.uasset/.uexp)で
あり、Palworld自身が使う形式・パス構造(`/Game/Pal/...`)を模している。外形だけ
見ると「ゲームから抽出したのでは」と疑われかねないため、SignPath審査に向けて
中身を実際に解析し、Palworld由来の痕跡が無いことを機械的に示す。

やること(2段構え):

1. **再生成一致**(最強の証拠、対象は t00 4096版の2ファイルのみ):
   `pipeline\\py\\devtool_make_t00_4096.py` を実際に実行し、種
   (`noue_master\\tex_src_2048\\t00.*`)から4096版を再生成して、リポジトリ
   同梱の `pak_extract_extra\\...\\t00.*` とバイト単位で一致することを確認する。
   これは他の32ファイル(UEマテリアルcook・t01・tex_src_2048のt00自体)には
   適用できない — 生成にUnreal Editor本体が必要で、dev#114(2026-07-29)で
   UEクックパイプライン(`pipeline\\ue\\`、`pipeline\\templates\\ue_project\\`)が
   完全削除されており、このマシンにもUnreal Engineはインストールされていない
   (両方を本スクリプトが起動時に確認しログへ残す)。

2. **バイナリ解析**(全34ファイル対象): UE cooked package format
   (`FPackageFileSummary` → `ImportMap`)を前方パースし、各アセットが実際に
   *参照している外部パッケージ名を全部列挙する*。UEのオブジェクトシリアライズ
   規約上、パッケージ外のオブジェクトへの参照は必ずImportMapのエントリを
   経由する(近道は存在しない)。したがってImportMapが空であるか、
   `/Script/*`(UEエンジン標準クラス)とこのプロジェクト自身のパッケージ
   (`/Game/Pal/Model/Character/Player/ModelMaterials/MainShader/*`)しか
   参照していなければ、Palworld本体の他のアセット(マテリアル・関数
   ライブラリ等)には一切依存していないことが構造的に証明される。

   ヘッダのフィールドオフセット計算は `pipeline\\py\\parse_uasset_header.py`
   (U2 T2、既存・書き込み許可外につき無改変で読み取り専用import)の
   `parse_package_summary()` をそのまま使う。本スクリプトが追加するのは
   ImportMap(FObjectImport配列)のパースのみ(現状どのモジュールにも実装が
   無かった)。

   FObjectImportの実測ストライド(このプロジェクトの全cooked資産で共通):
   32バイト = ClassPackage(FName, 8B) + ClassName(FName, 8B) +
   OuterIndex(int32, 4B) + ObjectName(FName, 8B) + bImportOptional
   (UE archiveの`bool`は歴史的経緯で4byte値としてシリアライズされる, 4B)。
   実測根拠: `M_VP_m00_LitMaster1S.uasset` で
   `(export_offset - import_offset) / import_count == 32.0`(割り切れる)。
   34ファイル全件で同じ検算(下記 `_parse_imports` 内)を行い、割り切れなければ
   即座に例外を出す(構造の思い込みで結果を捏造しないため)。

使い方:
    python devtools\\verify_noue_asset_provenance.py
        … noue_master配下の34ファイルを解析してレポートを表示
    python devtools\\verify_noue_asset_provenance.py --regen-check
        … 上記1に加えてt00再生成の一致確認も行う
    python devtools\\verify_noue_asset_provenance.py --file <path.uasset>
        … 任意の1ファイルだけを解析する(負の対照実験用。Palworld本体の
          アセットを一時的に指定して参照パッケージが変わることを示す用途)

終了コード: 0 = 全ファイルが許可リスト内のパッケージのみ参照(自作性と矛盾しない)
           1 = 許可リスト外のパッケージ参照を検出、またはパース失敗
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
PIPELINE_PY = os.path.join(REPO_ROOT, "pipeline", "py")
if PIPELINE_PY not in sys.path:
    sys.path.insert(0, PIPELINE_PY)

import parse_uasset_header as puh  # noqa: E402  (既存・読み取り専用で使用)
import vp_core  # noqa: E402  (read_names)

NOUE_MASTER = os.path.join(PIPELINE_PY, "noue_master")

IMPORT_ENTRY_SIZE = 32

# このプロジェクト自身が使うパッケージパスの接頭辞(自作resultとして許可)。
# live_template.py の MVP_PACKAGE_PREFIX と一致させている。
OWN_PACKAGE_PREFIX = "/Game/Pal/Model/Character/Player/ModelMaterials/MainShader"
# UEエンジン標準の名前空間(Palworld固有ではなく、あらゆるUEプロジェクトに
# 共通して存在するエンジンクラス定義)。
ENGINE_PREFIXES = ("/Script/",)


class ProvenanceError(RuntimeError):
    pass


def _resolve_fname(names, idx, num):
    try:
        s = names[idx]
    except IndexError:
        return f"<bad_name_idx:{idx}>"
    return s if num == 0 else f"{s}_{num - 1}"


def _parse_imports(data, names, summary):
    """ImportMap(FObjectImport配列)をパースする。
    ストライドを実測で検算し、想定(32B)とズレたら即例外にする。"""
    import_count = summary["import_count"]
    import_offset = summary["import_offset"]
    export_offset = summary["export_offset"]
    if import_count == 0:
        return []
    if import_offset < export_offset:
        span = export_offset - import_offset
    else:
        # importがexportより後ろに置かれるcookedパッケージも理論上あり得るため、
        # depends_offsetとの間隔で代替検算する。
        span = summary["depends_offset"] - import_offset
    if span % import_count != 0:
        raise ProvenanceError(
            f"import stride not integral: span={span} count={import_count}")
    stride = span // import_count
    if stride != IMPORT_ENTRY_SIZE:
        raise ProvenanceError(
            f"import stride mismatch: measured={stride} expected={IMPORT_ENTRY_SIZE}")

    imports = []
    off = import_offset
    for i in range(import_count):
        class_pkg_idx, class_pkg_num = struct.unpack_from("<ii", data, off)
        class_name_idx, class_name_num = struct.unpack_from("<ii", data, off + 8)
        (outer_index,) = struct.unpack_from("<i", data, off + 16)
        obj_name_idx, obj_name_num = struct.unpack_from("<ii", data, off + 20)
        (b_import_optional,) = struct.unpack_from("<I", data, off + 28)
        if b_import_optional not in (0, 1):
            raise ProvenanceError(
                f"bImportOptional not bool @ import {i} off {off}: {b_import_optional}")
        imports.append({
            "index": i,
            "class_package": _resolve_fname(names, class_pkg_idx, class_pkg_num),
            "class_name": _resolve_fname(names, class_name_idx, class_name_num),
            "outer_index": outer_index,
            "object_name": _resolve_fname(names, obj_name_idx, obj_name_num),
        })
        off += IMPORT_ENTRY_SIZE
    return imports


def _resolve_import_path(imports_by_neg_index, imp):
    """OuterIndexを辿ってフルパスを組み立てる(表示用)。
    負のインデックス = 他のimportがouter。0 = トップレベル(パッケージ自身)。"""
    parts = [imp["object_name"]]
    cur = imp["outer_index"]
    guard = 0
    while cur != 0 and guard < 64:
        guard += 1
        if cur < 0:
            outer = imports_by_neg_index.get(cur)
            if outer is None:
                parts.append(f"<unresolved:{cur}>")
                break
            parts.append(outer["object_name"])
            cur = outer["outer_index"]
        else:
            parts.append(f"<export:{cur}>")
            break
    return ".".join(reversed(parts))


def analyze_file(uasset_path):
    uexp_path = uasset_path[:-len(".uasset")] + ".uexp"
    with open(uasset_path, "rb") as f:
        data = f.read()
    summary = puh.parse_package_summary(data)
    names = vp_core.read_names(uasset_path)
    imports = _parse_imports(data, names, summary)
    imports_by_neg_index = {-(i + 1): imp for i, imp in enumerate(imports)}

    # 34件全部(17ペア)を漏れなく検証するため、対の.uexpも構造的に検算する:
    # ExportMap記載のSerialSize合計がuexpの実サイズ(先頭4byteのマジック分を除く)
    # と一致することを確認する。既存 parse_uasset_header.verify() をそのまま使う。
    pair_ok = None
    pair_error = None
    if os.path.exists(uexp_path):
        try:
            pair_ok = puh.verify(uasset_path, uexp_path, verbose=False)
        except Exception as e:  # noqa: BLE001
            pair_error = str(e)
    else:
        pair_error = "uexp file missing"

    resolved = []
    referenced_packages = set()
    for imp in imports:
        path = _resolve_import_path(imports_by_neg_index, imp)
        resolved.append({**imp, "resolved_path": path})
        if imp["class_name"] == "Package" and imp["outer_index"] == 0:
            referenced_packages.add(imp["object_name"])

    # ClassPackage自体も「参照しているパッケージ」の一部(そのクラス定義が
    # どのパッケージから来ているか)なので、Package名と合わせて集計する。
    for imp in imports:
        if imp["class_package"] not in ("None", ""):
            referenced_packages.add(imp["class_package"])

    disallowed = set()
    for pkg in referenced_packages:
        if pkg.startswith(OWN_PACKAGE_PREFIX):
            continue
        if any(pkg.startswith(p) for p in ENGINE_PREFIXES):
            continue
        disallowed.add(pkg)

    return {
        "file": os.path.relpath(uasset_path, REPO_ROOT),
        "uexp_file": os.path.relpath(uexp_path, REPO_ROOT) if os.path.exists(uexp_path) else None,
        "uexp_pair_structurally_consistent": pair_ok,
        "uexp_pair_error": pair_error,
        "package_name": summary["package_name"],
        "import_count": summary["import_count"],
        "export_count": summary["export_count"],
        "referenced_packages": sorted(referenced_packages),
        "disallowed_packages": sorted(disallowed),
        "imports": resolved,
    }


def find_all_uasset(root=NOUE_MASTER):
    return sorted(
        p for p in glob.glob(os.path.join(root, "**", "*.uasset"), recursive=True)
    )


# 判定対象のPalworld/ゲーム識別子(大小文字無視)。この文字列群が.uexp内の
# 印字可能ASCII文字列に一切現れないことを、compiled shader blob(357KB級)を
# 含む全.uexpについて確認する。DXBC/DXILコンテナ内のシェーダーバイトコード
# メタデータ(dx.entryPoints等)はUE5の標準コンパイラが常に出力するもので
# Palworld固有ではない — ここでは「Palworldというゲームを示す痕跡」だけを探す。
SUSPECT_PATTERNS = (b"pal", b"palworld", b"pocket", b"monster", b"pocketpair")


def scan_uexp_for_game_strings(uexp_path):
    with open(uexp_path, "rb") as f:
        data = f.read()
    low = data.lower()
    hits = {}
    for pat in SUSPECT_PATTERNS:
        idx = 0
        found = []
        while True:
            i = low.find(pat, idx)
            if i < 0:
                break
            found.append(i)
            idx = i + 1
            if len(found) >= 20:
                break
        if found:
            hits[pat.decode("ascii")] = [
                data[max(0, h - 24):h + 24] for h in found[:5]
            ]
    import re as _re
    strings = _re.findall(rb"[\x20-\x7e]{6,}", data)
    return {
        "size": len(data),
        "hit_patterns": {k: [repr(c) for c in v] for k, v in hits.items()},
        "notable_strings": sorted({
            s.decode("ascii") for s in strings
            if s.decode("ascii") in ("ShadowLift", "SelectionColor", "MainVS", "MainPS")
        }),
    }


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def regen_check():
    """devtool_make_t00_4096.py を実際に実行し、種から作った4096版が
    リポジトリ同梱物とバイト一致することを確認する(一時ディレクトリへ出力、
    リポジトリは一切変更しない)。"""
    gen_script = os.path.join(PIPELINE_PY, "devtool_make_t00_4096.py")
    asset_dir = os.path.join(NOUE_MASTER, "pak_extract_extra", "Player",
                              "ModelMaterials", "MainShader")
    committed = {
        "uasset": os.path.join(asset_dir, "t00.uasset"),
        "uexp": os.path.join(asset_dir, "t00.uexp"),
    }
    tmp_dir = tempfile.mkdtemp(prefix="d2p_t00_regen_")
    try:
        import subprocess
        proc = subprocess.run(
            [sys.executable, gen_script, "--out", tmp_dir],
            cwd=REPO_ROOT, capture_output=True, text=True)
        result = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "matches": {},
        }
        if proc.returncode == 0:
            for kind, committed_path in committed.items():
                regen_path = os.path.join(tmp_dir, "t00" + ("." + kind))
                if os.path.exists(regen_path) and os.path.exists(committed_path):
                    result["matches"][kind] = (
                        _sha256(regen_path) == _sha256(committed_path))
                else:
                    result["matches"][kind] = False
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _check_ue_available():
    """UnrealEngineが手元に無いことをログに残す(手段Aの可否判定の根拠)。"""
    candidates = []
    for env_var in ("UE_ROOT", "UE5_ROOT", "PROGRAMFILES"):
        base = os.environ.get(env_var)
        if base:
            candidates.append(base)
    found = []
    for base in candidates:
        for root, dirs, files in os.walk(base):
            depth = root[len(base):].count(os.sep)
            if depth > 3:
                dirs[:] = []
                continue
            for fn in files:
                if fn.lower().startswith("unrealeditor") and fn.lower().endswith(".exe"):
                    found.append(os.path.join(root, fn))
    ue_project_template = os.path.join(REPO_ROOT, "pipeline", "templates", "ue_project")
    return {
        "unreal_editor_found": found,
        "ue_project_template_exists": os.path.isdir(ue_project_template),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="単一ファイルだけを解析する(負の対照実験用)")
    ap.add_argument("--regen-check", action="store_true",
                     help="t00 4096版の再生成一致確認も行う")
    ap.add_argument("--shader-scan", action="store_true",
                     help="全.uexpの印字可能文字列からPalworld/ゲーム識別子の"
                          "有無を走査する(357KB級のコンパイル済みシェーダーblobを含む)")
    ap.add_argument("--json", default=None, help="全結果をJSONで書き出すパス")
    a = ap.parse_args()

    print("=== UE availability (Hand A feasibility) ===")
    ue_info = _check_ue_available()
    print(json.dumps(ue_info, ensure_ascii=False, indent=2))
    if not ue_info["unreal_editor_found"] and not ue_info["ue_project_template_exists"]:
        print("  -> Unreal Editor not found AND ue_project template deleted (dev#114). "
              "Hand A (full recook) is NOT possible on this machine for the UE-material "
              "assets (Groups A/B/E) or the tex_src_2048 seed (Group D).")

    if a.regen_check:
        print("\n=== Regen check: devtool_make_t00_4096.py (pure-Python, no UE) ===")
        r = regen_check()
        print(f"  returncode={r['returncode']}")
        print(f"  stdout:\n{r['stdout']}")
        if r["stderr"]:
            print(f"  stderr:\n{r['stderr']}")
        print(f"  byte-match vs committed pak_extract_extra/t00.*: {r['matches']}")
        if r["returncode"] != 0 or not all(r["matches"].values()):
            print("  -> REGEN MISMATCH/FAILURE")

    targets = [a.file] if a.file else find_all_uasset()
    total_file_count = sum(
        (1 if os.path.exists(p) else 0) +
        (1 if os.path.exists(p[:-len('.uasset')] + '.uexp') else 0)
        for p in targets)
    print(f"\n=== Import-table analysis: {len(targets)} uasset/uexp pair(s), "
          f"{total_file_count} file(s) total ===")
    all_results = []
    any_disallowed = False
    any_error = False
    any_pair_bad = False
    for path in targets:
        try:
            r = analyze_file(path)
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] {path}: {e}")
            any_error = True
            continue
        all_results.append(r)
        flag = "DISALLOWED!" if r["disallowed_packages"] else "ok"
        pair_flag = "pair-ok" if r["uexp_pair_structurally_consistent"] else "PAIR-FAIL"
        print(f"  {r['file']}: imports={r['import_count']} "
              f"referenced_packages={r['referenced_packages']} [{flag}] [{pair_flag}]")
        if r["disallowed_packages"]:
            any_disallowed = True
            print(f"    !!! disallowed packages: {r['disallowed_packages']}")
        if not r["uexp_pair_structurally_consistent"]:
            any_pair_bad = True
            print(f"    !!! uexp pair inconsistency: {r['uexp_pair_error']}")

    if a.shader_scan:
        print(f"\n=== Shader-string scan (all .uexp under noue_master) ===")
        uexp_targets = ([t[:-len('.uasset')] + '.uexp' for t in targets]
                         if not a.file else
                         [a.file[:-len('.uasset')] + '.uexp'])
        any_suspect = False
        for uexp in uexp_targets:
            if not os.path.exists(uexp):
                continue
            r = scan_uexp_for_game_strings(uexp)
            flag = "SUSPECT!" if r["hit_patterns"] else "clean"
            print(f"  {os.path.relpath(uexp, REPO_ROOT)}: size={r['size']} "
                  f"notable={r['notable_strings']} [{flag}]")
            if r["hit_patterns"]:
                any_suspect = True
                print(f"    !!! hits: {r['hit_patterns']}")
        print(f"  shader-scan RESULT: {'FAIL (suspect strings found)' if any_suspect else 'PASS (no Palworld/game identifiers found)'}")
        if any_suspect:
            any_disallowed = True

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"\nJSON written: {a.json}")

    print(f"\n=== Summary ===")
    print(f"  uasset/uexp pairs analyzed: {len(all_results)} / errors: {0 if not any_error else 'YES'}")
    print(f"  total files covered (uasset+uexp): {total_file_count}")
    print(f"  files with disallowed (non-Script/non-own) package references: "
          f"{'YES' if any_disallowed else 'none'}")
    print(f"  uexp/uasset pairs with structural inconsistency: "
          f"{'YES' if any_pair_bad else 'none'}")

    ok = (not any_disallowed) and (not any_error) and (not any_pair_bad) and len(all_results) == len(targets)
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
