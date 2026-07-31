"""devtools\\pub_overlay\\.github\\workflows\\build.yml (公開repo用CIビルドワークフロー)の
取得物固定の静的検査。

SignPathのOrigin Verificationが懸念する「ビルドスクリプトが任意のソフトウェアを
取得しうる」への対策として、build.ymlは以下を固定している:
  1. pyooz (ooz.pyd) の取得: バージョン固定 + 取得後のSHA256検証
  2. python.org embeddable zip (python3.dll) の取得: SHA256検証
  3. 使用しているGitHub Actions(actions/checkout, actions/upload-artifact)を
     浮動タグではなくコミットSHAで固定

ここでの検査はYAML構造として壊れていないか・固定に必要な要素が揃っているかを機械的に
検査する(実行を伴わない静的検査)。実際に取得ステップを実行してのEXIT=0/EXIT=1の実証
(正の対照・負の対照)は開発側の記録に残っている
(ローカルでbuild.ymlの run: ブロックを逐語コピーして、正しいハッシュではEXIT=0、
1文字破壊した偽ハッシュではEXIT=1になることを実機確認済み)。
"""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "devtools" / "pub_overlay" / ".github" / "workflows" / "build.yml"
)

# 40桁16進 = gitのコミットSHA(短縮SHAは意図的に許容しない。曖昧さの余地を無くすため)
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _load_raw_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_yaml():
    return yaml.safe_load(_load_raw_text())


def _steps():
    data = _load_yaml()
    return data["jobs"]["build"]["steps"]


def _uses_action_refs(text: str):
    """`uses: actions/<name>@<ref>` の <name> と <ref> を全件抽出する。
    コメント行(#で始まる行)は除外する(署名雛形ブロック内のuses:を誤検出しないため)。
    """
    refs = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = re.search(r"uses:\s*actions/([\w-]+)@([0-9a-zA-Z.]+)", line)
        if m:
            refs.append((m.group(1), m.group(2)))
    return refs


# --- 受入ゲート2: Actionsがコミット SHA で固定されている -----------------------------

def test_all_actions_uses_are_pinned_to_full_commit_sha():
    text = _load_raw_text()
    refs = _uses_action_refs(text)
    # WP(2026-07-31、#394/#414のマージに追随): ランチャーexe廃止で署名候補artifactが
    # 1本になり、upload-artifactの実ステップは2件(本体exe/zip)に減った
    # (checkout 1件 + upload-artifact 2件 = 最低3件を期待)。
    assert len(refs) >= 3, (
        "actions/* の uses: 参照が想定より少ない(checkout 1件 + "
        "upload-artifact 2件 = 最低3件を期待): {}".format(refs))
    for name, ref in refs:
        assert _FULL_SHA_RE.match(ref), (
            "actions/{}@{} がコミットSHAで固定されていない"
            "(タグ・省略形の参照は改竄耐性が無い)".format(name, ref))


def test_pinned_sha_has_tag_comment_for_future_maintenance():
    """SHAだけでは人間が読めないため、`# vX.Y.Z` のようなタグ番号コメントが
    同じ行に併記されていること(将来の更新作業のため)。"""
    text = _load_raw_text()
    for line in text.splitlines():
        if re.search(r"uses:\s*actions/[\w-]+@[0-9a-f]{40}", line):
            assert re.search(r"#\s*v\d", line), (
                "SHA固定行にタグ番号コメントが無い(更新時に何のバージョンか"
                "わからなくなる): {!r}".format(line))


def test_negative_control_regex_rejects_floating_tag_reference():
    """負の対照: 「タグ参照のままの行」を検査ロジックに食わせたとき、SHA固定と
    誤判定されないことを確認する(検査自体が空振りしていないことの担保)。"""
    fake_line = "        uses: actions/checkout@v4\n"
    refs = _uses_action_refs(fake_line)
    assert refs == [("checkout", "v4")]
    name, ref = refs[0]
    assert not _FULL_SHA_RE.match(ref), (
        "負の対照が機能していない: 'v4' のようなタグがSHA正規表現にマッチしてしまっている")


def test_checkout_action_is_actions_checkout_pinned_to_known_sha():
    """2026-07-31にgh apiで実際に解決したSHA(v4 == v4.4.0)であることを固定的に検査する。
    (`gh api repos/actions/checkout/git/refs/tags/v4` の実測値、推測ではない)"""
    text = _load_raw_text()
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in text, (
        "actions/checkoutの固定SHAが期待値と異なる(gh apiで再解決した場合は"
        "テストとドキュメント両方を更新すること)")


def test_upload_artifact_action_is_pinned_to_known_sha_in_all_places():
    """2026-07-31にgh apiで実際に解決したSHA(v4 == v4.6.2)であることを固定的に検査する。

    WP(2026-07-31、#394/#414のマージに追随): ランチャーexe廃止で署名候補artifactが
    1本になったため、upload-artifactの実ステップは2件(本体exe/zip)。旧期待値3件
    (ランチャー/本体/zip)から変更。"""
    text = _load_raw_text()
    count = text.count("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02")
    assert count == 2, (
        "actions/upload-artifactの固定SHA参照が2件(本体/zip)"
        "見つからない(実際: {}件)".format(count))


# --- 受入ゲート1: pyoozの取得ステップがバージョン+SHA256を固定し、不一致で失敗する ---------

def _pyooz_step_run() -> str:
    steps = _steps()
    step = next(s for s in steps if "pyooz" in s.get("name", "").lower())
    return step["run"]


