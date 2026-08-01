# compat_check.py -- Palworld版互換判定(DESIGN.md §2.7)のPython移植。
#
# 移植元: app\DiveToPalworld.cs 末尾の独立静的クラス群(MainFormから独立済み、
# 元々 --check-palworld-compat 隠しCLIから画面無しで試験するために切り出されて
# いたもの。DESIGN.md §2.7「そのままモジュール関数として1:1移植しやすい部類」):
#   - KnownPalworldVersion (struct, L.6194-6199)
#   - KnownGoodPalworld    (class,  L.6201-6205)
#   - PalworldDetection    (struct, L.6209-6214)
#   - PalworldCompatStatus (struct, L.6217-6228)
#   - PalworldCompat       (static class, L.6230-6400)
#       ParseKnownVersions / ParseKnownManifestHashes / MergeKnownGood /
#       IsKnownVersion / LabelFor / IsKnownManifest / SupportedLabelsJoined /
#       Evaluate / FormatDetected / FormatSupported / BuildLogLine
#
# 3階層の判定(Evaluate()がMainForm.CheckPalworldVersionOnce()から呼ばれる順、
# L.6174-6187のコメントそのまま):
#   1) 既知版番号(known_versions: Steam buildid + Pal-Windows.pakサイズの組)
#   2) 抽出物マニフェスト(known_vanilla_manifest_sha256、dev#91)。版番号が
#      未知でも、実際に変換が消費する材料が既知良好と一致していれば警告しない
#   3) どちらにも一致しなければ警告する
#
# JSON解析について: C#側はcsc.exe単体コンパイル制約(NuGet不可)のため自前の
# 正規表現ベースJSONパーサ(JsonStr/JsonNum/JsonStrArray/JsonObj)を使っており、
# ネストしたオブジェクトの波括弧深さを正しく数えられるかという専用の負の対照
# (CheckPalworldCompatLogicのcase10、JsonObj balanced-brace extraction)まで
# 持っていた。Python移植では標準ライブラリのjsonモジュールをそのまま使うため、
# この種のパーサ自前実装バグはそもそも構造的に発生しない
# (json.loadsはネストしたオブジェクトを常に正しく解釈する)。したがって
# case10は「該当ロジックがPython版に存在しない」ため移植対象から除外した
# (WP-A6の合理的解釈。case1-9は全てEvaluate()自体の分岐なのでそのまま移植する)。
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class KnownPalworldVersion:
    build_id: str
    pak_size: int
    label: str


@dataclass
class KnownGoodPalworld:
    versions: List[KnownPalworldVersion] = field(default_factory=list)
    manifest_hashes: List[str] = field(default_factory=list)


@dataclass
class PalworldDetection:
    """1回分のバージョン検出結果(I/O抜きの値だけ)。Paksが見つからなければ
    detected=Falseのまま(従来の「判定不能=黙って動く」を表す、L.6207-6214)。"""

    detected: bool = False
    build_id: Optional[str] = None  # 取得できなければNone
    pak_size: int = 0               # 取得できなければ0


@dataclass
class PalworldCompatStatus:
    """PalworldCompat.Evaluate()の結果。should_warnがTrueの時だけ警告を出す
    (L.6217-6228)。"""

    detected: bool = False
    build_id: Optional[str] = None
    pak_size: int = 0
    known_version: bool = False
    version_label: Optional[str] = None
    manifest_available: bool = False
    manifest_hash: Optional[str] = None
    known_manifest: bool = False
    should_warn: bool = False


def parse_known_versions(json_text: Optional[str]) -> List[KnownPalworldVersion]:
    """ParseKnownVersions(L.6232-6253)相当。"known_versions"配列を解析する。
    不正なJSON/欠落フィールドは黙ってスキップする(C#側もbuild_id空/pak_size<0の
    要素をcontinueで読み飛ばす、というfail-safe方針を踏襲)。"""
    result: List[KnownPalworldVersion] = []
    if not json_text:
        return result
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return result
    if not isinstance(data, dict):
        return result
    for item in data.get("known_versions") or []:
        if not isinstance(item, dict):
            continue
        build_id = item.get("build_id")
        pak_size = item.get("pak_size")
        if not build_id or pak_size is None or pak_size < 0:
            continue
        label = item.get("label") or build_id
        result.append(KnownPalworldVersion(build_id=str(build_id), pak_size=int(pak_size), label=str(label)))
    return result


def parse_known_manifest_hashes(json_text: Optional[str]) -> List[str]:
    """ParseKnownManifestHashes(L.6255-6258)相当。"known_vanilla_manifest_sha256"
    配列を解析する。"""
    if not json_text:
        return []
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    hashes = data.get("known_vanilla_manifest_sha256")
    if not isinstance(hashes, list):
        return []
    return [str(h) for h in hashes if isinstance(h, str)]


