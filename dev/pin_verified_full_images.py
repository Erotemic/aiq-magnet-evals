"""Checkpoint digest resolution for every member of the frozen Verified dataset."""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
from pathlib import Path
from urllib.request import urlopen


def resolve_image(instance):
    match = re.fullmatch(r'(.+?)__(.+)-(\d+)', instance)
    if not match:
        raise ValueError(f'Invalid instance: {instance}')
    org, repo, issue = match.groups()
    name = f'sweb.eval.x86_64.{org}_1776_{repo}-{issue}'
    url = f'https://hub.docker.com/v2/repositories/swebench/{name}/tags/latest'
    with urlopen(url, timeout=60) as response:
        value = json.load(response)
    platforms = [item for item in value['images']
                 if item.get('architecture') == 'amd64' and item.get('os') == 'linux']
    if len(platforms) != 1 or not re.fullmatch(r'sha256:[a-f0-9]{64}', platforms[0]['digest']):
        raise ValueError(f'Expected one linux/amd64 platform manifest: {name}')
    platform = platforms[0]
    return 'swebench/' + name + '@' + platform['digest'], {
        'resolution': 'Docker Hub tags API; content verified by digest pull at runtime',
        'url': url, 'platform': platform, 'tag_digest': value.get('digest')}



def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(value, indent=2) + '\n')
    pending.replace(path)


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        output = kwconf.Value('dev/environments/swebench-verified-full-images.json')
        report = kwconf.Value(None, required=True)
        workers = kwconf.Value(2)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    root = Path(__file__).resolve().parents[1]
    selection = json.loads((root / 'dev/environments/swebench-verified-full-selection.json').read_text())
    ids = selection['instance_ids']
    path, report_path = Path(args.output), Path(args.report)
    images = json.loads(path.read_text()) if path.exists() else {}
    known = json.loads((root / 'dev/environments/swebench-verified-screening-images.json').read_text())
    for instance, image in known.items():
        if instance in images and images[instance] != image:
            raise ValueError(f'Existing screening pin changed: {instance}')
        images[instance] = image
    if not set(images) <= set(ids):
        raise ValueError('Pin checkpoint has unknown instances')
    report = json.loads(report_path.read_text()) if report_path.exists() else {'manifests': {}}
    errors = {}

    def resolve(instance):
        for attempt in range(4):
            try:
                return resolve_image(instance)
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))

    with concurrent.futures.ThreadPoolExecutor(max_workers=int(args.workers)) as pool:
        futures = {pool.submit(resolve, instance): instance for instance in ids if instance not in images}
        for future in concurrent.futures.as_completed(futures):
            instance = futures[future]
            try:
                images[instance], report['manifests'][instance] = future.result()
            except Exception as error:
                errors[instance] = str(error)
            save(path, {instance: images[instance] for instance in ids if instance in images})
            report['errors'] = errors
            save(report_path, report)
            if len(images) % 25 == 0 or errors:
                print(f'Pinned {len(images)}/500; errors={len(errors)}', flush=True)
    if set(images) != set(ids):
        raise RuntimeError(f'Unresolved images remain: {errors}; rerun to resume the checkpoint')
    layers = {layer['digest']: layer['size'] for value in report['manifests'].values()
              for layer in value.get('layers', [])}
    report['unique_compressed_bytes'] = sum(layers.values())
    save(report_path, report)
    print('All 500 linux/amd64 pins frozen. Digest pulls verify content on the host.')


if __name__ == '__main__':
    main()
