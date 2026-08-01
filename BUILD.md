# ビルド手順 (Build Instructions)

*English section is below the Japanese one.*

現行(v2.3.1)の配布物は `Uchinoko.bat` + 組み込み版 Python(`res\python_embed\`、
python.org 公式 embeddable ビルド + Tcl/Tk)+ `res\app\`(`app_py\` のソース一式)
という構成です。ビルドの正本は Python スクリプト `app_py\build.py` で、
zip 化を行う `build\make_dist.ps1` はそれを呼び出すだけの薄い殻です。
第三者がこのリポジトリを clone しただけの状態から、配布物の生成まで
再現できることを目的として、この文書を用意しています。

旧 C#/WinForms 実装(`app\DiveToPalworld.cs` / `app\build_app.ps1`、
`csc.exe` ビルド)はリポジトリに残っていますが、**現在の配布物のビルド
対象ではありません**(v2.3.0 で `app_py\` ベースの構成に切り替え済み)。

## 前提

- Windows 10 / 11
- Python 3(`app_py\build.py` 自体を実行するインタプリタ。バージョンは
  問いません)
- PowerShell 7+(`pwsh`)— 手順2(配布用 zip の作成)でのみ必要。
  手順1(ペイロードの組み立てのみ)は Python だけで完結します
- git
- インターネット接続 — `app_py\build.py` が python.org の embeddable
  Python zip とフルインストーラ(tkinter 抽出用)を初回実行時に自動取得
  します(取得後はハッシュ検証つきでローカルキャッシュ、`packaging\_cache\`)

以下は、ライセンス上の理由でリポジトリに同梱できないため、
clone しただけでは揃いません。ビルド前に各自で用意してください。

| 前提物 | 入手元 | 配置方法 |
|---|---|---|
| pyooz 0.0.8(`ooz.pyd`) | `pip install pyooz`、またはソースを同梱している `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` からビルド | 既定では Python 3.13 環境のユーザー site-packages(`%APPDATA%\Python\Python313\site-packages\ooz.pyd`、`pip install` の既定出力先)を探します。別の場所にある場合は環境変数 `D2P_OOZ_SITE_PACKAGES` に site-packages ディレクトリのフルパスを設定してください(`app_py\build.py` `_resolve_ooz_pyd()`) |

前提物が揃っていない状態で `app_py\build.py` を実行すると、何が足りないか・
どこから入手すべきかを明示してビルドを中断します(黙って失敗する設計にはしていません)。

## 手順1: 配布ペイロードだけを組み立てる

```
python app_py\build.py --out <出力先ディレクトリ>
```

出力: 指定したディレクトリ直下に `Uchinoko.bat` / `README.txt` / `res\`
の3点のみが並ぶ構成(この3点以外が生成された場合、ビルド自体が
`ROOT_LAYOUT=FAIL` で失敗します)。実行の最後に以下のゲートが
自動で走り、いずれか1つでも `FAIL` ならビルド全体が失敗として終了します。

- `SIGNATURE_GATE` — `packaging\check_signatures.py` による署名検査
  (詳細: [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md))
- `BAT_ISOLATION_GATE` — `Uchinoko.bat` が `%~dp0` 相対パスのみを参照し、
  ホスト環境の PATH 上の Python に依存していないことの検査
- `PTH_GATE` — 組み込み Python の `._pth` 設定が正しく、実行時の
  暗黙の `pip`/サイトパッケージ経路が開いていないことの検査

`--fixture` を付けると、`app_py\` 本体の代わりに軽量なスタブアプリを
使ってビルド一式(組み込み Python の取得・tkinter 抽出・署名検査等)
だけを素早く検証できます(生成した `Uchinoko.bat` を実際に起動する
自己テストも自動で走ります)。

## 手順2: 配布用フルセットzipをビルドする

```
pwsh -File build\make_dist.ps1 -Version vX.Y.Z
```

`-Version` は `app_py\ui\main_window.py` 内の `TOOL_VERSION` 定数と
一致させる必要があります。不一致の場合、ビルド前のバージョン整合
チェックがエラーで停止します。

`make_dist.ps1` は内部で手順1の `app_py\build.py`(`--fixture` なし、
実際の `app_py\` ソースを使用)を呼び出すため、手順1を個別に実行しておく
必要はありません。

出力: `dist\Uchinoko_vX.Y.Z_full.zip`(dev#625(2026-08-01)以降。旧: `Uchinoko_for_Palworld_vX.Y.Z_full.zip`)。

Blender ポータブル本体はこの配布zipに同梱されず、利用者の初回起動時に
公式サイトから自動取得される方式(`pipeline\cli\ensure_blender.ps1`、
配置先は展開後の `res\assets\tools\`)のため、zipサイズは組み込み
Python + アプリ本体コードのみを含む数十MB程度に収まります。

## テストの実行(任意)

このリポジトリには pytest ベースのテストが同梱されています。例:

```
python -m pytest app_py\tests -q
python -m pytest packaging\tests -q
python -m pytest tests\coverage -q
```

`app_py\tests` は GUI 本体(`app_py\`)、`packaging\tests` はビルド
スクリプト自身(署名ゲートの負の対照テスト等)、`tests\coverage` は
変換パイプラインのカバレッジ試験群です。一部のテストは Blender /
Palworld 実機等の外部依存を必要とします。テストごとの前提は
`tests\shipcheck\SHIPCHECK.md` を参照してください。

---

## English

The current (v2.3.1) distributable is `Uchinoko.bat` plus an embedded Python
runtime (`res\python_embed\`, the official python.org embeddable build with
Tcl/Tk overlaid) and `res\app\` (a copy of the `app_py\` source tree). The
canonical build script is the Python script `app_py\build.py`; the zip-making
`build\make_dist.ps1` is a thin shell that just calls it. This document
exists so that a third party can reproduce a build starting from nothing
more than a clone of this repository.

The retired C#/WinForms implementation (`app\DiveToPalworld.cs` /
`app\build_app.ps1`, built with `csc.exe`) still exists in the repository,
but it is **not part of the current distributable's build** (the project
switched to the `app_py\`-based build in v2.3.0).

### Prerequisites

- Windows 10 / 11
- Python 3 (any version, used only to run `app_py\build.py` itself)
- PowerShell 7+ (`pwsh`) — needed only for Step 2 (building the zip). Step 1
  (assembling the payload) is Python-only
- git
- Internet access — `app_py\build.py` downloads the python.org embeddable
  Python zip and the full installer (used to extract tkinter) the first time
  it runs (hash-verified, then cached locally under `packaging\_cache\`)

The following item cannot be bundled in the repository for licensing
reasons, so a plain clone does not provide it. Obtain it yourself before
building.

| Prerequisite | Source | How to place it |
|---|---|---|
| pyooz 0.0.8 (`ooz.pyd`) | `pip install pyooz`, or build it from the bundled source at `third_party\pyooz-0.0.8-source\pyooz-0.0.8.tar.gz` | By default, looked up under the Python 3.13 user site-packages (`%APPDATA%\Python\Python313\site-packages\ooz.pyd`, the default `pip install` location). If it lives elsewhere, set the `D2P_OOZ_SITE_PACKAGES` environment variable to the full path of the site-packages directory (`app_py\build.py`, `_resolve_ooz_pyd()`) |

If you run `app_py\build.py` without this prerequisite in place, it stops
the build and tells you exactly what is missing and where to get it (it is
not designed to fail silently).

### Step 1: Assemble the distribution payload only

```
python app_py\build.py --out <output directory>
```

Output: a directory containing exactly `Uchinoko.bat` / `README.txt` /
`res\` at its root (the build itself fails with `ROOT_LAYOUT=FAIL` if
anything else ends up there). The following gates run automatically at the
end of the build, and any single `FAIL` fails the whole build:

- `SIGNATURE_GATE` — the signature check performed by
  `packaging\check_signatures.py` (see
  [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md) for details)
- `BAT_ISOLATION_GATE` — verifies `Uchinoko.bat` only references paths
  relative to `%~dp0` and does not depend on a Python found via the host's
  PATH
- `PTH_GATE` — verifies the embedded Python's `._pth` configuration is
  correct and does not implicitly open a runtime `pip`/site-packages escape
  path

Passing `--fixture` swaps in a lightweight stub app in place of the real
`app_py\` tree, letting you quickly exercise the whole build machinery
(embeddable Python fetch, tkinter extraction, signature gate, etc.) without
the full application. It also automatically launches the generated
`Uchinoko.bat` as a self-test.

### Step 2: Build the full distribution zip

```
pwsh -File build\make_dist.ps1 -Version vX.Y.Z
```

`-Version` must match the `TOOL_VERSION` constant in
`app_py\ui\main_window.py`. If they don't match, the pre-build
version-consistency check stops with an error.

`make_dist.ps1` calls Step 1's `app_py\build.py` internally (without
`--fixture`, using the real `app_py\` sources), so you do not need to run
Step 1 separately.

Output: `dist\Uchinoko_vX.Y.Z_full.zip` (since dev#625, 2026-08-01; formerly `Uchinoko_for_Palworld_vX.Y.Z_full.zip`).

The Blender portable build is not bundled in this distribution zip — it is
fetched automatically from the official site on first launch
(`pipeline\cli\ensure_blender.ps1`, unpacked under `res\assets\tools\` once
extracted), which is why the zip, containing only the embedded Python
runtime plus the application's own code, stays on the order of a few tens
of MB.

### Running tests (optional)

This repository ships with pytest-based tests. For example:

```
python -m pytest app_py\tests -q
python -m pytest packaging\tests -q
python -m pytest tests\coverage -q
```

`app_py\tests` covers the GUI application itself (`app_py\`),
`packaging\tests` covers the build script (including negative-control tests
for the signature gate), and `tests\coverage` is the conversion pipeline's
coverage test suite. Some tests require external dependencies such as a
Blender install or a real Palworld installation. See
`tests\shipcheck\SHIPCHECK.md` for the prerequisites of each test.
