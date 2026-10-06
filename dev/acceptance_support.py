"""Source fingerprint for carrying VM acceptance to a separate GPU host."""
import hashlib
import json
from pathlib import Path


def source_digest(root: Path, includes=('magnet_evals', 'dev', 'tests', 'pyproject.toml')):
    entries = []
    for name in includes:
        base = root / name
        paths = base.rglob('*') if base.is_dir() else [base]
        for path in sorted(paths):
            relative = path.relative_to(root)
            if 'fixtures' in relative.parts or '__pycache__' in relative.parts or path.suffix == '.pyc':
                continue
            if path.is_file():
                entries.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(sorted(entries), separators=(',', ':')).encode()).hexdigest()
