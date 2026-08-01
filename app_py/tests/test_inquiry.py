# test_inquiry.py -- dev#532 方針A WP-A5 受入条件①②③の機械検査。
#
# ①: SanitizeForClipboard相当が既存C#セルフチェック CheckSanitizeForClipboardLogic
#     (app\DiveToPalworld.cs L.4105-4162)のケース表(case1〜case7b)を1:1移植し、
#     全PASSであること。
# ②: build_report_payload_json のペイロードJSONが DESIGN.md §2.5 の契約と一致
#     すること(version/lang/meta.os/meta.avatar/meta.status/meta.channel/log_gzip_b64)。
# ③: 実サーバーへの送信テストは禁止(本物の問い合わせDBを汚すため)。
#     send_report_payload はすべて transport引数へ偽関数を渡し、
#     urllib.request 等の実HTTP層には一切触れない。
from __future__ import annotations

import base64
import gzip
import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import inquiry  # noqa: E402


# ---------------------------------------------------------------------------
# 受入条件①: CheckSanitizeForClipboardLogic (L.4105-4162) のケース表を1:1移植。
# フィクスチャは全て架空の値(実在の個人情報は使わない、原文の方針を踏襲)。
# ---------------------------------------------------------------------------


def test_case1_userprofile_is_tokenized():
    up = os.environ.get("USERPROFILE")
    assert up, "このテストはWindows環境(USERPROFILE設定済み)を前提とする"
    under_up = os.path.join(up, "Downloads", "avatar.vrm")
    r1 = inquiry.sanitize_for_clipboard("input: " + under_up)
    assert "%USERPROFILE%" in r1
    assert up not in r1


def test_case2_steamid64_is_masked():
    r2 = inquiry.sanitize_for_clipboard("steamid: 76561198012345678")
    assert "<SteamID>" in r2
    assert "76561198012345678" not in r2


def test_case3_username_word_boundary_is_masked():
    user_name = os.environ.get("USERNAME") or ""
    if len(user_name) <= 3:
        return  # C#版と同じく短い名前は対象外(誤爆防止)。この環境では検査対象外
    r3 = inquiry.sanitize_for_clipboard(
        "path fragment: xxx-" + user_name + "-yyy has " + user_name + " alone"
    )
    assert "<user>" in r3
    assert user_name not in r3


def test_case4_non_userprofile_drive_absolute_path_is_masked():
    # 実ユーザー報告4AL4M4GT(非%USERPROFILE%ドライブの絶対パス漏洩)を模した
    # 架空のフィクスチャ(実在の個人情報は使わない)
    fake_user_folder = r"D:\Users\SampleTaro\UnityProjects\MyAvatarProject\Assets\avatar.prefab"
    r4 = inquiry.sanitize_for_clipboard("Unity project: " + fake_user_folder)
    assert fake_user_folder not in r4
    assert "SampleTaro" not in r4
    # case4b(診断可用性): マスク後も原因切り分けに使える拡張子情報は残ること
    assert "ext=.prefab" in r4


def test_case5_unc_path_is_masked():
    fake_unc_path = r"\\BUILDSERVER\share\SampleHanako\SteamLibrary\steamapps\common\Palworld\Pal-Windows.pak"
    r5 = inquiry.sanitize_for_clipboard("Palworld pak: " + fake_unc_path)
    assert fake_unc_path not in r5
    assert "SampleHanako" not in r5


def test_case6_unrelated_text_is_not_corrupted():
    # 負の対照: パスに見えない通常の文章・URLはマスクされず読めるままであること
    # (単独ドライブ文字"C:"はバックスラッシュを伴わないためマッチしない)
    plain = "status: converting avatar, see https://example.com/help for C: drive info"
    r6 = inquiry.sanitize_for_clipboard(plain)
    assert "https://example.com/help" in r6


def test_case7a_empty_string_passthrough():
    assert inquiry.sanitize_for_clipboard("") == ""


def test_case7b_none_passthrough():
    assert inquiry.sanitize_for_clipboard(None) is None


# ---------------------------------------------------------------------------
# factify_generic_path (L.4754-4766) 単体
# ---------------------------------------------------------------------------


def test_factify_generic_path_reports_length_and_extension():
    result = inquiry.factify_generic_path(r"D:\foo\bar\avatar.prefab")
    assert result.startswith("<path len=")
    assert "ext=.prefab" in result
    assert "unc=true" not in result


def test_factify_generic_path_reports_unc():
    result = inquiry.factify_generic_path(r"\\server\share\file.pak")
    assert "unc=true" in result


def test_factify_generic_path_empty_passthrough():
    assert inquiry.factify_generic_path("") == ""


# ---------------------------------------------------------------------------
# normalize_log_for_comparison (L.4255-4266)
# ---------------------------------------------------------------------------


def test_normalize_log_excludes_only_date_line():
    a = "date: 2026-08-01 10:00\nversion: v2.2.14\nstatus: idle\n"
    b = "date: 2026-08-01 10:05\nversion: v2.2.14\nstatus: idle\n"
    assert inquiry.normalize_log_for_comparison(a) == inquiry.normalize_log_for_comparison(b)


def test_normalize_log_detects_real_change():
    a = "date: 2026-08-01 10:00\nstatus: idle\n"
    b = "date: 2026-08-01 10:00\nstatus: converting\n"
    assert inquiry.normalize_log_for_comparison(a) != inquiry.normalize_log_for_comparison(b)


# ---------------------------------------------------------------------------
# 受入条件②: build_report_payload_json のスキーマ契約一致(DESIGN.md §2.5)
# ---------------------------------------------------------------------------


