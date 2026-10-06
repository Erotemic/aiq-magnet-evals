"""Local Docker Pro V2 profile: native generation, exact patch, fresh replay.

Harbor remains the engine. This execution protocol composes two owned native
jobs and indexes their evidence; it adds no scheduler or patch grader.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import replace
from functools import partial
from pathlib import Path

from magnet_evals.backends.harbor.normalize import normalize_harbor_job, read_object
from magnet_evals.contracts import CoverageFacts, EvaluationRequest, ModelBinding
from magnet_evals.errors import ArtifactError, RequestValidationError
from magnet_evals.jsonutil import sha256_file

PRO_REVISION = '66f92766bba642462d4bbe5479e83f91f9211862'
PRO_CHECKSUMS = '9d84f8507c89241d42d8b3ef911600a1ec75dbbb32687ce9b45b93318502c0bd'
PROTOCOL = 'local-harbor/pro-v2-offline-replay/v1'
SMOKE_TASK = 'instance_ansible__ansible-0ea40e09d1b35bcb69ff4d9cecf3d0defa4b36e8-v30a923fb5c164d6cd18280c02422f75e611e8fb2'


def profile_request(source: str | Path, profile: str, model: ModelBinding,
                    image_ids: dict[str, str]) -> EvaluationRequest:
    """Define smoke/HARD-51/full work without claiming untested runtime cells.

    All selected physical images must be pinned by the caller before execution.
    The upstream locked config's bytes are identified by ordinary Harbor resolve.
    """
    root = Path(source).resolve()
    if profile == 'smoke':
        ids = [SMOKE_TASK]
    elif profile == 'hard51':
        ids = (Path(__file__).parent / 'data/swebench-pro-hard51.txt').read_text().splitlines()
    elif profile == 'full':
        ids = sorted(p.name for p in (root / 'v2/tasks').iterdir() if (p / 'task.toml').is_file())
        if len(ids) != 642:
            raise RequestValidationError('the pinned Pro V2 full profile must contain 642 tasks')
    else:
        raise RequestValidationError('Pro V2 profile must be smoke, hard51 or full')
    if set(image_ids) != set(ids):
        raise RequestValidationError('pin an immutable image ID for every selected Pro V2 instance')
    return EvaluationRequest(engine='harbor', task='path:' + str(root / 'v2/tasks'),
        task_revision=PRO_REVISION, data_revision='sha256:' + PRO_CHECKSUMS, models=(model,),
        task_options={'task_ids': ids, 'agent': 'python:locked_mini_swe:LockedMiniSwe',
            'agent_revision': PRO_REVISION, 'n_attempts': 1, 'n_concurrent': 1,
            'agent_kwargs': {'version': '2.4.6',
                'config_file': str(root / 'v2/tooling/configs/mini_toolcall.yaml')}},
        engine_options={'checksums': str(root / 'v2/SHA256SUMS'),
            'execution_protocol': 'python:magnet_evals.benchmarks.swe_bench_pro:ProV2Protocol',
            'protocol_options': {'image_ids': image_ids},
            'required_secrets': ['OPENAI_API_KEY'], 'registration_modules': ['locked_mini_swe', 'patch_replay'],
            'job_options': {'agent_setup_timeout_multiplier': 20}})


def replay_source(source: Path, destination: Path, expected_names: list[str]) -> dict:
    """Create an unambiguous view for unchanged upstream first-match replay.

    Original result and patch bytes survive unchanged. A missing patch is an
    artifact error; an actually captured empty patch is a valid failed prediction.
    """
    trials = {}
    for path in sorted(source.glob('*/result.json')):
        result = read_object(path)
        name = result['task_name']
        if name in trials or name not in expected_names:
            raise ArtifactError('ambiguous or unexpected generation trial for replay')
        if result.get('exception_info') or not result.get('finished_at'):
            raise ArtifactError(f'generation trial is not successful: {name}')
        patch = path.parent / 'agent/model.patch'
        if not patch.is_file() or patch.is_symlink():
            raise ArtifactError(f'missing captured generation patch: {name}')
        trials[name] = (path, patch, result)
    if set(trials) != set(expected_names):
        raise ArtifactError('generation trial coverage does not match replay selection')
    destination.mkdir(parents=True, exist_ok=False)
    joins = {}
    for index, (name, (result_path, patch, result)) in enumerate(sorted(trials.items())):
        trial = destination / f'instance_{index}'
        (trial / 'agent').mkdir(parents=True)
        shutil.copy2(result_path, trial / 'result.json')
        shutil.copy2(patch, trial / 'agent/model.patch')
        joins[name] = {'generation_trial_id': result['id'],
                       'generation_trial_name': result['trial_name'],
                       'patch_sha256': sha256_file(patch), 'patch_bytes': patch.stat().st_size}
    return joins


def verifier_observation(trial: Path, task: Path) -> dict:
    """Record native test coverage; an early trap's zero is not a scored trial."""
    config = read_object(task / 'tests/config.json')
    required = set()
    for key in ('fail_to_pass', 'pass_to_pass'):
        values = config.get(key, [])
        if isinstance(values, str):
            import ast
            try:
                values = json.loads(values)
            except ValueError:
                values = ast.literal_eval(values)
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ArtifactError(f'invalid native Pro required-test config: {task}')
        required.update(values)
    output = trial / 'verifier/output.json'
    stdout = trial / 'verifier/test-stdout.txt'
    if not output.is_file() or not stdout.is_file():
        return {'complete': False, 'reason': 'native verifier did not retain test results'}
    tests = read_object(output).get('tests', [])
    if not isinstance(tests, list) or any(not isinstance(t, dict) for t in tests):
        raise ArtifactError('invalid native Pro parser test output')
    observed = {t.get('name') for t in tests if t.get('status') in ('PASSED', 'FAILED', 'ERROR', 'SKIPPED')}
    missing = required - observed
    complete = bool(required) and not missing and 'RESULT: ' in stdout.read_text()
    return {'complete': complete, 'required': sorted(required),
            'observed': sorted(n for n in observed if isinstance(n, str)),
            'missing': sorted(missing),
            'reason': None if complete else 'native verifier coverage is unavailable or ambiguous'}


