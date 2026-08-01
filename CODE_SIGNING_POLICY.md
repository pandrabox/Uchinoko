# Code Signing Policy / コード署名ポリシー

*English section is below the Japanese one.*

## 現状(2026-08-01時点、v2.3.1)

現行の配布物(`Uchinoko.bat` + `res\`)は、**自作でコンパイルした実行ファイル
(exe/dll/pyd)を一切含みません**。したがって「自作バイナリに署名するかどうか」
という問題自体が、この配布形態では構造的に発生しません。

配布物に含まれる実行ファイルの内訳は次のとおりです。

- `res\python_embed\`(`python.exe` / `pythonw.exe` / `python311.dll` /
  `_tkinter.pyd` / `tcl86t.dll` / `tk86t.dll` 等): いずれも
  [python.org](https://www.python.org/) が公式配布する embeddable Python
  および Tcl/Tk ランタイムをそのまま(無改変で)同梱したものです。
  Authenticode 署名は "CN=Python Software Foundation" のまま保持されています。
  取得・展開の手順は `app_py\build.py`(`ensure_embeddable_zip` /
  `ensure_tkinter_bundle`)を参照してください。
- `res\assets\blender_patch\ooz.pyd`: 第三者ライブラリ pyooz(GPLv3+)の
  バイナリで、署名はありません。Palworld の pak が採用する Oodle 互換圧縮
  (ooz)の解凍にのみ使用し、初回起動時にダウンロードした Blender の Python
  環境へ差し込まれます(このファイル自体は本ツールが自作したものではありません)。
  詳細は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) を参照してください。

エントリポイントの `Uchinoko.bat` はバッチファイル(非 PE)であり、
署名の対象外です。

## 検証方法

`packaging\check_signatures.py` が、配布ペイロード内の全ての `*.exe` /
`*.dll` / `*.pyd` を走査し、Windows の `Get-AuthenticodeSignature` で
署名状態を機械的に分類します。このゲートは `app_py\build.py`
(配布物を組み立てるビルドスクリプト)から毎回自動実行され、ビルドの
合否(`SIGNATURE_GATE=PASS`/`FAIL`)に直結します。

判定基準は「本ツール自身の過去のビルド出力と同名のファイル
(既定: `Uchinoko.exe` / `DiveToPalworld.exe`。旧 C#/WinForms 時代の
実行ファイル名)が、未署名のまま含まれていないか」の1点です。現行の
配布物にはこれらの名前のファイルは存在しないため、このゲートは常に
`PASS` します。第三者コンポーネント(前述の `ooz.pyd` 等)が未署名で
あること自体はレポートに記録されますが、ゲートの合否には影響しません
(既知の許容事項)。

## このプログラムが送信する情報について

本ツールは Windows デスクトップアプリとして**ローカル完結**で動作します。
外部ネットワークへ情報を送信する経路は、次の2つに限られます。

1. **起動時の自動アップデート確認**(バックグラウンド・非ブロッキング):
   `https://dl.osakishokai.com/versions.json` への GET リクエストを1回送信し、
   最新版の有無だけを確認します。個人情報・アバターデータ・利用状況の類は
   一切含まれません。オフライン時や失敗時は無音で諦めます。
   (実装: `app_py\update_check.py` `check_for_update()`、起動時に1回呼ばれる)
2. **ユーザーが明示的に操作した場合のみ送信される診断ログ**:
   アプリ内の「問合せ」(Contact)ボタンを押し、送信される内容を画面上で
   確認・編集した上で、あらためて [OK] をクリックしたときにだけ送信されます。
   アバターファイルそのものは含まれません(診断ログのみ)。
   (実装: `app_py\inquiry.py` `build_report_payload_json()` /
   `send_report_payload()`。送信は確認画面での明示操作からのみ呼ばれます)

上記の2つ以外に、ユーザーの意図しない自動送信は行いません。
より詳細な取り扱いは [`SECURITY.md`](SECURITY.md) の「このツールの設計上の前提」節、
および [`PRIVACY.md`](PRIVACY.md) を参照してください。

## 単独開発者による保守

本プロジェクトは個人開発者 **pandrabox**([GitHub](https://github.com/pandrabox))が
単独で開発・メンテナンスしています。

---

## English

### Current status (as of 2026-08-01, v2.3.1)

The current distributable (`Uchinoko.bat` + `res\`) contains **no
self-compiled executable files (exe/dll/pyd)**. As a result, the question of
"whether to sign our own binary" does not structurally arise for this
distribution format.

The executable files included in the distribution break down as follows:

- `res\python_embed\` (`python.exe` / `pythonw.exe` / `python311.dll` /
  `_tkinter.pyd` / `tcl86t.dll` / `tk86t.dll`, etc.): these are the official,
  unmodified embeddable Python and Tcl/Tk runtime files distributed by
  [python.org](https://www.python.org/). They retain their original
  Authenticode signature ("CN=Python Software Foundation"). See
  `app_py\build.py` (`ensure_embeddable_zip` / `ensure_tkinter_bundle`) for
  how they are fetched and unpacked.
- `res\assets\blender_patch\ooz.pyd`: a binary from the third-party library
  pyooz (GPLv3+), unsigned. It is used solely to decompress the Oodle-
  compatible compression (ooz) format used by Palworld's paks, and is
  patched into the downloaded Blender's own Python environment on first
  launch (this file is not something this project compiled itself). See
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for details.

The entry point `Uchinoko.bat` is a batch file (not a PE), so it is not a
signing target.

### How this is verified

`packaging\check_signatures.py` scans every `*.exe` / `*.dll` / `*.pyd` in
the distribution payload and mechanically classifies each one's signature
status via Windows' `Get-AuthenticodeSignature`. This gate runs automatically
every time `app_py\build.py` (the script that assembles the distributable)
runs, and its result (`SIGNATURE_GATE=PASS`/`FAIL`) directly gates the build.

The pass/fail criterion is a single check: whether any file whose *name*
matches this project's own historical build output (default:
`Uchinoko.exe` / `DiveToPalworld.exe` — names from the retired C#/WinForms
era) is present unsigned. No file with either of those names exists in the
current distribution, so this gate always passes. Third-party components
being unsigned (e.g. `ooz.pyd` above) is recorded in the report but does not
by itself fail the gate (a known, accepted condition).

### What this program transmits

This tool is a Windows desktop application that runs **entirely locally**.
There are exactly two paths by which it sends information to the network:

1. **An automatic update check on startup** (background, non-blocking): a
   single GET request to `https://dl.osakishokai.com/versions.json` to check
   whether a newer version exists. It contains no personal information, avatar
   data, or usage telemetry. Failures (including being offline) are silently
   ignored.
   (Implementation: `app_py\update_check.py`, `check_for_update()`, invoked
   once at startup.)
2. **A diagnostic log, sent only when the user explicitly requests it**: the
   in-app "Contact" button shows the exact content that would be sent, lets
   the user review and edit it, and only transmits it after the user clicks
   [OK] on that confirmation screen. It does not include the user's avatar
   file, only diagnostic log text.
   (Implementation: `app_py\inquiry.py`, `build_report_payload_json()` /
   `send_report_payload()`; the send call is only reached from that explicit
   confirmation action.)

Beyond these two paths, this program does not transmit information without
the user's explicit action. See [`SECURITY.md`](SECURITY.md) ("Design
assumptions of this tool") for more detail, and [`PRIVACY.md`](PRIVACY.md)
(English version: [`PRIVACY.en.md`](PRIVACY.en.md)) for the full privacy
policy.

### Sole maintainer

This project is developed and maintained solely by an individual developer,
**pandrabox** ([GitHub](https://github.com/pandrabox)).
