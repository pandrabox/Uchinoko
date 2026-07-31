# -*- coding: utf-8 -*-
"""実際にビルドされた配布zip(build\\make_dist.ps1 の出力そのもの)に同梱される
文書ファイルへ、プロジェクトの絶対禁止事項(CLAUDE.md)を機械的に検査する。

背景(SignPath WP33、2026-07-31): これまでの禁止語・事実整合性の検査
(tests\\oss_docs\\ 配下)は、すべて「gitリポジトリ内のソースファイル」だけを
直接開いて読んでいた。**配布zipの中身そのもの**を検査した試験は一つも
無かった。実測で次の2件が見つかった:

  1. 公開中の `Uchinoko_for_Palworld_v2.2.12_full.zip` の
     `Uchinoko_for_Palworld\\README.md` に、Windows Defenderの「保護の履歴」から
     検出を復元し、展開先フォルダを「除外」に登録させる操作手順が番号付きで
     残っていた(ソース側のREADME.mdでは既に除去済みだったにもかかわらず、
     同期タイミングのズレで旧配布物には残っていた)。
  2. `manual\\manual.md` / `manual\\manual.en.md` に「最新版は検出されていません」
     という、SECURITY.md/README.mdの「現在も検出されます」という実測結果と
     矛盾する誤った断定が残っていた(本WPで是正、is_manual_defender_claim_fixed
     系のテストは tests\\oss_docs\\ 側に別途存在するがmanual.md/en.mdは
     対象外だった)。

いずれも「git上のソース」だけを見ていれば直る保証がない。配布zipは
ビルドタイミングでソースの複製を作る工程(build\\make_dist.ps1)を経ており、
ソース側を直しても、①同期が遅れる、②zip生成の途中で複製されるファイル
(manual\\manual.html は manual\\manual.md とは独立した手打ちの複製であり、
自動生成されない)、のいずれかで「配布物にだけ古い内容が残る」事故が起き得る。
この試験はその死角そのものを塞ぐ。

設計方針:
  1. 検査対象は「同梱される全ての文書ファイル」から**動的に列挙する**
     (拡張子ベース: .md/.txt/.html/.htm/.rst に加え、LICENSE等の拡張子無し
     ライセンス表記ファイルも対象に含める)。ファイル名のハードコード列挙は
     しない――次に文書が増えても自動的に走査対象へ入るようにするため
     (BRIEFING指示: 「ファイル名のハードコード列挙は次に文書が増えたとき
     同じ穴を作る」)。
  2. コード資産(.py/.cs/.ps1等)は対象外。CLAUDE.mdは「開発メモ・コード・
     CLIオプションとしてのFBXは引き続き触ってよい」と明記しており、禁止対象は
     文書ファイルに限る。文書拡張子だけを対象にすることで自動的にこの区別が付く。
  3. `manual\\manual.html` は画像をbase64埋め込みした2MB超のHTMLで、統計的偶然で
     短い禁止語トークン(実測: "FBX"が78回、すべてbase64ノイズ内)が
     頻出する。判定前に80文字以上のbase64/圧縮データ様の連続英数字列を
     プレースホルダへ機械的に置換してから照合する(誤検知で検査全体の信頼を
     失わないため)。空白や非ASCII文字を含む多語フレーズ(Defender案内文言・
     虚偽断定文など)はbase64アルファベットには本質的に出現し得ないため、
     この前処理をしなくても元々誤検知しない。
  4. 2段構成(test_signpath_dist_layout.py・test_u28_zip_audit.pyと同じ型):
     a. 純関数 `find_doc_violations()` の単体表(合成テキストによる正/負の対照)。
     b. 実際に `build\\make_dist.ps1` を実行して配布zipを作り、その実物へ
        適用する統合テスト。ビルド前提(pwsh/csc.exe/ooz.pyd/python3.dll)が
        無い環境ではskipする(test_signpath_dist_layout.pyと同じ前提)。

実行: python -m pytest tests\\shipcheck\\test_dist_shipped_docs_content.py -q
"""
import os
import re
import subprocess
import sys
import tempfile
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
MAKE_DIST_PS1 = os.path.join(REPO_ROOT, "build", "make_dist.ps1")
MAIN_SRC = os.path.join(REPO_ROOT, "app", "DiveToPalworld.cs")