def join_replay(generation, replay, joins: dict, *, replay_root: Path, tasks: dict[str, Path],
                require_test_coverage: bool):
    """Use replay rewards, with exact patch/native UUID lineage and no fake zero."""
    observed_ids = [s.sample_id for s in replay.samples]
    if (len(set(observed_ids)) != len(observed_ids) or set(observed_ids) - set(joins)
            or (replay.status == 'succeeded' and set(observed_ids) != set(joins))):
        raise ArtifactError('replay selection does not match generation patches')
    generated = {s.sample_id: s for s in generation.samples}
    samples, errors = [], 0
    for sample in replay.samples:
        origin = generated[sample.sample_id]
        link = joins[sample.sample_id]
        trial = replay_root / sample.native['trial_name']
        replay_path = trial / 'agent/replay.json'
        evidence = read_object(replay_path) if replay_path.is_file() else None
        if sample.native['trial_status'] == 'succeeded' and evidence is None:
            raise ArtifactError('completed replay trial has no native replay diagnostic')
        views = [p.parent.name for p in (replay_root.parent / 'replay-source').glob('*/result.json')
                 if read_object(p).get('task_name') == sample.sample_id]
        if len(views) != 1:
            raise ArtifactError('replay source view is not unambiguous')
        relative = Path('replay-inputs/agent-inputs/0/replay-source') / views[0] / 'agent/model.patch'
        snapshot = replay_root.parent / relative
        if not snapshot.is_file() or snapshot.is_symlink() or sha256_file(snapshot) != link['patch_sha256']:
            raise ArtifactError('replay input snapshot does not match the generation patch')
        if evidence is not None and link['patch_bytes']:
            applied = evidence.get('patch')
            if not isinstance(applied, str) or Path(applied).parts[-len(relative.parts):] != relative.parts:
                raise ArtifactError('upstream replay did not consume the selected generation patch')
        elif evidence is not None and evidence.get('patch') is not None:
            raise ArtifactError('empty captured patch was not replayed as empty')
        if sample.native['trial_status'] != 'succeeded':
            observation = {'complete': False, 'reason': 'native replay trial did not complete'}
        else:
            observation = verifier_observation(trial, tasks[sample.sample_id]) if require_test_coverage else {'complete': True}
        native = {**sample.native, **link, 'protocol': PROTOCOL,
                  'replay_trial_id': sample.native['trial_id'], 'replay': evidence,
                  'generation_native': origin.native, 'generation_rewards': origin.scores,
                  'replay_patch_artifact': 'native/harbor/' + relative.as_posix(),
                  'verifier_observation': observation,
                  'authoritative_phase': 'fresh-replay'}
        if not observation['complete']:
            errors += 1
            native.update(counted_as_model_failure=False,
                          verifier_error=native.get('verifier_error') or {'message': observation['reason']})
            if sample.native['trial_status'] == 'succeeded':
                native['trial_status'] = 'incomplete'
        samples.append(replace(sample, scores=sample.scores if observation['complete'] else {},
                               trajectory=origin.trajectory, usage=origin.usage, native=native))
    records = replay.records
    if errors:
        records = tuple(replace(record, metrics=(), primary_metric=None,
            coverage=CoverageFacts(status='partial', expected=len(joins), processed=record.coverage.processed,
                                   saved=len(samples) - errors, failed=errors),
            native_status='incomplete' if replay.status == 'succeeded' else replay.status) for record in records)
    return replace(replay, status='incomplete' if errors and replay.status == 'succeeded' else replay.status,
        records=records, samples=tuple(samples), diagnostics={**replay.diagnostics,
        'protocol': PROTOCOL, 'authoritative_phase': 'fresh-replay',
        'generation_diagnostics': generation.diagnostics,
        'missing_replay_ids': sorted(set(joins) - set(observed_ids)),
        'verifier_coverage_error_count': errors, 'aggregate_withheld': bool(errors) or replay.status != 'succeeded'})


