# pipeline_runner.py -- 変換パイプラインの起動契約
# (旧 app\DiveToPalworld.cs の WriteJob/BuildConvertScriptPath/BuildConvertArgs/
#  FindPwsh/RunPipeline/RunUnityExport 相当)。
#
# 正本: C:\P\Work\DiveToPalworld\work\wp532A\DESIGN.md §2.1(convert.ps1起動契約と
# job.jsonスキーマ)/ §4.3(非同期処理方式)。移植元行番号(app\DiveToPalworld.cs):
#   - SanitizeName()                 L.1734-1742
#   - AssetSubDir()                  L.1752-1757
#   - FindFirst()                    L.1862-1867
#   - FindBlender()                  L.1836-1861 (TryGetShortBlenderPathの
#     NTFSジャンクション最適化 L.1889- は移植対象外。dev#149のMAX_PATH対策
#     であり、job.jsonの値の正しさ自体には影響しない性能最適化のため
#     〈本WPの合理的解釈。DESIGN.md §5.2 A2の受入条件はjob.jsonのスキーマ・
#     起動コマンドの契約一致であり、パス短縮策の有無は対象外〉)
#   - WriteJob()                     L.1771-1817
#   - BuildConvertScriptPath()       L.1824-1827
#   - BuildConvertArgs()             L.1829-1834
#   - FindPwsh()                     L.2721-2739
#   - RunPipeline()                  L.2547-2607
#   - RunUnityExport()               L.2612-2682
#   - AppendLog()の##PROGRESS##/##AVATAR_WARNING##解析とANSI除去 L.2829-2883
#   - Strings.ProgressLabelTemplates (可変部を含む進捗ラベル)  L.352-362
#
# 書き込み許可(DESIGN.md §5.2 WP-A2行): このファイル +
# app_py\ui\main_window.py の該当ハンドラ部分のみ。
#
# 指揮者裁定(dev#532 A2発進指示): job.jsonへ`engine_mode: "noue"`を明示的に書く
# (DESIGN.md §6-1で指摘された既存ドリフトの解消。gui_wiring_check.pyの必須キー
# には含まれないが、pipeline\cli\convert.ps1は`$cfg.engine_mode`を読み、
# `$Step01IgnoredKeys`にも既に列挙済みの正規のトップレベルキーであるため、
# 追加しても既存契約と衝突しない)。
#
# 依存モジュールの解決: main_window.py と同じ流儀(app_pyディレクトリを
# sys.pathへ入れてから絶対importする)。
from __future__ import annotations

import glob
import json
import os
import queue
import re
import string
import subprocess
import sys
import threading
from typing import Callable, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import settings  # noqa: E402

# ---------------------------------------------------------------------------
# job.jsonスキーマ定数(DESIGN.md §2.1)
# ---------------------------------------------------------------------------

PAL_WINDOWS_PAK_NAME = "Pal-Windows.pak"  # DiveToPalworld.cs L.2985 PalWindowsPakName

# 指揮者裁定によりconvert.ps1の既定と明示的に一致させる(§0. モジュールdocstring参照)。
ENGINE_MODE = "noue"


# ---------------------------------------------------------------------------
# パス解決ヘルパー(SanitizeName/AssetSubDir/FindFirst/FindBlender/PaksDirQuiet相当)
# ---------------------------------------------------------------------------

_SANITIZE_ALLOWED = set(string.ascii_letters + string.digits)


def sanitize_name(name: str) -> str:
    """SanitizeName() L.1734-1742相当。ASCII英数字以外を捨て、空ならAvatarへ。"""
    kept = "".join(c for c in name if c in _SANITIZE_ALLOWED)
    return kept if kept else "Avatar"


def asset_sub_dir(app_root: str, name: str) -> str:
    """AssetSubDir() L.1752-1757相当。配布zip(assets\\配下)/開発チェックアウト
    (リポジトリ直下)のどちらでも動くフォールバック。"""
    dist = os.path.join(app_root, "assets", name)
    if os.path.isdir(dist):
        return dist
    return os.path.join(app_root, name)


