"""Regenerate engine-free regression inputs/goldens from committed native fixtures.

Run from the repository root:

* OLMo and HELM goldens need no engine:
  ``python dev/regenerate_native_regressions.py olmo helm``.
* Harbor and paired Pro V2 goldens need no engine:
  ``python dev/regenerate_native_regressions.py harbor pro``.
* Inspect needs the pinned runtime, because ``.eval`` entries are zstd-compressed:
  ``/tmp/aiq-inspect-p1/bin/python dev/regenerate_native_regressions.py inspect``.
  This writes each ``.eval`` fixture through Inspect's own JSON log writer to
  ``tests/fixtures/inspect-native/json/`` and records the summary normalized
  from the *native* ``EvalLog`` objects. The dependency-free tests normalize
  the JSON dicts and must reproduce those summaries.

Review any golden diff: a change means normalization semantics changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from magnet_evals.contracts import MeasurementIdentity  # noqa: E402
from tests.regression.summary import summarize  # noqa: E402

IDENTITY = MeasurementIdentity(algorithm='regression', digest='0' * 64, reusable=False)
INSPECT_ROOT = REPO / 'tests' / 'fixtures' / 'inspect-native'
OLMO_ROOT = REPO / 'tests' / 'fixtures' / 'olmo-native'
HELM_ROOT = REPO / 'tests' / 'fixtures' / 'helm-native'
HARBOR_ROOT = REPO / 'tests' / 'fixtures' / 'harbor-native'
PRO_ROOT = REPO / 'tests' / 'fixtures' / 'swebench-pro-native'
PRO_AGENT_ROOT = REPO / 'tests' / 'fixtures' / 'swebench-pro-agent-native'

# fixture directory -> native tasks the originating request resolved to
OLMO_FIXTURES = {
    'generation': ['aiq_p1_local'],
    'tool': ['aiq_p1_tool'],
    'failure': ['aiq_p1_tool'],
    'multi': ['aiq_p1_local', 'aiq_p1_local_alt'],
}


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def regenerate_inspect() -> None:
    from inspect_ai.log import read_eval_log, write_eval_log

    from magnet_evals.backends.inspect_ai.normalize import normalize_inspect_logs

    out = INSPECT_ROOT / 'json'
    out.mkdir(exist_ok=True)
    goldens = {}
    for source in sorted(INSPECT_ROOT.rglob('*.eval')):
        name = source.relative_to(INSPECT_ROOT).with_suffix('').as_posix().replace('/', '__')
        log = read_eval_log(str(source))
        write_eval_log(log, str(out / f'{name}.json'), format='json')
        result = normalize_inspect_logs([log], identity=IDENTITY, fallback_task=name)
        goldens[name] = summarize(result)
    _write(INSPECT_ROOT / 'expected-normalized.json', goldens)


def regenerate_olmo() -> None:
    from tests.regression.olmo import import_fixture

    goldens = {key: summarize(import_fixture(key, tasks)) for key, tasks in OLMO_FIXTURES.items()}
    _write(OLMO_ROOT / 'expected-normalized.json', goldens)


def regenerate_helm() -> None:
    from magnet_evals.backends.helm.normalize import normalize_helm_runs

    goldens = {
        path.name: summarize(normalize_helm_runs([path], identity=IDENTITY))
        for path in sorted(HELM_ROOT.iterdir())
        if (path / 'run_spec.json').is_file()
    }
    _write(HELM_ROOT / 'expected-normalized.json', goldens)


def regenerate_harbor() -> None:
    from magnet_evals.backends.harbor.normalize import normalize_harbor_job

    goldens = {path.name: summarize(normalize_harbor_job(path, identity=IDENTITY, fallback_task=path.name))
               for path in sorted(HARBOR_ROOT.iterdir()) if (path / 'result.json').is_file()}
    _write(HARBOR_ROOT / 'expected-normalized.json', goldens)


def regenerate_pro() -> None:
    from magnet_evals.benchmarks.swe_bench_pro import normalize_pro_jobs
    from magnet_evals.outputs import load_run

    goldens = {}
    for root in (PRO_ROOT, PRO_AGENT_ROOT):
        goldens = {}
        for source in sorted(root.iterdir()):
            if not (source / 'run_manifest.json').is_file():
                continue
            run = load_run(source)
            result = normalize_pro_jobs(source / 'native/harbor', identity=IDENTITY,
                fallback_task='pro-v2/fixture', synthetic=source.name == 'locked-mini-synthetic')
            goldens[source.name] = summarize(result)
            assert [s.scores for s in result.samples] == [s.scores for s in run.result.samples]
        _write(root / 'expected-normalized.json', goldens)


if __name__ == '__main__':
    targets = sys.argv[1:] or ['olmo']
    for target in targets:
        {'pro': regenerate_pro, 'harbor': regenerate_harbor, 'inspect': regenerate_inspect, 'olmo': regenerate_olmo, 'helm': regenerate_helm}[target]()
