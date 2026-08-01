# test_main_window_restore.py -- dev#605/#616/#623受入条件:
#   dev#605: pak一覧の行選択(PakListSelectedIndexChanged)が実処理へ結線され、
#            スタブ文言("[stub] PakListSelectedIndexChanged")がもう出ないこと
#   dev#616 A+I: アバター再選択(browse/D&D/pak一覧いずれの経路でも)で
#            job.jsonの肩オフセット・指結合・unlit・両面・shadow_lift・
#            削除ボーン・規約確認状態と、プレビュー画像が復元されること
#   dev#623: 起動時に前回VRM(settings.load_last_vrm)があれば自動で開き直すこと
#
# 正本: app\DiveToPalworld.cs
#   - PakListSelectedIndexChanged  L.1126-1137
#   - RestoreSettings/ApplyRestoredSettings  L.1621-1663
#   - SetVrm/ApplyAvatarLoad  L.1510-1546, L.1571-1599
#   - Shownデリゲートの最後に開いたVRM復帰部分  L.1258-1271
#
# 実tkウィンドウは一切開かない(既存test_gui_log_robustness.py/test_dnd.pyと
# 同じく、束縛前のMainWindowメソッドをフェイクselfに対して直接呼ぶ)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
import settings  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# フェイク部品(実tkウィジェットは一切生成しない)
# ---------------------------------------------------------------------------


class _FakeEntry:
    """tk.Entry互換の最小フェイク(delete/insert/get)。vrmBox/dropBonesBox用。"""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def delete(self, _start, _end) -> None:
        self._text = ""

    def insert(self, _index, text: str) -> None:
        self._text += text

    def get(self) -> str:
        return self._text


class _FakeScale:
    """tk.Scale互換の最小フェイク(set/get)。shadowBar用。"""

    def __init__(self, value: int = 30) -> None:
        self._value = value

    def set(self, value) -> None:
        self._value = value

    def get(self):
        return self._value


class _FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakePakList:
    """ttk.Treeview互換の最小フェイク(selection()のみ)。"""

    def __init__(self, selected_iid: str | None) -> None:
        self._selected_iid = selected_iid

    def selection(self):
        return [self._selected_iid] if self._selected_iid else []


class _FakeSelf:
    """MainWindowの各メソッドを束縛せずに呼ぶための最小self。
    _apply_previewsは実画像読み込み(tk.PhotoImage)を伴うため、呼び出し記録
    だけを行うフェイクに差し替える(単体テストの対象はjob.json復元ロジック
    であり、実画像デコードはdev#599側の既存試験の担当)。

    試験対象の本物のメソッドをクラス属性として束縛する(既存
    test_gui_log_robustness.pyの`_poll_active_handle = mw.MainWindow.\
    _poll_active_handle`と同じ手法)。これにより、内部で`self._set_vrm_path(...)`
    のように他メソッドを呼ぶコード(例: _restore_last_vrm_on_startup →
    _set_vrm_path)もフェイクself上でそのまま解決できる。"""

    _set_vrm_path = mw.MainWindow._set_vrm_path
    _apply_restored_settings = mw.MainWindow._apply_restored_settings
    _on_pak_list_selected = mw.MainWindow._on_pak_list_selected
    _restore_last_vrm_on_startup = mw.MainWindow._restore_last_vrm_on_startup

    def __init__(self, app_root: str, work_root: str) -> None:
        self.app_root = app_root
        self.work_root = work_root
        self.widgets = {
            "vrmBox": _FakeEntry(),
            "dropBonesBox": _FakeEntry(),
            "shadowBar": _FakeScale(30),
            "statusLabel": _FakeLabel(),
            "pakList": _FakePakList(None),
        }
        self._shoulder_offset_deg = 0
        self._merge_fingers = False
        self._unlit = False
        self._force_two_sided = True
        self._license_confirmed = False
        self._pak_paths: dict[str, str] = {}
        self.applied_previews: list[dict] = []
        self.logs: list[str] = []
        self.auto_preview_calls: list[str] = []

    def _log(self, text: str) -> None:
        self.logs.append(text)

    def _apply_previews(self, previews: dict) -> None:
        self.applied_previews.append(previews)

    def _maybe_auto_preview(self, path: str) -> None:
        # 実変換起動(_start_pipeline)は本試験の対象外(dev#611の担当)。
        # 呼ばれたこと自体だけ記録する。
        self.auto_preview_calls.append(path)

    def _refresh_convert_button_freshness(self) -> None:
        # 2026-08-01 #635マージ後に判明: _set_vrm_path末尾がdev#613/#617で
        # このメソッドを呼ぶようになった。本ファイルの関心事はjob.json復元
        # ロジックのみ(convertButtonの鮮度判定はtest_preview_freshness.pyの
        # 担当)なので、呼ばれたことだけ許容するno-opにする。
        pass