def find_first(directory: str, pattern: str) -> Optional[str]:
    """FindFirst() L.1862-1867相当。ディレクトリが無ければNone、一致が無ければNone。
    C#のDirectory.GetFileSystemEntriesはOS依存順序で先頭を返すが、Python版は
    再現性のためソート順の先頭を返す(値の存在有無という契約自体は変えない、
    複数一致時の決定性を上げる合理的な差分)。"""
    if not os.path.isdir(directory):
        return None
    hits = sorted(glob.glob(os.path.join(directory, pattern)))
    return hits[0] if hits else None


def find_blender(app_root: str) -> str:
    """FindBlender() L.1836-1861相当(NTFSジャンクション短縮は移植対象外、
    モジュールdocstring参照)。見つからなければ"blender.exe"(PATH解決に委ねる
    C#既存の最終フォールバックと同じ)。"""
    candidates = [
        find_first(asset_sub_dir(app_root, "tools"), "blender-*-windows-x64"),
        r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64",
    ]
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "blender.exe")):
            return os.path.join(c, "blender.exe")
    return "blender.exe"


def _paks_dir_has_pak(paks_dir: Optional[str]) -> bool:
    return bool(paks_dir) and os.path.isfile(os.path.join(paks_dir, PAL_WINDOWS_PAK_NAME))


def paks_dir_quiet(app_root: str) -> Optional[str]:
    """PaksDirQuiet() L.3328-3342相当の簡略版。settings_paksdir.txt に保存済みの
    キャッシュのみを見て、ダイアログはもちろんSteamライブラリの生自動探索
    (SteamRootCandidates/SteamLibraryRoots、レジストリ読取を伴う)も行わない。
    その自動発見の完全実装は pak_manager.py(WP-A4、DESIGN.md §2.3/§5.2)の
    責務であり、本WPの書き込み許可ファイルには含まれない
    〈WP-A2の合理的解釈〉。未解決ならNoneを返し、呼び出し側(write_job)は
    §2.1のとおりpaths.palworld_pakキーを省略する(「省略可」と明記されている)。
    """
    cached = settings.load_paksdir(app_root)
    if _paks_dir_has_pak(cached):
        return cached
    return None


# ---------------------------------------------------------------------------
# RestoreSettings() L.1621-1628 前段(job.json読み込み)相当
# ---------------------------------------------------------------------------


