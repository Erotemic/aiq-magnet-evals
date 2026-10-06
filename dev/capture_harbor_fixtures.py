"""Capture unmodified native Phase 0 jobs for engine-free regression tests."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def capture(source: Path, destination: Path):
    if destination.exists():
        raise FileExistsError(f"refusing to replace existing fixture tree: {destination}")
    labels = ("oracle", "nop", "scripted", "no-network", "partial-failure",
              "cancellation", "replay-generation", "fresh-replay")
    jobs = {}
    for label in labels:
        pattern = "*/cancelled/result.json" if label == "cancellation" else "*/result.json"
        candidates = list((source / label).glob(pattern))
        if not candidates:
            raise FileNotFoundError(f"no native job for {label}: run dev/ci/harbor_phase0.sh")
        path = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        result = json.loads(path.read_text())
        cancelled = (
            label == "cancellation"
            and result.get("stats", {}).get("n_cancelled_trials") == result.get("n_total_trials")
            and result.get("stats", {}).get("n_pending_trials") == 0
            and result.get("stats", {}).get("n_running_trials") == 0
        )
        if not result.get("finished_at") and not cancelled:
            raise ValueError(f"native job is not terminal: {path}")
        jobs[label] = path.parent
    destination.mkdir(parents=True)
    for label, job in jobs.items():
        shutil.copytree(job, destination / label)
    manifest = {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(destination.rglob("*")) if path.is_file()}
    (destination / "capture.json").write_text(json.dumps({
        "harbor_version": "0.23.0",
        "harbor_revision": "1e5c5c6db929a10a140d05e606882c671ae20729",
        "pro_revision": "66f92766bba642462d4bbe5479e83f91f9211862",
        "source_jobs": {key: str(value) for key, value in jobs.items()},
        "sha256": manifest,
    }, indent=2, sort_keys=True) + "\n")


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        source = kwconf.Value(None, required=True)
        destination = kwconf.Value(None, required=True)

    args = Config.cli(argv=argv, strict=True, special_options=False)
    capture(Path(args.source), Path(args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
