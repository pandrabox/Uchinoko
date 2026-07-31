# -*- coding: utf-8 -*-
r"""dev#163(ゲート別入力指紋キャッシュ、devtools\gate_cache.py)のWP-1受入試験。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、本試験は実変換・
実relgate実行・実release.py本番実行を一切課さない(pak不変の構造変更のため)。
フィンガープリント計算・キャッシュI/O・成果物実体化のロジック単体を、
monkeypatchで隔離した小さな入力で検証する。

2026-07-29簡素化改訂(ぱん指摘「オーバーエンジニアリング」、指揮者経由の
設計変更指示): dist_smoke/relgateそれぞれに独立した入力定義表を持たせる
設計は廃止し、共通の単一フィンガープリント(gate_cache.compute_gate_fingerprint）
1本に統合した。あわせて受入ゲートの負の対照も8種から3種へ絞った
(①入力1バイト変更でキャッシュ無効化 ②成功runを--resume-fromに渡すと拒否
③除外ゲート(WSB)がキャッシュされない)。本ファイルは①を担当する
(②③はtests\shipcheck\test_release_resume.pyで確認する)。

実行: python -m pytest tests\shipcheck\test_gate_cache.py -v
"""
import importlib
import os
import stat
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
TESTS_RELGATE = os.path.join(REPO, "tests", "relgate")

for p in (DEVTOOLS, TESTS_RELGATE):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_gate_cache():
    return importlib.import_module("gate_cache")


def _gate_specimen_fixtures_present():
    """gate_input_files()が要求する検体一式(.devonly/fixtures/relgate/shapell/
    shapell.fbx 等)がこの環境に実在するか。

    dev#317: .devonly/fixtures/ は .gitignore で除外されている
    (dev#186で実体を移設。第三者購入アセット/非再配布アバターの実データを
    含むため、そもそもgitへコミットできない)。hosted CIランナーの新規
    checkoutにはこのディレクトリが構造的に生成されず、開発機にのみ
    実在する前提のテストなので、無ければ理由付きでSKIPする(単に
    「落ちるから外す」のではなく、原理的にhosted環境で用意できない
    ことをここに明記する)。"""
    try:
        gate_cache = _import_gate_cache()
        for _rel, p in gate_cache._gate_specimen_files():
            if not os.path.isfile(p):
                return False
        return True
    except Exception:
        return False


HAS_GATE_SPECIMEN_FIXTURES = _gate_specimen_fixtures_present()
_GATE_SPECIMEN_SKIP_REASON = (
    "検体フィンガープリント対象(.devonly/fixtures/relgate/shapell/shapell.fbx等)"
    "がこの環境に無い。.devonly/fixtures/は.gitignoreで除外されており"
    "(第三者購入アセット等を再配布できないため、dev#186)、hosted CIの新規"
    "checkoutでは構造的に存在し得ない(開発機のみに置かれる想定の検体)。"
)


class DummyReport:
    """release.Report/BufferedReportと同じ log()/section() インタフェースの
    最小スタブ(実ファイルへ書かない)。"""

    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)


def _isolate_gate_cache_dirs(gate_cache, tmp_path, monkeypatch):
    """実リポジトリのwork\\release_cert\\gate_cache\\を一切触らないよう、
    キャッシュ置き場をtmp_pathへ差し替える。"""
    monkeypatch.setattr(gate_cache, "GATE_CACHE_ROOT", str(tmp_path / "gate_cache"))
    monkeypatch.setattr(gate_cache, "ARTIFACTS_ROOT", str(tmp_path / "gate_cache" / "artifacts"))


# --- 基本の疎通(実リポジトリに対して計算できること) -----------------------------

@pytest.mark.skipif(not HAS_GATE_SPECIMEN_FIXTURES, reason=_GATE_SPECIMEN_SKIP_REASON)
def test_compute_gate_fingerprint_runs_against_real_repo():
    gate_cache = _import_gate_cache()
    fp = gate_cache.compute_gate_fingerprint("none")
    assert isinstance(fp["combined"], str) and len(fp["combined"]) == 64
    assert fp["num_files"] > 0
    assert fp["pak_declared"] == "none"


# --- 負の対照1: 入力1バイト変更でキャッシュが無効化されること -------------------

