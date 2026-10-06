"""Native Harbor test agent: execute scripted tool calls in its actual sandbox.

This proves transport/tools, not the capability of any production agent.
"""
from __future__ import annotations

import json
import shlex

from harbor.agents.base import BaseAgent

PROBE = '''
import json, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
targets = json.load(open("/tmp/probe-targets.json"))
results = {}
for name, url in targets.items():
    try:
        with opener.open(url, timeout=5) as response:
            results[name] = {"reachable": response.status == 200}
    except Exception as exc:
        results[name] = {"reachable": False, "exception": type(exc).__name__}
print(json.dumps(results))
'''

CHAT = '''
import json, urllib.request
body = json.load(open("/tmp/chat-request.json"))
url = json.load(open("/tmp/probe-targets.json"))["allowed"].rsplit("/models", 1)[0]
request = urllib.request.Request(url + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(request, timeout=10) as response:
    print(response.read().decode())
'''


class ProbeAgent(BaseAgent):
    def __init__(self, *args, targets, chat=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.targets = targets
        self.chat = chat

    @staticmethod
    def name():
        return "aiq-harbor-phase0-probe"

    def version(self):
        return "1"

    async def setup(self, environment):
        (self.logs_dir / "environment-capabilities.json").write_text(
            environment.capabilities.model_dump_json(indent=2))
        targets = self.logs_dir / "probe-targets.json"
        targets.write_text(json.dumps(self.targets))
        await environment.upload_file(source_path=targets, target_path="/tmp/probe-targets.json")
        probe = self.logs_dir / "network-probe.py"
        probe.write_text(PROBE)
        await environment.upload_file(source_path=probe, target_path="/tmp/network-probe.py")
        result = await environment.exec(command="python /tmp/network-probe.py", timeout_sec=30)
        (self.logs_dir / "network-setup.json").write_text(result.stdout)

    async def run(self, instruction, environment, context):
        result = await environment.exec(command="python /tmp/network-probe.py", timeout_sec=30)
        (self.logs_dir / "network-agent.json").write_text(result.stdout)
        if not self.chat:
            return
        messages = [{"role": "user", "content": instruction}]
        trajectory = []
        for _ in range(10):
            request = self.logs_dir / "chat-request.json"
            request.write_text(json.dumps({"model": "fixture-coding", "messages": messages,
                "tools": [{"type": "function", "function": {"name": "bash",
                    "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                                   "required": ["command"]}}}]}))
            await environment.upload_file(source_path=request, target_path="/tmp/chat-request.json")
            response = await environment.exec(command="python -c " + shlex.quote(CHAT), timeout_sec=30)
            if response.return_code:
                raise RuntimeError(f"endpoint request failed: {response.stderr}")
            completion = json.loads(response.stdout)
            usage = completion.get("usage", {})
            if "prompt_tokens" in usage:
                context.n_input_tokens = (context.n_input_tokens or 0) + usage["prompt_tokens"]
            if "completion_tokens" in usage:
                context.n_output_tokens = (context.n_output_tokens or 0) + usage["completion_tokens"]
            message = completion["choices"][0]["message"]
            messages.append(message)
            if not message.get("tool_calls"):
                break
            for call in message["tool_calls"]:
                command = json.loads(call["function"]["arguments"])["command"]
                result = await environment.exec(command=command, timeout_sec=30)
                observation = {"command": command, "return_code": result.return_code,
                               "stdout": result.stdout, "stderr": result.stderr}
                trajectory.append(observation)
                (self.logs_dir / "trajectory.json").write_text(json.dumps(trajectory, indent=2))
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(observation)})
        else:
            raise RuntimeError("script exceeded fixture step limit")
        # Capture the actual diff, including any newly created files.
        await environment.exec(command="cd /app && git add -A && git diff --cached > /logs/agent/model.patch && git reset -q")
