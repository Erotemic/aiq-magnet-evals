"""Preserve completed native Verified bundles and fresh official grader outputs."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from magnet_evals.jsonutil import sha256_file
from magnet_evals.outputs import load_run


def capture(source: Path, destination: Path):
    if destination.exists():
        raise FileExistsError(f'refusing to replace fixture tree: {destination}')
    sources = {}
    for solver in ('oracle', 'nop'):
        candidates = list((source / solver).glob('*/official/protocol.json'))
        if len(candidates) != 1:
            raise ValueError(f'expected one {solver} capture, found {len(candidates)}')
        root = candidates[0].parents[1]
        bundles = list((root / 'store/runs').glob('*/*/RUN_COMPLETE'))
        if len(bundles) != 1 or not load_run(bundles[0].parent).complete:
            raise ValueError(f'expected one completed {solver} native bundle')
        sources[solver] = (root, bundles[0].parent)
    destination.mkdir(parents=True)
    for solver, (root, bundle) in sources.items():
        target = destination / solver
        target.mkdir()
        shutil.copytree(bundle, target / 'run')
        shutil.copytree(root / 'official', target / 'official')
        for name in ('dataset.json', 'predictions.jsonl', 'predictions.jsonl.provenance.json'):
            shutil.copy2(root / name, target / name)
    (destination / 'capture.json').write_text(json.dumps({
        'schema': 'aiq-magnet-evals-verified-native-capture/1',
        'source_runs': {key: str(value[1]) for key, value in sources.items()},
        'sha256': {p.relative_to(destination).as_posix(): sha256_file(p)
                   for p in sorted(destination.rglob('*')) if p.is_file()},
    }, indent=2, sort_keys=True) + '\n')


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        source = kwconf.Value(None, required=True)
        destination = kwconf.Value(None, required=True)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    capture(Path(args.source), Path(args.destination))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
