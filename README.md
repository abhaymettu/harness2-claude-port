# harness2-ports

Claude Code and Hermes Agent executors for [Harness²](https://github.com/google-research/harness2),
the recursive agent harnessing method from Google Research
([paper](https://arxiv.org/abs/2610.14224)). This is an independent port. It is not a Google
project and is not endorsed by the Harness² authors.

## What Harness² does

A harness is everything around a model that lets it work as an agent. Harness² splits it into
eight editable components: system prompt, guardrails, memory, tool guidance, subagents, skills,
scripts and plugins.

For each task, an executor runs the task under a starting harness. A harness editor proposes
edits, probes run the same task under each edited harness, and a composer builds a refined
harness from the differences between those runs. No ground-truth score is used. After the
task, a reflector keeps the adopted harness and the lessons the evidence supports in a
per-domain library that guides the next task in that domain. Model weights never change.

Upstream ships OpenCode and Codex executors and three benchmarks (JobBench, LAB and
WorkBuddy-Bench). This repository adds:

* `--substrate cc`, an executor that runs each rollout as a headless Claude Code session.
* `--substrate hm`, an executor that runs each rollout in a throwaway Hermes Agent home.
* `--bench local`, 12 small tasks with deterministic checkers, for checking an executor end to
  end without a judge model, Docker or a cloud project.
* An isolation floor that harness edits cannot change, a read boundary that keeps the
  checkers out of reach of the sessions being scored, and a pre-flight that scans the whole
  git history before publishing.

The core method code is upstream's. [UPSTREAM.md](UPSTREAM.md) lists every changed upstream
file and why.

## Install

Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/). From the
repository root:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e '.[render]'
harness2-demo --output runs/demo --k 2
```

The demo runs both recursion modes with deterministic editors and needs no model credentials.
The Claude Code executor needs the `claude` CLI and a Claude Code login (subscription or API
key). The Hermes executor needs the `hermes` CLI. The localbench read boundary uses macOS
`sandbox-exec`; see [localbench](#localbench) for running elsewhere.

## Claude Code executor

`--substrate cc` runs each rollout as a
headless Claude Code session (`claude -p`, tested on Claude Code 2.1.301 on macOS) in a fresh
workspace built from the harness. The improver sessions (editor, composer, reflector) use the
`claude_cli` channel, so a Claude Code login, subscription or API key, is all either needs.
Google Cloud is optional (`HARNESS2_CLAUDE_VIA_VERTEX=1`).

| Variable | Meaning |
|---|---|
| `HARNESS2_CLAUDE_MODEL` | Executor model, for example `claude-haiku-5-5` |
| `HARNESS2_IMPROVER_MODEL` | Improver model on the `claude_cli` channel; localbench defaults to `claude-opus-5-5` |

Check that every component reaches a rollout and that the floor holds, then run and judge two
localbench tasks:

```bash
export HARNESS2_CLAUDE_MODEL=claude-haiku-5-5
harness2-check --substrate cc --conformance
harness2 --bench local --substrate cc --k 1 --only-domains data-cleaning --max-tasks 2
harness2-judge --bench local --substrate cc --k 1
```

Where each component goes:

| Component | In the rollout |
|---|---|
| System prompt | `.claude/systemprompt.md`, passed with `--append-system-prompt-file` |
| Guardrails, memory, tool guidance | The workspace `CLAUDE.md` |
| Skills | `.claude/skills/<name>/SKILL.md` |
| Scripts | `scripts/` |
| Subagents | `.claude/agents/<name>.md`, run on the executor model |
| Plugins | Hooks in `.claude/settings.json`; no other settings key is accepted |

Every session, rollouts and improvers alike, also gets a floor through `--settings` that no
harness edit reaches. It excludes your user-level `CLAUDE.md` and every `CLAUDE.md` in a parent
directory, turns auto-memory off, keeps hooks on, denies tools whose effects outlive the session
(schedules, remote triggers, notifications), and adds the operator's hooks. Sessions run with
`--setting-sources project --strict-mcp-config --no-session-persistence`, and with permission
prompts skipped (`--dangerously-skip-permissions`). A session runs as you and can read what you can, so run
untrusted tasks in a container or as a separate user.

## localbench

`--bench local` is a small suite for
checking a substrate end to end: 12 tasks in 3 domains (data cleaning, document-to-table
extraction, a small repository bugfix), each with a deterministic checker, so it needs no judge
model, Docker or cloud project. The checkers live in `localbench/tasks/<task>/grader/`, outside
every workspace and model context.

On macOS every localbench session, rollouts and improvers alike, runs under `sandbox-exec`,
enforced by the kernel for the whole process tree. A session cannot read, write or rename
anything under `localbench/tasks/`, the checkout's `.git` (which holds every checker as a blob)
or Claude Code's session transcripts, cannot read or write the run state under `runs/` (scores,
other rollouts' outputs) outside its own directory, and cannot reach a tmux server or send
Apple Events, through which it could ask a process outside the sandbox to read for it. Links
are dropped from a workspace before it is scored. Copies of a checker made elsewhere on the
machine are outside the boundary, so run untrusted executors as a separate user or in a
container. A sudoers rule for `HARNESS2_HERMES_RUNNER` must also allow `/usr/bin/sandbox-exec`,
which the runner starts. Elsewhere set `HARNESS2_GRADER_BOUNDARY=off` and run where
`localbench/tasks/` is not mounted; the only guard left is then a floor hook that refuses tool
calls naming the tasks, and it matches strings.

## Hermes executor

`--substrate hm` runs rollouts on
[Hermes Agent](https://github.com/NousResearch/hermes-agent) (tested on v0.21.5). Each rollout
gets a fresh `HERMES_HOME` built from the harness and a fixed operator floor; your own Hermes
home, its `config.yaml`, memories, skills and `state.db` are never read. Settings come from the
environment:

| Variable | Meaning |
|---|---|
| `HARNESS2_HERMES_MODEL` | Executor model, for example `claude-haiku-5-5` |
| `HARNESS2_HERMES_PROVIDER` | Hermes provider name, for example `anthropic` |
| `HARNESS2_HERMES_CMD` | The command that starts Hermes (default `hermes`) |
| `HARNESS2_HERMES_ROLLOUTS` | Where rollout homes are created (default `~/.cache/harness2/hermes-rollouts`); refused inside a `.hermes` directory or a git checkout, whose `AGENTS.md` and `.hermes.md` Hermes would load |
| `HARNESS2_HERMES_RUNNER` | Optional prefix that runs Hermes as another user, for example `sudo -n -u rollouts` |
| `HARNESS2_HERMES_PASS_ENV` | Names of variables passed to the rollout, such as `ANTHROPIC_API_KEY`; nothing else from your environment is |
| `HARNESS2_HERMES_PROVIDERS_FILE` | Optional JSON file with a `providers:` map, for a custom endpoint |

Credentials reach Hermes through `HARNESS2_HERMES_PASS_ENV` (sent on stdin to the launcher,
never on a command line), or through a wrapper named in `HARNESS2_HERMES_CMD` that loads them
itself. Then check that every component reaches a rollout and that the floor holds, and run:

```bash
export HARNESS2_HERMES_MODEL=claude-haiku-5-5 HARNESS2_HERMES_PROVIDER=anthropic \
  HARNESS2_HERMES_PASS_ENV=ANTHROPIC_API_KEY
harness2-check --substrate hm --conformance
harness2 --bench local --substrate hm --k 1 --only-domains data-cleaning --max-tasks 2
harness2-judge --bench local --substrate hm --k 1
```

The conformance probe runs two rollouts and prints one line per component (C1 to C8), the floor
line and the override line. Where each component goes:

| Component | In the rollout |
|---|---|
| System prompt, guardrails, tool guidance | `SOUL.md`, in that order |
| Memory | `memories/MEMORY.md`, one entry per paragraph |
| Skills | `work/skills/`, loaded through `skills.external_dirs` so helper paths resolve from the workspace |
| Scripts | `work/scripts/` |
| Subagents | A brief skill `agent-<name>` in the home's `skills/`, named in `SOUL.md` |
| Plugins | `hooks.json` with Hermes shell hooks (flat entries: `matcher`, `command`, `timeout`, `fail_closed`) |

Two gaps against the eight components:

* **Hermes has no file-defined subagents.** `delegate_task` children get Hermes's default
  identity, not the parent's `SOUL.md` or memory, and cannot be named. A harness subagent becomes
  a skill holding its brief; `SOUL.md` tells the agent to load it and pass the brief as the
  `context` of `delegate_task`. Whether the brief is used depends on the model following that
  instruction; the probe checks that it did.
* **Hermes caps memory at 2,200 characters by default.** The floor raises
  `memory.memory_char_limit` to 20,000, the always-on cap the surface enforces, so a harness
  memory loads whole.

The floor also denies any command that would need an approval, turns off background review,
title generation, memory and skill nudges, the curator and bundled skills, and puts the
operator's hooks before the harness's. That order is not enforcement: Hermes applies a hook's
argument rewrite after every hook has seen the original call, and a hook command is shell.

On a subscription login Hermes reports no price, so `rollout.json` records `cost_usd: null`
and `cost_source: unknown` with token counts. Hermes passes some credential variables on to
the agent's terminal and every passed variable on to hook commands; it redacts token-shaped
tool output. Use a key you can revoke, and a separate OS user (`HARNESS2_HERMES_RUNNER`) if
rollouts must not read your files.

## Validation

Both executors were run on all 12
localbench tasks at `--k 1` over two stream-order seeds, then scored by the deterministic
checkers on the selected output and on the base output. Executor `claude-haiku-5-5`, improver
`claude-opus-5-5`; cost is at list price as Claude Code reports it.

| Executor | Seed | Tasks ok | Base mean (SD) | Adopted mean (SD) | Fallbacks | Library entries | Rollout cost | Improver cost |
|---|---|---|---|---|---|---|---|---|
| Claude Code | 1 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 8 | $0.16 | $9.30 |
| Claude Code | 2 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 8 | $0.17 | $9.20 |
| Hermes | 1 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 10 | unknown | $10.47 |
| Hermes | 2 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 9 | unknown | $9.76 |

The executor already passes every check at base, so this run shows the whole pipeline working
on both executors and measures no gain from adaptation. Hermes reports no price on a
subscription login. [VALIDATION.md](VALIDATION.md) has the commands, the conformance probes,
the isolation tests and the publish pre-flight.

## Upstream benchmarks

JobBench, LAB and WorkBuddy-Bench, the OpenCode and Codex executors, and parallel and
sequential recursion work as upstream documents them. That code is unchanged here and was not
rerun for this port. See the [setup guide](docs/SETUP.md), the
[benchmark guides](docs/BENCHMARKS.md) and the [experiment guide](docs/EXPERIMENTS.md).
Model-backed runs cost money; start with `--max-tasks 1`.

Executor network access is unrestricted, and public benchmark rubrics may be online. Configure
[network restrictions](docs/EXPERIMENTS.md#web-access) before an evaluation that has to be
clean.

## Citation

Cite the Harness² paper:

```bibtex
@article{xu2026harness2,
  title   = {Harness$^2$: Recursive Agent Harnessing for an Open World},
  author  = {Xu, Ruiyao and Chen, Yanfei and CuiZhu, Zhongying and Dalvi Mishra, Bhavana and Ming, Yifei and Yu, Han and Han, Rujun and Lee, Chen-Yu and Pfister, Tomas},
  journal = {arXiv preprint arXiv:2610.14224},
  year    = {2026},
  url     = {https://arxiv.org/abs/2610.14224}
}
```

## License

Apache 2.0, the same license as upstream; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Code
under [`third_party/`](third_party/README.md), benchmarks and datasets keep their own licenses;
see the [third-party notices](dependencies/README.md). The Harness² logo, wordmark, figures and
video are not included. Modified by The harness2-ports Authors: this README replaces the
upstream one, which is in the [upstream repository](https://github.com/google-research/harness2).

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
