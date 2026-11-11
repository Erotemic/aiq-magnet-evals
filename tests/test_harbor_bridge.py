"""Slow HTTP replies retain the native network restrictions and diagnostics."""
import asyncio
import contextlib
import json
from types import SimpleNamespace

from magnet_evals.backends.harbor import adapter, bridge

STOCK = '''services:
  - name: transparent-egress
    addr: ":12345"
    bypass: allowlist
    metadata: {so_mark: 114514}
    handler:
      type: red
      metadata: {sniffing: true, sniffing.timeout: 5s, sniffing.fallback: true}
    listener: {type: red}
bypasses:
  - name: allowlist
    whitelist: true
    reload: 1s
    file: {path: /opt/egress-sidecar/allowlist.txt}
'''


def test_timeout_override_preserves_native_network_policy():
    import yaml
    before = yaml.safe_load(STOCK)
    after = bridge.egress_response_config(STOCK, 3600)
    timeout = after['services'][0]['handler']['metadata'].pop('readTimeout')
    assert timeout == '3600s'
    assert after == before


def test_default_bridge_does_not_add_an_egress_sidecar_or_import_harbor(tmp_path, monkeypatch):
    @contextlib.contextmanager
    def relay(*args, **kwargs):
        assert kwargs['timeout'] == 600
        yield 12345
    monkeypatch.setattr(bridge, 'relay', relay)
    monkeypatch.setattr(bridge, 'files', lambda *args: (_ for _ in ()).throw(AssertionError('unexpected native import')))
    monkeypatch.setattr(bridge.subprocess, 'check_output', lambda *a, **kw: b'[{"Gateway":"172.17.0.1"}]')
    with bridge.endpoint_bridge(tmp_path, 'http://127.0.0.1:14042/v1') as (compose, url):
        services = json.loads(compose.read_text())['services']
        assert set(services) == {'model-relay'}
        assert url == 'http://model-relay:8080/v1'


def test_slow_response_bridge_mounts_config_read_only_and_aligns_both_hops(tmp_path, monkeypatch):
    source = tmp_path/'stock/harbor-docker-egress-control-sidecar/gost.yaml'
    source.parent.mkdir(parents=True)
    source.write_text(STOCK)
    @contextlib.contextmanager
    def relay(*args, **kwargs):
        assert kwargs['timeout'] == 3600
        yield 12345
    monkeypatch.setattr(bridge, 'relay', relay)
    monkeypatch.setattr(bridge, 'files', lambda *args: source.parent.parent)
    monkeypatch.setattr(bridge.subprocess, 'check_output', lambda *a, **kw: b'[{"Gateway":"172.17.0.1"}]')
    with bridge.endpoint_bridge(tmp_path/'bridge', 'http://127.0.0.1:14042/v1', egress_response_timeout=3600) as (compose, _):
        services = json.loads(compose.read_text())['services']
        mount, = services['harbor-docker-egress-control-sidecar']['volumes']
        assert mount['read_only'] is True
        assert mount['target'] == '/opt/egress-sidecar/gost.yaml'
        config = json.loads((tmp_path/'bridge/egress-response-timeout.json').read_text())
        assert config['services'][0]['handler']['metadata']['readTimeout'] == '3600s'
        assert 'timeout=3600' in services['model-relay']['command'][-1]
        assert 'ports' not in services['model-relay']


def test_native_job_exception_group_keeps_underlying_causes(tmp_path, monkeypatch):
    backend = adapter.HarborBackend()
    resolved = SimpleNamespace(identity=SimpleNamespace(digest='same'),
        request=SimpleNamespace(task='fixture', primary_model=SimpleNamespace(provider_options={})),
        native_config={'tasks': [], 'agents': [{}], 'environment': {}}, resolved_facts={})
    context = SimpleNamespace(output_dir=tmp_path, env={}, model_endpoints={})
    class Job:
        @classmethod
        async def create(cls, config):
            obj = cls()
            obj.config = config
            return obj
        def on_environment_started(self, callback):
            pass
        async def run(self):
            root = tmp_path/'native/harbor/evaluation'
            root.mkdir(parents=True)
            (root/'result.json').write_text('{}')
            raise ExceptionGroup('native setup failed', [OSError('disk write failed'), ValueError('bad config')])
    monkeypatch.setattr(adapter, '_runtime', lambda: (Job, SimpleNamespace(model_validate=lambda v: v), None, None))
    monkeypatch.setattr(backend, 'resolve', lambda request: resolved)
    monkeypatch.setattr(adapter, 'normalize_harbor_job', lambda *args, **kwargs: kwargs)
    result = asyncio.run(backend.execute_job(resolved, context))
    assert result['forced_status'] == 'failed'
    assert 'disk write failed' in result['failure'] and 'bad config' in result['failure']
    assert (tmp_path/'native/harbor/evaluation/exception.txt').read_text().strip() == result['failure']
