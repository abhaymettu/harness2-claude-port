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

"""HermesSubstrate: surface rules, materialise, floor, executor, renderer and conformance read-back.

The executor tests run a fake `hermes` (a Python script) through the real launch path. The
renderer and conformance tests read one recorded live conformance rollout (claude-haiku-5-5,
hermes-agent v0.21.5) with host paths replaced.
"""

import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from harness2 import config
from harness2 import conformance_hermes as CF
from harness2.core import prompts as P
from harness2.core import tree as HT
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
from harness2.substrate import hermes as HM

FIXTURE = Path(__file__).parent / "fixtures" / "hermes" / "conformance"
NONCE = "9ec963f2"


def spec(root: Path) -> BenchSpec:
    channel = ChannelSpec("claude_cli", "claude-haiku-5-5")
    return BenchSpec(
        name="t",
        runs_root=root,
        install_mode=HM.INSTALL_MODE,
        prompts=BenchPrompts(work="clean a table"),
        channels={"proposer": channel, "selector": channel},
        allow_subagents=True,
    )


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tree = CF.build_tree("n0")

    def problems(self, **changes) -> str:
        with self.assertRaises(ValueError) as cm:
            HT.validate(HM.HERMES_SURFACE, {**self.tree, **changes})
        return str(cm.exception)

    def hooks(self, doc) -> str:
        return self.problems(**{HM.HOOKS_FILE: json.dumps(doc)})

    def test_probe_tree_is_a_valid_harness(self):
        census = HT.validate(HM.HERMES_SURFACE, self.tree)
        self.assertEqual(
            (census["skills"], census["sub_agents"], census["scripts"], census["hooks"]),
            (1, 1, 1, 1),
        )

    def test_hooks_file_holds_hooks_only(self):
        msg = self.hooks({"hooks": {}, "approvals": {"mode": "off"}, "memory": {}})
        self.assertIn("remove ['approvals', 'memory']", msg)

    def test_claude_code_shaped_hooks_are_refused(self):
        msg = self.hooks(
            {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "true"}]}]}}
        )
        self.assertIn("unknown event 'PreToolUse'", msg)

    def test_flat_entries_take_only_known_keys_of_the_right_type(self):
        entry = {"command": "true", "timeout": True, "type": "command", "matcher": 3}
        msg = self.hooks({"hooks": {"pre_tool_call": [entry]}})
        self.assertIn(
            "pre_tool_call[0] may use only ['command', 'fail_closed', 'matcher', 'timeout']; "
            "remove ['type']",
            msg,
        )
        self.assertIn("pre_tool_call[0] `timeout` must be a int", msg)
        self.assertIn("pre_tool_call[0] `matcher` must be a str", msg)

    def test_a_hook_needs_a_command(self):
        msg = self.hooks({"hooks": {"pre_verify": [{"matcher": "x"}]}})
        self.assertIn("pre_verify[0] has an empty `command`", msg)

    def test_skill_name_must_match_its_directory(self):
        skill = "skills/probe-skill/SKILL.md"
        msg = self.problems(**{skill: self.tree[skill].replace("name: probe-skill", "name: other")})
        self.assertIn(f"{skill} needs frontmatter `name: probe-skill`", msg)

    def test_subagents_take_no_tools_or_model(self):
        agent = "sub_agents/probe-agent/AGENT.md"
        msg = self.problems(**{agent: self.tree[agent].replace("---\n", "---\ntools: x\n", 1)})
        self.assertIn(f"{agent} frontmatter may use only ['description', 'name']", msg)

    def test_always_on_cap_is_hermes_context_file_cap(self):
        msg = self.problems(**{"LongTermMEMORY.md": "x" * 20_001})
        self.assertIn("over the 20000 cap", msg)

    def test_improver_prompts_know_the_hermes_surface(self):
        bp = BenchPrompts(work="clean a table")
        text = P.propose(bp, "INV", HM.HERMES_SURFACE)
        self.assertIn("`hooks.json`", text)
        self.assertIn("`agent-<name>`", text)
        self.assertNotIn(".claude/settings.json", text)


class MaterialiseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def stage(self, tree: HT.Tree, ctx=None) -> Path:
        d = self.tmp / "tree"
        for rel, body in tree.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(body)
        install = HM.HermesSubstrate().materialise(d, spec(self.tmp), ctx or {})
        self.addCleanup(shutil.rmtree, install.staging_dir, ignore_errors=True)
        return install.staging_dir

    def test_components_land_where_hermes_reads_them(self):
        tree = CF.build_tree("n0")
        staged = self.stage(tree, {"file:data/in.csv": "a,b\n"})
        files = sorted(str(p.relative_to(staged)) for p in staged.rglob("*") if p.is_file())
        self.assertEqual(
            files,
            [
                "home/SOUL.md",
                "home/memories/MEMORY.md",
                "home/skills/agent-probe-agent/SKILL.md",
                "tree-hooks.json",
                "work/data/in.csv",
                "work/scripts/probe_code.py",
                "work/skills/probe-skill/SKILL.md",
                "work/skills/probe-skill/scripts/skill_code.py",
            ],
        )

    def test_soul_is_system_prompt_then_sections_then_subagents(self):
        staged = self.stage(
            {
                "systemprompt.md": "Be careful.\n",
                "guardrails.md": "Never guess.\n",
                "LongTermMEMORY.md": "",
                "tool_descriptions/tool_guidance.md": "Prefer patch.\n",
                "sub_agents/reader/AGENT.md": "---\ndescription: Reads.\n---\nSummarise.\n",
            }
        )
        self.assertEqual(
            (staged / "home/SOUL.md").read_text(),
            "Be careful.\n\n# Guardrails\n\nNever guess.\n\n# Tool guidance\n\nPrefer patch.\n\n"
            "# Subagents\n\nThese subagents are available: `reader` (skill `agent-reader`). To "
            "consult one, load its skill with skill_view and call delegate_task with the brief "
            "from that skill, verbatim, as `context`, followed by the inputs the subagent needs; "
            "put the question in `goal`. The subagent sees nothing else.\n",
        )
        self.assertEqual(
            (staged / "home/skills/agent-reader/SKILL.md").read_text(),
            '---\nname: agent-reader\ndescription: "Brief for the reader subagent: Reads."\n---\n'
            "Subagent `reader`. Call delegate_task with the brief below, verbatim, as `context` "
            "(add the inputs the task needs after it) and the question as `goal`.\n\n"
            "## Brief\n\nSummarise.\n",
        )

    def test_memory_paragraphs_become_entries(self):
        staged = self.stage(
            {
                "systemprompt.md": "x\n",
                "LongTermMEMORY.md": "Fact one.\nstill one.\n\n\nFact two.\n",
            }
        )
        self.assertEqual(
            (staged / "home/memories/MEMORY.md").read_text(),
            "Fact one.\nstill one.\n§\nFact two.\n",
        )

    def test_only_the_hooks_key_of_hooks_json_is_staged(self):
        hooks = {"pre_tool_call": [{"command": "true"}]}
        staged = self.stage(
            {
                "systemprompt.md": "x\n",
                HM.HOOKS_FILE: json.dumps({"hooks": hooks, **CF.OVERRIDE_KEYS}),
            }
        )
        self.assertEqual(json.loads((staged / "tree-hooks.json").read_text()), hooks)

    def test_agent_prefix_is_reserved_for_subagent_briefs(self):
        with self.assertRaisesRegex(ValueError, r"skills \['agent-x'\] use the `agent-` prefix"):
            self.stage(
                {
                    "systemprompt.md": "use the `agent-x` skill\n",
                    "skills/agent-x/SKILL.md": "---\nname: agent-x\ndescription: d\n---\nb\n",
                }
            )

    def test_wrong_install_mode_is_refused(self):
        bad = BenchSpec(**{**spec(self.tmp).__dict__, "install_mode": "claude_workspace"})
        with self.assertRaisesRegex(ValueError, "not the Hermes mode"):
            HM.HermesSubstrate().materialise(self.tmp, bad, {})


