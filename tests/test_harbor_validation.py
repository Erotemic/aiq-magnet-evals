"""Side-effect-free static validation of the new native job boundary."""
import builtins
from dataclasses import replace

import pytest

from magnet_evals.backends.harbor import HarborBackend
from magnet_evals.contracts import EvaluationRequest, ModelBinding
from magnet_evals.errors import RequestValidationError


def request(**kwargs):
    return EvaluationRequest(engine='harbor', task='path:/not-read-during-validation',
        models=(ModelBinding(role='primary', model='fixture', revision='immutable'),), **kwargs)


def test_validation_does_not_import_native_engine_or_read_task_source(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == 'harbor' or name.startswith('harbor.'):
            raise AssertionError('native import during static validation')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    HarborBackend().validate_request(request())


@pytest.mark.parametrize('options', [
    {'job_options': {'jobs_dir': '/elsewhere'}},
    {'job_options': {'tasks': []}},
    {'job_options': {'retry': {'max_retries': 2}}},
    {'job_options': {'install_only': True}},
    {'job_options': {'environment': {'delete': False}}},
    {'unknown': 1},
])
def test_protected_job_ownership_and_hidden_runs_are_rejected(options):
    with pytest.raises(RequestValidationError):
        HarborBackend().validate_request(request(engine_options=options))


@pytest.mark.parametrize('options', [
    {'task_ids': ['../escape']}, {'task_ids': ['division', 'division']},
    {'n_attempts': True}, {'n_concurrent': 0}, {'environment': 'modal'},
    {'agent_kwargs': {'logs_dir': '/elsewhere'}}, {'agent_kwargs': {'base_url': 'http://hidden'}},
    {'unexpected': True},
])
def test_unsupported_scientific_requests_are_explicit(options):
    with pytest.raises(RequestValidationError):
        HarborBackend().validate_request(request(task_options=options))


def test_auxiliary_models_do_not_silently_disappear():
    with pytest.raises(RequestValidationError):
        HarborBackend().validate_request(replace(request(), models=(
            ModelBinding(role='primary', model='fixture'), ModelBinding(role='grader', model='other'))))