def test_pyooz_step_pins_a_specific_version():
    run = _pyooz_step_run()
    assert re.search(r'pyooz==\$PyoozVersion|pyooz==0\.0\.8', run), (
        "pyoozステップがバージョンを固定していない(pip download pyoozだけだと"
        "常に最新版を取得してしまい、Origin Verificationの懸念そのもの)")
    assert re.search(r'\$PyoozVersion\s*=\s*"0\.0\.8"', run), (
        "pyoozの固定バージョン変数(0.0.8)が見つからない")


def test_pyooz_step_verifies_sha256_and_fails_on_mismatch():
    run = _pyooz_step_run()
    assert re.search(r'\$PyoozSha256\s*=\s*"[0-9a-f]{64}"', run), (
        "pyoozの固定SHA256(64桁16進)が見つからない")
    assert "Get-FileHash" in run and "SHA256" in run, (
        "pyoozステップがGet-FileHashでSHA256を算出していない")
    # 「比較して不一致ならexit 1」という制御フローが実在することを確認する。
    # (単にハッシュ値を変数に持っているだけで比較していない、という誤魔化しを防ぐ)
    mismatch_block = re.search(
        r'if\s*\(\$actualHash\s*-ne\s*\$PyoozSha256\)\s*\{[^}]*exit 1', run)
    assert mismatch_block, (
        "pyoozステップにSHA256不一致時のexit 1分岐が見つからない"
        "(検証コードがあっても失敗させなければ誤魔化しの緑になる)")


def test_pyooz_step_pins_expected_wheel_filename():
    run = _pyooz_step_run()
    assert "pyooz-0.0.8-cp38-abi3-win_amd64.whl" in run, (
        "pyoozの想定wheelファイル名が固定されていない"
        "(バージョン固定が実際に効いているかの二重チェック)")


# --- 受入ゲート1: python3.dllの取得ステップがSHA256を固定し、不一致で失敗する ---------------

def _python3dll_step_run() -> str:
    steps = _steps()
    step = next(s for s in steps if "python3.dll" in s.get("name", "") and "run" in s)
    return step["run"]


def test_python3dll_step_verifies_sha256_and_fails_on_mismatch():
    run = _python3dll_step_run()
    assert re.search(r'\$PyEmbedSha256\s*=\s*"[0-9a-f]{64}"', run), (
        "python3.dll取得ステップの固定SHA256(64桁16進)が見つからない")
    assert "Get-FileHash" in run and "SHA256" in run, (
        "python3.dllステップがGet-FileHashでSHA256を算出していない")
    mismatch_block = re.search(
        r'if\s*\(\$actualHash\s*-ne\s*\$PyEmbedSha256\)\s*\{[^}]*exit 1', run)
    assert mismatch_block, (
        "python3.dllステップにSHA256不一致時のexit 1分岐が見つからない")


def test_python3dll_step_still_sets_expected_env_var_after_verification():
    """検証ステップを追加したことで既存の動作(D2P_PYTHON311_DLL設定)を
    壊していないことの回帰確認。"""
    run = _python3dll_step_run()
    assert "D2P_PYTHON311_DLL" in run
    assert "GITHUB_ENV" in run


# --- 負の対照: 検査ロジック自体がハッシュ検証の欠落を検出できることの自己検査 -----------------

def test_negative_control_missing_hash_check_is_detected_by_the_assertion_logic():
    """検査ロジックの空振りを防ぐための負の対照。SHA256検証もexit 1分岐も無い
    「固定なし」の擬似run:ブロックを用意し、上と同じ正規表現アサーションが
    確実に失敗する(=欠落を検出できる)ことを確認する。"""
    unpinned_fake_run = (
        '$dlDir = Join-Path $env:RUNNER_TEMP "pyooz_dl"\n'
        'python -m pip download --no-deps --no-cache-dir -d $dlDir pyooz\n'
        '$whl = Get-ChildItem $dlDir -Filter "pyooz-*.whl" | Select-Object -First 1\n'
    )
    assert re.search(r'\$PyoozSha256\s*=\s*"[0-9a-f]{64}"', unpinned_fake_run) is None
    assert "Get-FileHash" not in unpinned_fake_run
    mismatch_block = re.search(
        r'if\s*\(\$actualHash\s*-ne\s*\$PyoozSha256\)\s*\{[^}]*exit 1', unpinned_fake_run)
    assert mismatch_block is None, (
        "負の対照が機能していない: ハッシュ検証の無い擬似コードが誤って"
        "「検証あり」と判定されている")


# --- 受入ゲート5: 既存のトリガ・YAML構造を壊していない(回帰確認) -----------------------------

def test_workflow_still_parses_and_retains_all_four_triggers():
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "workflow_dispatch" in triggers
    assert "push" in triggers
    assert triggers["push"].get("branches") == ["main"]
    assert triggers["push"].get("tags") == ["v*"]
    assert "pull_request" in triggers


def test_signpath_signing_block_still_commented_out():
    """署名雛形のuses: actions/upload-artifact@v4 (末尾コメント内)まで誤って
    SHA固定してしまっていないか、かつコメントアウト状態が保たれているかの回帰確認。
    WP34(2026-07-31)でアクション参照を正しい名前(signpath/...@v2)へ修正したため、
    期待文字列もそれに追随している。"""
    text = _load_raw_text()
    for line in text.splitlines():
        if "signpath/github-action-submit-signing-request" in line:
            assert line.lstrip().startswith("#")
    data = _load_yaml()
    assert "sign" not in data["jobs"]
