"""U2 T2: cooked uasset側 FPackageFileSummary + ExportMap(FObjectExport)のパース。

頂点数を変える改変にはuexpのファイルサイズが変わるため、.uasset側の
エクスポートマップのSerialSize(そのエクスポートが占めるバイト数)を
書き換える必要がある。本スクリプトはSerialSize/SerialOffsetの位置を
UE5.1ソース(CoreUObject/Private/UObject/PackageFileSummary.cpp の
operator<<(FStructuredArchive::FSlot, FPackageFileSummary&)、および
CoreUObject/Private/UObject/ObjectResource.cpp の
operator<<(FStructuredArchive::FSlot, FObjectExport&))通りに前方パースして特定する。

実測で確認した本ファイル群の前提(Bronze001、2,583バイトのuassetで検証。
フィールドの値そのものは実測なので、以下は「このゲームのcookパイプラインでは
毎回この通りになる」という前提。値が食い違えばSkStructureError/plausibility
チェックで即座に検出される):
  - Legacy file version = -8 (FileVersionUE5フィールドあり)
  - FileVersionUE4/UE5/LicenseeUE は全て0 → bUnversioned(未バージョン管理cook)。
    実行時は「現在のエンジンの最新バージョン」を暗黙適用する規約なので、
    UE5.1のEUnrealEngineObjectUE5Version::AUTOMATIC_VERSION(=1008=
    ADD_SOFTOBJECTPATH_LIST)を前提に以下のバージョンゲートを固定的に解決する:
      - ADD_SOFTOBJECTPATH_LIST(1008) 以上 → SoftObjectPathsCount/Offsetあり
      - REMOVE_OBJECT_EXPORT_PACKAGE_GUID(1005) 以上 → per-export PackageGuidなし
      - TRACK_OBJECT_EXPORT_IS_INHERITED(1006) 以上 → bIsInheritedInstanceあり
      - OPTIONAL_RESOURCES(1003) 以上 → bGeneratePublicHashあり
  - PackageFlags & PKG_FilterEditorOnly(0x80000000) が真 → LocalizationId(FString)は
    シリアライズされない(実測: 本ファイル群は常に真。フラグはファイルごとに
    直接読んで判定するので、これ自体はハードコードではない)
  - WITH_EDITORONLY_DATA無効(ショップ向けcookedビルド)→ PersistentGuidなし
  - VER_UE4_64BIT_EXPORTMAP_SERIALSIZES 以上 → SerialSize/SerialOffsetはint64
  - GatherableTextDataCount/Offset、TemplateIndexは常時あり(いずれも
    上記より遥かに古いバージョンのゲートなので無条件に真)

FObjectExportの全フィールド(bForcedExport〜CreateBeforeCreateDependencies)まで
読み切ることで1エントリのバイト長(stride)を実測し、これが後続の
DependsOffsetと一致することで検証している(Bronze001実測: stride=96、
export_offset(2459)+stride=2555=DependsOffset、完全一致)。
"""
import os
import struct
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
ROOT = r"C:\P\Work\DiveToPalworld\work\toto\build\pak_extract\Player\Outfit"

PKG_FILTER_EDITOR_ONLY = 0x80000000


class UassetHeaderError(RuntimeError):
    pass


class _Reader:
    def __init__(self, data, off=0):
        self.data = data
        self.off = off

    def i32(self):
        v = struct.unpack_from('<i', self.data, self.off)[0]
        self.off += 4
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.data, self.off)[0]
        self.off += 4
        return v

    def i64(self):
        v = struct.unpack_from('<q', self.data, self.off)[0]
        self.off += 8
        return v

    def bytes(self, n):
        v = self.data[self.off:self.off + n]
        self.off += n
        return v

    def fstring(self):
        slen = self.i32()
        if slen == 0:
            return ''
        if slen > 0:
            s = self.data[self.off:self.off + slen - 1].decode('ascii', errors='replace')
            self.off += slen
        else:
            n = -slen * 2
            s = self.data[self.off:self.off + n - 2].decode('utf-16-le', errors='replace')
            self.off += n
        return s


