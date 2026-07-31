# Reviewer Notes / 審査担当者向けサマリー

*English section is below the Japanese one. This document is written primarily for
someone auditing this repository from the outside (e.g. a SignPath Foundation
reviewer) who does not have time to read every document individually.*

## この文書について

このファイルは、他の文書(README / SECURITY.md / CODE_SIGNING_POLICY.md /
THIRD_PARTY_NOTICES.md / PROVENANCE_NOUE_ASSETS.md / PRIVACY.md)に散らばっている
情報を1ページに要約した、外部の審査担当者向けの入口ページです。詳細な一次情報は
それぞれのリンク先を参照してください。ここで新しい主張はしていません。

## 何のツールか(要約)

Windows デスクトップアプリ。VRChat 用のアバター(VRM 0.0 / VRM 1.0 / Unity prefab)を
入力に取り、Palworld の MOD 用アセットへ変換します。ファンメイドの非公式ツールで、
Pocketpair, Inc. とは無関係です。詳細: [README.md](README.md) / [README.en.md](README.en.md)。

## ライセンス境界(要約)

- ツール本体: **MIT License**([LICENSE](LICENSE))
- 例外は1ファイルのみ: `pipeline/py/ooz_worker_gpl.py` が **GPLv3+**。この
  ファイルは本体からは別プロセス(`subprocess`)としてのみ起動され、import も
  リンクもされません(外部実行ファイルを呼ぶのと同じ形の mere aggregation)。
  境界の詳細説明: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 配布フルセット版には、GPL の Blender Portable(無改変の公式ビルド、初回起動時に
  公式サイトから自動ダウンロード)と MIT の VRM Add-on for Blender も含まれます。
  一覧: [README.md](README.md) の「ライセンス」節

## 同梱アセットの出自(要約)

`pipeline/py/noue_master/` 配下に Unreal Engine 形式のバイナリアセット(`.uasset` /
`.uexp`、34ファイル)が含まれています。**これらは Palworld 本体のデータではなく、
すべて自作アセット**です(独自マテリアル・独自テクスチャ)。全件の import table
解析・一部ファイルのバイト単位再現・負の対照(本物の Palworld アセットを食わせると
判定が反転する)による検証結果を含む詳細な説明: [PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md)。

パルワールド本体のゲームデータ自体はリポジトリに一切同梱していません。変換時に
ユーザー自身が正規に所有・インストール済みの Palworld から、実行時にのみ読み取ります。

## この種のツールの性質について

本ツールの中核は、他社の商用ゲームが使う非公開のバイナリフォーマット(pak / Oodle
互換圧縮など)を解析・変換するリバースエンジニアリングです。これは謝罪すべき事実
ではなく、単なる技術的前提として明記します。同種の手法を用いる SignPath 署名済みの
先行事例(CryEngine Converter、ValveResourceFormat、REasy Editor 等)は
[CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md) の「参考にした前例」節に記載しています。
ゲーム開発元(Pocketpair, Inc.)は modding を公式に歓迎しており、禁止事項は
①公式オンラインサーバでの mod 使用 ②第三者権利の侵害の2点のみで、本ツールは
どちらにも該当しません。

## 誠実な開示: 抱えている弱点

- **コード署名は未取得です。** SignPath Foundation への申請段階であり、
  **まだ申請していません**(README.md / CODE_SIGNING_POLICY.md に同じ記載)。
  「申請中」「審査中」ではありません。
- **現在も検出されます。** 2026-07-30、配布物がアンチウイルスに誤検知され、
  配布3チャネル(BOOTH / itch.io / GitHub Releases)から一時取り下げる事態が
  ありました。原因の一つとみられたランチャー exe を廃止したソース構成の本体単体
  (258,048 バイト時点で計測したビルド)を VirusTotal へ提出したところ、
  74エンジン中3件が検出しました(その後さらにコードを削ったため、本日時点の
  正確な検出数は未測定です)。**対照実験では、何もしない空のプログラムの方が
  より多く検出されました**(12件・4件 vs 実物3件)。これは検出が本ツールの
  コードの挙動に起因しないことを示しています。**署名すれば検出が無くなる
  保証もありません**(ウェブ調査でも、EV 署名後に検出が続いた実例が複数
  見つかっています)。**SignPath Foundation へはまだ申請していません。**
  自ら進んでランチャー・実行時の C# コンパイル・使われていなかった
  自己更新コードを**ソースから**除去しました。**⚠ これらの除去はソース・CI
  には反映済みですが、現在配布中の最新リリース(v2.2.12)にはまだ反映されて
  おらず、v2.2.12 は引き続き旧レイアウト(ランチャー exe +
  `_internal\Uchinoko.exe` の2 exe 構成)です。**次回リリースからの反映を
  予定していますが、AV の検出状況が改善していないため急いではいません。
  詳細な数値と分析は [SECURITY.md](SECURITY.md)
  の「アンチウイルス誤検知についての開示」節を参照してください。隠さず
  先に開示する方針です。
