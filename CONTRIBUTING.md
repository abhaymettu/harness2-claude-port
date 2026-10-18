# Contributing

Issues and pull requests are welcome. Contributions are accepted under the Apache 2.0 license
that covers this repository.

Changes to the Harness² method itself, or to the OpenCode and Codex executors, belong upstream at
[google-research/harness2](https://github.com/google-research/harness2), which has its own
contribution terms.

Before opening a pull request, run the tests:

```bash
python -m pytest -q tests
```

The repository's commit hooks refuse home-directory paths, secrets and attribution trailers. Turn
them on with `git config core.hooksPath .githooks`.

Modified by The harness2-ports Authors: this file replaces the upstream contribution guide.
