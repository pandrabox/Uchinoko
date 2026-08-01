# inquiry.py -- 問い合わせ送信API契約(DESIGN.md §2.5)のPython移植。
#
# 移植元: app\DiveToPalworld.cs
#   - SanitizeForClipboard          (L.4673-4737)
#   - FactifyGenericPath            (L.4754-4766)
#   - GenericAbsolutePathRegex      (L.4747-4749)
#   - AddFolderToken                (L.4768-4776)
#   - BuildReportPayloadJson        (L.4316-4361, 2オーバーロード)
#   - JsonEscape                    (L.4363-4383, json.dumpsに置き換えたため本ファイルには無い)
#   - SendReportPayload             (L.4391-4440)
#   - GetReportBaseUrl              (L.720-725)
#   - NormalizeLogForComparison     (L.4255-4266)
#
# 正本: work\wp532A\DESIGN.md §2.5。CLIから叩ける旧`--check-sanitize-clipboard`の
# 単体表(CheckSanitizeForClipboardLogic, L.4105-4162)は app_py\tests\test_inquiry.py
# へ1:1で移植した(受入条件①)。
#
# 依存の分離(WP-A5のスコープが inquiry.py + ui/support_dialog.py のみで
# main_window.py に触れられないため): C#版はMainFormのvrmBox/statusLabel等の
# UIフィールドを直接読んでいたが、Python版は呼び出し元が値を渡す関数として
# 設計した(build_report_payload_jsonの引数群)。ToolVersion定数もここでは
# 定義せず引数で受け取る(main_window.pyのTOOL_VERSION定数と重複させないため。
# 統合WPでui.main_window.TOOL_VERSIONを渡す想定)。
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

# dev#25: 不具合報告の送信先(Cloudflare Worker)。環境変数 D2P_REPORT_BASEURL で
# 上書き可能(GetReportBaseUrl L.720-725と1:1。疎通しない偽URLを与えればオフライン
# 縮退の試験ができる、通常ユーザーは触らない)。
REPORT_BASE_URL_DEFAULT = "https://report.osakishokai.com"
_REPORT_BASEURL_ENV = "D2P_REPORT_BASEURL"


def get_report_base_url() -> str:
    """GetReportBaseUrl (L.720-725) 相当。末尾スラッシュは除去する。"""
    env = os.environ.get(_REPORT_BASEURL_ENV)
    if env:
        return env.rstrip("/")
    return REPORT_BASE_URL_DEFAULT


# ---------------------------------------------------------------------------
# SanitizeForClipboard (L.4673-4737)
# クリップボードへ渡す/サーバーへ送る直前の文字列からユーザーを特定できる情報を
# 伏せる。呼び出し元はコピー・送信の直前のみで使うこと(画面表示・ログファイルには
# 適用しない、C#版と同じ運用方針)。
# ---------------------------------------------------------------------------

# 任意ドライブの絶対パス(例: D:\Users\...\avatar.prefab)またはUNCパス
# (\\server\share\...)にマッチする。GenericAbsolutePathRegex (L.4747-4749) と
# 1:1(C#の verbatim 文字列 `\\`は2文字=正規表現で1個のバックスラッシュ、
# `\\\\`は4文字=正規表現で2個のバックスラッシュ=UNC先頭、という対応関係を
# Pythonのraw文字列でもそのまま再現している)。
_GENERIC_PATH_RE = re.compile(
    r'(?:[A-Za-z]:\\|\\\\)[^\s"\'<>|?*\r\n]+(?:[ \t](?![ \t(),])[^\s"\'<>|?*\r\n]+)*'
)

# SteamID64(7656119で始まる17桁の数字)
_STEAM_ID_RE = re.compile(r"\b7656119\d{10}\b")


def _known_folder(env_name: str) -> Optional[str]:
    """AddFolderToken (L.4768-4776) のうち Environment.GetFolderPath 相当部分。
    Windows環境変数から直接引く(Pythonにos.path.expanduser以上の特殊フォルダ
    APIが無いため。LOCALAPPDATA/APPDATA/USERPROFILEはいずれもWindowsが
    標準で設定する環境変数)。ルート直下等の異常に短い値(3文字以下)は
    誤爆の恐れがあるため対象外にする(AddFolderTokenの`path.Length > 3`と同じ)。"""
    v = os.environ.get(env_name)
    if v and len(v) > 3:
        return v
    return None


