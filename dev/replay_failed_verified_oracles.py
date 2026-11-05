"""Replay failed captured oracles with full grader output, without a model or lease."""
from __future__ import annotations

import importlib.metadata
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from magnet_evals.benchmarks.swe_bench_verified import INSPECT_EVALS_REVISION
from magnet_evals.outputs import load_run


def replay(run_path: Path, output: Path, *, current_environment=False):
    from inspect_evals.swe_bench.scorers import (
        get_eval_script,
        get_score_and_explanation_from_test_output,
    )

    from magnet_evals.benchmarks.inspect_verified_task import (
        verified_sandbox_environment,
    )

    run = load_run(run_path)
    request = run.resolved.request
    if (request.task_revision != INSPECT_EVALS_REVISION
            or request.task != 'python:magnet_evals.benchmarks.inspect_verified_task:verified_task'
            or request.task_options.get('solver') != 'oracle'
            or request.task_options.get('clean_repository') is not True or not run.complete):
        raise ValueError('Requires a complete captured pinned Verified oracle run')
    if (importlib.metadata.version('inspect-ai') != '0.3.272'
            or importlib.metadata.version('swebench') != '3.0.15'):
        raise ValueError('Requires the pinned Verified worker')
    samples = [s for s in run.result.samples if s.native.get('kind') == 'sample'
               and s.scores['swe_bench_scorer']['value'] != 1]
    if not samples:
        raise ValueError('No failing oracle samples to replay')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'source.json').write_text(json.dumps({
        'run': str(run_path.resolve()), 'measurement_identity': run.resolved.identity.to_dict(),
        'inspect_ai': importlib.metadata.version('inspect-ai'),
        'swebench': importlib.metadata.version('swebench'),
        'inspect_evals': importlib.metadata.version('inspect-evals'),
        'current_environment': current_environment,
        'instance_ids': [sample.sample_id for sample in samples]}, indent=2) + '\n')
    summary = []
    for sample in samples:
        metadata = sample.native['metadata']
        image = request.task_options['images'][sample.sample_id]
        case = output / sample.sample_id
        case.mkdir()
        patch = sample.scores['swe_bench_scorer']['metadata']['model_patch']
        (case / 'oracle.patch').write_text(patch)
        script = get_eval_script(**{key: metadata[key] for key in (
            'test_patch', 'repo', 'version', 'base_commit')})
        (case / 'eval_script').write_text(script)
        subprocess.run(['docker', 'image', 'inspect', image], check=True,
                       stdout=subprocess.DEVNULL)
        environment = (verified_sandbox_environment(metadata['repo'],
            clean_repository=request.task_options['clean_repository'],
            agent_protocol=request.task_options.get('agent_protocol', 'upstream'))
            if current_environment else {})
        env_args = [item for key, value in environment.items() for item in ('--env', f'{key}={value}')]
        container = subprocess.check_output(['docker', 'create', '--network', 'none',
            '--workdir', '/testbed', *env_args, image, 'sleep', 'infinity'], text=True).strip()
        print(f'Replaying {sample.sample_id}; full output: {case / "grader.log"}', flush=True)
        try:
            subprocess.run(['docker', 'start', container], check=True, stdout=subprocess.DEVNULL)
            for name in ('oracle.patch', 'eval_script'):
                subprocess.run(['docker', 'cp', str(case / name), f'{container}:/tmp/{name}'],
                               check=True, stdout=subprocess.DEVNULL)
            commit = metadata['base_commit']
            # Match this run's git-reset-clean/v1 setup, then apply its actual
            # captured solver patch and run the upstream native script unchanged.
            subprocess.run(['docker', 'exec', container, 'git', 'reset', '--hard', commit],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run(['docker', 'exec', container, 'git', 'clean', '-fd'],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run(['docker', 'exec', container, 'git', 'apply', '/tmp/oracle.patch'],
                           check=True)
            with (case / 'grader.log').open('w') as log:
                completed = subprocess.run(['docker', 'exec', container, 'bash', '/tmp/eval_script'],
                    stdout=log, stderr=subprocess.STDOUT, timeout=900)
            log_text = (case / 'grader.log').read_text()
            value, explanation = get_score_and_explanation_from_test_output(log_text,
                SimpleNamespace(sample_id=sample.sample_id, metadata=metadata, input='oracle replay'))
            row = {'instance_id': sample.sample_id, 'image': image,
                   'environment': environment,
                   'original_score': sample.scores['swe_bench_scorer']['value'],
                   'replay_score': value, 'script_exit_code': completed.returncode,
                   'explanation': explanation}
            (case / 'result.json').write_text(json.dumps(row, indent=2) + '\n')
            summary.append(row)
            (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
            print(f'{sample.sample_id}: replay score={value}\n{log_text[-5000:]}', flush=True)
        finally:
            subprocess.run(['docker', 'rm', '-f', container], check=True,
                           stdout=subprocess.DEVNULL)
    return summary


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        run = kwconf.Value(None, required=True)
        output = kwconf.Value(None, required=True)
        current_environment = kwconf.Value(False, isflag=True)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    replay(Path(args.run), Path(args.output), current_environment=args.current_environment)


if __name__ == '__main__':
    main()
