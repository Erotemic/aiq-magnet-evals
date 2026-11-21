"""Verified request partitioning uses ordinary runtime identity and native semantics."""
import json
from pathlib import Path

import pytest

from magnet_evals import ModelBinding
from magnet_evals.benchmarks.swe_bench_verified import (
    INSPECT_EVALS_REVISION,
    VERIFIED_REVISION,
    profile_request,
    profile_requests,
)
from magnet_evals.errors import RequestValidationError


def inputs():
    root = Path(__file__).resolve().parents[1] / 'dev/environments'
    selection = json.loads((root / 'swebench-verified-full-selection.json').read_text())
    pins = json.loads((root / 'swebench-verified-full-images.json').read_text())
    return selection['instance_ids'], pins, ModelBinding(role='primary', model='coding', provider='openai',
        revision='a' * 40, provider_options={'responses_api': False})


def test_full_selection_partitions_without_changing_native_protocol():
    ids, pins, model = inputs()
    requests = profile_requests(ids, pins, model, message_limit=200, agent_protocol='minimal-edit/v1')
    assert len(requests) == 500
    assert [r.task_options['instance_ids'][0] for r in requests] == ids
    for request in requests:
        assert request.engine == 'inspect_ai'
        assert request.task.endswith('inspect_verified_task:verified_task')
        assert request.task_revision == INSPECT_EVALS_REVISION
        assert request.data_revision == VERIFIED_REVISION
        instance, = request.task_options['instance_ids']
        assert request.task_options['images'] == {instance: pins[instance]}
        assert request.task_options['solver'] == 'agent'
        assert request.task_options['agent_protocol'] == 'minimal-edit/v1'
        assert request.engine_options['eval_options']['message_limit'] == 200
        assert request.models == (model,)
    changed = dict(pins)
    changed[ids[-1]] = changed[ids[-1]].split('@')[0] + '@sha256:' + 'f' * 64
    again = profile_requests(ids, changed, model)
    original = profile_requests(ids, pins, model)
    assert original[0].to_dict() == again[0].to_dict()
    assert original[-1].to_dict() != again[-1].to_dict()


def test_shard_size_and_explicit_settings_are_inputs():
    ids, pins, model = inputs()
    requests = profile_requests(ids[:5], pins, model, shard_size=2,
        generation={'max_tokens': 8192, 'reasoning_effort': 'high'})
    assert [len(r.task_options['instance_ids']) for r in requests] == [2, 2, 1]
    assert requests[0].generation['max_tokens'] == 8192
    assert requests[0].generation['reasoning_effort'] == 'high'
    assert requests[0].engine_options['eval_options']['message_limit'] == 30
    other = ModelBinding(role='primary', model='other', provider='openai', revision='b' * 40)
    assert profile_request(ids[:1], pins, other).models == (other,)


@pytest.mark.parametrize('bad', ['empty', 'duplicate', 'missing-pin', 'mutable-pin', 'bad-size'])
def test_invalid_selections_are_not_silently_changed(bad):
    ids, pins, model = inputs()
    ids = ids[:2]
    settings = {}
    if bad == 'empty':
        ids = []
    if bad == 'duplicate':
        ids = ids[:1] * 2
    if bad == 'missing-pin':
        pins.pop(ids[0])
    if bad == 'mutable-pin':
        pins[ids[0]] = 'image:latest'
    if bad == 'bad-size':
        settings['shard_size'] = 0
    with pytest.raises(RequestValidationError):
        profile_requests(ids, pins, model, **settings)
