"""dev#532 WP-B1: Python-native PE signature classifier.

Successor to the one-off `work\\wp532\\proto\\check_signatures.ps1` prototype
(dev#532 realizability study), promoted to a permanent repo-tracked gate.

Walks a payload directory, finds every *.exe/*.dll/*.pyd, and asks Windows
(Get-AuthenticodeSignature, via a single batched PowerShell call) whether each
one carries a valid Authenticode signature. Classifies each file as:

  SIGNED    - Authenticode Status == "Valid" (third-party or Microsoft signed)
  UNSIGNED  - anything else (NotSigned / HashMismatch / UnknownError / ...)

The gate (GATE=PASS/FAIL) only cares about one thing: no *self-made* PE
(matched by filename against --self-made-names, default "Uchinoko.exe" /
"DiveToPalworld.exe" - the historical WinForms exe names) may be present
unsigned. Third-party unsigned PEs (e.g. pyooz's ooz.pyd, a known accepted
residual risk per work\\wp532\\PROPOSAL.md SS5) are reported but do not fail
the gate by themselves.

Usage:
    python packaging\\check_signatures.py --payload-dir <dir> --report <path>
        [--self-made-names "Uchinoko.exe,DiveToPalworld.exe"]

Exit code: 0 on GATE=PASS, 1 on GATE=FAIL.

Also importable: `classify(payload_dir, self_made_names)` returns
`(rows: list[SignatureRow], gate_pass: bool)` for use from build.py or tests
without shelling out twice.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_SELF_MADE_NAMES: tuple[str, ...] = ("Uchinoko.exe", "DiveToPalworld.exe")
PE_EXTENSIONS: tuple[str, ...] = (".exe", ".dll", ".pyd")


@dataclass
class SignatureRow:
    rel_path: str
    size_bytes: int
    status: str
    signed: bool
    subject: str
    self_made_name_match: bool


def find_pe_files(payload_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in payload_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in PE_EXTENSIONS
    )


def _powershell_signature_batch(paths: Sequence[Path]) -> dict[str, dict]:
    """Query Get-AuthenticodeSignature for many files in a single PowerShell call.

    Paths are fed via stdin (one per line) rather than as command-line
    arguments to sidestep the ~8k char command-line length limit when a
    payload has hundreds of PE files.
    """
    if not paths:
        return {}
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$paths = [Console]::In.ReadToEnd() -split \"`n\" | "
        "  Where-Object { $_.Trim() -ne '' }; "
        "$rows = foreach ($p in $paths) { "
        "  $p = $p.Trim(); "
        "  try { $sig = Get-AuthenticodeSignature -LiteralPath $p } "
        "  catch { $sig = $null }; "
        "  $status = if ($sig) { $sig.Status.ToString() } else { 'UnknownError' }; "
        "  $subject = if ($sig -and $sig.SignerCertificate) { "
        "    $sig.SignerCertificate.Subject } else { '' }; "
        "  [PSCustomObject]@{ Path = $p; Status = $status; Subject = $subject } "
        "}; "
        "if ($null -eq $rows) { $rows = @() }; "
        "ConvertTo-Json -InputObject @($rows) -Depth 3"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        input="\n".join(str(p) for p in paths),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    raw = proc.stdout.strip()
    if not raw or raw == "null":
        return {}
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return {row["Path"]: row for row in data}


def classify(
    payload_dir: Path,
    self_made_names: Iterable[str] = DEFAULT_SELF_MADE_NAMES,
) -> tuple[list[SignatureRow], bool]:
    self_made_names = tuple(self_made_names)
    payload_dir = payload_dir.resolve()
    files = find_pe_files(payload_dir)
    sigs = _powershell_signature_batch(files)
    rows: list[SignatureRow] = []
    self_made_unsigned = 0
    for f in files:
        info = sigs.get(str(f), {})
        status = info.get("Status", "UnknownError")
        subject = info.get("Subject", "") or ""
        signed = status == "Valid"
        is_self_made = f.name in self_made_names
        if is_self_made and not signed:
            self_made_unsigned += 1
        rows.append(
            SignatureRow(
                rel_path=str(f.relative_to(payload_dir)),
                size_bytes=f.stat().st_size,
                status=status,
                signed=signed,
                subject=subject,
                self_made_name_match=is_self_made,
            )
        )
    gate_pass = self_made_unsigned == 0
    return rows, gate_pass


def write_report(
    rows: list[SignatureRow],
    report_path: Path,
    self_made_names: Iterable[str] = DEFAULT_SELF_MADE_NAMES,
) -> bool:
    self_made_names = tuple(self_made_names)
    self_made_unsigned = sum(1 for r in rows if r.self_made_name_match and not r.signed)
    self_made_present = sum(1 for r in rows if r.self_made_name_match)
    third_party_unsigned = [r for r in rows if not r.signed and not r.self_made_name_match]
    gate_pass = self_made_unsigned == 0

    lines: list[str] = []
    lines.append(f"{'RelPath':<60} {'SizeBytes':>10} {'Status':<14} {'Signed':<7} Subject")
    for r in sorted(rows, key=lambda r: r.rel_path):
        lines.append(
            f"{r.rel_path:<60} {r.size_bytes:>10} {r.status:<14} {str(r.signed):<7} {r.subject}"
        )
    lines.append("")
    lines.append(f"TOTAL_PE_FILES={len(rows)}")
    lines.append(f"SELF_MADE_NAMES={','.join(self_made_names)}")
    lines.append(f"SELF_MADE_PE_COUNT={self_made_present}")
    lines.append(f"SELF_MADE_NAME_MATCHES_UNSIGNED={self_made_unsigned}")
    lines.append(f"THIRD_PARTY_UNSIGNED_COUNT={len(third_party_unsigned)}")
    for u in third_party_unsigned:
        lines.append(f"  THIRD_PARTY_UNSIGNED: {u.rel_path}")
    if gate_pass:
        lines.append("GATE=PASS (no self-made PE by name found unsigned)")
    else:
        lines.append("GATE=FAIL (self-made PE present and unsigned)")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return gate_pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--payload-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--self-made-names",
        default=",".join(DEFAULT_SELF_MADE_NAMES),
        help="Comma-separated filenames treated as our own build output.",
    )
    args = parser.parse_args(argv)
    self_made_names = tuple(n.strip() for n in args.self_made_names.split(",") if n.strip())

    if not args.payload_dir.is_dir():
        print(f"ERROR: payload dir not found: {args.payload_dir}", file=sys.stderr)
        return 2

    rows, gate_pass = classify(args.payload_dir, self_made_names)
    write_report(rows, args.report, self_made_names)
    print(f"TOTAL_PE_FILES={len(rows)}")
    print("GATE=PASS" if gate_pass else "GATE=FAIL")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
