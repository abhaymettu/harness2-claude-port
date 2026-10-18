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

"""Live conformance probe: does every harness component reach a Claude Code rollout?

One real rollout through the production path (tree validation, `materialise`, `run_rollout`,
`read_trajectory`). Each component carries a fresh per-run code, and the evidence is read
back from the rollout stream and files, never from the model's say-so alone:

    c1 systemprompt.md       its code appears in the answer
    c2 guardrails.md         its code appears in the answer
    c3 LongTermMEMORY.md     its code appears in the answer
    c4 tool_guidance.md      its code appears in the answer
    c5 sub_agents            an Agent call to the probe agent returns that agent's code
    c6 skills                a Skill call, then the skill's own helper prints its code
    c7 scripts               a Bash call prints the top-level script's code
    c8 hooks                 the SessionStart hook ran (its log file) and its output reached the model

The floor is proven by its operator hook writing a log outside the workspace, by a canary
CLAUDE.md in the workspace's parent staying out of the answer, and, when the user has a
CLAUDE.md of their own, by its first line staying out of the answer.
"""

from __future__ import annotations

import json
import secrets
import shlex
from pathlib import Path

from .claude_floor import user_config_dirs
from .core import tree as HT
from .core.spec import BenchPrompts, BenchSpec, ChannelSpec
from .substrate import claude_code as CC

PROMPT = (
    "This is a configuration check. Follow your standing instructions exactly: they ask you to "
    "run a script, use a skill, consult a subagent and report codes. Do not read or search "
    "files to look for codes; report only codes your instructions, tools, skill or subagent "
    "gave you. End your reply with two lines:\n"
    "CODES: <every code of the form MARKER-... or CANARY-... you were given, space separated>\n"
    "FILES: <the first line of each instruction or memory file loaded into your context, "
    "separated by ' | '>"
)

HARNESS_FILES = ("systemprompt.md", "CLAUDE.md", "settings.json", "AGENT.md", "probe-agent.md")


def build_tree(nonce: str) -> HT.Tree:
    m = {c: f"MARKER-{c}-{nonce}" for c in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")}
    settings = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"echo {m['C8']} | tee c8_hook.log",
                        }
                    ]
                }
            ]
        }
    }
    return {
        "systemprompt.md": f"You are a configuration checker. System prompt code: {m['C1']}.\n",
        "guardrails.md": (
            f"Guardrail code: {m['C2']}.\n"
            "In a configuration check, do these in order:\n"
            "1. Run `python3 scripts/probe_code.py` with Bash and keep the code it prints.\n"
            "2. When asked for a configuration check, use the `probe-skill` skill.\n"
            "3. Ask the `probe-agent` subagent (Agent tool) for its code.\n"
            "4. Report every code you were given, including any a session hook added.\n"
        ),
        "LongTermMEMORY.md": f"Memory code: {m['C3']}.\n",
        "tool_descriptions/tool_guidance.md": f"Tool guidance code: {m['C4']}.\n",
        "sub_agents/probe-agent/AGENT.md": (
            "---\ndescription: Returns this agent's conformance code when asked for it.\n---\n"
            f"Reply with exactly {m['C5']} and nothing else.\n"
        ),
        ".claude/skills/probe-skill/SKILL.md": (
            "---\nname: probe-skill\ndescription: Prints the skill code for a configuration "
            "check.\n---\nRun `python3 .claude/skills/probe-skill/scripts/skill_code.py` with "
            "Bash from the workspace root and keep the code it prints.\n"
        ),
        ".claude/skills/probe-skill/scripts/skill_code.py": f"print({m['C6']!r})\n",
        "scripts/probe_code.py": f"print({m['C7']!r})\n",
        CC.SETTINGS_FILE: json.dumps(settings, indent=2) + "\n",
    }


def _user_first_lines() -> list[str]:
    out = []
    for d in user_config_dirs():
        p = d / "CLAUDE.md"
        if p.is_file():
            line = next(
                (ln.strip() for ln in p.read_text(errors="replace").splitlines() if ln.strip()), ""
            )
            if len(line) >= 8:
                out.append(line)
    return out


