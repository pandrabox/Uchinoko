# ship_smoke — 出荷直前20分ゲート

`tests\shipcheck\ship_smoke.py` は、配布直前に**約20分で回せるクリティカル部分だけの
試験**。Unity・Palworld実機には一切触れない。既存の `tests\shipcheck\test_offline.py`
等(U32本格スイート、実変換・実機まで含む30分〜8時間級)とは別物で、置き換えではなく
「その手前で毎回回す、もっと速いゲート」という位置づけ。

## 使い方

```powershell
# Tier Aのみ(高速ゲート、目標2分以内)
python tests\shipcheck\ship_smoke.py --fast

# Tier A -> Tier B(変換を伴うケース群、上限20分)
python tests\shipcheck\ship_smoke.py --minutes 20

# 作業フォルダを明示指定したい場合
python tests\shipcheck\ship_smoke.py --minutes 20 --work work\shipcheck_release
```

終了コード: FAILが1件でもあれば1、全部PASS(SKIPは許容)なら0。

## Tier A(このファイルが直接実装。排他資源なし)

各ゲートが「何を守っているか」:

| ゲート | 守っているもの | 実体 |
|---|---|---|
| **A1 権利監査(最重要)** | パルワールド資産・配布不可個人アバター「toto」の混入がゼロであること。**これがFAILなら配布してはいけない** | `devtools\u45_toto_perceptual_audit.py --live`(常時実行)+ `devtools\u28_zip_audit.py <最新のdist\*.zip>`(zipがあれば実行、無ければ理由付きSKIP) |
| A2 文書整合 | README.md・docs\・manual\ 配下の公開文書に、FBXが対応形式として書かれておらず、「Modular Avatar以外のNDMFプラグイン非対応」相当の記載があること(CLAUDE.md「対応スコープ」節が根拠) | `check_doc_consistency()`(本ファイル内の純関数。pytest非依存、単体で任意ディレクトリに対して呼べる) |
| A3 アプリ健全性 | GUI(`app\DiveToPalworld.cs`)がコンパイルでき、起動直後(3.5秒)に落ちないこと。終了処理でゾンビプロセスを残さない | `app\build_app.ps1 -Out <work>\build\...` を呼び、生成exeを起動→数秒待って強制終了 |
| A4 パイプライン健全性 | `pipeline\` 配下の全`.py`が構文的に壊れていない(py_compile)。`pipeline\py\` の主要モジュールが実際にimportできる(bpy/bmesh依存の2ファイルは対象外) | `py_compile.compile()` + サブプロセスでの`__import__` |
| A5 変換入口の静的検査 | `convert.ps1` / `export_from_unity.ps1` / `build_app.ps1` がPowerShellとして構文エラーなしであること(実行はしない) | `[System.Management.Automation.Language.Parser]::ParseFile` |
| A6 cp932環境でのサブプロセス出力安全性 | `convert.ps1`が起動する子プロセス(Blender同梱python/Blender埋め込みpython)の標準出力が、cp932しか使えない環境(日本語Windows既定、UTF-8ベータ未有効)でもクラッシュしないこと。2026-07-26 他PCでの実行失敗(`work\fx_cp932\fix_FX_cp932.md`)の再発防止ゲート | `gate_a6_cp932_subprocess_safety()`(本ファイル内) |
| A8 GUI配線契約 | GUI(`app\DiveToPalworld.cs`)の「フル変換」ボタンが実際に行う job.json生成→convert.ps1起動 の配線が壊れていないこと(「GUIで変換できる」の保証)。A3は起動直後に落ちないことしか見ておらず、この配線自体は無検証だった。2026-07-26のcp932事故はまさにこの経路(GUI経由の出力リダイレクト)が引き金だったクラスの再発防止 | `tests\shipcheck\gui_wiring_check.py`(WP11、下記「A8の実装メモ」参照) |
| A9 外部依存resolverユニット試験 | `pipeline\py\dep_resolver.py`(dev#22 Unity発見問題の共通resolver)の挙動退行が無いこと: Hub台帳(editors-v2.json等)からの範囲一致発見、手動指定(`settings_unityeditor.txt`/`D2P_UNITY_EDITOR`)の最優先、失敗時に探索trail全列挙+手動指定案内が返ること(負の対照込み)。A4はimportまでしか見ないため挙動はここで守る | `tests\resolver\test_dep_resolver.py`(stdlib unittest、偽台帳フィクスチャ自作・排他資源なし・数秒) |

### A1の実装メモ

- `devtools\u28_zip_audit.py` は**zip必須**(`--live`相当のオプションが無い)。本スクリプトは
  `dist\*.zip` → リポジトリ直下`*.zip` の順で最も新しいzipを自動選択して渡す。
  見つからなければ「zip未生成のためSKIP。配布zip作成後に必ず実行すること」と明示し、
  黙って落とさない。
- `devtools\u45_toto_perceptual_audit.py` は`--live`でリポジトリ実体を直接検査できるので、
  zipの有無に関わらず常時実行する。
- u45とu28のどちらかがFAILならA1はFAIL。両方SKIPならA1もSKIP。それ以外はPASS。
- **`--zip-audit defer`(WP17、2026-07-27追加)**: `release.py`のリリースフローでは
  `ship_smoke --fast`は新しい配布zipをビルドする**前**に走るため、`dist\`にあるのは
  常に前回リリースの旧zip。それをu28で鮮度照合すると直前の正当なコード修正が
  毎回不一致検出される(構造的偽陽性、v1.1.1リリースのA1誤FAILで発覚)。
  このオプション指定時はu28_zip_audit.pyを実行せず「ビルド後の新zipに対して
  release.pyが実施(deferred)」と理由付きでSKIP扱いにする(u45 --liveは変わらず必須実行、
  FAILなら従来どおりA1もFAIL)。オプション無しの既定(`auto`)は従来どおり最新zipを監査する。

### A2の実装メモ(負の対照のとりかた)

`check_doc_consistency(root)` は `ship_smoke.py` 側に独立した純関数として実装している
(pytestにもCLIにも依存しない)。任意のディレクトリを渡して単体で呼べるので、
リポジトリ本体のREADMEを書き換えずに「壊れたドキュメント」を一時ディレクトリに
作ってFAILすることを確認できる(下記「検証記録」参照)。

判定は単語境界必須の正規表現(`\bFBX\b`)を使う。`manual\manual.html` はBlenderで
生成したPNGをbase64埋め込みしており、その文字列中に単純な部分一致で"FBX"が
偶然含まれるケースが実測で複数見つかった(例: `...FBXsUD3LL...`)ため、単語境界なしの
検査は誤検知する。単語境界ありなら実測で誤検知ゼロ。

### A6の実装メモ(2026-07-26 FX班追加)

背景: 2026-07-26、開発機以外のPCで `convert.ps1` 経由の変換が
`UnicodeEncodeError: 'cp932' codec can't encode character '—' in position 75` で
Phase 0(`convert_noue.py`の`ensure_vanilla()`)の時点で必ずクラッシュする不具合が
発覚した。原因は、GUI等からPython子プロセスの標準出力がリダイレクト/パイプされる
状況で、`convert.ps1`がPYTHONIOENCODING/PYTHONUTF8を明示設定していなかったため、
Pythonが`locale.getpreferredencoding()`(日本語WindowsではUTF-8ベータ機能を
有効化していない大多数の環境で既定cp932)にフォールバックしていたこと。
詳細な再現手順・実エラー出力・修正の妥当性検証は `work\fx_cp932\fix_FX_cp932.md`
参照。修正は`convert.ps1`冒頭への

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
```

の2行追加(`tests\coverage\run_overnight.ps1`に既にあった対策と同一)。

**A6が検査していること**: 「emダッシュという文字が無いこと」ではない(それは対症療法で、
次に別の非ASCII記号が入るたびに再発する)。検査するのは
**「cp932しか使えない環境下でも、実際に子プロセスがクラッシュしないこと」**という
実行時の振る舞いであり、かつ判定は`convert.ps1`の**現在の実体**
(`PYTHONIOENCODING`/`PYTHONUTF8`設定行を動的に読み取る、コメントアウトされた行は
除外)から動的に導く。具体的な手順:

1. `pipeline\py\`・`pipeline\blender\`配下の全`.py`から、文字列リテラルを実際に
   `.encode("cp932")`してみて失敗するもの(=cp932非互換文字を含むもの)を動的に
   収集する(em dash専用のスキャンではなく汎用判定。将来別の記号が入っても自動で
   検出対象に入る)。加えて、将来ソース側から全部除去されてもゲート自体が
   無意味化しないよう、カナリア文字列(em dashを含む固定文字列)を必ず1つ加える。
2. 「他PCで起きたこと」を再現する基底環境(hostile env)を作る: この開発機自身の
   ユーザー環境変数(`PYTHONUTF8=1`が`HKCU:\Environment`に永続化済み——今回の
   調査で判明した、開発機がたまたま踏まなかった理由そのもの)がテストをマスク
   しないよう、`PYTHONUTF8`/`PYTHONIOENCODING`をプロセス環境から完全に除去した上で
   `PYTHONIOENCODING=cp932`を明示指定する。レジストリのACP実値に依存しないので、
   どのホスト(CI含む)で走らせても同じ条件になる。
3. `convert.ps1`の実体を読み、`$env:PYTHONIOENCODING = "..."` /
   `$env:PYTHONUTF8 = "..."` の行(コメント行は除外)があればhostile envの上に
   上書きする。`convert.ps1`を実際に起動しない(ミューテックス排他や実変換を
   避けて高速化)が、判定は`convert.ps1`の現在の中身に追従する。
4. 上記1で集めた文字列を、上記2-3で作った環境のPythonサブプロセスへ実際に
   `print()`させ、`UnicodeEncodeError`が出ないこと・全件出力できたことを確認する。

`convert.ps1`にPYTHONIOENCODING/PYTHONUTF8の設定行が見つからない場合(修正が
外れている場合)は、hostile envがそのまま残るため無条件でFAILする。

**負の対照(検証記録、2026-07-26)**: `convert.ps1`の該当2行を一時的に
`#NEGATIVE_CONTROL_TEMP_REMOVED#`でコメントアウトしてA6を実行したところ、実際に
`subprocess rc=1`・`UnicodeEncodeError: 'cp932' codec can't encode character
'—' in position 21`が観測され、A6はFAILした。直後に2行を復元し、A6が
再びPASSすることを確認した(コメント行を誤って検出しないよう、判定ロジックは
行頭が`#`の行を除外して読む)。

