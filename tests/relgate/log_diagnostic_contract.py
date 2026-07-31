# -*- coding: utf-8 -*-
"""T4(WP6): ログ診断力の契約テスト。

前提(CLAUDE.md「問い合わせからのデバッグ」節が正本): ユーザーのアバターは絶対に
送ってもらえない。手に入るのは「ログをコピー」の中身だけであり、**ログだけで
原因に到達できないなら、その不具合は永久に直らない**。しかも実例(帽子が
足元に落ちて灰色になる事故)が示すとおり、必要な情報は**成功時のログにも**
残っていなければならない(失敗ログの強化だけでは足りない。実際の問い合わせの
多くは「成功したのに結果が変」という形で来る)。

このスクリプトは、実際に1回変換した結果のログ(`devtools\\relgate.py` 層1/2が
生成する `<run_dir>\\convert_stdout.log`(convert.ps1の標準出力全文、本WP6で
`relgate.py`側に追記させた) + `<run_dir>\\build\\logs\\*.log`(Blender/Python
工程別ログ))を読み、問い合わせ診断に必須の構造情報が実際に出力されているかを
機械検査する。

必須項目とその根拠:
  1. engine_mode   — どのパイプライン経路(noue/ue)が使われたか。INQUIRIES.md
                      ID006/008/010/013/015/017は全て「noueモードのdev
                      fallbackがwork/toto/vanillaを誤って参照する」系の同一
                      症状で、経路の特定が診断の出発点になる。
  2. phase_progress — どの工程まで到達したか(`=== Phase N ===`系マーカー)。
                      bug-reportスキルは「ログの各行をコードとfile:lineで
                      突き合わせる」ことを要求しており、フェーズ区切りが
                      無いと該当行がどの工程のものか特定できない。
  3. step_completion — Blender工程(step01/step02)が実際に完了したか
                      (`[stepNN...] OK (...)`)。「実装した」と「効いている」は
                      別(CLAUDE.md)——工程が呼ばれたことではなく完了したことを
                      示す証跡が要る。
  4. material_slot_coverage — 各メッシュがmaterial_map.json(Unity輸出)で
                      解決されたスロット構成。CLAUDE.md実例(帽子が足元に落ちて
                      灰色になる事故)は `material_map.jsonに無いメッシュ: Beret`
                      という**失敗時**ログ1行で原因特定できたが、**成功時にも
                      同種の行(どのメッシュがどのテクスチャに解決されたか)が
                      残っていること**が「たまたま失敗した特定メッシュだけでなく
                      全体の構成」を問い合わせなしで再構成できる条件になる。
  5. remap_lines    — 頂点グループのリターゲット結果(`remap: <mesh> -> N pal
                      groups`)。同事故のもう半分(位置ズレ)の原因特定に使った
                      実ログそのもの。
  6. pak_output_path — 最終的に生成したpakの実パスが完了ログに残っているか。
                      「成功したのに結果が変」型の問い合わせでは、そもそも
                      期待したpakが生成されたかどうか自体を確認する必要がある。

負の対照の作法: `check_log_diagnostics(text)` は任意のテキストに対して呼べる
純関数(pytest非依存)。該当行を除去したテキストを渡せば、その項目だけがFAILに
なることを直接確認できる(是正のたびにrelgate\\/pipeline\\本体を壊さずに
テストできる)。

使い方:
    python tests\\relgate\\log_diagnostic_contract.py <run_dir>
        (run_dir配下の convert_stdout.log + build\\logs\\*.log を集約して判定)

exit 0 = 必須項目が全て出力されている(PASS)。exit 1 = 1件でも欠落(FAIL)。
"""
import argparse
import glob
import os
import re
import sys

