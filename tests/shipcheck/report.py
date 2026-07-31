# -*- coding: utf-8 -*-
"""U32: 実行後レポート生成(junit-xml+Markdown結果表+コンタクトシート)。

conftest.pyのpytest_sessionfinishから自動的に呼ばれる
(`python -m tests.shipcheck.report <run_dir>` としても単独実行可)。
入力はrun_dir配下のresults.jsonl(各行=1ゲート判定、conftest.recorderが記録)
とprovenance.json。
"""
import glob
import html
import json
import os
import sys
import xml.sax.saxutils as sx


def _load_results(run_dir):
    path = os.path.join(run_dir, "results.jsonl")
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_provenance(run_dir):
    path = os.path.join(run_dir, "provenance.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_junit_xml(run_dir, rows):
    n_fail = sum(1 for r in rows if r["status"] == "FAIL")
    n_skip = sum(1 for r in rows if r["status"] == "SKIP")
    lines = ['<?xml version="1.0" encoding="utf-8"?>']
    lines.append('<testsuite name="shipcheck" tests="{}" failures="{}" skipped="{}">'.format(
        len(rows), n_fail, n_skip))
    for r in rows:
        classname = sx.escape(str(r.get("case") or "shipcheck"))
        name = sx.escape("{}::{}".format(r.get("avatar") or "-", r.get("gate") or "-"))
        lines.append('  <testcase classname="{}" name="{}">'.format(classname, name))
        if r["status"] == "FAIL":
            detail = sx.escape(json.dumps(r.get("detail", {}), ensure_ascii=False)[:2000])
            lines.append('    <failure message="gate FAIL">{}</failure>'.format(detail))
        elif r["status"] == "SKIP":
            lines.append('    <skipped/>')
        lines.append('  </testcase>')
    lines.append('</testsuite>')
    out_path = os.path.join(run_dir, "junit.xml")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def write_markdown_report(run_dir, rows, provenance):
    out_path = os.path.join(run_dir, "report.md")
    n_pass = sum(1 for r in rows if r["status"] == "PASS")
    n_fail = sum(1 for r in rows if r["status"] == "FAIL")
    n_skip = sum(1 for r in rows if r["status"] == "SKIP")
    lines = ["# 出荷検査結果レポート", ""]
    lines.append("## 来歴(provenance)")
    for k, v in provenance.items():
        lines.append("- {}: `{}`".format(k, v))
    lines.append("")
    lines.append("## サマリ: PASS {} / FAIL {} / SKIP {} (計{})".format(
        n_pass, n_fail, n_skip, len(rows)))
    lines.append("")
    lines.append("失敗を調査するときの入口: 下表でFAIL行のavatar/gateを特定し、"
                  "同じ行のdetail列(ログ末尾・differ件数・crash_evidence等)をまず読む。"
                  "machine系(E/F)はdetail.log、offline系(A/C)はdetail.log_tail、"
                  "H1はdetail.diff_paths_sampleに手がかりがある。")
    lines.append("")
    lines.append("| avatar | case | gate | status | detail |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        detail_str = json.dumps(r.get("detail", {}), ensure_ascii=False)
        if len(detail_str) > 300:
            detail_str = detail_str[:300] + "…"
        detail_str = detail_str.replace("|", "\\|").replace("\n", " ")
        lines.append("| {} | {} | {} | {} | {} |".format(
            r.get("avatar") or "-", r.get("case") or "-", r.get("gate") or "-",
            r["status"], detail_str))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def write_contact_sheet(run_dir, rows):
    """体ごとにゲーム内SS/Blender参照/判定JSONを並べる(見た目advisoryの最終目視用)。
    shots_dir(既定run_dir/shots)配下の*_crop.pngと、対応するwork\\<avatar>\\converted\\
    preview_male_stand.pngを拾えるだけ拾う。無ければその旨を書く(存在しない体は
    シートに載らないだけで、レポート全体は生成される)。"""
    shots_dir = os.path.join(run_dir, "shots")
    avatars = sorted({r["avatar"] for r in rows if r.get("avatar")})
    out_path = os.path.join(run_dir, "contact_sheet.md")
    lines = ["# コンタクトシート(体ごとのSS/参照/判定 並べ比べ)", ""]
    any_row = False
    for avatar in avatars:
        crops = sorted(glob.glob(os.path.join(shots_dir, avatar, "*_crop.png")))
        if not crops:
            continue
        any_row = True
        lines.append("## {}".format(avatar))
        crop_rel = os.path.relpath(crops[-1], run_dir).replace(os.sep, "/")
        lines.append("- ゲーム内クロップ: ![]({})".format(crop_rel))
        ref_candidates = [r for r in rows if r.get("avatar") == avatar and r.get("gate") == "G_compare_avatar"]
        if ref_candidates:
            verdict = ref_candidates[-1].get("detail", {}).get("verdict", {})
            lines.append("- compare_avatar判定: `{}`".format(json.dumps(verdict, ensure_ascii=False)))
        checker_rows = [r for r in rows if r.get("avatar") == avatar and r.get("gate") == "G_checker"]
        if checker_rows:
            verdict = checker_rows[-1].get("detail", {}).get("verdict", {})
            lines.append("- チェッカー柄判定: `{}`".format(json.dumps(verdict, ensure_ascii=False)))
        lines.append("")
    if not any_row:
        lines.append("(このrunにはSS/参照ペアが1件もありません — ゲートF/Gが未実施か、"
                      "--shots-dirの既定値が変更されています)")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def generate(run_dir):
    rows = _load_results(run_dir)
    provenance = _load_provenance(run_dir)
    junit_path = write_junit_xml(run_dir, rows)
    md_path = write_markdown_report(run_dir, rows, provenance)
    contact_path = write_contact_sheet(run_dir, rows)
    return {"junit": junit_path, "report_md": md_path, "contact_sheet": contact_path}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python report.py <run_dir>", file=sys.stderr)
        sys.exit(1)
    paths = generate(sys.argv[1])
    for k, v in paths.items():
        print("{}: {}".format(k, v))
