"""Native tests register test-only task/plugin modules (``tests.native.*``).

Workers only see the ``magnet_evals`` package itself (see
``magnet_evals.runner.worker_package_path``), so the repository root must be
on ``PYTHONPATH`` explicitly for workers, and their engine-spawned children,
to import those modules. Installed examples (``magnet_evals.examples``) need
nothing like this.
"""
import os
from pathlib import Path

import pytest

REPO = str(Path(__file__).resolve().parents[2])

# Harbor task repositories are sandbox inputs, not host-side pytest modules.
collect_ignore = ['harbor_tasks']


@pytest.fixture(autouse=True, scope='session')
def _repo_on_worker_path():
    old = os.environ.get('PYTHONPATH')
    parts = [p for p in (old or '').split(os.pathsep) if p]
    if REPO not in parts:
        os.environ['PYTHONPATH'] = os.pathsep.join([REPO, *parts])
    yield
    if old is None:
        os.environ.pop('PYTHONPATH', None)
    else:
        os.environ['PYTHONPATH'] = old