def factify_generic_path(raw_path: str) -> str:
    """FactifyGenericPath (L.4754-4766) 相当。生パスの代わりに、診断に要る
    「事実」(長さ・UNCかどうか・拡張子)だけを返す(構造保存型の伏字化)。"""
    if not raw_path:
        return raw_path
    try:
        _, ext = os.path.splitext(raw_path)
    except ValueError:
        ext = ""
    # 異常に長い/記号だらけの「拡張子」はsplitextの誤爆の可能性があるため出さない
    if not ext or len(ext) > 10:
        ext = ""
    is_unc = raw_path.startswith("\\\\")
    parts = [f"<path len={len(raw_path)}"]
    if is_unc:
        parts.append(" unc=true")
    if ext:
        parts.append(f" ext={ext}")
    parts.append(">")
    return "".join(parts)


def sanitize_for_clipboard(text: Optional[str]) -> Optional[str]:
    """SanitizeForClipboard (L.4673-4737) 相当。空文字列/Noneはそのまま返す
    (case7a/7bの受入条件そのもの)。"""
    if not text:
        return text

    # 1) 既知フォルダのパスを伏せる。%LOCALAPPDATA% / %APPDATA% は %USERPROFILE% の
    #    サブフォルダなので、長い順(具体的な方から先)に置換する(コメントL.4677-4680と同じ理由)。
    folder_map = []
    for env_name, token in (
        ("LOCALAPPDATA", "%LOCALAPPDATA%"),
        ("APPDATA", "%APPDATA%"),
        ("USERPROFILE", "%USERPROFILE%"),
    ):
        path = _known_folder(env_name)
        if path:
            folder_map.append((path, token))
    folder_map.sort(key=lambda kv: len(kv[0]), reverse=True)

    for path, token in folder_map:
        text = re.sub(re.escape(path), token, text, flags=re.IGNORECASE)

    # 2) SteamID64
    text = _STEAM_ID_RE.sub("<SteamID>", text)

    # 3) アカウント名がパス以外に露出している場合の保険(3文字以下は誤爆防止で対象外)
    user_name = os.environ.get("USERNAME") or os.environ.get("USER")
    if user_name and len(user_name) > 3:
        text = re.sub(
            r"(?<![A-Za-z0-9_])" + re.escape(user_name) + r"(?![A-Za-z0-9_])",
            "<user>",
            text,
            flags=re.IGNORECASE,
        )

    # 4) PCのマシン名も同様の理由で保険として伏せる(短い名前は除外)
    machine_name = os.environ.get("COMPUTERNAME")
    if machine_name and len(machine_name) > 3:
        text = re.sub(
            r"(?<![A-Za-z0-9_])" + re.escape(machine_name) + r"(?![A-Za-z0-9_])",
            "<machine>",
            text,
            flags=re.IGNORECASE,
        )

    # 5) dev#7: 汎用の最終防衛。任意ドライブの絶対パス・UNCパスを構造保存型で伏せる。
    #    1)〜4)より後に実行する(既にトークン化済みの文字列を誤って再度巻き込まないため)。
    text = _GENERIC_PATH_RE.sub(lambda m: factify_generic_path(m.group(0)), text)

    return text


def normalize_log_for_comparison(text: Optional[str]) -> Optional[str]:
    """NormalizeLogForComparison (L.4255-4266) 相当。「送信済み後にログが変わったか」
    の比較専用の正規化。"date: "行(DateTime.Nowを分単位で埋め込むため1分でも
    経てば必ず変わる)だけを比較対象から除外する。"""
    if not text:
        return text
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        if line.startswith("date: "):
            continue
        out.append(line)
    return "".join(line + "\n" for line in out)


# ---------------------------------------------------------------------------
# BuildReportPayloadJson (L.4316-4361) / JsonEscape (L.4363-4383)
# ---------------------------------------------------------------------------


