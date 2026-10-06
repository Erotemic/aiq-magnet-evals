"""Required native evidence cannot disappear behind a coarse green gate."""
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dev.swebench_vm_checks import checks_pass, collect_checks

RECORDED = Path(__file__).parents[1] / 'docs/planning/evidence/swebench-vm-2026-10-05'


def recorded_report(root):
    for path in RECORDED.glob('*.xml'):
        shutil.copy2(path, root / path.name)
    return json.loads((RECORDED / 'report.json').read_text())['gates']


def test_recorded_native_evidence_reports_each_requirement(tmp_path):
    gates = recorded_report(tmp_path)
    report = collect_checks(tmp_path, gates)
    assert len(report['checks']) == 17
    failed = {name for name, row in report['checks'].items() if row['status'] == 'FAIL'}
    assert failed == {'magnet-fake-lease-integration', 'quantization-measurement-invalidation'}
    assert not checks_pass(report)
    assert report['evidence_sha256']['verified.xml']


@pytest.mark.parametrize('failure', ['missing', 'skipped', 'failure', 'error', 'duplicate'])
def test_required_case_is_never_inferred_from_other_passing_tests(tmp_path, failure):
    gates = recorded_report(tmp_path)
    path = tmp_path / 'pro-generation-replay.xml'
    tree = ET.parse(path)
    suite, = tree.iter('testsuite')
    wanted, = [case for case in suite.iter('testcase') if case.get('name', '').endswith('[nop-0]')]
    if failure == 'missing':
        suite.remove(wanted)
    elif failure == 'duplicate':
        suite.append(ET.fromstring(ET.tostring(wanted)))
    else:
        ET.SubElement(wanted, failure)
    tree.write(path)
    assert gates['pro-generation-replay'] == 'PASS'  # Deliberately stale coarse status.
    report = collect_checks(tmp_path, gates)
    assert report['checks']['pro-v2-nop-smoke']['status'] == 'FAIL'
    assert report['checks']['fresh-patch-replay']['status'] == 'FAIL'
    assert report['checks']['pro-v2-oracle-smoke']['status'] == 'PASS'


def test_magnet_binding_requires_actual_unique_junit_cases(tmp_path):
    gates = recorded_report(tmp_path)
    gates['magnet-fake-lease'] = 'PASS'
    path = tmp_path / 'magnet-fake-lease.xml'
    path.write_text('<testsuite><testcase classname="consumer" name="fake_lease"/>'
                    '<testcase classname="consumer" name="quantization_mutation"/></testsuite>')
    binding = tmp_path / 'magnet-checks.json'
    binding.write_text(json.dumps({'magnet-fake-lease-integration': ['consumer.fake_lease'],
        'quantization-measurement-invalidation': ['consumer.quantization_mutation']}))
    assert checks_pass(collect_checks(tmp_path, gates))
    binding.write_text(json.dumps({'magnet-fake-lease-integration': ['consumer.unexecuted_test']}))
    assert not checks_pass(collect_checks(tmp_path, gates))
    path.write_text('<testsuite/>')
    assert not checks_pass(collect_checks(tmp_path, gates))


def test_old_or_malformed_reports_cannot_authorize_gpu_work():
    assert not checks_pass({'status': 'PASS', 'gates': {'everything': 'PASS'}})
    assert not checks_pass({'checks': None})
