"""Regression against captured native Harbor truth, without importing Harbor."""
import builtins
import json
import shutil
from pathlib import Path

import pytest

from magnet_evals.backends.harbor.normalize import normalize_harbor_job
from magnet_evals.contracts import MeasurementIdentity
from magnet_evals.errors import ArtifactError
from magnet_evals.jsonutil import sha256_file

FIXTURES = Path(__file__).parent / 'fixtures/harbor-native'
IDENTITY = MeasurementIdentity(algorithm='test', digest='a' * 64, reusable=False)


def normalize(label, root=FIXTURES):
    return normalize_harbor_job(root / label, identity=IDENTITY, fallback_task='synthetic/division')


def test_native_capture_integrity():
    capture = json.loads((FIXTURES / 'capture.json').read_text())
    for relative, digest in capture['sha256'].items():
        assert sha256_file(FIXTURES / relative) == digest


def test_engine_free_oracle_nop_and_scripted_roundtrip(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == 'harbor' or name.startswith('harbor.'):
            raise AssertionError('native engine imported by normalizer')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    for label, reward in (('oracle', 1), ('nop', 0), ('scripted', 1), ('fresh-replay', 1)):
        result = normalize(label)
        assert result.status == 'succeeded'
        assert result.records[0].coverage.to_dict() == {'status': 'complete', 'expected': 1,
            'processed': 1, 'saved': 1, 'failed': 0}
        assert result.samples[0].scores['reward'] == reward
        assert result.records[0].metrics[0].value == reward
        assert result.records[0].metrics[0].denominator == 1
        assert result.samples[0].native['counted_as_model_failure'] == (reward == 0)
        assert type(result).from_dict(result.to_dict()) == result
    scripted = normalize('scripted').samples[0]
    assert len(scripted.trajectory) == 3
    assert scripted.usage['n_input_tokens'] == 20
    assert scripted.native['patch_sha256'] == sha256_file(
        FIXTURES / 'scripted' / scripted.native['patch_artifact'])


def test_verifier_error_and_cancellation_never_become_model_zero():
    partial = normalize('partial-failure')
    assert partial.status == 'failed'
    assert partial.records[0].coverage.failed == 1
    assert partial.records[0].metrics == ()
    assert partial.diagnostics['native_job_stats']['evals']['oracle__adhoc']['metrics'][0]['mean'] == 0.5
    failed = next(s for s in partial.samples if s.sample_id == 'broken-verifier')
    assert failed.scores == {}
    assert failed.native['verifier_error']['exception_type'] == 'RewardFileNotFoundError'
    assert not failed.native['counted_as_model_failure']
    cancelled = normalize('cancellation')
    assert cancelled.status == 'cancelled'
    assert not cancelled.records[0].metrics
    assert cancelled.samples[0].scores == {}
    assert cancelled.samples[0].native['trial_status'] == 'cancelled'


def test_inconsistent_native_counters_cannot_prove_success(tmp_path):
    shutil.copytree(FIXTURES / 'oracle', tmp_path / 'oracle')
    path = tmp_path / 'oracle/result.json'
    job = json.loads(path.read_text())
    job['stats']['n_completed_trials'] = 2
    path.write_text(json.dumps(job))
    with pytest.raises(ArtifactError, match='disagrees'):
        normalize('oracle', tmp_path)


def test_a_results_file_without_successful_terminal_job_is_incomplete(tmp_path):
    shutil.copytree(FIXTURES / 'oracle', tmp_path / 'oracle')
    path = tmp_path / 'oracle/result.json'
    job = json.loads(path.read_text())
    job['finished_at'] = None
    path.write_text(json.dumps(job))
    result = normalize('oracle', tmp_path)
    assert result.status == 'incomplete'
    assert result.records[0].coverage.status == 'partial'
    assert result.records[0].metrics == ()
