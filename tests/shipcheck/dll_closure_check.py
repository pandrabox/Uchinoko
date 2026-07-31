# -*- coding: utf-8 -*-
"""T3(WP6): 配布zip内exe/pydのDLL依存クロージャ静的検査。

背景: 実事故(前提ソフト無しの
まっさらなWindowsで python.exe / ooz.pyd が VCRUNTIME140.dll 等を見つけられず
STATUS_DLL_NOT_FOUND で即死)の再発防止。当時の対策は `build\\make_dist.ps1` に
実装済み(VC++ランタイムDLLをBlender本体のblender.crt\\からpython\\bin\\と
site-packages\\へ複製する処理)だが、それが**今も効いていること**を継続的に
機械検査するゲートが無かった。このスクリプトがその役目を担う。

やること(標準ライブラリのみ、pip追加禁止の既存方針を厳守):
  1. zip内の全 .exe / .pyd エントリのPEインポートテーブルを読む
     (dev側の読み取り専用調査ツールと同じ手法をここに再実装。
     devtools\\配下は非公開のためtests\\shipcheck\\配下に独立実装する)。
  2. 各インポートDLL名を「システム標準DLL」許容リスト
     (Windowsレジストリの KnownDLLs + api-ms-*/ext-ms-* API Set + 既知の
     OS同梱DLL)と照合し、非該当のものだけを残す。
  3. 残った依存DLLが、zip自身の同梱物(全エントリのbasename集合)の中に
     存在するか("同梱物で閉じているか")を確認する。見つからなければFAIL。

スコープの絞り込み(意図的): 全.dllの推移的依存までは追わない。歴史的事故は
すべて.exe/.pydという「エントリポイント」バイナリの直接依存だったため、
.exe/.pydの直接インポートテーブルだけを見れば実害クラスは捕捉できる。
Blenderポータブル本体が抱える数百のDLL相互依存まで追うのはコストに見合わない
(Blender自体はupstreamでテスト済みの完成品として同梱している)。

使い方:
    python tests\\shipcheck\\dll_closure_check.py <zipパス>
    python tests\\shipcheck\\dll_closure_check.py <zipパス> --json <出力先>

exit 0 = 全exe/pydの非システム依存がzip内に閉じている(PASS)。
exit 1 = 1件でも閉じていない依存がある(FAIL)、またはzipが読めない。
"""
import argparse
import json
import os
import re
import struct
import sys
import zipfile

# --- PEインポートテーブル解析(標準ライブラリのみ) --------------------------
# dev側の調査ツールと同じロジック(読み取り専用の調査
# ツールとして先行実装済み)をここへ再実装する。devtoolsは非公開の
# ため出荷物側のtests\shipcheck\に依存を持たせられない。


def list_import_dlls(data):
    """PEバイナリ(bytes)のインポートテーブルから参照DLL名一覧を返す。
    PEとして解釈できない場合は空リスト(壊れているとは断定せず、単に
    インポートテーブルを持たない/読めないものとして扱う。判定はFAILにしない
    ——実行ファイルとして壊れているかどうかはこのゲートの責務ではない)。"""
    try:
        if data[0:2] != b"MZ":
            return []
        (pe_off,) = struct.unpack_from("<I", data, 0x3C)
        if data[pe_off:pe_off + 4] != b"PE\x00\x00":
            return []
        coff_off = pe_off + 4
        (_machine, n_sections) = struct.unpack_from("<HH", data, coff_off)
        opt_hdr_off = coff_off + 20
        size_opt_hdr = struct.unpack_from("<H", data, coff_off + 16)[0]
        if size_opt_hdr == 0:
            return []  # オブジェクトファイル等、実行可能PEではない
        (opt_magic,) = struct.unpack_from("<H", data, opt_hdr_off)
        is_pe32_plus = (opt_magic == 0x20B)
        n_rva_off = opt_hdr_off + (108 if is_pe32_plus else 92)
        dd_off = n_rva_off + 4
        import_rva, _import_size = struct.unpack_from("<II", data, dd_off + 8)  # entry 1 = Import Table

        sec_hdr_off = opt_hdr_off + size_opt_hdr
        sections = []
        for i in range(n_sections):
            off = sec_hdr_off + i * 40
            _name = data[off:off + 8].rstrip(b"\x00")
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off + 8)
            sections.append((vaddr, vsize, rawptr, rawsize))

        def rva2off(rva):
            if rva == 0:
                return None
            for vaddr, vsize, rawptr, rawsize in sections:
                if vaddr <= rva < vaddr + max(vsize, rawsize):
                    return rawptr + (rva - vaddr)
            return None

        names = []
        off = rva2off(import_rva)
        if off is None:
            return names
        i = 0
        while True:
            entry_off = off + i * 20
            if entry_off + 20 > len(data):
                break
            (_orig_first_thunk, _ts, _fchain, name_rva, _first_thunk) = struct.unpack_from(
                "<IIIII", data, entry_off)
            if name_rva == 0:
                break
            noff = rva2off(name_rva)
            if noff is None:
                break
            end = data.find(b"\x00", noff)
            if end == -1:
                break
            names.append(data[noff:end].decode("ascii", errors="replace"))
            i += 1
            if i > 500:  # 異常データでの無限ループ防止(フェイルセーフ)
                break
        return names
    except (struct.error, IndexError, ValueError):
        return []


