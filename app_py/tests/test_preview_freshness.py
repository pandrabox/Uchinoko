# test_preview_freshness.py -- dev#613/#617受入条件:
#   ①preview_freshness.py(新規)がC#版 BuildPreviewSig/SigFile/IsPreviewFresh/
#     SavePreviewSig(DiveToPalworld.cs L.2402-2431)と同じ構成要素・同じ書式で
#     署名を組み立てること(近似禁止、値を寄せない・閾値を緩めない)
#   ②main_window.pyの結線: dev#613(自動プレビューが鮮度チェックでスキップ
#     されること)、dev#617(Full Convertボタンの鮮度ゲート・StatusPreviewStale)
#
# tkの実ウィンドウは一切開かない(tk.Tk()を呼ばない)。main_window.py側の
# テストは既存test_gui_log_robustness.pyと同じ「フェイクself + unbound
# メソッド直接呼び出し」手法を踏襲する。
from __future__ import annotations

import inspect
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import preview_freshness as pf  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# build_preview_sig (BuildPreviewSig L.2402-2408)
# ---------------------------------------------------------------------------


def test_build_preview_sig_matches_cs_join_order_and_format():
    """C#: string.Join("|", vrmBox.Text.Trim(), shoulderBar.Value.ToString(),
    mergeFingersCheck.Checked.ToString(), dropBonesBox.Text.Trim())。
    bool.ToString()は"True"/"False"(先頭大文字)で、str(bool(...))と表記が
    一致する(近似ではなく固定文字列そのものを比較する)。"""
    sig = pf.build_preview_sig(
        vrm_path="  C:\\avatars\\Foo.vrm  ",
        shoulder_offset_deg=-3,
        merge_fingers=True,
        drop_bones_text="  Bone1, Bone2 ",
    )
    assert sig == "C:\\avatars\\Foo.vrm|-3|True|Bone1, Bone2"


def test_build_preview_sig_false_bool_and_zero_offset():
    sig = pf.build_preview_sig(
        vrm_path="a.vrm", shoulder_offset_deg=0, merge_fingers=False, drop_bones_text="",
    )
    assert sig == "a.vrm|0|False|"


def test_build_preview_sig_has_exactly_the_four_cs_components():
    """コメント(L.2404「プレビューの見た目に影響する設定だけ(影の濃さ・
    影なしはBlenderプレビューに出ない)」)どおり、shadow_bar/unlit/
    force_two_sidedはBuildPreviewSigの構成要素に含まれないこと
    (シグネチャに存在しないこと自体がその証跡=値を寄せて追加していない証明)。"""
    params = list(inspect.signature(pf.build_preview_sig).parameters)
    assert params == [
        "vrm_path",
        "shoulder_offset_deg",
        "merge_fingers",
        "drop_bones_text",
    ]


# ---------------------------------------------------------------------------
# sig_file_path (SigFile L.2410-2414)
# ---------------------------------------------------------------------------


def test_sig_file_path_uses_sanitized_avatar_name(tmp_path):
    work_root = str(tmp_path / "work")
    path = pf.sig_file_path(work_root, "C:/x/My Avatar-01!.vrm")
    assert path == os.path.join(work_root, "MyAvatar01", "preview_sig.txt")


# ---------------------------------------------------------------------------
# is_preview_fresh / save_preview_sig (IsPreviewFresh/SavePreviewSig L.2416-2431)
# ---------------------------------------------------------------------------


def test_is_preview_fresh_false_when_sig_file_missing(tmp_path):
    work_root = str(tmp_path / "work")
    assert pf.is_preview_fresh(work_root, "a.vrm", 0, False, "") is False


def test_save_then_is_fresh_true_for_identical_inputs(tmp_path):
    work_root = str(tmp_path / "work")
    os.makedirs(os.path.join(work_root, "a"), exist_ok=True)
    pf.save_preview_sig(work_root, "a.vrm", 1, True, "Bone1")
    assert pf.is_preview_fresh(work_root, "a.vrm", 1, True, "Bone1") is True


