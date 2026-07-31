# relgate — リリースゲート(層0/層1/層2)

`devtools\relgate.py` は、private issue #9「試験体系化: 軽い層を毎回・重い層
(実機)を夜間に置く3層+決定性ゲート」のうち、層0/層1/層2を1コマンドで回す
統合ランナー。**「安心してリリースできる仕組み」**の一部で、
`tests\shipcheck\ship_smoke.py`(出荷直前20分ゲート)・`tests\coverage\`
(カバレッジスイート)・実機チェック(crash-check / play-start-check)とは
置き換えではなく、それらの**手前で毎回まわす、もっと軽い層**という位置づけ。

## 層構成と、それぞれが何を守るか

| 層 | 何を守るか | 実体 | 実行タイミング |
|---|---|---|---|
| **層0 決定性** | 同じ入力・同じコードから焼いたpakが、毎回バイト単位で同一であること。ここが崩れると「baselineと比較して差分が出た」こと自体の意味が無くなる(比較対象が毎回揺れるなら差分検出が信用できない) | 既定検体(`prefab_flatapron`、WP9で変更)を同一job.jsonで**2回**フル変換し、pak本体のSHA256を比較する | 重い(1回約5分の変換を2回=約10分)。**変更時のみ**でよい |
| **層1 中身差分** | pakの中身(エントリ単位)が、前回承認した状態からどう変わったか。**バイナリ全体のハッシュ比較はしない**(意図した変更のたびに赤になり運用に耐えない)。エントリ単位で「追加/削除/変更」を提示し、人が承認する | `devtools\pak_manifest.py`(WP2成果)。既定恒常セット各検体のフル変換結果をmanifest化し、`tests\relgate\baseline\<検体キー>\manifest.json` と比較 | 毎変更 |
| **層2 見た目相関** | 「数値は揃っているのに実物は壊れていた」を機械的に検出する。素体と衣装のズレ、テクスチャが別の絵に化ける、UV外れで灰色になる、といった**画像を見ないと分からない**回帰 | `tests\relgate\visual_check.py`。既定恒常セット各検体の変換で生成される固定画像(アトラス化前後×男女、検体により最大4枚)を承認済みbaseline画像とNCC比較 | 毎変更(Blenderのみで完結、Palworld実機には触れない) |
| 層3 実機 | 実際にPalworld上でクラッシュしない・プレイ開始できること | 既存の `palworld-crash-check` / `palworld-play-start-check` スキル(`devtools\crash_test.py` / `devtools\play_start_test.py`) | 重い。夜間 or リリース直前 |
| **T4 ログ診断力**(WP6追加) | 問い合わせ診断に必須の構造情報(engine_mode/フェーズ進行/工程完了/material_mapカバレッジ/remap結果/pak出力パス)が**成功時のログにも**残っていること。CLAUDE.md「問い合わせからのデバッグ」節の実例(帽子が足元に落ちて灰色になる事故)の恒久対策 | `tests\relgate\log_diagnostic_contract.py`。既定検体(`prefab_flatapron`、FBX/Unity輸出入力)の変換が生成する `<run_dir>\convert_stdout.log`(WP6でrelgate.pyに追記させた)+ `build\logs\*.log` を読む | 毎変更(層1/2の変換に相乗り、追加の変換コストゼロ) |

**WP9(2026-07-27)で既定検体をShapellから変更**: リリース可否を判定するbaselineは
「安全・楽(CC0)」ではなく「オーナーが大事にしているものの代表性」で選ぶという
オーナー裁定を受け、既定恒常セット(層1/2)を`prefab_flatapron` + `vrm1_seedsan` +
`vrm0_kate`の3検体に、層0の既定検体を`prefab_flatapron`単体に変更した。
詳細は本文書後半「検体の選定(WP9、2026-07-27)」節を参照。

## T4: ログ診断力の契約テスト(WP6、2026-07-27追加)

前提はCLAUDE.md「問い合わせからのデバッグ」節: ユーザーのアバターは絶対に
送ってもらえない。手に入るのは「ログをコピー」の中身だけであり、**ログだけで
原因に到達できないなら、その不具合は永久に直らない**。しかも「成功したのに
結果が変」型の問い合わせ(`.devonly\support\INQUIRIES.md`に多数)が最も多く、
**失敗ログの強化だけでは足りない**——成功時にも構造が残っている必要がある。

`tests\relgate\log_diagnostic_contract.py` は、layer1/2用に既定検体
(`prefab_flatapron`、WP9でShapellから変更)を1回変換した結果のログ
(`devtools\relgate.py`の`run_convert()`が保存する
`<run_dir>\convert_stdout.log`)を読み、以下が出力されているかを検査する:

| 項目 | 根拠 |
|---|---|
| `engine_mode`(`=== EngineMode: ... ===`) | どのパイプライン経路(noue/ue)かの特定はINQUIRIES.mdの多くの症状(noue dev-fallback系)の出発点 |
| `phase_progress`(`=== Phase N ===`、2回以上) | bug-reportスキル手順1「ログの各行をfile:lineへ突き合わせる」にはフェーズ区切りが要る |
| `step_completion`(`[stepNN...] OK (...)`) | 「実装した」と「効いている」は別(CLAUDE.md)。工程が完了した証跡 |
| `material_slot_coverage`(`[step01] slot mNN: ... (unity map)`) | 帽子事故の恒久対策。全メッシュの解決結果が成功時にも残る必要がある |
| `remap_lines`(`[step02] remap: ... -> N pal groups`) | 帽子事故のもう半分(位置ズレ)の診断に使った実ログそのもの |
| `pak_output_path`(`pak: ...\*.pak`) | 「成功したのに結果が変」型の診断に、期待したpakの実パスが要る |

**統合方法**: `devtools\relgate.py`の`run_convert()`を、成功/失敗にかかわらず
標準出力全文を`<job_dir>\convert_stdout.log`へ保存するよう変更した(従来は
FAIL時の末尾40行しかレポートに残らなかった)。`main()`は層1/2用の変換が
1回でも走れば(`--layers`指定に関わらず)`layer_t4()`を自動実行し、追加の
変換コストをゼロに保っている。

**負の対照(2026-07-27実測)**: 実際の成功ログから`(unity map)`行と
`pal groups`行を除去したテキストに対して`check_log_diagnostics()`を呼ぶと、
`material_slot_coverage`/`remap_lines`の2項目だけが正しくFAILすることを確認
(他の4項目はPASSのまま=誤検知していない)。詳細は`work\relgate\wp6\REPORT.md`
T4節参照。

**既知の限界**: `material_slot_coverage`はFBX(Unity輸出)入力の
`material_map.json`経由の解決結果を見る実装であり、VRM直入力(`vrm0_kate`/
`vrm1_seedsan`等)はマテリアル解決の実装経路が異なる(VRM本体の
マテリアル情報を直接読む)ため、この項目はFBX入力(既定検体の`prefab_flatapron`、
WP9でShapellから変更)でのみ検査している。VRM直入力向けの同種契約は将来の拡張課題。

(2026-07-27: `vrm1_alicia`は非準拠検体撤去により`vrm1_vita`へ差し替え済み。
本節の記述内容(VRM直入力の実装経路の話)には影響しない。)

## 検体の選定(WP9、2026-07-27オーナー裁定)

**設計の転換**: baselineは「安全・楽(CC0)」ではなく「オーナーが大事にしている
ものの代表性」で選ぶ。具体的な代表性の軸は4つ:
①ケモノアバター ②Modular Avatar(MA)カバレッジ ③VRM0/VRM1/prefabの3公式
入力形式カバレッジ ④drop_bones(除外ボーン)機能カバレッジ。

**既定恒常セット(層1/2、`DEFAULT_AVATARS`)**:

| キー | 検体 | 代表する軸 |
|---|---|---|
| `prefab_flatapron` | `C:\UnityP\apron\Assets\flatapron.prefab`(元データ`C:\UnityP\DiveToPalworldPreviousAvatars`) | prefab入力・Modular Avatar(NDMFベイク)・ケモノ |
| `vrm1_seedsan` | `test\vrm\Seed-san.vrm` | VRM1.0入力・drop_bones機能(背中の機械腕`robo_root_pole`を除去する回帰を兼ねる) |
| `vrm0_kate` | `test\vrm\collected\100Avatars_038_Kate.vrm` | VRM0.x入力(既存、変更なし) |

**層0(決定性、低頻度)の既定検体**: `prefab_flatapron`のみ(`DEFAULT_AVATAR_KEY`)。
複数検体を2回焼きすると層0だけで検体数×10分かかり、"毎変更"ではなく
リリース前限定の低頻度ゲートという位置づけ(本文書冒頭の層構成表)に対して
過剰なため、既定検体1体に限定した。

**opt-in(`--extra-avatars`で明示指定したときだけ回す)**:
- `shapell`(旧既定検体、CC0・人型・旧SDK構成の軽量検体としての価値は残る)
- `vrm1_vita`(旧VRM1.0代表。素直な対照検体としての価値は残る。選定経緯は後述)

```powershell
# 既定恒常セット(flatapron+seedsan+kate)のみ(check、baseline整備済み前提)
python devtools\relgate.py --layers 12 --work work\<名前>

