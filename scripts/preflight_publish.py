#!/usr/bin/env python3
# Copyright 2026 The harness2-ports Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Check that this repository's whole history can be published, before it is.

    H2_DENY_FILE=<private list> python3 scripts/preflight_publish.py [--repo PATH]

Scans what a push would publish: every blob reachable from any ref (`git rev-list --objects
--all`, so a file added and later deleted still counts), every commit message, and every
author and committer line. Checks, each printed as PASS or FAIL with what it found:

    secrets       gitleaks over the whole history
    private       the generic patterns of .githooks/deny_check.py plus the private list, over
                  blobs, paths, messages and identities
    footers       no attribution trailer in any message
    hermes        no Hermes home file (config, SOUL.md, .env, state database, sessions,
                  memories) outside tests/fixtures/, and no SQLite database anywhere
    attribution   LICENSE is the upstream Apache-2.0 text, NOTICE names the upstream, commit 1
                  is the import, and every changed upstream file says so and is in UPSTREAM.md
    em-dashes     none in Markdown or NOTICE text we wrote, nor in any commit message
                  (tests/fixtures/ holds recorded tool output, quoted verbatim, so it is skipped)

The private list is one regex per line, `allow: <regex>` lines remove their matches first. It
must live outside the repository, so publishing the scanner never publishes the names it scans
for. Exit 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT_SUBJECT = "Import Harness² from google-research/harness2 at 1cfe254"
NOTICE_MUST_SAY = (
    "google-research/harness2",
    "1cfe254",
    "Google LLC",
    "not an officially supported Google product",
)
MODIFIED_MARK = "harness2-ports Authors"
COMMIT_ONE_OURS = {"NOTICE", "UPSTREAM.md"}
FIXTURES = "tests/fixtures/"
HERMES_HOME_FILES = re.compile(
    r"(?:^|/)(?:config\.yaml|SOUL\.md|\.env|auth\.json|state\.db(?:-wal|-shm)?|[^/]+\.(?:db|sqlite3?))$"
    r"|(?:^|/)(?:sessions|memories)/"
)
SQLITE_MAGIC = b"SQLite format 3\x00"
EM_DASH = "—"


def git(repo: Path, *args: str, binary: bool = False, stdin: bytes | None = None):
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotePath=false", *args],
        input=stdin,
        check=True,
        capture_output=True,
    ).stdout
    return out if binary else out.decode("utf-8", errors="replace")


