"""devtools\\pub_overlay\\.github\\workflows\\build.yml の `release` ジョブ
(WP34/2026-07-31追加)の構造検査。

背景: `.devonly\\docs\\signpath\\verify\\WP31_release_artifact_gap.md` が実測した通り、
従来は公開リポジトリの GitHub Releases が CI と無関係な手動経路
(`gh release create` + `gh release upload` を人間が都度実行)でのみ作られており、
公開済み9タグのどれもCIビルドを経由していなかった。SignPath Origin Verificationは
「署名対象がCIから出ていること」を要求するため、これでは要件を満たせない。
`release` ジョブはこの欠落を埋めるために新設した。

ここでのテストは実行を伴わない静的検査(YAML構造・文字列パターン)のみ。
実際にタグを打つ・リリースを作成する行為はこのテストも含めて一切行っていない。
"""
import re
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "devtools" / "pub_overlay" / ".github" / "workflows" / "build.yml"
)

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _load_raw_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_yaml():
    return yaml.safe_load(_load_raw_text())


def _release_job():
    return _load_yaml()["jobs"]["release"]


# --- 受入ゲート1: release ジョブが存在し、build に依存し、タグpushのみで動く -----------

def test_release_job_exists():
    jobs = _load_yaml()["jobs"]
    assert "release" in jobs, "release ジョブが見つからない"


def test_release_job_depends_on_build():
    job = _release_job()
    assert job.get("needs") == "build", (
        "release ジョブが build ジョブに依存していない(未ビルドの成果物を"
        "添付してしまう恐れ): {}".format(job.get("needs")))


def test_release_job_only_triggers_on_tag_push():
    job = _release_job()
    cond = job.get("if", "")
    assert "refs/tags/" in cond, (
        "release ジョブの if 条件がタグ参照(refs/tags/)を見ていない: {!r}".format(cond))
    assert "success()" in cond, (
        "release ジョブの if 条件が明示的な success() を含んでいない"
        "(if:を書くと既定のneeds成功判定が上書きされるため、明示しないと"
        "buildジョブ失敗時にもreleaseジョブが走ってしまう恐れ): {!r}".format(cond))


def test_negative_control_branch_push_does_not_match_tag_condition():
    """負の対照: ブランチpush由来のref('refs/heads/main')は
    release ジョブの起動条件にマッチしないことを確認する。"""
    job = _release_job()
    cond = job.get("if", "")
    # if 条件式は `startsWith(github.ref, 'refs/tags/v')` の形。
    # 実際の式評価はGitHub Actions側で行われるため、ここでは文字列パターンで
    # 「refs/heads」ではなく「refs/tags」を対象にしていることだけを検査する。
    assert "refs/tags/" in cond and "refs/heads" not in cond


# --- 受入ゲート2: release ジョブだけが contents: write に昇格している(最小権限) -----------

def test_release_job_requests_contents_write_permission():
    job = _release_job()
    perms = job.get("permissions", {})
    assert perms.get("contents") == "write", (
        "release ジョブに contents: write 権限が無い(gh release create/upload には"
        "書き込み権限が必要): {}".format(perms))


def test_build_job_permissions_unaffected_by_release_job_addition():
    """release ジョブの権限昇格が、build ジョブやトップレベルのread-only既定に
    漏れ出していないことの回帰確認。"""
    data = _load_yaml()
    assert data.get("permissions", {}).get("contents") == "read"
    build_job = data["jobs"]["build"]
    # build ジョブ自体はjob単位のpermissions上書きを持たない(トップレベルのreadを継承)
    assert "permissions" not in build_job


# --- 受入ゲート3: 成果物のダウンロードがSHA固定されたactions/download-artifactを使う -------

def test_release_job_downloads_both_build_artifacts_via_pinned_action():
    job = _release_job()
    download_steps = [s for s in job["steps"] if str(s.get("uses", "")).startswith(
        "actions/download-artifact")]
    assert len(download_steps) == 2, (
        "download-artifactステップが2件(app/zip)見つからない: {}".format(download_steps))
    names = {s["with"]["name"] for s in download_steps}
    assert names == {"uchinoko-app-unsigned", "uchinoko-dist-zip-unsigned"}, (
        "buildジョブがuploadしたartifact名と一致しない: {}".format(names))
    for s in download_steps:
        ref = s["uses"].split("@", 1)[1]
        assert _FULL_SHA_RE.match(ref), (
            "download-artifactがコミットSHAで固定されていない: {}".format(s["uses"]))


# --- 受入ゲート4: バージョン整合性(タグ vs ToolVersion由来のversion出力)を検査し失敗させる ---

def test_release_job_asserts_tag_matches_resolved_version():
    job = _release_job()
    combined_run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "needs.build.outputs.version" in combined_run, (
        "release ジョブが build ジョブの version 出力を参照していない")
    assert re.search(r"if\s*\(\$tag\s*-ne\s*\$ver\)\s*\{[^}]*exit 1", combined_run), (
        "タグとバージョンの不一致を検出してexit 1する分岐が見つからない"
        "(依頼要件: 『タグとToolVersionが食い違ったら失敗させる』)")


def test_build_job_output_version_step_id_matches_resolve_version_step():
    """build ジョブの outputs.version が実際に `Resolve version` ステップ
    (id: version)の出力を指していることの配線確認(名前だけ似ていて実は
    別ステップを指す、という配線漏れを防ぐ)。"""
    data = _load_yaml()
    build_job = data["jobs"]["build"]
    assert build_job["outputs"]["version"] == "${{ steps.version.outputs.version }}"
    resolve_step = next(s for s in build_job["steps"] if s.get("id") == "version")
    assert resolve_step["name"] == "Resolve version"


