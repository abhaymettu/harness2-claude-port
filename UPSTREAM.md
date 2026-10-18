# Upstream

This repository starts from [google-research/harness2](https://github.com/google-research/harness2)
at commit `1cfe254e8d25b15f37048c3730134686abe60335` (2026-10-13), licensed under Apache-2.0.

The first commit is that tree, unchanged, taken with `git archive 1cfe254`, except `assets/`.
Upstream history is not carried. `LICENSE` is the upstream text, unchanged.

`assets/` (the Harness² logo, wordmark, figures and video) is left out. Apache-2.0 section 6
grants no right to use the licensor's trademarks, and the logo and wordmark are marks. The
upstream `README.md` and `MANIFEST.in` still name those files; the images are at the upstream
repository.

## Modified upstream files

Apache-2.0 section 4(b) asks that changed files say so. Each file below carries the line
`Modified by The harness2-ports Authors` under its license header, and the table says why.

| File | Change | Why |
|---|---|---|
| `harness2/config.py` | `CLAUDE_VIA_VERTEX` (Vertex only when a Google Cloud project is set, or `HARNESS2_CLAUDE_VIA_VERTEX=1`); `SOLVER_MODEL_CC` from `HARNESS2_CLAUDE_MODEL`; default improver channel is `claude_cli` for a bare model id, overridable with `HARNESS2_IMPROVER_CHANNEL` | Run without Google Cloud on a Claude Code login |
| `harness2/core/proposer.py` | `Proposer.env()` leaves the caller's environment alone for `claude_cli` when Vertex is off | Upstream always forced Vertex and stripped `ANTHROPIC_API_KEY`, which breaks API-key and subscription logins |

New files added by this project are listed in `README.md`, not here.
