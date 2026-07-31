# -*- coding: utf-8 -*-
r"""非ASCII(日本語+絵文字)パス上の job.json 読み書き規約テスト(起票案1、2026-07-28)。

背景(独立2件の実報告: BOOTH No.2 / メール No.19、v1.1.2でも再現):
GUIは job.json を UTF-8(BOMなし)で書くが、配布実行環境 PowerShell 5.1 の
Get-Content は既定エンコーディングが ANSI(日本語Windowsでは cp932)。
「デスクトップ」のような非ASCIIパスを含む job.json を cp932 として誤読すると、
プ(UTF-8: E3 83 97)の末尾バイト 0x97 が cp932 の先行バイトとして直後の
0x5C(\)を食い(97 5C = 予)、JSONのエスケープ対「\\」が壊れて裸の「\」が残る
→ ConvertFrom-Json「認識できないエスケープ シーケンスです。」で必ず失敗する。

修正: job.json 等「UTF-8で書かれるファイル」のPS側読取に -Encoding UTF8 を明示
(pipeline\cli\convert.ps1 ほか。個別のencode/decode差し込みではなく規約の統一)。

このテストが守るもの:
  1. バイト列レベルの機構再現(PS不要・環境非依存の負の対照)
  2. PS5.1実機での修正後イディオムの往復(日本語+絵文字パスで green)
  3. PS5.1実機での修正前イディオムの失敗(負の対照。cp932 ACP環境でのみ実行)
  4. ソース回帰ガード(convert.ps1等から -Encoding UTF8 が外れたら赤)

実行: python tests\nonascii\test_nonascii_job_json.py
(stdlib unittestのみ。変換・実機・排他資源には一切触れない)
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CONVERT_PS1 = os.path.join(REPO, "pipeline", "cli", "convert.ps1")
EXPORT_PS1 = os.path.join(REPO, "pipeline", "cli", "export_from_unity.ps1")
ENSURE_PS1 = os.path.join(REPO, "pipeline", "cli", "ensure_blender.ps1")

# 配布版の実行環境と同じ Windows PowerShell 5.1(pwshではない)
PS51 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                    "System32", "WindowsPowerShell", "v1.0", "powershell.exe")

# 報告事例を忠実になぞる: 「デスクトップ」+ 絵文字 + 非ASCIIファイル名(No.15副次)
JP_DIRNAME = "デスクトップ"
EMOJI_DIRNAME = "GAME🍣"
JP_FILENAME = "model_パイロットスーツ.fbx"


def _acp():
    """WindowsのANSIコードページ実値(日本語Windows既定=932)。"""
    try:
        return ctypes.windll.kernel32.GetACP()
    except Exception:
        return None


def _make_job(tmp_root):
    """日本語+絵文字ディレクトリ配下に job.json(UTF-8 BOMなし=GUIと同じ)を作る。"""
    job_dir = os.path.join(tmp_root, JP_DIRNAME, EMOJI_DIRNAME, "DiveToPalworld")
    os.makedirs(job_dir, exist_ok=True)
    vrm_path = os.path.join(job_dir, JP_FILENAME)
    job = {
        "vrm_path": vrm_path,
        "avatar_name": "テスト検体🍣",
        "engine_mode": "noue",
        "paths": {"blender_exe": os.path.join(job_dir, "blender.exe"),
                  "vrm_addon_zip": os.path.join(job_dir, "addon.zip")},
    }
    job_json = os.path.join(job_dir, "job.json")
    # GUI(app\DiveToPalworld.cs:914)と同じ UTF-8 BOMなし。ensure_ascii=Falseで
    # 非ASCIIを生バイトのまま書く(GUIも生の日本語を書く)
    with open(job_json, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    return job_json, vrm_path


def _run_ps51(script_text, *args):
    """ASCIIのみの一時ps1を書き、PS5.1で実行する(非ASCIIは引数でのみ渡す=
    CreateProcessWのUnicode引数経由なのでスクリプト自体の文字コードに依存しない)。"""
    fd, ps1 = tempfile.mkstemp(suffix=".ps1")
    os.close(fd)
    try:
        with open(ps1, "w", encoding="ascii") as f:
            f.write(script_text)
        cp = subprocess.run(
            [PS51, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1] + list(args),
            capture_output=True, timeout=120)
        return cp
    finally:
        try:
            os.remove(ps1)
        except OSError:
            pass


# 修正後イディオム(convert.ps1:$cfg読取と同一)/ 修正前イディオム(v1.1.2相当)
_PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
$Job = $args[0]
$Out = $args[1]
try {
    $cfg = Get-Content $Job -Raw %ENC% | ConvertFrom-Json
    [System.IO.File]::WriteAllText($Out, $cfg.vrm_path, (New-Object System.Text.UTF8Encoding($false)))
    exit 0
} catch {
    [System.IO.File]::WriteAllText($Out, ('PARSE_ERROR: ' + $_.Exception.Message), (New-Object System.Text.UTF8Encoding($false)))
    exit 3
}
"""