def test_gate_fingerprint_changes_on_source_byte_change(monkeypatch):
    """gate_input_files()の戻り値だけをモックし、集計ロジック
    (compute_gate_fingerprint自体)は無改変のまま検証する(高速+隔離)。"""
    gate_cache = _import_gate_cache()
    contents = {"a.py": "original-a", "b.py": "original-b"}

    monkeypatch.setattr(gate_cache, "gate_input_files",
                         lambda: sorted((rel, rel) for rel in contents))
    monkeypatch.setattr(gate_cache, "_sha256_normalized_file",
                         lambda rel: gate_cache.sha256_bytes(contents[rel].encode("utf-8")))

    fp_before = gate_cache.compute_gate_fingerprint("none")
    contents["a.py"] = "original-a-CHANGED-ONE-BYTE"
    fp_after = gate_cache.compute_gate_fingerprint("none")
    assert fp_before["combined"] != fp_after["combined"], (
        "1ファイルの内容が変わればフィンガープリントも変わらなければならない")


@pytest.mark.skipif(not HAS_GATE_SPECIMEN_FIXTURES, reason=_GATE_SPECIMEN_SKIP_REASON)
def test_gate_fingerprint_changes_against_real_repo_on_byte_change(tmp_path, monkeypatch):
    """実際のcompute_gate_fingerprint()の集計対象に、tmp_pathの制御された
    1ファイルを追加注入して、内容変更で指紋が変わることを確認する
    (モックだけでなく実配線に近い経路でも確認する)。"""
    gate_cache = _import_gate_cache()
    real_gate_input_files = gate_cache.gate_input_files
    injected = tmp_path / "injected_extra_file.py"
    injected.write_text("v1", encoding="utf-8")

    def _with_injection():
        return real_gate_input_files() + [("injected_extra_file.py", str(injected))]

    monkeypatch.setattr(gate_cache, "gate_input_files", _with_injection)

    fp_before = gate_cache.compute_gate_fingerprint("none")
    injected.write_text("v2-one-byte-different", encoding="utf-8")
    fp_after = gate_cache.compute_gate_fingerprint("none")

    assert fp_before["combined"] != fp_after["combined"]

    # 統合確認: fp_beforeで登録したエントリはfp_after(=変更後)のキーでは
    # 引けない(異なるフィンガープリント=異なるキャッシュキー=構造的に別エントリ)。
    _isolate_gate_cache_dirs(gate_cache, tmp_path, monkeypatch)
    entry = {
        "schema": gate_cache.SCHEMA, "gate_name": "relgate_layers12",
        "fingerprint": fp_before["combined"], "fingerprint_components": fp_before,
        "recorded_at": "now", "source_run_id": "run_before", "gate_result_ok": True,
        "gate_result": {"ok": True}, "pak_hashes": {}, "intermediate_hashes": {},
    }
    gate_cache.save_cache_entry("relgate_layers12", fp_before["combined"], entry)
    assert gate_cache.load_cache_entry("relgate_layers12", fp_after["combined"]) is None, (
        "1バイト変更後のフィンガープリントでは、変更前に登録したエントリを引けてはならない")


@pytest.mark.skipif(not HAS_GATE_SPECIMEN_FIXTURES, reason=_GATE_SPECIMEN_SKIP_REASON)
def test_gate_fingerprint_changes_with_pak_declared_only():
    """--pak-declaredの値だけを変えても指紋は変わる(relgateの判定モード自体を
    変える要素であり、意図的に指紋へ折り込んである、compute_gate_fingerprint参照)。"""
    gate_cache = _import_gate_cache()
    fp_none = gate_cache.compute_gate_fingerprint("none")
    fp_expected = gate_cache.compute_gate_fingerprint("expected")
    assert fp_none["combined"] != fp_expected["combined"]


# --- 成果物実体化の破損検出(pak SHA256再検証でフル実行へフォールバック) ----------

def test_relgate_cache_hit_falls_back_on_corrupted_pak_artifact(tmp_path, monkeypatch):
    gate_cache = _import_gate_cache()
    _isolate_gate_cache_dirs(gate_cache, tmp_path, monkeypatch)
    relgate_mod = gate_cache._relgate_module()
    key = relgate_mod.DEFAULT_AVATARS[0]

    source_relgate_work = tmp_path / "source_run" / "relgate"
    build_dir = source_relgate_work / f"avatar_{key}" / "build"
    build_dir.mkdir(parents=True)
    pak_path = build_dir / f"relgateAvatar_{key}_PlayerSwap_P.pak"
    pak_path.write_bytes(b"genuine-pak-bytes")
    real_sha = gate_cache.sha256_file(str(pak_path))

    fingerprint = "deadbeef" * 8
    gate_cache.store_artifact_dir("relgate_layers12", fingerprint, str(source_relgate_work))
    entry = {
        "schema": gate_cache.SCHEMA, "gate_name": "relgate_layers12", "fingerprint": fingerprint,
        "fingerprint_components": {}, "recorded_at": "now", "source_run_id": "run_source",
        "gate_result_ok": True, "gate_result": {"ok": True, "rc": 0},
        "pak_hashes": {key: real_sha}, "intermediate_hashes": {},
    }
    gate_cache.save_cache_entry("relgate_layers12", fingerprint, entry)

    # キャッシュ本体(gate_cache\artifacts\...)側のpakを直接破損させる。
    cached_pak = os.path.join(
        gate_cache.artifact_dir_for("relgate_layers12", fingerprint),
        f"avatar_{key}", "build", f"relgateAvatar_{key}_PlayerSwap_P.pak")
    assert os.path.isfile(cached_pak)
    with open(cached_pak, "wb") as f:
        f.write(b"corrupted-bytes")

    report = DummyReport()
    work_dir = str(tmp_path / "run_new")
    result = gate_cache.try_use_cached_relgate(fingerprint, work_dir, report)

    assert result is None, "破損したキャッシュはヒットせず、フル実行へフォールバックしなければならない"
    assert not os.path.isdir(os.path.join(work_dir, "relgate")), (
        "破損検出後は実体化済みディレクトリを掃除しなければならない(半端な状態を残さない)")
    assert any("MISS" in line for line in report.lines), (
        "破損検出の経緯がreportへログされていなければならない")


