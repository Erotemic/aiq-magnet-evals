"""Pinned Harbor Phase 0 probes. Native imports only occur in its worker."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

TASKS = Path(__file__).parent / "harbor_tasks"


async def run_job(jobs_dir: Path, name: str, *, agent="oracle", tasks=None, **options):
    from harbor.job import Job
    from harbor.models.job.config import JobConfig

    if isinstance(agent, str) and agent.startswith("python:"):
        agent = {"import_path": agent.removeprefix("python:")}
    config = JobConfig.model_validate({
        "job_name": name,
        "jobs_dir": str(jobs_dir),
        "n_concurrent_trials": 1,
        "n_attempts": 1,
        "retry": {"max_retries": 0},
        "quiet": True,
        "agents": [agent if isinstance(agent, dict) else {"name": agent}],
        "tasks": [{"path": str(path)} for path in (tasks or [TASKS / "division"])],
        **options,
    })
    job = await Job.create(config)
    await job.run()
    return job.job_dir


def trial_results(job_dir: Path):
    return [json.loads(path.read_text()) for path in sorted(job_dir.glob("*/result.json"))]


def main(argv=True):
    import kwconf

    class Config(kwconf.Config):
        jobs_dir = kwconf.Value(None, required=True, help="Native artifacts destination")
        agent = kwconf.Value("oracle", help="Built-in Harbor agent")
        name = kwconf.Value("division-oracle", help="Unique native job name")

    args = Config.cli(argv=argv, strict=True, special_options=False)
    job_dir = asyncio.run(run_job(Path(args.jobs_dir), args.name, agent=args.agent))
    for result in trial_results(job_dir):
        print(json.dumps({key: result.get(key) for key in (
            "task_name", "exception_info", "verifier_result")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
