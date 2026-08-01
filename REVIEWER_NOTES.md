# Reviewer Notes / 審査担当者向けサマリー

*English section is below the Japanese one. This document is written primarily for
someone auditing this repository from the outside who does not have time to read
every document individually.*

## この文書について

このファイルは、他の文書(README / SECURITY.md / THIRD_PARTY_NOTICES.md / PRIVACY.md)に
散らばっている情報を1ページに要約した、外部の審査担当者向けの入口ページです。詳細な
一次情報はそれぞれのリンク先を参照してください。ここで新しい主張はしていません。

## 何のツールか(要約)

Windows デスクトップアプリ。VRChat 用のアバター(VRChat 用 prefab、Modular Avatar 対応 /
VRM 0.0 / VRM 1.0)を入力に取り、Palworld の MOD 用アセットへ変換します。ファンメイドの
非公式ツールで、Pocketpair, Inc. とは無関係です。詳細: [README.md](README.md) /
[README.en.md](README.en.md)。

## ライセンス境界(要約)

- ツール本体: **MIT License**([LICENSE](LICENSE))
- 例外は1ファイルのみ: `pipeline/py/ooz_worker_gpl.py` が **GPLv3+**。この
  ファイルは本体からは別プロセス(`subprocess`)としてのみ起動され、import も
  リンクもされません(外部実行ファイルを呼ぶのと同じ形の mere aggregation)。
  境界の詳細説明: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 配布フルセット版には、GPL の Blender Portable(無改変の公式ビルド、初回起動時に
  公式サイトから自動ダウンロード)と MIT の VRM Add-on for Blender も含まれます。
  一覧: [README.md](README.md) の「ライセンス」節

## 配布物の構成(要約)

配布物は `Uchinoko.bat`(エントリポイント)+ Python ソース + python.org 公式配布の
embeddable Python ランタイム(Tcl/Tk ランタイム込み)で構成されます。いずれのランタイムも
Python Software Foundation の Authenticode 署名を保持したまま同梱しており、**自作の
コンパイル済み実行ファイル(PE)は1つも含みません**。ビルド時に
`packaging\check_signatures.py` が自作PEの混入を機械検査するゲートとして機能します
(第三者コンポーネントのうち未署名のものは個別に許容リスト化されており、詳細は
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照)。

## ローカル完結・VRC SDK 不可侵(要約)

本ツールは**ローカル完結**で動作し、アバターデータを外部へ送信しません(問合せフォームでの
明示送信を除く。送信内容は送信前に確認・編集できます)。本ツールは VRC SDK を実行・
呼び出ししません。詳細: [SECURITY.md](SECURITY.md) の「このツールの設計上の前提」節。

## 検査体制(要約)

配布物の PE 署名は `packaging\check_signatures.py` がビルド時に機械検査します。
変換結果の無退行(pak 不変・見た目・実機)は、リリースのたびに `devtools\release.py` の
リリース関所が自動検証してから配布します。

## 検証手順

