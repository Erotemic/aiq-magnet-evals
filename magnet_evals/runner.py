"""Shared resolve/execute/import facades."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from magnet_evals import errors as errors_module
from magnet_evals.artifacts import (
    RunBundle,
    copy_native_tree,
    native_source_identity,
    publish_run,
)
from magnet_evals.backends.registry import get_backend
from magnet_evals.contracts import (
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
    as_execution_status,
)
from magnet_evals.errors import (
    ActiveEventLoopError,
    ExecutionError,
    RequestValidationError,
)
from magnet_evals.jsonutil import (
    MIN_REDACTED_VALUE_LENGTH,
    redact_values,
    required_secret_names,
)


def validate_request(request: EvaluationRequest) -> None:
    """Perform engine-specific static validation without importing the engine."""
    get_backend(request.engine).validate_request(request)


def resolve_evaluation(request: EvaluationRequest) -> ResolvedEvaluation:
    """Resolve native configuration and measurement identity in the engine runtime."""
    backend = get_backend(request.engine)
    backend.validate_request(request)
    return backend.resolve(request)


# Seconds a worker gets after SIGINT to run native cleanup (sandbox teardown,
# cancelled logs) before escalation to SIGTERM and then SIGKILL.
CANCEL_GRACE_SECONDS = 15.0
_TERM_GRACE_SECONDS = 5.0


async def _terminate_process_tree(
    process: asyncio.subprocess.Process,
    *,
    grace_seconds: float = CANCEL_GRACE_SECONDS,
) -> None:
    """Interrupt, then terminate, then kill the worker's process group.

    SIGINT first gives the engine its own interruption path (Inspect handles it
    and runs sandbox cleanup; OLMo's runner sees task cancellation through
    asyncio.run). Escalation keeps cancellation bounded if the engine hangs.
    """
    if process.returncode is not None:
        return
    if os.name != 'posix':
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERM_GRACE_SECONDS)
        except TimeoutError:
            process.kill()
            await process.wait()
        return
    for sig, wait in (
        (signal.SIGINT, grace_seconds),
        (signal.SIGTERM, _TERM_GRACE_SECONDS),
        (signal.SIGKILL, None),
    ):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            await asyncio.wait_for(process.wait(), timeout=wait)
            break
        except TimeoutError:
            continue
    # The leader may have exited while other group members linger.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


def _redact_file(path: Path, env: Any) -> None:
    if not path.is_file():
        return
    data = path.read_bytes()
    for key, value in dict(env).items():
        if value:
            data = data.replace(value.encode(), f'<redacted:{key}>'.encode())
    path.write_bytes(data)


def _worker_result_path(work_dir: Path) -> Path:
    return work_dir / '.aiq-evals-worker' / 'result.json'


_WORKER_PATH_CACHE: dict[tuple, str] = {}


#: Packages a worker imports from the caller: magnet_evals itself and its one
#: runtime dependency (kwconf, pure Python, no dependencies of its own).
WORKER_PACKAGES = ('magnet_evals', 'kwconf')


def _package_dir(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        raise errors_module.MissingDependencyError(f'{name!r} must be importable to start a worker')
    return Path(next(iter(spec.submodule_search_locations))).resolve()


def worker_package_path() -> str:
    """A directory that exposes exactly the packages a worker needs.

    Engine workers run in their own environments, which need not have
    ``magnet_evals`` installed. Putting the parent of this package on their
    path would also expose everything installed beside it: for a wheel that is
    the caller's whole ``site-packages``, which would shadow the engine's own
    dependencies (possibly built for another Python). Instead a private
    directory holds one symlink per package in :data:`WORKER_PACKAGES`. It
    goes on ``PYTHONPATH`` so engine-spawned children inherit it too.
    """
    packages = {name: _package_dir(name) for name in WORKER_PACKAGES}
    key = tuple(sorted((name, str(path)) for name, path in packages.items()))
    cached = _WORKER_PATH_CACHE.get(key)
    if cached is not None and all((Path(cached) / n).resolve() == p for n, p in packages.items()):
        return cached
    digest = hashlib.sha256(repr(key).encode()).hexdigest()[:16]
    cache_home = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    root = cache_home / 'magnet_evals' / 'worker-path' / digest
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, target in packages.items():
            link = root / name
            if not link.is_symlink() or link.resolve() != target:
                staged = root / f'.{name}.{os.getpid()}.{secrets.token_hex(4)}'
                staged.symlink_to(target, target_is_directory=True)
                os.replace(staged, link)  # atomic for concurrent workers
        if root.stat().st_uid != os.getuid():
            raise OSError('worker path directory is not ours')
    except OSError:
        # Unwritable cache: a private per-process directory.
        root = Path(tempfile.mkdtemp(prefix='magnet-evals-worker-path-'))
        for name, target in packages.items():
            (root / name).symlink_to(target, target_is_directory=True)
    _WORKER_PATH_CACHE[key] = str(root)
    return str(root)


def _worker_env(context: ExecutionContext) -> dict[str, str]:
    env = os.environ.copy()
    env.update(context.env)
    # The worker environment need not have magnet_evals installed; expose this
    # package, and nothing installed beside it, ahead of any existing path.
    package_path = worker_package_path()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = package_path if not old_pythonpath else package_path + os.pathsep + old_pythonpath
    return env


async def _run_worker(
    arguments: list[str],
    context: ExecutionContext,
    stdout_path: Path,
    stderr_path: Path,
    secrets: Mapping[str, str],
) -> int:
    """Run ``python -m magnet_evals.worker ...`` in its own process group.

    Output goes to files rather than pipes, so a worker that keeps writing
    during the cancellation grace period can never block on an unread pipe.
    Cancellation and timeout terminate the whole group (SIGINT first).
    """
    assert context.worker_python is not None
    try:
        with stdout_path.open('wb') as stdout_file, stderr_path.open('wb') as stderr_file:
            process = await asyncio.create_subprocess_exec(
                context.worker_python, '-m', 'magnet_evals.worker', *arguments,
                stdout=stdout_file,
                stderr=stderr_file,
                env=_worker_env(context),
                start_new_session=(os.name == 'posix'),
            )
            try:
                if context.timeout_seconds is None:
                    await process.wait()
                else:
                    await asyncio.wait_for(process.wait(), context.timeout_seconds)
            except (asyncio.CancelledError, TimeoutError):
                await _terminate_process_tree(process)
                raise
    finally:
        _redact_file(stdout_path, secrets)
        _redact_file(stderr_path, secrets)
    assert process.returncode is not None
    return process.returncode


async def _execute_in_worker(
    resolved: ResolvedEvaluation,
    context: ExecutionContext,
    work_dir: Path,
) -> EvaluationResult:
    protocol_dir = work_dir / '.aiq-evals-worker'
    protocol_dir.mkdir(parents=True, exist_ok=True)
    resolved_path = protocol_dir / 'resolved.json'
    result_path = _worker_result_path(work_dir)
    # Worker diagnostics must survive publication, especially when a native
    # runner fails after writing partial artifacts.
    worker_log_dir = work_dir / 'native' / 'aiq_worker'
    worker_log_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = worker_log_dir / 'stderr.log'
    resolved_path.write_text(json.dumps(resolved.to_dict(), indent=2, sort_keys=True) + '\n')
    returncode = await _run_worker(
        [
            'execute',
            '--resolved', str(resolved_path),
            '--output-dir', str(work_dir),
            '--result', str(result_path),
            '--model-endpoints', json.dumps(dict(context.model_endpoints)),
        ],
        context,
        worker_log_dir / 'stdout.log',
        stderr_path,
        effective_secrets(resolved.request, context),
    )
    if returncode != 0:
        detail = stderr_path.read_text(errors='replace')[-4000:]
        raise ExecutionError(f'evaluation worker exited with code {returncode}: {detail}')
    try:
        payload = json.loads(result_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as ex:
        raise ExecutionError('evaluation worker did not produce a valid result protocol file') from ex
    return EvaluationResult.from_dict(payload)


async def resolve_evaluation_async(
    request: EvaluationRequest,
    context: ExecutionContext | None = None,
    *,
    require_secrets: bool = True,
) -> ResolvedEvaluation:
    """Resolve in ``context.worker_python`` when given, else in this process.

    Resolution imports the native engine (and task/plugin code), so it belongs
    in the engine's worker environment (ADR-0002). Errors raised there keep
    their aiq-magnet-evals error type.

    ``require_secrets=False`` skips the declared-secret check. Resolution never
    needs a secret's value, and a scheduler may resolve before the credential
    exists (e.g. a key only a later endpoint lease provides); execution still
    checks.
    """
    if context is not None and require_secrets:
        # Before any task/plugin code runs, in-process or in the worker.
        check_required_secrets(request, context)
    if context is None or context.worker_python is None:
        return resolve_evaluation(request)
    validate_request(request)
    with tempfile.TemporaryDirectory(prefix='aiq-evals-resolve-') as scratch:
        scratch_dir = Path(scratch)
        request_path = scratch_dir / 'request.json'
        result_path = scratch_dir / 'resolved.json'
        request_path.write_text(json.dumps(request.to_dict(), sort_keys=True))
        stderr_path = scratch_dir / 'stderr.log'
        returncode = await _run_worker(
            ['resolve', '--request', str(request_path), '--result', str(result_path)],
            context,
            scratch_dir / 'stdout.log',
            stderr_path,
            effective_secrets(request, context),
        )
        try:
            payload = json.loads(result_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as ex:
            detail = stderr_path.read_text(errors='replace')[-4000:]
            raise ExecutionError(
                f'resolution worker exited with code {returncode} without a result: {detail}'
            ) from ex
    _raise_worker_error(payload)
    return ResolvedEvaluation.from_dict(payload['resolved'])


def _raise_worker_error(payload: Mapping[str, Any]) -> None:
    if 'error' not in payload:
        return
    error_cls = getattr(errors_module, str(payload['error'].get('type')), None)
    if not (isinstance(error_cls, type) and issubclass(error_cls, errors_module.AiqEvalsError)):
        error_cls = ExecutionError
    raise error_cls(str(payload['error'].get('message')))


def _cancelled_result(resolved: ResolvedEvaluation, work_dir: Path, detail: str) -> EvaluationResult:
    """Terminal cancelled result, keeping native facts a worker wrote while interrupted."""
    fallback = _terminal_error_result(resolved, status='cancelled', kind='cancelled', detail=detail)
    try:
        native = EvaluationResult.from_dict(json.loads(_worker_result_path(work_dir).read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return fallback
    diagnostics = dict(native.diagnostics)
    diagnostics.update(fallback.diagnostics)
    # Whatever the engine reported, this attempt was cancelled by its caller.
    diagnostics['worker_reported_status'] = native.status
    return EvaluationResult(
        engine=native.engine,
        identity=resolved.identity,
        status='cancelled',
        records=native.records,
        samples=native.samples,
        artifacts=native.artifacts,
        diagnostics=diagnostics,
    )


async def _execute_resolved(
    resolved: ResolvedEvaluation,
    context: ExecutionContext,
    work_dir: Path,
) -> EvaluationResult:
    backend = get_backend(resolved.request.engine)
    capabilities = dict(backend.capabilities())
    requires_worker = bool(capabilities.get('requires_worker_process'))
    if context.worker_python is not None or requires_worker:
        worker_context = ExecutionContext(
            output_dir=context.output_dir,
            env=context.env,
            worker_python=context.worker_python or sys.executable,
            timeout_seconds=context.timeout_seconds,
            model_endpoints=context.model_endpoints,
        )
        try:
            return await _execute_in_worker(resolved, worker_context, work_dir)
        except (asyncio.CancelledError, Exception):
            cleanup = getattr(backend, 'cleanup_worker_resources', None)
            if cleanup is not None:
                try:
                    await cleanup(work_dir)
                except Exception as exc:
                    # Preserve the original cancellation/failure and a separate
                    # cleanup diagnostic if the Docker daemon is unavailable.
                    path = work_dir / 'native/aiq_worker/cleanup-error.json'
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({'error': str(exc)}) + '\n')
            raise
    direct_context = ExecutionContext(
        output_dir=work_dir,
        env=context.env,
        worker_python=None,
        timeout_seconds=context.timeout_seconds,
        model_endpoints=context.model_endpoints,
    )
    if context.timeout_seconds is None:
        return await backend.execute(resolved, direct_context)
    # Same semantics as the worker path: on expiry the adapter task is
    # cancelled (running its cleanup) and TimeoutError becomes a failed run.
    return await asyncio.wait_for(backend.execute(resolved, direct_context), context.timeout_seconds)


def _redacted_exception_text(ex: BaseException, env: Mapping[str, str]) -> str:
    text = f'{type(ex).__name__}: {ex}'
    for key, value in dict(env).items():
        if value:
            text = text.replace(value, f'<redacted:{key}>')
    return text


def effective_secrets(request: EvaluationRequest, context: ExecutionContext) -> dict[str, str]:
    """Secret values to scrub: ``ExecutionContext.env`` plus declared secrets inherited.

    Workers inherit the parent environment, so a ``required_secrets`` name set
    only in ``os.environ`` is as sensitive as one passed explicitly.
    """
    secrets = {name: value for name, value in context.env.items() if value}
    for name in required_secret_names(request.to_dict()):
        if name not in secrets and os.environ.get(name):
            secrets[name] = os.environ[name]
    return secrets


def check_required_secrets(request: EvaluationRequest, context: ExecutionContext) -> None:
    """Fail before any worker starts when a declared secret is unavailable.

    Names come from ``required_secrets`` lists in the request; values must be
    supplied through ``ExecutionContext.env`` or the inherited environment.
    """
    missing = [
        name for name in required_secret_names(request.to_dict())
        if not (context.env.get(name) or os.environ.get(name))
    ]
    if missing:
        raise RequestValidationError(
            f'required secrets are not set in ExecutionContext.env or the environment: {missing}'
        )


def _redact_result(result: EvaluationResult, secrets: Mapping[str, str]) -> EvaluationResult:
    # Adapters retain native exception text/tracebacks, which can quote
    # credentials supplied through the environment; never publish those values.
    if not any(secrets.values()):
        return result
    redacted = EvaluationResult.from_dict(redact_values(result.to_dict(), secrets))
    diagnostics = dict(redacted.diagnostics)
    short = sorted(
        name for name, value in secrets.items()
        if value and len(value) < MIN_REDACTED_VALUE_LENGTH
    )
    if short:
        diagnostics['env_values_not_redacted_as_too_short'] = short
    return EvaluationResult(
        engine=redacted.engine,
        identity=result.identity,
        status=redacted.status,
        records=redacted.records,
        samples=redacted.samples,
        artifacts=redacted.artifacts,
        diagnostics=diagnostics,
    )


def _terminal_error_result(
    resolved: ResolvedEvaluation,
    *,
    status: str,
    kind: str,
    detail: str,
) -> EvaluationResult:
    return EvaluationResult(
        engine=resolved.request.engine,
        identity=resolved.identity,
        status=as_execution_status(status),
        records=(),
        diagnostics={
            'runner_failure_kind': kind,
            'runner_error': detail,
        },
    )


async def run_evaluation_async(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    context: ExecutionContext,
) -> RunBundle:
    """Execute once and atomically publish the run bundle at ``context.output_dir``.

    Always executes; use ``ensure_evaluation`` for store lookup and reuse. A
    request is resolved in ``context.worker_python`` when given.
    """
    if isinstance(request_or_resolved, EvaluationRequest):
        resolved = await resolve_evaluation_async(request_or_resolved, context)
    else:
        resolved = request_or_resolved
        check_required_secrets(resolved.request, context)
    secrets = effective_secrets(resolved.request, context)
    destination = context.output_dir
    destination.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix='.aiq-evals-work-', dir=destination.parent))
    try:
        try:
            result = _redact_result(await _execute_resolved(resolved, context, work_dir), secrets)
        except asyncio.CancelledError as ex:
            # Preserve an inspectable terminal attempt, but do not consume task
            # cancellation: callers still receive CancelledError.
            cancelled = _redact_result(
                _cancelled_result(resolved, work_dir, _redacted_exception_text(ex, secrets)),
                secrets,
            )
            try:
                publish_run(
                    destination,
                    resolved=resolved,
                    result=cancelled,
                    context=context,
                    native_dir=work_dir / 'native',
                )
            except Exception:
                # Cancellation semantics take precedence over a secondary
                # publication failure. There may simply be no terminal bundle.
                pass
            raise
        except (ExecutionError, TimeoutError, OSError) as ex:
            result = _terminal_error_result(
                resolved,
                status='failed',
                kind='execution',
                detail=_redacted_exception_text(ex, secrets),
            )
        return publish_run(
            destination,
            resolved=resolved,
            result=result,
            context=context,
            native_dir=work_dir / 'native',
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_evaluation(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    context: ExecutionContext,
) -> RunBundle:
    """Synchronous facade; use ``run_evaluation_async`` inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_evaluation_async(request_or_resolved, context))
    raise ActiveEventLoopError(
        'run_evaluation() cannot be called from an active event loop; '
        'await run_evaluation_async() instead'
    )


