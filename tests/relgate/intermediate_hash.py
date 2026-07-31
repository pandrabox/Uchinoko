# -*- coding: utf-8 -*-
r"""relgate中間ハッシュスキップの土台(WP-C、dev issue #27)。

目的: relgateの3検体フル変換(約6分)のうち、入力形式差が効くPhase 0-1
(バニラ準備+Blender工程)だけを実行し、「正規化後中間生成物」のハッシュが
前回リリース時の記録と一致する検体は noue工程(Phase 2-6、全体の9割超)を
省略して前回リリース結果を継承する。決定性の根拠はWP-B3
(commit 844abb8: `blender -t 1` で `dump_avatar_mesh.py` の出力がバイト完全
一致)と層0実測(pak本体のSHA256が2回焼きで完全一致)。

## なぜ .blend を直接ハッシュしないか

.blend/.gz/ログ/プレビュー画像は構造的にバイト非決定(WP1実測、
devtools\relgate.py 冒頭コメント)。そこで「noue工程が実際に消費する形」への
正規化ダンプ = `pipeline\py\dump_avatar_mesh.py`(noue本体がPhase 2で使うのと
同じスクリプト。`-t 1` でタンジェント計算まで決定的)を
converted\step02_{female,male}.blend に適用し、そのJSON(作業フォルダ依存の
絶対パスを含む "source_blend" キーのみ除去)をハッシュする。

## ダイジェストの構成要素(検体ごと)

    dump_female / dump_male : 上記の正規化メッシュダンプ(canonical JSON hash)
    avatar_meta             : converted\avatar_meta.json(canonical JSON hash)
    chibi_female/chibi_male : converted\chibi_bone_world_head_*.json(同上、無ければ absent)
    textures/<fn>           : textures\ 配下(PNGはクリティカルチャンクのみの
                              ハッシュ=エンコーダのメタデータ(パス文字列等)
                              埋め込み耐性。WP1「IDATはメタデータを除けば決定的」)
    job_settings            : job.json から "paths" を除いた設定
                              (unlit/shadow_lift/force_two_sided等、下流にも
                              効く設定の変化を捕捉)

## 下流フィンガープリント(全検体共通)

「中間が同一なら下流も同一」が成り立つのは下流のコード・環境が同一のとき
だけ。pipeline\ 配下のファイル(後述の除外を除く)+検査側モジュール+
Blender実体+Palworld pakの同一性を1つのハッシュに畳む。除外するのは
**効果が中間ダイジェストで検体ごとに完全に捕捉される上流専用ファイル**
(step01_import_vrm.py / step02_retarget.py / export_from_unity.ps1)のみ。
判断に迷うものは含める(漏れの倒れる向き: 含めすぎ=余計にフル実行が走る
だけで正しい / 除外しすぎ=誤スキップ。convert.ps1のStep01IgnoredKeysと
同じブラックリスト思想)。
dev#114(2026-07-29): UEクックパイプライン(pipeline\ue\ / pipeline\templates\
ue_project\)自体を削除したため、旧UEモード専用の除外エントリは撤去した
(除外対象のディレクトリがそもそも存在しなくなったため)。

## 記録とpakキャッシュ

    devtools\relgate_skip_record.json  … リポジトリ管理。更新は
        relgate.py --promote-skip-record 経由のみで、対象runの3検体pak SHA256が
        .devonly\publish\releases.json の最新エントリ pak_hashes と全一致する
        場合しか書かない(=「リリース成功時のみ更新」の構造的ゲート)。
    work\_relgate_pak_cache\<sha256>.pak … マシンローカル(work\はgitignore)。
        スキップ時にここから新しい作業フォルダへ実体化し、sha256を再検証して
        から使う(release.py の compute_avatar_paks / --pak none 判定が
        無改修で成立する)。キャッシュが無ければスキップ不成立=フル実行
        (安全側へ倒れる)。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zlib

HERE_DIR = os.path.dirname(os.path.abspath(__file__))            # tests\relgate
REPO_DIR = os.path.dirname(os.path.dirname(HERE_DIR))
PIPELINE_DIR = os.path.join(REPO_DIR, "pipeline")
DUMP_SCRIPT = os.path.join(PIPELINE_DIR, "py", "dump_avatar_mesh.py")
# 検証官F4(2026-07-28): スロット単位のマテリアル割り当てダンプ(同ディレクトリ)
SLOT_DUMP_SCRIPT = os.path.join(HERE_DIR, "dump_slot_assignments.py")

DEFAULT_RECORD_PATH = os.path.join(REPO_DIR, "devtools", "relgate_skip_record.json")
DEFAULT_PAK_CACHE_DIR = os.path.join(REPO_DIR, "work", "_relgate_pak_cache")
RELEASES_JSON_PATH = os.path.join(REPO_DIR, ".devonly", "publish", "releases.json")

# 2: 検証官F1/F4対応(2026-07-28)。inheritが実測結果になり、ダイジェストに
#    slots_*/preview_*が加わった。schema=1の記録(inherit PASS決め打ち世代)は
#    load_record()が読まない=スキップ不可へ倒れる
SCHEMA = 2

# dump_avatar_mesh.py の max_influences。build_pak_from_avatar.py の既定値と
# 揃える必要は無い(ハッシュ用に固定の条件で毎回同じダンプが取れればよい)が、
# 本番と同じ8にしておく(ダンプ内容=noueが実際に消費する形に一致させる)。
DUMP_MAX_INFLUENCES = "8"

# 下流フィンガープリントから除外するもの(リポジトリルートからの相対、/区切り)。
# 除外してよい根拠を必ず書くこと(迷ったら含める=安全側)。
FP_EXCLUDE_EXACT = {
    # 上流(Phase 0-1)専用。変更の影響は中間ダイジェストが検体ごとに捕捉する。
    # これを除外することで「FBX入口だけ直した→VRM検体はスキップのまま」の
    # 検体粒度スキップが成立する(dev issue #27 の設計の眼目)。
    #
    # 除外根拠の再確立(検証官F4への回答、2026-07-28): 「捕捉できている」と
    # 言えるのは、下流がblend/converted成果物から実際に**消費する情報**を
    # ダイジェストが網羅している場合に限る。下流の消費は
    #   ① dump_avatar_mesh.py: 頂点/法線/接線/UV/ウェイト/三角形+クラス
    #      → comp["dump_*"](WP-B3条件でバイト決定的)
    #   ② vp_atlas_uvbake.py: poly.material_index+スロット名(スロット単位)
    #      → comp["slots_*"](F4で追加。クラス単位ダンプの盲点=
    #        「面のスロット入れ替えはダイジェスト不変・pak可変」を封鎖)
    #   ③ resolve_textures/build_pak: avatar_meta.json / textures\ / chibi
    #      → comp["avatar_meta"/"textures/*"/"chibi_*"]
    #   ④ 層2の比較対象(preview_*_stand.png)の見た目: マテリアルノード設定・
    #      blend_method等はダンプに現れないが描画に効く
    #      → comp["preview_*"](F4で追加。実測画素で捕捉)
    # の4系統で、いずれもダイジェストの構成要素にある。将来step01/02が
    # 「上記のどれにも現れない・かつ下流に効く」出力を持つ場合は、この除外を
    # 外すか、ダイジェストへ対応コンポーネントを足すこと。
    "pipeline/blender/step01_import_vrm.py",
    "pipeline/blender/step02_retarget.py",
    # Unity輸出(FBX入力ファイルを作る工程)。入力FBX自体の変化はstep01出力
    # (=中間ダイジェスト)に現れる。
    "pipeline/cli/export_from_unity.ps1",
    # ドキュメント用サンプル。実行時には読まれない。
    "pipeline/job.example.json",
}
# dev#114(2026-07-29): 旧UEモード専用(pipeline/ue/, pipeline/templates/)の
# 除外エントリはUEクックパイプライン自体の削除に伴い撤去した。現時点で
# プレフィックス除外の必要はないが、将来また出てきたときのためにこの機構
# (FP_EXCLUDE_EXACTとの2段構え)自体は残す。
FP_EXCLUDE_PREFIX = ()
# 検査・判定側のモジュール(閾値やbaseline比較ロジックの変更で「継承したPASS」が
# 古くなるのを防ぐため、下流フィンガープリントに含める)
FP_EXTRA_FILES = (
    "devtools/relgate.py",
    "devtools/pak_manifest.py",
    "devtools/atlas_compare.py",
    "tests/relgate/visual_check.py",
    "tests/relgate/log_diagnostic_contract.py",
    "tests/relgate/intermediate_hash.py",   # 自分自身(ダイジェスト定義の変更=全フル)
)
# convert.ps1 が参照するPalworld pakの既定パス(vp_core.DEFAULT_PALWORLD_PAKと同値)
DEFAULT_PALWORLD_PAK = (r"C:\Program Files (x86)\Steam\steamapps\common\Palworld"
                        r"\Pal\Content\Paks\Pal-Windows.pak")

PNG_SIG = b"\x89PNG\r\n\x1a\n"
# 画素・表示に効くチャンクだけを残す(tEXt/zTXt/tIME等のメタデータは
# エンコーダがパス文字列や日時を埋め込みうるため除外)
PNG_KEEP_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"tRNS", b"gAMA", b"sRGB", b"IEND"}


class DigestError(RuntimeError):
    """中間ダイジェストが計算できない(ファイル欠如・ダンプ失敗等)。
    呼び出し側はフル実行へフォールバックすること(fail-safe方向)。"""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_hash(obj):
    """JSONの意味内容だけをハッシュする(キー順・空白・インデント非依存)。"""
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(s.encode("utf-8"))


def canonical_json_file_hash(path):
    with open(path, encoding="utf-8") as f:
        return canonical_json_hash(json.load(f))


def png_pixel_hash(path):
    """PNGのクリティカル(+色表示に効く)チャンクだけをハッシュする。
    PNGでない/壊れている場合は生バイトハッシュへフォールバック
    (接頭辞で区別し、種別が変わったこと自体も差分として検出される)。"""
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(PNG_SIG):
        return "raw:" + sha256_bytes(data)
    h = hashlib.sha256()
    pos = len(PNG_SIG)
    try:
        while pos + 8 <= len(data):
            ln = int.from_bytes(data[pos:pos + 4], "big")
            typ = data[pos + 4:pos + 8]
            chunk = data[pos + 8:pos + 8 + ln]
            if len(chunk) != ln:
                return "raw:" + sha256_bytes(data)   # 途中で切れている
            if typ in PNG_KEEP_CHUNKS:
                h.update(typ)
                h.update(chunk)
            pos += 12 + ln  # length(4) + type(4) + data + crc(4)
            if typ == b"IEND":
                break
    except Exception:
        return "raw:" + sha256_bytes(data)
    return "png:" + h.hexdigest()


def _run_blender_dump(blender_exe, script, script_args, out_json, log_path, label):
    """WP-B3の決定化条件(-t 1)でBlender headlessスクリプトを実行する。"""
    cmd = [blender_exe, "--background", "-t", "1",
           "--python-exit-code", "1", "--python", script,
           "--"] + list(script_args)
    with open(log_path, "w", encoding="utf-8") as lf:
        r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0 or not os.path.isfile(out_json):
        raise DigestError(f"{label}失敗 (exit={r.returncode}, log={log_path})")


def _run_mesh_dump(blender_exe, blend_path, gender, out_json, log_path):
    """build_pak_from_avatar.py main()のPhase 1と同じ引数構成のメッシュダンプ。"""
    _run_blender_dump(blender_exe, DUMP_SCRIPT,
                      [blend_path, gender, out_json, DUMP_MAX_INFLUENCES],
                      out_json, log_path, f"mesh dump({gender})")


def compute_intermediate_hash(job_dir, blender_exe):
    """job_dir(Phase 0-1実行済み)の正規化後中間生成物ダイジェストを計算する。
    戻り値: {"combined": <sha256hex>, "components": {name: hash, ...}}
    計算不能なら DigestError(呼び出し側はフル実行へ倒す)。"""
    conv = os.path.join(job_dir, "converted")
    comp = {}

    # --- job設定(pathsを除く。下流にも効く設定の変化を捕捉) ---
    job_json = os.path.join(job_dir, "job.json")
    if not os.path.isfile(job_json):
        raise DigestError(f"job.jsonが無い: {job_json}")
    with open(job_json, encoding="utf-8") as f:
        job_cfg = json.load(f)
    job_cfg.pop("paths", None)
    comp["job_settings"] = canonical_json_hash(job_cfg)

    # --- avatar_meta / chibi(正規化JSONハッシュ) ---
    meta_path = os.path.join(conv, "avatar_meta.json")
    if not os.path.isfile(meta_path):
        raise DigestError(f"avatar_meta.jsonが無い(step01未完了?): {meta_path}")
    comp["avatar_meta"] = canonical_json_file_hash(meta_path)
    for gender in ("female", "male"):
        p = os.path.join(conv, f"chibi_bone_world_head_{gender}.json")
        comp[f"chibi_{gender}"] = canonical_json_file_hash(p) if os.path.isfile(p) else "absent"

    # --- 正規化メッシュダンプ(WP-B3条件、source_blendキーのみ除去)
    #     +スロット割り当てダンプ(検証官F4: メッシュダンプの三角形は
    #     body/parkaクラスしか持たず、面のスロット入れ替えが盲点だった。
    #     vp_atlas_uvbake.pyが実際に読むpoly.material_index+スロット名を
    #     別ダンプで捕捉する。dump_slot_assignments.py参照) ---
    digest_dir = os.path.join(job_dir, "build", "relgate_digest")
    os.makedirs(digest_dir, exist_ok=True)
    for gender in ("Female", "Male"):
        blend = os.path.join(conv, f"step02_{gender.lower()}.blend")
        if not os.path.isfile(blend):
            raise DigestError(f"step02_{gender.lower()}.blendが無い(Phase 1未完了?): {blend}")
        out_json = os.path.join(digest_dir, f"dump_{gender.lower()}.json")
        log_path = os.path.join(digest_dir, f"dump_{gender.lower()}.log")
        _run_mesh_dump(blender_exe, blend, gender, out_json, log_path)
        with open(out_json, encoding="utf-8") as f:
            dump = json.load(f)
        dump.pop("source_blend", None)   # 作業フォルダ依存の絶対パス
        comp[f"dump_{gender.lower()}"] = canonical_json_hash(dump)
        slots_json = os.path.join(digest_dir, f"slots_{gender.lower()}.json")
        slots_log = os.path.join(digest_dir, f"slots_{gender.lower()}.log")
        _run_blender_dump(blender_exe, SLOT_DUMP_SCRIPT, [blend, slots_json],
                          slots_json, slots_log, f"slot dump({gender})")
        comp[f"slots_{gender.lower()}"] = canonical_json_file_hash(slots_json)

    # --- プレビュー画像(画素ハッシュ。検証官F4の残余指摘への対応:
    #     blendのマテリアルノード設定・blend_method等はダンプに現れないが
    #     層2の比較対象(preview_*_stand.png)の見た目に効く。Phase 0-1が
    #     実際にレンダリングしたプレビューの画素をダイジェストへ含めることで、
    #     「見た目に効く上流変化」を実測画素で捕捉する。実測で独立2runの
    #     画素バイト一致を確認済み(2026-07-28)。もし環境要因で画素が揺れる
    #     場合はハッシュ不一致→フル実行に倒れるだけ(誤スキップ側には
    #     倒れない)。GPU無し環境ではプレビューが無い=absent同士の比較になり、
    #     その環境内では一貫する ---
    for gender in ("female", "male"):
        p = os.path.join(conv, f"preview_{gender}_stand.png")
        comp[f"preview_{gender}"] = png_pixel_hash(p) if os.path.isfile(p) else "absent"

    # --- textures(PNGクリティカルチャンクハッシュ) ---
    tex_dir = os.path.join(job_dir, "textures")
    if os.path.isdir(tex_dir):
        for fn in sorted(os.listdir(tex_dir)):
            p = os.path.join(tex_dir, fn)
            if os.path.isfile(p):
                comp[f"textures/{fn}"] = png_pixel_hash(p)

    return {"combined": canonical_json_hash(comp), "components": comp}


def _iter_fingerprint_files():
    """下流フィンガープリント対象ファイルの(相対パス, 絶対パス)を列挙する。"""
    rels = []
    for cur, dirs, files in os.walk(PIPELINE_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            p = os.path.join(cur, fn)
            rel = os.path.relpath(p, REPO_DIR).replace("\\", "/")
            base = os.path.basename(rel)
            if base.endswith(".pyc") or ".bak" in base or base.endswith(".log"):
                continue
            if rel in FP_EXCLUDE_EXACT:
                continue
            if any(rel.startswith(pfx) for pfx in FP_EXCLUDE_PREFIX):
                continue
            rels.append((rel, p))
    for rel in FP_EXTRA_FILES:
        p = os.path.join(REPO_DIR, *rel.split("/"))
        if os.path.isfile(p):
            rels.append((rel, p))
    rels.sort(key=lambda t: t[0])
    return rels


def downstream_fingerprint(blender_exe=None, palworld_pak=None):
    """下流コード+実行環境のフィンガープリント。
    戻り値: {"combined": <sha256hex>, "num_files": N}"""
    h = hashlib.sha256()
    n = 0
    for rel, p in _iter_fingerprint_files():
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(bytes.fromhex(sha256_file(p)))
        n += 1
    # 実行環境: Blender実体(パス+サイズ)とPalworld pak(サイズ+mtime秒)。
    # extract_vanilla.pyのキャッシュ鮮度判定(mtime+size)と同じ考え方。
    # 検証官F5(2026-07-28): 判定側インタプリタのPython/numpy/zlibも含める
    # (pak_manifest/visual_checkの比較ロジックがこの環境で走るため。
    # RELGATE.mdが警告する「環境ドリフト」がスキップ経路の盲点になるのを塞ぐ)。
    # 変換側(Blender同梱python内のnumpy等)はBlender実体の同一性で近似する
    # — 同梱環境を手でpip改変した場合は検出できない既知の限界(RELGATE.md参照)。
    env_parts = [f"python:{sys.version}"]
    try:
        import numpy
        env_parts.append(f"numpy:{numpy.__version__}")
    except Exception:
        env_parts.append("numpy:absent")
    env_parts.append(f"zlib:{getattr(zlib, 'ZLIB_RUNTIME_VERSION', zlib.ZLIB_VERSION)}")
    if blender_exe and os.path.isfile(blender_exe):
        env_parts.append(f"blender:{os.path.abspath(blender_exe)}:{os.path.getsize(blender_exe)}")
    else:
        env_parts.append(f"blender:absent:{blender_exe}")
    pak = palworld_pak or DEFAULT_PALWORLD_PAK
    if pak and os.path.isfile(pak):
        st = os.stat(pak)
        env_parts.append(f"palworld_pak:{st.st_size}:{int(st.st_mtime)}")
    else:
        env_parts.append("palworld_pak:absent")
    h.update("\n".join(env_parts).encode("utf-8"))
    return {"combined": h.hexdigest(), "num_files": n}


def baseline_fingerprint(baseline_dir):
    r"""検体のbaseline(manifest.json + images\*.png)のフィンガープリント。
    リリース後にbaselineだけが更新された場合、「継承したPASS」は現行baselineに
    対する保証ではなくなるため、スキップ判定の前提条件として照合する。"""
    h = hashlib.sha256()
    found = False
    manifest = os.path.join(baseline_dir, "manifest.json")
    if os.path.isfile(manifest):
        h.update(b"manifest.json\0")
        h.update(bytes.fromhex(sha256_file(manifest)))
        found = True
    images_dir = os.path.join(baseline_dir, "images")
    if os.path.isdir(images_dir):
        for fn in sorted(os.listdir(images_dir)):
            p = os.path.join(images_dir, fn)
            if os.path.isfile(p):
                h.update(("images/" + fn).encode("utf-8"))
                h.update(b"\0")
                h.update(bytes.fromhex(sha256_file(p)))
                found = True
    return h.hexdigest() if found else "absent"


# --- 記録IO ---------------------------------------------------------------

def load_record(path=DEFAULT_RECORD_PATH):
    """記録を読む。無い/壊れている/schema不一致なら None(=スキップ不可)。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    if rec.get("schema") != SCHEMA:
        return None
    return rec


