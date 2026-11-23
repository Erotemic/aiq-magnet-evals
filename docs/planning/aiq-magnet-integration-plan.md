# aiq-magnet integration plan for aiq-magnet-evals

This file contains work that should happen in `aiq-magnet`, not in the core
`aiq-magnet-evals` package.

**2026-11-22 architectural correction:**
[ADR-0013](../adrs/0013-offline-command-planning.md) supersedes the original
scheduling-time preflight requirement. Command construction must work without
the native runtime or execution host. The MAGNET correction is staged on
`fix/offline-command-planning`; an already-running campaign retains its
current code until completion. M3 and M9 below describe the corrected boundary.

Status (2026-09-29): M1-M10 implemented and tested on the MAGNET branch
`dev/aiq-evals-integration`. Checked items cite their evidence in
`integration-evidence.md`. One item is explicitly deferred (M1, migrating the
legacy HELM internals), and hosted CI has not run yet.

## Goal

MAGNET should delegate native evaluation acquisition to `aiq-magnet-evals` while
retaining ownership of scheduling, evidence selection, claims, and dashboards.

```text
MAGNET recipe / kwdagger campaign
      |
      v
EvaluationNode
      |
      v
magnet_evals.ensure/run/import
      |
      v
EvaluationRun
      |
      v
MAGNET evidence projection
      |
      v
metrics.evaluate.* -> ClaimResultNamespace -> card/dashboard
```

## M1 - Dependency and compatibility seam

- [x] Add `aiq-magnet-evals` as a MAGNET dependency only after its phase-2 core contract
  is usable. (Optional extra `aiq-magnet[aiq-magnet-evals]`, imported lazily;
  resolved from git until it is on PyPI.)
- [x] Keep `magnet evaluate` legacy behavior compatible. (MAGNET's full suite;
  E-M1.)
- [x] Integrate through `magnet evaluate_new` first.
- [ ] Preserve existing HELM commands/loaders while migrating their generic
  execution/import implementation underneath to `aiq-magnet-evals`.
  **Deferred.** The preservation half holds: legacy HELM commands, loaders, and
  recipes are unchanged and pass. HELM through `EvaluationNode` uses the
  aiq-magnet-evals HELM adapter, which also imports MAGNET-materialized run
  directories. Rewiring MAGNET's legacy materialization code onto
  aiq-magnet-evals is not required for those guarantees and has not been done.
  It is the remaining step of the migration principle below.
- [x] Keep HELM-specific predictor/instance-predictor APIs in MAGNET until a
  separate migration is justified.

## M2 - Generic EvaluationNode

Create a MAGNET/kwdagger node whose job is to invoke one `aiq-magnet-evals` evaluation
request.

The node owns:

- conversion from recipe parameters to `EvaluationRequest`;
- output product path known to kwdagger;
- scheduler/container/lease wiring;
- invocation of the worker/facade;
- result-loader projection into one flat kwdagger evidence row.

The node must not own native engine-specific execution logic.

Use `engine` for `helm`, `olmo_eval`, or `inspect_ai`. Retain `backend` for the
kwdagger/cmd_queue scheduler (`serial`, `tmux`, etc.).

`magnet.backends.aiq_evals.EvaluationNode` renders `cli.run_node` and, for
leased work, `cli.resolve_node`. Resolution and acquisition run only when the
generated job executes, wrapped for its host or container environment.

## M3 - Declared scheduling identity and runtime measurement identity

kwdagger hashes declared work; the evaluator resolves native facts when the
generated job executes. A scheduling ID does not attest to an unobserved
execution environment or justify native cache reuse.

Requirements:

- Construct complete commands with missing target interpreters/packages,
  subprocess creation forbidden and no serving-catalog query.
- Resolve measurement/import identities inside the executing job, in its
  native host/container context. An unresolved mutable input disables native
  reuse, not command construction.
- Completed scheduler outputs use cheap file-existence checks, without native
  resolution or artifact audits. Undeclared engine/task/import changes require
  an explicit refresh or a declared revision. Native identity is resolved when
  an acquisition command actually executes.
- Retain native identity and artifact validation during acquisition and evidence
  readout. Invalid evidence is reported there rather than making every completed
  node pending to audit it on resume.
- Changing a MAGNET evidence selector does not rerun an unchanged native
  evaluation unless it changes native computation; concurrent selector nodes
  execute it once (aiq-magnet-evals ADR-0011).

Staged MAGNET evidence: normal host/container command compilation with native
imports, catalog queries and subprocess creation blocked; runtime task/import
change and store-reuse cases; pinned native Inspect and real tmux lease cases.
No evaluator identity algorithm or existing bundle changes are needed.

## M4 - Evidence projection

MAGNET defines a separate evidence-view record containing at least:

- source evaluation identity/artifact;
- selected task/model binding;
- selected scorer/metric/reducer;
- coverage policy;
- eligibility result and reasons;
- denominator when known;
- claim-facing provenance.

Strict default evidence eligibility should continue to require the policy MAGNET
chooses (for example successful execution, sufficient coverage, and a finite
selected scalar metric), but that judgment must not mutate the underlying
`aiq-magnet-evals` run.

Status: done. The node's `evaluation.json` records only the run reference and
the projection (selector, coverage policy). The view is recomputed from the
validated run every time a row is loaded, so editing `evaluation.json` cannot
change what a claim sees (E-M4).

## M5 - One artifact -> one evidence row

Preserve the existing kwdagger contract: a completed result-node artifact maps
to exactly one row.

