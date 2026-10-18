#!/usr/bin/env python3
"""Refuse a commit that would make this history unpublishable.

    deny_check.py pre-commit          scan the staged diff and the author identity
    deny_check.py commit-msg <file>   scan the commit message, refuse attribution trailers

Generic patterns live in this file. Patterns that name a maintainer's private machines or
accounts stay out of the repository: one regex per line in the file named by env
`H2_DENY_FILE`, or in `.git/deny-patterns.local` when that is unset. A line `allow: <regex>`
there removes its matches before scanning (for example a public author identity that would
otherwise match a private name).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SELF = ".githooks/deny_check.py"

CONTENT = {
    "Anthropic API key": r"sk-ant-[A-Za-z0-9_\-]{8,}",
    "OpenAI-style API key": r"\bsk-[A-Za-z0-9]{32,}",
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "Google API key": r"\bAIza[0-9A-Za-z_\-]{35}\b",
    "Slack token": r"\bxox[abposr]-[A-Za-z0-9\-]{10,}",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "home-directory path": r"(?:/Users/|/home/)[A-Za-z0-9_.\-]+/|[A-Za-z]:\\Users\\",
}

FILENAMES = {
    "dotenv file": r"(?:^|/)\.env(?:\.(?!example$)[^/]+)?$",
    "key file": r"(?:^|/)(?:id_rsa|id_ed25519|id_ecdsa)(?:\.pub)?$|\.pem$|\.p12$",
}

TRAILERS = r"(?im)^\s*(?:Claude-Session|Co-Authored-By|Generated with|Signed-off-by: Claude)\b"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, errors="replace"
    ).stdout


def _local() -> tuple[dict[str, str], list[re.Pattern]]:
    path = Path(
        os.environ.get("H2_DENY_FILE")
        or Path(_git("rev-parse", "--git-dir").strip()) / "deny-patterns.local"
    ).expanduser()
    deny: dict[str, str] = {}
    allow: list[re.Pattern] = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("allow:"):
                allow.append(re.compile(line[len("allow:") :].strip(), re.I))
            else:
                deny[f"local pattern {line!r}"] = line
    return deny, allow


def _hits(text: str, patterns: dict[str, str], allow: list[re.Pattern]) -> list[str]:
    for rx in allow:
        text = rx.sub("", text)
    return [label for label, rx in patterns.items() if re.search(rx, text, re.I)]


def _staged_additions() -> dict[str, list[str]]:
    """path -> added lines, for every added/copied/modified/renamed path in the index."""
    diff = _git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR")
    out: dict[str, list[str]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            if path is not None:
                out.setdefault(path, [])
        elif path is not None and line.startswith("+"):
            out[path].append(line[1:])
    for name in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines():
        out.setdefault(name, [])
    return out


def pre_commit() -> list[str]:
    local, allow = _local()
    patterns = {**CONTENT, **local}
    problems = []
    for path, lines in _staged_additions().items():
        for label in _hits(path, {**FILENAMES, **local}, allow):
            problems.append(f"{path}: file name matches {label}")
        if path == SELF:
            continue
        for n, line in enumerate(lines, 1):
            for label in _hits(line, patterns, allow):
                problems.append(f"{path}: added line {n} matches {label}: {line.strip()[:120]}")
    ident = _git("var", "GIT_AUTHOR_IDENT").rsplit(">", 1)[0] + ">"
    for label in _hits(ident, local, allow):
        problems.append(f"author identity matches {label}; set a public user.email first")
    return problems


def commit_msg(path: str) -> list[str]:
    local, allow = _local()
    text = "\n".join(
        ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if not ln.startswith("#")
    )
    problems = [f"message matches {label}" for label in _hits(text, {**CONTENT, **local}, allow)]
    if re.search(TRAILERS, text):
        problems.append("message carries an attribution trailer; this history takes none")
    return problems


def main(argv: list[str]) -> int:
    if argv[:1] == ["pre-commit"]:
        problems = pre_commit()
    elif argv[:1] == ["commit-msg"] and len(argv) == 2:
        problems = commit_msg(argv[1])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for p in problems:
        print(f"deny_check: {p}", file=sys.stderr)
    if problems:
        print(f"deny_check: commit refused ({len(problems)} problem(s))", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
