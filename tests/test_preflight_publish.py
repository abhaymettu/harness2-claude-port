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

"""scripts/preflight_publish.py: each check fails on a planted problem, even one deleted later."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "preflight_publish.py"
PRIVATE = "planted" + "-private-name"


@unittest.skipUnless(shutil.which("gitleaks"), "gitleaks runs the secrets check")
class PreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.clone = tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(REPO), str(self.clone)], check=True)
        self.deny = tmp / "deny.txt"
        self.deny.write_text(f"{PRIVATE}\n")

    def git(self, *args: str, msg: str | None = None) -> None:
        ident = [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.org",
            "-c",
            "core.hooksPath=/dev/null",
        ]
        cmd = ["git", "-C", str(self.clone), *ident, *args]
        subprocess.run(cmd + (["-m", msg] if msg else []), check=True, capture_output=True)

    def commit(self, files: dict[str, bytes | None], msg: str = "Change a file") -> None:
        for rel, body in files.items():
            path = self.clone / rel
            if body is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
        self.git("add", "-A")
        self.git("commit", "-q", msg=msg)

    def preflight(self) -> tuple[int, dict[str, str]]:
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.clone)],
            capture_output=True,
            text=True,
            env={**os.environ, "H2_DENY_FILE": str(self.deny)},
        )
        status = {}
        for line in p.stdout.splitlines():
            word, _, rest = line.partition("  ")
            if word in ("PASS", "FAIL"):
                status[rest.split()[0]] = word
        return p.returncode, status

    def test_a_clean_clone_passes_every_check(self):
        rc, status = self.preflight()
        self.assertEqual(
            status,
            {
                "secrets": "PASS",
                "private": "PASS",
                "footers": "PASS",
                "hermes": "PASS",
                "attribution": "PASS",
                "em-dashes": "PASS",
            },
        )
        self.assertEqual(rc, 0)

    def test_problems_deleted_from_the_tree_still_fail(self):
        token = "gh" + "p_" + "Zq8RkT2mWv5Xy7Ab3Cd9Ef1Gh4Jk6Lm0Np2Q"
        self.commit({"notes.txt": f"token = {token}\nowner {PRIVATE}\n".encode()})
        self.commit({"notes.txt": None}, msg="Remove notes")
        rc, status = self.preflight()
        self.assertEqual((status["secrets"], status["private"]), ("FAIL", "FAIL"))
        self.assertEqual(rc, 1)

    def test_trailers_hermes_files_attribution_and_em_dashes_fail(self):
        cases = {
            "footers": ({"a.txt": b"a\n"}, "Add a\n\nCo-Authored-By: someone <x@example.org>"),
            "hermes": ({"home/state.db": b"SQLite format 3\x00rest"}, "Add a database"),
            "attribution": ({"harness2/demo.py": b"# rewritten without a mark\n"}, "Rewrite"),
            "em-dashes": ({"docs/NEW.md": "A note — with a dash.\n".encode()}, "Add a doc"),
        }
        for check, (files, msg) in cases.items():
            with self.subTest(check=check):
                self.setUp()
                self.commit(files, msg=msg)
                rc, status = self.preflight()
                self.assertEqual(status[check], "FAIL")
                self.assertEqual([k for k, v in status.items() if v == "FAIL"], [check])
                self.assertEqual(rc, 1)

    def test_a_deny_list_inside_the_repository_is_refused(self):
        inside = self.clone / "deny.txt"
        inside.write_text(f"{PRIVATE}\n")
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.clone)],
            capture_output=True,
            text=True,
            env={**os.environ, "H2_DENY_FILE": str(inside)},
        )
        self.assertEqual(p.returncode, 1)
        self.assertIn("must live outside the repository", p.stderr)


if __name__ == "__main__":
    unittest.main()
