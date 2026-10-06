from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import kwconf

from magnet_evals._version import __version__
from magnet_evals.backends.registry import registrations
from magnet_evals.contracts import EvaluationRequest, ExecutionContext
from magnet_evals.engines import ENGINE_SPECS
from magnet_evals.ensure import ensure_evaluation
from magnet_evals.outputs import load_run
from magnet_evals.phase1 import PHASE1_TASKS
from magnet_evals.probes.api_surface import probe_all_api_surfaces
from magnet_evals.probes.environment import host_facts, probe_all_engine_imports
from magnet_evals.probes.model import ProbeReport
from magnet_evals.probes.source import inspect_checkout
from magnet_evals.runner import (
    import_evaluation,
    resolve_evaluation,
    resolve_evaluation_async,
    run_evaluation,
    validate_request,
)


def _load_request(path: Path) -> EvaluationRequest:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f'request must be a JSON object: {path}')
    return EvaluationRequest.from_dict(data)


def _parse_checkouts(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if '=' not in item:
            raise SystemExit(f'--checkout expects ENGINE=PATH, got {item!r}')
        engine, path = item.split('=', 1)
        if engine not in ENGINE_SPECS:
            known = ', '.join(sorted(ENGINE_SPECS))
            raise SystemExit(f'unknown engine {engine!r}; expected one of: {known}')
        parsed[engine] = path
    return parsed


def _phase1_status(as_json: bool) -> int:
    rows = [task.__dict__ for task in PHASE1_TASKS]
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for task in PHASE1_TASKS:
            print(f'{task.id:6} {task.status:7} {task.title}')
            print(f'       {task.note}')
    return 0


def _engines(as_json: bool) -> int:
    rows = {key: spec.__dict__ for key, spec in ENGINE_SPECS.items()}
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for key in sorted(ENGINE_SPECS):
            spec = ENGINE_SPECS[key]
            print(f'{key}: {spec.repository}')
            print(f'  pin_state={spec.pin_state} candidate_revision={spec.candidate_revision!r}')
            print(f'  candidate_version={spec.candidate_version!r}')
            print(f'  python_hint={spec.python_requirement_hint!r}')
    return 0


def _backends(as_json: bool) -> int:
    rows = {key: registration.__dict__ for key, registration in registrations().items()}
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for key, row in sorted(rows.items()):
            print(f'{key}: {row["module"]}:{row["factory"]} experimental={row["experimental"]}')
    return 0


def _phase1_probe(args) -> int:
    records = probe_all_engine_imports()
    records.extend(probe_all_api_surfaces())
    for engine, path in _parse_checkouts(list(args.checkout or [])).items():
        records.extend(inspect_checkout(engine, path))
    report = ProbeReport(
        schema_version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        host=host_facts(),
        records=records,
    )
    if args.output:
        path = report.write_json(Path(args.output))
        print(path)
    else:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


def _validate(path: Path) -> int:
    request = _load_request(path)
    validate_request(request)
    print(json.dumps({'valid': True, 'engine': request.engine}, sort_keys=True))
    return 0


def _resolve(path: Path, output: Path | None, worker_python: str | None = None) -> int:
    request = _load_request(path)
    if worker_python:
        context = ExecutionContext(output_dir=Path.cwd(), worker_python=worker_python)
        resolved = asyncio.run(resolve_evaluation_async(request, context))
    else:
        resolved = resolve_evaluation(request)
    text = json.dumps(resolved.to_dict(), indent=2, sort_keys=True) + '\n'
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        print(output)
    else:
        print(text, end='')
    return 0


def _ensure(args) -> int:
    outcome = ensure_evaluation(
        _load_request(Path(args.request)),
        args.store,
        worker_python=args.worker_python,
        timeout_seconds=args.timeout,
        import_source=args.import_source,
        allow_external_symlinks=args.allow_external_symlinks,
    )
    payload = {
        'action': outcome.action,
        'path': str(outcome.run.path),
        'status': outcome.run.result.status,
        'measurement_identity': outcome.resolved.identity.to_dict(),
        'reuse_reason': outcome.reuse_reason,
        'import_identity': outcome.import_identity,
        'waited': outcome.waited,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if outcome.run.result.status == 'succeeded' else 2


def _run(args) -> int:
    request = _load_request(Path(args.request))
    context = ExecutionContext(
        output_dir=Path(args.output),
        worker_python=args.worker_python,
        timeout_seconds=args.timeout,
    )
    bundle = run_evaluation(request, context)
    print(bundle.path)
    return 0 if bundle.result.status == 'succeeded' else 2


def _import_native(args) -> int:
    request = _load_request(Path(args.request))
    context = ExecutionContext(output_dir=Path(args.output), worker_python=args.worker_python)
    bundle = import_evaluation(
        request, args.source, context, allow_external_symlinks=args.allow_external_symlinks
    )
    print(bundle.path)
    return 0 if bundle.result.status == 'succeeded' else 2


def _show(args) -> int:
    bundle = load_run(args.run_dir, verify_checksums=not args.no_verify)
    payload = {
        'path': str(bundle.path),
        'complete': bundle.complete,
        'engine': bundle.result.engine,
        'status': bundle.result.status,
        'measurement_identity': bundle.resolved.identity.to_dict(),
        'records': [record.to_dict() for record in bundle.result.records],
        'sample_count': len(bundle.result.samples),
        'manifest': dict(bundle.manifest),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cli_args(cls, argv, kwargs):
    return cls.cli(argv=argv, data=kwargs, strict=True, special_options=False)


class Phase1StatusCLI(kwconf.Config):
    """Show the refined phase-1 checklist."""

    emit_json = kwconf.Value(False, isflag=True, alias=['json'], help='Emit JSON instead of text.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _phase1_status(_cli_args(cls, argv, kwargs).emit_json)


class Phase1ProbeCLI(kwconf.Config):
    """Capture local package/source facts without executing native evaluations."""

    checkout = kwconf.Value(
        [], nargs='*', parser=str,
        help='Upstream checkouts to inspect, as ENGINE=PATH (several may follow one --checkout).',
    )
    output = kwconf.Value(None, parser=str, help='Write a JSON probe report here.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _phase1_probe(_cli_args(cls, argv, kwargs))


class EnginesCLI(kwconf.Config):
    """Show phase-1 engine research metadata."""

    emit_json = kwconf.Value(False, isflag=True, alias=['json'], help='Emit JSON instead of text.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _engines(_cli_args(cls, argv, kwargs).emit_json)


class BackendsCLI(kwconf.Config):
    """Show implemented lazy backend adapters."""

    emit_json = kwconf.Value(False, isflag=True, alias=['json'], help='Emit JSON instead of text.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _backends(_cli_args(cls, argv, kwargs).emit_json)


class ValidateCLI(kwconf.Config):
    """Statically validate a request without importing the native engine."""

    request = kwconf.Value(None, position=1, required=True, parser=str, help='Request JSON file.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _validate(Path(_cli_args(cls, argv, kwargs).request))


class ResolveCLI(kwconf.Config):
    """Resolve a request in the native engine environment and print its identity."""

    request = kwconf.Value(None, position=1, required=True, parser=str, help='Request JSON file.')
    output = kwconf.Value(None, parser=str, help='Write the resolved request here.')
    worker_python = kwconf.Value(None, parser=str, help='Resolve inside this engine interpreter.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        args = _cli_args(cls, argv, kwargs)
        output = None if args.output is None else Path(args.output)
        return _resolve(Path(args.request), output, args.worker_python)


class EnsureCLI(kwconf.Config):
    """Reuse a validated stored result, or import/execute and publish one."""

    request = kwconf.Value(None, position=1, required=True, parser=str, help='Request JSON file.')
    store = kwconf.Value(None, required=True, parser=str, help='Result store directory.')
    worker_python = kwconf.Value(None, parser=str, help='Engine worker interpreter.')
    timeout = kwconf.Value(None, type=float, help='Execution timeout in seconds.')
    import_source = kwconf.Value(None, parser=str, help='Import these native artifacts instead of executing.')
    allow_external_symlinks = kwconf.Value(
        False, isflag=True, help='Follow symlinks leaving the import source (trusted sources only).',
    )

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _ensure(_cli_args(cls, argv, kwargs))


class RunCLI(kwconf.Config):
    """Execute a request and atomically publish a run bundle."""

    request = kwconf.Value(None, position=1, required=True, parser=str, help='Request JSON file.')
    output = kwconf.Value(None, required=True, parser=str, help='Run bundle directory to publish.')
    worker_python = kwconf.Value(None, parser=str, help='Engine worker interpreter.')
    timeout = kwconf.Value(None, type=float, help='Execution timeout in seconds.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _run(_cli_args(cls, argv, kwargs))


class ImportNativeCLI(kwconf.Config):
    """Import native engine artifacts into an engine-free run bundle."""

    request = kwconf.Value(None, position=1, required=True, parser=str, help='Request JSON file.')
    source = kwconf.Value(None, position=2, required=True, parser=str, help='Native artifacts to import.')
    output = kwconf.Value(None, required=True, parser=str, help='Run bundle directory to publish.')
    worker_python = kwconf.Value(
        None, parser=str, help='Resolve and read native artifacts in this engine interpreter.',
    )
    allow_external_symlinks = kwconf.Value(
        False, isflag=True, help='Follow symlinks leaving the import source (trusted sources only).',
    )

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _import_native(_cli_args(cls, argv, kwargs))


class ShowCLI(kwconf.Config):
    """Inspect a published run without engine dependencies."""

    run_dir = kwconf.Value(None, position=1, required=True, parser=str, help='Run bundle directory.')
    no_verify = kwconf.Value(False, isflag=True, help='Skip checksum verification.')

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        return _show(_cli_args(cls, argv, kwargs))


class AiqMagnetEvalsCLI(kwconf.ModalCLI):
    """Backend-agnostic evaluation runtime and artifact tooling."""

    __prog__ = 'aiq-magnet-evals'
    __version__ = __version__


class ExportPredictionsCLI(kwconf.Config):
    """Export captured Inspect patches into official SWE-bench JSONL."""
    run_dir = kwconf.Value(None, position=1, required=True, parser=str)
    output = kwconf.Value(None, required=True, parser=str)

    @classmethod
    def main(cls, argv=True, **kwargs) -> int:
        from magnet_evals.benchmarks.swe_bench_verified import export_predictions
        args = _cli_args(cls, argv, kwargs)
        print(export_predictions(args.run_dir, args.output))
        return 0


class SWEBenchCLI(kwconf.ModalCLI):
    """SWE-bench benchmark protocols and retained patch tooling."""


SWEBenchCLI.register(ExportPredictionsCLI, command='export-predictions')


for _command, _cli in (
    ('phase1-status', Phase1StatusCLI),
    ('phase1-probe', Phase1ProbeCLI),
    ('engines', EnginesCLI),
    ('backends', BackendsCLI),
    ('validate', ValidateCLI),
    ('resolve', ResolveCLI),
    ('ensure', EnsureCLI),
    ('run', RunCLI),
    ('import-native', ImportNativeCLI),
    ('show', ShowCLI),
    ('swebench', SWEBenchCLI),
):
    AiqMagnetEvalsCLI.register(_cli, command=_command)


def main(argv: list[str] | None = None) -> int:
    """Console entry point (``aiq-magnet-evals``); returns the exit status."""
    return AiqMagnetEvalsCLI.main(argv=argv)
