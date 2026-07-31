# -*- coding: utf-8 -*-
r"""dev#7: 診断ログへ生の絶対パス(利用者名・PC固有フォルダ名を含みうる)を出さない
ための共通ヘルパー。構造保存型の伏字化(値そのものはマスクしつつ、デバッグに必要な
「事実」の形だけ残す)。

出典: 元々 pipeline\py\fast_repack.py に `_path_facts` / `_display_path` として実装
されていた(dev#7の最初の修正、job.json/入力アバターの生フルパス漏洩対策)。
実ユーザー報告4AL4M4GT(非%USERPROFILE%ドライブの絶対パスがUnity/VCC・インストール先・
Steamライブラリで漏洩)を受けて、これを一般化してここへ切り出し、convert.ps1・
export_from_unity.ps1からも共通で使えるようにした(三段構成のうち「各所factify」、
work\issue_zero\i7\NOTES.md参照)。

呼び出し方法:
  - Python側から: from pipeline.py.path_privacy import display_path, path_facts, factify
  - PowerShell(export_from_unity.ps1)側から: 本ファイルをCLIとして呼ぶ
      python pipeline\py\path_privacy.py factify "<path>" [--base <dir> ...]
    標準出力へ1行だけ伏字化済み文字列を出す。

本モジュールは**表示専用**。実際のファイル操作(存在確認以外)には一切使わない。
"""
import argparse
import os
import sys


def drive_type(path):
    """Windowsのドライブ種別(固定/リムーバブル/ネットワーク等)。取得できなければ '?'。
    非Windows環境やctypes呼び出し失敗時も安全に '?' へ倒す(診断補助情報の欠落は
    許容するが、例外で呼び出し元を巻き込んで止めてはいけない)。"""
    try:
        import ctypes
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not drive:
            return "?"
        names = {0: "unknown", 1: "none", 2: "removable", 3: "fixed",
                 4: "network", 5: "CD-ROM", 6: "RAM disk"}
        t = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
        return names.get(t, str(t))
    except Exception:
        return "?"


def path_facts(p):
    """生フルパスの代わりに診断に要る事実だけを返す。
    ファイル名(利用者のフォルダ名は含まない)+存在有無+ドライブ種別+パスの特徴のみで、
    ユーザー名等が乗る中間ディレクトリ名は一切出さない。"""
    if not p:
        return "(no path)"
    name = os.path.basename(p.rstrip("\\/")) or p
    exists = os.path.exists(p)
    non_ascii = any(ord(c) > 127 for c in p)
    has_space = " " in p
    is_unc = p.startswith("\\\\")
    onedrive = os.environ.get("OneDrive", "")
    under_onedrive = bool(onedrive) and os.path.normcase(p).startswith(os.path.normcase(onedrive))
    return (f"name={name} exists={exists} drive_type={drive_type(p)} "
            f"length={len(p)} non_ascii_chars={non_ascii} has_space={has_space} "
            f"UNC={is_unc} under_OneDrive={under_onedrive}")


def display_path(p, bases=()):
    """生フルパスをログへ出さないための表示用ヘルパー。
    bases に列挙したディレクトリのいずれか配下なら相対パスにして返す
    (work配下の中間成果パスはこちらで足りる)。どれにも当てはまらなければ
    ファイル名のみを返す。実際のファイル操作には一切使わない(表示専用)。"""
    if not p:
        return p
    ap = os.path.abspath(p)
    for b in bases:
        if not b:
            continue
        try:
            b_abs = os.path.abspath(b)
            rp = os.path.relpath(ap, b_abs)
            if rp != "." and not rp.startswith(".."):
                return rp
        except Exception:
            continue
    return os.path.basename(ap.rstrip("\\/")) or ap


def factify(p, bases=()):
    """display_path + path_facts を1行にまとめた、呼び出し側が最も使いやすい形。
    - bases配下(work域等の既知安全パス)なら相対パスを主に見せる(十分に安全で有用)
    - それ以外は生パスを一切出さず、ファイル名+事実だけを返す(dev#7の核心対応:
      非%USERPROFILE%ドライブ・任意フォルダ名でも個人情報を出さない)
    """
    if not p:
        return "(no path)"
    disp = display_path(p, bases)
    ap = os.path.abspath(p)
    # dispがbases配下の相対パスに変換できた場合はそのまま使う(相対パスなので安全)。
    # できなかった場合(=ファイル名のみへ落ちた場合)はfactsも併記して診断価値を補う。
    if disp != (os.path.basename(ap.rstrip("\\/")) or ap):
        return disp
    return f"{disp} (path masked; {path_facts(p)})"


def _main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_factify = sub.add_parser("factify", help="1個のパスを伏字化して標準出力へ1行返す")
    p_factify.add_argument("path")
    p_factify.add_argument("--base", action="append", default=[],
                            help="このディレクトリ配下なら相対パスとして表示してよい(複数指定可)")

    args = ap.parse_args(argv)
    if args.cmd == "factify":
        sys.stdout.write(factify(args.path, tuple(args.base)) + "\n")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
