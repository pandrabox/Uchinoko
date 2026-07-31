# -*- coding: utf-8 -*-
r"""**負の対照**: わざと壊したらゲートが落ちることの確認。

2026-07-25 に「テストは通るが実際は壊れている」事故が3件見つかっている:
  * 設定フリップの期待差分カテゴリが死んだ経路を指しており、
    実際に描画される158ファイルが全部壊れてもゲートが通った
  * `force_two_sided` のフリップが既定値と同値で、差分ゼロ=検査になっていなかった
  * `shadow_lift` がそもそも実機に届いていなかった(no-op)のに誰も気づかなかった

したがって「通ったから良し」は根拠にならない。**各ゲートについて、
故意に壊した入力を食わせて FAIL することを確認する**のが本ファイルの役目。

実変換・実機・実 pak を必要としない(モックのみ)。ただし末尾の
`test_real_pak_*` だけは、リポジトリに既存の pak があれば実データで検証する
(無ければ SKIP)。

    python -m pytest tests\coverage\selftest -q
"""
import glob
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
COVERAGE_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(os.path.dirname(COVERAGE_DIR))
if COVERAGE_DIR not in sys.path:
    sys.path.insert(0, COVERAGE_DIR)

import probes  # noqa: E402
import matrix  # noqa: E402


# ---------------------------------------------------------------------------
# モックの世界: 「生きている参照集合」と pak エントリハッシュを手で作る
# ---------------------------------------------------------------------------

LIVE_MI = {
    "Player/Outfit/SK_A/v01/MI_A_v01_M01.uasset",
    "Player/Outfit/SK_A/v01/MI_A_v01_M01.uexp",
}
LIVE_MESH = {
    "Player/Outfit/SK_A/SK_A.uasset",
    "Player/Outfit/SK_A/SK_A.uexp",
}
DEAD = {
    # 実測: pak 内 ModelMaterials/MainShader は16件しかなく、M_VP_* は
    # どの SK からも参照されていない。旧 shipcheck が期待していた場所そのもの。
    "Player/ModelMaterials/MainShader/M_VP_m00.uasset",
    "Player/ModelMaterials/MainShader/M_VP_m00.uexp",
}
EXCLUDED_ONLY_MI = {
    "Player/Outfit/SK_Player_Female_Outfit_Yakushima001/v01/MI_Y_M01.uasset",
    "Player/Outfit/SK_Player_Female_Outfit_Yakushima001/v01/MI_Y_M01.uexp",
}

ALL_ENTRIES = LIVE_MI | LIVE_MESH | DEAD | EXCLUDED_ONLY_MI | {"Player/Body/x.uasset"}


EXCLUDED_ONLY_PACKAGES = {
    "/Game/Pal/Model/Character/Player/Outfit/"
    "SK_Player_Male_Outfit_Yakushima001/MI_Player_Male_Outfit_Yakushima001_M01",
}


def fake_live(_pak):
    return {
        "mesh_entries": set(LIVE_MESH),
        "material_entries": set(LIVE_MI),
        "excluded_entries": set(),
        "excluded_only_material_entries": set(EXCLUDED_ONLY_MI),
        "excluded_only_material_packages": set(EXCLUDED_ONLY_PACKAGES),
        "dead_entries": set(DEAD),
        "n_sk": 1, "n_excluded_sk": 1, "n_live_mi_paths": 1,
        "skipped": [], "n_entries": len(ALL_ENTRIES),
    }


def hasher_factory(changed):
    """`changed` に入れたエントリだけハッシュが変わる2つの pak を作る。"""
    base = {p: "aaaa" for p in ALL_ENTRIES}
    flip = dict(base)
    for p in changed:
        flip[p] = "bbbb"
    table = {"BASE": base, "FLIP": flip}

    def _h(pak_path, use_cache=True):
        return table[pak_path]
    return _h


def _run(changed, kind="material"):
    return probes.gate_live_diff("t", "BASE", "FLIP", kind=kind,
                                 hasher=hasher_factory(changed), live_fn=fake_live)


