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
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from harness2 import config
from harness2.benchmarks import localbench as LB
from harness2.core import context
from harness2.core import runmark as RM
from harness2.core.proposer import Proposer
from harness2.core.spec import ChannelSpec


def make_adapter(runs: Path, improver: str = "", **kw) -> LB.LocalBenchAdapter:
    with (
        patch.object(config, "RUNS", runs),
        patch.object(config, "IMPROVER_MODEL", improver),
        patch.object(config, "SOLVER_MODEL_CC", "claude-haiku-5-5"),
    ):
        return LB.LocalBenchAdapter(**kw)


def scratch(case: unittest.TestCase) -> Path:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name)


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
        self.adapter = make_adapter(scratch(self) / "runs")

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

    def test_upstream_guards_refuse_a_planted_rubric_in_a_context_dir(self):
        for planted, body in (
            ("grader/rubric.md", "criteria"),
            (".claude/skills/x/grader/grade.py", "print(1)"),
            ("notes/result.json", '{"passed_count": 12}'),
        ):
            with self.subTest(planted=planted):
                ctx = scratch(self) / "context"
                (ctx / planted).parent.mkdir(parents=True)
                (ctx / planted).write_text(body)
                with self.assertRaises(ValueError):
                    context.assert_no_leak_paths(ctx, self.adapter.spec.leak_globs)
                    context.assert_no_grader_verdicts(ctx)

    def test_source_copied_into_model_context_excludes_graders(self):
        with tempfile.TemporaryDirectory() as tmp:
            for task_id in self.adapter.tasks():
                root = Path(tmp) / task_id
                context.copy_source(self.adapter, task_id, root)
                self.assertFalse(any("grader" in p.parts for p in root.rglob("*")), task_id)


class GuardTests(unittest.TestCase):
    def setUp(self):
        root = scratch(self)
        (root / "suite" / "t1").mkdir(parents=True)
        self.given = root / "suite"
        self.adapter = make_adapter(root / "runs", tasks_root=self.given)
        self.command = self.adapter.floor_hooks["PreToolUse"][0]["hooks"][0]["command"]

    def run_guard(self, command: str, env: dict | None = None) -> tuple[int, str]:
        event = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        base = {k: v for k, v in os.environ.items() if k != LB.GUARD_ENV}
        p = subprocess.run(
            self.command,
            shell=True,
            input=event,
            text=True,
            capture_output=True,
            env={**base, **(self.adapter.floor_env if env is None else env)},
        )
        return p.returncode, p.stderr

    def test_hook_refuses_tool_calls_naming_the_tasks_or_checkers(self):
        blocked = (2, "blocked: that path is outside this task\n")
        for command in (
            f"cat {self.given}/t1/files/x.csv",
            f"ls {self.given.resolve()}",
            "cat ../GRADER/grade.py",
            "find / -path '*/gr?der/*'",
            "ls ~/code/localbench",
            "python3 grade.py .",
            "pytest hidden_tests",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.run_guard(command), blocked)
        self.assertEqual(self.run_guard("python3 scripts/clean.py"), (0, ""))

    def test_hook_refuses_everything_when_its_environment_is_missing(self):
        self.assertEqual(
            self.run_guard("python3 scripts/clean.py", env={}),
            (2, "blocked: that path is outside this task\n"),
        )

    def test_hook_command_names_neither_the_tasks_nor_the_checkers(self):
        self.assertNotIn(str(self.given.resolve()), self.command)
        self.assertNotIn(str(self.given), self.command)
        self.assertNotIn("grader", self.command.lower())

    def test_deny_tokens_cover_both_spellings_of_the_tasks_root(self):
        root = self.given.resolve()
        self.assertEqual(
            self.adapter.floor_env,
            {
                "H2_GUARD_DENY": os.pathsep.join(
                    [str(self.given), str(root), "localbench", "grade.py", "hidden_tests"]
                    + ["/grader", "gr?der"]
                )
            },
        )


