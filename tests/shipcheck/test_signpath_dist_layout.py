# -*- coding: utf-8 -*-
"""SignPath対応(2026-07-31): 配布物レイアウトのフラット化(ランチャー廃止)の検査。

背景: 配布物のAV誤検知(Mark-of-the-Web付与済み実測で、ランチャーだけが白黒
くじ引き)を受け、`build\\make_dist.ps1` はもうルート用ランチャーexeを作らない。
配布zipのルート直下に本体exe一式をそのまま置く(旧: `_internal\\`という1階層の
入れ子に本体一式を畳み、ルートには起動ラッパーだけを置いていた)。

この試験は2段構成:
  1. `check_dist_layout()`(純関数、I/Oなし)の単体表。合成した良/悪のzipエントリ
     一覧で正の対照+3つの負の対照を検査する(devtools\\u28_zip_audit.py・
     tests\\shipcheck\\test_u28_zip_audit.pyと同じ「合成エントリ一覧」の手口)。
  2. 実際に `build\\make_dist.ps1` を実行して配布zipを作り、その実物へ
     `check_dist_layout()` を適用する統合テスト(受入ゲート「配布物にランチャー
     exeが含まれない」「エントリポイントが期待の位置にある」の本体)。
     pyooz/python3.dll等のビルド前提が無い環境ではskipする(make_dist.ps1自体が
     それらを必須としているため、無い環境では他の配布物テストと同様に検証不能)。

pytestからも `python tests/shipcheck/test_signpath_dist_layout.py` からも実行できる。
"""
import os
import re
import subprocess
import sys
import tempfile
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
MAKE_DIST_PS1 = os.path.join(REPO_ROOT, "build", "make_dist.ps1")
MAIN_SRC = os.path.join(REPO_ROOT, "app", "DiveToPalworld.cs")
STAGE = "Uchinoko_for_Palworld"   # build\make_dist.ps1の$Stageフォルダ名(v2.0.0改名)


# ---------------------------------------------------------------------------
# 純関数: 配布物レイアウトの検査ロジック(I/Oなし、zipのnamelist()相当を受け取る)
# ---------------------------------------------------------------------------

def check_dist_layout(names, stage_root=STAGE):
    """zip内エントリ名の一覧(namelist()相当)が、ランチャー廃止後の期待レイアウトを
    満たすかを検査する。戻り値: (ok: bool, problems: list[str])。

    検査項目:
      a. どのエントリにも"_internal"というパスセグメントが含まれない
         (旧レイアウトの入れ子が復活していないこと)。
      b. 配布物全体に.exeがちょうど1個だけ存在する(ランチャー+本体の2exe構成に
         戻っていないこと)。
      c. そのexeは stage_root 直下(1階層のみ)にあり、名前は "Uchinoko.exe"
         (=配布物の唯一のエントリポイント)。
      d. stage_root/pipeline/cli/convert.ps1 が存在する(エントリポイントの直接の
         兄弟としてpipeline\が来ている、という旧来のappRoot相対解決の前提が
         新レイアウトでも成立していることの確認)。
    """
    problems = []
    norm = [n.replace("\\", "/").strip("/") for n in names]

    internal_hits = [n for n in norm if "_internal" in n.split("/")]
    if internal_hits:
        problems.append(
            "_internalというパスセグメントを含むエントリが残っている(旧U50レイアウトの"
            "入れ子が復活している疑い): %s" % internal_hits[:5])

    all_exes = [n for n in norm if n.endswith(".exe")]
    if len(all_exes) != 1:
        problems.append(
            "配布物全体の.exe総数が1ではない(ランチャー+本体の2exe構成に戻っている"
            "疑い): %s" % all_exes)
    else:
        exe = all_exes[0]
        prefix = stage_root + "/"
        if not exe.startswith(prefix) or exe[len(prefix):].count("/") != 0:
            problems.append(
                "唯一の.exeが配布物ルート直下(1階層)にない(エントリポイントの位置が"
                "期待とズレている): %s" % exe)
        elif os.path.basename(exe) != "Uchinoko.exe":
            problems.append("配布物ルート直下のexe名がUchinoko.exeではない: %s" % exe)

    expected_convert = stage_root + "/pipeline/cli/convert.ps1"
    if expected_convert not in norm:
        problems.append(
            "%s が見つからない(エントリポイントの直接の兄弟としてpipeline\\が"
            "無い)" % expected_convert)

    return (len(problems) == 0, problems)


# ---------------------------------------------------------------------------
# 1. 単体表(正の対照 + 3つの負の対照)
# ---------------------------------------------------------------------------

def _flat_good_entries():
    """新レイアウト(ランチャー廃止後)の最小構成。正の対照。"""
    return [
        STAGE + "/README.md",
        STAGE + "/manual.html",
        STAGE + "/LICENSE",
        STAGE + "/THIRD_PARTY_LICENSES.txt",
        STAGE + "/Uchinoko.exe",
        STAGE + "/pipeline/cli/convert.ps1",
        STAGE + "/pipeline/py/vp_core.py",
        STAGE + "/unity/DiveToPalworldExporter.cs",
        STAGE + "/assets/third_party/dummy.zip",
    ]