_DEVTOOLS = os.path.join(REPO_ROOT, "devtools")
if _DEVTOOLS not in sys.path:
    sys.path.insert(0, _DEVTOOLS)

# ---------------------------------------------------------------------------
# 禁止語・禁止フレーズの定義
# ---------------------------------------------------------------------------

# オーナーの仕事用ハンドル。このテストファイル自身はtests\shipcheck配下にあり
# WHITELIST_DIR_SUBPATH_EXCLUDESの対象外、つまり意図的にPub側へも同期される
# (配布物の監査テストが公開されている方が審査官の心証にも資する)。
# 2026-07-31 WP32で tests\oss_docs\test_forbidden_terms.py が是正された理由と
# 同じく、base64化は「自プロジェクトの機微スキャンを迂回する難読化」に見えるため
# 使わない。値の正本は devtools\sensitive_denylist.py の owner_real_handle だが、
# devtools\ 自体はPubへ同期されない(オーナー裁定、実値を含むため意図的に非公開)。
# そのためPub側ではこのimportが失敗する。fail-closedにImportErrorを伝播させると
# Pub側でこのファイル全体のcollectionが壊れてしまうため、失敗時は
# _OWNER_HANDLE=Noneとして該当チェックのみ無効化する(他の禁止語チェックは
# Pub側でも引き続き有効)。Dev側では常にimportに成功し、フル機能で動作する。
try:
    import sensitive_denylist as _denylist  # noqa: E402

    _OWNER_HANDLE = next(
        e["value"] for e in _denylist.SENSITIVE_IDENTITY if e["label"] == "owner_real_handle"
    )
    # ライセンス上名指し禁止のサードパーティ製品名。同じ理由(devtools\はPubへ
    # 同期されない)で、この固有名詞の文字列そのものをこのファイルには書かない。
    # 正本は devtools\sensitive_denylist.py の SCOPE_FORBIDDEN_TERMS。
    _SCOPE_FORBIDDEN_THIRDPARTY_NAME = next(
        e["value"] for e in _denylist.SCOPE_FORBIDDEN_TERMS
        if e["label"] == "thirdparty_asset_name_no_mention"
    )
except ImportError:
    _OWNER_HANDLE = None
    _SCOPE_FORBIDDEN_THIRDPARTY_NAME = None

# ① Windows Defenderの検出回避「操作手順」(メニュー名を伴う具体的な手順)。
#    tests\oss_docs\test_defender_no_operational_steps.py と同じ判定基準。
DEFENDER_BYPASS_PHRASES = [
    "保護の履歴",
    "除外の追加または削除",
    "Protection history",
    "Add or remove exclusions",
]

# ② 「もう検出されない/安全」という虚偽の断定(2026-07-31時点の実測では
#    現在も検出される)。tests\oss_docs\test_security_md_av_disclosure_accuracy.py
#    と同じ判定基準に、実際に見つかったmanual.md/en.mdの旧文言を追加。
FALSE_SAFETY_CLAIM_PHRASES = [
    "本体は一度も検出されていません",
    "実処理を行う本体は一度も検出されていません",
    "has never been flagged in any version, on any channel",
    "作者の手元の確認では、最新版は検出されていません",
    "the latest release has not been flagged",
    "最新版は検出されていません",
    "もう検出されません",
    "もう検出されない",
    "no longer detected",
    "no longer flagged",
    "安全です",
    "is now safe",
]

# ③ SignPathへ「既に申請済み・審査中」であるかのような虚偽の断定
#    (2026-07-31時点、申請自体はまだ行われていない)。
FALSE_APPLICATION_STATUS_PHRASES = [
    "コード署名の適用を申請中です",
    "によるコード署名を申請中",
    "無償のコード署名を申請中",
    "審査中です",
    "審査待ちであり、まだ署名は取得できていません",
    "currently under review",
    "application in progress",
    "申請予定/申請中",
    "intends to apply / has applied for",
    "has applied for a free code-signing certificate",
]

# ④ プロジェクトのスコープ外・ライセンス上の禁止トピック。
#    「マルチプレイ/multiplayer」は README.md の「非対応範囲(将来にわたって
#    対応しません)」節に正当な理由で出現するため、ここには含めない
#    (tests\oss_docs\test_forbidden_terms.py も同じ理由でREADMEを除外している)。
#    ライセンス上名指し禁止のサードパーティ製品名(_SCOPE_FORBIDDEN_THIRDPARTY_NAME)は
#    このファイル自身がPubへ同期されるため文字列をここに直接書けない。devtools\
#    経由のimportが成功するDev側でのみ検査対象へ加わり、Pub側(import失敗時)は
#    このエントリだけ無効化される(_OWNER_HANDLEと同じ避難パターン)。
OUT_OF_SCOPE_TOPIC_PHRASES = [
    p for p in [_SCOPE_FORBIDDEN_THIRDPARTY_NAME, "VRChat SDK", "VRCSDK"]
    if p is not None
]

