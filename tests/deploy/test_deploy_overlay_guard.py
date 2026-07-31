"""devtools\\deploy.py のoverlayガード(穴1/穴2対処)の単体テスト。

敵対的レビューが実証した2つの穴:
  穴1: overlayが持ち込んだファイルはEXCLUDE_TOPの事後検証を一度も通らない
       (overlayディレクトリ自体にdev専用ファイルが紛れ込んでも検知されない)
  穴2: overlayとホワイトリストが同じパスを取り合うと、overlayが無警告で勝つ
がdeploy.pyの実行経路(phase3_sync_whitelist/cmd_check)自身の中で塞がれていることを、
純粋関数レベルと「実行経路そのもの」レベルの両方で確認する。

安全制約: deploy.pyの実PUB_ROOT/OVERLAY_DIR/DEV_ROOT、実C:\\P\\Work\\UchinokoPub
には一切触れない。すべて一時ディレクトリへ monkeypatch した上で phase3_sync_whitelist の
ような実関数を直接呼ぶ。
"""
import os
import sys
from pathlib import Path

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent.parent / "devtools"
sys.path.insert(0, str(DEVTOOLS))

import deploy  # noqa: E402


class _NullReporter(object):
    def log(self, text):
        pass


def _build_fake_dev_root(root: Path):
    """phase3_sync_whitelist がabortせずに完走できる最小のDEV_ROOTを作る
    (WHITELIST_DIRS/WHITELIST_FILES/REQUIRED_SUBPATHS を満たすだけの空ツリー)。"""
    for d in deploy.WHITELIST_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    for rel in deploy.REQUIRED_SUBPATHS:
        target = root / rel
        target.mkdir(parents=True, exist_ok=True)
        (target / "placeholder.txt").write_text("x", encoding="utf-8")
    for f in deploy.WHITELIST_FILES:
        (root / f).write_text("placeholder\n", encoding="utf-8")


@pytest.fixture
def fake_trees(tmp_path, monkeypatch):
    """DEV_ROOT/PUB_ROOT/OVERLAY_DIR をすべて偽の一時ディレクトリへ差し替える。
    実リポジトリ・実Pubクローンには一切触れない。"""
    dev_root = tmp_path / "dev"
    pub_root = tmp_path / "pub"
    overlay_dir = tmp_path / "overlay"
    dev_root.mkdir()
    pub_root.mkdir()
    # overlay_dirはここでは作らない(各テストで必要な内容だけを用意する。
    # overlay_relative_files()は未存在ディレクトリに対して空集合を返す仕様)。

    _build_fake_dev_root(dev_root)

    monkeypatch.setattr(deploy, "DEV_ROOT", str(dev_root))
    monkeypatch.setattr(deploy, "PUB_ROOT", str(pub_root))
    monkeypatch.setattr(deploy, "OVERLAY_DIR", str(overlay_dir))
    return dev_root, pub_root, overlay_dir


# --- 受入ゲート1: 負の対照(overlayに偽のci.ymlを混入させると検査が落ちる) -------------

def test_fake_ci_yml_in_overlay_detected_by_pure_check(fake_trees):
    """WP13の再現条件そのもの: devtools\\pub_overlay\\.github\\workflows\\ 配下に、
    dev専用ワークフローと同名の偽ファイルを置く。find_overlay_unexpected_files が
    OVERLAY_ALLOWED_FILES外として検知することを確認する(純粋関数レベル)。"""
    _, _, overlay_dir = fake_trees
    workflows = overlay_dir / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: dev-only-ci-workflow-that-should-never-reach-pub\n", encoding="utf-8")
    # 正規のoverlayファイルも同時に混ぜて「一部だけ既知」というケースも検証する。
    (workflows / "build.yml").write_text("name: build\n", encoding="utf-8")

    unexpected = deploy.find_overlay_unexpected_files(str(overlay_dir))
    assert unexpected == [".github/workflows/ci.yml"], unexpected


def test_fake_ci_yml_in_overlay_aborts_phase3(fake_trees):
    """WP13が実証した『overlay適用後の再検証が無い』穴1が、phase3_sync_whitelist
    ―― deploy.py run の実際の実行経路そのもの ―― の中で塞がれていることを確認する。
    (「検査ロジックはあるが実行経路に効いていない」という穴1の本質を再発させないための
    テスト。純粋関数だけでなく phase3_sync_whitelist を直接呼ぶ。)"""
    _, _, overlay_dir = fake_trees
    workflows = overlay_dir / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: dev-only-ci-workflow-that-should-never-reach-pub\n", encoding="utf-8")

    with pytest.raises(deploy.DeployAbort) as excinfo:
        deploy.phase3_sync_whitelist(_NullReporter())
    msg = str(excinfo.value)
    assert ".github/workflows/ci.yml" in msg, msg

    # コピー前に落ちているはずなので、偽PUB_ROOTへdev専用ファイルが実際に
    # 渡っていないことも確認する(「落ちたが実は既にコピーされていた」を防ぐ)。
    pub_root = Path(deploy.PUB_ROOT)
    assert not (pub_root / ".github" / "workflows" / "ci.yml").exists()


