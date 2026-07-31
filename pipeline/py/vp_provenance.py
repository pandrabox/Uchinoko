# -*- coding: utf-8 -*-
"""U34: noueビルドの来歴(git commit/dirty・テンプレートバージョン・pak SHA1等)を
build_provenance.json として out_dir 直下に焼き込む。

convert_noue.py の main() が build_pak_from_avatar.main() を呼び終えた直後
(=ビルド成功が確定した時点)から write_build_provenance() を呼ぶ想定。
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import live_template  # noqa: E402

TAG = "vp_provenance"

_HASH_CHUNK_SIZE = 1024 * 1024  # 1MB


def _git_commit(repo_dir):
    """gitリポジトリでない環境(配布zip展開先等)ではgitコマンドが
    非0終了する(CalledProcessError)か、gitが未インストールなら
    FileNotFoundErrorになる。どちらも来歴スタンプ全体を失敗させては
    ならないため、"unknown" にフォールバックする(U41)。"""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=repo_dir, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


def _git_dirty(repo_dir):
    """_git_commit と同じ理由でフォールバックする(U41)。
    真偽が不明であることを表すため None(JSONのnull)を返す
    (Trueにするとdirty扱い誤判定、Falseにするとclean扱い誤判定になるため)。"""
    try:
        out = subprocess.run(["git", "status", "--porcelain"],
                              cwd=repo_dir, capture_output=True, text=True, check=True)
        return out.stdout.strip() != ""
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _sha1_of_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def write_build_provenance(out_dir, out_pak, avatar_name, template_source, repo_dir):
    """out_dir(build_provenance.jsonの出力先) にavatarのビルド来歴をJSONで書き込む。"""
    provenance = {
        "git_commit": _git_commit(repo_dir),
        "git_dirty": _git_dirty(repo_dir),
        "template_build_version": live_template.TEMPLATE_BUILD_VERSION,
        "avatar_name": avatar_name,
        "engine_mode": "noue",
        "build_time": datetime.now().isoformat(),
        "pak_filename": os.path.basename(out_pak),
        "pak_sha1": _sha1_of_file(out_pak),
        "template_source": template_source,
    }
    out_path = os.path.join(out_dir, "build_provenance.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, ensure_ascii=False, indent=2)
    print(f"[{TAG}] writing provenance stamp: {out_path}")
    return out_path
