"""The improver channel works without Google Cloud: Vertex is opt-in, login is the CLI's own."""

import os
import unittest
from unittest.mock import patch

from harness2 import config
from harness2.core.proposer import Proposer
from harness2.core.spec import ChannelSpec


class ProviderNeutralTests(unittest.TestCase):
    def test_claude_cli_keeps_the_callers_login_when_vertex_is_off(self):
        proposer = Proposer(ChannelSpec("claude_cli", "claude-haiku-5-5"))
        with (
            patch.object(config, "CLAUDE_VIA_VERTEX", False),
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            env = proposer.env()
        self.assertEqual(env["ANTHROPIC_API_KEY"], "test-key")
        self.assertEqual(env["ANTHROPIC_MODEL"], "claude-haiku-5-5")
        self.assertNotIn("CLAUDE_CODE_USE_VERTEX", env)

    def test_claude_cli_routes_through_vertex_when_asked(self):
        proposer = Proposer(
            ChannelSpec("claude_cli", "claude-haiku-5-5"), project="proj", region="us-east5"
        )
        with (
            patch.object(config, "CLAUDE_VIA_VERTEX", True),
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            env = proposer.env()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["CLAUDE_CODE_USE_VERTEX"], "1")
        self.assertEqual(env["ANTHROPIC_VERTEX_PROJECT_ID"], "proj")
        self.assertEqual(env["CLOUD_ML_REGION"], "us-east5")


if __name__ == "__main__":
    unittest.main()
