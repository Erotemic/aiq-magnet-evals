"""Native Phase 0 gates; require the candidate worker and a Docker daemon."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.native.harbor_fixture import TASKS, run_job, trial_results
from tests.native.harbor_relay import relay
from tests.native.scripted_endpoint import scripted_endpoint

pytestmark = [pytest.mark.native, pytest.mark.docker_sandbox, pytest.mark.release_gate]
ARTIFACTS = Path(os.environ.get("AIQ_HARBOR_PROBE_DIR", "/tmp/aiq-harbor-phase0"))


@pytest.fixture(autouse=True)
def harbor_pin(monkeypatch):
    import importlib.metadata

    if importlib.metadata.version("harbor") != "0.23.0":
        pytest.fail("Phase 0 requires candidate harbor==0.23.0")
    monkeypatch.setenv("HARBOR_TELEMETRY", "0")


def read_trial(job_dir):
    results = trial_results(job_dir)
    assert len(results) == 1
    result = results[0]
    return result, job_dir / result["trial_name"]


def run_probe(name, **options):
    destination = ARTIFACTS / name
    # Never resume an old job and call it a fresh acceptance result.
    destination.mkdir(parents=True, exist_ok=True)
    return asyncio.run(run_job(destination, os.urandom(6).hex(), **options))


def test_oracle_nop_and_native_artifacts():
    for agent, reward in (("oracle", 1), ("nop", 0)):
        job_dir = run_probe(agent, agent=agent)
        result, trial = read_trial(job_dir)
        assert result["exception_info"] is None
        assert result["verifier_result"]["rewards"]["reward"] == reward
        assert (job_dir / "config.json").is_file()
        assert (trial / "verifier/reward.txt").is_file()
        assert (trial / "verifier/pytest.txt").is_file()
        if agent == "oracle":
            assert (trial / "agent/model.patch").read_bytes() == (
                TASKS / "division/solution/model.patch").read_bytes()


@contextlib.contextmanager
def endpoint_bridge(directory, upstream):
    """Use Harbor's extra-compose hook to expose only a fixed-upstream relay.

    The second host hop is bound to docker0, never the LAN. Only the relay
    service can access it in the allowlisted phase; it forwards to loopback.
    Both hops are owned by this attempt and removed on exit.
    """
    gateway = json.loads(subprocess.check_output([
        "docker", "network", "inspect", "bridge", "--format", "{{json .IPAM.Config}}",
    ]))[0]["Gateway"]
    # The relay is engine-free; the container imports it without invoking a CLI.
    module = Path(__file__).with_name("harbor_relay.py").resolve()
    with relay(upstream.rsplit("/v1", 1)[0], gateway) as port:
        startup = (
            "from harbor_relay import relay; import threading; "
            f"bridge=relay('http://{gateway}:{port}', '0.0.0.0', 8080); "
            "bridge.__enter__(); threading.Event().wait()"
        )
        compose = directory / "bridge.json"
        compose.write_text(json.dumps({"services": {"model-relay": {
            "image": "python:3.12-alpine@sha256:4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111",
            "working_dir": "/fixture",
            "command": ["python", "-c", startup],
            "networks": ["default"],
            "volumes": [{"type": "bind", "source": str(module),
                         "target": "/fixture/harbor_relay.py", "read_only": True}],
            "healthcheck": {"test": ["CMD", "python", "-c",
                "import socket; socket.create_connection(('127.0.0.1',8080),2).close()"],
                "interval": "1s", "timeout": "3s", "retries": 15},
        }}}))
        yield compose, gateway


@pytest.mark.external
def test_allowlist_bridge_tool_execution_and_phase_policy(tmp_path):
    commands = [
        "cd /app && cat calc.py",
        "cd /app && python -c " + shlex.quote(
            "from pathlib import Path; Path('calc.py').write_text("
            "'def divide(numerator, denominator):\\n    if denominator == 0:\\n"
            "        raise ValueError(\"zero denominator\")\\n    return numerator / denominator\\n')"),
        "cd /app && python -m pytest -q test_calc.py",
    ]
    with scripted_endpoint(commands) as (upstream, requests), scripted_endpoint() as (unlisted, _):
        with endpoint_bridge(tmp_path, upstream) as (compose, gateway):
            with relay(unlisted.rsplit("/v1", 1)[0], gateway) as unlisted_port:
                targets = {
                    "allowed": "http://model-relay:8080/v1/models",
                    "unlisted": f"http://{gateway}:{unlisted_port}/v1/models",
                    "internet": "https://example.com/",
                }
                job_dir = run_probe("scripted", agent={
                    "import_path": "tests.native.harbor_probe_agent:ProbeAgent",
                    "model_name": "openai/fixture-coding",
                    "extra_allowed_hosts": ["model-relay"],
                    "kwargs": {"targets": targets},
                }, environment={"type": "docker", "extra_docker_compose": [str(compose)]})
                result, trial = read_trial(job_dir)
                assert result["exception_info"] is None, result["exception_info"]
                assert result["verifier_result"]["rewards"]["reward"] == 1
                setup = json.loads((trial / "agent/network-setup.json").read_text())
                agent = json.loads((trial / "agent/network-agent.json").read_text())
                verifier = json.loads((trial / "verifier/network.json").read_text())
                assert all(item["reachable"] for item in setup.values()), setup
                assert agent["allowed"]["reachable"], agent
                assert not agent["unlisted"]["reachable"], agent
                assert not agent["internet"]["reachable"], agent
                assert all(item["reachable"] for item in verifier.values()), verifier
                trajectory = json.loads((trial / "agent/trajectory.json").read_text())
                assert [step["command"] for step in trajectory] == commands
                assert all(step["return_code"] == 0 for step in trajectory)
                assert len(requests) == 4
                assert result["agent_result"]["n_input_tokens"] == 20
                assert (trial / "agent/model.patch").read_bytes() == (
                    TASKS / "division/solution/model.patch").read_bytes()


@pytest.mark.external
def test_no_network_denies_all_and_verifier_restores_public(tmp_path):
    with scripted_endpoint() as (upstream, _):
        with endpoint_bridge(tmp_path, upstream) as (compose, gateway):
            targets = {"allowed": "http://model-relay:8080/v1/models",
                       "unlisted": f"http://{gateway}:1/", "internet": "https://example.com/"}
            job_dir = run_probe("no-network", agent={
                "import_path": "tests.native.harbor_probe_agent:ProbeAgent",
                "kwargs": {"targets": targets, "chat": False},
            }, environment={"type": "docker", "extra_docker_compose": [str(compose)]})
            result, trial = read_trial(job_dir)
            assert result["exception_info"] is None
            agent = json.loads((trial / "agent/network-agent.json").read_text())
            verifier = json.loads((trial / "verifier/network.json").read_text())
            assert not any(item["reachable"] for item in agent.values()), agent
            assert verifier["allowed"]["reachable"] and verifier["internet"]["reachable"], verifier


def test_partial_verifier_failure_is_not_zero_reward(tmp_path):
    broken = tmp_path / "broken-verifier"
    shutil.copytree(TASKS / "division", broken)
    (broken / "tests/test.sh").write_text("#!/bin/bash\nexit 1\n")
    job_dir = run_probe("partial-failure", tasks=[TASKS / "division", broken])
    results = {result["task_name"]: result for result in trial_results(job_dir)}
    assert len(results) == 2
    assert results["division"]["verifier_result"]["rewards"]["reward"] == 1
    assert results["broken-verifier"]["exception_info"]["exception_type"] == "RewardFileNotFoundError"
    assert results["broken-verifier"]["verifier_result"] is None
    job = json.loads((job_dir / "result.json").read_text())
    assert job["stats"]["n_completed_trials"] == 2
    assert job["stats"]["n_errored_trials"] == 1


def test_sigint_worker_group_cleans_sandbox_and_keeps_diagnostics():
    from magnet_evals.runner import _terminate_process_tree

    async def probe():
        destination = ARTIFACTS / "cancellation" / os.urandom(6).hex()
        destination.mkdir(parents=True)
        with (destination / "worker.txt").open("w") as output:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "tests.native.harbor_fixture",
                f"--jobs_dir={destination}", "--name=cancelled",
                "--agent=python:tests.native.harbor_sleep_agent:SleepAgent",
                stdout=output, stderr=output, start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 180
                while not list(destination.glob("cancelled/*/agent/started")):
                    assert process.returncode is None, (destination / "worker.txt").read_text()
                    assert time.monotonic() < deadline, "sandbox did not start"
                    await asyncio.sleep(0.2)
            finally:
                await _terminate_process_tree(process, grace_seconds=30)
        job_dir = destination / "cancelled"
        result, trial = read_trial(job_dir)
        assert result["exception_info"]["exception_type"] == "CancelledError"
        assert (trial / "agent/started").is_file()
        assert not (job_dir / "RUN_COMPLETE").exists()
        assert not (trial / "verifier/reward.txt").exists()
        containers = subprocess.check_output([
            "docker", "ps", "-aq", "--filter",
            "label=com.docker.compose.project=" + result["trial_name"].lower() + "__env",
        ], text=True)
        assert not containers.strip(), "Harbor-owned sandbox survived cancellation"
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        else:
            pytest.fail("worker process group survived cancellation")

    asyncio.run(probe())


def test_exact_patch_replay_in_fresh_sandbox(tmp_path, monkeypatch):
    upstream = Path(os.environ.get("SWE_PRO_REPO", "/tmp/aiq-harbor-roadmap/swe-pro"))
    assert (upstream / "v2/tooling/patch_replay.py").is_file(), "run dev/ci/harbor_phase0.sh first"
    # The unchanged upstream replay agent searches only instance_* trials.
    task = tmp_path / "instance_division"
    shutil.copytree(TASKS / "division", task)
    generation = run_probe("replay-generation", tasks=[task])
    source, source_trial = read_trial(generation)
    expected = (TASKS / "division/solution/model.patch").read_bytes()
    assert (source_trial / "agent/model.patch").read_bytes() == expected
    monkeypatch.syspath_prepend(str(upstream / "v2/tooling"))
    replay_job = run_probe("fresh-replay", tasks=[task], agent={
        "import_path": "patch_replay:PatchReplayAgent", "model_name": "replay",
        "kwargs": {"source_job": str(generation)},
    })
    result, trial = read_trial(replay_job)
    assert result["exception_info"] is None, result["exception_info"]
    assert result["verifier_result"]["rewards"]["reward"] == 1
    replay = json.loads((trial / "agent/replay.json").read_text())
    assert replay["apply_rc"] == 0
    assert Path(replay["patch"]).read_bytes() == expected
    assert result["id"] != source["id"]
    assert result["config"]["agent"]["import_path"] == "patch_replay:PatchReplayAgent"
