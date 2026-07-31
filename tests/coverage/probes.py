# -*- coding: utf-8 -*-
r"""U53 カバレッジ検査: 判定ロジック本体(pytest 非依存の純関数)。

`tests\shipcheck\gates.py` と同じ設計方針(判定はここ、pytest 側は薄いラッパー)。
shipcheck の資産は **import して再利用**する(GateResult / build_or_get_cached /
gate_a〜d / static_check)。ゼロから作り直してはいない。

------------------------------------------------------------------------
■ このモジュールが存在する理由(2026-07-25 の事故)

`tests\shipcheck\cases.py` の `SETTINGS_FLIPS` は、影の濃さ等の差分が
`ModelMaterials/MainShader/` に出ることを期待していた。しかし実測では

    Player/ModelMaterials/MainShader/  … pak 内 **16 ファイルだけ**
                                        (M_VP_* 12 + t00/t01 4)
    どのスケルタルメッシュからも参照されていない M_VP_* = **死んだ経路**

であり、**実際に描画に使われる 158 ファイル(統一MI 79 パッケージ ×
uasset/uexp)が全部壊れてもゲートは通る**状態だった。

そこで本モジュールの中心は「期待するパスを人が書く」のをやめ、
**pak 自身から『生きている参照集合』を実測する**ことにある:

    衣装SK(Player/Outfit/*.uasset)の Materials[] が実際に指している
    MI パッケージパスを全件解決し(live_template.find_outfit_material_paths_all)、
    それを pak 内エントリへ写像したものを LIVE とする。

設定フリップの差分が LIVE と交わらなければ FAIL。
`ModelMaterials/MainShader/M_VP_*` だけが変わった場合は LIVE と交わらないので
**今日の事故はこのゲートで必ず落ちる**(selftest の負の対照で実証済み)。
------------------------------------------------------------------------
"""
import functools
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
SHIPCHECK_DIR = os.path.join(TESTS_DIR, "shipcheck")
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
DEVTOOLS_DIR = os.path.join(REPO_ROOT, "devtools")
UE_EXIT_DIR = os.path.join(REPO_ROOT, "research", "ue_exit")

for _p in (SHIPCHECK_DIR, PIPELINE_PY_DIR, DEVTOOLS_DIR, UE_EXIT_DIR):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import gates as shipcheck_gates  # noqa: E402  (既存スイートの再利用)

GateResult = shipcheck_gates.GateResult
_gate = shipcheck_gates._gate
sha1_file = shipcheck_gates.sha1_file

# 作業域(devtools\new_experiment.ps1 -Name u53_cov で作成済み)。
# ここより外へは一切書かない。
WORK_ROOT = os.path.join(REPO_ROOT, "work", "u53_cov")
CASES_DIR = os.path.join(WORK_ROOT, "cases")
REPORTS_DIR = os.path.join(WORK_ROOT, "reports")
# prefab の Unity 輸出物。**ケース名で分ける**(既定の work\<prefab名>_export は
# 同名 prefab 同士で衝突するうえ、既存検体 work\flatVer2_export を潰す)。
EXPORTS_DIR = os.path.join(WORK_ROOT, "exports")

# --- 変換の実行(mutex リトライつき) -----------------------------------------
# convert.ps1 の Global\DiveToPalworld_pipeline mutex は **待たずに即エラー**で
# 返る(convert.ps1:38 WaitOne(0))。無人で一晩回すには呼び出し側でリトライする
# しかない。shipcheck の _run_conversion は 15分×3回 だが、本スイートは
# 「短い間隔で長く粘る」に振る(他セッションの変換1本 ≒ 6分なので、
# 90秒×40回 = 最大1時間待てば実用上十分)。
MUTEX_BUSY_MARKER = "別の変換が実行中です"
MUTEX_RETRY_INTERVAL_SEC = 90
MUTEX_MAX_RETRIES = 40
# 1回の変換がハングしても朝までに必ず終わるようにする(無人運転の必須条件)。
CONVERT_TIMEOUT_SEC = 60 * 60

# ログファイルの試行区切り(run_convert:114-116 の書式と一致させること)。
# fix_stale_log_path が「最後の試行だけ」を切り出すのに使う。
_ATTEMPT_MARKER_RE = re.compile(r"^=== attempt \d+.*===$", re.MULTILINE)


def run_convert(job_path, log_path, engine_mode="noue", target_root=None,
                extra_args=(), timeout=CONVERT_TIMEOUT_SEC, sleep=time.sleep):
    """convert.ps1 を叩く唯一の関数。戻り値 (exit_code, log_text)。

    shipcheck.gates.build_or_get_cached の `run_conversion` 引数と互換
    (job_path, log_path, target_root=...)。extra_args で -MaterialsOnly 等を足す。
    """
    # shipcheck.gates.build_or_get_cached はログ先を work\u32_diag\ に固定で
    # 組み立てる(gates.py:215)。本スイートの書き込み先は work\u53_cov\ だけと
    # 決めているので、ここで自分の作業域へ引き取る。
    if "u32_diag" in log_path:
        log_path = os.path.join(WORK_ROOT, "convert_logs", os.path.basename(log_path))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    root = target_root or REPO_ROOT
    convert_ps1 = os.path.join(root, "pipeline", "cli", "convert.ps1")
    cmd = ["pwsh", "-NoProfile", "-File", convert_ps1, "-Job", job_path,
           "-EngineMode", engine_mode] + list(extra_args)
    text = ""
    rc = -1
    for attempt in range(1, MUTEX_MAX_RETRIES + 1):
        try:
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
            rc = proc.returncode
            text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except subprocess.TimeoutExpired as e:
            rc = 124
            text = "##TIMEOUT## convert.ps1 が {}秒で終わらなかった\n{}".format(
                timeout, (e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or ""))
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("=== attempt {} (rc={}) @{} ===\n{}\n".format(
                attempt, rc, time.strftime("%Y-%m-%d %H:%M:%S"), text))
        if MUTEX_BUSY_MARKER in text and attempt < MUTEX_MAX_RETRIES:
            sleep(MUTEX_RETRY_INTERVAL_SEC)
            continue
        return rc, text
    return rc, text


