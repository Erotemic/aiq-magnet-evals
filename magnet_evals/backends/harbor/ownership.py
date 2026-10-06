"""Attempt-owned Docker resources survive abrupt worker termination."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def record_project(work_dir: Path, trial_name: str) -> str:
    project = (trial_name + '__env').lower()
    if not project[0].isalnum():
        project = '0' + project
    project = re.sub(r'[^a-z0-9_-]', '-', project)
    root = work_dir / 'native/harbor/owned-projects'
    root.mkdir(parents=True, exist_ok=True)
    target = root / (project + '.json')
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'project': project, 'trial_name': trial_name}) + '\n')
    temporary.replace(target)
    return project


def cleanup_owned_docker(work_dir: Path) -> dict:
    """Remove only journaled projects with an attempt-owned Compose directory."""
    removed, errors = [], []

    def docker(*args):
        return subprocess.check_output(['docker', *args], text=True, timeout=30).strip()

    for path in sorted((work_dir / 'native/harbor/owned-projects').glob('*.json')):
        try:
            if path.is_symlink():
                raise ValueError('ownership record is a symlink')
            project = json.loads(path.read_text())['project']
            if not isinstance(project, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*__env', project):
                raise ValueError('invalid owned project')
            selector = 'label=com.docker.compose.project=' + project
            containers = docker('ps', '-aq', '--filter', selector).split()
            for container in containers:
                facts, = json.loads(docker('inspect', container))
                directory = facts['Config']['Labels'].get('com.docker.compose.project.working_dir')
                if not directory or not Path(directory).resolve().is_relative_to(work_dir.resolve()):
                    raise ValueError(f'container Compose directory {directory!r} is outside owned attempt {str(work_dir)!r}')
            if containers:
                docker('rm', '-f', '-v', *containers)
                removed.extend(containers)
            for network in docker('network', 'ls', '-q', '--filter', selector).split():
                facts, = json.loads(docker('network', 'inspect', network))
                if facts.get('Containers'):
                    raise ValueError('owned network still has attached containers')
                docker('network', 'rm', network)
        except Exception as exc:
            errors.append({'record': path.name, 'error': f'{type(exc).__name__}: {exc}'})
    report = {'removed_containers': removed, 'errors': errors}
    destination = work_dir / 'native/aiq_worker/harbor-cleanup.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    return report
