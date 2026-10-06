"""Native local Pro V2 and locked mini-SWE generation/fresh-replay acceptance."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from magnet_evals.benchmarks.swe_bench_pro import (
    PRO_CHECKSUMS,
    PRO_REVISION,
    profile_request,
)
from magnet_evals.contracts import EvaluationRequest, ModelBinding
from magnet_evals.ensure import ensure_evaluation
from magnet_evals.outputs import load_run
from magnet_evals.store import ResultStore
from tests.native.harbor_fixture import TASKS
from tests.native.scripted_endpoint import scripted_endpoint

pytestmark = [pytest.mark.native, pytest.mark.docker_sandbox, pytest.mark.release_gate]
ROOT = Path(__file__).parents[2]
SMOKE = json.loads((ROOT / 'dev/environments/swebench-pro-smoke.json').read_text())
PRO_ROOT = Path(os.environ.get('SWE_PRO_DIR', '/tmp/aiq-harbor-roadmap/swe-pro'))


@pytest.fixture(autouse=True)
def native_tooling(monkeypatch):
    sys.path.insert(0, str(PRO_ROOT / 'v2/tooling'))
    monkeypatch.setenv('PYTHONPATH', str(PRO_ROOT / 'v2/tooling') + os.pathsep + os.environ.get('PYTHONPATH', ''))
    monkeypatch.setenv('HARBOR_TELEMETRY', '0')
    yield
    sys.path.remove(str(PRO_ROOT / 'v2/tooling'))


def preserve(tmp_path, label):
    if destination := os.environ.get('AIQ_PRO_CAPTURE_DIR'):
        shutil.copytree(tmp_path, Path(destination) / label / tmp_path.name)


@pytest.mark.parametrize('mode,reward', [('oracle', 1), ('nop', 0)])
def test_pro_gold_and_nop_are_scored_by_fresh_replay(tmp_path, mode, reward):
    task = SMOKE['task_id']
    request = EvaluationRequest(engine='harbor', task='path:' + str(PRO_ROOT / 'v2/tasks'),
        task_revision=PRO_REVISION, data_revision='sha256:' + PRO_CHECKSUMS,
        models=(ModelBinding(role='primary', model='fixture', revision='fixture-v1'),),
        task_options={'task_ids': [task], 'agent': 'python:tests.native.harbor_capture_agent:CaptureAgent',
                      'agent_kwargs': {'mode': mode}, 'agent_revision': 'acceptance-v1'},
        engine_options={'checksums': str(PRO_ROOT / 'v2/SHA256SUMS'),
            'registration_modules': ['locked_mini_swe', 'patch_replay'],
            'execution_protocol': 'python:magnet_evals.benchmarks.swe_bench_pro:ProV2Protocol',
            'protocol_options': {'image_ids': {task: SMOKE['image_id']}}})
    outcome = ensure_evaluation(request, ResultStore(tmp_path / 'store'), worker_python=sys.executable)
    assert outcome.run.complete, outcome.run.result.diagnostics
    sample, = outcome.run.result.samples
    assert sample.scores['reward'] == reward
    assert sample.native['authoritative_phase'] == 'fresh-replay'
    assert sample.native['generation_trial_id'] != sample.native['replay_trial_id']
    assert sample.native['verifier_observation']['complete']
    if reward:
        assert sample.native['patch_bytes'] > 0 and sample.native['replay']['apply_rc'] == 0
    else:
        assert sample.native['patch_bytes'] == 0
    assert not subprocess.check_output(['docker', 'ps', '-aq', '--filter',
        'label=com.docker.compose.project=' + (sample.native['trial_name'] + '__env').lower()]).strip()
    preserve(tmp_path, mode)


def test_locked_mini_swe_tools_capture_exact_patch_and_replay(tmp_path):
    from harbor.environments.docker.utils import (
        default_docker_platform,
        ensure_docker_image_built,
    )

    task = TASKS / 'division'

    async def build():
        return await ensure_docker_image_built(docker_name='division',
            docker_build_context=task / 'environment', dockerfile_path=task / 'environment/Dockerfile',
            build_args={}, platform=await default_docker_platform())

    image = asyncio.run(build())
    image_id = subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip()
    # extra_docker_compose selects Harbor's Compose build path, whose per-project
    # image labels differ from its shared native build cache. Freeze the actual
    # prebuilt fixture instead of pretending those image IDs are interchangeable.
    frozen_task = tmp_path / 'tasks/division'
    shutil.copytree(task, frozen_task)
    config = frozen_task / 'task.toml'
    config.write_text(config.read_text().replace('[environment]\n',
        '[environment]\ndocker_image = ' + json.dumps(image_id) + '\n'))
    commands = [
        'cd /app && cat calc.py',
        'cd /app && python -c ' + shlex.quote(
            "from pathlib import Path; Path('calc.py').write_text("
            "'def divide(numerator, denominator):\\n    if denominator == 0:\\n"
            "        raise ValueError(\"zero denominator\")\\n    return numerator / denominator\\n')"),
        'cd /app && python -m pytest -q test_calc.py',
        'echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT',
    ]
    request = EvaluationRequest(engine='harbor', task='path:' + str(frozen_task.parent), data_revision='fixture-v1',
        models=(ModelBinding(role='primary', model='fixture-coding', provider='openai', revision='fixture-v1'),),
        task_options={'task_ids': ['division'], 'agent': 'python:locked_mini_swe:LockedMiniSwe',
            'agent_revision': PRO_REVISION, 'agent_kwargs': {'version': SMOKE['mini_swe_agent_version'],
                'config_file': str(PRO_ROOT / 'v2/tooling/configs/mini_toolcall.yaml')}},
        engine_options={'execution_protocol': 'python:magnet_evals.benchmarks.swe_bench_pro:ProV2Protocol',
            'protocol_options': {'synthetic': True, 'image_ids': {'division': image_id}},
            'job_options': {'agent_setup_timeout_multiplier': 20},
            'required_secrets': ['OPENAI_API_KEY'], 'registration_modules': ['patch_replay', 'locked_mini_swe']})
    with scripted_endpoint(commands) as (endpoint, calls):
        outcome = ensure_evaluation(request, ResultStore(tmp_path / 'store'), worker_python=sys.executable,
            env={'OPENAI_API_KEY': 'fixture-key'}, model_endpoints={'primary': endpoint}, timeout_seconds=1200)
    assert outcome.run.complete, outcome.run.result.diagnostics
    sample, = outcome.run.result.samples
    assert len(calls) == 4 and sample.scores['reward'] == 1
    assert not outcome.resolved.identity.reusable  # Container dependency closure remains mutable.
    assert sample.native['generation_trial_id'] != sample.native['replay_trial_id']
    generated = outcome.run.path / sample.native['generation_native']['patch_artifact']
    assert generated.read_bytes() == (task / 'solution/model.patch').read_bytes()
    assert sample.native['replay']['apply_rc'] == 0
    preserve(tmp_path, 'locked-mini-synthetic')


def test_locked_mini_swe_runs_inside_actual_pro_image_and_replays_scripted_gold(tmp_path):
    task = SMOKE['task_id']
    gold = (PRO_ROOT / 'v2/tasks' / task / 'solution/gold_patch.diff').read_bytes()
    encoded = base64.b64encode(gold).decode()
    edit = 'cd /app && python3 -c ' + shlex.quote(
        "import base64; from pathlib import Path; Path('/tmp/fixture.patch').write_bytes(base64.b64decode('"
        + encoded + "'))") + ' && git apply /tmp/fixture.patch'
    commands = ['cd /app && cat lib/ansible/utils/vars.py', edit,
        'cd /app && python3 -m py_compile lib/ansible/utils/vars.py lib/ansible/vars/manager.py',
        'echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT']
    request = profile_request(PRO_ROOT, 'smoke',
        ModelBinding(role='primary', model='fixture-coding', provider='openai', revision='fixture-v1'),
        {task: SMOKE['image_id']})
    with scripted_endpoint(commands) as (endpoint, calls):
        outcome = ensure_evaluation(request, ResultStore(tmp_path / 'store'), worker_python=sys.executable,
            env={'OPENAI_API_KEY': 'fixture-key'}, model_endpoints={'primary': endpoint}, timeout_seconds=1800)
    assert outcome.run.complete, outcome.run.result.diagnostics
    sample, = outcome.run.result.samples
    assert len(calls) == 4 and sample.scores['reward'] == 1
    assert sample.native['replay']['apply_rc'] == 0 and sample.native['verifier_observation']['complete']
    generated = outcome.run.path / sample.native['generation_native']['patch_artifact']
    oracle = load_run(ROOT / 'tests/fixtures/swebench-pro-native/oracle')
    expected = oracle.path / oracle.result.samples[0].native['generation_native']['patch_artifact']
    assert generated.read_bytes() == expected.read_bytes()
    preserve(tmp_path, 'locked-mini-pro-scripted-gold')
