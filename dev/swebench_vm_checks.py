"""Derive the roadmap's independent checks from actual JUnit evidence."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from magnet_evals.jsonutil import sha256_file


def _case(gate, module, name):
    return gate, module + '.' + name


def required_checks():
    native = 'tests.native.'
    def conformance(name):
        return _case('harbor-conformance', native + 'test_conformance', name + '[harbor]')

    bridge = _case('harbor-phase0', native + 'test_harbor_phase0', 'test_allowlist_bridge_tool_execution_and_phase_policy')
    replay = _case('harbor-phase0', native + 'test_harbor_phase0', 'test_exact_patch_replay_in_fresh_sandbox')
    tools = _case('pro-generation-replay', native + 'test_swebench_pro', 'test_locked_mini_swe_tools_capture_exact_patch_and_replay')
    oracle = _case('pro-generation-replay', native + 'test_swebench_pro', 'test_pro_gold_and_nop_are_scored_by_fresh_replay[oracle-1]')
    nop = _case('pro-generation-replay', native + 'test_swebench_pro', 'test_pro_gold_and_nop_are_scored_by_fresh_replay[nop-0]')
    quantization = _case('serving-provenance', 'tests.test_serving_provenance', 'test_weight_changes_invalidate_same_alias[quantization-Q5]')
    return {
        'harbor-backend-conformance': [conformance(name) for name in (
            'test_resolution_is_deterministic_and_worker_consistent',
            'test_ensure_executes_reuses_imports_and_reads_engine_free',
            'test_failure_is_inspectable_and_never_canonical',
            'test_cancellation_leaves_cancelled_attempt_and_no_canonical')],
        'harbor-import-normalization-parity': [
            conformance('test_ensure_executes_reuses_imports_and_reads_engine_free'),
            _case('engine-free', 'tests.test_harbor_normalize', 'test_engine_free_oracle_nop_and_scripted_roundtrip')],
        'nested-container-endpoint-bridge': [bridge, _case('harbor-conformance',
            native + 'test_harbor_native', 'test_worker_uses_shared_bridge_and_scripted_tools')],
        'scripted-tool-using-synthetic-task': [bridge, tools],
        'unlisted-local-lan-egress-denial': [bridge],
        'internet-egress-denial': [bridge],
        'endpoint-allowlist-success': [bridge],
        'exact-patch-capture': [replay, tools],
        'fresh-patch-replay': [replay, oracle, nop],
        'model-infrastructure-failure-separation': [
            _case('harbor-phase0', native + 'test_harbor_phase0', 'test_partial_verifier_failure_is_not_zero_reward'),
            _case('engine-free', 'tests.test_harbor_normalize', 'test_verifier_error_and_cancellation_never_become_model_zero'),
            _case('engine-free', 'tests.test_swebench_pro', 'test_early_native_verifier_zero_does_not_depress_the_replay_aggregate')],
        'verified-smoke-official-regrade': [_case('verified', native + 'test_swebench_verified',
            'test_verified_patches_regrade_in_fresh_official_containers[' + mode + ']') for mode in ('oracle-1', 'nop-0')],
        'pro-v2-oracle-smoke': [oracle],
        'pro-v2-nop-smoke': [nop],
        'magnet-fake-lease-integration': [],
        'serving-provenance-identity': [quantization,
            _case('serving-provenance', 'tests.test_serving_provenance', 'test_placement_and_reclaim_are_operational'),
            _case('serving-provenance', 'tests.test_serving_provenance', 'test_descriptor_uses_actual_deployment_and_emits_private_free_json')],
        'quantization-measurement-invalidation': [quantization],
        'result-reuse-single-flight': [conformance('test_ensure_executes_reuses_imports_and_reads_engine_free'),
            _case('engine-free', 'tests.test_single_flight', 'test_concurrent_ensures_execute_once'),
            _case('engine-free', 'tests.test_single_flight', 'test_single_flight_spans_processes')],
    }


MAGNET_CHECKS = {'magnet-fake-lease-integration', 'quantization-measurement-invalidation'}


def collect_checks(root: Path, gates: dict[str, str]) -> dict:
    """Missing, skipped, failed or ambiguous required evidence is FAIL."""
    cases, sources = {}, {}
    for gate in gates:
        path = root / (gate + '.xml')
        cases[gate] = {}
        if not path.is_file():
            continue
        sources[path.name] = sha256_file(path)
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        for node in tree.iter('testcase'):
            key = node.get('classname', '') + '.' + node.get('name', '')
            state = 'PASS' if all(node.find(tag) is None for tag in ('skipped', 'failure', 'error')) else 'FAIL'
            cases[gate].setdefault(key, []).append(state)
    bindings = {}
    mapping = root / 'magnet-checks.json'
    if mapping.is_file():
        sources[mapping.name] = sha256_file(mapping)
        try:
            value = json.loads(mapping.read_text())
            if isinstance(value, dict):
                bindings = value
        except ValueError:
            pass
    checks = {}
    for label, requirements in required_checks().items():
        evidence = []
        if label in MAGNET_CHECKS:
            names = bindings.get(label)
            if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names):
                evidence.append({'gate': 'magnet-fake-lease', 'status': 'FAIL',
                                 'reason': 'missing MAGNET check-to-JUnit binding'})
            else:
                requirements = [*requirements, *(('magnet-fake-lease', name) for name in names)]
        for gate, name in requirements:
            observed = cases.get(gate, {}).get(name, [])
            passed = gates.get(gate) == 'PASS' and observed == ['PASS']
            evidence.append({'gate': gate, 'test': name, 'status': 'PASS' if passed else 'FAIL',
                             'reason': None if passed else 'gate failed or required test missing, skipped, failed or duplicated'})
        checks[label] = {'status': 'PASS' if evidence and all(e['status'] == 'PASS' for e in evidence) else 'FAIL',
                         'evidence': evidence}
    return {'checks': checks, 'evidence_sha256': sources}


def checks_pass(report: dict) -> bool:
    checks = report.get('checks', {})
    return (isinstance(checks, dict) and set(checks) == set(required_checks())
            and all(isinstance(row, dict) and row.get('status') == 'PASS'
                    and isinstance(row.get('evidence'), list) and row['evidence']
                    and all(isinstance(item, dict) and item.get('status') == 'PASS' for item in row['evidence'])
                    for row in checks.values()))
