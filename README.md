<h3 align="center">
  <img src="assets/Harness2-wordmark.png" alt="Harness²" width="360"><br>
  Recursive Agent Harnessing for an Open World
</h3>

<p align="center">
  <a href="https://arxiv.org/pdf/2610.14224"><img src="https://img.shields.io/badge/Paper-arXiv-EA4335?logo=arxiv&logoColor=white" alt="Paper"></a>
  <a href="https://harness2.github.io"><img src="https://img.shields.io/badge/Website-harness2.github.io-4285F4?logo=googlechrome&logoColor=white" alt="Website"></a>
  <a href="docs/BENCHMARKS.md"><img src="https://img.shields.io/badge/Docs-Benchmark%20guides-FBBC04" alt="Benchmark guides"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-34A853" alt="License"></a>
</p>

<p align="center">
  <a href="docs/BENCHMARKS.md#jobbench">
    <img src="assets/harness2-setup.gif" alt="Install, set up, and run JobBench: uv pip install -e '.[render]', harness2-setup jb, then harness2 --bench jb --k 1 --mode parallel. Click for prerequisites and commands." width="640">
  </a>
</p>

A **harness** is the system around a model that enables it to act as an agent:
prompts, tools, memory, skills, orchestration, and more. **Harnessing** is the
process of optimizing that system.

Harness² is a plug-and-play framework for **recursive agent harnessing** in an
open world, where agents encounter tasks unseen during harness design. It
connects two levels of recursion while keeping model weights fixed:

* **Task-level recursion** refines the execution harness for the current task
  through a contrastive **Propose–Probe–Compose** step: propose edits, probe
  their effects on the same task, and compose a refined harness from behavioral
  contrasts between executions, without ground-truth feedback.
* **Harnessing-level recursion** updates a persistent *improvement harness*
  with adopted harnesses and evidence-supported lessons from each task to guide
  future refinement.

<p align="center">
  <a href="assets/harness2_pipeline.png">
    <img src="assets/harness2_pipeline.png" alt="Harness² pipeline. Task-level recursion: an agent executor runs the initial harness, a harness editor proposes invariant and domain edits, candidate probes execute them, and a harness composer combines them into the final harness. Harnessing-level recursion: an experience reflector reflects on the step and updates the improvement harness used for the next task." width="100%">
  </a>
</p>

Across three professional benchmarks and four model–harness configurations, a
single Harness² step improves GLM-5 and Gemini 3.5 Flash over their base
harnesses, with gains of up to 11.5 points on WorkBuddy-Bench, 4.5 points on
JobBench, and 11.8 percentage points on LAB's partial pass rate. Increasing the
task-level recursion budget brings further gains.

The release supports **parallel and sequential recursion**, **OpenCode and
Codex executors**, and **JobBench, LAB, and WorkBuddy-Bench**.

## Video overview

https://github.com/user-attachments/assets/76b10548-b14b-4c8f-9aa5-a93662df4d56

## Contents

