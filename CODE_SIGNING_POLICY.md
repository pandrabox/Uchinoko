# Code Signing Policy / コード署名ポリシー

*English section is below the Japanese one.*

## 現状(2026-07-31 時点)

本プロジェクトは、[SignPath Foundation](https://signpath.org) が
オープンソースプロジェクト向けに提供する無償コード署名証明書の利用を
**申請する準備を進めています**(2026-07現在、申請の準備段階であり、
**まだ申請していません**。証明書も付与されていません)。
申請・承認が完了し次第、公開リリースの実行ファイル(GitHub Actions によるビルド成果物)は
この証明書で署名される予定です。

このドキュメントは、審査にあたって SignPath 側が確認する観点
(誰が署名リクエストを承認できるか/このプログラムが外部へ何を送信するか)に
あらかじめ答えるために用意しています。書式は、SignPath Foundation から
既に署名を受けている他のオープンソースプロジェクト(後述)の公開文書を
参考にしています。

## 承認者・コミッター(Approvers / Committers)

本プロジェクトは個人開発者 **pandrabox**([GitHub](https://github.com/pandrabox))が
単独で開発・メンテナンスしています。

| 役割 | 担当 |
|---|---|
| Committers(コミット権限) | [pandrabox](https://github.com/pandrabox) |
| Approvers(署名リクエストの承認者) | [pandrabox](https://github.com/pandrabox) |

複数人体制になった場合は、このドキュメントを更新します。

## このプログラムが送信する情報について

本ツールは Windows デスクトップアプリとして**ローカル完結**で動作します。
外部ネットワークへ情報を送信する経路は、次の2つに限られます。

1. **起動時の自動アップデート確認**(バックグラウンド・非ブロッキング):
   `https://dl.osakishokai.com/versions.json` への GET リクエストを1回送信し、
   最新版の有無だけを確認します。個人情報・アバターデータ・利用状況の類は
   一切含まれません。オフライン時や失敗時は無音で諦めます。
   (実装: `app/DiveToPalworld.cs` `CheckForUpdateOnStartup()`、起動時に1回呼ばれる)
2. **ユーザーが明示的に操作した場合のみ送信される診断ログ**:
   アプリ内の「問合せ」(Contact)ボタンを押し、送信される内容を画面上で
   確認・編集した上で、あらためて [OK] をクリックしたときにだけ送信されます。
   アバターファイルそのものは含まれません(診断ログのみ)。
   (実装: `app/DiveToPalworld.cs` `ShowSupportDialog()` の第2段確認画面、
   送信は `okBtn` のクリックハンドラ内でのみ実行される)

上記の2つ以外に、ユーザーの意図しない自動送信は行いません。
より詳細な取り扱いは [`SECURITY.md`](SECURITY.md) の「このツールの設計上の前提」節、
および [`PRIVACY.md`](PRIVACY.md) を参照してください。

## `.signpath/` ポリシーファイルについて

SignPath Foundation から署名を受けている一部のオープンソースプロジェクトは、
Origin Verification(署名リクエストの出所検証)用の設定ファイルを
`.signpath/policies/<project>/*.yml` の形でリポジトリに直接コミットしています。

本プロジェクトでは、**このWPの時点ではこの種のファイルを設置しません。**
理由: このファイルが実際に必要とする値(SignPath 側のプロジェクト名・組織設定)は
SignPath への申請が承認され、プロジェクトが作成されるまで確定しません。
確定していない値をそれらしく埋めたひな形を置くと、「動いているように見えて
実際には機能しない設定」を本物として公開することになり、審査上も
利用者に対しても不正確です。承認プロセスの中で SignPath 側に
「このファイルは申請前に用意すべきものか、承認後の案内に従って追加するものか」を
確認し、必要と判明した時点で追加します。

## 参考にした前例(SignPath Foundation から既に署名を受けているプロジェクト)

- [Cryengine Converter](https://github.com/Markemp/Cryengine-Converter) —
  他社商用ゲームの独自バイナリ形式をポータブル3D形式へ変換するツール。
  README 内の「Code Signing Policy」節(Approvers/Committers 表 + プライバシー文)を参考にした
- [me3](https://github.com/garyttierney/me3) — 商用ゲーム向け MOD ローダー。
  独立ファイル `CODE_SIGNING_POLICY.md`(本ファイルと同名)を参考にした
- [KSP-CKAN](https://github.com/KSP-CKAN/CKAN) — MOD 管理ツール。
  謝辞形式での SignPath 言及を確認した
- [REasy Editor](https://github.com/seifhassine/REasy) — 他社商用ゲームの
  独自バイナリ形式を解析・編集するツール。`.signpath/policies/` の実物を確認した
  (上記「`.signpath/` ポリシーファイルについて」の判断根拠)

---

## English

### Current status (as of 2026-07-31)

This project is **preparing to apply** for a free code-signing certificate from
the [SignPath Foundation](https://signpath.org) for open source projects. As of
2026-07, **the application has not been submitted yet**, and no certificate has
been granted. Once the application is submitted and approved, public release
binaries (built via GitHub Actions) are intended to be signed with that
certificate.

This document exists to proactively answer the questions SignPath's review is
expected to ask (who can approve signing requests, what this program transmits
externally), following the format used by other open source projects that
already have SignPath Foundation signing (see below).

### Approvers / Committers

This project is developed and maintained solely by an individual developer,
**pandrabox** ([GitHub](https://github.com/pandrabox)).

| Role | Members |
|---|---|
| Committers | [pandrabox](https://github.com/pandrabox) |
| Approvers (for signing requests) | [pandrabox](https://github.com/pandrabox) |

This document will be updated if the project grows beyond a single maintainer.

### What this program transmits

This tool is a Windows desktop application that runs **entirely locally**.
There are exactly two paths by which it sends information to the network:

1. **An automatic update check on startup** (background, non-blocking): a
   single GET request to `https://dl.osakishokai.com/versions.json` to check
   whether a newer version exists. It contains no personal information, avatar
   data, or usage telemetry. Failures (including being offline) are silently
   ignored.
   (Implementation: `app/DiveToPalworld.cs`, `CheckForUpdateOnStartup()`,
   invoked once at startup.)
2. **A diagnostic log, sent only when the user explicitly requests it**: the
   in-app "Contact" button shows the exact content that would be sent, lets
   the user review and edit it, and only transmits it after the user clicks
   [OK] on that confirmation screen. It does not include the user's avatar
   file, only diagnostic log text.
   (Implementation: `app/DiveToPalworld.cs`, `ShowSupportDialog()`'s
   confirmation stage; the send call is only reached from the `okBtn` click
   handler.)

Beyond these two paths, this program does not transmit information without the
user's explicit action. See [`SECURITY.md`](SECURITY.md) ("Design assumptions
of this tool") for more detail, and [`PRIVACY.md`](PRIVACY.md) (English version:
[`PRIVACY.en.md`](PRIVACY.en.md)) for the full privacy policy.

### On the `.signpath/` policy directory

Some SignPath-signed open source projects commit an Origin Verification policy
file at `.signpath/policies/<project>/*.yml`.

**This WP intentionally does not add such a file yet.** The values it would
need (the SignPath-side project/organization identifiers) are not known until
after the application is approved and the SignPath project is created. Filling
in a template with placeholder values would present a non-functional
configuration as if it were real, which is inaccurate both for reviewers and
for anyone reading the repository. We plan to ask SignPath, during the
application process, whether this file should be pre-staged before approval or
added afterward per their instructions, and add it once that is known.

### Precedents consulted (projects already signed by SignPath Foundation)

- [Cryengine Converter](https://github.com/Markemp/Cryengine-Converter) — a
  tool that converts a third-party commercial game's proprietary binary
  formats into portable 3D formats. Its README's "Code Signing Policy"
  section (an Approvers/Committers table plus a privacy statement) was used
  as a reference.
- [me3](https://github.com/garyttierney/me3) — a mod loader for commercial
  games. Its standalone `CODE_SIGNING_POLICY.md` (same filename as this file)
  was used as a reference.
- [KSP-CKAN](https://github.com/KSP-CKAN/CKAN) — a mod manager, referencing
  SignPath in an acknowledgments-style mention.
- [REasy Editor](https://github.com/seifhassine/REasy) — a tool that parses
  and edits a third-party commercial game's proprietary binary formats. Its
  `.signpath/policies/` directory was inspected directly (the basis for the
  decision above).