def parse_package_summary(data):
    """FPackageFileSummaryを前方パースし、ExportMap/ImportMap等の
    カウント・オフセットを返す。"""
    if struct.unpack_from('<I', data, 0)[0] != 0x9E2A83C1:
        raise UassetHeaderError("uasset magic mismatch")
    r = _Reader(data, 4)

    legacy_ver = r.i32()
    if legacy_ver != -4:
        r.i32()  # LegacyUE3Version
    file_version_ue4 = r.i32()
    file_version_ue5 = r.i32() if legacy_ver <= -8 else 0
    file_version_licensee = r.i32()

    cv_count = r.i32()
    if not (0 <= cv_count <= 200):
        raise UassetHeaderError(f"CustomVersion count implausible: {cv_count}")
    r.off += cv_count * 20  # FGuid(16) + int32 Version(4)

    total_header_size = r.i32()
    package_name = r.fstring()

    package_flags = r.u32()
    filter_editor_only = bool(package_flags & PKG_FILTER_EDITOR_ONLY)

    name_count = r.i32()
    name_offset = r.i32()

    # SoftObjectPathsCount/Offset: ADD_SOFTOBJECTPATH_LIST以上(前提。上記docstring参照)
    soft_object_paths_count = r.i32()
    soft_object_paths_offset = r.i32()

    if not filter_editor_only:
        r.fstring()  # LocalizationId

    gatherable_text_count = r.i32()
    gatherable_text_offset = r.i32()

    export_count = r.i32()
    export_offset = r.i32()
    import_count = r.i32()
    import_offset = r.i32()
    depends_offset = r.i32()

    if not (0 < export_count <= 10000):
        raise UassetHeaderError(f"ExportCount implausible: {export_count}")
    if not (0 <= export_offset < len(data)):
        raise UassetHeaderError(f"ExportOffset out of range: {export_offset}")

    return {
        'file_version_ue4': file_version_ue4,
        'file_version_ue5': file_version_ue5,
        'file_version_licensee': file_version_licensee,
        'total_header_size': total_header_size,
        'package_name': package_name,
        'package_flags': package_flags,
        'filter_editor_only': filter_editor_only,
        'name_count': name_count,
        'name_offset': name_offset,
        'soft_object_paths_count': soft_object_paths_count,
        'soft_object_paths_offset': soft_object_paths_offset,
        'export_count': export_count,
        'export_offset': export_offset,
        'import_count': import_count,
        'import_offset': import_offset,
        'depends_offset': depends_offset,
    }


