from dataclasses import replace

import pytest

from magnet_evals.contracts import EvaluationRequest, ModelBinding
from magnet_evals.errors import RequestValidationError
from magnet_evals.identity import build_measurement_identity


def make_request(**kwargs):
    data = {
        'engine': 'olmo_eval',
        'task': 'tiny',
        'task_revision': 'task-sha',
        'data_revision': 'data-sha',
        'models': (
            ModelBinding(
                role='primary',
                model='model-a',
                provider='mock',
                revision='model-sha',
            ),
        ),
        'generation': {'temperature': 0.0},
    }
    data.update(kwargs)
    return EvaluationRequest(**data)


def test_request_roundtrip_and_strict_fields():
    request = make_request()
    assert EvaluationRequest.from_dict(request.to_dict()) == request
    with pytest.raises(RequestValidationError, match='unknown evaluation request fields'):
        EvaluationRequest.from_dict({**request.to_dict(), 'wat': 1})


def test_request_rejects_secrets_and_non_json_values(tmp_path):
    with pytest.raises(RequestValidationError, match='credential-bearing'):
        make_request(engine_options={'api_key': 'nope'})
    with pytest.raises(RequestValidationError, match='Path'):
        make_request(task_options={'path': tmp_path})


def test_measurement_identity_is_stable_and_context_free():
    request = make_request()
    kwargs = {
        'adapter_version': '0.1',
        'engine_version': '1.2.3',
        'native_config': {'task_specs': ['tiny']},
        'resolved_facts': {'engine_version': '1.2.3', 'engine_revision': 'engine-sha'},
    }
    one = build_measurement_identity(request, **kwargs)
    two = build_measurement_identity(EvaluationRequest.from_dict(request.to_dict()), **kwargs)
    assert one == two
    assert one.reusable

    changed = build_measurement_identity(
        replace(request, generation={'temperature': 0.5}),
        **kwargs,
    )
    assert changed.digest != one.digest


def test_unknown_identity_disables_reuse():
    request = make_request(task_revision=None, data_revision=None)
    identity = build_measurement_identity(
        request,
        adapter_version='0.1',
        engine_version=None,
        native_config={},
        resolved_facts={},
    )
    assert not identity.reusable
    assert any('task revision' in reason for reason in identity.unknown_reasons)
    assert any('data revision' in reason for reason in identity.unknown_reasons)


def test_model_uncertainty_disables_reuse_even_with_revision_and_token():
    model = replace(make_request().primary_model, cache_token='scientific-config-digest',
                    identity_unknown_reasons=('serving image is mutable',))
    request = make_request(models=(model,))
    assert EvaluationRequest.from_dict(request.to_dict()) == request
    identity = build_measurement_identity(request, adapter_version='0.1', engine_version='1',
                                          native_config={}, resolved_facts={'engine_version': '1'})
    assert not identity.reusable
    assert identity.unknown_reasons == ("model role 'primary': serving image is mutable",)
    assert 'identity_unknown_reasons' not in make_request().primary_model.to_dict()
    with pytest.raises(RequestValidationError, match='identity_unknown_reasons'):
        replace(model, identity_unknown_reasons='not a sequence of reasons')


def test_request_allows_required_secret_names_but_not_values():
    request = make_request(
        engine_options={
            'harness_config': {
                'required_secrets': ['SERPER_API_KEY'],
                'provider': {'required_secrets': ['OPENAI_API_KEY']},
            }
        }
    )
    assert request.engine_options['harness_config']['required_secrets'] == ['SERPER_API_KEY']
    with pytest.raises(RequestValidationError, match='credential-bearing'):
        make_request(engine_options={'harness_config': {'api_key': 'secret-value'}})


def test_identity_facts_change_digest_but_informational_facts_do_not():
    request = make_request()
    base = {
        'adapter_version': '0.1',
        'engine_version': '1.2.3',
        'native_config': {'task_specs': ['tiny']},
        'resolved_facts': {'engine_version': '1.2.3', 'engine_revision': 'engine-sha'},
        'identity_facts': {'task_source_sha256': 'a' * 64, 'adapter_source_sha256': 'b' * 64},
    }
    one = build_measurement_identity(request, **base)
    edited_task = build_measurement_identity(
        request, **{**base, 'identity_facts': {**base['identity_facts'], 'task_source_sha256': 'c' * 64}}
    )
    edited_adapter = build_measurement_identity(
        request, **{**base, 'identity_facts': {**base['identity_facts'], 'adapter_source_sha256': 'd' * 64}}
    )
    moved_checkout = build_measurement_identity(
        request,
        **{**base, 'resolved_facts': {**base['resolved_facts'], 'task_source_path': '/elsewhere/task.py'}},
    )
    assert one.reusable and edited_task.reusable
    assert edited_task.digest != one.digest
    assert edited_adapter.digest != one.digest
    assert moved_checkout.digest == one.digest


