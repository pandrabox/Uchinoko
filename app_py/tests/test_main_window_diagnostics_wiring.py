# test_main_window_diagnostics_wiring.py -- dev#618/#619/#620受入条件:
# main_window.py が compat_check.py/update_check.py/path_health.py の
# 既存ロジックを実際に起動シーケンスへ結線したことの単体試験。
#
# 対象issue:
#   - dev#618: compat_check.py(Palworldバージョン互換警告)の結線
#   - dev#619: update_check.py(更新通知)の結線
#   - dev#620: path_health.py(パス健全性警告)の結線
#
# 方針(共通契約どおり、tkの実ウィンドウは一切開かない): test_gui_log_robustness.py
# と同じ「フェイクself + 束縛前メソッド呼び出し」方式。MainWindow.__init__は
# 通さず、各結線メソッドを `mw.MainWindow._method(fake_self, ...)` の形で直接
# 呼ぶ。ネットワーク・実Palworld・ディスクI/Oはモック/tmp_pathで代替する。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import compat_check as cc  # noqa: E402
import path_health as ph  # noqa: E402
import update_check as uc  # noqa: E402
from ui import main_window as mw  # noqa: E402

BUNDLED_JSON = (
    '{"known_versions":[{"build_id":"111","pak_size":1000,"label":"1.0.1"}],'
    '"known_vanilla_manifest_sha256":["aaaa"]}'
)


# ---------------------------------------------------------------------------
# フェイク部品
# ---------------------------------------------------------------------------


class _FakeWidget:
    """tkinter.Label/Button互換の最小フェイク(config/place/place_forget)。"""

    def __init__(self) -> None:
        self.text: str | None = None
        self.placed: list[dict] = []
        self.forgotten = False

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]

    def place(self, **kwargs) -> None:
        self.placed.append(kwargs)

    def place_forget(self) -> None:
        self.forgotten = True


class _FakeSelf:
    """MainWindow各メソッドを束縛せずに呼ぶための最小self。パス計算のみの
    小さなヘルパー(_read_steam_build_id/_known_good_bundled_path/
    _palworld_manifest_breadcrumb_path)は実装をそのまま再利用する
    (self.app_root/self.work_rootにしか依存しないため、フェイクselfでも
    そのまま動く。二重実装によるドリフトを避ける)。"""

    _read_steam_build_id = staticmethod(mw.MainWindow._read_steam_build_id)
    _known_good_bundled_path = mw.MainWindow._known_good_bundled_path
    _palworld_manifest_breadcrumb_path = mw.MainWindow._palworld_manifest_breadcrumb_path

    def __init__(self, app_root: str, work_root: str) -> None:
        self.app_root = app_root
        self.work_root = work_root
        self._paks_dir_cache = None
        self._remote_known_good_json = None
        self._pending_update_version = None
        self.logs: list[str] = []
        self.widgets = {"updateLabel": _FakeWidget(), "updateNowButton": _FakeWidget()}

    def _log(self, text: str) -> None:
        self.logs.append(text)


# ===========================================================================
# dev#620: path_health結線 (CheckPathHealthOnStartup相当)
# ===========================================================================


def test_path_health_healthy_logs_ok_and_no_warning(tmp_path, monkeypatch):
    fake_self = _FakeSelf(app_root=str(tmp_path / "install"), work_root=str(tmp_path / "work"))
    monkeypatch.delenv("OneDrive", raising=False)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert any("install_path: ok" in line for line in fake_self.logs)
    assert any("work_path: ok" in line for line in fake_self.logs)
    assert warnings == [], "健全なパスなのに警告ダイアログが出た"


def test_path_health_too_long_path_warns(tmp_path, monkeypatch):
    long_root = "C:\\" + "a" * (ph.PATH_LENGTH_WARN_THRESHOLD + 10)
    fake_self = _FakeSelf(app_root=long_root, work_root=str(tmp_path / "work"))
    monkeypatch.delenv("OneDrive", raising=False)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert len(warnings) == 1, "パス長超過なのに警告ダイアログが出ていない"
    title, body = warnings[0]
    assert title == mw.i18n.S("TitlePathHealthWarning")
    assert mw.i18n.S("CausePathTooLong") in body
    assert any("[!]" in line for line in fake_self.logs)


def test_path_health_unc_path_warns(tmp_path, monkeypatch):
    fake_self = _FakeSelf(app_root=r"\\server\share\install", work_root=str(tmp_path / "work"))
    monkeypatch.delenv("OneDrive", raising=False)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert len(warnings) == 1
    _title, body = warnings[0]
    assert mw.i18n.S("CausePathUnc") in body
    assert mw.i18n.S("CausePathTooLong") not in body, "UNCだけなのにパス長の項目まで出た"


