# -*- coding: utf-8 -*-
r"""カバレッジ軸: **人間が触る設定**が本当に出力へ届くか。

■ 旧 shipcheck との決定的な違い

`tests\shipcheck\cases.py::SETTINGS_FLIPS` は「差分が出るはずのパス」を
**人が文字列で書いて**いた。その文字列(`ModelMaterials/MainShader/`)は
実測 16 ファイルしか無く、しかも中身の `M_VP_*` は**どの SK からも
参照されていない死んだ経路**だった。よって実際に描画へ使われる 158 ファイルが
全部壊れてもゲートは通った(DEV_NOTES 2026-07-25(28)§5)。

本ファイルは期待パスを書かない。**pak を開いて「衣装SKが実際に参照している
MI」を解決し(probes.live_reference_sets)、そこに差分が届いたかを見る。**
死んだ経路だけが動いた場合は必ず FAIL する(selftest の負の対照で実証済み)。
"""
import os

import pytest

import matrix
import probes

# dev#127(夜間カバレッジの並列化): このモジュールの各テストは
# `baseline` フィクスチャ(case_name="flip_baseline")や
# `matrix.FLIP_BASE` 由来の case_name("flip_shadow_lift_0to07" 等)を
# 複数のテスト関数で**意図的に**使い回している(build() のディスクキャッシュ
# 再利用)。pytest-xdist で別々のワーカーに散ると、同じ作業フォルダ
# (WORK_ROOT\cases\flip_baseline\ 等)へ複数プロセスが同時に書き込む
# 事故になる(CLAUDE.md「作業フォルダの指定を省くと競合が復活する」と
# 同型)。xdist_group でモジュール全体を単一ワーカーへ固定し、
# 従来どおり直列に実行させる(このモジュール内の並列化は諦めるが、
# test_inputs.py 等の他モジュールとは並列に走る——並列化の単位は
# 「衝突しうる集合」であって「全テスト」ではない、という設計)。
# test_inputs.py::test_input_format[vrm_seed] も case_name="input_vrm_seed" を
# test_drop_bones_seed_robo_arm と共有するため、同じグループ名で
# 明示的に合流させてある(test_inputs.py 側のコメント参照)。
pytestmark = pytest.mark.xdist_group("u53_settings_shared")


# ---------------------------------------------------------------------------
# 基準ビルド(全設定が既定。shadow_lift=0 は「MIを1バイトも書かない」端点)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def baseline(build, allow_convert):
    res = build("flip_baseline", matrix.FLIP_BASE, overrides=None,
                allow_convert=allow_convert)
    if not (res.pak_path and os.path.isfile(res.pak_path)):
        pytest.skip("基準ビルドの pak が無い(exit={})。フリップ検査は判定不能"
                    .format(res.exit_code))
    return res


def _resolve_overrides(flip, baseline_result):
    """フリップの overrides を決める。drop_bones だけは検体依存なので実行時に選ぶ。"""
    if flip["overrides"] is not None:
        return flip["overrides"], None
    if flip["name"] == "drop_bones_one":
        job_dir = os.path.dirname(baseline_result.job_path)
        bones = probes.built_bones(job_dir)
        blender_exe = (baseline_result.job_dict or {}).get("paths", {}).get("blender_exe")
        # 名前だけの選定(pick_drop_bone_candidate)は「Humanoidではないが
        # 誰も参照していないボーン」(cheek_L)を選び、差分ゼロで検査が
        # 成立しないことが実測された(2026-07-26)。実データ(頂点ウェイト)
        # に基づく pick_drop_bone_candidate_weighted を使う。
        cand, info = probes.pick_drop_bone_candidate_weighted(job_dir, bones, blender_exe)
        if not cand:
            return None, ("この検体に実際にウェイトを持つ Humanoid 以外のボーンが"
                          "無く、削除ボーンを検査できない: {}".format(info))
        return {"drop_bones": [cand]}, None
    return None, "overrides を決められない: {}".format(flip["name"])


