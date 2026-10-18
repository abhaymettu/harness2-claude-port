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

"""HermesSubstrate: NousResearch hermes-agent (`hermes chat -q`) as a solver substrate.

Every rollout gets its own throwaway HERMES_HOME, built from a template and never from a user's
own home, and an empty environment. The c1..c8 surface (HERMES_SURFACE) maps as:

    c1 systemprompt.md                     -> $HERMES_HOME/SOUL.md, first section (the identity)
    c2 guardrails.md                       -> SOUL.md, section "Guardrails"
    c3 LongTermMEMORY.md                   -> $HERMES_HOME/memories/MEMORY.md, one entry per paragraph
    c4 tool_descriptions/tool_guidance.md  -> SOUL.md, section "Tool guidance"
    c5 sub_agents/<n>/AGENT.md             -> EMULATED: skill `agent-<n>` holding a brief that the
                                              parent passes to delegate_task (Hermes has no
                                              file-defined subagents)
    c6 skills/<n>/SKILL.md (+ scripts/*)   -> workspace skills/<n>/, loaded via skills.external_dirs
    c7 scripts/<n>.py                      -> workspace scripts/<n>.py
    c8 hooks.json                          -> the `hooks:` map of the rollout config.yaml (shell hooks)

The floor is the rest of that config.yaml: no background review, nudges, curator or title
calls, memory raised to the always-on cap, no borrowed logins, and the operator's hooks first.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .. import config
from ..core import runmark as RM
from ..core import tree as HT
from ..core.tree import SurfaceSpec
from .base import Install, Launcher, RunRequest

INSTALL_MODE = "hermes_home"
HOOKS_FILE = "hooks.json"
SOUL_SECTIONS = (
    ("guardrails.md", "Guardrails"),
    ("tool_descriptions/tool_guidance.md", "Tool guidance"),
)
MEMORY_DELIMITER = "\n§\n"
AGENT_SKILL_PREFIX = "agent-"
TOOLSETS = "terminal,file,skills,delegation"
MAX_TURNS = 60
WALL_SLACK_S = 600
ALWAYS_ON_MAX = 20_000

# Shell-hook events a single-query CLI session dispatches (hermes_cli/plugins.py VALID_HOOKS,
# minus the gateway, streaming-observer and API-request events).
HOOK_EVENTS = frozenset(
    {
        "pre_tool_call",
        "post_tool_call",
        "transform_terminal_output",
        "transform_tool_result",
        "transform_llm_output",
        "pre_llm_call",
        "post_llm_call",
        "pre_verify",
        "on_session_start",
        "on_session_end",
        "on_session_finalize",
        "subagent_start",
        "subagent_stop",
    }
)

HERMES_SURFACE = SurfaceSpec(
    name="hermes",
    always_on=(
        "systemprompt.md",
        "guardrails.md",
        "LongTermMEMORY.md",
        "tool_descriptions/tool_guidance.md",
    ),
    always_on_max=ALWAYS_ON_MAX,
    always_on_cap_reason=(
        "systemprompt.md, guardrails.md and tool_guidance.md are SOUL.md and LongTermMEMORY.md "
        "is the memory snapshot, all in the system prompt on every turn, and Hermes caps a "
        "context file at 20,000 chars"
    ),
    skill_dir="skills",
    skill_name_rule="must_match",
    trigger_hint=(
        "Fix it by adding a trigger line naming `{name}` to systemprompt.md or guardrails.md, "
        'e.g. "When <the situation this skill handles>, use the `{name}` skill."'
    ),
    autotrigger_file="guardrails.md",
    trigger_line="- When {desc}, use the `{name}` skill.\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=HOOKS_FILE,
    hook_events=HOOK_EVENTS,
    hook_entry_shape="flat",
    compile_skill_scripts=True,
    hooks_file_keys=frozenset({"hooks"}),
    skill_frontmatter_keys=frozenset({"name", "description"}),
    subagent_frontmatter_keys=frozenset({"name", "description"}),
    stubs=(
        (
            "scripts/README.md",
            "<!-- c7: deterministic helpers, run with the terminal tool as "
            "`python3 scripts/<name>.py`. Add one by emitting scripts/<name>.py. -->\n",
        ),
        (
            "sub_agents/README.md",
            "<!-- c5: delegated subagents. Hermes has no file-defined subagents: each "
            "sub_agents/<name>/AGENT.md (frontmatter `description:`) becomes a skill "
            "`agent-<name>` holding its brief, which the agent passes to delegate_task. The "
            "child sees only that brief and the goal: no SOUL, no memory. -->\n",
        ),
        (
            "skills/README.md",
            "<!-- c6: reusable workflows loaded on demand with skill_view. Add one as "
            "skills/<name>/SKILL.md with YAML frontmatter `name: <name>` (matching the "
            "directory) and `description:`. Helpers it runs go in skills/<name>/scripts/ and are "
            "run from the workspace root as `python3 skills/<name>/scripts/<file>.py`. -->\n",
        ),
        (
            "hooks.README.md",
            "<!-- c8: Hermes shell hooks, the only lever that acts INSIDE the tool loop. Add ONE "
            'file, hooks.json, holding only {"hooks": {"pre_tool_call": [{"matcher": '
            '"terminal", "command": "...", "timeout": 10}]}}. -->\n',
        ),
    ),
)


@dataclass(frozen=True)
class Launch:
    """Where and how rollouts run: deployment facts, not harness content.

    `runner` prefixes every command that touches the rollout root (`sudo -n -u <user>`, say),
    so the root can belong to another OS user. `pass_env` names variables copied from this
    process into the rollout's otherwise empty environment. Secrets reach the rollout over a
    pipe, never on a command line. `providers` is a `providers:` map for config.yaml.
    """

    hermes: tuple[str, ...] = ("hermes",)
    runner: tuple[str, ...] = ()
    root: Path = field(default_factory=lambda: config.HERMES_ROLLOUTS)
    pass_env: tuple[str, ...] = ()
    providers: Mapping = field(default_factory=dict)
    python: str = "python3"

    @classmethod
    def from_config(cls) -> "Launch":
        providers = {}
        if config.HERMES_PROVIDERS_FILE:
            providers = json.loads(Path(config.HERMES_PROVIDERS_FILE).read_text(encoding="utf-8"))
        return cls(
            hermes=tuple(shlex.split(config.HERMES_CMD)),
            runner=tuple(shlex.split(config.HERMES_RUNNER)),
            root=Path(config.HERMES_ROLLOUTS),
            pass_env=tuple(n for n in re.split(r"[,\s]+", config.HERMES_PASS_ENV) if n),
            providers=providers,
        )


def render_soul(tree: HT.Tree) -> str:
    """SOUL.md: the system prompt first, then the other prose sections, then the subagent note."""
    parts = [tree.get("systemprompt.md", "").strip()]
    parts += [
        f"# {title}\n\n{body.strip()}"
        for rel, title in SOUL_SECTIONS
        if (body := tree.get(rel, "")).strip()
    ]
    subs = HT.subagent_names(HERMES_SURFACE, tree)
    if subs:
        listed = ", ".join(f"`{n}` (skill `{AGENT_SKILL_PREFIX}{n}`)" for n in subs)
        parts.append(
            "# Subagents\n\nThese subagents are available: "
            f"{listed}. To consult one, load its skill with skill_view and call delegate_task "
            "with the brief from that skill, verbatim, as `context`, followed by the inputs the "
            "subagent needs; put the question in `goal`. The subagent sees nothing else."
        )
    return "\n\n".join(p for p in parts if p) + "\n"


def render_memory(body: str) -> str:
    """MEMORY.md entries are separated by a line holding only `§`; one entry per paragraph."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return MEMORY_DELIMITER.join(paras) + ("\n" if paras else "")


