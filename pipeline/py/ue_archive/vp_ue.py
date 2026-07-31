# -*- coding: utf-8 -*-
"""UE工程の共通設定。ジョブJSONは環境変数 D2P_JOB で渡される
(UnrealEditor-Cmdの-scriptに引数を渡せないため)。"""

import json
import os

JOB_PATH = os.environ.get("D2P_JOB")
if not JOB_PATH or not os.path.isfile(JOB_PATH):
    raise RuntimeError(f"環境変数D2P_JOBが不正: {JOB_PATH}")

with open(JOB_PATH, encoding="utf-8") as _f:
    JOB = json.load(_f)
JOB_DIR = os.path.dirname(os.path.abspath(JOB_PATH))

with open(os.path.join(JOB_DIR, "converted", "avatar_meta.json"),
          encoding="utf-8") as _f:
    META = json.load(_f)

GENDERS = JOB.get("genders", ["Male", "Female"])
AVATAR = JOB.get("avatar_name", "Avatar")
UNLIT = bool(JOB.get("unlit", False))
# 影の持ち上げ(0=Litそのまま 〜 1=実質アンリット)。GUIの「影の濃さ」スライダー
SHADOW_LIFT = max(0.0, min(1.0, float(JOB.get("shadow_lift", 0.0))))
# 全マテリアル強制両面(裏面が透けるモデル対策。既定ON)
FORCE_TWO_SIDED = bool(JOB.get("force_two_sided", True))

# ディスク側
CONV = os.path.join(JOB_DIR, "converted")
TEX_DIR = os.path.join(JOB_DIR, "textures")
VANILLA = os.path.join(JOB_DIR, "vanilla")
FBX = {g: os.path.join(CONV, f"Avatar_{g}.fbx") for g in GENDERS}
FBX_DUMMY = os.path.join(CONV, "Dummy.fbx")
# 揺れ髪: 存在すればHair001をダミーではなく本物の髪メッシュにする
FBX_HAIRSWAY = os.path.join(CONV, "HairSway.fbx")
HAIR_SWAY = bool(JOB.get("hair_sway", True)) and os.path.exists(FBX_HAIRSWAY)
CSV = {
    "outfit_male": os.path.join(VANILLA, "dup_outfit_male.csv"),
    "outfit_female": os.path.join(VANILLA, "dup_outfit_female.csv"),
    "head_male": os.path.join(VANILLA, "dup_head_male.csv"),
    "head_female": os.path.join(VANILLA, "dup_head_female.csv"),
    "hair": os.path.join(VANILLA, "dup_hair.csv"),
    "headequip": os.path.join(VANILLA, "dup_headequip.csv"),
}

# プロジェクト側(パルワールドの実パス構造。プロジェクト名は必ず「Pal」)
BASE = "/Game/Pal/Model/Character"
DIR_OUTFIT = {g: f"{BASE}/Player/Outfit/SK_Player_{g}_Outfit_OldCloth001"
              for g in ("Male", "Female")}
NAME_SK = {g: f"SK_Player_{g}_Outfit_OldCloth001" for g in ("Male", "Female")}
DIR_SKELETON = f"{BASE}/Skeleton/Human"
NAME_SKELETON = "SK_PalHuman_Skeleton"
DIR_PHYSICS = f"{BASE}/Player/Body/Female"  # 男性用物理はバニラに無い(女性用のみ)
NAME_PHYSICS = "SK_Player_Female_PhysicsAsset"
DIR_HEAD = f"{BASE}/Player/Head/Head001"
NAME_HEAD = {g: f"SK_Player_{g}_Head001" for g in ("Male", "Female")}
DIR_HAIR = f"{BASE}/Player/Hair/Hair001"
NAME_HAIR = "SK_Player_Hair001"
# 頭装備(兜)もダミー化して非表示にする(2026-07-21ぱん指摘: 頭装備が残って見える)
DIR_HEADEQUIP = f"{BASE}/Player/HeadEquip/HeadEquip001"
NAME_HEADEQUIP = "SK_HeadEquip001"
DIR_MATERIALS = f"{BASE}/Player/ModelMaterials/MainShader"

# マテリアル: avatar_meta.jsonのスロット表(m00.. → テクスチャ/単色/両面/アルファ)
SLOTS = META["slots"]
