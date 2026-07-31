"""devtools\\pub_overlay\\.github\\workflows\\build.yml (公開repo用CIビルドワークフロー)の
構造検査(SignPath対応)。

このファイル自体を実行するテスト(実際のcsc.exe/pip/ネットワークを伴うビルド実証)は
行わない。素の%APPDATA%/%LOCALAPPDATA%を偽装した環境でEXIT=0を確認済み、取得ステップを
1つ抜くとmake_dist.ps1:926/936付近で失敗する負の対照も確認済み(ローカル模擬実行による
実測記録は開発側に保管)。

ここでのテストは、YAML構造として壊れていないか・必須要素が揃っているか・
署名ステップが誤って有効化されていないかを機械的に検査する(実行を伴わない静的検査)。
"""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "devtools" / "pub_overlay" / ".github" / "workflows" / "build.yml"
)


def _load_raw_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_yaml():
    return yaml.safe_load(_load_raw_text())


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
    assert "build" in data["jobs"], "jobs.build が見つからない"
    steps = data["jobs"]["build"]["steps"]
    assert isinstance(steps, list) and len(steps) > 0, "jobs.build.steps が空"


# --- 受入ゲート2: TODO(WP2)の残存が無い ---------------------------------------------

def test_no_todo_wp2_marker_remains():
    text = _load_raw_text()
    assert "TODO(WP2)" not in text, "TODO(WP2)の目印が未解消のまま残っている"


# --- 受入ゲート5: ooz.pyd / python3.dll の取得ステップが存在する -----------------------

def _step_names(data) -> list:
    steps = data["jobs"]["build"]["steps"]
    return [s.get("name", "") for s in steps]


def test_pyooz_acquisition_step_present():
    data = _load_yaml()
    names = _step_names(data)
    assert any("pyooz" in n.lower() or "ooz.pyd" in n for n in names), (
        "pyooz(ooz.pyd)取得ステップが見つからない: {}".format(names))
    # run: ブロックの中身も、期待する挙動(pip downloadでの取得、目的地への展開)を
    # 満たしているか確認する。
    step = next(s for s in data["jobs"]["build"]["steps"] if "pyooz" in s.get("name", "").lower())
    run = step["run"]
    assert "pip" in run and "download" in run, "pyoozステップがpip downloadを使っていない"
    assert "ooz.pyd" in run, "pyoozステップがooz.pydの配置先を検査していない"


def test_python3dll_acquisition_step_present():
    data = _load_yaml()
    names = _step_names(data)
    assert any("python3.dll" in n for n in names), (
        "python3.dll取得ステップが見つからない: {}".format(names))
    step = next(s for s in data["jobs"]["build"]["steps"] if "python3.dll" in s.get("name", "")
                and "run" in s)
    run = step["run"]
    assert "python.org" in run or "python-3.11" in run, (
        "python3.dllステップがpython.org embeddable zipを参照していない")
    assert "D2P_PYTHON311_DLL" in run, (
        "python3.dllステップがD2P_PYTHON311_DLL環境変数を設定していない"
        "(make_dist.ps1が最優先で参照する変数)")


def test_build_and_make_dist_steps_present_and_ordered_after_dependency_acquisition():
    """依存取得(pyooz/python3.dll)が make_dist.ps1 実行より前に来ていること。
    順序を間違えると make_dist.ps1:926/936 で必ず失敗する(WP2/WP7実測)。"""
    data = _load_yaml()
    steps = data["jobs"]["build"]["steps"]
    names = [s.get("name", "") for s in steps]

    # 「Acquire pyooz ... make_dist.ps1 expects」のようにステップ名自体に
    # "make_dist.ps1"という語が含まれるステップがあるため、実行コマンド(run:)側で
    # 判定する。make_dist.ps1を実行する行を持つのは "Build full distribution package"
    # ステップのみ(pyooz/python3.dll取得ステップのrun:はダウンロード処理のみ)。
    pyooz_idx = next((i for i, n in enumerate(names) if "pyooz" in n.lower()), None)
    py3dll_idx = next((i for i, n in enumerate(names) if "python3.dll" in n), None)
    make_dist_idx = next(
        (i for i, s in enumerate(steps) if "pwsh -File build\\make_dist.ps1" in s.get("run", "")),
        None,
    )

    assert pyooz_idx is not None and py3dll_idx is not None and make_dist_idx is not None
    assert pyooz_idx < make_dist_idx, "pyooz取得がmake_dist.ps1実行より後になっている"
    assert py3dll_idx < make_dist_idx, "python3.dll取得がmake_dist.ps1実行より後になっている"


