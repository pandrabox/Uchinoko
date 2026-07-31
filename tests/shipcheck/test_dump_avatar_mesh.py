# -*- coding: utf-8 -*-
"""WP-7781 受入試験: dump_avatar_mesh.py の決定性(dev#77案A)+
UV無し/0ポリゴンメッシュでの優雅な継続(dev#81)+NaN頂点位置のfail-fast検出(dev#193)。

対象: pipeline\\py\\dump_avatar_mesh.py

G1(dev#77・決定性): HairSampleMale実測入力(work\\HairSampleMale\\converted\\
step02_male.blend、dev#77の実報告そのもの)を`-t 1`固定(build_pak_from_avatar.py
Phase1と同じBlender起動引数)で独立2回ダンプし、出力JSONがバイト完全一致すること。

G2(dev#81・最小検体): 最小検体2種をBlenderで都度生成する
(生成スクリプトは本ファイルへ埋め込み、tests\\shipcheck\\配下=git管理下に置くことで、
新規チェックアウトでもwork\\配下の生成物に依存せず再現できるようにしてある):
  - ケースA: ボーン1本+UVレイヤー0枚のCube(issue #81本文が提案する検体そのもの)。
    修正前は`dump_avatar_mesh.py`226-228行目相当の既存ガード(`if not mesh.uv_layers:
    raise ...`)で停止する。
  - ケースB: ボーン1本+1頂点・0ポリゴンの補助メッシュ(実報告4AL4M4GT、
    geo_00=AvatarHightの再現)。`mesh.uv_layers`は非空(UVレイヤーの"入れ物"は
    残っている)なのに中身(ループ)が0件のため、ケースAの既存ガードを素通りして
    `mesh.calc_tangents()`(247行目相当)で初めて例外になる、ケースAとは別の失敗点
    (WP-7781実測、work\\wp_7781\\case_a_baseline.log / case_b_baseline.log)。

負の対照: UVありメッシュのみの既存検体(HairSampleMale)の出力(頂点数・三角形数)が
タスクB(UV無し/0ポリゴンガード追加)によって変わらないこと。

G3(dev#193・NaN頂点位置のfail-fast検出、W5S4T8HL事案の恒久対策): 最小構造検体
(ケースC、1三角形+頂点1個をNaN Zで直接構築)をダンプすると、`dump_avatar_mesh.py`が
工程の頭で`RuntimeError`を投げて非0終了すること(rc!=0)。異常メッセージに対象
メッシュ名・頂点インデックス・最大寄与ボーン名が含まれること。負の対照として、
同じ構造で全頂点が有限値のケースC'(正常版)は問題なく完走すること。

Blenderが見つからない環境ではpytest.skip(理由付き、無言スキップはしない)。
pytestからも `python tests/shipcheck/test_dump_avatar_mesh.py` からも実行できる
(tests\\shipcheck\\test_shared_cache.py と同じ構成)。
"""
import hashlib
import json
import math
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

DUMP_SCRIPT = os.path.join(REPO_ROOT, "pipeline", "py", "dump_avatar_mesh.py")
# WP-7781の書き込み許可範囲(work\wp_7781\配下)を一時ファイル置き場として使う。
WP_DIR = os.path.join(REPO_ROOT, "work", "wp_7781")
HAIR_SAMPLE_BLEND = os.path.join(
    REPO_ROOT, "work", "HairSampleMale", "converted", "step02_male.blend")

# dev#77実測(work\rd_77\PROPOSAL.md、work\wp_29a\convert_stdout*.log)・
# WP-7781実測(work\wp_7781\g1_run1.log)で確認済みの固定値。この値がテスト実行で
# 変化したら「検体自体が変わった」または「タスクAの寄与集約が結果を変えた」の
# どちらかであり、いずれも要調査。
HAIR_SAMPLE_EXPECTED_NUM_VERTICES = 18321
HAIR_SAMPLE_EXPECTED_NUM_TRIANGLES = 24858