def test_negative_control_changed_drop_bones_makes_it_stale(tmp_path):
    """負の対照: drop_bones_textだけ変えても、鮮度判定はstale側へ倒れること
    (値を寄せる/緩める実装だとこれが緑にならない)。"""
    work_root = str(tmp_path / "work")
    os.makedirs(os.path.join(work_root, "a"), exist_ok=True)
    pf.save_preview_sig(work_root, "a.vrm", 0, False, "Bone1")
    assert pf.is_preview_fresh(work_root, "a.vrm", 0, False, "Bone1, Bone2") is False


def test_negative_control_changed_shoulder_offset_makes_it_stale(tmp_path):
    work_root = str(tmp_path / "work")
    os.makedirs(os.path.join(work_root, "a"), exist_ok=True)
    pf.save_preview_sig(work_root, "a.vrm", 0, False, "")
    assert pf.is_preview_fresh(work_root, "a.vrm", 5, False, "") is False


def test_negative_control_changed_merge_fingers_makes_it_stale(tmp_path):
    work_root = str(tmp_path / "work")
    os.makedirs(os.path.join(work_root, "a"), exist_ok=True)
    pf.save_preview_sig(work_root, "a.vrm", 0, False, "")
    assert pf.is_preview_fresh(work_root, "a.vrm", 0, True, "") is False


def test_negative_control_changed_vrm_path_makes_it_stale(tmp_path):
    """同じアバター名(sanitize後)に別のフルパスが来ても、署名にvrm_path
    そのものを含めるためstaleになる(SanitizeNameで潰れる差分ではない)。"""
    work_root = str(tmp_path / "work")
    os.makedirs(os.path.join(work_root, "Avatar"), exist_ok=True)
    pf.save_preview_sig(work_root, "C:/x/Avatar.vrm", 0, False, "")
    assert pf.is_preview_fresh(work_root, "C:/y/Avatar.vrm", 0, False, "") is False


