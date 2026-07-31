# -*- coding: utf-8 -*-
"""dev#153 受入試験: dump_avatar_mesh.py の非有限ジオメトリ診断。

対象: pipeline\\py\\dump_avatar_mesh.py

背景(実報告W5S4T8HL): 衣装SK注入58件が全滅し、全FAILが
`position頂点135279が範囲外: (nan, nan, nan)` で揃っていた。下流の
`vp_core._parse_skeletalmesh_buffers_with_index`は頂点0から昇順に走査して
**最初の**範囲外で止まるため、この行が意味するのは「135279番だけが壊れている」
ではなく「0〜135278番は有限で、最初の破綻が135279番」でしかない。
dev#193のfail-fast実装も同じく最初の1個でraiseしていたため、
**「何個壊れたか」「どの段階で壊れたか」という切り分けに最も効く情報が、
検出位置を前に倒したあとも依然として落ちていた。**

本試験が守る仕様(dev#153):
  D1 ボーン起因(オブジェクト全滅型): 1本のポーズボーン行列が非有限だと、
     そのボーンにウェイトされたオブジェクトが丸ごとNaNになる(WP153実測、
     work\\wp153\\probe4.log G4)。このとき診断は「影響頂点数=全頂点数」
     「ALL vertices of this object」「stage=armature_deform」
     「non_finite_pose_bones=['beret']」まで名指しできること。
  D2 元データ起因: 変形前(rest)の座標が既に非有限なら
     「stage=source_geometry」と判定し、rest側の非有限数も出すこと
     (=NaNは本スクリプトより上流で生まれた、という結論がログだけで出る)。
  D3 ループ属性: 位置が有限でもUVが非有限なら検出して停止すること。
     UVには下流に検査が一切無く、`vp_meshrestore.encode_uv0()`がNaNを
     黙ってhalf floatへ書き込む(WP153実測: `encode_uv0(nan,0.0)`→`007e003c`、
     例外なし)ため、従来は「変換成功なのに絵が壊れたpak」として出荷されていた。
  D4 負の対照: D1と全く同じ2オブジェクト構造で全値が有限な検体は、
     一切の診断を発火させずに完走し、幾何(頂点数・三角形数)も無傷であること。
  D5 実経路到達性: 上記はすべて`build_pak_from_avatar.py`のPhase 1が実際に
     使うのと同一のコマンド形(同じスクリプトパス定数・同じBlender引数・
     同じ位置引数4個、avatar_meta.jsonは.blendと同じフォルダから暗黙解決)で
     起動して確認する。「正しいが呼ばれていない検査」を作らないための条項。

Blenderが見つからない環境ではpytest.skip(理由付き、無言スキップはしない)。
"""
import json
import os
import re
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
BUILD_PAK = os.path.join(REPO_ROOT, "pipeline", "py", "build_pak_from_avatar.py")
WP_DIR = os.path.join(REPO_ROOT, "work", "wp153")

BLENDER_EXE = matrix.resolve_blender_exe()

# build_pak_from_avatar.py の Phase 1 が使うBlender引数(WP-B3の-t 1固定を含む)。
# D5でこの列が実物と一致していることを静的にも検査する。
REAL_BLENDER_ARGS = ["--background", "--factory-startup", "-t", "1",
                     "--python-exit-code", "1"]


# ============================================================================
# 最小検体の生成スクリプト(Blender内蔵Python用、埋め込み)
#
# 構造は実報告の形をなぞる: 名前順で先に来る健全なオブジェクト(geo_00)と、
# 後に来るアクセサリ相当のオブジェクト(geo_99、別ボーンにウェイト)。
# dump_avatar_mesh.pyはsorted(o.name)順に処理するので、これは実報告の
# 「途中の頂点番号から破綻する」形と同じ配置になる。
# ============================================================================