# --- 受入ゲート5: ダウンロード後のハッシュ再検証(改変が無いことの確認)を行っている ---------

def test_release_job_reverifies_hashes_against_build_job_outputs():
    job = _release_job()
    combined_run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "needs.build.outputs.app-sha256" in combined_run
    assert "needs.build.outputs.zip-sha256" in combined_run
    assert "Get-FileHash" in combined_run
    # 不一致時にexit 1する分岐が両方(app/zip)に存在すること
    assert re.search(
        r"if\s*\(\$actualAppHash\s*-ne\s*\$expectedAppHash\)\s*\{[^}]*exit 1", combined_run)
    assert re.search(
        r"if\s*\(\$actualZipHash\s*-ne\s*\$expectedZipHash\)\s*\{[^}]*exit 1", combined_run)


def test_build_job_computes_and_summarizes_hashes():
    """依頼要件: 『成果物のハッシュをCIのログ/サマリに出す』。build ジョブの
    ハッシュ計算ステップが GITHUB_STEP_SUMMARY へ書き込んでいることを検査する。"""
    data = _load_yaml()
    build_job = data["jobs"]["build"]
    hash_step = next(s for s in build_job["steps"] if s.get("id") == "hashes")
    run = hash_step["run"]
    assert "Get-FileHash" in run
    assert "GITHUB_STEP_SUMMARY" in run
    assert "app_sha256" in run and "zip_sha256" in run


# --- 受入ゲート6: リリース作成は既定でdraft、かつ冪等(既存releaseがあればupload) ------------

def test_release_creation_defaults_to_draft():
    job = _release_job()
    combined_run = "\n".join(s.get("run", "") for s in job["steps"])
    assert re.search(r"gh release create .*--draft", combined_run), (
        "gh release create に --draft が付いていない"
        "(依頼の安全側デフォルト設計: draftのまま人間の確認を挟む)")


def test_release_job_is_idempotent_for_reruns_on_same_tag():
    job = _release_job()
    combined_run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "gh release view" in combined_run, (
        "既存releaseの有無を確認する分岐が無い(同じタグでの再実行時に"
        "gh release createが失敗する恐れ)")
    assert "gh release upload" in combined_run and "--clobber" in combined_run


def test_release_upload_does_not_pass_raw_wildcards_to_gh_cli():
    """実装中に発見した実バグの回帰テスト: PowerShell(pwsh)は外部exeへ渡す引数の
    ワイルドカード("*")をbashのように自動展開しない。`gh release create $tag ...
    release_upload\\Uchinoko_*.exe` のような書き方は、gh.exeへリテラルな
    "Uchinoko_*.exe" という文字列を渡すだけで、実在するファイルとして解決されず
    「ファイルが無い」エラーになる。正しくはGet-ChildItemでPowerShell側に
    ワイルドカードを解決させてから配列splat(@files)で渡す必要がある。"""
    job = _release_job()
    for step in job["steps"]:
        run = step.get("run", "")
        for line in run.splitlines():
            if re.search(r"gh release (create|upload)\b", line):
                assert "*" not in line, (
                    "gh release create/upload の行にワイルドカード(*)が"
                    "直接含まれている(PowerShellは外部exeへの引数を自動展開しない"
                    "ため、この形は実行時にファイルが見つからず失敗する): {!r}".format(line))
    combined_run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "Get-ChildItem" in combined_run and "@assetFiles" in combined_run, (
        "release資産の列挙にGet-ChildItem+配列splatを使っていない")


def test_release_assets_include_sha256sums_file():
    job = _release_job()
    combined_run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "SHA256SUMS.txt" in combined_run, (
        "第三者検証用のSHA256SUMS.txtがリリース資産に含まれていない")


# --- 負の対照: 検査ロジック自体が「draft無し」「ハッシュ検証無し」を検出できることの自己検査 ---

def test_negative_control_missing_draft_flag_is_detected():
    fake_run = 'gh release create $tag --title $tag release_upload\\*\n'
    assert re.search(r"gh release create .*--draft", fake_run) is None


def test_negative_control_missing_hash_mismatch_branch_is_detected():
    fake_run = (
        '$actualAppHash = (Get-FileHash -Path $appFile.FullName -Algorithm SHA256).Hash\n'
        '# 比較も exit 1 も無い\n'
    )
    assert re.search(
        r"if\s*\(\$actualAppHash\s*-ne\s*\$expectedAppHash\)\s*\{[^}]*exit 1", fake_run
    ) is None


# --- 受入ゲート7: SignPath連携の雛形コメントが実在のアクション名(v2)を指している ----------

def test_signpath_template_references_correct_action_name_and_version():
    """docs.signpath.io/trusted-build-systems/github (2026-07-31 WebFetch実測)によれば、
    公式のSignPath連携アクションは `signpath/github-action-submit-signing-request@v2`
    (`signpath-io/...@v1` という組織名・バージョンは実在しない/古い)。
    雛形コメントが古いまま(v1・誤った組織名)だと、有効化時に混乱を招く。"""
    text = _load_raw_text()
    assert "signpath/github-action-submit-signing-request@v2" in text, (
        "SignPath連携アクションの雛形が正しい参照名(signpath/..@v2)を"
        "使っていない(docs.signpath.io/trusted-build-systems/github で"
        "2026-07-31に確認した実際のアクション名)")