def load_hook_patterns(repo: Path):
    spec = importlib.util.spec_from_file_location(
        "deny_check", repo / ".githooks" / "deny_check.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def private_list(repo: Path) -> tuple[dict[str, str], list[re.Pattern]]:
    name = os.environ.get("H2_DENY_FILE")
    if not name:
        sys.exit("preflight: set H2_DENY_FILE to the private deny list (kept outside the repo)")
    path = Path(name).expanduser().resolve()
    if not path.is_file():
        sys.exit(f"preflight: H2_DENY_FILE names a missing file ({path})")
    if path.is_relative_to(repo.resolve()):
        sys.exit("preflight: the private deny list must live outside the repository")
    deny, allow = {}, []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("allow:"):
            allow.append(re.compile(line[len("allow:") :].strip(), re.I))
        else:
            deny[f"private pattern {len(deny) + 1}"] = line
    return deny, allow


def history_blobs(repo: Path) -> dict[str, set[str]]:
    """blob sha -> every path it appears under, across all refs."""
    paths: dict[str, set[str]] = {}
    for line in git(repo, "rev-list", "--objects", "--all").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            paths.setdefault(sha, set()).add(path)
    kinds = git(
        repo,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        stdin="\n".join(paths).encode(),
    )
    blobs = {ln.split()[0] for ln in kinds.splitlines() if ln.endswith(" blob")}
    return {sha: p for sha, p in paths.items() if sha in blobs}


def read_blobs(repo: Path, shas: list[str]) -> dict[str, bytes]:
    raw = git(repo, "cat-file", "--batch", binary=True, stdin="\n".join(shas).encode() + b"\n")
    out, i = {}, 0
    for sha in shas:
        end = raw.index(b"\n", i)
        _, _, size = raw[i:end].decode().split()
        start = end + 1
        out[sha] = raw[start : start + int(size)]
        i = start + int(size) + 1
    return out


def commits(repo: Path) -> list[dict[str, str]]:
    fmt = "%H%x1f%an <%ae>%x1f%cn <%ce>%x1f%P%x1f%B%x1e"
    rows = []
    for rec in git(repo, "log", "--all", f"--format={fmt}").split("\x1e"):
        if rec.strip():
            sha, author, committer, parents, body = rec.strip("\n").split("\x1f")
            rows.append(
                dict(sha=sha, author=author, committer=committer, parents=parents, body=body)
            )
    return rows


class Report:
    def __init__(self):
        self.results: list[tuple[str, bool, str, list[str]]] = []

    def add(self, name: str, problems: list[str], summary: str) -> None:
        self.results.append((name, not problems, summary, problems))

    def print(self) -> bool:
        for name, ok, summary, problems in self.results:
            print(f"{'PASS' if ok else 'FAIL'}  {name:<12} {summary}")
            for p in problems[:50]:
                print(f"        {p}")
            if len(problems) > 50:
                print(f"        ... {len(problems) - 50} more")
        return all(ok for _, ok, _, _ in self.results)


def check_secrets(repo: Path, report: Report) -> None:
    exe = shutil.which("gitleaks")
    if not exe:
        report.add("secrets", ["gitleaks is not installed"], "not run")
        return
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "leaks.json"
        p = subprocess.run(
            [exe, "detect", "--source", str(repo), "--log-opts=--all", "--no-banner", "--redact"]
            + ["--report-format", "json", "--report-path", str(out), "--exit-code", "3"],
            capture_output=True,
            text=True,
        )
        leaks = json.loads(out.read_text() or "[]") if out.is_file() else []
    scanned = re.search(r"(\d+) commits scanned", p.stdout + p.stderr)
    problems = [f"{x.get('RuleID')} in {x.get('File')} at {x.get('Commit', '')[:8]}" for x in leaks]
    if p.returncode not in (0, 3):
        problems.append(f"gitleaks exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}")
    n = scanned.group(1) if scanned else "?"
    report.add("secrets", problems, f"gitleaks: {n} commits scanned, {len(leaks)} leak(s)")


def check_private(repo, blobs, bodies, history, hook, deny, allow, report) -> None:
    content = {**hook.CONTENT, **deny}
    names = {**hook.FILENAMES, **deny}
    problems = []
    hook_self = {sha for sha, ps in blobs.items() if hook.SELF in ps}
    for sha, ps in sorted(blobs.items()):
        for path in sorted(ps):
            problems += [f"path {path}: {label}" for label in hook._hits(path, names, allow)]
        if sha in hook_self:
            continue
        text = bodies[sha].decode("utf-8", errors="replace")
        for label in hook._hits(text, content, allow):
            n = next(
                i
                for i, ln in enumerate(text.splitlines(), 1)
                if hook._hits(ln, {label: content[label]}, allow)
            )
            problems.append(f"blob {sha[:8]} ({sorted(ps)[0]}) line {n}: {label}")
    for c in history:
        for field in ("author", "committer"):
            problems += [
                f"commit {c['sha'][:8]} {field}: {label}"
                for label in hook._hits(c[field], deny, allow)
            ]
        problems += [
            f"commit {c['sha'][:8]} message: {label}"
            for label in hook._hits(c["body"], content, allow)
        ]
    report.add(
        "private",
        problems,
        f"{len(blobs)} blobs, {sum(len(p) for p in blobs.values())} paths, {len(history)} messages "
        f"and identities; {len(hook.CONTENT)} generic + {len(deny)} private patterns",
    )


def check_footers(history, hook, report) -> None:
    problems = [f"commit {c['sha'][:8]}" for c in history if re.search(hook.TRAILERS, c["body"])]
    report.add("footers", problems, f"{len(history)} messages, {len(problems)} with a trailer")


def check_hermes(blobs, bodies, report) -> None:
    problems, fixtures = [], set()
    for sha, ps in blobs.items():
        for path in ps:
            if HERMES_HOME_FILES.search(path):
                (fixtures.add(path) if path.startswith(FIXTURES) else problems.append(path))
        if bodies[sha].startswith(SQLITE_MAGIC):
            problems.append(f"SQLite database in history: {sorted(ps)[0]}")
    report.add(
        "hermes",
        sorted(problems),
        f"{len(problems)} Hermes home file(s) outside {FIXTURES}, {len(fixtures)} inside "
        f"(recorded throwaway-home rollouts); no SQLite blob",
    )


def check_attribution(repo, history, report) -> None:
    problems = []
    roots = [c for c in history if not c["parents"]]
    if len(roots) != 1 or not roots[0]["body"].startswith(ROOT_SUBJECT):
        problems.append(f"want one root commit '{ROOT_SUBJECT}...', got {len(roots)}")
    first = roots[0]["sha"] if roots else "HEAD"
    license_now = git(repo, "show", "HEAD:LICENSE")
    if license_now != git(repo, "show", f"{first}:LICENSE") or not re.search(
        r"Apache License\s+Version 2\.0", license_now
    ):
        problems.append("LICENSE is not the upstream Apache-2.0 text")
    notice = git(repo, "show", "HEAD:NOTICE")
    problems += [f"NOTICE does not say {s!r}" for s in NOTICE_MUST_SAY if s not in notice]
    upstream_md = git(repo, "show", "HEAD:UPSTREAM.md")
    changed = git(repo, "diff", "--name-status", "--no-renames", first, "HEAD").splitlines()
    n_mod = 0
    for line in changed:
        status, path = line.split("\t", 1)
        if status == "A" or path in COMMIT_ONE_OURS:
            continue
        n_mod += 1
        if f"`{path}`" not in upstream_md:
            problems.append(f"{path}: changed upstream file not listed in UPSTREAM.md")
        if status == "M" and MODIFIED_MARK not in git(repo, "show", f"HEAD:{path}"):
            problems.append(f"{path}: changed upstream file without a 'Modified by' line")
    report.add(
        "attribution",
        problems,
        f"root commit is the import; LICENSE unchanged; NOTICE complete; {n_mod} changed "
        f"upstream file(s), each marked and listed",
    )


def authored_markdown_lines(repo: Path, first: str) -> dict[str, list[str]]:
    """Lines we wrote in Markdown and NOTICE: commit 1's own files whole, then every added line."""
    out = {p: git(repo, "show", f"HEAD:{p}").splitlines() for p in COMMIT_ONE_OURS}
    path = None
    for line in git(repo, "diff", "-U0", "--no-color", "--no-renames", first, "HEAD").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif (
            path
            and line.startswith("+")
            and PurePosixPath(path).suffix == ".md"
            and not path.startswith(FIXTURES)
        ):
            out.setdefault(path, []).append(line[1:])
    return out


def check_em_dashes(repo, history, report) -> None:
    roots = [c["sha"] for c in history if not c["parents"]]
    problems = []
    lines = authored_markdown_lines(repo, roots[0])
    for path, body in sorted(lines.items()):
        problems += [f"{path}: {ln.strip()[:100]}" for ln in body if EM_DASH in ln]
    problems += [f"commit {c['sha'][:8]} message" for c in history if EM_DASH in c["body"]]
    n = sum(len(v) for v in lines.values())
    report.add(
        "em-dashes", problems, f"{n} authored Markdown/NOTICE lines, {len(history)} messages"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    hook = load_hook_patterns(repo)
    deny, allow = private_list(repo)
    blobs = history_blobs(repo)
    bodies = read_blobs(repo, sorted(blobs))
    history = commits(repo)
    refs = git(repo, "for-each-ref", "--format=%(refname) %(objectname:short)").split("\n")
    print(f"preflight {repo.name}: HEAD {git(repo, 'rev-parse', 'HEAD').strip()}")
    print(f"refs: {', '.join(r for r in refs if r)}")
    report = Report()
    check_secrets(repo, report)
    check_private(repo, blobs, bodies, history, hook, deny, allow, report)
    check_footers(history, hook, report)
    check_hermes(blobs, bodies, report)
    check_attribution(repo, history, report)
    check_em_dashes(repo, history, report)
    ok = report.print()
    print("preflight: clean" if ok else "preflight: NOT clean, do not publish")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