def test_check_dist_layout_accepts_new_flat_layout():
    ok, problems = check_dist_layout(_flat_good_entries())
    assert ok, "新レイアウトの最小構成がFAILした: " + "; ".join(problems)


def test_check_dist_layout_rejects_old_internal_nesting():
    """負の対照①: 旧U50レイアウト(_internal\\へ本体一式+ルートにランチャー)は
    落ちること。"""
    old_style_entries = [
        STAGE + "/README.md",
        STAGE + "/manual.html",
        STAGE + "/Uchinoko.exe",             # ルート起動ラッパー(旧ランチャー)
        STAGE + "/_internal/Uchinoko.exe",   # 本体exe
        STAGE + "/_internal/LICENSE",
        STAGE + "/_internal/pipeline/cli/convert.ps1",
    ]
    ok, problems = check_dist_layout(old_style_entries)
    assert not ok, "旧_internal入れ子レイアウトがPASSしてしまった(検査が効いていない)"
    assert any("_internal" in p for p in problems), (
        "_internal混入を理由とする指摘が無い: " + "; ".join(problems))


def test_check_dist_layout_rejects_two_exes():
    """負の対照②: _internal\\が無くても、exeが2個(ランチャー+本体相当)ある構成は
    落ちること(2exe構成そのものへの回帰を検出する)。"""
    two_exe_entries = _flat_good_entries() + [STAGE + "/LauncherRevival.exe"]
    ok, problems = check_dist_layout(two_exe_entries)
    assert not ok, "2exe構成がPASSしてしまった(検査が効いていない)"
    assert any(".exe" in p for p in problems), (
        "exe個数不一致を理由とする指摘が無い: " + "; ".join(problems))


def test_check_dist_layout_rejects_missing_convert_ps1():
    """負の対照③: エントリポイントの直接の兄弟にpipeline\\cli\\convert.ps1が
    無い構成は落ちること。"""
    entries = [e for e in _flat_good_entries() if not e.endswith("convert.ps1")]
    ok, problems = check_dist_layout(entries)
    assert not ok, "convert.ps1欠落構成がPASSしてしまった(検査が効いていない)"
    assert any("convert.ps1" in p for p in problems), (
        "convert.ps1欠落を理由とする指摘が無い: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# 2. 統合テスト: 実際にmake_dist.ps1でzipを作り、実物を検査する
# ---------------------------------------------------------------------------

def _tool_version():
    with open(MAIN_SRC, encoding="utf-8-sig") as f:
        src = f.read()
    m = re.search(r'const\s+string\s+ToolVersion\s*=\s*"([^"]+)"', src)
    assert m, "ToolVersion定数が見つからない"
    return m.group(1)


def _build_prereqs_missing():
    """make_dist.ps1が必須とする前提(pwsh/csc.exe/ooz.pyd/python3.dll)のうち
    無いものを列挙する(1つでもあればビルドできない=このテストをskipする)。"""
    missing = []
    if not _which("pwsh"):
        missing.append("pwsh")
    csc = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                        "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")
    if not os.path.isfile(csc):
        missing.append("csc.exe")
    ooz = os.path.join(os.environ.get("APPDATA", ""), "Python", "Python313",
                        "site-packages", "ooz.pyd")
    if not os.path.isfile(ooz):
        missing.append("ooz.pyd (pip install pyooz)")
    py3dll = os.environ.get("D2P_PYTHON311_DLL") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python311", "python3.dll")
    if not os.path.isfile(py3dll):
        missing.append("python3.dll (Python 3.11)")
    return missing


def _which(cmd):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, cmd)
        for ext in ("", ".exe", ".cmd", ".bat"):
            if os.path.isfile(cand + ext):
                return cand + ext
    return None


@pytest.fixture(scope="module")
def built_dist_zip():
    missing = _build_prereqs_missing()
    if missing:
        pytest.skip("配布物ビルドの前提が無い環境: " + ", ".join(missing))
    version = _tool_version()
    out_dir = tempfile.mkdtemp(prefix="d2p_signpath_dist_layout_")
    suffix = "_layouttest"
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-File", MAKE_DIST_PS1, "-Version", version, "-Suffix", suffix],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )
    zip_path = os.path.join(REPO_ROOT, "dist",
                             "Uchinoko_for_Palworld_{}_full{}.zip".format(version, suffix))
    if proc.returncode != 0 or not os.path.isfile(zip_path):
        pytest.fail("build\\make_dist.ps1 の実行に失敗した:\nrc={}\n{}".format(
            proc.returncode, (proc.stdout or "") + (proc.stderr or "")))
    try:
        yield zip_path
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass


def test_real_dist_zip_has_no_launcher_and_correct_entrypoint(built_dist_zip):
    with zipfile.ZipFile(built_dist_zip) as zf:
        names = zf.namelist()
    ok, problems = check_dist_layout(names)
    assert ok, "実際のmake_dist.ps1出力がレイアウト検査に落ちた: " + "; ".join(problems)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