BLENDER_EXE = matrix.resolve_blender_exe()

# ============================================================================
# ケースA/ケースB最小検体の生成スクリプト(Blender内蔵Python用、埋め込み)
# ============================================================================

_MAKE_CASE_A_PY = r'''
import sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out_path = argv[0]

bpy.ops.wm.read_factory_settings(use_empty=True)

arm_data = bpy.data.armatures.new("RootArm")
arm_obj = bpy.data.objects.new("Armature", arm_data)
bpy.context.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode='EDIT')
b = arm_data.edit_bones.new("root")
b.head = (0.0, 0.0, 0.0)
b.tail = (0.0, 0.0, 1.0)
bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.mesh.primitive_cube_add(size=1.0)
cube = bpy.context.active_object
cube.name = "geo_00"

while cube.data.uv_layers:
    cube.data.uv_layers.remove(cube.data.uv_layers[0])
assert len(cube.data.uv_layers) == 0

vg = cube.vertex_groups.new(name="root")
vg.add(list(range(len(cube.data.vertices))), 1.0, 'REPLACE')
cube.parent = arm_obj
mod = cube.modifiers.new("Armature", type='ARMATURE')
mod.object = arm_obj

bpy.ops.wm.save_as_mainfile(filepath=out_path)
print(f"[make_case_a] saved: {out_path}")
'''

_MAKE_CASE_B_PY = r'''
import sys
import bmesh
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out_path = argv[0]

bpy.ops.wm.read_factory_settings(use_empty=True)

arm_data = bpy.data.armatures.new("RootArm")
arm_obj = bpy.data.objects.new("Armature", arm_data)
bpy.context.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode='EDIT')
b = arm_data.edit_bones.new("root")
b.head = (0.0, 0.0, 0.0)
b.tail = (0.0, 0.0, 1.0)
bpy.ops.object.mode_set(mode='OBJECT')

mesh_data = bpy.data.meshes.new("geo_00")
bm = bmesh.new()
bm.verts.new((0.0, 0.0, 1.0))
bm.to_mesh(mesh_data)
bm.free()
mesh_data.update()
# UVレイヤーの"入れ物"だけ作る(実報告のgeo_00=AvatarHightと同じ状態を再現:
# ループが無いので中身は0件のまま)。
mesh_data.uv_layers.new(name="UVMap")

obj = bpy.data.objects.new("geo_00", mesh_data)
bpy.context.collection.objects.link(obj)
vg = obj.vertex_groups.new(name="root")
vg.add([0], 1.0, 'REPLACE')
obj.parent = arm_obj
mod = obj.modifiers.new("Armature", type='ARMATURE')
mod.object = arm_obj

bpy.ops.wm.save_as_mainfile(filepath=out_path)
print(f"[make_case_b] saved: {out_path}")
'''