# --- gate_live_diff --------------------------------------------------------

def test_live_diff_passes_when_live_material_changed():
    """正の対照: 生きた MI が変われば PASS。"""
    r = _run(LIVE_MI, kind="material")
    assert r.status == "PASS", r.detail
    assert r.detail["n_live_hits"] == 2


def test_live_diff_fails_when_nothing_changed():
    """負の対照①: 差分ゼロ(設定が配線されていない)→ FAIL。

    `force_two_sided` を既定値と同値でフリップしていた事故の形。
    """
    r = _run(set(), kind="material")
    assert r.status == "FAIL", r.detail
    assert "差分ゼロ" in r.detail.get("note", "")


def test_live_diff_fails_when_only_dead_path_changed():
    """負の対照②【本命】: 死んだ経路(M_VP_*)だけが変わった → FAIL。

    **これが 2026-07-25 の事故そのもの。**旧 shipcheck の
    `expected_diff_categories=["ModelMaterials/MainShader/"]` は
    この入力を PASS と判定していた。
    """
    r = _run(DEAD, kind="material")
    assert r.status == "FAIL", r.detail
    assert r.detail["dead_only"] is True
    assert r.detail["n_live_hits"] == 0
    assert r.detail["n_dead_hits"] == 2

    # 参考: 旧方式(パス部分文字列の一致)なら通ってしまうことを明示しておく
    assert any("ModelMaterials/MainShader/" in p for p in r.detail["diff_sample"])


def test_live_diff_fails_when_wrong_kind_changed():
    """負の対照③: メッシュしか変わっていないのに material を期待 → FAIL。

    「影の濃さを変えたらジオメトリだけ変わった」= 明らかに配線が違う。
    """
    r = _run(LIVE_MESH, kind="material")
    assert r.status == "FAIL", r.detail
    r2 = _run(LIVE_MI, kind="mesh")
    assert r2.status == "FAIL", r2.detail


def test_live_diff_any_kind_accepts_either():
    assert _run(LIVE_MESH, kind="any").status == "PASS"
    assert _run(LIVE_MI, kind="any").status == "PASS"
    assert _run(DEAD, kind="any").status == "FAIL"


def test_live_diff_skips_when_live_set_empty():
    """生きた参照集合が取れなかったら PASS ではなく SKIP(判定不能)。"""
    def empty_live(_p):
        d = fake_live(_p)
        d["material_entries"] = set()
        return d
    r = probes.gate_live_diff("t", "BASE", "FLIP", kind="material",
                              hasher=hasher_factory(DEAD), live_fn=empty_live)
    assert r.status == "SKIP", r.detail


# --- gate_exclusions_untouched ---------------------------------------------

def test_exclusions_pass_when_untouched():
    r = probes.gate_exclusions_untouched("t", "BASE", "FLIP",
                                         hasher=hasher_factory(LIVE_MI),
                                         live_fn=fake_live)
    assert r.status == "PASS", r.detail


def test_exclusions_fail_when_collab_mi_modified():
    """負の対照: コラボ除外SK固有の MI が動いたら FAIL(除外が効いていない)。"""
    r = probes.gate_exclusions_untouched("t", "BASE", "FLIP",
                                         hasher=hasher_factory(EXCLUDED_ONLY_MI),
                                         live_fn=fake_live)
    assert r.status == "FAIL", r.detail
    assert r.detail["n_diff"] == 2


def test_exclusions_pass_when_collab_mi_not_shipped_at_all():
    """**実測(2026-07-26)がこの形**: 除外SK固有の MI は6パッケージあるが
    pak には1件も収録されていない = MOD が触っていない → PASS。

    以前はここを SKIP にしていたが、「触っていない」は判定不能ではなく合格。
    """
    def not_shipped(_p):
        d = fake_live(_p)
        d["excluded_only_material_entries"] = set()   # pak に無い
        return d                                      # packages は残る
    r = probes.gate_exclusions_untouched("t", "BASE", "FLIP",
                                         hasher=hasher_factory(LIVE_MI),
                                         live_fn=not_shipped)
    assert r.status == "PASS", r.detail
    assert r.detail["n_excluded_only_mi_in_pak"] == 0
    assert r.detail["n_excluded_only_mi_packages"] == 1