A multi-log Inspect run or OLMo Eval suite may contain many native result
records. The MAGNET loader still returns one flat row.

A selector must identify exactly one claim-facing task/model/scorer/metric (and
reducer where required), or select one explicit native suite aggregate.

Nonselected records remain available from `aiq-magnet-evals` readers but do not create
additional MAGNET claim votes.

Examples:

- two task logs x three epochs -> one evidence row when task A reduced accuracy
  is selected;
- separate task claims -> schedule separate nodes;
- cross-task comparison -> schedule an explicit downstream comparison node.

## M6 - Cardinality acceptance experiment

This remains an early MAGNET integration gate even though native fixture capture
happens in `aiq-magnet-evals`. On 2026-09-29 it moved here from the `aiq-magnet-evals` P1-10
acceptance gate, because it needs the M4/M5 projection, which does not exist
yet. Representative native inputs are committed in `aiq-magnet-evals`:
`tests/fixtures/inspect-native/multi/` (three task logs, two epochs, auxiliary
role) and `tests/fixtures/olmo-native/multi/` (one suite expanded to two
prefix-overlapping task names). Engine-free `json/` renderings of the Inspect
logs and `expected-normalized.json` goldens sit beside them.

Using representative multi-result fixtures:

- [x] feed them through real `kwdagger.aggregate_loader.build_tables`;
- [x] load with `KWDaggerProcessor.load_available_result_rows`;
- [x] evaluate through `ClaimResultNamespace`;
- [x] record flat column examples (E-M6);
- [x] assert exactly one row/verdict per artifact;
- [x] test duplicate sample IDs across tasks/models;
- [x] test repeated epochs/reducers;
- [x] test ambiguous selector rejection;
- [x] prove no silent averaging of unrelated results.

Repeat with production adapters. Nothing on either side is frozen before a PyPI
release (aiq-magnet-evals ADR-0010).

## M7 - Recipes and mixed-engine examples

- [x] generation recipe using HELM;
- [x] generation recipe using OLMo Eval;
- [x] generation recipe using Inspect;
- [x] agent/tool recipe using OLMo Eval;
- [x] agent/tool recipe using Inspect;
- [x] mixed-engine pipeline with explicit task/metric mappings;
- [x] explicit downstream comparison node rather than assuming cross-engine
  scores are interchangeable.

The recipes live in MAGNET's `magnet/examples/aiq_evals/`, ship as package data,
and use only the installed `magnet_evals.examples` tasks (E-M7).

All should use a stable result node such as `evaluate` and expose
`metrics.evaluate.score` only when selection is unambiguous.

## M8 - Scheduling and resource ownership

kwdagger continues to own campaign scheduling and node attempt/cache policy.
`aiq-magnet-evals` owns execution inside the node.

For MAGNET leasing/container integration:

- [x] pass leased endpoints/model role bindings into `aiq-magnet-evals` execution
  context (`endpoint` for the primary, `endpoints: {role: alias}` for others,
  one lease for all; per-role reach: Inspect any bound role, OLMo Eval primary,
  HELM none);
- [x] avoid duplicate model startup: leasing is decided when the node runs,
  under the store's acquisition lock (a stored run takes no lease; concurrent
  nodes for one measurement start one lease), and infer-stack coalesces
  same-model leases;
- [x] propagate cancellation to engine workers/sandboxes;
- [x] keep secrets in runtime bindings, not hash/manifests/commands;
- [x] keep scheduler `backend` independent of evaluation `engine`;
- [x] container execution: runtime resolution and execution use the node's
  container, including a worker interpreter that exists only there. The
  planning machine need not have that interpreter or container image.

## M9 - Planning and dry-run semantics

`magnet evaluate_new --dry-run` must remain side-effect free:

- no arbitrary task-factory execution;
- no model startup;
- no tool calls;
- no dataset download;
- no evidence publication;
- no verdict.

Static compilation may validate serializable request shape. All command
construction, including normal scheduling, excludes runtime resolution. Native
workers are invoked by generated jobs at execution, never by a configuration
property or a mandatory pre-compilation preparation stage (ADR-0013).

A dry run resolves nothing and writes no store, but rejects malformed selectors
and coverage policies (E-M9). The staged correction extends the same runtime-free
construction guarantee to normal scheduling before explicit backend dispatch.

## M10 - MAGNET integration validation

Required MAGNET-side tests (each mapped to a test in E-M10):

- [x] common metric/provenance columns from all three engines;
- [x] agentic results reaching the same evidence interface;
- [x] requested versus accumulated evidence scopes;
- [x] requested cached result behavior;
- [x] execution failure provenance separate from scientific claim truth;
- [x] same-measurement reuse and invalidation;
- [x] no cross-engine cache collision;
- [x] stale/failed attempt handling;
- [x] serial and tmux scheduler behavior;
- [x] existing dashboard/card compatibility (the file contract eval-card-viz
  uploads; the viewer itself was not run);
- [x] HELM legacy regression coverage;
- [x] a dedicated CI job (xcookie source check `aiq-magnet-evals`) that runs
  these with `MAGNET_REQUIRE_AIQ_EVALS=1`, so a missing engine fails rather
  than skips. Reproduced locally; not yet run on hosted CI.

## Migration principle

The migration should shrink MAGNET's engine-specific surface rather than copy it.
At the end, MAGNET should know how to *request and interpret* an evaluation, but
not how OLMo Eval's runner or Inspect's log reader works internally.