_MAKE_SPECIMEN_PY = r'''
import sys
import bmesh
import bpy
from mathutils import Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
out_path, mode = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)

arm_data = bpy.data.armatures.new("Arm")
arm_obj = bpy.data.objects.new("Armature", arm_data)
bpy.context.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode='EDIT')
b0 = arm_data.edit_bones.new("root")
b0.head, b0.tail = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
b1 = arm_data.edit_bones.new("beret")
b1.head, b1.tail = (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)
bpy.ops.object.mode_set(mode='OBJECT')


def add_cube(name, bone, loc, nan_rest_vertex=None, nan_uv_loop=None):
    md = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.5)
    bm.to_mesh(md)
    bm.free()
    md.update()
    for v in md.vertices:
        v.co = (v.co[0] + loc[0], v.co[1] + loc[1], v.co[2] + loc[2])
    uv = md.uv_layers.new(name="UVMap")
    for i in range(len(md.loops)):
        uv.data[i].uv = ((i % 2) * 1.0, ((i // 2) % 2) * 1.0)
    if nan_rest_vertex is not None:
        c = md.vertices[nan_rest_vertex].co
        md.vertices[nan_rest_vertex].co = (c[0], c[1], float('nan'))
    if nan_uv_loop is not None:
        uv.data[nan_uv_loop].uv = (float('nan'), 0.0)
    ob = bpy.data.objects.new(name, md)
    bpy.context.collection.objects.link(ob)
    ob.vertex_groups.new(name=bone).add(
        list(range(len(md.vertices))), 1.0, 'REPLACE')
    ob.parent = arm_obj
    m = ob.modifiers.new("Armature", type='ARMATURE')
    m.object = arm_obj
    return ob


add_cube("geo_00", "root", (0.0, 0.0, 0.5))

if mode == "clean":
    add_cube("geo_99", "beret", (1.0, 0.0, 0.5))
elif mode == "nanbone":
    # 健全なジオメトリだが、ウェイト先ボーンのポーズ行列が非有限。
    add_cube("geo_99", "beret", (1.0, 0.0, 0.5))
    nan_m = Matrix.Identity(4)
    nan_m[0][3] = float('nan')
    arm_obj.pose.bones["beret"].matrix = nan_m
elif mode == "nanrest":
    # 変形前の座標が既に非有限(=上流で生まれたNaN)。
    add_cube("geo_99", "beret", (1.0, 0.0, 0.5), nan_rest_vertex=3)
elif mode == "nanuv":
    # 位置は全て有限、UVだけ非有限。
    add_cube("geo_99", "beret", (1.0, 0.0, 0.5), nan_uv_loop=5)
else:
    raise RuntimeError("unknown mode: " + mode)

bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=out_path)
print("[make_specimen] saved:", out_path, "mode:", mode)
'''


def _skip_if_no_blender():
    if not BLENDER_EXE:
        pytest.skip("Blenderが見つからない環境のためskip "
                    "(tests.coverage.matrix.resolve_blender_exe()が解決できなかった)")


