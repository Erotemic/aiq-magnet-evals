"""Frozen full membership and architecture-specific pin generation."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ENV = ROOT / 'dev/environments'


def test_full_pins_cover_all_500_and_preserve_the_accepted_subset():
    selection = json.loads((ENV / 'swebench-verified-full-selection.json').read_text())
    pins = json.loads((ENV / 'swebench-verified-full-images.json').read_text())
    subset = json.loads((ENV / 'swebench-verified-screening-images.json').read_text())
    assert len(pins) == len(set(selection['instance_ids'])) == 500
    assert list(pins) == selection['instance_ids']
    assert selection['instance_ids'][:25] == list(subset)
    assert {key: pins[key] for key in subset} == subset
    assert selection['dataset_revision'] == 'c104f840cc67f8b6eec6f759ebc8b2693d585d4a'
    assert all('@sha256:' in image and len(image.rsplit(':', 1)[-1]) == 64 for image in pins.values())


def test_pinner_selects_one_linux_amd64_child_manifest(monkeypatch):
    spec = importlib.util.spec_from_file_location('full_pinner', ROOT / 'dev/pin_verified_full_images.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = {'digest': 'sha256:' + 'a' * 64, 'images': [
        {'os': 'unknown', 'architecture': 'unknown', 'digest': 'sha256:' + 'b' * 64},
        {'os': 'linux', 'architecture': 'amd64', 'digest': 'sha256:' + 'c' * 64}]}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps(value)

    monkeypatch.setattr(module, 'urlopen', lambda *args, **kwargs: Response())
    pin, metadata = module.resolve_image('example__repo-1')
    assert pin == 'swebench/sweb.eval.x86_64.example_1776_repo-1@sha256:' + 'c' * 64
    assert metadata['platform']['architecture'] == 'amd64'
    value['images'].append(dict(value['images'][1]))
    with pytest.raises(ValueError, match='one linux/amd64'):
        module.resolve_image('example__repo-1')