def test_exclusions_skip_when_no_exclusive_mi():
    """除外SKの参照MIがすべて非除外SKと共有 → この観点では判定できない(SKIP)。

    **黙って PASS にしないこと**が要点。共有MIは統一の対象になるので
    「触られていない」とは言えない。
    """
    def no_excl(_p):
        d = fake_live(_p)
        d["excluded_only_material_entries"] = set()
        d["excluded_only_material_packages"] = set()
        return d
    r = probes.gate_exclusions_untouched("t", "BASE", "FLIP",
                                         hasher=hasher_factory(LIVE_MI),
                                         live_fn=no_excl)
    assert r.status == "SKIP", r.detail


def test_exclusions_skip_when_no_excluded_sk_present():
    """pak に除外SKが1体も無ければ判定不能(SKIP)。"""
    def no_sk(_p):
        d = fake_live(_p)
        d["n_excluded_sk"] = 0
        return d
    r = probes.gate_exclusions_untouched("t", "BASE", "FLIP",
                                         hasher=hasher_factory(LIVE_MI),
                                         live_fn=no_sk)
    assert r.status == "SKIP", r.detail


# --- preflight ゲート --------------------------------------------------------
# 2026-07-26 実測の本物の preflight 出力(work\u53_cov の flip_baseline ビルド)。
# **12件出る**(G1〜G11 + G5b)。shipcheck の gate C は `total == 9` を要求するので
# この健全なログを FAIL と判定してしまう。
REAL_PREFLIGHT_LOG = "\n".join([
    "  [PASS] G1 マウントポイント — ../../../Pal/Content/Pal/Model/Character/",
    "  [PASS] G2 全エントリのパスがバニラと一致(平坦化なし) — 883件OK",
    "  [PASS] G3 禁止物ゼロ(Skeleton/Body/Physics/ubulk、素体MI 4パスのみ例外許可)",
    "  [PASS] G4 収録数(衣装/頭/髪/頭装備/マテリアル/テクスチャ)",
    "  [PASS] G5 バインド回転差の検査対象カバレッジ(構造健全性) — 58/58体検証",
    "  [PASS] G5b メッシュのボーン集合⊆バニラ — 全ボーン一致",
    "  [PASS] G6 参照の閉包性(宙ぶらりん参照なし)",
    "  [PASS] G7 シェーダーSM5+SM6 — log=True 最大=350KB",
    "  [PASS] G8 テクスチャ実体(NeverStream焼き込み) — 最小=2731KB / 2枚",
    "  [PASS] G9 マテリアルにGPUSkinシェーダー — 全マテリアルOK",
    "  [PASS] G10 ライブpakの全SKが対象一覧に含まれる — バニラ全221SK収録済み",
    "  [PASS] G11 全衣装SKの全描画スロットが注入アトラスt00を指す — NG 0/58 SK",
])


def test_preflight_gate_passes_on_real_healthy_log():
    """正の対照: 実測の健全な preflight ログ(12件)で PASS。"""
    r = probes.gate_preflight("t", REAL_PREFLIGHT_LOG)
    assert r.status == "PASS", r.detail
    assert r.detail["n_pass"] == 12


def test_shipcheck_gate_c_is_stale():
    """**旧ゲートが健全なビルドを FAIL にする**ことの実証(退行の記録)。

    `tests\\shipcheck\\gates.py::gate_c_preflight_from_log` は
    `ok = total == 9` と件数を固定している。preflight に G10/G11 が
    足された(2026-07-25, 7ac3d7b)ので、この条件はもう成立しない。
    """
    import gates as shipcheck_gates
    old = shipcheck_gates.gate_c_preflight_from_log(REAL_PREFLIGHT_LOG)
    assert old.status == "FAIL", (
        "旧ゲートが通るようになった。preflight のゲート数が9件へ戻ったなら"
        "この記録は不要になる: {}".format(old.detail))
    assert old.detail["total"] == 12


