# third_party 出所記録

| ファイル | 出所 | ライセンス | 取得日 |
|---|---|---|---|
| VRM_Addon_for_Blender-Extension-4_4_0.zip | https://github.com/saturday06/VRM-Addon-for-Blender/releases/tag/v4.4.0 | MIT | 2026-07-21 |
| pyooz-0.0.8-source/pyooz-0.0.8.tar.gz(同梱sdist内に別プロジェクトのコードを含む。詳細はNOTICE.md参照) | https://files.pythonhosted.org/packages/97/95/025dc21dbfe92855d6ab7b3c960159a682f647f71ac748714f0512695af6/pyooz-0.0.8.tar.gz (PyPI sdist、`pypi.org/pypi/pyooz/0.0.8/json`経由) | GPLv3+ | 2026-07-26 |

### pyooz(GPLv3+)について

配布物に同梱している `ooz.pyd`(pyooz 0.0.8、Oodle互換解凍ライブラリoozのPythonバインディング。
`pipeline\py\ooz_worker_gpl.py` からsubprocess経由でのみ呼び出される)に対応するソースコードを、
`pyooz-0.0.8-source\` に無改変のsdist(`pyooz-0.0.8.tar.gz`)として同梱している(GPLv3の
「対応するソースコードを入手可能にすること」という義務を、外部リンクに依存せず満たすため)。
SHA256・取得元URL・バージョン一致の確認記録は `pyooz-0.0.8-source\NOTICE.md` を参照。
GPLv3全文は `pyooz-0.0.8-source\LICENSE`。

sdist内には pyooz/ooz本体コード(一部ファイルにGPLv3の明示的なCopyright表記あり、
`Kraken Decompressor for Windows, Copyright (C) 2016, Powzix` 等)に加え、SIMD互換レイヤー
「SIMDe」(MIT License, Copyright 2017-2020 Evan Nemerson)と「Hedley」(CC0-1.0, 同氏)が
vendoringされている。いずれもソースファイル冒頭のコメントで確認したのみで、pyoozのsdist自体には
これらのLICENSEファイルは同梱されていない。判断は行わず、事実として記録する
(詳細は `pyooz-0.0.8-source\NOTICE.md` 参照)。

## テスト用VRM(test/vrm/、リポジトリには含めない)

| ファイル | 出所 | ライセンス |
|---|---|---|
| AliciaSolid_vrm-0.51.vrm | https://github.com/vrm-c/UniVRM (Tests/Models) | ニコニ立体ちゃん規約 https://3d.nicovideo.jp/alicia/rule.html |
| Seed-san.vrm | https://github.com/vrm-c/vrm-specification (samples) | VRM Public License 1.0 (著作者 VirtualCast, Inc.)。VRMファイル自体に埋め込まれたメタデータ(`extensions.VRMC_vrm.meta`)を実物解析して確認済み(2026-07-31): `avatarPermission: everyone` / `allowRedistribution: true` / `modification: allowModificationRedistribution` / `commercialUsage: corporation` / `creditNotation: required`(**クレジット表記必須**。THIRD_PARTY_NOTICES.md側で充足) |
| VitaVRM1.0.vrm | VRoid Hub「歴代サンプルモデル」 https://hub.vroid.com/en/characters/4593660874193246717/models/7942721847119018516 (β版VRoid Studioで配布されていたサンプルモデルをVRM1.0化したもの。アップロード者 Coatie(Koh-Tee)) | CC0 1.0 Universal 相当。VRoid Hub掲載の利用条件(2026-07-31確認): アバター利用/暴力表現/性的表現/宗教政治/反社会表現/法人利用/個人商用利用/再配布/改変/改変物の再配布いずれもOK、クレジット表記不要。VRMファイル埋め込みメタデータ(`extensions.VRMC_vrm.meta`、authors: "pixiv inc.", "coati")でも同内容(`avatarPermission: everyone` / `allowRedistribution: true` / `modification: allowModificationRedistribution` / `creditNotation: unnecessary`)を実物解析で確認済み |
| collected/100Avatars_038_Kate.vrm(他、`test/vrm/collected/100Avatars_*.vrm`シリーズ全般) | "100 Avatars" 系公開サンプルモデル群。制作 Polygonal Mind (www.polygonalmind.com) | CC0。VRMファイル埋め込みメタデータ(`extensions.VRM.meta`)を実物解析して確認済み(2026-07-31): `licenseName: CC0` / `allowedUserName: Everyone` / `commercialUssageName: Allow` / `violentUssageName: Allow` / `sexualUssageName: Allow` |

いずれもテスト目的の使用。VRMファイル自体の再配布はしない(.gitignore済み)。ただし
Seed-san / Vita / Kateはいずれも埋め込みライセンスが改変物の再配布・商用利用を明示的に
許可しているため、本ツールで変換した後の見た目を示すレンダリング画像
(`tests\relgate\baseline\<検体キー>\images\`)はリポジトリに同梱している。詳細な
クレジット表記は `THIRD_PARTY_NOTICES.md` を参照。

## テスト用アバター(test/cc0avatar/、CC0のため追跡・同梱可)

| ファイル | 出所 | ライセンス |
|---|---|---|
| Shapell_v1_0_3.zip | 取得元URL未確認(要確認)。zip内 `Shapell/LICENSE.txt` に "CC0 1.0 Universal (CC0 1.0) Public Domain Dedication / https://creativecommons.org/publicdomain/zero/1.0/deed.ja" と明記されていることを実物確認済み(2026-07-26) | CC0 1.0 Universal (Public Domain Dedication) |

同梱の3Dシェーダー「arktoon shader」自体は上記CC0とは別ライセンスであり、
Shapellのライセンス表記でも「シェーダーはそちらのライセンスに従うこと」と
明記されている(シェーダー自体のライセンス文言は未確認)。本プロジェクトでは
テスト目的での使用のみで、シェーダーコード自体の再配布・改変は行っていない。

## ユーザーが自分で取得するもの

- Blender 4.3.2 Windows Portable — https://www.blender.org/download/ (GPL)。
  u54(2026-07-27)以降、配布zipには同梱せず、ツールの初回起動時に
  `pipeline\cli\ensure_blender.ps1` が自動的にダウンロードして配置する
  (ユーザーが手動で取得・配置する操作は不要になった。ダウンロードURL・
  SHA256ピン留め値は同スクリプト参照)。開発チェックアウトから
  `build\make_dist.ps1` でビルドする場合も、Blender実体はもう不要
  (差し込み素材`ooz.pyd`/`python3.dll`だけが必要)。

dev#114(2026-07-29): 従来のUE経由モード(`-EngineMode ue`)は削除した(以降noue専用)。
Unreal Engine 5.1はもはやどの経路でも不要なため、本リストから外した。
