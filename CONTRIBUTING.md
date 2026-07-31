# Contributing / 貢献について

*English section is below the Japanese one.*

## このプロジェクトについて

Uchinoko for Palworld は、個人開発者(pandrabox)がメンテナンスしている
ファンメイドの非公式ツールです。VRChatterが自分のアバターでPalworldを
遊べるようにすることが目的です。

## 対応スコープ

このプロジェクトが公式にサポートする入力形式は次の3つです。

- VRM 0.0
- VRM 1.0
- prefab(VRChat向け、Modular Avatar 対応)

**Modular Avatar 以外の NDMF プラグインは非対応**です(副作用に責任が持てないため、
変換時に意図的に除去されます)。対応スコープの詳細は [README.md](README.md) の
「対応範囲」「非対応範囲」節を参照してください。

## Issue を立てる前に

- 既存の Issue を検索し、重複していないか確認してください。
- 不具合報告の場合は、アプリの「問合せ」ボタンから送信できる診断ログの内容が
  最も有用です。個人のアバターファイルの送付は不要です(むしろ多くの場合、
  購入した有料アセットのため再配布できません)。
- 機能要望は、このツールの対応スコープ(上記)に収まるものかご確認のうえ
  投稿してください。

## Pull Request を送る前に

- 大きな変更(仕様追加・挙動変更)は、まず Issue で相談してから着手することを
  おすすめします。手戻りを防げます。
- ビルド手順は [`BUILD.md`](BUILD.md) を参照してください。第三者がこのリポジトリの
  clone だけからビルド・動作確認できることを目標にしています。
- 変更内容に応じたテストが `tests\` 配下にあれば実行してください
  (`python -m pytest tests\coverage -q` など)。
- 本ツールが同梱しない・触れないもの:
  - Palworld のゲームデータ・アセットそのもの(同梱しません)
  - VRC SDK の実行・呼び出し(利用規約上の理由により行いません)
- Pull Request を送ることで、その変更がこのリポジトリの
  [MIT License](LICENSE) の下でライセンスされることに同意したものとみなします。

## 行動規範

このプロジェクトへの参加者は [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) に
従ってください。

---

## English

### About this project

Uchinoko for Palworld is a fan-made, unofficial tool maintained by an individual
developer (pandrabox). Its goal is to let VRChatters play Palworld as their own
avatar.

### Supported scope

The officially supported input formats are:

- VRM 0.0
- VRM 1.0
- A prefab (for VRChat, with Modular Avatar support)

**NDMF plugins other than Modular Avatar are not supported** (they are
intentionally removed during conversion, since their side effects cannot be
guaranteed). For the full list of what is and isn't supported, see the
"Supported Scope" / "Not Supported" sections of [README.en.md](README.en.md).

### Before filing an issue

- Please search existing issues first to avoid duplicates.
- For bug reports, the diagnostic log available via the in-app "Contact" button is
  the most useful thing to include. You do not need to send your personal avatar
  file (and in most cases you couldn't — most avatars are paid assets that cannot
  be redistributed).
- For feature requests, please check that the request fits within the supported
  scope described above before posting.

### Before sending a pull request

- For larger changes (new features, behavior changes), please open an issue to
  discuss first — this avoids wasted rework.
- See [`BUILD.md`](BUILD.md) for build instructions. The goal is that a third party
  can build and verify the tool from nothing more than a clone of this repository.
- If tests exist under `tests\` for the area you're changing, please run them
  (e.g. `python -m pytest tests\coverage -q`).
- Things this tool does not bundle or touch:
  - Palworld's own game data/assets (never bundled)
  - The VRC SDK (never executed or invoked, for terms-of-service reasons)
- By submitting a pull request, you agree that your contribution will be licensed
  under this repository's [MIT License](LICENSE).

### Code of Conduct

Participants in this project are expected to follow the
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