- [Video overview](#video-overview)
- [Harness components](#harness-components)
- [Install](#install)
- [Run a benchmark](#run-a-benchmark)
- [Claude Code executor](#claude-code-executor)
- [localbench](#localbench)
- [Hermes executor](#hermes-executor)
- [Validation](#validation)
- [Experiments](#experiments)
- [Web access](#web-access)
- [Results and resume](#results-and-resume)
- [Citation](#citation)
- [Contributing](#contributing)
- [License](#license)
- [Disclaimer](#disclaimer)

## Harness components

Harness² exposes eight editable components around the model: **system prompt,
guardrails, memory, tool guidance, subagents, skills, scripts, and plugins**.
They control context construction, the tool interface, delegation, and behavior
inside the tool loop.

<p align="center">
  <a href="assets/components.png">
    <img src="assets/components.png" alt="Eight harness components grouped by runtime role: system prompt, guardrails, memory, and skills construct context; tool guidance and scripts define the tool interface; subagents orchestrate delegated work; plugins control middleware." width="100%">
  </a>
</p>

## Install

Use **Linux, Python 3.12, and [uv](https://docs.astral.sh/uv/getting-started/installation/)**.
From the repository root:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e '.[render]'
harness2-demo --output runs/demo --k 2
```

The local demo runs both recursion modes with deterministic editors and real
Python executions. It requires no model credentials.

For model-backed benchmarks, install **Node.js 20+, the Google Cloud CLI**, and
the [benchmark dependencies](docs/SETUP.md#requirements). LAB needs Pandoc and
Poppler; WorkBuddy-Bench needs Docker. Then configure your models:

```bash
cp .env.example .env
# Edit .env with your Vertex AI project and model IDs.
gcloud auth application-default login
```

See the [setup guide](docs/SETUP.md) for model settings, authentication
alternatives, and the [Codex executor](docs/SETUP.md#codex-executor).

## Run a benchmark

The following example installs LAB and runs one task, then evaluates and reports
its result. Model-backed runs incur API costs; start with a small task selection.

```bash
harness2-setup lab
harness2-check --bench lab
harness2 --bench lab --k 1 --mode parallel \
  --only-domains antitrust-competition --max-tasks 1
harness2-judge --bench lab --k 1 --mode parallel
harness2-report --bench lab --k 1 --mode parallel
```

Sequential recursion runs the same commands with `--mode sequential`. `--k` is
the task-level recursion budget; see [Experiments](#experiments). Judging and
reporting must use the same benchmark, executor, subset, `--k`, `--mode`, and
seed as the refinement run. Add `--dry-run` to `harness2` to preview task
selection without model calls.

| Benchmark | Tasks | Install | Guide |
|---|---|---|---|
| JobBench | Professional work | `harness2-setup jb` | [JobBench](docs/BENCHMARKS.md#jobbench) |
| LAB | Legal work | `harness2-setup lab` | [LAB](docs/BENCHMARKS.md#lab) |
| WorkBuddy-Bench | Office, web, and code | `harness2-setup wb` | [WorkBuddy](docs/BENCHMARKS.md#workbuddy-bench) |

Choose one benchmark per command. WorkBuddy also takes `--subset office`,
`--subset web`, or `--subset code` on every command after setup. The
[benchmark guides](docs/BENCHMARKS.md) cover each one's data, domains, and
grading.

## Claude Code executor

This section is added by The harness2-ports Authors. `--substrate cc` runs each rollout as a
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
`--setting-sources project --strict-mcp-config --no-session-persistence`, and with permissions
bypassed inside the workspace. A session runs as you and can read what you can, so run
untrusted tasks in a container or as a separate user.

## localbench

This section is added by The harness2-ports Authors. `--bench local` is a small suite for
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
which the runner now starts. Elsewhere set `HARNESS2_GRADER_BOUNDARY=off` and run where
`localbench/tasks/` is not mounted; the only guard left is then a floor hook that refuses tool
calls naming the tasks, and it matches strings.

## Hermes executor

This section is added by The harness2-ports Authors. `--substrate hm` runs rollouts on
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

This section is added by The harness2-ports Authors. Both new executors were run on all 12
localbench tasks at `--k 1` over two stream-order seeds, then scored by the deterministic
checkers on the selected output and on the base output. Executor `claude-haiku-5-5`, improver
`claude-opus-5-5`; cost is at list price as Claude Code reports it.

| Executor | Seed | Tasks ok | Base mean (SD) | Adopted mean (SD) | Fallbacks | Library entries | Rollout cost | Improver cost |
|---|---|---|---|---|---|---|---|---|
| Claude Code | 1 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 6 | $0.16 | $8.84 |
| Claude Code | 2 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 9 | $0.18 | $12.36 |
| Hermes | 1 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 9 | unknown | $9.57 |
| Hermes | 2 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 10 | unknown | $11.39 |

The executor already passes every check at base, so this run shows the whole pipeline working
on both executors and measures no gain from adaptation. Hermes reports no price on a
subscription login. [VALIDATION.md](VALIDATION.md) has the commands, the conformance probes,
the isolation tests and the publish pre-flight.

## Experiments

Scale task-level recursion in two ways: **parallel recursion** explores multiple
candidate harnesses and composes refinements from their execution evidence;
**sequential recursion** carries the refined harness and accumulated evidence
through successive Propose–Probe–Compose steps.

<p align="center">
  <a href="assets/harness2_recursion_modes.png">
    <img src="assets/harness2_recursion_modes.png" alt="Two ways to scale task-level recursion. Parallel: probe k general and k domain-specific candidate harnesses, then produce k compositions from the shared evidence. Sequential: carry the refined harness and accumulated evidence through k Propose–Probe–Compose steps." width="100%">
  </a>
</p>
<p align="center"><em>Parallel recursion explores wider; sequential recursion refines deeper.</em></p>

| Option | Behavior |
|---|---|
| `--k 1` | One Propose–Probe–Compose step |
| `--k K --mode parallel` | Probe `K` general and `K` domain-specific candidates, then produce `K` compositions |
| `--k K --mode sequential` | Refine the harness through `K` successive steps |
| `--substrate cx` | Use Codex instead of the default OpenCode executor |

After each task, harnessing-level recursion retains the adopted harness and
evidence-supported lessons to guide future refinement. See the
[experiment guide](docs/EXPERIMENTS.md) for task selection, concurrency,
reproducibility, and baseline comparisons.

## Web access

Executor network access is unrestricted, and Codex runs with its sandbox
disabled. Public benchmark rubrics may be accessible online. Before evaluation,
configure [network restrictions](docs/EXPERIMENTS.md#web-access) to prevent
access to benchmark answers and grading criteria.

## Results and resume

Results are saved under `runs/`, organized by benchmark and subset where
applicable. They include task summaries, deliverables, adopted harnesses,
reflection notes, and evaluation results.

Repeat the same command to resume. Use a new `HARNESS2_RUNS_DIR` when changing
models or task selection. See [results and resume](docs/EXPERIMENTS.md#results-and-resume)
for details; each command also supports `--help`.

## Citation

```bibtex
@article{xu2026harness2,
  title   = {Harness$^2$: Recursive Agent Harnessing for an Open World},
  author  = {Xu, Ruiyao and Chen, Yanfei and CuiZhu, Zhongying and Dalvi Mishra, Bhavana and Ming, Yifei and Yu, Han and Han, Rujun and Lee, Chen-Yu and Pfister, Tomas},
  journal = {arXiv preprint arXiv:2610.14224},
  year    = {2026},
  url     = {https://arxiv.org/abs/2610.14224}
}
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Harness² is licensed under [Apache 2.0](LICENSE). Third-party code under
[`third_party/`](third_party/README.md), benchmarks, and datasets retain their
upstream licenses; see
[third-party notices](dependencies/README.md).

## Disclaimer

This is not an officially supported Google product. This project is not eligible
for the [Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security).