def fix_stale_log_path(res, case_name):
    r"""**黙って SKIP するテストの原因の修復**(2026-07-26 発見)。

    `tests\shipcheck\gates.py::build_or_get_cached` はログ先を常に
    `work\u32_diag\convert_logs\{avatar}_{key}.log` として固定で組み立て
    (gates.py:215-216)、その変数をそのまま `PakBuildResult.log_path` と
    キャッシュ record の両方に書き込む。ところが実際に変換を叩く
    `run_convert`(このファイル、上の関数)は「u32_diag を含む log_path」を
    渡されると、本スイートの作業域 `work\u53_cov\convert_logs\` へ書き先を
    自分で付け替えてから書き込む(95-97行)。build_or_get_cached はこの
    付け替えを知らないまま古いパスを覚え続けるため:

      * 初回実行(cache miss)は log_text が呼び出しの戻り値からそのまま
        渡るので問題は表面化しない。
      * だが記録された log_path は実在しないパスのまま cache record
        (`work\u53_cov\pak_cache\*.json`)へ書き込まれる。
      * **2回目以降、同じキャッシュにヒットした瞬間**に
        `build_or_get_cached` が存在しない log_path を読もうとして失敗し、
        `log_text = ""` になる。
      * `probes.gate_preflight` 等は `log_text` が空だと「判定不能」として
        SKIP を返し、`gate()` フィクスチャがそれを `pytest.skip` に変換する
        ため、**テストが FAIL でも PASS でもなく黙って SKIP される**。

    実測(2026-07-26): `work\u53_cov\pak_cache\` の cache record 17件
    **全件**がこの壊れた log_path を持っていた(ue_free / 全 flip_* /
    全 input_* 等)。つまりキャッシュに一度でも乗った build はすべて、
    2回目以降 log_text 依存のゲート(gate_preflight /
    gate_engine_mode_is_noue / gate_no_ue_tool_in_log など、
    test_inputs.py / test_settings.py / test_prefab.py /
    test_ue_independence.py が使うもの全部)が SKIP に落ちる状態だった。

    ここで実際の書き込み先を逆算して読み直し、`result` とキャッシュ record
    の両方をその場で修復する(自己修復。以後の同一キャッシュヒットで
    再発しない)。`tests\coverage\**` 以外は変更禁止という制約があるため、
    根本(gates.py)は直さず、この関数で吸収する。
    """
    if res.log_path and "u32_diag" in res.log_path:
        real_path = os.path.join(WORK_ROOT, "convert_logs", os.path.basename(res.log_path))
        if os.path.isfile(real_path):
            if not res.log_text:
                with open(real_path, encoding="utf-8", errors="replace") as f:
                    res.log_text = f.read()
            res.log_path = real_path
            # キャッシュ record も直す(次回以降の cache hit で再発させないため)
            try:
                key = shipcheck_gates.cache_key(res.job_dict)
                record_path = shipcheck_gates._cache_record_path(case_name, key)
                if os.path.isfile(record_path):
                    with open(record_path, encoding="utf-8") as f:
                        rec = json.load(f)
                    if rec.get("log_path") != real_path:
                        rec["log_path"] = real_path
                        with open(record_path, "w", encoding="utf-8") as f:
                            json.dump(rec, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    # --- 副次発見(2026-07-26、上の修復で初めて表面化した第2のバグ) -------------
    # run_convert はログを "a"(追記)で開く。同じキャッシュ鍵に対して
    # 日をまたいで複数回ビルドされたケース(例: input_vrm_kate。01:18 rc=1
    # 失敗 → 07:19 rc=0 成功、の2回分が同じファイルに連結されていた)では、
    # cache hit 時にファイル全体を読み直す(gates.py:189-191、変更不可)ため、
    # log_text に**過去の失敗試行の [FAIL] 行**まで含まれてしまう。
    # gate_preflight 等は log_text 全体を正規表現で舐めるだけなので、
    # 「最新の試行は G4 PASS なのに、古い試行の G4 FAIL を拾って誤FAILする」
    # という実例が実際に起きていた(input_vrm_kate で確認)。
    # ここで **最後の "=== attempt" ブロックだけ** を切り出す。
    if res.log_text:
        marks = list(_ATTEMPT_MARKER_RE.finditer(res.log_text))
        if len(marks) > 1:
            res.log_text = res.log_text[marks[-1].start():]
    return res


# --- Unity ヘッドレス輸出(prefab → FBX + humanoid.json) ----------------------
# 変換の前段。`pipeline\cli\export_from_unity.ps1` を叩くだけだが、VRM/FBX 検体と
# 違って **他人の Unity プロジェクトへ書き込みが起きる**(Assets\Editor\ への
# Exporter 複製、FBX Exporter 未導入なら manifest.json 追記)ため、
# 呼ぶかどうかの判断は conftest の `--allow-unity` に委ねる。ここは実行だけ。
#
# 所要は初回インポートを含むと十数分になりうる(Unity のパッケージ解決 + import)。
# 一晩運転で全体が溶けないよう、変換(60分)より短い既定にしてある。
UNITY_EXPORT_TIMEOUT_SEC = 30 * 60

# unity_export.log に出る実行痕(unity\DiveToPalworldExporter.cs)。
# **成果物の存在ではなくこの行で MA ベイクの実行を判定する**
# (DEV_NOTES(29)§4「実装した」と「効いている」は別)。
NDMF_BAKED_MARKER = "D2P: NDMFベイク完了"
NDMF_SKIPPED_MARKER = "D2P: NDMF未導入のためベイクをスキップ"
UNITY_EXPORT_DONE_MARKER = "D2P_EXPORT_DONE"


def run_unity_export(prefab_path, out_dir, timeout=UNITY_EXPORT_TIMEOUT_SEC):
    r"""`export_from_unity.ps1 -Prefab <p> -Out <out_dir>` を実行する。

    戻り値 `(exit_code, stdout_text, unity_log_text)`。

    **`-Out` を必ず明示する。**省略すると出力先が prefab のファイル名だけで
    決まり(`work\<name>_export`)、
      * Agyo / Jinbe の `flatVer2.prefab` 同士が衝突する
      * さらに既存検体 `work\flatVer2_export`(fbx_flat_ma の実体)を上書きする
    という二重事故になる。検査が検体を壊すのは論外なので、
    本スイートはケースごとに独立した out_dir を渡す
    (その衝突自体は test_prefab.py::test_prefab_name_collision が別途 static に見る)。
    """
    os.makedirs(out_dir, exist_ok=True)
    script = os.path.join(REPO_ROOT, "pipeline", "cli", "export_from_unity.ps1")
    cmd = ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
           "-Prefab", prefab_path, "-Out", out_dir]
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        rc, text = proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        rc = 124
        text = "##TIMEOUT## export_from_unity.ps1 が {}秒で終わらなかった\n{}".format(
            timeout, e.stdout if isinstance(e.stdout, str) else "")
    unity_log = ""
    log_path = os.path.join(out_dir, "unity_export.log")
    if os.path.isfile(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as f:
            unity_log = f.read()
    return rc, text, unity_log


def gate_unity_export(name, rc, stdout_text, unity_log, out_dir):
    """prefab → FBX + humanoid.json の輸出が成立したこと。

    exit code だけでは足りない(ps1 は失敗時も出力を残しうる)ので、
    **成果物3点が揃っていること**まで要求する。
    """
    fbx = [f for f in os.listdir(out_dir) if f.lower().endswith(".fbx")] \
        if os.path.isdir(out_dir) else []
    humanoid = os.path.join(out_dir, "humanoid.json")
    matmap = os.path.join(out_dir, "material_map.json")
    missing = []
    if not fbx:
        missing.append("FBX")
    if not os.path.isfile(humanoid):
        missing.append("humanoid.json")
    if not os.path.isfile(matmap):
        missing.append("material_map.json")
    detail = {
        "exit_code": rc, "out_dir": out_dir, "fbx": fbx, "missing": missing,
        "export_done_marker": UNITY_EXPORT_DONE_MARKER in unity_log,
    }
    if rc != 0 or missing:
        # Unity が開かれている等、環境都合の失敗は判定不能として切り分ける
        # (FAIL にすると「壊れている」と読めてしまう)。
        env_reasons = ("このプロジェクトはUnityで開かれています",
                       "プロジェクトに合うUnity", "Unityプロジェクトが特定できない")
        hit = [r for r in env_reasons if r in stdout_text]
        if hit:
            detail["note"] = "環境都合で輸出できない: {}".format(hit[0])
            detail["stdout_tail"] = stdout_text[-1500:]
            return _gate("SKIP", name, **detail)
        detail["stdout_tail"] = stdout_text[-3000:]
        detail["unity_log_tail"] = unity_log[-3000:]
        return _gate("FAIL", name, **detail)
    return _gate("PASS", name, **detail)


def gate_ma_bake_executed(name, unity_log, expected=True):
    """**MA(NDMF)ベイクが実際に走ったか**を輸出ログの実行痕で判定する。

    `DiveToPalworldExporter.BakeNdmf` は NDMF が見つからないと例外を投げず
    `D2P: NDMF未導入のためベイクをスキップ` と書いて**素通りする**。
    つまり「輸出が成功した」だけでは MA が効いた証拠にならない
    ——これが DEV_NOTES(29)§4 の構図そのもの。
    """
    baked = NDMF_BAKED_MARKER in unity_log
    skipped = NDMF_SKIPPED_MARKER in unity_log
    detail = {"baked": baked, "skipped": skipped, "expected_bake": expected}
    if not unity_log:
        detail["note"] = "unity_export.log が無い(輸出自体が走っていない)"
        return _gate("SKIP", name, **detail)
    if not baked and not skipped:
        detail["note"] = ("ベイクの実行痕も未導入の痕跡も無い。Exporter の"
                          "ログ文言が変わった可能性(probes の目印を更新すること)")
        return _gate("FAIL", name, **detail)
    return _gate("PASS" if baked == bool(expected) else "FAIL", name, **detail)


def materials_only_runner():
    """`-MaterialsOnly`(影のみ更新)経路の runner。build_or_get_cached へ渡す。"""
    return functools.partial(run_convert, extra_args=("-MaterialsOnly",))


# --- pak の読み取り ----------------------------------------------------------

def _read_entry_bytes(f, e):
    f.seek(e["data_offset"])
    return f.read(e["csize"] if e["compression"] != 0 else e["size"])


def pak_entries(pak_path):
    import vp_core
    _mount, entries = vp_core.read_pak_entries(pak_path)
    return entries


_HASH_CACHE = {}


def _pak_identity(pak_path):
    """パス+mtime+サイズ。**中身が差し替わればキャッシュは自動で外れる。**
    (2026-07-25 の取り違え事故は『同じパスの別物を掴む』形で起きた)"""
    return (os.path.abspath(pak_path), os.path.getmtime(pak_path),
            os.path.getsize(pak_path))


def pak_entry_hashes(pak_path, use_cache=True):
    """pak 内エントリ単位の sha1。shipcheck.gates._pak_entry_hashes と同等
    (あちらは private なので同じ読み方をここで持つ)。"""
    key = _pak_identity(pak_path)
    if use_cache and key in _HASH_CACHE:
        return _HASH_CACHE[key]
    entries = pak_entries(pak_path)
    out = {}
    with open(pak_path, "rb") as f:
        for rel, e in entries.items():
            out[rel] = hashlib.sha1(_read_entry_bytes(f, e)).hexdigest()
    if use_cache:
        _HASH_CACHE[key] = out
    return out


def game_path_to_pak_rels(game_path, mount_suffix="Player/"):
    """`/Game/Pal/Model/Character/Player/Outfit/X/v01/MI_Y` → pak 内相対パス2件。

    本パイプラインの pak のマウントは
    `../../../Pal/Content/Pal/Model/Character/` 固定(実測)なので、
    `Player/` 以降がそのまま pak 内相対パスになる。
    """
    idx = game_path.find("/" + mount_suffix.rstrip("/") + "/")
    if idx < 0:
        return []
    rel = game_path[idx + 1:]
    return [rel + ".uasset", rel + ".uexp"]


_LIVE_CACHE = {}


def live_reference_sets(pak_path, use_cache=True):
    r"""**pak 自身から**「生きている参照集合」を実測する(本モジュールの心臓部)。

    返り値 dict:
      mesh_entries      … 注入対象の衣装/頭/髪 SK 本体のエントリ(除外SKを含まない)
      material_entries  … 上記 SK の描画スロットが実際に参照している MI のエントリ
      excluded_entries  … コラボ除外SK 本体のエントリ
      excluded_only_material_entries
                        … **除外SKだけが参照している** MI のエントリ
                           (= 触られていないことを確認すべき対象)
      dead_entries      … pak にあるが上のどれからも参照されていないマテリアル資産
                           (M_VP_* がここに落ちる。今日の事故の現場)
      n_sk / n_excluded_sk / skipped

    解決には `live_template.find_outfit_material_paths_all`(パイプライン本体の
    関数)をそのまま使う。テスト側で uasset を独自パースし直すと、
    パイプラインが実際に見ているものとズレて「テストだけ正しい」になる。
    """
    key = _pak_identity(pak_path)
    if use_cache and key in _LIVE_CACHE:
        return _LIVE_CACHE[key]

    import live_template as lt
    import vp_exclusions

    entries = pak_entries(pak_path)
    sk_rels = sorted(
        r for r in entries
        if r.endswith(".uasset")
        and (r.startswith("Player/Outfit/") or r.startswith("Player/Head/")
             or r.startswith("Player/Hair/") or r.startswith("Player/HeadEquip/"))
        and "/MI_" not in r
    )

    mesh_entries, excluded_entries = set(), set()
    live_mi_paths, excluded_mi_paths = set(), set()
    skipped = []
    n_sk = n_excluded = 0

    tmpd = tempfile.mkdtemp(prefix="u53live_")
    ua_tmp = os.path.join(tmpd, "x.uasset")
    ue_tmp = os.path.join(tmpd, "x.uexp")
    try:
        with open(pak_path, "rb") as f:
            for rel in sk_rels:
                uexp_rel = rel[:-len(".uasset")] + ".uexp"
                if uexp_rel not in entries:
                    skipped.append((rel, "uexp が無い"))
                    continue
                excluded = vp_exclusions.is_excluded(rel)
                if excluded:
                    n_excluded += 1
                    excluded_entries.update((rel, uexp_rel))
                else:
                    n_sk += 1
                    mesh_entries.update((rel, uexp_rel))
                with open(ua_tmp, "wb") as g:
                    g.write(_read_entry_bytes(f, entries[rel]))
                with open(ue_tmp, "wb") as g:
                    g.write(_read_entry_bytes(f, entries[uexp_rel]))
                try:
                    paths = lt.find_outfit_material_paths_all(ua_tmp, ue_tmp, limit=2)
                except Exception as ex:  # SK 以外/形が違うものはここに落ちる
                    skipped.append((rel, repr(ex)[:120]))
                    continue
                (excluded_mi_paths if excluded else live_mi_paths).update(paths)
    finally:
        for p in (ua_tmp, ue_tmp):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpd)
        except OSError:
            pass

    def _to_entries(paths):
        s = set()
        for p in paths:
            for rel in game_path_to_pak_rels(p):
                if rel in entries:
                    s.add(rel)
        return s

    material_entries = _to_entries(live_mi_paths)
    excluded_only_packages = excluded_mi_paths - live_mi_paths
    excluded_only = _to_entries(excluded_only_packages)

    referenced = mesh_entries | material_entries | excluded_entries | excluded_only
    dead_entries = {
        r for r in entries
        if r not in referenced
        and (r.startswith("Player/ModelMaterials/") or "/MI_" in r)
    }

    result = {
        "mesh_entries": mesh_entries,
        "material_entries": material_entries,
        "excluded_entries": excluded_entries,
        "excluded_only_material_entries": excluded_only,
        # pak に載っているかどうかに関係なく、除外SKだけが参照する MI パッケージ。
        # 実測(2026-07-26): 6件あるが **1件も pak に収録されていない**
        # = 「バニラの装備がそのまま出る」が実際に成立している証拠。
        "excluded_only_material_packages": excluded_only_packages,
        "dead_entries": dead_entries,
        "n_sk": n_sk,
        "n_excluded_sk": n_excluded,
        "n_live_mi_paths": len(live_mi_paths),
        "skipped": skipped,
        "n_entries": len(entries),
    }
    if use_cache:
        _LIVE_CACHE[key] = result
    return result