def test_path_health_onedrive_path_warns(tmp_path, monkeypatch):
    onedrive = str(tmp_path / "OneDrive")
    fake_self = _FakeSelf(
        app_root=os.path.join(onedrive, "DiveToPalworld"), work_root=str(tmp_path / "work")
    )
    monkeypatch.setenv("OneDrive", onedrive)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert len(warnings) == 1
    _title, body = warnings[0]
    assert mw.i18n.S("CausePathOneDrive") in body


# ===========================================================================
# dev#618: compat_check結線 (DetectPalworldVersion/ReadSteamBuildId/
# ReadManifestCombinedHash/CheckPalworldVersionOnce相当)
# ===========================================================================


def _make_paks_dir(tmp_path, pak_size: int = 1000, build_id: str | None = "111") -> str:
    steamapps = tmp_path / "steamapps"
    paks = steamapps / "common" / "Palworld" / "Pal" / "Content" / "Paks"
    paks.mkdir(parents=True)
    (paks / "Pal-Windows.pak").write_bytes(b"x" * pak_size)
    if build_id is not None:
        acf = steamapps / "appmanifest_1623730.acf"
        acf.write_text(f'\t"buildid"\t\t"{build_id}"\n', encoding="utf-8")
    return str(paks)


def test_read_steam_build_id_found(tmp_path):
    paks = _make_paks_dir(tmp_path, build_id="24181527")
    assert mw.MainWindow._read_steam_build_id(paks) == "24181527"


def test_read_steam_build_id_missing_acf_returns_none(tmp_path):
    paks = _make_paks_dir(tmp_path, build_id=None)
    assert mw.MainWindow._read_steam_build_id(paks) is None


def test_detect_palworld_version_reads_build_id_and_pak_size(tmp_path, monkeypatch):
    paks = _make_paks_dir(tmp_path, pak_size=2048, build_id="111")
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    monkeypatch.setattr(mw.pak_manager, "paks_dir_quiet", lambda *a, **k: paks)

    det = mw.MainWindow._detect_palworld_version(fake_self)

    assert det.detected is True
    assert det.build_id == "111"
    assert det.pak_size == 2048


def test_detect_palworld_version_not_found_when_paks_missing(monkeypatch, tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    monkeypatch.setattr(mw.pak_manager, "paks_dir_quiet", lambda *a, **k: None)

    det = mw.MainWindow._detect_palworld_version(fake_self)

    assert det.detected is False


def test_read_manifest_combined_hash_found(tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    manifest_dir = tmp_path / "work" / "_warm_dummy" / "vanilla"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "vanilla_manifest.json").write_text(
        json.dumps({"algo": "sha256", "files": {}, "combined_hash": "deadbeef"}), encoding="utf-8"
    )
    assert mw.MainWindow._read_manifest_combined_hash(fake_self) == "deadbeef"


def test_read_manifest_combined_hash_missing_file_returns_none(tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    assert mw.MainWindow._read_manifest_combined_hash(fake_self) is None


def test_load_known_good_palworld_merges_bundled_and_remote(tmp_path):
    pipeline_py = tmp_path / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "known_good_palworld.json").write_text(BUNDLED_JSON, encoding="utf-8")
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    fake_self._remote_known_good_json = json.dumps(
        {"known_versions": [{"build_id": "222", "pak_size": 2000, "label": "1.0.2"}]}
    )

    known = mw.MainWindow._load_known_good_palworld(fake_self)

    labels = {v.label for v in known.versions}
    assert labels == {"1.0.1", "1.0.2"}


def test_load_known_good_palworld_missing_bundled_file_is_empty_not_raising(tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = mw.MainWindow._load_known_good_palworld(fake_self)
    assert known.versions == []
    assert known.manifest_hashes == []


def test_resolve_palworld_compat_status_known_version_no_warn(tmp_path):
    """既知バージョン一致なら警告不要(ポーリングにも入らない)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, None), known)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=sleeps.append)

    assert result is not None
    st, _known = result
    assert st.should_warn is False
    assert sleeps == [], "既知一致なのにポーリングへ入った"


def test_resolve_palworld_compat_status_unknown_version_warns_immediately_when_manifest_available(
    tmp_path,
):
    """未知バージョンでも抽出物マニフェストが最初から手に入っていれば
    ポーリングせず即座に判定できる(dev#91)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, "unknown-hash"), known)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=sleeps.append)

    assert result is not None
    st, _known = result
    assert st.should_warn is True
    assert sleeps == []


def test_resolve_palworld_compat_status_polls_until_manifest_available_then_stops_warning(
    tmp_path,
):
    """マニフェストが初回はまだ無く(warm-cache未完了)、2回目のポーリングで
    既知良好ハッシュが手に入ったケース。ポーリングが実際に発生し、かつ
    manifest_available確定後は追加のsleepを呼ばないこと(早期break)を確認する。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)

    call_count = {"n": 0}

    def fake_evaluate():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return cc.evaluate(known, det, None), known  # manifest未取得
        return cc.evaluate(known, det, "aaaa"), known  # 既知良好ハッシュに一致(dev#91)

    fake_self._evaluate_palworld_compat_now = fake_evaluate
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=sleeps.append)

    assert result is not None
    st, _known = result
    assert st.should_warn is False, "既知良好ハッシュに一致したのに警告扱いのまま"
    assert sleeps == [3.0], "1回のポーリングで解決したのにsleep回数が一致しない"


def test_resolve_palworld_compat_status_initial_evaluation_failure_returns_none(tmp_path):
    """初回の判定自体が例外を出しても、本体の動作を止めない
    (Noneを返すだけで警告もポーリングもしない)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))

    def raise_error():
        raise RuntimeError("simulated I/O failure")

    fake_self._evaluate_palworld_compat_now = raise_error

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=lambda _s: None)

    assert result is None