def _specimen_dir(mode):
    d = os.path.join(WP_DIR, "specimen_" + mode)
    os.makedirs(d, exist_ok=True)
    # 実経路(build_pak_from_avatar.py)は位置引数を4個しか渡さず、
    # avatar_meta.json は .blend と同じフォルダから暗黙解決される。
    # D5のため、検体側も本番と同じ配置にしておく。
    with open(os.path.join(d, "avatar_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"slots": {}}, f)
    return d


def _make_specimen(mode):
    _skip_if_no_blender()
    d = _specimen_dir(mode)
    script = os.path.join(WP_DIR, "pytest_dev153_make_specimen.py")
    os.makedirs(WP_DIR, exist_ok=True)
    with open(script, "w", encoding="utf-8") as f:
        f.write(_MAKE_SPECIMEN_PY)
    blend = os.path.join(d, "step02_male.blend")
    log = os.path.join(d, "make.log")
    cmd = [BLENDER_EXE, "--background", "--factory-startup",
           "--python-exit-code", "1", "--python", script, "--", blend, mode]
    with open(log, "w", encoding="utf-8") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    assert r.returncode == 0, f"検体({mode})の生成に失敗した:\n{_read(log)}"
    return blend


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _run_dump_like_production(blend, tag):
    """build_pak_from_avatar.py の Phase 1 と同一のコマンド形でダンプを起動する。

    実物(pipeline\\py\\build_pak_from_avatar.py の _dump_gender):
        [blender_exe, "--background", "--factory-startup", "-t", "1",
         "--python-exit-code", "1", "--python",
         DEFAULT_DUMP_SCRIPT, "--", blend, gender, out_json, str(max_influences)]
    位置引数は4個のみ(avatar_meta.jsonは渡さない=暗黙解決)。
    """
    d = os.path.dirname(blend)
    out_json = os.path.join(d, f"avatar_{tag}.json")
    if os.path.isfile(out_json):
        os.remove(out_json)
    log = os.path.join(d, f"dump_{tag}.log")
    cmd = [BLENDER_EXE, *REAL_BLENDER_ARGS, "--python",
           DUMP_SCRIPT, "--", blend, "Male", out_json, "8"]
    with open(log, "w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    return r.returncode, _read(log), out_json


@pytest.fixture(scope="module")
def clean_blend():
    return _make_specimen("clean")


@pytest.fixture(scope="module")
def nanbone_blend():
    return _make_specimen("nanbone")


@pytest.fixture(scope="module")
def nanrest_blend():
    return _make_specimen("nanrest")


@pytest.fixture(scope="module")
def nanuv_blend():
    return _make_specimen("nanuv")


# ============================================================================
# D1: ボーン起因(オブジェクト全滅型)
# ============================================================================

def test_d1_nan_pose_bone_reports_full_object_and_names_the_bone(nanbone_blend):
    rc, log, out_json = _run_dump_like_production(nanbone_blend, "d1")
    assert rc != 0, f"非有限ポーズボーン由来のNaNが素通りした:\n{log}"
    assert not os.path.isfile(out_json), (
        f"検出失敗のはずなのに出力JSONが書かれている(NaNが下流へ漏れた): {out_json}")

    assert "non-finite vertex position" in log, log
    assert "geo_99" in log, f"原因オブジェクト名が出ていない:\n{log}"
    # 分布: このオブジェクトの全頂点が影響を受けている
    m = re.search(r"affected vertices\s*:\s*(\d+) / (\d+) evaluated vertices", log)
    assert m, f"影響頂点数/全頂点数の行が無い:\n{log}"
    n_bad, n_all = int(m.group(1)), int(m.group(2))
    assert n_bad == n_all == 8, (
        f"Cube全8頂点が影響を受けるはず: {n_bad}/{n_all}\n{log}")
    assert "ALL vertices of this object" in log, (
        f"「オブジェクト全滅=原因はオブジェクト/ボーン階層」という判定が出ていない:\n{log}")
    # 段階: 元座標は健全 -> アーマチュア変形で生まれた
    assert "stage                 : armature_deform" in log, (
        f"段階がarmature_deformと判定されていない:\n{log}")
    assert "pre-deform (rest) co  : non-finite in 0 of 8" in log, (
        f"変形前座標が健全である旨が出ていない:\n{log}")
    # 上流の退化入力の名指し
    assert "non_finite_pose_bones=['beret']" in log, (
        f"非有限なポーズ行列を持つボーン名(beret)が名指しされていない:\n{log}")
    assert "'beret'" in log
    # 健全な先行オブジェクト(geo_00)は正常に処理されてから停止している
    assert "geo_00: src_verts=8" in log, (
        f"名前順で先行する健全オブジェクトが処理されていない(実報告の"
        f"「途中の頂点番号から破綻」形になっていない):\n{log}")


# ============================================================================
# D2: 元データ起因(上流で生まれたNaN)
# ============================================================================

def test_d2_non_finite_rest_coordinate_is_attributed_to_source_geometry(nanrest_blend):
    rc, log, out_json = _run_dump_like_production(nanrest_blend, "d2")
    assert rc != 0, f"変形前座標のNaNが素通りした:\n{log}"
    assert not os.path.isfile(out_json)
    assert "non-finite vertex position" in log, log
    assert "geo_99" in log, log
    assert "stage                 : source_geometry" in log, (
        f"段階がsource_geometry(上流由来)と判定されていない:\n{log}")
    assert re.search(r"pre-deform \(rest\) co  : non-finite in 1 of 1", log), (
        f"変形前座標側の非有限数が出ていない:\n{log}")
    assert "a subset of this object's vertices" in log, (
        f"部分破綻(1頂点)であることが判定されていない:\n{log}")
    assert "vertex_index=3" in log, f"NaNにした頂点index(3)が出ていない:\n{log}"
    assert "top_weight_bone='beret'" in log, log


def test_d2b_stage_attribution_actually_discriminates(nanbone_blend, nanrest_blend):
    """D1とD2は「同じNaN位置」という同一症状だが、**段階の判定が逆に出る**こと。

    この2ケースが同じ文言になるなら、段階の欄は情報を持っていない(常に同じ
    ことを言う欄は診断ではない)。負の対照の一種として明示的に検査する。"""
    _, log_bone, _ = _run_dump_like_production(nanbone_blend, "d2b_bone")
    _, log_rest, _ = _run_dump_like_production(nanrest_blend, "d2b_rest")
    assert "stage                 : armature_deform" in log_bone
    assert "stage                 : source_geometry" not in log_bone
    assert "stage                 : source_geometry" in log_rest
    assert "stage                 : armature_deform" not in log_rest


# ============================================================================
# D3: ループ属性(UV)
# ============================================================================

def test_d3_non_finite_uv_is_detected(nanuv_blend):
    rc, log, out_json = _run_dump_like_production(nanuv_blend, "d3")
    assert rc != 0, (
        "非有限UVが素通りした。位置と違いUVには下流に一切検査が無く、"
        f"encode_uv0()がNaNを黙って書き込むため「成功したのに絵が壊れたpak」になる:\n{log}")
    assert not os.path.isfile(out_json)
    assert "non-finite loop attr" in log, f"ループ属性の診断が出ていない:\n{log}"
    assert "'uv'" in log, f"非有限だった属性種別(uv)が出ていない:\n{log}"
    assert "geo_99" in log, log


def test_d3b_uv_nan_would_be_silently_packed_downstream():
    """D3の存在理由の実証(この検査が無いと何が起きるか)。

    下流`vp_meshrestore.encode_uv0()`はNaN UVを例外も警告も無しにhalf floatへ
    書き込む。つまりdump段階で止めなければ、NaN UVは最後まで誰にも
    気づかれずpakへ入る。"""
    sys.path.insert(0, os.path.join(REPO_ROOT, "pipeline", "py"))
    import vp_meshrestore  # noqa: E402
    packed = vp_meshrestore.encode_uv0(float("nan"), 0.0)
    assert len(packed) == 4 and packed[:2] != b"\x00\x00", (
        "encode_uv0がNaNを黙って通す前提が崩れている(この試験の根拠が変わった)")


# ============================================================================
# D4: 負の対照
# ============================================================================

def test_d4_negative_control_clean_specimen_completes_untouched(clean_blend):
    rc, log, out_json = _run_dump_like_production(clean_blend, "d4")
    assert rc == 0, f"健全な検体がガードに誤検知された(構造的な誤検知):\n{log}"
    for token in ("non-finite vertex position", "non-finite loop attr",
                  "stage                 :"):
        assert token not in log, f"健全検体に対して診断が誤発火した({token}):\n{log}"
    with open(out_json, encoding="utf-8") as f:
        d = json.load(f)
    # Cube2個 = 12三角形 x2。頂点はUV/法線分割で24個 x2。
    assert d["num_triangles"] == 24, (
        f"健全検体の幾何が変化した(三角形): {d['num_triangles']}")
    assert d["num_vertices"] == 48, (
        f"健全検体の幾何が変化した(頂点): {d['num_vertices']}")
    import math as _m
    for v in d["vertices"]:
        assert all(_m.isfinite(c) for c in v["pos"] + v["normal"] + v["uv"]), v


# ============================================================================
# D5: 実経路到達性
# ============================================================================

def test_d5_guard_is_on_the_production_code_path():
    """本試験が叩いているスクリプトとBlender引数が、実際に製品が使うものと
    同一であることを`build_pak_from_avatar.py`のソースから確認する
    (「正しいが呼ばれていない検査」を作らないための条項)。"""
    src = _read(BUILD_PAK)
    assert 'DEFAULT_DUMP_SCRIPT = os.path.join(HERE, "dump_avatar_mesh.py")' in src, (
        "build_pak_from_avatar.pyが参照するダンプスクリプトのパス解決が変わった")
    # Phase 1 の起動行(引数の並び)が本試験のREAL_BLENDER_ARGSと一致していること
    assert ('run([blender_exe, "--background", "--factory-startup", '
            '*dump_blender_args,') in src
    assert '"--python-exit-code", "1", "--python",' in src
    assert ('DEFAULT_DUMP_SCRIPT, "--", blend, gender, out_json, '
            'str(max_influences)]') in src
    assert 'dump_blender_args = ["-t", "1"]' in src
    # 実物が指すファイルが、本試験が起動しているファイルと同一実体であること
    assert os.path.samefile(
        DUMP_SCRIPT, os.path.join(REPO_ROOT, "pipeline", "py", "dump_avatar_mesh.py"))


def test_d5b_guard_source_is_present_in_the_shipped_script():
    """ガード本体がダンプスクリプト側に存在すること(テスト内の再実装ではない)。"""
    src = _read(DUMP_SCRIPT)
    assert "def _diagnose_non_finite(" in src
    assert "bad_pos.setdefault(vi," in src
    assert "raise RuntimeError(msg)" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
