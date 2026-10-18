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

"""The frozen floor for headless Claude Code sessions: settings no harness edit can reach.

A `claude -p` session started in a workspace still discovers the user's own CLAUDE.md and any
CLAUDE.md in a parent directory, and keeps an auto-memory directory outside the workspace. The
floor, passed with `--settings`, excludes those files by absolute path and turns auto-memory
off, so the only instructions a session sees are the ones the workspace carries. An isolated
CLAUDE_CONFIG_DIR or `--bare` would also isolate it, but both drop a subscription login.

Operator hooks given here run in addition to the workspace's own `.claude/settings.json`
hooks, so a hook in the floor fires whatever the harness says.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

# Tools whose effects outlive the session (schedules, remote triggers, notifications,
# background orchestration). A rollout must be rerunnable without side effects.
PERSISTENT_TOOLS = (
    "CronCreate",
    "CronDelete",
    "RemoteTrigger",
    "PushNotification",
    "ScheduleWakeup",
    "Workflow",
    "DesignSync",
    "SendMessage",
)

ISOLATION_FLAGS = (
    "--setting-sources",
    "project",
    "--strict-mcp-config",
    "--no-session-persistence",
)


def user_config_dirs() -> list[Path]:
    """Where Claude Code reads user-level instructions: CLAUDE_CONFIG_DIR, then ~/.claude."""
    dirs = []
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        dirs.append(Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser())
    dirs.append(Path.home() / ".claude")
    return list(dict.fromkeys(d.resolve() for d in dirs))


def instruction_excludes(workspace: Path) -> list[str]:
    """Absolute globs for every CLAUDE.md a session in `workspace` could find outside it."""
    out = []
    for d in user_config_dirs():
        out += [str(d / "CLAUDE.md"), str(d / "rules" / "**")]
    # Both spellings of each ancestor, since a symlinked path (macOS /tmp) may be matched as is.
    given, real = Path(workspace).absolute(), Path(workspace).resolve()
    for parent in [*given.parents, *real.parents]:
        out += [
            str(parent / "CLAUDE.md"),
            str(parent / "CLAUDE.local.md"),
            str(parent / ".claude" / "CLAUDE.md"),
            str(parent / ".claude" / "rules" / "**"),
        ]
    return list(dict.fromkeys(out))


def floor_settings(workspace: Path, *, hooks: Mapping | None = None) -> dict:
    """The settings document for `--settings`: isolation, no persistent tools, operator hooks."""
    doc: dict = {
        "claudeMdExcludes": instruction_excludes(workspace),
        "autoMemoryEnabled": False,
        "disableAllHooks": False,
        "permissions": {"deny": list(PERSISTENT_TOOLS)},
    }
    if hooks:
        doc["hooks"] = json.loads(json.dumps(dict(hooks)))
    return doc


def write_floor(path: Path, workspace: Path, *, hooks: Mapping | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(floor_settings(workspace, hooks=hooks), indent=2), encoding="utf-8")
    return path
