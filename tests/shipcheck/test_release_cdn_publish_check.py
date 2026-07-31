# -*- coding: utf-8 -*-
r"""dev#370(CDN配信 latest 未反映事故、2026-07-31)の再発防止 -- 受入試験。

背景: 配信CDN(dl.osakishokai.com)のversions.jsonが「latest: 2.2.8」のまま
v2.2.9〜v2.2.12の4版分放置され、アプリの自動更新通知(app\DiveToPalworld.cs の
VersionCheckUrl)が一切出なかった。原因は release.py が CDN反映
(devtools\dist_publish.py)を一度も呼ばない設計だったこと(詳細調査は開発側の記録に保管)。

このWPで release.py に足したのは「配信中のversions.jsonのlatestが、今回
リリースしたバージョンと一致しているか」を読み取り専用HTTP GETで確認する
軽量チェック(check_cdn_latest / run_cdn_publish_check_step)。
dist_publish.py 自体は変更していない(完動品)。実publishはこのテストからも
一切実行しない(読み取り専用GETのみ)。

対象の負の対照・正の対照:
  1. モック: CDN latest と期待バージョンが乖離 -> match=False で検知が発火
  2. モック: 一致 -> match=True でWARNバナーは出ない
  3. モック: ネットワーク不通(URLError) -> checked=False、例外は外へ伝播しない
  4. 実ネットワーク統合デモ: 実際のCDNに対してcheck_cdn_latest()を実行し、
     実世界の乖離/一致を正しく判定できることを示す(オフラインなら自動skip、
     既に同期済みなら「デモの必要が無い」としてskip -- 将来この乖離が解消
     されてもテストスイートを壊さない設計)。

実行: python -m pytest tests\shipcheck\test_release_cdn_publish_check.py -v
"""
import importlib
import io
import json
import os
import subprocess
import sys
import urllib.error

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEVTOOLS = os.path.join(REPO, "devtools")
TESTS_RELGATE = os.path.join(REPO, "tests", "relgate")

for p in (DEVTOOLS, TESTS_RELGATE):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_release():
    return importlib.import_module("release")


class DummyReport:
    def __init__(self):
        self.lines = []

    def log(self, text, echo=True):
        self.lines.append(text)

    def section(self, title):
        self.lines.append(title)

    def joined(self):
        return "\n".join(self.lines)


class _FakeHTTPResponse:
    """urllib.request.urlopen()のcontext manager互換の最小フェイク。"""

    def __init__(self, body_bytes):
        self._body = body_bytes

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mock_urlopen_returning(monkeypatch, release, payload_dict):
    body = json.dumps(payload_dict).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        return _FakeHTTPResponse(body)

    monkeypatch.setattr(release.urllib.request, "urlopen", fake_urlopen)


def _mock_urlopen_raising(monkeypatch, release, exc):
    def fake_urlopen(req, timeout=None):
        raise exc

    monkeypatch.setattr(release.urllib.request, "urlopen", fake_urlopen)


# =====================================================================
# check_cdn_latest: 純粋な判定ロジック(モック、ネットワーク不使用)
# =====================================================================

def test_check_cdn_latest_detects_mismatch(monkeypatch):
    """負の対照1: CDNのlatestが期待バージョンより古い -> match=Falseで検知。"""
    release = _import_release()
    _mock_urlopen_returning(monkeypatch, release, {"latest": "2.2.4", "versions": []})

    result = release.check_cdn_latest("v2.2.12")

    assert result["checked"] is True
    assert result["match"] is False
    assert result["cdn_latest"] == "2.2.4"


def test_check_cdn_latest_detects_match(monkeypatch):
    """正の対照: CDNのlatestが期待バージョンと一致 -> match=True。"""
    release = _import_release()
    _mock_urlopen_returning(monkeypatch, release, {"latest": "2.2.5", "versions": []})

    result = release.check_cdn_latest("v2.2.5")

    assert result["checked"] is True
    assert result["match"] is True
    assert result["cdn_latest"] == "2.2.5"


def test_check_cdn_latest_strips_v_prefix_before_compare(monkeypatch):
    """CDN側は'v'接頭辞なし('2.2.5')で保存されている(dist_publish.py準拠)。
    expected_versionはformat_version()の出力そのまま('v'接頭辞あり)で渡される
    ため、比較前に正規化されていることを確認する。"""
    release = _import_release()
    _mock_urlopen_returning(monkeypatch, release, {"latest": "2.2.5", "versions": []})

    result = release.check_cdn_latest("v2.2.5")
    assert result["match"] is True

    result_no_prefix = release.check_cdn_latest("2.2.5")
    assert result_no_prefix["match"] is True


def test_check_cdn_latest_network_failure_does_not_raise(monkeypatch):
    """負の対照3: ネットワーク不通(URLError)でも例外を外へ伝播させず、
    checked=Falseのdictを返すだけ(release.py全体をfail-closedにしない設計の
    直接の根拠)。"""
    release = _import_release()
    _mock_urlopen_raising(monkeypatch, release, urllib.error.URLError("simulated: no network"))

    result = release.check_cdn_latest("v2.2.12")

    assert result["checked"] is False
    assert result["match"] is None
    assert result["cdn_latest"] is None
    assert "到達に失敗" in result["detail"]


def test_check_cdn_latest_malformed_json_does_not_raise(monkeypatch):
    release = _import_release()

    def fake_urlopen(req, timeout=None):
        return _FakeHTTPResponse(b"not valid json{{{")

    monkeypatch.setattr(release.urllib.request, "urlopen", fake_urlopen)

    result = release.check_cdn_latest("v2.2.12")

    assert result["checked"] is False
    assert result["match"] is None