# ⑤ 内部専用の痕跡(開発機パス・非公開ディレクトリ)。
INTERNAL_TRACE_PHRASES = [
    ".devonly",
    r"C:\P\Work",
    r"C:\UnityP",
]

# ⑥ 開発機のWindowsアカウント名・マシン名(短いトークンなので単語境界必須、
#    devtools\sensitive_denylist.pyのDEV_TRACE_ENVと同じ方針)。
INTERNAL_TRACE_WORD_TOKENS = [
    "raichu",
    "PB2306",
]

# ⑦ FBXを「対応形式」として書かない(公式サポートはVRM 0.0/VRM 1.0/prefabの3つ)。
#    文書拡張子だけを対象にしている時点でコード(CLIオプション等)は既に対象外
#    なので、ここでは単純に「文書内にFBXという語が出現するか」を見る
#    (現時点でREADME/manual/LICENSE等にFBXが出現する正当な理由は無い)。
FBX_TOKEN = "FBX"

DOC_EXTENSIONS = {".md", ".txt", ".html", ".htm", ".rst"}

# 拡張子の無いライセンス表記ファイル(LICENSE / third_party\pyooz-0.0.8-source\LICENSE等)
# も「同梱ライセンス表記」として検査対象に含める(BRIEFING指示の例示そのもの)。
# 拡張子ベースの動的列挙だけだと "LICENSE" という慣習的なファイル名を取りこぼす
# ため、拡張子が空文字のエントリも対象に加える。実測(2026-07-31)では該当7件は
# いずれも小さなテキスト(LICENSE本体・pyoozのdist-info metadata)であり、
# 巨大バイナリの誤検査混入を避けるため下記 _MAX_DOC_SIZE_BYTES の上限も併用する。
DOC_EXTENSIONS_INCLUDING_EXTENSIONLESS = DOC_EXTENSIONS | {""}

# 拡張子なしファイルまで対象を広げた際に、万一バイナリが紛れ込んでも
# テキストデコード・正規表現走査が重くならないための安全弁(5MB)。
# 実測の対象7件は最大でも35,823バイト(third_party\pyooz-0.0.8-source\LICENSE)であり、
# 通常の文書ファイルなら十分な余裕がある。
_MAX_EXTENSIONLESS_DOC_SIZE_BYTES = 5 * 1024 * 1024

# base64/圧縮データ様の連続英数字列(80文字以上)を検出する正規表現。
# manual.html(画像embedded HTML)がこれに該当する。80文字という閾値は、
# 実際の禁止フレーズ(いずれも80文字未満)を誤って巻き込まないための余裕を持たせた値。
_BASE64_NOISE_RE = re.compile(r"[A-Za-z0-9+/=]{80,}")


def desensitize_base64_noise(text):
    """判定対象のノイズ(長い base64 相当の連続英数字列)をプレースホルダへ
    置換する。禁止フレーズ側(空白・非ASCII文字を含む多語)はbase64アルファベット
    には出現し得ないため、この処理をしなくても元々誤検知しない。単独の短い
    ASCIIトークン(FBX等)はbase64ノイズ内に統計的偶然で出現し得るため、
    この前処理が無いと manual.html のようなbase64埋め込みHTMLで誤検知する
    (実測: 前処理無しだと manual.html 内で "FBX" が78回ヒットし、すべて
    base64ノイズ内だった)。"""
    return _BASE64_NOISE_RE.sub("<<<BASE64_NOISE_STRIPPED>>>", text)


def list_doc_entries(names):
    """zipエントリ名一覧(namelist()相当)から、文書拡張子のファイル+拡張子無しの
    ライセンス表記ファイル(LICENSE等)を動的に抽出する(ディレクトリエントリ・
    コード/バイナリファイルは除外)。サイズ情報が無い名前一覧だけを対象とする
    軽量版で、拡張子無しファイルのサイズ上限チェックは scan_zip_docs() 側で行う。"""
    out = []
    for n in names:
        if n.endswith("/"):
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext in DOC_EXTENSIONS_INCLUDING_EXTENSIONLESS:
            out.append(n)
    return out


