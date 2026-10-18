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

"""A scripted OpenAI-compatible chat endpoint for running a real agent with no model.

The agent framework sends real requests (system prompt, tools, history); a policy function
decides the reply, and every request is appended to a JSONL log. A probe can then prove what
reached the model by reading the log, without a credential and without spend.

    python tests/scripted_model.py --port 8765 --log requests.jsonl --policy conformance
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CODE = re.compile(r"\b(?:MARKER|CANARY)-[A-Za-z0-9-]+\b")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _call(name: str, args: dict) -> dict:
    return {"tool_calls": [{"name": name, "arguments": args}]}


def _say(text: str) -> dict:
    return {"content": text}


def _tool_names(req: dict) -> set[str]:
    return {(t.get("function") or {}).get("name") for t in req.get("tools") or []}


def policy_echo(req: dict) -> dict:
    return _say("DONE")


def policy_conformance(req: dict) -> dict:
    """A cooperative model that follows the conformance instructions step by step.

    It reports only codes that literally reached it: in the system prompt, the user turn, hook
    context or tool results. A delegated child (no delegate_task tool) answers with the codes
    in its own goal and context.
    """
    msgs = req.get("messages") or []
    tools = _tool_names(req)
    seen = "\n".join(_text(m.get("content")) for m in msgs)
    results = [_text(m.get("content")) for m in msgs if m.get("role") == "tool"]
    done = "\n".join(
        json.dumps(tc.get("function", {}), ensure_ascii=False)
        for m in msgs
        if m.get("role") == "assistant"
        for tc in m.get("tool_calls") or []
    )
    if "delegate_task" not in tools:
        return _say(" ".join(dict.fromkeys(CODE.findall(seen))) or "NO CODE")
    if "probe_code.py" not in done:
        return _call("terminal", {"command": "python3 scripts/probe_code.py"})
    if "probe-skill" not in done:
        return _call("skill_view", {"name": "probe-skill"})
    if "skill_code.py" not in done:
        m = re.search(r"python3 (\S*skill_code\.py)", "\n".join(results))
        return _call("terminal", {"command": f"python3 {m.group(1) if m else 'skill_code.py'}"})
    if "agent-probe-agent" not in done:
        return _call("skill_view", {"name": "agent-probe-agent"})
    if "delegate_task" not in done:
        brief = next((r for r in reversed(results) if "probe-agent" in r), "")
        return _call(
            "delegate_task",
            {"goal": "Return your conformance code.", "context": brief[:4000]},
        )
    return _say_codes(seen)


def _say_codes(seen: str) -> dict:
    codes = " ".join(dict.fromkeys(CODE.findall(seen)))
    return _say(f"Configuration check complete.\nCODES: {codes}\nFILES: (scripted)")


POLICIES = {"echo": policy_echo, "conformance": policy_conformance}


def _completion(model: str, reply: dict) -> dict:
    msg: dict = {"role": "assistant", "content": reply.get("content")}
    if reply.get("tool_calls"):
        msg["tool_calls"] = [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
            }
            for c in reply["tool_calls"]
        ]
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": "tool_calls" if reply.get("tool_calls") else "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    }


def _chunks(body: dict):
    """The same completion as an SSE stream: one delta with everything, then usage, then DONE."""
    choice = body["choices"][0]
    delta = {"role": "assistant", "content": choice["message"].get("content") or ""}
    if choice["message"].get("tool_calls"):
        delta["tool_calls"] = [
            {"index": i, **tc} for i, tc in enumerate(choice["message"]["tool_calls"])
        ]
    base = {k: body[k] for k in ("id", "created", "model")} | {"object": "chat.completion.chunk"}
    yield {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
    yield {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]}
    yield {**base, "choices": [], "usage": body["usage"]}


def make_server(port: int, log: Path, policy) -> ThreadingHTTPServer:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code: int, doc: dict):
            data = json.dumps(doc).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/").endswith("/models"):
                return self._json(
                    200,
                    {
                        "object": "list",
                        "data": [{"id": "scripted", "object": "model", "context_length": 200000}],
                    },
                )
            self._json(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            with lock, log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"path": self.path, "request": req}) + "\n")
            if not self.path.rstrip("/").endswith("/chat/completions"):
                return self._json(404, {"error": f"unsupported {self.path}"})
            body = _completion(req.get("model", "scripted"), policy(req))
            if not req.get("stream"):
                return self._json(200, body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in _chunks(body):
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--policy", choices=sorted(POLICIES), default="echo")
    a = p.parse_args()
    make_server(a.port, a.log, POLICIES[a.policy]).serve_forever()


if __name__ == "__main__":
    main()