def test_check_cdn_latest_missing_latest_key_does_not_raise(monkeypatch):
    release = _import_release()
    _mock_urlopen_returning(monkeypatch, release, {"versions": []})  # latestキー無し

    result = release.check_cdn_latest("v2.2.12")

    assert result["checked"] is True
    assert result["match"] is None
    assert result["cdn_latest"] is None


# =====================================================================
# run_cdn_publish_check_step: report.log()/標準出力バナーの配線確認
# =====================================================================

def test_run_step_logs_ok_without_banner_when_matching(monkeypatch, capsys):
    """正の対照: 一致時はreport.logへOKを1行残すのみで、
    警告バナー(標準出力への"CDN未反映警告")は出さない。"""
    release = _import_release()
    _mock_urlopen_returning(monkeypatch, release, {"latest": "2.2.5", "versions": []})
    report = DummyReport()

    result = release.run_cdn_publish_check_step("v2.2.5", report, is_provisional=False)

    assert result["match"] is True
    assert any("OK" in line for line in report.lines)
    captured = capsys.readouterr()
    assert "CDN未反映警告" not in captured.out


def test_run_step_prints_banner_with_publish_command_when_mismatched(monkeypatch, capsys):
    """負の対照1続き: 乖離時は標準出力にバナー+dist_publish.pyのコピペ実行
    コマンドを出す(見逃せない形で目立たせる、というWP要求の直接の根拠)。"""
    release = _import_release()
    _mock_urlopen_returning(monkeypatch, release, {"latest": "2.2.4", "versions": []})
    report = DummyReport()

    result = release.run_cdn_publish_check_step("v2.2.12", report, is_provisional=False)

    assert result["match"] is False
    captured = capsys.readouterr()
    assert "CDN未反映警告" in captured.out
    assert "dist_publish.py publish" in captured.out
    assert "--version 2.2.12" in captured.out
    assert any("WARN" in line for line in report.lines)


def test_run_step_provisional_banner_defers_to_confirm(monkeypatch, capsys):
    """--provisional実行時は、乖離を検知しても「今すぐ実行」ではなく
    「事後承認(--confirm-provisional)完了後まで待て」という案内文に
    差し替わる(未承認版の誤公開導線を作らないため)。"""
    release = _import_release()
    _mock_urlopen_returning(monkeypatch, release, {"latest": "2.2.4", "versions": []})
    report = DummyReport()

    release.run_cdn_publish_check_step("v2.2.12", report, is_provisional=True)

    captured = capsys.readouterr()
    assert "confirm-provisional" in captured.out
    assert "事後承認" in captured.out
    assert "GitHub Release/BOOTH/itchと同様に" in captured.out


def test_run_step_network_failure_warns_without_raising(monkeypatch, capsys):
    """負の対照3続き: run_cdn_publish_check_step()自体もネットワーク不通で
    例外を投げない(呼び出し元のmain()がこの関数の戻り値をrc判定に一切
    使わない設計と合わせて、リリース全体を失敗させないことの直接の根拠)。"""
    release = _import_release()
    _mock_urlopen_raising(monkeypatch, release, urllib.error.URLError("simulated: no network"))
    report = DummyReport()

    result = release.run_cdn_publish_check_step("v2.2.12", report, is_provisional=False)

    assert result["checked"] is False
    assert any("WARN" in line for line in report.lines)
    captured = capsys.readouterr()
    # ネットワーク不通時はバナー(dist_publish案内)は出さない -- 判定不能なので
    # 「乖離している」と断定できる情報が無いため。
    assert "CDN未反映警告" not in captured.out


# =====================================================================
# 実ネットワーク統合デモ(gate3/gate4を実物データで兼ねる)
# オフライン/gh CLI不通/既に同期済みのいずれでも自動skipし、CIを不安定にしない。
# =====================================================================

def test_real_cdn_latest_reflects_actual_release_state():
    """実際のdl.osakishokai.com/versions.jsonと、実際のGitHub Release
    (pandrabox/Uchinoko)の最新タグを比較し、check_cdn_latest()が実世界の
    状態を正しく判定できることを示す統合デモ。

    - gh CLIが無い/ネットワーク不通 -> skip
    - 既にCDNとGitHub Releaseが同期済み(match=True) -> デモの余地が無いのでskip
      (将来dev#370系の乖離が解消された後もこのテストで赤くならない)
    - 乖離している(2026-07-31時点の実例) -> 検知が正しく発火することを確認
    """
    release = _import_release()

    try:
        proc = subprocess.run(
            ["gh", "release", "view", "--repo", "pandrabox/Uchinoko",
             "--json", "tagName", "-q", ".tagName"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"gh CLIが使えない、またはタイムアウト(オフラインの可能性): {e}")

    if proc.returncode != 0 or not proc.stdout.strip():
        pytest.skip(f"GitHub Releaseの取得に失敗(オフラインの可能性): {proc.stderr.strip()}")

    expected_version = proc.stdout.strip()

    result = release.check_cdn_latest(expected_version, timeout=10)
    if not result["checked"]:
        pytest.skip(f"CDNへの到達に失敗(オフラインの可能性): {result['detail']}")

    if result["match"]:
        pytest.skip(
            f"既にCDNとGitHub Releaseが同期済み(latest={result['cdn_latest']})"
            "、乖離デモは不要(dev#370の状態が解消された)"
        )

    # ここに到達した時点で「実際に乖離している」ことが確認できた(2026-07-31
    # 時点の実例: cdn_latest=2.2.8, expected=v2.2.12相当)。検知が正しく
    # 発火することを直接assertする。
    assert result["match"] is False
    assert result["cdn_latest"] is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
