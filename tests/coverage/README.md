# tests\coverage — カバレッジ検査スイート(U53)

**「アバターを11体並べる」のは1つの軸を11回なぞっているだけ**という指摘を受けて、
**入力形式 × 機能 × 人間の操作**の格子へ組み直した pytest スイート。

`tests\shipcheck`(U23/U32)は**置き換えない**。あちらのゲート判定
(`gates.py`: A 変換 / B pak存在 / C preflight 9/9 / D UE非依存の来歴 /
E クラッシュ / F プレイ開始)は **import してそのまま再利用**している。
本スイートが足すのは **軸**と、**「そのゲートが本当に効いているか」の担保**。

---

## 1コマンドで無人起動する

```powershell
pwsh -NoProfile -File tests\coverage\run_overnight.ps1
```

* 実変換を行う(`--allow-convert`)。**Palworld には一切触らない**
* 途中で人の操作を求めない。1件 FAIL しても最後まで回る
* 結果は `work\u53_cov\reports\<timestamp>\` に残る

| ファイル | 中身 |
|---|---|
| `progress.log` | 1件ごとの進行。**実行中でも読める**(1行ごとに fsync) |
| `report.md` | 判定一覧(FAIL → SKIP → PASS 順) |
| `coverage.md` | カバー状況の表 + 検体の棚卸し |
| `gates.jsonl` | ゲート判定の全 detail(report.md で切り詰めた分の全文) |
| `tests.jsonl` | pytest のテスト単位の結果(FAIL の traceback つき) |
| `provenance.json` | git HEAD / テンプレート版 / 起動引数 |
| `pytest_stdout.log` | pytest の生出力 |

実行中に別ウィンドウで追うなら:

```powershell
Get-Content -Wait work\u53_cov\reports\<timestamp>\progress.log
```

### 他のモード

```powershell
# 負の対照(モック自己検証)だけ。実変換も実機接触もしない。数十秒
pwsh -NoProfile -File tests\coverage\run_overnight.ps1 -SelfTestOnly

# 配線確認だけ(検体2体)
pwsh -NoProfile -File tests\coverage\run_overnight.ps1 -Specimens fast

