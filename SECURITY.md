# Security Policy / セキュリティポリシー

*English section is below the Japanese one.*

## サポート対象バージョン

このツールは個人開発者(pandrabox)がメンテナンスしています。
サポート対象は **常に最新版のみ** です。過去バージョンへの遡及的な
セキュリティ修正は行いません。

## 脆弱性の報告方法

セキュリティ上の懸念(脆弱性、意図しないデータ送信の疑い等)を発見された場合は、
以下のいずれかの方法でご連絡ください。

1. **アプリ内の「問合せ」ボタン**(推奨)。診断情報を添えて報告できます。
   公開の場に詳細を出したくない場合はこちらをお使いください。
2. **GitHub の Issue**。機密性の高くない内容(例: 依存パッケージの既知の
   脆弱性情報の共有など)であれば、通常の Issue として投稿していただいて
   構いません。

個人を特定する情報(実名・連絡先等)を Issue 本文に含めないようご注意ください。

## 報告時にお願いしたいこと

- 再現手順(可能であれば)
- 発生したバージョン
- ログ(アプリ内の「ログをコピー」機能で取得できるもの)

## このツールの設計上の前提

- 本ツールは**ローカル完結**で動作し、アバターデータを外部へ送信しません
  (問合せフォームでの送信を除く。送信内容は送信前に確認・編集できます)。
- 本ツールが同梱するアセット(`.uasset`/`.uexp` 形式、34ファイル)は、いずれも
  本プロジェクトが独自に生成した自作データです(公開リポジトリにも含まれます)。
  Palworld本体に由来するファイル(約426ファイル)は同梱しておらず、変換の
  実行時にユーザー自身がインストール済みのPalworldから都度取り出します。
- 本ツールは VRC SDK を実行・呼び出ししません。

これらの前提が破られていると思われる挙動を発見された場合は、
上記いずれかの方法で最優先で報告してください。

## アンチウイルス誤検知についての開示

2026-07-30、本ツールのビルド(v2.2.11)が Windows Defender に
`Trojan:Win32/Wacatac.H!ml` として検出され、配布3チャネル(BOOTH / itch.io /
GitHub Releases)すべてから一時的に取り下げる事態がありました。実際にマルウェアが
含まれていたわけではありません。審査等でスキャン結果に遭遇した場合に文脈なしに
驚かれるより、先にこちらから開示しておく方針です。

**現在も検出されます。** ランチャー exe を廃止した後の、単一の本体
`Uchinoko.exe`(258,048 バイト時点で計測したビルド。**この構成のビルドは
ソース・CI 上のものであり、まだリリースしていません**。下記「自ら進んで
行った対応」の重要な注記を参照)を VirusTotal へ提出した
ところ、74エンジン中3件に検出されました: Microsoft Defender
(`Trojan:Win32/Wacatac.B!ml`)、APEX(`Malicious`)、Malwarebytes
(`MachineLearning/Anomalous.97%`)。いずれも機械学習・ヒューリスティック系の
判定であり、既知マルウェアのシグネチャ一致ではありません。「本体は検出されない」
とは言えません。

**対照実験: 何もしないプログラムの方が多く検出されました。** 実アプリのビルドと
完全に同一の `csc.exe` コンパイラフラグを使い、ネットワーク・プロセス起動・
レジストリアクセスを一切含まない、空の WinForms アプリを2種類ビルドし、同じく
VirusTotal へ提出しました。アイコンと製品風のアセンブリメタデータを付けた版は
74エンジン中**12件**、何も付けない素の版は**4件**で検出され、**いずれも実アプリ
(3件)より多い**結果でした。実アプリを検出した3社は、この空のプログラムも
同じ検出名(Microsoftは`Trojan:Win32/Wacatac.B!ml`で完全一致)で検出しました。
コードの中身が完全に異なるのに判定が変わらなかったことは、検出が本ツールの
コードの挙動(PowerShell起動・自己更新・レジストリ読み取り等)に起因するもの
ではないことを直接示しています。

**推定している原因(断定はできません)**: 署名が無く、`csc.exe` でビルドする
たびにモジュールバージョンID(MVID)とタイムスタンプが変わる .NET 実行ファイルと
いう構造そのものです。リリースのたびに「初めて見るファイル」としてレピュテーション
ゼロから評価される点が、機械学習系の判定を招きやすいと考えています。

