# test_pipeline_runner.py -- WP-A2受入条件:
#   ①ヘッドレス関数がjob.jsonをDESIGN.md §2.1スキーマと1:1一致で生成
#   ②convert.ps1起動コマンド文字列が§2.1契約と一致
# (旧 --emit-wiring / tests\shipcheck\gui_wiring_check.py 相当のPython単体版。
#  DESIGN.md §5.2 WP-A2行。GUI起動を伴う確認はしない、単体テストのみ)
from __future__ import annotations

import json
import os
import re
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
import settings  # noqa: E402

# gui_wiring_check.py (tests\shipcheck\gui_wiring_check.py) の
# REQUIRED_TOP_KEYS/REQUIRED_PATHS_KEYSと同じ集合(dev#114以降、engine_modeは
# 必須には含めない設計だが、書くこと自体は指揮者裁定により明示要求されている
# ため、本ファイルでは「必須キーは満たしつつ、engine_modeも追加で存在する」
# ことの両方を検査する)。
REQUIRED_TOP_KEYS = ["vrm_path", "avatar_name", "paths"]
REQUIRED_PATHS_KEYS = ["blender_exe", "vrm_addon_zip"]


# ---------------------------------------------------------------------------
# fixtures (tmp_path ベース、実Blender/実third_partyには依存しない)
# ---------------------------------------------------------------------------


def _make_app_root(tmp_path, with_blender=False, with_addon=False):
    app_root = tmp_path / "app_root"
    app_root.mkdir()
    if with_blender:
        blender_dir = app_root / "tools" / "blender-4.3.2-windows-x64"
        blender_dir.mkdir(parents=True)
        (blender_dir / "blender.exe").write_bytes(b"")
    if with_addon:
        (app_root / "third_party").mkdir()
        (app_root / "third_party" / "VRM_Addon_for_Blender-Extension-4_4_0.zip").write_bytes(b"")
    return str(app_root)


def _make_vrm(tmp_path, name="MyAvatar.vrm"):
    vrm = tmp_path / name
    vrm.write_bytes(b"")
    return str(vrm)


# ---------------------------------------------------------------------------
# sanitize_name (SanitizeName L.1734-1742)
# ---------------------------------------------------------------------------


def test_sanitize_name_keeps_only_ascii_alnum():
    assert pr.sanitize_name("My Avatar-02!") == "MyAvatar02"


def test_sanitize_name_unicode_input_falls_back_to_avatar():
    assert pr.sanitize_name("アバター") == "Avatar"


def test_sanitize_name_empty_falls_back_to_avatar():
    assert pr.sanitize_name("") == "Avatar"


# ---------------------------------------------------------------------------
# find_first / asset_sub_dir / find_blender
# ---------------------------------------------------------------------------


def test_asset_sub_dir_prefers_assets_subdir_when_present(tmp_path):
    app_root = tmp_path / "app_root"
    (app_root / "assets" / "tools").mkdir(parents=True)
    assert pr.asset_sub_dir(str(app_root), "tools") == str(app_root / "assets" / "tools")


def test_asset_sub_dir_falls_back_to_repo_root_when_assets_missing(tmp_path):
    app_root = tmp_path / "app_root"
    app_root.mkdir()
    assert pr.asset_sub_dir(str(app_root), "tools") == str(app_root / "tools")


def test_find_first_returns_none_for_missing_dir(tmp_path):
    assert pr.find_first(str(tmp_path / "nope"), "*.zip") is None


def test_find_first_returns_none_when_no_match(tmp_path):
    (tmp_path / "somefile.txt").write_text("x")
    assert pr.find_first(str(tmp_path), "*.zip") is None


def test_find_blender_found(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True)
    found = pr.find_blender(app_root)
    assert found.endswith(os.path.join("blender-4.3.2-windows-x64", "blender.exe"))
    assert os.path.isfile(found)


