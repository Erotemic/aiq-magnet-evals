"""Attempt-owned endpoint bridge preserving Harbor's native egress sidecar."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from magnet_evals.backends.harbor.relay import relay
from magnet_evals.errors import RequestValidationError

RELAY_IMAGE = 'python:3.12-alpine@sha256:4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111'


def egress_response_config(source: str, timeout: int) -> dict:
    """Keep the native allowlist/sniffer, extending its HTTP header deadline."""
    import yaml  # Harbor worker dependency; the core package stays engine-free.

    config = yaml.safe_load(source)
    for service in config['services']:
        handler = service.get('handler', {})
        if handler.get('type') in ('red', 'redir', 'redirect'):
            handler.setdefault('metadata', {})['readTimeout'] = f'{timeout}s'
    return config


@contextlib.contextmanager
def endpoint_bridge(directory: Path, upstream: str, *, egress_response_timeout: int | None = None):
    """Expose the exact upstream through a named private service, not the host.

    The native job owns/removes the compose service. This context owns the
    gateway-bound host hop. Only Linux local Docker was evidenced in Phase 0.
    """
    parsed = urlsplit(upstream)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RequestValidationError('Harbor endpoint must be an HTTP(S) base URL without embedded credentials/query/fragment')
    if os.environ.get('DOCKER_HOST', '').startswith(('tcp:', 'ssh:')):
        raise RequestValidationError('Harbor endpoint bridge requires the evidenced local Docker daemon')
    gateway = json.loads(subprocess.check_output([
        'docker', 'network', 'inspect', 'bridge', '--format', '{{json .IPAM.Config}}',
    ], timeout=10))[0]['Gateway']
    origin = urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))
    directory.mkdir(parents=True, exist_ok=True)
    services = {}
    if egress_response_timeout is not None:
        stock_config = files('harbor.environments.docker').joinpath(
            'harbor-docker-egress-control-sidecar/gost.yaml').read_text()
        egress_config = directory / 'egress-response-timeout.json'
        # JSON is valid YAML. Keep the effective config in retained job inputs.
        egress_config.write_text(json.dumps(egress_response_config(
            stock_config, egress_response_timeout), indent=2) + '\n')
        services['harbor-docker-egress-control-sidecar'] = {'volumes': [{
            'type': 'bind', 'source': str(egress_config.resolve()),
            'target': '/opt/egress-sidecar/gost.yaml', 'read_only': True}]}
    timeout = egress_response_timeout or 600
    with relay(origin, gateway, timeout=timeout) as port:
        startup = (
            'from relay import relay; import threading; '
            f"bridge=relay('http://{gateway}:{port}', '0.0.0.0', 8080, timeout={timeout}); "
            'bridge.__enter__(); threading.Event().wait()'
        )
        compose = directory / 'endpoint-bridge.json'
        services['model-relay'] = {
            'image': RELAY_IMAGE, 'working_dir': '/aiq-relay',
            'command': ['python', '-c', startup], 'networks': ['default'],
            'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('relay.py').resolve()),
                         'target': '/aiq-relay/relay.py', 'read_only': True}],
            'healthcheck': {'test': ['CMD', 'python', '-c',
                "import socket; socket.create_connection(('127.0.0.1',8080),2).close()"],
                'interval': '1s', 'timeout': '3s', 'retries': 15},
        }
        compose.write_text(json.dumps({'services': services}))
        yield compose, 'http://model-relay:8080' + parsed.path.rstrip('/')