def find_doc_violations(raw_text):
    """1文書ファイルのテキストを検査し、違反の説明文字列のリストを返す
    (空リストなら違反なし)。純関数(I/Oなし)。"""
    text = desensitize_base64_noise(raw_text)
    lowered = text.lower()
    hits = []

    for phrase in DEFENDER_BYPASS_PHRASES:
        if phrase.lower() in lowered:
            hits.append("defender_bypass_instructions: %r" % phrase)
    for phrase in FALSE_SAFETY_CLAIM_PHRASES:
        if phrase.lower() in lowered:
            hits.append("false_safety_claim: %r" % phrase)
    for phrase in FALSE_APPLICATION_STATUS_PHRASES:
        if phrase.lower() in lowered:
            hits.append("false_application_status: %r" % phrase)
    for phrase in OUT_OF_SCOPE_TOPIC_PHRASES:
        if phrase.lower() in lowered:
            hits.append("out_of_scope_topic: %r" % phrase)
    for phrase in INTERNAL_TRACE_PHRASES:
        if phrase.lower() in lowered:
            hits.append("internal_trace: %r" % phrase)
    for token in INTERNAL_TRACE_WORD_TOKENS:
        # 単純な部分一致(大小文字無視)。日本語の地の文に直接続くと(例:
        # "raichuのPCで")\bが\w判定の都合でJP文字との境界を検出できない
        # ことがあるため、ここでは単語境界を使わない。"raichu"/"PB2306"は
        # 一般語の部分文字列として誤爆する可能性が低いトークンなので許容する。
        if token.lower() in lowered:
            hits.append("internal_trace_token: %r" % token)
    if _OWNER_HANDLE is not None and _OWNER_HANDLE.lower() in lowered:
        hits.append("owner_handle_leak")
    if re.search(r"\b%s\b" % FBX_TOKEN, text, re.IGNORECASE):
        hits.append("fbx_mentioned_in_user_doc")

    return hits


def scan_zip_docs(zip_path):
    """zip_path内の全文書ファイル(動的列挙)を検査し、
    {entry_name: [violation, ...]} の辞書を返す(空dictなら違反なし)。
    拡張子無しファイル(LICENSE等)は _MAX_EXTENSIONLESS_DOC_SIZE_BYTES を
    超える場合スキップする(バイナリ混入時の重い誤走査を避ける安全弁)。"""
    offenders = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in list_doc_entries(zf.namelist()):
            ext = os.path.splitext(name)[1].lower()
            info = zf.getinfo(name)
            if ext == "" and info.file_size > _MAX_EXTENSIONLESS_DOC_SIZE_BYTES:
                continue
            raw = zf.read(name)
            text = raw.decode("utf-8", errors="replace")
            hits = find_doc_violations(text)
            if hits:
                offenders[name] = hits
    return offenders


# ---------------------------------------------------------------------------
# 1. 単体表: list_doc_entries() / find_doc_violations() の正・負の対照
# ---------------------------------------------------------------------------

def test_list_doc_entries_picks_documents_and_skips_code_and_dirs():
    names = [
        "Stage/README.md",
        "Stage/manual.html",
        "Stage/LICENSE",
        "Stage/THIRD_PARTY_LICENSES.txt",
        "Stage/Uchinoko.exe",
        "Stage/pipeline/",
        "Stage/pipeline/py/vp_core.py",
        "Stage/pipeline/cli/convert.ps1",
        "Stage/unity/DiveToPalworldExporter.cs",
        "Stage/assets/third_party/SOURCES.md",
    ]
    picked = list_doc_entries(names)
    assert picked == [
        "Stage/README.md",
        "Stage/manual.html",
        "Stage/LICENSE",
        "Stage/THIRD_PARTY_LICENSES.txt",
        "Stage/assets/third_party/SOURCES.md",
    ]
    # LICENSE(拡張子無しのライセンス表記)は対象に含む。
    # exe・ディレクトリエントリ・コードファイルはいずれも対象外。
    assert "Stage/LICENSE" in picked
    assert not any(p.endswith((".py", ".ps1", ".cs", ".exe")) for p in picked)


