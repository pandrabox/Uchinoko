r"""dev#532 WP-B1: production packaging builder ("Python版 build_app.ps1").

Assembles the bat + embeddable-Python distributable described in
work\wp532A\DESIGN.md SS3/SS4.1 (tkinter bundling strategy, directory layout)
and work\wp532\PROPOSAL.md (the bat+embeddable prototype this promotes to a
real, repeatable build script).

What it does, end to end:
  1. Downloads (or reuses a cached, hash-verified copy of) the official
     python.org embeddable zip for Windows amd64.
  2. Downloads (or reuses a cached copy of) the official python.org *full*
     installer, silently installs it to a private scratch directory
     (Include_tcltk=1, no shortcuts/PATH/file-association changes), copies
     out just the tkinter runtime pieces (_tkinter.pyd, tcl86t.dll,
     tk86t.dll, the tcl8.6/tk8.6 script libraries, and the Lib\tkinter
     Python package), uninstalls the scratch install, and caches the
     extracted bundle for future builds (so steps 1-2 normally only pay the
     network+install cost once).
  3. Overlays the tkinter bundle onto a fresh embeddable-Python extraction.
  4. Copies the application source (real app_py\ sources, or - since WP-A1
     has not landed yet - a --fixture stub) plus license text into a
     `res\` payload directory.
  5. Writes `Uchinoko.bat` (entry point, non-PE) and `README.txt` at the
     payload root.
  6. Verifies the payload root contains *only* Uchinoko.bat / README.txt /
     res\ (owner-mandated layout constraint, dev#532 WP-B1 amendment), runs
     the packaging\check_signatures.py gate against res\, and (with
     --fixture) launches the generated bat end-to-end as a smoke test.

Usage:
    python app_py\build.py --fixture
    python app_py\build.py --fixture --console      # visible console variant
    python app_py\build.py --out D:\stage\Uchinoko  # custom output location
    python app_py\build.py --stage-dir D:\stage\Uchinoko  # same, staging-only name (dev#628)

dev#628: --stage-dir is an alias for --out, added so callers whose whole
purpose is "assemble the unzipped payload and stop" (e.g.
.devonly\HumanTest\make_humantest.bat) can say so without reusing the more
generic --out flag. This script never creates a zip itself either way (that
step lives in build\make_dist.ps1, which calls this script with --out and
then Compress-Archive's the result) -- --stage-dir does not change that,
it only names the same behavior for the no-zip callers. --out and
--stage-dir are mutually exclusive (both just set the same output directory).

All network fetches are pinned to a known-good SHA256 recorded below (the
hashes were computed from a direct download of python.org's own files during
this WP; see completion report). A hash mismatch aborts the build rather than
silently using a different binary.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = REPO_ROOT / "packaging"
DEFAULT_CACHE_DIR = PACKAGING_DIR / "_cache"
DEFAULT_OUT_DIR = PACKAGING_DIR / "dist" / "Uchinoko"
FIXTURE_APP_DIR = PACKAGING_DIR / "_fixture" / "app"

PYTHON_VERSION = "3.11.9"
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
EMBED_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
INSTALLER_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-amd64.exe"
INSTALLER_SHA256 = "5ee42c4eee1e6b4464bb23722f90b45303f79442df63083f05322f1785f5fdde"

# Pinned hashes of the three tkinter PE files, computed once from the
# verified python.org full installer during this WP. Guards the cache
# against silent corruption/tampering across runs.
TKINTER_PE_SHA256 = {
    "_tkinter.pyd": "6f7bdc2f60a1795b58ec7015ec262d6b234aa8d0f022185de0f52bac4adab449",
    "tcl86t.dll": "4e699ff2d6d147d0586c8c77be5a18f20ca0758f432d7b0f489223f2fa4dd221",
    "tk86t.dll": "b6af038120f2b8644c7ce1e11917f410009848287622135d7e386f90d28a831c",
}

sys.path.insert(0, str(PACKAGING_DIR))
import check_signatures  # noqa: E402

PIPELINE_PY_DIR = REPO_ROOT / "pipeline" / "py"
sys.path.insert(0, str(PIPELINE_PY_DIR))
import vp_core  # noqa: E402  (dev#642: rmtree_robust、read-only施錠済みshared_cache対策)


def log(msg: str) -> None:
    print(f"[build.py] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_verified(url: str, dest: Path, expected_sha256: str, label: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256_file(dest) == expected_sha256:
        log(f"{label}: cached, hash OK ({dest})")
        return dest
    log(f"{label}: downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    actual = sha256_file(tmp)
    if actual != expected_sha256:
        tmp.unlink(missing_ok=True)
        raise SystemExit(
            f"ERROR: {label} SHA256 mismatch. expected={expected_sha256} actual={actual} url={url}"
        )
    tmp.replace(dest)
    log(f"{label}: downloaded and verified ({dest})")
    return dest


def ensure_embeddable_zip(cache_dir: Path) -> Path:
    dest = cache_dir / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    return download_verified(EMBED_URL, dest, EMBED_SHA256, "embeddable python zip")


def ensure_installer_exe(cache_dir: Path) -> Path:
    dest = cache_dir / f"python-{PYTHON_VERSION}-amd64.exe"
    return download_verified(INSTALLER_URL, dest, INSTALLER_SHA256, "full python installer")


def _tkinter_bundle_dir(cache_dir: Path) -> Path:
    return cache_dir / f"tkinter_bundle_{PYTHON_VERSION}"


def _tkinter_bundle_is_valid(bundle_dir: Path) -> bool:
    if not bundle_dir.is_dir():
        return False
    for name, expected in TKINTER_PE_SHA256.items():
        f = bundle_dir / name
        if not f.is_file() or sha256_file(f) != expected:
            return False
    for rel in ("tcl/tcl8.6", "tcl/tk8.6", "tkinter/__init__.py", "licenses/TCL_TK_LICENSE.txt"):
        if not (bundle_dir / rel).exists():
            return False
    return True


def ensure_tkinter_bundle(cache_dir: Path) -> Path:
    """Ensures a cached folder with the tkinter runtime pieces extracted
    from python.org's official *full* installer (embeddable zips ship
    without tkinter at all - confirmed empirically in work\\wp532\\PROPOSAL.md
    SS2). Established procedure (this WP, verified end-to-end):

      1. Silently run the full installer into a private scratch TargetDir
         with InstallAllUsers=0, Shortcuts=0, PrependPath=0,
         AssociateFiles=0, Include_tcltk=1, Include_test/doc/dev/tools=0
         (minimal footprint - only core+lib+tcltk features are materialized).
         IMPORTANT: the installer's bundle-level properties (TargetDir etc.)
         are only honored when each argument is passed as a *separate*
         process argument (subprocess.run with a list does this correctly
         on Windows); joining them into one string before invoking silently
         falls back to the installer's own default per-user location instead
         of erroring, which is easy to miss (empirically confirmed in this
         WP: PowerShell's `Start-Process -ArgumentList <array>` mis-flattens
         it, `System.Diagnostics.ProcessStartInfo.ArgumentList` and Python's
         `subprocess.run([...])` both do it correctly).
      2. Copy DLLs\\_tkinter.pyd, DLLs\\tcl86t.dll, DLLs\\tk86t.dll,
         tcl\\tcl8.6, tcl\\tk8.6, and Lib\\tkinter (minus test/__pycache__)
         out of the scratch install.
      3. Uninstall the scratch install (`/uninstall /quiet TargetDir=...`)
         and delete the scratch directory, restoring the host to its prior
         state.

    All three tkinter PE files inherited this way carry the same
    "CN=Python Software Foundation" Authenticode signature as the embeddable
    zip's own files (verified with packaging\\check_signatures.py during
    this WP) - bundling them does not introduce any unsigned PE.
    """
    bundle_dir = _tkinter_bundle_dir(cache_dir)
    if _tkinter_bundle_is_valid(bundle_dir):
        log(f"tkinter bundle: cached and verified ({bundle_dir})")
        return bundle_dir

    log("tkinter bundle: not cached (or failed verification) - building it now")
    installer = ensure_installer_exe(cache_dir)
    staging = cache_dir / "_staging_pyfull"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    install_args = [
        str(installer),
        "/quiet",
        "InstallAllUsers=0",
        f"TargetDir={staging}",
        "Include_pip=0",
        "Include_launcher=0",
        "Include_test=0",
        "Include_doc=0",
        "Include_dev=0",
        "Include_tools=0",
        "Include_exe=1",
        "Include_lib=1",
        "Include_tcltk=1",
        "Include_symbols=0",
        "Include_debug=0",
        "AssociateFiles=0",
        "PrependPath=0",
        "Shortcuts=0",
        "CompileAll=0",
    ]
    log(f"tkinter bundle: running full installer into scratch dir {staging}")
    try:
        subprocess.run(install_args, check=True, timeout=600)

        dlls = staging / "DLLs"
        tcl_src = staging / "tcl"
        tkinter_src = staging / "Lib" / "tkinter"
        for required in (dlls / "_tkinter.pyd", dlls / "tcl86t.dll", dlls / "tk86t.dll",
                         tcl_src / "tcl8.6", tcl_src / "tk8.6", tkinter_src):
            if not required.exists():
                raise SystemExit(f"ERROR: expected file/dir missing from scratch install: {required}")

        tmp_bundle = cache_dir / f"_staging_tkinter_bundle_{PYTHON_VERSION}"
        if tmp_bundle.exists():
            shutil.rmtree(tmp_bundle, ignore_errors=True)
        tmp_bundle.mkdir(parents=True)

        shutil.copy2(dlls / "_tkinter.pyd", tmp_bundle / "_tkinter.pyd")
        shutil.copy2(dlls / "tcl86t.dll", tmp_bundle / "tcl86t.dll")
        shutil.copy2(dlls / "tk86t.dll", tmp_bundle / "tk86t.dll")
        (tmp_bundle / "tcl").mkdir()
        shutil.copytree(tcl_src / "tcl8.6", tmp_bundle / "tcl" / "tcl8.6")
        shutil.copytree(tcl_src / "tk8.6", tmp_bundle / "tcl" / "tk8.6")
        shutil.copytree(
            tkinter_src,
            tmp_bundle / "tkinter",
            ignore=shutil.ignore_patterns("__pycache__", "test"),
        )
        (tmp_bundle / "licenses").mkdir()
        license_terms = tcl_src / "tk8.6" / "license.terms"
        if license_terms.exists():
            shutil.copy2(license_terms, tmp_bundle / "licenses" / "TCL_TK_LICENSE.txt")
        else:
            (tmp_bundle / "licenses" / "TCL_TK_LICENSE.txt").write_text(
                "Tcl/Tk license.terms not found in this installer build; "
                "see https://www.tcl.tk/software/tcltk/license.html\n",
                encoding="utf-8",
            )

        for name, expected in TKINTER_PE_SHA256.items():
            actual = sha256_file(tmp_bundle / name)
            if actual != expected:
                raise SystemExit(
                    f"ERROR: tkinter bundle file {name} SHA256 mismatch "
                    f"(python.org build changed?). expected={expected} actual={actual}"
                )
    finally:
        log("tkinter bundle: uninstalling scratch install")
        subprocess.run(
            [str(installer), "/uninstall", "/quiet", f"TargetDir={staging}"],
            check=False,
            timeout=600,
        )
        shutil.rmtree(staging, ignore_errors=True)

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)
    tmp_bundle.replace(bundle_dir)
    log(f"tkinter bundle: built and cached at {bundle_dir}")
    return bundle_dir


def _extract_embeddable(embed_zip: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(embed_zip) as zf:
        zf.extractall(dest)
    pth = dest / "python311._pth"
    if pth.exists():
        text = pth.read_text(encoding="utf-8")
        if not any(line.strip() == "." for line in text.splitlines()):
            pth.write_text(text.rstrip("\n") + "\n.\n", encoding="utf-8")


def _overlay_tkinter(python_embed_dir: Path, tkinter_bundle: Path) -> None:
    for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
        shutil.copy2(tkinter_bundle / name, python_embed_dir / name)
    shutil.copytree(tkinter_bundle / "tcl", python_embed_dir / "tcl")
    shutil.copytree(tkinter_bundle / "tkinter", python_embed_dir / "tkinter")


RESIDUE_DIR_NAMES = ("__pycache__", ".pytest_cache")
RESIDUE_FILE_GLOBS = ("*.bak", "*.bak_*", "*.bak2_*", "*.orig", "*.log")


def _clean_residue(root: Path) -> None:
    """U28(旧make_dist.ps1「開発残骸の除外」)の移植。pipeline\\/unity\\丸ごと
    コピーで開発中の__pycache__/.pytest_cache/*.bak系が混入する事故クラスを防ぐ。"""
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in RESIDUE_DIR_NAMES]
    for name in RESIDUE_DIR_NAMES:
        for d in root.rglob(name):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
    for pattern in RESIDUE_FILE_GLOBS:
        for f in root.rglob(pattern):
            if f.is_file():
                f.unlink(missing_ok=True)


def _copy_pipeline_and_unity(res_dir: Path, fixture: bool) -> None:
    """旧make_dist.ps1の `foreach ($d in @("pipeline", "unity"))` 相当。
    dev#532 D1: 新レイアウト(zip直下は3点のみ)ではpipeline\\/unity\\は
    ルートではなく res\\ 配下(=app_root、pipeline_runner.build_convert_script_path
    等が期待する `<app_root>\\pipeline\\cli\\convert.ps1` と一致)へ置く。"""
    if fixture:
        log("pipeline/unity: skipped (--fixture)")
        return
    for name in ("pipeline", "unity"):
        src = REPO_ROOT / name
        if not src.is_dir():
            raise SystemExit(f"ERROR: {src} not found (repo layout unexpected)")
        dest = res_dir / name
        shutil.copytree(src, dest)
        log(f"{name}: copied {src} -> {dest}")
    # 旧make_dist.ps1「梱包しない開発物の掃除」(smoke_all.ps1は開発専用CLI)
    smoke_all = res_dir / "pipeline" / "cli" / "smoke_all.ps1"
    smoke_all.unlink(missing_ok=True)


def _resolve_ooz_pyd() -> Path:
    """ooz.pyd(pyooz、GPLv3+)の所在解決。旧make_dist.ps1と同じ既定パス
    (`%APPDATA%\\Python\\Python313\\site-packages\\ooz.pyd`、`pip install pyooz`後の
    python.org既定インストール先)。D2P_OOZ_SITE_PACKAGES で上書き可能
    (旧ps1には無かった追加のフォールバックだが、環境が変わっても壊れないよう
    外部依存パスの原則(CLAUDE.md)に沿って手動指定口を用意した)。"""
    site_pkg = os.environ.get("D2P_OOZ_SITE_PACKAGES") or os.path.join(
        os.environ.get("APPDATA", ""), "Python", "Python313", "site-packages"
    )
    ooz_pyd = Path(site_pkg) / "ooz.pyd"
    if not ooz_pyd.is_file():
        raise SystemExit(
            f"ERROR: ooz.pyd not found: {ooz_pyd}\n"
            "  (pip install pyooz が必要。既定と異なる場所にある場合は "
            "D2P_OOZ_SITE_PACKAGES で site-packages ディレクトリを指定できる)"
        )
    return ooz_pyd


# dev#577: python3.dll(stable ABI redirector)は「どのpython3XX.dllへフォワード
# するか」がファイルごとに焼き込まれている(CPython 3.11由来ならpython311、
# 3.13由来ならpython313)。Blender 4.3.2同梱Pythonは3.11なので、python311以外へ
# フォワードする個体を差し込むと、開発機(PATH上にpython313.dllがある)では
# 動くのにクリーン環境(WSB・実ユーザー機)でだけ `import ooz` がDLL load failed
# になる——v2.3.0 D1ビルドで実際に起きた事故(3.13のpython3.dllが混入)。
_PYTHON3_DLL_FORWARD_RE = re.compile(rb"python3\d\d")
_PYTHON3_DLL_REQUIRED_TARGET = b"python311"


def _python3_dll_forward_targets(path: Path) -> set[bytes]:
    """python3.dllのバイト列からフォワード先(python3XX)の集合を抽出する。
    リダイレクタのエクスポート転送文字列(例: `python311.PyObject_...`)を
    そのまま見るので、フォワード先というファイルの機能そのものを判定できる
    (バージョン表示等の代理値ではない)。"""
    return set(_PYTHON3_DLL_FORWARD_RE.findall(path.read_bytes()))


def _validate_python3_dll(path: Path, origin: str) -> Path:
    targets = _python3_dll_forward_targets(path)
    if targets != {_PYTHON3_DLL_REQUIRED_TARGET}:
        found = ", ".join(sorted(t.decode("ascii") for t in targets)) or "(none)"
        raise SystemExit(
            f"ERROR: {origin} の python3.dll はPython 3.11用のリダイレクタではない: {path}\n"
            f"  フォワード先検出: {found} / 要求: python311\n"
            "  (Blender 4.3.2同梱Pythonは3.11。python311以外へフォワードする"
            "python3.dllを同梱すると、開発機では動くのにクリーン環境でだけ "
            "import ooz がDLL load failedになる。dev#577)"
        )
    return path


def _resolve_python3_dll(python_embed_dir: Path) -> Path:
    """python3.dll(stable ABI redirector、PSFライセンス)の所在解決。

    dev#577(入口で正規化): 既定はビルド自身が展開済みの embeddable Python
    (SHA256ピン留め済みのpython.org公式3.11.9)に入っている python3.dll。
    ホスト機のPythonインストール状態に一切依存しない(旧既定の
    %LOCALAPPDATA%\\Programs\\Python\\Python311\\ 探索は、ホストに3.13しか
    無い環境で誤ったdllを掴む事故経路だったため廃止)。
    D2P_PYTHON311_DLL による明示上書きは維持する(CI互換)が、どちらの経路でも
    フォワード先=python311 の検証を必ず通す(fail-closed)。

    dev#628 で確認: この既定経路（embeddable由来のpython3.dll）自体が、
    「D2P_PYTHON311_DLL未設定でもキャッシュ済み公式embeddable zipから
    python3.dllを取り出して使う」フォールバック要件を既に満たしている
    (python_embed_dir はこの関数の呼び出し時点で、SHA256照合済みの
    埋め込みzip(ensure_embeddable_zip)を_extract_embeddable()で展開した
    実体であり、追加のダウンロードや別経路の抽出は不要)。dev#628時点で
    D2P_PYTHON311_DLL 未設定のクリーン環境で実走確認済み(work\\wp_628_progress.md
    参照)。"""
    override = os.environ.get("D2P_PYTHON311_DLL")
    if override:
        p = Path(override)
        if not p.is_file():
            raise SystemExit(f"ERROR: D2P_PYTHON311_DLL が指すファイルが無い: {p}")
        return _validate_python3_dll(p, "D2P_PYTHON311_DLL")
    p = python_embed_dir / "python3.dll"
    if not p.is_file():
        raise SystemExit(
            f"ERROR: 展開済みembeddable Pythonに python3.dll が無い: {p}\n"
            "  (python.org embeddable zipの構成が変わった可能性)"
        )
    return _validate_python3_dll(p, "embeddable python (python_embed)")


def _copy_assets(res_dir: Path, python_embed_dir: Path) -> None:
    """third_party\\ + blender_patch素材(旧make_dist.ps1の同名節)をres\\assets\\
    へ同梱する。third_party\\自体(VRM Addon zip等)はMIT互換のもの限りで、
    ooz.pyd/python3.dllはBlenderの初回起動セットアップ(ensure_blender.ps1)が
    ダウンロード直後のBlenderへ差し込む「差し込み素材」(Blender本体は同梱しない、
    dev#54)。"""
    assets_dir = res_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    third_party_src = REPO_ROOT / "third_party"
    if not third_party_src.is_dir():
        raise SystemExit(f"ERROR: {third_party_src} not found")
    shutil.copytree(third_party_src, assets_dir / "third_party")
    log(f"assets: third_party copied -> {assets_dir / 'third_party'}")

    blender_patch_dir = assets_dir / "blender_patch"
    blender_patch_dir.mkdir(parents=True)
    ooz_pyd = _resolve_ooz_pyd()
    shutil.copy2(ooz_pyd, blender_patch_dir / "ooz.pyd")
    dist_info_dirs = list(ooz_pyd.parent.glob("pyooz-*.dist-info"))
    for d in dist_info_dirs:
        shutil.copytree(d, blender_patch_dir / d.name)
    python3_dll = _resolve_python3_dll(python_embed_dir)
    shutil.copy2(python3_dll, blender_patch_dir / "python3.dll")
    # dev#577: コピー後の実体を最終検証(コピー元の検証だけだと、将来コピー経路が
    # 変わったときに素通りする)。ここがFAILすればビルド自体が止まる(fail-closed)。
    _validate_python3_dll(blender_patch_dir / "python3.dll", "blender_patch(コピー後検証)")
    log(f"assets: blender_patch (ooz.pyd + {len(dist_info_dirs)} dist-info + python3.dll) "
        f"-> {blender_patch_dir} (python3.dll forward-target=python311 verified)")


THIRD_PARTY_LICENSES_TEXT = """Uchinoko for Palworld: THIRD-PARTY NOTICES
=============================================

Uchinoko for Palworld本体は MIT License(licenses\\UCHINOKO_LICENSE.txt参照)です。

以下のコンポーネントはGPLv3+ (GNU General Public License v3 or later) であり、
本体からは常にsubprocess経由でのみ起動されます(importもリンクもしない、
"mere aggregation"構成。ffmpeg.exe等の外部実行ファイルをMITツールが
subprocessで呼ぶのと同じ扱いです)。

1. pipeline\\py\\ooz_worker_gpl.py
   本体からpyoozを呼び出すための単独完結した別プロセス実行体。
   ライセンス: GPLv3 (ファイル冒頭のヘッダ参照)

2. pyooz (初回起動時にダウンロードするBlenderの
   python\\lib\\site-packages\\ooz.pyd等へ配置。差し込み素材そのものは
   assets\\blender_patch\\ooz.pyd に小容量で同梱)
   Oodle互換解凍ライブラリoozのPythonバインディング。
   配布元: https://pypi.org/project/pyooz/ (https://github.com/zao/pyooz)
   ライセンス: GPLv3+ (GNU General Public License v3 or later)

GPLv3全文: https://www.gnu.org/licenses/gpl-3.0.txt

Blender Portable(GPL、公式配布に GPL-3.0-or-later.txt / GPL-2.0-or-later.txt 同梱)は
この配布物(zip)には含まれません。初回起動時にツールが公式サイト
(https://www.blender.org/download/) から自動的にダウンロードし、
assets\\tools\\ に配置します(SHA256をピン留めして照合。
pipeline\\cli\\ensure_blender.ps1 参照)。

python3.dll(初回起動時にダウンロードするBlenderの
python\\bin\\python3.dll へ配置。差し込み素材そのものは
assets\\blender_patch\\python3.dll に同梱)は
CPython公式配布物の一部(PSFライセンス)です。 https://www.python.org/

このres\\python_embed\\配下のPython本体・Tcl/Tkランタイムは
python.org公式配布物のうち著作権者・ライセンスが licenses\\PYTHON_LICENSE.txt /
licenses\\TCL_TK_LICENSE.txt に含まれています。
"""


def _copy_app_sources(res_dir: Path, fixture: bool) -> None:
    app_dest = res_dir / "app"
    app_dest.mkdir(parents=True)
    if fixture:
        log(f"app sources: using fixture ({FIXTURE_APP_DIR})")
        shutil.copytree(FIXTURE_APP_DIR, app_dest, dirs_exist_ok=True)
        return

    app_py_dir = REPO_ROOT / "app_py"
    main_py = app_py_dir / "main.py"
    if not main_py.exists():
        raise SystemExit(
            "ERROR: app_py\\main.py not found (WP-A1 not landed yet). "
            "Use --fixture to build with the packaging smoke-test stub instead."
        )
    log(f"app sources: copying real app_py\\ tree from {app_py_dir}")
    for item in app_py_dir.iterdir():
        if item.name == "build.py":
            continue
        if item.is_dir():
            shutil.copytree(item, app_dest / item.name)
        else:
            shutil.copy2(item, app_dest / item.name)


def _copy_licenses(res_dir: Path, python_embed_dir: Path, tkinter_bundle: Path) -> None:
    licenses_dir = res_dir / "licenses"
    licenses_dir.mkdir(parents=True)

    repo_license = REPO_ROOT / "LICENSE"
    if repo_license.exists():
        shutil.copy2(repo_license, licenses_dir / "UCHINOKO_LICENSE.txt")
    third_party = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
    if third_party.exists():
        shutil.copy2(third_party, licenses_dir / "THIRD_PARTY_NOTICES.md")

    python_license = python_embed_dir / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, licenses_dir / "PYTHON_LICENSE.txt")

    tcl_tk_license = tkinter_bundle / "licenses" / "TCL_TK_LICENSE.txt"
    if tcl_tk_license.exists():
        shutil.copy2(tcl_tk_license, licenses_dir / "TCL_TK_LICENSE.txt")

    # dev#532 D1: GPLv3+第三者コンポーネント(ooz_worker_gpl.py本体+pyooz)の
    # 通知(旧make_dist.ps1「THIRD_PARTY_LICENSES.txtの作成」節と同内容、
    # res\\licenses\\へ集約する新レイアウトに合わせて配置場所のみ変更)。
    (licenses_dir / "THIRD_PARTY_LICENSES.txt").write_text(
        THIRD_PARTY_LICENSES_TEXT, encoding="utf-8"
    )


# dev#532 D1(拘束条件、dev#532コメント列): batは `%~dp0` 相対のみ(裸のpython参照
# 禁止)+ `-E`(PYTHON*環境変数を無視、環境隔離)+ TCL_LIBRARY/TK_LIBRARY明示上書き。
# 出荷ゲート(gate_bat_isolation()、下記)がこの3点を機械照合する。
BAT_TEMPLATE_HIDDEN = """@echo off
rem dev#532 WP-B1/D1, dev#593 generated entry point (non-PE launcher).
rem dev#593: pythonw.exe is launched asynchronously via `start ""` (NOT
rem `start "" cmd /c ...`, which would pop a new console window -- a bare
rem GUI-subsystem exe launched via `start` gets no console of its own).
rem This batch file returns and its console window closes immediately,
rem instead of staying open/visible until the GUI app itself exits
rem (dev#593 root cause: a direct, unstarted invocation blocks cmd.exe on
rem the child regardless of subsystem, keeping the window up for the whole
rem GUI session).
rem Console hidden by design (pythonw.exe has no console of its own).
rem Output capture moved to the Python side (dev#593): main.py itself opens
rem res\\logs\\launch.log as soon as it detects it has no usable
rem sys.stdout/sys.stderr (always true for this pythonw+start launch path),
rem so nothing is silently lost -- the redirection moved from this batch
rem file into main.py, it did not go away.
rem -E: ignore PYTHON*-prefixed environment variables (isolation, dev#532 D1).
rem -X utf8: force UTF-8 stdio regardless of the OS locale (cp932/cp437/
rem EUC-KR/...), so launch.log never raises UnicodeEncodeError on non-ASCII
rem log lines (dev#592 root cause fix, kept here).
setlocal
set "HERE=%~dp0"
set "TCL_LIBRARY=%HERE%res\\python_embed\\tcl\\tcl8.6"
set "TK_LIBRARY=%HERE%res\\python_embed\\tcl\\tk8.6"
start "" "%HERE%res\\python_embed\\pythonw.exe" -E -X utf8 "%HERE%res\\app\\main.py"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
"""

BAT_TEMPLATE_CONSOLE = """@echo off
rem dev#532 WP-B1/D1 generated entry point (non-PE launcher).
rem --console build: console window stays visible, no output redirection.
rem -E: ignore PYTHON*-prefixed environment variables (isolation, dev#532 D1).
setlocal
set "HERE=%~dp0"
set "TCL_LIBRARY=%HERE%res\\python_embed\\tcl\\tcl8.6"
set "TK_LIBRARY=%HERE%res\\python_embed\\tcl\\tk8.6"
"%HERE%res\\python_embed\\python.exe" -E "%HERE%res\\app\\main.py"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
"""

# dev#532コメント列: マニュアルHTMLは同梱しない。READMEにオンラインURLを記載する。
MANUAL_URL_JA = "https://dl.osakishokai.com/manual"
MANUAL_URL_EN = "https://dl.osakishokai.com/manual/en"

README_TEMPLATE = f"""Uchinoko for Palworld
=====================

Double-click Uchinoko.bat to start.

Manual (online, not bundled in this zip):
  Japanese: {MANUAL_URL_JA}
  English:  {MANUAL_URL_EN}

Folder layout:
  Uchinoko.bat   - entry point
  README.txt     - this file
  res\\           - everything else (Python runtime, app code, pipeline, assets)
  res\\logs\\      - launch.log appears here after the first run
  res\\licenses\\  - license texts (this app + bundled third-party components)

License documents are under res\\licenses\\.
"""


def assemble_payload(out_dir: Path, cache_dir: Path, fixture: bool, console: bool) -> None:
    if out_dir.exists():
        # dev#642: out_dir can contain a prior run's res\work\_shared_cache\live_template\
        # (intentionally read-only locked by vp_core.lock_cache_dir_readonly, e.g. when
        # .devonly\HumanTest\make_humantest.bat staged this same out_dir and then ran a
        # real conversion through it). A plain shutil.rmtree hits PermissionError
        # (WinError 5) on those files; rmtree_robust clears the read-only bit and retries.
        vp_core.rmtree_robust(out_dir)
    out_dir.mkdir(parents=True)
    res_dir = out_dir / "res"
    res_dir.mkdir()

    embed_zip = ensure_embeddable_zip(cache_dir)
    tkinter_bundle = ensure_tkinter_bundle(cache_dir)

    python_embed_dir = res_dir / "python_embed"
    log(f"assembling: extracting embeddable python into {python_embed_dir}")
    _extract_embeddable(embed_zip, python_embed_dir)
    log("assembling: overlaying tkinter bundle")
    _overlay_tkinter(python_embed_dir, tkinter_bundle)

    _copy_app_sources(res_dir, fixture)
    _copy_pipeline_and_unity(res_dir, fixture)
    if not fixture:
        _copy_assets(res_dir, python_embed_dir)
    _copy_licenses(res_dir, python_embed_dir, tkinter_bundle)
    if not fixture:
        _clean_residue(res_dir)

    bat_text = BAT_TEMPLATE_CONSOLE if console else BAT_TEMPLATE_HIDDEN
    (out_dir / "Uchinoko.bat").write_text(bat_text, encoding="utf-8")
    (out_dir / "README.txt").write_text(README_TEMPLATE, encoding="utf-8")
    log(f"assembling: payload written to {out_dir}")


ALLOWED_ROOT_ENTRIES = {"Uchinoko.bat", "README.txt", "res"}


def verify_root_layout(out_dir: Path) -> tuple[bool, list[str]]:
    entries = sorted(p.name for p in out_dir.iterdir())
    ok = set(entries) == ALLOWED_ROOT_ENTRIES
    return ok, entries


# dev#532 D1: 環境隔離ゲート。「bat は %~dp0 相対のみ(裸のpython参照禁止)+
# -E + TCL_LIBRARY/TK_LIBRARY明示上書き。._pth 内容を出荷ゲートで機械照合」
# (dev#532コメント列の拘束条件)を機械的にチェックする。負の対照は
# packaging\tests\test_check_signatures.py と対になる
# packaging\tests\test_build_gates.py 側で取る(壊すとFAILすることの確認)。
_BAT_REQUIRED_SUBSTRINGS = (
    "%~dp0",        # HERE=%~dp0 の形。裸のpython参照(PATH依存)を許さない。
    " -E ",         # PYTHON*環境変数の無視(環境隔離)。
    "TCL_LIBRARY",
    "TK_LIBRARY",
)
# 「裸のpython参照」の具体的な禁止パターン: python_embed\ を経由しないpython(w).exe
# への言及(例: 単に `python.exe ...` とだけ書かれている行、PATH依存で不定)。
# コメント行(rem ...)は説明文でpython(w).exeという単語を含みうるため対象外にする。
_BARE_PYTHON_RE = re.compile(r"\bpython(w)?\.exe\b", re.IGNORECASE)


def gate_bat_isolation(bat_path: Path) -> tuple[bool, list[str]]:
    """Uchinoko.bat の環境隔離3点(%~dp0相対のみ/-E/TCL_LIBRARY・TK_LIBRARY明示
    上書き)をgrepで機械照合する。戻り値は(ok, problems)。"""
    problems: list[str] = []
    if not bat_path.is_file():
        return False, [f"bat not found: {bat_path}"]
    text = bat_path.read_text(encoding="utf-8", errors="replace")
    for needle in _BAT_REQUIRED_SUBSTRINGS:
        if needle not in text:
            problems.append(f"missing required token: {needle!r}")
    # 「%HERE%res\python_embed\...」を経由しないpython(w).exeへの実行行が
    # あれば禁止(PATH上のどのpythonが呼ばれるか不定になる=環境隔離の破れ)。
    # コメント行(rem)と、既にpython_embedへの言及を含む行は対象外。
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("rem "):
            continue
        if "python_embed" in line:
            continue
        if _BARE_PYTHON_RE.search(line):
            problems.append(f"bare python(w).exe reference outside python_embed (line {lineno}): {line.strip()!r}")
    return (len(problems) == 0), problems


def gate_pth_content(python_embed_dir: Path) -> tuple[bool, list[str]]:
    """python3xx._pth の内容照合。embeddable Pythonが sys.path に
    `.`(res\\python_embed直下、tkinter/_tkinter.pydを含む)を確実に含むこと、
    かつ pip 等の実行時ネットワークインストール経路を暗黙に有効化する
    `import site` の非コメント化(=有効化)がされていないこと(dev#532コメント列
    「実行時pip禁止」)を検査する。"""
    problems: list[str] = []
    pth_files = sorted(python_embed_dir.glob("python3*._pth"))
    if not pth_files:
        return False, [f"no python3*._pth found under {python_embed_dir}"]
    pth = pth_files[0]
    lines = pth.read_text(encoding="utf-8").splitlines()
    stripped = [ln.strip() for ln in lines]
    if "." not in stripped:
        problems.append(f"{pth.name}: missing bare '.' entry (app/tkinter DLLs would not resolve)")
    for ln in stripped:
        if ln == "import site":
            problems.append(
                f"{pth.name}: 'import site' is active (uncommented) -- this would allow a "
                "user-site/PYTHONPATH escape from the pinned embeddable runtime"
            )
    return (len(problems) == 0), problems


# dev#593: the fixture app (packaging\_fixture\app\main.py) prints this
# marker on success. Used below to judge pass/fail for the async (hidden)
# template, since that bat's own exit code no longer reflects the launched
# app's outcome (see self_test_bat).
_FIXTURE_SUCCESS_MARKER = "TK_OK"


def self_test_bat(out_dir: Path) -> int:
    bat = out_dir / "Uchinoko.bat"
    bat_text = bat.read_text(encoding="utf-8", errors="replace")
    # dev#593: the hidden template now launches pythonw.exe asynchronously
    # via `start ""` and returns before that process necessarily finishes;
    # the console template is unaffected (still synchronous, no redirection,
    # main.py finds a real console and never touches launch.log). Detect
    # which one we're testing so the two need different pass/fail logic.
    is_async_launch = 'start "" "' in bat_text

    log(f"self-test: running {bat}")
    proc = subprocess.run(["cmd", "/c", str(bat)], cwd=str(out_dir), timeout=60)
    log_file = out_dir / "res" / "logs" / "launch.log"

    if is_async_launch:
        # dev#593: bat has already returned, but the pythonw.exe child it
        # started with `start ""` may still be running/writing. Poll for
        # launch.log to appear and stop growing (Start-Sleep-equivalent
        # synchronous polling per WP dev#593 instructions), capped so a
        # stuck fixture app cannot hang the build forever.
        poll_deadline = time.monotonic() + 30.0
        last_size = -1
        stable_since: float | None = None
        while time.monotonic() < poll_deadline:
            if log_file.exists():
                size = log_file.stat().st_size
                if size > 0 and size == last_size:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 1.0:
                        break
                else:
                    stable_since = None
                last_size = size
            time.sleep(0.5)

    if log_file.exists():
        log("self-test: launch.log contents:")
        text = log_file.read_text(encoding="utf-8", errors="replace")
        print(text)
        if is_async_launch:
            # dev#593: `start ""`'s own exit code (in proc.returncode) says
            # nothing about whether the launched app succeeded, so judge
            # pass/fail from the fixture's own success marker in the log
            # instead.
            rc = 0 if _FIXTURE_SUCCESS_MARKER in text else 1
            log(
                f"self-test: async launch -- judging pass/fail from launch.log "
                f"content ({_FIXTURE_SUCCESS_MARKER} found={rc == 0}) instead of "
                f"bat exit code (bat exit code was {proc.returncode})"
            )
            return rc
    elif is_async_launch:
        # dev#593: for the async template, `start ""` having exited 0 only
        # means cmd.exe *launched* pythonw.exe successfully -- it is not
        # evidence the app itself ran or wrote anything. If launch.log never
        # appeared within the poll window above, that is itself a failure
        # signal (the app crashed before/without reaching its own log setup,
        # or never started), so do NOT fall through to trusting bat's exit
        # code here the way the (unaffected) console-template branch below
        # still does.
        log(
            "self-test: no launch.log appeared within the poll window -- "
            "treating as FAIL (bat's own exit code cannot vouch for the "
            "launched app under the async `start \"\"` template)"
        )
        return 1
    else:
        log("self-test: no launch.log found (console build, or crash before log setup)")
    log(f"self-test: exit code = {proc.returncode}")
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=None, help=f"Output payload directory (default: {DEFAULT_OUT_DIR}).")
    parser.add_argument(
        "--stage-dir",
        type=Path,
        default=None,
        help=(
            "dev#628: alias for --out. Assembles the unzipped payload "
            "(Uchinoko.bat/README.txt/res\\) directly at this directory and stops "
            "(no zip is ever produced by this script regardless of which of "
            "--out/--stage-dir is used). Mutually exclusive with --out."
        ),
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_DIR, help="Download/build cache directory.")
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Use the packaging\\_fixture stub app instead of app_py\\ (needed until WP-A1 lands).",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep the console visible (python.exe, no redirection) instead of the default hidden pythonw.exe + log file.",
    )
    parser.add_argument(
        "--no-self-test",
        action="store_true",
        help="Skip running the generated bat after assembly (self-test only ever runs automatically with --fixture).",
    )
    args = parser.parse_args(argv)
    # dev#628: --stage-dir is just --out under a different name (see module
    # docstring). Reject both being given explicitly (ambiguous which output
    # directory wins); otherwise fold --stage-dir into args.out and fall back
    # to the historical default when neither was given, so the no-flags and
    # --out-only code paths below are byte-for-byte what they were before
    # this WP (negative control: omitting --stage-dir must not change output).
    if args.out is not None and args.stage_dir is not None:
        parser.error("--out と --stage-dir は同時指定できません(どちらも出力先ディレクトリの指定のため)")
    if args.stage_dir is not None:
        args.out = args.stage_dir
        log(f"stage-dir mode: assembling payload directly to {args.out} (no zip; dev#628)")
    if args.out is None:
        args.out = DEFAULT_OUT_DIR
    # Resolve to absolute paths up front: self_test_bat() below runs the
    # generated bat with cwd=out_dir, which would otherwise double-apply a
    # relative --out (bug found and fixed during this WP's own --console
    # test run: a relative --out made the self-test invoke a
    # nonexistent doubly-relative bat path and fail with exit code 1).
    args.out = args.out.resolve()
    args.cache = args.cache.resolve()

    args.cache.mkdir(parents=True, exist_ok=True)
    assemble_payload(args.out, args.cache, fixture=args.fixture, console=args.console)

    ok_layout, entries = verify_root_layout(args.out)
    print(f"ROOT_ENTRIES={entries}")
    print("ROOT_LAYOUT=PASS" if ok_layout else "ROOT_LAYOUT=FAIL")

    self_made_names = check_signatures.DEFAULT_SELF_MADE_NAMES
    rows, sig_gate_pass = check_signatures.classify(args.out / "res", self_made_names)
    report_path = args.out.parent / "signature_report.txt"
    check_signatures.write_report(rows, report_path, self_made_names)
    self_made_count = sum(1 for r in rows if r.self_made_name_match)
    print(f"TOTAL_PE_FILES={len(rows)}")
    print(f"SELF_MADE_PE_COUNT={self_made_count}")
    print("SIGNATURE_GATE=PASS" if sig_gate_pass else "SIGNATURE_GATE=FAIL")
    print(f"signature report: {report_path}")

    bat_ok, bat_problems = gate_bat_isolation(args.out / "Uchinoko.bat")
    print("BAT_ISOLATION_GATE=PASS" if bat_ok else "BAT_ISOLATION_GATE=FAIL")
    for p in bat_problems:
        print(f"  BAT_ISOLATION_PROBLEM: {p}")

    pth_ok, pth_problems = gate_pth_content(args.out / "res" / "python_embed")
    print("PTH_GATE=PASS" if pth_ok else "PTH_GATE=FAIL")
    for p in pth_problems:
        print(f"  PTH_PROBLEM: {p}")

    overall_ok = (
        ok_layout and sig_gate_pass and self_made_count == 0 and bat_ok and pth_ok
    )

    if args.fixture and not args.no_self_test:
        rc = self_test_bat(args.out)
        print(f"SELF_TEST_EXITCODE={rc}")
        overall_ok = overall_ok and rc == 0

    print("BUILD=PASS" if overall_ok else "BUILD=FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
