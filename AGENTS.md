# AGENTS.md

Instructions for coding agents working in this repository. This file is added by The
harness2-ports Authors.

## What this repository is

An independent port of [Harness²](https://github.com/google-research/harness2) that adds a
Claude Code executor (`--substrate cc`) and a small deterministic task suite (`--bench local`).
The Harness² method, the OpenCode and Codex executors and the upstream benchmarks come from
upstream and are kept as close to it as possible. The README explains the idea;
[docs/QUICKSTART.md](docs/QUICKSTART.md) has the install and run steps.

## Layout

| Path | What is there |
|---|---|
| `harness2/core/` | The method: proposer, recursion, library, selection, judge, ledger |
| `harness2/substrate/` | Executors. `claude_code.py` is this port's; `opencode.py` and `codex.py` are upstream |
| `harness2/conformance.py` | The live probe that checks all eight harness components reach a rollout |
| `harness2/cli/` | Entry points (`harness2`, `harness2-check`, `harness2-judge`, ...) |
| `harness2/benchmarks/` | Benchmark adapters; `localbench.py` is this port's |
| `localbench/tasks/<task>/grader/` | Hidden checkers. Never read them into a model context or a rollout |
| `tests/` | The test suite; `test_workflow.py` is upstream's |
| `docs/` | Quick start, setup, experiment and benchmark guides |
| `VALIDATION.md` | The validation record, with commands and receipts |
| `UPSTREAM.md` | Every upstream file this port changes, and why |

## Setup and tests

Use Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e '.[render]' pytest
python -m pytest -q tests
```

The tests need no model credentials. Run them before every commit. Lint with
`ruff check .` (configuration in `pyproject.toml`, line length 100).

Commands that start rollouts or improver sessions (`harness2`, `harness2-check --conformance`,
`harness2-judge` on a model-backed benchmark) call a paid model. Do not run them unless the task
asks for it.

## Rules

* **Keep upstream intact.** `tests/test_workflow.py` must stay byte-identical to upstream. Do
  not change the method text of the stage prompts. A change to the method itself, or to the
  OpenCode or Codex executors, belongs upstream.
* **Record every upstream change.** When you modify an upstream file, add the line
  `Modified by The harness2-ports Authors` under its license header (Python files) and add a
  row to the table in `UPSTREAM.md`. New files say that the harness2-ports Authors added them.
* **Keep the floor and the read boundary.** Do not weaken the isolation floor in
  `harness2/claude_floor.py`, the settings allowlists in `harness2/core/tree.py`, or the
  `sandbox-exec` boundary around `localbench/tasks/` (in `harness2/benchmarks/localbench.py`).
  A harness edit must never reach them.
* **Turn on the commit hooks** with `git config core.hooksPath .githooks`. They refuse
  home-directory paths, secrets and attribution trailers. Do not bypass them with
  `--no-verify`.
* **Check before publishing.** `scripts/preflight_publish.py` scans the whole git history; run
  it before any push.
* **Keep claims measured.** This port has not been properly tested; the checks so far only ran
  the pipeline end to end on easy tasks it already solved. Write expectations, not results,
  and never claim measured improvement in docs or commit messages.

## Docs

Write plain, short sentences. The README explains the idea for a general reader; install
steps, variables and flags go in `docs/QUICKSTART.md` or `docs/SETUP.md`, not the README.