def agent_skill(name: str, body: str) -> str:
    """A sub_agents/<n>/AGENT.md as the brief skill `agent-<n>`."""
    m = re.match(r"---\n(.*?)\n---\n?", body, re.S)
    fm, brief = (m.group(1), body[m.end() :]) if m else ("", body)
    d = re.search(r"^description:\s*(.+)$", fm, re.M)
    desc = d.group(1).strip().strip("\"'") if d else f"the {name} subagent"
    return (
        f"---\nname: {AGENT_SKILL_PREFIX}{name}\n"
        f"description: {json.dumps('Brief for the ' + name + ' subagent: ' + desc)}\n---\n"
        f"Subagent `{name}`. Call delegate_task with the brief below, verbatim, as `context` "
        "(add the inputs the task needs after it) and the question as `goal`.\n\n"
        f"## Brief\n\n{brief.strip()}\n"
    )


def hooks_of(tree: HT.Tree) -> dict:
    """The tree's hook map; only the `hooks` key of hooks.json is ever read."""
    src = tree.get(HOOKS_FILE, "")
    if not src.strip():
        return {}
    doc = json.loads(src)
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    return hooks if isinstance(hooks, dict) else {}


def merge_hooks(operator: Mapping | None, harness: Mapping) -> dict:
    """Operator hooks run first for each event; the harness cannot remove them."""
    out: dict[str, list] = {}
    for src in (operator or {}, harness):
        for event, entries in src.items():
            out.setdefault(event, []).extend(json.loads(json.dumps(list(entries))))
    return out