class FloorTests(unittest.TestCase):
    def test_operator_hooks_run_before_harness_hooks(self):
        merged = HM.merge_hooks(
            {"pre_tool_call": [{"command": "guard"}]},
            {"pre_tool_call": [{"command": "tree"}], "pre_llm_call": [{"command": "ctx"}]},
        )
        self.assertEqual(
            merged,
            {
                "pre_tool_call": [{"command": "guard"}, {"command": "tree"}],
                "pre_llm_call": [{"command": "ctx"}],
            },
        )

    def test_floor_config_is_fixed_whatever_the_hooks(self):
        cfg = HM.floor_config(
            work=Path("/r/work"), model="m", provider="anthropic", hooks={"pre_verify": []}
        )
        self.assertEqual(cfg["model"], {"default": "m", "provider": "anthropic"})
        self.assertEqual(cfg["approvals"], {"mode": "manual", "single_query_mode": "deny"})
        self.assertEqual(cfg["memory"]["memory_char_limit"], 20_000)
        self.assertEqual(cfg["memory"]["nudge_interval"], 0)
        self.assertFalse(cfg["auxiliary"]["background_review"]["enabled"])
        self.assertFalse(cfg["auxiliary"]["title_generation"]["enabled"])
        self.assertEqual(cfg["skills"]["external_dirs"], ["/r/work/skills"])
        self.assertFalse(cfg["curator"]["enabled"])
        self.assertFalse(cfg["auth"]["adopt_external_logins"])
        self.assertEqual(cfg["hooks"], {"pre_verify": []})

    def test_rollout_root_inside_a_hermes_home_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "inside a .hermes directory"):
            HM.check_root(Path("/srv/u/.hermes/rollouts"))

    def test_rollout_root_inside_a_git_checkout_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "repo" / ".git").mkdir(parents=True)
        (tmp / "outside").mkdir()
        (tmp / "link").symlink_to(tmp / "repo")
        HM.check_root(tmp / "outside" / "rollouts")
        for root in (tmp / "repo" / "runs" / "rollouts", tmp / "link" / "rollouts"):
            with self.assertRaisesRegex(RuntimeError, "inside the git checkout"):
                HM.check_root(root)

    def test_cost_counts_each_call_once_and_names_its_source(self):
        def usage(*rows):
            return HM.usage_summary(
                {"usage": [{"actual_cost_usd": a, "estimated_cost_usd": e} for a, e in rows]}
            )

        self.assertEqual(
            [
                (u["cost_usd"], u["cost_source"])
                for u in (
                    usage((0.5, 0.4), (0.0, 0.25)),
                    usage((0.5, 0.4)),
                    usage((None, 0.25)),
                    usage((None, None)),
                )
            ],
            [(0.75, "mixed"), (0.5, "actual"), (0.25, "estimated"), (None, "unknown")],
        )

    def test_launch_reads_its_settings_from_config(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"local": {"base_url": "http://127.0.0.1:1/v1"}}, f)
        self.addCleanup(os.unlink, f.name)
        with (
            patch.object(config, "HERMES_CMD", "/opt/h/hermes --flag"),
            patch.object(config, "HERMES_RUNNER", "sudo -n -u bot"),
            patch.object(config, "HERMES_ROLLOUTS", Path("/srv/rollouts")),
            patch.object(config, "HERMES_PASS_ENV", "A_KEY, B_KEY"),
            patch.object(config, "HERMES_PROVIDERS_FILE", f.name),
        ):
            launch = HM.Launch.from_config()
        self.assertEqual(launch.hermes, ("/opt/h/hermes", "--flag"))
        self.assertEqual(launch.runner, ("sudo", "-n", "-u", "bot"))
        self.assertEqual(launch.root, Path("/srv/rollouts"))
        self.assertEqual(launch.pass_env, ("A_KEY", "B_KEY"))
        self.assertEqual(launch.providers, {"local": {"base_url": "http://127.0.0.1:1/v1"}})


