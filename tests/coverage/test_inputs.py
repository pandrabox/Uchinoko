# -*- coding: utf-8 -*-
r"""カバレッジ軸: **入力形式**(.vrm / .fbx+humanoid.json / .prefab)と
**テクスチャ枚数**(アトラス行数)、**MA(Modular Avatar)対応**。

旧 `tests\shipcheck` はアバター11体を同じ経路で流すだけで、この軸が無かった。
"""
import os

import pytest

import matrix
import probes

# dev#127(夜間カバレッジの並列化): "vrm_seed" 検体は test_settings.py::
# test_drop_bones_seed_robo_arm と同じ作業域(case_name="input_vrm_seed")を
# 意図的に共有している(build() のディスクキャッシュ再利用、2026-07-26設計)。
# pytest-xdist で別ワーカーに散ると**2プロセスが同じ作業フォルダへ同時に
# 書き込む**(CLAUDE.md「作業フォルダの指定を省くと競合が復活する」と同型の
# 事故)。xdist_group で test_settings.py 側(pytestmark で同じグループ名)と
# 必ず同じワーカーへ固定する。他の検体は case_name が互いに素なので無指定
# のまま(=自由に別ワーカーへ散ってよい。これが本WPの並列化効果の本体)。
_XDIST_GROUP_SHARED_WITH_SETTINGS = "u53_settings_shared"


def pytest_generate_tests(metafunc):
    if "specimen" in metafunc.fixturenames:
        spec = metafunc.config.getoption("specimens")
        if spec == "all":
            names = list(matrix.SPECIMENS)
        elif spec == "fast":
            # 1本だけ回して配線を見るとき用(rows=1 と rows=2、FBX と VRM を1つずつ)
            names = ["vrm_kate", "fbx_flat_ma"]
        else:
            names = [s.strip() for s in spec.split(",") if s.strip()]
        params = [
            pytest.param(n, marks=pytest.mark.xdist_group(_XDIST_GROUP_SHARED_WITH_SETTINGS))
            if n == "vrm_seed" else n
            for n in names
        ]
        metafunc.parametrize("specimen", params, ids=names)


# ---------------------------------------------------------------------------
# 静的検査(実変換なしで回る = 既定モードでも価値が出る)
# ---------------------------------------------------------------------------

def test_specimen_inventory(specimen, gate, recorder):
    """検体が実在すること。**無ければ『その軸はカバーされていない』**という事実。"""
    spec = matrix.SPECIMENS[specimen]
    exists = os.path.isfile(spec["path"])
    res = probes._gate("PASS" if exists else "FAIL", "specimen_exists",
                       path=spec["path"], input_format=spec["input_format"],
                       why=spec["why"])
    gate(res, case=specimen, axis="入力形式:{}".format(
        "VRM" if spec["input_format"] == "vrm" else "FBX+humanoid.json"))


def test_texture_profile_matches_selection(specimen, gate):
    """検体表に書いたテクスチャ枚数が実物と合っていること。

    ここがズレていると「rows=3 を踏んだつもりで踏んでいない」という、
    カバレッジ表だけが正しい状態になる(今日の事故と同じ形)。
    """
    spec = matrix.SPECIMENS[specimen]
    if not os.path.isfile(spec["path"]):
        pytest.skip("検体が無い: {}".format(spec["path"]))
    if spec["input_format"] != "vrm":
        pytest.skip("VRM 以外は静的にテクスチャ枚数を数えられない")
    prof = probes.avatar_texture_profile(spec["path"])
    ok = (prof["n_images"] == spec["n_images"]
          and prof["n_materials"] == spec["n_materials"])
    res = probes._gate("PASS" if ok else "FAIL", "texture_profile_matches",
                       measured=prof, declared={"n_images": spec["n_images"],
                                                "n_materials": spec["n_materials"]})
    gate(res, case=specimen, axis="テクスチャ枚数(アトラス行数)")


def test_specimen_gaps_are_declared(gate, recorder):
    r"""**検体が無くて埋められない軸を、実行のたびに明示的に申告する。**

    「静かに PASS」は今日いちばん危険な状態(検査したつもりが検査していない)。
    したがって未カバーの軸は毎回 **SKIP として記録**され、report.md / coverage.md に
    「検体が無い」と出る。

    同時に、その申告が**実態と合っているか**も検査する。宣言と現実がズレたまま
    誰も気づかない、という腐り方を防ぐのが目的:
      * `covered: False` と宣言した軸に検体が現れていないか
      * 逆に、検体があると宣言した軸の検体が消えていないか
        (**2026-07-26 に prefab 検体4体が入ったので、後者が本番になった**)
    """
    declared_uncovered = [n for n, m in matrix.AXES.items() if m["covered"] is False]
    missing_prefabs = [(n, s["path"]) for n, s in matrix.PREFAB_SPECIMENS.items()
                       if not os.path.isfile(s["path"])]
    missing_vrm_fbx = [(n, s["path"]) for n, s in matrix.SPECIMENS.items()
                       if not os.path.isfile(s["path"])]

    recorder.record(probes._gate(
        "PASS" if not declared_uncovered else "SKIP", "uncovered_axes_declared",
        uncovered_axes=declared_uncovered,
        note=("`covered: False` の軸は無い(prefab は 2026-07-26 に検体を得て "
              "opt-in へ昇格した)" if not declared_uncovered
              else "検体が無いためこの軸は埋められない"),
    ), case="(検体なし)", axis="入力形式:prefab")

    res = probes._gate(
        "PASS" if not (missing_prefabs or missing_vrm_fbx) else "FAIL",
        "declared_specimens_exist",
        missing_prefab_specimens=missing_prefabs,
        missing_vrm_fbx_specimens=missing_vrm_fbx,
        note=("検体表に書いてあるのに実物が無いと、そのケースは静かに SKIP になり"
              "『検査したつもり』が生まれる。**検体はリポジトリ外にあるので"
              "移動・削除で簡単に消える**"))
    gate(res, case="(検体なし)", axis="入力形式:prefab")