# dev#193 G3: ケースC(NaN頂点位置)/ケースC'(同構造の正常版、負の対照)。
# ボーン1本+3頂点1三角形の最小メッシュ。argv[1]="nan"のときだけ頂点2のZ座標を
# float('nan')にする(それ以外は通常の有限値)。dump_avatar_mesh.pyの
# `pos = (mw @ mesh.vertices[vi].co) * 0.01`はidentity相当の行列でも
# 0*nan=nanがどの成分にも伝播するため、1成分だけNaNにしても出力位置は
# (nan, nan, nan)になる(実機ログのW5S4T8HL報告と同じ形、Blender 4.3.2で実測確認済み)。
_MAKE_CASE_C_PY = r'''
import sys
import bmesh
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out_path = argv[0]
make_nan = len(argv) > 1 and argv[1] == "nan"

bpy.ops.wm.read_factory_settings(use_empty=True)

arm_data = bpy.data.armatures.new("RootArm")
arm_obj = bpy.data.objects.new("Armature", arm_data)
bpy.context.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode='EDIT')
b = arm_data.edit_bones.new("root")
b.head = (0.0, 0.0, 0.0)
b.tail = (0.0, 0.0, 1.0)
bpy.ops.object.mode_set(mode='OBJECT')

mesh_data = bpy.data.meshes.new("geo_00")
bm = bmesh.new()
v0 = bm.verts.new((0.0, 0.0, 0.0))
v1 = bm.verts.new((1.0, 0.0, 0.0))
z2 = float('nan') if make_nan else 1.0
v2 = bm.verts.new((0.0, 1.0, z2))
bm.verts.ensure_lookup_table()
bm.faces.new((v0, v1, v2))
bm.to_mesh(mesh_data)
bm.free()
mesh_data.update()

uv_layer = mesh_data.uv_layers.new(name="UVMap")
for i, loop in enumerate(mesh_data.loops):
    uv_layer.data[i].uv = (0.0, 0.0)

obj = bpy.data.objects.new("geo_00", mesh_data)
bpy.context.collection.objects.link(obj)
vg = obj.vertex_groups.new(name="root")
vg.add([0, 1, 2], 1.0, 'REPLACE')
obj.parent = arm_obj
mod = obj.modifiers.new("Armature", type='ARMATURE')
mod.object = arm_obj

bpy.ops.wm.save_as_mainfile(filepath=out_path)
print(f"[make_case_c] saved: {out_path} make_nan={make_nan}")
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


def _run_blender(script, args, log_path, extra_blender_args=()):
    cmd = [BLENDER_EXE, "--background", "--factory-startup", *extra_blender_args,
           "--python-exit-code", "1", "--python", script, "--", *args]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    return r.returncode


def _sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _read_log(log_path):
    with open(log_path, encoding="utf-8", errors="replace") as f:
        return f.read()


@pytest.fixture(scope="module")
def hair_sample_blend():
    if not os.path.isfile(HAIR_SAMPLE_BLEND):
        pytest.skip(f"HairSampleMale検体が無い環境のためskip: {HAIR_SAMPLE_BLEND}")
    return HAIR_SAMPLE_BLEND


@pytest.fixture(scope="module")
def minimal_avatar_meta():
    """ケースA/ケースB検体は material slot を持たないため、slots={} の
    avatar_meta.json で足りる(dump_avatar_mesh.pyが既定で要求する引数)。"""
    p = os.path.join(WP_DIR, "pytest_avatar_meta.json")
    os.makedirs(WP_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"slots": {}}, f)
    return p


@pytest.fixture(scope="module")
def case_a_blend():
    _skip_if_no_blender()
    script = _write_script("pytest_make_case_a.py", _MAKE_CASE_A_PY)
    out = os.path.join(WP_DIR, "pytest_case_a.blend")
    log = os.path.join(WP_DIR, "pytest_make_case_a.log")
    rc = _run_blender(script, [out], log)
    assert rc == 0, f"ケースA検体の生成に失敗した(log: {log}):\n{_read_log(log)}"
    return out


@pytest.fixture(scope="module")
def case_b_blend():
    _skip_if_no_blender()
    script = _write_script("pytest_make_case_b.py", _MAKE_CASE_B_PY)
    out = os.path.join(WP_DIR, "pytest_case_b.blend")
    log = os.path.join(WP_DIR, "pytest_make_case_b.log")
    rc = _run_blender(script, [out], log)
    assert rc == 0, f"ケースB検体の生成に失敗した(log: {log}):\n{_read_log(log)}"
    return out


@pytest.fixture(scope="module")
def case_c_nan_blend():
    """dev#193 G3: 頂点2のZ座標がNaNの最小検体(1三角形、root 100%ウェイト)。"""
    _skip_if_no_blender()
    script = _write_script("pytest_make_case_c.py", _MAKE_CASE_C_PY)
    out = os.path.join(WP_DIR, "pytest_case_c_nan.blend")
    log = os.path.join(WP_DIR, "pytest_make_case_c_nan.log")
    rc = _run_blender(script, [out, "nan"], log)
    assert rc == 0, f"ケースC(NaN)検体の生成に失敗した(log: {log}):\n{_read_log(log)}"
    return out


@pytest.fixture(scope="module")
def case_c_normal_blend():
    """dev#193 G3負の対照: ケースCと同構造で全頂点が有限値の版。"""
    _skip_if_no_blender()
    script = _write_script("pytest_make_case_c.py", _MAKE_CASE_C_PY)
    out = os.path.join(WP_DIR, "pytest_case_c_normal.blend")
    log = os.path.join(WP_DIR, "pytest_make_case_c_normal.log")
    rc = _run_blender(script, [out, "normal"], log)
    assert rc == 0, f"ケースC(正常)検体の生成に失敗した(log: {log}):\n{_read_log(log)}"
    return out


# ============================================================================
# G1: dev#77 決定性
# ============================================================================

def test_g1_dump_is_byte_identical_across_two_independent_runs(hair_sample_blend):
    _skip_if_no_blender()
    out1 = os.path.join(WP_DIR, "pytest_g1_run1.json")
    out2 = os.path.join(WP_DIR, "pytest_g1_run2.json")
    log1 = os.path.join(WP_DIR, "pytest_g1_run1.log")
    log2 = os.path.join(WP_DIR, "pytest_g1_run2.log")

    rc1 = _run_blender(DUMP_SCRIPT, [hair_sample_blend, "Male", out1, "8"], log1,
                        extra_blender_args=["-t", "1"])
    assert rc1 == 0, f"G1 run1が失敗した(log: {log1}):\n{_read_log(log1)}"
    rc2 = _run_blender(DUMP_SCRIPT, [hair_sample_blend, "Male", out2, "8"], log2,
                        extra_blender_args=["-t", "1"])
    assert rc2 == 0, f"G1 run2が失敗した(log: {log2}):\n{_read_log(log2)}"

    h1, h2 = _sha256_file(out1), _sha256_file(out2)
    assert h1 == h2, (
        "dump_avatar_mesh.pyの出力が2回の独立実行でバイト一致しない"
        "(dev#77非決定性の再発疑い)。"
        f"run1_sha256={h1} run2_sha256={h2}")

    with open(out1, encoding="utf-8") as f:
        d1 = json.load(f)
    with open(out2, encoding="utf-8") as f:
        d2 = json.load(f)
    assert d1["num_vertices"] == d2["num_vertices"] > 0, "num_verticesが2回の実行で一致しない"
    assert d1["num_triangles"] == d2["num_triangles"] > 0, "num_trianglesが2回の実行で一致しない"


# ============================================================================
# G2: dev#81 最小検体(ケースA/ケースB)+負の対照
# ============================================================================

def test_g2_case_a_uvless_cube_completes_with_warning(case_a_blend, minimal_avatar_meta):
    out = os.path.join(WP_DIR, "pytest_case_a_out.json")
    log = os.path.join(WP_DIR, "pytest_case_a_dump.log")
    rc = _run_blender(DUMP_SCRIPT, [case_a_blend, "Male", out, "8", minimal_avatar_meta], log,
                       extra_blender_args=["-t", "1"])
    assert rc == 0, (
        f"ケースA(UV無しCube)の変換が停止した(dev#81修正が効いていない, log: {log}):\n"
        f"{_read_log(log)}")
    log_text = _read_log(log)
    assert "geo_00" in log_text and "no UV layer" in log_text, (
        f"警告行(対象メッシュ名+no UV layer)が標準出力に出ていない:\n{log_text}")
    with open(out, encoding="utf-8") as f:
        d = json.load(f)
    assert d["num_triangles"] == 12, (
        f"UV無しCubeは合成UVで幾何自体は保持され12三角形になるはず: {d['num_triangles']}")


def test_g2_case_b_zero_polygon_mesh_completes_with_warning(case_b_blend, minimal_avatar_meta):
    out = os.path.join(WP_DIR, "pytest_case_b_out.json")
    log = os.path.join(WP_DIR, "pytest_case_b_dump.log")
    rc = _run_blender(DUMP_SCRIPT, [case_b_blend, "Male", out, "8", minimal_avatar_meta], log,
                       extra_blender_args=["-t", "1"])
    assert rc == 0, (
        f"ケースB(0ポリゴンメッシュ)の変換が停止した(dev#81修正が効いていない, log: {log}):\n"
        f"{_read_log(log)}")
    log_text = _read_log(log)
    assert "geo_00" in log_text and "0 polygons" in log_text, (
        f"警告行(対象メッシュ名+0 polygons)が標準出力に出ていない:\n{log_text}")
    with open(out, encoding="utf-8") as f:
        d = json.load(f)
    assert d["num_vertices"] == 0 and d["num_triangles"] == 0, (
        "0ポリゴンメッシュはvertices/trianglesへ一切寄与しないはず: "
        f"num_vertices={d['num_vertices']} num_triangles={d['num_triangles']}")


def test_g2_case_a_synthesized_uv_is_well_formed(case_a_blend, minimal_avatar_meta):
    """バグ修正が本当に効いている(値を握りつぶしていない)ことの確認。
    `mesh.uv_layers.new()`はBlenderの既定動作で各面へ単位正方形
    (0,0)-(1,0)-(1,1)-(0,1)のUVを自動割当する(全頂点(0,0)固定にはならない、
    WP-7781実測)。合成UVがこの既定パターンどおりの非退化な値になっており、
    かつ位置・法線・ウェイトが無傷であることを確認する。"""
    out = os.path.join(WP_DIR, "pytest_case_a_uv_check.json")
    log = os.path.join(WP_DIR, "pytest_case_a_uv_check.log")
    rc = _run_blender(DUMP_SCRIPT, [case_a_blend, "Male", out, "8", minimal_avatar_meta], log,
                       extra_blender_args=["-t", "1"])
    assert rc == 0, f"log: {log}\n{_read_log(log)}"
    with open(out, encoding="utf-8") as f:
        d = json.load(f)
    unit_square_corners = ([0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0])
    for v in d["vertices"]:
        assert v["uv"] in unit_square_corners, (
            f"合成UVがBlender既定の単位正方形パターン以外の値になっている: {v['uv']}")
        assert len(v["weights"]) == 1 and v["weights"][0][0] == "root", (
            f"ウェイトが無傷でない(root 100%のはず): {v['weights']}")


def test_g2_negative_control_normal_avatar_unaffected_by_task_b(hair_sample_blend):
    """負の対照(issue #81本文の要求そのもの): UVありメッシュのみの既存検体
    (HairSampleMale)の出力(頂点数・三角形数)がタスクB(UV無し/0ポリゴンガード追加)
    によって変わらないこと。かつタスクBの警告が誤発火していないこと。"""
    _skip_if_no_blender()
    out = os.path.join(WP_DIR, "pytest_negctrl_normal.json")
    log = os.path.join(WP_DIR, "pytest_negctrl_normal.log")
    rc = _run_blender(DUMP_SCRIPT, [hair_sample_blend, "Male", out, "8"], log,
                       extra_blender_args=["-t", "1"])
    assert rc == 0, f"HairSampleMaleの変換が失敗した(log: {log}):\n{_read_log(log)}"
    with open(out, encoding="utf-8") as f:
        d = json.load(f)
    assert d["num_vertices"] == HAIR_SAMPLE_EXPECTED_NUM_VERTICES, (
        f"HairSampleMaleの頂点数がタスクBの変更で変化した"
        f"(想定{HAIR_SAMPLE_EXPECTED_NUM_VERTICES}): {d['num_vertices']}")
    assert d["num_triangles"] == HAIR_SAMPLE_EXPECTED_NUM_TRIANGLES, (
        f"HairSampleMaleの三角形数がタスクBの変更で変化した"
        f"(想定{HAIR_SAMPLE_EXPECTED_NUM_TRIANGLES}): {d['num_triangles']}")
    log_text = _read_log(log)
    assert "no UV layer" not in log_text and "0 polygons" not in log_text, (
        f"通常アバターに対してタスクBのガードが誤発火した(構造的な誤検知):\n{log_text}")


# ============================================================================
# G3: dev#193 NaN頂点位置のfail-fast検出(W5S4T8HL事案)+負の対照
# ============================================================================

def test_g3_nan_vertex_position_is_detected_fail_fast(case_c_nan_blend, minimal_avatar_meta):
    out = os.path.join(WP_DIR, "pytest_case_c_nan_out.json")
    log = os.path.join(WP_DIR, "pytest_case_c_nan_dump.log")
    rc = _run_blender(DUMP_SCRIPT, [case_c_nan_blend, "Male", out, "8", minimal_avatar_meta], log,
                       extra_blender_args=["-t", "1"])
    assert rc != 0, (
        f"NaN頂点位置を含む最小検体がdump_avatar_mesh.pyを通過してしまった"
        f"(dev#193 fail-fastが効いていない, log: {log}):\n{_read_log(log)}")
    assert not os.path.isfile(out), (
        f"検出失敗のはずなのに出力JSONが書き出されている(NaNが下流へ漏れた恐れ): {out}")
    log_text = _read_log(log)
    assert "non-finite vertex position" in log_text, (
        f"想定した検出メッセージ(non-finite vertex position)が出ていない:\n{log_text}")
    assert "geo_00" in log_text, f"対象メッシュオブジェクト名(geo_00)がエラーメッセージに無い:\n{log_text}"
    assert "vertex_index=2" in log_text, (
        f"NaNにした頂点インデックス(2)がエラーメッセージに無い:\n{log_text}")
    assert "top_weight_bone='root'" in log_text, (
        f"最大寄与ボーン名(root)がエラーメッセージに無い:\n{log_text}")
    assert "dev#193" in log_text, f"issue参照(dev#193)がエラーメッセージに無い:\n{log_text}"


def test_g3_negative_control_finite_vertex_position_completes(case_c_normal_blend, minimal_avatar_meta):
    """負の対照: ケースCと全く同じ構造で全頂点が有限値の版は、fail-fastガードに
    誤検知されず正常に完走し、期待どおりの三角形/頂点を出力すること。"""
    out = os.path.join(WP_DIR, "pytest_case_c_normal_out.json")
    log = os.path.join(WP_DIR, "pytest_case_c_normal_dump.log")
    rc = _run_blender(DUMP_SCRIPT, [case_c_normal_blend, "Male", out, "8", minimal_avatar_meta], log,
                       extra_blender_args=["-t", "1"])
    assert rc == 0, (
        f"NaNを含まない正常な最小検体がfail-fastガードに誤検知された"
        f"(構造的な誤検知, log: {log}):\n{_read_log(log)}")
    log_text = _read_log(log)
    assert "non-finite vertex position" not in log_text, (
        f"正常検体に対してdev#193ガードが誤発火した:\n{log_text}")
    with open(out, encoding="utf-8") as f:
        d = json.load(f)
    assert d["num_vertices"] == 3, f"1三角形の最小検体は3頂点になるはず: {d['num_vertices']}"
    assert d["num_triangles"] == 1, f"1三角形の最小検体は1三角形になるはず: {d['num_triangles']}"
    for v in d["vertices"]:
        assert all(math.isfinite(c) for c in v["pos"]), f"正常検体の位置に非有限値が混入した: {v['pos']}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
