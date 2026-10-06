"""A stale serving descriptor must fail before real-model work starts."""
import copy

import pytest

from dev.swebench_gpu_acceptance import verify_descriptor


def test_gpu_descriptor_matches_scheduled_scientific_provenance():
    expected = {'immutable': True, 'digest': 'configured-Q4', 'facts': {'quantization': 'Q4'}}
    actual = {'lease_id': 'owned-lease', 'endpoints': {'coding': 'coding'},
              'base_url': 'http://leased-host/v1', 'serving_provenance': {'coding': expected}}
    verify_descriptor('coding', expected, actual)
    changed = copy.deepcopy(actual)
    changed['serving_provenance']['coding']['facts']['quantization'] = 'Q5'
    with pytest.raises(ValueError, match='reschedule'):
        verify_descriptor('coding', expected, changed)


@pytest.mark.parametrize('missing', ['lease_id', 'base_url', 'endpoints'])
def test_gpu_descriptor_requires_an_owned_lease_endpoint(missing):
    expected = {'immutable': True, 'digest': 'configured'}
    actual = {'lease_id': 'owned', 'endpoints': {'coding': 'coding'},
              'base_url': 'http://host/v1', 'serving_provenance': {'coding': expected}}
    actual.pop(missing)
    with pytest.raises(ValueError):
        verify_descriptor('coding', expected, actual)