# ---------------------------------------------------------------------------
# フィクスチャヘルパー
# ---------------------------------------------------------------------------


def _write_job_dir(work_root: str, avatar_name: str, vrm_path: str, **job_overrides) -> str:
    """job.jsonを直接組み立てて配置する(pr.write_job()はBlender/addon資産の
    存在に依存する分岐を持つため、本試験の関心事=復元ロジックだけに絞るには
    最小限のjob.jsonを自前で書く方が焦点が合う。キースキーマはDESIGN.md §2.1
    /pr.write_job()の出力と同じ)。"""
    job_dir = os.path.join(work_root, avatar_name)
    os.makedirs(job_dir, exist_ok=True)
    job = {
        "vrm_path": vrm_path,
        "avatar_name": avatar_name,
        "shoulder_offset_deg": 0,
        "merge_fingers": False,
        "unlit": False,
        "force_two_sided": True,
        "shadow_lift": 0.7,
        "drop_bones": [],
        "license_confirmed": False,
        "engine_mode": "noue",
        "paths": {"blender_exe": "blender.exe", "vrm_addon_zip": ""},
    }
    job.update(job_overrides)
    with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    return job_dir


def _write_previews(job_dir: str) -> None:
    converted = os.path.join(job_dir, "converted")
    os.makedirs(converted, exist_ok=True)
    with open(os.path.join(converted, "preview_male_stand.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake-front")
    with open(os.path.join(converted, "preview_male_stand_side.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nfake-side")


# ---------------------------------------------------------------------------
# _apply_restored_settings() 単体(dev#616 A+I)
# ---------------------------------------------------------------------------


def test_apply_restored_settings_returns_false_when_job_json_missing(tmp_path):
    fake = _FakeSelf(str(tmp_path / "app_root"), str(tmp_path / "work"))
    missing_job_dir = str(tmp_path / "work" / "NoSuchAvatar")

    result = mw.MainWindow._apply_restored_settings(fake, missing_job_dir, set_vrm_path=True)

    assert result is False
    assert fake.applied_previews == []  # 復元も試行もされない(L.1621-1623相当)


def test_apply_restored_settings_restores_all_fields(tmp_path):
    """dev#616 A: 肩オフセット・指結合・unlit・両面・shadow_lift・削除ボーン・
    規約確認状態がすべてjob.jsonから反映されること。"""
    work_root = str(tmp_path / "work")
    job_dir = _write_job_dir(
        work_root, "MyAvatar", "C:/avatars/MyAvatar.vrm",
        shoulder_offset_deg=12, merge_fingers=True, unlit=True,
        force_two_sided=False, shadow_lift=0.4,
        drop_bones=["Bone_L", "Bone_R"], license_confirmed=True,
    )
    _write_previews(job_dir)
    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)

    result = mw.MainWindow._apply_restored_settings(fake, job_dir, set_vrm_path=False)

    assert result is True
    assert fake._shoulder_offset_deg == 12
    assert fake._merge_fingers is True
    assert fake._unlit is True
    assert fake._force_two_sided is False
    assert fake._license_confirmed is True
    assert fake.widgets["dropBonesBox"].get() == "Bone_L, Bone_R"
    # shadow_lift=0.4 -> value = round(100 - 0.4*100) = 60 (L.1646-1648相当)
    assert fake.widgets["shadowBar"].get() == 60
    # vrmBoxはset_vrm_path=Falseなので変更されない
    assert fake.widgets["vrmBox"].get() == ""


def test_apply_restored_settings_sets_vrm_box_when_requested(tmp_path):
    """dev#605: pak一覧選択時(set_vrm_path=True)はjob.jsonのvrm_pathを
    vrmBoxへ反映する(RestoreSettings(..., true)相当)。"""
    work_root = str(tmp_path / "work")
    job_dir = _write_job_dir(work_root, "MyAvatar", "C:/avatars/MyAvatar.vrm")
    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)

    mw.MainWindow._apply_restored_settings(fake, job_dir, set_vrm_path=True)

    assert fake.widgets["vrmBox"].get() == "C:/avatars/MyAvatar.vrm"


