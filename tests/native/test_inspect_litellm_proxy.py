"""Pinned native Inspect ReAct, metadata lookup and context termination over HTTP."""
import sys

import pytest

pytest.importorskip('inspect_ai')

from magnet_evals import (
    EvaluationRequest,
    ExecutionContext,
    ModelBinding,
    run_evaluation,
)
from tests.native.litellm_proxy_server import proxy_server


@pytest.mark.parametrize('overflow', [False, True])
def test_proxy_tool_loop_reaches_scoring_on_context_stop(tmp_path, overflow):
    request = EvaluationRequest(
        engine='inspect_ai', task='python:tests.native.inspect_fixture:proxy_context_task',
        data_revision='fixture-v1', models=(ModelBinding(role='primary', model='local-context',
            provider='litellm-proxy', revision='fixture-v1',
            provider_options={'responses_api': False, 'stream': False}),),
        generation={'reasoning_effort': 'high', 'max_tokens': 512},
        engine_options={'required_secrets': ['LITELLM_PROXY_API_KEY']},
    )
    with proxy_server(overflow=overflow) as (url, calls):
        bundle = run_evaluation(request, ExecutionContext(output_dir=tmp_path / 'run',
            worker_python=sys.executable, timeout_seconds=60,
            env={'LITELLM_PROXY_API_KEY': 'local-proxy-fixture-key'},
            model_endpoints={'primary': url}))
    assert bundle.result.status == 'succeeded', bundle.result.diagnostics
    assert bundle.result.records[0].coverage.status == 'complete'
    assert bundle.result.records[0].metrics[0].value == (0 if overflow else 1)
    samples = [s for s in bundle.result.samples if s.native.get('kind') == 'sample']
    assert len(samples) == 1 and samples[0].native.get('error') is None
    assert any(m['role'] == 'tool' and m['content'] == '4'
               for m in samples[0].trajectory['messages'])
    assert any(c.get('path', '').endswith('/model/info') for c in calls)
    posts = [c for c in calls if c['method'] == 'POST']
    assert len(posts) == 2 and all(c['reasoning_effort'] == 'high' for c in posts)
    if overflow:
        assert any(e.get('event') == 'model' and any(
            choice.get('stop_reason') == 'model_length'
            for choice in (e.get('output') or {}).get('choices', []))
            for e in samples[0].trajectory['events'])
