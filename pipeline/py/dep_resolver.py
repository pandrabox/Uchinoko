# -*- coding: utf-8 -*-
"""外部依存(ユーザー端末にあると期待している物)の共通resolver(dev#22 / dev#23)。

背景: Palworld本体・Unity・Blender等の「ユーザー端末にある物」の発見が
各所で個別に決め打ち実装されており(C問題・Unity発見問題 dev#22 の共通根因)、
探し方の決め打ちが環境差で「見つからない」を量産していた。
本モジュールは CLAUDE.md「外部依存パスの原則」の三点セット
(①自動発見 → ②手動指定フォールバック → ③探索過程を全部ログへ)を
一手に実装する共通の入口である(入口で正規化、特別扱いを積まない方針。
先例: pipeline\\py\\palworld_locate.py — Palworld側の移行は別WPで本モジュールへ寄せる)。

最初の利用者は Unity エディタの発見(dev#22)。呼び出し元は
pipeline\\cli\\export_from_unity.ps1。**同ps1は探索ロジックを一切持たない殻**で、
本モジュールをCLIとして呼び、マーカー MARKER_RESOLVED / MARKER_FAILED を読むだけ
(dev#21方針: ps1に新規ロジックを書かない)。マーカー文字列・CLI引数・
settings_unityeditor.txt のファイル名を変えるときは ps1 側も必ず更新すること
(convert.ps1⇔fast_repack.pyのERR_*マーカーと同じ「片方だけ変えないこと」方式)。

設計:
  - resolve(name, **kw) が候補戦略を順に試す。優先順位は
      1. 手動指定(設定ファイル <approot>\\settings_unityeditor.txt。
         既存のGUIグローバル設定 settings_paksdir.txt と
         同じ「appRoot直下のフラットtxt」機構を踏襲)
      2. 手動指定(環境変数 D2P_UNITY_EDITOR)
      3. 自動発見(台帳: %APPDATA%\\UnityHub\\editors-v2.json / editors.json /
         secondaryInstallPath.json)
      4. 自動発見(既知パス: %ProgramFiles%\\Unity\\Hub\\Editor 配下の走査)
    自動発見(3・4)の候補はプールし、プロジェクトの完全一致版を最優先、
    無ければ対応系列(2022.3.x)内の最新パッチを選ぶ(パッチ版決め打ち禁止)。
  - 試した全候補と各判定結果を trail(Candidateのリスト)として常に保持する。
    「成功したのに結果が変」の問い合わせでも探索過程が残るようにするため、
    成功時も trail は Resolution に入って返る。
  - どの戦略でも見つからなければ DependencyNotFoundError を送出する。
    メッセージは「探した場所の全列挙(英語のtrail行)+手動指定の方法(日本語)」で、
    「ログをコピー」の中身だけで遠隔診断と自己解決の両方ができる文言にする。
    無言でどこかへフォールバックすることはしない。

標準ライブラリのみ使用(pip禁止。Blender同梱PythonでもシステムPythonでも
動かすため。palworld_locate.py / vp_core.py と同じ制約)。
"""

import json
import os
import re
import sys

# 「python <このファイル>」実行時にPythonが自動でスクリプトの場所をsys.path[0]へ
# 入れるため追加のsys.path操作なしでimportできるが、明示しておく(fast_repack.pyの
# 既存作法を踏襲。頑健性のため)。
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))
if _HERE_DIR not in sys.path:
    sys.path.insert(0, _HERE_DIR)
# dev#325: trail出力(Candidate.format())の生パス正規化。dev#7で新設した
# path_privacy.py(既存の三段防御の一部)を再利用する(新規の伏字化実装を作らない)。
from path_privacy import factify as _factify  # noqa: E402

# このファイルは <appRoot>\pipeline\py\dep_resolver.py に置かれる前提
# (開発リポジトリ直下でも配布物でも、pipeline\ の親 = appRoot。
#  export_from_unity.ps1 の $Root、GUIの appRoot と同じ場所)。
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UNITY_SUPPORTED_FAMILY = "2022.3"  # export_from_unity.ps1 の $SupportedFamily と一致させること
UNITY_SETTINGS_BASENAME = "settings_unityeditor.txt"
ENV_UNITY_EDITOR = "D2P_UNITY_EDITOR"

