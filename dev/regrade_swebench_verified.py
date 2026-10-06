"""Fresh upstream official grading of a completed pinned Verified run.

Run in the pinned Verified worker. The exporter itself remains engine-free.
"""
from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

from magnet_evals.benchmarks.swe_bench_verified import (
    VERIFIED_DATASET,
    VERIFIED_REVISION,
    export_predictions,
)
from magnet_evals.errors import ArtifactError
from magnet_evals.jsonutil import sha256_json
from magnet_evals.outputs import load_run


def regrade(run_dir: Path, output: Path):
    from datasets import load_dataset

    if importlib.metadata.version('swebench') != '3.0.15':
        raise ArtifactError('official regrading requires the candidate SWE-bench 3.0.15 worker')
    run = load_run(run_dir)
    options = run.resolved.request.task_options
    if run.resolved.request.data_revision != VERIFIED_REVISION:
        raise ArtifactError('official regrading requires the pinned Verified dataset')
    ids = options['instance_ids']
    images = options['images']
    output.mkdir(parents=True, exist_ok=False)
    predictions = export_predictions(run_dir, output / 'predictions.jsonl')
    dataset = load_dataset(VERIFIED_DATASET, revision=VERIFIED_REVISION, split='test')
    selected = [row for row in dataset if row['instance_id'] in ids]
    if {row['instance_id'] for row in selected} != set(ids):
        raise ArtifactError('official dataset selection does not match the request')
    dataset_path = output / 'dataset.json'
    dataset_path.write_text(json.dumps(selected))
    tag = 'aiq-verified-' + sha256_json(images)[:16]
    for image in images.values():
        subprocess.run(['docker', 'image', 'inspect', image], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'tag', image, image.split('@')[0] + ':' + tag], check=True)
    command = [sys.executable, '-m', 'swebench.harness.run_evaluation',
        '--dataset_name', str(dataset_path.resolve()), '--predictions_path', str(predictions.resolve()),
        '--max_workers', '1', '--run_id', 'acceptance', '--instance_ids', *ids,
        '--instance_image_tag', tag, '--timeout', '600', '--cache_level', 'instance', '--clean', 'False']
    with (output / 'grader.log').open('w') as log:
        subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT, timeout=3600, check=True)
    reports = list(output.glob('*.acceptance.json'))
    if len(reports) != 1:
        raise ArtifactError('official grader did not retain exactly one report')
    report = json.loads(reports[0].read_text())
    expected_resolved = {sample.sample_id for sample in run.result.samples
        if sample.native.get('kind') == 'sample' and sample.scores['swe_bench_scorer']['value'] == 1}
    if report['error_ids'] or report['incomplete_ids'] or set(report['submitted_ids']) != set(ids):
        raise ArtifactError('official grading did not cover all selected predictions without errors')
    (output / 'protocol.json').write_text(json.dumps({
        'dataset': VERIFIED_DATASET, 'dataset_revision': VERIFIED_REVISION,
        'dataset_sha256': sha256_json(selected), 'images': images,
        'swebench_version': '3.0.15', 'swebench_revision': 'b524f150d5d76f188c741d75669025f718c89c2e',
        'repository_setup': 'git-reset-clean/v1' if options.get('clean_repository') else None,
        'grader_command': command, 'inspect_resolved_ids': sorted(expected_resolved),
        'verdict_agreement': set(report['resolved_ids']) == expected_resolved}, indent=2) + '\n')
    if set(report['resolved_ids']) != expected_resolved:
        raise ArtifactError('Inspect and official per-instance verdicts disagree; inspect retained reports')
    return report


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        run = kwconf.Value(None, required=True)
        output = kwconf.Value(None, required=True)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    report = regrade(Path(args.run), Path(args.output))
    print(json.dumps({'resolved_ids': report['resolved_ids'], 'submitted_ids': report['submitted_ids']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
