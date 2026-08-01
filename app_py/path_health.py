# path_health.py -- パス健全性判定・workRootフォールバック・起動時セルフチェック
# (DESIGN.md §2.8、§5.2 WP-A6行)。
#
# 移植元1: app\DiveToPalworld.cs のPathHealth系(dev#134、L.5631-5768・L.6402-6421):
#   - PathHealthFacts (struct, L.6414-6421)
#   - BuildPathFacts / PathHealthHasTooLong / PathHealthProblem / PathHealthLine
#     (L.5646-5676)
#   - CheckPathHealthLogic (L.5678-5754, --check-path-health隠しCLIの検査本体)
#
# 移植元2: workRootの書き込み可否+自動フォールバック(dev#298、L.5770-5887・
# L.6423-6478):
#   - WorkRootResolution (struct, L.6435-6444)
#   - WorkRootResolveLogic.Resolve (L.6446-6477)
#   - ProbeWorkRootWritable (実I/O、L.5788-5802)
#   - CheckWorkRootFallbackLogic (L.5804-5873, --check-work-root-fallback隠しCLI)
#
# 移植元3: 起動時セルフチェック(dev#532コメント記載の「環境隔離4層」の④、
# C#に前例なし・Python配布(embeddable+tkinter同梱、DESIGN.md §3)に伴う新規要件)。
# 指揮者裁定: sys.executableがアプリ配下(同梱embeddable Python)かどうか、
# 同梱バージョンとアプリ本体のバージョンが一致するかを起動時に検査し、
# 不一致ならUchinoko.bat経由での起動を促す(想定事故: ユーザーが同梱exe/batを
# 経由せずpython.exeやmain.pyを直接叩く、または新旧のpython_embedが混在した
# 中途半端な更新状態で起動する)。判定不能(情報が渡ってこない)ケースは
# PathHealthLogic case6/7と同じ「黙って動く」安全側に倒す(WP-A6の合理的解釈。
# バージョン同梱ファイルの正式な設置場所自体はB1(packaging)の担当のため、
# ここでは値を受け取って比較するだけの純粋関数として設計し、統合はB1/main.py側)。
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, List, Optional

# ---------------------------------------------------------------------------
# パス健全性(dev#134)
# ---------------------------------------------------------------------------

# PathLengthWarnThreshold (L.5644)。WindowsのMAX_PATH(260)から、変換パイプ
# ラインが後段で継ぎ足す典型的なサブパス分の余裕を差し引いた値(実測合わせの
# 調整ではない、L.5638-5640)。
PATH_LENGTH_WARN_THRESHOLD = 200


@dataclass
class PathHealthFacts:
    """1つのパス(インストール先/作業先)の健全性を表す事実(L.6414-6421)。"""

    label: str
    length: int = 0
    non_ascii: bool = False
    unc: bool = False
    under_onedrive: bool = False


def build_path_facts(
    label: str, path: Optional[str], onedrive_root_or_none: Optional[str]
) -> PathHealthFacts:
    """BuildPathFacts(L.5646-5656)相当。空/None パスは例外を投げず、長さ0・
    問題なしとして扱う(case7の保険経路)。"""
    f = PathHealthFacts(label=label)
    if not path:
        return f
    f.length = len(path)
    f.non_ascii = any(ord(c) > 127 for c in path)
    f.unc = path.startswith("\\\\")
    if onedrive_root_or_none:
        f.under_onedrive = path.lower().startswith(onedrive_root_or_none.lower())
    return f


def path_health_has_too_long(f: PathHealthFacts) -> bool:
    """PathHealthHasTooLong(L.5658)相当。"""
    return f.length > PATH_LENGTH_WARN_THRESHOLD


def path_health_problem(f: PathHealthFacts) -> bool:
    """PathHealthProblem(L.5660-5663)相当。非ASCII単独はproblem扱いにしない
    (日本語ユーザー名配下は珍しくないため、ノイズになるだけ、L.5735-5736)。"""
    return path_health_has_too_long(f) or f.unc or f.under_onedrive


def path_health_line(f: PathHealthFacts) -> str:
    """PathHealthLine(L.5665-5676)相当。"""
    notes: List[str] = []
    if path_health_has_too_long(f):
        notes.append(f"length {f.length} > {PATH_LENGTH_WARN_THRESHOLD}")
    if f.unc:
        notes.append("UNC path (unsupported)")
    if f.under_onedrive:
        notes.append("under OneDrive (sync can lock files during conversion)")
    if f.non_ascii:
        notes.append("non-ASCII characters")
    status = "risk" if path_health_problem(f) else "ok"
    detail = f" [{', '.join(notes)}]" if notes else ""
    return f"{f.label}_path: {status} (len={f.length}){detail}"


# ---------------------------------------------------------------------------
# workRoot書き込み可否+自動フォールバック(dev#298)
# ---------------------------------------------------------------------------


