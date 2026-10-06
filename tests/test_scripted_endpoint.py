"""The deterministic substitute must detect real protocol drift."""
import json
import urllib.error
import urllib.request

import pytest

from tests.native.harbor_relay import relay
from tests.native.scripted_endpoint import scripted_endpoint


def chat(url, messages):
    request = urllib.request.Request(url + "/chat/completions", data=json.dumps({
        "model": "fixture-coding", "messages": messages,
    }).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def test_script_rejects_wrong_prior_tool_call_and_keeps_servers_independent():
    with scripted_endpoint(["cat calc.py"]) as (first, captured), scripted_endpoint() as (second, _):
        messages = [{"role": "user", "content": "fix"}]
        assert chat(second, messages)["choices"][0]["message"]["content"] == "Done."
        answer = chat(first, messages)["choices"][0]["message"]
        tool_call = answer["tool_calls"][0]
        assert json.loads(tool_call["function"]["arguments"])["command"] == "cat calc.py"
        broken = [*messages, answer, {"role": "tool", "tool_call_id": "wrong", "content": "data"}]
        with pytest.raises(urllib.error.HTTPError) as error:
            chat(first, broken)
        assert error.value.code == 409
        correct = [*messages, answer, {"role": "tool", "tool_call_id": "call_0", "content": "data"}]
        assert chat(first, correct)["choices"][0]["finish_reason"] == "stop"
        assert len(captured) == 3


def test_relay_preserves_errors_and_cannot_select_another_upstream():
    with scripted_endpoint(error=True) as (upstream, requests):
        with relay(upstream.rsplit("/v1", 1)[0], "127.0.0.1") as port:
            url = f"http://127.0.0.1:{port}/v1"
            with pytest.raises(urllib.error.HTTPError) as error:
                chat(url, [{"role": "user", "content": "hello"}])
            assert error.value.code == 503
            assert requests[0]["model"] == "fixture-coding"
            with urllib.request.urlopen(url + "/models", timeout=5) as response:
                assert json.load(response)["data"][0]["id"] == "fixture-coding"
