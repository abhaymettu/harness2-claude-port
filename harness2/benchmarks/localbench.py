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

`grader/` never enters a rollout workspace or a model context: it is outside `files/` and it
matches `leak_globs`. The operator floor also refuses any tool call that names the tasks or
their checkers, in rollouts and improver sessions alike. That hook is a guard against an agent
wandering into answer keys, not a security boundary: a tool call can reach a path without
spelling it.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from functools import cached_property
from pathlib import Path

from .. import config
from ..core import runmark as RM
from ..core import tree as HT
from ..core.spec import BenchPrompts, BenchSpec, ChannelSpec, resolve_channel_model
from ..substrate import claude_code as CC
from ..substrate import hermes as HM
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

# A PreToolUse hook in the floor: a tool call naming any token in H2_GUARD_DENY is refused
# (exit 2). The tokens travel in the environment and the reason is fixed, so neither the hook
# command nor its refusal shows the model where the tasks live. An unset variable refuses all.
GUARD_ENV = "H2_GUARD_DENY"
_GUARD = (
    "import json,os,sys; e=json.load(sys.stdin).get('tool_input',{}); "
    "s=json.dumps(e,ensure_ascii=False).lower(); d=os.environ.get('H2_GUARD_DENY'); "
    "t=[x.lower() for x in (d or '').split(os.pathsep) if x]; "
    "hit=d is None or any(x in s for x in t); "
    "hit and print('blocked: that path is outside this task',file=sys.stderr); "
    "sys.exit(2 if hit else 0)"
)


class LocalBenchAdapter:
    """`--bench local`: the localbench tasks, run under Claude Code (cc) or Hermes (hm)."""

    def __init__(self, substrate: str = "cc", tasks_root: Path = TASKS_ROOT):
        if substrate not in ("cc", "hm"):
            raise ValueError(f"localbench runs on --substrate cc or hm, got {substrate!r}")
        given = Path(tasks_root).absolute()
        self.tasks_root = given.resolve()
        self._deny = (str(given), str(self.tasks_root), "localbench", "grade.py", "hidden_tests")
        self._deny += ("/grader", "gr?der")
        self.kind = substrate
        if substrate == "hm":
            self.substrate = HM.HermesSubstrate(launcher=self._launch)
            self.model = config.SOLVER_MODEL_HM
        else:
            self.substrate = CC.ClaudeCodeSubstrate(launcher=self._launch)
            self.model = config.SOLVER_MODEL_CC
        editor = (
            resolve_channel_model("claude_cli", config.IMPROVER_MODEL)
            if config.IMPROVER_MODEL
            else ChannelSpec("claude_cli", DEFAULT_EDITOR_MODEL)
        )
        self.spec = BenchSpec(
            name="local",
            runs_root=config.RUNS / ("local" if substrate == "cc" else f"local-{substrate}"),
            install_mode=HM.INSTALL_MODE if substrate == "hm" else CC.INSTALL_MODE,
            prompts=BenchPrompts(work="complete small data and code tasks in a local workspace"),
            channels={"proposer": editor, "selector": editor},
            leak_globs=("grader/*", "grader/**", "*/grader/*"),
            allow_subagents=True,
        )
        self._base = self._build_base()

    @property
    def floor_hooks(self) -> dict:
        """Operator hooks for every session this benchmark starts, rollouts and improvers."""
        guard = " ".join(shlex.quote(a) for a in (sys.executable, "-I", "-c", _GUARD))
        return {"PreToolUse": [{"hooks": [{"type": "command", "command": guard}]}]}

    @property
    def rollout_hooks(self) -> dict:
        """The same guard in Hermes's shell-hook shape; `python3` because the rollout may run as
        another user who cannot execute this process's interpreter."""
        guard = " ".join(shlex.quote(a) for a in ("python3", "-I", "-c", _GUARD))
        return {"pre_tool_call": [{"command": guard}]}

    @property
    def floor_env(self) -> dict[str, str]:
        return {GUARD_ENV: os.pathsep.join(self._deny)}

    def _build_base(self) -> Path:
        """Write the base tree once, swapped in whole so a concurrent reader never sees half."""
        d = self.spec.runs_root / "base"
        surface = self.substrate.surface()
        base = {rel: "" for rel in surface.always_on}
        base["systemprompt.md"] = BASE_SYSTEM_PROMPT
        if HT.read_tree(surface, d) == base:
            return d
        d.parent.mkdir(parents=True, exist_ok=True)
        new = Path(tempfile.mkdtemp(prefix=".base-", dir=d.parent))
        old = Path(tempfile.mkdtemp(prefix=".base-old-", dir=d.parent))
        try:
            HT.write_tree(surface, base, new, stubs=False)
            with contextlib.suppress(FileNotFoundError):
                os.replace(d, old / "base")
            try:
                os.replace(new, d)
            except OSError:
                # Another adapter swapped its copy in first; keep it if it is the same tree.
                if HT.read_tree(surface, d) != base:
                    raise
        finally:
            shutil.rmtree(new, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)
        return d

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
        return self._base

    def validate_tree(self, tree: HT.Tree) -> None:
        bad = sorted(rel for rel, body in tree.items() if "grader" in body.lower())
        if bad:
            raise ValueError(
                f"{bad} mention the task checker; a harness must describe the work, never how "
                f"it is checked, and must not send the agent looking for answer keys"
            )

    def preflight(self) -> None:
        if self.kind == "hm":
            config.require("HARNESS2_HERMES_MODEL", needed_by="Hermes executor rollouts")
        else:
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
                f"{self._outcome(run_dir)}); "
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

    @staticmethod
    def _outcome(run_dir: Path) -> str:
        record = json.loads((Path(run_dir) / "rollout.json").read_text())
        return str(record.get("subtype") or f"exit {record.get('exit_code')}")

    def _launch(self, req: RunRequest, install: Install) -> list[Path]:
        out = []
        for run_id in req.run_ids:
            run_dir = self.run_dir(run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            if self.kind == "hm":
                HM.run_rollout(
                    install,
                    run_dir,
                    self.task_prompt(req.task_ref),
                    model=self.model,
                    provider=config.HERMES_PROVIDER or None,
                    timeout=req.timeout,
                    task_files=self.task_files(req.task_ref),
                    hooks=self.rollout_hooks,
                    env=self.floor_env,
                )
                out.append(run_dir)
                continue
            CC.run_rollout(
                install,
                run_dir,
                self.task_prompt(req.task_ref),
                model=self.model,
                timeout=req.timeout,
                task_files=self.task_files(req.task_ref),
                hooks=self.floor_hooks,
                env=self.floor_env,
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