def test_apply_restored_settings_license_confirmed_defaults_false_when_key_missing(tmp_path):
    """license_confirmedはJsonBool(json, "license_confirmed", false)相当
    (L.1652): キー欠落時は「現在値を維持」ではなく常にFalse。"""
    work_root = str(tmp_path / "work")
    job_dir = os.path.join(work_root, "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)
    minimal_job = {"vrm_path": "C:/avatars/MyAvatar.vrm"}  # license_confirmedキー無し
    with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(minimal_job, f)
    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)
    fake._license_confirmed = True  # 事前に真だった状態から始める

    mw.MainWindow._apply_restored_settings(fake, job_dir, set_vrm_path=False)

    assert fake._license_confirmed is False, (
        "license_confirmedはキー欠落時も常にFalseへ倒す契約(C#版 L.1652の"
        "JsonBool第3引数がハードコードfalseであることの移植漏れ)"
    )


def test_apply_restored_settings_other_fields_keep_current_value_when_key_missing(tmp_path):
    """shoulder_offset_deg等はJsonNum/JsonBoolの第3引数(既定値)が「現在値」
    そのもの(L.1643-1651)。license_confirmedとは対照的に、キー欠落時は
    変更されないことを確認する。"""
    work_root = str(tmp_path / "work")
    job_dir = os.path.join(work_root, "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)
    minimal_job = {"vrm_path": "C:/avatars/MyAvatar.vrm"}
    with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(minimal_job, f)
    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)
    fake._shoulder_offset_deg = 7
    fake._merge_fingers = True
    fake._unlit = True
    fake._force_two_sided = False

    mw.MainWindow._apply_restored_settings(fake, job_dir, set_vrm_path=False)

    assert fake._shoulder_offset_deg == 7
    assert fake._merge_fingers is True
    assert fake._unlit is True
    assert fake._force_two_sided is False


def test_apply_restored_settings_clamps_shoulder_offset_to_widget_range(tmp_path):
    """shoulderBar.Minimum/Maximumは-20/20(DiveToPalworld.cs L.1042)。
    job.jsonの値がその範囲外でもクランプされること。"""
    work_root = str(tmp_path / "work")
    job_dir = _write_job_dir(
        work_root, "MyAvatar", "C:/avatars/MyAvatar.vrm", shoulder_offset_deg=999,
    )
    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)

    mw.MainWindow._apply_restored_settings(fake, job_dir, set_vrm_path=False)

    assert fake._shoulder_offset_deg == 20


def test_apply_restored_settings_negative_shadow_lift_is_ignored(tmp_path):
    """JsonNum(json, "shadow_lift", -1); if (lift >= 0) ... (L.1646-1648)相当:
    負の値(既定センチネル)ならshadowBarに触れない。"""
    work_root = str(tmp_path / "work")
    job_dir = _write_job_dir(
        work_root, "MyAvatar", "C:/avatars/MyAvatar.vrm", shadow_lift=-1,
    )
    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)
    fake.widgets["shadowBar"] = _FakeScale(30)

    mw.MainWindow._apply_restored_settings(fake, job_dir, set_vrm_path=False)

    assert fake.widgets["shadowBar"].get() == 30  # 変更されない


def test_apply_restored_settings_loads_previews(tmp_path):
    """dev#616 I: プレビュー画像もjob.json復元と同時に反映されること。"""
    work_root = str(tmp_path / "work")
    job_dir = _write_job_dir(work_root, "MyAvatar", "C:/avatars/MyAvatar.vrm")
    _write_previews(job_dir)
    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)

    mw.MainWindow._apply_restored_settings(fake, job_dir, set_vrm_path=False)

    assert len(fake.applied_previews) == 1
    previews = fake.applied_previews[0]
    assert previews["front"] is not None and os.path.isfile(previews["front"])
    assert previews["side"] is not None and os.path.isfile(previews["side"])


# ---------------------------------------------------------------------------
# _on_pak_list_selected() (dev#605: PakListSelectedIndexChangedのスタブ解消)
# ---------------------------------------------------------------------------


