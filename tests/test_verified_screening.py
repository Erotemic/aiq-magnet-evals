"""Frozen profile integrity and registry pinning without pulling image layers."""
import hashlib
import io
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from dev.pin_verified_screening_images import resolve_image

ENV = Path(__file__).parents[1] / 'dev/environments'


def test_screening_pins_preserve_smoke_and_exact_frozen_membership():
    selection = json.loads((ENV / 'swebench-verified-selection.json').read_text())
    smoke = json.loads((ENV / 'swebench-verified-images.json').read_text())
    screening = json.loads((ENV / 'swebench-verified-screening-images.json').read_text())
    assert list(screening) == selection['screening']
    assert len(screening) == len(set(selection['screening'])) == 25
    assert len(selection['smoke']) == 5
    assert {k: screening[k] for k in smoke} == smoke
    assert all(re.fullmatch(r'swebench/sweb\.eval\.x86_64\..+@sha256:[0-9a-f]{64}', image)
               for image in screening.values())
    # Pins are preparation evidence, not new native runtime acceptance.
    assert selection['runtime_verified_ids'] == selection['screening']


def response(value, *, bad_digest=False):
    content = json.dumps(value).encode()
    result = io.BytesIO(content)
    result.headers = {'Docker-Content-Digest':
        'sha256:' + ('0' * 64 if bad_digest else hashlib.sha256(content).hexdigest())}
    return result


def test_registry_pinner_selects_amd64_and_verifies_manifest_bytes():
    image = {'config': {'digest': 'sha256:' + 'b' * 64},
             'layers': [{'digest': 'sha256:' + 'c' * 64, 'size': 123}]}
    digest = 'sha256:' + hashlib.sha256(json.dumps(image).encode()).hexdigest()
    index = {'manifests': [
        {'platform': {'os': 'linux', 'architecture': 'arm64'}, 'digest': 'not-selected'},
        {'platform': {'os': 'linux', 'architecture': 'amd64'}, 'digest': digest}]}
    with patch('dev.pin_verified_screening_images.urlopen', side_effect=[
            response({'token': 'fixture-token'}), response(index), response(image)]) as fetch:
        pin, observed = resolve_image('example__repo-123')
    assert pin == 'swebench/sweb.eval.x86_64.example_1776_repo-123@' + digest
    assert observed == image
    assert fetch.call_args.args[0].full_url.endswith('/manifests/' + digest)


def test_registry_pinner_refuses_corrupt_manifest():
    with patch('dev.pin_verified_screening_images.urlopen', side_effect=[
            response({'token': 'fixture-token'}), response({'layers': []}, bad_digest=True)]):
        with pytest.raises(ValueError, match='checksum mismatch'):
            resolve_image('example__repo-123')