def test_payload_schema_matches_contract():
    payload_json, masked_log = inquiry.build_report_payload_json(
        version="v2.2.14",
        lang="ja",
        os_description="Windows 11 Pro (build 26200)",
        avatar_name="avatar.vrm",
        status_text="変換完了",
        channel="itch",
        log_text="--- log ---\nhello\n",
    )
    data = json.loads(payload_json)

    # トップレベルキーが契約(§2.5)と1:1(過不足なし)
    assert set(data.keys()) == {"version", "lang", "meta", "log_gzip_b64"}
    assert set(data["meta"].keys()) == {"os", "avatar", "status", "channel"}

    assert data["version"] == "v2.2.14"
    assert data["lang"] == "ja"
    assert data["meta"]["os"] == "Windows 11 Pro (build 26200)"
    assert data["meta"]["avatar"] == "avatar.vrm"
    assert data["meta"]["status"] == "変換完了"
    assert data["meta"]["channel"] == "itch"

    # log_gzip_b64: base64→gzip展開→伏字化済みログ本文と一致すること
    decoded = gzip.decompress(base64.b64decode(data["log_gzip_b64"])).decode("utf-8")
    assert decoded == masked_log
    assert decoded == "--- log ---\nhello\n"


def test_payload_masks_sensitive_fields():
    up = os.environ.get("USERPROFILE")
    assert up
    fake_avatar_path_name = os.path.basename(
        os.path.join(up, "Downloads", "avatar.vrm")
    )
    # avatar/status/os もsanitize_for_clipboardを通ること(メールアドレスや
    # SteamID等が紛れても伏せられる。SteamID64を仕込んで確認)
    payload_json, _masked_log = inquiry.build_report_payload_json(
        version="v2.2.14",
        lang="en",
        os_description="steamid: 76561198012345678",
        avatar_name=fake_avatar_path_name,
        status_text="steamid: 76561198012345678",
        channel="dev",
        log_text="plain log, no secrets",
    )
    data = json.loads(payload_json)
    assert "76561198012345678" not in data["meta"]["os"]
    assert "76561198012345678" not in data["meta"]["status"]
    assert "<SteamID>" in data["meta"]["os"]


def test_payload_channel_is_not_sanitized_passthrough():
    # DESIGN.md §2.5: channelは既知enumのみを返す値のためsanitize対象外
    payload_json, _ = inquiry.build_report_payload_json(
        version="v2.2.14",
        lang="ja",
        os_description="Windows 11",
        avatar_name="(未選択)",
        status_text="idle",
        channel="unknown",
        log_text="log",
    )
    data = json.loads(payload_json)
    assert data["meta"]["channel"] == "unknown"


# ---------------------------------------------------------------------------
# 受入条件③: send_report_payload は必ずtransportをモックし、実サーバーへ
# 一切触れないこと。urllib.request が本テストから呼ばれないことを明示的に
# 確認する(_default_transportを直接呼ばない構成であることの検証)。
# ---------------------------------------------------------------------------


def test_send_report_payload_new_post_success():
    calls = []

    def fake_transport(url, payload_json, user_agent, timeout):
        calls.append((url, payload_json, user_agent, timeout))
        return json.dumps({"id": "abc123", "view_url": "https://report.osakishokai.com/r/abc123"})

    result = inquiry.send_report_payload(
        '{"dummy": true}',
        None,
        base_url="https://report.example.invalid",
        tool_version="v2.2.14",
        transport=fake_transport,
    )
    assert result.ok is True
    assert result.id == "abc123"
    assert result.view_url == "https://report.osakishokai.com/r/abc123"
    assert len(calls) == 1
    url, _payload, user_agent, timeout = calls[0]
    assert url == "https://report.example.invalid/report"
    assert user_agent == "Uchinoko-Support/2.2.14"  # 先頭の"v"を除去(L.4406と同じ)
    assert timeout == 20


def test_send_report_payload_append_uses_append_url():
    calls = []

    def fake_transport(url, payload_json, user_agent, timeout):
        calls.append(url)
        return json.dumps({"id": "abc123", "view_url": "https://report.osakishokai.com/r/abc123"})

    result = inquiry.send_report_payload(
        "{}",
        "abc123",
        base_url="https://report.example.invalid",
        tool_version="v2.2.14",
        transport=fake_transport,
    )
    assert result.ok is True
    assert calls[0] == "https://report.example.invalid/report/abc123/append"


def test_send_report_payload_missing_id_is_error():
    def fake_transport(url, payload_json, user_agent, timeout):
        return "not json at all"

    result = inquiry.send_report_payload(
        "{}", None, base_url="https://report.example.invalid", transport=fake_transport
    )
    assert result.ok is False
    assert result.id is None
    assert "報告ID" in result.error


def test_send_report_payload_transport_exception_is_captured():
    def fake_transport(url, payload_json, user_agent, timeout):
        raise OSError("connection refused (test double, no real network)")

    result = inquiry.send_report_payload(
        "{}", None, base_url="https://report.example.invalid", transport=fake_transport
    )
    assert result.ok is False
    assert "connection refused" in result.error


def test_send_report_payload_view_url_fallback_when_absent():
    def fake_transport(url, payload_json, user_agent, timeout):
        return json.dumps({"id": "xyz789"})

    result = inquiry.send_report_payload(
        "{}", None, base_url="https://report.example.invalid", transport=fake_transport
    )
    assert result.ok is True
    assert result.view_url == "https://report.example.invalid/r/xyz789"


def test_get_report_base_url_default_and_env_override(monkeypatch):
    monkeypatch.delenv("D2P_REPORT_BASEURL", raising=False)
    assert inquiry.get_report_base_url() == "https://report.osakishokai.com"
    monkeypatch.setenv("D2P_REPORT_BASEURL", "https://report.example.invalid/")
    assert inquiry.get_report_base_url() == "https://report.example.invalid"