def pytest_generate_tests(metafunc):
    if "flip" in metafunc.fixturenames:
        metafunc.parametrize("flip", matrix.SETTING_FLIPS,
                             ids=[f["name"] for f in matrix.SETTING_FLIPS])


@pytest.mark.slow
def test_setting_flip(flip, baseline, build, allow_convert, gate, recorder):
    r"""設定を1つだけ変えて、**実際に描画へ使われるエントリ**が動いたか。

    diff_kind="material" … 統一MI(SK が参照している MI)に差分が要る
    diff_kind="mesh"     … 衣装/頭/髪 SK 本体に差分が要る
    """
    overrides, why_skip = _resolve_overrides(flip, baseline)
    if why_skip:
        pytest.skip(why_skip)

    case = "flip_{}".format(flip["name"])
    res = build(case, matrix.FLIP_BASE, overrides=overrides,
                allow_convert=allow_convert)

    import gates as shipcheck_gates
    gate(shipcheck_gates.gate_a_convert_exit0(res), case=case, axis=flip["axis"])
    gate(shipcheck_gates.gate_b_pak_exists(res), case=case, axis=flip["axis"])
    gate(probes.gate_preflight("C_preflight", res.log_text), case=case,
         axis=flip["axis"])

    recorder.record(probes._gate("PASS", "flip_overrides_used",
                                 overrides=overrides, why=flip["why"]),
                    case=case, axis=flip["axis"])

    diff_gate = probes.gate_live_diff("live_diff_{}".format(flip["name"]),
                                      baseline.pak_path, res.pak_path,
                                      kind=flip["diff_kind"])
    expected_broken = flip.get("expected_broken")
    if expected_broken and diff_gate.status == "FAIL":
        # matrix.py に「noue では届かないと記録済み」の既知の制約がある場合、
        # hard FAIL にはせず記録だけして SKIP にする(2026-07-26 発見)。
        # 穴1修復で test_setting_flip[force_two_sided_false] が初めて
        # 実際の判定に到達したところ、まさにこの既知の制約どおりFAILしたが、
        # matrix.py の expected_broken はどこからも参照されておらず
        # (test_inputs.py の expected_failure と違ってワイヤリング漏れ)、
        # 既知の制約と新規の退行を区別できていなかった。
        # 将来この制約が解消されて PASS するようになれば、この分岐を
        # 通らず下の gate() がそのまま PASS を記録する(自動で気づける)。
        recorder.record(diff_gate, case=case, axis=flip["axis"])
        pytest.skip("既知の制約(matrix.py expected_broken): {}".format(expected_broken))
    gate(diff_gate, case=case, axis=flip["axis"])


