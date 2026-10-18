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

This repository is an **independent port** that lets Harness² improve
[Claude Code](https://github.com/anthropics/claude-code) agents, alongside
upstream's OpenCode and Codex executors. It is not a Google project and is not
endorsed by the Harness² authors. A sibling port does the same for Hermes Agent
at the **harness2-hermes-port** repository, published under the same GitHub
account.

## Contents

- [The idea in plain terms](#the-idea-in-plain-terms)
- [How one task goes](#how-one-task-goes)
- [Experiments](#experiments)
- [What Claude Code brings](#what-claude-code-brings)
- [Keeping the scores honest](#keeping-the-scores-honest)
- [What the validation showed](#what-the-validation-showed)
- [Going further](#going-further)
- [Citation](#citation)
- [Contributing](#contributing)
- [License](#license)
- [Disclaimer](#disclaimer)

## The idea in plain terms

Most ways of making an AI agent better change the model itself, by training it
on more data. Harness² leaves the model alone and improves everything around
it instead: the instructions it starts with, the notes it can consult, the
small tools and scripts it is handed, and the helpers it can delegate to.

Think of a capable new hire. You cannot change how smart they are, but you can
give them a better briefing, a better checklist and better tools. Harness²
does that automatically, one task at a time, and keeps a record of what helped
so the next task starts from a better place.

The unusual part is that it does this **without an answer key**. It never
looks at the correct answer to a task. It learns by comparing: it runs the
same task with slightly different setups, looks at how the agent behaved
differently in each, and keeps the changes that look like they helped.

## How one task goes

```mermaid
flowchart LR
  A[Task arrives] --> B[Run the agent with its current harness]
  B --> C[Propose edits to the harness]
  C --> D[Probe: rerun the task with each edit]
  D --> E[Compose: combine what helped]
  E --> F[Adopt the refined harness]
  F --> G[Library of harnesses and lessons]
  G -. guides the next task .-> A
```

1. **Run.** The agent attempts the task with its current harness.
2. **Propose.** A second model, the improver, reads what happened and suggests
   edits: a clearer instruction, a new checklist item, a helper script.
3. **Probe.** Each suggested edit is tried on the same task, so the runs can
   be compared side by side.
4. **Compose.** The improver looks at how behavior differed between the runs
   and builds one refined harness from the edits that made a difference.
5. **Remember.** The adopted harness and a short written lesson go into a
   library, which the improver consults on later tasks.

Steps 2 to 4 are the task-level recursion from the paper. Step 5 is the
harnessing-level recursion: the system gets better at improving itself, not
just at the task in front of it.

## Experiments

There are two ways to spend more effort on a task. **Parallel recursion**
tries several candidate harnesses at once and composes a refinement from all
of their evidence. **Sequential recursion** takes the refined harness and runs
Propose–Probe–Compose on it again, several times in a row. The
[experiment guide](docs/EXPERIMENTS.md) covers both, plus task selection,
reproducibility and baselines. The upstream benchmarks (JobBench, LAB,
WorkBuddy-Bench) are described in the [benchmark guides](docs/BENCHMARKS.md);
that code is unchanged here and was not rerun for this port.

## What Claude Code brings

Harness² describes a harness as eight editable parts: **system prompt,
guardrails, memory, tool guidance, subagents, skills, scripts and plugins**.
Claude Code already has a native home for every one of them, so an improved
harness is just a folder Claude Code knows how to read:

| Part of the harness | Where it lives in Claude Code |
|---|---|
| System prompt | An extra system prompt file added to the session |
| Guardrails, memory, tool guidance | The project's `CLAUDE.md` |
| Skills | `.claude/skills/`, one folder per skill |
| Scripts | `scripts/` |
| Subagents | `.claude/agents/`, one file per helper agent |
| Plugins | Hooks in `.claude/settings.json` |

Each attempt runs as a fresh, headless Claude Code session built from that
folder. Because the harness is made of ordinary Claude Code files, an adopted
harness is something a person can open, read and reuse by hand.

## Keeping the scores honest

An agent that edits its own setup could, in principle, edit its way around
the test. The port puts three guards in place:

* **A fixed floor.** Every session starts from settings that no harness edit
  can reach. Your personal `CLAUDE.md`, saved memories and other user settings
  never leak into a run, and tools whose effects would outlive the session,
  such as schedules and notifications, are switched off.
* **Hidden checkers.** On macOS, the operating system's sandbox stops every
  session from reading the scoring scripts, the run history and other runs'
  results, including any route through another process.
* **A clean history.** Before publishing, a pre-flight check scans the whole
  git history for secrets and private paths.

Agents in these runs can still use the internet, and some public benchmark
rubrics are online, so a strictly clean evaluation needs
[network restrictions](docs/EXPERIMENTS.md#web-access).

## What to expect

After each task, a second model (the improver) reads what happened and
updates the harness folder - the briefing, checklist, skills and scripts the
agent runs with - so the next task starts from a better place. The loop also
refines its own improvement process, so with use it should get better at
improving itself, not only better at the tasks.

In an ideal solution, a task the agent failed starts passing after a few
attempts, the harness folder fills with lessons that visibly change how it
works, and repeat work gets faster and cheaper as the harness settles in.

Over the next few weeks of constant usage, expect the lessons library to
grow, small wins on repeated chores first, and the improver proposing
changes you would not have written by hand. The signal to watch is whether
gains show up on tasks the agent could not already solve - that is what
separates real improvement from the machinery just running.

That last part is still open. This port has not been properly tested: the
runs so far were smoke checks on easy tasks the agent already solved, so
they show the pipeline works end to end, not that it improves anything.
Better tests, on harder tasks, are needed. [VALIDATION.md](VALIDATION.md)
records exactly what was run.

## Going further

* [Quick start](docs/QUICKSTART.md): install, run the offline demo, and try
  the Claude Code executor.
* [Setup guide](docs/SETUP.md): requirements, credentials and the upstream
  benchmarks.
* [Experiment guide](docs/EXPERIMENTS.md): recursion modes, cost, results and
  resuming a run.
* [Upstream changes](UPSTREAM.md): every upstream file this port modifies, and
  why.

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

See [CONTRIBUTING.md](CONTRIBUTING.md). Coding agents should read
[AGENTS.md](AGENTS.md) first.

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
