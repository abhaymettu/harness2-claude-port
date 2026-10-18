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

"""The pre-commit deny check, run against a throwaway repository."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / ".githooks" / "deny_check.py"


class PreCommitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.deny = self.root / "deny.txt"
        self.deny.write_text("zebra-canary\n")
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "H2_DENY_FILE": str(self.deny),
        }

    def stage(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        subprocess.run(["git", "-C", str(self.repo), "add", "--", rel], check=True)

    def check(self, **env: str) -> tuple[int, str]:
        p = subprocess.run(
            [sys.executable, str(HOOK), "pre-commit"],
            cwd=self.repo,
            env={**self.env, **env},
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stderr

    def test_clean_diff_passes(self):
        self.stage("a.txt", "hello\n")
        self.assertEqual(self.check(), (0, ""))

    def test_an_added_line_that_reads_like_a_header_is_still_scanned(self):
        self.stage("a.txt", "first\n++ zebra-canary\n")
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn(
            "a.txt: added line 2 matches local pattern 'zebra-canary': ++ zebra-canary", err
        )

    def test_a_path_git_would_quote_is_reported_as_written(self):
        self.stage("dir é/b.txt", "zebra-canary\n")
        code, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("dir é/b.txt: added line 1 matches local pattern", err)

    def test_a_missing_deny_file_refuses_the_commit(self):
        self.stage("a.txt", "hello\n")
        code, err = self.check(H2_DENY_FILE=str(self.root / "absent.txt"))
        self.assertEqual(code, 1)
        self.assertIn("H2_DENY_FILE names a missing file", err)
        self.assertIn("commit refused", err)


if __name__ == "__main__":
    unittest.main()
