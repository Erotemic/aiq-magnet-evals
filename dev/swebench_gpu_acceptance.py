"""Small real-model checks inside an owned infer-stack lease; never a campaign."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from magnet_evals.benchmarks.swe_bench_pro import PRO_CHECKSUMS, PRO_REVISION
from magnet_evals.contracts import EvaluationRequest, ModelBinding
from magnet_evals.ensure import ensure_evaluation
from magnet_evals.store import ResultStore

REPO = Path(__file__).resolve().parents[1]


def verify_descriptor(alias: str, expected: dict, actual: dict):
    if not expected.get('immutable'):
        raise ValueError('GPU acceptance requires immutable configured serving provenance')
    observed = actual.get('serving_provenance', {}).get(alias)
    if observed != expected:
        raise ValueError('serving provenance changed between preflight and lease; reschedule')
    if not actual.get('lease_id') or actual.get('endpoints', {}).get(alias) != alias:
        raise ValueError('descriptor must identify an actual lease and the scheduled served alias')
    if not actual.get('base_url'):
        raise ValueError('lease descriptor has no model endpoint')


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        alias = kwconf.Value(None, required=True)
        preflight = kwconf.Value(None, required=True)
        descriptor = kwconf.Value(os.environ.get('INFER_STACK_ENDPOINT_DESCRIPTOR'), required=True)
        output = kwconf.Value(None, required=True)
        pro_root = kwconf.Value(None, required=True)
        harbor_python = kwconf.Value(None, required=True)
        verified_python = kwconf.Value(None, required=True)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    expected = json.loads(Path(args.preflight).read_text())
    descriptor = json.loads(Path(args.descriptor).read_text())
    verify_descriptor(args.alias, expected, descriptor)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'serving-provenance.json').write_text(json.dumps(expected, indent=2) + '\n')
    binding = ModelBinding(role='primary', model=args.alias, provider='openai', cache_token=expected['digest'])
    pro_root = Path(args.pro_root).resolve()
    pin = json.loads((REPO / 'dev/environments/swebench-pro-smoke.json').read_text())
    options = {'agent': 'python:locked_mini_swe:LockedMiniSwe', 'agent_revision': PRO_REVISION,
               'agent_kwargs': {'version': pin['mini_swe_agent_version'],
                               'config_file': str(pro_root / 'v2/tooling/configs/mini_toolcall.yaml')}}
    engines = {'execution_protocol': 'python:magnet_evals.benchmarks.swe_bench_pro:ProV2Protocol',
               'job_options': {'agent_setup_timeout_multiplier': 20},
               'registration_modules': ['locked_mini_swe', 'patch_replay'],
               'required_secrets': ['OPENAI_API_KEY']}
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('lease did not provide OPENAI_API_KEY')

    def execute(request, worker):
        result = ensure_evaluation(request, ResultStore(output / 'store'), worker_python=worker,
            env={'OPENAI_API_KEY': os.environ['OPENAI_API_KEY']},
            model_endpoints={'primary': descriptor['base_url']}, timeout_seconds=7200)
        if not result.run.complete:
            raise RuntimeError(f'real-model protocol failed; inspect {result.run.path}')
        if request.engine == 'harbor':
            for sample in result.run.result.samples:
                for native in (sample.native, sample.native.get('generation_native', {})):
                    name = native.get('trial_name')
                    if name:
                        project = re.sub(r'[^a-z0-9_-]', '-', (name + '__env').lower())
                        remaining = subprocess.check_output(['docker', 'ps', '-aq', '--filter',
                            'label=com.docker.compose.project=' + project]).strip()
                        if remaining:
                            raise RuntimeError('owned Harbor sandbox containers remain after cleanup')
        return result.run

    # Build via the same native image helper used by VM acceptance, then verify
    # the actual owned container's image ID at the pre-inference hook.
    task = REPO / 'tests/native/harbor_tasks/division'
    build_code = '''import asyncio,subprocess,sys
from pathlib import Path
from harbor.environments.docker.utils import default_docker_platform,ensure_docker_image_built
async def main():
    task=Path(sys.argv[1])
    image=await ensure_docker_image_built(docker_name="division",docker_build_context=task/"environment",dockerfile_path=task/"environment/Dockerfile",build_args={},platform=await default_docker_platform())
    print(subprocess.check_output(["docker","image","inspect",image,"--format","{{.Id}}"],text=True).strip())
asyncio.run(main())
'''
    image_id = subprocess.check_output([args.harbor_python, '-c', build_code, str(task)], text=True).strip()
    frozen_task = output / 'synthetic-task/division'
    shutil.copytree(task, frozen_task)
    config = frozen_task / 'task.toml'
    config.write_text(config.read_text().replace('[environment]\n',
        '[environment]\ndocker_image = ' + json.dumps(image_id) + '\n'))
    synthetic = EvaluationRequest(engine='harbor', task='path:' + str(frozen_task), data_revision='fixture-v1',
        models=(binding,), task_options=options, engine_options={**engines,
            'protocol_options': {'synthetic': True, 'image_ids': {'division': image_id}}})
    synthetic_run = execute(synthetic, args.harbor_python)
    if synthetic_run.result.samples[0].scores.get('reward') != 1:
        raise RuntimeError('real model did not solve the synthetic coding acceptance task')
    verified = EvaluationRequest.from_dict(json.loads((REPO / 'examples/swebench_verified_request.json').read_text()))
    from dataclasses import replace
    verified_run = execute(replace(verified, models=(binding,)), args.verified_python)
    subprocess.run([args.verified_python, str(REPO / 'dev/regrade_swebench_verified.py'),
        '--run', str(verified_run.path), '--output', str(output / 'verified-official')], check=True)
    pro = EvaluationRequest(engine='harbor', task='path:' + str(pro_root / 'v2/tasks'),
        task_revision=PRO_REVISION, data_revision='sha256:' + PRO_CHECKSUMS, models=(binding,),
        task_options={**options, 'task_ids': [pin['task_id']]}, engine_options={**engines,
            'checksums': str(pro_root / 'v2/SHA256SUMS'),
            'protocol_options': {'image_ids': {pin['task_id']: pin['image_id']}}})
    pro_run = execute(pro, args.harbor_python)
    (output / 'result.json').write_text(json.dumps({'status': 'PASS', 'lease_id': descriptor['lease_id'],
        'serving_digest': expected['digest'], 'synthetic_run': str(synthetic_run.path),
        'verified_run': str(verified_run.path), 'pro_run': str(pro_run.path),
        'protocols_complete': True, 'cleanup_verified': False}, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
