"""Failed native preflights must retain their diagnostics for remote review."""
from types import SimpleNamespace

from tests.native import test_swebench_verified as native


def test_failed_attempt_is_captured_on_fixture_teardown(tmp_path, monkeypatch):
    source = tmp_path / 'attempt'
    source.mkdir()
    destination = tmp_path / 'captured'
    monkeypatch.setenv('AIQ_VERIFIED_CAPTURE_DIR', str(destination))
    request = SimpleNamespace(node=SimpleNamespace(callspec=SimpleNamespace(params={'solver': 'oracle'})))
    fixture = native.capture_native_attempt.__wrapped__(source, request)
    next(fixture)
    # Simulate the expensive native run writing evidence before an assertion fails.
    (source / 'diagnostic.txt').write_text('gold patch failed a test')
    fixture.close()
    assert (destination / 'oracle/attempt/diagnostic.txt').read_text() == 'gold patch failed a test'


def test_unrequested_capture_does_not_copy(tmp_path, monkeypatch):
    monkeypatch.delenv('AIQ_VERIFIED_CAPTURE_DIR', raising=False)
    fixture = native.capture_native_attempt.__wrapped__(tmp_path, None)
    next(fixture)
    fixture.close()
