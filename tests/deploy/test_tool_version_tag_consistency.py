"""app\\DiveToPalworld.cs の ToolVersion 定数が、各リリースgitタグの内容と
一致しているかを検査する回帰テスト(SignPath対応)。

## 背景

2026-07-31、第三者視点の初見監査が「公開リポジトリ pandrabox/Uchinoko の全9リリースタグ(v2.0.0〜v2.2.12)を
`git show <tag>:app/DiveToPalworld.cs` で確認すると、いずれも ToolVersion="v2.0.0" の
ままだ」と報告した。

再調査の結果、実際に配布されたビルド成果物(GitHub Releaseに添付されたzip内の
Uchinoko.exe、v2.2.6/v2.2.12で実物確認)は、いずれも埋め込み文字列が
"Uchinoko for Palworld v2.2.6" 等の正しいバージョンを名乗っており、
ユーザーに実害は無いことを確認した。

真の原因は app\\DiveToPalworld.cs 側のソース管理ではなく、**公開リポジトリ側で
git tagが実際にビルドされたコミットへ向けられていない**こと(release/deploy
パイプライン側の別問題。全タグが同一の初回同期コミットを指していた)と特定した。
このdev(開発)リポジトリ自身のタグは、release.py の create_release_commit_and_tag()
がToolVersionスタンプ直後にコミット・タグ付けを行うため、実際には全タグが
正しく一致している(本テストの `test_dev_repo_all_version_tags_match_toolversion`
で確認済み)。詳細な調査記録は開発側に保管している。

pub側のタグ修正は本テストの対象外(deploy.py/release.pyの改変が必要で、
本テストの権限外。別issueで追跡)。本テストは、少なくとも「単一の情報源
(ToolVersion定数)から両方が導出される」という不変条件がdevリポジトリ側で
壊れていないことを恒久的に保証する回帰ガードである。
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CS_PATH = "app/DiveToPalworld.cs"
# dev#532 D1(2026-08-01): バージョンの単一情報源をC#資産からapp_py側へ移行した
# (release.py.stamp_tool_version()/read_tool_version()参照)。過去のタグは
# CS_PATH側が正の情報源、D1以降の新しいタグはPY_PATH側が正の情報源になる
# ため、このテストは「どちらか一方が一致していればOK」という移行期対応の
# 判定にした(過去のタグを書き換えず、未来のタグにも追従できる)。
PY_PATH = "app_py/ui/main_window.py"
TAG_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
TOOLVERSION_RE = re.compile(r'const\s+string\s+ToolVersion\s*=\s*"([^"]+)"')
PY_TOOLVERSION_RE = re.compile(r'TOOL_VERSION\s*=\s*"([^"]+)"')


def _git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=30
    )


def _read_version_at_tag(repo_root, tag, path, pattern):
    show = _git(["show", "{}:{}".format(tag, path)], repo_root)
    if show.returncode != 0:
        return None
    m = pattern.search(show.stdout)
    return m.group(1) if m else None


def find_mismatched_version_tags(repo_root):
    """repo_root内の全 vX.Y.Z 形式タグについて、そのタグが指すコミットの
    バージョン定数(app/DiveToPalworld.cs の ToolVersion、または
    app_py/ui/main_window.py の TOOL_VERSION のいずれか)がタグ名と一致するかを
    確認する。dev#532 D1でスタンプ先がC#資産からapp_py側へ移った移行期対応の
    ため、**どちらか一方でも一致すればOK**とする(両方とも不一致/不在の場合のみ
    問題として報告する)。不一致の (tag, actual_cs_value, actual_py_value) の
    リストを返す。
    """
    r = _git(["tag", "--list"], repo_root)
    assert r.returncode == 0, "git tag --list failed: {}".format(r.stderr)
    tags = [t for t in r.stdout.splitlines() if TAG_VERSION_RE.match(t)]

    mismatches = []
    for tag in tags:
        actual_cs = _read_version_at_tag(repo_root, tag, CS_PATH, TOOLVERSION_RE)
        actual_py = _read_version_at_tag(repo_root, tag, PY_PATH, PY_TOOLVERSION_RE)
        if actual_cs == tag or actual_py == tag:
            continue
        mismatches.append((tag, actual_cs, actual_py))
    return mismatches


# --- 受入ゲート1: このdevリポジトリの実タグは全件一致(正の確認) --------------------

def test_dev_repo_all_version_tags_match_toolversion():
    mismatches = find_mismatched_version_tags(REPO_ROOT)
    assert mismatches == [], (
        "app\\DiveToPalworld.cs の ToolVersion がタグ名と一致しないタグがある"
        "(release.py の create_release_commit_and_tag() 経路を確認すること): {}"
        .format(mismatches)
    )


# --- 受入ゲート2: 検査関数自体が不一致を検知できることの負の対照 --------------------

def _write_cs(repo_dir, version):
    app_dir = repo_dir / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "DiveToPalworld.cs").write_text(
        'const string ToolVersion = "{}";\n'.format(version), encoding="utf-8"
    )


def _commit_all(repo_dir, message):
    r = _git(["add", "-A"], repo_dir)
    assert r.returncode == 0, r.stderr
    r = _git(["commit", "-q", "-m", message], repo_dir)
    assert r.returncode == 0, r.stderr


def _init_repo(repo_dir):
    _git(["init", "-q"], repo_dir)
    _git(["config", "user.email", "test@example.invalid"], repo_dir)
    _git(["config", "user.name", "Test"], repo_dir)


@pytest.fixture()
def tmp_git_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    return repo_dir


def test_checker_detects_frozen_version_regression(tmp_git_repo):
    """負の対照: 2026-07-31に公開リポジトリで実際に発見された症状——
    「v2.0.0だけが正しく、以降のリリースタグはすべて同一の(古い)コミットを
    指してしまっている」状態——を最小構成で再現し、検査関数がこれを
    不一致として検知することを確認する。
    """
    _init_repo(tmp_git_repo)
    _write_cs(tmp_git_repo, "v2.0.0")
    _commit_all(tmp_git_repo, "init")
    r = _git(["tag", "v2.0.0"], tmp_git_repo)
    assert r.returncode == 0, r.stderr

    # 後続タグを、ソースを更新しないまま同じコミットへ重ねて打つ
    # (=実際のバグと同じ「動かないタグ」状態の再現)。
    for stale_tag in ("v2.0.1", "v2.1.0", "v2.2.0"):
        r = _git(["tag", stale_tag], tmp_git_repo)
        assert r.returncode == 0, r.stderr

    mismatches = find_mismatched_version_tags(tmp_git_repo)
    mismatched_tags = sorted(t for t, _cs, _py in mismatches)
    assert mismatched_tags == ["v2.0.1", "v2.1.0", "v2.2.0"], mismatches
    for tag, actual_cs, actual_py in mismatches:
        assert actual_cs == "v2.0.0", (tag, actual_cs, actual_py)
        assert actual_py is None, (tag, actual_cs, actual_py)


def test_checker_passes_when_each_tag_is_correctly_stamped(tmp_git_repo):
    """正の対照: タグ作成の都度ToolVersionを正しくスタンプしてからコミット・
    タグ付けする(release.pyの実運用と同じ流儀)場合は、不一致が検出されない
    ことを確認する。
    """
    _init_repo(tmp_git_repo)
    _write_cs(tmp_git_repo, "v1.0.0")
    _commit_all(tmp_git_repo, "init")
    r = _git(["tag", "v1.0.0"], tmp_git_repo)
    assert r.returncode == 0, r.stderr

    for version in ("v1.0.1", "v1.1.0"):
        _write_cs(tmp_git_repo, version)
        _commit_all(tmp_git_repo, "bump to {}".format(version))
        r = _git(["tag", version], tmp_git_repo)
        assert r.returncode == 0, r.stderr

    assert find_mismatched_version_tags(tmp_git_repo) == []


# --- 受入ゲート3: dev#532 D1移行後(app_py側スタンプ)の正/負の対照 ------------------
# release.py.stamp_tool_version()が今後stampするのはPY_PATH側であり、CS_PATH側は
# もう更新されない。移行後のタグはPY_PATH側だけが一致していればOK(=CS_PATHは
# 過去の値のまま凍結されていて構わない)ことを確認する。

def _write_py(repo_dir, version):
    ui_dir = repo_dir / "app_py" / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "main_window.py").write_text(
        'TOOL_VERSION = "{}"\n'.format(version), encoding="utf-8"
    )


def test_checker_passes_when_only_py_side_is_stamped_after_migration(tmp_git_repo):
    """正の対照(dev#532 D1後の実運用形): CS_PATHは一度も存在しない/更新されない
    リポジトリでも、PY_PATH側だけが正しくタグ名と一致していれば問題なしと判定する。"""
    _init_repo(tmp_git_repo)
    _write_py(tmp_git_repo, "v2.3.0")
    _commit_all(tmp_git_repo, "init (py-only, post-migration)")
    r = _git(["tag", "v2.3.0"], tmp_git_repo)
    assert r.returncode == 0, r.stderr

    for version in ("v2.3.1", "v2.4.0"):
        _write_py(tmp_git_repo, version)
        _commit_all(tmp_git_repo, "bump to {}".format(version))
        r = _git(["tag", version], tmp_git_repo)
        assert r.returncode == 0, r.stderr

    assert find_mismatched_version_tags(tmp_git_repo) == []


def test_checker_still_detects_frozen_py_version_regression(tmp_git_repo):
    """負の対照: PY_PATH側運用へ移行した後も、「タグだけ進んでTOOL_VERSIONが
    凍結されたまま」という同種のバグ(dev#532 D1がまさに再発防止しようとしている
    もの)は引き続き検出できること。CS_PATHが存在しない(=CS側でも一致しえない)
    ケースであることが重要。"""
    _init_repo(tmp_git_repo)
    _write_py(tmp_git_repo, "v2.3.0")
    _commit_all(tmp_git_repo, "init (py-only)")
    r = _git(["tag", "v2.3.0"], tmp_git_repo)
    assert r.returncode == 0, r.stderr

    for stale_tag in ("v2.3.1", "v2.4.0"):
        r = _git(["tag", stale_tag], tmp_git_repo)
        assert r.returncode == 0, r.stderr

    mismatches = find_mismatched_version_tags(tmp_git_repo)
    mismatched_tags = sorted(t for t, _cs, _py in mismatches)
    assert mismatched_tags == ["v2.3.1", "v2.4.0"], mismatches
    for tag, actual_cs, actual_py in mismatches:
        assert actual_cs is None, (tag, actual_cs, actual_py)
        assert actual_py == "v2.3.0", (tag, actual_cs, actual_py)