# --- ゲート: 設定フリップが「生きている資産」を動かしたか ------------------------

DIFF_KINDS = ("material", "mesh", "any")


def gate_live_diff(name, baseline_pak, flip_pak, kind="material",
                   hasher=pak_entry_hashes, live_fn=live_reference_sets,
                   min_live_hits=1):
    r"""設定フリップの差分が **実際に描画へ使われるエントリ** に届いたかを見る。

    kind:
      "material" … 統一MI(SKが参照している MI)に差分が出ること
      "mesh"     … 衣装/頭/髪の SK 本体に差分が出ること
      "any"      … どちらかに出ること

    FAIL になる代表例(いずれも 2026-07-25 に実際に起きたもの):
      * 差分ゼロ                     → 設定が配線されていない
      * 差分が M_VP_* だけ           → 死んだ経路しか動いていない(dead_only=True)
      * 差分が除外SK固有のMIに出た   → コラボ除外が効いていない(別ゲートで判定)
    """
    base = hasher(baseline_pak)
    flip = hasher(flip_pak)
    all_paths = set(base) | set(flip)
    diff = {p for p in all_paths if base.get(p) != flip.get(p)}

    live = live_fn(baseline_pak)
    targets = {
        "material": live["material_entries"],
        "mesh": live["mesh_entries"],
        "any": live["material_entries"] | live["mesh_entries"],
    }[kind]

    hits = diff & targets
    dead_hits = diff & live["dead_entries"]
    detail = {
        "kind": kind,
        "n_diff": len(diff),
        "n_live_targets": len(targets),
        "n_live_hits": len(hits),
        "n_dead_hits": len(dead_hits),
        "dead_only": bool(diff) and not hits and bool(dead_hits),
        "diff_sample": sorted(diff)[:10],
        "live_hit_sample": sorted(hits)[:10],
        "dead_hit_sample": sorted(dead_hits)[:10],
    }
    if not diff:
        detail["note"] = "差分ゼロ。この設定は出力に一切届いていない"
        return _gate("FAIL", name, **detail)
    if not targets:
        detail["note"] = "生きた参照集合を取得できなかった(判定不能)"
        return _gate("SKIP", name, **detail)
    if len(hits) < min_live_hits:
        detail["note"] = ("差分はあるが、実際に描画へ使われるエントリに1件も届いていない"
                          "(死んだ経路だけが動いている)")
        return _gate("FAIL", name, **detail)
    return _gate("PASS", name, **detail)


