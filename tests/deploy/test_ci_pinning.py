"""devtools\\pub_overlay\\.github\\workflows\\build.yml (公開repo用CIワークフロー)の
取得物固定の静的検査。

2026-08-01(dev#573): D1(dev#532)のpy版切替に追随してbuild.ymlを全面書き換え、
フル配布ビルド(csc.exeビルド/ooz.pyd・python3.dll取得/make_dist.ps1実行/署名候補
exeのハッシュ計算・artifact upload/GitHub Release自動作成)を意図的に削除して
「軽量な健全性確認」(python構文チェック+軽いユニットテスト)のみへ縮小した
(再設計の要否はdev#636で追跡)。そのため、旧来ここで検査していたpyooz/python3.dll
固定に関する試験は対象ステップごと消滅した。

引き続き価値がある「利用するGitHub Actions自体をコミットSHAで固定する」
(サプライチェーン改竄耐性)方針は健全性確認ジョブでも継続しているため、
ここではそれだけを検査する(実行を伴わない静的検査)。
"""
import re
from pathlib import Path

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


# --- 受入ゲート1: Actionsがコミット SHA で固定されている -----------------------------

def test_all_actions_uses_are_pinned_to_full_commit_sha():
    text = _load_raw_text()
    refs = _uses_action_refs(text)
    # dev#573: 軽量ヘルスチェックに縮小後は checkout + setup-python の2件のみ。
    assert len(refs) == 2, (
        "actions/* の uses: 参照数が想定と異なる(checkout 1件 + "
        "setup-python 1件 = 2件を期待): {}".format(refs))
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
    """gh apiで実際に解決したSHA(v4 == v4.4.0)であることを固定的に検査する。
    (`gh api repos/actions/checkout/git/refs/tags/v4.4.0` の実測値、推測ではない)"""
    text = _load_raw_text()
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in text, (
        "actions/checkoutの固定SHAが期待値と異なる(gh apiで再解決した場合は"
        "テストとドキュメント両方を更新すること)")


def test_setup_python_action_is_pinned_to_known_sha():
    """gh apiで実際に解決したSHA(v5 == v5.6.0)であることを固定的に検査する。
    (`gh api repos/actions/setup-python/git/refs/tags/v5.6.0` の実測値、
    2026-08-01時点でv5タグが指すコミットと同一。dev#573で新規追加)。"""
    text = _load_raw_text()
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in text, (
        "actions/setup-pythonの固定SHAが期待値と異なる(gh apiで再解決した場合は"
        "テストとドキュメント両方を更新すること)")


# --- 受入ゲート2: 旧pyooz/python3.dll固定ステップが残っていない(負の対照) --------------

def test_pyooz_and_python3dll_pinning_steps_are_gone():
    """dev#573でフル配布ビルドを行わなくなったため、これらの取得・SHA256固定
    ステップ自体が不要になった。復活していないことの回帰確認。"""
    text = _load_raw_text()
    for token in ("PyoozVersion", "PyoozSha256", "PyEmbedSha256", "pyooz==0.0.8"):
        assert token not in text, (
            "pyooz/python3.dll固定ステップの痕跡が残っている(dev#573で削除済みのはず): "
            "{!r}".format(token))


# --- 受入ゲート3: 既存のトリガ・YAML構造を壊していない(回帰確認) -----------------------------

def test_workflow_still_parses_and_retains_three_triggers():
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "workflow_dispatch" in triggers
    assert "push" in triggers
    assert triggers["push"].get("branches") == ["main"]
    assert triggers["push"].get("tags") == ["v*"]
    assert "pull_request" in triggers


def test_signpath_signing_block_is_absent():
    """dev#573: SignPath連携の雛形(コメントアウト済みsignジョブ)は
    py版に自作PEが存在しないため削除した(再設計はdev#636で追跡)。
    signジョブ・SIGNPATH_API_TOKENがコメント外に紛れ込んでいないことも確認する。"""
    data = _load_yaml()
    assert "sign" not in data["jobs"]
    text = _load_raw_text()
    for line in text.splitlines():
        if "SIGNPATH_API_TOKEN" in line:
            assert line.lstrip().startswith("#")
