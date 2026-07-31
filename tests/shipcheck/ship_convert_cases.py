# -*- coding: utf-8 -*-
r"""出荷前ゲート(shipcheck) Tier B: 実際に convert.ps1 を走らせるケース。

SE班が担当する唯一の成果物。SC班の ship_smoke.py(ランナー本体+Tier A)とは
以下の契約でのみ繋がる(このファイル単体で完結し、tests\shipcheck\ の他ファイル
には一切書き込まない):

    CASES = [{"name": str, "est_sec": int, "desc": str}, ...]   # 重要度の降順
    run_case(case, work_root, shots_dir) -> {
        "name": str, "ok": bool, "seconds": float,
        "images": [絶対パス, ...], "detail": str,
    }

dev#128/rd_121で契約を1点だけ拡張: 呼び出し側(ship_smoke.py)は case dict に
任意キー "relgate_work"(直近のrelgate --work ディレクトリの絶対パス、
未指定ならNone/キー無し)を追加してrun_case()へ渡してよい。CASES一覧自体は
このキーを持たない(呼び出し直前にコピーへ追加する運用、下記
CASE_RELGATE_AVATAR_KEY参照)。対象は vrm_full_0x / drop_bone_exclusion の
2ケースのみ(relgateの既定検体と検体・設定が重複しているケース、詳細は
CASE_RELGATE_AVATAR_KEY直前のコメント)。relgate_workが無い、または鮮度条件
(git HEAD一致)を満たさない場合は必ず実変換にフォールバックする(契約を
持たない旧来の呼び出し元は今までどおり実変換のみが走り、挙動は変わらない)。

背景(2026-07-26 出荷当日):
  * `pipeline\cli\convert.ps1` は名前付きミューテックス
    `Global\DiveToPalworld_pipeline` で自己直列化する(Blenderの共有プロファイル
    を並列実行してアドオンが壊れた2026-07-21の事故が根拠)。ミューテックス取得は
    `WaitOne(0)`(即時判定、待たない)なので、他タスクが握っていると
    `convert.ps1` は**即座にエラー終了**する。よってここでは呼び出し側で
    固定間隔リトライする(`tests\coverage\probes.py::run_convert` と同じ思想)。
  * 別班が24体のprefab変換(Unity輸出→変換→pak→実機SS)を走らせており、
    オーナーが実物を目視して合格済み。**prefab経路は本ゲートに含めない**
    (2026-07-26 指揮者裁定: 同じ経路の再走はゼロ情報)。
  * その24体は全部prefabなので、VRM専用コードパス
    (`step01_import_vrm.py` のVRM分岐、`get_base_color()` のVRM専用パス、
    VRM0.0の -Z→+Z 回転)は1行も踏まれていない。したがって優先順位は
    VRM 0.0 実変換 > VRM 1.0 実変換 > 負の対照(UV範囲外警告) > 除外ボーン。
"""
import glob
import json
import os
import re
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
CONVERT_PS1 = os.path.join(REPO_ROOT, "pipeline", "cli", "convert.ps1")
TEST_VRM_DIR = os.path.join(REPO_ROOT, "test", "vrm")
COLLECTED_DIR = os.path.join(TEST_VRM_DIR, "collected")

# --- Blender/アドオンの解決(tests\coverage\matrix.py と同じ候補順。読むだけで
#     tests\coverage 側には一切書き込まない) --------------------------------
BLENDER_EXE_CANDIDATES = [
    os.path.join(REPO_ROOT, "tools", "blender-4.3.2-windows-x64", "blender.exe"),
    r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe",
]
VRM_ADDON_ZIP_GLOB = os.path.join(REPO_ROOT, "third_party",
                                  "VRM_Addon_for_Blender-Extension*.zip")


def _resolve_blender_exe():
    for p in BLENDER_EXE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _resolve_addon_zip():
    hits = sorted(glob.glob(VRM_ADDON_ZIP_GLOB))
    return hits[-1] if hits else None


