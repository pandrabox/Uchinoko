# -*- coding: utf-8 -*-
"""工程0: ユーザー自身のPalworldインストールからバニラ情報を実行時抽出する。

配布物にゲームデータを一切含めないための要。ここで作るもの(全てジョブ内):
  vanilla/refskel_male.json / refskel_female.json  … 各性別のバインドポーズ数値
  vanilla/common_bones.json                        … 両性別に共通するボーン集合
  vanilla/dup_outfit_{male,female}.csv             … 全ティア複製リスト
  vanilla/dup_head_{male,female}.csv / dup_hair.csv / dup_headequip.csv
  vanilla/sk_inventory.json                        … バニラpakのSK完全在庫
                                                     (場所依存列挙、preflight G10用)
  vanilla/pak_entries.txt.gz                       … バニラpak全エントリ(preflight用)

使い方: python extract_vanilla.py <job.json> [--stage blender|full]

U54(2026-07-26)でキャッシュ判定と2段化を入れた。詳細は下の STAGE_* 節を参照。
"""

import csv
import gzip
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_live_extract
import vp_core as core

TAG = "extract_vanilla"
# 抽出物の版数。出力の追加・形式変更時に上げる(convert.ps1が照合し、古ければ再抽出)
VANILLA_VERSION = "4"  # 1=初版 2=headequip追加 3=hair refskel追加 4=場所依存列挙(U50)

# ============================================================================
# U54(2026-07-26): 抽出のキャッシュ判定と2段化
# ----------------------------------------------------------------------------
# これまで main() には早期リターンが無く、**プレビュー1枚のためにも毎回**
# pakインデックス(18万エントリ)の走査を含むフル抽出が走っていた
# (実測: 初回74秒 / OSキャッシュが温まっていても6秒。しかもフル変換1回で
#  convert.ps1のPhase 0とconvert_noue.pyのmain()から計2回)。
#
# 出力は「誰が読むか」で2段に分かれる:
#   blender段 … refskel_{male,female,hair}.json / common_bones.json
#                Blender工程(step02_retarget.py / validate_armature.py)が
#                直接読む。**プレビュー生成に要るのはここまで**
#   full段    … dup_*.csv / sk_inventory.json / pak_entries.txt.gz
#                pak組み立て(build_pak_from_avatar.py)とpreflight_pak.pyだけが
#                読む。pakインデックス全走査が要る重い側
#
# version.txt の意味は従来どおり「**full段まで**完了した抽出物の版数」。
# UEモードのconvert.ps1(Phase 0)とrestore_full.pyが昔からこの意味で読むので、
# blender段だけで止めたときは**書かない**。中途半端な抽出物を「完了」と
# 誤認させないため。
STAGE_BLENDER = "blender"
STAGE_FULL = "full"
STAGES = (STAGE_BLENDER, STAGE_FULL)

# 段ごとの必須出力(スタンプを信じ切らず実在も確かめる)。refskel_hair.jsonは
# バニラ髪SKが取れないときに作られない(WARNを出して続行する)ので必須にしない
BLENDER_OUTPUTS = ("refskel_male.json", "refskel_female.json",
                   "common_bones.json")
FULL_OUTPUTS = ("dup_outfit_male.csv", "dup_outfit_female.csv",
                "dup_head_male.csv", "dup_head_female.csv",
                "dup_hair.csv", "dup_headequip.csv",
                "sk_inventory.json", "pak_entries.txt.gz")
STAMP_NAME = "extract_stamp.json"