def save_record(record, path=DEFAULT_RECORD_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def load_latest_release():
    """releases.jsonの最新エントリを返す(無ければNone)。"""
    if not os.path.isfile(RELEASES_JSON_PATH):
        return None
    with open(RELEASES_JSON_PATH, encoding="utf-8") as f:
        history = json.load(f)
    releases = history.get("releases") or []
    return releases[-1] if releases else None


# --- pakキャッシュ ---------------------------------------------------------

def pak_cache_path(pak_sha256, cache_dir=DEFAULT_PAK_CACHE_DIR):
    return os.path.join(cache_dir, f"{pak_sha256}.pak")


def store_pak_in_cache(pak_path, pak_sha256, cache_dir=DEFAULT_PAK_CACHE_DIR):
    """pak実体をキャッシュへ入れる(同一ボリュームならハードリンクで一瞬)。
    既にあれば何もしない。戻り値: キャッシュ内パス。"""
    os.makedirs(cache_dir, exist_ok=True)
    dst = pak_cache_path(pak_sha256, cache_dir)
    if os.path.isfile(dst):
        return dst
    tmp = dst + ".tmp"
    if os.path.isfile(tmp):
        os.remove(tmp)
    try:
        os.link(pak_path, tmp)
    except OSError:
        shutil.copyfile(pak_path, tmp)
    os.replace(tmp, dst)
    return dst


def materialize_cached_pak(pak_sha256, dest_path, cache_dir=DEFAULT_PAK_CACHE_DIR):
    """キャッシュから dest_path へ実体化し、sha256を再検証する。
    キャッシュ欠如/検証不一致なら DigestError(呼び出し側はフル実行へ)。"""
    src = pak_cache_path(pak_sha256, cache_dir)
    if not os.path.isfile(src):
        raise DigestError(f"pakキャッシュが無い: {src}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if os.path.isfile(dest_path):
        os.remove(dest_path)
    try:
        os.link(src, dest_path)
    except OSError:
        shutil.copyfile(src, dest_path)
    actual = sha256_file(dest_path)
    if actual != pak_sha256:
        try:
            os.remove(dest_path)
        finally:
            pass
        raise DigestError(f"pakキャッシュのsha256不一致(キャッシュ破損): "
                          f"expected={pak_sha256} actual={actual}")
    return dest_path
