"""Attempt-owned endpoint bridge preserving Harbor's native egress sidecar."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from magnet_evals.backends.harbor.relay import relay
from magnet_evals.errors import RequestValidationError

RELAY_IMAGE = 'python:3.12-alpine@sha256:4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111'


@contextlib.contextmanager
def endpoint_bridge(directory: Path, upstream: str):
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
    with relay(origin, gateway) as port:
        startup = (
            'from relay import relay; import threading; '
            f"bridge=relay('http://{gateway}:{port}', '0.0.0.0', 8080); "
            'bridge.__enter__(); threading.Event().wait()'
        )
        compose = directory / 'endpoint-bridge.json'
        compose.write_text(json.dumps({'services': {'model-relay': {
            'image': RELAY_IMAGE, 'working_dir': '/aiq-relay',
            'command': ['python', '-c', startup], 'networks': ['default'],
            'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('relay.py').resolve()),
                         'target': '/aiq-relay/relay.py', 'read_only': True}],
            'healthcheck': {'test': ['CMD', 'python', '-c',
                "import socket; socket.create_connection(('127.0.0.1',8080),2).close()"],
                'interval': '1s', 'timeout': '3s', 'retries': 15},
        }}}))
        yield compose, 'http://model-relay:8080' + parsed.path.rstrip('/')
