# tests\shipcheck — 出荷検査スイート(pytest)

出荷前最終検査(ゲートA〜G+設定マトリクスH)をデータ駆動で実行するpytest
スイート。仕様の正本は [`docs\U23_SONNET_INSTRUCTIONS.md`](../../docs/U23_SONNET_INSTRUCTIONS.md)
(ゲートの定義)と本ディレクトリのコード自身。本READMEは実行方法のみを扱う。

## 構成

```
tests\shipcheck\
  conftest.py     フィクスチャ・CLIオプション
  cases.py        アバター表・設定フリップ表・プロファイル定義
  gates.py        ゲート判定ロジック本体(A〜G/H1、pytestに依存しない純関数)
  test_offline.py    ゲートA〜D(変換・pak存在・preflight・noue出自)+静的構造検査+H1
  test_machine.py    ゲートE(起動)・F(実プレイ開始)  @machine
  test_visual.py     ゲートG(見た目AI一次照合、advisory)  @visual
  report.py       実行後レポート生成(junit.xml/report.md/contact_sheet.md)
  selftest\       モック自己検証(実機・変換・実pak不要)
```

## 安全設計(既定は「何もしない」)

以下は**既定で無効**。指定しない限り、実変換も実機接触も一切発生しない
(該当ケースはSKIPになるだけ):

- `--allow-convert` — 指定時のみ`pipeline\cli\convert.ps1`を実際に実行する
- `--allow-machine` — 指定時のみPalworld実機へ接触する(pak適用・起動・操作)

これにより、他セッションが変換や実機を使用中でも本スイートは安全に併走できる。

## pakキャッシュ

