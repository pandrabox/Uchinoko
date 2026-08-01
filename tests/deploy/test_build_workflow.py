"""devtools\\pub_overlay\\.github\\workflows\\build.yml (公開repo用CIワークフロー)の
構造検査。

2026-08-01(dev#573): D1(dev#532)でC#/WinForms(app\\DiveToPalworld.cs /
app\\build_app.ps1 / Uchinoko.exe)からPython/tkinter版(app_py\\)へ全面切替され、
配布zip直下がUchinoko.bat/README.txt/res\\の3点のみ(自作PEゼロ)になったのに
build.ymlがまだ旧exeビルド前提のままだったため、次にCIが実行された時点で確実に
赤くなる状態だった(本体exeが見つからずFAIL)。dev#573で全面書き換え、以降は
「公開リポジトリ単体で成立する軽量な健全性確認」(python構文チェック+軽い
ユニットテスト)に留める設計になった。フル配布ビルド・SignPath連携・GitHub
Release自動作成は意図的にスコープ外(dev#636でフォローアップ追跡)。

このファイル自体を実行するテスト(実際のpip/ネットワークを伴う実行)は行わない。
YAML構造として壊れていないか・必須要素が揃っているか・削除したはずの旧C#/exe
前提が誤って残っていないかを機械的に検査する(実行を伴わない静的検査)。
"""
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "devtools" / "pub_overlay" / ".github" / "workflows" / "build.yml"
)


def _load_raw_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_yaml():
    return yaml.safe_load(_load_raw_text())


def _job():
    """唯一のjob(healthcheck)を返す。"""
    data = _load_yaml()
    return data["jobs"]["healthcheck"]


def _step_names(job=None) -> list:
    job = job or _job()
    return [s.get("name", "") for s in job["steps"]]


# --- 受入ゲート1: YAMLとしてパースできる -------------------------------------------

def test_workflow_file_exists():
    assert WORKFLOW_PATH.is_file(), "build.ymlが存在しない: {}".format(WORKFLOW_PATH)


def test_workflow_parses_as_yaml_with_expected_top_level_keys():
    data = _load_yaml()
    assert isinstance(data, dict)
    # PyYAML(1.1準拠)は素の`on:`キーをbool Trueとして解釈する既知の癖があるため、
    # 'on'とTrueの両方を許容して探す(GitHub Actions自体の解釈には影響しない)。
    on_key = "on" if "on" in data else True
    assert on_key in data, "on: トリガーが見つからない: keys={}".format(list(data.keys()))
    assert "jobs" in data, "jobs: が見つからない"
    assert "healthcheck" in data["jobs"], "jobs.healthcheck が見つからない"
    steps = data["jobs"]["healthcheck"]["steps"]
    assert isinstance(steps, list) and len(steps) > 0, "jobs.healthcheck.steps が空"


# --- 受入ゲート2: 旧TODOマーカーの残存が無い --------------------------------------

def test_no_todo_wp2_marker_remains():
    text = _load_raw_text()
    assert "TODO(WP2)" not in text, "TODO(WP2)の目印が未解消のまま残っている"


# --- 受入ゲート3: dev#573で削除したはずの旧C#/exeビルド前提が残っていない(負の対照) ------

def _steps_text() -> str:
    """全ステップのname/run/uses/withフィールドだけを連結したテキストを返す。
    ファイル冒頭の説明コメント(履歴を語るため意図的に旧トークンへ言及する)を
    誤検出しないよう、YAMLとしてパース済みの構造(コメントは自動的に失われる)
    からのみ組み立てる。"""
    job = _job()
    parts = []
    for s in job["steps"]:
        parts.append(str(s.get("name", "")))
        parts.append(str(s.get("run", "")))
        parts.append(str(s.get("uses", "")))
        parts.append(str(s.get("with", "")))
    return "\n".join(parts)


def test_no_csharp_build_references_remain():
    """DiveToPalworld.cs / build_app.ps1 / csc.exe への参照が実行ステップに
    残っていないこと。残っていれば、旧C#前提の削除が中途半端であることを意味する。
    (ファイル冒頭の説明コメントは経緯を語るため意図的にこれらの語へ言及するので、
    検査対象はYAMLパース後のステップ本体のみに絞る)。"""
    text = _steps_text()
    for token in ("DiveToPalworld.cs", "build_app.ps1", "csc.exe"):
        assert token not in text, (
            "旧C#/exeビルド前提の参照が実行ステップに残っている"
            "(dev#573で除去したはずの語): {!r}".format(token))


def test_no_make_dist_or_dependency_acquisition_steps_remain():
    """make_dist.ps1実行・ooz.pyd/python3.dll取得ステップが実行ステップに
    残っていないこと。py版のapp_py\\build.pyはこれらを内部で使うが、本ワークフロー
    (軽量ヘルスチェック)はフル配布ビルドをしないため、これらの取得ステップ自体が
    不要(dev#573で削除)。"""
    text = _steps_text()
    for token in ("make_dist.ps1", "ooz.pyd", "python3.dll", "D2P_PYTHON311_DLL"):
        assert token not in text, (
            "フル配布ビルド関連の参照が実行ステップに残っている"
            "(dev#573で軽量化したはずの語): {!r}".format(token))


