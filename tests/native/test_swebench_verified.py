"""Pinned Verified Docker oracle/NOP and fresh official regrade acceptance."""
from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from magnet_evals.benchmarks.swe_bench_verified import (
    INSPECT_EVALS_REVISION,
    VERIFIED_DATASET,
    VERIFIED_REVISION,
    export_predictions,
)
from magnet_evals.contracts import EvaluationRequest, ModelBinding
from magnet_evals.ensure import ensure_evaluation
from magnet_evals.jsonutil import sha256_json
from magnet_evals.store import ResultStore

pytestmark = [pytest.mark.native, pytest.mark.docker_sandbox, pytest.mark.release_gate]
IMAGES_PATH = Path(__file__).parents[2] / 'dev/environments/swebench-verified-images.json'


@pytest.mark.parametrize('solver,reward', [('oracle', 1), ('nop', 0)])
def test_verified_patches_regrade_in_fresh_official_containers(tmp_path, solver, reward):
    from datasets import load_dataset

    assert importlib.metadata.version('inspect-ai') == '0.3.272'
    assert importlib.metadata.version('swebench') == '3.0.15'
    images = json.loads(IMAGES_PATH.read_text())
    ids = list(images)
    request = EvaluationRequest(engine='inspect_ai',
        task='python:magnet_evals.benchmarks.inspect_verified_task:verified_task',
        task_revision=INSPECT_EVALS_REVISION, data_revision=VERIFIED_REVISION,
        models=(ModelBinding(role='primary', model='mockllm/model', revision='fixture-v1'),),
        task_options={'instance_ids': ids, 'images': images, 'solver': solver,
                      'clean_repository': True, 'tool_timeout': 210},
        engine_options={'registration_modules': ['inspect_evals.swe_bench.scorers',
            'inspect_evals.swe_bench.solvers', 'inspect_evals.swe_bench.swe_bench'],
            'eval_options': {'max_sandboxes': 1, 'max_tasks': 1, 'message_limit': 30,
                             'sandbox_cleanup': True}})
    # Fresh store and fresh containers: an old canonical oracle is not a gate.
    outcome = ensure_evaluation(request, ResultStore(tmp_path / 'store'), worker_python=sys.executable)
    assert outcome.run.complete, outcome.run.result.diagnostics
    samples = [s for s in outcome.run.result.samples if s.native.get('kind') == 'sample']
    assert {s.sample_id for s in samples} == set(ids)
    assert all(s.native.get('error') is None for s in samples)
    assert all(s.scores['swe_bench_scorer']['value'] == reward for s in samples)
    predictions = export_predictions(outcome.run.path, tmp_path / 'predictions.jsonl')
    prediction_rows = [json.loads(line) for line in predictions.read_text().splitlines()]
    assert {row['instance_id'] for row in prediction_rows} == set(ids)
    if solver == 'nop':
        assert all(row['model_patch'] == '' for row in prediction_rows)
    else:
        assert all(row['model_patch'].startswith('diff --git ') for row in prediction_rows)

    # Upstream 3.0.15 has no dataset-revision flag. Its documented local-JSON
    # path freezes the same selected rows instead of loading a moving revision.
    dataset = load_dataset(VERIFIED_DATASET, revision=VERIFIED_REVISION, split='test')
    frozen = [row for row in dataset if row['instance_id'] in ids]
    dataset_path = tmp_path / 'dataset.json'
    dataset_path.write_text(json.dumps(frozen))
    tag = 'aiq-verified-' + sha256_json(images)[:16]
    for image in images.values():
        subprocess.run(['docker', 'image', 'inspect', image], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'tag', image, image.split('@')[0] + ':' + tag], check=True)
    grader_root = tmp_path / 'official'
    grader_root.mkdir()
    command = [sys.executable, '-m', 'swebench.harness.run_evaluation',
        '--dataset_name', str(dataset_path), '--predictions_path', str(predictions),
        '--max_workers', '1', '--run_id', solver, '--instance_ids', *ids,
        '--instance_image_tag', tag, '--timeout', '600', '--cache_level', 'instance',
        '--clean', 'False']
    with (grader_root / 'grader.log').open('w') as log:
        completed = subprocess.run(command, cwd=grader_root, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
    assert completed.returncode == 0, (grader_root / 'grader.log').read_text()[-4000:]
    report = json.loads((grader_root / f'mockllm__model.{solver}.json').read_text())
    assert report['error_ids'] == [] and report['incomplete_ids'] == []
    assert set(report['resolved_ids']) == (set(ids) if reward else set())
    assert set(report['submitted_ids']) == set(ids)
    assert report['completed_instances'] == (len(ids) if reward else 0)
    if not reward:
        # Official harness explicitly counts empty predictions without launching
        # a grader container; do not invent a per-instance test report for them.
        assert set(report['empty_patch_ids']) == set(ids)
    (grader_root / 'protocol.json').write_text(json.dumps({
        'dataset': VERIFIED_DATASET, 'dataset_revision': VERIFIED_REVISION,
        'dataset_sha256': sha256_json(frozen), 'images': images,
        'swebench_version': '3.0.15', 'swebench_revision': 'b524f150d5d76f188c741d75669025f718c89c2e',
        'repository_setup': 'git-reset-clean/v1', 'grader_command': command}, indent=2))
    destination = os.environ.get('AIQ_VERIFIED_CAPTURE_DIR')
    if destination:
        import shutil
        target = Path(destination) / solver / tmp_path.name
        shutil.copytree(tmp_path, target)
