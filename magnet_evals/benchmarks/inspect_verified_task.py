"""Thin task factory around pinned inspect-evals SWE-bench semantics.

Native imports remain inside the worker-only factory. This selects samples,
freezes image digests and chooses the upstream oracle for acceptance; grading,
patch capture and the production agent remain upstream implementations.
"""
from __future__ import annotations

import importlib
import re

from magnet_evals.errors import RequestValidationError


def _verified_task(*, instance_ids, images, solver='agent', tool_timeout=210,
                   clean_repository=True):
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
        compose = util.ComposeConfig.model_validate({'services': {'default': {
            'image': image, 'command': 'sleep infinity', 'working_dir': '/testbed',
            'network_mode': 'none'}}})
        return util.SandboxEnvironmentSpec(type=sandbox_type, config=compose)

    task = upstream.swe_bench(dataset=VERIFIED_DATASET, revision=VERIFIED_REVISION,
                     sandbox_type='docker', allow_internet=False,
                     sandbox_config=sandbox_config, tool_timeout=tool_timeout)
    task.dataset = task.dataset.filter(lambda sample: str(sample.id) in instance_ids)
    if {str(sample.id) for sample in task.dataset} != set(instance_ids):
        raise RequestValidationError('Verified selected ids are not in the pinned dataset')
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