def gate_no_diff(name, pak_a, pak_b, scope_entries=None, hasher=pak_entry_hashes):
    """2つの pak が(指定範囲で)一致することを要求する。

    「触ってはいけないものが触られていない」側の検査。scope_entries=None なら全体。
    """
    a = hasher(pak_a)
    b = hasher(pak_b)
    paths = set(a) | set(b)
    if scope_entries is not None:
        paths &= set(scope_entries)
    diff = sorted(p for p in paths if a.get(p) != b.get(p))
    detail = {"n_scope": len(paths), "n_diff": len(diff), "diff_sample": diff[:10]}
    if scope_entries is not None and not paths:
        detail["note"] = "対象範囲が空。判定不能"
        return _gate("SKIP", name, **detail)
    return _gate("PASS" if not diff else "FAIL", name, **detail)


def gate_exclusions_untouched(name, baseline_pak, flip_pak,
                              hasher=pak_entry_hashes, live_fn=live_reference_sets):
    r"""コラボ除外SK **固有の** MI が、MOD 側で一切いじられていないこと。

    除外の約束(`vp_exclusions` の docstring)は
    「メッシュ注入もMI差し替えもしない → **バニラの装備がそのまま出る**」。
    合格の形は2つあり、どちらでも約束は守られている:

      (a) **pak に収録されていない** … MOD が触っていない = ゲームのバニラ側が
          そのまま使われる。**これが本来あるべき姿**
          (2026-07-26 実測: 除外SK固有の MI は 6パッケージあり、
           **1件も pak に入っていなかった**)
      (b) pak には入っているが、設定フリップで**1バイトも変わらない**

    FAIL になるのは (b) で差分が出た場合 = 除外したはずの装備のマテリアルを
    MOD が書き換えている、という約束違反。

    判定不能(SKIP)は「除外SK自体が1体も pak に無い」ときだけ。
    """
    live = live_fn(baseline_pak)
    packages = live.get("excluded_only_material_packages") or set()
    in_pak = live["excluded_only_material_entries"]
    detail = {
        "n_excluded_sk": live["n_excluded_sk"],
        "n_excluded_only_mi_packages": len(packages),
        "n_excluded_only_mi_in_pak": len(in_pak),
        "package_sample": sorted(packages)[:6],
    }

    if not live["n_excluded_sk"]:
        detail["note"] = ("この pak に除外(コラボ)SK が1体も無く、除外が効いているか"
                          "判定できない")
        return _gate("SKIP", name, **detail)

    if not packages:
        # 除外SKの参照MIが全部「非除外SKとの共有」だった場合。共有MIは統一の
        # 対象になるので、この観点では除外の是非を判定できない(黙って PASS にしない)。
        detail["note"] = ("除外SKだけが参照する MI が1件も無い(すべて非対象SKと共有)。"
                          "この観点では除外の効きを判定できない")
        return _gate("SKIP", name, **detail)

    if not in_pak:
        detail["note"] = ("除外SK固有の MI は1件も pak に収録されていない"
                          "= MOD が触っていない(バニラの装備がそのまま出る)")
        return _gate("PASS", name, **detail)

    res = gate_no_diff(name, baseline_pak, flip_pak, scope_entries=in_pak, hasher=hasher)
    res.detail.update(detail)
    res.detail["scope_sample"] = sorted(in_pak)[:10]
    if res.status == "FAIL":
        res.detail["note"] = ("除外したはずの装備の MI が設定フリップで書き換わっている"
                              "(コラボ除外が効いていない)")
    return res