def test_task_source_digest_only_counts_when_it_is_an_identity_fact():
    request = make_request(task_revision=None)
    kwargs = {
        'adapter_version': '0.1',
        'engine_version': '1.2.3',
        'native_config': {},
        'resolved_facts': {'engine_version': '1.2.3', 'task_source_sha256': 'a' * 64},
    }
    assert not build_measurement_identity(request, **kwargs).reusable
    assert build_measurement_identity(
        request, **kwargs, identity_facts={'task_source_sha256': 'a' * 64}
    ).reusable


def test_adapter_source_digest_tracks_package_source(tmp_path, monkeypatch):
    from magnet_evals.identity import adapter_source_digest

    package = tmp_path / 'fake_adapter_pkg'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'normalize.py').write_text('X = 1\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    before = adapter_source_digest('fake_adapter_pkg')
    (package / 'normalize.py').write_text('X = 2\n')
    assert adapter_source_digest('fake_adapter_pkg') != before


def test_metric_record_int_value_round_trips(tmp_path):
    from magnet_evals.artifacts import RunBundle, publish_run
    from magnet_evals.contracts import (
        EvaluationResult,
        ExecutionContext,
        MeasurementIdentity,
        MetricRecord,
        ResolvedEvaluation,
        ResultRecord,
    )

    metric = MetricRecord(task='t', model_role='primary', metric='acc', value=1)
    assert isinstance(metric.value, float)
    assert MetricRecord.from_dict(metric.to_dict()) == metric
    identity = MeasurementIdentity(algorithm='t', digest='0' * 64, reusable=False)
    request = make_request()
    resolved = ResolvedEvaluation(
        request=request, adapter_version='a', engine_version=None, native_config={}, identity=identity
    )
    result = EvaluationResult(
        engine='olmo_eval', identity=identity, status='succeeded',
        records=(ResultRecord(task='t', model_role='primary', metrics=(metric,)),),
    )
    publish_run(tmp_path / 'r', resolved=resolved, result=result, context=ExecutionContext(output_dir=tmp_path / 'r'))
    RunBundle.load(tmp_path / 'r')


def test_operational_request_fields_do_not_change_the_measurement():
    # Secret names and endpoint URLs say how a measurement is reached, not what
    # it is (identity v3). Everything else in provider_options still counts.
    def digest(**kwargs):
        return build_measurement_identity(
            make_request(**kwargs), adapter_version='a', engine_version='1',
            native_config={}, resolved_facts={},
        ).digest

    def binding(**options):
        return (ModelBinding(role='primary', model='model-a', provider='mock', revision='model-sha',
                             provider_options=options),)

    base = digest(engine_options={'required_secrets': ['KEY_A']}, models=binding(base_url='http://a/v1'))
    assert digest(engine_options={'required_secrets': ['KEY_B']}, models=binding(base_url='http://a/v1')) == base
    assert digest(engine_options={}, models=binding(base_url='http://b/v1')) == base
    assert digest(engine_options={}, models=binding()) == base
    assert digest(engine_options={}, models=binding(temperature_scale=2)) != base
    identity = build_measurement_identity(make_request(), adapter_version='a', engine_version='1',
                                          native_config={}, resolved_facts={})
    assert identity.algorithm == 'aiq-evals-measurement-v3+sha256'


def test_nested_secret_names_do_not_change_the_measurement():
    # required_secrets is recognized at any depth (e.g. inside a harness config).
    def digest(names):
        request = make_request(engine_options={'harness_config': {'provider': {'required_secrets': names}}})
        return build_measurement_identity(request, adapter_version='a', engine_version='1',
                                          native_config={}, resolved_facts={}).digest

    assert digest(['KEY_A']) == digest(['KEY_B'])
