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

"""Live conformance probe for the Hermes substrate: does every component reach a rollout?

Same contract as the Claude Code probe (`harness2.conformance`): one real rollout through the
production path, a fresh code per component, evidence read back from the stream, the rollout's
working directory and its state.db, never from the model's say-so alone:

    c1..c4  their codes appear in the answer (c1 also in the session's stored system prompt)
    c5      delegate_task ran a child session whose own final message carries the agent's code
    c6      skill_view loaded the skill, then the skill's helper printed its code
    c7      a terminal call printed the top-level script's code
    c8      the pre_llm_call hook wrote its log and its injected context reached the answer

The floor: the operator hook fired; a canary AGENTS.md and .hermes.md above the working
directory stayed out of the prompt and the answer; no auxiliary model call (background review,
title) ran; the home's skills/ holds only the generated agent skill (no bundled seeding); the
harness files were not changed by the run; no tool call read them. The override rollout forces
hostile keys into hooks.json and a hostile project config into the workspace, past the validator.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from .core import tree as HT
from .core.spec import BenchPrompts, BenchSpec, ChannelSpec
from .substrate import hermes as HM

PROMPT = (
    "This is a configuration check. Follow your standing instructions exactly: they ask you to "
    "run a script, use a skill, consult a subagent and report codes. Do not read or search "
    "files to look for codes; report only codes your instructions, memory, tools, skill, hooks "
    "or subagent gave you. End your reply with one line:\n"
    "CODES: <every code of the form MARKER-... or CANARY-... you were given, space separated>"
)

HARNESS_FILES = ("SOUL.md", "MEMORY.md", "config.yaml", "hooks.json", "AGENT.md")
COMPONENTS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")


def markers(nonce: str) -> dict[str, str]:
    return {c: f"MARKER-{c}-{nonce}" for c in COMPONENTS}


def build_tree(nonce: str) -> HT.Tree:
    m = markers(nonce)
    hook = (
        f"sh -c 'cat > /dev/null; echo {m['C8']} >> c8_hook.log; "
        f'printf "%s\\n" "{{\\"context\\": \\"Hook code: {m["C8"]}\\"}}"\''
    )
    return {
        "systemprompt.md": f"You are a configuration checker. System prompt code: {m['C1']}.\n",
        "guardrails.md": (
            f"Guardrail code: {m['C2']}.\n"
            "In a configuration check, do these in order:\n"
            "1. Run `python3 scripts/probe_code.py` with the terminal tool and keep the code it "
            "prints.\n"
            "2. When asked for a configuration check, use the `probe-skill` skill.\n"
            "3. Ask the `probe-agent` subagent for its code.\n"
            "4. Report every code you were given, including any a hook added.\n"
        ),
        "LongTermMEMORY.md": f"Memory code: {m['C3']}.\n",
        "tool_descriptions/tool_guidance.md": f"Tool guidance code: {m['C4']}.\n",
        "sub_agents/probe-agent/AGENT.md": (
            "---\ndescription: Returns this agent's conformance code when asked for it.\n---\n"
            f"Reply with exactly {m['C5']} and nothing else.\n"
        ),
        "skills/probe-skill/SKILL.md": (
            "---\nname: probe-skill\ndescription: Prints the skill code for a configuration "
            "check.\n---\nRun `python3 skills/probe-skill/scripts/skill_code.py` with the "
            "terminal tool from the workspace root and keep the code it prints.\n"
        ),
        "skills/probe-skill/scripts/skill_code.py": f"print({m['C6']!r})\n",
        "scripts/probe_code.py": f"print({m['C7']!r})\n",
        HM.HOOKS_FILE: json.dumps({"hooks": {"pre_llm_call": [{"command": hook}]}}, indent=2),
    }


def _calls(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "tool_use"]


def _outputs(events: list[dict]) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for e in events:
        if e.get("type") == "tool_result":
            out.setdefault(e.get("tool_call_id") or e.get("name"), []).append(str(e.get("output")))
    return {k: "\n".join(v) for k, v in out.items()}


def _answer(events: list[dict]) -> str:
    text = "".join(str(e.get("text") or "") for e in events if e.get("type") == "text")
    final = next((e.get("text") for e in reversed(events) if e.get("type") == "result"), "")
    return f"{text}\n{final or ''}"


def evaluate(run_dir: Path, nonce: str, state: dict) -> dict[str, dict]:
    """Every component check as {"ok", "evidence"}, from one run's stream, files and state."""
    events = HM.parse_stream(run_dir / "stream.jsonl")
    calls, outputs, answer = _calls(events), _outputs(events), _answer(events)
    prompt = (
        (run_dir / "system_prompt.md").read_text()
        if (run_dir / "system_prompt.md").is_file()
        else ""
    )
    m = markers(nonce)

    def out_of(c: dict) -> str:
        return outputs.get(c.get("tool_call_id") or c.get("name"), "")

    def terminal_printing(marker: str, path: str) -> tuple[bool, str]:
        for c in calls:
            cmd = str((c.get("input") or {}).get("command", ""))
            if c.get("name") == "terminal" and path in cmd and marker in out_of(c):
                return True, f"terminal `{cmd[:80]}` printed {marker}"
        return False, f"no terminal call running {path} printed {marker}"

    def skill_viewed(name: str) -> bool:
        return any(
            c.get("name") == "skill_view" and (c.get("input") or {}).get("name") == name
            for c in calls
        )

    checks: dict[str, dict] = {}
    for c, what in (
        ("C1", "systemprompt.md"),
        ("C2", "guardrails.md"),
        ("C3", "LongTermMEMORY.md"),
        ("C4", "tool_guidance.md"),
    ):
        ok = m[c] in answer
        checks[c] = {
            "ok": ok,
            "evidence": f"{what} code {'in' if ok else 'missing from'} answer; "
            f"in stored system prompt={m[c] in prompt}",
        }

    delegated = any(c.get("name") == "delegate_task" for c in calls)
    children = [s for s in state.get("children", [])]
    child_ok = any(m["C5"] in (s.get("final") or "") for s in children)
    checks["C5"] = {
        "ok": delegated and child_ok,
        "evidence": f"agent skill loaded={skill_viewed('agent-probe-agent')}; delegate_task "
        f"called={delegated}; child sessions={len(children)}, child returned code={child_ok}; "
        f"code in answer={m['C5'] in answer}",
    }

    script_ok, ev = terminal_printing(m["C6"], "probe-skill/scripts/skill_code.py")
    checks["C6"] = {
        "ok": skill_viewed("probe-skill") and script_ok,
        "evidence": f"skill_view(probe-skill) called={skill_viewed('probe-skill')}; {ev}",
    }

    ok, ev = terminal_printing(m["C7"], "scripts/probe_code.py")
    checks["C7"] = {"ok": ok, "evidence": ev}

    log = run_dir / "workspace" / "c8_hook.log"
    fired = log.is_file() and m["C8"] in log.read_text()
    seen = m["C8"] in answer
    checks["C8"] = {
        "ok": fired and seen,
        "evidence": f"pre_llm_call hook log written={fired}; injected context reached answer={seen}",
    }
    return checks