def floor_config(
    *,
    work: Path,
    model: str,
    provider: str | None,
    hooks: Mapping,
    providers: Mapping | None = None,
    memory_limit: int = ALWAYS_ON_MAX,
) -> dict:
    """The rollout config.yaml (written as JSON, which YAML reads): nothing here comes from a
    harness tree except `hooks`, and nothing from a user's own Hermes config."""
    doc: dict = {
        "model": {"default": model, **({"provider": provider} if provider else {})},
        "approvals": {"mode": "manual", "single_query_mode": "deny"},
        "auxiliary": {
            "background_review": {"enabled": False},
            "title_generation": {"enabled": False, "model_upgrade_enabled": False},
        },
        "memory": {
            "memory_enabled": True,
            "user_profile_enabled": False,
            "memory_char_limit": int(memory_limit),
            "nudge_interval": 0,
            "write_approval": True,
            "provider": "",
        },
        "skills": {
            "external_dirs": [str(Path(work) / "skills")],
            "creation_nudge_interval": 0,
            "write_approval": True,
            "inline_shell": False,
            "project_discovery": False,
            "auto_load": [],
        },
        "curator": {"enabled": False},
        "auth": {"adopt_external_logins": False},
        "hooks": dict(hooks),
        "hooks_auto_accept": True,
    }
    if providers:
        doc["providers"] = json.loads(json.dumps(dict(providers)))
    return doc


class HermesSubstrate:
    """hermes-agent behind the one Substrate interface."""

    name = "hm"

    def __init__(self, launcher: Launcher | None = None):
        self._launcher = launcher

    def surface(self) -> SurfaceSpec:
        return HERMES_SURFACE

    def materialise(self, tree_dir: Path, spec, ctx: Mapping[str, str]) -> Install:
        """Stage `home/` (SOUL.md, memories/, generated agent skills), `work/` (scripts, skills,
        ctx files) and `tree-hooks.json`; the executor adds config.yaml and the task."""
        if spec.install_mode != INSTALL_MODE:
            raise ValueError(
                f"install_mode {spec.install_mode!r} is not the Hermes mode; this substrate has "
                f"exactly one: {INSTALL_MODE!r}"
            )
        tree_dir = Path(tree_dir)
        if not HT.is_tree(HERMES_SURFACE, tree_dir):
            raise ValueError(f"{tree_dir} is not a Hermes harness tree (no always-on file)")
        tree = HT.read_tree(HERMES_SURFACE, tree_dir)
        subs = HT.subagent_names(HERMES_SURFACE, tree)
        clash = sorted(
            n for n in HT.skill_names(HERMES_SURFACE, tree) if n.startswith(AGENT_SKILL_PREFIX)
        )
        if clash:
            raise ValueError(
                f"skills {clash} use the `{AGENT_SKILL_PREFIX}` prefix, which is reserved for "
                "the skills that carry sub_agents/ briefs"
            )
        files: dict[str, str] = {
            "home/SOUL.md": render_soul(tree),
            "home/memories/MEMORY.md": render_memory(tree.get("LongTermMEMORY.md", "")),
            "tree-hooks.json": json.dumps(hooks_of(tree), indent=2),
        }
        for n in subs:
            body = tree[f"sub_agents/{n}/AGENT.md"]
            files[f"home/skills/{AGENT_SKILL_PREFIX}{n}/SKILL.md"] = agent_skill(n, body)
        for rel, body in tree.items():
            if (
                rel in HERMES_SURFACE.always_on
                or rel == HOOKS_FILE
                or rel.startswith("sub_agents/")
            ):
                continue
            files[f"work/{rel}"] = body
        for key, body in ctx.items():
            if key.startswith("file:"):
                files[f"work/{HT.normalize_rel(key[len('file:') :])}"] = body
        staged = Path(tempfile.mkdtemp(prefix="adapt-hm-"))
        try:
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
                "HermesSubstrate was constructed without a launcher body; the benchmark adapter "
                "must supply one (it owns the task files, prompt and run locations)"
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

    def preflight(self, launch: Launch | None = None) -> None:
        """The command runs and reports a version, and the rollout root is usable. Never starts
        a model session."""
        launch = launch or Launch.from_config()
        check_root(launch.root)
        try:
            _as_runner(launch, ["mkdir", "-p", str(launch.root)], check=True, capture_output=True)
            p = _runner(
                launch,
                [*launch.hermes, "--version"],
                env=_rollout_env(launch, {"HERMES_HOME": str(launch.root / ".preflight-home")}),
                cwd="/",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"cannot run {launch.hermes[0]!r}: {exc}") from exc
        if p.returncode != 0 or "Hermes" not in p.stdout:
            raise RuntimeError(
                f"`{' '.join(launch.hermes)} --version` failed (exit {p.returncode}): "
                f"{(p.stderr or p.stdout).strip()[:300]}; install hermes-agent or set "
                "HARNESS2_HERMES_CMD"
            )