def test_find_doc_violations_clean_text_has_no_hits():
    clean = (
        "本ツールは個人開発のため未署名の実行ファイルです。"
        "現在も検出されます。詳細は SECURITY.md をご覧ください。\n"
        "This tool supports VRM 0.0, VRM 1.0, and prefab avatars.\n"
    )
    assert find_doc_violations(clean) == []


def test_find_doc_violations_detects_defender_bypass_steps():
    sample = (
        "1. 「保護の履歴」から本ツールの検出項目を探して「復元」してください。\n"
        "2. 「除外の追加または削除」で展開先フォルダーを除外に登録してください。\n"
    )
    hits = find_doc_violations(sample)
    assert any("保護の履歴" in h for h in hits)
    assert any("除外の追加または削除" in h for h in hits)


def test_find_doc_violations_detects_false_safety_claim():
    hits = find_doc_violations("作者の手元の確認では、最新版は検出されていません。")
    assert any("false_safety_claim" in h for h in hits)


def test_find_doc_violations_detects_false_application_status():
    hits = find_doc_violations("コード署名の適用を申請中です(2026-07現在、審査中)。")
    assert any("false_application_status" in h for h in hits)


def test_find_doc_violations_detects_out_of_scope_topics():
    hits = find_doc_violations("VRChat SDKのビルドを呼び出します。VRCSDKにも触れません。")
    assert any("VRChat SDK" in h for h in hits)
    assert any("VRCSDK" in h for h in hits)


@pytest.mark.skipif(
    _SCOPE_FORBIDDEN_THIRDPARTY_NAME is None,
    reason="devtools/sensitive_denylist.py が無い(Pub側の想定挙動。devtools\\は"
    "実値を含むため意図的に非公開。ライセンス上名指し禁止のサードパーティ製品名は"
    "Dev側専用でのみ検査する)。",
)
def test_find_doc_violations_detects_scope_forbidden_thirdparty_name():
    sample = "%sを検出したら警告します。" % _SCOPE_FORBIDDEN_THIRDPARTY_NAME
    hits = find_doc_violations(sample)
    assert any(_SCOPE_FORBIDDEN_THIRDPARTY_NAME in h for h in hits)


def test_find_doc_violations_detects_internal_traces():
    hits = find_doc_violations(r"詳細は C:\P\Work\DiveToPalworld\.devonly\docs を参照。raichuのPCで確認済み。")
    assert any("internal_trace" in h for h in hits)
    assert any("raichu" in h for h in hits)


@pytest.mark.skipif(
    _OWNER_HANDLE is None,
    reason="devtools/sensitive_denylist.py が無い(Pub側の想定挙動。devtools\\は"
    "実値を含むため意図的に非公開。owner_handle_leakチェックはDev側専用)。",
)
def test_find_doc_violations_detects_owner_handle():
    hits = find_doc_violations("連絡先: %s@example.com" % _OWNER_HANDLE)
    assert any("owner_handle_leak" in h for h in hits)


def test_find_doc_violations_detects_fbx_mention():
    hits = find_doc_violations("本ツールは FBX / VRM / prefab に対応しています。")
    assert any("fbx_mentioned_in_user_doc" in h for h in hits)


def test_find_doc_violations_does_not_flag_multiplayer_permanent_non_support():
    """マルチプレイは「将来にわたって対応しません」という正当な文脈での言及を
    誤検知しないこと(README.mdの既存の正当な記載を壊さないため、そもそも
    マルチプレイ/multiplayerは禁止語リストに入れていないことの確認)。"""
    sample = "## 非対応範囲(将来にわたって対応しません)\n- マルチプレイ\n"
    assert find_doc_violations(sample) == []


def test_desensitize_base64_noise_suppresses_fbx_false_positive_in_html_blob():
    """manual.html相当のbase64ノイズ内に偶然含まれる短いトークン(FBX)は、
    前処理で無害化されて誤検知しないこと(実際にmanual.htmlで観測された事象の
    負の対照的な再現)。"""
    fake_base64_blob = "AAAA" * 5 + "FBX" + "BBBB" * 15  # 80文字超のbase64様の連続英数字列
    assert len(fake_base64_blob) > 80
    hits = find_doc_violations("data:image/png;base64,%s" % fake_base64_blob)
    assert hits == [], "base64ノイズ内のFBXが誤検知された: %r" % hits