# CLI出力のマーカー(export_from_unity.ps1 がこの文字列を見る。片方だけ変えないこと)
MARKER_RESOLVED = "D2P_RESOLVED: "
MARKER_FAILED = "D2P_RESOLVE_FAILED"


class Candidate(object):
    """探索した1候補と判定結果(trailの1行分)。"""

    __slots__ = ("path", "source", "verdict", "ok")

    def __init__(self, path, source, verdict, ok):
        self.path = path      # 調べたパス(ファイル/ディレクトリ)
        self.source = source  # どの戦略か(manual-settings / hub-ledger 等)
        self.verdict = verdict  # 英語の判定文(ログにそのまま出す)
        self.ok = ok

    def format(self):
        # dev#325: 生パスをそのまま出さず、path_privacy.factify で正規化する
        # (_APP_ROOT配下なら相対パス、それ以外はファイル名+事実のみ)。
        # 出力の入口(このformat()自身)で正規化することで、成功時のtrail出力
        # (_main の format_trail 経由)と失敗時の DependencyNotFoundError 両方を
        # 一度に塞ぐ(呼び出し元ごとの後付けマスクを増やさない、CLAUDE.mdの方針)。
        # Resolution.path / MARKER_RESOLVED行はここを経由しないため生パスのまま
        # (呼び出し元が実際にUnity.exeを起動するために機能的に必要なため)。
        return "[dep_resolver] %s: %s -> %s" % (
            self.source, _factify(self.path, (_APP_ROOT,)), self.verdict)


class Resolution(object):
    """解決結果。path のほか、どの戦略で決まったかと探索trail全体を持つ。"""

    def __init__(self, name, path, strategy, trail, version=None):
        self.name = name
        self.path = path
        self.strategy = strategy
        self.trail = list(trail)
        self.version = version


class DependencyNotFoundError(RuntimeError):
    """どの戦略でも見つからなかった。.trail に探索過程全体を保持する。

    str(e) は「英語のtrail全行+日本語の手動指定案内」。呼び出し側は
    これをそのまま画面とログに出せばよい(問い合わせは「ログをコピー」のみが頼り)。
    """

    def __init__(self, name, trail, guidance):
        self.name = name
        self.trail = list(trail)
        self.guidance = guidance
        lines = ["[dep_resolver] FAILED to locate '%s'. Search trail:" % name]
        lines.extend(c.format() for c in self.trail)
        lines.append(guidance)
        super(DependencyNotFoundError, self).__init__("\n".join(lines))


def _norm(path):
    return os.path.normpath(path) if path else path


def format_trail(trail):
    return [c.format() for c in trail]


# ---------------------------------------------------------------------------
# Unity エディタ
# ---------------------------------------------------------------------------

_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)([a-z])(\d+)$")


def _unity_version_key(ver):
    """'2022.3.22f1' → 並べ替え可能なタプル。解釈できない形式は最弱。"""
    m = _VER_RE.match(ver or "")
    if not m:
        return (0, 0, 0, "", 0)
    a, b, c, ch, d = m.groups()
    return (int(a), int(b), int(c), ch, int(d))


