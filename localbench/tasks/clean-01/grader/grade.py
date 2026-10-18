#!/usr/bin/env python3
"""Usage: python3 grade.py <workspace_dir>. Prints one JSON line."""
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_csv(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.reader(f) if any(cell.strip() for cell in r)]
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    if not rows:
        return None
    return rows[0], rows[1:]


def run_check(check, header, body, ref):
    kind = check["type"]
    if kind == "parses":
        return True
    if kind == "header":
        return header == ref[0]
    if kind == "row_count":
        return len(body) == len(ref[1])
    if kind == "exact":
        return header == ref[0] and body == ref[1]
    rows = [dict(zip(header, r)) for r in body]
    if kind == "cell":
        hits = [r for r in rows if all(r.get(k) == v for k, v in check["where"].items())]
        return len(hits) == 1 and hits[0].get(check["col"]) == check["value"]
    if kind == "absent":
        if not rows or not all(k in header for k in check["where"]):
            return False
        return not any(all(r.get(k) == v for k, v in check["where"].items()) for r in rows)
    if kind == "column_regex":
        return bool(rows) and all(
            isinstance(r.get(check["col"]), str) and re.fullmatch(check["regex"], r[check["col"]])
            for r in rows
        )
    if kind == "order":
        return [[r.get(c) for c in check["cols"]] for r in rows] == check["values"]
    raise ValueError(kind)


def grade(workspace):
    spec = json.loads((HERE / "checks.json").read_text(encoding="utf-8"))
    checks = spec["checks"]
    results = [False] * len(checks)
    if workspace is not None:
        ref = load_csv(HERE / "reference" / spec["output"])
        got = load_csv(Path(workspace) / spec["output"])
        if got is not None:
            for i, check in enumerate(checks):
                try:
                    results[i] = bool(run_check(check, got[0], got[1], ref))
                except Exception:
                    results[i] = False
    return [{"name": c["name"], "ok": ok} for c, ok in zip(checks, results)]


def main():
    workspace = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        checks = grade(workspace)
    except Exception:
        checks = []
    print(json.dumps({"n_passed": sum(c["ok"] for c in checks), "n_criteria": len(checks), "checks": checks}))


if __name__ == "__main__":
    main()