# --- ゲート: preflight(shipcheck の gate C は古くなっている) --------------------
#
# `shipcheck_gates.gate_c_preflight_from_log` は **ゲート数がちょうど 9 件**である
# ことを要求する(`ok = total == 9 and not fails`)。ところが 2026-07-25 の
# コミット 7ac3d7b で preflight に G10/G11 が足され、G5b と合わせて実測 **12件**
# 出るようになった。よってあの関数は**健全なビルドでも必ず FAIL する**
# (2026-07-26 実測: 12 PASS / 0 FAIL なのに gate C は FAIL)。
#
# ここでは件数を固定しない。判定材料は
#   * `[FAIL] G*` が1件も無いこと
#   * `[WARN] G*` が1件も無いこと(G10/G11 は soft_gate なので NG は WARN で出る。
#     「ソフト」はパイプライン側の都合であって、出荷検査で見逃してよい理由ではない)
#   * 最低ライン G1〜G9 が全部揃っていること(preflight が途中で死んでいない)
PREFLIGHT_CORE_GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9")


def _preflight_lines(log_text, kind):
    return re.findall(r"\[{}\] (G\d+\w*)".format(kind), log_text)


def gate_preflight(name, log_text):
    passes = _preflight_lines(log_text, "PASS")
    fails = _preflight_lines(log_text, "FAIL")
    warns = _preflight_lines(log_text, "WARN")
    total = len(passes) + len(fails)
    if total == 0:
        return _gate("SKIP", name,
                     note="ログに preflight の [PASS]/[FAIL] 行が無い(変換が preflight まで届いていない)")
    seen = {p.split()[0] for p in passes}
    missing_core = [g for g in PREFLIGHT_CORE_GATES if g not in seen]
    detail = {
        "n_pass": len(passes), "n_fail": len(fails), "n_warn": len(warns),
        "failed": fails, "warned": warns, "missing_core": missing_core,
        "gates_seen": sorted(seen),
    }
    ok = not fails and not warns and not missing_core
    return _gate("PASS" if ok else "FAIL", name, **detail)


# --- ゲート: UE 非依存 --------------------------------------------------------

# convert.ps1 の UE 分岐が実際に呼ぶ実行ファイル/コマンド名(:324,:365,:392,:412)。
UE_TOOL_PATTERNS = [
    r"UnrealPak(\.exe)?",
    r"UnrealEditor-Cmd(\.exe)?",
    r"RunUAT(\.bat)?",
    r"BuildCookRun",
    r"-run=pythonscript",
]