def probe_work_root_writable(directory: str) -> Optional[str]:
    """ProbeWorkRootWritable(L.5788-5802)相当。実際にディレクトリを作成し、
    一時ファイルを書いて消せるかで書き込み可否を判定する。書き込めればNone、
    書き込めなければ例外メッセージ文字列を返す。"""
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, f".write_probe_{os.urandom(8).hex()}.tmp")
        with open(probe, "w", encoding="utf-8") as fp:
            fp.write("ok")
        os.remove(probe)
        return None
    except OSError as ex:
        return f"{type(ex).__name__}: {ex}"


@dataclass
class WorkRootResolution:
    """workRoot解決の結果(L.6435-6444)。pathは常に非None(両方失敗しても
    フォールバック先のパス文字列を入れておく、呼び出し側が後続処理で
    クラッシュしないための安全なデフォルト)。"""

    path: str
    used_fallback: bool = False
    failed: bool = False
    primary_path: str = ""
    fallback_path: str = ""
    primary_error: Optional[str] = None
    fallback_error: Optional[str] = None


def resolve_work_root(
    primary_path: str, fallback_path: str, probe: Callable[[str], Optional[str]]
) -> WorkRootResolution:
    """WorkRootResolveLogic.Resolve(L.6454-6477)相当。primary_pathへの書き込みを
    probeで試す。書ければそのまま使う。書けなければfallback_pathを試し、書ければ
    そちらへ切り替える(used_fallback=True)。どちらも書けなければfailed=Trueで
    両方のエラーを持ち帰る。probeは書き込み不可を表す非Noneエラー文字列、
    書き込み可能ならNoneを返す関数(実装はprobe_work_root_writable、テストでは
    スタブに差し替え可能)。"""
    primary_error = probe(primary_path)
    if primary_error is None:
        return WorkRootResolution(
            path=primary_path, primary_path=primary_path, fallback_path=fallback_path
        )
    fallback_error = probe(fallback_path)
    if fallback_error is None:
        return WorkRootResolution(
            path=fallback_path,
            used_fallback=True,
            primary_path=primary_path,
            fallback_path=fallback_path,
            primary_error=primary_error,
        )
    # 両方失敗でも下流コードが安全に動けるよう、フォールバック先のパス文字列だけは
    # 残す(L.6471-6476のコメントそのまま)
    return WorkRootResolution(
        path=fallback_path,
        failed=True,
        primary_path=primary_path,
        fallback_path=fallback_path,
        primary_error=primary_error,
        fallback_error=fallback_error,
    )


# ---------------------------------------------------------------------------
# 起動時セルフチェック(dev#532「環境隔離4層」の④、C#に前例なし)
# ---------------------------------------------------------------------------

MSG_LAUNCH_VIA_BAT = "Uchinoko.batから起動してください / Please launch via Uchinoko.bat"


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def runtime_executable_ok(sys_executable: Optional[str], app_root: Optional[str]) -> bool:
    """sys.executable(実行中のPythonインタプリタ本体)がapp_root配下(同梱
    embeddable Python)にあるかを判定する。どちらかの情報が渡ってこない場合は
    判定不能として黙って通す(PathHealthLogic case6/7と同じ安全側の方針)。"""
    if not sys_executable or not app_root:
        return True
    exe = _normalize(sys_executable)
    root = _normalize(app_root)
    root_with_sep = root if root.endswith(os.sep) else root + os.sep
    return exe == root or exe.startswith(root_with_sep)


def runtime_version_ok(bundled_version: Optional[str], expected_version: Optional[str]) -> bool:
    """同梱Python環境に添えられたバージョン文字列と、アプリ本体が期待する
    バージョンが一致するかを判定する。どちらかが不明(None/空)なら判定不能
    として黙って通す(新旧混在の検出が目的であり、情報が無い時に誤検知で
    ブロックしないことを優先する)。"""
    if not bundled_version or not expected_version:
        return True
    return bundled_version == expected_version


@dataclass
class RuntimeEnvironmentStatus:
    executable_ok: bool
    version_ok: bool
    sys_executable: Optional[str] = None
    app_root: Optional[str] = None
    bundled_version: Optional[str] = None
    expected_version: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.executable_ok and self.version_ok


def check_runtime_environment(
    sys_executable: Optional[str],
    app_root: Optional[str],
    bundled_version: Optional[str] = None,
    expected_version: Optional[str] = None,
) -> RuntimeEnvironmentStatus:
    """起動時セルフチェック本体。副作用なし(呼び出し側がsys.executable等の
    実値を集めて渡す)。"""
    return RuntimeEnvironmentStatus(
        executable_ok=runtime_executable_ok(sys_executable, app_root),
        version_ok=runtime_version_ok(bundled_version, expected_version),
        sys_executable=sys_executable,
        app_root=app_root,
        bundled_version=bundled_version,
        expected_version=expected_version,
    )


def runtime_environment_message(status: RuntimeEnvironmentStatus) -> Optional[str]:
    """statusが問題無しならNone、問題があれば案内文言(MSG_LAUNCH_VIA_BAT)を返す。"""
    return None if status.ok else MSG_LAUNCH_VIA_BAT
