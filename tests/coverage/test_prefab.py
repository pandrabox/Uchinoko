# -*- coding: utf-8 -*-
r"""カバレッジ軸: **入力形式 .prefab** と **MA(Modular Avatar)対応**。

DEV_NOTES(29)§5 で

    | **prefab** | **無し** | ✘ **検体が無い** |
    | **MA対応** | ベイク済み輸出物のみ | △ **部分。Unity実行が要る** |

と申告していた2行を埋めるためのモジュール(2026-07-26、責任者から検体4体を受領)。

------------------------------------------------------------------------
■ この軸だけ構造が違う

VRM / FBX 検体は「ファイル → convert.ps1 → pak」の1段だが、prefab は2段ある::

    .prefab ──(Unity ヘッドレス + NDMF ベイク)──> FBX + humanoid.json
            ──(convert.ps1)──> pak

前段で **MA が適用される**。したがって「MA 対応」の実体は前段にあり、
既存の `fbx_flat_ma` 検体は**その前段の出力を拾っているだけ**で、
前段自体は一度も自動検査されていなかった。

■ 安全弁が1つ多い(`--allow-unity`)

前段は Unity を起動する。しかも **他人の Unity プロジェクトへ書き込む**:
  * `Assets\Editor\DiveToPalworldExporter.cs` を複製する(冪等)
  * FBX Exporter 未導入なら `Packages\manifest.json` へ追記する
さらに **Unity でそのプロジェクトを開いていると起動できない**(二重起動禁止)。
検査が勝手にやってよい範囲を越えるので、既定 OFF の別スイッチにしてある。

■ 静的検査は常に走る

`--allow-unity` 無しでも、検体の実在・Unity プロジェクトの解決・NDMF の導入・
**同名衝突**は判定できる。ここを「検体が無いので SKIP」で流さないのが要点。
------------------------------------------------------------------------
"""
import os

import pytest

import matrix
import probes

# dev#127(夜間カバレッジの並列化): test_prefab_end_to_end と
# test_same_name_prefabs_produce_different_paks は同じ case_name
# (prefab_flatver2_agyo / prefab_flatver2_jinbe)を意図的に使い回す
# (キャッシュされたビルド結果を突き合わせるだけ、との設計。本ファイル内
# 各所のコメント参照)。pytest-xdist で別ワーカーに散ると同じ作業フォルダへ
# 複数プロセスが同時に書き込む事故になるため、モジュール全体を単一
# ワーカーへ固定する。既定(--allow-unity 無し)ではこのモジュールの
# slow/unity テストは build() を1回も呼ばず即 SKIP するため実害は無いが、
# --allow-unity 指定時のために安全側で常時グルーピングしておく
# (test_settings.py と同じ設計判断)。
pytestmark = pytest.mark.xdist_group("u53_prefab_shared")


def pytest_generate_tests(metafunc):
    if "prefab_specimen" in metafunc.fixturenames:
        names = list(matrix.PREFAB_SPECIMENS)
        metafunc.parametrize("prefab_specimen", names, ids=names)


# ---------------------------------------------------------------------------
# 静的検査(Unity 不要 = 既定モードでも走る)
# ---------------------------------------------------------------------------