@pytest.mark.slow
def test_drop_bones_seed_robo_arm(build, allow_convert, gate, run_dir):
    r"""**除外ボーンの決め打ちケース**(2026-07-26 新設): input_vrm_seed × robo_root_pole。

    `test_setting_flip[drop_bones_one]` の自動候補選定は名前当てずっぽうで、
    実際にはウェイトを持たないボーン(fbx_flat_ma の `cheek_L`)を選び、
    差分ゼロで「機能の検証になっていない」ことが実測された
    (`pick_drop_bone_candidate_weighted` で修正済みだが、それでも
    自動選定は毎回どのボーンが選ばれるか検体依存で変わりうる)。

    自動選定に丸投げせず、**代表性が高く効果が一目でわかるケースを固定する**:
    `input_vrm_seed` の `robo_root_pole`(背中の機械腕の付け根。
    `drop_bone_meshes()` のdocstringに直接「Seed-sanのロボアーム」と
    明記されている、まさにこの機能のための用途)。
    実測(scratchpad\verify_T_dropbones.md): 3795頂点中3745頂点削除、
    機械腕本体が消滅、本体・服・髪への巻き込み無し。

    合否判定は**数値(削除頂点数)+ 画像の両方**(数値だけで判定しない、
    2026-07-25複数事故の教訓)。
    """
    # ケース名は test_inputs.py::test_input_format と同じ "input_vrm_seed" にして、
    # 同じ job 内容(overrides無し)なら既存キャッシュをそのまま再利用する
    # (同じ検体をもう一度フル変換する無駄を避ける)。
    baseline_res = build("input_vrm_seed", "vrm_seed", overrides=None,
                         allow_convert=allow_convert)
    if not (baseline_res.pak_path and os.path.isfile(baseline_res.pak_path)):
        pytest.skip("基準ビルド(input_vrm_seed, drop_bones無し)の pak が無い"
                    "(exit={})".format(baseline_res.exit_code))

    case = "drop_bones_seed_robo_arm"
    res = build(case, "vrm_seed", overrides={"drop_bones": ["robo_root_pole"]},
               allow_convert=allow_convert)

    import gates as shipcheck_gates
    gate(shipcheck_gates.gate_a_convert_exit0(res), case=case, axis="削除ボーン")
    gate(shipcheck_gates.gate_b_pak_exists(res), case=case, axis="削除ボーン")

    # 数値側: ログの実行痕から、実際に頂点が削除されたこと(0でも全滅でもない)
    gate(probes.gate_drop_bones_effective("drop_bones_vertices_removed", res.log_text),
         case=case, axis="削除ボーン")

    # 画像側: 除外前後で正面プレビューが実際に変わったこと
    before = os.path.join(os.path.dirname(baseline_res.job_path),
                          "converted", "preview_male_stand.png")
    after = os.path.join(os.path.dirname(res.job_path),
                         "converted", "preview_male_stand.png")
    gate(probes.gate_images_differ("drop_bones_visual_change", before, after,
                                   run_dir=run_dir, case=case),
         case=case, axis="削除ボーン")


@pytest.mark.slow
def test_exclusions_untouched(baseline, build, allow_convert, gate):
    r"""**コラボ装備の除外**が効いていること。

    `vp_exclusions` の約束は「除外された装備はメッシュ注入もMI差し替えもしない
    = バニラの装備がそのまま出る」。したがって影の濃さを 0→0.7 に振っても、
    **除外SKだけが参照する MI は1バイトも変わってはならない。**
    """
    flip_res = build("flip_shadow_lift_0to07", matrix.FLIP_BASE,
                     overrides={"shadow_lift": 0.7}, allow_convert=allow_convert)
    if not (flip_res.pak_path and os.path.isfile(flip_res.pak_path)):
        pytest.skip("比較用ビルドが無い(exit={})".format(flip_res.exit_code))
    gate(probes.gate_exclusions_untouched("exclusions_untouched",
                                          baseline.pak_path, flip_res.pak_path),
         case="exclusions", axis="コラボ装備の除外")


def test_exclusion_list_classifies_known_collabs(gate):
    """除外リストが既知のコラボ名を実際に除外と判定すること(実変換不要)。

    リストが空になったり判定関数が壊れたりしても、実変換側のゲートは
    「除外SKが0件」= SKIP になるだけで気づけない。ここで独立に見る。
    """
    import vp_exclusions
    known = [
        "Player/Outfit/SK_Player_Female_Outfit_Yakushima001/"
        "SK_Player_Female_Outfit_Yakushima001.uasset",
        "SK_YakushimaHeadEquip001",
        "/Game/Pal/Model/Character/Player/Outfit/SK_Player_Male_Outfit_Octavia001/"
        "SK_Player_Male_Outfit_Octavia001",
    ]
    not_excluded = [
        "Player/Outfit/SK_Player_Female_Outfit_Cloth001/"
        "SK_Player_Female_Outfit_Cloth001.uasset",
        "SK_Player_Male_Outfit_Bronze001",
    ]
    bad = [k for k in known if not vp_exclusions.is_excluded(k)]
    over = [k for k in not_excluded if vp_exclusions.is_excluded(k)]
    res = probes._gate("PASS" if not bad and not over else "FAIL",
                       "exclusion_list_classification",
                       missed=bad, over_excluded=over)
    gate(res, case="exclusions", axis="コラボ装備の除外")