class TestMojibakeMechanism(unittest.TestCase):
    """1. バイト列レベルの機構再現(PS不要、全環境で決定的)。"""

    def test_cp932_misread_breaks_json_escape(self):
        # 「プ」(E3 83 97) + JSONエスケープ「\\」(5C 5C)。cp932復号では
        # 97 5C が「予」に結合され、残った 5C が裸のエスケープ「\G」になる
        raw = json.dumps({"p": "D:\\デスクトップ\\GAME"}, ensure_ascii=False).encode("utf-8")
        mojibake = raw.decode("cp932", errors="replace")
        self.assertIn("予", mojibake, "\\の前半バイトがSJIS2バイト文字(予)に食われるはず")
        self.assertIn("\\G", mojibake, "後半の\\が裸で残り、不正エスケープ\\Gになるはず")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(mojibake)  # 「認識できないエスケープ」と同じ構造で必ず不正

    def test_utf8_read_is_correct(self):
        raw = json.dumps({"p": "D:\\デスクトップ\\GAME"}, ensure_ascii=False).encode("utf-8")
        self.assertEqual(json.loads(raw.decode("utf-8"))["p"], "D:\\デスクトップ\\GAME")


@unittest.skipUnless(sys.platform == "win32" and os.path.isfile(PS51),
                     "Windows PowerShell 5.1が無い環境ではスキップ")
class TestPs51JobJsonRead(unittest.TestCase):
    """2・3. PS5.1実機での修正後(green)/修正前(負の対照)。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="d2p_nonascii_")
        self.job_json, self.vrm_path = _make_job(self.tmp)
        self.out = os.path.join(self.tmp, "out.txt")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read_out(self):
        with open(self.out, "r", encoding="utf-8-sig") as f:
            return f.read()

    def test_fixed_idiom_roundtrips_nonascii_path(self):
        """修正後: -Encoding UTF8 明示なら日本語+絵文字パスが完全往復する。"""
        cp = _run_ps51(_PS_TEMPLATE.replace("%ENC%", "-Encoding UTF8"),
                       self.job_json, self.out)
        self.assertEqual(cp.returncode, 0,
                         "修正後イディオムが失敗: stderr=%r out=%r" % (
                             cp.stderr[:500], os.path.isfile(self.out) and self._read_out()))
        self.assertEqual(self._read_out(), self.vrm_path,
                         "vrm_pathが往復で一致しない(mojibake残存の疑い)")

    def test_negative_control_old_idiom_fails_on_cp932(self):
        """負の対照: v1.1.2相当(エンコーディング未指定)は同条件で必ず失敗する。
        機構がANSI=cp932誤読なので、ACPが932の環境(日本語Windows既定)でのみ意味を持つ。"""
        if _acp() != 932:
            self.skipTest("ACP=%s: cp932環境でないため負の対照は成立しない" % _acp())
        cp = _run_ps51(_PS_TEMPLATE.replace("%ENC%", ""), self.job_json, self.out)
        out = self._read_out() if os.path.isfile(self.out) else ""
        # 期待: ConvertFrom-Jsonの解析失敗(exit 3)。万一解析だけ通っても
        # パスはmojibakeで原文と一致しないはず(どちらでも「壊れている」ことの証明)
        self.assertTrue(cp.returncode == 3 or out != self.vrm_path,
                        "修正前イディオムが非ASCIIパスで成功してしまった(前提崩れ): "
                        "rc=%s out=%r" % (cp.returncode, out[:300]))
        if cp.returncode == 3:
            self.assertIn("PARSE_ERROR", out)


class TestSourceRegressionGuard(unittest.TestCase):
    """4. ソース回帰ガード: 読取規約(-Encoding UTF8)が外れたら赤。"""

    @staticmethod
    def _lines(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()

    def test_convert_ps1_job_reads_specify_utf8(self):
        hits = [l for l in self._lines(CONVERT_PS1)
                if re.search(r"Get-Content\s+\$Job\b", l)]
        self.assertGreaterEqual(len(hits), 2, "job.json読取箇所が見つからない(構造変更?)")
        for l in hits:
            self.assertIn("-Encoding UTF8", l,
                          "job.json読取に-Encoding UTF8が無い(起票案1の再発): %r" % l)

    def test_convert_ps1_diag_read_specifies_utf8(self):
        hits = [l for l in self._lines(CONVERT_PS1)
                if re.search(r"Get-Content\s+\$diagOut\b", l)]
        self.assertTrue(hits, "_diag_structure.log読取箇所が見つからない(構造変更?)")
        for l in hits:
            self.assertIn("-Encoding UTF8", l,
                          "診断ダンプ読取に-Encoding UTF8が無い(No.20 mojibakeの再発): %r" % l)

    def test_export_ps1_manifest_read_specifies_utf8(self):
        hits = [l for l in self._lines(EXPORT_PS1)
                if re.search(r"Get-Content\s+\$manifestPath\b", l)]
        self.assertTrue(hits, "manifest.json読取箇所が見つからない(構造変更?)")
        for l in hits:
            self.assertIn("-Encoding UTF8", l,
                          "manifest.json読取に-Encoding UTF8が無い(manifest破壊リスク): %r" % l)

    def test_ensure_blender_marker_read_specifies_utf8(self):
        hits = [l for l in self._lines(ENSURE_PS1)
                if re.search(r"Get-Content\s+\$MarkerFile\b", l)]
        self.assertTrue(hits, "マーカー読取箇所が見つからない(構造変更?)")
        for l in hits:
            self.assertIn("-Encoding UTF8", l,
                          "マーカー読取に-Encoding UTF8が無い(規約からの逸脱): %r" % l)


if __name__ == "__main__":
    unittest.main(verbosity=2)