# 既定恒常セットに加えて、opt-inのShapell・Vitaも回す
python devtools\relgate.py --layers 12 --work work\<名前> --extra-avatars shapell,vrm1_vita

# 特定検体だけのbaselineを更新したい場合(他検体のbaselineには触れない)
# devtools\relgate.py の promote_avatar_baselines() をPythonから直接呼ぶ
# (dev#61後、通常経路はrelease.pyのGUI検収承認による自動昇格のみ。
#  個別昇格は復旧・整備用の例外操作であり、必ず画像を目視してから行う)
```

**`prefab_flatapron`の選定理由**: オーナーが大事にしているのは①ケモノアバター
②Modular Avatarカバレッジであり、この2点を単一検体で満たす代表がflatapron
(ケモノ・耳尻尾つき獣人にModular AvatarでD&D構成した衣装)。NDMFベイク後の
見た目をUnity輸出(`export_from_unity.ps1`)経由でFBX化し、Shapellと同じ
FBX入力形態として扱う。輸出結果は`.devonly\fixtures\relgate\flatapron\`に永続化
(`.devonly\fixtures\`は.gitignore対象、Shapellが`.devonly\fixtures\relgate\shapell\`
に置くのと同じ理由。dev#186(2026-07-29「work\に恒常データを置かない」裁定)前は
`work\relgate\wp9\export\`にあったが、work\緊急削除事故で実際に失われ
Unity再輸出で復旧した経緯があり、恒久領域へ移設した)。

**`vrm1_seedsan`の選定理由**: 真正VRM1.0(VRMC_vrm specVersion 1.0)であることに
加え、背中に機械腕(ロボアーム、Humanoid外拡張ボーン)を持つ検体で、これを
`drop_bones`(指定ボーン+子孫のメッシュ削除)で除去する回帰を兼ねる。
`drop_bones`機能は`DEV_NOTES.md`いわく実質この検体のために作られた機能であり、
除外ボーン名`robo_root_pole`は当て推量ではなく
`tests\coverage\test_settings.py::test_drop_bones_seed_robo_arm`
(2026-07-26新設)が「代表性が高く効果が一目でわかる固定ケース」として
確定した設定をそのまま踏襲している(実測: 3795頂点中3745頂点削除、機械腕
本体が消滅、本体・服・髪への巻き込み無し)。
**負の対照(2026-07-27実施)**: `drop_bones`無しでSeed-sanを変換すると、
`converted\preview_male_stand.png`に機械腕が棒立ち(伸びたまま)で明確に写る
ことを確認した(`work\relgate\wp9\seedsan_negctrl\`)。この状態と比較して
`drop_bones: ["robo_root_pole"]`ありの承認画像で機械腕が消えていることを
目視確認済み(=機能が実際に効いていることの確認、CLAUDE.md「実装したと
効いているは別」)。

**`vrm0_kate`の選定理由(既存、変更なし)**: `test\vrm\collected\100Avatars_038_Kate.vrm`
(1.4MB、PolygonalMind「100Avatars」、無改変転売のみ禁止で改変・利用は自由)。
人型・女性・標準体型で実際にヒューマノイドボーンを持つ、100Avatars系最軽量級の
検体。2026-07-27実測: 最初に選んだ`EmissionMigration_v0.106.0.vrm`(202KB)は
UniVRMのマテリアルmigration専用フィクスチャでヒューマノイドボーンを持たず
インポート自体が失敗したため、実際にパイプラインが処理する対象を代表する
Kateへ差し替えた経緯がある(CLAUDE.mdメモ「テストは代表性と情報量で選ぶ」)。

**`vrm1_vita`(opt-in)の選定理由**: `test\vrm\VitaVRM1.0.vrm`。旧選定の
`vrm1_alicia`(`test\vrm\collected\AliciaSolid_vrm-1.00.vrm`、vrm-c/UniVRM_1_0同梱)
は非準拠検体と判明したため撤去した。UniVRMのマテリアルmigration用内部テスト
フィクスチャで、骨格がVRM0.51版から正しく向き直されておらず、パイプライン
変換結果が後ろ向きに写る(検体自体の不備であり、パイプライン側のバグではない
ことを対照実験で確認)。オーナー裁定で、非準拠検体のための恒久フラグ・GUI設定は
追加せず検体を差し替える方針とした。Vitaは対照実験でパイプラインが正しく
正面へ変換することを確認済みの正規VRM1.0検体だが、WP9でVRM1.0代表の座は
drop_bonesカバレッジも持つ`vrm1_seedsan`に譲り、opt-inへ降格した。

**所要時間の実測(WP9)**: 各検体とも約5〜6分。既定恒常セット3検体を毎回
フル実行すると単純合計では15〜18分かかる計算になるが、WP15(PL14)以降は
`convert.ps1`のマシン全体Mutexの保護範囲をPhase 0-1(Blender工程まで)に
縮小し、`devtools\relgate.py`が3検体のconvert.ps1呼び出しをThreadPoolExecutorで
並行起動するようになった。Blender工程(検体ごと約10〜20秒)だけがMutexで
直列化され、全体の9割以上を占めるPhase 2-6(noueビルド)は3検体が実際に
並列で走るため、実測で約5分前後まで短縮される(3検体分の直列合計ではなく、
最も遅い1検体分の所要時間にほぼ収束する)。「毎変更でも軽い」という
層1/2の設計思想(本文書冒頭)との兼ね合いは、3検体を既定にしてでも
代表性(ケモノ・MA・VRM1.0・drop_bones)を優先するというオーナー裁定を
最終判断とした。

層0と層1/2は**独立した検査**であり、どちらも「今の状態は大丈夫か」という
問いに別の角度から答える。層0がPASSでも層1/2がFAILすることは普通にある
(コードを意図的に変更すればpakの中身は変わる。それ自体は正常で、
「差分があるので人間が見て承認してください」という意味)。

### 層0 PASS × 層1 FAIL の特別な組み合わせ(issue #9 必須要件)

`relgate.py`は、層0と層1を両方実行した結果「層0 PASS(今回の2回焼きは一致
=このコード状態自体は再現可能)なのに層1がbaseline差分でFAIL」した場合、
通常の層1 FAILメッセージに加えて明示の注意ブロックをレポートへ出す。

これは2通りの解釈がありうる状況だからである:

1. **コードを意図的に変更した**(新機能・バグ修正)→ 差分は想定どおり。
   リリース時に `--pak expected` を宣言すれば差分明細つきで実機GUI検収へ
   回り、承認でbaselineが自動昇格する(dev#61、下記「baseline承認手続き」)
2. **心当たりの無い変更**なのに差分が出た → ビルド環境のドリフト
   (Blenderのマイナーバージョン更新、依存ライブラリの自動更新等)を疑う。
   層0はあくまで「今この瞬間、2回焼いたら一致するか」しか見ておらず、
   「baselineを取った時点からの環境変化」までは検出できない

exit codeはどちらの場合も他の層1 FAILと同じ非0のまま(層0/層1は独立した
判定であり、どちらのケースも人間の最終判断が必要という点は変わらないため)。
レポート内の注意ブロックを見て人間が判断すること。

## 使い方

```powershell
# 毎変更: 層1+層2(既定恒常セット3検体、Blenderのみ、実機に触らない)
python devtools\relgate.py --layers 12 --work work\relgate_run

