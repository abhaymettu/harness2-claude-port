#!/usr/bin/env python3
"""Usage: python3 grade.py <workspace_dir>. Prints one JSON line."""
import ast
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE / "hidden_tests.py"
MARK = "@@RESULT@@"

RUNNER = r"""
import json, sys
sys.dont_write_bytecode = True
workspace, tests_path, names = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, workspace)
results = {}
try:
    ns = {"__name__": "hidden_tests"}
    with open(tests_path, encoding="utf-8") as f:
        exec(compile(f.read(), tests_path, "exec"), ns)
except BaseException:
    ns = None
for name in names:
    try:
        ns[name]()
        results[name] = True
    except BaseException:
        results[name] = False
print("@@RESULT@@" + json.dumps(results))
"""


def test_names():
    tree = ast.parse(TESTS.read_text(encoding="utf-8"))
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]


def run_tests(workspace, names):
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-c", RUNNER, str(workspace), str(TESTS), *names],
            cwd=str(workspace), capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(MARK):
            try:
                return json.loads(line[len(MARK):])
            except ValueError:
                return {}
    return {}


def changes_written(workspace):
    try:
        return len((Path(workspace) / "output" / "CHANGES.md").read_text(encoding="utf-8").strip()) >= 20
    except (OSError, UnicodeDecodeError):
        return False


def main():
    names = test_names()
    workspace = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    ok_by_name = run_tests(workspace, names) if workspace and workspace.is_dir() else {}
    checks = [{"name": n[len("test_"):], "ok": ok_by_name.get(n) is True} for n in names]
    checks.append({"name": "changes_md_written", "ok": bool(workspace) and changes_written(workspace)})
    print(json.dumps({"n_passed": sum(c["ok"] for c in checks), "n_criteria": len(checks), "checks": checks}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"n_passed": 0, "n_criteria": 0, "checks": []}))