- 単独の個人開発者(pandrabox)によるメンテナンスです。体制情報:
  [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md) の「承認者・コミッター」節、
  および [CODEOWNERS](CODEOWNERS)。

## 5分でできる検証手順

1. **ビルドの再現性を見る**: [Actions](https://github.com/pandrabox/Uchinoko/actions)
   でビルドログを確認する。すべてのリリースは公開の GitHub Actions ワークフロー
   (`.github/workflows/build.yml`)から作られており、Actions の各ステップが
   使用する外部アクションはコミット SHA 固定です。
2. **ライセンス境界を確認する**: [LICENSE](LICENSE)(MIT)と
   [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)(GPLv3+ ファイルの境界説明)を
   突き合わせる。
3. **同梱アセットの出自を確認する**: [PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md)
   の「Independent verification」節に記載の検証手順・検証結果を読む。
4. **送信データを確認する**: [PRIVACY.md](PRIVACY.md) / [PRIVACY.en.md](PRIVACY.en.md)
   と [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md) の「このプログラムが送信する
   情報について」節。外部送信経路は起動時の更新確認(1回・GET)と、ユーザーが
   明示的にボタンを押した場合のみの問い合わせ送信の2つに限定されています。
5. **既知のリスクの開示を確認する**: [SECURITY.md](SECURITY.md) を通読する
   (脆弱性の報告方法、設計上の前提、アンチウイルス誤検知についての開示)。

## 主要文書へのリンク

| 文書 | 内容 |
|---|---|
| [README.md](README.md) / [README.en.md](README.en.md) | 製品概要・対応範囲・使い方 |
| [LICENSE](LICENSE) | MIT License 本文 |
| [SECURITY.md](SECURITY.md) | 脆弱性報告・設計上の前提・AV誤検知の開示 |
| [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md) | 署名申請の現状・承認者体制・送信データ |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三者コンポーネントとライセンス境界 |
| [PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md) | 同梱バイナリアセットの出自と検証 |
| [PRIVACY.md](PRIVACY.md) / [PRIVACY.en.md](PRIVACY.en.md) | 問い合わせ機能の送信内容 |
| [BUILD.md](BUILD.md) | ソースからのビルド手順 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 貢献方法・対応スコープ |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | 行動規範 |
| [CODEOWNERS](CODEOWNERS) | 変更の責任者(単独メンテナ) |

---

## English

This file is a one-page entry point for an outside reviewer (for example, a
SignPath Foundation reviewer) auditing this repository, summarizing information
that is otherwise spread across several documents. It does not introduce any new
claims — every statement below links to the document that is the source of truth.

### What this tool is (summary)

A Windows desktop application. It takes a VRChat avatar (VRM 0.0, VRM 1.0, or a
Unity prefab) as input and converts it into a Palworld mod asset. It is an
unofficial, fan-made tool with no affiliation to Pocketpair, Inc. Details:
[README.md](README.md) / [README.en.md](README.en.md).

### License boundary (summary)

- The tool itself: **MIT License** ([LICENSE](LICENSE)).
- The one exception is a single file, `pipeline/py/ooz_worker_gpl.py`, which is
  **GPLv3+**. It runs only as a separate `subprocess`, never imported or linked
  into the MIT-licensed main program (the same "mere aggregation" shape as
  shelling out to an external tool like ffmpeg). Full boundary explanation:
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- The full distribution package also bundles GPL-licensed Blender Portable (an
  unmodified official build, downloaded automatically from the official site on
  first launch) and the MIT-licensed VRM Add-on for Blender. Full list: the
  "License" section of [README.en.md](README.en.md).

### Provenance of bundled binary assets (summary)

`pipeline/py/noue_master/` contains 34 Unreal Engine binary asset files
(`.uasset` / `.uexp`). **These are not Palworld's own game data — they are
entirely self-authored** (an original material and original textures). The
detailed verification (import-table analysis of all 34 files, byte-for-byte
regeneration for 2 of them, and a negative control that flips when fed a genuine
Palworld asset) is documented in
[PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md).

Palworld's own game data is never bundled in this repository. The conversion
pipeline reads it, at conversion time only, from the user's own legally-owned,
locally installed copy of the game.

### On the nature of this kind of tool

At its core, this tool reverse-engineers an undocumented binary format used by a
third-party commercial game (the `pak` container and its Oodle-compatible
compression). We state this plainly, as a technical fact rather than something
to apologize for. Other SignPath-signed open source projects that do the same
kind of thing (CryEngine Converter, ValveResourceFormat, REasy Editor) are
listed as precedents in the "Precedents consulted" section of
[CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md). The game's developer
(Pocketpair, Inc.) publicly welcomes modding; its only prohibitions are (1)
using mods on the official online servers and (2) infringing third-party
rights — neither of which applies to this tool.

### Honest disclosure: known weaknesses

- **Code signing has not been obtained yet.** This project is preparing to
  apply to the SignPath Foundation; **the application has not been submitted
  yet** (consistent with README.en.md and CODE_SIGNING_POLICY.md — not
  "submitted" and not "under review").
- **It is still detected today.** On 2026-07-30, a distributed build was
  flagged by antivirus software and briefly removed from all three
  distribution channels (BOOTH, itch.io, GitHub Releases). After removing the
  launcher executable believed to be a contributing factor (in source), we
  submitted the single remaining application binary (a build measured at
  258,048 bytes) to VirusTotal: it was flagged by **3 of 74** engines (we
  have since removed more code and have not re-tested the smaller current
  build, so we cannot state today's exact count). **A controlled experiment
  found that a do-nothing empty program was flagged more, not less**:
  **12 of 74** engines when it carried an icon and assembly metadata, and **4 of 74**
  when it had neither — both higher than the 3 of 74 for the real
  application — direct evidence the detection is not responding to this
  tool's code behavior. **Signing is not guaranteed to
  stop it either** — our own web research turned up multiple real-world
  reports of EV-signed applications still being flagged after signing.
  **We have not yet applied to the SignPath Foundation.** We proactively
  removed the launcher, the runtime C#-compile-and-execute self-diagnostic,
  and dormant self-update code **from the source** on our own initiative.
  **⚠ These removals have landed in source and CI, but have not yet reached
  the currently downloadable release (v2.2.12), which still ships the old
  layout (a launcher plus `_internal\Uchinoko.exe`, two executables).** We
  plan to include them starting with the next release, but are not rushing
  it since AV detection has not improved. Full numbers and
  analysis are in the "A note on antivirus false positives" section of
  [SECURITY.md](SECURITY.md). We would rather disclose this upfront than have
  it surface as a surprise during review.
- This project is maintained by a single individual developer (pandrabox).
  Governance details: the "Approvers / Committers" section of
  [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md), and [CODEOWNERS](CODEOWNERS).

### A 5-minute verification path for reviewers

1. **Check build reproducibility**: review the build logs under
   [Actions](https://github.com/pandrabox/Uchinoko/actions). Every release is
   produced by the public GitHub Actions workflow
   (`.github/workflows/build.yml`), whose external actions are pinned to commit
   SHAs.
2. **Check the license boundary**: cross-reference [LICENSE](LICENSE) (MIT)
   against [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (the GPLv3+
   boundary explanation).
3. **Check bundled asset provenance**: read the "Independent verification"
   section of [PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md).
4. **Check what data is transmitted**: [PRIVACY.md](PRIVACY.md) /
   [PRIVACY.en.md](PRIVACY.en.md) and the "What this program transmits" section
   of [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md). There are exactly two
   outbound network paths: a single background update-check GET request at
   startup, and a diagnostic report sent only after the user explicitly clicks
   through the in-app contact form.
5. **Check known-risk disclosure**: read [SECURITY.md](SECURITY.md) in full
   (vulnerability reporting, design assumptions, and the antivirus
   false-positive disclosure).

### Key documents

| Document | Contents |
|---|---|
| [README.md](README.md) / [README.en.md](README.en.md) | Product overview, supported scope, usage |
| [LICENSE](LICENSE) | Full text of the MIT License |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting, design assumptions, AV false-positive disclosure |
| [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md) | Signing application status, approver governance, what is transmitted |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Third-party components and the license boundary |
| [PROVENANCE_NOUE_ASSETS.md](PROVENANCE_NOUE_ASSETS.md) | Provenance and verification of bundled binary assets |
| [PRIVACY.md](PRIVACY.md) / [PRIVACY.en.md](PRIVACY.en.md) | What the in-app contact form transmits |
| [BUILD.md](BUILD.md) | How to build from source |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute, supported scope |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Code of conduct |
| [CODEOWNERS](CODEOWNERS) | Who is responsible for changes (single maintainer) |