def test_on_pak_list_selected_does_nothing_when_no_selection(tmp_path):
    fake = _FakeSelf(str(tmp_path / "app_root"), str(tmp_path / "work"))
    fake.widgets["pakList"] = _FakePakList(None)

    mw.MainWindow._on_pak_list_selected(fake)  # 例外を出さないこと

    assert fake.applied_previews == []
    assert fake.widgets["vrmBox"].get() == ""


def test_on_pak_list_selected_restores_settings_and_previews(tmp_path):
    work_root = str(tmp_path / "work")
    job_dir = _write_job_dir(
        work_root, "MyAvatar", "C:/avatars/MyAvatar.vrm",
        merge_fingers=True, drop_bones=["Tail"],
    )
    _write_previews(job_dir)
    pak_path = os.path.join(job_dir, "build", "MyAvatar_PlayerSwap_P.pak")
    os.makedirs(os.path.dirname(pak_path), exist_ok=True)
    with open(pak_path, "wb") as f:
        f.write(b"fake-pak")

    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)
    fake.widgets["pakList"] = _FakePakList("row0")
    fake._pak_paths = {"row0": pak_path}

    mw.MainWindow._on_pak_list_selected(fake)

    assert fake.widgets["vrmBox"].get() == "C:/avatars/MyAvatar.vrm"
    assert fake._merge_fingers is True
    assert fake.widgets["dropBonesBox"].get() == "Tail"
    # LoadPreviews(jd)(L.1135) + RestoreSettings内部のLoadPreviews(L.1660)で
    # 2回呼ばれる(C#版と同じ、無害な冗長呼び出し)。少なくとも1回は届いている
    # ことを確認する(呼び出し回数そのものはC#の実装詳細であり受入条件ではない)。
    assert len(fake.applied_previews) >= 1
    for previews in fake.applied_previews:
        assert previews["front"] is not None


def test_on_pak_list_selected_no_longer_logs_stub_message(tmp_path):
    """dev#605の核心受入条件: 選択してもスタブ文言がログへ出ないこと
    (負の対照は_stub()自体の単体挙動で別途保証されるため、ここでは新実装が
    "[stub] PakListSelectedIndexChanged"を出さないことだけを確認する)。"""
    work_root = str(tmp_path / "work")
    job_dir = _write_job_dir(work_root, "MyAvatar", "C:/avatars/MyAvatar.vrm")
    pak_path = os.path.join(job_dir, "build", "MyAvatar_PlayerSwap_P.pak")
    os.makedirs(os.path.dirname(pak_path), exist_ok=True)
    with open(pak_path, "wb") as f:
        f.write(b"fake-pak")

    fake = _FakeSelf(str(tmp_path / "app_root"), work_root)
    fake.widgets["pakList"] = _FakePakList("row0")
    fake._pak_paths = {"row0": pak_path}

    mw.MainWindow._on_pak_list_selected(fake)

    assert not any("[stub] PakListSelectedIndexChanged" in line for line in fake.logs)


def test_pak_list_treeview_select_binding_is_not_the_stub_handler():
    """grep相当の受入条件(brief: 「最後にself._stub(のgrepゼロを確認」)を
    ソースコードでも直接確認する(_build_widgets内のbind呼び出しが
    self._stub(...)ではなく実ハンドラを渡していること)。"""
    import inspect

    source = inspect.getsource(mw.MainWindow._build_widgets)
    assert 'pak_list.bind("<<TreeviewSelect>>", self._on_pak_list_selected)' in source
    assert "self._stub(\"PakListSelectedIndexChanged\")" not in source


# ---------------------------------------------------------------------------
# _set_vrm_path() 経由の復元結線(dev#616、browse/D&D/prefab輸出後経路)
# ---------------------------------------------------------------------------


