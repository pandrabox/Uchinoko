# -*- coding: utf-8 -*-
"""dev#7: pipeline\\cli\\convert.ps1 の Format-DiagPath(旧Mask-Path)のユニットテスト。

背景: 実ユーザー報告4AL4M4GTで、convert.ps1の旧`Mask-Path`(%USERPROFILE%の完全一致
プレフィックスしか扱えなかった)が、非%USERPROFILE%ドライブの絶対パスを無加工で
診断ログへ出力していた。三段構成(work\\issue_zero\\i7\\NOTES.md)の「Mask-Path引退+
各所factify」段に対応する試験。

convert.ps1自体は`-Job`必須の一気通貫スクリプトで単体実行できないため、PowerShellの
AST(Abstract Syntax Tree)パーサでGet-SafeValue/Get-PathFacts/Format-DiagPathの
関数定義だけを抽出し、新しいpwshプロセス内でその関数だけを評価してテストする
(convert.ps1本体は一切実行しない。将来3関数のいずれかが削除・改名されたら
このテスト自身がその場で失敗する=関数の実在確認も兼ねる)。

フィクスチャは全て架空の値(実在の個人情報は使わない)。
"""
import os
import subprocess
import sys
import textwrap
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
CONVERT_PS1 = os.path.join(_REPO, "pipeline", "cli", "convert.ps1")

FAKE_USER = "SampleTaro_Zzyzx9912"

_EXTRACT_HEADER = r"""
$ConvertPs1Path = "%s"
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ConvertPs1Path, [ref]$null, [ref]$null)
$names = @('Get-SafeValue', 'Get-PathFacts', 'Format-DiagPath')
$funcAsts = $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $n.Name}, $true)
if (@($funcAsts).Count -ne $names.Count) {
    Write-Output "EXTRACT_FAIL: found $(@($funcAsts).Count) of $($names.Count) expected functions"
    exit 1
}
$combined = ($funcAsts | ForEach-Object { $_.Extent.Text }) -join "`n`n"
Invoke-Expression $combined
""" % CONVERT_PS1.replace("\\", "\\\\")


def _run_ps(body):
    """抽出ヘッダ + 呼び出し元が渡す本文をpwshで実行し、標準出力を返す。"""
    script = _EXTRACT_HEADER + "\n" + body
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    return proc


class TestFormatDiagPath(unittest.TestCase):
    def test_functions_are_extractable(self):
        """3関数が抽出でき、実行時エラーにならないこと(関数の実在確認も兼ねる)。"""
        proc = _run_ps('Write-Output "OK"')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("OK", proc.stdout)
        self.assertNotIn("EXTRACT_FAIL", proc.stdout)

    def test_userprofile_path_is_tokenized(self):
        """正の対照(無退行): %USERPROFILE%配下は従来どおりトークン化される。"""
        body = textwrap.dedent(r"""
            $up = [Environment]::GetFolderPath("UserProfile")
            $p = Join-Path $up "Downloads\avatar.vrm"
            $r = Format-DiagPath $p
            Write-Output "RESULT_BEGIN"
            Write-Output $r
            Write-Output "RESULT_END"
        """)
        proc = _run_ps(body)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = proc.stdout.split("RESULT_BEGIN")[1].split("RESULT_END")[0].strip()
        self.assertTrue(result.startswith("%USERPROFILE%"), result)
        self.assertIn("avatar.vrm", result)

    def test_core_case_non_userprofile_drive_is_masked(self):
        """核心ケース(dev#7、4AL4M4GT実証): 非%USERPROFILE%ドライブの絶対パスは、
        生パス・架空ユーザー名とも一切残らないこと(旧Mask-Pathは素通りしていた)。"""
        fake_path = r"D:\Users\%s\UnityProjects\MyAvatarProject\Assets\avatar.prefab" % FAKE_USER
        body = textwrap.dedent(r"""
            $r = Format-DiagPath "%s"
            Write-Output "RESULT_BEGIN"
            Write-Output $r
            Write-Output "RESULT_END"
        """) % fake_path
        proc = _run_ps(body)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = proc.stdout.split("RESULT_BEGIN")[1].split("RESULT_END")[0].strip()
        self.assertNotIn(FAKE_USER, result)
        self.assertNotIn(fake_path, result)
        # 診断可用性: ファイル名(拡張子含む)は伏字化後も残ること
        self.assertIn("avatar.prefab", result)

    def test_unc_path_is_masked(self):
        fake_path = r"\\BUILDSERVER\share\%s\SteamLibrary\Palworld\Pal-Windows.pak" % FAKE_USER
        body = textwrap.dedent(r"""
            $r = Format-DiagPath "%s"
            Write-Output "RESULT_BEGIN"
            Write-Output $r
            Write-Output "RESULT_END"
        """) % fake_path
        proc = _run_ps(body)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = proc.stdout.split("RESULT_BEGIN")[1].split("RESULT_END")[0].strip()
        self.assertNotIn(FAKE_USER, result)
        self.assertNotIn(fake_path, result)

    def test_empty_and_null_do_not_throw(self):
        body = textwrap.dedent(r"""
            $r1 = Format-DiagPath ""
            $r2 = Format-DiagPath $null
            Write-Output "RESULT_BEGIN"
            Write-Output "r1=[$r1]"
            Write-Output "r2=[$r2]"
            Write-Output "RESULT_END"
        """)
        proc = _run_ps(body)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("r1=[]", proc.stdout)
        self.assertIn("r2=[]", proc.stdout)

    def test_mask_path_function_is_retired(self):
        """三段構成の第1段(Mask-Path引退)の確認: convert.ps1にMask-Path関数の
        定義がもう存在しないこと(呼び出し側は全てFormat-DiagPathへ移行済み)。"""
        with open(CONVERT_PS1, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("function Mask-Path", src)


if __name__ == "__main__":
    unittest.main()