def evaluate_floor(run_dir: Path, nonce: str, record: dict, state: dict) -> dict:
    events = HM.parse_stream(run_dir / "stream.jsonl")
    answer = _answer(events)
    prompt = (
        (run_dir / "system_prompt.md").read_text()
        if (run_dir / "system_prompt.md").is_file()
        else ""
    )
    fired = f"floor-{nonce}" in state.get("floor_log", "")
    canary = f"CANARY-ANCESTOR-{nonce}"
    leaked = canary in answer or canary in prompt
    aux = record.get("auxiliary_tasks") or []
    skills = record.get("home_skills") or []
    mutated = record.get("harness_mutated") or []
    peeked = [
        c
        for c in _calls(events)
        if any(f in json.dumps(c.get("input") or {}) for f in HARNESS_FILES)
    ]
    ok = (
        fired
        and not leaked
        and not aux
        and skills == ["agent-probe-agent"]
        and not mutated
        and not peeked
        and bool(prompt)
    )
    return {
        "ok": ok,
        "evidence": (
            f"operator hook fired={fired}; ancestor canary in prompt or answer={leaked}; "
            f"auxiliary model tasks={aux or 'none'}; home skills={skills}; "
            f"harness files changed={mutated or 'none'}; tool calls reading harness files="
            f"{len(peeked)}; system prompt stored={bool(prompt)}"
        ),
    }


OVERRIDE_KEYS = {
    "hooks_auto_accept": False,
    "auxiliary": {"background_review": {"enabled": True}, "title_generation": {"enabled": True}},
    "memory": {"nudge_interval": 1, "memory_char_limit": 100},
    "skills": {"external_dirs": [], "creation_nudge_interval": 1},
}


