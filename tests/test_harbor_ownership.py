"""Hard-kill cleanup may only touch containers from the owned attempt."""
import json
from pathlib import Path

from magnet_evals.backends.harbor.ownership import cleanup_owned_docker, record_project
from magnet_evals.jsonutil import sha256_file
from magnet_evals.outputs import load_run


def test_foreign_compose_directory_is_preserved(tmp_path, monkeypatch):
    record_project(tmp_path, 'division__unique')
    commands = []

    def docker(args, **kwargs):
        commands.append(args)
        if args[1] == 'ps':
            return 'foreign-container\n'
        return json.dumps([{'Config': {'Labels': {'com.docker.compose.project.working_dir': '/another/attempt'}}}])

    monkeypatch.setattr('magnet_evals.backends.harbor.ownership.subprocess.check_output', docker)
    result = cleanup_owned_docker(tmp_path)
    assert result['errors'] and not result['removed_containers']
    assert not any(args[1] == 'rm' for args in commands)


def test_incomplete_ownership_record_does_not_trigger_docker(tmp_path, monkeypatch):
    record_project(tmp_path, 'division__unique')
    record, = (tmp_path / 'native/harbor/owned-projects').glob('*.json')
    record.rename(record.with_suffix('.tmp'))

    def unexpected(*args, **kwargs):
        raise AssertionError('an unpublished ownership record is not actionable')

    monkeypatch.setattr('magnet_evals.backends.harbor.ownership.subprocess.check_output', unexpected)
    assert cleanup_owned_docker(tmp_path) == {'removed_containers': [], 'errors': []}


def test_captured_sigkill_is_cancelled_and_cleanup_is_not_a_score():
    root = Path(__file__).parent / 'fixtures/harbor-hardkill-native'
    capture = json.loads((root / 'capture.json').read_text())
    for relative, digest in capture['sha256'].items():
        assert sha256_file(root / relative) == digest, relative
    run = load_run(root / 'run')
    assert run.result.status == 'cancelled' and not run.complete
    assert not run.result.records and not (run.path / 'RUN_COMPLETE').exists()
    observation = json.loads((root / 'hardkill-observation.json').read_text())
    assert observation['worker']['returncode'] == -9
    assert observation['unrelated_container_preserved']
    assert observation['owned_containers_absent'] and observation['owned_networks_absent']
    cleanup = json.loads((run.path / 'native/aiq_worker/harbor-cleanup.json').read_text())
    assert cleanup['removed_containers'] and not cleanup['errors']