**自ら進んで行った対応(ソース・CI には反映済み。⚠ 現在配布中のリリースへの
反映状況は直後の重要な注記を必ず参照してください):**

- ランチャー exe(小さな未署名 exe が別の exe を起動し、自己更新の一部として
  隣接ファイルを書き換える構造)を廃止し、配布物をトップレベルの `Uchinoko.exe`
  1個のみへ一本化する変更をソースへ入れました。
- 実行ファイルへアセンブリのバージョン情報(製品名・発行者名・バージョン)を
  付与しました。**ただし上記の対照実験は、この対策が効果があるどころか逆効果で
  ある可能性を示しており、隠さず開示します**(メタデータ付きの検体の方が、
  無しの検体より多く検出されました)。
- 実行時に C# コードをコンパイル・実行する自己診断機能を、配布物から開発者専用
  ツール(`devtools\`)側へ分離しました。
- ダウンロードした更新ファイルを実際には適用しない、使われることのなかった
  自己更新の処理(ダウンロード・展開・書き込み)を配布物から削除する変更を
  ソースへ入れました。この削除により、上記で計測したビルド(258,048 バイト)
  より小さい(約 233,000 バイト)ビルドがソース上では作成可能ですが、
  **この縮小後のビルドはまだリリースしておらず、VirusTotal へ改めて提出しても
  いないため、本日時点の正確な検出件数は言えません。**

**⚠ 重要: 上記4件はいずれもソースコードと CI ビルドには反映済みですが、
現在配布中の最新リリース(v2.2.12)にはまだ反映されていません。** v2.2.12 は
引き続き旧レイアウト(トップレベルの `Uchinoko.exe` ランチャー exe +
`_internal\Uchinoko.exe` の2 exe 構成)のままです。これらの変更が実際の
配布物に反映されるのは次回リリースからです。次回リリースをまだ出していない
理由は、AV の検出状況が改善していないためです(ソース上で作成した次の
ビルド候補も VirusTotal で検出されることを確認済みで、配布を急ぐ判断は
していません)。

**コード署名について**: SignPath Foundation への申請を準備していますが、
**まだ申請していません**。コード署名は、上記の「未署名で毎回ゼロから評価される」
という構造そのものに対する標準的な対処ですが、**署名すれば検出が無くなると
断定はできません**(署名済みビルドはまだ存在せず、直接の検証はできていません)。

**ご自身で確認する方法**: 本ツールは公開の GitHub Actions
(https://github.com/pandrabox/Uchinoko/actions) でビルドされており、
ビルドログ・ソースコードとも公開リポジトリで誰でも確認できます。

これらの前提が破られていると思われる挙動を発見された場合は、このページ冒頭の
「脆弱性の報告方法」からご連絡ください。

---

## English

### Supported Versions

This tool is maintained by an individual developer (pandrabox). **Only the latest
release is supported.** Retroactive security fixes for older versions are not
provided.

### Reporting a Vulnerability

If you find a security concern (a vulnerability, suspected unintended data
transmission, etc.), please report it through one of the following:

1. **The in-app "Contact" button** (recommended). You can attach diagnostic
   information. Use this if you'd rather not disclose details publicly.
2. **A GitHub Issue.** For lower-sensitivity matters (e.g. sharing a known
   vulnerability in a dependency), a normal issue is fine.

Please avoid including personally identifying information (real names, contact
details, etc.) in issue bodies.

### What to include in a report

- Reproduction steps (if possible)
- The version affected
- Logs (available via the in-app "Copy log" feature)

### Design assumptions of this tool

- This tool runs **entirely locally** and never sends your avatar data anywhere
  else (except when you explicitly submit the in-app contact form, whose content
  you can review and edit before sending).
- The assets this tool bundles (`.uasset`/`.uexp` format, 34 files) are all
  original data we generated ourselves (also present in the public
  repository). Files derived from Palworld itself (roughly 426 files) are not
  bundled; the tool extracts them from your own installed copy of Palworld at
  conversion time.
- This tool does not execute or invoke the VRC SDK.

If you observe behavior that appears to violate any of these assumptions, please
report it as a priority using either channel above.

### A note on antivirus false positives

On 2026-07-30, a build of this tool (v2.2.11) was flagged by Windows Defender
as `Trojan:Win32/Wacatac.H!ml` and briefly removed from all three of our
distribution channels (BOOTH, itch.io, GitHub Releases). No malware was
present. We would rather disclose this upfront than have it surface as a
surprise during review.

**It is still detected today.** After removing the separate launcher
executable (see below), we submitted the single remaining application binary,
`Uchinoko.exe` (a build measured at 258,048 bytes; **this build exists only
in source/CI and has not been released yet** — see the important note under
"What we have done on our own initiative" below), to VirusTotal. It was
flagged by **3 of 74** engines: Microsoft Defender
(`Trojan:Win32/Wacatac.B!ml`), APEX (`Malicious`), and Malwarebytes
(`MachineLearning/Anomalous.97%`). All three are machine-learning/heuristic
verdicts, not matches against a known malware signature. We cannot say the
main executable is never flagged.

**A controlled experiment: an empty program was flagged more, not less.** We
built two minimal "Hello World" WinForms test programs — no networking, no
process launching, no registry access, nothing beyond a blank form — using
the exact same `csc.exe` compiler flags as the real build, and submitted them
to VirusTotal too. A version with an icon and product-style assembly metadata
was flagged by **12 of 74** engines; a bare version with neither was flagged
by **4 of 74** — both higher than the real application's 3 of 74. The same
three vendors that flag the real application flagged the empty test program
too, with Microsoft using the identical detection name
(`Trojan:Win32/Wacatac.B!ml`) on both. Since the code content was completely
different and the verdict from these three vendors did not change, this is
direct evidence that the detection is not responding to anything this tool's
code actually does (PowerShell invocation, self-update networking, registry
reads, etc.).

**What we believe is the underlying cause (not a proven fact)**: an unsigned
.NET executable compiled fresh with `csc.exe` on every build, which embeds a
new module version ID (MVID) and timestamp each time. Every release starts
from zero reputation, evaluated as a "never-seen-before" file — a pattern
machine-learning classifiers are prone to flag.

**What we have done on our own initiative (landed in source/CI — ⚠ see the
important note right after this list for how this maps onto what you can
actually download today):**

- Removed the separate launcher executable (a small, unsigned stub that
  started a second executable and, as part of self-update, could rewrite
  files next to itself), consolidating the source so the distributed
  package will become a single top-level `Uchinoko.exe`, with no
  `_internal\` subdirectory and no exe that starts another exe.
- Added assembly version metadata (product name, publisher, version) to the
  executable, which previously had none. **We are disclosing, not hiding,
  that our own controlled experiment above suggests this may not help and
  could even be counterproductive** — the metadata-carrying test binary was
  flagged more than the bare one.
- Moved the runtime C#-compile-and-execute self-diagnostic capability out of
  the distributed build and into a developer-only tool (`devtools\`).
- Removed dormant self-update code (a download/extract/staging path that
  downloaded and verified update packages but was never wired up to actually
  apply them) from the source. This brings the build down from the
  258,048-byte measurement above to roughly 233,000 bytes **when built from
  current source**. **We have not re-submitted this smaller build to
  VirusTotal, so we cannot state its exact detection count as of today.**

**⚠ Important: all four changes above have landed in source and CI, but
have not yet reached the currently downloadable release (v2.2.12).**
v2.2.12 still ships the old layout (a top-level `Uchinoko.exe` launcher plus
`_internal\Uchinoko.exe`, i.e. two executables). These changes will only
reach the distributed package starting with the next release. We have not
cut that release yet because AV detection has not improved enough to
justify shipping it (a build candidate produced from current source has
also been confirmed flagged on VirusTotal, so we are not rushing to
release it).

**On code signing**: we are preparing to apply to the SignPath Foundation,
but **the application has not been submitted yet**. Code signing is the
standard remedy for the "unsigned, freshly built, zero-reputation" structure
described above, but **we cannot claim it is guaranteed to stop these
detections** — no signed build exists yet, so we have not been able to test
one directly.

**How you can verify this yourself**: every release is built from public
GitHub Actions (https://github.com/pandrabox/Uchinoko/actions); both the
build logs and the source code are public.

If you observe behavior that appears to violate the design assumptions
above, please report it as a priority using either channel described in
"Reporting a Vulnerability."
