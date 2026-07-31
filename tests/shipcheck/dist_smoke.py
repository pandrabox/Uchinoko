# -*- coding: utf-8 -*-
"""T2(WP6): 配布zipスモーク(クリーン環境シミュレーション)ゲート。

やること:
  1. 配布zip(既定: dist\\*.zip の最新)を一時フォルダへ展開する。
  2. `subst` で空きドライブレターを割り当て、展開先を **C:以外のドライブパス**
     として見せる(開発機のCドライブに存在する何か——PATH上のツール、
     開発機固有の環境——にこっそり依存していないかを検出する狙い。
     `docs\\...\\pub#8`系の「Palworldインストール先がC以外だと動かない」事故と
     対の意味で、こちら側=ツール本体がCに依存していないかを見る)。
  3. `work\\relgate\\wp4\\`(WP4)が実証したcp932敵対環境技法を適用する
     (PYTHONUTF8/PYTHONIOENCODINGをプロセス環境から除去し、convert.ps1
     自身が設定する2行だけに依存させる。これにより「他PCでだけ起きる」
     文字コード事故の再発を、今回はエンドツーエンドの実変換で確認する)。
  4. 展開物**だけ**を使って(ランチャー廃止以降、`pipeline\\cli\\convert.ps1` /
     `assets\\tools\\...\\blender.exe` /
     `assets\\third_party\\...VRM_Addon...zip`。旧レイアウトの`_internal\\`は廃止済み)、
     変換を1本完走する。
     検体(vrm/fbx+humanoid.json)はリポジトリ側から読み取り専用で供給してよい
     (検体そのものはユーザーの手元にあるものの代替であり、配布物の一部ではない
     ため。実行コード・ツール類=配布物の中身、という区別)。
  5. fail-closed: zipが無い/展開失敗/変換失敗はすべて赤。`subst`解除・一時物
     削除のクリーンアップを finally で保証する。

使い方:
    python tests\\shipcheck\\dist_smoke.py [--zip <path>] [--work <dir>]
        [--job-template <job.jsonの雛形>] [--skip-cleanup] [--corrupt-for-negative-control <相対パス>]

--corrupt-for-negative-control: 展開直後、指定した相対パス(展開ルート=
    <extract_dir>\\Uchinoko_for_Palworld\\ からの相対)のファイルを削除してから変換を
    試みる。負の対照用(必須ファイル欠落時にfail-closedすることを示す)。

終了コード: 0=PASS(変換完走、pak生成確認)、1=FAIL(いずれかの工程で失敗)。
出力: <work>\\report.md(逐次追記)、<work>\\extracted\\、<work>\\job\\。
"""
import argparse
import glob
import json
import os
import re
import shutil
import string
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PIPELINE_PY_DIR = os.path.join(REPO_ROOT, "pipeline", "py")
if PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_PY_DIR)

# dev#186: devtools\relgate.py::SHAPELL_FBX/SHAPELL_HUMANOIDと同じ理由・同じ
# 実体パスへ移設済み(使い捨てのwork\ではなく.devonly\fixtures\、二重定義だが
# 値だけ揃える既存設計を踏襲)。
DEFAULT_VRM_PATH = os.path.join(REPO_ROOT, ".devonly", "fixtures", "relgate", "shapell", "shapell.fbx")
DEFAULT_HUMANOID_JSON = os.path.join(REPO_ROOT, ".devonly", "fixtures", "relgate", "shapell", "humanoid.json")

# u54(2026-07-27): 旧マーカーはWrite-Errorが自動付与する「スクリプトパス+コロン+
# 行番号」形式の文字列で、convert.ps1のその行より前に1行挿すだけで静かに壊れる
# 構造的な脆さがあった。ASCII安全トークンをconvert.ps1のメッセージ自体に
# 埋め込む方式へ変更した(devtools\relgate.py と同じトークン)。
MUTEX_RETRY_MARKER = "[D2P_MUTEX_BUSY]"

