"""Thin task factory around pinned inspect-evals SWE-bench semantics.

Native imports remain inside the worker-only factory. This selects samples,
freezes image digests and chooses the upstream oracle for acceptance; grading,
patch capture and the production agent remain upstream implementations.
"""
from __future__ import annotations

import importlib
import re

from magnet_evals.errors import RequestValidationError

AGENT_PROTOCOLS = ('upstream', 'minimal-edit/v1')
MINIMAL_EDIT_INSTRUCTIONS = """Working rules for this attempt:
- Make the smallest change that satisfies the issue. Preserve behavior outside
  the requested change. Treat suggested fixes as hypotheses to verify.
- Use existing tests as independent checks. Do not change existing assertions
  merely to accept your implementation. Explain any test expectation change
  required by the issue; preserve checks for unrelated behavior. Add focused
  regression tests where useful.
- First run targeted tests for the behavior you changed, then a bounded relevant
  regression subset. For Django runtests.py, pass --parallel 1 explicitly.
  Do not launch the entire test suite as a substitute for testing the issue.
- This sandbox has no Internet. Inspect the installed dependencies and choose
  local checks rather than repeatedly trying network installs. A test skipped
  because its required backend is absent does not validate the fix.
- The bash_session tool is stateful. Use action=type_submit to execute a
  command; action=type only types text. Read pending output before submitting
  another command to the same session. Use git --no-pager for inspection.
- Verify requested behavior and preserved behavior separately. Review the diff
  for unrelated changes, then submit when your focused checks are complete.

"""
MINIMAL_EDIT_ENV = {
    'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONIOENCODING': 'utf-8',
    'PAGER': 'cat', 'GIT_PAGER': 'cat', 'DJANGO_TEST_PROCESSES': '1',
    'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
}


def verified_sandbox_environment(repo, *, clean_repository=True, agent_protocol='upstream'):
    environment = dict(MINIMAL_EDIT_ENV) if agent_protocol == 'minimal-edit/v1' else {}
    if clean_repository and repo == 'sphinx-doc/sphinx':
        # git-reset-clean/v1 removes the image's tracked tox.ini pre-install
        # edit (pytest -rA). Restore per-test reporting through tox's public
        # environment overrides without adding harness edits to model.patch.
        environment.update({'PYTEST_ADDOPTS': '-rA',
                            'TOX_OVERRIDE': 'testenv.pass_env+=PYTEST_ADDOPTS'})
    return environment


def _verified_task(*, instance_ids, images, solver='agent', tool_timeout=210,
                   clean_repository=True, agent_protocol='upstream'):
    if agent_protocol not in AGENT_PROTOCOLS:
        raise RequestValidationError(f'unknown Verified agent_protocol: {agent_protocol!r}')
    if agent_protocol != 'upstream' and solver != 'agent':
        raise RequestValidationError('agent_protocol requires solver=agent')
    native_solver = importlib.import_module('inspect_ai.solver').solver
    util = importlib.import_module('inspect_ai.util')
    upstream = importlib.import_module('inspect_evals.swe_bench')

    from magnet_evals.benchmarks.swe_bench_verified import (
        VERIFIED_DATASET,
        VERIFIED_REVISION,
    )

    if not isinstance(instance_ids, list) or not instance_ids or len(instance_ids) != len(set(instance_ids)):
        raise RequestValidationError('Verified requires a nonempty unique instance_ids list')
    if set(images) != set(instance_ids) or any(not re.search(r'@sha256:[0-9a-f]{64}$', str(image)) for image in images.values()):
        raise RequestValidationError('Verified requires an image digest for every selected instance')
    if solver not in {'agent', 'oracle', 'nop'}:
        raise RequestValidationError('Verified solver must be agent, oracle or nop')
    if not isinstance(clean_repository, bool):
        raise RequestValidationError('Verified clean_repository must be a boolean')

    def sandbox_config(sandbox_type, sample):
        # Same upstream service configuration, using public ComposeConfig so
        # concurrent jobs cannot overwrite a shared per-instance cache file.
        image = images.get(str(sample.id), sample.metadata['image_name'])
        sample.metadata['image_name'] = image
        service = {
            'image': image, 'command': 'sleep infinity', 'working_dir': '/testbed',
            'network_mode': 'none'}
        environment = verified_sandbox_environment(sample.metadata.get('repo'),
            clean_repository=clean_repository, agent_protocol=agent_protocol)
        if environment:
            service['environment'] = environment
        compose = util.ComposeConfig.model_validate({'services': {'default': service}})
        return util.SandboxEnvironmentSpec(type=sandbox_type, config=compose)

    task = upstream.swe_bench(dataset=VERIFIED_DATASET, revision=VERIFIED_REVISION,
                     sandbox_type='docker', allow_internet=False,
                     sandbox_config=sandbox_config, tool_timeout=tool_timeout)
    task.dataset = task.dataset.filter(lambda sample: str(sample.id) in instance_ids)
    if {str(sample.id) for sample in task.dataset} != set(instance_ids):
        raise RequestValidationError('Verified selected ids are not in the pinned dataset')
    if agent_protocol == 'minimal-edit/v1':
        for sample in task.dataset:
            if not isinstance(sample.input, str):
                raise RequestValidationError('minimal-edit/v1 requires a text task input')
            sample.input = MINIMAL_EDIT_INSTRUCTIONS + sample.input
            sample.metadata['aiq_agent_protocol'] = agent_protocol
    if clean_repository:
        # Prebuilt benchmark images can contain untracked build outputs. The
        # upstream scorer's git add -A would capture those as model changes,
        # producing a patch that cannot replay in the same pristine image.
        for sample in task.dataset:
            commit = sample.metadata['base_commit']
            if not re.fullmatch(r'[0-9a-f]{40}', commit):
                raise RequestValidationError('Verified dataset base_commit is not a full git SHA')
            sample.setup = ('#!/bin/bash\nset -e\ncd /testbed\ngit reset --hard '
                            + commit + '\ngit clean -fd\n' + (sample.setup or ''))
            sample.metadata['aiq_repository_setup'] = 'git-reset-clean/v1'
    if solver == 'oracle':
        task.solver = upstream.swe_bench_oracle_solver()
    elif solver == 'nop':
        @native_solver
        def noop():
            async def solve(state, generate):
                return state
            return solve
        task.solver = noop()
    return task


def __getattr__(name):
    if name == 'verified_task':
        # Register only when the native worker resolves this attribute. Merely
        # importing the module remains possible without Inspect installed.
        factory = importlib.import_module('inspect_ai').task(name='aiq_swebench_verified')(_verified_task)
        globals()[name] = factory
        return factory
    raise AttributeError(name)