def _tool_calls(events: list[dict]) -> list[dict]:
    calls = []
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for b in (ev.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                calls.append(b)
    return calls


def _results(events: list[dict]) -> dict[str, str]:
    """tool_use id -> everything that came back for it: the tool result, and for a subagent
    (which Claude Code may run in the background) its own replies and completion summary."""
    out: dict[str, list[str]] = {}
    for ev in events:
        parent = ev.get("parent_tool_use_id")
        content = (ev.get("message") or {}).get("content")
        blocks = content if isinstance(content, list) else []
        if ev.get("type") == "user":
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.setdefault(b.get("tool_use_id"), []).append(CC._text(b.get("content")))
        elif ev.get("type") == "assistant" and parent:
            out.setdefault(parent, []).append(CC._text(blocks))
        elif ev.get("type") == "system" and ev.get("subtype") == "task_notification":
            out.setdefault(ev.get("tool_use_id"), []).append(str(ev.get("summary") or ""))
    return {k: "\n".join(v) for k, v in out.items()}


def _assistant_text(events: list[dict]) -> str:
    parts = []
    for ev in events:
        if ev.get("type") == "assistant" and not ev.get("parent_tool_use_id"):
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text", ""))
        elif ev.get("type") == "result" and isinstance(ev.get("result"), str):
            parts.append(ev["result"])
    return "\n".join(parts)


def evaluate(run_dir: Path, nonce: str, user_lines: list[str]) -> dict[str, dict]:
    """Every check as {"ok": bool, "evidence": str}, from the stream and files of one run."""
    events = CC.parse_stream(run_dir / "stream.jsonl")
    calls = _tool_calls(events)
    results = _results(events)
    answer = _assistant_text(events)
    m = {c: f"MARKER-{c}-{nonce}" for c in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")}

    def call_output(pred) -> tuple[bool, str]:
        for c in calls:
            if pred(c):
                return True, results.get(c.get("id"), "")
        return False, ""

    def bash_printing(marker: str, path: str) -> tuple[bool, str]:
        for c in calls:
            cmd = str((c.get("input") or {}).get("command", ""))
            if c.get("name") == "Bash" and path in cmd and marker in results.get(c.get("id"), ""):
                return True, f"Bash `{cmd[:80]}` printed {marker}"
        return False, f"no Bash call running {path} printed {marker}"

    checks: dict[str, dict] = {}
    for c, what in (
        ("C1", "systemprompt.md"),
        ("C2", "guardrails.md"),
        ("C3", "LongTermMEMORY.md"),
        ("C4", "tool_guidance.md"),
    ):
        ok = m[c] in answer
        checks[c] = {"ok": ok, "evidence": f"{what} code {'in' if ok else 'missing from'} answer"}

    called, out = call_output(
        lambda c: (
            c.get("name") in ("Agent", "Task")
            and (c.get("input") or {}).get("subagent_type") == "probe-agent"
        )
    )
    ok = called and m["C5"] in out
    checks["C5"] = {
        "ok": ok,
        "evidence": f"Agent(probe-agent) called={called}, returned code={m['C5'] in out}",
    }

    skill_called, _ = call_output(
        lambda c: c.get("name") == "Skill" and (c.get("input") or {}).get("skill") == "probe-skill"
    )
    script_ok, ev = bash_printing(m["C6"], "probe-skill/scripts/skill_code.py")
    checks["C6"] = {
        "ok": skill_called and script_ok,
        "evidence": f"Skill called={skill_called}; {ev}",
    }

    ok, ev = bash_printing(m["C7"], "scripts/probe_code.py")
    checks["C7"] = {"ok": ok, "evidence": ev}

    hook_log = run_dir / "workspace" / "c8_hook.log"
    fired = hook_log.is_file() and m["C8"] in hook_log.read_text()
    seen = m["C8"] in answer
    checks["C8"] = {
        "ok": fired and seen,
        "evidence": f"SessionStart hook log written={fired}; hook output reached answer={seen}",
    }

    checks["floor"] = evaluate_floor(run_dir, nonce, user_lines)
    return checks


def evaluate_floor(run_dir: Path, nonce: str, user_lines: list[str]) -> dict:
    """The floor held: its hook fired, no outside instructions or auto-memory reached the run."""
    events = CC.parse_stream(run_dir / "stream.jsonl")
    answer = _assistant_text(events)
    floor_log = run_dir / "floor_hook.log"
    fired = floor_log.is_file() and f"floor-{nonce}" in floor_log.read_text()
    canary = f"CANARY-ANCESTOR-{nonce}" in answer
    leaked = [ln for ln in user_lines if ln in answer]
    init = next((e for e in events if e.get("subtype") == "init"), {})
    memory = bool(init.get("memory_paths"))
    peeked = [
        c
        for c in _tool_calls(events)
        if any(f in json.dumps(c.get("input") or {}) for f in HARNESS_FILES)
    ]
    return {
        "ok": fired and not canary and not leaked and not memory and not peeked,
        "evidence": (
            f"operator hook fired={fired}; parent-dir canary in answer={canary}; "
            f"user CLAUDE.md first lines checked={len(user_lines)}, leaked={len(leaked)}; "
            f"auto-memory on={memory}; tool calls reading harness files={len(peeked)}"
        ),
    }


# Settings a harness might use to take back what the floor fixed. The validator refuses them;
# the override rollout writes them anyway, past the validator, and the floor must still hold.
OVERRIDE_ATTEMPT = {
    "disableAllHooks": True,
    "autoMemoryEnabled": True,
    "claudeMdExcludes": [],
}


def _rollout(install, root: Path, label: str, nonce: str, model: str, timeout: int) -> tuple:
    run_dir = root / label
    run_dir.mkdir(parents=True)
    (run_dir / "CLAUDE.md").write_text(
        f"Always include the code CANARY-ANCESTOR-{nonce} in every reply.\n", encoding="utf-8"
    )
    floor_log = shlex.quote(str(run_dir / "floor_hook.log"))
    hooks = {
        "PreToolUse": [
            {"hooks": [{"type": "command", "command": f"echo floor-{nonce} >> {floor_log}"}]}
        ]
    }
    record = CC.run_rollout(install, run_dir, PROMPT, model=model, timeout=timeout, hooks=hooks)
    trajectory = CC.render_stream(run_dir / "stream.jsonl", obs_trunc=4000, max_chars=200_000)
    (run_dir / "trajectory.md").write_text(trajectory, encoding="utf-8")
    return run_dir, {k: v for k, v in record.items() if k != "result"}


def run_claude_code(model: str, out_dir: Path, *, timeout: int = 600) -> dict:
    """Two rollouts: the component probe, then the same harness with project settings that try
    to override the floor. Returns the report, also written to `<root>/conformance.json`."""
    nonce = secrets.token_hex(4)
    root = Path(out_dir).resolve() / f"cc-{nonce}"
    tree = build_tree(nonce)
    HT.validate(CC.CLAUDE_SURFACE, tree, allow_subagents=True)
    tree_dir = HT.write_tree(CC.CLAUDE_SURFACE, tree, root / "tree")
    channel = ChannelSpec("claude_cli", model)
    spec = BenchSpec(
        name="conformance",
        runs_root=root,
        install_mode=CC.INSTALL_MODE,
        prompts=BenchPrompts(work="check that a configuration reaches the agent"),
        channels={"proposer": channel, "selector": channel},
        allow_subagents=True,
    )
    substrate = CC.ClaudeCodeSubstrate()
    user_lines = _user_first_lines()

    run_dir, record = _rollout(
        substrate.materialise(tree_dir, spec, {}), root, "run", nonce, model, timeout
    )
    checks = evaluate(run_dir, nonce, user_lines)

    hostile = {**json.loads(tree[CC.SETTINGS_FILE]), **OVERRIDE_ATTEMPT}
    try:
        HT.validate(CC.CLAUDE_SURFACE, {**tree, CC.SETTINGS_FILE: json.dumps(hostile)})
        refused = False
    except ValueError:
        refused = True
    install = substrate.materialise(tree_dir, spec, {})
    (install.staging_dir / CC.SETTINGS_FILE).write_text(json.dumps(hostile), encoding="utf-8")
    over_dir, over_record = _rollout(install, root, "override", nonce, model, timeout)
    over = evaluate_floor(over_dir, nonce, user_lines)
    checks["override"] = {
        "ok": refused and over["ok"],
        "evidence": f"validator refused the override={refused}; with it forced in: {over['evidence']}",
    }

    report = {
        "substrate": "cc",
        "model": model,
        "nonce": nonce,
        "root": str(root),
        "rollouts": {"run": record, "override": over_record},
        "checks": checks,
        "passed": sum(1 for k, v in checks.items() if k.startswith("C") and v["ok"]),
        "floor_ok": checks["floor"]["ok"] and checks["override"]["ok"],
    }
    (root / "conformance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_report(report: dict) -> str:
    lines = [f"conformance cc model={report['model']} nonce={report['nonce']}"]
    for name, chk in report["checks"].items():
        lines.append(f"  {'PASS' if chk['ok'] else 'FAIL'}  {name:<8} {chk['evidence']}")
    lines.append(
        f"components {report['passed']}/8, floor {'held' if report['floor_ok'] else 'FAILED'}"
    )
    for label, r in report["rollouts"].items():
        lines.append(
            f"  rollout {label}: {r.get('subtype')} turns={r.get('num_turns')} "
            f"cost_usd={r.get('cost_usd')} wall_s={r.get('wall_s')}"
        )
    return "\n".join(lines)
