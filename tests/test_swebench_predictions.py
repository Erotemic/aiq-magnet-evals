"""Patch-export contract tests; native acceptance proves benchmark semantics."""
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from magnet_evals.benchmarks.swe_bench_verified import (
    export_predictions,
    prediction_records,
)
from magnet_evals.contracts import EvaluationRequest, ModelBinding, SampleRecord
from magnet_evals.errors import ArtifactError
from magnet_evals.outputs import load_run

FIXTURES = Path(__file__).parent / 'fixtures/swebench-verified-native'


def sample(patch='', **changes):
    base = SampleRecord(task='verified', model_role='primary', sample_id='psf__requests-1142',
        epoch=1, scores={'swe_bench_scorer': {'value': 0, 'metadata': {'model_patch': patch}}},
        native={'kind': 'sample', 'log_location': 'native/log.eval', 'uuid': 'native-sample',
                'metadata': {'patch': 'gold patch must never be used as a fallback'}})
    return replace(base, **changes)


def run(*samples, complete=True):
    request = EvaluationRequest(engine='inspect_ai', task='python:test:verified',
                                models=(ModelBinding(role='primary', model='served-model'),))
    return SimpleNamespace(complete=complete, resolved=SimpleNamespace(request=request),
                           result=SimpleNamespace(samples=samples))


def test_empty_prediction_is_preserved_with_native_lineage():
    predictions, lineage = prediction_records(run(sample()))
    assert predictions == [{'instance_id': 'psf__requests-1142',
                            'model_name_or_path': 'served-model', 'model_patch': ''}]
    assert lineage[0]['native_log'] == 'native/log.eval'
    assert lineage[0]['native_sample_uuid'] == 'native-sample'


@pytest.mark.parametrize('broken', [
    sample(scores={}), sample(patch=None), sample(patch='Agent patch could not be decoded'),
    sample(scores={'one': {'metadata': {'model_patch': ''}},
                   'two': {'metadata': {'model_patch': 'diff --git a/x b/x\n'}}}),
    sample(native={'kind': 'sample', 'error': {'message': 'verifier failed'}}),
    sample(sample_id='../bad-instance')])
def test_ungradeable_export_is_refused(broken):
    with pytest.raises(ArtifactError):
        prediction_records(run(broken))


def test_multiple_attempts_are_not_silently_selected():
    with pytest.raises(ArtifactError, match='ambiguous repeated'):
        prediction_records(run(sample(), sample(epoch=2)))


def test_partial_run_is_not_exported_as_complete():
    with pytest.raises(ArtifactError, match='complete Inspect run'):
        prediction_records(run(sample(), complete=False))


def test_native_capture_checksums():
    manifest = json.loads((FIXTURES / 'capture.json').read_text())
    for name, checksum in manifest['sha256'].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == checksum, name


@pytest.mark.parametrize('solver,reward', [('oracle', 1), ('nop', 0)])
def test_captured_patches_match_fresh_official_grading(tmp_path, solver, reward):
    fixture = FIXTURES / solver
    native_run = load_run(fixture / 'run')
    predictions = export_predictions(native_run.path, tmp_path / 'predictions.jsonl')
    assert predictions.read_bytes() == (fixture / 'predictions.jsonl').read_bytes()
    rows = [json.loads(line) for line in predictions.read_text().splitlines()]
    ids = {row['instance_id'] for row in rows}
    assert len(ids) == 5
    report = json.loads((fixture / f'official/mockllm__model.{solver}.json').read_text())
    assert set(report['resolved_ids']) == (ids if reward else set())
    assert report['error_ids'] == [] and report['incomplete_ids'] == []
    for row in rows:
        if reward:
            graded = fixture / 'official/logs/run_evaluation' / solver / 'mockllm__model' / row['instance_id']
            assert (graded / 'patch.diff').read_text() == row['model_patch']
        else:
            assert row['model_patch'] == ''
    samples = [s for s in native_run.result.samples if s.native.get('kind') == 'sample']
    assert all(s.scores['swe_bench_scorer']['value'] == reward for s in samples)


def test_export_refuses_tampered_native_artifact(tmp_path):
    bundle = tmp_path / 'run'
    shutil.copytree(FIXTURES / 'oracle/run', bundle)
    next((bundle / 'native').rglob('*.eval')).write_bytes(b'tampered')
    with pytest.raises(ArtifactError, match='checksum mismatch'):
        export_predictions(bundle, tmp_path / 'predictions.jsonl')
