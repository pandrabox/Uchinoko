"""devtools\\pub_overlay\\.github\\workflows\\build.yml の `release` ジョブについて。

背景(WP34/2026-07-31): `.devonly\\docs\\signpath\\verify\\WP31_release_artifact_gap.md`
が実測した通り、従来は公開リポジトリの GitHub Releases が CI と無関係な手動経路
(`gh release create` + `gh release upload` を人間が都度実行)でのみ作られており、
公開済み9タグのどれもCIビルドを経由していなかった。SignPath Origin Verificationは
「署名対象がCIから出ていること」を要求するため、これでは要件を満たせない。
`release` ジョブはこの欠落を埋めるために新設された。

2026-08-01(dev#573)でこの `release` ジョブは削除した。D1(dev#532)でpy版
(方針A、`app_py\\`)へ全面切替され、py版には自作PEが一つも存在しない
(`packaging\\check_signatures.py` の `SELF_MADE_PE_COUNT=0` がこの前提そのもの)ため、
`release` ジョブが前提にしていた「csc.exeでビルドした署名候補exeをGitHub Release
へ添付する」という設計が丸ごと成立しなくなった。「そもそも何を署名候補artifactと
して提出するのか」はdev#530(SignPath申請凍結中)の解除・再開判断とセットで行う
べき製品判断のため、本WPの範囲外として据え置き、再設計はdev#636でフォローアップ
追跡している。

その結果、WP34が埋めた「CIビルド→GitHub Release」の経路は再び失われ、タグpush後の
GitHub Release作成は当面また人間の手動経路(`gh release create`/`gh release upload`)
に戻っている。この事実を隠さず記録しておくため、本ファイルは「releaseジョブが
実際に存在しないこと」を検査する形へ縮小した(削除ではなく、意図的な現状として
残す)。
"""
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "devtools" / "pub_overlay" / ".github" / "workflows" / "build.yml"
)


def _load_yaml():
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_release_job_no_longer_exists():
    """dev#573: releaseジョブは意図的に削除済み(再設計はdev#636で追跡)。
    復活する場合は、本テストではなくdev#636のissueに沿って新しい検査を書くこと。"""
    data = _load_yaml()
    assert "release" not in data["jobs"], (
        "releaseジョブが復活している。dev#573時点では自作PEが存在せず"
        "(SELF_MADE_PE_COUNT=0)、旧releaseジョブの前提(署名候補exeの添付)が"
        "そのままでは成立しないはず。再設計するなら、この前提の解消方法を"
        "dev#636のコメント列へ記録してからテストを書き直すこと。")