@pytest.mark.parametrize("broken,why", [
    (REAL_PREFLIGHT_LOG.replace("[PASS] G3", "[FAIL] G3"), "ハードFAILが1件"),
    (REAL_PREFLIGHT_LOG.replace("[PASS] G11", "[WARN] G11"), "ソフトNG(WARN)が1件"),
    ("\n".join(REAL_PREFLIGHT_LOG.splitlines()[:4]), "途中で死んで G5〜G9 が出ていない"),
])
def test_preflight_gate_fails_when_broken(broken, why):
    """負の対照: FAIL / WARN / 途中終了のいずれでも落ちること。"""
    r = probes.gate_preflight("t", broken)
    assert r.status == "FAIL", (why, r.detail)


def test_preflight_gate_skips_when_no_preflight_ran():
    r = probes.gate_preflight("t", "=== EngineMode: noue ===\nFATAL: 変換が落ちた")
    assert r.status == "SKIP", r.detail


# --- UE 非依存 --------------------------------------------------------------

NOUE_LOG = """=== EngineMode: noue ===
=== Phase 0(noue): 参照バニラデータ準備 ===
=== Phase 2〜6(noue): build_pak_from_avatar.py 一気通貫 ===
  [PASS] G1 マウントポイント
=== 完成 ===
"""


def test_no_ue_tool_passes_on_noue_log():
    assert probes.gate_no_ue_tool_in_log("t", NOUE_LOG).status == "PASS"


@pytest.mark.parametrize("needle", [
    "  & C:\\UE_5.1\\Engine\\Binaries\\Win64\\UnrealPak.exe out.pak -Create=list",
    "  & UnrealEditor-Cmd.exe Pal.uproject -run=pythonscript",
    "  RunUAT.bat BuildCookRun -project=...",
])
def test_no_ue_tool_fails_when_ue_invoked(needle):
    """負の対照: UE ツールの起動行が1行でもあれば FAIL。"""
    r = probes.gate_no_ue_tool_in_log("t", NOUE_LOG + needle + "\n")
    assert r.status == "FAIL", r.detail
    assert r.detail["found"]


def test_engine_mode_gate():
    assert probes.gate_engine_mode_is_noue("t", NOUE_LOG).status == "PASS"
    bad = NOUE_LOG.replace("EngineMode: noue", "EngineMode: ue")
    assert probes.gate_engine_mode_is_noue("t", bad).status == "FAIL"
    assert probes.gate_engine_mode_is_noue("t", "何も無い").status == "SKIP"


# --- 入力形式 ---------------------------------------------------------------

class _FakeBuild:
    def __init__(self, exit_code, pak_path):
        self.exit_code = exit_code
        self.pak_path = pak_path


def test_input_format_gate(tmp_path):
    pak = tmp_path / "x.pak"
    pak.write_bytes(b"x")
    ok = probes.gate_input_format_accepted(
        "t", {"vrm_path": "a.vrm"}, _FakeBuild(0, str(pak)))
    assert ok.status == "PASS"

    # 負の対照: 変換が落ちた / pak が無い / 未対応拡張子
    assert probes.gate_input_format_accepted(
        "t", {"vrm_path": "a.vrm"}, _FakeBuild(1, str(pak))).status == "FAIL"
    assert probes.gate_input_format_accepted(
        "t", {"vrm_path": "a.fbx"}, _FakeBuild(0, None)).status == "FAIL"
    assert probes.gate_input_format_accepted(
        "t", {"vrm_path": "a.prefab"}, _FakeBuild(0, str(pak))).status == "SKIP"


# --- 補助関数 ---------------------------------------------------------------

def test_game_path_to_pak_rels():
    got = probes.game_path_to_pak_rels(
        "/Game/Pal/Model/Character/Player/Outfit/SK_A/v01/MI_A_M01")
    assert got == ["Player/Outfit/SK_A/v01/MI_A_M01.uasset",
                   "Player/Outfit/SK_A/v01/MI_A_M01.uexp"]
    assert probes.game_path_to_pak_rels("/Game/SomethingElse/X") == []