def build_report_payload_json(
    *,
    version: str,
    lang: str,
    os_description: str,
    avatar_name: str,
    status_text: str,
    channel: str,
    log_text: str,
) -> tuple[str, str]:
    """BuildReportPayloadJson(string logText, out string maskedLog) 相当。
    ログ・meta とも、外へ出る文字列はすべて sanitize_for_clipboard を通してから
    詰める(channelのみ、C#同様に既知enumのみを返す値のため対象外)。

    戻り値は (payload_json, masked_log) のタプル(C#の out引数をPython流に置き換え)。
    JSONの組み立てはC#のJsonEscape手書き実装ではなく標準の json.dumps を使う
    (DESIGN.md §2.5に明記の通り、レスポンス側同様パース/生成方式の変更は
    契約を破壊しない=同一スキーマである限り置き換えて構わない)。

    §2.5契約のスキーマ:
        {"version": "...", "lang": "...",
         "meta": {"os": "...", "avatar": "...", "status": "...", "channel": "..."},
         "log_gzip_b64": "..."}
    """
    masked_log = sanitize_for_clipboard(log_text)
    masked_os = sanitize_for_clipboard(os_description)
    masked_avatar = sanitize_for_clipboard(avatar_name)
    masked_status = sanitize_for_clipboard(status_text)

    raw = (masked_log or "").encode("utf-8")
    gz = gzip.compress(raw)
    log_gzip_b64 = base64.b64encode(gz).decode("ascii")

    payload = {
        "version": version,
        "lang": lang,
        "meta": {
            "os": masked_os,
            "avatar": masked_avatar,
            "status": masked_status,
            "channel": channel,
        },
        "log_gzip_b64": log_gzip_b64,
    }
    return json.dumps(payload, ensure_ascii=False), masked_log


# ---------------------------------------------------------------------------
# SendReportPayload (L.4391-4440)
# ---------------------------------------------------------------------------


@dataclass
class ReportSendResult:
    """ReportSendResult (L.4302-4308) 相当。"""

    ok: bool = False
    id: Optional[str] = None
    view_url: Optional[str] = None
    error: Optional[str] = None


# レスポンスから id/view_url を拾う正規表現(L.4421/L.4429と同じ、厳密JSON
# parseではない緩い抽出。DESIGN.md §2.5「json.loadsに置き換えて構わない」の
# 通りだが、サーバーが厳密なJSONを返さない場合の後方互換のため正規表現版を残す)
_ID_RE = re.compile(r'"id"\s*:\s*"([A-Za-z0-9]+)"')
_VIEW_URL_RE = re.compile(r'"view_url"\s*:\s*"([^"]+)"')

Transport = Callable[[str, str, str, int], str]


def _default_transport(url: str, payload_json: str, user_agent: str, timeout: int) -> str:
    """実HTTP送信(urllib.request、devtools\\support.pyと同じ流儀のstdlibのみ実装)。
    テストではこの関数を呼ばせず、必ずtransport引数でモックへ差し替えること
    (受入条件③: 実サーバーへの送信テストは禁止)。"""
    req = urllib.request.Request(
        url,
        data=payload_json.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": user_agent},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def send_report_payload(
    payload_json: str,
    append_to_id: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    tool_version: str = "",
    timeout: int = 20,
    transport: Optional[Transport] = None,
) -> ReportSendResult:
    """SendReportPayload (L.4391-4440) 相当。例外はすべてErrorへ落とし、呼び出し元が
    エラー表示せず縮退案内に使えるようにする(C#版と同じ設計方針)。

    append_to_id: None/空なら新規 POST /report。指定があれば
    POST /report/<ID>/append (dev#42bの再送仕様、サーバーは新IDを発行せず
    同じid/view_urlを返す)。

    transport: (url, payload_json, user_agent, timeout) -> response_text の関数。
    省略時は実HTTP送信(_default_transport)。テストは必ず差し替えて実サーバーに
    触れないこと。
    """
    result = ReportSendResult()
    try:
        url_base = base_url or get_report_base_url()
        if append_to_id:
            url = f"{url_base}/report/{urllib.parse.quote(str(append_to_id), safe='')}/append"
        else:
            url = f"{url_base}/report"
        # 独自UA必須(既定UAはbot対策403の実測あり、L.4405-4406のコメントと同じ理由)
        user_agent = "Uchinoko-Support/" + str(tool_version).lstrip("v")
        post = transport or _default_transport
        resp_text = post(url, payload_json, user_agent, timeout)

        m = _ID_RE.search(resp_text)
        if not m:
            result.error = "サーバー応答に報告IDが含まれていません: " + (
                resp_text[:200] if resp_text else ""
            )
            return result
        result.id = m.group(1)
        mv = _VIEW_URL_RE.search(resp_text)
        result.view_url = (
            mv.group(1).replace("\\/", "/") if mv else f"{url_base}/r/{result.id}"
        )
        result.ok = True
    except Exception as ex:  # noqa: BLE001 -- C#版もcatch(Exception)で全例外を握りつぶす
        result.error = str(ex)
    return result
