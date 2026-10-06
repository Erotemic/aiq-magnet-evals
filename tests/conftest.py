"""Test classification, quarantine, and external-failure policy (plan phase 8).

* Tests under ``tests/native`` are marked ``native``.
* ``tests/quarantine.txt`` lists node IDs whose failures are reported as xfail
  (never silently skipped). A ``release_gate`` test can never be quarantined:
  listing one is a usage error, so quarantine cannot turn a required gate green.
* A test marked ``external`` whose failure is a network/connection error is
  reported as skipped with an ``external-unavailable`` reason instead of
  failing. The classification never applies to ``release_gate`` tests, and
  each test gets this treatment at most once per session: repeated external
  failure is a real failure.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

QUARANTINE_FILE = Path(__file__).with_name('quarantine.txt')
# Captures include upstream/sandbox test source. Read it as evidence; never
# collect or execute those files in the host's pytest process.
collect_ignore = ['fixtures', 'native/harbor_tasks']
RELEASE_GATE_MODULES = {
    'test_conformance.py',
    'test_native_fixture_regression.py',
    'test_schema_compat.py',
}
_NETWORK_ERRORS = (ConnectionError, TimeoutError, socket.gaierror, socket.timeout)
_EXTERNAL_SKIPS: set[str] = set()


def _quarantined() -> set[str]:
    if not QUARANTINE_FILE.is_file():
        return set()
    return {
        line.split('#', 1)[0].strip()
        for line in QUARANTINE_FILE.read_text().splitlines()
        if line.split('#', 1)[0].strip()
    }


def pytest_collection_modifyitems(config, items):
    quarantined = _quarantined()
    for item in items:
        path = Path(str(item.fspath))
        if 'native' in path.parts:
            item.add_marker(pytest.mark.native)
        if path.name in RELEASE_GATE_MODULES:
            item.add_marker(pytest.mark.release_gate)
    for item in items:
        if item.nodeid.split('[')[0] in quarantined or item.nodeid in quarantined:
            if item.get_closest_marker('release_gate'):
                raise pytest.UsageError(
                    f'{item.nodeid} is a release_gate test and cannot be quarantined'
                )
            item.add_marker(pytest.mark.xfail(reason='quarantined (tests/quarantine.txt)', strict=False))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if (
        report.when == 'call'
        and report.failed
        and item.get_closest_marker('external')
        and not item.get_closest_marker('release_gate')
        and call.excinfo is not None
        and call.excinfo.errisinstance(_NETWORK_ERRORS)
        and item.nodeid not in _EXTERNAL_SKIPS
    ):
        _EXTERNAL_SKIPS.add(item.nodeid)
        report.outcome = 'skipped'
        report.longrepr = (str(item.fspath), item.location[1], f'external-unavailable: {call.excinfo.exconly()}')