def test_desensitize_base64_noise_still_flags_real_short_mentions_outside_noise():
    """base64ノイズの無害化が過剰になっていないこと(ノイズの外にある正真の
    禁止語は引き続き検出されること)。"""
    hits = find_doc_violations("本ツールは FBX に対応しています。詳細は割愛。")
    assert any("fbx_mentioned_in_user_doc" in h for h in hits)


def test_scan_zip_docs_flags_a_synthetic_bad_zip():
    """負の対照: 意図的に違反文言を混入させた合成zipを作り、
    scan_zip_docs()が確実に検出することを示す(BRIEFING指示の負の対照要件)。
    owner_handle_leak行は_OWNER_HANDLEが無い環境(Pub側)では合成テキストから
    省く――他の6分類の検出力はDev/Pub両方で等しく検証する。"""
    handle_line = "連絡先: %s@example.com\n" % _OWNER_HANDLE if _OWNER_HANDLE is not None else ""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with zipfile.ZipFile(tmp_path, "w") as zf:
            zf.writestr(
                "Uchinoko_for_Palworld/README.md",
                "1. 「保護の履歴」から検出項目を探して「復元」してください。\n"
                "2. 「除外の追加または削除」で除外に登録してください。\n"
                "作者の手元の確認では、最新版は検出されていません。\n"
                "VRChat SDKのビルドを呼び出します。\n"
                "本ツールは FBX に対応しています。\n" + handle_line,
            )
            zf.writestr("Uchinoko_for_Palworld/Uchinoko.exe", b"\x00\x01\x02")  # 対象外(非文書)
        offenders = scan_zip_docs(tmp_path)
        assert "Uchinoko_for_Palworld/README.md" in offenders
        hits = offenders["Uchinoko_for_Palworld/README.md"]
        assert any("defender_bypass_instructions" in h for h in hits)
        assert any("false_safety_claim" in h for h in hits)
        assert any("out_of_scope_topic" in h for h in hits)
        assert any("fbx_mentioned_in_user_doc" in h for h in hits)
        if _OWNER_HANDLE is not None:
            assert any("owner_handle_leak" in h for h in hits)
        assert "Uchinoko_for_Palworld/Uchinoko.exe" not in offenders
    finally:
        os.remove(tmp_path)


def test_scan_zip_docs_accepts_a_synthetic_clean_zip():
    """正の対照: 現在の正しい文言(README.mdの実際の文面に近い、違反を含まない
    合成zip)はPASSすること(過検知で検査全体が信用を失わないための確認)。"""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with zipfile.ZipFile(tmp_path, "w") as zf:
            zf.writestr(
                "Uchinoko_for_Palworld/README.md",
                "現在も検出されます。直近の実測ではVirusTotal 74エンジン中3件が検出しました。\n"
                "セキュリティソフトの設定変更(除外の追加など)については、"
                "本ツールとしてご案内はしていません。\n"
                "## 非対応範囲(将来にわたって対応しません)\n- マルチプレイ\n",
            )
        offenders = scan_zip_docs(tmp_path)
        assert offenders == {}, "正当な文面が誤検知された: %r" % offenders
    finally:
        os.remove(tmp_path)


# ---------------------------------------------------------------------------
# 2. 統合テスト: 実際にmake_dist.ps1でzipを作り、実物を検査する
# ---------------------------------------------------------------------------

def _tool_version():
    with open(MAIN_SRC, encoding="utf-8-sig") as f:
        src = f.read()
    m = re.search(r'const\s+string\s+ToolVersion\s*=\s*"([^"]+)"', src)
    assert m, "ToolVersion定数が見つからない"
    return m.group(1)


def _which(cmd):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, cmd)
        for ext in ("", ".exe", ".cmd", ".bat"):
            if os.path.isfile(cand + ext):
                return cand + ext
    return None


def _build_prereqs_missing():
    """make_dist.ps1が必須とする前提のうち無いものを列挙する
    (test_signpath_dist_layout.pyと同じ判定)。"""
    missing = []
    if not _which("pwsh"):
        missing.append("pwsh")
    csc = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                        "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")
    if not os.path.isfile(csc):
        missing.append("csc.exe")
    ooz = os.path.join(os.environ.get("APPDATA", ""), "Python", "Python313",
                        "site-packages", "ooz.pyd")
    if not os.path.isfile(ooz):
        missing.append("ooz.pyd (pip install pyooz)")
    py3dll = os.environ.get("D2P_PYTHON311_DLL") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python311", "python3.dll")
    if not os.path.isfile(py3dll):
        missing.append("python3.dll (Python 3.11)")
    return missing


