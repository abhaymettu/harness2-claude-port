# Upstream

This repository starts from [google-research/harness2](https://github.com/google-research/harness2)
at commit `1cfe254e8d25b15f37048c3730134686abe60335` (2026-10-13), licensed under Apache-2.0.

The first commit is that tree, unchanged, taken with `git archive 1cfe254`, except `assets/`.
Upstream history is not carried. `LICENSE` is the upstream text, unchanged.

`assets/` (the Harness² logo, wordmark, figures and video) is left out. Apache-2.0 section 6
grants no right to use the licensor's trademarks, and the logo and wordmark are marks. The
upstream `MANIFEST.in` still names those files; the images are at the upstream repository.

## Modified upstream files

Apache-2.0 section 4(b) asks that changed files say so. Each Python file below carries the line
`Modified by The harness2-ports Authors` under its license header, `README.md` and `CONTRIBUTING.md` are
replaced, and the table says why.

| File | Change | Why |
|---|---|---|
| `harness2/config.py` | `CLAUDE_VIA_VERTEX` (Vertex only when a Google Cloud project is set, or `HARNESS2_CLAUDE_VIA_VERTEX=1`); `SOLVER_MODEL_CC` from `HARNESS2_CLAUDE_MODEL`; default improver channel is `claude_cli` for a bare model id, overridable with `HARNESS2_IMPROVER_CHANNEL` | Run without Google Cloud on a Claude Code login |
| `harness2/core/proposer.py` | `Proposer.env()` leaves the caller's environment alone for `claude_cli` when Vertex is off | Upstream always forced Vertex and stripped `ANTHROPIC_API_KEY`, which breaks API-key and subscription logins |
| `harness2/core/proposer.py` | `_claude_cli()` runs the improver under the same isolation floor as rollouts (`--setting-sources project`, `--strict-mcp-config`, `--no-session-persistence`, `--settings` with `claudeMdExcludes` and auto-memory off), plus the adapter's operator hooks and the environment they read (`floor_hooks`, `floor_env`) | Upstream ran editor, composer and reflector sessions with the caller's whole user configuration, so a user-level CLAUDE.md reached them and could be copied into adopted harnesses; the hooks keep improvers out of hidden checkers as rollouts are |
| `harness2/core/prompts.py` | A `claude_code` surface text (paths, Skill and Agent tools, the hooks file) beside the OpenCode and Codex ones; the method text of the stage prompts is unchanged | `_st()` refuses a surface it has no text for, and the existing texts name OpenCode and Codex paths |
| `harness2/core/tree.py` | Optional per-surface allowlists: top-level keys of the hooks file, and frontmatter keys of skills and sub-agents | A Claude Code settings file or agent frontmatter can carry permissions, environment, MCP servers or hooks; those belong to the operator's floor, not to an editable harness |
| `harness2/core/spec.py` | `INSTALL_MODES` gains `claude_workspace` | The Claude Code substrate's install mode |
| `harness2/cli/_common.py` | `--substrate cc`, `--bench local` | Select the Claude Code substrate and the local task suite |
| `harness2/cli/run_sweep.py` | Run identity records the `cc` executor model and the adapter's own editor model; the improver gets the adapter's `floor_hooks` and `floor_env` when it has them | Resume safety for Claude Code sweeps; improvers run under the same operator hooks as rollouts |
| `harness2/preflight.py` | A self-contained benchmark (`local`) checks only its substrate and its own preflight | localbench has nothing to install and no judge model |
| `harness2/cli/judge.py` | Skips the judge-model check for `--bench local` | localbench scores with deterministic checkers |
| `harness2/cli/check.py` | `--conformance` runs the live Claude Code component probe; `--bench` optional with it | Prove every component and the floor reach a rollout |
| `harness2/config.py` | `SOLVER_MODEL_HM` and the `HARNESS2_HERMES_*` settings (command, runner, rollout root, passed variables, providers file, provider) | Configure the Hermes substrate |
| `harness2/core/prompts.py` | A `hermes` surface text (SOUL.md sections, `hooks.json` shell hooks, `agent-<name>` brief skills) | The improver needs Hermes paths and tool names |
| `harness2/core/tree.py` | `SurfaceSpec.hook_entry_shape`: `nested` (default, unchanged) or `flat`, which checks Hermes hook entries (`matcher`, `command`, `timeout`, `fail_closed`, each typed) | Hermes hook entries are flat; the nested check would refuse every valid one |
| `harness2/core/spec.py` | `INSTALL_MODES` gains `hermes_home` | The Hermes substrate's install mode |
| `harness2/cli/_common.py`, `harness2/cli/run_sweep.py`, `harness2/cli/check.py` | `--substrate hm`; the run identity records the `hm` executor model; `--conformance` runs the Hermes probe, with `--provider` | Select and check the Hermes substrate |
| `README.md` | Replaced with a README for this port | It describes the port, its two executors, localbench and the measured results, and carries no upstream images |
| `CONTRIBUTING.md` | Replaced | Upstream's asks for Google's CLA, which does not apply to this repository |
| `harness2/core/proposer.py`, `harness2/cli/run_sweep.py` | `Proposer.floor_runner`: a callable giving the command prefix for a `claude_cli` session in its working directory, taken from the adapter's `runner_for` | Improver sessions run under the benchmark's read boundary, as rollouts do |
| `harness2/config.py` | `GRADER_BOUNDARY` from `HARNESS2_GRADER_BOUNDARY` (`seatbelt` default, `off`) | localbench's checker seal needs macOS `sandbox-exec`; `off` is for a container that never mounts the tasks |

## Files not in upstream

| File | What it is |
|---|---|
| `harness2/substrate/claude_code.py` | `ClaudeCodeSubstrate`: surface, install, `claude -p` launcher, stream-json renderer, preflight |
| `harness2/claude_floor.py` | The frozen floor shared by rollouts and improver sessions |
| `harness2/conformance.py` | The live component and floor probe behind `harness2-check --conformance` |
| `tests/test_claude_code_substrate.py`, `tests/test_provider_neutral.py` | Unit tests; `tests/fixtures/claude_code/` holds one recorded conformance stream |
| `harness2/benchmarks/localbench.py`, `localbench/tasks/` | `--bench local`: 12 tasks in 3 domains with deterministic checkers kept out of every workspace and model context; `tests/test_localbench.py` |
| `.githooks/` | Commit hooks that keep the history publishable |
| `scripts/preflight_publish.py`, `tests/test_preflight_publish.py` | The publish pre-flight over the whole history (secrets, private names, trailers, Hermes home files, attribution, em dashes), and tests that plant each problem |
| `scripts/validation_table.py` | Summarises judged localbench sweeps per seed: base against adopted, ledger identity, fallbacks, library entries, models and cost |
| `VALIDATION.md` | The validation record for both executors, with each command and its output |
| `harness2/substrate/hermes.py` | `HermesSubstrate`: surface, throwaway-home install, launcher (secrets on stdin), harvest, `state.db` read-back, stream-json renderer, preflight |
| `harness2/conformance_hermes.py` | The live component and floor probe behind `harness2-check --substrate hm --conformance` |
| `tests/test_hermes_substrate.py`, `tests/scripted_model.py` | Unit tests, and a scripted OpenAI-compatible endpoint for running Hermes with no model; `tests/fixtures/hermes/` holds one recorded conformance rollout |
