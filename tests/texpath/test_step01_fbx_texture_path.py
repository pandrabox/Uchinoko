# -*- coding: utf-8 -*-
r"""dev#369 受入試験: FBXに記録されたテクスチャ参照の解決が、
「明示的に与えたルート基準・正規化済み・非致命」になっていることの単体試験。

## 背景(実報告 UHJJH7ZW / 7QSRW4ZJ / MBVDNUUJ、同一ユーザーが同日に3連投)

v2.2.7 で `step01_import_vrm.py` が下記で停止した:

    File ".../io_scene_fbx/import_fbx.py", line 2144, in blen_read_texture_image
        image = image_utils.load_image(filepath, dirname=basedir, ...)
    File ".../bpy_extras/image_utils.py", line 158, in load_image
        bpy.path.resolve_ncase(filepath_test),
    File ".../bpy/path.py", line 308, in _ncase_path_found
        files = _os.listdir(dirpath)
    FileNotFoundError: [WinError 3] ...
      '...\work\Ciel_VRC_1.0_export\..\..\..\..\..\..\..\..
       \AppData\Local\VRChatProjects\...\_Texture'

構造的な原因は2つの欠陥の合成である:

1. **基準ディレクトリが違う。** Blenderの `import_fbx.py:2125` は
   FBXが持つ `RelativeFilename` を `os.path.join(basedir, filepath)` で
   「**今そのFBXが置かれているフォルダ**」へ連結する。しかしその相対パスを
   書いたのはUnityのFBX Exporterであり、基準は「**ユーザーのUnity
   プロジェクト**」(`%LOCALAPPDATA%\VRChatProjects\...`)である。D2Pは
   輸出FBXを `work\<名前>_export\` へ置くので基準が食い違い、`..` を
   延々と遡るだけの無意味なパスができる。
2. **その失敗が致命的だった。** `bpy/path.py:306-311` は
   `os.listdir()` を `PermissionError` でしか守っていない。冗長な `..` は
   正規化されないままOSへ渡るため、`..` 8段(24文字)ぶん長くなった
   パスがWin32のパス長上限をまたぐと `FileNotFoundError` が素通りし、
   変換全体が停止する。

`..` の段数は症状であって原因ではない(段数を数え直す修正は誤り)。
実測(`work\wp369\repro_maxpath.py`)では、報告のパスはユーザー名を除いて
254文字で、`os.path.isdir()`(上限259)は通るのに `os.listdir()` が内部で
足す `\*.*` の4文字で越える、という窓にユーザー名2〜5文字で正確に入る。
正規化すれば同じパスは117文字になり窓自体が消える。開発機は
LongPathsEnabled=1 のため窓が存在せず、開発中に一度も踏まなかった。

## この試験の位置づけ

`step01_import_vrm.py` はモジュール末尾で `main()` を無条件に呼ぶため
そのままimportできない。`tests\shipcheck\test_step02_remap_vertex_groups.py`
と同じ流儀で、末尾の `main()` を落としてから関数定義部だけをexecして取り出す。
bpy/mathutils は使わないダミーで足りる(検証対象は純粋なパス計算と、
`bpy_extras.image_utils.load_image` の差し替えだけ)。

Blender実行も実変換も伴わない。CLAUDE.mdの「受入試験はリリースゲートに
任せる」に従い、単体試験+負の対照のみで完結させる。
"""
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
BLENDER_DIR = os.path.join(REPO_ROOT, "pipeline", "blender")
PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
STEP01 = os.path.join(BLENDER_DIR, "step01_import_vrm.py")

# 報告に出てきた実際の構造(ユーザー名・ショップ名は伏せた等価物)。
# ホーム直下から8階層下ったところにD2Pの輸出フォルダがあり、テクスチャの
# 実体はホーム直下の別枝(Unityプロジェクト)にある、という配置。
# FBXに記録された相対パスの基準はUnityプロジェクト側なので、それを
# 輸出フォルダへ連結すると `..` が8段生える。
FBX_CHAIN = ["Downloads", "palworldmod", "2.2.7",
             "Uchinoko_for_Palworld_v2.2.7_full", "Uchinoko_for_Palworld",
             "_internal", "work", "Ciel_VRC_1.0_export"]
UNITY_CHAIN = ["AppData", "Local", "VRChatProjects", "ciel-NekochillparkerAA",
               "Assets", "ShopName", "PackName", "_Mat_Tex", "_Texture"]
