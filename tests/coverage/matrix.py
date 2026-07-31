# -*- coding: utf-8 -*-
r"""U53 カバレッジ検査: 検体表とカバレッジ軸の定義(機械が読むテーブル)。

------------------------------------------------------------------------
■ 設計の出発点(2026-07-25 責任者指摘)

> それ古いんだよ。試験の基本とはカバレッジだね。
> このシステムの入力は? vrm, fbx、prefab / 特徴は? MA対応、UE非依存 /
> できることは? 影の調整
> 最低限このへんの人間の操作に対するカバレッジを確保しないと試験としてだめだよね

旧 `tests\shipcheck\cases.py` は **アバター11体を同じ経路で流す**だけで、
軸としては「アバターの個体差」1本しか無い(しかも 11体の work\ ディレクトリは
現在1つも存在せず、スイート全体が SKIP になる)。
本ファイルはそれを **入力形式 × 機能 × 操作** の格子へ組み直したもの。
------------------------------------------------------------------------
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))

TEST_VRM_DIR = os.path.join(REPO_ROOT, "test", "vrm")
COLLECTED_DIR = os.path.join(TEST_VRM_DIR, "collected")
FLAT_EXPORT_DIR = os.path.join(REPO_ROOT, "work", "flatVer2_export")

# 変換に必ず要る外部ツール。job.json の paths へそのまま入る。
# 既存 job.json(work\u52_uvfix_flat\job.json 等)の実値をそのまま踏襲する。
BLENDER_EXE_CANDIDATES = [
    os.path.join(REPO_ROOT, "tools", "blender-4.3.2-windows-x64", "blender.exe"),
    r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64\blender.exe",
]
VRM_ADDON_ZIP_GLOB = os.path.join(REPO_ROOT, "third_party",
                                  "VRM_Addon_for_Blender-Extension*.zip")


def resolve_blender_exe():
    for p in BLENDER_EXE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def resolve_addon_zip():
    import glob
    hits = sorted(glob.glob(VRM_ADDON_ZIP_GLOB))
    return hits[-1] if hits else None


# ---------------------------------------------------------------------------
# 検体表
# ---------------------------------------------------------------------------
# n_images / n_materials は 2026-07-25 に glb の JSON チャンクを直接数えた実測値
# (probes.avatar_texture_profile が実行時にも数え直すので、ここはあくまで選定の根拠)。
#
# 「アトラス行数」= ceil(sqrt(スロット数))。DEV_NOTES(28) §1 のとおり
# **rows>=3 で壊れる疑いが出荷ブロッカーとして未解決**なので、
# rows=1 / 2 / 3 / 4以上 をそれぞれ踏む検体を必ず入れる。

SPECIMENS = {
    # --- 入力形式: VRM ---
    "vrm_kate": {
        "path": os.path.join(COLLECTED_DIR, "100Avatars_038_Kate.vrm"),
        "input_format": "vrm",
        "n_images": 1, "n_materials": 1, "rows_estimate": 1,
        "why": "テクスチャ1枚の最小構成。アトラス rows=1 の対照",
    },
    "vrm_robothead": {
        "path": os.path.join(COLLECTED_DIR, "100Avatars_017_Voxel_Robothead.vrm"),
        "input_format": "vrm",
        "n_images": 2, "n_materials": 1, "rows_estimate": 2,
        "why": "rows=2 の下端",
    },
    "vrm_alicia051": {
        "path": os.path.join(TEST_VRM_DIR, "AliciaSolid_vrm-0.51.vrm"),
        "input_format": "vrm",
        "n_images": 8, "n_materials": 12, "rows_estimate": 3,
        "why": ("rows=3 の代表検体。DEV_NOTES(28)§1では2026-07-25時点で"
                "UVセル包含チェック(Pass 3)が FATAL で止まる出荷ブロッカー"
                "だったが、同日中の Pass 1.5(面単位タイル正規化)と"
                "uvfix18(dev#18、2026-07-29、面/島単位の3分類+縮小フィット)"
                "で解消済み。dev#129(2026-07-30)で"
                "`pytest tests\\coverage -k vrm_alicia051 --allow-convert` "
                "実測により test_input_format[vrm_alicia051] が"
                "preflight 12/12 PASS・atlas NCC=0.9999 で PASS することを"
                "再確認した。**known_issue は無し**(以前ここにあった"
                "「未解決」の記述は解消後に取り残された誤記だった)"),
    },
    "vrm_seed": {
        "path": os.path.join(TEST_VRM_DIR, "Seed-san.vrm"),
        "input_format": "vrm",
        "n_images": 15, "n_materials": 17, "rows_estimate": 4,
        "why": "実運用アバター(742MB pak の実測に使われた個体)。rows=4",
    },
    "vrm_sample_b": {
        "path": os.path.join(COLLECTED_DIR, "AvatarSample_B.vrm"),
        "input_format": "vrm",
        "n_images": 30, "n_materials": 19, "rows_estimate": 6,
        "why": "検体中の最大テクスチャ数。rows=6 の上端",
    },
    "vrm_no_texture": {
        "path": os.path.join(COLLECTED_DIR, "EmissionMigration_v0.107.0.vrm"),
        "input_format": "vrm",
        "n_images": 0, "n_materials": 6, "rows_estimate": 1,
        "why": ("**負の検体**。テクスチャ0枚どころか**メッシュが1つも無い**"
                "(VRM アドオンの機能テスト用フィクスチャであってアバターではない)。"
                "U33 で 2件とも `[step01][FATAL] アバターのメッシュが1つも無い` で"
                "落ちることが実測済み。正常系として数えてはならない"),
        # DEV_NOTES(29)§5「壊れているVRMも資産。ただし正常系と混ぜず、
        # **『優雅に失敗すること』を期待値にする**」。
        # よって「変換が通ること」ではなく「FATAL で止まり、しかも
        # 原因が読めるメッセージであること」を PASS とする。
        "expected_failure": {
            "marker": "アバターのメッシュが1つも無い",
            "why": ("REPORT_U33_2026-07-25.md: collected 26体のうち FAIL はこの"
                    "EmissionMigration 2件のみ、失敗クラスは『メッシュ0のVRM』1種類"),
        },
    },
    "vrm_vrm1": {
        "path": os.path.join(COLLECTED_DIR, "AliciaSolid_vrm-1.00.vrm"),
        "input_format": "vrm",
        "n_images": 7, "n_materials": 12, "rows_estimate": 3,
        "why": "VRM 1.0 系(README 対応範囲『VRM 0.x / 1.0』の 1.0 側)",
        "known_issue": (
            "2026-07-26判明: このファイルは specVersion=1.0 を名乗るが、"
            "VRM1.0 が要求する180度移行が適用されていない不良ファイル"
            "(頂点座標が VRM0.51 版と非反転で同一)。Blenderプレビュー・"
            "実機とも後ろ向きになるのは**この検体自体の不備**であり、"
            "パイプラインのバグではない——正規の VRM1.0 検体 `vrm_vita`"
            "(VRoid Studio直接エクスポート)がパイプライン無変更のまま"
            "正面を向いたことで対照確認済み"
            "(scratchpad\\verify_W_vita_vrm1.md)。**削除しないこと**。"
            "『不良な VRM1.0 ファイルを食わせたときの挙動』を見る検体"
            "として価値がある"
        ),
    },
    "vrm_vita": {
        "path": os.path.join(TEST_VRM_DIR, "VitaVRM1.0.vrm"),
        "input_format": "vrm",
        "n_images": 28, "n_materials": 15, "rows_estimate": 6,
        "why": (
            "**正規の VRM1.0 検体**(VRoid Studio-1.20.2 の直接エクスポート、"
            "`extensions.VRMC_vrm.specVersion` = \"1.0\" を実測済み)。"
            "`vrm_vrm1`(AliciaSolid_vrm-1.00.vrm)が後ろ向きになる不具合の"
            "原因切り分け(検体の不備かパイプラインの不備か)のため"
            "2026-07-26 追加。パイプライン無変更のままフル変換 exit=0・"
            "pak生成・preflight G1〜G11全PASS・実機プレイ開始確認まで"
            "完走し、Blenderプレビュー・実機とも正面を向いた"
            "(scratchpad\\verify_W_vita_vrm1.md)。"
            "= vrm_vrm1 側が不良ファイルであることの対照(パイプラインは"
            "正しい)。rows=6 なので rows_estimate 上端(vrm_sample_b)の"
            "重複にも見えるが、n_materials/n_images の実測値が異なる"
            "別個体であり、正規VRM1.0という軸自体の代表個体として別枠で扱う"
        ),
    },

    # --- 入力形式: FBX(+ humanoid.json)= Unity/MA 経路の出口 ---
    "fbx_flat_ma": {
        "path": os.path.join(FLAT_EXPORT_DIR, "flatVer2.fbx"),
        "humanoid_json": os.path.join(FLAT_EXPORT_DIR, "humanoid.json"),
        "input_format": "fbx",
        "n_images": None, "n_materials": 4, "rows_estimate": 2,
        "why": ("Unity ヘッドレス輸出(export_from_unity.ps1 → DiveToPalworldExporter.cs)"
                "の実成果物。material_map.json / unity_export.log が同居しており、"
                "**MA(NDMF)ベイク後**の姿である証拠になる。現在唯一のフル変換成功実績"),
        "ma_evidence": [
            os.path.join(FLAT_EXPORT_DIR, "humanoid.json"),
            os.path.join(FLAT_EXPORT_DIR, "material_map.json"),
            os.path.join(FLAT_EXPORT_DIR, "unity_export.log"),
        ],
    },
}


# ---------------------------------------------------------------------------
# 検体表(prefab / MA)— 2026-07-26 追加、責任者提供
# ---------------------------------------------------------------------------
# DEV_NOTES(29)§5 で「**prefab: 検体が無い / MA対応: 部分**」と申告していた穴を
# 埋めるためのもの。**リポジトリ外**(UNITY_PROJECTS_ROOT、既定 CLAUDE.md 記載の
# 標準レイアウト)にあり、検体をリポジトリへ入れない方針(再配布にあたる)とも
# 矛盾しない。
#
# VRM/FBX 検体と決定的に違う点:
#   * 変換の**前段に Unity ヘッドレス起動が要る**(prefab → FBX + humanoid.json)。
#     数分〜十数分/体。したがって別の安全弁 `--allow-unity` を切ってある。
#   * その過程で **Unity プロジェクト側へ書き込みが起きる**
#     (`Assets\Editor\DiveToPalworldExporter.cs` の複製。FBX Exporter が
#     未導入なら `Packages\manifest.json` へ追記)。他人の作業場を触るので
#     既定 OFF は必須。
#   * **Unity でプロジェクトを開いていると起動できない**(Unity の二重起動禁止)。
#
# `ma_expected`: MA(NDMF)ベイクが**実際に走ったこと**を要求するか。
#   unity_export.log に `D2P: NDMFベイク完了` が出れば走った、
#   `D2P: NDMF未導入のためベイクをスキップ` ならベイクしていない。
#   ——「実装した」と「効いている」は別(DEV_NOTES(29)§4)なので、
#   ここは**成果物の存在ではなくログの実行痕**で判定する。

# 開発機ローカルの Unity プロジェクト群のルート。リポジトリ外(かつ人によって
# 置き場所が違いうる)なので、決め打ちにせず環境変数で上書きできるようにする
# (未設定時は元の既定値のまま動く。CLAUDE.md記載の標準レイアウト)。
UNITY_PROJECTS_ROOT = os.environ.get("D2P_UNITY_PROJECTS_ROOT", r"C:\UnityP")


def _unity_project_path(*parts):
    return os.path.join(UNITY_PROJECTS_ROOT, *parts)


PREFAB_SPECIMENS = {
    "prefab_flats_apron": {
        "path": _unity_project_path("apron", "Assets", "Pan", "Flats.prefab"),
        "input_format": "prefab",
        "ma_expected": True,
        "why": ("GUI 統合時(2026-07-23)に一度だけ手で通した実績のある個体。"
                "既知の警告『バインド行列が不一致(ポーズ済みrig?)』が出る検体でもある"),
    },
    "prefab_shata": {
        "path": _unity_project_path("PanShata", "Assets", "sha-ta.prefab"),
        "input_format": "prefab",
        "ma_expected": True,
        "why": ("らすちんワークス系以外の実運用アバター。FaceEmo(jp.suzuryg.face-emo)"
                "が入った構成で、MA 以外の NDMF プラグインが同居する場合を踏む"),
    },
    "prefab_flatver2_agyo": {
        "path": _unity_project_path("Agyo", "Assets", "flatVer2.prefab"),
        "input_format": "prefab",
        "ma_expected": True,
        "collision_group": "flatVer2",
        "why": ("**同名衝突試験(1/2)**。掲載体 flatVer2 の Agyo プロジェクト版。"
                "prefab 1.5MB と Jinbe 版(190KB)は**別物**であり、"
                "取り違えれば見た目で分かる"),
    },
    "prefab_flatver2_jinbe": {
        "path": _unity_project_path("Jinbe", "Assets", "flatVer2.prefab"),
        "input_format": "prefab",
        "ma_expected": True,
        "collision_group": "flatVer2",
        "why": ("**同名衝突試験(2/2)**。Agyo 版とファイル名が同一。"
                "export_from_unity.ps1 の既定 -Out もパイプラインの作業域も"
                "**ファイル名から作られる**ため、素直にやると衝突する"),
    },
}


def prefab_default_export_dir(prefab_path):
    r"""`export_from_unity.ps1` が `-Out` 省略時に選ぶ出力先を**再現**する。

    実装(pipeline\cli\export_from_unity.ps1:78-81)::

        $name = [IO.Path]::GetFileNameWithoutExtension($Prefab)
        $Out  = Join-Path $Root "work\${name}_export"

    GUI 側(app\DiveToPalworld.cs:982)も同じ規則で出力先を組み立てる。
    **prefab のフルパスではなくファイル名しか見ていない**ので、
    別プロジェクトの同名 prefab は同じ場所へ出る。それを機械で示すために
    テスト側で規則を持つ(実装を読んで人が判断するのでは腐る)。
    """
    name = os.path.splitext(os.path.basename(prefab_path))[0]
    return os.path.join(REPO_ROOT, "work", "{}_export".format(name))


def prefab_unity_project(prefab_path):
    r"""prefab パスから Unity プロジェクトルートを逆算する(`Assets` の親)。

    export_from_unity.ps1:17-24 と同じ規則。見つからなければ None。
    """
    d = os.path.dirname(os.path.abspath(prefab_path))
    while d:
        if os.path.basename(d) == "Assets":
            return os.path.dirname(d)
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


# 設定フリップの基準体。
# fbx_flat_ma を選ぶ理由: 2026-07-25 時点で **フル変換が通ると分かっている唯一の検体**
# (DEV_NOTES(28)§3「flatVer2 以外のアバターは未確認/alicia は変換自体が通らない」)。
# 基準体が落ちると全フリップが落ちて交絡するので、ここは「通ると分かっているもの」を選ぶ。
# 代償: **フリップ検査はすべて FBX 入力の上でしか行われていない**(カバー表に明記)。
FLIP_BASE = "fbx_flat_ma"

# ---------------------------------------------------------------------------
# 設定フリップ表
# ---------------------------------------------------------------------------
# baseline は「全部既定」。各フリップは baseline から **1項目だけ**変える。
#
# diff_kind:
#   "material" … 統一MI(SKが実際に参照しているMI)が変わるはず
#   "mesh"     … 衣装/頭/髪 SK 本体が変わるはず
#
# 旧 shipcheck の `expected_diff_categories`(人が書いたパス部分文字列)は使わない。
# 期待パスを人が書くと、それが死んだ経路を指していても誰も気づけないため
# (2026-07-25 の事故そのもの)。差分の宛先は pak から実測する(probes.live_reference_sets)。

BASELINE_OVERRIDES = {
    "shoulder_offset_deg": 0.0,
    "merge_fingers": False,
    "unlit": False,
    "force_two_sided": True,   # job.json 既定・GUI 既定と同じ
    "shadow_lift": 0.0,        # パイプライン既定(k=0 は「MIを1バイトも書かない」端点)
    "drop_bones": [],
}

SETTING_FLIPS = [
    {
        "name": "shadow_lift_0to07",
        "axis": "影の調整",
        "overrides": {"shadow_lift": 0.7},
        "diff_kind": "material",
        "why": ("GUI 既定(影の濃さ30%)が job.json では shadow_lift=0.7。"
                "k=0 は MI を1件も書かない端点なので、0→0.7 は"
                "『統一MI 79件が丸ごと現れる』という最大の差になる"),
    },
    {
        "name": "shadow_lift_0to10",
        "axis": "影の調整",
        "overrides": {"shadow_lift": 1.0},
        "diff_kind": "material",
        "why": "k=1.0(真の unlit 相当)。単調性の上端",
    },
    {
        "name": "unlit_true",
        "axis": "影の調整",
        "overrides": {"unlit": True},
        "diff_kind": "material",
        "why": ("live_template.unify_shadow_ops は unlit=True を k=1.0 として扱う"
                "(2026-07-26 裁定)。よって unlit も material 差分を出すはず"),
    },
    {
        "name": "force_two_sided_false",
        "axis": "マテリアル",
        "overrides": {"force_two_sided": False},
        "diff_kind": "any",
        "why": ("旧 shipcheck は True(=既定値と同値)でフリップしていたため差分ゼロ、"
                "つまり検査になっていなかった。既定と**違う**側へ倒す"),
        "expected_broken": ("DEV_NOTES 2026-07-25(27)§1: noue では force_two_sided は"
                            "実機に届かない(死)と記録されている。FAIL ならその裏付け"),
    },
    {
        "name": "drop_bones_one",
        "axis": "削除ボーン",
        "overrides": None,   # 実行時に avatar_meta.json の bones から自動選定する
        "diff_kind": "mesh",
        "why": ("GUI に残る数少ない設定の1つ。旧 shipcheck に検査ケースが無かった。"
                "ボーン名は検体依存なので、baseline ビルドの avatar_meta.json から選ぶ"),
    },
    {
        "name": "merge_fingers_true",
        "axis": "ジオメトリ",
        "overrides": {"merge_fingers": True},
        "diff_kind": "mesh",
        "why": "step02_retarget 側の設定。noue でも確実に効くはず(DEV_NOTES(27)§1)",
    },
    {
        "name": "shoulder_offset_20",
        "axis": "ジオメトリ",
        "overrides": {"shoulder_offset_deg": 20.0},
        "diff_kind": "mesh",
        "why": "同上。肩の開き",
    },
]


# ---------------------------------------------------------------------------
# カバレッジ軸(README のカバー表と1対1に対応する。増減させたら両方直すこと)
# ---------------------------------------------------------------------------
def make_job(case_name, specimen_key, overrides=None,
             path_override=None, humanoid_override=None):
    r"""`work\u53_cov\cases\<case_name>\job.json` を作って返す。

    **既存の work\ ディレクトリは一切触らない。**検体ファイル(VRM/FBX)は
    読み取り専用で参照するだけ。ケースごとにディレクトリを分けるのは
    devtools\new_experiment.ps1 と同じ理由(2026-07-25 の取り違え事故2件)。

    conftest ではなくここに置いてあるのは、テストモジュールから
    `from conftest import ...` すると pytest のモジュール名解決に依存して
    壊れうるため(conftest は pytest が独自の名前で読み込む)。
    """
    import json
    import probes

    # prefab 検体は「Unity 輸出で生えた FBX」を後から差し込むので、
    # 検体表の path ではなく path_override が本体になる。
    spec = SPECIMENS.get(specimen_key) or PREFAB_SPECIMENS[specimen_key]
    job_dir = os.path.join(probes.CASES_DIR, case_name)
    os.makedirs(job_dir, exist_ok=True)
    job = {
        "vrm_path": path_override or spec["path"],
        "avatar_name": case_name,
        "license_confirmed": True,
        "engine_mode": "noue",
    }
    job.update(BASELINE_OVERRIDES)
    humanoid = humanoid_override or spec.get("humanoid_json")
    if humanoid:
        job["humanoid_json"] = humanoid
    paths = {
        "blender_exe": resolve_blender_exe(),
        "vrm_addon_zip": resolve_addon_zip(),
    }
    job["paths"] = paths
    job.update(overrides or {})
    job_path = os.path.join(job_dir, "job.json")
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    return job_path


# ---------------------------------------------------------------------------
# カバレッジ軸(README のカバー表と1対1に対応する。増減させたら両方直すこと)
# ---------------------------------------------------------------------------
# 責任者が名指しした4軸。coverage.md の先頭にこの4つを必ず出す。
# 値は AXES のキー(下の表)。ここに書いたキーが AXES に無ければ
# cov_report がその旨を出す(表と実装がズレたまま気づかないのを防ぐ)。
REQUIRED_AXES = {
    "入力形式(vrm / fbx / prefab)": [
        "入力形式:VRM", "入力形式:FBX+humanoid.json", "入力形式:prefab",
        "入力形式:prefab(同名衝突)"],
    "MA対応": ["MA(Modular Avatar)対応"],
    "UE非依存": ["UE非依存"],
    "影の調整": ["影の調整:値が出力に届く", "影の調整:影のみ更新経路"],
}

AXES = {
    "入力形式:VRM": {"covered": True, "by": "test_inputs.py::test_input_format",
                     "note": "VRM 0.x 6体 + VRM 1.0 1体"},
    "入力形式:FBX+humanoid.json": {"covered": True, "by": "test_inputs.py::test_input_format",
                                   "note": "flatVer2(Unity 輸出物)1体のみ"},
    "入力形式:prefab": {"covered": "opt-in", "by": "test_prefab.py",
                        "note": ("検体4体を UNITY_PROJECTS_ROOT 配下から参照"
                                 "(2026-07-26 責任者提供)。"
                                 "静的検査(経路の存在・Unity プロジェクトの解決・同名衝突)は"
                                 "常に走る。**端から端まで(Unity 輸出→変換→pak)は "
                                 "--allow-unity 指定時のみ**——Unity ヘッドレス起動が要り、"
                                 "他人の Unity プロジェクトへ書き込みが起きるため")},
    "MA(Modular Avatar)対応": {"covered": "opt-in", "by": "test_prefab.py::test_prefab_end_to_end",
                               "note": ("MA(NDMF)ベイクが**実際に走ったこと**を "
                                        "unity_export.log の `D2P: NDMFベイク完了` で確認する"
                                        "(成果物の存在ではなく実行痕で見る)。"
                                        "--allow-unity 無しではベイク済み輸出物 flatVer2_export が"
                                        "変換を通ることまで")},
    "入力形式:prefab(同名衝突)": {"covered": True, "by": "test_prefab.py::test_prefab_name_collision",
                                   "note": ("別プロジェクトの同名 prefab(Agyo / Jinbe の "
                                            "flatVer2.prefab)が同じ出力先・同じ作業域を指すこと。"
                                            "静的検査なので Unity 不要")},
    "UE非依存": {"covered": True, "by": "(N/A: dev#114でUEパイプライン自体を削除)",
                 "note": ("2026-07-29 dev#114: convert.ps1からUEクック分岐・pipeline\\ue\\・"
                          "UE系GUI導線を完全削除した。UEを選択する経路自体が存在しないため"
                          "構造的に保証される(旧 test_ue_independence.py は検査対象消滅につき削除)")},
    "影の調整:値が出力に届く": {"covered": True, "by": "test_settings.py::test_setting_flip",
                                "note": "shadow_lift 0→0.7 / 0→1.0 / unlit"},
    "影の調整:影のみ更新経路": {"covered": True, "by": "test_settings.py::test_materials_only_equivalence",
                                "note": "convert.ps1 -MaterialsOnly(noue)= fast_repack"},
    "削除ボーン": {"covered": True, "by": "test_settings.py::test_setting_flip",
                   "note": "ボーン名は baseline の avatar_meta.json から自動選定"},
    "マテリアル": {"covered": True, "by": "test_settings.py::test_setting_flip",
                   "note": "force_two_sided を**既定と違う側(False)**へ倒す。"
                           "DEV_NOTES(27)§1 では noue で届かないとされており、FAIL ならその裏付け"},
    "ジオメトリ": {"covered": True, "by": "test_settings.py::test_setting_flip",
                   "note": "merge_fingers / shoulder_offset_deg"},
    "テクスチャ枚数(アトラス行数)": {"covered": True, "by": "test_inputs.py::test_input_format",
                                     "note": "rows=1/2/3/4/6 の検体を通す"},
    "コラボ装備の除外": {"covered": True, "by": "test_settings.py::test_exclusions_untouched",
                         "note": "除外SK固有のMIが設定フリップで動かないこと"},
    "実機:クラッシュ/プレイ開始/見た目": {"covered": "opt-in",
                                          "by": "test_machine_coverage.py",
                                          "note": ("既定で除外。--allow-machine 指定時のみ。"
                                                   "2026-07-26: test_machine_visual_vrm_fbx / "
                                                   "test_machine_visual_prefab を追加し、"
                                                   "machine_base 1検体だけでなく "
                                                   "SPECIMENS/PREFAB_SPECIMENS の全検体を"
                                                   "実機に立たせて run_dir/shots/ へ正面SSを"
                                                   "集約するようにした(判定はクラッシュ/UI"
                                                   "失敗/成功の3値のみ、見た目自体は人間が"
                                                   "画像を見て判断する)")},
}
