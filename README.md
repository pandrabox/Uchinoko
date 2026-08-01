# Uchinoko for Palworld

*[English](README.en.md)*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/pandrabox/Uchinoko)](https://github.com/pandrabox/Uchinoko/releases)
[![Build](https://github.com/pandrabox/Uchinoko/actions/workflows/build.yml/badge.svg)](https://github.com/pandrabox/Uchinoko/actions/workflows/build.yml)

**自分のアバターでパルワールドをやりたいVRChatterのためのツール**
(旧名: DiveToPalworld。v2.0.0で改名しました)
prefabやVRMファイルを入れるだけで、パルワールドのプレイヤーモデルを自分のアバターに差し替えます。
いつものアバターで、パルワードの世界を駆け巡ろう！


## 特徴
- 簡単：exe起動→ファイルを入れる→変換
- ローカル完結：アバターデータの外部送信一切なし
- Modular Avatar対応：いつも使っているアバターがそのまま使える
- 戻せる：ボタン1つで元の状態に戻せる
- 準備不要：必要なのはPalworldとVRCの環境だけ

## ダウンロード

最新版は [GitHub Releases](https://github.com/pandrabox/Uchinoko/releases) から入手できます。
[BOOTH](https://osaki-vrc.booth.pm/items/8662197) からのダウンロードも可能です(投げ銭制)。

Windows実行ファイルは、[SignPath Foundation](https://signpath.org/) が提供する証明書によるコード署名の適用を準備しています(2026-07現在、申請の準備段階であり、**まだ申請していません**)。
<!-- TODO: 申請したら「申請中(審査待ち)」に、承認されたら適用済みである旨に更新する -->
申請・承認が完了し次第、以降のリリースに適用します。適用後は下記「困ったとき」に記載のSmartScreen警告は表示されなくなる見込みです。

## 動作環境
- Windows 11
- Palworld 1.0.1(Steam版) — Xbox / Game Pass版は非対応
- Unity2022.3.22f1(VRMの場合は不要)
- GPUがあること
- インターネット接続(初回起動時にBlender約350MBを自動ダウンロードします。詳細は同梱のMANUALをご覧ください)

## 使い方
- 同梱のMANUALをご覧ください
- 初回起動時に「WindowsによってPCが保護されました」というSmartScreenの警告が表示されることがあります。詳しくは下記「SmartScreen警告について」をご覧ください。

## 対応範囲
- 入力：Humanoid AvatarのPrefab 又は VRM 0.0 / 1.0
- Modular Avatar対応 Modular Avatar以外のNDMFプラグインは非対応（変換時に意図的に除去されます）
- Humanoidボーンのみ対応　その他は直近Humanoidボーンに移管されます
- 影の強さ調整（ゲーム内のみ、プレビューかわりません）

## 未対応範囲（将来対応するかもしれません）
- 揺れもの

## 非対応範囲（将来にわたって対応しません）
- マルチプレイ
- 両面シェーダー
- コラボ装備の上書き
- Unity2019
- 他のpak MODとの併用（他のpak MODを検出した場合は警告が表示されます）

## コラボ装備について
- パルワールドでコラボ装備を装備しているとき、本ツールによる上書きは実行されません

| コラボ | 非対応の装備 |
|---|---|
| テラリア | ホーリープレート / ホーリーマスク / ホーリーヘッドギア / ホーリーヘルム / ホーリーフード / ムーンロードのおめん / クトゥルフのめだまマスク |
| ULTRAKILL | V1アーマー / V2アーマー |

**回避方法**: テクノロジーLv24(古代)の「**アンティークなドレッサー**」を利用して、
これらの服以外の見た目にしてご利用ください。


## SmartScreen警告について

本ツールの初回起動時、Windowsが「WindowsによってPCが保護されました(不明な発行者)」という
SmartScreenの警告を表示することがあります。**これは危険という意味ではありません。**

- **なぜ出るか**: 本ツールは個人開発でコード署名の無い実行ファイルです。SmartScreenは
  ファイルの評価実績(レピュテーション)を見ており、①署名が無く配布数もまだ十分ではないため
  レピュテーションが蓄積されていない、②ビルドのたびに実行ファイルの中身が変わるため
  毎回「初めて見るファイル」として扱われる、という2つの理由で警告が出やすくなっています。
- **起動方法**: 警告が出た場合は「詳細情報」→「実行」をクリックすると起動できます。
- **ご自身で確かめる方法**: 本ツールはすべて公開のGitHub Actionsワークフローでビルドしており、
  誰でもビルドの手順・ログを確認できます([Actions](https://github.com/pandrabox/Uchinoko/actions))。
  ソースコードも全て公開しています([リポジトリ](https://github.com/pandrabox/Uchinoko))。
- **署名取得後の見込み**: [SignPath Foundation](https://signpath.org/) によるコード署名の
  承認が下り次第、実行ファイルのプロパティに検証可能な発行元名(SignPath Foundation)が
  表示されるようになる見込みです。**現時点では署名は未取得**です(詳しくは下記
  「コード署名について」)。
  <!-- TODO: 署名取得後に、発行者名の確認手順(プロパティ→デジタル署名タブでの確認方法)へ更新する -->
- 解決しない場合・不安な場合は、下記「お問い合わせ」からご連絡ください。


## 困ったとき: Windows Defender等に「重大な脅威」としてブロックされる場合

本ツールは個人開発のため未署名の実行ファイルであり、セキュリティソフトの汎用的な誤検知(ヒューリスティック/機械学習判定)により「重大な脅威」として検出・ブロックされることがあります(不明な発行元の警告とは別の症状です)。実際にマルウェアが含まれているわけではありません。

- **原因は構造にあります。** 未署名の小さな実行ファイルはビルドごとに内容(バイナリ)が変わるため、セキュリティソフトからは毎回「初めて見るファイル」として評価されます。
- **現在も検出されます。** 直近の実測(2026-07-30、ランチャー廃止後の本体単体)では、VirusTotal 74エンジン中**3件**が検出しました。**ビルドによって検出されたりされなかったりします**(ブロックされた場合は、配布ページに残っている他のバージョンもお試しください)。その後さらにコードを削ったため、本日時点の正確な検出数は未測定です。
- **対照実験で、検出が本ツールのコードの挙動と無関係であることを確認しました。** 同じコンパイラでビルドした「何もしない」空のプログラムの方が多く検出されました(メタデータ付きで**12件**、素の版で**4件**、いずれも実物の3件より多い)。詳細は [SECURITY.md](SECURITY.md) の「アンチウイルス誤検知についての開示」をご覧ください。
- ご自身で確かめたい場合は、本ツールはすべて公開のGitHub Actionsワークフローでビルドしています。誰でもソースから同じ手順でビルドし、成果物を照合できます([リポジトリ](https://github.com/pandrabox/Uchinoko))。
- 恒久的な対策として、コード署名に取り組んでいます(まだ申請していません)。詳しくは下記「コード署名について」をご覧ください。
- セキュリティソフトの設定変更(除外の追加など)については、本ツールとしてご案内はしていません。解決しない場合は、下記「お問い合わせ」からご連絡ください。


## コード署名について

本ツールは現在、**[SignPath Foundation](https://signpath.org/) による無償のコード署名の申請を準備しています**(2026-07時点、申請の準備段階であり、**まだ申請・署名取得のいずれも完了していません**)。<!-- TODO: 申請したら「申請中(審査待ち)」に、署名取得後はこの節を「実行ファイルのプロパティで発行元がSignPath Foundationになっていることを確認する手順」に更新する -->

SignPath FoundationはOSSプロジェクトへ証明書を無償提供する非営利団体で、他社ゲームの独自データ形式を解析・変換する同種のツール(CryEngine Converter、ValveResourceFormat 等)にも署名実績があります。署名を取得できれば、実行ファイルに検証可能な発行元情報が付き、ビルドのたびに評価がゼロから始まる現在の状態(上記「困ったとき」参照)の改善が見込めます。

なお、アプリ内の「問合せ」ボタンから送信される診断レポートは、ユーザーが明示的にボタンを押した場合にのみ送信されます。送信される内容の詳細は [PRIVACY.md](PRIVACY.md)(プライバシーポリシー)をご覧ください。

署名リクエストの承認者(Approvers/Committers)などのガバナンス情報は、
[CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md) にまとめています。


## お問い合わせ

不具合報告・ご要望・権利に関するご指摘は、アプリの「問合せ」ボタンからお願いします。
診断ログの内容を確認・編集したうえで送信でき、送信後は専用ページで経過を確認できます。


## 本ツールの位置づけ

本ツールは**ファンメイドの非公式ツール**です。
**株式会社ポケットペアおよびPalworldの運営とは一切関係ありません。**
Palworld / パルワールド は株式会社ポケットペアの商標です。


## 免責事項
本ツールは作者の環境で安全確認したうえで配布していますが、事故の起こる可能性はゼロでないため、データのバックアップを推奨します。
- 変換元のUnityプロジェクト
- パルワールドのセーブデータ
本ツールの利用等によるあらゆる不利益について作者は責任を負いません。


## ライセンス

本ツール本体は **MITライセンス** です([LICENSE](LICENSE))。

**配布フルセット版**には、本体とは別のライセンスを持つ以下の第三者ソフトウェアを同梱しています。
下表のパスはソース・CI が生成する新しいフラット構成(ルート直下に本体一式を置く形)の
ものです。**現在配布中の最新リリース(v2.2.12)はこの変更より前のビルドで、引き続き
`_internal\` レイアウトのままです**(次回リリースから反映予定。理由・詳細は
[SECURITY.md](SECURITY.md) の「アンチウイルス誤検知についての開示」を参照)。
v2.2.12 をお使いの場合は、下表のパスをすべて `_internal\` 配下に読み替えてください。

| コンポーネント | ライセンス | 同梱形態・入手元 |
|---|---|---|
| Blender 4.3.2 Portable(無改変の公式ビルド) | GPL | 配布物には含まれません。初回起動時に公式サイト [blender.org](https://www.blender.org/download/) から自動的にダウンロードし、`assets\tools\` に配置します |
| VRM Add-on for Blender 4.4.0 | MIT | `third_party\`(配布物では `assets\third_party\`)に同梱。出所: [VRM-Addon-for-Blender](https://github.com/saturday06/VRM-Addon-for-Blender) |
| pyooz 0.0.8(`ooz.pyd` 等) | GPLv3+ | Palworldのpakが採用するOodle互換圧縮(ooz)の解凍に使用。差し込み素材のみ `assets\blender_patch\` に同梱し、初回起動時にダウンロードしたBlenderのPython環境へ配置されます。出所: [PyPI](https://pypi.org/project/pyooz/) / [GitHub](https://github.com/zao/pyooz) |

`pipeline\py\ooz_worker_gpl.py` のみ GPLv3+ です。pyoozのソースは `third_party\pyooz-0.0.8-source\` に同梱しています。

第三者コンポーネントの詳細な一覧・出所・ライセンス境界の説明は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
同梱している `pipeline\py\noue_master\` 配下の Unreal Engine 形式アセットファイルの出所については [PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md) を参照してください。


## ソースからビルドする場合の前提

配布zip(BOOTH配布フルセット版)は `pwsh -File build\make_dist.ps1` で作成しています。
Blenderポータブルはこの配布zipには同梱されず、ユーザーが初回起動時に
`pipeline\cli\ensure_blender.ps1` 経由で公式サイトから取得する方式になったため、
ビルド時にBlenderポータブルの実体を用意する必要はもうありません。
このリポジトリの clone だけでは揃わない前提物が2つあります(いずれもライセンス上リポジトリに同梱できないため、各自入手が必要です)。

| 前提物 | 入手元 | 配置方法 |
|---|---|---|
| pyooz 0.0.8(`ooz.pyd`) | `pip install pyooz`、またはソースを同梱している `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` からビルド | Python 3.13 環境のユーザーsite-packages(`pip install`の既定出力先)に入っていれば自動検出されます |
| python3.dll(Python 3.11、stable ABIリダイレクタ) | 準備不要(ビルドが自動取得するembeddable Python 3.11.9に含まれるものを使用) | 自動。別のファイルを使う場合のみ環境変数 `D2P_PYTHON311_DLL` にフルパスを設定する(どの経路でも「フォワード先=python311」検証を通らないとビルドは失敗する) |

他に .NET Framework 4.8(`csc.exe`。Windows 11に標準同梱)と PowerShell 7+(`pwsh`)が必要です。

前提物が揃っていない状態で `build\make_dist.ps1` を実行すると、何が足りないか・どこから入手すべきかを明示してビルドを中断します(黙って失敗する設計にはしていません)。

揃った状態で `pwsh -File build\make_dist.ps1` を実行すると、`dist\Uchinoko_for_Palworld_vX.Y.Z_full.zip` が生成されます。

より詳しいビルド手順(exe単体のビルド・実測記録・未検証部分の明記)は [BUILD.md](BUILD.md) を参照してください。


## 開発への参加

貢献方法は [CONTRIBUTING.md](CONTRIBUTING.md)、脆弱性の報告方法は [SECURITY.md](SECURITY.md)、
参加者に守っていただきたい行動規範は [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) をご覧ください。
このリポジトリを外部から監査・審査される方向けに、主要文書へのリンクを1ページへ
まとめた [REVIEWER_NOTES.md](REVIEWER_NOTES.md) も用意しています。