# 実機ゲートまで回す(Palworld を起動してよいときだけ)
pwsh -NoProfile -File tests\coverage\run_overnight.ps1 -Machine
```

素の pytest で叩く場合(既定は**何も起こさない**):

```powershell
python -m pytest tests\coverage                      # 静的検査だけ。変換も実機も無し
python -m pytest tests\coverage --allow-convert      # 実変換あり
python -m pytest tests\coverage --allow-convert --allow-unity   # prefab 4体も通す
python -m pytest tests\coverage -m machine --allow-machine --allow-convert
```

---

## 安全設計

| 弁 | 既定 | 効果 |
|---|---|---|
| `--allow-convert` | OFF | 指定しない限り `convert.ps1` を一切呼ばない(該当ケースは SKIP) |
| `--allow-machine` | OFF | 指定しない限り Palworld に触らない |
| `--allow-unity` | OFF | 指定しない限り Unity をヘッドレス起動しない。**他人の Unity プロジェクトへ書き込みが起きる**ため(下記) |
| `pytest.ini` の `-m "not machine"` | 常時 | 実機ゲートは**マーカーの時点で収集されない**(二重の弁) |

### `--allow-unity` を付ける前に

`.prefab` 検体は `C:\UnityP\` にある**ぱんの作業中プロジェクト**を参照する。
輸出のたびに `pipeline\cli\export_from_unity.ps1` が次を行う:

* `<project>\Assets\Editor\DiveToPalworldExporter.cs` を複製(冪等)
* FBX Exporter 未導入なら `<project>\Packages\manifest.json` へ `com.unity.formats.fbx` を追記
  (実測: 4体とも未導入 → **初回は4プロジェクトすべての manifest が書き換わる**)

さらに **Unity でそのプロジェクトを開いていると起動できない**(Unity の二重起動禁止)。
開いていた場合は `gate_unity_export` が FAIL ではなく **SKIP**(環境都合)として切り分ける。

出力先は必ず `-Out` を明示して `work\u53_cov\exports\<case>\` へ出す。
既定(`work\<prefab名>_export`)に任せてはならない — 下の「同名衝突」を参照。

`Global\DiveToPalworld_pipeline` mutex は待たずに即エラーで返るので、
`probes.run_convert` が **90秒間隔で最大40回(≒1時間)リトライ**する。
1本の変換は **60分でタイムアウト**する(必ず朝までに終わる)。

作業域は `work\u53_cov\` 配下だけ(`devtools\new_experiment.ps1 -Name u53_cov` で作成)。
ケースごとに `work\u53_cov\cases\<case>\` を分けるので、既存の `work\` は一切触らない。

---

## カバー状況の表

正本は `matrix.AXES`(機械可読)。実行ごとに `coverage.md` へ最新版が出る。

| 軸 | カバー | どこで | 備考 |
|---|---|---|---|
| **入力形式: VRM** | ✔ | `test_inputs.py::test_input_format` | VRM 0.x 6体 + VRM 1.0 1体 |
| **入力形式: FBX + humanoid.json** | ✔ | 同上 | **flatVer2 の1体だけ**(手元にある唯一の FBX) |
| **入力形式: prefab** | ✔ `--allow-unity` 時 | `test_prefab.py` | **検体4体**(2026-07-26 責任者提供、`C:\UnityP\` 配下)。静的検査(実在・Unity プロジェクトの解決・NDMF 導入・配線・同名衝突)は常時。端から端まで(Unity 輸出→変換→pak)は `--allow-unity` 時のみ |
| **MA(Modular Avatar)対応** | ✔ `--allow-unity` 時 | `test_prefab.py::test_prefab_end_to_end` | ベイクが**実際に走ったこと**を `unity_export.log` の `D2P: NDMFベイク完了` で判定する。`BakeNdmf` は NDMF が無いと**例外を投げず素通りする**ので、成果物の存在では証拠にならない(DEV_NOTES(29)§4 の構図) |
| **入力形式: prefab(同名衝突)** | ✔ | `test_prefab.py::test_prefab_name_collision` | Agyo / Jinbe の `flatVer2.prefab`(1.5MB と 190KB の別物)。**既定の出力先は prefab のファイル名だけで決まる**ので衝突する。詳細は下記 |
| **UE非依存** | ✔ | (N/A: dev#114でUEパイプライン自体を削除) | 2026-07-29 dev#114でconvert.ps1のUEクック分岐・`pipeline\ue\`・UE系GUI導線を完全削除。UEを選ぶ経路が無いため構造的に保証(旧 `test_ue_independence.py` は検査対象消滅につき削除) |
| **影の調整: 値が出力に届く** | ✔ | `test_settings.py::test_setting_flip` | `shadow_lift` 0→0.7 / 0→1.0 / `unlit` |
| **影の調整: 影のみ更新経路** | ✔ | `test_materials_only_equivalence` | `convert.ps1 -MaterialsOnly`(= `fast_repack.py`)の出力が**フル変換と同一の MI バイト**になること + preflight |
| **削除ボーン** | ✔ | `test_setting_flip[drop_bones_one]` | 旧 shipcheck に検査ケースが無かった。ボーン名は baseline の `avatar_meta.json` から自動選定 |
| **テクスチャ枚数(アトラス行数)** | ✔ | `test_input_format` + `test_atlas_rows_coverage` | rows=1/2/3/4/6 を踏む検体を選定。**軸を本当に振れたか自体を検査する** |
| **コラボ装備の除外** | ✔ | `test_exclusions_untouched` ほか | 除外SK**固有の** MI が設定フリップで1バイトも動かないこと |
| **両面表示 / 指を固定 / 肩の開き** | ✔ | `test_setting_flip` | `force_two_sided` は**既定と違う側(False)**へ倒す(旧スイートは既定値と同値だった) |
| **実機: クラッシュ / プレイ開始 / 見た目** | △ 既定除外 | `test_machine_coverage.py` | `-m machine --allow-machine` を明示したときだけ。2026-07-26: `test_machine_visual_vrm_fbx` / `test_machine_visual_prefab` を追加し、`machine_base` 1検体だけでなく **SPECIMENS/PREFAB_SPECIMENS の全検体**を実機に立たせて `run_dir\shots\` へ正面SSを集約するようにした(判定はクラッシュ/UI失敗/成功の3値のみ。見た目そのものの合否は引き続き人間が画像を見て判断する。1検体あたり概ね60〜150秒、全件で概ね+10〜25分) |

### カバーされていないもの(正直に)

| 項目 | 理由 |
|---|---|
| `.prefab` / MA ベイクの**既定実行** | 検体は揃ったが、Unity 起動は他人のプロジェクトを書き換えるので `--allow-unity` を明示したときだけ。素の一晩実行には**入っていない** |
| `.unitypackage` を直接入力にする経路 | GUI のフィルタは `.vrm/.fbx/.prefab` のみ。`test\cc0avatar\Shapell_v1_0_3.zip` の `.unitypackage` を使うには人が Unity へ取り込む段が要る |
| **設定フリップの入力形式** | すべて `FLIP_BASE`(= FBX の flatVer2)の上でしか行っていない。VRM 入力で設定が同じように効くかは未検査 |
| 見た目の正しさ | 差分の**有無と宛先**しか見ていない。「その差分が正しい絵になるか」は実機ゲート G(advisory)と人の目 |
| `shadow_lift` の単調性(0.35 < 0.7 < 1.0 で陰影が単調に減る) | pak のバイト差分では測れない。実機の撮影が要る(`work\u50_unify\SHADOW_REPORT.md` 相当) |
| 配布 zip を被検体にした検査 | `tests\shipcheck` の `--target-root` 相当は未移植 |

---

## prefab 検体と、そこで見つかった同名衝突(2026-07-26)

検体4体(いずれも Unity 2022.3.22f1、MA + NDMF 導入済みを実測確認):

| 検体キー | prefab | 意図 |
|---|---|---|
| `prefab_flats_apron` | `C:\UnityP\apron\Assets\Pan\Flats.prefab` | GUI 統合時に一度だけ手で通した個体。「バインド行列が不一致(ポーズ済みrig?)」警告が出る検体でもある |
| `prefab_shata` | `C:\UnityP\PanShata\Assets\sha-ta.prefab` | らすちんワークス系以外の実運用アバター。FaceEmo が同居し、MA 以外の NDMF プラグインがある構成 |
| `prefab_flatver2_agyo` | `C:\UnityP\Agyo\Assets\flatVer2.prefab` | 同名衝突 1/2(1,508,902 bytes) |
| `prefab_flatver2_jinbe` | `C:\UnityP\Jinbe\Assets\flatVer2.prefab` | 同名衝突 2/2(189,554 bytes) |

### 同名衝突: 出力先は prefab の**ファイル名だけ**で決まる

```
export_from_unity.ps1:79-80   $name = GetFileNameWithoutExtension($Prefab)
                              $Out  = work\${name}_export
