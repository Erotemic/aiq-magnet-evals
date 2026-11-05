"""Protocol isolation: preserve upstream defaults and keep hidden metadata private."""
import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from magnet_evals.benchmarks import inspect_verified_task as factory
from magnet_evals.contracts import EvaluationRequest, ModelBinding
from magnet_evals.errors import RequestValidationError
from magnet_evals.identity import build_measurement_identity


class Samples(list):
    def filter(self, predicate):
        return Samples(s for s in self if predicate(s))


@pytest.fixture
def native(monkeypatch):
    scorer, solver = object(), object()
    hidden = {'patch': 'PRIVATE_GOLD_CONTENT', 'test_patch': 'PRIVATE_TEST_CONTENT',
              'hints_text': 'PRIVATE_HINT_CONTENT'}

    def upstream(**kwargs):
        sample = SimpleNamespace(id='example__repo-1', input='Fix the stated issue.',
            metadata={**hidden, 'image_name': 'mutable-image', 'base_commit': 'a' * 40},
            setup='echo original-setup\n')
        sample.sandbox = kwargs['sandbox_config']('docker', sample)
        return SimpleNamespace(dataset=Samples([sample]), scorer=scorer, solver=solver)

    modules = {
        'inspect_ai.solver': SimpleNamespace(solver=lambda f: f),
        'inspect_ai.util': SimpleNamespace(
            ComposeConfig=SimpleNamespace(model_validate=lambda value: value),
            SandboxEnvironmentSpec=lambda **kwargs: SimpleNamespace(**kwargs)),
        'inspect_evals.swe_bench': SimpleNamespace(swe_bench=upstream),
    }
    real_import = factory.importlib.import_module
    monkeypatch.setattr(factory.importlib, 'import_module',
        lambda name: modules[name] if name in modules else real_import(name))
    return hidden, scorer, solver


def task(**kwargs):
    return factory._verified_task(instance_ids=['example__repo-1'],
        images={'example__repo-1': 'image@sha256:' + 'b' * 64}, **kwargs)


def test_opt_in_keeps_upstream_solver_scoring_and_setup(native):
    _, scorer, solver = native
    baseline = task()
    candidate = task(agent_protocol='minimal-edit/v1')
    assert baseline.solver is candidate.solver is solver
    assert baseline.scorer is candidate.scorer is scorer
    old, new = baseline.dataset[0], candidate.dataset[0]
    assert old.input == 'Fix the stated issue.'
    assert 'aiq_agent_protocol' not in old.metadata
    assert new.input.endswith(old.input)
    assert new.metadata['aiq_agent_protocol'] == 'minimal-edit/v1'
    assert old.setup == new.setup
    assert 'git reset --hard ' + 'a' * 40 in new.setup
    assert 'echo original-setup' in new.setup
    before = old.sandbox.config['services']['default']
    after = new.sandbox.config['services']['default']
    assert 'environment' not in before
    assert {k: v for k, v in after.items() if k != 'environment'} == before
    assert after['network_mode'] == 'none'
    assert after['environment']['DJANGO_TEST_PROCESSES'] == '1'


def test_guidance_is_independent_of_gold_tests_and_hints(native):
    hidden, _, _ = native
    first = task(agent_protocol='minimal-edit/v1').dataset[0].input
    hidden.update({k: 'CHANGED_' + v for k, v in hidden.items()})
    second = task(agent_protocol='minimal-edit/v1').dataset[0].input
    assert first == second
    assert 'PRIVATE_' not in first
    assert 'example__repo-1' not in first


@pytest.mark.parametrize('options', [
    {'agent_protocol': 'typo'},
    {'agent_protocol': 'minimal-edit/v1', 'solver': 'oracle'},
    {'agent_protocol': 'minimal-edit/v1', 'solver': 'nop'},
])
def test_unknown_or_inapplicable_protocol_fails_before_native_import(options):
    with pytest.raises(RequestValidationError):
        task(**options)


def test_protocol_changes_measurement_identity():
    baseline = EvaluationRequest(engine='inspect_ai', task='example',
        models=(ModelBinding(role='primary', model='served', revision='fixed'),),
        task_revision='fixed-task', data_revision='fixed-data')
    candidate = replace(baseline, task_options={'agent_protocol': 'minimal-edit/v1'})
    before = copy.deepcopy(baseline.to_dict())
    identities = [build_measurement_identity(r, adapter_version='test', engine_version='pinned',
                                             native_config={}, resolved_facts={})
                  for r in (baseline, candidate)]
    assert identities[0].digest != identities[1].digest
    assert baseline.to_dict() == before


@pytest.mark.parametrize('protocol', ['upstream', 'minimal-edit/v1'])
def test_clean_sphinx_keeps_per_test_reporting_out_of_model_patch(native, protocol):
    hidden, scorer, solver = native
    hidden['repo'] = 'sphinx-doc/sphinx'
    configured = task(agent_protocol=protocol)
    environment = configured.dataset[0].sandbox.config['services']['default']['environment']
    assert environment['PYTEST_ADDOPTS'] == '-rA'
    assert environment['TOX_OVERRIDE'] == 'testenv.pass_env+=PYTEST_ADDOPTS'
    assert configured.scorer is scorer and configured.solver is solver
    assert 'tox.ini' not in configured.dataset[0].setup
    if protocol == 'minimal-edit/v1':
        assert environment['DJANGO_TEST_PROCESSES'] == '1'
    untouched = task(agent_protocol=protocol, clean_repository=False)
    environment = untouched.dataset[0].sandbox.config['services']['default'].get('environment', {})
    assert 'PYTEST_ADDOPTS' not in environment and 'TOX_OVERRIDE' not in environment


def test_setup_excludes_untracked_python_cache_from_captured_patch(native, tmp_path):
    import subprocess

    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'config', 'user.email', 'test@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'config', 'user.name', 'Test'], check=True)
    (tmp_path / 'source.py').write_text('old\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'source.py'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'commit', '-qm', 'base'], check=True)
    commit = subprocess.check_output(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD'], text=True).strip()
    setup = task().dataset[0].setup.replace('/testbed', str(tmp_path)).replace('a' * 40, commit)
    subprocess.run(['bash', '-c', setup], check=True, stdout=subprocess.DEVNULL)
    cache = tmp_path / 'pkg/__pycache__'
    cache.mkdir(parents=True)
    (cache / 'mod.cpython-311.pyc.123').write_bytes(b'\0binary')
    (tmp_path / 'source.py').write_text('new\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '-A'], check=True)
    patch = subprocess.check_output(['git', '-C', str(tmp_path), 'diff', '--cached', commit], text=True)
    assert '__pycache__' not in patch
    assert '-old\n+new\n' in patch


def test_owner_marker_uses_supported_compose_environment_without_prompt_changes(native):
    configured = task(sandbox_owner='owned-campaign')
    sample = configured.dataset[0]
    service = sample.sandbox.config['services']['default']
    assert service['environment']['AIQ_EVAL_OWNER'] == 'owned-campaign'
    assert service['environment']['AIQ_EVAL_INSTANCE'] == sample.id
    assert 'labels' not in service
    assert sample.input == 'Fix the stated issue.'


@pytest.mark.parametrize('owner', ['', {}, 7])
def test_invalid_owner_is_rejected_before_native_import(owner):
    with pytest.raises(RequestValidationError, match='sandbox_owner'):
        task(sandbox_owner=owner)