def test_save_preview_sig_is_bom_less_utf8_with_no_trailing_newline(tmp_path):
    """SavePreviewSig() L.2429: File.WriteAllText(f, sig, new UTF8Encoding(false))
    相当。BOM無し・末尾改行を追加しない(WriteAllTextは改行を付与しない)こと。"""
    work_root = str(tmp_path / "work")
    os.makedirs(os.path.join(work_root, "a"), exist_ok=True)
    pf.save_preview_sig(work_root, "a.vrm", 0, False, "")
    with open(pf.sig_file_path(work_root, "a.vrm"), "rb") as fh:
        raw = fh.read()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM付きで書かれている(C#のUTF8Encoding(false)と不一致)"
    assert raw == pf.build_preview_sig("a.vrm", 0, False, "").encode("utf-8")


def test_save_preview_sig_swallows_missing_directory_like_cs_try_catch(tmp_path):
    """C#のSavePreviewSig()はtry/catch(Exception)で握りつぶす設計(ディレクトリが
    無ければFile.WriteAllTextが例外を出すが外へは伝播しない)。py版も同じ挙動に
    する(近似で「先にmkdirする」設計へ変えていないことの確認。ディレクトリを
    事前作成しない)。"""
    work_root = str(tmp_path / "work_no_dir")
    pf.save_preview_sig(work_root, "a.vrm", 0, False, "")  # 例外を投げなければ合格
    assert not os.path.exists(pf.sig_file_path(work_root, "a.vrm"))


# ---------------------------------------------------------------------------
# main_window._maybe_auto_preview (ApplyAvatarLoad L.1591-1597相当、dev#613)
# ---------------------------------------------------------------------------


class _NotRunningHandle:
    def is_running(self) -> bool:
        return False


class _RunningHandle:
    def is_running(self) -> bool:
        return True


class _FakeSelfForAutoPreview:
    def __init__(self, blender_ready=True, active_handle=None, fresh=False):
        self._blender_ready = blender_ready
        self._active_handle = active_handle
        self._fresh = fresh
        self.started: list[tuple] = []

    def _is_preview_fresh(self, _vrm_path: str) -> bool:
        return self._fresh

    def _start_pipeline(self, *, preview_only, materials_only, auto=False):
        self.started.append((preview_only, materials_only, auto))


def test_maybe_auto_preview_skips_when_fresh(tmp_path):
    """dev#613の本丸: 鮮度が新鮮なら自動プレビューを再実行しない。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _FakeSelfForAutoPreview(fresh=True)
    mw.MainWindow._maybe_auto_preview(fake, str(vrm))
    assert fake.started == [], "鮮度が新鮮でも自動プレビューを再実行している(dev#613再発)"


def test_maybe_auto_preview_runs_when_stale(tmp_path):
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _FakeSelfForAutoPreview(fresh=False)
    mw.MainWindow._maybe_auto_preview(fake, str(vrm))
    assert fake.started == [(True, False, True)]


def test_maybe_auto_preview_still_respects_blender_not_ready(tmp_path):
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _FakeSelfForAutoPreview(blender_ready=False, fresh=False)
    mw.MainWindow._maybe_auto_preview(fake, str(vrm))
    assert fake.started == []


def test_maybe_auto_preview_still_respects_already_running(tmp_path):
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _FakeSelfForAutoPreview(active_handle=_RunningHandle(), fresh=False)
    mw.MainWindow._maybe_auto_preview(fake, str(vrm))
    assert fake.started == []


def test_maybe_auto_preview_missing_file_returns_early(tmp_path):
    fake = _FakeSelfForAutoPreview(fresh=False)
    mw.MainWindow._maybe_auto_preview(fake, str(tmp_path / "missing.vrm"))
    assert fake.started == []


# ---------------------------------------------------------------------------
# main_window._refresh_convert_button_freshness
# (UpdateButtonStates() L.2479-2486/L.2520-2523相当、dev#617)
# ---------------------------------------------------------------------------


class _FakeWidget:
    def __init__(self) -> None:
        self.state_calls: list[str] = []
        self.text_calls: list[str] = []

    def config(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state_calls.append(kwargs["state"])
        if "text" in kwargs:
            self.text_calls.append(kwargs["text"])


class _FakeEntry:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value


class _FakeSelfForFreshnessRefresh:
    def __init__(self, vrm_path: str, fresh: bool, running: bool = False):
        self._fresh = fresh
        self.widgets = {
            "vrmBox": _FakeEntry(vrm_path),
            "convertButton": _FakeWidget(),
            "statusLabel": _FakeWidget(),
            "dropBonesBox": _FakeEntry(""),
        }
        self._active_handle = _RunningHandle() if running else None
        # dev#621: workRootFailedゲート(_refresh_convert_button_freshness側の
        # 早期return)がこのテスト群の対象外であることを明示。既定Falseで
        # 従来どおりhasVrm/fresh判定の経路を通す。
        self._work_root_failed = False
        # dev#639: blenderReadyゲート(同メソッド、#647統合で追加)も同様に
        # このテスト群の対象外。既定Trueでhas Vrm/fresh判定の経路を通す。
        self._blender_ready = True

    def _is_preview_fresh(self, _vrm_path: str) -> bool:
        return self._fresh


def test_refresh_convert_button_freshness_disables_and_shows_stale(tmp_path):
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _FakeSelfForFreshnessRefresh(str(vrm), fresh=False)
    mw.MainWindow._refresh_convert_button_freshness(fake)
    assert fake.widgets["convertButton"].state_calls == ["disabled"]
    assert fake.widgets["statusLabel"].text_calls == [i18n.S("StatusPreviewStale")]


def test_refresh_convert_button_freshness_enables_and_shows_ready(tmp_path):
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _FakeSelfForFreshnessRefresh(str(vrm), fresh=True)
    mw.MainWindow._refresh_convert_button_freshness(fake)
    assert fake.widgets["convertButton"].state_calls == ["normal"]
    assert fake.widgets["statusLabel"].text_calls == [i18n.S("StatusReadyToConvert")]


def test_refresh_convert_button_freshness_no_vrm_disables_without_touching_text():
    fake = _FakeSelfForFreshnessRefresh("", fresh=False)
    mw.MainWindow._refresh_convert_button_freshness(fake)
    assert fake.widgets["convertButton"].state_calls == ["disabled"]
    assert fake.widgets["statusLabel"].text_calls == []


def test_refresh_convert_button_freshness_skips_status_text_while_running(tmp_path):
    """UpdateButtonStates()はrunning中、`if (!running)`の外側にある
    convertButton.Enabled自体は計算するがテキストは書き換えない(L.2504)。
    これが無いと、実行中メッセージ(StatusPreviewGenerating等)を
    StatusPreviewStaleで上書きしてしまう。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    fake = _FakeSelfForFreshnessRefresh(str(vrm), fresh=False, running=True)
    mw.MainWindow._refresh_convert_button_freshness(fake)
    assert fake.widgets["convertButton"].state_calls == ["disabled"]
    assert fake.widgets["statusLabel"].text_calls == [], (
        "実行中にstatusLabelを書き換えている"
        "(実行中メッセージを上書きしてしまう、UpdateButtonStates()の"
        "`if (!running)`ガード相当が欠落)"
    )


# ---------------------------------------------------------------------------
# main_window._finalize_fresh_preview
# (OnPipelineDone() L.2914-2915 `SavePreviewSig(); UpdateButtonStates();`相当、
#  dev#613/#617)
# ---------------------------------------------------------------------------


def test_finalize_fresh_preview_saves_then_refreshes_in_order():
    calls: list[str] = []

    class _Fake:
        def _save_preview_sig(self, vrm_path: str) -> None:
            calls.append(f"save:{vrm_path}")

        def _refresh_convert_button_freshness(self) -> None:
            calls.append("refresh")

    fake = _Fake()
    mw.MainWindow._finalize_fresh_preview(fake, "a.vrm")
    assert calls == ["save:a.vrm", "refresh"], (
        "SavePreviewSig() -> UpdateButtonStates() の順序(C# L.2914-2915)と一致しない"
    )


def test_finalize_fresh_preview_makes_button_fresh_end_to_end(tmp_path):
    """preview_freshness.pyの実I/Oを使ったエンドツーエンド版: 生成直後は
    stale(convertButton disabled)だったものが、_finalize_fresh_previewを
    通すとfresh(convertButton normal)へ切り替わること。"""
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    work_root = str(tmp_path / "work")
    os.makedirs(os.path.join(work_root, "a"), exist_ok=True)

    class _RealishFake:
        def __init__(self) -> None:
            self.work_root = work_root
            self._shoulder_offset_deg = 0
            self._merge_fingers = False
            self._active_handle = None
            self._work_root_failed = False
            self._blender_ready = True
            self.widgets = {
                "vrmBox": _FakeEntry(str(vrm)),
                "convertButton": _FakeWidget(),
                "statusLabel": _FakeWidget(),
                "dropBonesBox": _FakeEntry(""),
            }

        _is_preview_fresh = mw.MainWindow._is_preview_fresh
        _save_preview_sig = mw.MainWindow._save_preview_sig
        _refresh_convert_button_freshness = mw.MainWindow._refresh_convert_button_freshness
        _finalize_fresh_preview = mw.MainWindow._finalize_fresh_preview

    fake = _RealishFake()
    # 事前確認: まだsig未保存なのでstale
    fake._refresh_convert_button_freshness()
    assert fake.widgets["convertButton"].state_calls[-1] == "disabled"

    fake._finalize_fresh_preview(str(vrm))
    assert fake.widgets["convertButton"].state_calls[-1] == "normal", (
        "SavePreviewSig()後もconvertButtonがdisabledのまま"
        "(dev#617: フル変換ボタンがここで解禁されるはず)"
    )