def test_deploy_check_cli_fails_on_fake_overlay_file(tmp_path, monkeypatch):
    """`python devtools\\deploy.py check` 相当(cmd_check関数)でも、overlayへの
    混入がNG判定されることを確認する(dry-runなのでPub/DEV_ROOTには触れない。
    --root は既存のDEV_ROOTをそのまま検証対象にし、overlay側だけ差し替える)。"""
    overlay_dir = tmp_path / "overlay"
    workflows = overlay_dir / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: fake\n", encoding="utf-8")

    monkeypatch.setattr(deploy, "OVERLAY_DIR", str(overlay_dir))

    class _Args(object):
        root = deploy.DEV_ROOT

    rc = deploy.cmd_check(_Args())
    assert rc == 1


# --- 受入ゲート2: 負の対照(overlayとwhitelistのパス衝突) -----------------------------

def test_overlay_whitelist_collision_detected_by_pure_check(fake_trees):
    """WP13の再現条件そのもの: devtools\\pub_overlay\\ 配下に、WHITELIST_FILES と
    同じ相対パス(README.md)のファイルを置く。find_overlay_whitelist_collisions が
    交差として検知することを確認する(純粋関数レベル)。"""
    dev_root, _, overlay_dir = fake_trees
    overlay_dir.mkdir(exist_ok=True)
    (overlay_dir / "README.md").write_text("OVERLAY OVERRIDE CONTENT\n", encoding="utf-8")

    collisions = deploy.find_overlay_whitelist_collisions(str(dev_root), str(overlay_dir))
    assert collisions == ["README.md"], collisions


def test_overlay_whitelist_collision_aborts_phase3(fake_trees, monkeypatch):
    """穴2がphase3_sync_whitelistの実行経路の中で塞がれていることを確認する。
    README.mdをOVERLAY_ALLOWED_FILESへ一時的に加え、『既知集合外』チェック(穴1対策)
    ではなく『パス衝突』チェック(穴2対策)そのものが発火することを切り分ける。"""
    _, pub_root, overlay_dir = fake_trees
    overlay_dir.mkdir(exist_ok=True)
    (overlay_dir / "README.md").write_text("OVERLAY OVERRIDE CONTENT\n", encoding="utf-8")

    monkeypatch.setattr(
        deploy, "OVERLAY_ALLOWED_FILES", frozenset(deploy.OVERLAY_ALLOWED_FILES | {"README.md"}))

    with pytest.raises(deploy.DeployAbort) as excinfo:
        deploy.phase3_sync_whitelist(_NullReporter())
    msg = str(excinfo.value)
    assert "README.md" in msg, msg

    # whitelistコピーで正規のREADME.mdは既に書き込まれているはずだが、
    # DeployAbortにより overlay の上書きコピーへは進んでいないことを確認する
    # (衝突検査が _sync_overlay の「前」で発火している証拠)。
    readme = pub_root / "README.md"
    assert readme.is_file()
    assert readme.read_text(encoding="utf-8") == "placeholder\n"


# --- 受入ゲート3: 正の対照(現在の正しいoverlayの内容では検査が通る) -------------------

def test_current_real_overlay_passes_unexpected_files_check():
    """実際の devtools\\pub_overlay\\ (monkeypatch無し、本物)がOVERLAY_ALLOWED_FILESと
    一致していることを確認する(『常に落ちる検査』を作っていないことの証明)。"""
    unexpected = deploy.find_overlay_unexpected_files()
    assert unexpected == [], unexpected


def test_current_real_overlay_has_no_whitelist_collision():
    """実際のDEV_ROOT/OVERLAY_DIR(monkeypatch無し、本物)でoverlayとホワイトリストの
    パス衝突が無いことを確認する。"""
    collisions = deploy.find_overlay_whitelist_collisions()
    assert collisions == [], collisions


def test_deploy_check_cli_passes_on_real_repo():
    """`python devtools\\deploy.py check` 相当(cmd_check関数)が、実リポジトリの
    現在の分類定義・overlay内容でPASS(戻り値0)することを確認する。"""

    class _Args(object):
        root = None

    rc = deploy.cmd_check(_Args())
    assert rc == 0