FAKE_HERMES = textwrap.dedent(
    """
    import json, os, sqlite3, sys
    if sys.argv[1:] == ["--version"]:
        print("Hermes Agent v0-test")
        sys.exit(0)
    home = os.environ["HERMES_HOME"]
    root = os.path.dirname(home)
    with open(os.path.join(root, "seen.json"), "w") as f:
        json.dump({"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd(),
                   "config": json.load(open(os.path.join(home, "config.yaml")))}, f)
    os.makedirs("output", exist_ok=True)
    open("output/result.csv", "w").write("a,b\\n1,2\\n")
    if os.environ.get("FAKE_MUTATE"):
        with open("skills/probe-skill/SKILL.md", "a") as f:
            f.write("tampered\\n")
    if os.environ.get("FAKE_LINKS"):
        os.symlink("/dev/zero", "skills/probe-skill/zero")
        os.symlink("missing-target", "skills/probe-skill/dangling")
        os.mkfifo("skills/probe-skill/pipe")
    db = sqlite3.connect(os.path.join(home, "state.db"))
    db.executescript(
        "CREATE TABLE sessions (id TEXT, parent_session_id TEXT, model TEXT, started_at REAL,"
        " system_prompt_hash TEXT);"
        "CREATE TABLE session_model_usage (session_id TEXT, model TEXT, task TEXT,"
        " input_tokens INT, output_tokens INT, api_call_count INT, estimated_cost_usd REAL,"
        " actual_cost_usd REAL);"
        "CREATE TABLE system_prompts (hash TEXT, prompt TEXT);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT);"
        "INSERT INTO sessions VALUES ('s1', NULL, 'm', 1, 'h1');"
        "INSERT INTO sessions VALUES ('s2', 's1', 'm', 2, NULL);"
        "INSERT INTO session_model_usage VALUES ('s1', 'm', NULL, 100, 20, 2, 0.5, 0);"
        "INSERT INTO session_model_usage VALUES ('s2', 'm', NULL, 10, 5, 1, 0.25, 0);"
        "INSERT INTO system_prompts VALUES ('h1', 'SOUL TEXT');"
        "INSERT INTO messages (session_id, role, content) VALUES ('s2', 'assistant', 'child says');"
    )
    db.commit()
    for ev in (
        {"type": "system", "subtype": "init", "model": "m", "session_id": "s1"},
        {"type": "tool_use", "name": "terminal", "tool_call_id": "c1",
         "input": {"command": "ls"}},
        {"type": "tool_result", "name": "terminal", "tool_call_id": "c1",
         "output": "output", "duration_ms": 3, "is_error": False},
        {"type": "text", "text": "Done "},
        {"type": "text", "text": "now."},
        {"type": "result", "session_id": "s1", "exit_code": 0, "text": "Done now.",
         "tokens": {"input": 100, "output": 20}, "duration_ms": 9},
    ):
        print(json.dumps(ev))
    """
)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        fake = self.tmp / "fake_hermes.py"
        fake.write_text(FAKE_HERMES)
        self.launch = HM.Launch(
            hermes=(sys.executable, str(fake)),
            root=self.tmp / "rollouts",
            pass_env=("H2_TEST_SECRET",),
            python=sys.executable,
        )
        tree_dir = HT.write_tree(HM.HERMES_SURFACE, CF.build_tree("n0"), self.tmp / "tree")
        self.install = HM.HermesSubstrate().materialise(tree_dir, spec(self.tmp), {})
        self.addCleanup(shutil.rmtree, self.install.staging_dir, ignore_errors=True)
        self.task = self.tmp / "task"
        (self.task / "data").mkdir(parents=True)
        (self.task / "data" / "in.csv").write_text("x\n")

    def run_once(self, **env) -> tuple[dict, dict, Path]:
        run_dir = self.tmp / "runs" / "r1"
        with patch.dict(os.environ, {"H2_TEST_SECRET": "s3cret", "H2_NOT_PASSED": "no"}):
            record = HM.run_rollout(
                self.install,
                run_dir,
                "Clean the table.",
                model="m",
                provider="anthropic",
                timeout=30,
                task_files=self.task,
                hooks={"pre_tool_call": [{"command": "guard"}]},
                env={"H2_GUARD_DENY": "secret-dir", **env},
                launch=self.launch,
            )
        seen = json.loads((Path(record["rollout_root"]) / "seen.json").read_text())
        return record, seen, run_dir

    def test_rollout_runs_in_an_empty_environment_with_a_fresh_home(self):
        record, seen, _ = self.run_once()
        root = Path(record["rollout_root"])
        self.assertEqual(
            sorted(seen["env"].keys() - {"__CF_USER_TEXT_ENCODING"}),
            [
                "H2_GUARD_DENY",
                "H2_TEST_SECRET",
                "HERMES_ACCEPT_HOOKS",
                "HERMES_BUNDLED_SKILLS",
                "HERMES_HOME",
                "HOME",
                "LANG",
                "PATH",
                "TERMINAL_CWD",
                "TERMINAL_HOME_MODE",
            ],
        )
        self.assertEqual(seen["env"]["HERMES_HOME"], str(root / "home"))
        self.assertEqual(seen["env"]["HOME"], str(root / "home" / "home"))
        self.assertEqual(seen["cwd"], str((root / "work").resolve()))
        self.assertEqual(
            seen["argv"],
            [
                "chat",
                "--query-file",
                str(root / "task.md"),
                "-Q",
                "--format",
                "stream-json",
                "-m",
                "m",
                "--provider",
                "anthropic",
                "-t",
                "terminal,file,skills,delegation",
                "--max-turns",
                "60",
                "--run-budget",
                "30",
            ],
        )
        self.assertNotIn("s3cret", json.dumps(seen["argv"]))
        self.assertEqual(
            seen["config"]["hooks"],
            {
                "pre_tool_call": [{"command": "guard"}],
                "pre_llm_call": json.loads(CF.build_tree("n0")[HM.HOOKS_FILE])["hooks"][
                    "pre_llm_call"
                ],
            },
        )

    def test_results_come_back_to_the_run_dir(self):
        record, _, run_dir = self.run_once()
        self.assertEqual(
            (run_dir / "workspace" / "output" / "result.csv").read_text(), "a,b\n1,2\n"
        )
        self.assertEqual((run_dir / "workspace" / "data" / "in.csv").read_text(), "x\n")
        self.assertEqual((run_dir / "system_prompt.md").read_text(), "SOUL TEXT")
        self.assertEqual(
            {k: record[k] for k in ("exit_code", "result", "cost_usd", "cost_source", "sessions")},
            {
                "exit_code": 0,
                "result": "Done now.",
                "cost_usd": 0.75,
                "cost_source": "estimated",
                "sessions": 2,
            },
        )
        self.assertEqual(
            (record["input_tokens"], record["output_tokens"], record["api_calls"]), (110, 25, 3)
        )
        self.assertEqual(record["harness_mutated"], [])
        self.assertEqual(record["home_skills"], ["agent-probe-agent"])
        self.assertEqual(json.loads((run_dir / "rollout.json").read_text()), record)

    def test_a_run_that_edits_its_own_harness_is_flagged(self):
        record, _, _ = self.run_once(FAKE_MUTATE="1")
        self.assertEqual(record["harness_mutated"], ["work/skills/probe-skill/SKILL.md"])

    def test_links_and_special_files_are_flagged_without_reading_them(self):
        record, _, _ = self.run_once(FAKE_LINKS="1")
        self.assertEqual(
            record["harness_mutated"],
            [
                "work/skills/probe-skill/dangling",
                "work/skills/probe-skill/pipe",
                "work/skills/probe-skill/zero",
            ],
        )
        self.assertEqual((record["input_tokens"], record["sessions"]), (110, 2))
        self.assertNotIn("inspect_error", record)

    def test_preflight_runs_the_command_without_a_model(self):
        HM.HermesSubstrate().preflight(self.launch)
        broken = HM.Launch(hermes=("false",), root=self.tmp / "r2", python=sys.executable)
        with self.assertRaisesRegex(RuntimeError, "--version` failed"):
            HM.HermesSubstrate().preflight(broken)


