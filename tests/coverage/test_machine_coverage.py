# -*- coding: utf-8 -*-
r"""実機(Palworld)を必要とするゲート。**既定で除外**。

受入条件: Palworld を必要とする検査は既定で走らないこと。二重の安全弁:
  1. `@pytest.mark.machine` … `pytest.ini` の `addopts` が `-m "not machine"` を既定にする
  2. `--allow-machine` 未指定なら、たとえマーカーで拾われても SKIP する

実行するには **両方**を明示する:
    python -m pytest tests\coverage -m machine --allow-machine --allow-convert

ゲートの中身(E: クラッシュ / F: プレイ開始)は `tests\shipcheck\gates.py` の
`gate_e_crash` / `gate_f_playstart` をそのまま再利用する(devtools\crash_test.py /
play_start_test.py を import する形も shipcheck と同じ)。

------------------------------------------------------------------------
■ 2026-07-26 追加: 全検体の実機正面撮影(test_machine_visual_*)

背景: 下の `test_machine_crash_and_play_start` は `FLIP_BASE`(machine_base、
実体は fbx_flat_ma)**1検体だけ**を対象にしていた。これは「設定フリップの
基準体が実機で生きているか」という別の軸の確認であって、**「全検体の見た目を
人間が確認できるようにする」ことは元々このテストのスコープではなかった**
(設計上の制約ではなく単純に未拡張)。しかも判定は**プロセスの生死だけ**
(gate_e_crash/gate_f_playstart はクラッシュ有無とUI到達しか見ない)。

本日、`prefab_flatver2_agyo`(素体と衣装が90度ずれる)・`input_vrm_seed`
(胸ロゴのノイズ化/腕の破綻)・`input_vrm_vrm1`(正面のはずが背面カメラ)など、
**この生死ゲートを全部PASSしながら実際には壊れている**視覚的破綻が複数見つかった。
machine_base 1検体だけのゲートではそもそも検体が違うので絶対に踏めない。

そこで `test_machine_visual_vrm_fbx` / `test_machine_visual_prefab` を追加し、
`matrix.SPECIMENS` / `matrix.PREFAB_SPECIMENS` の**全検体**を実機に立たせて
正面SSを `run_dir/shots/` へ集約する。判定は引き続き PASS/FAIL/SKIP
(クラッシュ/UI失敗/成功)の3値のみで、**見た目そのものの合否は人間が画像を
見て判断する**——このゲートの役目は「毎回、全検体の画像が同じ場所に残ること」。

キャッシュ再利用: `build()` フィクスチャの実体 `shipcheck_gates.build_or_get_cached`
は job 内容 + git HEAD でディスクキャッシュする(**セッションをまたいで有効**)。
ケース名を `test_inputs.py::test_input_format` / `test_prefab.py::test_prefab_end_to_end`
と**意図的に同じ**にしてあるので、同じ pytest 実行内で先にそれらが変換済みなら
再変換なしでヒットする。過去のセッションで `--allow-convert` 付きで一度でも
変換済みの検体も、キャッシュが有効な限り `--allow-convert` 無しで走る。

実行時間への影響(見積り): play_start_test.py 1回あたり実測 概ね60〜150秒
(起動待ち+メニュー操作+HUD検出での早期終了)。対象は VRM/FBX 6検体
(`vrm_no_texture` はメッシュ0の負の検体なので対象外)+ prefab 最大4検体
(`--allow-unity` 時のみ)= 最大10検体で**フルスイートに概ね+10〜25分**。
`--allow-machine` 自体が既定OFFの安全弁なので**既定の実行時間には無影響**。
1検体だけ確認したい場合は `test_inputs.py` と共有の `--specimens` オプション
(例 `--specimens vrm_seed,vrm_sample_b`)で絞り込める(prefab側は現状4体のみ
なので絞り込みオプションは設けていない)。

排他制御の実体(「キュー管理」の正体、2026-07-26確認): 専用のジョブキューは
存在しない。`play_start_test.py` 内蔵のファイルロック
(`work\u50_diag\queue\shoot.lock`、既定ON)が「同時に来た呼び出しを待たせて
直列化する mutex」として働く(ドキュメント曰く、当初は別ツール
`shoot_queue.py` を作る設計だったが、本体へ統合する方針に変更された)。
複数検体を回すこのテスト自身は pytest のパラメトライズが1件ずつ順に実行する
ため、このロックは「同時に別プロセスから撮影が走った場合の保険」として働く。
------------------------------------------------------------------------
"""
import contextlib
import os

