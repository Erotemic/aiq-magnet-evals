"""Shared native conformance suite (plan phase 6).

The same contract checks run for every engine; each engine contributes a
profile of native requests. Run the file in each engine's environment; profiles
whose engine is not importable are skipped:

    /tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_conformance.py
    PYTHONPATH=$PWD /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_conformance.py
    /tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_conformance.py
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import subprocess
import sys
import textwrap
import threading
from dataclasses import dataclass, replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Callable, ContextManager, Iterator

import pytest

from magnet_evals.contracts import EvaluationRequest, ExecutionContext, ModelBinding
from magnet_evals.ensure import ensure_evaluation, ensure_evaluation_async
from magnet_evals.runner import resolve_evaluation, resolve_evaluation_async
from magnet_evals.store import ResultStore

OLMO_REVISION = "73ade80e24f796af55caeb8fd7b75a7f3fd607fd"
ENGINE_MODULES = ("harbor", "inspect_ai", "olmo_eval", "helm")


@dataclass(frozen=True)
class Profile:
    engine: str
    module: str
    success: EvaluationRequest
    changed: EvaluationRequest
    # Context managers yield (request, env) so a profile can host local fixtures.
    failing: Callable[[], ContextManager[tuple[EvaluationRequest, dict[str, str]]]]
    slow: EvaluationRequest
    slow_pid_env: str
    native_subdir: str


def _fixed(request: EvaluationRequest, env: dict[str, str] | None = None):
    @contextlib.contextmanager
    def manager() -> Iterator[tuple[EvaluationRequest, dict[str, str]]]:
        yield request, dict(env or {})

    return manager


def _inspect_profile() -> Profile:
    def req(task: str, model: str = "local", **kwargs) -> EvaluationRequest:
        return EvaluationRequest(
            engine="inspect_ai",
            task=f"python:tests.native.{task}",
            data_revision="fixture-v1",
            models=(ModelBinding(role="primary", model=model, provider="fixture", revision="local-v1"),),
            engine_options={"registration_modules": ["tests.native.inspect_fixture"], **kwargs},
        )

    success = req("inspect_fixture:generation")
    return Profile(
        engine="inspect_ai",
        module="inspect_ai",
        success=success,
        changed=replace(success, generation={"temperature": 0.5}),
        failing=_fixed(req("inspect_failure_fixture:run_error_task", eval_options={"max_samples": 1})),
        slow=req("inspect_fixture:generation", model="slow"),
        slow_pid_env="AIQ_P1_CHILD_PID_FILE",
        native_subdir="native/inspect_ai/logs",
    )


def _olmo_profile() -> Profile:
    def req(task: str, **kwargs) -> EvaluationRequest:
        return EvaluationRequest(
            engine="olmo_eval",
            task=task,
            task_revision="fixture-v1",
            data_revision="fixture-v1",
            models=(ModelBinding(role="primary", model="mock", provider="mock", revision="local-v1"),),
            engine_options={"upstream_revision": OLMO_REVISION, "task_modules": ["tests.native.olmo_fixture"]},
            **kwargs,
        )

    @contextlib.contextmanager
    def failing() -> Iterator[tuple[EvaluationRequest, dict[str, str]]]:
        pytest.importorskip("agents")
        from tests.native import test_olmo_native as olmo

        olmo._DeterministicChatHandler.fail = True
        server = ThreadingHTTPServer(("127.0.0.1", 0), olmo._DeterministicChatHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = olmo._tool_request(server.server_port, failure_gate=True)
            yield replace(request, task_revision="fixture-v1", data_revision="fixture-v1"), {
                "OPENAI_API_KEY": "local-fixture"
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            olmo._DeterministicChatHandler.fail = False

    success = req("aiq_p1_local")
    return Profile(
        engine="olmo_eval",
        module="olmo_eval",
        success=success,
        changed=replace(success, task_options={"limit": 1}),
        failing=failing,
        slow=req("aiq_p1_slow"),
        slow_pid_env="AIQ_P1_CHILD_PID_FILE",
        native_subdir="native",
    )


def _helm_profile() -> Profile:
    def req(task: str, max_eval: int = 1, plugins: bool = False) -> EvaluationRequest:
        return EvaluationRequest(
            engine="helm",
            task=task,
            task_revision="helm-builtin",
            data_revision="helm-builtin",
            models=(ModelBinding(role="primary", model="simple/model1", revision="local-v1"),),
            task_options={"max_eval_instances": max_eval},
            engine_options={"plugins": ["tests.native.helm_plugin_fixture"]} if plugins else {},
        )

    return Profile(
        engine="helm",
        module="helm",
        success=req("simple_mcqa"),
        changed=req("simple_mcqa", max_eval=2),
        failing=_fixed(req("aiq_p5_fail", plugins=True)),
        slow=req("aiq_p5_slow", plugins=True),
        slow_pid_env="AIQ_P5_CHILD_PID_FILE",
        native_subdir="native/helm",
    )


def _harbor_profile() -> Profile:
    from tests.native.harbor_fixture import TASKS

    success = EvaluationRequest(
        engine='harbor', task='path:' + str(TASKS.resolve()), data_revision='synthetic-v1',
        models=(ModelBinding(role='primary', model='fixture', revision='synthetic-v1'),),
        task_options={'agent': 'oracle'},
    )
    return Profile(
        engine='harbor', module='harbor', success=success,
        changed=replace(success, task_options={'agent': 'oracle', 'n_attempts': 2}),
        failing=_fixed(replace(success, task_options={
            'agent': 'python:tests.native.harbor_failure_agent:FailureAgent'})),
        slow=replace(success, task_options={'agent': 'python:tests.native.harbor_sleep_agent:SleepAgent'}),
        slow_pid_env='AIQ_HARBOR_CHILD_PID_FILE', native_subdir='native/harbor/evaluation',
    )


PROFILES = {'harbor': _harbor_profile, "inspect_ai": _inspect_profile, "olmo_eval": _olmo_profile, "helm": _helm_profile}


@pytest.fixture(params=[pytest.param(name, marks=pytest.mark.docker_sandbox) if name == 'harbor' else name for name in sorted(PROFILES)])
def profile(request) -> Profile:
    if importlib.util.find_spec(request.param) is None:
        pytest.skip(f"{request.param} is not installed in this interpreter")
    return PROFILES[request.param]()


def _ensure(req: EvaluationRequest, store: ResultStore, **kwargs):
    return ensure_evaluation(req, store, worker_python=sys.executable, **kwargs)


def _metrics(bundle) -> list:
    return sorted(
        (
            [m.task, m.metric, m.scorer, m.score, m.group, m.reducer, m.value]
            for record in bundle.result.records
            for m in record.metrics
        ),
        key=json.dumps,
    )


def test_resolution_is_deterministic_and_worker_consistent(profile: Profile) -> None:
    one = resolve_evaluation(profile.success)
    two = resolve_evaluation(EvaluationRequest.from_dict(profile.success.to_dict()))
    worker = asyncio.run(
        resolve_evaluation_async(
            profile.success, ExecutionContext(output_dir=Path.cwd(), worker_python=sys.executable)
        )
    )
    assert one.identity == two.identity == worker.identity
    assert one.identity.reusable, one.identity.unknown_reasons
    assert resolve_evaluation(profile.changed).identity.digest != one.identity.digest


def test_ensure_executes_reuses_imports_and_reads_engine_free(profile: Profile, tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "store")
    first = _ensure(profile.success, store)
    assert first.action == "executed"
    assert first.run.result.status == "succeeded", first.run.result.diagnostics
    assert first.run.complete and first.run.path == store.run_path(first.resolved.identity.digest)
    assert first.run.result.records and all(r.coverage.status == "complete" for r in first.run.result.records)
    assert _metrics(first.run)

    again = _ensure(profile.success, store)
    assert again.reused and again.run.path == first.run.path

    changed = _ensure(profile.changed, store)
    assert changed.action == "executed" and changed.run.path != first.run.path

    imported = ensure_evaluation(
        first.resolved, ResultStore(tmp_path / "import-store"),
        import_source=first.run.path / profile.native_subdir,
    )
    assert imported.action == "imported" and imported.run.result.status == "succeeded"
    assert _metrics(imported.run) == _metrics(first.run)

    # Normalized results load with every engine import blocked.
    script = textwrap.dedent(
        f"""
        import importlib.abc, sys
        class Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split('.')[0] in {ENGINE_MODULES!r}:
                    raise ImportError('engine import blocked: ' + name)
        sys.meta_path.insert(0, Block())
        from magnet_evals.artifacts import RunBundle
        bundle = RunBundle.load(sys.argv[1])
        print(bundle.result.status, len(bundle.result.records))
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script, str(first.run.path)],
        capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[2],
    )
    assert out.stdout.split()[0] == "succeeded"


