# aiq-magnet-evals

`aiq-magnet-evals` is a backend-agnostic evaluation runtime and artifact interface.
Its intended high-level operation is:

```text
fully specified evaluation request
        |
        v
resolve measurement identity
        |
        +---- reusable compatible result exists? ----+
        |                                            |
       yes                                           no
        |                                            |
        v                                            v
load / import                                 execute native engine
        |                                            |
        +----------------------+---------------------+
                               |
                               v
                  normalized evaluation result
```

The initial engines are HELM, OLMo Eval, and Inspect. `aiq-magnet-evals` is not a
scheduler and is not a scientific claim system. MAGNET is expected to consume
its results and decide how a selected metric becomes claim evidence.

## Current status

Phase 1 (native validation) closed on 2026-09-29. The adapters passed native
fixtures at verified pins: Inspect `inspect-ai==0.3.272`, OLMo Eval
`73ade80e24f796af55caeb8fd7b75a7f3fd607fd` (isolated worker checkout), and
HELM `crfm-helm==0.5.14` through MAGNET. Support is limited to the tested
combinations in `docs/planning/phase1-capabilities.md`. All three engines pass
the shared conformance suite. Nothing is frozen before a PyPI release (ADR-0010).

Harbor is also registered as an experimental generic engine at candidate pin
`0.23.0`, in an isolated Python 3.12+ worker. Synthetic Docker probes and native
worker conformance are recorded in [the Harbor evidence ledger](docs/planning/harbor-evidence.md).
[SWE-bench Verified](docs/swebench.md) now has a pinned five-instance offline
oracle/NOP fixture with fresh official regrading and engine-free patch export.
Pro V2 has an experimental local Harbor generation/fresh-replay profile with
captured oracle/NOP and scripted locked-agent evidence. Cross-repository VM
acceptance passed all 17 required checks; real-model GPU acceptance remains
unrun. Scope and [retained evidence](docs/planning/evidence/swebench-vm-2026-10-06/README.md)
remain limited to the tested cells.

From a source checkout, `dev/ci/harbor_phase0.sh` runs the infrastructure probes
and `dev/ci/native_harbor.sh` runs generic adapter acceptance. The checkout-only
`examples/harbor_synthetic_request.json` uses an oracle and needs no model/GPU.
For model-driven jobs, use `task_options.endpoint_location="sandbox"` (default)
for installed agents, or `"host"` for agents whose model client runs in the worker.
The primary endpoint is operational; task/agent/config bytes and native phase
network policies contribute to measurement identity. Installed agent runtimes
without an explicit version are non-reusable.

Implemented now:

- versioned dependency-free request, resolution, result, sample, and metric contracts;
- strict JSON/static validation with credentials separated into execution context;
- canonical measurement identity and explicit no-reuse reasons;
- lazy backend registration;
- sync/async execution and native-import facades;
- isolated worker-process execution with timeout/cancellation termination;
- atomic terminal run bundles with native checksums and normalized artifact identity;
- a content-addressed filesystem result store and engine-free readers;
- single-flight acquisition: concurrent callers for one measurement, across
  processes sharing a store, execute it once (ADR-0011);
- explicit native imports keyed by their content, so different or edited
  artifacts are imported, never mistaken for an earlier import (ADR-0011);
- runnable, installed examples for every engine (`magnet_evals.examples`,
  `examples/*.json`), including agent/tool runs and an opt-in Docker sandbox;
- a schema-v1 regression fixture and conservative rejection of unknown schema versions;
- an experimental OLMo Eval adapter using `HarnessConfig`, `AsyncEvalRunner.validate()`,
  and `run_async()`;
- OLMo nested metric/scorer preservation, coverage accounting, predictions/trajectories,
  hard-failure handling, and native artifact import validation;
- an experimental Inspect adapter using the public `eval()` and log-reader APIs;
- Inspect multi-log normalization preserving scorer/score/metric/group/reducer identity;
- Inspect per-epoch samples, epoch reductions, model-role usage, and tool/event trajectories;
- automatic owned-worker execution for synchronous native runtimes such as Inspect;
- Inspect `.eval`/JSON import and native model/task-argument validation;
- an experimental HELM adapter resolving run entries through HELM's own RunSpec
  expansion, executing `helm.benchmark.run` in a worker, and importing native
  (including MAGNET-materialized) run directories.

Remaining work is tracked in `docs/planning/aiq-evals-plan.md`. MAGNET integration is tracked separately in
`docs/planning/aiq-magnet-integration-plan.md`.

