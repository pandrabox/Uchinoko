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
- 本ツールは VRC SDK を実行・呼び出ししません。

これらの前提が破られていると思われる挙動を発見された場合は、
上記いずれかの方法で最優先で報告してください。

## ウイルス対策ソフトによる検出について

過去のバージョン(〜v2.2.x)には、複数のウイルス対策製品に検出されるものが
ありました。個々の検出の当否について当方から断定はしません。v2.3.0以降は
配布物の構成を変更し、自作のコンパイル済み実行ファイル(PE)を一切含みません。
同梱される実行ファイルは python.org 公式配布の Python ランタイム(Python
Software Foundation の Authenticode 署名つき)のみで、ビルド時に
`packaging\check_signatures.py` が自作PEの混入を機械検査しています。
旧バージョンの利用は非推奨であり、サポート対象外です。

## ご自身で確認する方法

ソースコードは[公開リポジトリ](https://github.com/pandrabox/Uchinoko)で確認できます。

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
- This tool does not execute or invoke the VRC SDK.

If you observe behavior that appears to violate any of these assumptions, please
report it as a priority using either channel above.

### On detection by antivirus software

Past versions (up through the v2.2.x line) were sometimes flagged by multiple
antivirus products. We take no position on whether any individual detection was
correct. Starting with v2.3.0, the distributed package no longer contains any
self-compiled executable (PE) files. The only executables it bundles are the
official python.org Python runtime, carrying the Python Software Foundation's
Authenticode signature, and `packaging\check_signatures.py` machine-checks the
build for any self-made PE creeping in. Older versions are not recommended and
are not supported.

### How you can verify this yourself

The source code is available in our
[public repository](https://github.com/pandrabox/Uchinoko).

If you observe behavior that appears to violate the design assumptions above,
please report it as a priority using either channel described in "Reporting a
Vulnerability."