def test_no_exe_artifact_upload_remains():
    """actions/upload-artifactでexeを対象にするステップが残っていないこと
    (py版には自作PEが存在しないため、署名候補exeという概念自体が無い)。"""
    job = _job()
    upload_steps = [s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact")]
    assert upload_steps == [], (
        "upload-artifactステップが残っている(py版はフル配布ビルドをCIで行わないため"
        "artifact upload自体が不要): {}".format(upload_steps))


def test_no_release_job_remains():
    """タグpush時にexeをGitHub Releaseへ添付するreleaseジョブが残っていないこと。
    py版には署名候補exeが存在しないため、このジョブの前提自体が成立しない
    (再設計はdev#636でフォローアップ追跡)。"""
    data = _load_yaml()
    assert "release" not in data["jobs"], (
        "releaseジョブが残っている(py版には署名候補exeが存在せず前提が崩れている。"
        "再設計はdev#636で追跡)")
    assert list(data["jobs"].keys()) == ["healthcheck"], (
        "jobsが healthcheck 単体ではない: {}".format(list(data["jobs"].keys())))


def test_no_active_sign_job_and_no_signpath_secret_outside_comments():
    """SignPath署名ジョブが有効化されていないこと、SIGNPATH_API_TOKEN参照が
    コメント外に紛れ込んでいないこと(負の対照)。"""
    data = _load_yaml()
    assert "sign" not in data["jobs"], "SignPath署名ジョブ(sign)が有効化されている"
    text = _load_raw_text()
    for line in text.splitlines():
        if "SIGNPATH_API_TOKEN" in line:
            assert line.lstrip().startswith("#"), (
                "SIGNPATH_API_TOKEN参照が非コメント行にある(誤って有効化されている疑い): "
                "{!r}".format(line))


# --- 受入ゲート4: 新設計(軽量ヘルスチェック)の必須ステップが揃っている ---------------------

def test_python_syntax_check_step_present():
    names = _step_names()
    assert any("syntax" in n.lower() for n in names), (
        "Python構文チェックのステップ名が見つからない: {}".format(names))
    step = next(s for s in _job()["steps"] if "syntax" in s.get("name", "").lower())
    assert "compileall" in step["run"] and "app_py" in step["run"], (
        "構文チェックステップがcompileallでapp_pyを対象にしていない")


def test_apppy_unit_test_step_present():
    job = _job()
    step = next(
        (s for s in job["steps"] if "run" in s and "pytest" in s["run"] and "app_py" in s["run"]),
        None,
    )
    assert step is not None, "app_py\\testsを実行するpytestステップが見つからない"
    assert "app_py\\tests" in step["run"] or "app_py/tests" in step["run"]


def test_dist_shipped_docs_content_test_step_present():
    job = _job()
    step = next(
        (s for s in job["steps"]
         if "run" in s and "test_dist_shipped_docs_content.py" in s["run"]),
        None,
    )
    assert step is not None, (
        "tests\\shipcheck\\test_dist_shipped_docs_content.py を実行するステップが見つからない")


def test_setup_python_step_present_and_pinned():
    job = _job()
    step = next((s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-python")), None)
    assert step is not None, "actions/setup-pythonのステップが見つからない"
    assert step.get("with", {}).get("python-version") == "3.11", (
        "python-versionが3.11に固定されていない: {}".format(step.get("with")))


# --- 安全制約: release/tag等で自動的に公開する設定になっていないこと --------------------

def test_trigger_does_not_auto_publish_on_release_event():
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "release" not in triggers, (
        "release: トリガーが設定されている(承認境界を越える自動公開の恐れ)")


def test_permissions_are_read_only_by_default():
    data = _load_yaml()
    assert data.get("permissions", {}).get("contents") == "read", (
        "permissions.contents が read になっていない(最小権限の原則)")


# --- トリガ構成(WP25/2026-07-31の判断をdev#573以降も維持) -----------------------------

def test_tag_push_trigger_is_preserved():
    """タグpush(v*)でも同じ軽量ヘルスチェックを走らせる(「コミットのたびに緑が
    見える」目的の維持。フル配布ビルドを伴わなくなったので所要時間は短い)。"""
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "push" in triggers, "push: トリガーが見つからない"
    assert triggers["push"].get("tags") == ["v*"], (
        "タグpush(v*)トリガーが失われている: {}".format(triggers["push"]))


def test_workflow_dispatch_trigger_is_preserved():
    """dev#573: フル配布ビルドを伴わなくなったため、workflow_dispatchの
    version入力(必須)は不要になった。手動再実行できることだけを検査する。"""
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "workflow_dispatch" in triggers, "workflow_dispatch: トリガーが見つからない"


def test_push_trigger_includes_default_branch_pandrabox_uchinoko_is_main():
    """公開repo(pandrabox/Uchinoko)のdefault branchは "main"(dev側の"master"とは
    異なる。build.ymlは公開repo側で動くファイルなので"main"が正しい。実機確認:
    `gh api repos/pandrabox/Uchinoko --jq .default_branch` -> main、
    2026-07-31 WP25)。"""
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert triggers["push"].get("branches") == ["main"], (
        "pushトリガーに既定ブランチ(main)が設定されていない: {}".format(triggers["push"]))


def test_pull_request_trigger_present_targeting_default_branch():
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "pull_request" in triggers, "pull_request: トリガーが見つからない"
    assert triggers["pull_request"].get("branches") == ["main"]


def test_push_trigger_has_no_paths_filter_so_every_commit_stays_visible():
    """push(ブランチ/タグ)にはpaths-ignoreを付けない設計判断の負の対照。
    この追加の目的自体が「コミットのたびに緑が見える」ことなので、push側を
    パスで間引くと目的を弱める(paths-ignoreはpull_requestにのみ付与する)。"""
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "paths-ignore" not in triggers["push"], (
        "push トリガーに paths-ignore が付いている(健全性の可視化という追加目的と矛盾)")
    assert "paths" not in triggers["push"]