def check_root(root: Path) -> None:
    """A rollout root must never sit inside a Hermes home: a run there could read or write it."""
    if ".hermes" in Path(root).absolute().parts:
        raise RuntimeError(
            f"rollout root {root} is inside a .hermes directory; use a separate root "
            "(HARNESS2_HERMES_ROLLOUTS) so no rollout can touch a live home"
        )


# The rollout process: reads its environment as one JSON line on stdin, records its pid (its
# process group, so the whole tree can be killed by the user that owns it), then execs hermes.
_SHIM = (
    "import json,os,sys; e=json.loads(sys.stdin.readline()); a=e.pop('__argv'); "
    "c=e.pop('__cwd'); p=e.pop('__pidfile',None); os.setsid(); "
    "p and open(p,'w').write(str(os.getpid())); os.chdir(c); "
    "f=os.open(os.devnull,os.O_RDONLY); os.dup2(f,0); os.execvpe(a[0],a,e)"
)


def _rollout_env(launch: Launch, extra: Mapping[str, str]) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8"}
    for name in launch.pass_env:
        if os.environ.get(name):
            env[name] = os.environ[name]
    env.update(extra)
    return env


def _runner(
    launch: Launch,
    argv: list[str],
    *,
    env: Mapping[str, str],
    cwd: str,
    timeout: int,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    pidfile: str | None = None,
) -> subprocess.CompletedProcess:
    """Run `argv` under the runner with exactly `env`, delivered over stdin."""
    doc = {**env, "__argv": list(argv), "__cwd": cwd, **({"__pidfile": pidfile} if pidfile else {})}
    return subprocess.run(
        [*launch.runner, launch.python, "-I", "-c", _SHIM],
        input=json.dumps(doc) + "\n",
        stdout=stdout,
        stderr=stderr,
        text=True,
        timeout=timeout,
    )


def _as_runner(launch: Launch, argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run([*launch.runner, *argv], **kw)


def _shareable(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.mode = (ti.mode | 0o755) if ti.isdir() else (ti.mode | 0o644)
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    return ti


def put_tree(launch: Launch, src: Path, dst: Path) -> None:
    """Copy `src` into `dst` as the runner user, so the files belong to whoever runs Hermes."""
    _as_runner(launch, ["mkdir", "-p", str(dst)], check=True)
    proc = subprocess.Popen(
        [*launch.runner, "tar", "-C", str(dst), "-xf", "-"], stdin=subprocess.PIPE
    )
    try:
        with tarfile.open(fileobj=proc.stdin, mode="w|") as tf:
            tf.add(str(src), arcname=".", filter=_shareable)
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"could not stage {src} into {dst}")


def get_tree(launch: Launch, src: Path, dst: Path) -> None:
    """Copy `src` (owned by the runner user) into `dst`; links and special files are skipped."""
    dst.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [*launch.runner, "tar", "-C", str(src), "-cf", "-", "."], stdout=subprocess.PIPE
    )
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
        for member in tf:
            if member.isfile() or member.isdir():
                with contextlib.suppress(tarfile.FilterError, OSError):
                    tf.extract(member, dst, filter="data")
    proc.wait()


