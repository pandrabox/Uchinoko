# THIRD_PARTY_NOTICES

DiveToPalworld 本体は **MIT License** です([LICENSE](LICENSE) 参照)。

このファイルは、本体のソースコードおよび**配布フルセット版**に含まれる第三者
コンポーネントの一覧です。詳細な出所・取得記録は `third_party\SOURCES.md`
および `third_party\pyooz-0.0.8-source\NOTICE.md` に一次資料として記録しています(本ファイルは
その要約です。二重管理を避けるため、詳細記述はそちらを正とします)。

**レイアウトについての注記(2026-07-31)**: ソースコードと CI ビルドは、zip
ルート直下に本体 exe 一式をそのまま置くフラット構成(旧 `_internal\`
レイアウトを廃止したもの)になっています。**ただし現在配布中の最新リリース
(v2.2.12)はこの変更より前のビルドであり、引き続き `_internal\` レイアウト
(トップレベルのランチャー exe + `_internal\Uchinoko.exe`)のままです。**
フラット構成が実際の配布物に反映されるのは次回リリースからです(AV の検出
状況が改善していないため、配布を急いでいません。詳細は [SECURITY.md](SECURITY.md)
の「アンチウイルス誤検知についての開示」を参照)。下表のパス(`assets\tools\`
等)は新しい構成のものです。旧レイアウトの環境では、いずれも `_internal\`
配下に読み替えてください。

## GPLv3+ コードと MIT 本体の境界(重要)

`pipeline\py\ooz_worker_gpl.py` の**1ファイルのみ**が GPLv3+ です(ファイル冒頭に
`SPDX-License-Identifier: GPL-3.0-or-later` および説明コメントあり)。

このファイルは、Palworld の pak が採用する Oodle 互換圧縮(ooz)を解凍するための、
**独立した別プロセス**として実行されるプログラムです。本体(MIT)からは `subprocess`
経由でのみ起動され、import もリンクもされません(ffmpeg.exe 等の外部実行ファイルを
MIT ツールが subprocess で呼ぶのと同種の「mere aggregation」構成です)。呼び出し元は
`pipeline\py\pak_live_extract.py`。この経路は同ファイルの docstring とソース自体
(`subprocess.run` による呼び出し箇所)から、リポジトリ内だけで直接確認できます。

## リポジトリ(ソースコード)に含まれる第三者コンポーネント

| コンポーネント | ライセンス | 配置 | 出所 |
|---|---|---|---|
| pyooz 0.0.8 の対応ソース(sdist、無改変同梱) | GPLv3+ | `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` | https://pypi.org/project/pyooz/ , https://github.com/zao/pyooz |
| VRM Add-on for Blender 4.4.0 | MIT | `third_party\VRM_Addon_for_Blender-Extension-4_4_0.zip` | https://github.com/saturday06/VRM-Addon-for-Blender/releases/tag/v4.4.0 |
| Shapell(テスト用アバター) | CC0 1.0 Universal | `test\cc0avatar\Shapell_v1_0_3.zip` | 出所URL未確認(要オーナー確認)。zip内 LICENSE.txt で CC0 と明記されていることを実物確認済み |

pyoozのソース(`pyooz-0.0.8-source\`)は、GPLv3の「対応するソースコードを入手可能にすること」
という義務を、外部リンクに依存せず満たすために同梱しています。取得元URL・SHA256・
バージョン一致の確認記録は `third_party\pyooz-0.0.8-source\NOTICE.md` を参照してください。

なお pyooz の sdist 内には、pyooz/ooz 本体コードに加えて第三者の別プロジェクト
(SIMDe: MIT、Hedley: CC0-1.0)がvendoringされています。詳細は同 NOTICE.md を参照してください。

## 配布フルセット版(BOOTH等で配布する zip)にのみ含まれる第三者コンポーネント

以下は「配布 zip」にのみ含まれ、GitHub リポジトリのソースコード自体には含まれません。

| コンポーネント | ライセンス | バージョン | 同梱形態・入手元 |
|---|---|---|---|
| Blender Portable(無改変の公式ビルド) | GPL(公式配布に `GPL-3.0-or-later.txt` `GPL-2.0-or-later.txt` 同梱) | 4.3.2 | **配布zipには含まれません**(u54、2026-07-27)。初回起動時に `pipeline\cli\ensure_blender.ps1` が公式サイト [blender.org](https://www.blender.org/download/) から自動的にダウンロードし、`assets\tools\` に配置します(SHA256をピン留めして照合) |
| pyooz(`ooz.pyd`) | GPLv3+ | 0.0.8 | 差し込み素材のみ `assets\blender_patch\` に同梱し、初回起動時にダウンロードしたBlender同梱 Python 環境へ配置します。対応ソースはリポジトリ内 `third_party\pyooz-0.0.8-source\` にも同梱済み |
| python3.dll | PSF License | CPython 3.11 相当 | pyooz が stable ABI (`cp38-abi3`) ビルドのため、Blender 同梱 Python(3.11系)向けに別途配置。同上(`assets\blender_patch\` に同梱、初回起動時に配置)。CPython 公式配布物の一部。 https://www.python.org/ |
| Blender 同梱の各 Python パッケージ(numpy, requests, urllib3, certifi, Cython, autopep8 等) | 各種(MIT/BSD/PSF/Apache 等) | Blender 4.3.2 公式ビルド同梱のまま、無改変 | Blender 公式ビルドに元々含まれるもの(ダウンロードされるBlender本体の一部。配布zip自体には含まれない) |
| VC++ 再頒布可能ランタイム等 | Microsoft 再頒布可能ランタイムライセンス | — | 配布zipには含まれません。初回起動時にダウンロードするBlender公式ビルド内 `blender.crt\` から `ensure_blender.ps1` がそのまま複製します(新規追加なし) |

配布 zip 内には、ビルド時に動的生成される `THIRD_PARTY_LICENSES.txt`(zip ルート直下)にも
同様の説明があります。

## Python 版(dev#532、移行中。2026-08-01時点ではまだ出荷経路ではない)

`app\DiveToPalworld.cs`(csc.exe/WinForms)を `app_py\`(Python/tkinter)へ
全面書き直しする dev#532 が進行中です。この移行が完了するまでは上記の
「配布フルセット版」表に記載の内容が引き続き実際の出荷物です。移行完了後の
配布物(`app_py\build.py` がビルド、`packaging\` 配下)には、上記に加えて
以下の第三者コンポーネントが同梱される設計です。

| コンポーネント | ライセンス | バージョン | 同梱形態・入手元 |
|---|---|---|---|
| Python(embeddable 版、公式ビルド無改変) | PSF License | 3.11.9 | `res\python_embed\` に同梱。python.org の公式 embeddable zip をそのまま展開したもの(`app_py\build.py` が SHA256 をピン留めして取得・照合)。ライセンス全文は配布物の `res\licenses\PYTHON_LICENSE.txt` |
| Tcl/Tk ランタイム(`_tkinter.pyd` / `tcl86t.dll` / `tk86t.dll` / `tcl8.6` / `tk8.6` スクリプトライブラリ) | Tcl/Tk License(BSD 系) | Python 3.11.9 の公式フルインストーラに同梱されているもの相当 | embeddable 版には含まれないため、python.org の公式フルインストーラを一時的にサイレントインストールして該当ファイルのみを抽出し、embeddable Python へ上書き配置(`app_py\build.py` の `ensure_tkinter_bundle`)。抽出元と同じ Authenticode 署名("CN=Python Software Foundation")を保持していることを確認済み(`packaging\check_signatures.py`)。ライセンス全文は配布物の `res\licenses\TCL_TK_LICENSE.txt` |

pyooz(`ooz.pyd`、GPLv3+)の扱いは Python 版でも上表と同一(差し込み素材として
同梱、対応ソースは `third_party\pyooz-0.0.8-source\` に同梱済み)であり、
GUI 実装言語の変更による差異はありません。

## テスト結果に含まれるサンプルアバターのプレビュー画像について

`tests\relgate\baseline\<検体キー>\images\` には、リリース前の自動視覚回帰試験(層2)が
生成した固定画像(本ツールでの変換結果をレンダリングしたもの)を格納しています。
元の3DアバターファイルはリポジトリにVRMそのものは含めていません(`.gitignore`済み)が、
レンダリング画像には検体の見た目が写り込みます。写っているアバターの出所は以下のとおりです。

| 検体キー | アバター名 | 出所・著作者 | ライセンス・許諾 |
|---|---|---|---|
| `prefab_flatapron` | flatapron | プロジェクトオーナー自身が使用しているアバター | オーナー本人のアバターであり、本ツール自身の宣伝・試験目的での使用 |
| `shapell` | Shapell | `test\cc0avatar\Shapell_v1_0_3.zip` | CC0 1.0 Universal(上表参照) |
| `vrm0_kate` | Kate | "100 Avatars" 系サンプルモデル、制作 Polygonal Mind (www.polygonalmind.com) | CC0。ファイル埋め込みメタデータで確認済み(`third_party\SOURCES.md`参照) |
| `vrm1_seedsan` | Seed-san | VRM仕様公式サンプルモデル(vrm-c/vrm-specification)、著作者 **VirtualCast, Inc.** | VRM Public License 1.0。`avatarPermission: everyone` / `allowRedistribution: true` / `modification: allowModificationRedistribution` を確認済み。ライセンス上**クレジット表記必須**のため、本表をもって Seed-san の著作者が VirtualCast, Inc. であることを明記する |
| `vrm1_vita`(opt-in 検体) | Vita | VRoid Hub「歴代サンプルモデル」、アップロード者 Coatie(Koh-Tee)、pixiv inc. | CC0 1.0 Universal 相当(再配布・改変・改変物の再配布・商用利用いずれもOK、クレジット表記不要)。VRoid Hub掲載の利用条件およびファイル埋め込みメタデータの両方で確認済み(`third_party\SOURCES.md`参照) |

いずれも「特定の個人が購入し再配布を許可していないアセット」ではなく、著作者が
再配布・改変を明示的に許可している公開サンプルモデル、またはプロジェクトオーナー
自身のアバターです。詳細な確認記録は `third_party\SOURCES.md` を参照してください。

## `pipeline\py\noue_master\` 配下の `.uasset`/`.uexp` について

このリポジトリには Unreal Engine 形式のバイナリアセットファイル(`.uasset`/`.uexp`)が
`pipeline\py\noue_master\` 配下に含まれています。Palworld本体のゲームデータと同じ
コンテナ形式であるため誤解を招きやすく、出所を能動的に開示しています。詳細は
[PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md)(英語)を参照してください。

## Blenderの呼び出し形態について(透明性のための補足)

`pipeline\blender\step01_import_vrm.py` / `step02_retarget.py` は、Blender の `--python`
引数機構でロードされ、Blender が提供する `bpy` API を通じて動作します。これは
Blender コミュニティで広く行われている一般的な外部操作形態です。GPL文脈での評価が
議論されうる論点であることの記録として、ここに補足しておきます(結論は断定しません)。