import pytest

import matrix

# dev#127(夜間カバレッジの並列化): 既定(--allow-machine 無し)では
# `-m "not machine"` によりこのモジュール自体が丸ごとデセレクトされる
# (pytest_generate_tests すら実行前に除外される)ので通常時の並列実行に
# 影響は無い。
#
# --allow-machine 指定時は要注意: test_machine_visual_vrm_fbx /
# test_machine_visual_prefab は test_inputs.py / test_prefab.py と
# case_name(build() のディスクキャッシュ)を**モジュールをまたいで**
# 意図的に共有している(各テストの docstring 参照)。xdist_group は
# 「同じグループ内は同じワーカーへ固定する」機能であって、
# **別モジュール側にも同名の xdist_group を付けない限りモジュール間の
# 競合までは防げない**(test_inputs.py 側は "u53_settings_shared" という
# 別の目的のグループしか持たない)。そのため run_overnight.py は
# --Machine / --Unity 指定時は **並列実行そのものを無効化**する
# (-n を渡さない=常に直列。詳細は run_overnight.py のコメント)。
# ここでの xdist_group は「万一 run_overnight.py を介さず直接
# `pytest --allow-machine -n ...` された場合」への保険として、
# 少なくとも本モジュール内(machine_base 同士等)の競合だけは防ぐ
# ものであり、他モジュールとの競合までは解決しない。
pytestmark = [pytest.mark.machine, pytest.mark.xdist_group("u53_machine_shared")]


@pytest.fixture
def paks_dir(allow_machine):
    """Palworld の Paks ディレクトリ。--allow-machine が無ければ触らない。"""
    if not allow_machine:
        pytest.skip("実機接触には --allow-machine が要る(既定は禁止)")
    import apply_test_pak as atp
    return atp.DEFAULT_PAKS_DIR


@pytest.fixture
def pak_removed_after(allow_machine, paks_dir):
    """検査後に必ず MOD pak を撤去する(例外時も)。

    pak の適用そのものは crash_test / play_start_test が内部で行うので、
    ここでは**後片付けだけ**を保証する(二重適用を避ける)。
    """
    import apply_test_pak as atp

    @contextlib.contextmanager
    def _cm():
        try:
            yield
        finally:
            atp.cmd_remove(paks_dir)

    return _cm


@pytest.mark.slow
def test_machine_crash_and_play_start(build, allow_convert, allow_machine, gate,
                                      paks_dir, pak_removed_after, run_dir):
    """基準体の pak で、起動してクラッシュしないこと・プレイ開始まで届くこと。"""
    import gates as shipcheck_gates
    import crash_test as ct
    import play_start_test as pst

    res = build("machine_base", matrix.FLIP_BASE, overrides={"shadow_lift": 0.7},
                allow_convert=allow_convert)
    if not (res.pak_path and os.path.isfile(res.pak_path)):
        pytest.skip("pak が無い(exit={})".format(res.exit_code))

    shots = os.path.join(run_dir, "shots")
    os.makedirs(shots, exist_ok=True)

    with pak_removed_after():
        gate(shipcheck_gates.gate_e_crash(ct, res.pak_path, paks_dir,
                                          wait_seconds=40),
             case="machine_base", axis="実機:クラッシュ/プレイ開始/見た目")
        gate(shipcheck_gates.gate_f_playstart(pst, res.pak_path, repeat=1,
                                              shot_dir=shots),
             case="machine_base", axis="実機:クラッシュ/プレイ開始/見た目")


# ---------------------------------------------------------------------------
# 全検体 実機正面撮影(2026-07-26 追加。モジュール冒頭docstring参照)
# ---------------------------------------------------------------------------
# 本日の修正/発見の優先順(責任者指定)を先頭へ。残りは matrix 登場順のまま。
_MACHINE_VRM_FBX_ORDER = [
    "vrm_seed", "vrm_sample_b", "vrm_vrm1",
] + [k for k in matrix.SPECIMENS
     if k not in ("vrm_seed", "vrm_sample_b", "vrm_vrm1", "vrm_no_texture")]
# vrm_no_texture(メッシュ0の負の検体、matrix.py の expected_failure)は
# pak が原理的に生成されないので対象外(「優雅に失敗すること」は
# test_inputs.py::test_input_format が既に検査済み)。