def read_job(job_json_path: str) -> Optional[dict]:
    """RestoreSettings(string jobJson, bool setVrmPath) L.1621-1628のうち、
    ファイル読み込み+パース部分だけを切り出した純粋関数(dev#605/#616/#623)。
    存在しない/読めない/壊れたJSONはNoneを返す(RestoreSettingsの
    `if (!File.Exists(jobJson)) return;` および続く `try { json = ... }
    catch (Exception) { return; }` と同じ「読めなければ静かに復元しない」方針)。
    py側job.jsonは自前生成のUTF-8正規JSON(pipeline_runner.write_job()参照)
    なのでC#側の自前regex読み取り(JsonStr/JsonNum/JsonBool/JsonStrArray)では
    なくjson.loadで足りる(pak_manager.resolve_delete_targets()が既に同じ
    流儀でjob.jsonを読んでいる、DESIGN.md §2.5と同じ理由)。"""
    if not os.path.isfile(job_json_path):
        return None
    try:
        with open(job_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# WriteJob() 相当
# ---------------------------------------------------------------------------


def write_job(
    app_root: str,
    work_root: str,
    vrm_path: str,
    *,
    shoulder_offset_deg: int = 0,
    merge_fingers: bool = False,
    unlit: bool = False,
    force_two_sided: bool = True,
    shadow_bar_value: int = 30,
    drop_bones_text: str = "",
    license_confirmed: bool = False,
) -> str:
    """WriteJob() L.1771-1817相当。job.jsonを書き出し、そのファイルパスを返す。

    shoulder_offset_deg/merge_fingers/unlit/force_two_sidedの既定値は
    DiveToPalworld.cs L.1042-1046のコメント「内部互換性のためにフィールドを
    初期化(UIには表示しない)」に書かれた初期値そのもの(shoulderBar.Value=0,
    mergeFingersCheck.Checked=false, unlitCheck.Checked=false,
    twoSidedCheck.Checked=true)。これらはWP-A1の骨格(main_window.py)にも
    対応する可視ウィジェットが無い隠しフィールドであり、呼び出し側が
    以前のjob.jsonから復元した値を渡せるようキーワード引数にしてある
    (復元ロジック自体=SetVrmのjob.json読込はWP-A2のスコープ外)。
    """
    name = sanitize_name(os.path.splitext(os.path.basename(vrm_path))[0])
    job_dir = os.path.join(work_root, name)
    os.makedirs(job_dir, exist_ok=True)

    blender = find_blender(app_root)
    addon_zip = find_first(
        asset_sub_dir(app_root, "third_party"), "VRM_Addon_for_Blender-Extension*.zip"
    )
    # C#のJ(addonZip)はnullだと素朴に.Replace()を呼びNullReferenceExceptionで
    # 落ちる(gui_wiring_check.pyがフィクスチャを必ず用意しているのはこのため、
    # 既存の許容されたスキ)。Python版はここをnull安全にし、見つからなければ
    # 空文字列を書く(実運用ではthird_party配下に同梱されており通常到達しない
    # パスだが、クラッシュより「空のパスで後段が明確に失敗する」方を選ぶ、
    # CLAUDE.mdの「実装したと効いているは別」「値を寄せて合わせない」の精神に
    # 沿った意図的な改善。DESIGN.md §2.1のスキーマ契約〈キーは常に存在する〉は
    # 崩さない)。
    if addon_zip is None:
        addon_zip = ""

    drop_bones = [b.strip() for b in drop_bones_text.split(",") if b.strip()]
    shadow_lift = round((100 - shadow_bar_value) / 100.0, 3)

    job: dict = {
        "vrm_path": vrm_path,
        "avatar_name": name,
        "shoulder_offset_deg": shoulder_offset_deg,
        "merge_fingers": bool(merge_fingers),
        "unlit": bool(unlit),
        "force_two_sided": bool(force_two_sided),
        "shadow_lift": shadow_lift,
        "drop_bones": drop_bones,
        "license_confirmed": bool(license_confirmed),
        "engine_mode": ENGINE_MODE,
        "paths": {
            "blender_exe": blender,
            "vrm_addon_zip": addon_zip,
        },
    }
    paks_dir = paks_dir_quiet(app_root)
    if paks_dir is not None:
        job["paths"]["palworld_pak"] = os.path.join(paks_dir, PAL_WINDOWS_PAK_NAME)

    job_json_path = os.path.join(job_dir, "job.json")
    # File.WriteAllText(jobJson, sb.ToString(), new UTF8Encoding(false)) 相当
    # (BOM無しUTF-8)。ensure_ascii=Falseで非ASCII文字(日本語ファイル名等)を
    # \uXXXXへエスケープせず、C#のJ()(バックスラッシュ/引用符のみエスケープ)
    # と同じ見た目のJSONにする。
    with open(job_json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return job_json_path


# ---------------------------------------------------------------------------
# BuildConvertScriptPath/BuildConvertArgs/FindPwsh 相当
# ---------------------------------------------------------------------------


def build_convert_script_path(app_root: str) -> str:
    """BuildConvertScriptPath() L.1824-1827相当。"""
    return os.path.join(app_root, "pipeline", "cli", "convert.ps1")


def build_convert_args(
    script: str, job_json: str, preview_only: bool = False, materials_only: bool = False
) -> str:
    """BuildConvertArgs() L.1829-1834相当。文字列フォーマットも1:1で踏襲する。"""
    args = '-NoProfile -ExecutionPolicy Bypass -File "{}" -Job "{}"'.format(script, job_json)
    if preview_only:
        args += " -PreviewOnly"
    if materials_only:
        args += " -MaterialsOnly"
    return args


def build_unity_export_script_path(app_root: str) -> str:
    """RunUnityExport() L.2624相当。"""
    return os.path.join(app_root, "pipeline", "cli", "export_from_unity.ps1")


def resolve_unity_export_out_dir(work_root: str, prefab_path: str) -> str:
    """RunUnityExport() L.2630-2631相当(dev#298: workRoot基準のoutDirを明示的に渡す)。"""
    base = os.path.splitext(os.path.basename(prefab_path))[0]
    return os.path.join(work_root, base + "_export")


def build_unity_export_args(script: str, prefab_path: str, out_dir: str) -> str:
    """RunUnityExport() L.2639-2641相当。"""
    return '-NoProfile -ExecutionPolicy Bypass -File "{}" -Prefab "{}" -Out "{}"'.format(
        script, prefab_path, out_dir
    )


def find_pwsh() -> str:
    """FindPwsh() L.2721-2739相当。PATHからpwsh.exeを探し、無ければ
    Program Files\\PowerShell\\7\\pwsh.exe、それも無ければ"powershell.exe"。"""
    path_env = os.environ.get("PATH", "")
    for d in path_env.split(os.pathsep):
        try:
            cand = os.path.join(d.strip(), "pwsh.exe")
            if os.path.isfile(cand):
                return cand
        except OSError:
            continue
    # Environment.GetFolderPath(SpecialFolder.ProgramFiles)相当。Python標準ライブラリに
    # 直接の等価APIが無いため環境変数で近似する(通常の日本語/英語Windows環境では
    # 常にC:\Program Filesを指す。合理的な近似)。
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    pwsh = os.path.join(program_files, "PowerShell", "7", "pwsh.exe")
    if os.path.isfile(pwsh):
        return pwsh
    return "powershell.exe"


# ---------------------------------------------------------------------------
# 標準出力の解析(AppendLog() L.2829-2883相当)
# ---------------------------------------------------------------------------

_ANSI_ESCAPE_RE = re.compile("\x1b\\[[0-9;]*[A-Za-z]")
_PROGRESS_MARK_RE = re.compile(r"##PROGRESS## (\d+) (.*)")
_AVATAR_WARN_RE = re.compile(r"##AVATAR_WARNING## (.*)")


def strip_ansi(line: str) -> str:
    """AnsiEscape正規表現によるANSIカラーコード除去(L.2829, L.2841相当)。"""
    return _ANSI_ESCAPE_RE.sub("", line)


def parse_progress_marker(line: str) -> Optional[tuple[int, str]]:
    """ProgressMark正規表現(L.2830)相当。戻り値: (0-100にクランプ済みpct, 生ラベル)
    またはマッチしなければNone。"""
    m = _PROGRESS_MARK_RE.search(strip_ansi(line))
    if not m:
        return None
    try:
        pct = int(m.group(1))
    except ValueError:
        return None
    return max(0, min(100, pct)), m.group(2).strip()


def parse_avatar_warning(line: str) -> Optional[str]:
    """AvatarWarnMark正規表現(L.2836)相当。"""
    m = _AVATAR_WARN_RE.search(strip_ansi(line))
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Strings.ProgressLabelTemplates 相当(可変部を含む進捗ラベルの動的翻訳)
#
# 指揮者裁定: i18n.py(WP-A1)は固定文字列辞書(ProgressLabels)のみを移植し、
# 可変部を含むテンプレート判定は進捗リレー機構と一体のこちら(WP-A2)が担当する
# (DESIGN.md §5.2 A2行「進捗ラベルの動的翻訳(ProgressLabelTemplates)は本WPの
# 担当(A1が委ねた分)」)。
# ---------------------------------------------------------------------------

_PROGRESS_LABEL_TEMPLATES: list[tuple[re.Pattern, dict[str, str]]] = [
    (
        re.compile(r"^Retargeting skeleton \+ preview \(parallel: (.+)\)$"),
        {
            "ja": "スケルトン+プレビューをリターゲット中(並列: {0})",
            "en": "Retargeting skeleton + preview (parallel: {0})",
            "ko": "스켈레톤+미리보기 리타겟 중(병렬: {0})",
            "zhTW": "正在重新定位骨架+預覽(平行: {0})",
            "zhCN": "正在重新定位骨架+预览(并行: {0})",
        },
    ),
    (
        re.compile(r"^Retargeting skeleton \((.+)\)$"),
        {
            "ja": "スケルトンをリターゲット中({0})",
            "en": "Retargeting skeleton ({0})",
            "ko": "스켈레톤 리타겟 중({0})",
            "zhTW": "正在重新定位骨架({0})",
            "zhCN": "正在重新定位骨架({0})",
        },
    ),
    (
        re.compile(r"^Generating preview image \((.+)\)$"),
        {
            "ja": "プレビュー画像を生成中({0})",
            "en": "Generating preview image ({0})",
            "ko": "미리보기 이미지 생성 중({0})",
            "zhTW": "正在產生預覽圖({0})",
            "zhCN": "正在生成预览图({0})",
        },
    ),
]


def translate_progress_label_dynamic(raw: str, lang: Optional[str] = None) -> str:
    """TranslateProgressLabelFrom() L.381-404相当の完全版(固定辞書+テンプレート)。
    固定辞書(i18n.PROGRESS_LABELS)を優先し、無ければ可変部テンプレートを試し、
    どちらにも一致しなければ原文をそのまま返す(未知ラベル=無表示を作らない
    ブラックリスト方式、L.309のコメントどおり踏襲)。"""
    if not raw:
        return raw
    if raw in i18n.PROGRESS_LABELS:
        return i18n.translate_progress_label(raw, lang)
    lang = lang or i18n.current_lang
    for pattern, fmt_table in _PROGRESS_LABEL_TEMPLATES:
        m = pattern.match(raw)
        if not m:
            continue
        fmt = fmt_table.get(lang) or fmt_table.get("ja")
        if not fmt:
            return raw
        try:
            return fmt.format(m.group(1))
        except (IndexError, KeyError):
            return raw
    return raw


# ---------------------------------------------------------------------------
# 非同期プロセス実行(RunPipeline/RunUnityExport の非同期部分、DESIGN.md §4.3)
#
# tkinterはメインスレッド以外からのウィジェット操作を許さないため、
# threading.Thread(子プロセスの出力読み取り) + queue.Queue(受け渡し) +
# root.after()によるポーリング、という定番パターンを採る。このモジュール自体は
# tkinterに依存しない(pytestからheadlessにテストできるようにするため)。
# ---------------------------------------------------------------------------


class ProcessHandle:
    """RunPipeline()/RunUnityExport()が起動する子プロセスの非同期ハンドル。

    使い方: start()で起動し、呼び出し側(main_window.py)はtkinterの
    root.after(ms, handle.poll)で定期的にpoll()を呼ぶ。poll()はUIスレッド
    (=poll()を呼んでいるスレッド)上でon_line/on_exitコールバックを実行する。
    """

    def __init__(
        self,
        shell: str,
        args: str,
        on_line: Callable[[str], None],
        on_exit: Callable[[int], None],
    ):
        self.shell = shell
        self.args = args
        self._on_line = on_line
        self._on_exit = on_exit
        self._proc: Optional[subprocess.Popen] = None
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self.exit_code: Optional[int] = None
        self.job_dir: Optional[str] = None  # RunPipeline: currentPipelineJobDir相当
        self.out_dir: Optional[str] = None  # RunUnityExport: outDir相当

    def start(self) -> None:
        # ProcessStartInfo(shell, args){UseShellExecute=false,
        # RedirectStandardOutput/Error=true, CreateNoWindow=true,
        # StandardOutputEncoding=StandardErrorEncoding=UTF8} 相当。
        # 環境変数は一切明示操作しない(env=Noneで親プロセスの環境をそのまま
        # 継承、DESIGN.md §2.1のA8ゲートcheck_env_contract相当の性質を維持)。
        # C#はOutputDataReceived/ErrorDataReceivedを別々に購読するが、どちらも
        # 同じAppendLog()へ渡す設計(L.2580-2587)なので、Python版はstderrを
        # stdoutへ合流させて単一ストリームとして読む(実効的な挙動は同じ、
        # 行の混ざり順序だけがOS/バッファリング依存になりうる合理的な簡略化)。
        cmdline = '"{}" {}'.format(self.shell, self.args)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            cmdline,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=None,
            creationflags=creationflags,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None
        try:
            if proc.stdout is not None:
                for raw_line in proc.stdout:
                    self._queue.put(("line", raw_line.rstrip("\r\n")))
        finally:
            code = proc.wait()
            self.exit_code = code
            self._queue.put(("exit", code))

    def poll(self) -> None:
        """tkinterのroot.after()から定期呼び出しする(§4.3のqueue.Queue+afterパターン)。
        呼び出し中のスレッド上でon_line/on_exitを実行する。dev#592層3(本丸):
        1行分のon_line呼び出しを行単位try/exceptで包む。ログ表示の失敗
        (例: UnicodeEncodeError)が1行で起きても、残りの行とexitイベント
        (完了処理: プレビュー反映・完了通知)を止めてはならない。"""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "line":
                    try:
                        self._on_line(payload)  # type: ignore[arg-type]
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    self._on_exit(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def kill(self) -> None:
        """CancelConversion/KillConversion相当。プロセスツリーごと終了する
        (DESIGN.md §1.1 #6備考: taskkill /T /Fで足りるとされている方式を採用)。"""
        if self._proc is None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                    capture_output=True,
                )
            else:
                self._proc.terminate()
        except OSError:
            pass


def run_pipeline(
    app_root: str,
    work_root: str,
    vrm_path: str,
    *,
    preview_only: bool = False,
    materials_only: bool = False,
    on_line: Callable[[str], None],
    on_exit: Callable[[int], None],
    shoulder_offset_deg: int = 0,
    merge_fingers: bool = False,
    unlit: bool = False,
    force_two_sided: bool = True,
    shadow_bar_value: int = 30,
    drop_bones_text: str = "",
    license_confirmed: bool = False,
) -> ProcessHandle:
    """RunPipeline() L.2547-2607相当。job.json書き出し→convert.ps1起動までを
    1呼び出しで行い、非同期ハンドルを返す。UIの状態遷移(busyBar/statusLabel/
    cancelButton等)はmain_window.py側がハンドルとon_line/on_exitコールバックを
    使って組み立てる(このモジュールはtkinterに依存しない)。"""
    job_json = write_job(
        app_root,
        work_root,
        vrm_path,
        shoulder_offset_deg=shoulder_offset_deg,
        merge_fingers=merge_fingers,
        unlit=unlit,
        force_two_sided=force_two_sided,
        shadow_bar_value=shadow_bar_value,
        drop_bones_text=drop_bones_text,
        license_confirmed=license_confirmed,
    )
    script = build_convert_script_path(app_root)
    args = build_convert_args(script, job_json, preview_only, materials_only)
    shell = find_pwsh()
    handle = ProcessHandle(shell, args, on_line, on_exit)
    handle.job_dir = os.path.dirname(job_json)
    handle.start()
    return handle


def run_unity_export(
    app_root: str,
    work_root: str,
    prefab_path: str,
    *,
    on_line: Callable[[str], None],
    on_exit: Callable[[int], None],
) -> ProcessHandle:
    """RunUnityExport() L.2612-2682相当(実プロセス起動部分)。"""
    script = build_unity_export_script_path(app_root)
    out_dir = resolve_unity_export_out_dir(work_root, prefab_path)
    args = build_unity_export_args(script, prefab_path, out_dir)
    shell = find_pwsh()
    handle = ProcessHandle(shell, args, on_line, on_exit)
    handle.out_dir = out_dir
    handle.start()
    return handle


# ---------------------------------------------------------------------------
# busyBarのモード切替(dev#602: prefab変換で進捗マーカーが来ない長区間、busyBar
# が静止して見える問題)。
#
# C#版の実挙動(自由設計しない。以下がすべて):
#   - RunPipeline() L.2602-2603: busyBar.Style = Continuous; Value = 0
#     (フル変換=convert_noue.pyが開始直後から##PROGRESS##を出し続ける工程。
#     終始Continuousで、値はAppendLog() L.2849の`busyBar.Value = pct`のみで動く)
#   - RunUnityExport() L.2677-2679: 「実進捗マーカーが無い工程(Unity起動〜
#     インポート〜ベイク〜輸出)なのでマーキー表示にする」
#     busyBar.Style = Marquee; MarqueeAnimationSpeed = 30
#     (この工程は構造的に##PROGRESS##が一切来ない。C#はタイムアウト監視等は
#     持たず、工程の頭からMarquee固定)
#   - OnUnityExportDone() L.2686: busyBar.Style = Continuous
#     (成否に関わらず無条件でContinuousへ戻す)
#
# つまり「マーカーが長時間途絶えたらMarqueeへ」という汎用タイマーはC#に
# 存在しない。実際の切替単位は「工程(phase)」であり、フル変換は終始
# determinate、Unity輸出は終始indeterminateである。
# ---------------------------------------------------------------------------

BUSY_BAR_MODE_DETERMINATE = "determinate"
BUSY_BAR_MODE_INDETERMINATE = "indeterminate"

PHASE_PIPELINE = "pipeline"
PHASE_UNITY_EXPORT = "unity_export"


def initial_busy_bar_mode(phase: str) -> str:
    """RunPipeline() L.2602(Continuous)とRunUnityExport() L.2678(Marquee)の
    分岐を純関数化したもの。phase=PHASE_UNITY_EXPORTのみindeterminate
    (ttk Progressbarのmarquee相当)、それ以外(PHASE_PIPELINE、および未知の
    phase文字列に対する安全側フォールバック)はdeterminate。"""
    if phase == PHASE_UNITY_EXPORT:
        return BUSY_BAR_MODE_INDETERMINATE
    return BUSY_BAR_MODE_DETERMINATE


def busy_bar_mode_on_marker() -> str:
    """AppendLog()で##PROGRESS##行を受け取った時点のbusyBarモード。C#版は
    busyBar.Value = pctを代入するだけだが、それが意味を持つのはStyleが
    Continuousのときだけ(Marquee中はValueを見た目に反映しないWinForms仕様)。
    py版のttk.Progressbarはindeterminate中に["value"]を設定しても表示に
    反映されないため、マーカー到着時は明示的にdeterminateへ戻してから値を
    入れる(構造的にはUnity輸出工程では発生しない防御的な扱いだが、
    「マーカーが来た=実進捗が分かっている」を安全側で保証する)。"""
    return BUSY_BAR_MODE_DETERMINATE


# ---------------------------------------------------------------------------
# 早期プレビュー反映(dev#288 WP-UXIMPL提案2、DiveToPalworld.cs L.2854-2870/
# L.2957-2963相当。dev#532方針A WP-A11/dev#549で移植)。
#
# Phase1完了(39%到達)時点でプレビュー画像は既に生成済み(gender並列ブロックの
# render_preview.py実行が担当)。OnPipelineDone(全工程完了後)を待たず1回だけ
# 再読込することで、フル変換パスでの新プレビュー反映が30〜59秒早まる。
#
# 実際の画像デコード・PictureBox/Label反映(Pillow/ImageTk同梱)はB1完了後の
# WPが担う(main_window.py・DESIGN.md §1.1 #15備考のとおり、previewFront/
# previewSideは現状プレースホルダのTk Label)。ここでは「呼ぶべきタイミングか」
# の判定(should_load_early_preview、AppendLog L.2860の if 条件を純関数化)と
# 「どのファイルを読むか」の解決(load_previews、LoadPreviews L.2957-2963の
# ファイル存在確認部分)のみを、GUIフレームワーク非依存の形でここに置く
# (既存のDetectLangFromCulture/DecideBlenderSetupAction等と同じ「判定ロジック
# だけを純関数化してテスト容易にする」設計idiomを踏襲)。
# ---------------------------------------------------------------------------

EARLY_PREVIEW_THRESHOLD = 39


def should_load_early_preview(pct: int, already_loaded: bool) -> bool:
    """AppendLog() L.2860の判定
    `pct >= 39 && !earlyPreviewLoadedThisRun` を純関数化したもの。"""
    return pct >= EARLY_PREVIEW_THRESHOLD and not already_loaded


def load_previews(job_dir: str) -> dict[str, Optional[str]]:
    """LoadPreviews() L.2957-2963相当のうち、ファイル解決部分(純粋・読み取り
    のみ、書き込みなし)。存在しないファイルはNoneを返す(呼び出し側は
    Noneのキーを「画像なし」として扱う。C#のif (File.Exists(...))と同じ
    「無ければ何もしない」方針)。"""
    front = os.path.join(job_dir, "converted", "preview_male_stand.png")
    side = os.path.join(job_dir, "converted", "preview_male_stand_side.png")
    return {
        "front": front if os.path.isfile(front) else None,
        "side": side if os.path.isfile(side) else None,
    }


def find_exported_fbx(out_dir: str) -> Optional[str]:
    """OnUnityExportDone() L.2701-2707相当。輸出フォルダから最初の*.fbxを返す。"""
    if not os.path.isdir(out_dir):
        return None
    hits = sorted(glob.glob(os.path.join(out_dir, "*.fbx")))
    return hits[0] if hits else None
