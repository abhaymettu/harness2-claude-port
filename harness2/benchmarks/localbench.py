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

"""localbench: a small local task suite for validating a substrate end to end.

No Docker, no cloud, no model judge. Each task is a directory under `localbench/tasks/`:

    task.json        {"domain": ..., "timeout": seconds}
    prompt.md        the task as the agent receives it; deliverables go under output/
    files/           the agent's starting working directory
    grader/          hidden: grade.py <workspace> prints {"n_passed", "n_criteria", "checks"}

`grader/` never enters a rollout workspace or a model context: it is outside `files/`, it
matches `leak_globs`, and the operator floor refuses any tool call that names it.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from functools import cached_property
from pathlib import Path

from .. import config
from ..core import runmark as RM
from ..core import tree as HT
from ..core.spec import BenchPrompts, BenchSpec, ChannelSpec
from ..substrate import claude_code as CC
from ..substrate.base import Install, RunRequest

TASKS_ROOT = config.ROOT / "localbench" / "tasks"
DEFAULT_EDITOR_MODEL = "claude-opus-5-5"

WORK = {
    "data-cleaning": "clean and normalise messy tabular data files into the exact shape requested",
    "document-extraction": "extract structured rows from plain-text business documents into a table",
    "repo-bugfix": "find and fix a defect in a small Python package without breaking its behaviour",
}

BASE_SYSTEM_PROMPT = (
    "You are a careful assistant working in the current directory. Read the task, inspect the "
    "files it names, do the work with the tools available, and write every deliverable at the "
    "path the task gives. Check the deliverable before you finish.\n"
)

# A PreToolUse hook in the floor: a tool call naming the hidden graders is refused (exit 2).
_GUARD = (
    "import json,sys; e=json.load(sys.stdin); s=json.dumps(e.get('tool_input',{})); "
    "sys.exit(2 if any(t in s for t in sys.argv[1:]) else 0)"
)


class LocalBenchAdapter:
    """`--bench local`: the localbench tasks, run under the Claude Code substrate."""

    def __init__(self, substrate: str = "cc", tasks_root: Path = TASKS_ROOT):
        if substrate != "cc":
            raise ValueError(f"localbench runs on --substrate cc only, got {substrate!r}")
        self.tasks_root = Path(tasks_root).resolve()
        self.substrate = CC.ClaudeCodeSubstrate(launcher=self._launch)
        self.model = config.SOLVER_MODEL_CC
        editor = ChannelSpec("claude_cli", config.IMPROVER_MODEL or DEFAULT_EDITOR_MODEL)
        self.spec = BenchSpec(
            name="local",
            runs_root=config.RUNS / "local",
            install_mode=CC.INSTALL_MODE,
            prompts=BenchPrompts(work="complete small data and code tasks in a local workspace"),
            channels={"proposer": editor, "selector": editor},
            leak_globs=("grader/*", "grader/**", "*/grader/*"),
            allow_subagents=True,
        )

    @cached_property
    def _meta(self) -> dict[str, dict]:
        return {
            p.parent.name: json.loads(p.read_text())
            for p in sorted(self.tasks_root.glob("*/task.json"))
        }

    def tasks(self, split: str = "all") -> list[str]:
        if split != "all":
            raise ValueError(f"localbench has one split, 'all'; got {split!r}")
        if not self._meta:
            raise RuntimeError(f"no localbench tasks under {self.tasks_root}")
        return sorted(self._meta)

    def domain_of(self, task_id: str) -> str:
        return self._meta[task_id]["domain"]

    def prompts_for(self, task_id: str) -> BenchPrompts:
        return BenchPrompts(work=WORK[self.domain_of(task_id)])

    def task_prompt(self, task_id: str) -> str:
        return (self.tasks_root / task_id / "prompt.md").read_text(encoding="utf-8")

    def task_files(self, task_id: str) -> Path:
        return self.tasks_root / task_id / "files"

    def base_harness(self) -> Path:
        d = self.spec.runs_root / "base"
        base = {rel: "" for rel in self.substrate.surface().always_on}
        base["systemprompt.md"] = BASE_SYSTEM_PROMPT
        if HT.read_tree(self.substrate.surface(), d) != base:
            HT.write_tree(self.substrate.surface(), base, d, stubs=False)
        return d

    def validate_tree(self, tree: HT.Tree) -> None:
        bad = sorted(rel for rel, body in tree.items() if "grader" in body.lower())
        if bad:
            raise ValueError(
                f"{bad} mention the task checker; a harness must describe the work, never how "
                f"it is checked, and must not send the agent looking for answer keys"
            )

    def preflight(self) -> None:
        config.require("HARNESS2_CLAUDE_MODEL", needed_by="Claude Code executor rollouts")
        self.tasks()

    def run_dir(self, run_id: str) -> Path:
        return self.spec.runs_root / "executions" / run_id

    def execute(
        self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None
    ) -> Path:
        run_dir = self.run_dir(run_id)
        if RM.is_complete(run_dir, harness_dir=harness_dir) and self.delivered(run_dir):
            return run_dir
        shutil.rmtree(run_dir, ignore_errors=True)
        install = self.substrate.materialise(harness_dir or self.base_harness(), self.spec, {})
        try:
            limit = int(timeout or self._meta[task_id].get("timeout", 600))
            self.substrate.execute(task_id, install, [run_id], limit)
        finally:
            shutil.rmtree(install.staging_dir, ignore_errors=True)
        if not self.delivered(run_dir):
            raise RuntimeError(
                f"{run_id}: no deliverable under output/ (rollout "
                f"{json.loads((run_dir / 'rollout.json').read_text()).get('subtype')}); "
                f"left unmarked so it is re-rolled, not scored as a zero"
            )
        record = json.loads((run_dir / "rollout.json").read_text())
        RM.mark_complete(
            run_dir,
            run_id=run_id,
            harness_dir=harness_dir,
            extra={"cost_usd": record.get("cost_usd"), "model": self.model},
        )
        return run_dir

    def _launch(self, req: RunRequest, install: Install) -> list[Path]:
        guard = " ".join(
            shlex.quote(a)
            for a in (sys.executable, "-I", "-c", _GUARD, str(self.tasks_root), "/grader")
        )
        hooks = {"PreToolUse": [{"hooks": [{"type": "command", "command": guard}]}]}
        out = []
        for run_id in req.run_ids:
            run_dir = self.run_dir(run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            CC.run_rollout(
                install,
                run_dir,
                self.task_prompt(req.task_ref),
                model=self.model,
                timeout=req.timeout,
                task_files=self.task_files(req.task_ref),
                hooks=hooks,
            )
            out.append(run_dir)
        return out

    def _outputs(self, run_dir: Path) -> list[Path]:
        out = Path(run_dir) / "workspace" / "output"
        return sorted(p for p in out.rglob("*") if p.is_file()) if out.is_dir() else []

    def delivered(self, run_dir: Path) -> bool:
        return any(p.stat().st_size > 0 for p in self._outputs(run_dir))

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        return self.substrate.read_trajectory(
            Path(run_dir) / "stream.jsonl", obs_trunc=obs_trunc, max_chars=400_000
        )

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        root = Path(run_dir) / "workspace"
        return {
            str(p.relative_to(root)): p.read_text(encoding="utf-8", errors="replace")
            for p in self._outputs(run_dir)
        }

    def deliverable_text(self, run_dir: Path) -> str:
        return "\n\n".join(f"## {k}\n{v}" for k, v in self.deliverable_files(run_dir).items())

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        grader = self.tasks_root / task_id / "grader" / "grade.py"
        try:
            p = subprocess.run(
                [sys.executable, "-I", str(grader), str(Path(run_dir) / "workspace")],
                capture_output=True,
                text=True,
                timeout=300,
            )
            got = json.loads(p.stdout.strip().splitlines()[-1])
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            return None
        if not isinstance(got.get("n_criteria"), int) or got["n_criteria"] <= 0:
            return None
        return got