_INSPECT = r"""
import hashlib, json, os, sqlite3, sys
home, work = sys.argv[1], sys.argv[2]
out = {"hashes": {}, "sessions": [], "usage": [], "system_prompt": "", "skills_dir": [],
       "children": []}
for base in (os.path.join(home, "skills"), os.path.join(home, "memories"),
             os.path.join(work, "skills"), os.path.join(home, "SOUL.md")):
    paths = [base] if os.path.isfile(base) else [
        os.path.join(d, f) for d, _, fs in os.walk(base) for f in fs]
    for p in paths:
        name = os.path.basename(p)
        if name.startswith(".") or name.endswith(".lock"):
            continue
        with open(p, "rb") as fh:
            out["hashes"][os.path.relpath(p, os.path.dirname(home))] = hashlib.sha256(fh.read()).hexdigest()
sk = os.path.join(home, "skills")
out["skills_dir"] = sorted(n for n in os.listdir(sk) if not n.startswith(".")) if os.path.isdir(sk) else []
db = os.path.join(home, "state.db")
if os.path.isfile(db):
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    keep = ("id", "parent_session_id", "source", "model", "end_reason", "message_count",
            "tool_call_count", "api_call_count", "input_tokens", "output_tokens",
            "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "estimated_cost_usd",
            "actual_cost_usd", "cost_status", "billing_provider", "cwd", "system_prompt_hash")
    for r in c.execute("SELECT * FROM sessions ORDER BY started_at"):
        out["sessions"].append({k: r[k] for k in keep if k in r.keys()})
    for r in c.execute("SELECT * FROM session_model_usage"):
        out["usage"].append(dict(r))
    root = next((s for s in out["sessions"] if not s.get("parent_session_id")), None)
    if root and root.get("system_prompt_hash"):
        row = c.execute("SELECT prompt FROM system_prompts WHERE hash = ?",
                        (root["system_prompt_hash"],)).fetchone()
        out["system_prompt"] = row[0] if row else ""
    for s in out["sessions"]:
        if s.get("parent_session_id"):
            row = c.execute("SELECT content FROM messages WHERE session_id = ? AND role = "
                            "'assistant' AND content IS NOT NULL AND content != '' ORDER BY id DESC "
                            "LIMIT 1", (s["id"],)).fetchone()
            out["children"].append({"id": s["id"], "final": (row[0] or "")[:4000] if row else ""})
print(json.dumps(out))
"""


