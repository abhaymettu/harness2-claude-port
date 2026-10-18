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

"""localbench: the shipped tasks grade deterministically, graders stay hidden, rollouts resume."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness2 import config
from harness2.benchmarks import localbench as LB
from harness2.core import context
from harness2.core import runmark as RM


def grade(task: Path, workspace: Path) -> dict:
    out = subprocess.run(
        ["python3", "-I", str(task / "grader" / "grade.py"), str(workspace)],
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


class ShippedTasksTests(unittest.TestCase):
    def setUp(self):
        self.adapter = LB.LocalBenchAdapter()

    def test_twelve_tasks_in_three_domains(self):
        domains = [self.adapter.domain_of(t) for t in self.adapter.tasks()]
        self.assertEqual(
            {d: domains.count(d) for d in set(domains)},
            {"data-cleaning": 4, "document-extraction": 4, "repo-bugfix": 4},
        )

    def test_reference_scores_full_and_starting_files_do_not(self):
        for task_id in self.adapter.tasks():
            task = LB.TASKS_ROOT / task_id
            with self.subTest(task=task_id), tempfile.TemporaryDirectory() as tmp:
                ws = Path(tmp) / "ws"
                shutil.copytree(task / "files", ws)
                start = grade(task, ws)
                self.assertLess(start["n_passed"], start["n_criteria"])
                shutil.copytree(task / "grader" / "reference", ws, dirs_exist_ok=True)
                done = grade(task, ws)
                self.assertEqual(done["n_passed"], done["n_criteria"])
                self.assertEqual(done, grade(task, ws))

    def test_prompts_never_name_the_checker(self):
        for task_id in self.adapter.tasks():
            text = self.adapter.task_prompt(task_id).lower()
            for word in ("grader", "rubric", "hidden test", "score"):
                self.assertNotIn(word, text, task_id)

    def test_source_copied_into_model_context_excludes_graders(self):
        with tempfile.TemporaryDirectory() as tmp:
            for task_id in self.adapter.tasks():
                root = Path(tmp) / task_id
                context.copy_source(self.adapter, task_id, root)
                self.assertFalse(any("grader" in p.parts for p in root.rglob("*")), task_id)


class GuardTests(unittest.TestCase):
    def run_guard(self, tool_input: dict) -> int:
        adapter = LB.LocalBenchAdapter()
        argv = ["python3", "-I", "-c", LB._GUARD, str(adapter.tasks_root), "/grader"]
        event = json.dumps({"tool_name": "Bash", "tool_input": tool_input})
        return subprocess.run(argv, input=event, text=True).returncode

    def test_floor_hook_refuses_tool_calls_naming_the_graders(self):
        self.assertEqual(self.run_guard({"command": f"cat {LB.TASKS_ROOT}/x/grader/grade.py"}), 2)
        self.assertEqual(self.run_guard({"command": "find / -path '*/grader/*'"}), 2)
        self.assertEqual(self.run_guard({"command": "python3 scripts/clean.py"}), 0)


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        task = self.root / "tasks" / "t1"
        (task / "files").mkdir(parents=True)
        (task / "files" / "in.txt").write_text("a\n")
        (task / "task.json").write_text(json.dumps({"domain": "data-cleaning", "timeout": 60}))
        (task / "prompt.md").write_text("Copy in.txt to output/out.txt.\n")
        with (
            patch.object(config, "RUNS", self.root / "runs"),
            patch.object(config, "SOLVER_MODEL_CC", "claude-haiku-5-5"),
        ):
            self.adapter = LB.LocalBenchAdapter(tasks_root=self.root / "tasks")
        self.calls = []

    def fake_rollout(self, install, run_dir, prompt, **kw):
        self.calls.append((prompt, kw["model"], kw["task_files"]))
        ws = run_dir / "workspace"
        shutil.copytree(kw["task_files"], ws, dirs_exist_ok=True)
        (ws / "output").mkdir()
        (ws / "output" / "out.txt").write_text((ws / "in.txt").read_text())
        (run_dir / "rollout.json").write_text(json.dumps({"subtype": "success", "cost_usd": 0.01}))
        return {}

    def test_execute_marks_complete_and_resumes_without_rerunning(self):
        with patch.object(LB.CC, "run_rollout", side_effect=self.fake_rollout):
            run_dir = self.adapter.execute("t1", None, "ns/t1/base1")
            again = self.adapter.execute("t1", None, "ns/t1/base1")
        self.assertEqual(run_dir, again)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            self.calls[0][:2], ("Copy in.txt to output/out.txt.\n", "claude-haiku-5-5")
        )
        self.assertTrue(RM.is_complete(run_dir, harness_dir=None))
        self.assertEqual(self.adapter.deliverable_files(run_dir), {"output/out.txt": "a\n"})

    def test_a_rollout_without_a_deliverable_stays_unmarked(self):
        def empty(install, run_dir, prompt, **kw):
            (run_dir / "rollout.json").write_text(json.dumps({"subtype": "error_max_turns"}))

        with patch.object(LB.CC, "run_rollout", side_effect=empty):
            with self.assertRaisesRegex(RuntimeError, "no deliverable under output/"):
                self.adapter.execute("t1", None, "ns/t1/base1")
        self.assertIsNone(RM.read_mark(self.adapter.run_dir("ns/t1/base1")))


if __name__ == "__main__":
    unittest.main()