def test_failure_is_inspectable_and_never_canonical(profile: Profile, tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "store")
    with profile.failing() as (req, env):
        outcome = _ensure(req, store, env=env)
    assert outcome.action == "executed"
    assert outcome.run.result.status == "failed", outcome.run.result.status
    assert not outcome.run.complete
    assert store.lookup(outcome.resolved) is None
    assert not store.run_path(outcome.resolved.identity.digest).exists()
    assert [b.result.status for b in store.attempts(outcome.resolved.identity.digest)] == ["failed"]


def test_cancellation_leaves_cancelled_attempt_and_no_canonical(profile: Profile, tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "store")
    pid_file = tmp_path / "child.pid"

    async def exercise():
        task = asyncio.create_task(
            ensure_evaluation_async(
                profile.slow, store, worker_python=sys.executable,
                env={profile.slow_pid_env: str(pid_file)},
            )
        )
        for _ in range(300):
            if pid_file.exists() and pid_file.read_text():
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("slow native task never started its child")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    resolved = resolve_evaluation(profile.slow)
    child = Path(f"/proc/{int(pid_file.read_text())}/stat")
    assert not child.exists() or child.read_text().split()[2] == "Z"
    assert store.lookup(resolved) is None
    attempts = store.attempts(resolved.identity.digest)
    assert [b.result.status for b in attempts] == ["cancelled"]
    assert json.loads((attempts[0].path / "attempt.json").read_text())["status"] == "cancelled"