def parse_export_entry(data, off):
    """FObjectExportを1件、前方パースする。戻り値: (dict, 次エントリのoffset)"""
    start = off
    r = _Reader(data, off)

    class_index = r.i32()
    super_index = r.i32()
    template_index = r.i32()          # VER_UE4_TemplateIndex_IN_COOKED_EXPORTS(古い、常時あり)
    outer_index = r.i32()
    object_name_index = r.i32()
    object_name_number = r.i32()
    object_flags = r.u32()

    serial_size_off = r.off
    serial_size = r.i64()             # VER_UE4_64BIT_EXPORTMAP_SERIALSIZES以上前提
    serial_offset = r.i64()

    b_forced_export = r.u32()
    b_not_for_client = r.u32()
    b_not_for_server = r.u32()
    # REMOVE_OBJECT_EXPORT_PACKAGE_GUID以上前提 → per-export PackageGuidなし
    b_is_inherited_instance = r.u32()  # TRACK_OBJECT_EXPORT_IS_INHERITED以上前提
    export_package_flags = r.u32()
    b_not_always_loaded_for_editor_game = r.u32()  # VER_UE4_LOAD_FOR_EDITOR_GAME(古い、常時あり)
    b_is_asset = r.u32()               # VER_UE4_COOKED_ASSETS_IN_EDITOR_SUPPORT(古い、常時あり)
    b_generate_public_hash = r.u32()   # OPTIONAL_RESOURCES以上前提

    # VER_UE4_PRELOAD_DEPENDENCIES_IN_COOKED_EXPORTS(古い、常時あり)
    first_export_dependency = r.i32()
    ser_before_ser_deps = r.i32()
    create_before_ser_deps = r.i32()
    ser_before_create_deps = r.i32()
    create_before_create_deps = r.i32()

    for name, val in (('bForcedExport', b_forced_export), ('bNotForClient', b_not_for_client),
                       ('bNotForServer', b_not_for_server), ('bIsInheritedInstance', b_is_inherited_instance),
                       ('bNotAlwaysLoadedForEditorGame', b_not_always_loaded_for_editor_game),
                       ('bIsAsset', b_is_asset), ('bGeneratePublicHash', b_generate_public_hash)):
        if val not in (0, 1):
            raise UassetHeaderError(f"{name} not bool @ export {start}: {val}")

    return {
        'start': start,
        'end': r.off,
        'class_index': class_index,
        'super_index': super_index,
        'template_index': template_index,
        'outer_index': outer_index,
        'object_name': (object_name_index, object_name_number),
        'object_flags': object_flags,
        'serial_size_offset': serial_size_off,
        'serial_size': serial_size,
        'serial_offset': serial_offset,
        'b_is_asset': bool(b_is_asset),
    }, r.off


def parse_uasset_exports(uasset_path):
    with open(uasset_path, 'rb') as f:
        data = f.read()
    summary = parse_package_summary(data)
    exports = []
    off = summary['export_offset']
    for _ in range(summary['export_count']):
        entry, off = parse_export_entry(data, off)
        exports.append(entry)
    if off != summary['depends_offset']:
        raise UassetHeaderError(
            f"ExportMap end ({off}) != DependsOffset ({summary['depends_offset']})")
    return summary, exports


def verify(uasset_path, uexp_path, verbose=True):
    if verbose:
        print(f'--- {os.path.basename(uasset_path)} ---')
    summary, exports = parse_uasset_exports(uasset_path)
    uexp_size = os.path.getsize(uexp_path)
    total_serial_size = sum(e['serial_size'] for e in exports)
    ok = (total_serial_size == uexp_size - 4)
    if verbose:
        print(f"  ExportCount={summary['export_count']} ExportOffset={summary['export_offset']} "
              f"TotalHeaderSize={summary['total_header_size']}")
        for i, e in enumerate(exports):
            print(f"  export[{i}]: SerialSize={e['serial_size']}@{e['serial_size_offset']} "
                  f"SerialOffset={e['serial_offset']} bIsAsset={e['b_is_asset']}")
        print(f"  uexp_size={uexp_size} total_serial_size={total_serial_size} "
              f"(uexp_size-4={uexp_size - 4}) => {'OK' if ok else 'FAIL'}")
    return ok


if __name__ == '__main__':
    uasset = os.path.join(DATA_DIR, 'SK_Player_Female_Outfit_Bronze001.uasset')
    uexp = os.path.join(DATA_DIR, 'SK_Player_Female_Outfit_Bronze001.uexp')
    ok = verify(uasset, uexp)
    print(f'  => {"OK" if ok else "FAIL"}')

    print('\n=== 60-body (G3) ===')
    all_ok = True
    n = 0
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if not fn.lower().endswith('.uasset'):
                continue
            uasset = os.path.join(dirpath, fn)
            uexp = uasset[:-7] + '.uexp'
            if not os.path.exists(uexp):
                continue
            try:
                ok = verify(uasset, uexp, verbose=False)
            except Exception as e:
                ok = False
                print(f'  {fn}: EXCEPTION {e}')
            if not ok:
                all_ok = False
                print(f'  {fn}: FAIL')
            n += 1
    print(f'\n{n} files: {"PASS" if (all_ok and n > 0) else "FAIL"}')
    sys.exit(0 if (all_ok and n > 0) else 1)
