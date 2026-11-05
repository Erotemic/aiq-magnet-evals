"""Fresh official diagnostic grading with an explicitly derived bytecode-free patch.

Original native scores, predictions and grader reports are never overwritten.
This is an audit of a transformed prediction, not a replacement raw verdict.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

from magnet_evals.benchmarks.swe_bench_verified import omit_transient_bytecode
from magnet_evals.jsonutil import sha256_json
from magnet_evals.outputs import load_run


def audit(run_root: Path, output: Path):
    if importlib.metadata.version('swebench') != '3.0.15':
        raise ValueError('Requires the pinned SWE-bench worker')
    run = load_run((run_root / 'run-path.txt').read_text().strip())
    if not run.complete:
        raise ValueError('Requires a completed native run')
    reports = list((run_root / 'official').glob('*.acceptance.json'))
    if len(reports) != 1:
        raise ValueError('Requires one retained original official report')
    original = json.loads(reports[0].read_text())
    if original['error_ids'] or original['incomplete_ids']:
        raise ValueError('Original official grading is incomplete')
    native_ids = {s.sample_id for s in run.result.samples if s.native.get('kind') == 'sample'
                  and s.scores['swe_bench_scorer']['value'] == 1}
    mismatches = native_ids ^ set(original['resolved_ids'])
    if not mismatches:
        raise ValueError('No native/official mismatch to audit')
    rows, lineage = [], []
    for sample in run.result.samples:
        if sample.sample_id not in mismatches:
            continue
        patch = sample.scores['swe_bench_scorer']['metadata']['model_patch']
        derived, omitted = omit_transient_bytecode(patch)
        if not omitted or not derived.startswith('diff --git '):
            raise ValueError(f'Mismatch has no supported transient-bytecode transform: {sample.sample_id}')
        rows.append({'instance_id': sample.sample_id,
                     'model_name_or_path': run.resolved.request.primary_model.model,
                     'model_patch': derived})
        lineage.append({'instance_id': sample.sample_id,
            'captured_patch_sha256': hashlib.sha256(patch.encode()).hexdigest(),
            'derived_patch_sha256': hashlib.sha256(derived.encode()).hexdigest(),
            'omitted': omitted})
    output.mkdir(parents=True, exist_ok=False)
    predictions = output / 'derived-predictions.jsonl'
    predictions.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    dataset = json.loads((run_root / 'official/dataset.json').read_text())
    selected = [row for row in dataset if row['instance_id'] in mismatches]
    if {row['instance_id'] for row in selected} != mismatches:
        raise ValueError('Retained dataset does not cover the mismatch')
    dataset_path = output / 'dataset.json'
    dataset_path.write_text(json.dumps(selected))
    protocol = json.loads((run_root / 'official/protocol.json').read_text())
    if (sha256_json(dataset) != protocol['dataset_sha256']
            or protocol['images'] != run.resolved.request.task_options['images']):
        raise ValueError('Retained dataset or image lineage disagrees with the source protocol')
    tag = protocol['grader_command'][protocol['grader_command'].index('--instance_image_tag') + 1]
    images = {instance: run.resolved.request.task_options['images'][instance] for instance in mismatches}
    for image in images.values():
        subprocess.run(['docker', 'image', 'inspect', image], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'tag', image, image.split('@')[0] + ':' + tag], check=True)
    command = [sys.executable, '-m', 'swebench.harness.run_evaluation',
        '--dataset_name', str(dataset_path.resolve()), '--predictions_path', str(predictions.resolve()),
        '--max_workers', '1', '--run_id', 'bytecode-audit', '--instance_ids', *sorted(mismatches),
        '--instance_image_tag', tag, '--timeout', '600', '--cache_level', 'instance', '--clean', 'False']
    evidence = {'schema': 'verified-bytecode-patch-audit/v1', 'source_run': str(run.path),
        'original_official_report': str(reports[0].resolve()), 'images': images,
        'prediction_transform': 'omit-new-transient-cpython-cache/v1',
        'lineage': lineage, 'grader_command': command, 'status': 'prepared'}
    (output / 'audit.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'CPU-only official audit: {sorted(mismatches)}; output: {output}', flush=True)
    with (output / 'grader.log').open('w') as log:
        subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT,
                       timeout=900 * len(mismatches) + 600, check=True)
    reports = list(output.glob('*.bytecode-audit.json'))
    if len(reports) != 1:
        raise ValueError('Audit did not retain exactly one official report')
    result = json.loads(reports[0].read_text())
    if (result['error_ids'] or result['incomplete_ids']
            or set(result['submitted_ids']) != mismatches):
        raise ValueError('Audit did not grade all derived predictions without errors')
    evidence.update(status='complete', audit_report=str(reports[0].resolve()),
        original_native_resolved_ids=sorted(native_ids & mismatches),
        original_official_resolved_ids=sorted(set(original['resolved_ids']) & mismatches),
        derived_official_resolved_ids=result['resolved_ids'])
    (output / 'audit.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2), flush=True)
    return evidence


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        run_root = kwconf.Value(None, required=True)
        output = kwconf.Value(None, required=True)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    audit(Path(args.run_root), Path(args.output))


if __name__ == '__main__':
    main()