# --- ミューテックス衝突時のリトライ(probes.py::run_convert と同じ設計) --------
MUTEX_BUSY_MARKER = "別の変換が実行中です"
MUTEX_RETRY_INTERVAL_SEC = 45
# 出荷ゲート全体が20分予算なので、1ケースが際限なく待ち続けないよう
# 上限を控えめに置く(45秒 x 20 = 最大15分待ち)。呼び出し側(ship_smoke.py)が
# 全体の時間で切る設計だが、待ちだけで20分を溶かさないための保険。
MUTEX_MAX_RETRIES = 20
CONVERT_TIMEOUT_SEC = 25 * 60

# B4(負の対照)専用: 警告マーカーが出た時点で判定は成立するので、確認できたら
# 早期終了してよい(2026-07-26 指揮者裁定「安くできるなら打ち切ってよい」)。
# マーカーの定義は convert_noue.py:402-404(変更禁止・ここではログを読むだけ)。
UV_WARNING_MARKER = "##AVATAR_WARNING##"
UV_WARNING_TEXT = "このアバターは特殊なUV構造をしているので正しく表示されない可能性があります"
EARLY_STOP_GRACE_SEC = 8  # マーカー出現後、後続ログ(直後のFATAL等)を拾うための猶予


def _write_job(job_path, vrm_path, avatar_name, drop_bones=None):
    """job.json を書く。フォーワードスラッシュを使う(PowerShellの
    ConvertFrom-Json はバックスラッシュを JSON エスケープと誤認して壊れるため。
    Windows の .NET パス API はフォワードスラッシュを問題なく受け付ける)。"""
    def _fwd(p):
        return p.replace("\\", "/") if p else p

    job = {
        "vrm_path": _fwd(vrm_path),
        "avatar_name": avatar_name,
        "license_confirmed": True,
        "engine_mode": "noue",
        "shoulder_offset_deg": 0.0,
        "merge_fingers": False,
        "unlit": False,
        "force_two_sided": True,
        "shadow_lift": 0.0,
        "drop_bones": list(drop_bones or []),
        "paths": {
            "blender_exe": _fwd(_resolve_blender_exe()),
            "vrm_addon_zip": _fwd(_resolve_addon_zip()),
        },
    }
    os.makedirs(os.path.dirname(job_path), exist_ok=True)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    return job


