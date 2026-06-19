"""Real in-place static scanners — genuine computation, not magic numbers.

These run over actual file content the data owner holds and return ONLY counts /
findings by severity (file:line locations, never the source text). Used by the
code_scan capability so the deliverable is a real triaged fix-plan computed from
a real scan — the source repository never leaves the owner.

Pure: stdlib only (re), no band import.
"""

from __future__ import annotations

import re
from pathlib import Path

# (severity, label, compiled pattern). Conservative, well-known leak/risk classes.
_RULES = [
    ("critical", "secret:aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("critical", "secret:private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    # match suffixed names too (db_password=...), so 'db_password = "..."' is caught.
    ("critical", "secret:hardcoded_password", re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{4,}['\"]")),
    ("high", "secret:api_token", re.compile(r"(?i)\b(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")),
    ("high", "injection:eval_exec", re.compile(r"\b(eval|exec)\s*\(")),
    ("high", "injection:shell_true", re.compile(r"shell\s*=\s*True")),
    ("medium", "crypto:weak_hash", re.compile(r"(?i)\b(md5|sha1)\s*\(")),
    ("medium", "tls:verify_disabled", re.compile(r"(?i)verify\s*=\s*False")),
    ("low", "debug:left_on", re.compile(r"(?i)\bdebug\s*=\s*True")),
]


def _strip_comment(line: str) -> str:
    """Drop an inline comment so we don't flag findings that live in comments.

    Heuristic: cut at the first '#' or '//' that is NOT inside a quoted string.
    Good enough to avoid the comment false-positives a line scanner otherwise hits.
    """
    in_s = None
    for i, ch in enumerate(line):
        if in_s:
            if ch == in_s:
                in_s = None
            continue
        if ch in "'\"":
            in_s = ch
        elif ch == "#":
            return line[:i]
        elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return line[:i]
    return line


def scan_text(text: str) -> list[dict]:
    """Return findings for one document: [{severity, rule, line}] — locations only.

    Inline comments are stripped first so a pattern mentioned in a comment is not
    counted as a real finding (only code matches).
    """
    findings: list[dict] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        for severity, rule, rx in _RULES:
            if rx.search(line):
                findings.append({"severity": severity, "rule": rule, "line": lineno})
    return findings


def scan_repo(root: str | Path, *, exts=(".py", ".js", ".ts", ".env", ".yaml", ".yml", ".txt", ".cfg")) -> dict:
    """Scan every matching file under *root* in place. Returns severity counts +
    finding locations (file:line:rule). The file CONTENTS are never returned."""
    root = Path(root)
    by_sev: dict[str, int] = {}
    locations: list[str] = []
    files_scanned = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        files_scanned += 1
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for f in scan_text(text):
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
            locations.append(f"{p.relative_to(root)}:{f['line']}:{f['rule']}")
    return {
        "files_scanned": files_scanned,
        "findings_by_severity": by_sev,
        "total_findings": sum(by_sev.values()),
        "locations": locations,         # file:line:rule — never source text
        "source_exported": False,
    }
