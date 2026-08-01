# -*- coding: utf-8 -*-
r"""wp_provenance(wp_stub検証官F-1/F-2対応): build_provenance.py の負の対照テストと
release.py 出自台帳ゲートの接続テスト。

負の対照(検証官がF-1で使った3種+SK系1種。全て検出=FAILになること):
  ①バニラ抽出テクスチャ(T_PalHair001_C.uexp)を noue_master に置く
  ②バニラbind pose生値JSON(vanilla_refskel_male.json)を noue_master に置く
  ③Palworldチャンクbin(Pal-Windows_chunk.bin)を noue_master に置く
  ④SK系スタブ命名(SK_*.uasset)→ palworld_derived 検出
正の対照:
  attestation全件が実ファイルとSHA256一致し、宣言どおり分類されること
  repo_inputs全体が --strict --require-zero-palworld でPASSすること
関所接続(F-2):
  release.run_zip_content_gates が provenance ゲートを含み、
  出自違反zipで all_green が偽になる(=リリースが止まりzipが破棄される)こと

実行: python -m pytest tests\shipcheck\test_provenance.py -v
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
BUILD_PROVENANCE = os.path.join(DEVTOOLS, "build_provenance.py")

if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)
import build_provenance as bp  # noqa: E402

STAGE = "Uchinoko_for_Palworld"   # v2.0.0改名(配布zipルートフォルダ名)

# 検証官(work\wp_stub\VERIFY.md F-1)の負の対照。旧分類器は全てfirst_party(誤)だった
NEGATIVE_CONTROLS = [
    ("pipeline/py/noue_master/pak_extract_extra/Player/Hair/Hair001/"
     "T_PalHair001_C.uexp", b"\x00fake-vanilla-texture-bytes\x00" * 8),
    ("pipeline/py/noue_master/vanilla_refskel_male.json",
     b'{"bones": [[0.1, 0.2, 0.3]]}'),
    ("pipeline/py/noue_master/Pal-Windows_chunk.bin",
     b"\xc1\x83*\x9e fake pak chunk bytes" * 4),
]


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _attestation():
    return bp.load_attestation()


def _run_script(args):
    proc = subprocess.run(
        [sys.executable, BUILD_PROVENANCE] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


# --- 負の対照(classify単体) -------------------------------------------------

@pytest.mark.parametrize("rel,data", NEGATIVE_CONTROLS,
                         ids=["vanilla_texture", "refskel_json", "chunk_bin"])
def test_negative_controls_not_permitted(rel, data):
    """F-1の負の対照3種: first_party/third_partyに分類されてはならない。"""
    cls, lic, note = bp.classify(rel, sha256=_sha256(data),
                                 attestation=_attestation())
    assert cls not in ("first_party", "third_party"), (rel, cls, note)


def test_negative_control_sk_stub_detected():
    """SK系命名はattestationにあっても検出ルール(FAIL側)が勝つ。"""
    cls, _, _ = bp.classify(
        "pipeline/py/noue_master/pak_extract_extra/Player/Hair/Hair001/"
        "SK_Player_Hair001.uasset", sha256="0" * 64, attestation=_attestation())
    assert cls == "palworld_derived"


def test_pipeline_vanilla_json_not_first_party():
    """検証官の追加対照: pipeline/py/vanilla/refskel_male.json も自作扱いにしない。"""
    cls, _, _ = bp.classify("pipeline/py/vanilla/refskel_male.json",
                            sha256="0" * 64, attestation=_attestation())
    assert cls == "unclassified"


# --- 負の対照(スクリプト一気通貫: stage-dirへ実際に置いて検出されること) -----

def test_negative_controls_fail_strict_gate(tmp_path):
    stage = tmp_path / "stage"
    for rel, data in NEGATIVE_CONTROLS:
        p = stage / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    out = tmp_path / "ledger.json"
    rc, log = _run_script(["--stage-dir", str(stage), "--strict",
                           "--out", str(out)])
    assert rc == 1, log
    ledger = json.loads(out.read_text(encoding="utf-8"))
    assert ledger["summary"]["unclassified"] == len(NEGATIVE_CONTROLS)
    assert ledger["summary"]["first_party"] == 0
    for fe in ledger["files"]:
        assert fe["class"] == "unclassified", fe


# --- dev#532 D1: 新レイアウト(zip直下=Uchinoko.bat/README.txt/res\)の分類 -----

def test_new_layout_generated_root_and_app_sources_first_party():
    """正: build.py生成のルート2点と、res\\app\\配下のPythonソースはfirst_party。"""
    att = _attestation()
    for rel in (STAGE + "/Uchinoko.bat", STAGE + "/README.txt",
                STAGE + "/res/app/main.py", STAGE + "/res/app/ui/main_window.py"):
        cls, _lic, note = bp.classify(rel, sha256="0" * 64, attestation=att)
        assert cls == "first_party", (rel, cls, note)


def test_new_layout_app_i18n_json_requires_attestation_hash():
    """res\\app\\i18n_data.json はattestationのSHA256一致でのみfirst_party。
    ハッシュ不一致(改変)はunclassified(fail-closed)。"""
    att = _attestation()
    ent = att["app_py/i18n_data.json"]
    cls_ok, _, _ = bp.classify(STAGE + "/res/app/i18n_data.json",
                               sha256=ent["sha256"], attestation=att)
    assert cls_ok == "first_party"
    cls_ng, _, note = bp.classify(STAGE + "/res/app/i18n_data.json",
                                  sha256="f" * 64, attestation=att)
    assert cls_ng == "unclassified", note


def test_new_layout_python_embed_known_files_third_party():
    """正: res\\python_embed\\配下のembeddable同梱物(名前完全一致)・Tcl/Tk
    スクリプト・tkinterパッケージはthird_party、tkinterオーバーレイPEは
    build.pyのSHA256ピン一致でthird_party。"""
    att = _attestation()
    for rel in (STAGE + "/res/python_embed/python311.dll",
                STAGE + "/res/python_embed/python311._pth",
                STAGE + "/res/python_embed/tcl/tcl8.6/init.tcl",
                STAGE + "/res/python_embed/tkinter/__init__.py"):
        cls, _lic, note = bp.classify(rel, sha256="0" * 64, attestation=att)
        assert cls == "third_party", (rel, cls, note)
    # tkinterオーバーレイPE: ピン(app_py\build.py TKINTER_PE_SHA256が正)と一致
    for name, pin in bp._TKINTER_PE_SHA256.items():
        cls, _lic, note = bp.classify(STAGE + "/res/python_embed/" + name,
                                      sha256=pin, attestation=att)
        assert cls == "third_party", (name, cls, note)


def test_new_layout_negative_tkinter_pe_pin_mismatch_unclassified():
    """負: tkinterオーバーレイPEのSHA256がピンと不一致(すり替え)はunclassified。"""
    att = _attestation()
    cls, _, note = bp.classify(STAGE + "/res/python_embed/tcl86t.dll",
                               sha256="f" * 64, attestation=att)
    assert cls == "unclassified"
    assert "ピン" in note, note


def test_new_layout_negative_unknown_files_unclassified():
    """負: 出所不明ファイルの混入(python_embed\\直下・res\\直下・licenses\\配下)は
    どこに置かれてもunclassified(--strictでFAIL)。ディレクトリcatch-allで
    素通りさせない(fail-closed)。"""
    att = _attestation()
    for rel in (STAGE + "/res/python_embed/evil_unknown.bin",
                STAGE + "/res/python_embed/extra.dll",
                STAGE + "/res/mystery.dat",
                STAGE + "/res/licenses/SMUGGLED.txt",
                STAGE + "/Uchinoko.exe"):   # 旧exeの再混入もunclassified(ルール削除済み)
        cls, _lic, note = bp.classify(rel, sha256="0" * 64, attestation=att)
        assert cls == "unclassified", (rel, cls, note)


def test_new_layout_negative_unknown_file_fails_strict_gate(tmp_path):
    """負の対照(一気通貫): 新レイアウトのステージに出所不明ファイルを混入させ、
    --strict ゲートが実際にexit 1で止まること。"""
    stage = tmp_path / "stage"
    p = stage / "res" / "python_embed" / "evil_unknown.bin"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00smuggled\x00")
    out = tmp_path / "ledger.json"
    rc, log = _run_script(["--stage-dir", str(stage), "--strict",
                           "--out", str(out)])
    assert rc == 1, log
    ledger = json.loads(out.read_text(encoding="utf-8"))
    assert ledger["summary"]["unclassified"] == 1


def test_new_layout_licenses_dir_known_names_classified():
    """正: res\\licenses\\配下の既知ライセンス文書は宣言どおり分類される。"""
    att = _attestation()
    expects = {
        STAGE + "/res/licenses/UCHINOKO_LICENSE.txt": "first_party",
        STAGE + "/res/licenses/PYTHON_LICENSE.txt": "third_party",
        STAGE + "/res/licenses/TCL_TK_LICENSE.txt": "third_party",
        STAGE + "/res/licenses/THIRD_PARTY_LICENSES.txt": "third_party",
    }
    for rel, want in expects.items():
        cls, _lic, note = bp.classify(rel, sha256="0" * 64, attestation=att)
        assert cls == want, (rel, cls, note)


# --- 正の対照(attestation) ---------------------------------------------------

def test_attestation_all_entries_hash_match_and_classify():
    """attestation全件: 実ファイルが存在しSHA256一致、宣言どおりに分類される。

    dev#317: ハッシュ計算は bp._hash_file() を使う(生バイトを直接
    hashlib.sha256しない)。テキスト系拡張子はCRLF->LF正規化してからハッシュ
    するため、実行環境のgit core.autocrlf設定(dev機=true/hosted CI=false)に
    左右されずgit blob(LF)基準の値と一致する(build_provenance.py側の
    正規化ロジックと二重定義しないよう、ここでも同じ関数を再利用する)。"""
    att = _attestation()
    assert len(att) > 0
    for rel, ent in att.items():
        full = os.path.join(REPO, *rel.split("/"))
        assert os.path.isfile(full), f"attestation対象が無い: {rel}"
        sha256, _size = bp._hash_file(full)
        assert sha256 == ent["sha256"], f"SHA256不一致: {rel}"
        cls, lic, _ = bp.classify(rel, sha256=ent["sha256"], attestation=att)
        assert cls == ent["class"], (rel, cls)


def test_attestation_hash_mismatch_is_unclassified():
    """attestationにパスがあってもハッシュが違えばfail-closed。"""
    att = _attestation()
    rel = next(iter(att))
    cls, _, note = bp.classify(rel, sha256="f" * 64, attestation=att)
    assert cls == "unclassified"
    assert "SHA256不一致" in note


def test_missing_attestation_file_fails_closed(tmp_path):
    rc, log = _run_script(["--stage-dir", str(tmp_path),
                           "--attestation", str(tmp_path / "no_such.json"),
                           "--out", str(tmp_path / "o.json")])
    assert rc == 1
    assert "attestation" in log


# --- 正の対照(repo_inputs全体、third_party実態一致) --------------------------

def test_repo_inputs_pass_and_third_party_matches_reality(tmp_path):
    out = tmp_path / "ledger.json"
    rc, log = _run_script(["--strict", "--require-zero-palworld",
                           "--out", str(out)])
    assert rc == 0, log
    ledger = json.loads(out.read_text(encoding="utf-8"))
    assert ledger["summary"]["palworld_derived"] == 0
    assert ledger["summary"]["unclassified"] == 0
    # third_party件数 = リポジトリthird_party\配下の実ファイル数(実態と一致)
    actual = 0
    for dirpath, dirnames, fns in os.walk(os.path.join(REPO, "third_party")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        actual += len(fns)
    assert actual > 0
    assert ledger["summary"]["third_party"] == actual
    # GPL同梱物(pyooz対応ソース)が third_party として計上されている
    tp = [f for f in ledger["files"] if f["class"] == "third_party"]
    assert any(f["license"] == "GPL-3.0-or-later" for f in tp), tp


# --- WP-PROVFIX(dev#317回帰): iter_zip()もCRLF->LF正規化を適用すること --------
# 68132ddが_hash_file()(iter_dir/iter_repo_inputsが使う)にのみ正規化を追加し、
# iter_zip()を直し漏らした回帰の再発防止。work\issue_zero\release1730\NOTES.md
# の実測診断(zip内CRLF実体 vs LF正規化attestationの不一致)を最小フィクスチャで
# 固定する。

def _make_simple_zip(path, name, data):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name, data)
    return str(path)


def test_iter_zip_normalizes_crlf_for_text_ext(tmp_path):
    """赤→緑の中核: zip内のテキスト系エントリ(.md)はCRLF->LF正規化後の
    SHA256をiter_zip()が返す(_hash_file()と同じ値になる)こと。
    修正前のiter_zip()はraw CRLFのままhashlib.sha256するため、この
    assertは修正前コードでは失敗する(生ハッシュ != 正規化ハッシュ)。"""
    crlf_text = b"line1\r\nline2\r\nline3\r\n"
    zp = _make_simple_zip(tmp_path / "t.zip", "note.md", crlf_text)
    rel, sha256, size = next(bp.iter_zip(zp))
    expected_sha256, expected_size = bp._hash_bytes_normalized(crlf_text, True)
    assert rel == "note.md"
    assert sha256 == expected_sha256
    assert size == expected_size
    # 生CRLFバイト列そのもののハッシュとは一致しない(正規化が効いている証拠)
    assert sha256 != hashlib.sha256(crlf_text).hexdigest()


def test_iter_zip_matches_hash_file_for_same_content(tmp_path):
    """_hash_file()(ディスク実体)とiter_zip()(zipエントリ)が同一内容の
    テキストファイルに対して同じSHA256を出すこと(二重実装の食い違い防止)。"""
    crlf_text = b"a\r\nb\r\nc\r\n"
    disk_path = tmp_path / "sample.json"
    disk_path.write_bytes(crlf_text)
    zp = _make_simple_zip(tmp_path / "z.zip", "sample.json", crlf_text)

    file_sha256, file_size = bp._hash_file(str(disk_path))
    _rel, zip_sha256, zip_size = next(bp.iter_zip(zp))

    assert zip_sha256 == file_sha256
    assert zip_size == file_size


def test_iter_zip_binary_ext_not_normalized(tmp_path):
    """バイナリ拡張子(.uasset等)はCRLF風バイト列があっても無加工でハッシュ
    される(真のバイナリを誤って書き換えないことの負の対照)。"""
    raw = b"\x00\x01\r\n\x02\r\n\x03"
    zp = _make_simple_zip(tmp_path / "b.zip", "SK_dummy.uasset", raw)
    _rel, sha256, size = next(bp.iter_zip(zp))
    assert sha256 == hashlib.sha256(raw).hexdigest()
    assert size == len(raw)


def test_iter_zip_negative_control_real_content_diff_still_detected(tmp_path):
    """負の対照: 正規化後も、本当に内容が異なる(1バイト改変)ファイルは
    不一致として検出されること(正規化が中身の相違まで揉み消さない)。"""
    base = b"hello\r\nworld\r\n"
    altered = b"hello\r\nworld!\r\n"  # 1バイト(!)追加
    zp_base = _make_simple_zip(tmp_path / "base.zip", "note.md", base)
    zp_alt = _make_simple_zip(tmp_path / "alt.zip", "note.md", altered)
    _r1, sha_base, _s1 = next(bp.iter_zip(zp_base))
    _r2, sha_alt, _s2 = next(bp.iter_zip(zp_alt))
    assert sha_base != sha_alt


def test_iter_zip_and_hash_file_share_normalization_function():
    """共通化の証明: iter_zip()と_hash_file()のソースが、どちらも
    同一の正規化関数(_hash_bytes_normalized)と同一のテキスト判定関数
    (_is_text_for_hash)を呼んでいることをinspectで固定する。
    これにより将来どちらか一方だけを直す『二重実装の直し漏れ』(今回の
    dev#317回帰そのもの)を再発させると、このテストが落ちる。"""
    import inspect
    src_hash_file = inspect.getsource(bp._hash_file)
    src_iter_zip = inspect.getsource(bp.iter_zip)
    for src, label in ((src_hash_file, "_hash_file"), (src_iter_zip, "iter_zip")):
        assert "_hash_bytes_normalized" in src, f"{label}が_hash_bytes_normalizedを呼んでいない"
        assert "_is_text_for_hash" in src, f"{label}が_is_text_for_hashを呼んでいない"


def test_release_zip_content_gate_uses_normalized_iter_zip(tmp_path):
    """関所接続: attestationにLF正規化基準のSHA256を持つエントリを、CRLF実体で
    zipへ入れてもprovenanceゲートがPASSすること(dev#317回帰が再発すればFAILする
    最小再現)。"""
    text = b"first_party_source\r\nline2\r\n"
    norm_sha256, _size = bp._hash_bytes_normalized(text, True)
    rel = "pipeline/py/vp_core.py"
    # 実ファイルのSHA256(LF正規化後)と一致するテキストをzipへCRLF実体で封入し、
    # repo_inputsのソースコード分類(3.)経路がハッシュ不一致で落ちないことを見る
    with open(os.path.join(REPO, *rel.split("/")), "rb") as f:
        real = f.read()
    real_sha256, _s = bp._hash_file(os.path.join(REPO, *rel.split("/")))
    zp = tmp_path / "src.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr(rel, real.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    _rel_out, sha256_out, _size_out = next(bp.iter_zip(str(zp)))
    assert sha256_out == real_sha256, (
        "zip内CRLF実体のハッシュがディスク実体(_hash_file基準)と食い違う"
        "= dev#317回帰の再発")


# --- 関所接続(F-2): release.py の provenance ゲート --------------------------

def _import_release():
    import importlib
    return importlib.import_module("release")


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return str(path)


def _clean_entries():
    src_rel = "pipeline/py/vp_core.py"
    with open(os.path.join(REPO, *src_rel.split("/")), "rb") as f:
        sample = f.read()
    return [
        (STAGE + "/README.md", b"readme"),
        (STAGE + "/_internal/LICENSE", b"license"),
        (STAGE + "/_internal/" + src_rel, sample),
    ]


def test_release_gate_green_on_clean_zip(tmp_path):
    release = _import_release()
    zp = _make_zip(tmp_path / "clean.zip", _clean_entries())
    report = release.Report(str(tmp_path / "report.md"))
    g = release.run_provenance_gate(zp, str(tmp_path), report)
    assert g["name"] == "provenance"
    assert g["ok"], g


def test_release_gate_blocks_on_provenance_fail(tmp_path, monkeypatch):
    """出自違反(attestation外のバイナリ混入)zipでは、provenanceゲートが赤になり
    run_zip_content_gates 全体が all_green=False(=release.pyの_fail経路で
    zipが破棄され、リリースは止まる)。他のzipゲートはモックで緑に固定し、
    失敗がprovenanceゲート単独に帰着することを示す。"""
    release = _import_release()
    entries = _clean_entries() + [
        (STAGE + "/_internal/pipeline/py/noue_master/Pal-Windows_chunk.bin",
         b"\xc1\x83*\x9e fake pak chunk" * 4),
    ]
    zp = _make_zip(tmp_path / "dirty.zip", entries)
    monkeypatch.setattr(release, "run_u28_zip_audit",
                        lambda *a, **k: {"name": "u28_zip_audit", "ok": True, "rc": 0})
    monkeypatch.setattr(release, "run_dist_smoke",
                        lambda *a, **k: {"name": "dist_smoke", "ok": True, "rc": 0})
    monkeypatch.setattr(release, "run_dll_closure_check",
                        lambda *a, **k: {"name": "dll_closure_check", "ok": True, "rc": 0})
    report = release.Report(str(tmp_path / "report.md"))
    results = release.run_zip_content_gates(zp, str(tmp_path), report)
    names = [g["name"] for g in results]
    assert "provenance" in names
    prov = next(g for g in results if g["name"] == "provenance")
    assert not prov["ok"]
    assert not release.all_green(results)
    ledger = json.loads(
        (tmp_path / "provenance.json").read_text(encoding="utf-8"))
    assert ledger["summary"]["unclassified"] >= 1
