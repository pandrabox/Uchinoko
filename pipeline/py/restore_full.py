# -*- coding: utf-8 -*-
"""P2 Plan B: 復元オーケストレーションラッパー(受領側が1コマンドで実行する)。

従来は手動3ステップだった復元手順をまとめる:
  1) 同梱Blenderで pipeline\\blender\\step01〜03 を、sanitize時とまったく同じ
     再ターゲットパラメータ(recipe.jsonの retarget_job_params)で製品アバター
     (VRM/FBX)へ再実行し、Avatar_{gender}.fbx を再生する(Plan Bの前提:
     同一パラメータで再実行すれば頂点順・座標が決定的に一致する。実測済み
     — docs\\REPORT_P2_2026-07-22.md 追記2参照)
  2) devtools\\dump_restore_geometry.py で復元用ジオメトリ(位置/法線/タンジェント/
     UV/スキンウェイト)を性別ごとにダンプ
  3) pipeline\\py\\restore_pak.py --restore-geometry-male/-female で
     sanitizedpak + recipe.json + 改変PNG から復元pakへ注入

既存モジュール(vp_core.py / vp_meshrestore.py / restore_pak.py / sanitize_pak.py /
blender/step01〜03 / devtools/dump_restore_geometry.py)は一切変更しない。
本ファイルはそれらを subprocess で呼び出すだけの新規オーケストレータ。

実行例:
  python restore_full.py --sanitized <avatar.sanitizedpak> --recipe <recipe.json> \
      --avatar <製品VRM/FBX> --out <復元pak> --png-dir <改変PNGフォルダ>
      [--work <作業ディレクトリ、省略時は一時ディレクトリ>]
      [--blender-exe <blender.exe>] [--vrm-addon-zip <zip>]
      [--palworld-pak <Pal-Windows.pak>] [--ue-root <UEインストール先>]
      [--skip-vanilla]

注意(REPORT_P2_2026-07-22.md 追記2で踏んだ既知バグ): git-bash環境から
UnrealPak.exe を相対パスで呼ぶと生成物の場所がずれる。extract_vanilla.py が
内部でUnrealPakを使うため、本スクリプトが job.json へ書き込むパス・
サブプロセスへ渡すパスは全て絶対パスへ正規化している。
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.dirname(HERE)          # pipeline\
REPO_DIR = os.path.dirname(PIPELINE_DIR)       # リポジトリルート
PY_DIR = HERE                                  # pipeline\py
BLENDER_DIR = os.path.join(PIPELINE_DIR, "blender")
DEVTOOLS_DIR = os.path.join(REPO_DIR, "devtools")

TAG = "restore_full"

# このリポジトリの開発機での既定値(convert.ps1利用時のjob.jsonと同じ流儀。
# vp_core.DEFAULT_PALWORLD_PAK/DEFAULT_UE_ROOTと同様、開発機のローカルパスを
# 既定値として持ち、CLI引数で上書きできるようにする)
DEFAULT_BLENDER_EXE = (
    r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe")
DEFAULT_VRM_ADDON_ZIP = os.path.join(
    REPO_DIR, "third_party", "VRM_Addon_for_Blender-Extension-4_4_0.zip")

# recipe.json の retarget_job_params からそのままjob.jsonへ複製してよいキー
# (sanitize_pak.py --retarget-job が保存する集合と同一。パス類・購入者固有
# 情報は含まれない設計 — sanitize_pak.py本体コメント参照)
RETARGET_JOB_KEYS = (
    "avatar_name", "shoulder_offset_deg", "merge_fingers", "merge_eyes",
    "unlit", "force_two_sided", "shadow_lift", "drop_bones", "sway_cloth_bones",
)


def die(msg):
    print(f"[{TAG}][FATAL] {msg}")
    sys.exit(1)


def run(cmd, log_path):
    """subprocessを実行し、ログをファイルへ保存する。失敗したら末尾を出して停止する。"""
    print(f"[{TAG}] $ {' '.join(cmd)}")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        tail = ""
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-3000:]
        except OSError:
            pass
        die(f"command failed exit={r.returncode} (log: {log_path})\n"
            f"--- log tail ---\n{tail}")
    print(f"[{TAG}]   -> OK (log: {log_path})")


def find_bundled_python(blender_exe):
    """Blender同梱Pythonのpython.exeを探す(convert.ps1と同じ流儀:
    <blenderのフォルダ>\\*\\python\\bin\\python.exe)。"""
    cands = glob.glob(os.path.join(
        os.path.dirname(blender_exe), "*", "python", "bin", "python.exe"))
    if not cands:
        die(f"Blender's bundled Python was not found (no "
            f"*/python/bin/python.exe under the Blender folder): {os.path.dirname(blender_exe)}")
    return cands[0]


def read_vanilla_version():
    """extract_vanilla.py の VANILLA_VERSION 定数を読む(convert.ps1のPhase0
    キャッシュ判定と同じ流儀。ソース側の値をここへ複製しない)。"""
    path = os.path.join(PY_DIR, "extract_vanilla.py")
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith("VANILLA_VERSION"):
                return s.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
    die(f"could not read VANILLA_VERSION from extract_vanilla.py: {path}")


def build_job(avatar, genders, retarget_job_params, blender_exe, vrm_addon_zip,
              palworld_pak, ue_root):
    job = {k: retarget_job_params[k] for k in RETARGET_JOB_KEYS
           if k in retarget_job_params}
    job["vrm_path"] = avatar
    job["genders"] = genders
    job["license_confirmed"] = True
    paths = {"blender_exe": blender_exe, "vrm_addon_zip": vrm_addon_zip}
    if palworld_pak:
        paths["palworld_pak"] = palworld_pak
    if ue_root:
        paths["ue_root"] = ue_root
    job["paths"] = paths
    return job


def main():
    ap = argparse.ArgumentParser(
        description="sanitizedpak + recipe.json + 製品アバターから復元pakを1コマンドで生成する")
    ap.add_argument("--sanitized", required=True, help="avatar.sanitizedpak")
    ap.add_argument("--recipe", required=True, help="recipe.json")
    ap.add_argument("--avatar", required=True,
                    help="製品VRM/FBX(sanitize時に使ったのと同一アバター・同一ファイル)")
    ap.add_argument("--png-dir", default=None,
                    help="改変テクスチャPNGのフォルダ。省略時はrestore_pak.pyの規定に従う"
                         "(--png-dir/--inject-originalのどちらも無いとrestore_pak.py側で停止する)")
    ap.add_argument("--out", required=True, help="出力する復元pak")
    ap.add_argument("--work", default=None,
                    help="作業ディレクトリ(job.json/vanilla/converted等の置き場所)。"
                         "省略時は一時ディレクトリを新規作成する")
    ap.add_argument("--blender-exe", default=DEFAULT_BLENDER_EXE)
    ap.add_argument("--vrm-addon-zip", default=DEFAULT_VRM_ADDON_ZIP)
    ap.add_argument("--palworld-pak", default=None,
                    help="省略時はvp_core.DEFAULT_PALWORLD_PAKを使う")
    ap.add_argument("--ue-root", default=None,
                    help="省略時はvp_core.DEFAULT_UE_ROOTを使う")
    ap.add_argument("--skip-vanilla", action="store_true",
                    help="--work配下に既にvanilla一式がある場合、版数が違っても再抽出しない"
                         "(繰り返し実行時の高速化用)")
    args = ap.parse_args()

    # UnrealPak相対パス起因の既知バグ(REPORT追記2)を踏まないよう、以後の
    # サブプロセスへ渡すパスは全て絶対パスへ正規化してから使う
    sanitized = os.path.abspath(args.sanitized)
    recipe_path = os.path.abspath(args.recipe)
    avatar = os.path.abspath(args.avatar)
    out_pak = os.path.abspath(args.out)
    png_dir = os.path.abspath(args.png_dir) if args.png_dir else None
    blender_exe = os.path.abspath(args.blender_exe)
    vrm_addon_zip = os.path.abspath(args.vrm_addon_zip)
    palworld_pak = os.path.abspath(args.palworld_pak) if args.palworld_pak else None
    ue_root = os.path.abspath(args.ue_root) if args.ue_root else None

    for p, label in ((sanitized, "--sanitized"), (recipe_path, "--recipe"),
                     (avatar, "--avatar"), (blender_exe, "--blender-exe"),
                     (vrm_addon_zip, "--vrm-addon-zip")):
        if not os.path.exists(p):
            die(f"{label} does not exist: {p}")
    if png_dir and not os.path.isdir(png_dir):
        die(f"--png-dir does not exist: {png_dir}")

    if args.work:
        work = os.path.abspath(args.work)
        os.makedirs(work, exist_ok=True)
    else:
        work = tempfile.mkdtemp(prefix="d2p_restore_full_")
    print(f"[{TAG}] work directory: {work}")

    with open(recipe_path, encoding="utf-8") as f:
        recipe = json.load(f)
    if recipe.get("format") != "d2p-sanitized-recipe-1":
        die(f"unknown recipe format: {recipe.get('format')}")
    retarget_job_params = recipe.get("retarget_job_params") or {}
    if not retarget_job_params:
        die("recipe has no retarget_job_params. Needs a recipe.json created by running "
            "sanitize_pak.py --strip-vertices with --retarget-job")
    correspondence = recipe.get("vertex_correspondence") or {}
    genders = sorted(correspondence.keys())
    if not genders:
        die("recipe has no vertex_correspondence (recipe was not vertex-zero-filled)")
    print(f"[{TAG}] genders to restore: {genders}")
    print(f"[{TAG}] retarget parameters (from recipe): {retarget_job_params}")

    job = build_job(avatar, genders, retarget_job_params, blender_exe,
                    vrm_addon_zip, palworld_pak, ue_root)
    job_path = os.path.join(work, "job.json")
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    print(f"[{TAG}] job.json generated: {job_path}")

    bpython = find_bundled_python(blender_exe)
    log_dir = os.path.join(work, "logs")

    # === Phase 0: バニラ情報抽出 ===
    # step02_retarget.pyは vanilla/refskel_{gender}.json を直接要求するため必須の前提
    # (convert.ps1のPhase0と同じ役割。バージョン照合キャッシュも同じ流儀で真似る)
    vanilla_version = read_vanilla_version()
    version_file = os.path.join(work, "vanilla", "version.txt")
    have_version = None
    if os.path.exists(version_file):
        with open(version_file, encoding="utf-8") as f:
            have_version = f.read().strip()
    if have_version == vanilla_version:
        print(f"[{TAG}] === Phase 0: vanilla data extraction — cache match (version {have_version}), skipping ===")
    elif args.skip_vanilla and have_version:
        print(f"[{TAG}] === Phase 0: --skip-vanilla specified, reusing existing version {have_version} ===")
    else:
        print(f"[{TAG}] === Phase 0: vanilla data extraction ===")
        run([bpython, os.path.join(PY_DIR, "extract_vanilla.py"), job_path],
            os.path.join(log_dir, "extract_vanilla.log"))

    # === Phase 1: Blender step01〜03を同一パラメータで再実行 ===
    print(f"[{TAG}] === Phase 1: step01 (avatar import) ===")
    run([blender_exe, "--background", "--factory-startup",
         "--python-exit-code", "1", "--python",
         os.path.join(BLENDER_DIR, "step01_import_vrm.py"), "--", job_path],
        os.path.join(log_dir, "step01_import_vrm.log"))

    restore_geo = {}
    for gender in genders:
        print(f"[{TAG}] === Phase 1: step02 skeleton fit ({gender}) ===")
        run([blender_exe, "--background", "--factory-startup",
             "--python-exit-code", "1", "--python",
             os.path.join(BLENDER_DIR, "step02_retarget.py"), "--", job_path, gender],
            os.path.join(log_dir, f"step02_retarget_{gender}.log"))

        print(f"[{TAG}] === Phase 1: step03 FBX export ({gender}) ===")
        run([blender_exe, "--background", "--factory-startup",
             "--python-exit-code", "1", "--python",
             os.path.join(BLENDER_DIR, "step03_export_fbx.py"), "--", job_path, gender],
            os.path.join(log_dir, f"step03_export_fbx_{gender}.log"))

        avatar_fbx = os.path.join(work, "converted", f"Avatar_{gender}.fbx")
        if not os.path.exists(avatar_fbx):
            die(f"step03 produced no output (something in step01-03 failed): {avatar_fbx}")

        # === Phase 2: ジオメトリダンプ(devtools/dump_restore_geometry.py) ===
        print(f"[{TAG}] === Phase 2: restore geometry dump ({gender}) ===")
        geo_out = os.path.join(work, f"restore_geometry_{gender.lower()}.json")
        run([blender_exe, "--background", "--factory-startup",
             "--python-exit-code", "1", "--python",
             os.path.join(DEVTOOLS_DIR, "dump_restore_geometry.py"), "--",
             avatar_fbx, gender, geo_out],
            os.path.join(log_dir, f"dump_restore_geometry_{gender}.log"))
        if not os.path.exists(geo_out):
            die(f"geometry dump produced no output: {geo_out}")
        restore_geo[gender] = geo_out

    # === Phase 3: restore_pak.py(頂点+テクスチャ注入) ===
    print(f"[{TAG}] === Phase 3: restore_pak.py ===")
    cmd = [bpython, os.path.join(PY_DIR, "restore_pak.py"),
           "--sanitized", sanitized, "--recipe", recipe_path, "--out", out_pak]
    if png_dir:
        cmd += ["--png-dir", png_dir]
    if "Male" in restore_geo:
        cmd += ["--restore-geometry-male", restore_geo["Male"]]
    if "Female" in restore_geo:
        cmd += ["--restore-geometry-female", restore_geo["Female"]]
    run(cmd, os.path.join(log_dir, "restore_pak.log"))

    if not os.path.exists(out_pak):
        die(f"restore pak was not generated: {out_pak}")
    print(f"[{TAG}] done: {out_pak}")
    print(f"[{TAG}] work directory (job.json/logs/intermediates): {work}")


if __name__ == "__main__":
    main()