def test_pick_drop_bone_candidate():
    assert probes.pick_drop_bone_candidate(
        ["Hips", "Spine", "Head", "Hand.L", "Thumb Proximal.L"]) is None
    assert probes.pick_drop_bone_candidate(
        ["Hips", "Spine", "skirt_01", "Head"]) == "skirt_01"


def test_avatar_texture_profile_on_real_vrm():
    """検体表の枚数が実物と合っていること(実 VRM を読むが変換はしない)。"""
    for key in ("vrm_kate", "vrm_alicia051", "vrm_sample_b"):
        spec = matrix.SPECIMENS[key]
        if not os.path.isfile(spec["path"]):
            pytest.skip("検体が無い: {}".format(spec["path"]))
        prof = probes.avatar_texture_profile(spec["path"])
        assert prof["n_images"] == spec["n_images"], (key, prof)
        assert prof["n_materials"] == spec["n_materials"], (key, prof)


# ---------------------------------------------------------------------------
# 実データでの検証(pak があるときだけ)
# ---------------------------------------------------------------------------

def _any_existing_pak():
    hits = sorted(glob.glob(os.path.join(REPO_ROOT, "work", "*", "build",
                                          "*_PlayerSwap_P.pak")))
    # 責任者が使用中の work\flatVer2\ は読まない
    hits = [h for h in hits if os.sep + "flatVer2" + os.sep not in h]
    return hits[0] if hits else None


def test_real_pak_live_reference_extraction():
    r"""**モックでは証明できない部分**: 実 pak から「生きた参照集合」を
    本当に取り出せるか。

    合格条件:
      * 生きた MI エントリが1件以上ある
      * `ModelMaterials/MainShader/M_VP_*` が **dead 側に分類される**
        (= 旧 shipcheck の期待パスが死んでいたことの実データによる裏付け)
    """
    pak = _any_existing_pak()
    if not pak:
        pytest.skip("既存の pak が無い(実データ検証はできない)")
    live = probes.live_reference_sets(pak)
    assert live["material_entries"], live
    assert live["mesh_entries"], live
    mvp = {e for e in live["dead_entries"] if "/M_VP_" in e}
    assert mvp, ("M_VP_* が dead に分類されていない。"
                 "参照解決が想定と違う可能性がある: {}".format(
                     sorted(live["dead_entries"])[:10]))
    # 生きた MI は M_VP_* ではない(=旧期待パスとは別物)
    assert not any("/M_VP_" in e for e in live["material_entries"])


def test_real_pak_old_expectation_would_have_passed_on_dead_path():
    r"""実データで、**旧方式なら通ってしまう**ことを示す。

    旧 `gate_h1_wiring` は「差分パスに `ModelMaterials/MainShader/` が
    含まれれば PASS」だった。M_VP_* だけが変わった差分でも条件を満たす。
    新ゲートは同じ入力で FAIL する。
    """
    pak = _any_existing_pak()
    if not pak:
        pytest.skip("既存の pak が無い")
    live = probes.live_reference_sets(pak)
    dead_mvp = sorted(e for e in live["dead_entries"] if "/M_VP_" in e)
    assert dead_mvp

    # 旧方式の判定を再現
    old_categories = ["ModelMaterials/MainShader/"]
    assert any(cat in p for p in dead_mvp for cat in old_categories), \
        "旧期待カテゴリが M_VP_* に一致しない(前提が変わった)"

    # 新方式は同じ差分を FAIL にする
    def _live(_p):
        return live

    def _h(name, use_cache=True):
        base = {e: "a" for e in
                live["material_entries"] | live["mesh_entries"] | live["dead_entries"]}
        if name == "BASE":
            return base
        flip = dict(base)
        for e in dead_mvp:
            flip[e] = "b"
        return flip

    r = probes.gate_live_diff("t", "BASE", "FLIP", kind="material",
                              hasher=_h, live_fn=_live)
    assert r.status == "FAIL", r.detail
    assert r.detail["dead_only"] is True