# dev#288(work\speed_mission\mutexwait\NOTES.md): PR#228のブロッキング待機
# (-MutexWaitMs)はdevtools\relgate.pyのrun_convert()にしか適用されておらず、
# dist_smokeは旧来の45秒固定ポーリング(下のDEFAULT_MAX_RETRIES/
# DEFAULT_RETRY_WAIT_SEC。当時は20回×45秒)のままだった。relgate.pyの
# DEFAULT_MUTEX_WAIT_MS(180000、根拠はdevtools\relgate.py L132-154のコメント
# 参照。ここでは重複説明しない)と同じ値をconvert.ps1へ渡し、OSレベルの
# ブロッキング待機(解放された瞬間に取得)を主経路にする。外側のPython
# リトライは「180秒待ってもなお取れなかった」異常系向けの保険に格下げされる
# ため、relgate.pyの保険既定値(5回×5秒)に合わせて既定値を変更した
# (--max-retries/--retry-waitで呼び出し側が上書きできる点は従来どおり)。
DEFAULT_MUTEX_WAIT_MS = 180000
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_WAIT_SEC = 5

# dev#288 提案3: convert.ps1が標準出力へ既に出しているPhase別タイミングを
# 正規表現で拾うためのパターン。convert.ps1(pipeline\cli\convert.ps1)自身の
# 文言そのもの(無改変)。[Phase 1] OK 行は-SkipBlender/-MaterialsOnly時や
# 旧版convert.ps1では出力されないことがある(実ログ
# work\release_cert\run_20260730_011737\で確認済み)ため、各キーは
# 見つからなければNoneのまま返す(捏造しない・判定ロジックには使わない)。
CONVERT_PHASE_TIME_PATTERNS = {
    "phase0_vanilla_sec": r"\[Phase 0\] OK \(([\d.]+)s\)",
    "phase1_blender_sec": r"\[Phase 1\] OK \(([\d.]+)s\)",
    "noue_build_sec": r"\[noue build\] OK \(([\d.]+)s\)",
    "total_elapsed_sec": r"Total elapsed time: ([\d.]+)s",
}


def parse_convert_phase_times_sec(text):
    """convert.ps1のstdout+stderr結合テキストから、Phase別タイミングを
    正規表現で拾う純関数。マッチしないキーはNone(パース失敗を偽装しない、
    fail-openにしない=検査対象には一切使わない観測専用フィールド)。"""
    result = {}
    for key, pattern in CONVERT_PHASE_TIME_PATTERNS.items():
        m = re.search(pattern, text or "")
        result[key] = float(m.group(1)) if m else None
    return result