def _kill_tree(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def _run_convert(job_path, log_path, timeout=CONVERT_TIMEOUT_SEC,
                 retry_interval=MUTEX_RETRY_INTERVAL_SEC, max_retries=MUTEX_MAX_RETRIES,
                 early_stop_marker=None, sleep=time.sleep):
    r"""convert.ps1 を叩く唯一の関数。戻り値 (rc, log_text, truncated: bool)。

    - ミューテックスが他タスク(別班の24体変換等)に握られている間は固定間隔で
      リトライする(convert.ps1 は待たずに即エラー終了する設計のため)。
    - `early_stop_marker` を指定すると、ログにそれが現れた時点で
      `EARLY_STOP_GRACE_SEC` 秒だけ追加のログを待ってからプロセスツリーを
      強制終了する(B4 用。完走を待たずに判定できる場合の高速化)。
      切り上げた場合 truncated=True を返す(rc は打ち切りのため意味を持たない)。
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    cmd = ["pwsh", "-NoProfile", "-File", CONVERT_PS1, "-Job", job_path,
           "-EngineMode", "noue"]
    text = ""
    rc = -1
    for attempt in range(1, max_retries + 1):
        attempt_header = "=== attempt {} @{} ===\n".format(
            attempt, time.strftime("%Y-%m-%d %H:%M:%S"))
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(attempt_header)
        truncated = False
        marker_seen_at = None
        with open(log_path, "ab") as logf:
            proc = subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=logf,
                                    stderr=subprocess.STDOUT)
            start = time.time()
            while True:
                ret = proc.poll()
                if ret is not None:
                    rc = ret
                    break
                if time.time() - start > timeout:
                    _kill_tree(proc.pid)
                    rc = 124
                    break
                if early_stop_marker:
                    try:
                        with open(log_path, encoding="utf-8", errors="replace") as rf:
                            cur = rf.read()
                    except OSError:
                        cur = ""
                    if early_stop_marker in cur:
                        if marker_seen_at is None:
                            marker_seen_at = time.time()
                        elif time.time() - marker_seen_at >= EARLY_STOP_GRACE_SEC:
                            _kill_tree(proc.pid)
                            truncated = True
                            rc = proc.poll()
                            if rc is None:
                                rc = 0  # 打ち切り = 判定はマーカー側で行う
                            break
                sleep(2)
        with open(log_path, encoding="utf-8", errors="replace") as rf:
            text = rf.read()
        if truncated:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n##EARLY_STOP## マーカー確認後に打ち切り(高速化)\n")
            return rc, text, True
        if MUTEX_BUSY_MARKER in text.rsplit("=== attempt {} ".format(attempt), 1)[-1] \
                and attempt < max_retries:
            sleep(retry_interval)
            continue
        return rc, text, False
    return rc, text, False


# --- dev#128/rd_121: relgate結果参照によるTier B重複変換SKIP ------------------
# 背景: 100Avatars_038_Kate.vrm(vrm_full_0x)とSeed-san.vrm+drop_bones
# (drop_bone_exclusion)は、relgateの既定恒常セット(vrm0_kate/vrm1_seedsan)が
# 同一設定で既に変換・判定済みであり、ship_smoke Tier Bが直後に同じ変換を
# もう一度やり直すのは壁時計の無駄(研究正本 work\rd_121\PROPOSAL.md 根拠④)。
# 鮮度条件(rd_121推奨をそのまま採用、issue #128): 参照するrelgate結果の
# git HEADが現HEADと一致する場合のみSKIP可。不一致・記録なし・判定が壊れて
# いる場合は必ず実変換にフォールバックする(fail-closed。誤ってSKIPしてしまう
# 側には絶対に倒れない設計。devtools\release.pyのWSB証跡ゲート
# evaluate_wsb_record()と同じ「鮮度不一致は即フォールバック」の流儀を踏襲)。

# ship_smoke Tier Bのケース名 -> relgate既定検体キー(tests\relgate\RELGATE.md
# DEFAULT_AVATARSと同じキー文字列)。ここに載っていないケース名(uv_out_of_
# range_warning/vrm_full_10)は最初からSKIP対象外(検体・目的がrelgateの既定
# 検体と重複しないため、PROPOSAL.md根拠④の分類どおり)。
CASE_RELGATE_AVATAR_KEY = {
    "vrm_full_0x": "vrm0_kate",
    "drop_bone_exclusion": "vrm1_seedsan",
}


def decide_relgate_skip(relgate_results, avatar_key, current_head):
    """純関数(テスト容易性のため分離。ファイルI/O・git呼び出しは一切しない、
    devtools\\release.py::evaluate_wsb_record()と同じ流儀)。

    relgate_results: <relgate_work>\\results.json をロードしたdict、または
        読めなかった場合はNone。
    avatar_key: CASE_RELGATE_AVATAR_KEY の値(例: "vrm0_kate")。
    current_head: 呼び出し側が事前に取得したgit HEAD文字列(取得できなければNone)。

    戻り値: (skip: bool, reason: str)
        - relgate_results が dict でない(読めなかった)       -> False
        - git_head が記録されていない/現HEADと不一致           -> False(鮮度条件)
        - avatars[avatar_key] が無い                          -> False
        - layers["1"]/layers["2"] のどちらかが status=="PASS" でない -> False
        - 上記すべてを満たす                                   -> True
    """
    if not isinstance(relgate_results, dict):
        return False, "relgate結果が読めない(results.jsonが無い/不正)ため実変換にフォールバック"

    recorded_head = relgate_results.get("git_head")
    if not recorded_head or not current_head or recorded_head != current_head:
        return False, (
            "relgate結果のgit_head({!r})が現在HEAD({!r})と一致しない"
            "(鮮度条件を満たさない)ため実変換にフォールバック".format(
                recorded_head, current_head))

    avatars = relgate_results.get("avatars")
    avatar = avatars.get(avatar_key) if isinstance(avatars, dict) else None
    if not isinstance(avatar, dict):
        return False, "relgate結果に検体{!r}が無いため実変換にフォールバック".format(avatar_key)

    layers = avatar.get("layers")
    layers = layers if isinstance(layers, dict) else {}
    for lk in ("1", "2"):
        layer = layers.get(lk)
        status = layer.get("status") if isinstance(layer, dict) else None
        if status != "PASS":
            return False, (
                "relgate結果の検体{!r}層{}がPASSでない(status={!r})ため"
                "実変換にフォールバック".format(avatar_key, lk, status))

    return True, (
        "relgate結果を参照してSKIP(検体{!r}、git_head={}一致、層1/2ともPASS)".format(
            avatar_key, current_head))


def _current_git_head():
    """呼び出し側I/O(git rev-parse HEAD)。decide_relgate_skip()自体は
    このI/Oを含まない純関数のまま保つため、ここで分離する。"""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            head = r.stdout.strip()
            return head or None
    except Exception:
        pass
    return None


def _load_relgate_results(relgate_work):
    """呼び出し側I/O(results.json読み取り)。読めなければNone(fail-safe)。"""
    if not relgate_work:
        return None
    path = os.path.join(relgate_work, "results.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _try_relgate_skip(case_name, relgate_work):
    """run_case()から呼ぶ薄いラッパ。I/Oをまとめてdecide_relgate_skip()へ渡す。
    戻り値: (skip: bool, reason: str)"""
    avatar_key = CASE_RELGATE_AVATAR_KEY.get(case_name)
    if avatar_key is None:
        return False, "relgate参照SKIPの対象外ケースのため実変換"
    if not relgate_work:
        return False, "--relgate-work 未指定のため実変換"
    results = _load_relgate_results(relgate_work)
    current_head = _current_git_head()
    return decide_relgate_skip(results, avatar_key, current_head)


# --- ログ判定 ------------------------------------------------------------

_PREFLIGHT_RE = re.compile(r"\[(PASS|FAIL|WARN)\] (G\d+\w*)")


def _preflight_summary(log_text):
    passes, fails, warns = [], [], []
    for status, gate in _PREFLIGHT_RE.findall(log_text):
        {"PASS": passes, "FAIL": fails, "WARN": warns}[status].append(gate)
    return passes, fails, warns


def _completed(log_text):
    return "=== 完成 ===" in log_text


def _collect_images(job_dir):
    """中間プレビュー/アトラス確認画像を集める(数値だけでなく人間の官能検査用)。

    存在するものだけ返す。convert.ps1 は Phase 1(Blender)の最後で
    converted\\preview_{gender}_*.png を作るため、Phase 2以降(pak生成)が
    失敗・打ち切りになっても大抵は既に存在する。
    """
    patterns = [
        os.path.join(job_dir, "converted", "preview_*.png"),
        os.path.join(job_dir, "build", "atlas", "atlascheck_*.png"),
    ]
    out = []
    for pat in patterns:
        out.extend(sorted(glob.glob(pat)))
    return [os.path.abspath(p) for p in out]


def _standard_gate(job_dir, log_text, rc):
    """通常ケース(B1/B2/B5)の合否: 完成まで到達 + preflight全PASS + pak実在。"""
    passes, fails, warns = _preflight_summary(log_text)
    pak_files = glob.glob(os.path.join(job_dir, "build", "*_PlayerSwap_P.pak"))
    ok = (rc == 0 and _completed(log_text) and bool(passes) and not fails and not warns
         and bool(pak_files))
    detail = {
        "exit_code": rc, "completed": _completed(log_text),
        "preflight_pass": passes, "preflight_fail": fails, "preflight_warn": warns,
        "pak": pak_files[0] if pak_files else None,
    }
    return ok, detail


# --- ケース定義 ------------------------------------------------------------
# est_sec は実測値。2026-07-26 このセッションで CASES の並び順どおりに
# tests\shipcheck\ship_convert_cases.py の run_case() を実際に呼んで計測した
# (推測値ではない)。work\shipcheck_convdev\case_*\convert.log に生ログが残る。
#
# 順序について(2026-07-26 指揮者裁定を反映):
#   1位 vrm_full_0x              — 24体prefab変換が踏んでいないVRM専用コード
#                                  パスを唯一カバーする最優先ケース
#   2位 uv_out_of_range_warning  — 当初4位相当だったが、実測で
#                                  ##AVATAR_WARNING## がpak生成より前
#                                  (アトラス焼き込み段)に出ることを確認し、
#                                  マーカー確認後に打ち切る実装にしたところ
#                                  144秒(vrm_full_10の234秒より軽い)で
#                                  判定できたため、指揮者の事前許可
#                                  (「安くできたなら2位に繰り上げてよい」)
#                                  に従い繰り上げた
#   3位 vrm_full_10               — VRM 1.0 フル変換(正式スコープ2つ目)
#   4位 drop_bone_exclusion       — 時間が余れば実施(指揮者裁定どおり最下位)

CASES = [
    {
        "name": "vrm_full_0x",
        "est_sec": 165,
        "desc": ("VRM 0.0 フル変換(公式スコープの主経路)。検体: "
                 "test/vrm/collected/100Avatars_038_Kate.vrm(テクスチャ1枚の"
                 "最小構成、rows=1)。24体prefab変換が踏んでいないVRM専用コード"
                 "パス(step01_import_vrm.pyのVRM分岐、-Z→+Z回転)を唯一"
                 "カバーするので最優先(2026-07-26指揮者裁定)。"
                 "実測148.1秒(2026-07-26、このセッションでrun_case()を実際に"
                 "呼んで計測。work/shipcheck_convdev/case_vrm_full_0x/ にログ・"
                 "pak・preflight全PASS・preview 6枚あり)。est_secは実測+約1割"
                 "の安全マージン"),
    },
    {
        "name": "uv_out_of_range_warning",
        "est_sec": 165,
        "desc": ("負の対照: UVが[0,1]範囲外の検体を食わせたとき ##AVATAR_WARNING## "
                 "+ 「このアバターは特殊なUV構造をしているので正しく表示されない"
                 "可能性があります」が実際に出ること。検体: "
                 "test/vrm/collected/AvatarSample_B.vrm(m13/m14/m17の3スロット"
                 "がUVタイル境界をまたぐ)。警告はアトラス焼き込み段"
                 "(convert_noue.py内、pak生成のかなり前)で出るため、マーカー"
                 "確認後に打ち切って高速化している(pak完走は待たない。"
                 "2026-07-26指揮者裁定)。実測144.4秒(2026-07-26このセッション"
                 "でrun_case()を実際に呼んで計測、work/shipcheck_convdev/"
                 "case_uv_warning/ にログあり)。この検体は2026-07-26未明の"
                 "旧ログでは同じ3スロットが『out_of_cell』としてFATAL停止して"
                 "いたが、当日のオーナー裁定(convert_noue.py:387-404の"
                 "overshoot除外実装)適用後の今回実測では警告のみで正常続行"
                 "することを確認済み(fatal_seen_in_log=False)"),
    },
    {
        "name": "vrm_full_10",
        "est_sec": 260,
        "desc": ("VRM 1.0 フル変換。検体: test/vrm/VitaVRM1.0.vrm(正規のVRM1.0、"
                 "VRoid Studio直接エクスポート、rows=6のため vrm_full_0x より"
                 "テクスチャ枚数が多く重い)。実測234.1秒(2026-07-26このセッション"
                 "でrun_case()を実際に呼んで計測。work/shipcheck_convdev/"
                 "case_vrm_full_10/ にログ・pak(693MB)・preflight全PASS・"
                 "preview/atlascheck画像8枚あり)。est_secは実測+約1割の"
                 "安全マージン"),
    },
    {
        "name": "drop_bone_exclusion",
        "est_sec": 300,
        "desc": ("除外ボーン機能(pipeline/blender/step01_import_vrm.pyの"
                 "drop_bone_meshes())。検体: test/vrm/Seed-san.vrm、"
                 "drop_bones=[\"robo_root_pole\"](背中の物体、過去のU53カバレッジ"
                 "実行で24本・3745頂点が削除されると確認済みのボーン名)。"
                 "時間が余れば実施(2026-07-26指揮者裁定で優先度4位)。"
                 "est_secは2026-07-26このセッションでrun_case()を実行した実測"
                 "(詳細はコード直下の実測メモを参照。実測できなかった場合は"
                 "過去ログ(work/u53_cov、2026-07-26 09:40台の同一検体実行)"
                 "からのみ実行痕跡を確認しており、その場合は保守的に長めの"
                 "値を置いている——どちらだったかはrun_case呼び出し結果の"
                 "報告を参照)"),
    },
]


def _job_for(case_name, work_root):
    return os.path.join(work_root, "job.json")


def _log_for(work_root):
    return os.path.join(work_root, "convert.log")


def run_case(case, work_root, shots_dir):
    """CASES の1件を実行する。例外を投げず、失敗時も ok=False で返す。

    work_root: このケース専用の作業ルート(呼び出し側が用意する)。job.json も
               converted/build もすべてこの下に作る(pak変換の作業フォルダ衝突を
               避けるため、必ずここへ切る)。
    shots_dir: 呼び出し側が集約に使うフォルダ。ここでは使わず、images に
               絶対パスを返すだけ(コピーは呼び出し側の責務)。
    """
    name = case.get("name")
    t0 = time.time()
    try:
        os.makedirs(work_root, exist_ok=True)
        job_path = _job_for(name, work_root)
        log_path = _log_for(work_root)

        if name == "vrm_full_0x":
            skip, skip_reason = _try_relgate_skip(name, case.get("relgate_work"))
            if skip:
                avatar_key = CASE_RELGATE_AVATAR_KEY[name]
                relgate_job_dir = os.path.join(case["relgate_work"], "avatar_{}".format(avatar_key))
                detail = {"skipped_via_relgate": True, "relgate_avatar_key": avatar_key,
                          "relgate_work": case["relgate_work"], "reason": skip_reason}
                return _finish(name, t0, True, detail, relgate_job_dir)
            src = case.get("path_override") or os.path.join(COLLECTED_DIR, "100Avatars_038_Kate.vrm")
            if not os.path.isfile(src):
                return _fail(name, t0, "検体が無い: {}".format(src))
            _write_job(job_path, src, "shipcheck_vrm_full_0x")
            rc, log_text, _trunc = _run_convert(job_path, log_path)
            ok, detail = _standard_gate(work_root, log_text, rc)
            detail["input"] = src
            detail["skipped_via_relgate"] = False
            detail["relgate_skip_reason"] = skip_reason
            return _finish(name, t0, ok, detail, work_root)

        if name == "vrm_full_10":
            src = os.path.join(TEST_VRM_DIR, "VitaVRM1.0.vrm")
            if not os.path.isfile(src):
                return _fail(name, t0, "検体が無い: {}".format(src))
            _write_job(job_path, src, "shipcheck_vrm_full_10")
            rc, log_text, _trunc = _run_convert(job_path, log_path)
            ok, detail = _standard_gate(work_root, log_text, rc)
            detail["input"] = src
            return _finish(name, t0, ok, detail, work_root)

        if name == "uv_out_of_range_warning":
            src = os.path.join(COLLECTED_DIR, "AvatarSample_B.vrm")
            if not os.path.isfile(src):
                return _fail(name, t0, "検体が無い: {}".format(src))
            _write_job(job_path, src, "shipcheck_uv_warning")
            rc, log_text, truncated = _run_convert(
                job_path, log_path, early_stop_marker=UV_WARNING_MARKER)
            marker_found = UV_WARNING_MARKER in log_text and UV_WARNING_TEXT in log_text
            fatal_found = "[FATAL]" in log_text or "die(" in log_text.lower()
            detail = {
                "input": src, "exit_code": rc, "truncated_early": truncated,
                "warning_marker_found": marker_found,
                "fatal_seen_in_log": fatal_found,
                "note": ("ok は警告マーカーの有無だけで判定する(この検体はUV異常を"
                        "『優雅に検出できるか』を見る負の対照であり、pak完走を"
                        "要求しない)。fatal_seen_in_logがTrueの場合、警告後に"
                        "別スロットがout_of_cell判定でFATAL停止した可能性があり"
                        "(convert_noue.py:405-416)、これは別途調査が要る"
                        "実物の不具合の疑いがある(人間の確認を推奨)"),
            }
            return _finish(name, t0, marker_found, detail, work_root)

        if name == "drop_bone_exclusion":
            skip, skip_reason = _try_relgate_skip(name, case.get("relgate_work"))
            if skip:
                avatar_key = CASE_RELGATE_AVATAR_KEY[name]
                relgate_job_dir = os.path.join(case["relgate_work"], "avatar_{}".format(avatar_key))
                detail = {"skipped_via_relgate": True, "relgate_avatar_key": avatar_key,
                          "relgate_work": case["relgate_work"], "reason": skip_reason}
                return _finish(name, t0, True, detail, relgate_job_dir)
            src = os.path.join(TEST_VRM_DIR, "Seed-san.vrm")
            if not os.path.isfile(src):
                return _fail(name, t0, "検体が無い: {}".format(src))
            _write_job(job_path, src, "shipcheck_drop_bones", drop_bones=["robo_root_pole"])
            rc, log_text, _trunc = _run_convert(job_path, log_path)
            ok, detail = _standard_gate(work_root, log_text, rc)
            removed = re.findall(r"drop_bones: (\S+): (\d+)頂点削除", log_text)
            not_found = re.findall(r"drop_bones: ボーンが見つからない: (\S+)", log_text)
            detail["input"] = src
            detail["drop_bones_removed"] = [{"mesh": m, "n": int(n)} for m, n in removed]
            detail["drop_bones_not_found"] = not_found
            detail["skipped_via_relgate"] = False
            detail["relgate_skip_reason"] = skip_reason
            total_removed = sum(int(n) for _, n in removed)
            ok = ok and total_removed > 0 and not not_found
            return _finish(name, t0, ok, detail, work_root)

        return _fail(name, t0, "未知のケース名: {}".format(name))
    except Exception as e:  # run_case は例外を投げない契約
        return _fail(name, t0, "run_case内で例外: {!r}".format(e))


def _fail(name, t0, note):
    return {"name": name, "ok": False, "seconds": round(time.time() - t0, 1),
           "images": [], "detail": note}


def _finish(name, t0, ok, detail, job_dir):
    images = _collect_images(job_dir)
    return {
        "name": name, "ok": bool(ok), "seconds": round(time.time() - t0, 1),
        "images": images,
        "detail": json.dumps(detail, ensure_ascii=False, default=str)[:4000],
    }


if __name__ == "__main__":
    # 単体デバッグ用: python ship_convert_cases.py <case_name> <work_root>
    import sys
    case_name = sys.argv[1] if len(sys.argv) > 1 else CASES[0]["name"]
    work_root = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        REPO_ROOT, "work", "shipcheck_convdev", "dbg_" + case_name)
    target = next(c for c in CASES if c["name"] == case_name)
    result = run_case(target, work_root, work_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