def test_artifact_upload_paths_do_not_reference_deleted_stage_dir():
    """build\\make_dist.ps1:1055 は zip作成直後に dist\\stage を無条件削除する
    (実測で確認済み、既存の意図した挙動でmake_dist.ps1側は変更不可)。
    そのため upload-artifact の path が生の `dist\\stage\\...` を指したままだと、
    実行順序的に必ずファイルが無い状態になる。抽出済みディレクトリ(env変数経由)を
    指していることを検査する負の対照。

    2026-07-31: ランチャーexe廃止で配布レイアウトが
    フラット化され、署名候補exeは Uchinoko_for_Palworld\\Uchinoko.exe の
    1本のみになった(旧: ルートのランチャーexe + _internal\\の本体exeの2本)。
    期待件数を2->1に更新。"""
    data = _load_yaml()
    steps = data["jobs"]["build"]["steps"]
    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    exe_upload_steps = [
        s for s in upload_steps
        if "with" in s and str(s["with"].get("path", "")).lower().endswith("uchinoko.exe")
    ]
    assert len(exe_upload_steps) == 1, (
        "exeアーティファクトのuploadステップが1件見つからない(ランチャー廃止後は"
        "本体exeの1本のみのはず)")
    for s in exe_upload_steps:
        path = s["with"]["path"]
        assert not re.match(r"^dist\\stage\\", path), (
            "upload-artifactが削除済みのdist\\stageを直接参照している(壊れる): {}".format(path))


# --- 受入ゲート5: SignPath署名ステップがコメントアウトされた雛形として存在する -----------

def test_signpath_signing_step_is_commented_out_not_active():
    data = _load_yaml()
    jobs = data["jobs"]
    assert "sign" not in jobs, (
        "SignPath署名ジョブ(sign)が有効化されている。"
        "オーナーがSignPathアカウントを作成し、値を実値に置き換えるまでは"
        "コメントアウトされた雛形のままであるべき"
    )
    text = _load_raw_text()
    # WP34(2026-07-31): docs.signpath.io/trusted-build-systems/github を実測して確認した
    # 正しいアクション参照は `signpath/github-action-submit-signing-request@v2`
    # (旧雛形の `signpath-io/...@v1` は組織名・バージョンとも公式ドキュメントに存在しない
    # 誤り。修正はWP34で実施し、本テストの期待文字列も追随して更新した)。
    assert "signpath/github-action-submit-signing-request" in text, (
        "SignPath署名アクションの雛形コメントが見つからない")
    # コメントアウトされていること(行頭が # で始まる)を確認
    for line in text.splitlines():
        if "signpath/github-action-submit-signing-request" in line:
            assert line.lstrip().startswith("#"), (
                "SignPath署名アクションの行がコメントアウトされていない: {!r}".format(line))
    assert "TODO(オーナー)" in text, (
        "オーナー向けの有効化TODOが明記されていない")


def test_signpath_secret_reference_only_appears_inside_comments():
    """負の対照: SIGNPATH_API_TOKEN参照が非コメント行(=有効なステップ)に
    紛れ込んでいないことを確認する。"""
    text = _load_raw_text()
    for line in text.splitlines():
        if "SIGNPATH_API_TOKEN" in line:
            assert line.lstrip().startswith("#"), (
                "SIGNPATH_API_TOKEN参照が非コメント行にある(誤って有効化されている疑い): "
                "{!r}".format(line))


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


# --- WP25(2026-07-31): push(既定ブランチ)/pull_request トリガの追加 ---------------------
#
# 目的: 従来は workflow_dispatch とタグ push(v*)でしか起動せず、通常のコミットでは
# CIが動かないため「継続的に健全である」ことが外から見えなかった(SignPath審査対策)。
# ここでは、既存のworkflow_dispatch/タグ起動を壊さずにpush/pull_requestを追加できて
# いることを検査する。

def test_tag_push_trigger_is_preserved():
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "push" in triggers, "push: トリガーが見つからない"
    assert triggers["push"].get("tags") == ["v*"], (
        "タグpush(v*)トリガーが失われている(リリースビルド経路・"
        "SignPath Origin Verificationに直結するため必須): {}".format(triggers["push"]))


def test_workflow_dispatch_trigger_is_preserved():
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "workflow_dispatch" in triggers, "workflow_dispatch: トリガーが見つからない"
    version_input = triggers["workflow_dispatch"]["inputs"]["version"]
    assert version_input.get("required") is True


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
    パスで間引くと目的を弱める(paths-ignoreはpull_requestにのみ付与する、
    2026-07-31 WP25判断)。"""
    data = _load_yaml()
    on_key = "on" if "on" in data else True
    triggers = data[on_key]
    assert "paths-ignore" not in triggers["push"], (
        "push トリガーに paths-ignore が付いている(健全性の可視化という追加目的と矛盾)")
    assert "paths" not in triggers["push"]


def test_resolve_version_step_falls_back_to_toolversion_constant_for_non_tag_events():
    """make_dist.ps1は-VersionがApp\\DiveToPalworld.csのToolVersion定数と一致しないと
    EXIT=1で失敗する(build\\make_dist.ps1:48)。タグ名が存在しないブランチpush/
    pull_requestでは、"main"のようなプレースホルダではなくToolVersion定数の値を
    そのまま使う実装になっていることを検査する(2026-07-31 WP25)。"""
    data = _load_yaml()
    steps = data["jobs"]["build"]["steps"]
    resolve_step = next(s for s in steps if s.get("id") == "version")
    run = resolve_step["run"]
    assert "ref_type" in run, (
        "タグpushかどうかの判定にgithub.ref_typeを使っていない(ブランチpushと"
        "タグpushの区別が付かないと、ブランチpushでref_name(ブランチ名)を"
        "バージョンとして使ってしまいmake_dist.ps1が失敗する)")
    assert "ToolVersion" in run, (
        "非タグイベントの版決定にToolVersion定数を読んでいない")
    assert "DiveToPalworld.cs" in run