### A8の実装メモ(2026-07-27 WP11追加)

背景: リリースゲート群(`devtools\release.py` / `ship_smoke.py`)は既に完成しているが、
「ふつうの使い方」の入口であるGUI(`app\DiveToPalworld.cs`)の「フル変換」ボタンが
実際に行う **job.json生成(`WriteJob()`) → convert.ps1起動
(`BuildConvertScriptPath()`/`BuildConvertArgs()`/`FindPwsh()`)** という配線そのものは
誰も検証していなかった。A3は「GUIが起動して3.5秒落ちない」ことしか見ておらず、
job.jsonの中身や起動コマンドは一切見ていない。2026-07-26のcp932事故
(`work\fx_cp932\fix_FX_cp932.md`)はまさに「GUI経由でconvert.ps1の標準出力が
リダイレクトされる」状況が引き金だった——**GUI発の配線が壊れると起きるクラスの
不具合**であり、A6はconvert.ps1自体の対策の実行時効果は検証しているが、
「GUIがどう起動するか」は依然として無検証だった。

このプロジェクトのクリック自動化はこの環境では実行できない(WP6 T6で確認済み)ため、
ヘッドレス契約テストで代替する。

**GUI側に加えた変更(`app\DiveToPalworld.cs`、追加のみ)**:
1. `BuildConvertScriptPath()` / `BuildConvertArgs()` — `RunPipeline()` に元々
   あったconvert.ps1のパス解決・引数組み立てのロジックをそのままメソッドへ
   切り出した(戻り値・動作は不変)。`RunPipeline()`側は切り出したメソッドを
   呼ぶよう2行だけ変更している(この2行以外、GUIの見た目・通常動作は無変更)。