DEV369_RECORDED = os.sep.join([os.pardir] * len(FBX_CHAIN) + UNITY_CHAIN
                              + ["body.png"])
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# step01_import_vrm.py の関数だけを取り出す
# ---------------------------------------------------------------------------
def _install_stubs():
    """step01_import_vrm.py / vp_bl.py のモジュール先頭importを満たすだけの
    ダミー。検証対象(fbx_texture_candidates / resolve_fbx_texture /
    rooted_fbx_texture_resolution)はbpy・mathutilsの実体を一切使わない。"""
    if "bpy" not in sys.modules:
        bpy_stub = types.ModuleType("bpy")
        bpy_stub.data = types.SimpleNamespace()
        bpy_stub.context = types.SimpleNamespace()
        bpy_stub.ops = types.SimpleNamespace()
        bpy_stub.path = types.SimpleNamespace()
        sys.modules["bpy"] = bpy_stub
    if "mathutils" not in sys.modules:
        class _Dummy:
            def __init__(self, *a, **k):
                pass

            def __getattr__(self, _name):
                return lambda *a, **k: self

            def __matmul__(self, _other):
                return self

            def __add__(self, _other):
                return self

        mathutils_stub = types.ModuleType("mathutils")
        mathutils_stub.Matrix = _Dummy
        mathutils_stub.Quaternion = _Dummy
        mathutils_stub.Vector = _Dummy
        sys.modules["mathutils"] = mathutils_stub


