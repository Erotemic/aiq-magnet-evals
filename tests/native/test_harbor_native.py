"""Generic Harbor worker acceptance at its evidenced candidate pin."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from magnet_evals.backends.harbor import HarborBackend
from magnet_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from magnet_evals.ensure import ensure_evaluation
from magnet_evals.errors import ArtifactError, RequestValidationError
from magnet_evals.outputs import load_run
from magnet_evals.runner import run_evaluation_async
from magnet_evals.store import ResultStore
from tests.native.harbor_fixture import TASKS
from tests.native.harbor_relay import relay
from tests.native.scripted_endpoint import scripted_endpoint

pytestmark = [pytest.mark.native, pytest.mark.docker_sandbox, pytest.mark.release_gate]


@pytest.fixture(autouse=True)
def no_telemetry(monkeypatch):
    monkeypatch.setenv('HARBOR_TELEMETRY', '0')


def request(task=TASKS, **options):
    return EvaluationRequest(engine='harbor', task='path:' + str(task.resolve()),
        models=(ModelBinding(role='primary', model='fixture-coding', provider='openai', revision='fixture-v1'),),
        data_revision='fixture-v1', **options)


def test_content_identity_ignores_task_location_and_endpoint_but_not_task_bytes(tmp_path):
    one, two = tmp_path / 'one/tasks', tmp_path / 'two/tasks'
    shutil.copytree(TASKS, one)
    shutil.copytree(TASKS, two)
    first = HarborBackend().resolve(request(one))
    changed_endpoint = replace(request(two), models=(replace(request().primary_model,
        provider_options={'base_url': 'http://localhost:54321/v1'}),))
    second = HarborBackend().resolve(changed_endpoint)
    assert first.identity == second.identity
    path = two / 'division/instruction.md'
    path.write_text(path.read_text() + '\nDifferent issue text.\n')
    assert HarborBackend().resolve(request(two)).identity.digest != first.identity.digest


def test_config_file_bytes_and_network_policy_change_identity(tmp_path):
    source = tmp_path / 'tasks'
    shutil.copytree(TASKS, source)
    first_config, second_config = tmp_path / 'config-a.json', tmp_path / 'config-b.json'
    first_config.write_text('{"solve":true}')
    second_config.write_text(first_config.read_text())

    def req(config):
        return request(source, task_options={
            'agent': 'python:tests.native.harbor_config_agent:ConfigAgent',
            'agent_kwargs': {'config_file': str(config)}})

    first = HarborBackend().resolve(req(first_config))
    assert first.identity == HarborBackend().resolve(req(second_config)).identity
    second_config.write_text('{"solve":false}')
    assert first.identity != HarborBackend().resolve(req(second_config)).identity
    assert first.native_config['agents'][0]['kwargs']['config_file'] == str(first_config)
    task = source / 'division/task.toml'
    task.write_text(task.read_text().replace('network_mode = "no-network"', 'network_mode = "public"'))
    assert HarborBackend().resolve(req(first_config)).identity != first.identity


def test_unknown_agent_options_are_refused():
    with pytest.raises(RequestValidationError, match='unknown Harbor agent options'):
        HarborBackend().resolve(request(task_options={'agent_kwargs': {'config_file': __file__}}))


@pytest.mark.external
def test_file_configuration_is_consumed_from_attempt_snapshot(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{"solve":true}')
    outcome = ensure_evaluation(request(task_options={
        'agent': 'python:tests.native.harbor_config_agent:ConfigAgent',
        'agent_kwargs': {'config_file': str(config)}}), ResultStore(tmp_path / 'store'),
        worker_python=sys.executable)
    assert outcome.run.complete
    assert outcome.run.result.samples[0].scores['reward'] == 1
    consumed = next(outcome.run.path.glob('native/harbor/evaluation/*/agent/consumed-config.json'))
    assert json.loads(consumed.read_text()) == {'solve': True}
    native_config = json.loads(next(outcome.run.path.glob('native/harbor/evaluation/*/config.json')).read_text())
    assert native_config['agent']['kwargs']['config_file'] != str(config)


def test_checksum_mismatch_and_incomplete_manifest_are_refused(tmp_path):
    source = tmp_path / 'tasks'
    shutil.copytree(TASKS, source)
    checksums = tmp_path / 'SHA256SUMS'
    checksums.write_text('0' * 64 + '  tasks/division/instruction.md\n')
    with pytest.raises(RequestValidationError, match='checksum mismatch'):
        HarborBackend().resolve(request(source, engine_options={'checksums': str(checksums)}))
    checksums.write_text('')
    with pytest.raises(RequestValidationError, match='does not cover'):
        HarborBackend().resolve(request(source, engine_options={'checksums': str(checksums)}))


def test_changed_task_after_resolution_is_not_executed(tmp_path):
    source = tmp_path / 'tasks'
    shutil.copytree(TASKS, source)
    resolved = HarborBackend().resolve(request(source))
    (source / 'division/instruction.md').write_text('unexpected input drift\n')
    with pytest.raises(RequestValidationError, match='changed after resolution'):
        asyncio.run(HarborBackend().execute(resolved, ExecutionContext(output_dir=tmp_path / 'attempt')))
    assert not list((tmp_path / 'attempt').rglob('result.json'))


def test_import_rejects_another_model(tmp_path):
    source = tmp_path / 'native'
    shutil.copytree(Path(__file__).parents[1] / 'fixtures/harbor-native/scripted', source)
    resolved = HarborBackend().resolve(replace(request(), models=(replace(request().primary_model, model='different'),)))
    with pytest.raises(ArtifactError, match='model'):
        HarborBackend().import_results(resolved, str(source), ExecutionContext(output_dir=tmp_path / 'import'))


def test_harbor_hard_kill_cleans_only_owned_docker_resources(tmp_path, monkeypatch):
    import magnet_evals.runner as runner

    terminate = runner._terminate_process_tree
    terminated = []

    async def fast_escalation(process):
        await terminate(process, grace_seconds=0.1)
        terminated.append({'pid': process.pid, 'returncode': process.returncode})

    monkeypatch.setattr(runner, '_terminate_process_tree', fast_escalation)
    monkeypatch.setattr(runner, '_TERM_GRACE_SECONDS', 0.1)
    destination = tmp_path / 'run'

    async def probe():
        task = asyncio.create_task(run_evaluation_async(request(task_options={
            'agent': 'python:tests.native.harbor_sleep_agent:StubbornSleepAgent'}),
            ExecutionContext(output_dir=destination, worker_python=sys.executable)))
        witness = None
        try:
            async with asyncio.timeout(180):
                while not list(tmp_path.glob('.aiq-evals-work-*/native/harbor/evaluation/*/agent/started')):
                    if task.done():
                        await task
                        pytest.fail('worker exited before the cancellation probe')
                    await asyncio.sleep(0.2)
            work, = tmp_path.glob('.aiq-evals-work-*')
            record, = (work / 'native/harbor/owned-projects').glob('*.json')
            project = json.loads(record.read_text())['project']
            container = subprocess.check_output(['docker', 'ps', '-q', '--filter',
                'label=com.docker.compose.project=' + project, '--filter',
                'label=com.docker.compose.service=main'], text=True).strip()
            image = subprocess.check_output(['docker', 'inspect', container, '--format', '{{.Image}}'], text=True).strip()
            # Harbor's built image inherits Compose labels. Give this genuinely
            # unrelated container its own project instead of inheriting ours.
            witness = subprocess.check_output(['docker', 'run', '-d', '--label',
                'com.docker.compose.project=unrelated-' + os.urandom(6).hex(),
                image, 'sleep', '120'], text=True).strip()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert subprocess.check_output(['docker', 'inspect', witness, '--format', '{{.State.Running}}'], text=True).strip() == 'true'
            assert not subprocess.check_output(['docker', 'ps', '-aq', '--filter',
                'label=com.docker.compose.project=' + project]).strip()
            assert not subprocess.check_output(['docker', 'network', 'ls', '-q', '--filter',
                'label=com.docker.compose.project=' + project]).strip()
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if witness:
                subprocess.run(['docker', 'rm', '-f', witness], check=True, capture_output=True)

    asyncio.run(probe())
    assert terminated and terminated[-1]['returncode'] == -signal.SIGKILL
    run = load_run(destination)
    assert run.result.status == 'cancelled' and not run.complete
    assert not (destination / 'RUN_COMPLETE').exists()
    cleanup = json.loads((destination / 'native/aiq_worker/harbor-cleanup.json').read_text())
    assert cleanup['removed_containers'] and not cleanup['errors']
    observation = tmp_path / 'hardkill-observation.json'
    observation.write_text(json.dumps({
        'worker': terminated[-1], 'unrelated_container_preserved': True,
        'owned_containers_absent': True, 'owned_networks_absent': True}, indent=2) + '\n')
    assert not list(destination.glob('native/harbor/evaluation/*/verifier/reward.txt'))
    if capture := os.environ.get('AIQ_HARBOR_HARDKILL_CAPTURE_DIR'):
        shutil.copytree(destination, Path(capture) / 'run')
        shutil.copy2(observation, Path(capture) / observation.name)


@pytest.mark.external
def test_worker_uses_shared_bridge_and_scripted_tools(tmp_path):
    commands = [
        'cd /app && cat calc.py',
        'cd /app && python -c ' + shlex.quote(
            "from pathlib import Path; Path('calc.py').write_text("
            "'def divide(numerator, denominator):\\n    if denominator == 0:\\n"
            "        raise ValueError(\"zero denominator\")\\n    return numerator / denominator\\n')"),
        'cd /app && python -m pytest -q test_calc.py',
    ]
    gateway = json.loads(subprocess.check_output([
        'docker', 'network', 'inspect', 'bridge', '--format', '{{json .IPAM.Config}}']))[0]['Gateway']
    with scripted_endpoint(commands) as (upstream, calls), scripted_endpoint() as (unlisted, _):
        with relay(unlisted.rsplit('/v1', 1)[0], gateway) as unlisted_port:
            req = request(task_options={
                'agent': 'python:tests.native.harbor_probe_agent:ProbeAgent',
                'agent_kwargs': {'targets': {
                    'allowed': 'http://placeholder.invalid/v1/models',
                    'unlisted': f'http://{gateway}:{unlisted_port}/v1/models',
                    'internet': 'https://example.com/',
                }},
            })
            outcome = ensure_evaluation(req, ResultStore(tmp_path / 'store'), worker_python=sys.executable,
                                        model_endpoints={'primary': upstream})
    assert outcome.run.complete, outcome.run.result.diagnostics
    sample = outcome.run.result.samples[0]
    assert sample.scores['reward'] == 1 and len(calls) == 4
    assert [step['command'] for step in sample.trajectory] == commands
    agent = json.loads(next(outcome.run.path.glob('native/harbor/evaluation/*/agent/network-agent.json')).read_text())
    assert agent['allowed']['reachable']
    assert not agent['unlisted']['reachable'] and not agent['internet']['reachable']
    assert (outcome.run.path / sample.native['patch_artifact']).read_bytes() == (
        TASKS / 'division/solution/model.patch').read_bytes()