# ============================================================================
# dev#91(2026-07-29): 抽出物マニフェスト(層理論の互換プローブ)
# ----------------------------------------------------------------------------
# 「変換パイプラインが消費するバニラ抽出物セットのハッシュが前版と不変なら
# ツール互換は確定」という十分条件(dev#91、ぱん裁定でクライアント側自己判定を
# 主機構に採用)を実装する材料。GUI(app\DiveToPalworld.cs)が起動時のバージョン
# チェックで「版番号は不一致だが抽出物は既知良好と一致」を検出し、擬陽性警告を
# 自己抑止するのに使う。
#
# 37.7GBのpak本体は一切ハッシュしない。ハッシュ対象はfull段完了時点で既に
# ディスク上にある小さな出力ファイルだけ(実測合計は概ね1MB未満、
# pak_entries.txt.gzが支配的)。full段は「バニラ抽出はツール起動後どのみち
# 自動で走る」(U54 WP-Bのwarm-cache、GUI起動直後にバックグラウンドで実行)ため、
# 通常運用でこの計算が追加の起動遅延にはならない。
#
# ハッシュ対象からは意図的に extract_stamp.json / version.txt を除外する:
#   - extract_stamp.json … 絶対パス・mtime等の機体固有値を含み、
#     「抽出物の中身が同じか」という問いに無関係なノイズ
#   - version.txt        … 抽出器自身のスキーマ版数(VANILLA_VERSION)であって
#     パルワールド本体のバージョンではない(モジュール冒頭コメント参照)。
#     schema版が同じである前提はcompute_manifest()の外側(呼び出し側が
#     VANILLA_VERSION一致を別途確認する)で担保する
MANIFEST_NAME = "vanilla_manifest.json"
# refskel_hair.jsonは必須出力でない(バニラ髪SKが取れない環境では作られない)ため
# BLENDER_OUTPUTS/FULL_OUTPUTSには含めないが、存在すれば材料の一部として拾う
MANIFEST_OPTIONAL_FILES = ("refskel_hair.json",)
MANIFEST_FILES = BLENDER_OUTPUTS + FULL_OUTPUTS + MANIFEST_OPTIONAL_FILES


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest(vanilla_dir):
    """抽出物セットのsha256マニフェストを作る。戻り値:
    {"algo": "sha256", "files": {relname: hash, ...}, "combined_hash": hash}

    combined_hash は "relname:filehash\\n" をファイル名昇順に連結した文字列の
    sha256。ファイル集合が1つでも増減/変化すればcombined_hashも必ず変わる。
    存在しない任意ファイル(refskel_hair.json等)は静かにmanifestから除外する
    (欠落自体が既知良好リストとの不一致という形で自然に効く)。
    """
    files = {}
    for name in MANIFEST_FILES:
        path = os.path.join(vanilla_dir, name)
        if os.path.exists(path):
            files[name] = _sha256_file(path)
    combined = hashlib.sha256()
    for name in sorted(files):
        combined.update(f"{name}:{files[name]}\n".encode("utf-8"))
    return {"algo": "sha256", "files": files, "combined_hash": combined.hexdigest()}