app\DiveToPalworld.cs:982     同じ規則で GUI も組み立てる
```

したがって Agyo 版と Jinbe 版(**中身は別物、サイズが8倍違う**)は
どちらも `work\flatVer2_export` へ出る。後から輸出したほうが前を上書きする。

**さらに悪いことに、その衝突先は既存検体 `fbx_flat_ma` の実体そのもの**
(`matrix.FLAT_EXPORT_DIR`)。既定に任せると**検査が検体を壊す**。

本スイートの扱い:

* `test_prefab_name_collision` … 合否は「**本スイートが既定を使っていないこと**」。
  衝突しないことは要求しない(実装がそうなっていないため)
* `test_prefab_collision_is_declared` … 衝突の実在を毎回 SKIP 行として申告する
  (直れば PASS へ変わる)
* `test_same_name_prefabs_produce_different_paks` … 2体の pak の SHA1 が
  **別であること**を実測する(どこかがファイル名を鍵に共有していれば一致する)

未修正の欠陥であり、**GUI 側にも同じ規則がある**(= エンドユーザーも踏む)。

### 負の検体(`vrm_no_texture`)

`EmissionMigration_v0.107.0.vrm` は VRM アドオンの機能テスト用フィクスチャで、
**メッシュが1つも無い**。U33 で 2件とも
`[step01][FATAL] アバターのメッシュが1つも無い` で落ちることが実測済み。

DEV_NOTES(29)§5「壊れているVRMも資産。ただし正常系と混ぜず、**『優雅に失敗する
こと』を期待値にする**」に従い、この検体だけ判定を反転してある
(`matrix.SPECIMENS[...]["expected_failure"]`):
**期待どおりの理由で止まれば PASS。exit 0 で通っても、別の理由で落ちても FAIL。**

---

## なぜ「差分の宛先」を人が書かないのか(このスイートの中心)

`tests\shipcheck\cases.py::SETTINGS_FLIPS` は、設定フリップの差分が
`ModelMaterials/MainShader/` に出ることを**人が文字列で書いて**いた。実測すると:

```
Player/ModelMaterials/MainShader/   … pak 内 16 ファイルだけ(M_VP_* 12 + t00/t01 4)
    そのうち M_VP_* は どの SK からも参照されていない = 死んだ経路