def _family_of(ver):
    parts = (ver or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else ""


def _resolve_manual_path(raw):
    """手動指定の値から Unity.exe の実パスを求める。

    受け付ける形: Unity.exe へのフルパス / エディタのルートフォルダ
    (<dir>\\Editor\\Unity.exe)/ Editorフォルダ(<dir>\\Unity.exe)。
    見つからなければ None。
    """
    raw = (raw or "").strip().strip('"')
    if not raw:
        return None
    if os.path.isfile(raw) and raw.lower().endswith(".exe"):
        return _norm(raw)
    for sub in (os.path.join("Editor", "Unity.exe"), "Unity.exe"):
        cand = os.path.join(raw, sub)
        if os.path.isfile(cand):
            return _norm(cand)
    return None


def _collect_ledger_editors(node, out):
    """UnityHubの台帳JSONから (version, exe_path) を再帰収集する。

    editors-v2.json(新しめのHub: {"schema_version":..,"data":[{version,location,..}]})と
    editors.json(古いHub: {"2022.3.9f1":{version,location,..},..})の両形状、および
    location が文字列/配列のどちらでも拾えるよう、キー名だけを頼りに全ノードを歩く
    (Hubのバージョン差でトップレベル形状が変わっても壊れないようにするため)。
    """
    if isinstance(node, dict):
        ver = node.get("version")
        loc = node.get("location")
        if isinstance(ver, str) and loc:
            locs = loc if isinstance(loc, list) else [loc]
            for item in locs:
                if isinstance(item, str) and item.strip():
                    out.append((ver, _norm(item.strip())))
        for value in node.values():
            _collect_ledger_editors(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_ledger_editors(value, out)


def _read_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _unity_guidance(settings_path):
    return (
        "\n"
        "Unity editor (%s series) was not found. The trail above is everything that was "
        "actually searched and evaluated.\n"
        "If you have Unity %s series installed and still get this error, save the full "
        "path of your Unity.exe as a single line in the following file and run again "
        "(the manual override always takes priority):\n"
        "  %s\n"
        "Example: C:\\Program Files\\Unity\\Hub\\Editor\\2022.3.22f1\\Editor\\Unity.exe\n"
        "(you can also set the %s environment variable to Unity.exe's full path)\n"
        "If Unity %s series is not installed, install a %s series editor for VRChat via Unity Hub."
    ) % (UNITY_SUPPORTED_FAMILY, UNITY_SUPPORTED_FAMILY, settings_path,
         ENV_UNITY_EDITOR, UNITY_SUPPORTED_FAMILY, UNITY_SUPPORTED_FAMILY)


def resolve_unity_editor(project_version=None, family=UNITY_SUPPORTED_FAMILY,
                         approot=None, appdata=None, hub_roots=None,
                         settings_path=None, env=None):
    """Unity.exe(対応系列の範囲一致)を解決する。

    project_version: プロジェクトの完全なバージョン(例 '2022.3.22f1')。
        自動発見候補の中に同版があればそれを最優先。無ければ family内最新パッチ。
    family: 対応系列(既定 '2022.3')。範囲一致で選ぶ(パッチ版決め打ち禁止)。
    approot/appdata/hub_roots/settings_path/env: テストで実環境を差し替えるための注入点。
        省略時は実環境(appRoot自動判定・%APPDATA%・%ProgramFiles%・os.environ)。

    返り値: Resolution(path=Unity.exe, strategy, trail, version)
    見つからなければ DependencyNotFoundError(trail+日本語案内つき)。
    """
    env = os.environ if env is None else env
    approot = approot or _APP_ROOT
    settings_path = settings_path or os.path.join(approot, UNITY_SETTINGS_BASENAME)
    trail = []

    # --- 戦略1: 手動指定(設定ファイル)。最優先 ---
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8-sig") as f:
                raw = f.read().strip().splitlines()
            raw = raw[0].strip() if raw else ""
        except OSError as e:
            raw = ""
            trail.append(Candidate(settings_path, "manual-settings",
                                   "settings file unreadable (%s)" % e, False))
        if raw:
            exe = _resolve_manual_path(raw)
            if exe:
                trail.append(Candidate(exe, "manual-settings",
                                       "configured in %s -> exists, selected"
                                       % os.path.basename(settings_path), True))
                return Resolution("unity_editor", exe, "manual-settings", trail)
            trail.append(Candidate(raw, "manual-settings",
                                   "configured in %s but Unity.exe not found there"
                                   % os.path.basename(settings_path), False))
        else:
            trail.append(Candidate(settings_path, "manual-settings",
                                   "settings file exists but is empty", False))
    else:
        trail.append(Candidate(settings_path, "manual-settings",
                               "settings file not present (optional)", False))

    # --- 戦略2: 手動指定(環境変数) ---
    env_val = (env.get(ENV_UNITY_EDITOR) or "").strip()
    if env_val:
        exe = _resolve_manual_path(env_val)
        if exe:
            trail.append(Candidate(exe, "manual-env",
                                   "%s -> exists, selected" % ENV_UNITY_EDITOR, True))
            return Resolution("unity_editor", exe, "manual-env", trail)
        trail.append(Candidate(env_val, "manual-env",
                               "%s set but Unity.exe not found there" % ENV_UNITY_EDITOR,
                               False))

    # --- 自動発見の候補プール: (version, exe, source) ---
    pool = []

    def consider(ver, exe, source):
        if _family_of(ver) != family:
            trail.append(Candidate(exe, source,
                                   "version %s not in supported family %s.x, skipped"
                                   % (ver, family), False))
            return
        if not os.path.isfile(exe):
            trail.append(Candidate(exe, source,
                                   "version %s listed but Unity.exe missing on disk"
                                   % ver, False))
            return
        trail.append(Candidate(exe, source,
                               "version %s in family %s.x, exists -> candidate"
                               % (ver, family), True))
        pool.append((ver, exe, source))

    # --- 戦略3: UnityHubの台帳 ---
    appdata = appdata if appdata is not None else env.get("APPDATA", "")
    hub_dir = os.path.join(appdata, "UnityHub") if appdata else ""
    for basename in ("editors-v2.json", "editors.json"):
        ledger = os.path.join(hub_dir, basename) if hub_dir else ""
        if not ledger or not os.path.isfile(ledger):
            trail.append(Candidate(ledger or ("%%APPDATA%%\\UnityHub\\" + basename),
                                   "hub-ledger", "ledger file not present", False))
            continue
        try:
            data = _read_json(ledger)
        except (OSError, ValueError) as e:
            trail.append(Candidate(ledger, "hub-ledger",
                                   "ledger unreadable/invalid JSON (%s)" % e, False))
            continue
        editors = []
        _collect_ledger_editors(data, editors)
        if not editors:
            trail.append(Candidate(ledger, "hub-ledger",
                                   "ledger parsed but contains no editors", False))
            continue
        trail.append(Candidate(ledger, "hub-ledger",
                               "ledger parsed, %d editor(s) listed" % len(editors), True))
        for ver, loc in editors:
            exe = loc if loc.lower().endswith(".exe") else os.path.join(loc, "Unity.exe")
            consider(ver, exe, "hub-ledger")

    # secondaryInstallPath.json: Hubの「エディタのインストール先」変更値(JSON文字列)。
    # そこを版名ディレクトリとして走査する(editors台帳が無い/壊れたHubでも拾えるように)。
    secondary = os.path.join(hub_dir, "secondaryInstallPath.json") if hub_dir else ""
    if secondary and os.path.isfile(secondary):
        try:
            sec_root = _read_json(secondary)
        except (OSError, ValueError) as e:
            sec_root = None
            trail.append(Candidate(secondary, "hub-secondary",
                                   "unreadable/invalid JSON (%s)" % e, False))
        if isinstance(sec_root, str) and sec_root.strip():
            sec_root = _norm(sec_root.strip())
            if os.path.isdir(sec_root):
                trail.append(Candidate(sec_root, "hub-secondary",
                                       "secondary install root exists, scanning", True))
                for entry in sorted(os.listdir(sec_root)):
                    consider(entry, os.path.join(sec_root, entry, "Editor", "Unity.exe"),
                             "hub-secondary")
            else:
                trail.append(Candidate(sec_root, "hub-secondary",
                                       "secondary install root configured but missing",
                                       False))
        elif sec_root is not None:
            trail.append(Candidate(secondary, "hub-secondary",
                                   "no secondary install root configured (empty)", False))
    else:
        trail.append(Candidate(secondary or "%APPDATA%\\UnityHub\\secondaryInstallPath.json",
                               "hub-secondary", "file not present", False))

    # --- 戦略4: 既知パス(Hub既定のインストール先)。ドライブ決め打ちを避けるため
    #     %ProgramFiles% 経由(この実機のように台帳が無いHub構成でも実際に使われる経路)---
    if hub_roots is None:
        # D2P_UNITY_HUB_ROOT: 走査ルートの明示上書き(台帳に載らないカスタム配置向け+
        # 試験用。ProgramFilesはOSが子プロセスで必ず実値に戻すため試験の注入点にならない)
        override = (env.get("D2P_UNITY_HUB_ROOT") or "").strip()
        if override:
            hub_roots = [override]
        else:
            program_files = env.get("ProgramFiles", r"C:\Program Files")
            hub_roots = [os.path.join(program_files, "Unity", "Hub", "Editor")]
    for root in hub_roots:
        if not os.path.isdir(root):
            trail.append(Candidate(root, "known-paths",
                                   "default Unity Hub editor dir not present", False))
            continue
        trail.append(Candidate(root, "known-paths",
                               "default Unity Hub editor dir exists, scanning", True))
        for entry in sorted(os.listdir(root)):
            consider(entry, os.path.join(root, entry, "Editor", "Unity.exe"),
                     "known-paths")

    # Hub非経由の直インストール既定位置。版がパスから確認できないため自動選択は
    # しないが、trailに記録して手動指定の材料にする(dev#22 疑われる真因3)。
    if env.get("ProgramFiles"):
        direct = os.path.join(env.get("ProgramFiles"), "Unity", "Editor", "Unity.exe")
        if os.path.isfile(direct):
            trail.append(Candidate(
                direct, "known-paths",
                "non-Hub Unity install exists but its version cannot be verified; "
                "not auto-selected (add it to the settings file to use it)", False))

    # --- 選択: 完全一致 > family内最新 ---
    if pool:
        chosen = None
        if project_version:
            for ver, exe, source in pool:
                if ver == project_version:
                    chosen = (ver, exe, source)
                    break
        if chosen is None:
            chosen = max(pool, key=lambda item: _unity_version_key(item[0]))
        ver, exe, source = chosen
        trail.append(Candidate(exe, source,
                               "selected (version %s%s)" % (
                                   ver,
                                   ", exact project match" if ver == project_version
                                   else ", newest in family %s.x" % family), True))
        return Resolution("unity_editor", exe, source, trail, version=ver)

    raise DependencyNotFoundError("unity_editor", trail, _unity_guidance(settings_path))


# ---------------------------------------------------------------------------
# 共通入口
# ---------------------------------------------------------------------------

_RESOLVERS = {
    "unity_editor": resolve_unity_editor,
    "unity": resolve_unity_editor,  # 別名
}


def resolve(name, **kwargs):
    """外部依存 name を解決する共通入口。未知のnameはValueError。"""
    try:
        fn = _RESOLVERS[name]
    except KeyError:
        raise ValueError("unknown dependency name: %r (known: %s)"
                         % (name, ", ".join(sorted(_RESOLVERS))))
    return fn(**kwargs)


def _main(argv):
    import argparse
    parser = argparse.ArgumentParser(
        description="Locate external dependencies (Unity editor, ...). "
                    "Prints the full search trail; emits '%s<path>' on success."
                    % MARKER_RESOLVED)
    parser.add_argument("name", help="dependency name (unity_editor)")
    parser.add_argument("--project-version", default=None,
                        help="exact Unity version of the project (e.g. 2022.3.22f1)")
    parser.add_argument("--approot", default=None,
                        help="app root (where settings_*.txt live); auto-detected by default")
    parser.add_argument("--appdata", default=None,
                        help="override %%APPDATA%% (for tests/diagnosis)")
    parser.add_argument("--hub-root", action="append", default=None, dest="hub_roots",
                        help="override known Unity Hub editor dir (repeatable; for tests)")
    parser.add_argument("--settings", default=None, dest="settings_path",
                        help="override settings file path (for tests)")
    args = parser.parse_args(argv)

    kwargs = {}
    if args.name in ("unity", "unity_editor"):
        kwargs = dict(project_version=args.project_version, approot=args.approot,
                      appdata=args.appdata, hub_roots=args.hub_roots,
                      settings_path=args.settings_path)
    try:
        res = resolve(args.name, **kwargs)
    except DependencyNotFoundError as e:
        print(str(e))
        print(MARKER_FAILED)
        return 1
    except ValueError as e:
        print("[dep_resolver] %s" % e)
        print(MARKER_FAILED)
        return 1
    for line in format_trail(res.trail):
        print(line)
    print(MARKER_RESOLVED + res.path)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
