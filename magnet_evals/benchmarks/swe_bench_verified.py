"""Engine-free export of actual Inspect SWE-bench patches for official grading."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from magnet_evals.artifacts import RunBundle
from magnet_evals.errors import ArtifactError
from magnet_evals.jsonutil import sha256_file
from magnet_evals.outputs import load_run

INSPECT_EVALS_REVISION = '9080b5e9f1647ed14e45de8cb01e3d43411c0163'
VERIFIED_DATASET = 'princeton-nlp/SWE-bench_Verified'
VERIFIED_REVISION = 'c104f840cc67f8b6eec6f759ebc8b2693d585d4a'
SWEBENCH_CANDIDATE_VERSION = '3.0.15'


def prediction_records(run: RunBundle) -> tuple[list[dict], list[dict]]:
    """Require one actual, unambiguous patch per completed native sample.

    Empty patches are legitimate failed predictions. Gold patches in sample
    metadata are never substituted for the scorer's captured ``model_patch``.
    Multiple epochs require separate exports rather than picking one silently.
    """
    if run.resolved.request.engine != 'inspect_ai' or not run.complete:
        raise ArtifactError('SWE-bench patch export requires a complete Inspect run')
    rows, lineage, seen = [], [], set()
    model = run.resolved.request.primary_model.model
    for sample in run.result.samples:
        if sample.native.get('kind') != 'sample':
            continue
        instance = sample.sample_id
        if not re.fullmatch(r'[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+', instance):
            raise ArtifactError(f'invalid SWE-bench instance id: {instance!r}')
        if instance in seen:
            raise ArtifactError(f'ambiguous repeated SWE-bench instance: {instance}')
        seen.add(instance)
        if sample.native.get('error') is not None:
            raise ArtifactError(f'errored SWE-bench sample: {instance}')
        patches = []
        for score in sample.scores.values():
            if isinstance(score, dict) and isinstance(score.get('metadata'), dict):
                metadata = score['metadata']
                if 'model_patch' in metadata:
                    patches.append(metadata['model_patch'])
        if not patches or any(not isinstance(patch, str) for patch in patches) or len(set(patches)) != 1:
            raise ArtifactError(f'missing or ambiguous captured model_patch: {instance}')
        patch = patches[0]
        if patch and not patch.startswith('diff --git '):
            raise ArtifactError(f'captured model_patch is not a git diff: {instance}')
        rows.append({'instance_id': instance, 'model_name_or_path': model, 'model_patch': patch})
        lineage.append({'instance_id': instance, 'epoch': sample.epoch,
                        'native_log': sample.native.get('log_location'),
                        'native_sample_uuid': sample.native.get('uuid'),
                        'eval_id': sample.native.get('eval_id'),
                        'patch_sha256': hashlib.sha256(patch.encode()).hexdigest()})
    if not rows:
        raise ArtifactError('Inspect run contains no saved SWE-bench samples with patches')
    return rows, lineage


def export_predictions(run_dir: str | Path, output: str | Path) -> Path:
    """Write official JSONL plus source/checksum lineage from a verified bundle."""
    run = load_run(run_dir)
    rows, lineage = prediction_records(run)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    source = {'schema': 'aiq-magnet-evals-swebench-predictions/1',
              'measurement_identity': run.resolved.identity.to_dict(),
              'normalized_artifact_identity': run.manifest.get('normalized_artifact_identity'),
              'native_artifact_identity': run.manifest.get('native_artifact_identity'),
              'predictions_sha256': sha256_file(target), 'samples': lineage}
    target.with_suffix(target.suffix + '.provenance.json').write_text(
        json.dumps(source, indent=2, sort_keys=True) + '\n')
    return target
