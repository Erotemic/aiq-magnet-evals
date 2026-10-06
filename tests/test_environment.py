from magnet_evals.probes.environment import host_facts, probe_all_engine_imports


def test_host_facts():
    facts = host_facts()
    assert facts['python']
    assert facts['python_executable']


def test_probe_all_engine_imports():
    rows = probe_all_engine_imports()
    assert {row.details['engine'] for row in rows} == {'harbor', 'helm', 'olmo_eval', 'inspect_ai'}