def write_manifest(vanilla_dir):
    """compute_manifest()の結果をvanilla_dir直下へ書く。呼び出し側が
    read-only施錠(共有キャッシュ)の解除/再施錠を担当すること。"""
    manifest = compute_manifest(vanilla_dir)
    with open(os.path.join(vanilla_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(f"[{TAG}] vanilla manifest: combined_hash={manifest['combined_hash']} "
          f"({len(manifest['files'])} file(s))")
    return manifest


def ensure_manifest(vanilla_dir, shared):
    """vanilla_manifest.jsonが無ければ作る(既存の共有キャッシュ/job_dirを
    本機能導入前に作ったユーザーのための後方互換パス)。full段の出力が
    揃っていない場合は何もしない(まだ計算材料が無い)。"""
    if os.path.exists(os.path.join(vanilla_dir, MANIFEST_NAME)):
        return
    if not _have_all(vanilla_dir, FULL_OUTPUTS):
        return
    if shared:
        core.unlock_cache_dir_for_write(vanilla_dir)
    try:
        write_manifest(vanilla_dir)
    finally:
        if shared:
            core.lock_cache_dir_readonly(vanilla_dir)

SK_REL = ("Pal/Content/Pal/Model/Character/Player/Outfit/"
          "SK_Player_{g}_Outfit_OldCloth001/SK_Player_{g}_Outfit_OldCloth001")
HAIR_REL = ("Pal/Content/Pal/Model/Character/Player/Hair/Hair001/"
            "SK_Player_Hair001")


def extract_sk_files(job, out_dir):
    """OldCloth001のSK+バニラ髪SK(uasset/uexp)だけを抽出する。UE/UnrealPak.exeは
    使わず、pak_live_extract(U17)でPalworld本体のpakからその場解凍する。"""
    pak = job["paths"].get("palworld_pak")
    if not pak or not os.path.exists(pak):
        # WP16(公開issue #8): job.jsonに明示指定が無く自動探索も失敗した場合、
        # vp_core.load_job()がjob["_palworld_pak_search_error"]に「探した場所」
        # つきの詳細メッセージを残している。あればそちらを使い、無ければ
        # (=job.jsonの明示指定が単に無効だった場合)従来どおりの簡潔な文言にする。
        detail = job.get("_palworld_pak_search_error") or (
            f"Palworld's pak was not found: {pak}\n"
            "Please set paths.palworld_pak in job.json")
        core.die(TAG, detail)

    want = {}  # pak内相対パス -> (out_dirへの書き出し先絶対パス)
    for g in ("Male", "Female"):
        base_rel = SK_REL.format(g=g)
        for ext in (".uasset", ".uexp"):
            want[base_rel + ext] = os.path.join(out_dir, *(base_rel + ext).split("/"))
    for ext in (".uasset", ".uexp"):
        want[HAIR_REL + ext] = os.path.join(out_dir, *(HAIR_REL + ext).split("/"))

    mount, entries = core.read_pak_entries(pak)
    hair_available = (HAIR_REL + ".uasset") in entries and (HAIR_REL + ".uexp") in entries
    want_paths = [p for p in want if p in entries or not p.startswith(HAIR_REL)]
    missing_sk = [p for p in want_paths if p not in entries]
    if missing_sk:
        core.die(TAG, f"OldCloth001/Hair SK not found in pak: {missing_sk}")

    files = pak_live_extract.extract_files(pak, want_paths)
    for p, data in files.items():
        out_path = want[p]
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)

    result = {}
    for g in ("Male", "Female"):
        ua = want[SK_REL.format(g=g) + ".uasset"]
        result[g] = ua
    if hair_available:
        result["Hair"] = want[HAIR_REL + ".uasset"]
    else:
        print(f"[{TAG}][WARN] failed to extract vanilla hair SK — hair-sway feature unavailable")
    return result


# ============================================================================
# U50(2026-07-25): 対象一覧を「命名の形」依存から「場所」依存へ
# ----------------------------------------------------------------------------
# 旧実装は「SKは家族フォルダの直下にある」「頭装備のフォルダ名は HeadEquip\d+」
# のように**階層の深さと命名の型を決め打ちした正規表現**で列挙していた。
# その結果、命名がパターンから外れたバニラアセットが**静かに漏れて**いた
# (実測、work\u50_equip\out\FINDINGS.txt):
#   ・Outfit    : SK_Player_Male_Outfit_Octavia001/v01/SK_..._v01 が1階層深く漏れ
#                 (V1/V2アーマーにメッシュ注入が起きない)
#   ・HeadEquip : YakushimaHeadEquip001..006 / SK_YakushimaHeadEquip00N が
#                 フォルダ名・SK名の両方でパターンに当たらず漏れ
#                 (ホーリー系/ムーンロードのおめん/クトゥルフのめだまマスクが
#                  非表示化されずバニラのまま描画される)
# 対策として、「Player/Outfit 配下の SkeletalMesh はすべて衣装」
# 「Player/HeadEquip 配下はすべて頭装備」と**再帰・非決め打ちで**列挙する。
# 判定に使うのは「どのルート配下にあるか」「SK_ で始まるか」「Skeleton/Physics
# 付随アセットでないか」の3点のみで、深さも家族名も一切前提にしない。
# ============================================================================

# pak内エントリの座標系: "Pal/Content/" から始まる
PAK_CONTENT_PREFIX = "Pal/Content/"
# mod pak / noue_template_manifest.json 側の座標系(この接頭辞を除いた相対パス)
CHARACTER_PREFIX = "Pal/Content/Pal/Model/Character/"

# カテゴリ -> そのカテゴリのSkeletalMeshが置かれるルート(Pal/Content/ からの相対)
SK_CATEGORY_ROOTS = {
    "outfit": "Pal/Model/Character/Player/Outfit",
    "head": "Pal/Model/Character/Player/Head",
    "hair": "Pal/Model/Character/Player/Hair",
    "headequip": "Pal/Model/Character/Player/HeadEquip",
}

# 複製元(自作メッシュを直接置く場所)は複製先リストから外す
DUP_SOURCE_NAMES = frozenset({
    "SK_Player_Male_Outfit_OldCloth001",
    "SK_Player_Female_Outfit_OldCloth001",
    "SK_Player_Male_Head001", "SK_Player_Female_Head001",
    "SK_Player_Hair001", "SK_HeadEquip001",
})


def is_mesh_sk_name(name):
    """アセット名がSkeletalMesh本体のものか(付随のSkeleton/PhysicsAssetでないか)。

    命名の"型"は一切前提にしない。SK_ 接頭辞は Palworld の全カテゴリで
    例外なく守られている実測事実(Outfit 62 / Head 52 / Hair 37 /
    HeadEquip 70、いずれも100%)に基づく唯一の名前依存で、
    「どの家族か」「何階層目か」には依存しない。
    """
    return (name.startswith("SK_")
            and "Skeleton" not in name and "Physics" not in name)


def enumerate_vanilla_sk(entries):
    """バニラpakのエントリ一覧から、カテゴリ別のSkeletalMesh SKを場所依存で列挙する。

    引数 entries: core.read_pak_index/read_pak_entries が返す "Pal/Content/..."
                  形式のパス一覧。
    返り値: {category: [ {folder, name, rel} ... ]}(name昇順)
      folder … UE側のパッケージフォルダ(/Game/Pal/Model/Character/...)
      name   … アセット名(SK_...)
      rel    … CHARACTER_PREFIX を除いた相対パス(mod pak / manifest と同じ座標系。
               例: "Player/Outfit/SK_Player_Male_Outfit_Octavia001/v01/
                    SK_Player_Male_Outfit_Octavia001_v01.uasset")
    """
    out = {cat: [] for cat in SK_CATEGORY_ROOTS}
    for e in entries:
        if not e.endswith(".uasset"):
            continue
        for cat, root in SK_CATEGORY_ROOTS.items():
            prefix = PAK_CONTENT_PREFIX + root + "/"
            if not e.startswith(prefix):
                continue
            pkg = e[len(PAK_CONTENT_PREFIX):-len(".uasset")]  # Pal/Model/.../SK_x
            folder, _, name = pkg.rpartition("/")
            if not is_mesh_sk_name(name):
                break
            out[cat].append({"folder": f"/Game/{folder}", "name": name,
                             "rel": e[len(CHARACTER_PREFIX):]})
            break
    for cat in out:
        out[cat].sort(key=lambda r: (r["folder"], r["name"]))
    return out


def _gender_of(name):
    if "_Male_" in name:
        return "male"
    if "_Female_" in name:
        return "female"
    return None


def gen_duplication_lists(entries, vanilla_dir):
    """pakインデックスから全ティアの複製リストCSVを性別別に生成する(場所依存)。"""
    inventory = enumerate_vanilla_sk(entries)
    # カテゴリ -> {出力CSV名: 行リスト}。outfit/head のみ性別で分ける
    buckets = {
        "dup_outfit_male.csv": [], "dup_outfit_female.csv": [],
        "dup_head_male.csv": [], "dup_head_female.csv": [],
        "dup_hair.csv": [], "dup_headequip.csv": [],
    }
    ungendered = []
    for cat, rows in inventory.items():
        for r in rows:
            if r["name"] in DUP_SOURCE_NAMES:
                continue
            if cat in ("outfit", "head"):
                g = _gender_of(r["name"])
                if g is None:
                    # 性別が判定できないものを黙って落とすと、まさに今回直した
                    # 「静かな漏れ」の再発になる。落とすが**必ず声を上げる**
                    # (preflightのカバレッジゲートが名指しで検出する)
                    ungendered.append(r["rel"])
                    continue
                buckets[f"dup_{cat}_{g}.csv"].append(r)
            else:
                buckets[f"dup_{cat}.csv"].append(r)
    if ungendered:
        print(f"[{TAG}][WARN] excluded {len(ungendered)} Outfit/Head SK whose gender "
              f"could not be determined from the duplication list "
              f"(the preflight coverage gate will detect this): "
              f"{ungendered[:5]}")

    counts = {}
    for fname, rows in buckets.items():
        path = os.path.join(vanilla_dir, fname)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Folder", "Name"])
            w.writerows(sorted({(r["folder"], r["name"]) for r in rows}))
        counts[fname] = len(rows)
        print(f"[{TAG}] {fname}: {len(rows)} rows")
    print(f"[{TAG}] location-based enumeration (U50): "
          + ", ".join(f"{c}={len(inventory[c])}" for c in sorted(inventory)))
    if min(counts.values()) == 0:
        core.die(TAG, f"one or more duplication lists are empty: {counts} — pak structure "
                 "differs from expectations (possible Palworld major update)")

    # カバレッジゲート(preflight)の基準になる完全在庫。CSVは複製元を除いた
    # 「複製先」の一覧なので、漏れの検出にはこちらの生の全数を使う
    inv_path = os.path.join(vanilla_dir, "sk_inventory.json")
    with open(inv_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=1)
    print(f"[{TAG}] sk_inventory.json: "
          + " ".join(f"{c}={len(inventory[c])}" for c in sorted(inventory)))
    return counts


# --------------------------------------------------------------- キャッシュ判定

def build_fingerprint(job):
    """キャッシュの鍵。**パルワールド本体が更新されたら必ず変わること**が要件。

    鍵に何を使うか(U54、③はdev#226で mtime→内容ハッシュへ改訂):
      ① Pal-Windows.pak の絶対パス+サイズ+更新時刻
         … 抽出物の中身はすべてこのpakだけから決まる。本体が更新されれば
           サイズか更新時刻のどちらかは必ず動く。既に `live_template.
           build_live_template()` が同じ鍵(pak mtime+size)を使っており、
           GUI側の対応バージョン確認(app\\DiveToPalworld.cs)もpakサイズを
           判定材料にしている。プロジェクト全体で同じ流儀に揃える
      ② VANILLA_VERSION … 出力の形式が変わったら作り直す(UEモードの
         convert.ps1 Phase 0 が昔から見ている版数と同じもの)
      ③ この抽出器自身(extract_vanilla.py)の内容sha256(dev#226以前は
         サイズ+更新時刻だった)
         … VANILLA_VERSION の上げ忘れや、アプリ更新でロジックだけ変わった
           場合に「作り直す方」へ倒すため。誤検知の代償は再抽出1回だけで、
           倒れる向きが安全(古い抽出物を使い続ける事故が起きない)。
           dev#226(WSBキャッシュ持ち込みゲート)の実装中、配布zipを毎回
           まっさらなWindows Sandboxへ展開すると展開先ファイルのmtimeは
           「展開した瞬間の時刻」になり(Python zipfile.extractall()の
           挙動、2026-07-30実測)、mtimeベースの識別子は同一内容でも
           Sandbox起動のたびに変わってしまうことが判明した。クリーン
           都度環境でも安定した鮮度判定ができるよう、内容sha256(展開
           位置・タイミングに依存しない)へ切り替える。

    pak自体はハッシュ(sha1等)を採らない。40GBを毎回読むのは本末転倒であり、
    ①だけでもゲーム更新は検知できる(Steamの更新はファイルを置き換える)。
    """
    pak = job["paths"]["palworld_pak"]
    pst = os.stat(pak)
    return {
        "vanilla_version": VANILLA_VERSION,
        "pak_path": os.path.abspath(pak),
        "pak_size": pst.st_size,
        "pak_mtime": pst.st_mtime,
        "extractor_hash": core.sha256_file(os.path.abspath(__file__)),
    }


def _stamp_path(vanilla_dir):
    return os.path.join(vanilla_dir, STAMP_NAME)


def _read_stamp(vanilla_dir):
    path = _stamp_path(vanilla_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None  # 壊れていたら「無い」扱い=作り直す(安全側)


def _write_stamp(vanilla_dir, job, stage):
    with open(_stamp_path(vanilla_dir), "w", encoding="utf-8") as f:
        json.dump({"stage": stage, "fingerprint": build_fingerprint(job)},
                  f, indent=1)


def _clear_stamp(vanilla_dir):
    """これから出力を上書きする前に消す。途中で落ちても、次回に「完了済み」と
    誤認されないようにするため(古い抽出物を使い回す事故の予防)。"""
    try:
        os.remove(_stamp_path(vanilla_dir))
    except OSError:
        pass


def _have_all(vanilla_dir, names):
    return all(os.path.exists(os.path.join(vanilla_dir, n)) for n in names)


def _version_txt_ok(vanilla_dir):
    """version.txt が「full段まで今の版数で完了した」と言っているか。"""
    try:
        with open(os.path.join(vanilla_dir, "version.txt"), encoding="utf-8") as f:
            return f.read().strip() == VANILLA_VERSION
    except OSError:
        return False


# ============================================================================
# U54 WP-B(2026-07-27): マシン共有キャッシュ化
# ----------------------------------------------------------------------------
# 抽出物は完全にアバター非依存(pakと抽出器だけで決まる)なのに、従来は
# job_dir(work\<AvatarName>\vanilla\)へ書いていたためアバターごとに
# 再抽出していた。ここではPalworldのpakが解決できる通常経路(ライブ抽出)に
# 限り、マシン共有キャッシュ(vp_core.shared_cache_dir)へ本体を置く。
#
# ただし step02_retarget.py(Blender)とpreflight_pak.pyは job["job_dir"]/
# vanilla を直接読んでおり(本WPの書き込み許可ファイル一覧に含まれない
# ため、読み手側のパス解決を付け替えられない)、4.2の原則(per-jobコピー
# 禁止、読み手を共有キャッシュへ向け直す)を完全には満たせない。
# 「どうしても困難な場合のみ最小のper-jobコピーを許す」の規定に従い、
# 共有キャッシュ本体(重い計算=pak全走査等はここで1回だけ)とは別に、
# job_dir配下へも軽量な複製(実測<1MB、pak_entries.txt.gzが支配的でも
# 約800KB)を残す(_sync_job_local_copy)。節約したいのは**計算**であって
# 数百KBのコピーではないため、実害は無い。
#
# D2P_NOUE_TEMPLATE_ROOT(開発/検証用override)またはpakが解決できない
# (開発機フォールバック)場合は、従来どおりjob_dir/vanilla直接書き込みの
# ままにする(resolve_vanilla_source()のkind判定と同じ条件)。
# ============================================================================

def _job_local_vanilla_dir(job):
    return os.path.join(job["job_dir"], "vanilla")


def resolve_vanilla_dir(job):
    """読み手・書き手が共通して使うべきバニラ参照データの実際の場所を1箇所で
    決める。convert_noue.resolve_vanilla_source()のkind判定(override>live>dev)
    と同じ条件(pakの有無、override環境変数)だけを見る軽量な再実装
    (extract_vanilla.py は convert_noue.py から import される側なので、
    循環importを避けるためconvert_noue.pyへは依存しない)。"""
    if os.environ.get("D2P_NOUE_TEMPLATE_ROOT"):
        return _job_local_vanilla_dir(job)  # override: 従来どおりjob_dir直下
    pak = job["paths"].get("palworld_pak")
    if pak and os.path.exists(pak):
        work_root = core.job_work_root(job)
        return core.shared_cache_dir(work_root, "vanilla", build_fingerprint(job))
    return _job_local_vanilla_dir(job)  # 開発機フォールバック: 従来どおり


def cached_stage(job, vanilla_dir=None):
    """既存の抽出物が**今のpak・今の抽出器**に対して有効なら、どこまで
    済んでいるか(STAGE_FULL / STAGE_BLENDER)を返す。無効ならNone。

    スタンプの記載を信じ切らず、その段の出力が実在するかも必ず確かめる
    (作業域をコピーして一部だけ欠けている、手で消した等を拾う)。
    """
    if vanilla_dir is None:
        vanilla_dir = resolve_vanilla_dir(job)
    stamp = _read_stamp(vanilla_dir)
    if not stamp:
        return None
    try:
        if stamp.get("fingerprint") != build_fingerprint(job):
            return None  # pakが更新された/抽出器が変わった → 作り直す
    except OSError:
        # pakが読めない(パス違い等)。ここで判定はできないので「無効」を返し、
        # 抽出本体に理由付きで落としてもらう
        return None
    if not _have_all(vanilla_dir, BLENDER_OUTPUTS):
        return None
    if (stamp.get("stage") == STAGE_FULL
            and _have_all(vanilla_dir, FULL_OUTPUTS)
            and _version_txt_ok(vanilla_dir)):
        return STAGE_FULL
    return STAGE_BLENDER


def is_cache_fresh(job, want_stage):
    """want_stageが既存の抽出物で満たされているか(convert_noue.pyから使う)。"""
    have = cached_stage(job)
    if have == STAGE_FULL:
        return True
    return have == STAGE_BLENDER and want_stage == STAGE_BLENDER


# ------------------------------------------------------------------ 抽出の本体

def extract_blender_stage(job, vanilla_dir):
    """Blender工程が読む分(refskel_*.json / common_bones.json)を作る。"""
    # 1) SK抽出 → RefSkeleton数値化(ゲームバイナリは即削除、数値のみ保持)
    tmp = tempfile.mkdtemp(prefix="d2p_ext_")
    try:
        sk = extract_sk_files(job, tmp)
        ref = {}
        for g, ua in sk.items():
            # 髪SKは小骨格(root〜head+hair_01..09の十数本)なので下限を下げる
            ref[g] = core.load_refskel(ua, min_bones=5 if g == "Hair" else 40)
            out = os.path.join(vanilla_dir, f"refskel_{g.lower()}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(ref[g], f, indent=1)
            print(f"[{TAG}] refskel_{g.lower()}.json: {len(ref[g])} bones")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2) 共通ボーン集合(衣装固有のクロスボーン M_/F_OldCloth001_* を除いた交差)。
    #    Blender工程はこの集合だけでアーマチュアを構築する → 両性別で同一階層になり
    #    UE側で1つのSkeletonアセットを共有できる
    common = sorted(set(ref["Male"]) & set(ref["Female"]),
                    key=list(ref["Male"]).index)
    dropped = sorted((set(ref["Male"]) | set(ref["Female"])) - set(common))
    with open(os.path.join(vanilla_dir, "common_bones.json"), "w",
              encoding="utf-8") as f:
        json.dump({"common": common, "dropped": dropped}, f, indent=1)
    print(f"[{TAG}] common bones: {len(common)} (dropped: {dropped})")


def extract_full_stage(job, vanilla_dir):
    """pak組み立て/preflightが読む分(複製リスト+pak全エントリ)を作る。
    pakインデックスの全走査が要る重い側。"""
    # 3) 複製リスト+pak全エントリ(preflightの照合基準)
    mount, entries = core.read_pak_index(job["paths"]["palworld_pak"])
    gen_duplication_lists(entries, vanilla_dir)
    # dev#91(2026-07-29実測で発覚): core.read_pak_index()が返すentriesの並び順は
    # 同一pakでも実行のたびに変わる(pak内部インデックスの走査順が安定していない。
    # v1.0.1/v1.0.2の同一37万行の集合で818行の並び差を実測)。
    # 消費側(preflight_pak.py)はset()化してから使うため並び順に意味は無いが、
    # ここをソートせずに書くと、内容が完全に同一でもファイルのバイト列(ひいては
    # 抽出物マニフェストのcombined_hash、dev#91)が実行ごとに揺れてしまい、
    # 「材料が変わっていないことをハッシュで自己判定する」という目的そのものが
    # 壊れる。ソートして書けば、同じpakからは常に同じバイト列になる。
    # あわせてgzipヘッダのmtimeも固定する(既定はwtの度に現在時刻が入り、
    # 中身が同一でも圧縮後バイト列だけが変わってしまうため)。
    data = "\n".join(sorted(entries)).encode("utf-8")
    with gzip.GzipFile(os.path.join(vanilla_dir, "pak_entries.txt.gz"),
                        mode="wb", mtime=0) as f:
        f.write(data)
    print(f"[{TAG}] pak_entries: {len(entries)} entries (mount={mount})")


def _sync_job_local_copy(job, cache_dir, fingerprint):
    """共有キャッシュの中身をjob_dir配下の従来位置(vanilla\\)へも軽量複製する。
    理由はモジュール冒頭のU54 WP-Bコメント参照(step02_retarget.py/
    preflight_pak.pyがjob_dir/vanillaを直接読むため)。

    複製元(共有キャッシュ)はread-only施錠済みだが、複製先(job_dir側)は
    従来どおり書き込み可能なファイルとして置く(そちらを直接書き換える
    工程は無い読み取り専用の消費者だけなので実害はない)。

    **鮮度判定はfingerprint一致ではなくファイル単位の実在+サイズ一致で行う**
    (引数fingerprintは呼び出し元の互換のため残すが判定には使わない)。
    理由: fingerprintはstage(blender/full)に依存せず同一のため、
    「blender段だけ複製済み」の状態で後からfull段が共有キャッシュへ
    追加されても、fingerprint一致だけを見ていると複製が更新されない
    (実測で発覚: dup_*.csv/sk_inventory.json/pak_entries.txt.gz/version.txtが
    job_dir側に反映されないバグになっていた)。"""
    job_local = _job_local_vanilla_dir(job)
    cache_files = [fn for fn in os.listdir(cache_dir)
                   if fn != STAMP_NAME and os.path.isfile(os.path.join(cache_dir, fn))]
    need_copy = not os.path.isdir(job_local)
    if not need_copy:
        for fn in cache_files:
            dst = os.path.join(job_local, fn)
            src = os.path.join(cache_dir, fn)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
                need_copy = True
                break
    if not need_copy:
        return
    os.makedirs(job_local, exist_ok=True)
    for fn in cache_files:
        src = os.path.join(cache_dir, fn)
        dst = os.path.join(job_local, fn)
        # 複製元(共有キャッシュ)はread-only施錠済み。shutil.copy2はメタデータ
        # (パーミッションビット込み)も複製するため、そのまま使うとjob_dir側の
        # 複製先までread-only化されてしまい、次回以降の上書きコピーが
        # PermissionErrorで失敗する(実測で発覚)。copyfile(中身のみ)を使い、
        # 複製先は明示的に書き込み可能にする。
        if os.path.exists(dst):
            try:
                os.chmod(dst, stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                pass
        shutil.copyfile(src, dst)
        try:
            os.chmod(dst, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass
    print(f"[{TAG}] also copying shared cache into job_dir (for step02/preflight): "
          f"{cache_dir} -> {job_local} ({len(cache_files)} file(s))")


def ensure_job_local_copy(job):
    """共有キャッシュ(ライブ抽出モードのみ)の中身をjob_dir配下へも複製する。

    convert_noue.ensure_vanilla()の is_cache_fresh ショートサーキット
    (共有キャッシュが既に新鮮なため extract_vanilla.py のサブプロセス自体を
    一切起動しない経路)専用の公開エントリ。サブプロセス経由でmain()が
    実際に走る経路は、main()内部で必ず_sync_job_local_copyまで完了させる
    ため、ここを呼ぶ必要はない(呼んでも冪等なので害はない)。
    override/開発機フォールバックのときは何もしない(元からjob_dir直下)。"""
    vanilla_dir = resolve_vanilla_dir(job)
    if vanilla_dir == _job_local_vanilla_dir(job):
        return
    _sync_job_local_copy(job, vanilla_dir, build_fingerprint(job))


def parse_args(argv):
    """<job.json> [--stage blender|full]。--stage省略時はfull(従来と同じ)。"""
    stage = STAGE_FULL
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--stage":
            if i + 1 >= len(argv):
                core.die(TAG, "--stage requires a value (blender|full)")
            stage = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    if len(rest) != 1 or stage not in STAGES:
        core.die(TAG, "usage: python extract_vanilla.py <job.json> "
                      "[--stage blender|full]")
    return rest[0], stage


def _extract_body(job, vanilla_dir, stage, have):
    """実際の抽出処理(共有/job_dir直下どちらのvanilla_dirでも同じ)。
    呼び出し側(main)が共有キャッシュの場合はロック保持+read-only解除/再施錠
    を担当し、ここは中身の生成だけに専念する。"""
    if have == STAGE_BLENDER:
        # refskel/common_bonesは同じpakから作られた既存物。重い側だけ作り直す
        print(f"[{TAG}] reusing existing refskel/common_bones (pak unchanged). "
              f"building only the pak index side")
    else:
        _clear_stamp(vanilla_dir)  # 上書き前に無効化(中断時に誤認させない)
        extract_blender_stage(job, vanilla_dir)
        if stage == STAGE_BLENDER:
            _write_stamp(vanilla_dir, job, STAGE_BLENDER)
            print(f"[{TAG}] done (stage=blender, pak index side not run)")
            return

    # full段。version.txtは「full完了」の宣言なので、作り直す前に必ず消す
    # (途中で落ちたときに古い版数が残って「完了済み」に見えるのを防ぐ)。
    # スタンプはblender段として書き直しておく: ここまでの出力は今のpakから
    # 作られた正しいものなので、途中で落ちても次回はfull段からやり直せばよい
    try:
        os.remove(os.path.join(vanilla_dir, "version.txt"))
    except OSError:
        pass
    _write_stamp(vanilla_dir, job, STAGE_BLENDER)
    extract_full_stage(job, vanilla_dir)
    with open(os.path.join(vanilla_dir, "version.txt"), "w") as f:
        f.write(VANILLA_VERSION)
    # dev#91: full段が実際に揃った直後(まだ呼び出し側がロックを再施錠する前)に
    # マニフェストを書く。ここで書けば共有キャッシュ経路でも通常のunlock/relockの
    # 外側に追加処理を作らずに済む
    write_manifest(vanilla_dir)
    _write_stamp(vanilla_dir, job, STAGE_FULL)
    print(f"[{TAG}] done (version {VANILLA_VERSION})")


def run(job, stage):
    """job dict(core.load_job済み、または--warm-cache用の最小dict)とstageから
    実際の抽出/共有キャッシュ処理を行う。main()(サブプロセスCLI)と
    convert_noue.py --warm-cache(同一プロセス内の直接呼び出し)の共通経路。"""
    vanilla_dir = resolve_vanilla_dir(job)
    shared = (vanilla_dir != _job_local_vanilla_dir(job))

    have = cached_stage(job, vanilla_dir)
    if have == STAGE_FULL or have == stage:
        print(f"[{TAG}] reusing existing extraction (neither Palworld's pak nor the "
              f"extractor changed): stage={have} -> {vanilla_dir}")
        # dev#91: 本機能導入前に作られたキャッシュ/job_dirにはmanifestが無いので、
        # full段の出力が揃っているなら再抽出せず後追いで作る(後方互換)
        if have == STAGE_FULL:
            ensure_manifest(vanilla_dir, shared)
        if shared:
            _sync_job_local_copy(job, vanilla_dir, build_fingerprint(job))
        return

    if not shared:
        # 従来どおり(override/開発機フォールバック): job_dir直下、ロック不要
        os.makedirs(vanilla_dir, exist_ok=True)
        _extract_body(job, vanilla_dir, stage, have)
        return

    # 共有キャッシュ: クロスプロセスロックを取ってから構築する
    # (GUIのwarmと変換の同時実行、relgate並列複数検体の同時実行への対処)
    lock = core.acquire_cache_lock(vanilla_dir)
    try:
        have = cached_stage(job, vanilla_dir)  # ロック待ち中に他プロセスが完成させた可能性
        if have == STAGE_FULL or have == stage:
            print(f"[{TAG}] reusing existing extraction (another process finished it "
                  f"while waiting for the lock): stage={have} -> {vanilla_dir}")
            if have == STAGE_FULL:
                ensure_manifest(vanilla_dir, shared)
        else:
            os.makedirs(vanilla_dir, exist_ok=True)
            core.unlock_cache_dir_for_write(vanilla_dir)  # 既存分があれば書込可能に戻す
            _extract_body(job, vanilla_dir, stage, have)
            core.lock_cache_dir_readonly(vanilla_dir)  # 完成 -> 施錠
        _sync_job_local_copy(job, vanilla_dir, build_fingerprint(job))
    finally:
        core.release_cache_lock(lock)


def main():
    job_json, stage = parse_args(sys.argv[1:])
    job = core.load_job(job_json)
    run(job, stage)


if __name__ == "__main__":
    main()
