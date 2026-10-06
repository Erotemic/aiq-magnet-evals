"""Deterministic HTTP and tool-call endpoints; no engine or GPU dependency."""
from __future__ import annotations

import contextlib
import json
import threading
import time
from http.server import ThreadingHTTPServer

from tests.native.chat_server import DeterministicChatHandler


@contextlib.contextmanager
def scripted_endpoint(commands=(), *, delay=0, error=False, malformed=False):
    """Validate the prior tool results before returning each scripted command.

    Each server owns its request capture and script, permitting independent
    concurrent endpoints. An empty script is a repeatable transport endpoint.
    """
    requests = []

    class Handler(DeterministicChatHandler):
        def do_GET(self):
            self.reply(200, {"object": "list", "data": [{
                "id": "fixture-coding", "object": "model", "owned_by": "fixture",
            }]})

        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            if delay:
                time.sleep(delay)
            if error:
                self.reply(503, {"error": {"message": "scripted endpoint outage"}})
                return
            messages = request.get("messages", [])
            completed = [m for m in messages if m.get("role") == "tool"]
            assistants = [m for m in messages if m.get("tool_calls")]
            index = len(completed)
            if commands and (len(assistants) != index or any(
                m.get("tool_call_id") != f"call_{i}"
                for i, m in enumerate(completed)
            ) or any(
                json.loads(m["tool_calls"][0]["function"]["arguments"])["command"] != commands[i]
                for i, m in enumerate(assistants)
            )):
                self.reply(409, {"error": {"message": "script conversation mismatch"}})
                return
            message = {"role": "assistant", "content": "Done."}
            if index < len(commands):
                message = {
                    "role": "assistant", "content": "Execute the next fixture step.",
                    "tool_calls": [{"id": f"call_{index}", "type": "function", "function": {
                        "name": "bash", "arguments": json.dumps({"command": commands[index]}),
                    }}],
                }
            if malformed:
                self.reply(200, {"invalid": True})
                return
            self.reply(200, {
                "id": f"chatcmpl-fixture-{len(requests)}", "object": "chat.completion",
                "created": int(time.time()), "model": request.get("model", "fixture-coding"),
                "choices": [{"index": 0, "message": message,
                             "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            })

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