2. `EmitWiring(outDir, repoRoot)` / `--emit-wiring <出力先dir> <appRootに使う
   リポジトリ直下>` という隠しCLIモード(`Main()`に分岐を追加)。実際にGUIが
   「フル変換」時に呼ぶのと**同じメソッド**(`WriteJob()` / `BuildConvertScriptPath()` /
   `BuildConvertArgs()` / `FindPwsh()`)を画面を出さずに呼び出し、結果
   (job.jsonの中身、起動しようとするシェル・スクリプトパス・引数)を
   `wiring.json` / `job.json` としてファイルへ書き出して終了する。
   **convert.ps1は起動しない**(ミューテックス排他・実変換を避けて高速化)。
   第2引数(repoRoot)は、検査用にビルドしたexeが配布物と異なる場所
   (`work\relgate\wp11\...\build\`)に置かれ、通常起動時のappRoot自動検出
   (「exeの隣、無ければ親にpipeline\があるか」)だけでは正しいリポジトリ直下を
   見つけられないことがあるためのテスタビリティ用引数(job.jsonの値そのものは
   検体依存で検査対象外なので、フォルダ解決だけをここで補正する)。

**`gui_wiring_check.py` が検査すること**:
- **(a) job.jsonのスキーマ・必須キー**: `vrm_path` / `avatar_name` / `engine_mode` /
  `paths`(top-level)、`paths.blender_exe` / `paths.vrm_addon_zip`。根拠は
  `convert.ps1`冒頭コメント(8行目「前提: job.json(paths.blender_exe /
  vrm_addon_zip 必須...)」)+実装(`$Blender`未存在なら`Write-Error`即`exit 1`)+
  `pipeline\blender\vp_bl.py::ensure_vrm_addon()`(`vrm_addon_zip`を読む)+
  `pipeline\job.example.json`(CLI直接利用者向け公式サンプルも同じキー組を提示)。
  値そのものは検体依存で可(存在・非空文字列であることのみ確認)。
- **(b) 起動コマンド**: `script`が実在する`pipeline\cli\convert.ps1`を指し、
  `-File "<script>" -Job "<job.jsonの実パス>"`が正しく渡っていること。
- **(c) 環境変数契約**(PYTHONIOENCODING=utf-8 / PYTHONUTF8=1): 責務は
  `convert.ps1`側(自分の子プロセス全部に効くよう冒頭で無条件設定)にあり、
  GUI(`ProcessStartInfo`)は`EnvironmentVariables`を一切明示操作していない
  (=親環境をそのまま継承させるだけで、convert.ps1の自己設定を上書き・阻害する
  余地が構造的に無い)。このゲートは「GUI側がこの2変数を明示操作して
  convert.ps1の設定と競合していないこと」+「convert.ps1側が実際にこの2行を
  (コメントアウトせず)無条件で持っていること」の両輪を検査する
  (`check_env_contract()`のdocstring参照。実行時のcp932クラッシュ耐性自体は
  A6が別途担保している。A8は「GUIがそれを阻害していないか」という配線側の
  契約)。

**負の対照(検証記録、2026-07-27)**: `gui_wiring_check.py --mutate <種類>` で、
`app\DiveToPalworld.cs`の一時コピー(本体は変異しない)に対して2種類の変異を
それぞれ適用し、狙った検査項目だけがFAILすることを実測で確認した:

| 変異 | 内容 | 結果 |
|---|---|---|
| `missing_key` | `WriteJob()`から`"engine_mode"`を書く1行を削除 | `a_job_schema`がFAIL(`top-level必須キー欠落: engine_mode`)。`b_launch_command`/`c_env_contract`はPASSのまま(意図した箇所だけが落ちることを確認) |
| `broken_path` | `BuildConvertScriptPath()`の戻り値を`convert_BROKEN_PATH_NEGATIVE_CONTROL.ps1`に変更 | `b_launch_command`がFAIL(`scriptが期待パスと不一致`)。`a_job_schema`/`c_env_contract`はPASSのまま |

(初回実行時、変異コピー用の最小フィクスチャに`third_party\`のVRMアドオンzipを
含めておらず、`WriteJob()`の`J(addonZip)`が`addonZip==null`で
`NullReferenceException`を投げて意図と違う箇所で落ちる誤検知が出た。
`_prepare_source_tree()`が変異コピーへ実物のzipを1つコピーするよう修正し、
再実行して上表の結果に収束させた。)

**ship_smoke.py統合**: `gate_a8_gui_wiring()`が`gui_wiring_check.py`をimportして
`run_check(mutation_key=None)`(通常検査)を呼ぶ。**書き込み許可域の都合で
ship_smoke.py呼び出し元の`--work`は使わず、常に`gui_wiring_check.default_work_root()`
(`work\relgate\wp11\gui_wiring_check_<timestamp>\`)へ出力する**(他WPの作業域と
衝突しないため。将来この書き込み制限が外れたら通常のgate同様`work_root`引数を
使う形に統一してよい)。

## Tier B(SE班 `ship_convert_cases.py` を呼ぶだけ)

```python
from ship_convert_cases import CASES, run_case
CASES = [{"name": str, "est_sec": int, "desc": str}, ...]  # 重要度降順
run_case(case, work_root, shots_dir) -> {"name","ok","seconds","images","detail"}
```

- import失敗時(未実装含む)は「Tier B 未接続(SKIP)」として報告し、Tier Aだけで
  完走する(SE班の実装完了を待たない設計)。
- `--minutes` を実時間の上限として守る。Tier A完了後、`CASES` を先頭(重要度が高い順)
  から見て、その時点の残り時間に `est_sec` が収まるものだけ実行する。収まらない
  ケースは**スキップして次のケースの判定へ進む**(1つ大きいケースが弾かれても、
  後続のもっと軽いケースが収まるなら実行する)。実行しなかったケースは必ず
  `report.md` に `SKIPPED(時間切れ)` として明記する(黙って打ち切らない)。
- `run_case` が返す `images` は `<work>\shots\<ケース名>_<元ファイル名>` にコピーする
  (人間の官能検査用にフラットな1フォルダへ集約)。

## 出力

- `<work>\report.md` — 1ゲート/1ケース終わるごとに追記してflushする(逐次書き込み、
  途中停止しても直前までの結果は残る)。A1は実行順が最初なので常にレポート冒頭に出る
  (加えて🔴マーカーで強調)。末尾に全体サマリ表を追記する。
- `<work>\shots\` — Tier Bの画像を集約(Tier Aは画像を出さない)。
- `<work>\build\` — A3のビルド出力先(リポジトリ直下の`Uchinoko.exe`(v2.0.0改名)には触れない)。
- `<work>\pycache_scratch\` — A4のpy_compileが吐く`.pyc`置き場(`pipeline\`配下を
  汚さないための逃がし先。中身は使わない)。

## 既知の制約・実行時に見つかった事項

- **(2026-07-27 WP6是正)「A1(u28_zip_audit.py)は現行dist zipに対して実際に
  FAILする」という旧記載は解消済み、今となっては誤り。** `devtools\u28_zip_audit.py`
  の `EXPECTED_TOP_LEVEL` / `EXPECTED_INTERNAL_TOP_LEVEL` は2026-07-26のうちに
  現行の `_internal\` ラッパー構成 + `manual.html` 同梱へ既に追随済み(WP6着手時点の
  `git log` で確認、コミット `6418f19` 時点で修理完了)。実測(2026-07-27、
  `dist\DiveToPalworld_v1.0.0_full.zip`)で **PASS** を確認済み。負の対照(余計な
  トップレベル項目混入・禁制品混入)も両方FAILすることを確認済み
  (`work\relgate\wp6\REPORT.md` T1節)。
- A3の`app\build_app.ps1`は既定で`ico\favicon.ico`をwin32iconに使うが、無くても
  ビルド自体は失敗しない(スクリプト側でTest-Path分岐済み)。
- A4のimport対象は `pipeline\py\*.py`(直下のみ、非再帰glob)。`pipeline\blender\*.py`
  は bpy 前提で通常のpython環境では絶対にimportできないため対象外(py_compileの
  構文チェックだけは全件に掛かる)。dev#114(2026-07-29)でUEクックパイプライン
  (`pipeline\ue\`)を削除した際、noue実行時資産の再生成ツール(`import unreal`する
  ものを含む)を `pipeline\py\ue_archive\`(サブディレクトリ)へ移設したが、非再帰
  globの対象は `pipeline\py\` 直下のみなのでこのサブディレクトリは元々の
  `pipeline\ue\*.py` と同様に自動的にimport確認の対象外のまま(py_compileは
  os.walkで全件を見るので構文チェックは引き続き掛かる)。

## T2(WP6、2026-07-27): 配布zipスモーク(クリーン環境シミュレーション)

`tests\shipcheck\dist_smoke.py` — ship_smoke.py(Tier A、~2分)より重く、実際に
配布zipを展開してエンドツーエンドで1回変換する(~5分)。**位置づけの違い**:
Tier A/A1(u28_zip_audit.py)はzipの**中身の一覧**(残骸・レイアウト・禁制品・鮮度)
しか見ない静的検査であり、「展開して実際に動くか」は検査していなかった。
dist_smoke.pyはその穴を埋める。

**やること**:
1. `dist\*.zip` の最新を一時フォルダへ展開
2. `subst` で空きドライブレターを割り当て、**C:以外のドライブ**上で実行する
   (開発機のCドライブに存在する何かに構造的に依存していないかを検出)
3. WP4が確立したcp932敵対環境技法(`PYTHONUTF8`/`PYTHONIOENCODING`をプロセス
   環境から除去)を適用し、convert.ps1自身の対策(pipeline\cli\convert.ps1が
   自前で設定する2行)だけに依存させる
4. 展開物**だけ**(convert.ps1本体・Blender・VRMアドオンzip)を使って変換を
   1本完走させる。検体(vrm/fbx)はリポジトリから読み取り専用で供給してよい
   (検体そのものは配布物の一部ではないため)
5. fail-closed: zip無し/展開失敗/変換失敗は全て赤。`subst`解除・一時物削除は
   `finally`で保証

**使い方**:
```powershell
python tests\shipcheck\dist_smoke.py --work work\<名前>
```

**実測(2026-07-27)**: `dist\DiveToPalworld_v1.0.0_full.zip` を展開(11.0秒)、
`E:\`(空きドライブ)へsubst、敵対環境下でShapell検体を変換 → **PASS**
(281.5秒、pak 689,835,148 bytes生成確認)。負の対照は
`--corrupt-for-negative-control <DiveToPalworld\からの相対パス>` で展開物から
必須ファイルを1つ削除して実行し、fail-closedすることを確認する
(`work\relgate\wp6\REPORT.md` T2節に実測記録)。

## T3(WP6、2026-07-27): DLL/依存クロージャ静的検査

`tests\shipcheck\dll_closure_check.py` — 配布zip内の全`.exe`/`.pyd`のPE
インポートテーブルを読み、システム標準DLL(Windows KnownDLLsレジストリ +
api-ms-*/ext-ms-* API Set + 手動キュレートしたin-boxコンポーネント一覧)以外の
依存がzip同梱物で閉じているかを検査する。実事故(前提ソフト無しの
まっさらなWindowsでpython.exe/ooz.pydがVC++ランタイムを見つけられず即死)の
再発防止。標準ライブラリのみ
(pip追加なし)。詳細・負の対照の実測記録は`work\relgate\wp6\REPORT.md` T3節参照。

**使い方**:
```powershell
python tests\shipcheck\dll_closure_check.py dist\<最新zip>
```

## リリース関所(WP10/WP12/WP13、2026-07-27): `devtools\release.py`

リリースの正規手順は **`python devtools\release.py --bump patch|minor|major
--pak none|expected` の1コマンドのみ**。配布zipはこのスクリプトを通らないと
生成されない(旧手順 `build\make_dist.ps1` 直叩きの手順は廃止済み)。
「何かを実行し忘れるとチェックが抜ける」経路を
構造的に無くすのが目的。`--force` 等の抜け道フラグは存在しない。

**フロー**(どこかで赤が出たら、作りかけのzipを消し・バージョンスタンプを巻き戻し・
非0終了。中途半端な状態を残さない):

1. git working tree がクリーンであること(汚れていたら即FAIL)
2. `devtools\relgate.py --layers 12`(既定検体: flatapron / vrm1_seedsan / vrm0_kate)
   + `tests\shipcheck\ship_smoke.py --fast`(A1〜A8)
3. **pak判定(--pak、WP13 2026-07-27オーナー裁定で最終仕様に統一)**: 判定の正は
   **ただ1つ**、人間がGUI検収で承認した実機記録(`work\u53_cov\
   machine_pak_records.jsonl` の `status="approved"` 行)から集めた「承認済みpak
   SHA256ハッシュ集合」。前回リリース時点のpakとのbaseline差分比較(WP12当初の
   マニフェストエントリ単位比較、`devtools\pak_manifest.py`)はWP13で全廃した。
   - `--pak none`(出力は承認済み状態と同一のはず): 代表検体3体のpak SHA256が
     **全て**承認済みハッシュ集合に含まれていれば**実機試験・GUI検収を完全
     スキップ**して続行。1つでも含まれなければ**実機を起動せず即FAIL**
     (未承認ハッシュ一覧と「--pak expectedで実行し検収を受けよ」の案内を出す)
   - `--pak expected`(出力は新しくなるはず): 代表検体3体のpak SHA256が既に
     **全て**承認済みハッシュ集合に含まれていれば**FAIL**(「実装した」のに
     「効いていない」の検出)。1つでも含まれなければ、その未承認pakに限って
     実機層(4)へ進む
   - `--pak expected` は `--bump minor` か `major` を要求する(`patch`との組合せは
     引数検証の段階で即FAIL)。`--pak none` はどのbumpとも組合せ可
4. **実機層**(`--pak expected` かつ未承認pakがある場合のみ実施。`--pak none` で
   全て承認済みの場合は3で完全スキップ済み): 未承認のpakについて
   **release.py がその場で実機試験を実行**(`apply_test_pak.py` で適用[退避/
   復元厳守]→`play_start_test.py`→クラッシュ判定+キャラSS撮影)。クラッシュ1件
   でも即FAIL
5. **GUI検収(まとめ検収、WP15/PL14で改訂、2026-07-27オーナー裁定)**: 未承認の
   検体すべてについて実機試験(pak適用→起動→クラッシュ判定+撮影)を**先に
   全部**実行し、生存確認できたものは`pending_review`記録を貯める。途中の
   検体でクラッシュ・生存確認不能・pak復元失敗が出たら、その時点で(検収に
   進まず)整ったFAILにする(従来どおり)。全検体が生存確認まで到達したら、
   **1つのGUIウィンドウ**に全検体のスクリーンショットを検体ごとの列で並べて
   表示し、検体ごとに「承認」「却下」ボタンの明示クリックのみで承認可否を
   受け取る(コンソールのy/n入力は廃止。WP12時点の「検体ごとに個別ポップアップ」
   から、複数検体をまとめて1画面で見比べられる形へ変更)。ウィンドウを閉じる
   (×)は、その時点で未決定の検体をすべて却下扱いにする(既に承認/却下済みの
   検体の判定は確定したまま変わらない)。無応答タイムアウト(既定2時間)も
   未決定分を却下扱いにする(既定拒否・fail-closed)。GUIが表示できない環境
   (ヘッドレス等、tkinter初期化失敗)は実機に入る前の段階でFAIL(リリースは
   人間の行為)。自動承認の抜け道(環境変数等)は無い。全検体が承認された場合の
   み続行(1つでも却下/クローズ/タイムアウトならFAIL、従来のセマンティクスを
   維持)。承認された検体のpak SHA256はそれぞれ"approved"記録として追記され、
   以後のリリースで同じpak(内容が変わらない限り)は実機層をスキップできる
   ようになる
6. **バージョン規律**: 新バージョンは `--bump` と `.devonly\publish\releases.json`
   (git管理のリリース履歴: version/日付/代表pak SHA256/zip SHA256/pak宣言)から
   自動計算。**WP13以降、releases.jsonのpak_hashesは履歴記録専用でありバージョン
   規律の判定には使わない**(pakが変わるほどの変更かどうかは3節の`--pak
   expected`宣言と`--bump minor|major`要求で既に構造的に担保している)。バージョン
   後退・重複は、新バージョンが常に直前エントリからの繰り上げでのみ計算される
   ため構造的に発生しない
7. 全緑で `ToolVersion` スタンプ → zipビルド → zip監査3種(u28 / dist_smoke /
   dll_closure)→ `release vX.Y.Z` コミット+annotated tag → releases.json 追記
   (履歴記録専用)

初回セットアップ: `python devtools\init_release_history.py` で現行リリース
(v1.0.0)を履歴に登録してから使う。承認済みハッシュ集合が空の初回ブートストラップ
時は、`--pak none` でも `--pak expected` でも未承認pakとして扱われ、`--pak none`
なら即FAIL・`--pak expected`ならその場で実機試験+GUI検収に進む(実機未確認のpak
がそのままリリースされる穴を防ぐため)。夜間の `run_overnight.ps1 -Machine` は
「approved記録を先に作っておくとリリース当日の実機工程を省ける」任意の前倒しに
位置づけが変わった(必須ではない)。

分岐ロジックの検証はdry-runハーネス(`work\relgate\wp10\gate_probe\`)で実測済み
(WP13改訂後、承認済みハッシュ集合判定の6分岐を含め全緑。詳細は
`work\relgate\wp13\REPORT.md`)。**本物のPalworld起動+実コミットを含む通し実行は
初回リリースリハーサルで行うこと**(未実施の旨は `work\relgate\wp10\REPORT.md`
に記録)。