# --- システム標準DLLの許容リスト ---------------------------------------------
# api-ms-win-*.dll / ext-ms-*.dll はWindows 10以降のAPI Set(apisetschema.dllが
# 実行時に解決する仮想DLL)。実体を同梱する必要が無く、常にOSが提供する。
_API_SET_RE = re.compile(r"^(api-ms-win-|api-ms-|ext-ms-)", re.IGNORECASE)

# レジストリ(KnownDLLs)が読めない環境(非Windows含む)向けの最小フォールバック。
# 実行はWindows前提だが、CI等での構文チェックだけは他OSでも通したいため空でも
# 動作するようにしておく。
_FALLBACK_KNOWNDLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "comctl32.dll", "comdlg32.dll", "ws2_32.dll",
    "ntdll.dll", "msvcrt.dll", "shlwapi.dll", "version.dll", "winmm.dll",
    "imm32.dll", "rpcrt4.dll", "sechost.dll", "bcrypt.dll", "crypt32.dll",
    "setupapi.dll", "userenv.dll", "psapi.dll", "wtsapi32.dll", "netapi32.dll",
    "mscoree.dll",  # .NET Frameworkランチャースタブ(app\DiveToPalworld.cs等のmanaged exe)
}

# KnownDLLs(レジストリ)はWindowsローダーが起動時に共有セクションへ事前ロード
# する「最適化用の一覧」であり、意図的に小さい(=「Windowsに実在するDLL全部」
# ではない)。そのため実測(2026-07-27、v1.0.0 dist zip)でKnownDLLs単独では
# dbghelp.dll/dxgi.dll/CFGMGR32.dll/dwmapi.dll/Cabinet.dll/msi.dll/
# IPHLPAPI.DLLが「非システム扱い」の誤検知(偽陽性)になった。これらはいずれも
# **Windows本体に標準搭載されているコンポーネント**(デバッグヘルプAPI/DXGI
# グラフィックス基盤/PnP構成マネージャ/デスクトップウィンドウマネージャ/
# キャビネットファイルAPI/Windowsインストーラ/IPヘルパーAPI、すべてWindows
# Vista〜XP時代から一貫してin-boxでOSに同梱)であり、VC++ランタイムのような
# 「別途インストールが要る再頒布可能パッケージ」とは性質が違う
# (fix_DL_missing_dll.mdの実事故はvcruntime140.dll等の**再頒布可能**DLLが
# 原因であり、これらin-boxコンポーネントが原因だったことは無い)。
# 「揃わないから許容リストを広げて通す」ではなく、「OS本体同梱コンポーネントと
# 再頒布可能ランタイムは別物」という構造的な区別に基づく追加であることに注意
# (vcruntime*/msvcp*/python3.dll等の再頒布可能ランタイムはここに加えない。
# それらは実際にzipへ同梱されているかどうかを本検査で引き続き検証させる)。
_INBOX_WINDOWS_COMPONENTS = {
    "dbghelp.dll", "dxgi.dll", "cfgmgr32.dll", "dwmapi.dll", "cabinet.dll",
    "msi.dll", "iphlpapi.dll", "d3d9.dll", "d3d11.dll", "d3d12.dll",
    "opengl32.dll", "glu32.dll", "winspool.drv", "wininet.dll", "winhttp.dll",
    "urlmon.dll", "wintrust.dll", "gdiplus.dll", "oleacc.dll", "uxtheme.dll",
    "hid.dll", "powrprof.dll", "ncrypt.dll", "dnsapi.dll", "avrt.dll",
    "mf.dll", "mfplat.dll", "propsys.dll", "dbgeng.dll", "cryptbase.dll",
}


def get_system_dll_allowlist():
    """Windowsレジストリ(KnownDLLs)から実際のシステム標準DLL一覧を読む。
    読めない場合(非Windows、権限不足等)はフォールバック集合を使う
    (fail-closedの観点では「許容リストを小さく持つ」側に倒れるため安全:
    フォールバックが小さすぎても誤検知(過剰FAIL)止まりで、見逃し(過少FAIL)
    にはならない)。"""
    names = set(_FALLBACK_KNOWNDLLS) | set(_INBOX_WINDOWS_COMPONENTS)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\KnownDLLs")
        i = 0
        while True:
            try:
                _valname, val, _type = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            if isinstance(val, str) and val:
                base = val.lower()
                if not base.endswith(".dll"):
                    base += ".dll"
                names.add(base)
        winreg.CloseKey(key)
    except Exception:
        pass  # フォールバックのみで続行(上記の理由でfail-closed側)
    return names