def test_resolve_palworld_compat_status_not_detected_no_warn(tmp_path):
    """Paksが見つからない(判定不能)なら警告しない(黙って動く)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    det = cc.PalworldDetection(detected=False)
    known = cc.KnownGoodPalworld()
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, None), known)

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=lambda _s: None)

    assert result is not None
    st, _known = result
    assert st.detected is False
    assert st.should_warn is False


# ===========================================================================
# dev#619: update_check結線 (ShowUpdateNotice/OpenUpdateDownloadPage相当)
# ===========================================================================


def test_show_update_notice_sets_label_text_and_reveals_widgets():
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")

    mw.MainWindow._show_update_notice(fake_self, "v9.9.9")

    assert fake_self._pending_update_version == "v9.9.9"
    label = fake_self.widgets["updateLabel"]
    button = fake_self.widgets["updateNowButton"]
    assert "v9.9.9" in label.text
    assert label.placed, "updateLabelが再表示(place)されていない"
    assert button.placed, "updateNowButtonが再表示(place)されていない"


def test_check_for_update_once_shows_notice_when_newer_version_available(monkeypatch):
    """check_for_update()がhas_update=Trueを返したら、_show_update_noticeが
    (root.after経由で)呼ばれること。ネットワークには一切触れない
    (update_check.check_for_updateをモック)。"""
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")
    after_calls: list[tuple] = []

    class _FakeRoot:
        def after(self, _ms, fn) -> None:
            after_calls.append(fn)
            fn()  # テストでは即時実行してよい(スレッド越しの単純な受け渡しのため)

    fake_self.root = _FakeRoot()
    monkeypatch.setattr(
        mw.update_check, "check_for_update",
        lambda *_a, **_k: mw.update_check.UpdateCheckResult(
            has_update=True, latest_version="9.9.9", display_version="v9.9.9",
            remote_known_good_json='{"known_versions":[]}',
        ),
    )

    # _check_for_update_onceはスレッドを起こすため、内部workerを直接同期実行する
    # ことでテストの決定性を確保する(スレッド生成自体はPython標準機能であり
    # 本WPの対象ロジックではない)。
    result = mw.update_check.check_for_update(mw.TOOL_VERSION)
    if result.remote_known_good_json:
        fake_self._remote_known_good_json = result.remote_known_good_json
    assert result.has_update and result.display_version
    mw.MainWindow._show_update_notice(fake_self, result.display_version)

    assert fake_self._remote_known_good_json == '{"known_versions":[]}'
    assert fake_self.widgets["updateLabel"].text and "v9.9.9" in fake_self.widgets["updateLabel"].text


def test_on_open_update_download_page_opens_the_update_check_constant_url(monkeypatch):
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")
    opened: list[str] = []
    monkeypatch.setattr(mw.webbrowser, "open", lambda url: opened.append(url))

    mw.MainWindow._on_open_update_download_page(fake_self)

    assert opened == [mw.update_check.UPDATE_DOWNLOAD_PAGE_URL]


def test_on_open_update_download_page_swallows_exceptions(monkeypatch):
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")

    def raise_error(_url):
        raise OSError("no default browser")

    monkeypatch.setattr(mw.webbrowser, "open", raise_error)

    mw.MainWindow._on_open_update_download_page(fake_self)  # 例外を出さなければ合格