# 入力形式 .prefab / MA(Modular Avatar)の軸は **test_prefab.py** が持つ
# (2026-07-26、責任者から検体4体を受領して独立モジュールへ分離)。
# ここに残っているのは、ベイク**済み**輸出物 flatVer2_export についての検査だけ。


def test_ma_export_artifacts(gate):
    r"""ベイク済み輸出物(`fbx_flat_ma`)が、確かに Unity 輸出経路の産物であること。

    MA ベイクの**実行**を見るのは `test_prefab.py::test_prefab_end_to_end`
    (unity_export.log の実行痕で判定)。こちらは「手元の FBX 検体の出自」を
    確かめるだけの静的検査で、Unity を起動しない既定モードでも成立する。
    """
    spec = matrix.SPECIMENS["fbx_flat_ma"]
    missing = [p for p in spec["ma_evidence"] if not os.path.isfile(p)]
    gate(probes._gate("PASS" if not missing else "FAIL", "ma_export_artifacts_present",
                      missing=missing, evidence=spec["ma_evidence"],
                      note=("この FBX 検体が Unity 輸出物であることの証拠。"
                            "**ベイクが走ったことの証拠ではない** "
                            "(それは test_prefab.py が unity_export.log で見る)")),
         case="ma_static", axis="MA(Modular Avatar)対応")


# ---------------------------------------------------------------------------
# 実変換を伴う検査(--allow-convert が要る)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_input_format(specimen, build, allow_convert, gate, recorder):
    r"""検体を1体フル変換し、A〜D + 入力形式 + アトラス行数まで見る。

    **テクスチャ枚数の軸はここで同時に埋まる**(検体を rows=1/2/3/4/6 で選んである)。
    DEV_NOTES(28)§1 の出荷ブロッカー(rows>=3 で FATAL)は当時
    `vrm_alicia051` / `vrm_vrm1` / `vrm_seed` / `vrm_sample_b` が踏んでいたが、
    dev#18(uvfix18)・dev#129で解消済み(2026-07-30実測、matrix.pyの
    vrm_alicia051エントリを参照)。
    """
    import gates as shipcheck_gates

    spec = matrix.SPECIMENS[specimen]
    axis = "入力形式:{}".format(
        "VRM" if spec["input_format"] == "vrm" else "FBX+humanoid.json")
    case = "input_{}".format(specimen)

    res = build(case, specimen, allow_convert=allow_convert)

    expected_failure = spec.get("expected_failure")
    if expected_failure:
        # **負の検体**: 通ることではなく「優雅に失敗すること」が期待値
        # (DEV_NOTES(29)§5)。正常系のゲートに掛けると FAIL が並び、
        # 本物の退行が埋もれる。ここで判定を打ち切る。
        marker = expected_failure["marker"]
        failed_as_expected = (res.exit_code != 0 and marker in (res.log_text or ""))
        gate(probes._gate("PASS" if failed_as_expected else "FAIL",
                          "graceful_failure_as_expected",
                          exit_code=res.exit_code, expected_marker=marker,
                          marker_found=marker in (res.log_text or ""),
                          why=expected_failure["why"],
                          note=("期待どおりの理由で止まること。exit 0 で通って"
                                "しまう場合も、別の理由で落ちる場合も FAIL"
                                "(前者は不正な成果物、後者は原因不明の退行)")),
             case=case, axis=axis)
        return

    gate(shipcheck_gates.gate_a_convert_exit0(res), case=case, axis=axis)
    gate(shipcheck_gates.gate_b_pak_exists(res), case=case, axis=axis)
    gate(probes.gate_preflight("C_preflight", res.log_text), case=case, axis=axis)
    gate(shipcheck_gates.gate_d_noue_provenance(res.build_dir), case=case, axis="UE非依存")
    gate(probes.gate_input_format_accepted("input_format_accepted", res.job_dict, res),
         case=case, axis=axis)

    # アトラス行数の**実測**。matrix の rows_estimate は画像枚数からの推定であって
    # 実測値ではないので、一致を要求しない(推測を判定基準にしない)。
    # 要求するのは「スロットが1つ以上ある = テクスチャ工程が成立した」ことだけ。
    # 「rows=1/2/3/4+ を本当に踏んだか」は下の test_atlas_rows_coverage が見る。
    job_dir = os.path.dirname(res.job_path)
    n_slots = probes.built_slot_count(job_dir)
    import math
    rows = int(math.ceil(math.sqrt(n_slots))) if n_slots else None
    # dev#127: 実測値はここ(rows_res、直後の gate() 経由)で gates.jsonl へ
    # 恒久的に記録される。かつてはプロセスローカルな MEASURED_ROWS 辞書にも
    # 二重で貯めていたが、pytest-xdist 環境では各 specimen が別ワーカー
    # (別プロセス)で実行されうるため、プロセスローカルな辞書は他ワーカー分を
    # 一切見えない(=集計が壊れる)。test_atlas_rows_coverage は gates.jsonl を
    # 読み直して集計する(詳細はそちらの docstring)ので、ここでの二重保持は
    # 廃止した。
    rows_res = probes._gate(
        "SKIP" if rows is None else "PASS",
        "atlas_rows_measured",
        n_slots=n_slots, rows_measured=rows, rows_estimate=spec["rows_estimate"],
        note=("avatar_meta.json が無い(変換が step01 まで届いていない)"
              if rows is None else ""))
    gate(rows_res, case=case, axis="テクスチャ枚数(アトラス行数)")

    # アトラス化 前後の見た目(パッチ単位NCC、2026-07-26新設)。
    # 「PASS 117」の裏で input_vrm_seed の胸ロゴが文字化けしていた事故を
    # 踏まえ、全体平均だけでなくパッチ最小NCCでも見た目の破損を検出する。
    # 既知の限界: パッキング前後比較なので、前後で同じ壊れ方をする破綻
    # (例: bindポーズ自体のズレ、カメラが正面を向いていない)は検出できない。
    blender_exe = (res.job_dict or {}).get("paths", {}).get("blender_exe")
    gate(probes.gate_atlas_patch_ncc("atlas_patch_ncc", job_dir, blender_exe),
         case=case, axis="テクスチャ枚数(アトラス行数)")