@pytest.fixture(scope="module")
def built_dist_zip():
    missing = _build_prereqs_missing()
    if missing:
        pytest.skip("配布物ビルドの前提が無い環境: " + ", ".join(missing))
    version = _tool_version()
    out_dir = tempfile.mkdtemp(prefix="d2p_shipdocs_content_")
    suffix = "_shipdocstest"
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-File", MAKE_DIST_PS1, "-Version", version, "-Suffix", suffix],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )
    zip_path = os.path.join(REPO_ROOT, "dist",
                             "Uchinoko_for_Palworld_{}_full{}.zip".format(version, suffix))
    if proc.returncode != 0 or not os.path.isfile(zip_path):
        pytest.fail("build\\make_dist.ps1 の実行に失敗した:\nrc={}\n{}".format(
            proc.returncode, (proc.stdout or "") + (proc.stderr or "")))
    try:
        yield zip_path
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass


def test_real_dist_zip_has_doc_entries_to_scan(built_dist_zip):
    """検査対象が空振り(0件)になっていないこと(消えていたら検査自体が
    意味を失う事故を防ぐ)。"""
    with zipfile.ZipFile(built_dist_zip) as zf:
        docs = list_doc_entries(zf.namelist())
    assert docs, "配布zip内に文書拡張子のファイルが1件も無い(走査対象が空振り)"
    basenames = {os.path.basename(d) for d in docs}
    assert "README.md" in basenames
    assert "manual.html" in basenames


def test_real_dist_zip_docs_have_no_forbidden_content(built_dist_zip):
    offenders = scan_zip_docs(built_dist_zip)
    assert offenders == {}, (
        "実際のmake_dist.ps1出力(配布zip)の文書ファイルに禁止内容が見つかった: %r"
        % offenders
    )


# dev#444: manual.html は manual.md からの自動生成経路が無く、配布zipに同梱される
# manual.html には(ソース側でとうに追記済みの)Windows Defender誤検知についての
# 開示節が一度も含まれていなかった。「manual.htmlがmanual.mdの内容を含むこと」を
# 実際に配布zipへ適用して確認する(devtools\gen_manual_html.py の生成配線が
# build\make_dist.ps1へ実際に届いていることの証明。1-D finding、WP33監査記録
# .devonly\docs\signpath\verify\WP33_shipped_docs_audit.md 参照)。
_MANUAL_HTML_MUST_CONTAIN_JA = [
    "Windows Defenderなどのセキュリティソフトの汎用的な誤検知",
    "現在も検出されます。",
]
_MANUAL_EN_HTML_MUST_CONTAIN_EN = [
    "generic heuristic/ML-based",
    "It is still detected today.",
]


def test_real_dist_zip_manual_html_reflects_manual_md_av_disclosure(built_dist_zip):
    """manual.md(日本語)のAV誤検知開示節が、配布zip実物のmanual.htmlに
    実際に含まれていること。"""
    with zipfile.ZipFile(built_dist_zip) as zf:
        names = [n for n in zf.namelist() if os.path.basename(n) == "manual.html"]
        assert names, "配布zipにmanual.htmlが同梱されていない"
        text = zf.read(names[0]).decode("utf-8")
    for marker in _MANUAL_HTML_MUST_CONTAIN_JA:
        assert marker in text, (
            "配布zipのmanual.htmlにAV開示節の文言が見つからない(生成配線が"
            "切れている可能性): %r" % marker
        )


def test_real_dist_zip_manual_en_html_is_shipped_and_reflects_av_disclosure(built_dist_zip):
    """英語版(manual.en.html)も同梱され、対応するAV開示節を含むこと
    (dev#444: 日本語を読まないユーザーにも説明が届くようにする対応)。"""
    with zipfile.ZipFile(built_dist_zip) as zf:
        names = [n for n in zf.namelist() if os.path.basename(n) == "manual.en.html"]
        assert names, "配布zipにmanual.en.htmlが同梱されていない"
        text = zf.read(names[0]).decode("utf-8")
    for marker in _MANUAL_EN_HTML_MUST_CONTAIN_EN:
        assert marker in text, (
            "配布zipのmanual.en.htmlにAV disclosureの文言が見つからない: %r" % marker
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