# --- 正の対照: 破損していなければ普通にヒットする(負の対照だけで済ませず、
#     成功経路も壊れていないことを確認する) --------------------------------------

def test_relgate_cache_hit_succeeds_when_intact(tmp_path, monkeypatch):
    gate_cache = _import_gate_cache()
    _isolate_gate_cache_dirs(gate_cache, tmp_path, monkeypatch)
    relgate_mod = gate_cache._relgate_module()
    key = relgate_mod.DEFAULT_AVATARS[0]

    source_relgate_work = tmp_path / "source_run" / "relgate"
    build_dir = source_relgate_work / f"avatar_{key}" / "build"
    build_dir.mkdir(parents=True)
    pak_path = build_dir / f"relgateAvatar_{key}_PlayerSwap_P.pak"
    pak_path.write_bytes(b"genuine-pak-bytes")
    (source_relgate_work / "report.md").write_text("dummy relgate report", encoding="utf-8")
    real_sha = gate_cache.sha256_file(str(pak_path))

    report = DummyReport()
    relgate_result = {"name": "relgate_layers12", "ok": True, "rc": 0,
                       "relgate_work": str(source_relgate_work),
                       "report_path": str(source_relgate_work / "report.md")}
    fingerprint = "cafebabe" * 8
    gate_cache.register_relgate_cache(
        fingerprint, {"note": "unit-test"}, str(source_relgate_work),
        relgate_result, {key: real_sha}, "run_source", report)

    work_dir = str(tmp_path / "run_new")
    hit = gate_cache.try_use_cached_relgate(fingerprint, work_dir, report)

    assert hit is not None
    assert hit["ok"] is True
    assert hit["cache_hit"] is True
    assert hit["cache_fingerprint"] == fingerprint
    hit_pak = os.path.join(work_dir, "relgate", f"avatar_{key}", "build",
                            f"relgateAvatar_{key}_PlayerSwap_P.pak")
    assert os.path.isfile(hit_pak)
    assert gate_cache.sha256_file(hit_pak) == real_sha


def test_dist_smoke_cache_register_then_hit_roundtrip(tmp_path, monkeypatch):
    gate_cache = _import_gate_cache()
    _isolate_gate_cache_dirs(gate_cache, tmp_path, monkeypatch)

    source_work = tmp_path / "source_run" / "dist_smoke"
    source_work.mkdir(parents=True)
    (source_work / "report.md").write_text("dummy dist_smoke report", encoding="utf-8")

    report = DummyReport()
    dist_smoke_result = {"name": "dist_smoke", "ok": True, "rc": 0, "elapsed_sec": 12.3}
    fingerprint = "f00dbabe" * 8
    gate_cache.register_dist_smoke_cache(
        fingerprint, {"note": "unit-test"}, str(source_work), dist_smoke_result,
        "run_source", report)

    work_dir = str(tmp_path / "run_new")
    hit = gate_cache.try_use_cached_dist_smoke(fingerprint, work_dir, report)

    assert hit is not None
    assert hit["ok"] is True
    assert hit["cache_hit"] is True
    assert os.path.isfile(os.path.join(work_dir, "dist_smoke", "report.md"))


# --- FAILエントリは再利用されない(緑のエントリしか再利用しない、fail-closed) -----

