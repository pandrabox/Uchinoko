# Uchinoko for Palworld

*[English](README.en.md)*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/pandrabox/Uchinoko)](https://github.com/pandrabox/Uchinoko/releases)
[![Build](https://github.com/pandrabox/Uchinoko/actions/workflows/build.yml/badge.svg)](https://github.com/pandrabox/Uchinoko/actions/workflows/build.yml)

**自分のアバターでパルワールドをやりたいVRChatterのためのツール**
(旧名: DiveToPalworld。v2.0.0で改名しました)
prefabやVRMファイルを入れるだけで、パルワールドのプレイヤーモデルを自分のアバターに差し替えます。
いつものアバターで、パルワードの世界を駆け巡ろう!

## 特徴
- 簡単:`Uchinoko.bat`を起動→ファイルを入れる→変換
- ローカル完結:アバターデータの外部送信一切なし
- Modular Avatar対応:いつも使っているアバターがそのまま使える
- 戻せる:ボタン1つで元の状態に戻せる
- 準備不要:必要なのはPalworldとVRCの環境だけ

## ダウンロード

最新版は [GitHub Releases](https://github.com/pandrabox/Uchinoko/releases) から入手できます。
[BOOTH](https://osaki-vrc.booth.pm/items/8662197) からのダウンロードも可能です(投げ銭制)。

## 動作環境
- Windows 11
- Palworld 1.0.1(Steam版) — Xbox / Game Pass版は非対応
- Unity2022.3.22f1(VRMの場合は不要)
- GPUがあること
- インターネット接続(初回起動時にBlender約350MBを自動ダウンロードします)

## 使い方
- `Uchinoko.bat` をダブルクリックして起動します
- マニュアルはオンラインでご覧いただけます: https://dl.osakishokai.com/manual
- 初回起動時、Windowsがダウンロードしたファイルに対する確認画面を表示することがあります。詳しくは下記「起動時の確認画面について」をご覧ください。

## 対応範囲
- 入力:VRChat用prefab(Modular Avatar対応) / VRM 0.0 / VRM 1.0
- Modular Avatar以外のNDMFプラグインは非対応(変換時に意図的に除去されます)
- Humanoidボーンのみ対応 その他は直近Humanoidボーンに移管されます
- 影の強さ調整(ゲーム内のみ、プレビューは変わりません)

## 対応していない機能
- 揺れもの
- マルチプレイ
- 両面シェーダー
- コラボ装備の上書き
- Unity2019
- 他のpak MODとの併用(他のpak MODを検出した場合は警告が表示されます)

## コラボ装備について
- パルワールドでコラボ装備を装備しているとき、本ツールによる上書きは実行されません

| コラボ | 非対応の装備 |
|---|---|
| テラリア | ホーリープレート / ホーリーマスク / ホーリーヘッドギア / ホーリーヘルム / ホーリーフード / ムーンロードのおめん / クトゥルフのめだまマスク |
| ULTRAKILL | V1アーマー / V2アーマー |

**回避方法**: テクノロジーLv24(古代)の「**アンティークなドレッサー**」を利用して、
これらの服以外の見た目にしてご利用ください。


## 起動時の確認画面について

本ツールの初回起動時、Windowsが「発行元を確認できませんでした」等の確認画面を表示することがあります。**これは危険という意味ではありません。**

- **なぜ出るか**: `Uchinoko.bat` はダウンロードした zip から実行するファイルであり、Windows はインターネット経由で入手したファイルに対して確認を求めることがあります。本ツールが同梱する実行ファイルは python.org 公式配布の Python ランタイムのみで、本ツール自身が作成した実行ファイル(exe/dll等)は含みません。
- **起動方法**: 確認画面が出た場合は、表示内容をご確認のうえ実行してください。
- **ご自身で確かめる方法**: ソースコードは[公開リポジトリ](https://github.com/pandrabox/Uchinoko)で確認できます。
- 解決しない場合・不安な場合は、下記「お問い合わせ」からご連絡ください。


## ウイルス対策ソフトによる検出について

過去のバージョン(〜v2.2.x)には、複数のウイルス対策製品に検出されるものがありました。個々の検出の当否について当方から断定はしません。v2.3.0以降は配布物の構成を変更し、自作のコンパイル済み実行ファイル(PE)を一切含みません。詳しくは [SECURITY.md](SECURITY.md) の「ウイルス対策ソフトによる検出について」をご覧ください。

セキュリティソフトの設定変更(除外の追加など)については、本ツールとしてご案内はしていません。解決しない場合は、下記「お問い合わせ」からご連絡ください。


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

| コンポーネント | ライセンス | 同梱形態・入手元 |
|---|---|---|
| Blender 4.3.2 Portable(無改変の公式ビルド) | GPL | 配布物には含まれません。初回起動時に公式サイト [blender.org](https://www.blender.org/download/) から自動的にダウンロードし、`res\assets\tools\` に配置します |
| VRM Add-on for Blender 4.4.0 | MIT | `res\assets\third_party\` に同梱。出所: [VRM-Addon-for-Blender](https://github.com/saturday06/VRM-Addon-for-Blender) |
| pyooz 0.0.8(`ooz.pyd` 等) | GPLv3+ | Palworldのpakが採用するOodle互換圧縮(ooz)の解凍に使用。差し込み素材のみ `res\assets\blender_patch\` に同梱し、初回起動時にダウンロードしたBlenderのPython環境へ配置されます。出所: [PyPI](https://pypi.org/project/pyooz/) / [GitHub](https://github.com/zao/pyooz) |
| Python(embeddable版、無改変の公式ビルド) | PSF License | `res\python_embed\` に同梱。出所: [python.org](https://www.python.org/) |
| Tcl/Tkランタイム | Tcl/Tk License | `res\python_embed\` に同梱(python.org公式フルインストーラから抽出) |

`pipeline\py\ooz_worker_gpl.py` のみ GPLv3+ です。pyoozのソースは `third_party\pyooz-0.0.8-source\` に同梱しています。

第三者コンポーネントの詳細な一覧・出所・ライセンス境界の説明は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。


## ソースからビルドする場合の前提

配布物(`Uchinoko.bat` + `res\`)は `python app_py\build.py` でビルドしています。
このリポジトリの clone だけでは揃わない前提物が1つあります(ライセンス上リポジトリに同梱できないため、各自入手が必要です)。

| 前提物 | 入手元 | 配置方法 |
|---|---|---|
| pyooz 0.0.8(`ooz.pyd`) | `pip install pyooz`、またはソースを同梱している `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` からビルド | Python環境のユーザーsite-packages(`pip install`の既定出力先)に入っていれば自動検出されます |

`python app_py\build.py` を実行すると、`packaging\dist\Uchinoko\` 配下に `Uchinoko.bat` / `README.txt` / `res\` の配布用フォルダ一式が生成されます(Python本体は python.org 公式配布の embeddable 版を自動取得して同梱。Blenderポータブル本体はこの時点では同梱されず、利用者の初回起動時に自動取得されます)。

配布用zip(BOOTH配布フルセット版)を作る場合は、上記に加えて `pwsh -File build\make_dist.ps1` を実行してください(内部で `python app_py\build.py` を呼び出したうえでzip化します)。前提物が揃っていない状態で実行すると、何が足りないか・どこから入手すべきかを明示してビルドを中断します(黙って失敗する設計にはしていません)。揃った状態で実行すると、`dist\Uchinoko_vX.Y.Z_full.zip` が生成されます。

より詳しいビルド手順は [`packaging\README.md`](packaging/README.md) を参照してください。


## 開発への参加

貢献方法は [CONTRIBUTING.md](CONTRIBUTING.md)、脆弱性の報告方法は [SECURITY.md](SECURITY.md)、
参加者に守っていただきたい行動規範は [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) をご覧ください。
このリポジトリを外部から監査・審査される方向けに、主要文書へのリンクを1ページへ
まとめた [REVIEWER_NOTES.md](REVIEWER_NOTES.md) も用意しています。