def _disable_hardcoded_blender_fallback(monkeypatch):
    """FindBlender() L.1840のハードコード開発機フォールバック
    (C:\\P\\Work\\PalMod\\tools\\blender-4.3.2-windows-x64)は、たまたま実機
    (この開発機)に実在すると「見つからない」ケースの検査が環境依存になり
    再現性が壊れる(実測: このマシンには実在した)。app_root配下だけを見る
    経路を検査したいテストのために、そのハードコードパスだけ「無い」ことに
    差し替える(app_root配下の実ファイル判定は素通しする)。"""
    hardcoded = os.path.normcase(
        os.path.abspath(r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe")
    )
    original_isfile = os.path.isfile

    def fake_isfile(path):
        if os.path.normcase(os.path.abspath(path)) == hardcoded:
            return False
        return original_isfile(path)

    monkeypatch.setattr(pr.os.path, "isfile", fake_isfile)


def test_find_blender_not_found_falls_back_to_bare_exe(tmp_path, monkeypatch):
    _disable_hardcoded_blender_fallback(monkeypatch)
    app_root = _make_app_root(tmp_path, with_blender=False)
    assert pr.find_blender(app_root) == "blender.exe"


# ---------------------------------------------------------------------------
# paks_dir_quiet (settings_paksdir.txtキャッシュのみ、ダイアログ無し)
# ---------------------------------------------------------------------------


def test_paks_dir_quiet_none_when_no_cache(tmp_path):
    app_root = _make_app_root(tmp_path)
    assert pr.paks_dir_quiet(app_root) is None


def test_paks_dir_quiet_uses_cached_settings_when_pak_present(tmp_path):
    app_root = _make_app_root(tmp_path)
    paks_dir = tmp_path / "Paks"
    paks_dir.mkdir()
    (paks_dir / pr.PAL_WINDOWS_PAK_NAME).write_bytes(b"")
    settings.save_paksdir(app_root, str(paks_dir))
    assert pr.paks_dir_quiet(app_root) == str(paks_dir)


def test_paks_dir_quiet_none_when_cached_dir_missing_pak(tmp_path):
    app_root = _make_app_root(tmp_path)
    paks_dir = tmp_path / "Paks"
    paks_dir.mkdir()  # Pal-Windows.pak無し
    settings.save_paksdir(app_root, str(paks_dir))
    assert pr.paks_dir_quiet(app_root) is None


# ---------------------------------------------------------------------------
# write_job: job.jsonスキーマ1:1一致 (DESIGN.md §2.1)
# ---------------------------------------------------------------------------


def test_write_job_top_level_keys_match_design_schema(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    work_root = str(tmp_path / "work")
    vrm = _make_vrm(tmp_path)

    job_json_path = pr.write_job(app_root, work_root, vrm)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)

    # DESIGN.md §2.1のスキーマそのもの(§6-1裁定によりengine_modeを追加した版)
    expected_keys = {
        "vrm_path", "avatar_name", "shoulder_offset_deg", "merge_fingers",
        "unlit", "force_two_sided", "shadow_lift", "drop_bones",
        "license_confirmed", "engine_mode", "paths",
    }
    assert set(job.keys()) == expected_keys
    assert set(job["paths"].keys()) == {"blender_exe", "vrm_addon_zip", "palworld_pak"} \
        or set(job["paths"].keys()) == {"blender_exe", "vrm_addon_zip"}


def test_write_job_satisfies_gui_wiring_required_keys(tmp_path):
    """将来のC2(gui_wiring_check.py全面書換)がそのまま使えるよう、既存ゲートの
    必須キー集合(REQUIRED_TOP_KEYS/REQUIRED_PATHS_KEYS)を先取りで満たすことを
    確認する。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    work_root = str(tmp_path / "work")
    vrm = _make_vrm(tmp_path)

    job_json_path = pr.write_job(app_root, work_root, vrm)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)

    for k in REQUIRED_TOP_KEYS:
        assert k in job, "top-level必須キー欠落: {}".format(k)
    assert isinstance(job["vrm_path"], str) and job["vrm_path"].strip()
    assert isinstance(job["avatar_name"], str) and job["avatar_name"].strip()
    assert isinstance(job["paths"], dict)
    for k in REQUIRED_PATHS_KEYS:
        assert k in job["paths"], "paths必須キー欠落: {}".format(k)
        assert isinstance(job["paths"][k], str) and job["paths"][k].strip()
    # 指揮者裁定: engine_modeは明示的に書く(§0参照)
    assert job["engine_mode"] == "noue"


def test_write_job_engine_mode_is_noue(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["engine_mode"] == pr.ENGINE_MODE == "noue"


def test_write_job_avatar_name_sanitized_from_filename(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    vrm = _make_vrm(tmp_path, name="My Cool Avatar!!.vrm")
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), vrm)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["avatar_name"] == "MyCoolAvatar"
    # jobDir = workRoot\<name> になっていること(WriteJob() L.1775)
    assert os.path.dirname(job_json_path) == os.path.join(str(tmp_path / "work"), "MyCoolAvatar")


def test_write_job_drop_bones_parsed_trimmed_and_filtered(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path),
        drop_bones_text=" Hair_L , , Hair_R ,,Tail ",
    )
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["drop_bones"] == ["Hair_L", "Hair_R", "Tail"]


def test_write_job_drop_bones_empty_text_yields_empty_list(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path), drop_bones_text=""
    )
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["drop_bones"] == []


def test_write_job_shadow_lift_formula_matches_csharp():
    # WriteJob() L.1788-1789: shadow_lift = (100 - shadowBar.Value) / 100.0, 小数点以下3桁
    assert round((100 - 30) / 100.0, 3) == 0.7
    assert round((100 - 0) / 100.0, 3) == 1.0
    assert round((100 - 100) / 100.0, 3) == 0.0


def test_write_job_shadow_lift_value_wired(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), _make_vrm(tmp_path), shadow_bar_value=30
    )
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["shadow_lift"] == 0.7


def test_write_job_hidden_compat_defaults_match_csharp_initial_fields(tmp_path):
    # DiveToPalworld.cs L.1042-1046: 「内部互換性のためにフィールドを初期化
    # (UIには表示しない)」既定値そのもの
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["shoulder_offset_deg"] == 0
    assert job["merge_fingers"] is False
    assert job["unlit"] is False
    assert job["force_two_sided"] is True
    assert job["license_confirmed"] is False


def test_write_job_paths_when_assets_found(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["paths"]["blender_exe"].endswith("blender.exe")
    assert os.path.isfile(job["paths"]["blender_exe"])
    assert job["paths"]["vrm_addon_zip"].endswith(".zip")
    assert os.path.isfile(job["paths"]["vrm_addon_zip"])
    assert "palworld_pak" not in job["paths"]  # settings_paksdir.txt未設定


def test_write_job_paths_fallback_when_assets_missing(tmp_path, monkeypatch):
    _disable_hardcoded_blender_fallback(monkeypatch)
    app_root = _make_app_root(tmp_path, with_blender=False, with_addon=False)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["paths"]["blender_exe"] == "blender.exe"
    assert job["paths"]["vrm_addon_zip"] == ""  # 見つからない場合はnull安全に空文字列


def test_write_job_palworld_pak_included_when_paksdir_cached(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    paks_dir = tmp_path / "Paks"
    paks_dir.mkdir()
    (paks_dir / pr.PAL_WINDOWS_PAK_NAME).write_bytes(b"")
    settings.save_paksdir(app_root, str(paks_dir))

    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job["paths"]["palworld_pak"] == str(paks_dir / pr.PAL_WINDOWS_PAK_NAME)


def test_write_job_file_is_utf8_without_bom(tmp_path):
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    vrm = _make_vrm(tmp_path, name="日本語アバター.vrm")
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), vrm)
    raw = open(job_json_path, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")  # BOM無し
    text = raw.decode("utf-8")
    assert "日本語アバター.vrm" in text  # ensure_ascii=Falseで非ASCIIがそのまま出る


# ---------------------------------------------------------------------------
# read_job() (RestoreSettings L.1621-1628前段相当、dev#605/#616/#623)
# ---------------------------------------------------------------------------


def test_read_job_returns_none_when_file_missing(tmp_path):
    missing = str(tmp_path / "no_such_dir" / "job.json")
    assert pr.read_job(missing) is None


def test_read_job_returns_none_on_invalid_json(tmp_path):
    job_json = tmp_path / "job.json"
    job_json.write_text("{ not valid json", encoding="utf-8")
    assert pr.read_job(str(job_json)) is None


def test_read_job_round_trips_write_job_output(tmp_path):
    """write_job()が書いたjob.jsonをread_job()で読み戻すと、全キーが往復して
    一致すること(RestoreSettingsが自分の書いたWriteJob()の出力を読める、
    という最低限の契約)。"""
    app_root = _make_app_root(tmp_path, with_blender=True, with_addon=True)
    vrm = _make_vrm(tmp_path)
    job_json_path = pr.write_job(
        app_root, str(tmp_path / "work"), vrm,
        shoulder_offset_deg=5, merge_fingers=True, unlit=True,
        force_two_sided=False, shadow_bar_value=10,
        drop_bones_text="Bone_L, Bone_R", license_confirmed=True,
    )
    data = pr.read_job(job_json_path)
    assert data is not None
    assert data["vrm_path"] == vrm
    assert data["shoulder_offset_deg"] == 5
    assert data["merge_fingers"] is True
    assert data["unlit"] is True
    assert data["force_two_sided"] is False
    assert data["drop_bones"] == ["Bone_L", "Bone_R"]
    assert data["license_confirmed"] is True
    assert data["shadow_lift"] == round((100 - 10) / 100.0, 3)


# ---------------------------------------------------------------------------
# BuildConvertScriptPath / BuildConvertArgs / FindPwsh /起動コマンド契約
# (受入条件②: 起動コマンド文字列が§2.1の契約と一致)
# ---------------------------------------------------------------------------


def test_build_convert_script_path(tmp_path):
    app_root = str(tmp_path / "app_root")
    expected = os.path.join(app_root, "pipeline", "cli", "convert.ps1")
    assert pr.build_convert_script_path(app_root) == expected


def test_build_convert_args_no_flags():
    args = pr.build_convert_args(r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json")
    assert args == (
        '-NoProfile -ExecutionPolicy Bypass -File "C:\\app\\pipeline\\cli\\convert.ps1" '
        '-Job "C:\\work\\Avatar\\job.json"'
    )


def test_build_convert_args_preview_only():
    args = pr.build_convert_args(
        r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json", preview_only=True
    )
    assert args.endswith(" -PreviewOnly")
    assert "-MaterialsOnly" not in args


def test_build_convert_args_materials_only():
    args = pr.build_convert_args(
        r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json", materials_only=True
    )
    assert args.endswith(" -MaterialsOnly")
    assert "-PreviewOnly" not in args


def test_build_convert_args_both_flags_order():
    # BuildConvertArgs() L.1831-1833: previewOnlyが先、materialsOnlyが後
    args = pr.build_convert_args(
        r"C:\app\pipeline\cli\convert.ps1", r"C:\work\Avatar\job.json",
        preview_only=True, materials_only=True,
    )
    assert args.endswith(" -PreviewOnly -MaterialsOnly")


# gui_wiring_check.py の _ARGS_RE と同じ形の正規表現(§2.1契約の再検証)
_ARGS_RE = re.compile(r'^-NoProfile -ExecutionPolicy Bypass -File "([^"]+)" -Job "([^"]+)"')


def test_launch_command_matches_gui_wiring_contract_regex(tmp_path):
    app_root = str(tmp_path / "app_root")
    job_json = str(tmp_path / "work" / "Avatar" / "job.json")
    script = pr.build_convert_script_path(app_root)
    args = pr.build_convert_args(script, job_json)
    m = _ARGS_RE.match(args)
    assert m is not None
    assert m.group(1) == script
    assert m.group(2) == job_json


def test_find_pwsh_prefers_path_entry(tmp_path, monkeypatch):
    pwsh_dir = tmp_path / "pwshbin"
    pwsh_dir.mkdir()
    (pwsh_dir / "pwsh.exe").write_bytes(b"")
    monkeypatch.setenv("PATH", str(pwsh_dir))
    assert pr.find_pwsh() == str(pwsh_dir / "pwsh.exe")


def test_find_pwsh_falls_back_to_program_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    pf = tmp_path / "ProgramFiles"
    (pf / "PowerShell" / "7").mkdir(parents=True)
    (pf / "PowerShell" / "7" / "pwsh.exe").write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(pf))
    assert pr.find_pwsh() == str(pf / "PowerShell" / "7" / "pwsh.exe")


def test_find_pwsh_falls_back_to_powershell_exe(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no_pf_here"))
    assert pr.find_pwsh() == "powershell.exe"


# ---------------------------------------------------------------------------
# Unity輸出契約 (RunUnityExport L.2612-2682)
# ---------------------------------------------------------------------------


def test_build_unity_export_script_path(tmp_path):
    app_root = str(tmp_path / "app_root")
    expected = os.path.join(app_root, "pipeline", "cli", "export_from_unity.ps1")
    assert pr.build_unity_export_script_path(app_root) == expected


def test_resolve_unity_export_out_dir(tmp_path):
    work_root = str(tmp_path / "work")
    out_dir = pr.resolve_unity_export_out_dir(work_root, r"C:\proj\Assets\MyAvatar.prefab")
    assert out_dir == os.path.join(work_root, "MyAvatar_export")


def test_build_unity_export_args():
    args = pr.build_unity_export_args(
        r"C:\app\pipeline\cli\export_from_unity.ps1",
        r"C:\proj\Assets\MyAvatar.prefab",
        r"C:\work\MyAvatar_export",
    )
    assert args == (
        '-NoProfile -ExecutionPolicy Bypass -File "C:\\app\\pipeline\\cli\\export_from_unity.ps1" '
        '-Prefab "C:\\proj\\Assets\\MyAvatar.prefab" -Out "C:\\work\\MyAvatar_export"'
    )


def test_find_exported_fbx_returns_first_match(tmp_path):
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    (out_dir / "MyAvatar.fbx").write_bytes(b"")
    assert pr.find_exported_fbx(str(out_dir)) == str(out_dir / "MyAvatar.fbx")


def test_find_exported_fbx_none_when_missing(tmp_path):
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    assert pr.find_exported_fbx(str(out_dir)) is None


# ---------------------------------------------------------------------------
# 標準出力解析 (AppendLog L.2829-2883相当)
# ---------------------------------------------------------------------------


def test_strip_ansi_removes_color_codes():
    assert pr.strip_ansi("\x1b[31mred text\x1b[0m") == "red text"


def test_parse_progress_marker_basic():
    assert pr.parse_progress_marker("##PROGRESS## 42 Loading avatar") == (42, "Loading avatar")


def test_parse_progress_marker_clamps_to_0_100():
    assert pr.parse_progress_marker("##PROGRESS## 150 Overflow")[0] == 100
    assert pr.parse_progress_marker("##PROGRESS## -5 Underflow") is None  # 負数は\d+に非一致


def test_parse_progress_marker_none_when_not_matching():
    assert pr.parse_progress_marker("just a normal log line") is None


def test_parse_progress_marker_strips_ansi_first():
    line = "\x1b[32m##PROGRESS## 10 Preparing\x1b[0m"
    assert pr.parse_progress_marker(line) == (10, "Preparing")


def test_parse_avatar_warning_basic():
    assert pr.parse_avatar_warning("##AVATAR_WARNING## something looks off") == "something looks off"


def test_parse_avatar_warning_none_when_not_matching():
    assert pr.parse_avatar_warning("normal line") is None


# ---------------------------------------------------------------------------
# 進捗ラベル動的翻訳(ProgressLabelTemplates相当、A2担当分)
# ---------------------------------------------------------------------------


def test_translate_progress_label_dynamic_uses_fixed_dict_first():
    assert pr.translate_progress_label_dynamic("Loading avatar", lang="ja") == "アバターを読み込み中"


def test_translate_progress_label_dynamic_template_parallel_retarget():
    raw = "Retargeting skeleton + preview (parallel: Male, Female)"
    result = pr.translate_progress_label_dynamic(raw, lang="en")
    assert result == "Retargeting skeleton + preview (parallel: Male, Female)"
    result_ja = pr.translate_progress_label_dynamic(raw, lang="ja")
    assert result_ja == "スケルトン+プレビューをリターゲット中(並列: Male, Female)"


def test_translate_progress_label_dynamic_template_retarget_single():
    raw = "Retargeting skeleton (Male)"
    assert pr.translate_progress_label_dynamic(raw, lang="ja") == "スケルトンをリターゲット中(Male)"


def test_translate_progress_label_dynamic_template_preview_image():
    raw = "Generating preview image (Female)"
    assert pr.translate_progress_label_dynamic(raw, lang="zhCN") == "正在生成预览图(Female)"


def test_translate_progress_label_dynamic_unknown_label_passthrough():
    raw = "Some Brand New Stage Nobody Translated Yet"
    assert pr.translate_progress_label_dynamic(raw, lang="ja") == raw


def test_translate_progress_label_dynamic_empty_string():
    assert pr.translate_progress_label_dynamic("", lang="ja") == ""


# ---------------------------------------------------------------------------
# ProcessHandle: 実プロセス起動の非同期機構(convert.ps1やPalworldは起動しない、
# Pythonインタプリタ自身を子プロセスにしたごく軽量な単体試験)
# ---------------------------------------------------------------------------


def test_process_handle_captures_lines_and_exit_code():
    lines: list[str] = []
    exit_codes: list[int] = []
    script = 'import sys; print("hello"); print("world"); sys.exit(3)'
    handle = pr.ProcessHandle(
        sys.executable, '-c "{}"'.format(script.replace('"', '\\"')),
        on_line=lines.append, on_exit=exit_codes.append,
    )
    handle.start()
    import time

    deadline = time.time() + 10
    while time.time() < deadline and not exit_codes:
        handle.poll()
        time.sleep(0.05)
    handle.poll()

    assert lines == ["hello", "world"]
    assert exit_codes == [3]
    assert handle.exit_code == 3
    assert handle.is_running() is False