class RecordedRunTests(unittest.TestCase):
    """One live conformance rollout, recorded: renderer and read-back."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(FIXTURE, self.tmp, dirs_exist_ok=True)
        self.state = json.loads((FIXTURE / "state.json").read_text())

    def test_trajectory_renders_in_the_shared_grammar(self):
        out = HM.render_stream(FIXTURE / "stream.jsonl", obs_trunc=200, max_chars=100_000)
        lines = out.splitlines()
        self.assertEqual(lines[0], "[HARNESS] session: model=claude-haiku-5-5")
        self.assertEqual(lines[1], "[ACTION] terminal: python3 scripts/probe_code.py")
        self.assertEqual(
            lines[2],
            '[OBSERVATION] {"output": "MARKER-C7-9ec963f2", "exit_code": 0, "error": null}',
        )
        self.assertEqual(lines[3], '[ACTION] skill_view: {"name": "probe-skill"}')
        self.assertIn("[ASSISTANT] Configuration check complete. All steps ran in order:", lines)
        self.assertEqual(
            lines[-1], "[HARNESS] result: exit=0 | tokens in=8 out=1211 | duration_ms=10279"
        )

    def test_an_unpriced_subscription_run_has_no_cost(self):
        usage = HM.usage_summary(self.state)
        self.assertEqual(
            (usage["cost_usd"], usage["cost_source"], usage["sessions"], usage["auxiliary_tasks"]),
            (None, "unknown", 2, []),
        )

    def test_every_component_check_passes_on_the_recorded_run(self):
        checks = CF.evaluate(self.tmp, NONCE, self.state)
        self.assertEqual({c: v["ok"] for c, v in checks.items()}, {c: True for c in CF.COMPONENTS})

    def test_floor_holds_on_the_recorded_run(self):
        record = {
            **HM.usage_summary(self.state),
            "home_skills": self.state["skills_dir"],
            "harness_mutated": [],
        }
        self.assertTrue(CF.evaluate_floor(self.tmp, NONCE, record, self.state)["ok"])

    def test_floor_fails_when_a_canary_leaks(self):
        record = {
            **HM.usage_summary(self.state),
            "home_skills": self.state["skills_dir"],
            "harness_mutated": [],
        }
        prompt = self.tmp / "system_prompt.md"
        prompt.write_text(prompt.read_text() + f"\nCANARY-ANCESTOR-{NONCE}\n")
        floor = CF.evaluate_floor(self.tmp, NONCE, record, self.state)
        self.assertFalse(floor["ok"])
        self.assertIn("ancestor canary in prompt or answer=True", floor["evidence"])

    def test_a_check_fails_when_its_evidence_is_missing(self):
        (self.tmp / "workspace" / "c8_hook.log").unlink()
        state = {**self.state, "children": []}
        checks = CF.evaluate(self.tmp, NONCE, state)
        self.assertFalse(checks["C8"]["ok"])
        self.assertFalse(checks["C5"]["ok"])
        self.assertTrue(checks["C7"]["ok"])


if __name__ == "__main__":
    unittest.main()