def inspect_rollout(launch: Launch, rollout: Path) -> dict:
    """Harness file hashes, the home's skills/ listing and the state.db accounting, read as the
    runner user (a WAL-mode database needs a writable directory even to read)."""
    p = _as_runner(
        launch,
        [launch.python, "-I", "-c", _INSPECT, str(rollout / "home"), str(rollout / "work")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"error": (p.stderr or "no output").strip()[:500]}


def read_root_file(launch: Launch, path: Path) -> str:
    """A small file under the rollout root, read as the runner user; empty when absent."""
    p = _as_runner(launch, ["cat", str(path)], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def usage_summary(state: Mapping) -> dict:
    """Totals over every model call in the home: the rollout, its subagents, any auxiliary call."""
    usage = state.get("usage") or []
    est = sum(float(u.get("estimated_cost_usd") or 0) for u in usage)
    act = sum(float(u.get("actual_cost_usd") or 0) for u in usage)
    return {
        "cost_usd": (act or est) or None,
        "cost_source": "actual" if act else ("estimated" if est else "unknown"),
        "input_tokens": sum(int(u.get("input_tokens") or 0) for u in usage),
        "output_tokens": sum(int(u.get("output_tokens") or 0) for u in usage),
        "api_calls": sum(int(u.get("api_call_count") or 0) for u in usage),
        "auxiliary_tasks": sorted({u["task"] for u in usage if u.get("task")}),
        "sessions": len(state.get("sessions") or []),
    }


def _hash_local(staged: Path) -> dict[str, str]:
    """The same digests `_INSPECT` takes, computed over the staged copy before the run."""
    out = {}
    for base in ("home/skills", "home/memories", "work/skills", "home/SOUL.md"):
        root = staged / base
        paths = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for p in paths:
            if p.name.startswith(".") or p.name.endswith(".lock"):
                continue
            out[str(p.relative_to(staged))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run_rollout(
    install: Install,
    run_dir: Path,
    prompt: str,
    *,
    model: str,
    timeout: int,
    provider: str | None = None,
    task_files: Path | None = None,
    hooks: Mapping | None = None,
    env: Mapping[str, str] | None = None,
    launch: Launch | None = None,
    extra_root_files: Mapping[str, str] | None = None,
    max_turns: int = MAX_TURNS,
) -> dict:
    """One `hermes chat -q` session in a fresh home under the rollout root.

    `run_dir` (the caller's) receives stream.jsonl, stderr.txt, workspace/ (a copy of the
    rollout's working directory), system_prompt.md and rollout.json. `hooks` are operator hooks
    in Hermes's flat shape; `env` is added to the rollout environment. The rollout itself stays
    under `launch.root` for audit.
    """
    launch = launch or Launch.from_config()
    check_root(launch.root)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    rollout = launch.root / f"{run_dir.name}-{os.urandom(3).hex()}"
    home, work = rollout / "home", rollout / "work"

    staged = Path(tempfile.mkdtemp(prefix="h2-hm-run-"))
    try:
        shutil.copytree(install.staging_dir, staged, dirs_exist_ok=True)
        if task_files is not None and Path(task_files).is_dir():
            shutil.copytree(task_files, staged / "work", dirs_exist_ok=True)
        (staged / "work").mkdir(exist_ok=True)
        (staged / "home" / "home").mkdir(parents=True, exist_ok=True)
        (staged / "bundled-skills").mkdir(exist_ok=True)
        tree_hooks = json.loads((staged / "tree-hooks.json").read_text(encoding="utf-8") or "{}")
        cfg = floor_config(
            work=work,
            model=model,
            provider=provider,
            hooks=merge_hooks(hooks, tree_hooks),
            providers=launch.providers,
        )
        (staged / "home" / "config.yaml").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (staged / "task.md").write_text(prompt, encoding="utf-8")
        for rel, body in (extra_root_files or {}).items():
            p = staged / HT.normalize_rel(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        before = _hash_local(staged)
        put_tree(launch, staged, rollout)
    finally:
        shutil.rmtree(staged, ignore_errors=True)

    rollout_env = _rollout_env(
        launch,
        {
            **(env or {}),
            "HOME": str(home / "home"),
            "HERMES_HOME": str(home),
            "TERMINAL_CWD": str(work),
            "TERMINAL_HOME_MODE": "profile",
            "HERMES_ACCEPT_HOOKS": "1",
            "HERMES_BUNDLED_SKILLS": str(rollout / "bundled-skills"),
        },
    )
    argv = [
        *launch.hermes,
        "chat",
        "--query-file",
        str(rollout / "task.md"),
        "-Q",
        "--format",
        "stream-json",
        "-m",
        model,
        *(["--provider", provider] if provider else []),
        "-t",
        TOOLSETS,
        "--max-turns",
        str(max_turns),
        "--run-budget",
        str(int(timeout)),
    ]
    stream = run_dir / "stream.jsonl"
    pidfile = rollout / "rollout.pid"
    t0 = time.time()
    timed_out = False
    returncode = None
    try:
        with stream.open("w") as out, (run_dir / "stderr.txt").open("w") as err:
            try:
                returncode = _runner(
                    launch,
                    argv,
                    env=rollout_env,
                    cwd=str(work),
                    timeout=int(timeout) + WALL_SLACK_S,
                    stdout=out,
                    stderr=err,
                    pidfile=str(pidfile),
                ).returncode
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        # Background children outlive the session otherwise, still writing the workspace.
        pid = _as_runner(launch, ["cat", str(pidfile)], capture_output=True, text=True).stdout
        if pid.strip().isdigit():
            _as_runner(launch, ["kill", "-KILL", "--", f"-{pid.strip()}"], capture_output=True)
        get_tree(launch, work, run_dir / "workspace")
        state = inspect_rollout(launch, rollout)
        if state.get("system_prompt"):
            (run_dir / "system_prompt.md").write_text(state["system_prompt"], encoding="utf-8")
        after = state.get("hashes") or {}
        record = {
            "returncode": returncode,
            "timed_out": timed_out,
            "wall_s": round(time.time() - t0, 1),
            "model": model,
            "provider": provider,
            "rollout_root": str(rollout),
            "harness_mutated": sorted(
                k for k in set(before) | set(after) if before.get(k) != after.get(k)
            ),
            "home_skills": state.get("skills_dir", []),
            **usage_summary(state),
            **result_of(stream),
        }
        if state.get("error"):
            record["inspect_error"] = state["error"]
        (run_dir / "rollout.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


_TRUNC_FMT = "…(+{n} chars - render truncation)"


def _clip(s, n: int) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\x00", "")
    if n <= 0 or len(s) <= n:
        return s
    return s[:n] + _TRUNC_FMT.format(n=len(s) - n)


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
        with contextlib.suppress(json.JSONDecodeError):
            ev = json.loads(ln)
            if isinstance(ev, dict):
                events.append(ev)
    return events


def result_of(path: Path) -> dict:
    """The final `result` event, or an error record when the stream has none."""
    events = parse_stream(path)
    for ev in reversed(events):
        if ev.get("type") == "result":
            tokens = ev.get("tokens") if isinstance(ev.get("tokens"), dict) else {}
            return {
                "exit_code": ev.get("exit_code"),
                "is_error": bool(ev.get("exit_code")) or bool(ev.get("error")),
                "error": ev.get("error"),
                "session_id": ev.get("session_id"),
                "num_tool_calls": sum(1 for e in events if e.get("type") == "tool_use"),
                "stream_tokens": tokens,
                "result": ev.get("text") if isinstance(ev.get("text"), str) else "",
            }
    return {"exit_code": None, "is_error": True, "num_tool_calls": 0, "result": ""}


def final_message(path: Path) -> str:
    return result_of(path)["result"]


def _shown_input(name: str, inp) -> str:
    if isinstance(inp, dict) and name == "terminal" and isinstance(inp.get("command"), str):
        return inp["command"]
    return inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False)


def render_stream(path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 2000) -> str:
    """Render a `hermes chat -q --format stream-json` capture into the shared grammar."""
    lines: list[str] = []
    text: list[str] = []

    def flush() -> None:
        if "".join(text).strip():
            lines.append(f"[ASSISTANT] {_clip(''.join(text).strip(), obs_trunc)}")
        text.clear()

    for ev in parse_stream(Path(path)):
        et = ev.get("type")
        if et == "_read_error":
            return f"(failed to read trajectory: {ev.get('message')})"
        if et == "text":
            text.append(str(ev.get("text") or ""))
            continue
        flush()
        if et == "system" and ev.get("subtype") == "init":
            lines.append(f"[HARNESS] session: model={ev.get('model')}")
        elif et == "tool_use":
            name = ev.get("name")
            lines.append(
                f"[ACTION] {name}: {_clip(_shown_input(name, ev.get('input')), args_trunc)}"
            )
        elif et == "tool_result":
            tag = "OBSERVATION ERROR" if ev.get("is_error") else "OBSERVATION"
            lines.append(f"[{tag}] {_clip(ev.get('output'), obs_trunc)}")
        elif et == "result":
            if ev.get("exit_code") or ev.get("error"):
                lines.append(f"[ERROR] exit {ev.get('exit_code')}: {_clip(ev.get('error'), 1000)}")
            tokens = ev.get("tokens") or {}
            lines.append(
                f"[HARNESS] result: exit={ev.get('exit_code')} | tokens in={tokens.get('input')} "
                f"out={tokens.get('output')} | duration_ms={ev.get('duration_ms')}"
            )
    flush()
    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=len(rendered) - max_chars)
    return rendered


__all__ = [
    "HERMES_SURFACE",
    "HermesSubstrate",
    "INSTALL_MODE",
    "Launch",
    "final_message",
    "floor_config",
    "render_stream",
    "result_of",
    "run_rollout",
]
