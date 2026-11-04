"""Resolve the frozen screening images without downloading their layers."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ACCEPT = ', '.join((
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
))


def resolve_image(instance):
    match = re.fullmatch(r'(.+?)__(.+)-(\d+)', instance)
    if not match:
        raise ValueError(f'invalid instance: {instance}')
    org, repo, issue = match.groups()
    repository = f'swebench/sweb.eval.x86_64.{org}_1776_{repo}-{issue}'
    query = urlencode({'service': 'registry.docker.io', 'scope': f'repository:{repository}:pull'})
    with urlopen('https://auth.docker.io/token?' + query, timeout=60) as response:
        token = json.load(response)['token']

    def manifest(reference):
        request = Request(f'https://registry-1.docker.io/v2/{repository}/manifests/{reference}',
            headers={'Authorization': 'Bearer ' + token, 'Accept': ACCEPT})
        with urlopen(request, timeout=60) as response:
            content = response.read()
            digest = 'sha256:' + hashlib.sha256(content).hexdigest()
            if response.headers.get('Docker-Content-Digest') != digest:
                raise ValueError(f'registry manifest checksum mismatch: {repository}')
            if reference.startswith('sha256:') and reference != digest:
                raise ValueError(f'registry returned a different manifest: {repository}')
            return digest, json.loads(content)

    digest, value = manifest('latest')
    if 'manifests' in value:
        platforms = [m for m in value['manifests']
                     if m.get('platform', {}).get('architecture') == 'amd64'
                     and m.get('platform', {}).get('os') == 'linux']
        if len(platforms) != 1:
            raise ValueError(f'expected one linux/amd64 image: {repository}')
        digest, value = manifest(platforms[0]['digest'])
    if not value.get('layers') or not value.get('config'):
        raise ValueError(f'expected an image manifest: {repository}')
    return repository + '@' + digest, value


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        output = kwconf.Value('dev/environments/swebench-verified-screening-images.json')
        report = kwconf.Value(None, help='Optional registry metadata JSON path')

    args = Config.cli(argv=argv, strict=True, special_options=False)
    root = Path(__file__).resolve().parents[1]
    selection = json.loads((root / 'dev/environments/swebench-verified-selection.json').read_text())
    existing = json.loads((root / 'dev/environments/swebench-verified-images.json').read_text())
    images, metadata = {}, {}
    for instance in selection['screening']:
        if instance in existing:
            images[instance] = existing[instance]
        else:
            images[instance], metadata[instance] = resolve_image(instance)
        print(instance + ': ' + images[instance], flush=True)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(images, indent=2) + '\n')
    if args.report:
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(metadata, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
