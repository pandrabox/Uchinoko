# -*- coding: utf-8 -*-
"""U34受入ゲートG1: vp_provenance.write_build_provenance()の自動テスト。

実行: python test_vp_provenance.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_provenance  # noqa: E402
import live_template  # noqa: E402

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(label, cond, detail=""):
    if cond:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} {detail}")
        failures.append(label)


def test_write_build_provenance():
    tmp_dir = tempfile.mkdtemp(prefix="vp_provenance_test_")
    out_pak = os.path.join(tmp_dir, "Dummy_PlayerSwap_P.pak")
    dummy_bytes = b"dummy pak content for U34 provenance test\x00\x01\x02" * 1000
    with open(out_pak, "wb") as f:
        f.write(dummy_bytes)

    out_path = vp_provenance.write_build_provenance(
        tmp_dir, out_pak, "Dummy", "dev_fallback", REPO_DIR)

    check("write_build_provenance: file exists at returned path",
          os.path.exists(out_path), out_path)

    with open(out_path, encoding="utf-8") as f:
        data = json.load(f)

    expected_keys = {
        "git_commit", "git_dirty", "template_build_version", "avatar_name",
        "engine_mode", "build_time", "pak_filename", "pak_sha1", "template_source",
    }
    check("all 9 keys are present", expected_keys.issubset(data.keys()),
          str(sorted(data.keys())))

    want_commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_DIR,
        capture_output=True, text=True, check=True).stdout.strip()
    check("git_commit exactly matches git rev-parse --short HEAD",
          data.get("git_commit") == want_commit,
          f"got={data.get('git_commit')} want={want_commit}")

    want_sha1 = hashlib.sha1(dummy_bytes).hexdigest()
    check("pak_sha1 exactly matches the SHA1 of the dummy file contents",
          data.get("pak_sha1") == want_sha1,
          f"got={data.get('pak_sha1')} want={want_sha1}")

    check("template_build_version matches live_template.TEMPLATE_BUILD_VERSION",
          data.get("template_build_version") == live_template.TEMPLATE_BUILD_VERSION,
          f"got={data.get('template_build_version')} "
          f"want={live_template.TEMPLATE_BUILD_VERSION}")

    check("avatar_name is passed through from the argument", data.get("avatar_name") == "Dummy")
    check("engine_mode is fixed to noue", data.get("engine_mode") == "noue")
    check("pak_filename matches the basename",
          data.get("pak_filename") == os.path.basename(out_pak))
    check("template_source is passed through from the argument", data.get("template_source") == "dev_fallback")
    check("git_dirty is a bool", isinstance(data.get("git_dirty"), bool))


def test_write_build_provenance_git_fallback():
    """U41: repo_dirがgitリポジトリでない場合(配布zip展開先を模擬)でも
    raiseせず、git_commit="unknown"・git_dirty=None(JSON null)で
    JSONが書かれることを確認する。"""
    tmp_dir = tempfile.mkdtemp(prefix="vp_provenance_test_out_")
    no_git_dir = tempfile.mkdtemp(prefix="vp_provenance_test_nogit_")
    out_pak = os.path.join(tmp_dir, "Dummy_PlayerSwap_P.pak")
    dummy_bytes = b"dummy pak content for U41 git-fallback test\x00\x01\x02" * 1000
    with open(out_pak, "wb") as f:
        f.write(dummy_bytes)

    # no_git_dir配下に.gitが存在しないこと(gitリポジトリでないこと)を前提として確認
    check("simulated env: no_git_dir has no .git",
          not os.path.exists(os.path.join(no_git_dir, ".git")), no_git_dir)

    out_path = vp_provenance.write_build_provenance(
        tmp_dir, out_pak, "Dummy", "dev_fallback", no_git_dir)

    check("file is written without raising even with no git",
          os.path.exists(out_path), out_path)

    with open(out_path, encoding="utf-8") as f:
        data = json.load(f)

    check("no-git env: git_commit falls back to 'unknown'",
          data.get("git_commit") == "unknown", str(data.get("git_commit")))
    check("no-git env: git_dirty falls back to None (JSON null)",
          data.get("git_dirty") is None, str(data.get("git_dirty")))
    check("pak_sha1 is still required in a no-git env (non-git fields do not degrade)",
          data.get("pak_sha1") == hashlib.sha1(dummy_bytes).hexdigest())


def main():
    test_write_build_provenance()
    test_write_build_provenance_git_fallback()

    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
