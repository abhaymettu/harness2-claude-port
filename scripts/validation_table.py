#!/usr/bin/env python3
# Copyright 2026 The harness2-ports Authors
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

"""Summarise judged localbench sweeps: base against adopted, per seed, with the run checks.

    python3 scripts/validation_table.py --substrate cc --seeds 1,2 [--per-task]

Reads what `harness2 --bench local --k 1 --seed N` and `harness2-judge ... [--bases]` left on
disk: task summaries (status, ledger, fallbacks), judged rows for the adopted and base outputs,
the run identity and the experience library. Read-only. Scores are the fraction of checker
criteria passed, as percent; SD is the sample SD across tasks.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness2.benchmarks.localbench import LocalBenchAdapter  # noqa: E402
from harness2.cli import _common as C  # noqa: E402


def mean_sd(xs: list[float]) -> tuple[float, float]:
    return statistics.fmean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)


def seed_row(adapter: LocalBenchAdapter, seed: int) -> dict:
    ns_dir = C.runs_root_for(adapter) / C.summary_namespace(adapter, 1, seed=seed)
    ident = json.loads((ns_dir / "config.json").read_text())
    adopted = {r["task_id"]: r for r in json.loads((ns_dir / "judged.json").read_text())}
    base = {r["task"]: r for r in json.loads((ns_dir / "base_judged.json").read_text())}
    tasks, ledger_ok, fell_back, sel_fallback, picked_base, rollout_usd, session_usd = (
        [],
        0,
        0,
        0,
        0,
        [],
        0.0,
    )
    for summary_path in sorted(ns_dir.glob("*/summary.json")):
        s = json.loads(summary_path.read_text())
        mode, sel = s["modes"]["agg"], s["selections"]["agg"]
        led = mode["ledger"]
        ledger_ok += led["R"] == led["expected_R"] and led["P"] == led["expected_P"]
        fell_back += len(mode["fell_back"])
        sel_fallback += bool(sel.get("fallback"))
        picked_base += bool(sel.get("chosen_is_base"))
        session_usd += led.get("session_usd") or 0.0
        t = s["task_id"]
        a, b = adopted.get(t, {}), base.get(t, {}).get("score") or {}
        tasks.append(
            dict(
                task=t,
                status=s["status"],
                adopted=100 * a["n_passed"] / a["n_criteria"] if a.get("graded") else None,
                base=100 * b["n_passed"] / b["n_criteria"] if b.get("n_criteria") else None,
            )
        )
    executions = adapter.run_dir(C.summary_namespace(adapter, 1, seed=seed))
    for record in sorted(executions.glob("*/*/rollout.json")):
        rollout_usd.append(json.loads(record.read_text()).get("cost_usd"))
    lib = C.library_root_for(adapter, 1, seed=seed) / "agg"
    entries = {d.name: len(list((d / "harnesses").glob("*"))) for d in sorted(lib.glob("*"))}
    scored = [t for t in tasks if t["adopted"] is not None and t["base"] is not None]
    bm, bsd = mean_sd([t["base"] for t in scored])
    am, asd = mean_sd([t["adopted"] for t in scored])
    priced = [u for u in rollout_usd if u is not None]
    return dict(
        seed=seed,
        n=len(tasks),
        n_ok=sum(t["status"] == "ok" for t in tasks),
        n_scored=len(scored),
        base=(bm, bsd),
        adopted=(am, asd),
        better=sum(t["adopted"] > t["base"] for t in scored),
        worse=sum(t["adopted"] < t["base"] for t in scored),
        ledger_ok=ledger_ok,
        fell_back=fell_back,
        sel_fallback=sel_fallback,
        picked_base=picked_base,
        library=entries,
        executor=ident["executor"],
        improver=ident["improver"],
        n_rollouts=len(rollout_usd),
        rollout_usd=sum(priced) if len(priced) == len(rollout_usd) and priced else None,
        session_usd=session_usd,
        tasks=tasks,
    )


def fmt(ms: tuple[float, float]) -> str:
    return f"{ms[0]:.1f} ({ms[1]:.1f})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--substrate", choices=("cc", "hm"), required=True)
    ap.add_argument("--seeds", default="1,2")
    ap.add_argument("--per-task", action="store_true")
    args = ap.parse_args(argv)
    adapter = LocalBenchAdapter(args.substrate)
    rows = [seed_row(adapter, int(s)) for s in args.seeds.split(",")]
    print(
        "| substrate | seed | n (ok / scored) | base mean (SD) | adopted mean (SD) | better / worse "
        "| ledger identity | fell back | picked base | library entries | executor / improver "
        "| rollout cost | improver cost |"
    )
    print("|" + "---|" * 13)
    for r in rows:
        lib = sum(r["library"].values())
        cost = "unknown" if r["rollout_usd"] is None else f"${r['rollout_usd']:.2f}"
        cost += f" ({r['n_rollouts']} rollouts)"
        print(
            f"| {args.substrate} | {r['seed']} | {r['n']} ({r['n_ok']} / {r['n_scored']}) "
            f"| {fmt(r['base'])} | {fmt(r['adopted'])} | {r['better']} / {r['worse']} "
            f"| {r['ledger_ok']}/{r['n']} | {r['fell_back']} stage(s), {r['sel_fallback']} "
            f"selection(s) | {r['picked_base']} | {lib} in {len(r['library'])} domains "
            f"| {r['executor']} / {r['improver']} | {cost} | ${r['session_usd']:.2f} |"
        )
    gains = [r["adopted"][0] - r["base"][0] for r in rows]
    sds = [max(r["adopted"][1], r["base"][1]) for r in rows]
    improves = all(g > sd for g, sd in zip(gains, sds))
    print(
        f"\ngain per seed: {', '.join(f'{g:+.1f}' for g in gains)} points; larger SD per seed: "
        f"{', '.join(f'{sd:.1f}' for sd in sds)}; "
        f"{'improves on every seed' if improves else 'no improvement claim'}"
    )
    if args.per_task:
        for r in rows:
            print(f"\nseed {r['seed']}:")
            for t in r["tasks"]:
                print(f"  {t['task']:<12} {t['status']:<6} base {t['base']} adopted {t['adopted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
