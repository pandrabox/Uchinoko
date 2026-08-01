# ビルド手順 (Build Instructions)

*English section is below the Japanese one.*

このリポジトリは、追加のIDEやSDKのインストールなしに、Windows同梱の
.NET Framework 4.8(`csc.exe`)と PowerShell 7+(`pwsh`)だけでビルドできます。
第三者がこのリポジトリを clone しただけの状態から、配布物の生成まで
再現できることを目的として、この文書を用意しています。

## 前提

- Windows 10 / 11(`csc.exe` が `.NET Framework 4.8` に含まれる環境)
- PowerShell 7+(`pwsh`)
- git

以下の2つは、ライセンス上の理由でリポジトリに同梱できないため、
clone しただけでは揃いません。ビルド前に各自で用意してください。

| 前提物 | 入手元 | 配置方法 |
|---|---|---|
| pyooz 0.0.8(`ooz.pyd`) | `pip install pyooz`、またはソースを同梱している `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` からビルド | Python 3.13 環境のユーザー site-packages(`pip install` の既定出力先)に入っていれば自動検出されます |
| python3.dll(Python 3.11、stable ABI リダイレクタ) | 準備不要(ビルドが自動取得する embeddable Python 3.11.9 に含まれるものを使用) | 自動。別のファイルを使う場合のみ環境変数 `D2P_PYTHON311_DLL` にフルパスを設定してください(どの経路でも「フォワード先=python311」検証を通らないとビルドは失敗します) |

前提物が揃っていない状態で `build\make_dist.ps1` を実行すると、何が足りないか・
どこから入手すべきかを明示してビルドを中断します(黙って失敗する設計にはしていません)。

## 手順1: 本体exeだけをビルドする

```
pwsh -File app\build_app.ps1
```

出力: リポジトリ直下の `Uchinoko.exe`(`app\build_app.ps1` に `-Out` を渡すと
出力先を変更できます。`app\build_app.ps1:1-8`)。

**実測で確認済み**: 公開リポジトリ `pandrabox/Uchinoko` を新規に clone した直後の状態
(追加ファイル無し)から本コマンドを実行しても成功し、`Uchinoko.exe`(PE32 GUI .NET
assembly)が生成されることを確認しています。この文書の手順をそのまま実行すれば、
どなたでも同じ結果を再現・検証できます(生成物のサイズはコード量の変化に応じて
変わるため、ここでは具体的なバイト数は示していません)。

## 手順2: 配布用フルセットzipをビルドする

```
pwsh -File build\make_dist.ps1 -Version vX.Y.Z
```

`-Version` は `app\DiveToPalworld.cs` 内の `const string ToolVersion` と一致させる
必要があります。不一致の場合、ビルド前のバージョン整合チェックがエラーで停止します
(`build\make_dist.ps1:36-51`)。現在の `ToolVersion` は `app\DiveToPalworld.cs` 内で
`grep "const string ToolVersion"` すると確認できます。

`make_dist.ps1` は内部で手順1の `app\build_app.ps1` を呼び出すため、
手順1を個別に実行しておく必要はありません(`build\make_dist.ps1:60-61`)。

出力: `dist\Uchinoko_for_Palworld_vX.Y.Z_full.zip`。

**実測で確認済み**: 上記の前提物を用意した状態で、クリーンな clone から
`-Version` に `app\DiveToPalworld.cs` の `ToolVersion` と同じ値を渡して実行すると、
`dist\Uchinoko_for_Palworld_vX.Y.Z_full.zip` が生成されることを確認しています。
Blenderポータブル本体は配布zipに同梱されず、利用者の初回起動時に公式サイトから
自動取得される方式(`pipeline\cli\ensure_blender.ps1`)のため、zipサイズは
本体コードのみを含む数MB程度に収まります。

## 進行中の移行: Python版GUI(dev#532、2026-08-01時点ではまだ出荷経路ではない)

`app\DiveToPalworld.cs`(csc.exe/WinForms)は、dev#532で `app_py\`
(Python/tkinter)への全面書き直しが進行中です。**2026-08-01時点では
移行はまだ完了しておらず、上記の手順1・2(csc.exe/pwsh経由のビルド)が
引き続き唯一の正式な配布経路です。** `csc.exe`(.NET Framework 4.8)と
PowerShell 7+の前提は、この移行が完了(統合WP=D1完了)するまで変わりません。

移行完了後は本体exeの代わりに `Uchinoko.bat` + 組み込み版Python
(python.org embeddable、tkinter同梱)を配布する設計です
(詳細: `work\wp532A\DESIGN.md`)。現時点で移行中のコードを直接動かして
確認したい場合は以下が使えます(いずれも開発用途、配布物のビルド手順
としてはまだ確定していません):

```
python app_py\main.py            # GUIを直接起動して動作確認
python app_py\build.py --fixture # bat+組み込みPythonのパッケージング試作
```

この節は、統合WP(D1)が実際に配布経路を切り替えた時点で、上記の手順1・2の
記述そのものを書き換える形に更新する予定です。

## 未検証の部分(正直に明記します)

- **GitHub Actions 等の hosted runner 上での実行は本文書作成時点では未検証**です。
  上記の実測はいずれもローカル開発機の `csc.exe` / `pwsh` 環境によるものです。
  hosted runner 特有の差異(`csc.exe` のパス、`pip install pyooz` の成否等)が
  生じる可能性があります。
