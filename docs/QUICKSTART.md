# Quick start

This file is added by The harness2-ports Authors. It holds the install and run steps that the
[README](../README.md) leaves out, for the Claude Code executor (`--substrate cc`). For the
upstream benchmarks and their requirements, see the [setup guide](SETUP.md).

## Install

Use **Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/)**.
From the repository root:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e '.[render]'
harness2-demo --output runs/demo --k 2
```

The local demo runs both recursion modes with deterministic editors and needs
no model credentials.

The Claude Code executor needs the **`claude` CLI** (tested on Claude Code
2.1.301 on macOS) and a Claude Code login, subscription or API key; that one
login covers rollouts and improvers. Google Cloud is optional
(`HARNESS2_CLAUDE_VIA_VERTEX=1`). The localbench read boundary uses macOS
`sandbox-exec`; see [localbench](#localbench) for running elsewhere. For the
upstream benchmarks, see the [setup guide](SETUP.md).

## First run

Check that every component reaches a rollout and that the floor holds, then run
and judge two localbench tasks:

```bash
export HARNESS2_CLAUDE_MODEL=claude-haiku-5-5
harness2-check --substrate cc --conformance
harness2 --bench local --substrate cc --k 1 --only-domains data-cleaning --max-tasks 2
harness2-judge --bench local --substrate cc --k 1
```

The conformance probe runs two rollouts and prints one line per component (C1
to C8), the floor line and the override line. Judging must use the same
benchmark, subset, `--k` and seed as the refinement run. Model-backed runs
incur costs at list price as Claude Code reports them.

## The Claude Code executor

`--substrate cc` runs each rollout as a headless Claude Code session in a fresh
workspace built from the harness. The improver sessions (editor, composer,
reflector) use the `claude_cli` channel, so a Claude Code login, subscription
or API key, is all either needs.

| Variable | Meaning |
|---|---|
| `HARNESS2_CLAUDE_MODEL` | Executor model, for example `claude-haiku-5-5` |
| `HARNESS2_IMPROVER_MODEL` | Improver model on the `claude_cli` channel; localbench defaults to `claude-opus-5-5` |

Every session, rollouts and improvers alike, also gets a floor through
`--settings` that no harness edit reaches. It excludes your user-level
`CLAUDE.md` and every `CLAUDE.md` in a parent directory, turns auto-memory off,
keeps hooks on, denies tools whose effects outlive the session (schedules,
remote triggers, notifications), and adds the operator's hooks. Sessions run
with `--setting-sources project --strict-mcp-config --no-session-persistence`,
and with permission prompts skipped (`--dangerously-skip-permissions`). A
session runs as you and can read what you can, so run untrusted tasks in a
container or as a separate user.

### Where each component lands

Under `--substrate cc`, each one lands in a real Claude Code surface:

| Component | In the rollout |
|---|---|
| System prompt | `.claude/systemprompt.md`, passed with `--append-system-prompt-file` |
| Guardrails, memory, tool guidance | The workspace `CLAUDE.md` |
| Skills | `.claude/skills/<name>/SKILL.md` |
| Scripts | `scripts/` |
| Subagents | `.claude/agents/<name>.md`, run on the executor model |
| Plugins | Hooks in `.claude/settings.json`; no other settings key is accepted |

## localbench

`--bench local` is a small suite for checking the executor end to end: 12 tasks
in 3 domains (data cleaning, document-to-table extraction, a small repository
bugfix), each with a deterministic checker, so it needs no judge model, Docker
or cloud project. The checkers live in `localbench/tasks/<task>/grader/`,
outside every workspace and model context.

On macOS every localbench session, rollouts and improvers alike, runs under
`sandbox-exec`, enforced by the kernel for the whole process tree. A session
cannot read, write or rename anything under `localbench/tasks/`, the checkout's
`.git` (which holds every checker as a blob) or Claude Code's session
transcripts, cannot read or write the run state under `runs/` (scores, other
rollouts' outputs) outside its own directory, and cannot reach a tmux server or
send Apple Events, through which it could ask a process outside the sandbox to
read for it. Links are dropped from a workspace before it is scored. Copies of
a checker made elsewhere on the machine are outside the boundary, so run
untrusted executors as a separate user or in a container. Elsewhere set
`HARNESS2_GRADER_BOUNDARY=off` and run where `localbench/tasks/` is not
mounted; the only guard left is then a floor hook that refuses tool calls
naming the tasks, and it matches strings.

## Results and resume

Results are saved under `runs/`, organized by benchmark and subset where
applicable. They include task summaries, deliverables, adopted harnesses,
reflection notes, and evaluation results.

Repeat the same command to resume. Use a new `HARNESS2_RUNS_DIR` when changing
models or task selection. See [results and resume](EXPERIMENTS.md#results-and-resume)
for details; each command also supports `--help`.