def test_set_vrm_path_restores_settings_from_existing_job_json(tmp_path, monkeypatch):
    app_root = str(tmp_path / "app_root")
    os.makedirs(app_root, exist_ok=True)
    work_root = str(tmp_path / "work")
    vrm_path = str(tmp_path / "MyAvatar.vrm")
    with open(vrm_path, "wb") as f:
        f.write(b"fake-vrm")
    job_dir = _write_job_dir(
        work_root, pr.sanitize_name("MyAvatar"), vrm_path,
        unlit=True, license_confirmed=True,
    )
    _write_previews(job_dir)
    fake = _FakeSelf(app_root, work_root)

    mw.MainWindow._set_vrm_path(fake, vrm_path)

    assert fake.widgets["vrmBox"].get() == vrm_path
    assert fake._unlit is True
    assert fake._license_confirmed is True  # job.jsonの値で上書きされる
    assert len(fake.applied_previews) >= 1
    # 末尾で自動プレビュー判定(dev#611)にもそのまま繋がっている
    assert fake.auto_preview_calls == [vrm_path]


def test_set_vrm_path_resets_license_confirmed_when_job_json_absent(tmp_path):
    """job.jsonが無い(初めて開くアバター)場合はSetVrm() L.1514の
    `licenseConfirmed = false`のリセットのみが効くこと(復元処理は空振り)。"""
    app_root = str(tmp_path / "app_root")
    os.makedirs(app_root, exist_ok=True)
    work_root = str(tmp_path / "work")
    vrm_path = str(tmp_path / "BrandNewAvatar.vrm")
    with open(vrm_path, "wb") as f:
        f.write(b"fake-vrm")
    fake = _FakeSelf(app_root, work_root)
    fake._license_confirmed = True

    mw.MainWindow._set_vrm_path(fake, vrm_path)

    assert fake._license_confirmed is False
    assert fake.applied_previews == []  # job.jsonが無いので復元されない


# ---------------------------------------------------------------------------
# _restore_last_vrm_on_startup() (dev#623)
# ---------------------------------------------------------------------------


def test_restore_last_vrm_on_startup_opens_existing_last_vrm(tmp_path):
    app_root = str(tmp_path / "app_root")
    os.makedirs(app_root, exist_ok=True)
    vrm_path = str(tmp_path / "LastOpened.vrm")
    with open(vrm_path, "wb") as f:
        f.write(b"fake-vrm")
    settings.save_last_vrm(app_root, vrm_path)

    fake = _FakeSelf(app_root, str(tmp_path / "work"))

    mw.MainWindow._restore_last_vrm_on_startup(fake)

    assert fake.widgets["vrmBox"].get() == vrm_path
    assert fake.auto_preview_calls == [vrm_path]


def test_restore_last_vrm_on_startup_does_nothing_when_no_last_vrm_recorded(tmp_path):
    app_root = str(tmp_path / "app_root")
    os.makedirs(app_root, exist_ok=True)
    fake = _FakeSelf(app_root, str(tmp_path / "work"))

    mw.MainWindow._restore_last_vrm_on_startup(fake)

    assert fake.widgets["vrmBox"].get() == ""
    assert fake.auto_preview_calls == []


def test_restore_last_vrm_on_startup_does_nothing_when_file_no_longer_exists(tmp_path):
    """File.Exists(last)相当: 記録はあるがファイルが削除済みなら何もしない。"""
    app_root = str(tmp_path / "app_root")
    os.makedirs(app_root, exist_ok=True)
    deleted_vrm_path = str(tmp_path / "DeletedAvatar.vrm")
    settings.save_last_vrm(app_root, deleted_vrm_path)  # ファイル自体は作らない

    fake = _FakeSelf(app_root, str(tmp_path / "work"))

    mw.MainWindow._restore_last_vrm_on_startup(fake)

    assert fake.widgets["vrmBox"].get() == ""
    assert fake.auto_preview_calls == []


def test_restore_last_vrm_on_startup_swallows_exceptions(tmp_path, monkeypatch):
    """L.1262/1271のtry/catch(Exception)相当: 復元処理中の例外がGUI起動
    (__init__)を止めないこと。"""
    app_root = str(tmp_path / "app_root")
    os.makedirs(app_root, exist_ok=True)
    vrm_path = str(tmp_path / "Boom.vrm")
    with open(vrm_path, "wb") as f:
        f.write(b"fake-vrm")
    settings.save_last_vrm(app_root, vrm_path)

    fake = _FakeSelf(app_root, str(tmp_path / "work"))

    def _boom(_path):
        raise RuntimeError("simulated failure inside _set_vrm_path")

    fake._set_vrm_path = _boom

    mw.MainWindow._restore_last_vrm_on_startup(fake)  # 例外を外へ漏らしてはならない

    assert any("last vrm restore failed" in line for line in fake.logs)