# 2026-07-26 発覚: 穴1(黙ってSKIPするバグ)を直したことで
# test_ue_independent_conversion が初めて実際の判定に到達したところ、
# noue分岐のバナー行 `=== Phase 2〜6(noue): build_pak_from_avatar.py
# 一気通貫(UnrealPak不使用) ===` が「UnrealPak」を含むというだけで
# 誤検知(FAIL)していた。これは起動痕跡ではなく**起動していないことの
# 説明文**なので、同じ行に否定語があれば除外する。
_UE_TOOL_NEGATION_MARKERS = (
    "不使用", "使わない", "使用しない", "呼ばない", "not used", "unused",
)


def gate_no_ue_tool_in_log(name, log_text, patterns=UE_TOOL_PATTERNS):
    """変換ログに UE ツールの起動痕跡が無いこと(UE非依存の実証その1)。

    「(パターン名)を使わない/呼ばない」という**説明文**は除外し、
    起動痕跡だけを拾う(上の _UE_TOOL_NEGATION_MARKERS 参照)。
    """
    found = []
    lines = log_text.splitlines()
    for pat in patterns:
        for ln in lines:
            if not re.search(pat, ln):
                continue
            if any(neg in ln for neg in _UE_TOOL_NEGATION_MARKERS):
                continue
            found.append({"pattern": pat, "line": ln.strip()[:200]})
            break
    return _gate("PASS" if not found else "FAIL", name,
                 found=found, checked=list(patterns), log_len=len(log_text))


def gate_engine_mode_is_noue(name, log_text):
    """convert.ps1 が実際に noue で走ったこと(`=== EngineMode: noue ===`)。"""
    m = re.search(r"=== EngineMode: (\w+) ===", log_text)
    if not m:
        return _gate("SKIP", name, note="ログに EngineMode 行が無い")
    return _gate("PASS" if m.group(1) == "noue" else "FAIL", name, engine_mode=m.group(1))


# --- ゲート: 入力形式 ---------------------------------------------------------

def gate_input_format_accepted(name, job_dict, build_result):
    """入力形式(.vrm / .fbx)がパイプラインに受理され、pak まで到達したこと。"""
    src = job_dict.get("vrm_path", "")
    ext = os.path.splitext(src)[1].lower()
    detail = {"input_ext": ext, "input": src, "exit_code": build_result.exit_code,
              "pak": build_result.pak_path}
    if ext not in (".vrm", ".fbx"):
        detail["note"] = ("パイプラインが直接受けるのは .vrm / .fbx のみ"
                          "(step01_import_vrm.py:549)。.prefab は GUI が Unity で FBX 化する")
        return _gate("SKIP", name, **detail)
    ok = build_result.exit_code == 0 and build_result.pak_path and \
        os.path.isfile(build_result.pak_path)
    return _gate("PASS" if ok else "FAIL", name, **detail)


# --- ゲート: アトラス見た目(パッチ単位NCC) ------------------------------------
# 2026-07-26 新設。既存の全体NCCゲート(pipeline/py/convert_noue.py:
# _render_atlas_visual_check、閾値0.95、変更禁止)は「アトラス化"前"
# (converted/preview_{gender}_stand.png)対"後"(build/atlas/atlascheck_
# {gender}.png)を同一カメラ・同一ポーズで比較する」設計そのものは健全だが、
# **全画面の平均**で判定するため、広いキャンバスの一部だけが破損しても
# 平均に薄まって見逃す(実例: input_vrm_seed の胸ロゴが別の模様に文字化け
# したのに全体NCC=0.9989で通過していた)。
# devtools/atlas_compare.py(本日新設、変更禁止)が同じ2枚を
# 64x64パッチ単位のNCCで比較する機能を既に持っているので、それを
# **本試験スイートのゲートとして配線する**(devtools側は数値を返すだけで
# 合否を決めない設計なので、閾値の適用と PASS/FAIL 判定はここが担う)。
#
# 閾値0.97の根拠(scratchpad\baseline_G_atlas.md、23検体の実測):
#   正常系(既知の欠陥を除く) tile_min_ncc の最低値 = 0.9956(vrm1)
#   既知の欠陥               tile_min_ncc            = 0.9335/0.9351(seed の
#                                                       胸ロゴ文字化け)
# 0.97 は正常系の床から約0.6pp下、既知欠陥の上限から約3.7pp上に置いた
# 暫定値(n=17と少ないので、検体が増えたら再校正すること)。
ATLAS_PATCH_SIZE = 64
ATLAS_PATCH_MIN_NCC = 0.97


def gate_atlas_patch_ncc(name, job_dir, blender_exe):
    r"""アトラス化「前」(converted/preview_{gender}_stand.png)と「後」
    (build/atlas/atlascheck_{gender}.png)を同一カメラ・同一ポーズで比較した
    パッチ単位(64x64)最小NCCによるゲート。

    **既存の全体NCCゲート(0.95)を置き換えるものではない**(convert_noue.py
    側にそのまま残る)。こちらは devtools/atlas_compare.py を使った
    追加のパッチ単位ゲート(局所破損の検出用)。

    既知の限界: パッキング前後の比較なので、**前も後も同じように壊れている
    見た目の破綻**(例: prefab_flatver2_agyo のbindポーズ90度ずれ、
    input_vrm_vrm1の後ろ姿カメラ)は検出できない(差分がゼロになるため)。
    """
    import atlas_compare
    result = atlas_compare.compare_case(job_dir, blender_exe, patch=ATLAS_PATCH_SIZE)
    genders = result.get("genders", {})
    comparable = {g: e for g, e in genders.items() if e.get("comparable")}
    if not comparable:
        skip_notes = {g: (e.get("skipped") or e.get("reason") or "不明")
                      for g, e in genders.items()}
        return _gate("SKIP", name, note="比較可能な性別が無い(単一テクスチャで"
                     "アトラス不要、または参照レンダーが無い)", genders=skip_notes)
    worst_gender, worst_entry = min(
        comparable.items(), key=lambda kv: kv[1]["tile_min_ncc"])
    ok = worst_entry["tile_min_ncc"] >= ATLAS_PATCH_MIN_NCC
    detail = {
        "threshold": ATLAS_PATCH_MIN_NCC, "patch": ATLAS_PATCH_SIZE,
        "worst_gender": worst_gender,
        "tile_min_ncc": worst_entry["tile_min_ncc"],
        "global_ncc": worst_entry["global_ncc"],
        "worst_tile": worst_entry.get("worst_tile"),
        "per_gender": {g: {"tile_min_ncc": e["tile_min_ncc"],
                           "global_ncc": e["global_ncc"]}
                      for g, e in comparable.items()},
    }
    return _gate("PASS" if ok else "FAIL", name, **detail)