REQUIRED_CHECKS = [
    {
        "id": "engine_mode",
        "pattern": re.compile(r"===\s*EngineMode:\s*\S+"),
        "min_count": 1,
        "why": "どのパイプライン経路(noue/ue)が使われたかを特定できないと、"
               "INQUIRIES.md ID006等のnoue dev-fallback系症状の切り分けができない",
    },
    {
        "id": "phase_progress",
        "pattern": re.compile(r"===\s*Phase\s+\S+"),
        "min_count": 2,
        "why": "どの工程まで到達したかを示すフェーズ区切りが無いと、"
               "ログの各行をfile:lineへ突き合わせる診断(bug-reportスキル手順1)ができない",
    },
    {
        "id": "step_completion",
        "pattern": re.compile(r"\[step0[12]_(?:import_vrm|retarget)\.py\]\s*OK\s*\("),
        "min_count": 1,
        "why": "「実装した」と「効いている」は別(CLAUDE.md)——Blender工程が"
               "実際に完了した証跡(OKタイムスタンプ)が無いと、途中で無言スキップ"
               "していないかを確認できない",
    },
    {
        "id": "material_slot_coverage",
        "pattern": re.compile(r"\[step01\]\s*slot\s+m\d+:.*\(unity map\)"),
        "min_count": 1,
        "why": "CLAUDE.md実例(帽子事故)の恒久対策: 失敗したメッシュだけでなく"
               "全メッシュのマテリアル解決結果が成功時にも残っていないと、"
               "「成功したのに結果が変」型の問い合わせ(INQUIRIES.md多数)を"
               "診断できない。FBX(Unity輸出)経路が対象(shapell検体はこの経路)",
    },
    {
        "id": "remap_lines",
        "pattern": re.compile(r"\[step02\]\s*remap:\s*\S+\s*->\s*\d+\s*pal groups"),
        "min_count": 1,
        "why": "CLAUDE.md実例のもう半分(位置ズレ)。頂点グループのリターゲット結果が"
               "成功時にも残っている必要がある",
    },
    {
        "id": "pak_output_path",
        "pattern": re.compile(r"^pak:\s*.+\.pak\s*$", re.MULTILINE),
        "min_count": 1,
        "why": "「成功したのに結果が変」型の問い合わせでは、期待したpakが"
               "実際にどこに生成されたかがログから再構成できる必要がある",
    },
]


def check_log_diagnostics(text):
    """テキスト(複数ログの結合でよい)に対して全必須項目を判定する純関数。
    戻り値: {"ok": bool, "results": [{"id","ok","count","why"}], "missing": [...]}"""
    results = []
    missing = []
    for check in REQUIRED_CHECKS:
        matches = check["pattern"].findall(text or "")
        count = len(matches)
        ok = count >= check["min_count"]
        results.append({"id": check["id"], "ok": ok, "count": count,
                         "min_count": check["min_count"], "why": check["why"]})
        if not ok:
            missing.append(check["id"])
    return {"ok": not missing, "results": results, "missing": missing}


def gather_log_text(run_dir):
    """<run_dir>\\convert_stdout.log(devtools\\relgate.pyのrun_convert()が
    T4のために保存する、convert.ps1の標準出力全文) + <run_dir>\\build\\logs\\*.log
    (Blender/Python工程別ログ)を結合して返す。1つも見つからなければ空文字列
    (呼び出し側でfail-closed判定する)。"""
    parts = []
    stdout_log = os.path.join(run_dir, "convert_stdout.log")
    found_any = False
    if os.path.isfile(stdout_log):
        with open(stdout_log, encoding="utf-8", errors="replace") as f:
            parts.append(f.read())
        found_any = True
    logs_dir = os.path.join(run_dir, "build", "logs")
    for p in sorted(glob.glob(os.path.join(logs_dir, "*.log"))):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                parts.append(f.read())
            found_any = True
        except Exception:
            pass
    if not found_any:
        return None
    return "\n".join(parts)


def check_run_dir(run_dir):
    text = gather_log_text(run_dir)
    if text is None:
        return {"ok": False, "results": [], "missing": ["<no logs found>"],
                "reason": "run_dir配下にconvert_stdout.logもbuild\\logs\\*.logも"
                          "見つからない(fail-closed): {}".format(run_dir)}
    result = check_log_diagnostics(text)
    result["run_dir"] = run_dir
    result["text_len"] = len(text)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", help="convert.ps1のJobDir(convert_stdout.log / build\\logs\\ を含む)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.run_dir):
        print("FATAL: run_dirが存在しない: {}".format(args.run_dir))
        return 1

    result = check_run_dir(args.run_dir)
    print("=== T4 ログ診断力契約テスト ===")
    print("run_dir: {}".format(args.run_dir))
    if "reason" in result:
        print("FAIL: {}".format(result["reason"]))
        return 1

    for r in result["results"]:
        status = "PASS" if r["ok"] else "FAIL"
        print("[{}] {} (出現{}回、必要{}回以上)".format(status, r["id"], r["count"], r["min_count"]))
        if not r["ok"]:
            print("    根拠: {}".format(r["why"]))

    print("\n=== 結果: {} ===".format("PASS" if result["ok"] else "FAIL"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