def normalize_pro_jobs(source: Path, *, identity, fallback_task: str, synthetic=False):
    """Re-normalize a retained paired job without Harbor or the original paths."""
    generation = normalize_harbor_job(source / 'generation', identity=identity,
        fallback_task=fallback_task, location_prefix='native/harbor/generation')
    replay = normalize_harbor_job(source / 'replay', identity=identity,
        fallback_task=fallback_task, location_prefix='native/harbor/replay')
    tasks = {}
    for sample in generation.samples:
        name = sample.sample_id.split('/')[-1]
        if name in ('', '.', '..'):
            raise ArtifactError('invalid native Pro task name')
        tasks[sample.sample_id] = source / 'generation-inputs/inputs' / name
    return join_replay(generation, replay, read_object(source / 'joins.json'),
        replay_root=source / 'replay', tasks=tasks, require_test_coverage=not synthetic)


class ProV2Protocol:
    """Native execution-protocol extension for the generic Harbor backend."""

    def import_results(self, backend, resolved, source: Path):
        generation = normalize_harbor_job(source / 'generation', identity=resolved.identity,
            fallback_task=resolved.request.task, location_prefix='native/generation')
        backend.validate_import_facts(resolved, generation)
        result = normalize_pro_jobs(source, identity=resolved.identity,
            fallback_task=resolved.request.task,
            synthetic=resolved.request.engine_options.get('protocol_options', {}).get('synthetic', False))
        # The importer snapshots this source as the bundle's native root.
        # Rebase semantic paths from execution's native/harbor to native.
        def rebase(value):
            if isinstance(value, dict):
                return {key: rebase(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rebase(item) for item in value]
            if isinstance(value, str) and value.startswith('native/harbor/'):
                return 'native/' + value[len('native/harbor/'):]
            return value

        generated = {sample.sample_id: sample for sample in generation.samples}
        samples = []
        for sample in result.samples:
            native = rebase(sample.native)
            native['generation_native'] = generated[sample.sample_id].native
            samples.append(replace(sample, native=native))
        return replace(result, samples=tuple(samples), diagnostics={**result.diagnostics,
            'provenance': 'native paired Harbor import; request revisions/runtime pins are not attested'})

    def resolve_facts(self, request, native_config, tasks):
        options = request.engine_options.get('protocol_options', {})
        if set(options) - {'image_ids', 'synthetic'}:
            raise RequestValidationError('unknown Pro V2 protocol_options')
        synthetic = options.get('synthetic', False)
        if not isinstance(synthetic, bool) or request.task_options.get('n_attempts', 1) != 1:
            raise RequestValidationError('Pro V2 requires one attempt per instance and a boolean synthetic flag')
        if not synthetic and (request.task_revision != PRO_REVISION or request.data_revision != 'sha256:' + PRO_CHECKSUMS):
            raise RequestValidationError('Pro V2 requires the accepted candidate source/checksum pins')
        if not synthetic and not request.engine_options.get('checksums'):
            raise RequestValidationError('Pro V2 requires its native SHA256SUMS manifest')
        expected = options.get('image_ids', {})
        if (not isinstance(expected, dict) or set(expected) != {p.name for p in tasks}
                or any(not isinstance(v, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', v) for v in expected.values())):
            raise RequestValidationError('Pro V2 requires an immutable Docker image ID for each selected task')
        for path in tasks:
            config = tomllib.loads((path / 'task.toml').read_text())
            if config.get('agent', {}).get('network_mode') != 'no-network':
                raise RequestValidationError('Pro V2 requires the native offline agent phase')
            image = config.get('environment', {}).get('docker_image')
            if image:
                actual = subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True, timeout=30).strip()
                if actual != expected[path.name]:
                    raise RequestValidationError(f'Pro V2 image differs from pinned image ID: {path.name}')
        replay = importlib.import_module('patch_replay').PatchReplayAgent
        return {'protocol': PROTOCOL, 'replay_source_sha256': sha256_file(Path(inspect.getfile(replay))),
                'image_ids': expected, 'synthetic': synthetic}

    async def execute(self, backend, resolved, context):
        async def check_image(event, *, job_name):
            # Harbor 0.23's project naming rule, checked at the public agent-start
            # hook after sandbox/setup completion and before model inference.
            # Its environment-start event actually precedes container creation.
            project = (event.trial_name + '__env').lower()
            if not project[0].isalnum():
                project = '0' + project
            project = re.sub(r'[^a-z0-9_-]', '-', project)
            containers = (await asyncio.to_thread(subprocess.check_output,
                ['docker', 'ps', '--filter', 'label=com.docker.compose.project=' + project,
                 '--filter', 'label=com.docker.compose.service=main', '--format', '{{.ID}}'],
                text=True, timeout=30)).split()
            if len(containers) != 1:
                raise RuntimeError('cannot identify exactly one owned Harbor main container')
            actual = (await asyncio.to_thread(subprocess.check_output,
                ['docker', 'inspect', containers[0], '--format', '{{.Image}}'], text=True, timeout=30)).strip()
            expected = resolved.resolved_facts['identity_facts']['execution_protocol']['facts']['image_ids'][event.task_name.split('/')[-1]]
            destination = context.output_dir / 'native/harbor' / job_name / event.trial_name / 'runtime-image.json'
            destination.write_text(json.dumps({'image_id': actual, 'expected_image_id': expected,
                'trial_id': str(event.trial_id), 'timestamp': event.timestamp.isoformat()}, indent=2) + '\n')
            if actual != expected:
                raise RuntimeError('owned Harbor container image differs from the pinned image')
            if job_name == 'generation' and resolved.request.task_options.get('agent') == 'python:locked_mini_swe:LockedMiniSwe':
                probe = (
                    'import importlib.metadata as m,json,platform; '
                    'print(json.dumps({"python":platform.python_version(),'
                    '"packages":{d.metadata["Name"]:d.version for d in m.distributions()}}))'
                )
                runtime = json.loads(await asyncio.to_thread(subprocess.check_output,
                    ['docker', 'exec', '-u', 'root', containers[0],
                     '/root/.local/share/uv/tools/mini-swe-agent/bin/python', '-c', probe], text=True, timeout=30))
                destination.with_name('runtime-agent.json').write_text(json.dumps(runtime, indent=2, sort_keys=True) + '\n')
                version = resolved.request.task_options['agent_kwargs'].get('version')
                if runtime['packages'].get('mini-swe-agent') != version:
                    raise RuntimeError('observed installed mini-SWE agent differs from its requested version')

        generation = await backend.execute_job(resolved, context, job_name='generation',
            agent_started_hook=partial(check_image, job_name='generation'))
        if generation.status != 'succeeded':
            return replace(generation, records=tuple(replace(r, metrics=(), primary_metric=None) for r in generation.records),
                diagnostics={**generation.diagnostics, 'protocol': PROTOCOL, 'authoritative_phase': None, 'aggregate_withheld': True})
        root = context.output_dir / 'native/harbor'
        names = resolved.resolved_facts['identity_facts']['native_task_names']
        joins = replay_source(root / 'generation', root / 'replay-source', names)
        request = resolved.request
        replay_request = replace(request, models=(ModelBinding(role='primary', model='replay', revision=PRO_REVISION),),
            generation={}, task_options={**request.task_options,
                'agent': 'python:patch_replay:PatchReplayAgent', 'agent_revision': PRO_REVISION,
                'agent_kwargs': {'source_job': str(root / 'replay-source')}},
            engine_options={key: value for key, value in request.engine_options.items()
                            if key not in ('execution_protocol', 'protocol_options', 'required_secrets')})
        replay_resolved = backend.resolve(replay_request)
        replay_context = replace(context, model_endpoints={})
        replay = await backend.execute_job(replay_resolved, replay_context, job_name='replay',
            agent_started_hook=partial(check_image, job_name='replay'))
        # The parent measurement names the generation model and both native phases.
        replay = replace(replay, identity=resolved.identity)
        tasks = dict(zip(names, (Path(t['path']) for t in resolved.native_config['tasks']), strict=True))
        result = join_replay(generation, replay, joins, replay_root=root / 'replay', tasks=tasks,
                             require_test_coverage=not request.engine_options['protocol_options'].get('synthetic', False))
        (root / 'generation-normalized.json').write_text(json.dumps(generation.to_dict(), indent=2) + '\n')
        (root / 'replay-normalized.json').write_text(json.dumps(replay.to_dict(), indent=2) + '\n')
        (root / 'joins.json').write_text(json.dumps(joins, indent=2, sort_keys=True) + '\n')
        return result