@pytest.fixture(scope="module")
def step01():
    _install_stubs()
    for p in (BLENDER_DIR, PY_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
    with open(STEP01, encoding="utf-8") as f:
        src = f.read()
    assert src.rstrip().endswith("main()"), \
        "step01_import_vrm.pyの末尾形状が想定と違う(末尾の main() 呼び出しが無い)"
    src_no_main = src.rsplit("main()", 1)[0]
    ns = {"__file__": STEP01, "__name__": "d2p_step01_under_test"}
    exec(compile(src_no_main, STEP01, "exec"), ns)
    return types.SimpleNamespace(**ns)


# ---------------------------------------------------------------------------
# Blender 4.3.2 の load_image / resolve_ncase の失敗契約を忠実に写したスタブ。
#   * image_utils.py:143-165 …… imagepath → join(dirname, imagepath)
#     → join(dirname, basename) の順に resolve_ncase() を通して試す
#   * bpy/path.py:294-313 …… dirpathをlistdir()する。PermissionError以外の
#     OSErrorは捕捉されず外へ抜ける(=変換が止まる)
# 実機ではWin32のパス長上限がその「捕捉されないOSError」を生んだ。ここでは
# 開発機(LongPathsEnabled=1)でも決定的に再現できるよう、上限を引数で与える。
# ---------------------------------------------------------------------------
class FakeBlenderImageUtils:
    def __init__(self, path_limit):
        self.path_limit = path_limit
        self.loaded = []          # 実際に読み込んだ実在パス
        self.placeholders = []    # 見つからずプレースホルダにしたパス
        self.seen_paths = []      # OSへ渡された全パス(正規化の検証用)

    def _probe(self, path):
        """resolve_ncase() 相当。listdir()に相当する長さ判定で例外を投げる。"""
        self.seen_paths.append(path)
        dirpath = os.path.dirname(path)
        if os.path.isdir(dirpath) and len(dirpath) + 4 > self.path_limit:
            raise FileNotFoundError(
                3, "指定されたパスが見つかりません。", dirpath)
        return os.path.exists(path)

    def load_image(self, imagepath, dirname="", place_holder=False, **kwargs):
        variants = [imagepath]
        if dirname:
            variants.append(os.path.join(dirname, imagepath))
            variants.append(os.path.join(dirname, os.path.basename(imagepath)))
        for v in variants:
            if self._probe(v):
                self.loaded.append(v)
                return ("IMAGE", v)
        if place_holder:
            self.placeholders.append(imagepath)
            return ("PLACEHOLDER", imagepath)
        return None


@pytest.fixture
def fake_bpy_extras(monkeypatch):
    """`from bpy_extras import image_utils` を偽物に差し替える。"""
    def _make(path_limit):
        fake = FakeBlenderImageUtils(path_limit)
        image_utils_mod = types.ModuleType("bpy_extras.image_utils")
        image_utils_mod.load_image = fake.load_image
        bpy_extras_mod = types.ModuleType("bpy_extras")
        bpy_extras_mod.image_utils = image_utils_mod
        monkeypatch.setitem(sys.modules, "bpy_extras", bpy_extras_mod)
        monkeypatch.setitem(sys.modules, "bpy_extras.image_utils",
                            image_utils_mod)
        return fake, image_utils_mod
    return _make


@pytest.fixture
def specimen(tmp_path):
    """dev#369の最小検体(構造だけ。報告者のアバターは一切不要)。

        <home>/Downloads/.../work/Ciel_VRC_1.0_export/   ← FBXと輸出テクスチャ
            body.png, Textures/hair.png
        <home>/AppData/Local/VRChatProjects/.../_Texture/ ← 相対パスの本来の基準
            body.png

    輸出フォルダはhomeから8階層下にあるので、FBXに記録された
    `..` × 8 + Unity側の枝、という相対パスは**実在するディレクトリ**へ
    行き着く。報告者の環境と同じで、ここが実在することが重要
    (実在するからこそ `isdir()` が通り、`listdir()` だけが落ちた)。
    """
    home = tmp_path / "home"
    export_dir = home.joinpath(*FBX_CHAIN)
    export_dir.mkdir(parents=True)
    (export_dir / "body.png").write_bytes(PNG_MAGIC)
    sub = export_dir / "Textures"
    sub.mkdir()
    (sub / "hair.png").write_bytes(PNG_MAGIC)
    unity_tex = home.joinpath(*UNITY_CHAIN)
    unity_tex.mkdir(parents=True)
    (unity_tex / "body.png").write_bytes(PNG_MAGIC)
    # 「正規化済みのパスは全部通るが、`..` を残したパスだけが越える」上限。
    # 実機ではWin32の259文字がこれにあたる。
    path_limit = max(len(str(export_dir)), len(str(sub)),
                     len(str(unity_tex))) + 8
    return types.SimpleNamespace(
        home=str(home), export_dir=str(export_dir),
        unity_tex=str(unity_tex), path_limit=path_limit)


@pytest.fixture
def export_dir(specimen):
    return specimen.export_dir


# ===========================================================================
# G1: dev#369 の構造 — 基準の違う相対パスが正規化され、明示ルートで解決される
# ===========================================================================
def test_candidates_never_contain_parent_segments(step01, export_dir):
    """候補パスに `..` が一切残らないこと。

    残った `..` をそのままOSへ渡したことが、実報告の
    FileNotFoundError の直接の引き金だった。"""
    cands = step01.fbx_texture_candidates(DEV369_RECORDED, export_dir)
    assert cands, "候補が1つも組み立てられていない"
    for c in cands:
        assert os.pardir not in c.split(os.sep), \
            f"正規化されていない候補が残っている: {c}"
        assert c == os.path.normpath(c)


def test_dev369_resolves_to_texture_beside_fbx(step01, export_dir):
    """基準の違う(FBXの外へ逃げる)相対参照でも、実体のある
    「FBXと同じフォルダのファイル名一致」で解決されること。"""
    resolved, cands = step01.resolve_fbx_texture(DEV369_RECORDED, export_dir)
    assert resolved == os.path.join(export_dir, "body.png"), \
        f"解決先が想定と違う (候補: {cands})"


def test_wrong_base_join_is_not_preferred(step01, export_dir):
    """Blenderがまず試す `join(FBXのフォルダ, 記録された相対パス)` を、
    そのままの形では候補の先頭に置かないこと(=基準の食い違いを是正する)。"""
    cands = step01.fbx_texture_candidates(DEV369_RECORDED, export_dir)
    naive = os.path.join(export_dir, DEV369_RECORDED)
    assert naive not in cands
    assert cands[0] == os.path.join(export_dir, "body.png")


def test_reference_inside_export_dir_is_honoured(step01, export_dir):
    """非退行: 輸出フォルダの内側で完結する相対参照は、
    記録どおりのサブフォルダから読むこと(従来の挙動を保つ)。"""
    resolved, _ = step01.resolve_fbx_texture(r"Textures\hair.png", export_dir)
    assert resolved == os.path.join(export_dir, "Textures", "hair.png")


def test_subdir_fallback_by_basename(step01, export_dir):
    """記録されたフォルダ構成が食い違っていても、輸出フォルダ直下の
    サブフォルダにファイル名一致があれば拾えること。"""
    resolved, _ = step01.resolve_fbx_texture(
        r"..\..\somewhere\else\hair.png", export_dir)
    assert resolved == os.path.join(export_dir, "Textures", "hair.png")


def test_absolute_reference_outside_root_is_last_resort(step01, export_dir,
                                                        tmp_path):
    """輸出フォルダの外を指す実在パスは、候補の**最後**に来ること
    (=まず自分たちの輸出物を見る)。"""
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "body.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    cands = step01.fbx_texture_candidates(
        str(foreign / "body.png"), export_dir)
    assert cands[-1] == os.path.normpath(str(foreign / "body.png"))
    resolved, _ = step01.resolve_fbx_texture(
        str(foreign / "body.png"), export_dir)
    assert resolved == os.path.join(export_dir, "body.png")