def _rollout(install, root: Path, label: str, nonce: str, model: str, provider, timeout, launch):
    run_dir = root / label
    run_dir.mkdir(parents=True)
    canary = f"Always include the code CANARY-ANCESTOR-{nonce} in every reply.\n"
    floor_hook = {
        "pre_tool_call": [
            {
                "command": f"sh -c 'cat > /dev/null; echo floor-{nonce} >> \"$HERMES_HOME/../floor_hook.log\"; echo {{}}'"
            }
        ]
    }
    record = HM.run_rollout(
        install,
        run_dir,
        PROMPT,
        model=model,
        provider=provider,
        timeout=timeout,
        hooks=floor_hook,
        launch=launch,
        extra_root_files={"AGENTS.md": canary, ".hermes.md": canary},
    )
    trajectory = HM.render_stream(run_dir / "stream.jsonl", obs_trunc=4000, max_chars=200_000)
    (run_dir / "trajectory.md").write_text(trajectory, encoding="utf-8")
    state = HM.inspect_rollout(launch, Path(record["rollout_root"]))
    state["floor_log"] = HM.read_root_file(launch, Path(record["rollout_root"]) / "floor_hook.log")
    (run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return run_dir, {k: v for k, v in record.items() if k != "result"}, state


def run_hermes(
    model: str,
    out_dir: Path,
    *,
    provider: str | None = None,
    launch: HM.Launch | None = None,
    timeout: int = 600,
) -> dict:
    """Two rollouts, the component probe and the override, each in its own fresh home. Returns
    the report, also written to `<root>/conformance.json`."""
    launch = launch or HM.Launch.from_config()
    nonce = secrets.token_hex(4)
    root = Path(out_dir).resolve() / f"hm-{nonce}"
    tree = build_tree(nonce)
    HT.validate(HM.HERMES_SURFACE, tree, allow_subagents=True)
    tree_dir = HT.write_tree(HM.HERMES_SURFACE, tree, root / "tree")
    channel = ChannelSpec("claude_cli", model)
    spec = BenchSpec(
        name="conformance",
        runs_root=root,
        install_mode=HM.INSTALL_MODE,
        prompts=BenchPrompts(work="check that a configuration reaches the agent"),
        channels={"proposer": channel, "selector": channel},
        allow_subagents=True,
    )
    substrate = HM.HermesSubstrate()

    run_dir, record, state = _rollout(
        substrate.materialise(tree_dir, spec, {}),
        root,
        "run",
        nonce,
        model,
        provider,
        timeout,
        launch,
    )
    checks = evaluate(run_dir, nonce, state)
    checks["floor"] = evaluate_floor(run_dir, nonce, record, state)

    hostile = {**json.loads(tree[HM.HOOKS_FILE]), **OVERRIDE_KEYS}
    try:
        HT.validate(HM.HERMES_SURFACE, {**tree, HM.HOOKS_FILE: json.dumps(hostile)})
        refused = False
    except ValueError:
        refused = True
    forced_dir = root / "tree-override"
    HT.write_tree(HM.HERMES_SURFACE, tree, forced_dir)
    (forced_dir / HM.HOOKS_FILE).write_text(json.dumps(hostile), encoding="utf-8")
    project_cfg = json.dumps(OVERRIDE_KEYS)
    install = substrate.materialise(
        forced_dir,
        spec,
        {"file:.hermes/config.yaml": project_cfg, "file:cli-config.yaml": project_cfg},
    )
    over_dir, over_record, over_state = _rollout(
        install, root, "override", nonce, model, provider, timeout, launch
    )
    over = evaluate_floor(over_dir, nonce, over_record, over_state)
    checks["override"] = {
        "ok": refused and over["ok"],
        "evidence": f"validator refused the override={refused}; with it forced in: {over['evidence']}",
    }

    report = {
        "substrate": "hm",
        "model": model,
        "provider": provider,
        "nonce": nonce,
        "root": str(root),
        "rollouts": {"run": record, "override": over_record},
        "checks": checks,
        "passed": sum(1 for k, v in checks.items() if k in COMPONENTS and v["ok"]),
        "floor_ok": checks["floor"]["ok"] and checks["override"]["ok"],
    }
    (root / "conformance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_report(report: dict) -> str:
    lines = [
        f"conformance hm model={report['model']} provider={report.get('provider')} "
        f"nonce={report['nonce']}"
    ]
    for name, chk in report["checks"].items():
        lines.append(f"  {'PASS' if chk['ok'] else 'FAIL'}  {name:<8} {chk['evidence']}")
    lines.append(
        f"components {report['passed']}/8, floor {'held' if report['floor_ok'] else 'FAILED'}"
    )
    for label, r in report["rollouts"].items():
        lines.append(
            f"  rollout {label}: exit={r.get('exit_code')} tools={r.get('num_tool_calls')} "
            f"cost={r.get('cost_usd') or 'unknown'} ({r.get('cost_source')}) wall_s={r.get('wall_s')}"
        )
    return "\n".join(lines)