実際に描画に使われる統一MI               … 79 パッケージ = 158 ファイル
```

つまり **描画に使われる 158 ファイルが全部壊れてもゲートは通る**状態だった
(DEV_NOTES 2026-07-25(28) §5)。

本スイートは期待パスを書かない。**pak を開いて「衣装SKの `Materials[]` が
実際に指している MI」を全件解決し**(`live_template.find_outfit_material_paths_all`
= パイプライン本体の関数をそのまま使う)、そこへ差分が届いたかを見る
(`probes.live_reference_sets` / `probes.gate_live_diff`)。

* 差分ゼロ → FAIL(設定が配線されていない)
* 差分が死んだ経路だけ → FAIL(`dead_only=True`。**今日の事故はここで落ちる**)
* 期待した種類(material / mesh)に届いていない → FAIL

### もう1つ見つかった古いゲート: shipcheck の gate C

`tests\shipcheck\gates.py::gate_c_preflight_from_log` は
**preflight のゲート数がちょうど 9 件**であることを合格条件にしている
(`ok = total == 9 and not fails`)。ところが 2026-07-25 のコミット `7ac3d7b` で
preflight に G10/G11 が足され、G5b と合わせて **実測 12 件**出るようになった。

つまりあのゲートは **健全なビルドを必ず FAIL と判定する**
(2026-07-26 実測: 12 PASS / 0 FAIL のログに対して gate C は FAIL)。
本スイートは件数を固定しない `probes.gate_preflight` を使う:

* `[FAIL] G*` が 0 件
* `[WARN] G*` が 0 件(G10/G11 は `soft_gate` なので NG は WARN で出る。
  「ソフト」はパイプライン側の都合であって、出荷検査で見逃してよい理由ではない)
* 最低ライン G1〜G9 が全部揃っている(preflight が途中で死んでいない)

この件は `selftest::test_shipcheck_gate_c_is_stale` が実証つきで記録している。

---

## 負の対照(わざと壊したら落ちるか)

```powershell
python -m pytest tests\coverage\selftest -q
```

`selftest\test_negative_controls.py` が、各ゲートについて
**正の対照(PASS するはずの入力)と負の対照(FAIL するはずの入力)を対で**流す。
実変換も実機も要らない。末尾の2件だけは既存 pak があれば実データで検証する
(`M_VP_*` が本当に dead 側へ分類されるか = 旧期待パスが死んでいたことの裏付け)。

---

## このスイート自身の検証状況(2026-07-26 時点)

**実行して確かめた**:

| 内容 | 結果 |
|---|---|
| 負の対照 28件(モック + 実 pak) | **28 passed** |
| 静的検査だけの実行(変換なし) | **exitstatus=0**。SKIP は全部「`--allow-convert` が要る」 |
| `run_overnight.ps1 -SelfTestOnly` | 起動〜レポート生成まで通る |
| フル変換 2本(k=0.0 / k=0.7、flatVer2) | 両方 exit 0、preflight 12/12 PASS |
| **`live_diff_shadow_lift_0to07`**(本スイートの核) | **PASS。差分 160件のうち 158件が「生きた MI」= 全件命中**、死んだ `M_VP_*` は 2件だけ |
| `exclusions_untouched` | **PASS**。除外SK固有の MI 6パッケージは pak に1件も入っていない |
| `probes.gate_preflight` | 実測 12件のログで PASS(旧 gate C は同じログを FAIL にする) |

**まだ実行していない(未検証)**:

* `run_overnight.ps1` の**通し実行**(責任者の指示で変換の実行を停止したため)。
  コードとしては完結しているが、全ケースを最後まで流した実績は無い
* `test_input_format` の VRM 7体(`vrm_alicia051` は DEV_NOTES(28)§1 の出荷ブロッカーを一時踏んでいたが、
  dev#18(uvfix18)・dev#129で解消済み。2026-07-30実測で PASS を確認済み。matrix.py 参照)
* `test_atlas_rows_coverage`(rows を実際に振れたかの検査)
* `test_materials_only_equivalence`(影のみ更新)
* `test_setting_flip` の残り 6件(`shadow_lift_0to10` / `unlit` / `force_two_sided` / `drop_bones` / `merge_fingers` / `shoulder_offset`)
* 実機ゲート E/F(既定で除外)
* **prefab 4体の端から端まで**(2026-07-26 追加)。静的検査は 12/12 PASS を実測済みだが、
  `--allow-unity` を付けた Unity ヘッドレス輸出は**一度も走らせていない**。
  未知数: 初回インポートの所要、FBX Exporter 追記の影響、
  `sha-ta`(FaceEmo 同居)のベイクが通るか

## 構成

```
tests\coverage\
  matrix.py        検体表・設定フリップ表・カバレッジ軸(機械が読むテーブル)
  probes.py        新ゲートの判定ロジック(pytest 非依存の純関数)
  conftest.py      オプション・job.json 生成・ビルド・逐次記録
  cov_report.py    report.md / coverage.md の生成
  pytest.ini       既定で -m "not machine"(実機ゲートを収集しない)
  test_inputs.py           入力形式軸(VRM/FBX)・テクスチャ枚数軸・検体宣言の整合
  test_prefab.py           入力形式 prefab・MA ベイクの実行・同名衝突(--allow-unity)
  test_settings.py         設定フリップ・影のみ更新・コラボ除外
  test_machine_coverage.py 実機(既定除外)
  selftest\test_negative_controls.py   負の対照
  run_overnight.ps1        1コマンド無人起動
```

## 落ちたときの入口

1. `report.md` の FAIL 行を見る(軸 / ケース / ゲート / detail)
2. 詳細が切れていたら `gates.jsonl` の同じ `gate` 行を全文で読む
3. 変換そのものが落ちているなら `work\u53_cov\convert_logs\` と
   `work\u53_cov\cases\<case>\build\logs\`
4. スイート自身を疑うときは先に `-SelfTestOnly` を回す
   (通るならスイートは健全 → 被検体側の問題)