def merge_known_good(
    bundled_json: Optional[str], remote_block_json_or_none: Optional[str]
) -> KnownGoodPalworld:
    """MergeKnownGood(L.6263-6281)相当。同梱データ(bundled_json)にリモート
    (remote_block_json_or_none、versions.jsonの"palworld_known_good"部分を
    既に切り出したもの)を重複除去しつつ足し込む。remote_block_json_or_noneが
    None/空なら同梱データのみ(dev#89のオフラインフォールバック)。"""
    result = KnownGoodPalworld()
    result.versions.extend(parse_known_versions(bundled_json))
    result.manifest_hashes.extend(parse_known_manifest_hashes(bundled_json))
    if remote_block_json_or_none:
        for v in parse_known_versions(remote_block_json_or_none):
            dup = any(
                existing.build_id == v.build_id and existing.pak_size == v.pak_size
                for existing in result.versions
            )
            if not dup:
                result.versions.append(v)
        for h in parse_known_manifest_hashes(remote_block_json_or_none):
            if h not in result.manifest_hashes:
                result.manifest_hashes.append(h)
    return result


def is_known_version(known: KnownGoodPalworld, build_id: Optional[str], pak_size: int) -> bool:
    """IsKnownVersion(L.6283-6289)相当。"""
    if not build_id:
        return False
    return any(v.build_id == build_id and v.pak_size == pak_size for v in known.versions)


def label_for(known: KnownGoodPalworld, build_id: Optional[str], pak_size: int) -> Optional[str]:
    """LabelFor(L.6291-6296)相当。"""
    for v in known.versions:
        if v.build_id == build_id and v.pak_size == pak_size:
            return v.label
    return None


def is_known_manifest(known: KnownGoodPalworld, manifest_hash: Optional[str]) -> bool:
    """IsKnownManifest(L.6298-6304)相当(大文字小文字を無視して比較)。"""
    if not manifest_hash:
        return False
    return any(h.lower() == manifest_hash.lower() for h in known.manifest_hashes)


def supported_labels_joined(known: KnownGoodPalworld) -> str:
    """SupportedLabelsJoined(L.6306-6312)相当。"""
    labels: List[str] = []
    for v in known.versions:
        if v.label not in labels:
            labels.append(v.label)
    return ", ".join(labels) if labels else "(none)"


def evaluate(
    known: KnownGoodPalworld, det: PalworldDetection, manifest_hash: Optional[str]
) -> PalworldCompatStatus:
    """Evaluate(L.6316-6364)相当。純粋なロジックのみ(I/Oなし)。manifest_hashは
    呼び出し側が既に読み込んだ値(無ければNone)を渡す。判定不能(Paksが見つから
    ない)ならdetected=Falseのまま返す。"""
    st = PalworldCompatStatus(detected=det.detected, build_id=det.build_id, pak_size=det.pak_size)
    if not det.detected:
        st.should_warn = False
        return st

    if det.build_id is not None and is_known_version(known, det.build_id, det.pak_size):
        st.known_version = True
        st.version_label = label_for(known, det.build_id, det.pak_size)
        st.should_warn = False
        return st

    # 保険経路: buildidが取れない環境でも、pakサイズだけでも既知の値に一致すれば
    # 十分とする(旧PalworldVersionWarning()のサイズ保険と同じ考え方、L.6334-6348)
    if det.build_id is None and det.pak_size > 0:
        for v in known.versions:
            if v.pak_size == det.pak_size:
                st.known_version = True
                st.version_label = v.label
                st.should_warn = False
                return st

    if manifest_hash:
        st.manifest_available = True
        st.manifest_hash = manifest_hash
        if is_known_manifest(known, manifest_hash):
            st.known_manifest = True
            st.should_warn = False
            return st

    st.should_warn = True
    return st


def format_detected(st: PalworldCompatStatus) -> str:
    """FormatDetected(L.6366-6376)相当。"""
    if not st.detected:
        return "not found"
    if st.build_id is not None and st.pak_size > 0:
        return f"build {st.build_id}, pak {st.pak_size:,} bytes"
    if st.build_id is not None:
        return f"build {st.build_id}"
    if st.pak_size > 0:
        return f"pak {st.pak_size:,} bytes"
    return "unknown"


def format_supported(known: KnownGoodPalworld) -> str:
    """FormatSupported(L.6378-6383)相当。"""
    parts = [f"{v.label} (build {v.build_id})" for v in known.versions]
    return ", ".join(parts) if parts else "(none)"


def build_log_line(known: KnownGoodPalworld, st: PalworldCompatStatus) -> str:
    """BuildLogLine(L.6387-6399)相当。dev#87: 診断ログヘッダ用の1行。検出成否・
    版番号・マニフェスト自己判定の結果を必ず数字入りで残す(検出失敗時も
    "not found"の事実を残す)。"""
    supported = format_supported(known)
    if not st.detected:
        return f"palworld: not found (supported: {supported})"
    if st.known_version:
        return f"palworld: {st.version_label} (build {st.build_id}) (supported: {supported})"
    if st.manifest_available:
        note = (
            "extracted materials match known-good, warning suppressed (dev#91)"
            if st.known_manifest
            else "extracted materials differ from known-good"
        )
    else:
        note = "extraction manifest not available yet"
    return f"palworld: unknown ({format_detected(st)}) (supported: {supported}) [{note}]"
