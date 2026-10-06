"""Capture unmodified successful generation/replay bundles for regression."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from magnet_evals.jsonutil import sha256_file
from magnet_evals.outputs import load_run


def capture(source: Path, destination: Path, labels=('oracle', 'nop', 'locked-mini-synthetic')):
    if destination.exists():
        raise FileExistsError(f'refusing to replace fixture tree: {destination}')
    selected = {}
    for label in labels:
        if label not in {'oracle', 'nop', 'locked-mini-synthetic', 'locked-mini-pro-scripted-gold'}:
            raise ValueError(f'unknown native capture label: {label}')
        roots = list((source / label).glob('*/store'))
        if len(roots) != 1:
            raise ValueError(f'expected one {label} capture')
        paths = list((roots[0] / 'runs').glob('*/*/RUN_COMPLETE'))
        if not paths:
            paths = list((roots[0] / 'attempts').glob('**/RUN_COMPLETE'))
        if len(paths) != 1:
            raise ValueError(f'expected one completed {label} bundle')
        run = load_run(paths[0].parent)
        if not run.complete or any(s.native.get('authoritative_phase') != 'fresh-replay' for s in run.result.samples):
            raise ValueError(f'{label} is not a complete fresh-replay result')
        selected[label] = run.path
    destination.mkdir(parents=True)
    for label, path in selected.items():
        shutil.copytree(path, destination / label)
    (destination / 'capture.json').write_text(json.dumps({
        'schema': 'aiq-magnet-evals-pro-v2-native-capture/1',
        'source_runs': {key: str(value) for key, value in selected.items()},
        'sha256': {path.relative_to(destination).as_posix(): sha256_file(path)
                   for path in sorted(destination.rglob('*')) if path.is_file()},
    }, indent=2, sort_keys=True) + '\n')


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        source = kwconf.Value(None, required=True)
        destination = kwconf.Value(None, required=True)
        labels = kwconf.Value('oracle,nop,locked-mini-synthetic')

    args = Config.cli(argv=argv, strict=True, special_options=False)
    capture(Path(args.source), Path(args.destination), tuple(args.labels.split(',')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
