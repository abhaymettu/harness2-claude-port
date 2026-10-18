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

"""ClaudeCodeSubstrate: headless Claude Code (`claude -p`) as a solver substrate.

Carries the c1..c8 surface (CLAUDE_SURFACE), the one install mode (claude_workspace), the
`claude -p` flag contract with its frozen floor (`harness2.claude_floor`), a rollout launcher
shared by every benchmark, and the stream-json trajectory renderer.

    c1 systemprompt.md                     -> .claude/systemprompt.md, --append-system-prompt-file
    c2 guardrails.md                       -> CLAUDE.md, section "Guardrails"
    c3 LongTermMEMORY.md                   -> CLAUDE.md, section "Long-term memory"
    c4 tool_descriptions/tool_guidance.md  -> CLAUDE.md, section "Tool guidance"
    c5 sub_agents/<n>/AGENT.md             -> .claude/agents/<n>.md (frontmatter name: <n>)
    c6 .claude/skills/<n>/SKILL.md (+ scripts/*), unchanged paths
    c7 scripts/<n>.py, unchanged paths
    c8 .claude/settings.json, a top-level "hooks" object and nothing else
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Mapping

from .. import claude_floor, config
from ..core import runmark as RM
from ..core import tree as HT
from ..core.tree import SurfaceSpec
from .base import Install, Launcher, RunRequest

INSTALL_MODE = "claude_workspace"
SYSTEM_PROMPT_FILE = ".claude/systemprompt.md"
SETTINGS_FILE = ".claude/settings.json"
CLAUDE_MD_SECTIONS = (
    ("guardrails.md", "Guardrails"),
    ("LongTermMEMORY.md", "Long-term memory"),
    ("tool_descriptions/tool_guidance.md", "Tool guidance"),
)
WALL_SLACK_S = 600

CLAUDE_SURFACE = SurfaceSpec(
    name="claude_code",
    always_on=(
        "systemprompt.md",
        "guardrails.md",
        "LongTermMEMORY.md",
        "tool_descriptions/tool_guidance.md",
    ),
    always_on_max=24_000,
    always_on_cap_reason=(
        "systemprompt.md is appended to the system prompt and the other three are the project "
        "CLAUDE.md, so every character is in context on every turn"
    ),
    skill_dir=".claude/skills",
    skill_name_rule="overrides_dir",
    trigger_hint=(
        "Fix it by adding a trigger line naming `{name}` to systemprompt.md or guardrails.md, "
        'e.g. "When <the situation this skill handles>, use the `{name}` skill."'
    ),
    autotrigger_file="guardrails.md",
    trigger_line="- When {desc}, use the `{name}` skill.\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=SETTINGS_FILE,
    hook_events=frozenset(
        {
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "PreCompact",
            "PostCompact",
            "SessionStart",
            "SubagentStart",
            "SubagentStop",
            "UserPromptSubmit",
            "Stop",
        }
    ),
    compile_skill_scripts=True,
    hooks_file_keys=frozenset({"hooks"}),
    skill_frontmatter_keys=frozenset({"name", "description"}),
    subagent_frontmatter_keys=frozenset({"name", "description", "tools", "model"}),
    stubs=(
        (
            "scripts/README.md",
            "<!-- c7: deterministic helpers, run as `python3 scripts/<name>.py`. "
            "Add one by emitting scripts/<name>.py. -->\n",
        ),
        (
            "sub_agents/README.md",
            "<!-- c5: delegated subagents, each spawned with the Agent tool in its OWN context. "
            "Add one as sub_agents/<name>/AGENT.md with frontmatter `description:` (and "
            "optionally `tools:`); it is installed as .claude/agents/<name>.md. -->\n",
        ),
        (
            ".claude/skills/README.md",
            "<!-- c6: reusable workflows loaded on demand with the Skill tool. Add one as "
            ".claude/skills/<name>/SKILL.md with YAML frontmatter: `description:` is REQUIRED; "
            "`name:` is optional and must match the directory. Helpers it runs go in "
            ".claude/skills/<name>/scripts/. -->\n",
        ),
        (
            ".claude/README.md",
            "<!-- c8: Claude Code lifecycle hooks, the only lever that acts INSIDE the tool loop. "
            "Add ONE file, .claude/settings.json, holding only a top-level hooks object: "
            '{"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", '
            '"command": "..."}]}]}}. -->\n',
        ),
    ),
)


def render_claude_md(tree: HT.Tree) -> str:
    parts = [
        f"# {title}\n\n{body.strip()}\n"
        for rel, title in CLAUDE_MD_SECTIONS
        if (body := tree.get(rel, "")).strip()
    ]
    return "\n".join(parts)


def agent_file(name: str, body: str) -> str:
    """A Claude Code agent definition: the AGENT.md with `name: <name>` in its frontmatter."""
    m = re.match(r"---\n(.*?)\n---\n?", body, re.S)
    if not m:
        return f"---\nname: {name}\n---\n{body}"
    fm = [ln for ln in m.group(1).splitlines() if not re.match(r"name:\s", ln)]
    return "---\n" + "\n".join([f"name: {name}", *fm]) + "\n---\n" + body[m.end() :]


def place(install: Install, workspace: Path) -> Path:
    """Copy a materialised harness into a rollout workspace and make it a git root.

    The git root makes the workspace the project directory, so `.claude/` resolves here.
    """
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    shutil.copytree(install.staging_dir, workspace, dirs_exist_ok=True)
    if not (workspace / ".git").exists():
        subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    return workspace


def exec_argv(
    prompt: str,
    *,
    model: str,
    floor_path: Path,
    system_prompt_file: Path | None,
    effort: str | None = None,
    claude_bin: str | None = None,
) -> list[str]:
    argv = [
        claude_bin or shutil.which("claude") or "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        *claude_floor.ISOLATION_FLAGS,
        "--settings",
        str(floor_path),
        "--dangerously-skip-permissions",
        "--model",
        model,
    ]
    if system_prompt_file is not None:
        argv += ["--append-system-prompt-file", str(system_prompt_file)]
    if effort:
        argv += ["--effort", effort]
    return argv


def exec_env(base_env: Mapping[str, str], *, model: str) -> dict[str, str]:
    """Subagents run on the executor model too, so one model id names the whole rollout."""
    env = dict(base_env)
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = model
    if config.CLAUDE_VIA_VERTEX:
        env.update(
            {
                "CLAUDE_CODE_USE_VERTEX": "1",
                "ANTHROPIC_VERTEX_PROJECT_ID": config.VERTEX_PROJECT,
                "CLOUD_ML_REGION": config.VERTEX_REGION,
            }
        )
    return env


def run_rollout(
    install: Install,
    run_dir: Path,
    prompt: str,
    *,
    model: str,
    timeout: int,
    task_files: Path | None = None,
    hooks: Mapping | None = None,
    env: Mapping[str, str] | None = None,
    effort: str | None = None,
    claude_bin: str | None = None,
) -> dict:
    """One headless session in `run_dir/workspace`; the stream lands in `run_dir/stream.jsonl`.

    Runs in its own process group, killed whole when the session ends or at
    `timeout + WALL_SLACK_S`. `env` is added to the caller's environment (operator hook
    settings, say). The return value (also `run_dir/rollout.json`) reports what happened;
    whether the task was delivered is the benchmark's call, never the exit code's.
    """
    run_dir = Path(run_dir)
    workspace = run_dir / "workspace"
    if task_files is not None and Path(task_files).is_dir():
        shutil.copytree(task_files, workspace, dirs_exist_ok=True)
    place(install, workspace)
    floor = claude_floor.write_floor(run_dir / "floor.json", workspace, hooks=hooks)
    spf = workspace / SYSTEM_PROMPT_FILE
    argv = exec_argv(
        prompt,
        model=model,
        floor_path=floor,
        system_prompt_file=spf if spf.is_file() and spf.read_text().strip() else None,
        effort=effort,
        claude_bin=claude_bin,
    )
    stream = run_dir / "stream.jsonl"
    t0 = time.time()
    timed_out = False
    proc = None
    try:
        with stream.open("wb") as out, (run_dir / "stderr.txt").open("wb") as err:
            proc = subprocess.Popen(
                argv,
                cwd=workspace,
                env=exec_env({**os.environ, **(env or {})}, model=model),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            try:
                proc.wait(timeout=int(timeout) + WALL_SLACK_S)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Background children outlive the session otherwise, still writing the workspace.
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    finally:
        record = {
            "returncode": proc.returncode if proc else None,
            "timed_out": timed_out,
            "wall_s": round(time.time() - t0, 1),
            "model": model,
            **result_of(stream),
        }
        (run_dir / "rollout.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


class ClaudeCodeSubstrate:
    """Claude Code behind the one Substrate interface."""

    name = "cc"

    def __init__(self, launcher: Launcher | None = None):
        self._launcher = launcher

    def surface(self) -> SurfaceSpec:
        return CLAUDE_SURFACE

    def materialise(self, tree_dir: Path, spec, ctx: Mapping[str, str]) -> Install:
        if spec.install_mode != INSTALL_MODE:
            raise ValueError(
                f"install_mode {spec.install_mode!r} is not the Claude Code mode; this "
                f"substrate has exactly one: {INSTALL_MODE!r}"
            )
        tree_dir = Path(tree_dir)
        if not HT.is_tree(CLAUDE_SURFACE, tree_dir):
            raise ValueError(f"{tree_dir} is not a Claude Code harness tree (no always-on file)")
        tree = HT.read_tree(CLAUDE_SURFACE, tree_dir)
        staged = Path(tempfile.mkdtemp(prefix="adapt-cc-"))
        try:
            files: dict[str, str] = {SYSTEM_PROMPT_FILE: tree.get("systemprompt.md", "")}
            claude_md = render_claude_md(tree)
            if claude_md:
                files["CLAUDE.md"] = claude_md
            agents = {
                f"sub_agents/{n}/AGENT.md": n for n in HT.subagent_names(CLAUDE_SURFACE, tree)
            }
            for rel, body in tree.items():
                if rel in CLAUDE_SURFACE.always_on:
                    continue
                if rel in agents:
                    files[f".claude/agents/{agents[rel]}.md"] = agent_file(agents[rel], body)
                else:
                    files[rel] = body
            for key, body in ctx.items():
                if key.startswith("file:"):
                    files[HT.normalize_rel(key[len("file:") :])] = body
            for rel, body in files.items():
                p = staged / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return Install(
            staging_dir=staged,
            fingerprint=RM.fingerprint(tree_dir),
            extras={
                "install_mode": INSTALL_MODE,
                **{k: v for k, v in ctx.items() if not k.startswith("file:")},
            },
        )

    def execute(
        self, task_ref: str, install: Install, run_ids: list[str], timeout: int
    ) -> list[Path]:
        if self._launcher is None:
            raise RuntimeError(
                "ClaudeCodeSubstrate was constructed without a launcher body; the benchmark "
                "adapter must supply one (it owns the task files, prompt and run locations)"
            )
        return self._launcher(
            RunRequest(task_ref=task_ref, run_ids=tuple(run_ids), timeout=int(timeout)), install
        )

    def read_trajectory(
        self, stream_path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 2000
    ) -> str:
        return render_stream(
            Path(stream_path), obs_trunc=obs_trunc, max_chars=max_chars, args_trunc=args_trunc
        )

    def preflight(self) -> None:
        """The CLI is installed and logged in. Never starts a model session."""
        binary = shutil.which("claude")
        if not binary:
            raise RuntimeError(
                "Claude Code is not on PATH; install it (https://docs.claude.com/en/docs/"
                "claude-code/setup) and run `claude` once to log in"
            )
        if config.CLAUDE_VIA_VERTEX:
            config.require("GOOGLE_CLOUD_PROJECT", needed_by="Claude Code on Vertex AI")
            return
        if os.environ.get("ANTHROPIC_API_KEY"):
            return
        try:
            out = subprocess.run(
                [binary, "auth", "status"], capture_output=True, text=True, timeout=30
            ).stdout
            logged_in = bool(json.loads(out).get("loggedIn"))
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            logged_in = False
        if not logged_in:
            raise RuntimeError(
                "Claude Code is not logged in; run `claude auth login`, or set ANTHROPIC_API_KEY"
            )


_TRUNC_FMT = "…(+{n} chars - render truncation)"
_SKILL_BODY = "Base directory for this skill:"


def _clip(s, n: int) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\x00", "")
    if n <= 0 or len(s) <= n:
        return s
    return s[:n] + _TRUNC_FMT.format(n=len(s) - n)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else ""
            for b in content
        ).strip()
    return ""


def parse_stream(path: Path) -> list[dict]:
    """The stream-json events in order; non-JSON lines are skipped."""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [{"type": "_read_error", "message": str(e)}]
    events = []
    for ln in raw.replace("\x00", "").splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events


def result_of(path: Path) -> dict:
    """The final `result` event's accounting, or an error record when there is none."""
    for ev in reversed(parse_stream(path)):
        if ev.get("type") == "result":
            return {
                "subtype": ev.get("subtype"),
                "is_error": bool(ev.get("is_error")),
                "num_turns": ev.get("num_turns"),
                "cost_usd": float(ev.get("total_cost_usd") or 0.0),
                "result": ev.get("result") if isinstance(ev.get("result"), str) else "",
            }
    return {"subtype": None, "is_error": True, "num_turns": 0, "cost_usd": 0.0, "result": ""}


