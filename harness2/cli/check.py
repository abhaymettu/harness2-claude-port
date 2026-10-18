# Copyright 2026 Google LLC
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
#
# Modified by The harness2-ports Authors.

"""Check one installed benchmark before running adaptation and judging.

`--conformance` instead runs one live rollout proving that every harness component and the
operator floor reach the executor (Claude Code only):

    harness2-check --substrate cc --conformance --model claude-haiku-5-5
"""

from __future__ import annotations

import argparse
from pathlib import Path

from harness2.cli._common import BENCHES, SUBSTRATES, make_adapter
from harness2.preflight import check


def conformance(args) -> int:
    from harness2 import conformance as CF
    from harness2.substrate.claude_code import ClaudeCodeSubstrate

    if args.substrate != "cc":
        print("FAIL: --conformance is implemented for --substrate cc only")
        return 1
    if not args.model:
        print("FAIL: --conformance needs --model (or HARNESS2_CLAUDE_MODEL)")
        return 1
    try:
        ClaudeCodeSubstrate().preflight()
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1
    report = CF.run_claude_code(args.model, args.output)
    print(CF.format_report(report))
    return 0 if report["passed"] == 8 and report["floor_ok"] else 1


def main(argv=None):
    from harness2 import config

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--bench", choices=BENCHES)
    p.add_argument("--subset", choices=("office", "web", "code"))
    p.add_argument("--substrate", choices=SUBSTRATES, default="oc")
    p.add_argument("--conformance", action="store_true", help="live component probe (cc only)")
    p.add_argument(
        "--model", default=config.SOLVER_MODEL_CC, help="executor model for --conformance"
    )
    p.add_argument("--output", type=Path, default=Path("runs/conformance"))
    args = p.parse_args(argv)
    if args.conformance:
        return conformance(args)
    if not args.bench:
        p.error("--bench is required unless --conformance is given")
    try:
        adapter = make_adapter(args.bench, args.subset, args.substrate)
        errors = check(adapter, judge=True)
    except (OSError, RuntimeError, ValueError) as exc:
        errors = [str(exc)]
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        print(f"Setup incomplete: {len(errors)} issue(s). See docs/BENCHMARKS.md.")
        return 1
    print(
        f"Ready: {adapter.spec.name}/{args.substrate}; {len(adapter.tasks())} tasks. "
        "Model access is not exercised; the first real run is the first model call."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
