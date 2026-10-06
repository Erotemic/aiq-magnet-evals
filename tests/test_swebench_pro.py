"""Replay ambiguity and native verifier coverage, using retained native files."""
import json
import shutil
from pathlib import Path

import pytest

from magnet_evals.artifacts import publish_run
from magnet_evals.backends.harbor import HarborBackend
from magnet_evals.benchmarks.swe_bench_pro import (
    normalize_pro_jobs,
    replay_source,
    verifier_observation,
)
from magnet_evals.contracts import ExecutionContext, MeasurementIdentity
from magnet_evals.errors import ArtifactError
from magnet_evals.jsonutil import sha256_file
from magnet_evals.outputs import load_run
from tests.regression.summary import summarize

HARBOR_FIXTURES = Path(__file__).parent / 'fixtures/harbor-native'
PRO_FIXTURES = Path(__file__).parent / 'fixtures/swebench-pro-native'
AGENT_FIXTURES = Path(__file__).parent / 'fixtures/swebench-pro-agent-native'
CAPTURES = [(PRO_FIXTURES, 'oracle', 1), (PRO_FIXTURES, 'nop', 0),
            (PRO_FIXTURES, 'locked-mini-synthetic', 1),
            (AGENT_FIXTURES, 'locked-mini-pro-scripted-gold', 1)]
IDENTITY = MeasurementIdentity(algorithm='regression', digest='0' * 64, reusable=False)


def test_replay_view_preserves_exact_result_and_patch_bytes(tmp_path):
    source = HARBOR_FIXTURES / 'replay-generation'
    result = next(source.glob('*/result.json'))
    names = [json.loads(result.read_text())['task_name']]
    view = tmp_path / 'view'
    joins = replay_source(source, view, names)
    assert (view / 'instance_0/result.json').read_bytes() == result.read_bytes()
    assert (view / 'instance_0/agent/model.patch').read_bytes() == (result.parent / 'agent/model.patch').read_bytes()
    assert joins[names[0]]['generation_trial_id'] == json.loads(result.read_text())['id']


def test_repeated_trials_and_missing_patch_are_not_silently_replayed(tmp_path):
    source = tmp_path / 'source'
    shutil.copytree(HARBOR_FIXTURES / 'replay-generation', source)
    result = next(source.glob('*/result.json'))
    names = [json.loads(result.read_text())['task_name']]
    shutil.copytree(result.parent, source / 'duplicate')
    with pytest.raises(ArtifactError, match='ambiguous'):
        replay_source(source, tmp_path / 'duplicate-view', names)
    shutil.rmtree(source / 'duplicate')
    (result.parent / 'agent/model.patch').unlink()
    with pytest.raises(ArtifactError, match='missing captured'):
        replay_source(source, tmp_path / 'missing-view', names)


def test_native_early_verifier_zero_has_no_completed_test_observation(tmp_path):
    task, trial = tmp_path / 'task', tmp_path / 'trial'
    (task / 'tests').mkdir(parents=True)
    (task / 'tests/config.json').write_text(json.dumps({'fail_to_pass': ['test_divide'], 'pass_to_pass': []}))
    (trial / 'verifier').mkdir(parents=True)
    (trial / 'verifier/reward.txt').write_text('0\n')
    assert not verifier_observation(trial, task)['complete']
    (trial / 'verifier/output.json').write_text(json.dumps({'tests': [{'name': 'test_divide', 'status': 'FAILED'}]}))
    (trial / 'verifier/test-stdout.txt').write_text('RESULT: FAILED\n')
    assert verifier_observation(trial, task)['complete']


@pytest.mark.parametrize('root', [PRO_FIXTURES, AGENT_FIXTURES])
def test_native_pro_capture_integrity(root):
    capture = json.loads((root / 'capture.json').read_text())
    for relative, digest in capture['sha256'].items():
        assert sha256_file(root / relative) == digest, relative


@pytest.mark.parametrize('root,label,reward', CAPTURES)
def test_retained_pro_jobs_renormalize_without_engine_or_original_worker_paths(root, label, reward):
    source = root / label
    result = normalize_pro_jobs(source / 'native/harbor', identity=IDENTITY,
        fallback_task='pro-v2/fixture', synthetic=label == 'locked-mini-synthetic')
    expected = json.loads((root / 'expected-normalized.json').read_text())
    assert summarize(result) == expected[label]
    assert result.status == 'succeeded' and result.samples[0].scores['reward'] == reward
    assert result.records[0].metrics[0].value == reward
    sample = result.samples[0]
    assert sample.native['generation_trial_id'] != sample.native['replay_trial_id']
    assert sha256_file(source / sample.native['replay_patch_artifact']) == sample.native['patch_sha256']
    assert load_run(source).result.samples[0].scores == sample.scores


def test_early_native_verifier_zero_does_not_depress_the_replay_aggregate(tmp_path):
    source = tmp_path / 'native/harbor'
    shutil.copytree(PRO_FIXTURES / 'oracle/native/harbor', source)
    next((source / 'replay').glob('*/verifier/output.json')).unlink()
    result = normalize_pro_jobs(source, identity=IDENTITY, fallback_task='pro-v2/fixture')
    assert result.status == 'incomplete' and not result.records[0].metrics
    assert result.samples[0].scores == {}
    assert not result.samples[0].native['counted_as_model_failure']
    assert result.samples[0].native['native_rewards'] == {'reward': 1.0}


@pytest.mark.parametrize('root,label,reward', CAPTURES)
def test_paired_native_import_preserves_scores_and_semantic_paths(tmp_path, root, label, reward):
    original = load_run(root / label)
    context = ExecutionContext(output_dir=tmp_path / 'imported')
    source = original.path / 'native/harbor'
    result = HarborBackend().import_results(original.resolved, str(source), context)
    imported = publish_run(context.output_dir, resolved=original.resolved, result=result,
                           context=context, native_dir=source)
    assert imported.result.samples[0].scores == original.result.samples[0].scores
    sample = imported.result.samples[0]
    assert (imported.path / sample.native['replay_patch_artifact']).is_file()
    assert (imported.path / sample.native['generation_native']['result_artifact']).is_file()
    assert 'not attested' in imported.result.diagnostics['provenance']
