# -*- coding: utf-8 -*-
"""rd_120(2026-07-29 机上調査 work\\rd_120\\PROPOSAL.md): 変換パイプライン
並列化の共有ヘルパー(pak不変設計)。

対象3点(build_pak_from_avatar.py / convert_noue.py)がそれぞれ独自に
ThreadPoolExecutor/ProcessPoolExecutorを組み立てると、"入力順を保つ"
"片方失敗でももう片方の完了を待つ" という2つの不変条件をあちこちに
重複実装することになる。ここへ1本化し、pytest(tests\\parallel\\)で
その2つの不変条件だけを実プロセス/実Blenderなしに検証する。

なぜpak不変と言えるか(rd_120 PROPOSAL 3節の実装への落とし込み):
  - run_pool_ordered()はexecutor.map()を使う。map()は「完了した順」ではなく
    「入力に渡した順」で結果を返すことがconcurrent.futures仕様として保証されて
    いるため、並列度・実行順が変わっても呼び出し元が受け取る結果列は
    逐次実行時と同じ順序になる(=ログ順・集計順を変えない)。
  - run_pair_parallel()はThreadPoolExecutor(max_workers=len(items))で全item
    (通常2件、female/male)を即座にsubmitしてから、submit順に.result()を
    呼ぶ。片方が例外(die()のSystemExitを含む——concurrent.futures.thread.
    _WorkItem.run()はBaseExceptionを捕捉してfutureへ格納するため、SystemExitも
    通常の例外と同様にfuture.result()で再送出される)を投げても、
    `with ThreadPoolExecutor() as ex:` のcontext managerがshutdown(wait=True)を
    __exit__で呼ぶため、例外が呼び出し元へ伝播しきる前に**もう片方の処理も
    最後まで走り切る**(=両方の診断ログ・副作用ファイルが残る。
    rd_120 PROPOSAL 8節論点2で許容範囲と評価済みの trade-off)。
"""
import concurrent.futures
import os


def run_pair_parallel(fn, items):
    """items(通常2要素)の各要素を独立にfn(item)へ渡し、ThreadPoolExecutorで
    並列実行して**入力順**の結果リストを返す。

    fnがsubprocess.run()などブロッキングI/O待ちの処理を含む場合に向く
    (GILは関係ない。プロセスを増やす必要はない)。

    片方が例外を投げても、context managerのshutdown(wait=True)がもう片方の
    完了を待ってから例外を伝播する(モジュールdocstring参照)。"""
    items = list(items)
    if not items:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(items)) as ex:
        futures = [ex.submit(fn, item) for item in items]
        return [fut.result() for fut in futures]


def run_pool_ordered(worker_fn, tasks, n_workers, initializer=None, initargs=(),
                      executor_factory=concurrent.futures.ProcessPoolExecutor):
    """tasksをworker_fnへ並列分配し、**入力順を保った**結果リストを返す。

    executor_factoryは既定でProcessPoolExecutor(CPUバウンドなPython処理向け、
    rd_120 5.1のPhase2 SK注入ループを想定)。テスト時はThreadPoolExecutor等を
    注入することで、実プロセス起動コストを払わずに「入力順=出力順」
    「1件の失敗が他タスクの実行・収集を止めない」という不変条件だけを検証できる
    (worker_fn自体は例外を投げず(ok=False, ...)形の結果を返す設計を前提とする
    ——build_pak_from_avatar._injection_worker参照)。"""
    with executor_factory(max_workers=n_workers, initializer=initializer,
                           initargs=initargs) as ex:
        return list(ex.map(worker_fn, tasks))


def default_worker_count(env_var, floor=2):
    """既定ワーカー数 = max(1, cpu_count - floor)。env_var環境変数が正の整数で
    設定されていればそれを最優先する(rd_120 PROPOSAL 8節論点1: WSB等の低スペック
    機やユーザー環境向けの手動上書き口。GUI設定には出さず環境変数のみ
    ——「設定項目は少ないほうがいい」方針、feedback-fewer-user-settings.md)。"""
    override = os.environ.get(env_var)
    if override:
        try:
            n = int(override)
            if n >= 1:
                return n
        except ValueError:
            pass
    cpu = os.cpu_count() or 4
    return max(1, cpu - floor)
