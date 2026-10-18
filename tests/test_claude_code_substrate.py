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

"""ClaudeCodeSubstrate: surface rules, materialise, floor, argv, renderer and conformance read-back.

The renderer and conformance tests read a recorded stream from one live conformance rollout
(claude-haiku-5-5, Claude Code 2.1.301) with host paths replaced.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness2 import claude_floor, conformance
from harness2.core import runmark as RM
from harness2.core import tree as HT
from harness2.core.proposer import Proposer
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
from harness2.substrate import claude_code as CC

FIXTURE = Path(__file__).parent / "fixtures" / "claude_code" / "conformance"
NONCE = "9f111c20"


def spec(root: Path) -> BenchSpec:
    channel = ChannelSpec("claude_cli", "claude-haiku-5-5")
    return BenchSpec(
        name="t",
        runs_root=root,
        install_mode=CC.INSTALL_MODE,
        prompts=BenchPrompts(work="clean a table"),
        channels={"proposer": channel, "selector": channel},
        allow_subagents=True,
    )


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tree = conformance.build_tree("n0")

    def problems(self, **changes) -> str:
        with self.assertRaises(ValueError) as cm:
            HT.validate(CC.CLAUDE_SURFACE, {**self.tree, **changes})
        return str(cm.exception)

    def test_probe_tree_is_a_valid_harness(self):
        census = HT.validate(CC.CLAUDE_SURFACE, self.tree)
        self.assertEqual(
            (census["skills"], census["sub_agents"], census["scripts"], census["hooks"]),
            (1, 1, 1, 1),
        )

    def test_settings_file_holds_hooks_only(self):
        settings = {"hooks": {}, "permissions": {"allow": ["Bash"]}, "env": {"X": "1"}}
        msg = self.problems(**{CC.SETTINGS_FILE: json.dumps(settings)})
        self.assertIn("remove ['env', 'permissions']", msg)

    def test_frontmatter_keys_outside_the_allowlist_are_refused(self):
        skill = ".claude/skills/probe-skill/SKILL.md"
        agent = "sub_agents/probe-agent/AGENT.md"
        msg = self.problems(
            **{
                skill: self.tree[skill].replace("name:", "hooks: x\nname:"),
                agent: self.tree[agent].replace("description:", "permissionMode: x\ndescription:"),
            }
        )
        self.assertIn(
            f"{skill} frontmatter may use only ['description', 'name']; remove ['hooks']", msg
        )
        self.assertIn("remove ['permissionMode']", msg)

    def test_untriggered_skill_is_refused(self):
        guard = self.tree["guardrails.md"].replace("`probe-skill`", "the skill")
        self.assertIn(
            "skill 'probe-skill' is never named", self.problems(**{"guardrails.md": guard})
        )


class MaterialiseTests(unittest.TestCase):
    def test_components_land_where_claude_code_reads_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree_dir = HT.write_tree(CC.CLAUDE_SURFACE, conformance.build_tree("n1"), root / "tree")
            install = CC.ClaudeCodeSubstrate().materialise(
                tree_dir, spec(root), {"file:task.md": "x"}
            )
            staged = install.staging_dir
            self.addCleanup(shutil.rmtree, staged, True)
            files = sorted(str(p.relative_to(staged)) for p in staged.rglob("*") if p.is_file())
            self.assertEqual(
                files,
                [
                    ".claude/agents/probe-agent.md",
                    ".claude/settings.json",
                    ".claude/skills/probe-skill/SKILL.md",
                    ".claude/skills/probe-skill/scripts/skill_code.py",
                    ".claude/systemprompt.md",
                    "CLAUDE.md",
                    "scripts/probe_code.py",
                    "task.md",
                ],
            )
            claude_md = (staged / "CLAUDE.md").read_text()
            self.assertEqual(
                [ln for ln in claude_md.splitlines() if ln.startswith("# ")],
                ["# Guardrails", "# Long-term memory", "# Tool guidance"],
            )
            self.assertTrue(
                (staged / ".claude/agents/probe-agent.md")
                .read_text()
                .startswith("---\nname: probe-agent\ndescription:")
            )
            self.assertIn("MARKER-C1-n1", (staged / CC.SYSTEM_PROMPT_FILE).read_text())
            self.assertEqual(install.fingerprint, RM.fingerprint(tree_dir))

    def test_agent_name_is_the_directory_name(self):
        self.assertEqual(
            CC.agent_file("a", "---\nname: b\ndescription: d\n---\nbody\n"),
            "---\nname: a\ndescription: d\n---\nbody\n",
        )


class FloorTests(unittest.TestCase):
    def test_floor_excludes_instructions_outside_the_workspace(self):
        ws = Path("/tmp/h2-floor/a/b/workspace")
        with patch.object(claude_floor, "user_config_dirs", return_value=[Path("/cfg")]):
            doc = claude_floor.floor_settings(ws, hooks={"PreToolUse": []})
        for path in (
            "/cfg/CLAUDE.md",
            "/cfg/rules/**",
            "/tmp/h2-floor/a/b/CLAUDE.md",
            "/tmp/h2-floor/a/b/.claude/rules/**",
            "/CLAUDE.md",
        ):
            self.assertIn(path, doc["claudeMdExcludes"])
        self.assertNotIn(str(ws / "CLAUDE.md"), doc["claudeMdExcludes"])
        self.assertIs(doc["autoMemoryEnabled"], False)
        self.assertIs(doc["disableAllHooks"], False)
        self.assertEqual(doc["hooks"], {"PreToolUse": []})
        self.assertIn("CronCreate", doc["permissions"]["deny"])

    def test_rollout_argv_carries_isolation_and_the_floor(self):
        argv = CC.exec_argv(
            "do it",
            model="m",
            floor_path=Path("/f.json"),
            system_prompt_file=Path("/w/.claude/systemprompt.md"),
            claude_bin="claude",
        )
        self.assertEqual(argv[:3], ["claude", "-p", "do it"])
        for pair in (
            ["--setting-sources", "project"],
            ["--settings", "/f.json"],
            ["--model", "m"],
            ["--append-system-prompt-file", "/w/.claude/systemprompt.md"],
        ):
            i = argv.index(pair[0])
            self.assertEqual(argv[i : i + 2], pair)
        for flag in ("--strict-mcp-config", "--no-session-persistence", "--verbose"):
            self.assertIn(flag, argv)

    def test_improver_session_runs_under_the_same_floor(self):
        proposer = Proposer(ChannelSpec("claude_cli", "claude-haiku-5-5"))
        reply = json.dumps({"result": "ok", "subtype": "success", "total_cost_usd": 0.01})
        done = subprocess.CompletedProcess([], 0, stdout=reply, stderr="")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(claude_floor, "user_config_dirs", return_value=[Path("/cfg")]),
            patch("harness2.core.proposer.subprocess.run", return_value=done) as run,
        ):
            text, cost, err = proposer._claude_cli(Path(tmp), "mission", "", 60)
        cmd = run.call_args.args[0]
        self.assertEqual((text, cost, err), ("ok", 0.01, ""))
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "project")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn("--no-session-persistence", cmd)
        floor = json.loads(cmd[cmd.index("--settings") + 1])
        self.assertIn("/cfg/CLAUDE.md", floor["claudeMdExcludes"])
        self.assertIs(floor["autoMemoryEnabled"], False)


class TrajectoryTests(unittest.TestCase):
    def test_recorded_stream_renders_to_the_shared_grammar(self):
        text = CC.render_stream(FIXTURE / "stream.jsonl", obs_trunc=4000, max_chars=100_000)
        for expected in (
            "[HARNESS] session: model=claude-haiku-5-5; skills: probe-skill,",
            "[ACTION] Bash: python3 scripts/probe_code.py",
            f"[OBSERVATION] MARKER-C7-{NONCE}",
            '[ACTION] Skill: {"skill": "probe-skill"',
            "[HARNESS skill] Base directory for this skill:",
            '[ACTION] Agent: {"subagent_type": "probe-agent"',
            f"[ASSISTANT] (in subagent) MARKER-C5-{NONCE}",
            f"[OBSERVATION] subagent completed: MARKER-C5-{NONCE}",
            f"[HARNESS hook SessionStart] MARKER-C8-{NONCE}",
            "[HARNESS] result: success | turns=",
        ):
            self.assertIn(expected, text)

    def test_render_clips_to_max_chars(self):
        text = CC.render_stream(FIXTURE / "stream.jsonl", obs_trunc=4000, max_chars=200)
        self.assertEqual(
            text[:200],
            CC.render_stream(FIXTURE / "stream.jsonl", obs_trunc=4000, max_chars=10**6)[:200],
        )
        self.assertRegex(text[200:], r"^\n…\(\+\d+ chars - render truncation\)$")

    def test_result_accounting(self):
        r = CC.result_of(FIXTURE / "stream.jsonl")
        self.assertEqual((r["subtype"], r["is_error"]), ("success", False))
        self.assertGreater(r["cost_usd"], 0)
        self.assertIn(f"MARKER-C1-{NONCE}", r["result"])

    def test_missing_stream_is_an_error_record(self):
        self.assertEqual(CC.result_of(Path("/nonexistent/stream.jsonl"))["is_error"], True)


class ConformanceReadBackTests(unittest.TestCase):
    def test_recorded_run_proves_all_components_and_the_floor(self):
        checks = conformance.evaluate(FIXTURE, NONCE, ["# A user-level heading line"])
        self.assertEqual({k: v["ok"] for k, v in checks.items()}, {k: True for k in checks})
        self.assertEqual(len(checks), 9)

    def test_a_missing_marker_fails_its_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            shutil.copytree(FIXTURE, run)
            stream = run / "stream.jsonl"
            stream.write_text(stream.read_text().replace(f"MARKER-C7-{NONCE}", "gone"))
            (run / "floor_hook.log").unlink()
            checks = conformance.evaluate(run, NONCE, [])
        self.assertFalse(checks["C7"]["ok"])
        self.assertFalse(checks["floor"]["ok"])
        self.assertTrue(checks["C6"]["ok"])


if __name__ == "__main__":
    unittest.main()