# リリース前: 層0(既定検体prefab_flatapronの決定性)も含めてフルセット
python devtools\relgate.py --layers 012 --work work\relgate_release

# pak変更が想定どおりかを差分明細つきで確認するとき(FAILせずPENDING_APPROVALになる)
# ※baselineの更新(承認)はrelease.pyのGUI検収経由でのみ行う(dev#61で--mode approve廃止)
python devtools\relgate.py --layers 12 --work work\relgate_run --pak-declared expected

# opt-in検体(shapell/vrm1_vita)も含めて回す
python devtools\relgate.py --layers 12 --work work\relgate_run --extra-avatars shapell,vrm1_vita
```

- `--work` は必須(省略時はエラー)。convert.ps1の出力先はjob.jsonの
  親ディレクトリから自動決定されるため、`--work`ごとに専用の作業フォルダを
  割り当てることで既定出力先の奪い合いを構造的に防いでいる。
- `--baseline-dir`(既定 `tests\relgate\baseline\prefab_flatapron`)は**層0専用**の
  baseline置き場(fail-closed動作の確認等に使う)。層1/2のbaselineは検体ごとに
  `tests\relgate\baseline\<検体キー>\` に個別に持つ(`--baseline-dir`は影響しない)。
- 変換は `pipeline\cli\convert.ps1` のマシン全体ミューテックス
  (`Global\DiveToPalworld_pipeline`)で**Phase 0-1(Blender工程まで)のみ**
  直列化される(WP15/PL14、2026-07-27)。Phase 2-6(noueビルド)はロック無しで
  実行されるため、`relgate.py`は既定恒常セット(+opt-in追加検体)の
  convert.ps1呼び出しをThreadPoolExecutorで並行起動する(CLAUDE.md「排他
  リソースと並列実行の可否」参照、pak変換行はWP15でこの前提に更新済み)。
  Mutex競合時(Blender工程同士がかち合った場合)は45秒間隔で自動リトライする
  (既定20回、`--retry-wait`/`--max-retries`で調整可)。
- 1検体あたりの所要時間は約5〜6分だが、`--layers 12`は既定恒常セット3検体分を
  並行実行するため合計では約5分前後(実測はG2ゲート、`work\relgate\wp15\
  REPORT.md`参照)。`--extra-avatars`指定分も同じ並行実行の対象に含まれる。
  `--layers 012`はそれに加えて層0(既定検体を2回、従来どおり直列)が乗る。

### 追記: U54 WP-B(2026-07-27)バニラ準備/ライブテンプレートの共有キャッシュ化との関係

`pipeline\py\extract_vanilla.py`(バニラ準備)と`pipeline\py\live_template.py`
(`build_live_template()`、noueテンプレート組み立て、実測約30秒/700MB)は
アバター非依存であるため、WP-Bで出力先を`work\<Avatar>\`から**マシン共有
キャッシュ**(既定`<work_root>\_shared_cache\{vanilla,live_template}\
<fingerprint先頭12桁>\`)へ変更した。`work_root`は`job_dir`の親ディレクトリ
(=`--work`で指定したフォルダそのもの)から解決するため、relgateの並列
実行にとっての実際上の効果は以下のとおり:

- **同一`--work`内で並行実行される既定恒常セット3検体は、共有キャッシュを
  正しく1回だけ構築して使い回す。** 3検体とも同じPalworldインストール
  (=同じfingerprint)を見るため、最初にPhase 0/Phase 2-6へ到達した1検体が
  構築し、残り2検体はロック待ち後にキャッシュヒットする(WP-Bの
  `vp_core.acquire_cache_lock()`が保護する。上述のGlobal Mutexとは別の、
  共有キャッシュディレクトリ単位のロック)。3検体分のvanilla抽出
  (pak全走査)とlive_template組み立てが3回→実質1回に減るため、
  Phase 0とPhase 2-6冒頭がわずかに速くなる方向の効果がある
  (Phase 2-6全体の90%超を占めるのは実アバター注入・アトラス・pak化の
  部分であり、これ自体はWP-Bの対象外なので体感できる短縮幅は小さい)。
- **`--work`を変えるたびに(=relgateを別のワークフォルダで再実行するたびに)
  共有キャッシュも作り直しになる。** `work_root`が`--work`のパスそのもの
  から決まるため、`work\relgate_run1`と`work\relgate_run2`は別々の
  `_shared_cache`を持つ。GUIの通常アバター変換(`work\`直下)とrelgateの
  検体変換とで共有キャッシュが自動的に分かれる形になり、relgateの負の
  対照(意図的な壊れた状態の検証等)がGUI利用者の共有キャッシュを汚す
  心配は無い。裏を返すと、relgateを何度も別`--work`で回す運用では
  「複数アバター間で共有」という本来のメリットのうち「relgate実行を
  跨いだ共有」までは効かない(1回のrelgate実行内の3検体間でのみ有効)。
  env`D2P_SHARED_CACHE`で複数のrelgate実行にまたがる固定キャッシュ場所を
  明示指定すればこの制限を回避できるが、`devtools\relgate.py`自体への
  配線(既定で`D2P_SHARED_CACHE`を安定パスへセットする等)は本WP-Bの
  書き込み許可ファイル一覧に含まれておらず未実装(将来のPLへの引き継ぎ
  事項)。
- 共有キャッシュ機構自体の受入試験は`tests\shipcheck\test_shared_cache.py`
  (本WP-Bで新設)が担う。relgateはこの機構を**間接的に使うだけ**で、
  relgate自身のゲート(層0/1/2)はpak不変を前提に据え置いている
  (WP-Bはpak不変が建前の変更であり、変換結果はrelgateが検証する)。

## baseline承認手続き(dev#61で一本化: release.pyのGUI検収でのみ承認される)

**閾値やハッシュの数値だけを見て承認してはならない。** 2026-07-29のdev#61で
`--mode approve`(事前の手動承認コマンド)は廃止され、承認は次の1本に統合された:

1. pakが変わる変更のリリースは `python devtools\release.py --bump <minor|major> --pak expected`
2. relgateが層1差分を検出すると、FAILせず**差分明細つきPENDING_APPROVAL**で通し、
   release.pyが実機試験→**GUI検収ポップアップ**(実機SS)を出す
3. 人間がSSと差分明細を見て承認 → リリース最終PASS到達時に
   `tests\relgate\baseline\<検体キー>\`(manifest+images)が**原子的に自動昇格**され、
   releaseコミットに含まれる。**却下・タイムアウト・後続ゲート失敗なら1バイトも
   昇格しない**(fail-closed)
4. 単体実行(`relgate.py --pak-declared expected`)はPENDINGの明細を出すだけで、
   baselineを更新する経路はrelease.pyのGUI検収経由以外に存在しない

**人間の目視確認を経ない承認は事故のもと**(数値が揃っているのに実物が壊れていた
ケースがこのプロジェクトで繰り返し起きているため)。この原則はdev#61後も不変で、
変わったのは「目視のタイミングが事前コマンドからリリース中のGUI検収へ移った」ことだけ。

## fail-closed方針

層1・層2とも、以下はすべて **exit非0** になる(SKIPにしない、無言で
PASS側に倒さない):

- baselineが存在しない・壊れている(JSON不正、entries 0件、画像欠落)
- 変換自体が失敗した(convert.ps1が非0終了)
- 変換は成功したが、判定対象のpak/画像が生成されなかった
  (Blenderが落ちた等)
- サイズ不一致等でNCCが計算できない

**最適化**: `--mode check`で層1/2両方のbaselineが未整備の場合、5分かかる
変換自体を省略していきなり赤にする(結論が変わらないので待たせない)。
片方だけ未整備なら、もう片方のために変換は実行する。

## 出力

- `<work>\report.md` — 1層終わるごとに追記・flush(逐次書き込み、途中停止
  しても直前までの結果は残る)。実行のたびに新規化される(1回のrelgate
  実行=1レポート)
- `<work>\layer0_run1\` / `layer0_run2\` — 層0用の2回焼き(層0実行時のみ)
- `<work>\convert\` — 層1/2共有の1回焼き(層0を実行しない、または層0が
  変換自体に失敗した場合)
- `<work>\layer1_manifest_new.json` — 層1で生成したmanifest(baselineとの
  比較対象。release.pyのGUI検収承認時にはこれがbaselineへ昇格コピーされる)

## リリース手順全体の中での位置づけ(推奨フロー)

```
毎変更のたびに:
    層1 + 層2  (relgate.py --layers 12、数分)
        ↓ PASS