`pak_for`フィクスチャは job.json内容 + `TEMPLATE_BUILD_VERSION` + git HEAD +
`--target-root` をキーにpakをキャッシュする(`work\u32_diag\pak_cache\`)。
同一条件なら1体20分級の変換を再度実行しない。キャッシュキーが変わる
(設定・コード・被検体ルートのいずれかが変わる)と自動的に再構築される。

## `--target-root`(配布zip最終出荷検査モード、2026-07-25運用開始)

既定では本リポジトリ自身の`pipeline\cli\convert.ps1`を被検体として使うが、
`--target-root <配布zip展開先>` を指定すると、そちらの
`<target-root>\pipeline\cli\convert.ps1`を実行する
(job.json・テストコード・devtools側の実機操作ツールは常に本リポジトリのまま
= ハーネスと被検体を分離)。**最終出荷検査はこのオプションで隔離ディレクトリを
指定して回すのが本番運用**(配布物だけを実行させることで「開発環境の残骸に
救われている」誤判定を防ぐ)。

```powershell
python -m pytest tests\shipcheck --avatars all --allow-convert --allow-machine `
    --target-root C:\d2p_dist_test --run-dir work\u32_diag\shipcheck_reports\dist_full
```

## プロファイル

| プロファイル | 対象 | ゲート | 目安時間 | コマンド |
|---|---|---|---|---|
| smoke | toto 1体 | offline+machine | 約30分 | 下記参照 |
| full | 11体+設定マトリクス6件 | offline+machine+visual+H1/H2 | 6〜8時間 | 下記参照 |
| corpus | `test\vrm\collected` 26体 | offline+machine | 数時間〜(体数依存) | 下記参照 |
| stats | 指定pak×`--repeat N` | machine(F)のみ | N×5分程度 | 下記参照 |

### smoke(回帰確認用、パイプライン修正後にまず実行)

```powershell
python -m pytest tests\shipcheck --avatars smoke -m "not visual" --allow-convert --allow-machine
```

### full(U23本番相当。11体+設定マトリクス、見た目照合まで)

```powershell
python -m pytest tests\shipcheck --avatars all --allow-convert --allow-machine
python -m pytest tests\shipcheck\test_offline.py -k gate_h1 --allow-convert   # 設定マトリクス(H1)
```

### corpus(意地悪コーパス26体、頑健性マトリクス。U27相当)

```powershell
python -m pytest tests\shipcheck --avatars corpus -m "not visual" --allow-convert --allow-machine
```

job.jsonは`_ensure_corpus_job`ヘルパが`work\u32_diag\corpus_jobs\<name>\job.json`へ
自動生成する(既定設定、`pipeline\cli\smoke_all.ps1`のjob辞書パターンを踏襲)。

### stats(クラッシュ率記録。U26b相当)

```powershell
python -m pytest tests\shipcheck\test_machine.py --avatars heon --repeat 20 --allow-machine
```

`--repeat`回のうち何回クラッシュしたかは`report.md`のdetail列
(`n_crash`/`n_pass`/`exit_codes`)に記録される(合否ではなく率の記録が目的)。

## 実機接触を伴うオプション

- `--world modtest|panworld`(既定modtest。panworldは`save_guard`フィクスチャが
  セーブのバックアップ→整合検証→リストアを自動で行う)
- `--shots-dir <path>`(SS保存先。既定はレポートディレクトリ配下の`shots\`)

## selftest(モック自己検証)

実機・変換・実pak不要。CIやこのスイート自身の改修時にまず実行する:

```powershell
python -m pytest tests\shipcheck\selftest -q
```

## 出力(レポート)

各実行ごとに `work\u32_diag\shipcheck_reports\<timestamp>\`
(`--run-dir`で上書き可)へ以下を生成する:

- `provenance.json` — git HEAD・TEMPLATE_BUILD_VERSION・実行日時・target_root
- `results.jsonl` — 全ゲート判定の生ログ(1行1判定)
- `junit.xml` — CI取り込み用(pytest本体のCIサマリが要る場合は別途
  `--junitxml=<path>`をpytestに渡せば標準のjunit-xmlも並行して得られる)
- `report.md` — 結果表(avatar/case/gate/status/detail)
- `contact_sheet.md` — 体ごとにゲーム内クロップSS・Blender参照・判定JSONを
  並べたシート(見た目advisoryの最終目視用)

## スイートが落ちたときの調査の入口

1. まず `report.md` を開き、FAIL行のavatar/gate/detail列を見る
   - `A_convert_exit0` FAIL → `detail.log_tail`(変換ログ末尾)
   - `C_preflight_9of9` FAIL → `detail.failed`(落ちたG1〜G9のどれか)
   - `D_noue_provenance` FAIL → `detail.found_ue_fingerprints`(UE経路混入の証拠)
   - `static_check` FAIL → `detail.problems`(ファイル単位の構造異常)
   - `H1_settings_wiring` FAIL → `detail.diff_paths_sample`(差分が出ていない/
     想定外の場所にしか出ていない)
   - `E_crash_notcrashed` / `F_play_start` FAIL → `detail.log`(crash_test/
     play_start_testの出力。クラッシュ証跡パスが含まれる)
   - `G_checker` / `G_compare_avatar` — advisoryなのでスイートは止まらない。
     `contact_sheet.md`で該当avatarのSS/参照/判定JSONを並べて目視確認する
2. 次にresults.jsonlの該当行(同じgate/avatar)を見ると、report.mdで
   省略された詳細(300字超の切り詰め分)が全文で読める
3. offline系ゲート(A〜D)が全滅している場合は、まず
   `python -m pytest tests\shipcheck\selftest -q` でスイート自身が壊れて
   いないかを切り分ける(selftestが通るならスイートは健全 → 対象の変換/pak側の問題)
4. pakキャッシュの状態を疑う場合は `work\u32_diag\pak_cache\<avatar>_*.json`
   を直接見る(pak_path/sha1/git_head/template_build_version/target_rootを記録)

## 既知の制約

- ゲートGの判定(`checker_pattern_check`/`compare_avatar.compare`)はローカル
  `claude` CLIのヘッドレス呼び出しに依存する。CLIが無い/失敗する環境では
  自動的にSKIP(判定不能)として記録される(advisoryなので全体は止まらない)
- H1(設定配線ゲート)は常に`toto`をベースラインに取る(2マテリアル・最速・
  最安定という選定理由はU23 T1bと同じ)
- 設定インベントリ(`cases.SETTINGS_FLIPS`)は
  docs\U23_SONNET_INSTRUCTIONS.md T1b-1の「既知の最低ライン」5項目のみを
  収録している。新設定が追加されたらここへの追記漏れが検査漏れになる