## MAGNET

MAGNET consumes this package through `magnet.backends.aiq_evals.EvaluationNode`
(aiq-magnet, optional extra `aiq-magnet-evals`). MAGNET owns scheduling,
evidence selection, and claims; this package owns obtaining the evaluation. See
`docs/planning/aiq-magnet-integration-plan.md` and `integration-evidence.md`.

## Bootstrap

```bash
python -m pip install -e '.[tests]'
pytest -q
aiq-magnet-evals phase1-status
aiq-magnet-evals phase1-probe
aiq-magnet-evals backends
```

A request is JSON-shaped and contains measurement inputs only. Credentials stay
in the execution environment rather than the persisted request. For example:

```json
{
  "schema_version": 1,
  "engine": "olmo_eval",
  "task": "my_registered_task",
  "task_revision": "<immutable-task-revision>",
  "data_revision": "<immutable-data-revision>",
  "models": [{
    "role": "primary",
    "model": "my-model",
    "provider": "mock",
    "revision": "<immutable-model-revision>",
    "cache_token": null,
    "provider_options": {}
  }],
  "task_options": {"limit": 4},
  "generation": {"temperature": 0.0},
  "engine_options": {
    "upstream_revision": "73ade80e24f796af55caeb8fd7b75a7f3fd607fd"
  }
}
```

Static validation does not import OLMo Eval or Inspect:

```bash
aiq-magnet-evals validate request.json
aiq-magnet-evals validate examples/inspect_ai_request.json
```

To install the verified Inspect runtime in the same environment:

```bash
python -m pip install -e '.[inspect]'
```

Resolution and execution require the native engine environment. A separate
worker interpreter can be selected without adding the engine to core:

```bash
aiq-magnet-evals resolve request.json
aiq-magnet-evals run request.json --output run-dir --worker-python /path/to/worker/python
aiq-magnet-evals ensure request.json --store results/ --worker-python /path/to/worker/python
aiq-magnet-evals show run-dir
```

To inspect exact upstream source checkouts without importing them:

```bash
aiq-magnet-evals phase1-probe \
    --checkout olmo_eval=/path/to/olmo-eval inspect_ai=/path/to/inspect_ai helm=/path/to/helm \
    --output phase1-artifacts/local-probe.json
```

The probe is deliberately non-executing. The native acceptance suites live in
`tests/native/` and run only inside the matching engine environment (see
`docs/planning/phase1-evidence.md` for the exact environments).

## Examples

Every `examples/*.json` request (except the two placeholder templates) runs
from an installed package: tasks, a deterministic model provider, and an
OpenAI-compatible example endpoint live in `magnet_evals.examples`. Each
engine runs in its own worker interpreter:

```bash
aiq-magnet-evals ensure examples/inspect_tool_request.json --store results/ \
    --worker-python /path/to/inspect-venv/bin/python
python -m magnet_evals.examples.chat_server --port 8000 &   # for *_agent / *_endpoint examples
OPENAI_API_KEY=any aiq-magnet-evals ensure examples/olmo_agent_request.json --store results/ \
    --worker-python /path/to/olmo-eval/.venv/bin/python
```

`dev/walkthrough.sh` runs the generation, tool, local-sandbox, and OLMo agent
examples from a fresh engine-free venv; `tests/native/test_examples_native.py`
runs every runnable example (the Docker one only where Docker is usable).

## Documentation

- `docs/api.md`: public API, CLI, contracts, bundle and store layout.
- `docs/security-review.md`: trust model and security findings.
- `docs/release-gate.md`: release checks and the latest local record.
- `dev/ci/*.sh`: the CI jobs, runnable locally; `dev/walkthrough.sh`: the clean-environment walkthrough.

## Architecture review target

Reviewers should start with `docs/adrs/README.md`. The ADRs define the intended architecture and reviewer invariants independently of roadmap status. `docs/planning/` tracks implementation progress and evidence.

## Planning

- `docs/planning/aiq-evals-plan.md`: work owned by this repository.
- `docs/planning/integration-evidence.md`: MAGNET integration evidence.
- `docs/planning/aiq-magnet-integration-plan.md`: work that belongs in MAGNET.
- `docs/planning/phase1-evidence.md`: canonical phase-1 native acceptance ledger.
- `docs/planning/phase2-phase3-evidence.md`: phase-2/3 implementation evidence and remaining native gates.
- `docs/planning/phase4-evidence.md`: Inspect implementation evidence and remaining native gates.
- `docs/planning/architecture.md`: package boundary and identity model.