# u54: Blenderポータブル同梱廃止に伴う既定のキャッシュ済み公式Blender zip
# (4.7の実DL検証で取得済み。以後の試験はこれを使い、再ダウンロードしない)。
# dev#186棚卸しでの分類: これは「恒常台帳」ではなく「再生成可能キャッシュ」
# (無ければtest_ensure_blender.py側が黙ってSKIPするfail-safe設計で、
# 必要なら4.7の実DL検証を再実行すれば再取得できる)。405MBと大きいため
# .devonly側へは移さず、work\のまま据え置く(移すと.devonly\state\の
# 「小さな判定台帳置き場」という性質と衝突するため)。
DEFAULT_BLENDER_CACHE_ZIP = os.path.join(REPO_ROOT, "work", "u54_unbundle", "cache",
                                          "blender-4.3.2-windows-x64.zip")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _append(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def find_latest_dist_zip():
    candidates = glob.glob(os.path.join(REPO_ROOT, "dist", "*.zip"))
    candidates = [c for c in candidates if not c.endswith(".provenance.json")]
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def extract_zip(zip_path, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)


def find_free_drive_letter():
    used = set()
    try:
        out = subprocess.run(["subst"], capture_output=True, text=True, timeout=15)
        for line in (out.stdout or "").splitlines():
            if len(line) >= 2 and line[1] == ":":
                used.add(line[0].upper())
    except Exception:
        pass
    for letter in string.ascii_uppercase:
        drive = letter + ":\\"
        if letter in used:
            continue
        if os.path.exists(drive):
            continue
        if letter in ("A", "B", "C"):
            continue  # Cは絶対に使わない(このゲートの目的そのもの)。A/Bはフロッピー予約の慣習を尊重
        return letter
    return None


def subst_mount(letter, target_dir):
    proc = subprocess.run(["subst", letter + ":", target_dir], capture_output=True, text=True, timeout=30)
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def subst_unmount(letter):
    proc = subprocess.run(["subst", letter + ":", "/d"], capture_output=True, text=True, timeout=30)
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def build_hostile_env():
    """WP4(`work\\relgate\\wp4\\REPORT.md`)が実証した技法: この開発機自身の
    ユーザー環境変数(PYTHONUTF8=1等)がconvert.ps1自身の対策をマスクしないよう、
    プロセス環境から明示的に除去する。convert.ps1が自前でPYTHONIOENCODING=utf-8/
    PYTHONUTF8=1を設定する2行を持っていれば、この除去があっても最終的には
    正しい値で子プロセスが起動するはず——つまりこのゲートは「対策が今も
    効いているか」をエンドツーエンドの実変換で確認する。"""
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    return env


def write_job_json(job_path, blender_exe, vrm_addon_zip, palworld_pak, avatar_name):
    cfg = {
        "vrm_path": DEFAULT_VRM_PATH.replace("\\", "/"),
        "avatar_name": avatar_name,
        "license_confirmed": True,
        "engine_mode": "noue",
        "humanoid_json": DEFAULT_HUMANOID_JSON.replace("\\", "/"),
        "shoulder_offset_deg": 0.0,
        "merge_fingers": False,
        "unlit": False,
        "force_two_sided": True,
        "shadow_lift": 0.0,
        "drop_bones": [],
        "paths": {
            "blender_exe": blender_exe.replace("\\", "/"),
            "vrm_addon_zip": vrm_addon_zip.replace("\\", "/"),
        },
    }
    if palworld_pak:
        cfg["paths"]["palworld_pak"] = palworld_pak.replace("\\", "/")
    os.makedirs(os.path.dirname(job_path), exist_ok=True)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def find_real_palworld_pak():
    """開発機にインストール済みのPalworldから既定パスのpakを探す(検体供給と
    同様、ユーザー環境の代替でありツール本体ではないので repo/dev 側の実体を
    使ってよい)。見つからなければNoneを返し、vp_core.load_job()側の
    自動探索(WP16: palworld_locate.py、公開issue #8対応)に委ねる。"""
    try:
        import palworld_locate
        return palworld_locate.find_palworld_pak()
    except Exception:
        return None


def run_convert(convert_ps1, job_path, env, log_path, max_retries=DEFAULT_MAX_RETRIES,
                 retry_wait=DEFAULT_RETRY_WAIT_SEC, mutex_wait_ms=DEFAULT_MUTEX_WAIT_MS):
    """convert.ps1を実行する。dev#288(2026-07-30)以降、まずconvert.ps1自身に
    -MutexWaitMs(既定DEFAULT_MUTEX_WAIT_MS)を渡してOSレベルのブロッキング待機
    (解放された瞬間に取得)をさせる(devtools\\relgate.py::run_convert()と同じ
    パターンの横展開)。それでも取れなかった場合(異常系、通常は発生しない想定)
    だけ、外側のこのループが保険としてretry_wait秒バックオフしてから再試行する
    (`work\\relgate\\wp4\\green\\run_green.ps1` / `ship_convert_cases.py` と同じ
    思想)。戻り値: (成功bool, 全stdout+stderrテキスト, 試行回数)"""
    for attempt in range(1, max_retries + 1):
        proc = subprocess.run(
            # WP-A2(2026-07-28): クリーンWindows実機にpwshは無い(v1.1.3の
            # ensure_blender.ps1 ParserError事故の原因調査で判明)。開発機が
            # pwshで固定していたためこの乖離をゲートが検出できなかった。
            # 実機と同じpowershell.exe(Windows PowerShell 5.1)で回す。
            ["powershell.exe", "-NoProfile", "-File", convert_ps1, "-Job", job_path,
             "-EngineMode", "noue", "-MutexWaitMs", str(mutex_wait_ms)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=1800,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        _append(log_path, "\n--- attempt %d (rc=%s) ---\n%s\n" % (attempt, proc.returncode, out))
        if proc.returncode == 0:
            return True, out, attempt
        if MUTEX_RETRY_MARKER in out and attempt < max_retries:
            time.sleep(retry_wait)
            continue
        return False, out, attempt
    return False, "(リトライ上限到達)", max_retries


def run_ensure_blender(ensure_blender_ps1, app_root, extra_args, report_path, label, timeout=1800):
    """u54: pipeline\\cli\\ensure_blender.ps1を実行する(展開物自身の同スクリプト、
    subst済みドライブ上で動かす)。戻り値: (returncode, 全stdout+stderrテキスト)。"""
    # WP-A2(2026-07-28): 同上。ensure_blender.ps1はクリーンWindows実機では
    # powershell.exe(PS5.1)で起動される(convert.ps1/GUIとも同方式)。
    # ここをpwsh固定にしていたため、BOM無しUTF-8起因のParserErrorが
    # ゲートで検出できなかった実例がある。
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ensure_blender_ps1,
            "-AppRoot", app_root] + list(extra_args)
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    _append(report_path, "\n### ensure_blender.ps1: {}\n\nrc={}\n```\n{}\n```\n".format(
        label, proc.returncode, out[-4000:]))
    return proc.returncode, out


def run_ensure_blender_negative_control(ensure_blender_ps1, app_root, extra_args, report_path, label):
    """4.6の負の対照(a)/(b)共通: ensure_blender.ps1がfail-closed
    ([D2P_BLENDER_SETUP_FAIL]マーカー付きで非0終了)することだけを確認する。
    通常の変換フローには進まない(呼び出し側がそのままreturnする前提)。"""
    rc, out = run_ensure_blender(ensure_blender_ps1, app_root, extra_args, report_path, label)
    ok = (rc != 0) and ("[D2P_BLENDER_SETUP_FAIL]" in out)
    if ok:
        print("PASS(負の対照): {} -> fail-closed確認(rc={})".format(label, rc))
        _append(report_path, "\n## PASS(負の対照): {} -> fail-closed確認\n".format(label))
        return 0
    print("FAIL(負の対照): {} -> fail-closedにならなかった(rc={})".format(label, rc))
    _append(report_path, "\n## FAIL(負の対照): {} -> fail-closedにならなかった(rc={})\n".format(label, rc))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", default=None, help="配布zipのパス(既定: dist\\*.zip の最新)")
    ap.add_argument("--work", default=None, help="作業フォルダ(既定: work\\relgate\\wp6\\t2_run_<timestamp>)")
    ap.add_argument("--corrupt-for-negative-control", default=None,
                     help="展開直後、Uchinoko_for_Palworld\\からの相対パスで指定したファイルを削除してから実行する(負の対照用)")
    ap.add_argument("--skip-cleanup", action="store_true", help="subst解除・一時物削除をスキップ(デバッグ用)")
    # dev#288: -MutexWaitMsブロッキング待機が主経路になったため、外側の
    # Python再試行は保険(既定値をrelgate.py同等の5回×5秒へ縮小)。
    # 呼び出し側が明示指定すれば旧値(20回×45秒)にも戻せる。
    ap.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    ap.add_argument("--retry-wait", type=int, default=DEFAULT_RETRY_WAIT_SEC)
    ap.add_argument("--mutex-wait-ms", type=int, default=DEFAULT_MUTEX_WAIT_MS,
                     help="convert.ps1へ渡す-MutexWaitMs(既定180000=180秒、relgate.pyと同値)")
    # u54: Blenderポータブル同梱廃止(初回起動時ダウンロード化)関連
    ap.add_argument("--blender-cache-zip", default=DEFAULT_BLENDER_CACHE_ZIP,
                     help="ensure_blender.ps1に-SourceZipとして渡すキャッシュ済み公式Blender zip"
                          "(既定: work\\u54_unbundle\\cache\\。実ネットワークに出ない)")
    ap.add_argument("--ensure-blender-bad-url", action="store_true",
                     help="負の対照(4.6a): SourceZipを指定せず無効URLを注入してensure_blender.ps1を"
                          "実行し、fail-closed([D2P_BLENDER_SETUP_FAIL])を確認して終了する"
                          "(通常の変換は行わない。実ネットワークに出て404を踏む)")
    ap.add_argument("--ensure-blender-corrupt-cache", action="store_true",
                     help="負の対照(4.6b): --blender-cache-zipを1バイト改竄したコピーを"
                          "-SourceZipに指定してensure_blender.ps1を実行し、SHA256不一致による"
                          "fail-closedを確認して終了する(通常の変換は行わない)")
    args = ap.parse_args(argv)

    work_root = os.path.abspath(args.work) if args.work else os.path.join(
        REPO_ROOT, "work", "relgate", "wp6", "t2_run_{}".format(time.strftime("%Y%m%d_%H%M%S")))
    os.makedirs(work_root, exist_ok=True)
    report_path = os.path.join(work_root, "report.md")
    _append(report_path, "# dist_smoke report\n\n- 開始: {}\n- 作業フォルダ: {}\n".format(_now(), work_root))

    letter = None
    extract_dir = os.path.join(work_root, "extracted")
    ok = False
    detail = {}

    try:
        # --- 1. zip特定 ---
        zip_path = args.zip or find_latest_dist_zip()
        if not zip_path or not os.path.isfile(zip_path):
            _append(report_path, "\n## FAIL: 配布zipが見つからない\n\n探索先: dist\\*.zip\n")
            print("FAIL: 配布zipが見つからない")
            return 1
        _append(report_path, "\n## 1. zip特定\n\n- zip: {}\n".format(zip_path))
        print("zip: {}".format(zip_path))

        # --- 2. 展開 ---
        t0 = time.time()
        try:
            extract_zip(zip_path, extract_dir)
        except Exception as e:
            _append(report_path, "\n## FAIL: 展開失敗\n\n```\n{}\n```\n".format(e))
            print("FAIL: 展開失敗: {}".format(e))
            return 1
        elapsed = time.time() - t0
        stage_root = os.path.join(extract_dir, "Uchinoko_for_Palworld")   # v2.0.0改名(make_dist.ps1の$Stageと一致)
        if not os.path.isdir(stage_root):
            _append(report_path, "\n## FAIL: 展開後にUchinoko_for_Palworld\\が見つからない\n")
            print("FAIL: 展開後にUchinoko_for_Palworld\\が見つからない")
            return 1
        _append(report_path, "\n## 2. 展開\n\n- 所要: {:.1f}秒\n- 展開先: {}\n".format(elapsed, extract_dir))
        print("展開OK ({:.1f}秒)".format(elapsed))

        # --- 負の対照: 意図的にファイルを消す ---
        if args.corrupt_for_negative_control:
            victim = os.path.join(stage_root, args.corrupt_for_negative_control)
            if os.path.isfile(victim):
                os.remove(victim)
                _append(report_path, "\n## 負の対照: ファイル欠落を注入\n\n- 削除: {}\n".format(victim))
                print("負の対照: 削除 -> {}".format(victim))
            else:
                _append(report_path, "\n## 負の対照の指定ミス: ファイルが最初から存在しない: {}\n".format(victim))
                print("FAIL: 負の対照対象が最初から存在しない: {}".format(victim))
                return 1

        # --- 3. subst ---
        letter = find_free_drive_letter()
        if not letter:
            _append(report_path, "\n## FAIL: 空きドライブレターが無い\n")
            print("FAIL: 空きドライブレターが無い")
            return 1
        mounted, mount_out = subst_mount(letter, extract_dir)
        if not mounted:
            _append(report_path, "\n## FAIL: subst失敗\n\n```\n{}\n```\n".format(mount_out))
            print("FAIL: subst失敗: {}".format(mount_out))
            return 1
        _append(report_path, "\n## 3. subst\n\n- ドライブ: {}:\\ -> {}\n".format(letter, extract_dir))
        print("subst OK: {}:\\ -> {}".format(letter, extract_dir))

        x_stage_root = "{}:\\Uchinoko_for_Palworld".format(letter)
        # 2026-07-31: ランチャー廃止に伴い配布レイアウトを
        # フラット化した(_internal\という1階層の入れ子を廃止)。本体exe一式は
        # 配布物ルート直下に直接置かれる。旧: internal_root = x_stage_root\_internal
        internal_root = x_stage_root
        convert_ps1 = os.path.join(internal_root, "pipeline", "cli", "convert.ps1")
        # u54: Blenderポータブル本体はもう展開物に含まれない(blender.exeの必須
        # チェックは撤去)。代わりにensure_blender.ps1本体と、それが使う差し込み
        # 素材(assets\blender_patch\)が同梱されていることを見る。
        ensure_blender_ps1 = os.path.join(internal_root, "pipeline", "cli", "ensure_blender.ps1")
        vrm_addon_zip = os.path.join(internal_root, "assets", "third_party",
                                      "VRM_Addon_for_Blender-Extension-4_4_0.zip")
        blender_patch_dir = os.path.join(internal_root, "assets", "blender_patch")
        blender_exe = os.path.join(internal_root, "assets", "tools",
                                    "blender-4.3.2-windows-x64", "blender.exe")  # ensure_blender後の到達先
        for label, p in (
            ("convert.ps1", convert_ps1),
            ("ensure_blender.ps1", ensure_blender_ps1),
            ("vrm_addon_zip", vrm_addon_zip),
            ("blender_patch/ooz.pyd", os.path.join(blender_patch_dir, "ooz.pyd")),
            ("blender_patch/python3.dll", os.path.join(blender_patch_dir, "python3.dll")),
        ):
            if not os.path.isfile(p):
                _append(report_path, "\n## FAIL: 展開物に必須ファイルが無い({})\n\n{}\n".format(label, p))
                print("FAIL: 展開物に必須ファイルが無い({}): {}".format(label, p))
                return 1

        # --- 3'. 負の対照(4.6a/4.6b): ensure_blender.ps1のfail-closed確認のみ行い終了 ---
        # (通常の変換フローには進まない。実行するのはこの展開物自身のensure_blender.ps1)
        if args.ensure_blender_bad_url:
            rc = run_ensure_blender_negative_control(
                ensure_blender_ps1, internal_root,
                ["-DownloadUrlOverride",
                 "https://download.blender.org/release/Blender4.3/does-not-exist-negctrl.zip"],
                report_path, "SourceZipなし+無効URL注入(4.6a)")
            ok = (rc == 0)
            return rc
        if args.ensure_blender_corrupt_cache:
            if not os.path.isfile(args.blender_cache_zip):
                _append(report_path, "\n## FAIL: --blender-cache-zipが見つからない: {}\n".format(
                    args.blender_cache_zip))
                print("FAIL: --blender-cache-zipが見つからない: {}".format(args.blender_cache_zip))
                return 1
            corrupt_zip = os.path.join(work_root, "corrupt_blender_cache.zip")
            shutil.copy(args.blender_cache_zip, corrupt_zip)
            with open(corrupt_zip, "r+b") as f:
                f.seek(1000)
                b = f.read(1)
                f.seek(1000)
                f.write(bytes([(b[0] + 1) % 256]))
            rc = run_ensure_blender_negative_control(
                ensure_blender_ps1, internal_root, ["-SourceZip", corrupt_zip],
                report_path, "SourceZip改竄・SHA256不一致(4.6b)")
            ok = (rc == 0)
            return rc

        # --- 3''. ensure_blender.ps1でBlenderを準備する(正常系。キャッシュzip使用、
        #     実ネットワークに出ない) ---
        if not os.path.isfile(args.blender_cache_zip):
            _append(report_path, "\n## FAIL: --blender-cache-zipが見つからない: {}\n"
                    "(4.7の実DL検証でwork\\u54_unbundle\\cache\\に作成される想定)\n".format(
                        args.blender_cache_zip))
            print("FAIL: --blender-cache-zipが見つからない: {}".format(args.blender_cache_zip))
            return 1
        eb_rc, eb_out = run_ensure_blender(
            ensure_blender_ps1, internal_root, ["-SourceZip", args.blender_cache_zip],
            report_path, "正常系(キャッシュzip使用)")
        if eb_rc != 0:
            print("FAIL: ensure_blender.ps1が失敗した(rc={})".format(eb_rc))
            _append(report_path, "\n## FAIL: ensure_blender.ps1が失敗した(rc={})\n".format(eb_rc))
            return 1
        if not os.path.isfile(blender_exe):
            _append(report_path, "\n## FAIL: ensure_blender.ps1は成功終了したがblender.exeが無い: {}\n".format(
                blender_exe))
            print("FAIL: ensure_blender.ps1後もblender.exeが無い: {}".format(blender_exe))
            return 1
        print("ensure_blender.ps1 OK: {}".format(blender_exe))

        # --- 4. job.json組み立て ---
        job_dir = "{}:\\wp6job".format(letter)
        job_path = os.path.join(job_dir, "job.json")
        palworld_pak = find_real_palworld_pak()
        write_job_json(job_path, blender_exe, vrm_addon_zip, palworld_pak, "wp6_t2_distsmoke")
        _append(report_path, "\n## 4. job.json\n\n- job: {}\n- blender_exe(展開物): {}\n"
                "- vrm_addon_zip(展開物): {}\n- vrm_path(repo読取専用): {}\n"
                "- palworld_pak: {}\n".format(
                    job_path, blender_exe, vrm_addon_zip, DEFAULT_VRM_PATH, palworld_pak or "(convert.ps1既定値)"))
        print("job.json -> {}".format(job_path))

        # --- 5. 敵対環境+変換実行 ---
        env = build_hostile_env()
        convert_log = os.path.join(work_root, "convert_full_log.txt")
        _append(report_path, "\n## 5. 変換実行(敵対環境: PYTHONUTF8/PYTHONIOENCODING除去、C:以外のドライブ)\n\n"
                "- 開始: {}\n".format(_now()))
        t1 = time.time()
        success, out, attempts = run_convert(
            convert_ps1, job_path, env, convert_log,
            max_retries=args.max_retries, retry_wait=args.retry_wait,
            mutex_wait_ms=args.mutex_wait_ms)
        elapsed2 = time.time() - t1
        detail["convert_elapsed_sec"] = elapsed2
        detail["convert_attempts"] = attempts

        # dev#288 提案3: 合否判定には一切使わない観測専用の副産物。
        # パース失敗時もdetailにNoneが入るだけで、以降の成否判定を分岐させない。
        phase_times = parse_convert_phase_times_sec(out)
        detail["convert_phase_times_sec"] = phase_times
        try:
            with open(os.path.join(work_root, "convert_phase_times.json"), "w", encoding="utf-8") as f:
                json.dump(phase_times, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # 保存失敗は診断能力の劣化に留め、合否判定には影響させない

        tail = out[-4000:]
        if not success:
            _append(report_path, "\n### FAIL: 変換失敗(試行{}回、所要{:.1f}秒)\n\n```\n{}\n```\n".format(
                attempts, elapsed2, tail))
            print("FAIL: 変換失敗(試行{}回)".format(attempts))
            return 1

        # --- 6. pak生成確認 ---
        expected_pak = os.path.join(job_dir, "build", "wp6_t2_distsmoke_PlayerSwap_P.pak")
        if not os.path.isfile(expected_pak):
            _append(report_path, "\n### FAIL: 変換は成功終了したがpakが見つからない\n\n期待パス: {}\n"
                    "```\n{}\n```\n".format(expected_pak, tail))
            print("FAIL: pakが見つからない: {}".format(expected_pak))
            return 1
        pak_size = os.path.getsize(expected_pak)
        _append(report_path, "\n### PASS: 変換完走(試行{}回、所要{:.1f}秒)\n\n"
                "- pak: {}\n- サイズ: {:,} bytes\n\n```\n{}\n```\n".format(
                    attempts, elapsed2, expected_pak, pak_size, tail[-1500:]))
        print("PASS: pak生成確認 ({:,} bytes)".format(pak_size))
        ok = True
        return 0

    finally:
        if letter and not args.skip_cleanup:
            unmounted, umount_out = subst_unmount(letter)
            _append(report_path, "\n## クリーンアップ\n\n- subst解除({}:): {}\n".format(
                letter, "OK" if unmounted else "FAIL: " + umount_out))
            print("subst解除: {}".format("OK" if unmounted else "FAIL"))
            if os.path.isdir(extract_dir):
                try:
                    shutil.rmtree(extract_dir, ignore_errors=True)
                    _append(report_path, "- 展開物削除: OK\n")
                except Exception as e:
                    _append(report_path, "- 展開物削除: FAIL: {}\n".format(e))
        _append(report_path, "\n## 結果: {}\n".format("PASS" if ok else "FAIL"))


if __name__ == "__main__":
    sys.exit(main())