@pytest.mark.slow
@pytest.mark.atlas_summary
def test_atlas_rows_coverage(gate, run_dir):
    """**軸そのものの検査**: 今回の実行がアトラス行数を実際に振れたか。

    rows=1 しか踏んでいないなら「テクスチャ枚数の軸はカバーされていない」。
    DEV_NOTES(28)§1 の出荷ブロッカーは rows>=3 でしか出ないので、
    ここが 1〜2 で止まっているスイートには意味が無い。

    dev#127(夜間カバレッジの並列化): この検査は「全 specimen の実測値を
    横断集計する」性質上、`test_input_format[*]` の**全件が終わったあと**に
    走らないと正しい答えが出ない。かつてはプロセスローカルな辞書
    (MEASURED_ROWS)を直接読んでいたが、pytest-xdist 導入後は specimen ごとに
    別ワーカー(別プロセス)で実行されうるため、その方式は他ワーカー分の
    実測値が一切見えない(壊れた集計)。そこで **run_dir\\gates.jsonl を
    読み直す**方式に変更した(`report_merge.read_gate_rows`、conftest.py と
    同じ集約経路)。

    ただし gates.jsonl は「そのプロセスが自分で書いた分」しか持たない点は
    変わらないので、xdist 並列実行時にこのテスト自身が specimen 群と同じ
    セッション内で走ると、たまたま自分のワーカーが処理した specimen 分しか
    集計できない(=ワーカー間の集約は conftest.py の `pytest_sessionfinish`
    でセッション終了時にしか行われないため、セッション中はまだ未集約)。
    したがって並列実行時は `run_overnight.py` が本体フェーズ(-n 付き)を
    完走させたあと、**別プロセスとして本テストだけを単独実行**する
    (`-m atlas_summary`、-n無し)。その時点では前フェーズの
    `pytest_sessionfinish` が既に gates.jsonl を集約済みなので、
    このテストが読む内容は常に完全である。非並列実行(-n 無し)では
    そもそもワーカー分割が無いので、同一セッション内でそのまま正しく動く
    (今までと同じ経路)。
    """
    import report_merge

    rows = report_merge.read_gate_rows(run_dir)
    measured = {}
    for r in rows:
        if r.get("gate") != "atlas_rows_measured" or r.get("status") != "PASS":
            continue
        case = r.get("case") or ""
        if not case.startswith("input_"):
            continue
        specimen = case[len("input_"):]
        detail = r.get("detail") or {}
        rows_measured = detail.get("rows_measured")
        if rows_measured is not None:
            measured[specimen] = rows_measured

    rows_seen = sorted(set(measured.values()))
    res = probes._gate(
        "PASS" if (len(rows_seen) >= 3 and max(rows_seen or [0]) >= 3) else "FAIL",
        "atlas_rows_axis_swept",
        rows_measured=rows_seen, per_specimen=dict(measured),
        note="rows が3種類以上、かつ 3 以上を1回は踏んでいることを要求する")
    if not measured:
        pytest.skip("実変換が1件も走っていない(--allow-convert 未指定)")
    gate(res, case="(軸全体)", axis="テクスチャ枚数(アトラス行数)")
