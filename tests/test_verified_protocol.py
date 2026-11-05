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