def final_message(path: Path) -> str:
    return result_of(path)["result"]


def _render_message(ev: dict, lines: list[str], obs_trunc: int, args_trunc: int) -> None:
    msg = ev.get("message")
    if not isinstance(msg, dict):
        return
    sub = " (in subagent)" if ev.get("parent_tool_use_id") else ""
    content = msg.get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if ev["type"] == "assistant":
            if kind == "text" and block.get("text", "").strip():
                lines.append(f"[ASSISTANT]{sub} {_clip(block['text'], obs_trunc)}")
            elif kind == "thinking" and block.get("thinking", "").strip():
                lines.append(f"[REASONING]{sub} {_clip(block['thinking'], obs_trunc)}")
            elif kind == "tool_use":
                inp = block.get("input")
                if isinstance(inp, dict) and set(inp) <= {"command", "description", "timeout"}:
                    inp = inp.get("command", inp)
                shown = inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False)
                lines.append(f"[ACTION]{sub} {block.get('name')}: {_clip(shown, args_trunc)}")
        elif kind == "tool_result":
            tag = "OBSERVATION ERROR" if block.get("is_error") else "OBSERVATION"
            lines.append(f"[{tag}]{sub} {_clip(_text(block.get('content')), obs_trunc)}")
        elif kind == "text" and block.get("text", "").strip():
            txt = block["text"]
            tag = "HARNESS skill" if txt.lstrip().startswith(_SKILL_BODY) else "USER"
            lines.append(f"[{tag}]{sub} {_clip(txt, obs_trunc)}")