- `pyooz` の `pip install` がインターネット経由のビルド環境(hosted runner等)でも
  同様に成功するかは未検証です(開発機では事前にインストール済みの環境で確認しています)。

## テストの実行(任意)

このリポジトリには pytest ベースのテストが同梱されています。例:

```
python -m pytest tests\coverage -q
```

一部のテストは Blender / Palworld 実機等の外部依存を必要とします。
テストごとの前提は `tests\shipcheck\SHIPCHECK.md` を参照してください。

---

## English

This repository can be built without installing any additional IDE or SDK — only
the .NET Framework 4.8 compiler (`csc.exe`, bundled with Windows) and
PowerShell 7+ (`pwsh`) are required. This document exists so that a third party can
reproduce a build starting from nothing more than a clone of this repository.

### Prerequisites

- Windows 10 / 11 (an environment where `csc.exe` is available via `.NET Framework 4.8`)
- PowerShell 7+ (`pwsh`)
- git

The following two items cannot be bundled in the repository for licensing reasons,
so a plain clone does not provide them. Obtain them yourself before building.

| Prerequisite | Source | How to place it |
|---|---|---|
| pyooz 0.0.8 (`ooz.pyd`) | `pip install pyooz`, or build it from the bundled source at `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` | Auto-detected if present in the user site-packages of your Python 3.13 environment (the default `pip install` location) |
| python3.dll (Python 3.11, stable ABI redirector) | No preparation needed (taken from the embeddable Python 3.11.9 that the build downloads automatically) | Automatic. Only set the `D2P_PYTHON311_DLL` environment variable to a full path if you need a different file (either way, the build fails unless the file passes the "forwards to python311" check) |

If you run `build\make_dist.ps1` without these prerequisites in place, it stops the
build and tells you exactly what is missing and where to get it (it is not designed
to fail silently).

### Step 1: Build only the main executable

```
pwsh -File app\build_app.ps1
```

Output: `Uchinoko.exe` at the repository root (pass `-Out` to `app\build_app.ps1` to
change the output location; see `app\build_app.ps1:1-8`).

**Verified by an actual build run**: starting from a fresh clone of the public
repository `pandrabox/Uchinoko`, with no additional files in place, this command
succeeds and produces `Uchinoko.exe` (a PE32 GUI .NET assembly). Anyone can
reproduce and verify this by running the steps in this document as written (the
exact byte size is not stated here, since it drifts as the code changes).

### Step 2: Build the full distribution zip

```
pwsh -File build\make_dist.ps1 -Version vX.Y.Z
```

`-Version` must match `const string ToolVersion` inside `app\DiveToPalworld.cs`.
If they don't match, the pre-build version-consistency check stops with an error
(`build\make_dist.ps1:36-51`). You can check the current `ToolVersion` by grepping
for `const string ToolVersion` in `app\DiveToPalworld.cs`.

`make_dist.ps1` calls Step 1's `app\build_app.ps1` internally, so you do not need to
run Step 1 separately (`build\make_dist.ps1:60-61`).

Output: `dist\Uchinoko_for_Palworld_vX.Y.Z_full.zip`.

**Verified by an actual build run**: with the prerequisites above in place, running
this command from a clean clone with `-Version` set to the same value as
`ToolVersion` in `app\DiveToPalworld.cs` produces
`dist\Uchinoko_for_Palworld_vX.Y.Z_full.zip`. The Blender portable build is not
bundled in the distribution zip — it is fetched automatically from the official site
on first launch (`pipeline\cli\ensure_blender.ps1`) — which is why the zip, containing
only the tool's own code, stays a few MB in size.

### Ongoing migration: Python-based GUI (dev#532, not yet the shipping path as of 2026-08-01)

`app\DiveToPalworld.cs` (csc.exe / WinForms) is being rewritten from scratch in
`app_py\` (Python / tkinter) under dev#532. **As of 2026-08-01 this migration is
not complete, and Steps 1-2 above (building via csc.exe/pwsh) remain the only
official distribution path.** The `csc.exe` (.NET Framework 4.8) and
PowerShell 7+ prerequisites stay unchanged until this migration finishes (the
integration work package, "D1").

Once migration completes, the plan is to distribute `Uchinoko.bat` plus an
embedded Python runtime (python.org embeddable build, with tkinter bundled)
instead of the main executable (see `work\wp532A\DESIGN.md` for details). If
you want to try the in-progress code directly today, the following works for
development purposes only — it is not yet the confirmed build procedure for
the distributable:

```
python app_py\main.py            # launch the GUI directly to check it works
python app_py\build.py --fixture # prototype the bat + embedded-Python packaging
```

This section will be updated to replace Steps 1-2 themselves once the
integration work package ("D1") actually switches the distribution path over.

### What is not yet verified (stated honestly)

- **Running on a hosted runner such as GitHub Actions has not been verified as of
  writing this document.** Both measurements above were performed on a local
  development machine's `csc.exe` / `pwsh` environment. Hosted-runner-specific
  differences (the path to `csc.exe`, whether `pip install pyooz` succeeds, etc.)
  may occur.
- Whether `pip install pyooz` succeeds in an internet-connected CI build
  environment such as a hosted runner has not been verified (verification so far
  was done on a machine where it was already installed).

### Running tests (optional)

This repository ships with pytest-based tests. For example:

```
python -m pytest tests\coverage -q
```

Some tests require external dependencies such as a Blender install or a real
Palworld installation. See `tests\shipcheck\SHIPCHECK.md` for the prerequisites of
each test.
