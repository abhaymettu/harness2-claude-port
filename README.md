<h3 align="center">
  harness2-claude-port<br>
  A Claude Code executor for Harness²
</h3>

<p align="center">
  <a href="https://arxiv.org/pdf/2610.14224"><img src="https://img.shields.io/badge/Paper-arXiv-EA4335?logo=arxiv&logoColor=white" alt="Paper"></a>
  <a href="docs/BENCHMARKS.md"><img src="https://img.shields.io/badge/Docs-Benchmark%20guides-FBBC04" alt="Benchmark guides"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-34A853" alt="License"></a>
</p>

<p align="center">
  <em>An independent port of <a href="https://github.com/google-research/harness2">Harness²</a> - not from the original authors.</em>
</p>


A **harness** is the system around a model that enables it to act as an agent:
prompts, tools, memory, skills, orchestration, and more. **Harnessing** is the
process of optimizing that system.

[Harness²](https://github.com/google-research/harness2) is Google Research's
framework for **recursive agent harnessing** in an open world
([paper](https://arxiv.org/abs/2610.14224)). It connects two levels of
recursion while keeping model weights fixed:

* **Task-level recursion** refines the execution harness for the current task
  through a contrastive **Propose–Probe–Compose** step: propose edits, probe
  their effects on the same task, and compose a refined harness from behavioral
  contrasts between executions, without ground-truth feedback.
* **Harnessing-level recursion** updates a persistent *improvement harness*
  with adopted harnesses and evidence-supported lessons from each task to guide
  future refinement.

This repository is an **independent port** that adds a Claude Code executor to
upstream's OpenCode and Codex executors. It is not a Google project and is not
endorsed by the Harness² authors. The Hermes Agent executor port of the same
method lives at the **harness2-hermes-port** repository, published under the same GitHub account.

What the port adds:

* `--substrate cc`, an executor that runs each rollout as a headless Claude
  Code session (`claude -p`) in a fresh workspace built from the harness.
* `--bench local`, 12 small tasks with deterministic checkers, for checking an
  executor end to end without a judge model, Docker or a cloud project.
* An isolation floor that harness edits cannot change, a read boundary that
  keeps the checkers out of reach of the sessions being scored, and a
  pre-flight that scans the whole git history before publishing.

Checked end to end on all 12 localbench tasks at two stream-order seeds:
**12/12 tasks ok on both seeds, conformance probe 8/8 with the floor held**.
The executor already passes every checker at base, so the run validates the
whole pipeline rather than measuring an adaptation gain. The full record, with
commands and receipts, is in [VALIDATION.md](VALIDATION.md).

## Contents

- [Harness components](#harness-components)
- [Install](#install)
- [Quickstart](#quickstart)
- [The Claude Code executor](#the-claude-code-executor)
- [localbench](#localbench)
- [Experiments](#experiments)
- [Web access](#web-access)
- [Results and resume](#results-and-resume)
- [Validation](#validation)
- [Citation](#citation)
- [Contributing](#contributing)
- [License](#license)
- [Disclaimer](#disclaimer)

## Harness components

Harness² exposes eight editable components around the model: **system prompt,
guardrails, memory, tool guidance, subagents, skills, scripts, and plugins**.
Under `--substrate cc`, each one lands in a real Claude Code surface:

| Component | In the rollout |
|---|---|
| System prompt | `.claude/systemprompt.md`, passed with `--append-system-prompt-file` |
| Guardrails, memory, tool guidance | The workspace `CLAUDE.md` |
| Skills | `.claude/skills/<name>/SKILL.md` |
| Scripts | `scripts/` |
| Subagents | `.claude/agents/<name>.md`, run on the executor model |
| Plugins | Hooks in `.claude/settings.json`; no other settings key is accepted |

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
upstream benchmarks, see the [setup guide](docs/SETUP.md).

## Quickstart

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

## Experiments

Scale task-level recursion in two ways: **parallel recursion** explores multiple
candidate harnesses and composes refinements from their execution evidence;
**sequential recursion** carries the refined harness and accumulated evidence
through successive Propose–Probe–Compose steps.

| Option | Behavior |
|---|---|
| `--k 1` | One Propose–Probe–Compose step |
| `--k K --mode parallel` | Probe `K` general and `K` domain-specific candidates, then produce `K` compositions |
| `--k K --mode sequential` | Refine the harness through `K` successive steps |

After each task, harnessing-level recursion retains the adopted harness and
evidence-supported lessons to guide future refinement. See the
[experiment guide](docs/EXPERIMENTS.md) for task selection, concurrency,
reproducibility, and baseline comparisons. The upstream benchmarks (JobBench,
LAB, WorkBuddy-Bench) and the OpenCode and Codex executors work as upstream
documents them; that code is unchanged here and was not rerun for this port.
See the [benchmark guides](docs/BENCHMARKS.md).

## Web access

Executor network access is unrestricted, and public benchmark rubrics may be
online. Configure [network restrictions](docs/EXPERIMENTS.md#web-access) before
an evaluation that has to be clean.

## Results and resume

Results are saved under `runs/`, organized by benchmark and subset where
applicable. They include task summaries, deliverables, adopted harnesses,
reflection notes, and evaluation results.

Repeat the same command to resume. Use a new `HARNESS2_RUNS_DIR` when changing
models or task selection. See [results and resume](docs/EXPERIMENTS.md#results-and-resume)
for details; each command also supports `--help`.

## Validation

The executor was run on all 12 localbench tasks at `--k 1` over two
stream-order seeds, then scored by the deterministic checkers on the selected
output and on the base output. Executor `claude-haiku-5-5`, improver
`claude-opus-5-5`; cost is at list price as Claude Code reports it.

| Executor | Seed | Tasks ok | Base mean (SD) | Adopted mean (SD) | Fallbacks | Library entries | Rollout cost | Improver cost |
|---|---|---|---|---|---|---|---|---|
| Claude Code | 1 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 8 | $0.16 | $9.30 |
| Claude Code | 2 | 12/12 | 100.0 (0.0) | 100.0 (0.0) | 0 | 8 | $0.17 | $9.20 |

The executor already passes every check at base, so this run shows the whole
pipeline working and measures no gain from adaptation.
[VALIDATION.md](VALIDATION.md) has the commands, the conformance probes, the
isolation tests and the publish pre-flight; it is the full validation record of
the port, which was validated on both executors at the same commit.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache 2.0, the same license as upstream; see [LICENSE](LICENSE) and
[NOTICE](NOTICE). Code under [`third_party/`](third_party/README.md),
benchmarks and datasets keep their own licenses; see the
[third-party notices](dependencies/README.md). The Harness² logo, wordmark,
figures and video are not included. Modified by The harness2-ports Authors:
this README replaces the upstream one, which is in the
[upstream repository](https://github.com/google-research/harness2).

## Disclaimer

This is an independent port, not an officially supported Google product, and it
is not endorsed by the Harness² authors.