def test_prefab_specimen_inventory(prefab_specimen, gate):
    """prefab 検体が実在し、Unity プロジェクトが逆算できること。

    `export_from_unity.ps1` は prefab から `Assets` の親を遡ってプロジェクトを
    決める。Assets 配下に無い prefab を渡すと輸出は必ず失敗するので、
    **Unity を起動する前に**ここで落とす。
    """
    spec = matrix.PREFAB_SPECIMENS[prefab_specimen]
    path = spec["path"]
    exists = os.path.isfile(path)
    proj = matrix.prefab_unity_project(path) if exists else None
    ver_file = os.path.join(proj, "ProjectSettings", "ProjectVersion.txt") if proj else None
    ver = None
    if ver_file and os.path.isfile(ver_file):
        with open(ver_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "m_EditorVersion:" in line:
                    ver = line.split(":", 1)[1].strip()
                    break
    ok = bool(exists and proj and ver)
    gate(probes._gate("PASS" if ok else "FAIL", "prefab_specimen_exists",
                      path=path, exists=exists, unity_project=proj,
                      editor_version=ver, why=spec["why"],
                      note=("prefab が Assets 配下に無い、または "
                            "ProjectSettings\\ProjectVersion.txt が無い"
                            if not ok else "")),
         case=prefab_specimen, axis="入力形式:prefab")


def test_prefab_project_has_ma(prefab_specimen, gate):
    r"""検体の Unity プロジェクトに MA(と NDMF)が導入されていること。

    NDMF が無いと `DiveToPalworldExporter.BakeNdmf` は例外を投げず
    `D2P: NDMF未導入のためベイクをスキップ` と書いて素通りする。
    つまり **MA 検体のつもりで MA を通っていない**輸出物ができあがる。
    そのすり抜けを起こしうる構成かどうかを、起動前に静的に見る。
    """
    spec = matrix.PREFAB_SPECIMENS[prefab_specimen]
    proj = matrix.prefab_unity_project(spec["path"])
    if not proj:
        pytest.skip("Unity プロジェクトが解決できない(inventory 側で FAIL 済み)")
    pkg_dir = os.path.join(proj, "Packages")
    installed = sorted(os.listdir(pkg_dir)) if os.path.isdir(pkg_dir) else []
    need = ["nadena.dev.modular-avatar", "nadena.dev.ndmf"]
    missing = [n for n in need if n not in installed]
    gate(probes._gate("PASS" if not missing else "FAIL", "prefab_project_has_ma",
                      unity_project=proj, missing=missing,
                      installed=[p for p in installed if not p.endswith(".json")],
                      expects_bake=spec.get("ma_expected", True)),
         case=prefab_specimen, axis="MA(Modular Avatar)対応")


def test_prefab_name_collision(gate):
    r"""**同名 prefab は同じ出力先・同じ作業域を指す**(責任者指定の試験)。

    `C:\UnityP\Agyo\Assets\flatVer2.prefab` と
    `C:\UnityP\Jinbe\Assets\flatVer2.prefab` は**別物**(1.5MB と 190KB)。
    しかし出力先を決めているのは**ファイル名だけ**:

      * `export_from_unity.ps1:79-80` … `work\<prefab名>_export`
      * `app\DiveToPalworld.cs:982`   … 同じ規則で GUI も組み立てる

    したがって素直に2体続けて輸出すると、後の1体が前の1体を上書きする。
    **さらに悪いことに、その衝突先 `work\flatVer2_export` は既存検体
    `fbx_flat_ma` の実体そのもの**(matrix.FLAT_EXPORT_DIR)であり、
    検査が検体を壊す形になる。

    このテストは「衝突しないこと」を要求しない(実装がそうなっていないため)。
    要求するのは **衝突の事実が記録に残ること**と、
    **本スイートがその既定を使っていないこと**の2点。
    """
    findings = collision_findings()

    # **本スイートが既定の出力先を使っていないこと**が合否。
    # 「衝突しないこと」を合否にはしない(実装は衝突する。既知の欠陥として
    # test_prefab_collision_is_declared が毎回申告する)。
    # ここで見るのは、検査が検体を壊さない構造になっているか。
    uses_default = os.path.normcase(probes.EXPORTS_DIR).startswith(
        os.path.normcase(os.path.join(matrix.REPO_ROOT, "work", "u53_cov")))
    clobbers = os.path.normcase(probes.EXPORTS_DIR) == os.path.normcase(
        matrix.FLAT_EXPORT_DIR)
    gate(probes._gate("PASS" if (uses_default and not clobbers) else "FAIL",
                      "prefab_export_isolated_from_default",
                      suite_export_dir=probes.EXPORTS_DIR,
                      default_would_be=[matrix.prefab_default_export_dir(s["path"])
                                        for s in matrix.PREFAB_SPECIMENS.values()],
                      existing_specimen_dir=matrix.FLAT_EXPORT_DIR,
                      collisions=findings,
                      note=("本スイートは -Out を明示してケース別ディレクトリへ出す。"
                            "既定に任せると同名 prefab 同士が衝突し、かつ既存検体 "
                            "work\\flatVer2_export を上書きする")),
         case="prefab_collision", axis="入力形式:prefab(同名衝突)")


def collision_findings():
    r"""検体表のうち、既定の `-Out` が衝突する組み合わせを算出する。

    テストの実行順に依存しないよう、状態を持たず毎回数え直す。
    """
    groups = {}
    for name, spec in matrix.PREFAB_SPECIMENS.items():
        g = spec.get("collision_group")
        if g:
            groups.setdefault(g, []).append((name, spec["path"]))

    findings = []
    for g, members in groups.items():
        paths = dict(members)
        outs = {}
        for name, path in members:
            outs.setdefault(matrix.prefab_default_export_dir(path), []).append(name)
        for out_dir, names in outs.items():
            if len(names) > 1:
                findings.append({
                    "group": g, "shared_default_out": out_dir, "specimens": names,
                    "sizes": {n: (os.path.getsize(paths[n])
                                  if os.path.isfile(paths[n]) else None)
                              for n in names},
                    "also_clobbers_existing_specimen":
                        os.path.normcase(out_dir) == os.path.normcase(
                            matrix.FLAT_EXPORT_DIR),
                })
    return findings


def test_prefab_collision_is_declared(recorder):
    """同名衝突の実在を、実行のたびに明示的に申告する。

    「衝突する実装のままである」ことを毎回目に入れるための記録であって、
    合否ではない(直ったら findings が空になり、この行は PASS へ変わる)。
    """
    findings = collision_findings()
    recorder.record(probes._gate(
        "SKIP" if findings else "PASS",
        "prefab_default_out_collides",
        findings=findings,
        note=("既定の出力先(work\\<prefab名>_export)は prefab のファイル名だけで"
              "決まるため、別プロジェクトの同名 prefab が同じ場所へ出る。"
              "GUI(DiveToPalworld.cs:982)も同じ規則。**未修正**"
              if findings else "衝突する組み合わせが検体表に無い")),
        case="prefab_collision", axis="入力形式:prefab(同名衝突)")


def test_prefab_path_wiring(gate):
    r"""GUI → export_from_unity.ps1 → Exporter の経路が存在すること。

    (旧 `test_inputs.py::test_prefab_path_static` をこちらへ移した。
    検体がある今も、**配線が消えていないこと**の退行検知としては有効。)
    """
    repo = matrix.REPO_ROOT
    parts = {
        "GUI が .prefab を受ける": (os.path.join(repo, "app", "DiveToPalworld.cs"), ".prefab"),
        "Unity ヘッドレス輸出スクリプト": (
            os.path.join(repo, "pipeline", "cli", "export_from_unity.ps1"), "-Prefab"),
        "Unity 側 Exporter": (
            os.path.join(repo, "unity", "DiveToPalworldExporter.cs"), "humanoid"),
        "Exporter が NDMF ベイクを呼ぶ": (
            os.path.join(repo, "unity", "DiveToPalworldExporter.cs"),
            "nadena.dev.ndmf.AvatarProcessor"),
    }
    missing = []
    for label, (path, needle) in parts.items():
        if not os.path.isfile(path):
            missing.append((label, "ファイルが無い", path))
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            if needle.lower() not in f.read().lower():
                missing.append((label, "目印 '{}' が無い".format(needle), path))
    gate(probes._gate("PASS" if not missing else "FAIL", "prefab_path_exists",
                      missing=missing, checked=sorted(parts)),
         case="prefab_static", axis="入力形式:prefab")


# ---------------------------------------------------------------------------
# 端から端まで(Unity 輸出 → 変換 → pak)。--allow-unity + --allow-convert が要る
# ---------------------------------------------------------------------------

@pytest.mark.unity
@pytest.mark.slow
def test_prefab_end_to_end(prefab_specimen, unity_export, build, allow_convert,
                           gate, recorder):
    r"""**prefab を投げたら pak が出る**ことを、1体まるごと通して確かめる。

    段:
      1. Unity ヘッドレス輸出(MA/NDMF ベイク込み)→ FBX + humanoid.json
      2. **ベイクが実際に走ったか**を unity_export.log の実行痕で判定
      3. その FBX を通常の変換へ投入 → ゲート A(exit0)/B(pak)/C(preflight)/D(UE非依存)

    2 を入れてあるのが肝。1 と 3 だけだと「MA が素通りしていても全部 PASS」になる
    ——DEV_NOTES(29)§4 で4件踏んだのと同じ形。
    """
    import gates as shipcheck_gates

    spec = matrix.PREFAB_SPECIMENS[prefab_specimen]
    case = prefab_specimen   # 検体キーがすでに prefab_ 始まり

    rc, stdout, unity_log, out_dir = unity_export(case, prefab_specimen)

    gate(probes.gate_unity_export("unity_export", rc, stdout, unity_log, out_dir),
         case=case, axis="入力形式:prefab")
    gate(probes.gate_ma_bake_executed("ma_bake_executed", unity_log,
                                      expected=spec.get("ma_expected", True)),
         case=case, axis="MA(Modular Avatar)対応")

    fbx = sorted(f for f in os.listdir(out_dir) if f.lower().endswith(".fbx"))
    fbx_path = os.path.join(out_dir, fbx[0])
    humanoid = os.path.join(out_dir, "humanoid.json")

    res = build(case, prefab_specimen, allow_convert=allow_convert,
                path_override=fbx_path, humanoid_override=humanoid)

    gate(shipcheck_gates.gate_a_convert_exit0(res), case=case, axis="入力形式:prefab")
    gate(shipcheck_gates.gate_b_pak_exists(res), case=case, axis="入力形式:prefab")
    gate(probes.gate_preflight("C_preflight", res.log_text), case=case,
         axis="入力形式:prefab")
    gate(shipcheck_gates.gate_d_noue_provenance(res.build_dir), case=case,
         axis="UE非依存")

    # アトラス化 前後の見た目(パッチ単位NCC、2026-07-26新設)。
    # 既知の限界: prefab_flatver2_agyo のような bindポーズ自体のズレは
    # パッキング前後で同じように壊れるため、このゲートでは検出できない。
    job_dir = os.path.dirname(res.job_path)
    blender_exe = (res.job_dict or {}).get("paths", {}).get("blender_exe")
    gate(probes.gate_atlas_patch_ncc("atlas_patch_ncc", job_dir, blender_exe),
         case=case, axis="入力形式:prefab")


@pytest.mark.unity
@pytest.mark.slow
def test_same_name_prefabs_produce_different_paks(build, allow_convert, gate):
    r"""**同名 prefab 2体が、本当に別物として最後まで通ること。**

    Agyo / Jinbe の `flatVer2.prefab` は名前だけ同じで中身は別。
    どこか1箇所でもファイル名を鍵にしてキャッシュ・共有していれば、
    2つの pak が同一になる(= 片方が他方に化ける)。
    `test_prefab_name_collision` が静的に示した危険が、
    **本スイートの独立化で実際に回避できているか**の実測版。

    前段の輸出・変換は `test_prefab_end_to_end` が済ませているので、
    ここはキャッシュされたビルド結果を突き合わせるだけ(追加の Unity 起動なし)。
    """
    import hashlib

    group = [n for n, s in matrix.PREFAB_SPECIMENS.items()
             if s.get("collision_group") == "flatVer2"]
    if len(group) < 2:
        pytest.skip("同名グループが2体そろっていない")

    paks = {}
    for name in group:
        case = name   # 検体キーがそのままケース名(end_to_end 側と一致させること)
        out_dir = os.path.join(probes.EXPORTS_DIR, case)
        if not os.path.isdir(out_dir):
            pytest.skip("輸出物が無い({})。--allow-unity 付きで先に "
                        "test_prefab_end_to_end を通すこと".format(out_dir))
        fbx = sorted(f for f in os.listdir(out_dir) if f.lower().endswith(".fbx"))
        if not fbx:
            pytest.skip("FBX が無い: {}".format(out_dir))
        res = build(case, name, allow_convert=allow_convert,
                    path_override=os.path.join(out_dir, fbx[0]),
                    humanoid_override=os.path.join(out_dir, "humanoid.json"))
        if not (res.pak_path and os.path.isfile(res.pak_path)):
            pytest.skip("pak が無い({})。先に end_to_end が通ること".format(case))
        with open(res.pak_path, "rb") as f:
            paks[name] = (hashlib.sha1(f.read()).hexdigest(), res.pak_path)

    digests = {v[0] for v in paks.values()}
    gate(probes._gate("PASS" if len(digests) == len(paks) else "FAIL",
                      "same_name_prefabs_are_distinct",
                      paks={k: {"sha1": v[0], "path": v[1]} for k, v in paks.items()},
                      note=("pak が一致した場合、どこかがファイル名を鍵にして"
                            "成果物を共有している(片方が他方に化けている)")),
         case="prefab_collision", axis="入力形式:prefab(同名衝突)")