# --- 検体の性質を測る(テクスチャ枚数軸の自動化) --------------------------------

def vrm_gltf_json(path):
    """VRM(=glb)の JSON チャンクを読む。Blender も外部ライブラリも要らない。"""
    with open(path, "rb") as f:
        magic, _ver, _total = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67:
            raise ValueError("glb ではない: {}".format(path))
        clen, _ctype = struct.unpack("<II", f.read(8))
        return json.loads(f.read(clen).decode("utf-8", errors="replace"))


def avatar_texture_profile(path):
    """検体のテクスチャ規模。返り値 {n_images, n_materials, atlas_rows_estimate}。

    アトラスの行数は `ceil(sqrt(スロット数))`(vp_atlas 系の敷き方)。
    **推定値**であり、実測はビルド後の avatar_meta.json(slots)から取る。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext != ".vrm":
        return {"n_images": None, "n_materials": None, "atlas_rows_estimate": None,
                "note": "VRM 以外は静的には数えられない"}
    j = vrm_gltf_json(path)
    n_img = len(j.get("images", []))
    n_mat = len(j.get("materials", []))
    n = max(n_img, 1)
    return {"n_images": n_img, "n_materials": n_mat,
            "atlas_rows_estimate": int(math.ceil(math.sqrt(n)))}


def built_slot_count(job_dir):
    """ビルド後の実測スロット数(converted\\avatar_meta.json の slots)。"""
    p = os.path.join(job_dir, "converted", "avatar_meta.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        meta = json.load(f)
    return len(meta.get("slots", {}) or {})


def built_bones(job_dir):
    """ビルド後の全ボーン名(drop_bones の指定候補を自動で選ぶために使う)。"""
    p = os.path.join(job_dir, "converted", "avatar_meta.json")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        meta = json.load(f)
    return list(meta.get("bones", []))


# 削除ボーンの検体を自動選定するとき、これらは選ばない
# (Humanoid 必須ボーンを消すと変換自体が別の理由で落ち、交絡する)。
_HUMANOID_PREFIXES = (
    "Hips", "Spine", "Chest", "Neck", "Head", "Shoulder", "Upper Arm", "Lower Arm",
    "Hand", "Upper Leg", "Lower Leg", "Foot", "Toe", "Eye",
    "Index", "Little", "Middle", "Ring", "Thumb",
)


def _normalize_bone_name(name):
    """命名規則の揺れ(大文字/小文字、`_`/`.`/半角スペース区切り)を吸収する。

    2026-07-26 発覚: `_HUMANOID_PREFIXES` は "Hips" のような大文字始まりを
    前提にしているが、VRM系検体(例: input_vrm_seed)は Blender 工程後に
    小文字ドット命名(`hips`, `upper_arm.L` 等)になる。
    `"hips".startswith("Hips")` は False なので、この命名規則の検体では
    人型除外フィルタが**一切効かず**、`hips` のような人型必須ボーンが
    そのまま削除候補に選ばれかねなかった(実データで確認済み)。
    """
    return name.lower().replace("_", " ").replace(".", " ")


_HUMANOID_PREFIXES_NORM = tuple(_normalize_bone_name(p) for p in _HUMANOID_PREFIXES)


def pick_drop_bone_candidate(bones):
    """削除ボーン検査に使える「Humanoid 以外の枝」を1本選ぶ。無ければ None。

    **名前だけで選ぶ**(このボーンが実際に頂点ウェイトを持つかは見ない)。
    そのため実データでは「Humanoid ではないが誰も参照していないボーン」
    (例: fbx_flat_ma の `cheek_L`。表情駆動用の補助ボーンで頂点ウェイトが
    無い)を選び、削除ボーン検査が「差分ゼロ」で機能検証にならないまま
    通ってしまうことがある(2026-07-26 実測)。**実データに基づく選定は
    `pick_drop_bone_candidate_weighted` を使うこと。**
    こちらは Blender 不要な軽量フォールバック、および selftest 用に残す。
    """
    for b in bones:
        nb = _normalize_bone_name(b)
        if any(nb.startswith(p) for p in _HUMANOID_PREFIXES_NORM):
            continue
        return b
    return None


def pick_drop_bone_candidate_weighted(job_dir, bones, blender_exe, min_vertices=30):
    """`pick_drop_bone_candidate` の実データ版(2026-07-26 新設)。

    `converted/step01_clean.blend` を Blender ヘッドレスで直接開き、
    `drop_bone_meshes()`(pipeline\\blender\\step01_import_vrm.py:278-332)と
    **同じ閾値**(合計ウェイト>0.5)で各ボーン(子孫込み)が支配する頂点数を
    実測する(`_dump_bone_weights.py`)。実際に `min_vertices` 頂点以上を
    支配するボーンの中から最大のものを選ぶ——「名前は人型じゃないが
    誰も参照していない」ボーンを誤って選ぶ事故(cheek_L)を構造的に防ぐ。

    Blender が使えない/計測できない場合は `pick_drop_bone_candidate`
    (名前ベース)へフォールバックする(疎通そのものは落とさない)。
    戻り値: (candidate_or_None, detail_dict)。detail は診断用。
    """
    blend_path = os.path.join(job_dir, "converted", "step01_clean.blend")
    if not (blender_exe and os.path.isfile(blender_exe) and os.path.isfile(blend_path)):
        return pick_drop_bone_candidate(bones), {
            "method": "name_fallback",
            "why": "blender_exe または step01_clean.blend が無い",
        }

    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "_dump_bone_weights.py")
    out_json = os.path.join(WORK_ROOT, "convert_logs",
                            "_bone_weights_{}.json".format(os.getpid()))
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    prefixes_json = json.dumps(list(_HUMANOID_PREFIXES_NORM))
    cmd = [blender_exe, "--background", blend_path, "--python", script,
           "--", out_json, prefixes_json]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        return pick_drop_bone_candidate(bones), {
            "method": "name_fallback", "why": "blender実行に失敗: {!r}".format(e)}

    if not os.path.isfile(out_json):
        return pick_drop_bone_candidate(bones), {
            "method": "name_fallback",
            "why": "計測結果が生成されなかった(blender rc={})".format(proc.returncode),
            "blender_tail": (proc.stdout or "")[-1000:] + (proc.stderr or "")[-1000:],
        }
    try:
        with open(out_json, encoding="utf-8") as f:
            counts = json.load(f)
    finally:
        try:
            os.remove(out_json)
        except OSError:
            pass

    candidates = {b: n for b, n in counts.items() if n >= min_vertices}
    if not candidates:
        return None, {
            "method": "weighted", "counts": counts, "min_vertices": min_vertices,
            "why": "{}頂点以上を支配する Humanoid 以外のボーンが無い".format(min_vertices),
        }
    best = max(candidates, key=candidates.get)
    return best, {
        "method": "weighted", "counts": counts, "min_vertices": min_vertices,
        "picked": best, "picked_vertex_count": candidates[best],
    }


# --- ゲート: 除外ボーンが実効的に働いたか(2026-07-26 新設) --------------------
# `drop_bone_meshes()`(pipeline\blender\step01_import_vrm.py:278-332)が
# 出す実行痕跡(ログ行)を判定材料にする。「実装した」と「効いている」は別
# (DEV_NOTES(29)§4)なので、成果物の存在ではなくログの実行痕で見る。

_DROP_BONES_NOT_FOUND_RE = re.compile(r"drop_bones: ボーンが見つからない: (\S+)")
_DROP_BONES_REMOVED_RE = re.compile(r"drop_bones: (\S+): (\d+)頂点削除")
_DROP_BONES_WHOLE_MESH_RE = re.compile(r"drop_bones: メッシュごと削除: (\S+)")
_DROP_BONES_ALL_GONE_MARKER = "drop_bonesで全メッシュが消えた"


def gate_drop_bones_effective(name, log_text):
    """drop_bones 指定が実際に頂点を削除したこと(0件でも全滅でもない)。

    数値だけで判定しない方針(2026-07-25複数事故の教訓)により、この
    ゲートは「機能が動いた証拠」の**数値側**だけを担う。画像側の裏取りは
    `gate_images_differ` を別途併用すること。
    """
    not_found = _DROP_BONES_NOT_FOUND_RE.findall(log_text)
    removed = _DROP_BONES_REMOVED_RE.findall(log_text)
    whole_mesh_removed = _DROP_BONES_WHOLE_MESH_RE.findall(log_text)
    total_removed = sum(int(n) for _, n in removed)
    all_gone = _DROP_BONES_ALL_GONE_MARKER in log_text
    detail = {
        "not_found_bones": not_found,
        "per_mesh_removed": [{"mesh": m, "n": int(n)} for m, n in removed],
        "whole_mesh_removed": whole_mesh_removed,
        "total_vertices_removed": total_removed,
        "all_meshes_gone": all_gone,
    }
    if not_found:
        return _gate("FAIL", name, note="指定したボーンがアーマチュアに見つからない",
                     **detail)
    if all_gone:
        return _gate("FAIL", name, note="指定が広すぎて全メッシュが消えた"
                     "(die で変換自体も止まっているはず)", **detail)
    if total_removed == 0 and not whole_mesh_removed:
        return _gate("FAIL", name, note="頂点が1つも削除されていない"
                     "(候補ボーンにウェイトが乗っていない疑い)", **detail)
    return _gate("PASS", name, **detail)


# --- ゲート: 画像が実際に変わったか(2026-07-26 新設) --------------------------
# 「除外ボーンを指定したら絵が変わるはず」のような**変化が期待される操作**の
# 裏取り用。数値(頂点数)だけで判定しない方針の画像側を担う。
# devtools側の車輪(atlas_compare.ncc_flat)とは独立実装(用途が違う: あちらは
# 同一のはずの画像の一致度、こちらは意図的に変えた画像の相違度)。

def _load_rgb_array(path):
    import numpy as np
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)


def gate_images_differ(name, before_path, after_path, run_dir=None, case=None,
                       max_ncc_if_changed=0.999):
    """2枚のレンダリングが実際に違うことを画像側から確認する。

    NCC(全画面、RGBフラット化→平均減算→相関係数)が `max_ncc_if_changed`
    以上(ほぼ同一)なら「操作が絵に届いていない」とみなし FAIL にする。
    FAIL 時は両画像を run_dir 配下へコピーして残す(数値だけで判定せず、
    人間が最終確認できるようにする。2026-07-25 複数事故の教訓)。
    """
    if not (os.path.isfile(before_path) and os.path.isfile(after_path)):
        return _gate("SKIP", name, note="比較用の画像が無い",
                     before=before_path, after=after_path)
    import numpy as np
    a = _load_rgb_array(before_path)
    b = _load_rgb_array(after_path)
    if a.shape != b.shape:
        ncc, changed = None, True
    else:
        af = a.ravel() - a.mean()
        bf = b.ravel() - b.mean()
        denom = float(np.linalg.norm(af) * np.linalg.norm(bf))
        ncc = float((af * bf).sum() / denom) if denom > 0 else 1.0
        changed = ncc < max_ncc_if_changed
    detail = {"ncc": ncc, "before": before_path, "after": after_path}
    if not changed:
        if run_dir:
            import shutil
            out_dir = os.path.join(run_dir, "artifacts", case or name)
            os.makedirs(out_dir, exist_ok=True)
            shutil.copy(before_path, os.path.join(out_dir, "before.png"))
            shutil.copy(after_path, os.path.join(out_dir, "after.png"))
            detail["saved_to"] = out_dir
        return _gate("FAIL", name, note="除外前後で絵がほぼ変わっていない"
                     "(操作が届いていない疑い)", **detail)
    return _gate("PASS", name, **detail)
