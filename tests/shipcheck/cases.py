# -*- coding: utf-8 -*-
"""U32: 出荷検査のデータ駆動テーブル(アバター表・設定フリップ表・プロファイル)。

出典: docs\\U23_SONNET_INSTRUCTIONS.md 5節(対象11体)・T1b(設定インベントリの
既知最低ライン)。ここは「機械が読むテーブル」であり、仕様の正本はU23指示書。
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# docs\U23_SONNET_INSTRUCTIONS.md 5節の実施順そのまま。
# full プロファイルはこの11体(+prefab枠のtoto、smoke/corpusの基準体も兼ねる)。
FULL_AVATARS = [
    "heon", "toto", "comodo", "shata", "alicia", "higan",
    "kutari", "zizi", "flatif", "sherbi", "tatsunoko",
]

# smoke: 最速回帰用の1体。totoが実績最速・2マテリアル・最安定(U23 T1b基準体と同じ理由)。
SMOKE_AVATARS = ["toto"]

CORPUS_DIR = os.path.join(REPO_ROOT, "test", "vrm", "collected")


def corpus_vrm_files():
    """test\\vrm\\collected 配下の *.vrm を安定順(名前順)で列挙する(=U27統合分)。"""
    if not os.path.isdir(CORPUS_DIR):
        return []
    return sorted(
        f for f in os.listdir(CORPUS_DIR) if f.lower().endswith(".vrm")
    )


def corpus_case_name(vrm_filename):
    stem = os.path.splitext(vrm_filename)[0]
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in stem)
    return "corpus_" + safe


# --- 設定フリップ表(H1: 設定配線ゲート) ---------------------------------
# docs\U23_SONNET_INSTRUCTIONS.md T1b-1「既知の最低ライン」5項目そのまま。
# 新設定が追加された場合はここへの追記漏れが検査漏れになる(cases.py内で完結)。
# expected_diff_categories: フリップ後pakとベースラインpakのエントリ単位ハッシュ差分が
# 出現するはずの資産カテゴリ(パス部分文字列)。差分が「想定外の場所にしか出ない」
# ケースを拾うためのヒントであり、ゲートH1の主判定はあくまで「差分の有無」。
SETTINGS_FLIPS = [
    {
        "name": "shoulder_offset_deg",
        "overrides": {"shoulder_offset_deg": 20.0},
        "expected_diff_categories": ["Player/Outfit/", "Player/Head/", "Player/Hair/"],
    },
    {
        "name": "merge_fingers",
        "overrides": {"merge_fingers": True},
        "expected_diff_categories": ["Player/Outfit/", "Player/Head/", "Player/Hair/"],
    },
    {
        "name": "unlit",
        "overrides": {"unlit": True},
        "expected_diff_categories": ["ModelMaterials/MainShader/"],
    },
    {
        "name": "shadow_lift",
        "overrides": {"shadow_lift": 0.0},
        "expected_diff_categories": ["ModelMaterials/MainShader/"],
    },
    {
        "name": "force_two_sided",
        "overrides": {"force_two_sided": True},
        "expected_diff_categories": ["ModelMaterials/MainShader/"],
    },
]

# H1のベースライン体(U23 T1bと同じ選定理由: 最速・2マテリアル・安定実績)
SETTINGS_BASELINE_AVATAR = "toto"


# --- プロファイル定義(README記載内容の機械可読な写し) ---------------------
PROFILES = {
    "smoke": {
        "avatars": SMOKE_AVATARS,
        "gates": ["offline", "machine"],
        "settings": False,
    },
    "full": {
        "avatars": FULL_AVATARS,
        "gates": ["offline", "machine", "visual"],
        "settings": True,
    },
    "corpus": {
        "avatars": None,  # 実行時に corpus_vrm_files() から動的生成
        "gates": ["offline", "machine"],
        "settings": False,
    },
    "stats": {
        "avatars": None,  # 実行時に --avatars で指定
        "gates": ["machine"],
        "settings": False,
        "repeat": True,
    },
}
