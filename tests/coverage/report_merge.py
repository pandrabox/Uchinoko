# -*- coding: utf-8 -*-
r"""dev#127(夜間カバレッジの並列化): pytest-xdist 環境でのレポート集約。

背景: `pytest-xdist` を導入すると、テストは「コントローラ(-n を渡した
呼び出し元プロセス)」ではなく「ワーカー(gw0, gw1, ... の別プロセス)」が
実行する。従来の conftest.py は `config._u53_gate_rows`(プロセスローカルな
Python リスト)へ判定行を溜め、セッション終了時にそれを report.md/
coverage.md へ書き出していたが、この方式は **プロセスをまたいだ集約ができない**
(コントローラ自身はテストを1件も実行しないので `config._u53_gate_rows` は
常に空、ワーカーは自分が実行した分しか持たない)。

そこで本モジュールは「判定行はプロセスごとに別ファイルへ書く → セッション
終了時にコントローラが全ファイルを1本へ集約する」という、relgate.py の
BufferedReport(WP15)と同じ思想(並列実行中は共有ファイルへ直接書き込まず、
完了後にまとめて正規化する)をファイルベースで実現したもの。

ワーカーが同一ファイルへ同時追記する危険(Windows でのマルチプロセス
追記はPOSIXのO_APPENDほど強い原子性保証が無い)を構造的に避けるため、
**ワーカーごとに別名ファイルへ書く**(`gates.gw0.jsonl` 等)。コントローラは
非xdist実行時と全く同じ役回り(唯一のプロセス)なので、ワーカー識別子を
持たず、常に正規名(`gates.jsonl` 等)へ直接書く——つまり「並列でなければ
今までと1バイトも変わらない」。
"""
import glob
import json
import os

# conftest.py と共有する既定のファイル名(3種)。
GATES_BASENAME = "gates.jsonl"
TESTS_BASENAME = "tests.jsonl"
PROGRESS_BASENAME = "progress.log"


def worker_suffixed_name(basename, worker_id):
    r"""`gates.jsonl` -> `gates.gw0.jsonl`(worker_id が None ならそのまま)。

    非xdist実行(worker_id=None)では常に正規名を返す=既存の書式を変えない。
    """
    if not worker_id:
        return basename
    stem, ext = os.path.splitext(basename)
    return "{}.{}{}".format(stem, worker_id, ext)


def validate_run_dir_for_xdist(numprocesses, run_dir_option):
    r"""pytest-xdist(-n)使用時は `--run-dir` の明示指定を必須にする。

    理由: `--run-dir` を省略すると、conftest.py の既定挙動
    (`work\u53_cov\reports\<time.strftime時点のタイムスタンプ>\`)が
    **コントローラとワーカーそれぞれで別々に**評価される
    (各プロセスが個別に `time.strftime` を呼ぶため、1秒でもずれれば
    別ディレクトリを指す)。その場合ワーカーはそれぞれ孤立したディレクトリへ
    判定行を書き、コントローラは別のディレクトリを見て「0件」の
    report.md を書いてしまう——**静かに空の結果が『正常終了』する**という
    最悪の壊れ方(CLAUDE.md「作業フォルダの指定を省くと競合が復活する」の
    xdist版)。したがって未指定は握りつぶさずここで即座に落とす。

    `numprocesses` は `config.option.numprocesses`(-n の値。0/None なら
    xdist 不使用)、`run_dir_option` は `config.getoption("run_dir")`。
    戻り値は無く、条件を満たさなければ ValueError を投げる
    (呼び出し側の conftest.py で pytest.UsageError に包む)。
    """
    if numprocesses and not run_dir_option:
        raise ValueError(
            "pytest-xdist (-n {}) 使用時は --run-dir を明示指定すること"
            "(省略すると各ワーカーが別のタイムスタンプで reports\\<ts>\\ を"
            "作ってしまい、gates.jsonl 等の集約が壊れる)".format(numprocesses))


def merge_worker_files(run_dir):
    r"""`<run_dir>\{gates,tests}.<workerid>.jsonl` と `progress.<workerid>.log`
    を正規名へ集約する(コントローラの sessionfinish からのみ呼ぶこと)。

    非xdist実行(ワーカーファイルが1つも無い)では何もしない
    ——正規名ファイルは各プロセス自身が直接書いているのでそのままでよい。

    集約は「連結」だけ(ワーカーIDの昇順)。gates.jsonl/tests.jsonl は
    1行1JSONなので行の意味は変わらない。progress.log は人間が読む進行ログ
    なので、ワーカーごとの区切りが分かるよう見出しを挟む。

    戻り値: 集約したワーカー数(0なら非並列実行、何もしていない)。
    """
    n_merged = 0
    for basename in (GATES_BASENAME, TESTS_BASENAME):
        pattern = os.path.join(run_dir, worker_suffixed_name(basename, "*"))
        worker_paths = sorted(
            p for p in glob.glob(pattern)
            if p != os.path.join(run_dir, basename))
        if not worker_paths:
            continue
        n_merged = max(n_merged, len(worker_paths))
        canonical = os.path.join(run_dir, basename)
        with open(canonical, "a", encoding="utf-8") as out:
            for p in worker_paths:
                with open(p, encoding="utf-8") as f:
                    out.write(f.read())

    progress_pattern = os.path.join(run_dir, worker_suffixed_name(PROGRESS_BASENAME, "*"))
    progress_paths = sorted(
        p for p in glob.glob(progress_pattern)
        if p != os.path.join(run_dir, PROGRESS_BASENAME))
    if progress_paths:
        canonical = os.path.join(run_dir, PROGRESS_BASENAME)
        with open(canonical, "a", encoding="utf-8") as out:
            for p in progress_paths:
                worker_id = os.path.basename(p).split(".")[1]
                out.write("\n=== worker {} ===\n".format(worker_id))
                with open(p, encoding="utf-8") as f:
                    out.write(f.read())
    return n_merged


def read_gate_rows(run_dir):
    r"""`<run_dir>\gates.jsonl`(正規名。merge_worker_files 済みなら全ワーカー分
    を含む)を読み直し、`_Recorder.record` が書いたのと同じ形の dict のリストへ
    復元する。

    プロセス境界を越えた唯一の集約経路として、xdist の有無に関わらず
    **常にこの関数でrowsを組み立てる**(config._u53_gate_rows という
    プロセスローカルな経路は廃止。「非並列なら今までと同じ、並列でも
    同じコードパス」という一本化がxdist対応の事故を防ぐ——分岐を増やすほど
    踏まれないパスが生まれる、というのがこのプロジェクトの経験則)。
    壊れた行(途中で書き込みが切れた等)は黙ってスキップする
    (無人運転なので1行の破損でレポート生成全体を落とさない)。
    """
    rows = []
    path = os.path.join(run_dir, GATES_BASENAME)
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