class AdapterSetupTests(unittest.TestCase):
    def test_base_tree_is_built_at_construction_and_repaired_whole(self):
        runs = scratch(self) / "runs"
        adapter = make_adapter(runs)
        base = runs / "local" / "base"
        self.assertEqual(adapter.base_harness(), base)
        self.assertEqual((base / "systemprompt.md").read_text(), LB.BASE_SYSTEM_PROMPT)
        (base / "systemprompt.md").write_text("stale\n")
        (base / "guardrails.md").unlink()
        make_adapter(runs)
        self.assertEqual((base / "systemprompt.md").read_text(), LB.BASE_SYSTEM_PROMPT)
        self.assertEqual((base / "guardrails.md").read_text(), "")
        self.assertEqual(sorted(p.name for p in base.parent.iterdir()), ["base"])

    def test_editor_channel_defaults_and_honours_a_bare_improver_id(self):
        runs = scratch(self) / "runs"
        self.assertEqual(
            make_adapter(runs).spec.channels["proposer"],
            ChannelSpec("claude_cli", "claude-opus-5-5"),
        )
        self.assertEqual(
            make_adapter(runs, improver="claude-sonnet-5").spec.channels["selector"],
            ChannelSpec("claude_cli", "claude-sonnet-5"),
        )

    def test_editor_channel_refuses_a_provider_prefixed_improver_id(self):
        with self.assertRaisesRegex(ValueError, "claude_cli channel takes a bare Anthropic id"):
            make_adapter(scratch(self) / "runs", improver="google-vertex/gemini-x")


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch(self)
        task = self.root / "tasks" / "t1"
        (task / "files").mkdir(parents=True)
        (task / "files" / "in.txt").write_text("a\n")
        (task / "task.json").write_text(json.dumps({"domain": "data-cleaning", "timeout": 60}))
        (task / "prompt.md").write_text("Copy in.txt to output/out.txt.\n")
        self.adapter = make_adapter(self.root / "runs", tasks_root=self.root / "tasks")
        self.calls = []

    def fake_rollout(self, install, run_dir, prompt, **kw):
        self.calls.append((prompt, kw["model"], kw["task_files"], kw["hooks"], kw["env"]))
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
        self.assertEqual(self.calls[0][3:], (self.adapter.floor_hooks, self.adapter.floor_env))
        self.assertTrue(RM.is_complete(run_dir, harness_dir=None))
        self.assertEqual(self.adapter.deliverable_files(run_dir), {"output/out.txt": "a\n"})

    def test_a_rollout_without_a_deliverable_stays_unmarked(self):
        def empty(install, run_dir, prompt, **kw):
            (run_dir / "rollout.json").write_text(json.dumps({"subtype": "error_max_turns"}))

        with patch.object(LB.CC, "run_rollout", side_effect=empty):
            with self.assertRaisesRegex(RuntimeError, "no deliverable under output/"):
                self.adapter.execute("t1", None, "ns/t1/base1")
        self.assertIsNone(RM.read_mark(self.adapter.run_dir("ns/t1/base1")))


SECRET = "PLANTED-ANSWER-KEY"

# Both fakes try to read the grader the rollout must never see, and deliver what they got.
PLANTED_READ = textwrap.dedent(
    """
    import os, sys
    if sys.argv[1:] == ["--version"]:
        sys.exit(0)
    os.makedirs("output", exist_ok=True)
    try:
        got = open({grader!r}).read()
    except OSError as e:
        got = "refused errno=%d" % e.errno
    open("output/out.txt", "w").write(got)
    """
)