def is_system_allowed(dll_name, allowlist):
    base = dll_name.lower()
    if base in allowlist:
        return True
    if _API_SET_RE.match(dll_name):
        return True
    return False


# --- zip全体のクロージャ検査 --------------------------------------------------

_SCAN_EXTS = (".exe", ".pyd")

# u54(2026-07-27): Blenderポータブルの同梱を廃止し、代わりに ensure_blender.ps1 が
# 初回起動時に使う差し込み素材(ooz.pyd等)だけを _internal\assets\blender_patch\
# へ小容量で同梱するようになった。この ooz.pyd は VCRUNTIME140.dll 等に依存するが、
# その実体(Blender自身のblender.crt\)は配布zipの中にはまだ無い
# (ダウンロードするBlenderポータブル自身が持ってくる。ensure_blender.ps1が
# ダウンロード直後にpython\bin\へ複製する)。つまりblender_patch\配下のバイナリは
# **配布zip単体では意図的にクロージャが閉じていない**(閉じるのはユーザー環境で
# ensure_blender.ps1が実行された後)。ここでfail-closedの対象から後退させるのは
# 「揃わないから許容リストを広げる」のとは違う理由(閾値を緩めているのではなく、
# 検査対象の前提=「zip単体で完結している」が変わったことの反映)。この経路の
# 正しさは tests\shipcheck\test_ensure_blender.py が別途担保する(4.6参照)。
_DEFERRED_CLOSURE_PATH_MARKER = "/assets/blender_patch/"


def _is_deferred_closure_entry(zip_entry_name):
    return _DEFERRED_CLOSURE_PATH_MARKER in zip_entry_name.replace("\\", "/").lower()


def scan_zip_closure(zip_path, allowlist=None):
    """戻り値: {"ok": bool, "scanned": [...], "missing": [...], "deferred": [...],
    "system_skip_count": int}
    missing の各要素: {"binary": zipエントリ名, "missing_dll": DLL名}
    deferred は assets\\blender_patch\\配下(ensure_blender.ps1が後で閉じる前提の
    バイナリ)で見つかった同種の不足で、okの判定には含めない(FAILにしない)。
    """
    if allowlist is None:
        allowlist = get_system_dll_allowlist()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        basenames = set(os.path.basename(n).lower() for n in names if not n.endswith("/"))
        targets = [n for n in names if n.lower().endswith(_SCAN_EXTS)]
        scanned = []
        missing = []
        deferred = []
        system_skip_count = 0
        for n in targets:
            data = zf.read(n)
            imports = list_import_dlls(data)
            entry_missing = []
            for dll in imports:
                if is_system_allowed(dll, allowlist):
                    system_skip_count += 1
                    continue
                if dll.lower() not in basenames:
                    entry_missing.append(dll)
            scanned.append({"binary": n, "import_count": len(imports),
                             "non_system_missing": entry_missing})
            bucket = deferred if _is_deferred_closure_entry(n) else missing
            for dll in entry_missing:
                bucket.append({"binary": n, "missing_dll": dll})
    return {"ok": not missing, "scanned": scanned, "missing": missing, "deferred": deferred,
            "system_skip_count": system_skip_count}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zip_path")
    ap.add_argument("--json", default=None, help="詳細結果のJSON出力先")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.zip_path):
        print("FATAL: zipが見つからない: %s" % args.zip_path)
        return 1

    print("=== T3 DLLクロージャ検査 ===")
    print("zip: %s" % args.zip_path)
    allowlist = get_system_dll_allowlist()
    print("システム標準DLL許容リスト件数: %d" % len(allowlist))

    result = scan_zip_closure(args.zip_path, allowlist)
    print("検査対象(.exe/.pyd)件数: %d" % len(result["scanned"]))
    print("システム標準DLLとして許容(スキップ)した依存件数(延べ): %d" % result["system_skip_count"])

    if result.get("deferred"):
        print("\nINFO(非FAIL): assets\\blender_patch\\配下 %d件は判定対象外" %
              len(result["deferred"]))
        print("  (ensure_blender.ps1がダウンロード直後のBlenderからVC++ランタイムを"
              "複製して初めて閉じる設計。この経路はtest_ensure_blender.pyが別途検証する)")
        for m in result["deferred"]:
            print("  DEFERRED: %s は %s に依存(zip単体では未解決、想定どおり)" %
                  (m["binary"], m["missing_dll"]))

    if result["missing"]:
        print("\nFAIL: 同梱物内で閉じていない非システム依存 %d件" % len(result["missing"]))
        for m in result["missing"]:
            print("  MISSING: %s は %s に依存しているが、zip内のどこにも見つからない" %
                  (m["binary"], m["missing_dll"]))
    else:
        print("\nPASS: 全%d件の.exe/.pydについて、非システム依存はすべてzip内に閉じている"
              "(assets\\blender_patch\\配下は判定対象外、上記INFO参照)" %
              len(result["scanned"]))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("\n詳細JSON: %s" % args.json)

    print("\n=== 結果: %s ===" % ("PASS" if result["ok"] else "FAIL"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
