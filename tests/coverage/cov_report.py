# -*- coding: utf-8 -*-
r"""U53: 実行後レポート生成(朝に見て分かる形)。

`conftest.pytest_sessionfinish` から呼ばれる。ここが落ちてもテスト結果は
`progress.log` / `tests.jsonl` / `gates.jsonl` に既に残っている(冗長化)。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import matrix  # noqa: E402

_ORDER = {"FAIL": 0, "SKIP": 1, "PASS": 2}


def _md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_reports(run_dir, gate_rows, exitstatus):
    _write_summary(run_dir, gate_rows, exitstatus)
    _write_coverage(run_dir, gate_rows)


def _write_summary(run_dir, gate_rows, exitstatus):
    n = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for r in gate_rows:
        n[r["status"]] = n.get(r["status"], 0) + 1
    lines = [
        "# U53 カバレッジ検査 結果",
        "",
        "- run_dir: `{}`".format(run_dir),
        "- pytest exitstatus: `{}`".format(exitstatus),
        "- ゲート判定: **PASS {} / FAIL {} / SKIP {}**".format(
            n.get("PASS", 0), n.get("FAIL", 0), n.get("SKIP", 0)),
        "",
        "> SKIP は「判定できなかった」であって合格ではない。FAIL と同じ重さで読むこと。",
        "",
        "## 判定一覧(FAIL → SKIP → PASS の順)",
        "",
        "| status | 軸 | ケース | ゲート | detail(抜粋) |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(gate_rows, key=lambda x: (_ORDER.get(x["status"], 9),
                                              str(x.get("axis")), str(x.get("case")))):
        detail = json.dumps(r.get("detail", {}), ensure_ascii=False, default=str)
        if len(detail) > 300:
            detail = detail[:300] + "…"
        lines.append("| {} | {} | {} | {} | {} |".format(
            r["status"], _md_escape(r.get("axis") or ""), _md_escape(r.get("case") or ""),
            _md_escape(r.get("gate")), _md_escape(detail)))
    lines += [
        "",
        "## 生ログ",
        "",
        "- `progress.log` — 1件ごとの進行(実行中でも読める)",
        "- `tests.jsonl` — pytest のテスト単位の結果(FAIL の traceback つき)",
        "- `gates.jsonl` — ゲート判定の全 detail(上表で切り詰めた分の全文)",
        "- `provenance.json` — git HEAD / テンプレート版 / 起動引数",
        "",
    ]
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_coverage(run_dir, gate_rows):
    """カバー状況の表。**実行結果に依らない設計上の表**(matrix.AXES)と、
    今回の実行で各軸が実際に判定されたかを並べる。"""
    by_axis = {}
    for r in gate_rows:
        ax = r.get("axis") or "(軸未指定)"
        d = by_axis.setdefault(ax, {"PASS": 0, "FAIL": 0, "SKIP": 0})
        d[r["status"]] = d.get(r["status"], 0) + 1

    cov_label = {True: "✔ あり", False: "✘ **検体が無い**", "partial": "△ 部分",
                 "opt-in": "△ 既定除外"}

    lines = ["# カバー状況", ""]

    # --- 責任者が名指しした4軸を最初に出す -----------------------------------
    lines += [
        "## 【最低ライン】責任者の4軸",
        "",
        "| 要求された軸 | 内訳の軸 | カバー | 今回の判定(P/F/S) |",
        "|---|---|---|---|",
    ]
    for req, keys in matrix.REQUIRED_AXES.items():
        for i, k in enumerate(keys):
            meta = matrix.AXES.get(k)
            if meta is None:
                lines.append("| {} | {} | ⚠ **AXES に未定義** | — |".format(
                    _md_escape(req) if i == 0 else "", _md_escape(k)))
                continue
            hit = by_axis.get(k)
            counts = ("{}/{}/{}".format(hit["PASS"], hit["FAIL"], hit["SKIP"])
                      if hit else "— (未実行)")
            lines.append("| {} | {} | {} | {} |".format(
                _md_escape(req) if i == 0 else "", _md_escape(k),
                cov_label.get(meta["covered"], str(meta["covered"])), counts))
    lines += [
        "",
        "> `✘ 検体が無い` は「検査していない」であって合格ではない。",
        "> `— (未実行)` はこの実行でその軸のテストが1件も走らなかったという意味"
        "(`--allow-convert` 無しなど)。",
        "",
    ]

    lines += [
        "## 設計上の軸(matrix.AXES が正本。増減させたらここも直る)",
        "",
        "| 軸 | カバー | 実行 | 判定(P/F/S) | 備考 |",
        "|---|---|---|---|---|",
    ]
    for name, meta in matrix.AXES.items():
        cov = cov_label.get(meta["covered"], str(meta["covered"]))
        hit = by_axis.get(name)
        counts = "{}/{}/{}".format(hit["PASS"], hit["FAIL"], hit["SKIP"]) if hit else "—"
        lines.append("| {} | {} | `{}` | {} | {} |".format(
            _md_escape(name), cov, _md_escape(meta["by"]), counts,
            _md_escape(meta["note"])))

    lines += ["", "## 検体の棚卸し", "",
              "| 検体 | 形式 | 画像 | マテリアル | アトラス行(推定) | 実在 | 備考 |",
              "|---|---|---|---|---|---|---|"]
    for k, s in matrix.SPECIMENS.items():
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            k, s["input_format"], s.get("n_images"), s.get("n_materials"),
            s.get("rows_estimate"), "○" if os.path.isfile(s["path"]) else "**×**",
            _md_escape(s.get("known_issue") or s.get("why", ""))))

    lines += ["", "## 今回の実行で軸ごとに出た判定", "",
              "| 軸 | PASS | FAIL | SKIP |", "|---|---|---|---|"]
    for ax, d in sorted(by_axis.items()):
        lines.append("| {} | {} | {} | {} |".format(
            _md_escape(ax), d["PASS"], d["FAIL"], d["SKIP"]))
    lines.append("")

    with open(os.path.join(run_dir, "coverage.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
