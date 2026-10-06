"""Engine-free reading of the evidenced Harbor 0.23 job/trial layout.

Raw native aggregates remain diagnostics when any trial errored. In this pin
Harbor's mean includes infrastructure errors as zeros; those are not model
failures. Rewards and exceptions remain separate sample facts.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from magnet_evals.contracts import (
    CoverageFacts,
    EvaluationResult,
    MeasurementIdentity,
    MetricRecord,
    ResultRecord,
    SampleRecord,
    as_execution_status,
)
from magnet_evals.errors import ArtifactError
from magnet_evals.jsonutil import sha256_file


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ArtifactError(f'cannot read Harbor JSON {path}: {exc}') from exc
    if not isinstance(value, dict):
        raise ArtifactError(f'Harbor JSON must be an object: {path}')
    return value


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactError(f'Harbor {label} must be a nonnegative integer')
    return value


def _exception_phase(trial: dict[str, Any]) -> str | None:
    if not trial.get('exception_info'):
        return None
    for phase in ('verifier', 'agent_execution', 'agent_setup', 'environment_setup'):
        if (trial.get(phase) or {}).get('started_at'):
            return {'agent_execution': 'agent', 'agent_setup': 'agent_setup',
                    'environment_setup': 'environment', 'verifier': 'verifier'}[phase]
    return 'unknown'


def normalize_harbor_job(
    source: Path,
    *,
    identity: MeasurementIdentity,
    fallback_task: str,
    location_prefix: str = '',
    forced_status: str | None = None,
    failure: str | None = None,
) -> EvaluationResult:
    source = Path(source)
    job = read_object(source / 'result.json')
    config = read_object(source / 'config.json')
    expected = _count(job.get('n_total_trials'), 'n_total_trials')
    if expected == 0:
        raise ArtifactError('Harbor job contains no requested trials')
    stats = job.get('stats') or {}
    if not isinstance(stats, dict):
        raise ArtifactError('Harbor job stats must be an object')
    trials = []
    ids = set()
    for path in sorted(source.glob('*/result.json')):
        if path.is_symlink():
            raise ArtifactError(f'Harbor trial result must not be a symlink: {path}')
        trial = read_object(path)
        for field in ('id', 'trial_name', 'task_name'):
            if not isinstance(trial.get(field), str) or not trial[field]:
                raise ArtifactError(f'Harbor trial missing {field}: {path}')
        if trial['trial_name'] != path.parent.name or trial['id'] in ids:
            raise ArtifactError(f'Harbor trial identity/directory mismatch or duplicate: {path}')
        ids.add(trial['id'])
        trials.append((path.parent, trial))
    if len(trials) > expected:
        raise ArtifactError('Harbor job contains more trial results than requested')

    def location(path: Path) -> str:
        return '/'.join(part for part in (location_prefix.rstrip('/'), path.relative_to(source).as_posix()) if part)

    samples = []
    rewarded = errors = cancelled = terminal = 0
    for directory, trial in trials:
        exception = trial.get('exception_info')
        rewards = (trial.get('verifier_result') or {}).get('rewards')
        if rewards is not None and (not isinstance(rewards, dict) or any(not _finite(v) for v in rewards.values())):
            raise ArtifactError(f'invalid Harbor verifier rewards: {directory}')
        # Never let an exception become a scientific zero (or a stale reward).
        if exception:
            if not isinstance(exception, dict):
                raise ArtifactError(f'invalid Harbor exception: {directory}')
            errors += 1
            is_cancelled = exception.get('exception_type') == 'CancelledError'
            cancelled += int(is_cancelled)
            trial_status = 'cancelled' if is_cancelled else 'errored'
        elif not trial.get('finished_at') or not rewards:
            trial_status = 'incomplete'
        else:
            rewarded += 1
            trial_status = 'succeeded'
        terminal += int(bool(trial.get('finished_at')))
        phase = _exception_phase(trial)
        native = {
            'trial_id': trial['id'], 'trial_name': trial['trial_name'],
            'trial_status': trial_status, 'exception_phase': phase,
            'exception_info': exception,
            'agent_error': exception if phase in ('agent', 'agent_setup') else None,
            'environment_error': exception if phase == 'environment' else None,
            'verifier_error': exception if phase == 'verifier' else None,
            'counted_as_model_failure': trial_status == 'succeeded' and any(v == 0 for v in (rewards or {}).values()),
            'native_rewards': rewards,
            'result_artifact': location(directory / 'result.json'),
            'task_checksum': trial.get('task_checksum'),
            'agent_info': trial.get('agent_info'),
            'verifier_environment_mode': trial.get('verifier_environment_mode'),
            'timings': {key: trial.get(key) for key in ('environment_setup', 'agent_setup', 'agent_execution', 'verifier')},
            # Harbor does not record a numerical attempt index in TrialResult.
            'attempt_id': trial['id'],
            'verifier_artifacts': [location(p) for p in sorted((directory / 'verifier').glob('*')) if p.is_file()],
        }
        patch = directory / 'agent/model.patch'
        if patch.is_file():
            native['patch_artifact'] = location(patch)
            native['patch_sha256'] = sha256_file(patch)
        trajectory = None
        trajectory_path = directory / 'agent/trajectory.json'
        if trajectory_path.is_file():
            try:
                trajectory = json.loads(trajectory_path.read_text())
            except ValueError as exc:
                raise ArtifactError(f'invalid Harbor trajectory: {trajectory_path}') from exc
            native['trajectory_artifact'] = location(trajectory_path)
        usage = {key: value for key, value in (trial.get('agent_result') or {}).items()
                 if key in ('n_input_tokens', 'n_output_tokens', 'n_cache_tokens', 'cost_usd') and value is not None}
        samples.append(SampleRecord(task=fallback_task, model_role='primary', sample_id=trial['task_name'],
            scores=(rewards or {}) if trial_status == 'succeeded' else {}, trajectory=trajectory, usage=usage, native=native))

    for key, observed in (('n_completed_trials', terminal), ('n_errored_trials', errors), ('n_cancelled_trials', cancelled)):
        if key in stats and _count(stats[key], key) != observed:
            raise ArtifactError(f'Harbor {key} disagrees with retained trial files')
    complete = len(trials) == expected and rewarded == expected and bool(job.get('finished_at'))
    status = 'cancelled' if cancelled else 'failed' if errors else 'succeeded' if complete else 'incomplete'
    if forced_status:
        status = as_execution_status(forced_status)
    coverage = CoverageFacts(status='complete' if complete else 'partial', expected=expected,
                             processed=terminal, saved=rewarded, failed=errors)
    metrics = []
    if complete and status == 'succeeded':
        for group, evaluation in (stats.get('evals') or {}).items():
            denominator = _count(evaluation.get('n_trials'), 'evals.n_trials')
            for entry in evaluation.get('metrics', []):
                for name, value in entry.items():
                    if _finite(value):
                        metrics.append(MetricRecord(task=fallback_task, model_role='primary', metric=name,
                            value=value, scorer='verifier', score='reward', group=group,
                            reducer=name, denominator=denominator))
    record = ResultRecord(task=fallback_task, model_role='primary', metrics=tuple(metrics),
        coverage=coverage, primary_metric='mean' if any(m.metric == 'mean' for m in metrics) else None,
        native_status=status, error=failure, native_config=config)
    return EvaluationResult(engine='harbor', identity=identity, status=status, records=(record,),
        samples=tuple(samples), diagnostics={'native_job_id': job.get('id'), 'native_job_stats': stats,
            'infrastructure_error_count': errors, 'failure': failure,
            'aggregate_withheld': not complete or status != 'succeeded',
            'provenance': 'native Harbor job; request revision tokens are not attested by an import'})
