# update_check.py -- 起動時の更新通知(DESIGN.md §1.2-#32, §2.8, §5.2 WP-A6行)。
#
# 移植元: app\DiveToPalworld.cs dev#15セクション(L.3499-3617):
#   - CheckForUpdateOnStartup (L.3505-3546)
#   - ParseVersion / IsNewerVersion (L.3552-3586)
#   - ShowUpdateNotice (L.3595-3607) ※UI反映部分はmain_window側の担当、
#     ここでは「通知すべきか・表示用の版文字列」までの純粋ロジックのみ
#   - OpenUpdateDownloadPage (L.3613-3617)
#
# 指揮者裁定(2026-08-01): update_checkは**更新通知のみ**(新版があることの表示+
# ストアページURL誘導)。自己更新(自動ダウンロード・置換)機能は実装禁止
# (旧ランチャーの自己更新はFIX38(L.6480-6501)で既に廃止済み・復活させない)。
# C#側も既にダウンロード経路を削除済みで、このモジュールの移植元と完全に対応する。
#
# HTTP層の分離: 「取得失敗はいかなるエラー表示・例外にもならないこと」(聖域、
# L.3502-3503)という要件を、実HTTP呼び出し(_default_fetch_versions_json)と
# 判定ロジック(evaluate_update_json)を分離することで両方を単体試験可能にした。
# pytestはcheck_for_update()のfetch引数にモック関数を注入し、ネットワークに
# 一切触れず「versions.jsonのJSON文字列を渡したときの判定結果」だけを検証する
# (WP-A6受入条件「ネットワークアクセスを伴うupdate_checkはHTTP層モックで判定
# ロジックのみ検証」への対応)。
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional

# VersionCheckUrl (L.731)。C#側はこのURLを環境変数で上書きしない
# (D2P_REPORT_BASEURLがあるのはinquiry.py相当のレポート送信先だけ、L.716)。
VERSION_CHECK_URL = "https://dl.osakishokai.com/versions.json"

# UpdateDownloadPageUrl (L.733)。
UPDATE_DOWNLOAD_PAGE_URL = "https://osaki-vrc.booth.pm/items/8662197"

# req.Timeout = req.ReadWriteTimeout = 4000 (L.3518-3519、ミリ秒)。
_REQUEST_TIMEOUT_SECONDS = 4.0


def parse_version(v: Optional[str]) -> Optional[List[int]]:
    """ParseVersion(L.3552-3569)相当。"latest"は"2.0.0"(vプレフィックス無し)、
    ToolVersionは"v2.0.0"(プレフィックス有り)という実測差があるため、両者とも
    先頭のv/Vを吸収してから数値比較する。プレリリース表記(-beta等)は考慮不要
    なので、数字とドットの並びだけを見る。解析できなければNoneを返す。"""
    if not v:
        return None
    s = v.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    # C#のRegex ^[0-9]+(\.[0-9]+)* と同じ: 先頭の "N(.N)*" 部分だけを取り出す
    m = re.match(r"^[0-9]+(\.[0-9]+)*", s)
    if not m or not m.group(0):
        return None
    return [int(p) for p in m.group(0).split(".")]


def is_newer_version(latest: Optional[str], current: Optional[str]) -> bool:
    """IsNewerVersion(L.3573-3586)相当。latestがcurrentより真に新しい
    (semver的な各桁の数値比較。足りない桁は0扱い)場合のみTrue。同じ/古い/
    どちらかが解析不能ならFalse。"""
    a = parse_version(latest)
    b = parse_version(current)
    if a is None or b is None:
        return False
    length = max(len(a), len(b))
    for i in range(length):
        av = a[i] if i < len(a) else 0
        bv = b[i] if i < len(b) else 0
        if av != bv:
            return av > bv
    return False


@dataclass
class UpdateCheckResult:
    """check_for_update()/evaluate_update_json()の結果。has_updateがTrueの時だけ
    通知を表示する(ShowUpdateNotice相当)。remote_known_good_jsonはdev#89の
    "palworld_known_good"ブロック(compat_check.merge_known_goodへそのまま渡せる
    JSON文字列)で、latestの有無とは独立に取得できる(L.3526-3531のコメントの
    とおり、バージョン更新が無い時でも既知良好リストは拡張したいため、
    has_update=Falseでも非Noneになりうる)。"""

    has_update: bool
    latest_version: Optional[str] = None
    display_version: Optional[str] = None
    remote_known_good_json: Optional[str] = None


def _format_display_version(latest: str) -> str:
    """ShowUpdateNotice内のdisplay算出(L.3600-3602)相当。latestVersionが既に
    v/Vで始まっていれば二重表示("vv2.1.0")にせずそのまま使う。"""
    return latest if latest[:1] in ("v", "V") else "v" + latest


def evaluate_update_json(json_text: Optional[str], current_version: str) -> UpdateCheckResult:
    """CheckForUpdateOnStartupのうち、HTTP応答本文(json_text、取得失敗時はNone)
    を受け取った後の判定ロジックだけを純粋関数として切り出したもの
    (L.3525-3544相当)。不正なJSON/非オブジェクトは黙って「更新なし」扱い
    (L.3533-3536の「オフライン・DNS失敗・タイムアウト等はすべて無音で諦める」
    と同じfail-safe方針をパースエラーにも適用する)。"""
    if not json_text:
        return UpdateCheckResult(has_update=False)
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return UpdateCheckResult(has_update=False)
    if not isinstance(data, dict):
        return UpdateCheckResult(has_update=False)

    latest = data.get("latest")
    # dev#89: "latest"の有無とは独立の任意フィールドなので、latest早期returnより
    # 前で拾っておく(L.3526-3531のコメントそのまま)
    remote_kg = data.get("palworld_known_good")
    remote_kg_json = json.dumps(remote_kg) if isinstance(remote_kg, dict) else None

    if not latest or not isinstance(latest, str):
        return UpdateCheckResult(has_update=False, remote_known_good_json=remote_kg_json)
    if not is_newer_version(latest, current_version):
        return UpdateCheckResult(has_update=False, remote_known_good_json=remote_kg_json)

    return UpdateCheckResult(
        has_update=True,
        latest_version=latest,
        display_version=_format_display_version(latest),
        remote_known_good_json=remote_kg_json,
    )


def _default_fetch_versions_json(current_version: str) -> Optional[str]:
    """実HTTP GET(L.3507-3536相当)。失敗は完全に無音でNoneを返す(聖域:
    取得失敗はいかなるエラー表示・例外にもならないこと、L.3502-3503)。"""
    try:
        req = urllib.request.Request(
            VERSION_CHECK_URL,
            headers={"User-Agent": "Uchinoko-UpdateCheck/" + current_version.lstrip("vV")},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset)
    except Exception:
        return None


def check_for_update(
    current_version: str, fetch: Optional[Callable[[], Optional[str]]] = None
) -> UpdateCheckResult:
    """起動時の更新通知本体(CheckForUpdateOnStartup L.3505-3546相当、ダウンロード
    無し=通知のみ)。fetchはHTTP層を差し替えるための注入点(既定は実際に
    versions.jsonをGETする_default_fetch_versions_json)。呼び出し側
    (main_window等、統合はWP範囲外)は非同期スレッドから呼ぶこと(C#側も
    ThreadPool.QueueUserWorkItemで非同期・非ブロッキング、L.3507)。"""
    if fetch is None:
        fetch = lambda: _default_fetch_versions_json(current_version)
    try:
        json_text = fetch()
    except Exception:
        json_text = None  # 聖域: 取得失敗は無音(L.3533-3536と同じ)
    return evaluate_update_json(json_text, current_version)