def snapshot_native_source(
    source: str | Path, staging: Path, *, allow_external_symlinks: bool = False,
) -> tuple[Path, dict[str, list[str]]]:
    """Copy native artifacts once into ``staging`` and return the copy.

    An import reads its source exactly once: identity, normalization, and the
    published native files all come from this snapshot, so they describe the
    same bytes even if the source changes meanwhile. A single file is copied
    as ``staging/native/<name>``; a directory as ``staging/native``, with links
    that leave it refused unless ``allow_external_symlinks`` (followed links
    are listed in the returned manifest notes).
    """
    source_path = Path(source).expanduser().absolute()
    native = staging / 'native'
    if source_path.is_file():
        native.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path.resolve(), native / source_path.name)
        return native / source_path.name, {}
    if not source_path.is_dir():
        raise errors_module.ArtifactError(f'native artifact source does not exist: {source_path}')
    notes = copy_native_tree(
        source_path, native, external_symlinks='follow' if allow_external_symlinks else 'raise',
    )
    return native, notes


def _replace_text(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, Mapping):
        return {str(key).replace(old, new): _replace_text(child, old, new) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_replace_text(child, old, new) for child in value]
    return value


async def import_evaluation_async(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    source: str | Path,
    context: ExecutionContext,
    *,
    allow_external_symlinks: bool = False,
    expected_native_identity: str | None = None,
) -> RunBundle:
    """Import native artifacts and atomically publish an engine-free run bundle.

    The source is snapshotted once (:func:`snapshot_native_source`); the
    adapter normalizes the snapshot and the bundle preserves the same snapshot.
    With ``expected_native_identity`` the snapshot must have exactly that
    content identity, or :class:`~magnet_evals.errors.ImportIdentityMismatch`
    is raised before anything is normalized or published.

    Resolution and native reading happen in ``context.worker_python`` when given,
    so an engine-free caller can import, e.g., Inspect ``.eval`` logs. Symlinks in
    ``source`` that leave it are refused unless ``allow_external_symlinks`` is set
    for a trusted source; followed links are listed in the manifest.
    """
    # Reading native artifacts needs no credentials, so declared secrets are
    # not required here (they are scrubbed from the result if present).
    if isinstance(request_or_resolved, EvaluationRequest):
        resolved = await resolve_evaluation_async(request_or_resolved, context, require_secrets=False)
    else:
        resolved = request_or_resolved
    secrets = effective_secrets(resolved.request, context)
    source_path = Path(source).expanduser().absolute()
    context.output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.aiq-evals-import-', dir=context.output_dir.parent))
    try:
        snapshot, link_notes = await asyncio.to_thread(
            snapshot_native_source, source_path, staging, allow_external_symlinks=allow_external_symlinks,
        )
        if expected_native_identity is not None:
            actual = await asyncio.to_thread(native_source_identity, snapshot)
            if actual != expected_native_identity:
                raise errors_module.ImportIdentityMismatch(
                    f'native artifacts at {source_path} have content identity {actual}, '
                    f'expected {expected_native_identity} (they changed since they were identified)'
                )
        if context.worker_python is None:
            backend = get_backend(resolved.request.engine)
            result = backend.import_results(resolved, str(snapshot), context)
        else:
            result = await _import_in_worker(resolved, snapshot, context, secrets)
        # Diagnostics name the caller's source, not the private snapshot.
        result = EvaluationResult.from_dict(_replace_text(result.to_dict(), str(snapshot), str(source_path)))
        return publish_run(
            context.output_dir,
            resolved=resolved,
            result=_redact_result(result, secrets),
            context=context,
            native_dir=snapshot,
            manifest_notes=link_notes,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def _import_in_worker(
    resolved: ResolvedEvaluation,
    source: Path,
    context: ExecutionContext,
    secrets: Mapping[str, str],
) -> EvaluationResult:
    with tempfile.TemporaryDirectory(prefix='aiq-evals-import-') as scratch:
        scratch_dir = Path(scratch)
        resolved_path = scratch_dir / 'resolved.json'
        result_path = scratch_dir / 'result.json'
        stderr_path = scratch_dir / 'stderr.log'
        resolved_path.write_text(json.dumps(resolved.to_dict(), sort_keys=True))
        returncode = await _run_worker(
            [
                'import',
                '--resolved', str(resolved_path),
                '--source', str(source),
                '--output-dir', str(context.output_dir),
                '--result', str(result_path),
            ],
            context,
            scratch_dir / 'stdout.log',
            stderr_path,
            secrets,
        )
        try:
            payload = json.loads(result_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as ex:
            detail = stderr_path.read_text(errors='replace')[-4000:]
            raise ExecutionError(f'import worker exited with code {returncode} without a result: {detail}') from ex
    _raise_worker_error(payload)
    return EvaluationResult.from_dict(payload['result'])


def import_evaluation(
    request_or_resolved: EvaluationRequest | ResolvedEvaluation,
    source: str | Path,
    context: ExecutionContext,
    *,
    allow_external_symlinks: bool = False,
    expected_native_identity: str | None = None,
) -> RunBundle:
    """Synchronous facade for :func:`import_evaluation_async`."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            import_evaluation_async(
                request_or_resolved, source, context, allow_external_symlinks=allow_external_symlinks,
                expected_native_identity=expected_native_identity,
            )
        )
    raise ActiveEventLoopError(
        'import_evaluation() cannot be called from an active event loop; '
        'await import_evaluation_async() instead'
    )
