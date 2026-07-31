# pyooz 0.0.8 — 対応するソースコード(Corresponding Source)

このディレクトリは、配布物(初回起動時にダウンロードされるBlenderの
`python\lib\site-packages\ooz.pyd`。差し込み素材そのものは配布zip内
`assets\blender_patch\ooz.pyd` に同梱。2026-07-31のランチャー廃止・配布レイアウトの
フラット化以降、`_internal\`という入れ子は無い)に同梱している **pyooz 0.0.8**
バイナリに対応するソースコードです。
GPLv3の「対応するソースコードを入手可能にすること」という義務を満たすため、
外部リンクに依存せず本リポジトリへ同梱しています。

## 内容

- `pyooz-0.0.8.tar.gz` — PyPIで配布されているsdist(ソース配布物)を無改変のまま同梱したもの
- `LICENSE` — GPLv3全文(https://www.gnu.org/licenses/gpl-3.0.txt から取得)

## 取得記録

- 取得元URL: https://files.pythonhosted.org/packages/97/95/025dc21dbfe92855d6ab7b3c960159a682f647f71ac748714f0512695af6/pyooz-0.0.8.tar.gz
  (PyPI JSON API `https://pypi.org/pypi/pyooz/0.0.8/json` の `urls[].packagetype == "sdist"` から取得)
- ファイル名: pyooz-0.0.8.tar.gz
- サイズ: 734,484 バイト
- SHA256: 98916331773493764483bc6448c9c6166bf2440939abe77cd140509038cc3adf
  (ローカルで `sha256sum` により再計算し、PyPI JSON APIが報告する値と一致することを確認済み)
- 取得日: 2026-07-26

## バージョン一致の確認

配布物内 `pyooz-0.0.8.dist-info\METADATA`(配布zip展開後の
`assets\blender_patch\pyooz-0.0.8.dist-info\METADATA`。2026-07-31のランチャー廃止・
配布レイアウトのフラット化以降、`_internal\`という入れ子は無くなり、この差し込み素材は
配布物ルート直下の `assets\blender_patch\` に同梱される。実際にBlenderのPython環境へ
配置されるのは初回起動時、`pipeline\cli\ensure_blender.ps1` がダウンロードしたBlenderの
`python\lib\site-packages\` へこの素材をコピーした後)を実物確認し、
`Version: 0.0.8` であることを確認した。この METADATA は、BUILD.md の
手順どおりに配布zipをビルドすれば誰でも同じ場所に生成され、直接確認できる。
ビルド時に pyooz を供給する開発機側のインストール元(`build\make_dist.ps1` が参照する
`$env:APPDATA\Python\Python313\site-packages`、既定では `pip install pyooz` の
出力先)も同じく `pyooz-0.0.8.dist-info` であることを確認した。
いずれも同梱バイナリと一致するバージョン 0.0.8 である。

## python3.dll について

`python3.dll` は pyoozに付随するファイルではない。CPython公式配布物(Python 3.11)に含まれる、
stable ABI (`Py_LIMITED_API`) 用のリダイレクタDLLである。pyoozのwheelタグが `cp38-abi3-win_amd64`
(= stable ABI向けビルド)であるため、Blender同梱Python(3.11系)側に本来無い `python3.dll` を
別途配置する必要が生じている(`ooz_worker_gpl.py`ラッパー自体はGPLv3+だが、python3.dll自体は
PSF Licenseの下にあるCPython本体の一部であり、GPLの対象ではない)。

## 上流の追加の権利表示について(判断はせず、確認できた事実のみ記載)

pyoozのsdistには、pyooz自身のLICENSEファイルは同梱されていない
(`pyooz-0.0.8.tar.gz` を展開して確認。ライセンスの明示はPyPIの
Classifier (`License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)`)
と、各ソースファイル冒頭のコメントのみ)。

sdist内には、pyooz/oozのコード以外に、**第三者の別プロジェクトのソースが同梱されている**ことを確認した:

### 1. ooz本体(Kraken/Bitknit/LZNA等の解凍コード)

`ooz/dep/ooz/kraken.cpp` の冒頭(1〜17行目)に以下の表記があることを実物確認した(引用):

```
=== Kraken Decompressor for Windows ===
Copyright (C) 2016, Powzix

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
```

`bitknit.cpp` / `lzna.cpp` には同様のヘッダコメントは無い(無表記。ファイル冒頭を実物確認済み)。
このファイルが参照する「GNU General Public License」の全文は、本ディレクトリの `LICENSE`(GPLv3)
としてすでに同梱済み。

### 2. SIMDe (SIMD Everywhere)

`ooz/dep/ooz/simde/` 配下に、SIMD互換レイヤー「SIMDe」が丸ごとvendoringされている
(バージョン記載: `SIMDE_VERSION 0.7.3`、`simde-common.h`より)。**サンプル確認した限り、
ファイルごとにライセンスが異なる**(単一のライセンスで統一されていない):

- **MITライセンスのファイル群**(SIMDの各命令セット実装本体。例: `simde-common.h`、
  `arm/neon/add.h` 等、確認した限り大半がこちら): ファイル冒頭に以下の**MITライセンス全文**が
  そのまま記載されている。これは `ooz/dep/ooz/simde/simde/simde-common.h` の冒頭(1〜26行目)からの
  **引用**(上流sdist内に全文が存在したため、標準文面を補う必要はなかった):

  ```
  SPDX-License-Identifier: MIT

  Permission is hereby granted, free of charge, to any person
  obtaining a copy of this software and associated documentation
  files (the "Software"), to deal in the Software without
  restriction, including without limitation the rights to use, copy,
  modify, merge, publish, distribute, sublicense, and/or sell copies
  of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be
  included in all copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
  EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
  MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
  NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
  BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
  ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
  CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.

  Copyright:
    2017-2020 Evan Nemerson <evan@nemerson.com>
  ```

  著作権表示の年範囲はファイルごとに異なる(サンプル確認: `simde-common.h`は
  「2017-2020」、`arm/neon/add.h`は「2020」)。作者名(Evan Nemerson)はサンプルした
  全ファイルで一致していた。**全412ファイルを1件ずつは確認していない**(サンプル抽出による確認)。

- **CC0-1.0のファイル群**(ユーティリティ系ヘッダ。例: `simde-arch.h`): MITではなく
  以下の表記(`simde-arch.h`冒頭からの引用):

  ```
  Created by Evan Nemerson <evan@nemerson.com>

  To the extent possible under law, the authors have waived all
  copyright and related or neighboring rights to this code.  For
  details, see the Creative Commons Zero 1.0 Universal license at
  <https://creativecommons.org/publicdomain/zero/1.0/>

  SPDX-License-Identifier: CC0-1.0
  ```

**訂正**: 当初「pyoozのsdist自体にはSIMDeのLICENSEファイルは同梱されていない」とだけ記載していたが、
これは独立した`LICENSE`ファイルが無いという意味では正しい。ただし**MITの全文(著作権表示+許諾文)
自体は上記のとおり各ソースファイルのヘッダコメント内に verbatim で存在している**ため、標準の
MIT文面を別途補う必要はなかった。上流プロジェクト: https://github.com/simd-everywhere/simde
(公式リポジトリでの追加確認は本タスクでは未実施)。

### 3. Hedley

`ooz/dep/ooz/simde/simde/hedley.h`(SIMDeが内部で使う別の小規模ヘッダライブラリ)の冒頭
(1〜11行目)に以下の表記があることを実物確認した(引用):

```
Hedley - https://nemequ.github.io/hedley
Created by Evan Nemerson <evan@nemerson.com>

To the extent possible under law, the author(s) have dedicated all
copyright and related and neighboring rights to this software to
the public domain worldwide. This software is distributed without
any warranty.

For details, see <http://creativecommons.org/publicdomain/zero/1.0/>.
SPDX-License-Identifier: CC0-1.0
```

**私はこれらの追加の権利表示についてライセンス上の結論(GPLv3全体に対する影響の有無等)を判断していない。**
事実として見つかったこと(=各ファイルのヘッダコメントに実際に書かれていた文面)のみをここに
verbatimで記録する。要判断であれば指揮者・オーナーへ報告する。