_MACHINE_PREFAB_ORDER = [
    "prefab_flatver2_agyo", "prefab_flatver2_jinbe",
] + [k for k in matrix.PREFAB_SPECIMENS
     if k not in ("prefab_flatver2_agyo", "prefab_flatver2_jinbe")]


def pytest_generate_tests(metafunc):
    # test_inputs.py と同じ --specimens (all|fast|カンマ区切り) を共有する。
    # prefab 側は現状4体のみなので絞り込みオプションは設けない。
    if "machine_vrm_fbx_specimen" in metafunc.fixturenames:
        spec = metafunc.config.getoption("specimens")
        if spec == "all":
            names = list(_MACHINE_VRM_FBX_ORDER)
        elif spec == "fast":
            names = ["vrm_kate", "fbx_flat_ma"]
        else:
            wanted = {s.strip() for s in spec.split(",") if s.strip()}
            names = [n for n in _MACHINE_VRM_FBX_ORDER if n in wanted]
        metafunc.parametrize("machine_vrm_fbx_specimen", names, ids=names)
    if "machine_prefab_specimen" in metafunc.fixturenames:
        metafunc.parametrize("machine_prefab_specimen", _MACHINE_PREFAB_ORDER,
                             ids=_MACHINE_PREFAB_ORDER)


@pytest.mark.slow
def test_machine_visual_vrm_fbx(machine_vrm_fbx_specimen, build, allow_convert,
                                allow_machine, gate, paks_dir, pak_removed_after,
                                run_dir):
    """VRM/FBX全検体を実機に立たせて正面SSを残す(見た目そのものの合否は人間が見る)。

    ケース名 `input_<specimen>` は test_inputs.py::test_input_format と
    意図的に同一(build() のディスクキャッシュを再利用するため、モジュール
    docstring参照)。
    """
    import gates as shipcheck_gates
    import play_start_test as pst

    specimen = machine_vrm_fbx_specimen
    case = "input_{}".format(specimen)
    res = build(case, specimen, allow_convert=allow_convert)
    if not (res.pak_path and os.path.isfile(res.pak_path)):
        pytest.skip("pak が無い(exit={})".format(res.exit_code))

    shots = os.path.join(run_dir, "shots")
    os.makedirs(shots, exist_ok=True)
    with pak_removed_after():
        gate(shipcheck_gates.gate_f_playstart(pst, res.pak_path, repeat=1,
                                              shot_dir=shots),
             case=case, axis="実機:クラッシュ/プレイ開始/見た目")


@pytest.mark.unity
@pytest.mark.slow
def test_machine_visual_prefab(machine_prefab_specimen, unity_export, build,
                               allow_convert, allow_machine, gate, paks_dir,
                               pak_removed_after, run_dir):
    """prefab全検体(Unity輸出込み)を実機に立たせて正面SSを残す。

    --allow-unity が要る(unity_export フィクスチャの既定安全弁、他人の Unity
    プロジェクトへ書き込みが起きるため)。ケース名は test_prefab.py::
    test_prefab_end_to_end と同一(= specimen キーそのまま)にして build() の
    ディスクキャッシュを共有する。
    """
    import gates as shipcheck_gates
    import play_start_test as pst

    specimen = machine_prefab_specimen
    case = specimen
    rc, stdout, unity_log, out_dir = unity_export(case, specimen)
    fbx = sorted(f for f in os.listdir(out_dir) if f.lower().endswith(".fbx")) \
        if os.path.isdir(out_dir) else []
    if not fbx:
        pytest.skip("Unity 輸出物(FBX)が無い: {}".format(out_dir))
    fbx_path = os.path.join(out_dir, fbx[0])
    humanoid = os.path.join(out_dir, "humanoid.json")

    res = build(case, specimen, allow_convert=allow_convert,
               path_override=fbx_path, humanoid_override=humanoid)
    if not (res.pak_path and os.path.isfile(res.pak_path)):
        pytest.skip("pak が無い(exit={})".format(res.exit_code))

    shots = os.path.join(run_dir, "shots")
    os.makedirs(shots, exist_ok=True)
    with pak_removed_after():
        gate(shipcheck_gates.gate_f_playstart(pst, res.pak_path, repeat=1,
                                              shot_dir=shots),
             case=case, axis="実機:クラッシュ/プレイ開始/見た目")