def test_cache_entry_with_gate_result_not_ok_is_never_reused(tmp_path, monkeypatch):
    gate_cache = _import_gate_cache()
    _isolate_gate_cache_dirs(gate_cache, tmp_path, monkeypatch)

    fingerprint = "0badc0de" * 8
    entry = {
        "schema": gate_cache.SCHEMA, "gate_name": "dist_smoke", "fingerprint": fingerprint,
        "fingerprint_components": {}, "recorded_at": "now", "source_run_id": "run_fail",
        "gate_result_ok": False,  # 赤のエントリ(仮に存在したとして)
        "gate_result": {"ok": False, "rc": 1},
    }
    gate_cache.save_cache_entry("dist_smoke", fingerprint, entry)

    report = DummyReport()
    result = gate_cache.try_use_cached_dist_smoke(fingerprint, str(tmp_path / "run_new"), report)
    assert result is None, "gate_result_ok=Falseのエントリは絶対に再利用してはならない"


# --- dev#521: 読み取り専用ファイルを含むディレクトリのrmtree/複製 ----------------
# 実ログ(.devonly\docs\wp2214_release.err): dist_smokeキャッシュ内の.uassetが
# Windows上で読み取り専用属性を持ち、素のshutil.rmtree(onexc無し)が
# PermissionError [WinError 5]を出してrelease.py全体を異常終了させた。

def _make_dir_with_readonly_file(base_path):
    d = base_path / "target"
    d.mkdir()
    p = d / "readonly_file.uasset"
    p.write_bytes(b"dummy-uasset-bytes")
    os.chmod(str(p), stat.S_IREAD)
    return d


def test_rmtree_force_removes_directory_with_readonly_file(tmp_path):
    """_rmtree_force単体が、読み取り専用ファイルを含むディレクトリを
    削除できることを確認する(dev#521)。"""
    gate_cache = _import_gate_cache()
    d = _make_dir_with_readonly_file(tmp_path)
    gate_cache._rmtree_force(str(d))
    assert not d.exists()


def test_copy_tree_overwrites_destination_containing_readonly_file(tmp_path):
    """dev#521本体の回帰試験: _copy_treeがコピー先(dst_dir)に読み取り専用
    ファイルを含む場合でも上書きに成功することを確認する。修正前は
    shutil.rmtree(dst_dir)がPermissionErrorになっていた箇所。"""
    gate_cache = _import_gate_cache()
    src = tmp_path / "src"
    src.mkdir()
    (src / "new_content.txt").write_text("fresh copy", encoding="utf-8")
    dst = _make_dir_with_readonly_file(tmp_path)

    gate_cache._copy_tree(str(src), str(dst))

    assert (dst / "new_content.txt").is_file()
    assert not (dst / "readonly_file.uasset").exists(), (
        "旧内容(読み取り専用ファイル)が削除されずに残っている")


def test_copy_tree_negative_control_plain_rmtree_fails_on_readonly(tmp_path):
    """負の対照: onexcハンドラの無い素のshutil.rmtree(修正前のgate_cache.
    _copy_treeと同じ挙動)は、同条件でPermissionErrorになることを確認する。
    (このテストは_copy_tree自体ではなく素のshutil.rmtreeを直接使う。
    修正が本当に効いていることの反証可能性を担保するため。)"""
    import shutil
    gate_cache = _import_gate_cache()  # noqa: F841 (importの副作用確認のみ)
    d = _make_dir_with_readonly_file(tmp_path)
    with pytest.raises(PermissionError):
        shutil.rmtree(str(d))
    # 後始末(pytestのtmp_path掃除が読み取り専用のまま失敗しないように戻す)
    os.chmod(str(d / "readonly_file.uasset"), stat.S_IWRITE)


def test_register_dist_smoke_cache_warns_and_continues_when_copy_tree_fails(
        tmp_path, monkeypatch):
    """dev#521 仕様2: store_artifact_dir(_copy_tree)がOSErrorで失敗しても、
    register_dist_smoke_cacheは例外を送出せずWARNログを出して続行しなければ
    ならない(release.py本体を道連れにしない)。"""
    gate_cache = _import_gate_cache()
    _isolate_gate_cache_dirs(gate_cache, tmp_path, monkeypatch)

    def _always_fail(src_dir, dst_dir):
        raise PermissionError("模擬: 再試行してもなお失敗するケース")

    monkeypatch.setattr(gate_cache, "_copy_tree", _always_fail)

    source_work = tmp_path / "source_run" / "dist_smoke"
    source_work.mkdir(parents=True)
    (source_work / "report.md").write_text("dummy", encoding="utf-8")

    report = DummyReport()
    fingerprint = "d521d521" * 8
    # 例外を送出せず正常にreturnすることが仕様。
    gate_cache.register_dist_smoke_cache(
        fingerprint, {"note": "dev521-test"}, str(source_work),
        {"name": "dist_smoke", "ok": True, "rc": 0}, "run_d521", report)

    assert any("WARN" in line for line in report.lines)
    assert gate_cache.load_cache_entry("dist_smoke", fingerprint) is None, (
        "登録に失敗したのにエントリが保存されている(帳簿とジョブが不整合)")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