# ===========================================================================
# G1(赤→緑): ガード無しでは実報告と同じ例外が出て、ガード有りでは出ない
# ===========================================================================
def _blender_native_call(image_utils_mod, basedir, recorded):
    """io_scene_fbx.import_fbx.blen_read_texture_image (4.3.2) の実際の呼び方。
    import_fbx.py:2125 で basedir へ連結し、2144 で load_image に渡す。"""
    filepath = os.path.join(basedir, recorded.lstrip(os.sep))
    return image_utils_mod.load_image(
        filepath, dirname=basedir, place_holder=True, recursive=False)


def test_red_without_guard_raises_like_the_report(specimen, fake_bpy_extras):
    """負の対照(赤): ガードを掛けない素のBlender経路は、実報告と同じ
    FileNotFoundError で落ちる。これが出ないなら試験自体が無意味。"""
    _fake, image_utils_mod = fake_bpy_extras(specimen.path_limit)
    with pytest.raises(FileNotFoundError):
        _blender_native_call(image_utils_mod, specimen.export_dir,
                             DEV369_RECORDED)


def test_green_with_guard_resolves_without_raising(step01, specimen,
                                                   fake_bpy_extras):
    """緑: 同じ条件でも、ガード下では例外が出ず、FBXと同じフォルダの
    実テクスチャを読む。"""
    fake, image_utils_mod = fake_bpy_extras(specimen.path_limit)
    export_dir = specimen.export_dir
    with step01.rooted_fbx_texture_resolution(export_dir):
        result = _blender_native_call(sys.modules["bpy_extras"].image_utils,
                                      export_dir, DEV369_RECORDED)
    assert result[0] == "IMAGE"
    assert result[1] == os.path.join(export_dir, "body.png")
    assert fake.placeholders == []
    for p in fake.seen_paths:
        assert os.pardir not in p.split(os.sep), \
            f"ガード下なのに正規化されていないパスがOSへ渡った: {p}"
    assert image_utils_mod.load_image is not None


def test_guard_restores_original_load_image(step01, export_dir,
                                            fake_bpy_extras):
    """ガードは差し替えを必ず元へ戻すこと(例外時も含む)。"""
    _fake, image_utils_mod = fake_bpy_extras(10_000)
    original = image_utils_mod.load_image
    with step01.rooted_fbx_texture_resolution(export_dir):
        assert image_utils_mod.load_image is not original
    assert image_utils_mod.load_image is original

    with pytest.raises(RuntimeError):
        with step01.rooted_fbx_texture_resolution(export_dir):
            raise RuntimeError("boom")
    assert image_utils_mod.load_image is original


# ===========================================================================
# G2(負の対照): 本当に存在しないテクスチャは、成功に化けず失敗として残ること
# ===========================================================================
def test_negative_control_missing_texture_is_not_resolved(step01, export_dir):
    """本当に存在しないテクスチャは None を返し、勝手に別ファイルへ
    すり替えないこと。ここが緑に化けると、本修正は不具合より悪くなる。"""
    resolved, cands = step01.resolve_fbx_texture(
        r"..\..\..\Assets\NoSuchPack\missing_texture.png", export_dir)
    assert resolved is None, f"存在しないテクスチャが解決されてしまった: {resolved}"
    assert cands, "候補リストが空(どこを探したか報告できない)"
    for c in cands:
        assert not os.path.exists(c)
        assert os.pardir not in c.split(os.sep)


def test_negative_control_diagnostic_names_base_and_candidates(
        step01, export_dir, fake_bpy_extras, capsys):
    """解決できなかったときは、**使った基準**と**試した候補を全部**
    ログに出すこと(自動探索は探索先と判定を必ず残す、という規約)。"""
    fake, _mod = fake_bpy_extras(10_000)
    missing = r"..\..\..\Assets\NoSuchPack\missing_texture.png"
    with step01.rooted_fbx_texture_resolution(export_dir):
        result = _blender_native_call(sys.modules["bpy_extras"].image_utils,
                                      export_dir, missing)
    out = capsys.readouterr().out
    assert "could not be resolved" in out
    assert "base used:" in out
    assert export_dir in out
    assert "missing_texture.png" in out
    tried = [ln for ln in out.splitlines() if "tried:" in ln]
    expected = step01.fbx_texture_candidates(missing, export_dir)
    assert len(tried) == len(expected) and expected, \
        f"試した候補が全部は出ていない: {tried}"
    # 見つからなかった事実は握り潰されず、プレースホルダとして残る
    assert result[0] == "PLACEHOLDER"
    assert fake.placeholders, "存在しないテクスチャが成功扱いになっている"


def test_negative_control_empty_reference(step01, export_dir):
    """参照が空なら候補ゼロ・未解決。空文字をルートへ連結して
    「フォルダそのもの」を掴んでしまわないこと。"""
    assert step01.fbx_texture_candidates("", export_dir) == []
    resolved, cands = step01.resolve_fbx_texture("", export_dir)
    assert resolved is None and cands == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
