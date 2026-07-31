# -*- coding: utf-8 -*-
"""dev#288 WP-UXIMPL(2026-07-30、提案1)の単体試験。

背景: `pipeline\\cli\\convert.ps1` のPhase 2-6(noue一気通貫ビルド、
convert_noue.py呼び出し1本)は Progress 55 "Generating MOD files" から
Progress 96 まで、温状態で全体の53〜74%を占める区間、バー・ラベルが一切
動かない見かけ上の停滞だった(分析: work\\speed_mission\\ux\\PROPOSAL.md)。
convert_noue.py/build_pak_from_avatar.pyが既に出している工程境界print
(`[TAG] === NoueSubphase: <name> start/done ===` 等、dev#220計装)を
convert.ps1側で検出し、55〜96の範囲へリスケールした``##PROGRESS##``として
中継する($script:NoueSubphaseMarkers / Relay-NoueSubphaseProgress、
convert.ps1)。

このテストは実装を再実装せず、convert.ps1の実ソースからマーカーテーブルと
中継関数の本体をそのまま抽出して実行する(test_phase1_gender_parallel.py の
_extract_worker_body と同じ手口: 「テストが検証しているのはテスト自身の
コピー」という事故を避ける)。

検証内容:
  1. リスケール表がすべて55<pct<96の範囲に収まり、宣言順に単調増加していること
     (静的ガード)。
  2. 実行時試験: マーカー行の並びを流し込み、絵に描いた餅ではなく実際に
     ``##PROGRESS##`` 行が単調非減少で出ること。
  3. 負の対照: 順序が乱れた入力(後退)・重複行・無関係な行を混ぜても、
     出力されるpctが後退しない/余計な行が出ないこと。
  4. GUI側正規表現(app\\DiveToPalworld.cs の ProgressMark、
     ``##PROGRESS## (\\d+) (.*)``)が新マーカーの出力形式を拾えること。

変換出力(pak本体)には一切触れない(convert_noue.py/Blenderは起動しない、
文字列レベルの単体試験)。
Layers-Affected: none(このテスト自体はロジック検証のみ)。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
CONVERT_PS1 = os.path.join(REPO_ROOT, "pipeline", "cli", "convert.ps1")
APP_CS = os.path.join(REPO_ROOT, "app", "DiveToPalworld.cs")

PWSH = shutil.which("pwsh") or "pwsh"

# app\DiveToPalworld.cs の ProgressMark と一字一句同じ正規表現(C#の\\dはPythonの
# \dと同じ)。ここは値のコピーであり、下のtest_progress_mark_regex_matches_cs_source
# がconvert.ps1側の実ソースと文字列一致することを確認するので、二重管理にはならない。
PROGRESS_MARK_PATTERN = r"##PROGRESS## (\d+) (.*)"


def _pwsh_available():
    try:
        r = subprocess.run([PWSH, "-NoProfile", "-Command", "1"],
                            capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_balanced(src, anchor, open_ch, close_ch):
    """anchor直後の最初のopen_chから対応するclose_chまでを、ブレース(または
    括弧)カウントで取り出す(コメント中の}を誤って終端と数える心配はない
    ——convert.ps1のこの区間にコメント中の閉じ括弧は無いことをコード側で確認済み)。
    戻り値はanchorからclose_ch(含む)までの文字列全体。"""
    start = src.index(anchor)
    open_idx = src.index(open_ch, start)
    depth = 1
    i = open_idx + 1
    while depth > 0:
        c = src[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
        i += 1
    return src[start:i]


def _extract_progress_relay_source(src):
    """convert.ps1から Progress()関数 / $script:NoueSubphaseMarkers テーブル /
    Relay-NoueSubphaseProgress関数 の3つを実ソースのまま抽出して連結する。"""
    progress_fn = [ln for ln in src.splitlines()
                   if ln.strip().startswith("function Progress(")]
    assert progress_fn, "convert.ps1にfunction Progress(...)が見当たらない"
    marker_table = _extract_balanced(
        src, "$script:NoueSubphaseMarkers = @(", "(", ")")
    relay_fn = _extract_balanced(
        src, "function Relay-NoueSubphaseProgress($line) {", "{", "}")
    return "\n".join([progress_fn[0], marker_table, relay_fn])


def _read_marker_table_literal(src):
    return _extract_balanced(src, "$script:NoueSubphaseMarkers = @(", "(", ")")


HARNESS_TEMPLATE = textwrap.dedent(r"""
    {relay_src}

    $script:LastNoueProgressPct = 0
    $linesPath = $args[0]
    $lines = Get-Content -Path $linesPath -Encoding UTF8
    foreach ($l in $lines) {{
        Relay-NoueSubphaseProgress $l
    }}
    """)


def _run_relay(src, lines, tmp_path):
    """convert.ps1から抽出したRelay-NoueSubphaseProgressへlinesを1行ずつ通し、
    実際に発行された##PROGRESS##行のリスト([(pct:int, label:str), ...])を返す。"""
    relay_src = _extract_progress_relay_source(src)
    harness = HARNESS_TEMPLATE.format(relay_src=relay_src)
    harness_path = os.path.join(tmp_path, "harness.ps1")
    lines_path = os.path.join(tmp_path, "lines.txt")
    with open(harness_path, "w", encoding="utf-8") as f:
        f.write(harness)
    with open(lines_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    r = subprocess.run(
        [PWSH, "-NoProfile", "-File", harness_path, lines_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert r.returncode == 0, f"harness.ps1がエラー終了した: rc={r.returncode}\n{r.stderr}"
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"^##PROGRESS## (\d+) (.*)$", line)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


# =====================================================================
# 静的ガード: マーカーテーブル自体の妥当性(実行不要、pwsh不要)
# =====================================================================

def test_marker_table_entries_are_strictly_between_55_and_96():
    """55%(Progress 55、ブロック開始)と96%(Progress 96、ブロック終了)の
    「間」を埋める中間マーカーである以上、両端の値そのものを使ってはいけない
    (両端は既存のProgress呼び出しの意味を持つため、重複させると
    Relay側のガード判定が曖昧になる)。"""
    src = _read(CONVERT_PS1)
    table_src = _read_marker_table_literal(src)
    pcts = [int(m) for m in re.findall(r"Pct\s*=\s*(\d+)", table_src)]
    assert pcts, "マーカーテーブルからPct値を抽出できなかった"
    for pct in pcts:
        assert 55 < pct < 96, f"マーカーのPctが55-96の範囲外: {pct}"


def test_marker_table_is_declared_in_monotonic_increasing_order():
    """宣言順=実際に発生する工程順のはず(convert_noue.py/build_pak_from_avatar.py
    の実行順と一致させる設計)。宣言順で値が増加していないと、後発の行が先発の
    行より小さいpctを持つことになり、単調非減少ガード自体が事実上死んだ
    コードになってしまう。"""
    src = _read(CONVERT_PS1)
    table_src = _read_marker_table_literal(src)
    pcts = [int(m) for m in re.findall(r"Pct\s*=\s*(\d+)", table_src)]
    assert pcts == sorted(pcts), (
        f"マーカーテーブルの宣言順がPctの昇順になっていない: {pcts}")
    assert len(pcts) == len(set(pcts)), (
        f"マーカーテーブルにPctの重複がある(単調性チェックが素通りしてしまう): {pcts}")


def test_relay_function_resets_nothing_by_itself_and_uses_script_scope():
    """Relay-NoueSubphaseProgressはconvert.ps1側で毎回ビルド開始前に
    $script:LastNoueProgressPct=0へリセットされる前提の関数(=関数内で
    リセットしない)。関数内リセットが紛れ込むと2検体目のビルドで前回値を
    参照できず、常に55%からしか判定できなくなる回帰を防ぐ。"""
    src = _read(CONVERT_PS1)
    relay_fn = _extract_balanced(
        src, "function Relay-NoueSubphaseProgress($line) {", "{", "}")
    assert "$script:LastNoueProgressPct = 0" not in relay_fn, (
        "Relay-NoueSubphaseProgress関数内で$script:LastNoueProgressPctを"
        "リセットしている(呼び出し側でビルドごとにリセットする設計のはず)")


def test_convert_ps1_progress_96_label_no_longer_implies_check_is_upcoming():
    """提案3(dev#288): 96%到達時点でpreflightは実際には既にconvert_noue.py内部で
    完了済みなのに、旧文言「Final check (preflight already run inside
    convert_noue.py)」は「これから最終チェックをする」という誤解を招いていた
    (PROPOSAL.md 2.4節)。旧文言が消え、新文言(事後処理であることが伝わる表現)に
    置き換わっていることを回帰ガードする。"""
    src = _read(CONVERT_PS1)
    assert 'Progress 96 "Final check (preflight already run inside convert_noue.py)"' not in src, (
        "旧来の誤解を招く96%ラベルがまだ残っている(提案3が未適用)")
    m = re.search(r'Progress 96 "([^"]*)"', src)
    assert m, "Progress 96 の呼び出しが見当たらない"
    new_label = m.group(1)
    assert new_label, "Progress 96 のラベルが空になっている"
    # 「これからチェックする」ではなく「終わった直後」であることが伝わる表現に
    # なっていること(過去形/完了含意の語のいずれかを含む、緩い回帰ガード)
    assert re.search(r"complete|done|verifying|finished", new_label, re.IGNORECASE), (
        f"新しい96%ラベルが完了含意の表現になっていない: {new_label!r}")


def test_convert_ps1_resets_last_progress_pct_before_each_noue_run():
    """呼び出し側(convert_noue.py起動直前)で$script:LastNoueProgressPctを
    0へ戻していること(前回ビルドの値を持ち越さない)。"""
    src = _read(CONVERT_PS1)
    call_idx = src.index('& $BPython (Join-Path $Pipeline "py\\convert_noue.py") $Job')
    preceding = src[max(0, call_idx - 400):call_idx]
    assert "$script:LastNoueProgressPct = 0" in preceding, (
        "convert_noue.py呼び出し直前で$script:LastNoueProgressPctがリセットされていない")


def test_convert_ps1_still_pipes_all_lines_through_for_logging():
    """マーカー検出のために追加したForEach-Objectが、既存の全行ログ可視性
    (Tee-Objectでの保存 + GUI/コンソールへの全文表示)を壊していないこと
    ——側作用(Relay呼び出し)の後、必ず元の行をパイプラインへ流していること。"""
    src = _read(CONVERT_PS1)
    call_idx = src.index('& $BPython (Join-Path $Pipeline "py\\convert_noue.py") $Job')
    following = src[call_idx:call_idx + 700]
    assert "Tee-Object $noueLog" in following, (
        "convert_noue.py呼び出し後にTee-Object $noueLogが見当たらない"
        "(保存ログの生成経路が失われていないか確認)")
    # ForEach-Objectブロックの最後の文が$line(素通し)であること
    foreach_block = _extract_balanced(following, "ForEach-Object {", "{", "}")
    body_lines = [ln.strip() for ln in foreach_block.splitlines() if ln.strip()]
    assert body_lines[-2] == "$line", (
        f"ForEach-Objectブロックの末尾が$lineの素通しになっていない: {body_lines}")


# =====================================================================
# 実行時試験(pwsh実行、convert.ps1の実ソースをそのまま使う)
# =====================================================================

@pytest.mark.skipif(not _pwsh_available(), reason="pwshが利用できない環境")
class TestRelayNoueSubphaseProgressRealExecution:

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="d2p_noue_progress_relay_test_")
        self.src = _read(CONVERT_PS1)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    TAG = "convert_noue"

    def test_full_forward_sequence_emits_monotonic_progress(self):
        """正の対照: 実際のconvert_noue.py/build_pak_from_avatar.pyが出す順序
        どおりにマーカー行を流すと、期待したpct列がそのまま単調増加で出ること。"""
        lines = [
            f"[{self.TAG}] === NoueSubphase: template_prep start ===",
            f"[{self.TAG}] Template assets: live (...)",
            f"[{self.TAG}] === NoueSubphase: template_prep done ===",
            f"[{self.TAG}] === NoueSubphase: atlas_bake start ===",
            f"[{self.TAG}] === NoueSubphase: atlas_bake done ===",
            f"[{self.TAG}] === NoueSubphase: material_override start ===",
            f"[{self.TAG}] === NoueSubphase: material_override done ===",
            f"[{self.TAG}] === Phase1Subphase: avatar_dump start ===",
            f"[{self.TAG}] === Phase1Subphase: avatar_dump done ===",
            f"[{self.TAG}] === Phase 2: injecting real avatar into outfit SKs ===",
            f"[{self.TAG}] === Phase2Subphase: sk_injection done ===",
            f"[{self.TAG}] === Phase2Subphase: overrides start ===",
            f"[{self.TAG}] === Phase2Subphase: overrides done ===",
            f"[{self.TAG}] === Phase 3: building pak (mount=/Game) ===",
            f"[{self.TAG}] pak generated: foo.pak (total entries 500)",
            f"[{self.TAG}] === Phase 4: preflight_pak.py ===",
        ]
        emitted = _run_relay(self.src, lines, self.tmp_dir)
        pcts = [p for p, _ in emitted]
        assert pcts, "1件も##PROGRESS##が出なかった"
        assert pcts == sorted(pcts), f"単調非減少になっていない: {pcts}"
        assert all(55 < p < 96 for p in pcts), f"55-96の範囲外の値が出た: {pcts}"
        # 期待した8件がすべて意図した順序どおりに出ること
        assert pcts == [58, 61, 63, 65, 66, 78, 90, 94], (
            f"想定した工程順のpct列と一致しない: {pcts}")

    def test_negative_control_out_of_order_line_does_not_regress(self):
        """負の対照(本題): ログの乱れ・想定外の順序(例えば重複起動や再試行で
        古いマーカーがもう一度紛れ込む)があっても、出力されるpctが一度到達した
        値より下がらないこと(単調非減少の実体テスト)。"""
        lines = [
            f"[{self.TAG}] === Phase2Subphase: overrides start ===",  # 78
            f"[{self.TAG}] === NoueSubphase: template_prep done ===",  # 58 (逆行、無視されるべき)
            f"[{self.TAG}] === Phase 3: building pak (mount=/Game) ===",  # 90
        ]
        emitted = _run_relay(self.src, lines, self.tmp_dir)
        pcts = [p for p, _ in emitted]
        assert pcts == [78, 90], (
            f"逆行マーカー(template_prep done, 58%)が無視されず出力に混入した: {pcts}")

    def test_negative_control_duplicate_line_does_not_re_emit(self):
        """同じ工程境界行が2回出ても(ログの重複行・再送信等)、2回目は
        pctが変わらないため再発行されない(冪等性)。"""
        line = f"[{self.TAG}] === NoueSubphase: atlas_bake done ==="
        emitted = _run_relay(self.src, [line, line, line], self.tmp_dir)
        assert len(emitted) == 1, f"同一行の再入力で複数回発行された: {emitted}"

    def test_negative_control_unrelated_lines_emit_nothing(self):
        """マーカーと無関係な通常ログ行(衣装SK注入の進捗行58件分を模擬)は
        一切##PROGRESS##を発行しないこと(誤検出の回帰ガード)。"""
        lines = [
            f"[{self.TAG}] [OK] Player/Outfit/SK_Foo.uexp gender=Male numv=1200 tri=800",
            f"[{self.TAG}] [OK] Player/Outfit/SK_Bar.uexp gender=Female numv=900 tri=600",
            "",
            "some random stderr noise",
        ]
        emitted = _run_relay(self.src, lines, self.tmp_dir)
        assert emitted == [], f"無関係な行から##PROGRESS##が誤って発行された: {emitted}"

    def test_error_record_style_line_is_still_detected(self):
        """convert.ps1呼び出し元は2>&1でstderrも合流させる。ErrorRecordの
        .Exception.Messageへ還元した後の生テキストがRelayへ渡る前提なので、
        ここでは還元後の文字列(=通常の文字列)を流し込んでも検出できることを
        確認する(還元処理自体はconvert.ps1のパイプ構成側の責務、
        test_convert_ps1_still_pipes_all_lines_through_for_loggingが別途保証)。"""
        lines = [f"[{self.TAG}] === Phase 4: preflight_pak.py ==="]
        emitted = _run_relay(self.src, lines, self.tmp_dir)
        assert emitted == [(94, "Running preflight checks")]


# =====================================================================
# GUI側正規表現との整合(app\DiveToPalworld.cs の ProgressMark)
# =====================================================================

def test_progress_mark_regex_matches_cs_source():
    """テスト側でハードコードしたPROGRESS_MARK_PATTERNが、実際に
    app\\DiveToPalworld.cs で使われている正規表現と文字列一致していること
    (テストが検証しているのがC#側の実物ではなく古いコピーになる事故を防ぐ)。"""
    cs_src = _read(APP_CS)
    m = re.search(r'new Regex\("([^"]*##PROGRESS##[^"]*)"\)', cs_src)
    assert m, "app\\DiveToPalworld.csにProgressMarkの正規表現定義が見当たらない"
    cs_pattern_literal = m.group(1)
    # C#の文字列リテラル中の \\d は実際の正規表現では \d(1つのバックスラッシュ)。
    # C#ソースの生テキストは `\\d` の2文字なので、Pythonのraw文字列比較でも
    # 同じ2文字("\\\\d")になる。
    assert cs_pattern_literal == r"##PROGRESS## (\\d+) (.*)", (
        f"app\\DiveToPalworld.csのProgressMark正規表現が想定と異なる: {cs_pattern_literal!r}"
        "(このテストの追随漏れの可能性、正規表現を変更した場合はこのテストも更新すること)")


def test_new_marker_labels_are_matched_by_progress_mark_regex():
    """convert.ps1側のマーカーテーブルが出す各ラベルについて、
    ``Progress $pct $label`` が実際に生成する ``##PROGRESS## <pct> <label>``
    行が、GUI側正規表現(PROGRESS_MARK_PATTERN)で pct/label を正しく
    分離抽出できること。改行・タブなど正規表現の(.*)が壊れる文字を
    含んでいないことも合わせて確認する。"""
    src = _read(CONVERT_PS1)
    table_src = _read_marker_table_literal(src)
    entries = re.findall(
        r"Pct\s*=\s*(\d+);\s*Label\s*=\s*'([^']*)'", table_src)
    assert len(entries) >= 8, f"マーカーテーブルの抽出件数が想定より少ない: {entries}"
    for pct_str, label in entries:
        assert "\n" not in label and "\t" not in label, (
            f"ラベルに改行/タブが含まれている(GUI側の1行パースが壊れる): {label!r}")
        rendered = f"##PROGRESS## {pct_str} {label}"
        m = re.match(PROGRESS_MARK_PATTERN, rendered)
        assert m, f"GUI側正規表現がこの行を拾えない: {rendered!r}"
        assert m.group(1) == pct_str
        assert m.group(2).strip() == label


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