def render_stream(path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 2000) -> str:
    """Render a `claude -p --output-format stream-json --verbose` capture into the grammar."""
    lines: list[str] = []
    for ev in parse_stream(Path(path)):
        et, st = ev.get("type"), ev.get("subtype")
        if et == "_read_error":
            return f"(failed to read trajectory: {ev.get('message')})"
        if et in ("assistant", "user"):
            _render_message(ev, lines, obs_trunc, args_trunc)
        elif et == "system" and st == "init":
            lines.append(
                f"[HARNESS] session: model={ev.get('model')}; "
                f"skills: {', '.join(ev.get('skills') or []) or '(none)'}; "
                f"agents: {', '.join(ev.get('agents') or []) or '(none)'}"
            )
        elif et == "system" and st == "hook_response":
            out = (ev.get("output") or ev.get("stdout") or "").strip()
            if out:
                lines.append(f"[HARNESS hook {ev.get('hook_event')}] {_clip(out, obs_trunc)}")
        elif et == "system" and st == "task_notification":
            lines.append(
                f"[OBSERVATION] subagent {ev.get('status')}: {_clip(ev.get('summary'), obs_trunc)}"
            )
        elif et == "result":
            if ev.get("is_error") or ev.get("subtype") != "success":
                lines.append(f"[ERROR] {ev.get('subtype')}: {_clip(ev.get('result'), 1000)}")
            lines.append(
                f"[HARNESS] result: {ev.get('subtype')} | turns={ev.get('num_turns')} "
                f"cost_usd={ev.get('total_cost_usd')}"
            )
    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=len(rendered) - max_chars)
    return rendered


__all__ = [
    "CLAUDE_SURFACE",
    "ClaudeCodeSubstrate",
    "INSTALL_MODE",
    "exec_argv",
    "final_message",
    "render_stream",
    "result_of",
    "run_rollout",
]