1. **ライセンス境界を確認する**: [LICENSE](LICENSE)(MIT)と
   [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を突き合わせる。
2. **配布物の構成を確認する**: `packaging\README.md` と
   `packaging\check_signatures.py` のソースを読む。
3. **送信データを確認する**: [PRIVACY.md](PRIVACY.md) / [PRIVACY.en.md](PRIVACY.en.md)。
   外部送信経路は起動時の更新確認(1回・GET)と、ユーザーが明示的にボタンを押した場合のみの
   問い合わせ送信の2つに限定されています。
4. **既知のリスクの開示を確認する**: [SECURITY.md](SECURITY.md) を通読する
   (脆弱性の報告方法、設計上の前提、ウイルス対策ソフトによる検出についての開示)。

## 主要文書へのリンク

| 文書 | 内容 |
|---|---|
| [README.md](README.md) / [README.en.md](README.en.md) | 製品概要・対応範囲・使い方 |
| [LICENSE](LICENSE) | MIT License 本文 |
| [SECURITY.md](SECURITY.md) | 脆弱性報告・設計上の前提・ウイルス対策ソフトによる検出について |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三者コンポーネントとライセンス境界 |
| [PRIVACY.md](PRIVACY.md) / [PRIVACY.en.md](PRIVACY.en.md) | 問い合わせ機能の送信内容 |
| [BUILD.md](BUILD.md) | ソースからのビルド手順 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 貢献方法・対応スコープ |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | 行動規範 |
| [CODEOWNERS](CODEOWNERS) | 変更の責任者(単独メンテナ) |

---

## English

This file is a one-page entry point for an outside reviewer auditing this
repository, summarizing information that is otherwise spread across several
documents. It does not introduce any new claims — every statement below links to
the document that is the source of truth.

### What this tool is (summary)

A Windows desktop application. It takes a VRChat avatar (a VRChat prefab with
Modular Avatar support, VRM 0.0, or VRM 1.0) as input and converts it into a
Palworld mod asset. It is an unofficial, fan-made tool with no affiliation to
Pocketpair, Inc. Details: [README.md](README.md) / [README.en.md](README.en.md).

### License boundary (summary)

- The tool itself: **MIT License** ([LICENSE](LICENSE)).
- The one exception is a single file, `pipeline/py/ooz_worker_gpl.py`, which is
  **GPLv3+**. It runs only as a separate `subprocess`, never imported or linked
  into the MIT-licensed main program (the same "mere aggregation" shape as
  shelling out to an external tool). Full boundary explanation:
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- The full distribution package also bundles GPL-licensed Blender Portable (an
  unmodified official build, downloaded automatically from the official site on
  first launch) and the MIT-licensed VRM Add-on for Blender. Full list: the
  "License" section of [README.en.md](README.en.md).

### Composition of the distributed package (summary)

The distributed package consists of `Uchinoko.bat` (the entry point), Python
source, and the official python.org embeddable Python runtime (including the
Tcl/Tk runtime). Both runtimes are bundled with their original Python Software
Foundation Authenticode signature intact, and **the package contains zero
self-compiled executable (PE) files**. `packaging\check_signatures.py` gates
every build against any self-made PE creeping in (a small number of unsigned
third-party components are individually allow-listed; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details).

### Local-only operation, no VRC SDK (summary)

This tool runs **entirely locally** and never sends your avatar data anywhere
else (except when you explicitly submit the in-app contact form, whose content
you can review and edit before sending). This tool does not execute or invoke
the VRC SDK. Details: the "Design assumptions of this tool" section of
[SECURITY.md](SECURITY.md).

### Verification regime (summary)

`packaging\check_signatures.py` machine-checks the PE signatures of the
distributed package at build time. Conversion output non-regression (unchanged
pak, appearance, and in-game behavior) is automatically verified by the
`devtools\release.py` release gate before every release is shipped.

### A verification path for reviewers

1. **Check the license boundary**: cross-reference [LICENSE](LICENSE) (MIT)
   against [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
2. **Check the composition of the distributed package**: read
   `packaging\README.md` and the source of `packaging\check_signatures.py`.
3. **Check what data is transmitted**: [PRIVACY.md](PRIVACY.md) /
   [PRIVACY.en.md](PRIVACY.en.md). There are exactly two outbound network
   paths: a single background update-check GET request at startup, and a
   diagnostic report sent only after the user explicitly clicks through the
   in-app contact form.
4. **Check known-risk disclosure**: read [SECURITY.md](SECURITY.md) in full
   (vulnerability reporting, design assumptions, and the disclosure on
   antivirus software detection).

### Key documents

| Document | Contents |
|---|---|
| [README.md](README.md) / [README.en.md](README.en.md) | Product overview, supported scope, usage |
| [LICENSE](LICENSE) | Full text of the MIT License |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting, design assumptions, disclosure on antivirus detection |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Third-party components and the license boundary |
| [PRIVACY.md](PRIVACY.md) / [PRIVACY.en.md](PRIVACY.en.md) | What the in-app contact form transmits |
| [BUILD.md](BUILD.md) | How to build from source |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute, supported scope |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Code of conduct |
| [CODEOWNERS](CODEOWNERS) | Who is responsible for changes (single maintainer) |