@unittest.skipUnless(Path(LB.SANDBOX_EXEC).is_file(), "the read boundary is macOS sandbox-exec")
class ReadBoundaryTests(unittest.TestCase):
    """A planted read of a grader fails at the OS, by every route, in every session kind."""

    def setUp(self):
        self.root = scratch(self).resolve()
        task = self.root / "tasks" / "t1"
        (task / "files").mkdir(parents=True)
        (task / "grader").mkdir()
        (task / "files" / "in.txt").write_text("a\n")
        (task / "task.json").write_text(json.dumps({"domain": "data-cleaning", "timeout": 60}))
        (task / "prompt.md").write_text("Copy in.txt to output/out.txt.\n")
        self.grader = task / "grader" / "grade.py"
        self.grader.write_text(f"print({SECRET!r})\n")
        git = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "tasks"], check=True)
        # Rollout workspaces live inside the checkout, as under runs/ in this repo.
        self.ws = self.root / "runs" / "ws"
        self.ws.mkdir(parents=True)
        (self.ws / "mine.txt").write_text("workspace file\n")
        (self.ws / "link").symlink_to(self.root / "tasks")
        self.adapter = make_adapter(self.root / "runs", tasks_root=self.root / "tasks")

    def read(self, argv: list[str], *, sealed: bool) -> subprocess.CompletedProcess:
        prefix = list(self.adapter.floor_runner) if sealed else []
        return subprocess.run(
            prefix + argv, cwd=self.ws, capture_output=True, text=True, timeout=60
        )

    def test_the_tasks_root_and_the_git_object_store_are_sealed(self):
        self.assertEqual(
            LB.sealed_paths(self.root / "tasks"), (self.root / "tasks", self.root / ".git")
        )

    def test_planted_reads_of_a_grader_fail_by_every_route(self):
        routes = {
            "absolute path": ["cat", str(self.grader)],
            "relative path": ["sh", "-c", "cat ../../tasks/t1/grader/grade.py"],
            "symlink": ["cat", "link/t1/grader/grade.py"],
            "git object store": [
                "git",
                "-C",
                str(self.root),
                "show",
                "HEAD:tasks/t1/grader/grade.py",
            ],
            "interpreter": ["python3", "-c", f"print(open({str(self.grader)!r}).read())"],
            "directory listing": ["ls", str(self.grader.parent)],
        }
        for route, argv in routes.items():
            with self.subTest(route=route):
                self.assertIn(
                    SECRET if route != "directory listing" else "grade.py",
                    self.read(argv, sealed=False).stdout,
                )
                p = self.read(argv, sealed=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertNotIn(SECRET, p.stdout)
                self.assertNotIn("grade.py", p.stdout)
        self.assertEqual(self.read(["cat", "mine.txt"], sealed=True).stdout, "workspace file\n")

    def fake_bin(self, name: str) -> Path:
        bindir = self.root.parent / f"{self.root.name}-bin"
        bindir.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, bindir, ignore_errors=True)
        fake = bindir / name
        fake.write_text(f"#!{sys.executable}\n" + PLANTED_READ.format(grader=str(self.grader)))
        fake.chmod(0o755)
        return fake

    def test_a_claude_code_rollout_cannot_read_the_grader(self):
        fake = self.fake_bin("claude")
        with patch.dict(os.environ, {"PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}"}):
            run_dir = self.adapter.execute("t1", None, "ns/t1/base1")
        self.assertEqual(
            self.adapter.deliverable_files(run_dir), {"output/out.txt": "refused errno=1"}
        )

    def test_a_hermes_rollout_cannot_read_the_grader(self):
        fake = self.fake_bin("hermes")
        rollouts = self.root.parent / f"{self.root.name}-rollouts"
        self.addCleanup(shutil.rmtree, rollouts, ignore_errors=True)
        with (
            patch.object(config, "SOLVER_MODEL_HM", "m"),
            patch.object(config, "HERMES_CMD", str(fake)),
            patch.object(config, "HERMES_ROLLOUTS", rollouts),
        ):
            adapter = make_adapter(
                self.root / "runs", tasks_root=self.root / "tasks", substrate="hm"
            )
            run_dir = adapter.execute("t1", None, "ns/t1/base1")
        self.assertEqual(adapter.deliverable_files(run_dir), {"output/out.txt": "refused errno=1"})

    def test_improver_sessions_run_under_the_same_boundary(self):
        prop = Proposer(ChannelSpec("claude_cli", "m"), floor_runner=self.adapter.floor_runner)
        done = subprocess.CompletedProcess([], 0, stdout='{"result": "ok"}', stderr="")
        with patch("harness2.core.proposer.subprocess.run", return_value=done) as run:
            prop._claude_cli(self.ws, "mission", "", 60)
        cmd = run.call_args.args[0]
        self.assertEqual(tuple(cmd[:3]), self.adapter.floor_runner)
        self.assertTrue(cmd[3].endswith("claude"))


if __name__ == "__main__":
    unittest.main()