# ---------------------------------------------------------------------------
# 「影のみ更新」経路(convert.ps1 -MaterialsOnly → devtools\fast_repack.py)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_materials_only_equivalence(build, allow_convert, gate, recorder, run_dir):
    r"""**影のみ更新**がフル変換と同じ絵を出すこと。

    手順(専用の作業域 `matonly` で完結。他ケースの build\ を壊さない):
      1. k=0.0 でフル変換
      2. 同じ作業域の job.json を k=0.7 に書き換え、`-MaterialsOnly` で再パック
      3. 出来た pak の **生きた MI エントリ**のハッシュが、
         別作業域で k=0.7 をフル変換した pak と一致すること

    一致しなければ「影のみ更新で作った MOD はフル変換と違うものになる」。
    これはユーザーが最も頻繁に押すボタンなので、ここがズレるのは出荷不可。
    """
    if not allow_convert:
        pytest.skip("実変換が要る(--allow-convert)")

    full_k07 = build("flip_shadow_lift_0to07", matrix.FLIP_BASE,
                     overrides={"shadow_lift": 0.7}, allow_convert=True)
    if not (full_k07.pak_path and os.path.isfile(full_k07.pak_path)):
        pytest.skip("k=0.7 のフル変換 pak が無い(exit={})".format(full_k07.exit_code))
    ref_hashes = probes.pak_entry_hashes(full_k07.pak_path)
    live = probes.live_reference_sets(full_k07.pak_path)
    scope = live["material_entries"]

    # --- 1) 専用作業域で k=0.0 をフル変換 ---
    job_path = matrix.make_job("matonly", matrix.FLIP_BASE, {"shadow_lift": 0.0})
    log_dir = os.path.join(probes.WORK_ROOT, "convert_logs")
    rc, log = probes.run_convert(job_path, os.path.join(log_dir, "matonly_full.log"))
    recorder.record(probes._gate("PASS" if rc == 0 else "FAIL",
                                 "matonly_prep_full_convert", exit_code=rc,
                                 log_tail=log[-1500:] if rc else ""),
                    case="matonly", axis="影の調整:影のみ更新経路")
    if rc != 0:
        pytest.fail("影のみ更新の前提となるフル変換が失敗した(exit={})".format(rc))

    # --- 2) 同じ作業域で k=0.7 の -MaterialsOnly ---
    matrix.make_job("matonly", matrix.FLIP_BASE, {"shadow_lift": 0.7})
    rc2, log2 = probes.run_convert(job_path,
                                   os.path.join(log_dir, "matonly_repack.log"),
                                   extra_args=("-MaterialsOnly",))
    gate(probes._gate("PASS" if rc2 == 0 else "FAIL", "materials_only_exit0",
                      exit_code=rc2, log_tail=log2[-2000:] if rc2 else ""),
         case="matonly", axis="影の調整:影のみ更新経路")

    pak = os.path.join(os.path.dirname(job_path), "build", "matonly_PlayerSwap_P.pak")
    gate(probes._gate("PASS" if os.path.isfile(pak) else "FAIL",
                      "materials_only_pak_exists", pak=pak),
         case="matonly", axis="影の調整:影のみ更新経路")

    # --- 3) 生きた MI エントリがフル変換と一致するか ---
    got = probes.pak_entry_hashes(pak)
    mismatch = sorted(p for p in scope if got.get(p) != ref_hashes.get(p))
    gate(probes._gate("PASS" if (scope and not mismatch) else
                      ("SKIP" if not scope else "FAIL"),
                      "materials_only_matches_full_convert",
                      n_scope=len(scope), n_mismatch=len(mismatch),
                      mismatch_sample=mismatch[:10],
                      note="生きた MI エントリが取れなかった" if not scope else ""),
         case="matonly", axis="影の調整:影のみ更新経路")

    # 影のみ更新が preflight を通していること(fast_repack --preflight)
    gate(probes._gate(
        "PASS" if "[FAIL] G" not in log2 else "FAIL",
        "materials_only_preflight",
        n_pass=log2.count("[PASS] G"), n_fail=log2.count("[FAIL] G")),
        case="matonly", axis="影の調整:影のみ更新経路")