リリース前に1回:
    ship_smoke.py --minutes 20   (権利監査・文書整合・アプリ健全性等)
        ↓ PASS
    層0                          (relgate.py --layers 0、決定性の最終確認)
        ↓ PASS
    夜間実機チェック              (tests\coverage\run_overnight.ps1 -Machine、
                                   または palworld-play-start-check)
        ↓ PASS
    検収(人間が実機のスクリーンショットを見る)
        ↓
    リリース
```

層1/2は「壊れていないか」を速く広く見張る網、層0は「今のビルドは
再現可能か」の最終確認、ship_smoke/実機チェックは「配布物として成立するか」
の最終関門、という役割分担。どれか1つだけでは足りない
(数値ゲートが全部通っても実物は壊れていた、という事故がこのプロジェクトで
繰り返し起きているため——CLAUDE.md「検証の作法」参照)。

## 中間ハッシュスキップ(WP-C、dev issue #27、2026-07-28)

3検体フル変換(並列で約6分)のうち、入力形式差が効くのはPhase 0-1
(バニラ準備+Blender工程)まで、正規化後のnoue工程(Phase 2-6、全体の9割超)は
共通、という構造を利用した高速化。checkモードで自動的に働く。

### 仕組み

1. 検体ごとにPhase 0-1だけを本番と同一経路で実行する(convert.ps1を無改変のまま、
   環境変数 `D2P_STOP_BEFORE_NOUE=1` で `pipeline\py\convert_noue.py` がnoue工程の
   入口で即0終了する)
2. 「正規化後中間生成物」のダイジェストを計算する(`tests\relgate\intermediate_hash.py`。
   .blendはバイト非決定なので、noueが実際に消費する形=`dump_avatar_mesh.py` を
   WP-B3の決定化条件 `-t 1` で適用したJSONをハッシュする。ほかにavatar_meta.json /
   chibi_bone_world_head_*.json / textures(PNGクリティカルチャンクのみ)/
   job設定(paths除く))
3. 前回リリースの記録 `devtools\relgate_skip_record.json`(git管理)と比較し、
   一致した検体は noue工程を省略。pakは `work\_relgate_pak_cache\<sha256>.pak`
   (マシンローカル)から実体化+sha256再検証し、層1/2/T4は
   「PASS(SKIP継承)」として報告する(release.pyのcompute_avatar_paks /
   --pak none 判定は無改修で成立する)
4. 不一致の検体だけ、その場で `-SkipBlender` フル実行に落ちる(Phase 0-1成果を再利用)

前提条件が1つでも崩れたら必ずフル実行へ倒れる(誤スキップ側には倒れない):
記録なし/schema不一致/**下流フィンガープリント不一致**(pipeline配下+検査モジュール+
Blender実体+Palworld pakのどれかが変化。step01/step02のみ除外=その影響は中間
ダイジェストが検体ごとに捕捉する)/baselineフィンガープリント不一致/pakキャッシュ
欠如・破損/ダイジェスト計算不能。

### 記録の更新(リリース成功時のみ)

    # リリース成功直後に、そのリリースを検証したrelgate runから昇格する
    python devtools\relgate.py --promote-skip-record --work work\release_cert\run_<ts>\relgate
    git add devtools/relgate_skip_record.json   # コミットは人間の作業

昇格は次の3つの構造的証拠が揃わないと拒否される:
①3検体のpak SHA256が `.devonly\publish\releases.json` 最新エントリと全一致
(=リリースとして成立した状態)②そのrunの `downstream_fingerprint.json`
(relgateが実行開始時に必ず書く)が現在の下流コード状態と一致(=古いrunや
コード変更後の昇格による偽スキップを防ぐ)③そのrunの `results.json`
(relgateが書く機械可読の実測判定)が全層PASS(=検証官F1対応。
「実比較でFAILだったpakをPASS(SKIP継承)として報告する」構造を封鎖。
inheritは実測結果から書かれ、万一FAILが記録に入ってもスキップ継承時に
FAILのまま表面化する)。テスト時のみ
`--promote-allow-unreleased` + 既定以外の `--skip-record` で免除できる
(既定の記録パスへは書けない。テスト用記録は使用時にも警告が出る)。

### 自己試験(負の対照)

    python devtools\relgate.py --layers 12 --work work\<名前> --selftest-corrupt vrm0_kate

Phase 0-1直後に該当検体の converted\avatar_meta.json へ未知キーを注入し
(=中間生成物の意図的変更。後段はこのキーを読まないため変換結果自体は不変)、
その検体だけがハッシュ不一致→フル実行に落ちることを検証する。
`--no-skip` でスキップ機構全体を無効化できる。

### dev issue #6(視覚検査の自己参照)との関係

「検査の基準側をリリース済み基準画像(正解)との相関にする」要求は、層2
(`tests\relgate\baseline\<key>\images\` とのNCC比較、approve運用)が既にそれで
ある(preview=リターゲット起因の破損、atlascheck=アトラス起因の破損の両方を
基準画像と比較するため、`_render_atlas_visual_check` /
`tests\coverage\probes.py::gate_atlas_patch_ncc` の「前後とも同じように壊れると
検出不能」という自己参照の盲点を代表3検体について塞ぐ)。スキップ経路でも
継承元は「リリースとして成立し人間検収を通った状態」に限定され(上記昇格ゲート)、
baselineフィンガープリント一致を前提条件にすることでこの保証を維持している。
なお公開issue #5(検査の無言スキップ)は `_render_atlas_visual_check` 側で封じた
(全スキップ経路が理由コード付きWARN+##AVATAR_WARNING##+機械可読マーカーになり、
relgate経由(D2P_STRICT_VISUAL_CHECK=1)ではdie=fail-closed)。
