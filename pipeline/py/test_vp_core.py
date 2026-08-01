# -*- coding: utf-8 -*-
"""dev#642: vp_core.rmtree_robust() の単体テスト。

shared_cache/live_template は vp_core.lock_cache_dir_readonly() で意図的に
read-only施錠される(silent corruptionをloud failureに変えるための正規の
安全機構、vp_core.py の _set_tree_readonly 参照)。このツリーを丸ごと
コピー/削除する側(app_py\\build.py assemble_payload、devtools\\disk_guard.py
のrelease_cert旧run削除・孤立worktree削除)は、素のshutil.rmtreeでは
PermissionError(WinError 5)で必ず落ちる。rmtree_robust() がこれを
onexc/onerrorハンドラでos.chmod(S_IWRITE)して再試行することで乗り越える
ことを検証し、あわせて素のshutil.rmtreeが同じ入力で失敗すること
(負の対照)を確認する。

実行: python -m pytest pipeline\\py\\test_vp_core.py -q
"""
import os
import shutil
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core  # noqa: E402


def _make_readonly_tree(base):
    """base配下にread-onlyファイルを含む小さなツリー(ネスト込み)を作る。"""
    sub = os.path.join(base, "sub")
    os.makedirs(sub, exist_ok=True)
    top_file = os.path.join(base, "top.txt")
    nested_file = os.path.join(sub, "nested.uasset")
    with open(top_file, "w", encoding="utf-8") as f:
        f.write("top")
    with open(nested_file, "w", encoding="utf-8") as f:
        f.write("nested")
    os.chmod(top_file, stat.S_IREAD)
    os.chmod(nested_file, stat.S_IREAD)
    return top_file, nested_file


def test_plain_rmtree_fails_on_readonly_tree_negative_control(tmp_path):
    """負の対照: 素のshutil.rmtreeはread-onlyファイルを含むツリーで
    PermissionErrorになる(dev#642で実際に踏んだ障害そのもの)。"""
    target = tmp_path / "plain"
    target.mkdir()
    top_file, nested_file = _make_readonly_tree(str(target))

    with pytest.raises(OSError):
        shutil.rmtree(str(target))

    # 後始末(次のテストに影響しないよう属性を戻してから素の手段で削除する。
    # rmtree_robust自体は使わず、このテストの合否から独立させる)
    os.chmod(top_file, stat.S_IWRITE)
    os.chmod(nested_file, stat.S_IWRITE)
    shutil.rmtree(str(target), ignore_errors=True)


def test_rmtree_robust_removes_readonly_tree(tmp_path):
    """rmtree_robust()はread-onlyファイルを含むツリーでも削除に成功する。"""
    target = tmp_path / "robust"
    target.mkdir()
    _make_readonly_tree(str(target))

    vp_core.rmtree_robust(str(target))

    assert not target.exists()


def test_rmtree_robust_on_missing_path_is_noop(tmp_path):
    """存在しないパスは例外を投げず静かに戻る(shutil.rmtree素の挙動との
    差分。呼び出し側の `if out_dir.exists(): rmtree(...)` 前チェックを
    省略しても安全なようにする)。"""
    missing = tmp_path / "does_not_exist"
    vp_core.rmtree_robust(str(missing))  # 例外なしで戻ればOK


def test_rmtree_robust_ignore_errors_true_swallows_still_locked_file(tmp_path):
    """chmodしても尚削除できない項目(Windowsで開いたままのハンドル)がある
    場合: ignore_errors=Falseは例外を伝播し、ignore_errors=Trueは黙って
    続行する(shutil.rmtree(ignore_errors=True)と同じ契約)。"""
    target = tmp_path / "stubborn"
    target.mkdir()
    locked_path = target / "locked.txt"
    locked_path.write_text("x", encoding="utf-8")
    os.chmod(str(locked_path), stat.S_IREAD)

    # 共有削除フラグを立てないPythonの open() は、ハンドル保持中の削除を
    # Windows上でブロックする(chmodだけでは回避できない、read-only属性とは
    # 別種の失敗要因)。
    handle = open(str(locked_path), "rb")
    try:
        with pytest.raises(OSError):
            vp_core.rmtree_robust(str(target), ignore_errors=False)

        vp_core.rmtree_robust(str(target), ignore_errors=True)  # 例外を投げない
    finally:
        handle.close()

    # 後始末(ハンドルを閉じた後なら削除できる)
    if target.exists():
        os.chmod(str(locked_path), stat.S_IWRITE)
        shutil.rmtree(str(target), ignore_errors=True)
