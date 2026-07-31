# -*- coding: utf-8 -*-
"""U54 WP-B: マシン共有キャッシュ(バニラ準備+ライブテンプレート)の受入試験。

対象:
  - pipeline\\py\\vp_core.py の汎用キャッシュ機構
    (shared_cache_dir/fingerprint_hash/acquire_cache_lock/release_cache_lock/
     lock_cache_dir_readonly/unlock_cache_dir_for_write/replace_dir_atomic)
  - pipeline\\py\\extract_vanilla.py のバニラ準備の共有キャッシュ化
    (resolve_vanilla_dir/run/ensure_job_local_copy)
  - pipeline\\py\\live_template.py の build_live_template() 共有キャッシュ化
  - pipeline\\py\\convert_noue.py の --warm-cache / warm_cache()

前半(test_lock_*/test_readonly_*/test_replace_dir_atomic_*)はpakを使わず、
vp_coreの汎用ロック/read-only機構だけを高速に検証する(数秒で終わる)。

後半(test_warm_*以降)は実機のPalworld pak(開発機にインストール済み、
**読み取りのみ**)を使って実際にwarm_cache()を走らせる受入試験。pakが
見つからない環境ではSKIPする(無言スキップにはせず理由を出す。テスト
コレクション自体は落とさない — test_ensure_blender.pyと同じ方針)。

pytestからも `python tests/shipcheck/test_shared_cache.py` からも実行できる
(tests\\shipcheck\\test_palworld_locate.py と同じ構成)。
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
if PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_PY_DIR)

import vp_core as core  # noqa: E402
import extract_vanilla  # noqa: E402
import live_template  # noqa: E402
import convert_noue  # noqa: E402


def _find_real_pak():
    try:
        import palworld_locate
        p = palworld_locate.find_palworld_pak()
        return p if p and os.path.isfile(p) else None
    except Exception:
        return None


REAL_PAK = _find_real_pak()
_TESTROOT_PREFIX = "d2p_shared_cache_test_"


def _fresh_work_root(name):
    """孤立したwork_root(=work\\相当)を用意する。前回の残骸があれば
    (read-only施錠込みで)まず片付ける。"""
    d = os.path.join(tempfile.gettempdir(), _TESTROOT_PREFIX + name)
    if os.path.isdir(d):
        core._set_tree_readonly(d, False)  # noqa: SLF001 (テスト側からの意図的な内部ヘルパ利用)
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def _cache_subdirs(work_root, kind):
    return [d for d in glob.glob(os.path.join(work_root, "_shared_cache", kind, "*"))
            if os.path.isdir(d)]


# ============================================================================
# 前半: vp_core汎用機構(pak不要、高速)
# ============================================================================

def test_fingerprint_hash_is_order_independent_and_12_hex():
    h1 = core.fingerprint_hash({"a": 1, "b": 2})
    h2 = core.fingerprint_hash({"b": 2, "a": 1})
    assert h1 == h2, "dictのキー順序でfingerprint_hashが変わってしまう"
    assert len(h1) == 12
    assert all(c in "0123456789abcdef" for c in h1)

    h3 = core.fingerprint_hash({"a": 1, "b": 3})
    assert h3 != h1, "値が変わってもハッシュが変わらない(鍵として機能していない)"


def test_shared_cache_dir_changes_path_when_fingerprint_changes():
    work_root = _fresh_work_root("dirpath")
    p1 = core.shared_cache_dir(work_root, "vanilla", {"pak_size": 100})
    p2 = core.shared_cache_dir(work_root, "vanilla", {"pak_size": 200})
    assert p1 != p2, "fingerprintが違うのに同じディレクトリを指してしまう(共有汚染の危険)"
    assert os.path.dirname(p1) == os.path.dirname(p2) == os.path.join(work_root, "_shared_cache", "vanilla")


def test_shared_cache_root_env_override(monkeypatch):
    work_root = _fresh_work_root("envoverride")
    override_base = _fresh_work_root("envoverride_target")
    monkeypatch.setenv("D2P_SHARED_CACHE", override_base)
    try:
        p = core.shared_cache_dir(work_root, "vanilla", {"k": 1})
        assert p.startswith(os.path.abspath(override_base)), (
            "D2P_SHARED_CACHEを設定してもwork_root配下を指し続けている: {}".format(p))
    finally:
        monkeypatch.delenv("D2P_SHARED_CACHE", raising=False)


def test_lock_blocks_second_acquirer_and_stale_lock_is_taken_over():
    """ロックファイル存在中(かつ新鮮)は待つ。stale(30分超過)は即座に奪取する。"""
    work_root = _fresh_work_root("lock")
    cache_dir = core.shared_cache_dir(work_root, "dummy", {"k": 1})

    # 1) 新鮮なロック保持中は、別スレッドからのacquireが完了しないこと
    lock1 = core.acquire_cache_lock(cache_dir, poll_interval=0.2)
    completed = []

    def _second_acquirer():
        lock2 = core.acquire_cache_lock(cache_dir, poll_interval=0.2)
        completed.append("second")
        core.release_cache_lock(lock2)

    t = threading.Thread(target=_second_acquirer)
    t.start()
    time.sleep(0.8)
    assert completed == [], "新鮮なロック保持中に2つ目のacquireが素通りした(排他になっていない)"
    core.release_cache_lock(lock1)
    t.join(timeout=5)
    assert completed == ["second"], "ロック解放後も2つ目のacquireが完了しなかった"

    # 2) stale(31分前の偽タイムスタンプ)なロックは待たずに奪取されること
    lock_path = core._cache_lock_path(cache_dir)  # noqa: SLF001
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"pid": 999999999, "time": time.time() - 31 * 60}, f)
    t0 = time.time()
    lock3 = core.acquire_cache_lock(cache_dir, poll_interval=0.2, stale_seconds=30 * 60)
    elapsed = time.time() - t0
    assert elapsed < 5.0, "staleロックの奪取に{:.1f}秒もかかった(即時奪取のはず)".format(elapsed)
    core.release_cache_lock(lock3)


def test_readonly_lockdown_blocks_write_then_negative_control_before_lock():
    """完成後read-only化されたキャッシュへの書き込みは失敗する。
    負の対照: read-only化する**前**は普通に書き込めること(検査自体の有効性確認)。"""
    work_root = _fresh_work_root("readonly")
    cache_dir = core.shared_cache_dir(work_root, "dummy", {"k": 2})
    os.makedirs(cache_dir, exist_ok=True)
    fpath = os.path.join(cache_dir, "a.txt")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write("hello")

    # 負の対照: read-only化前は書き込める
    with open(fpath, "a", encoding="utf-8") as f:
        f.write("!")

    core.lock_cache_dir_readonly(cache_dir)
    wrote = False
    try:
        with open(fpath, "a", encoding="utf-8") as f:
            f.write("x")
        wrote = True
    except PermissionError:
        pass
    assert not wrote, "read-only化されたはずのファイルへ書き込めてしまった(silent corruption対策が効いていない)"

    core.unlock_cache_dir_for_write(cache_dir)
    with open(fpath, "a", encoding="utf-8") as f:
        f.write("y")  # 解錠後は書き込めること


def test_replace_dir_atomic_removes_old_content():
    work_root = _fresh_work_root("replace")
    cache_dir = core.shared_cache_dir(work_root, "dummy", {"k": 3})
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "old.txt"), "w", encoding="utf-8") as f:
        f.write("old")

    tmp = core.cache_tmp_dir(cache_dir)
    with open(os.path.join(tmp, "new.txt"), "w", encoding="utf-8") as f:
        f.write("new")
    core.replace_dir_atomic(tmp, cache_dir)

    assert os.path.exists(os.path.join(cache_dir, "new.txt"))
    assert not os.path.exists(os.path.join(cache_dir, "old.txt")), "旧内容が残っている(置き換わっていない)"


# ============================================================================
# 後半: 実machine pak を使ったwarm_cache()の受入試験(読み取りのみ)
# ============================================================================

@pytest.fixture(scope="module")
def real_pak():
    if not REAL_PAK:
        pytest.skip("Palworldのpakが見つからない環境のため実warm試験をskip"
                     "(palworld_locate.find_palworld_pak()が解決できなかった)")
    return REAL_PAK


@pytest.fixture(scope="module")
def warm_base(real_pak):
    """このモジュール内の実warm系テストが共有する基準ビルド。1回だけ実行する
    (live_templateの組み立ては実測30秒級のため、テストごとに繰り返さない)。"""
    work_root = _fresh_work_root("base")
    t0 = time.time()
    info = convert_noue.warm_cache(real_pak, work_root)
    print("\n[test_shared_cache] warm 1回目(新規構築): total_sec={} detail={}".format(
        time.time() - t0, info))
    return {"work_root": work_root, "info": info}


def test_warm_cache_builds_vanilla_and_live_template(warm_base):
    work_root = warm_base["work_root"]

    vanilla_dirs = _cache_subdirs(work_root, "vanilla")
    assert len(vanilla_dirs) == 1, "vanilla共有キャッシュは1件だけ作られるはず: {}".format(vanilla_dirs)
    vdir = vanilla_dirs[0]
    for fn in ("common_bones.json", "refskel_male.json", "refskel_female.json",
               "dup_outfit_male.csv", "dup_outfit_female.csv", "dup_head_male.csv",
               "dup_head_female.csv", "dup_hair.csv", "dup_headequip.csv",
               "sk_inventory.json", "pak_entries.txt.gz", "version.txt",
               "extract_stamp.json"):
        assert os.path.exists(os.path.join(vdir, fn)), "vanilla共有キャッシュに{}が無い".format(fn)

    with open(os.path.join(vdir, "extract_stamp.json"), encoding="utf-8") as f:
        stamp = json.load(f)
    assert stamp["stage"] == "full"
    assert stamp["fingerprint"]["vanilla_version"] == extract_vanilla.VANILLA_VERSION

    lt_dirs = _cache_subdirs(work_root, "live_template")
    assert len(lt_dirs) == 1, "live_template共有キャッシュは1件だけ作られるはず: {}".format(lt_dirs)
    ltdir = lt_dirs[0]
    marker = ltdir.rstrip("\\/") + ".fingerprint.json"
    assert os.path.isfile(marker), "live_templateのfingerprintマーカー(兄弟ファイル)が無い"
    with open(marker, encoding="utf-8") as f:
        fp = json.load(f)
    assert fp.get("template_build_version") == live_template.TEMPLATE_BUILD_VERSION
    # T3のMI差替え(_inject_outfit_body_parka_textures)が最終位置に対して行われた
    # 証拠(t00/t01への統一MI)が実在すること
    assert os.path.isfile(os.path.join(
        ltdir, "Player", "ModelMaterials", "MainShader", "t00.uexp"))

    # job_dir配下(step02_retarget.py/preflight_pak.py用の複製、4.2のper-job
    # コピー fallback)にも反映されていること
    job_local_vanilla = os.path.join(work_root, "_warm_dummy", "vanilla")
    assert os.path.isfile(os.path.join(job_local_vanilla, "pak_entries.txt.gz")), (
        "job_dir配下へのvanilla複製(_sync_job_local_copy)が反映されていない")


def test_warm_cache_second_call_is_fast_cache_hit(warm_base, real_pak):
    """warm_baseで既に1回構築済みの状態から、もう一度呼ぶと即終了し
    (キャッシュ内ファイルのmtimeが変化しない=再構築されていない)。"""
    work_root = warm_base["work_root"]
    vdir = _cache_subdirs(work_root, "vanilla")[0]
    ltdir = _cache_subdirs(work_root, "live_template")[0]

    mtimes_before = {}
    for root, _dirs, files in os.walk(vdir):
        for fn in files:
            p = os.path.join(root, fn)
            mtimes_before[p] = os.path.getmtime(p)
    lt_sample = os.path.join(ltdir, "Player", "ModelMaterials", "MainShader", "t00.uexp")
    mtime_lt_before = os.path.getmtime(lt_sample)

    t0 = time.time()
    info2 = convert_noue.warm_cache(real_pak, work_root)
    elapsed = time.time() - t0
    print("[test_shared_cache] warm 2回目(キャッシュヒット): total_sec={:.3f} detail={}".format(
        elapsed, info2))

    assert elapsed < 5.0, "2回目のwarmが{:.1f}秒もかかった(キャッシュヒットで数秒以内のはず)".format(elapsed)
    assert info2["total_sec"] < 5.0

    for p, mt in mtimes_before.items():
        assert os.path.getmtime(p) == mt, "vanillaキャッシュのファイルmtimeが変化した(再構築された疑い): {}".format(p)
    assert os.path.getmtime(lt_sample) == mtime_lt_before, "live_templateのファイルmtimeが変化した(再構築された疑い)"


def test_fingerprint_mismatch_triggers_new_cache_dir(warm_base, real_pak):
    """鍵の一部(VANILLA_VERSION相当)を変えて注入すると、fp12が変わり
    別ディレクトリで再構築される(=既存の共有キャッシュを汚さず作り直す)こと。"""
    work_root = warm_base["work_root"]
    before_dirs = set(_cache_subdirs(work_root, "vanilla"))

    orig_version = extract_vanilla.VANILLA_VERSION
    try:
        extract_vanilla.VANILLA_VERSION = orig_version + "_TESTMUT"
        job = convert_noue._warm_job(real_pak, work_root)
        extract_vanilla.run(job, extract_vanilla.STAGE_BLENDER)
    finally:
        extract_vanilla.VANILLA_VERSION = orig_version

    after_dirs = set(_cache_subdirs(work_root, "vanilla"))
    assert len(after_dirs) == len(before_dirs) + 1, (
        "fingerprint変更で新しい共有キャッシュディレクトリが作られなかった: "
        "before={} after={}".format(before_dirs, after_dirs))
    assert before_dirs <= after_dirs, "既存の共有キャッシュディレクトリが消えている(汚染/巻き添え削除の疑い)"


def test_corrupt_stamp_triggers_rebuild(warm_base, real_pak):
    """負の対照: extract_stamp.json(共有キャッシュ内マーカー)を破損させると、
    次回実行時に(read-only解除→)再構築され、正しいスタンプへ復元されること。"""
    work_root = warm_base["work_root"]
    vdir = _cache_subdirs(work_root, "vanilla")[0]
    stamp_path = os.path.join(vdir, "extract_stamp.json")

    core.unlock_cache_dir_for_write(vdir)
    with open(stamp_path, "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    core.lock_cache_dir_readonly(vdir)

    job = convert_noue._warm_job(real_pak, work_root)
    extract_vanilla.run(job, extract_vanilla.STAGE_FULL)

    with open(stamp_path, encoding="utf-8") as f:
        stamp = json.load(f)  # 壊れていれば例外→テスト失敗。ここに来た時点で修復成功
    assert stamp["stage"] == "full"
    assert stamp["fingerprint"]["vanilla_version"] == extract_vanilla.VANILLA_VERSION


def _hash_tree(root_dir):
    """root_dir配下の全ファイルを(相対パス, 内容sha256)の一覧としてハッシュ化する
    (ディレクトリ全体の決定性を1個のダイジェストで比較するための補助)。"""
    import hashlib
    digest = hashlib.sha256()
    rels = []
    for cur, _dirs, files in os.walk(root_dir):
        for fn in files:
            p = os.path.join(cur, fn)
            rels.append(os.path.relpath(p, root_dir).replace("\\", "/"))
    for rel in sorted(rels):
        with open(os.path.join(root_dir, *rel.split("/")), "rb") as f:
            data = f.read()
        digest.update(rel.encode("utf-8"))
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest(), len(rels)


def test_live_template_two_independent_fresh_builds_are_byte_identical(real_pak):
    """U54 WP-B3: build_live_template()自体(共有キャッシュが管理する範囲)が
    2回独立に新規構築しても中身が完全に決定的であることを確認する回帰試験。

    背景(work\\u54_unbundle\\wpB3\\REPORT.md参照): release.py v1.1.4試行で
    prefab_flataponのpakがOutfit系SK uexp 29件だけ変更ありでFAILした事象を
    調査した結果、原因は本モジュール(live_template/共有キャッシュ)ではなく、
    Blenderのmesh.calc_tangents()(pipeline\\py\\dump_avatar_mesh.py、共有
    キャッシュ対象外・avatar個別処理)が実行ごとに1e-6オーダーで値がブレる
    こと(実測で確認済み、Blender単体・逐次2回実行でも再現)と判明した。
    このテストは「疑われた共有キャッシュ機構自体は無罪」を固定化する:
    2つの独立したwork_root(=互いにキャッシュを共有しない)へそれぞれ
    fresh(コールドキャッシュ)でbuild_live_templateを走らせ、生成される
    live_templateディレクトリの中身(全ファイルの相対パス+内容ハッシュ)が
    完全一致することを検証する。"""
    work_root_a = _fresh_work_root("determinism_a")
    work_root_b = _fresh_work_root("determinism_b")

    job_a = convert_noue._warm_job(real_pak, work_root_a)
    job_b = convert_noue._warm_job(real_pak, work_root_b)

    extract_vanilla.run(job_a, extract_vanilla.STAGE_BLENDER)
    extract_vanilla.run(job_a, extract_vanilla.STAGE_FULL)
    template_dir_a = live_template.build_live_template(job_a)

    extract_vanilla.run(job_b, extract_vanilla.STAGE_BLENDER)
    extract_vanilla.run(job_b, extract_vanilla.STAGE_FULL)
    template_dir_b = live_template.build_live_template(job_b)

    digest_a, n_a = _hash_tree(template_dir_a)
    digest_b, n_b = _hash_tree(template_dir_b)
    assert n_a == n_b and n_a > 0, (
        "live_templateのファイル数が2回のfresh構築で一致しない: {} vs {}".format(n_a, n_b))
    assert digest_a == digest_b, (
        "live_template(共有キャッシュ管理対象)が2回のfresh構築で1バイトでも異なった。"
        "共有キャッシュ機構自体に非決定性が入り込んだ疑いがある(WP-B3の前提が"
        "崩れた場合の検知用)。digest_a={} digest_b={}".format(digest_a, digest_b))


def test_write_into_readonly_shared_cache_fails(warm_base):
    """共有キャッシュ(vanilla/live_template どちらも)完成後は、直接の書き込み
    試行がread-onlyで失敗すること(4.4の要件そのものの実機確認)。"""
    work_root = warm_base["work_root"]
    vdir = _cache_subdirs(work_root, "vanilla")[0]
    ltdir = _cache_subdirs(work_root, "live_template")[0]

    for target in (os.path.join(vdir, "common_bones.json"),
                   os.path.join(ltdir, "Player", "ModelMaterials", "MainShader", "t00.uexp")):
        wrote = False
        try:
            with open(target, "ab") as f:
                f.write(b"x")
            wrote = True
        except PermissionError:
            pass
        assert not wrote, "read-only施錠済みの共有キャッシュへ書き込めてしまった: {}".format(target)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
