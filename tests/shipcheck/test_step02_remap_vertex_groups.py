# -*- coding: utf-8 -*-
"""dev#234 受入試験: step02_retarget.py の remap_vertex_groups() が
「unknown ancestor」(マップ先の無い)頂点グループを除去することを確認する。

対象: pipeline\\blender\\step02_retarget.py の remap_vertex_groups() /
rescue_zero_weight_vertices()

背景(実報告SB7BAUA5、2026-07-29、v2.2.0・VRM 1.0経由): remap_vertex_groups()は
マップ先が見つからない頂点グループ(build_group_targets()がavatar_arm.data.bones
全件について祖先を辿ってpal_mapへ解決を尽くしても解決できなかったもの。典型は
対応するボーンがアーマチュアに実在しないダングリング頂点グループ)を、警告だけ
出して除去していなかった。そのため元ボーン名(例: "pelvis001")を保持したまま
メッシュに残存し、後段のdump_avatar_mesh.pyがそれをJSONへ書き出し、
build_avatar_variant.pyのRefSkeletonボーン名照合で衣装SK注入58件が同時に
全滅していた(性別1個のdumpを全Outfit SKが共有する設計のため)。

G1(赤→緑の性質確認): ダングリング頂点グループ("pelvis001", 対応ボーン無し)を
持つ最小検体に対し、remap_vertex_groups()後にそのグループが除去され、
rescue_zero_weight_vertices()で該当頂点がフォールバックボーン(pelvis)へ
束縛されること(すなわちRefSkeletonに存在しないボーン名を持つ頂点グループが
生き残らないこと)を確認する。

G2(負の対照): 全頂点グループがマップ済み(build_group_targets()で解決できる)
通常ケースは、この変更で挙動が変わらない(グループ名・ウェイトが変化しない)こと。

Blenderが見つからない環境ではpytest.skip(理由付き、無言スキップはしない)。
pytestからも `python tests/shipcheck/test_step02_remap_vertex_groups.py` からも
実行できる(tests\\shipcheck\\test_dump_avatar_mesh.py と同じ構成)。
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
COVERAGE_DIR = os.path.join(REPO_ROOT, "tests", "coverage")
if COVERAGE_DIR not in sys.path:
    sys.path.insert(0, COVERAGE_DIR)
import matrix  # noqa: E402

STEP02_SCRIPT = os.path.join(REPO_ROOT, "pipeline", "blender", "step02_retarget.py")
WP_DIR = os.path.join(REPO_ROOT, "work", "wp234")

BLENDER_EXE = matrix.resolve_blender_exe()

# ============================================================================
# 最小検体の生成スクリプト(Blender内蔵Python用、埋め込み)
# ============================================================================

_MAKE_CASE_PY = r'''
import sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out_path = argv[0]
with_dangling = len(argv) > 1 and argv[1] == "dangling"

bpy.ops.wm.read_factory_settings(use_empty=True)

arm_data = bpy.data.armatures.new("RootArm")
arm_obj = bpy.data.objects.new("Armature", arm_data)
bpy.context.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode='EDIT')
eb = arm_data.edit_bones
b_pelvis = eb.new("pelvis")
b_pelvis.head = (0.0, 0.0, 1.0)
b_pelvis.tail = (0.0, 0.0, 1.2)
bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.mesh.primitive_cube_add(size=1.0)
cube = bpy.context.active_object
cube.name = "geo_00"
cube.data.uv_layers.new(name="UVMap")

# マップ済みグループ(build_group_targetsで"pelvis"へ解決できる想定): 全頂点
vg_ok = cube.vertex_groups.new(name="pelvis")
vg_ok.add([0, 1, 2, 3], 1.0, 'REPLACE')

if with_dangling:
    # dev#234: 対応するボーンが実在しない(ダングリング)頂点グループ。
    # 実報告(SB7BAUA5)のログにある"pelvis001"を模す。
    vg_bad = cube.vertex_groups.new(name="pelvis001")
    vg_bad.add([4, 5, 6, 7], 1.0, 'REPLACE')
else:
    vg_ok.add([4, 5, 6, 7], 1.0, 'REPLACE')

cube.parent = arm_obj
mod = cube.modifiers.new("Armature", type='ARMATURE')
mod.object = arm_obj

bpy.ops.wm.save_as_mainfile(filepath=out_path)
print(f"[make_case234] saved: {out_path} with_dangling={with_dangling}")
'''

# ============================================================================
# remap_vertex_groups()/rescue_zero_weight_vertices()を直接呼ぶハーネス。
# step02_retarget.pyはモジュール末尾でmain()を無条件呼び出す(job.json前提)ため、
# そのままimportできない。関数定義部分だけをexecして取り出す。
# ============================================================================

_RUN_REMAP_PY = r'''
import json
import sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
blend_path = argv[0]
step02_path = argv[1]
out_json = argv[2]

bpy.ops.wm.open_mainfile(filepath=blend_path)

with open(step02_path, encoding="utf-8") as f:
    src = f.read()
assert src.rstrip().endswith("main()"), "step02_retarget.pyの末尾形状が想定と違う"
src_no_main = src.rsplit("main()", 1)[0]

ns = {"__file__": step02_path, "__name__": "d2p_step02_under_test"}
exec(compile(src_no_main, step02_path, "exec"), ns)
remap_vertex_groups = ns["remap_vertex_groups"]
rescue_zero_weight_vertices = ns["rescue_zero_weight_vertices"]
ZERO_WEIGHT_FALLBACK_BONE = ns["ZERO_WEIGHT_FALLBACK_BONE"]

obj = bpy.data.objects["geo_00"]
arm = bpy.data.objects["Armature"]

# build_group_targets()相当: 実在するボーンはそのままpal名として解決できる、
# というシンプルな対応表(このテストの対象はremap_vertex_groups()自体の
# 「マップ先が無い場合の処理」であって、build_group_targets()の祖先探索
# ロジックそのものは別関数として別途検証されるため、ここでは最小の対応表で足りる)。
group_targets = {b.name: b.name for b in arm.data.bones}

before_names = sorted(vg.name for vg in obj.vertex_groups)
n_pal = remap_vertex_groups(obj, group_targets)
after_remap_names = sorted(vg.name for vg in obj.vertex_groups)
rescue_zero_weight_vertices(obj, ZERO_WEIGHT_FALLBACK_BONE)
after_rescue_names = sorted(vg.name for vg in obj.vertex_groups)

idx_to_name = {vg.index: vg.name for vg in obj.vertex_groups}
weights_by_vertex = {}
for v in obj.data.vertices:
    weights_by_vertex[str(v.index)] = {
        idx_to_name.get(g.group, "?%d" % g.group): round(g.weight, 3)
        for g in v.groups if g.weight > 0.0}

result = {
    "before_names": before_names,
    "n_pal_groups_returned": n_pal,
    "after_remap_names": after_remap_names,
    "after_rescue_names": after_rescue_names,
    "weights_by_vertex": weights_by_vertex,
}
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print(f"[run_remap] wrote: {out_json}")
'''


def _skip_if_no_blender():
    if not BLENDER_EXE:
        pytest.skip("Blenderが見つからない環境のためskip "
                     "(tests.coverage.matrix.resolve_blender_exe()が解決できなかった)")


def _write_script(name, content):
    os.makedirs(WP_DIR, exist_ok=True)
    path = os.path.join(WP_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _run_blender(script, args, log_path):
    cmd = [BLENDER_EXE, "--background", "--factory-startup",
           "--python-exit-code", "1", "--python", script, "--", *args]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    return r.returncode


def _read_log(log_path):
    with open(log_path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _make_case(name, with_dangling):
    _skip_if_no_blender()
    script = _write_script("pytest_make_case234.py", _MAKE_CASE_PY)
    out = os.path.join(WP_DIR, f"pytest_case234_{name}.blend")
    log = os.path.join(WP_DIR, f"pytest_make_case234_{name}.log")
    rc = _run_blender(script, [out, "dangling" if with_dangling else "normal"], log)
    assert rc == 0, f"検体生成に失敗した(log: {log}):\n{_read_log(log)}"
    return out


def _run_remap(blend_path, name):
    _skip_if_no_blender()
    script = _write_script("pytest_run_remap234.py", _RUN_REMAP_PY)
    out_json = os.path.join(WP_DIR, f"pytest_remap234_{name}_out.json")
    log = os.path.join(WP_DIR, f"pytest_remap234_{name}.log")
    rc = _run_blender(script, [blend_path, STEP02_SCRIPT, out_json], log)
    assert rc == 0, f"remap_vertex_groups()呼び出しが失敗した(log: {log}):\n{_read_log(log)}"
    with open(out_json, encoding="utf-8") as f:
        result = json.load(f)
    result["_log"] = _read_log(log)
    return result


@pytest.fixture(scope="module")
def dangling_blend():
    return _make_case("dangling", with_dangling=True)


@pytest.fixture(scope="module")
def normal_blend():
    return _make_case("normal", with_dangling=False)


# ============================================================================
# G1: dev#234 ダングリング頂点グループの除去+rescue
# ============================================================================

def test_dev234_dangling_group_is_removed_and_rescued(dangling_blend):
    r = _run_remap(dangling_blend, "dangling")
    assert r["before_names"] == ["pelvis", "pelvis001"], r
    assert "unknown ancestor" in r["_log"] and "pelvis001" in r["_log"], (
        f"unmatchedグループの警告ログが出ていない:\n{r['_log']}")
    assert "pelvis001" not in r["after_remap_names"], (
        "dev#234再発: マップ先の無い頂点グループ(pelvis001)がremap後も"
        f"生き残っている: {r['after_remap_names']}")
    assert r["after_remap_names"] == ["pelvis"], r
    assert r["after_rescue_names"] == ["pelvis"], r
    # 元pelvis001だった頂点4-7が、除去後にzero-weight rescueでpelvisへ
    # 束縛されていること(重みが完全に失われたままにはならない)
    for vi in ("4", "5", "6", "7"):
        assert r["weights_by_vertex"][vi] == {"pelvis": 1.0}, (
            f"頂点{vi}がpelvisへrescueされていない: {r['weights_by_vertex'][vi]}")
    for vi in ("0", "1", "2", "3"):
        assert r["weights_by_vertex"][vi] == {"pelvis": 1.0}, (
            f"元々マップ済みだった頂点{vi}の重みが変化した: {r['weights_by_vertex'][vi]}")


# ============================================================================
# G2: 負の対照 — 全グループがマップ済みの通常ケースは無影響
# ============================================================================

def test_dev234_negative_control_fully_mapped_groups_unaffected(normal_blend):
    r = _run_remap(normal_blend, "normal")
    assert r["before_names"] == ["pelvis"], r
    assert "unknown ancestor" not in r["_log"], (
        f"マップ済みグループのみの通常ケースでunmatched警告が誤発火した:\n{r['_log']}")
    assert r["after_remap_names"] == ["pelvis"], r
    assert r["after_rescue_names"] == ["pelvis"], r
    for vi in range(8):
        assert r["weights_by_vertex"][str(vi)] == {"pelvis": 1.0}, (
            f"通常ケースの頂点{vi}の重みがdev#234の変更で変化した: "
            f"{r['weights_by_vertex'][str(vi)]}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
