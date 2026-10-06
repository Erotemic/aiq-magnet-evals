# SWE-bench, SWE-bench Pro V2, and Harbor integration roadmap

Status: proposed implementation roadmap, 2026-10-05

This document plans the work required to make `aiq-magnet-evals` a trustworthy
runtime for repository-level coding benchmarks, with particular emphasis on
Harbor and SWE-bench Pro V2. It also defines the cross-repository work needed
in `aiq-magnet` and `infer-stack` so local quantizations, distillations, and
serving configurations can be compared without silently changing the
benchmark protocol.

The intended end state is not merely "we can launch SWE-bench." The goal is a
reproducible measurement system that can answer questions such as:

> Does `Qwen3.8-27B-Q4_K_M` lose agentic coding capability relative to the
> same model at Q5, Q8, FP16, an EXL3 quant, or a distilled derivative when
> the benchmark, agent scaffold, serving configuration, and grader are held
> fixed?

The system must also distinguish that controlled local comparison from a
publisher-score reproduction, where the goal is to match the model author's
reported agent scaffold and sampling configuration.

## Snapshot used for this plan

The plan was written against these supplied repository snapshots:

- `aiq-magnet-evals` at `c8a9a17dde1ae2f3468da83d794c84df9da6f020`;
- `aiq-magnet` main at `7bb105ab1c85bfaa01bf68c97ff7523332479ee4`;
- `aiq-magnet` `dev/aiq-evals-integration` at `b2311d2`, 19 commits ahead of
  the supplied main and directly based on it;
- `infer-stack` at `edbf6492b52a9e439a4c6d1336c4d4efbd106510`.

The MAGNET integration branch is important. It already implements most of the
scheduler/serving boundary this roadmap needs: `EvaluationNode`, preflight
measurement identity, content-aware reuse, a shared result store,
infer-stack leasing, per-role endpoint injection, Dockerized evaluation
workers, evidence projection, and real-GPU Inspect/OLMo acceptance tests.
Harbor should use that path rather than creating a separate scheduler.

## Verified upstream state

The following upstream facts were rechecked when this plan was written and
should be rechecked when implementation begins:

- Harbor latest stable release: `v0.23.0`, Python 3.12+.
- SWE-bench Pro V2: 642 validated tasks across 11 repositories, in Harbor task
  format under `v2/tasks/`.
- SWE-bench Pro V2 includes `HARD-51`, oracle/NOP validation, locked agents,
  per-phase network policy, patch capture, and fresh-sandbox patch replay.
- The Pro V2 reference instructions use Harbor with Modal and require a fresh
  patch-replay job for the authoritative score.
- Pro V2's locked mini-SWE agent can target an OpenAI-compatible endpoint via
  `OPENAI_API_BASE` / `OPENAI_API_KEY`.
- SWE-bench Verified remains a 500-task benchmark supported by the upstream
  `swebench` CLI and by `inspect-evals`.
- The upstream SWE-bench grader consumes prediction records with
  `instance_id`, `model_name_or_path`, and `model_patch` and performs grading
  in benchmark containers.
- Harbor stores per-job and per-trial structured results, verifier output, and
  trajectories. Current job output includes `config.json`, `result.json`, and
  trial directories with per-trial result/agent/verifier artifacts.

Useful upstream references:

- https://github.com/scaleapi/SWE-bench_Pro-os/blob/main/v2/README.md
- https://github.com/SWE-bench/SWE-bench/blob/main/docs/reference/cli.md
- https://github.com/harbor-framework/harbor
- https://www.harborframework.com/docs/tasks

Do not treat those URLs as immutable protocol definitions. Pin exact source
revisions in measurement identity and keep captured native artifacts.

---

## 1. Executive architecture decision

Use four layers with clear ownership:

```text
                      experiment / campaign layer
                            aiq-magnet
                                |
                 scheduling, matrix, reuse, evidence
                                |
                       EvaluationNode boundary
                                |
                     aiq-magnet-evals runtime
             +------------------+------------------+
             |                  |                  |
          Inspect             Harbor             other
       SWE-Verified       SWE-Pro V2        HELM / OLMo / ...
             |                  |
       native sandbox      native Harbor task
             |                  |
             +-------- model endpoint --------+
                                |
                           infer-stack
                  lease + serving provenance
                                |
                       local GPU / cluster
```

For repository benchmarks the scientifically important artifact is the patch,
not the agent's self-reported success. Keep the agent phase and authoritative
grading phase separate whenever the benchmark does.

For SWE-bench Pro V2 specifically:

```text
leased local model
       |
       v
locked Harbor agent
       |
       v
repository diff / model.patch
       |
       +-------------------------+
                                 v
                     pristine replay sandbox
                                 |
                                 v
                         authoritative reward
```

The first Harbor integration must be generic. Do not create a
`SWEProBackend`. Add a `harbor` evaluation engine, then add benchmark-specific
requests/recipes that preserve the upstream task tree and locked agent.

SWE-bench Verified does not need to block on Harbor. The shortest path is to
run its maintained Inspect task now, retain/export generated patches, and
cross-check the final score with the official SWE-bench grader.

---

## 2. Measurement classes: never collapse these into one leaderboard

We need named protocols because the same model can legitimately receive
multiple scores.

### 2.1 Publisher reproduction

Purpose: reproduce a published number as closely as possible.

Freeze the publisher's:

- benchmark revision;
- agent/scaffold;
- system prompt;
- sampling parameters;
- context policy;
- tools;
- turn/time budget;
- grading harness;
- number of attempts/epochs;
- model serving behavior where known.

Example: reproducing a Qwen SWE-Pro number reported with a Claude Code harness
is a different measurement from running the same weights through locked
mini-SWE-agent.

### 2.2 Controlled local model comparison

Purpose: determine what changed when weights or serving configuration change.

Hold fixed:

- benchmark snapshot;
- task selection;
- agent implementation and revision;
- agent config;
- system prompt/tool schema;
- environment provider and isolation policy;
- grader;
- generation policy;
- context/output budgets;
- concurrency policy where it can affect rate limiting or serving behavior.

Vary only the model/deployment under test.

This is the primary protocol for quantization and distillation research.

### 2.3 Infrastructure acceptance

Purpose: prove the stack works. The model need not solve the benchmark task.

Examples:

- Harbor can reach a leased endpoint;
- no unapproved network access is available to the agent;
- patch capture works;
- fresh-sandbox replay works;
- a tool result is actually executed;
- cleanup happens after cancellation.

Infrastructure acceptance results must not be presented as benchmark scores.

---

## 3. Core invariants

Implementation work is complete only if these remain true.

### I1. Native benchmark semantics remain native

`aiq-magnet-evals` may adapt Harbor, Inspect, or SWE-bench artifacts, but it
must not rewrite task semantics into a home-grown universal coding harness.

### I2. Patch is an authoritative intermediate artifact

For patch-based coding benchmarks, persist the exact generated patch/diff for
every instance. A score that cannot be connected back to the patch that was
graded is insufficient evidence.

### I3. Fresh grading means fresh grading

When Pro V2 says authoritative scoring is patch replay in a pristine sandbox,
the score in normalized results must come from that replay, not the possibly
contaminated agent container.

### I4. Model failure and infrastructure failure are different states

A wrong patch is a model failure. A missing image, broken network policy,
endpoint outage, verifier crash, or harness exception is infrastructure error.
Do not silently convert the latter into a zero benchmark reward.

### I5. Endpoint location is operational; model realization is scientific

`http://127.0.0.1:14042/v1` versus another reachable URL must not change
measurement identity.

The following can change model behavior and therefore must be captured in the
model/deployment identity:

- exact weight revision/artifact;
- quantization scheme and quantizer artifact;
- LoRA/adapters;
- chat template;
- inference engine and behavior-changing version/patch set;
- attention backend when numerically significant;
- KV-cache quantization;
- speculative/draft/MTP configuration;
- relevant custom launch arguments;
- context/output limits when they differ between compared runs.

### I6. Benchmark and agent source are immutable inputs

Pin benchmark repository commit, task-tree/checksum identity, Harbor version,
agent source/config, and grading implementation.

### I7. Offline means enforced offline

Do not infer compliance from "the prompt told the agent not to browse." For
Pro V2, the agent phase needs an enforced network policy that exposes only the
approved model endpoint and any explicitly permitted benchmark host.

### I8. Reuse may only cross operational differences

A stored result may be reused when only endpoint URL, temporary lease id,
worker path, or credential values change. A change in model realization,
benchmark task bytes, agent implementation, network policy, or grader must
invalidate reuse.

### I9. Native artifacts remain inspectable

Normalized metrics are an index into evidence, not a replacement for it.
Preserve Harbor jobs/trials, Inspect logs, patches, verifier output, and
upstream reports.

---

## 4. Existing stack capabilities to reuse

### 4.1 `aiq-magnet-evals`

Already present:

- engine-independent `EvaluationRequest`;
- `ModelBinding` with immutable `revision` / `cache_token` identity inputs;
- `ExecutionContext.model_endpoints`, explicitly operational;
- lazy backend registry;
- native worker isolation;
- cancellation and worker cleanup;
- content-keyed task/adapter identity;
- reusable result store and single-flight acquisition;
- normalized `MetricRecord`, `SampleRecord`, `ResultRecord`;
- native artifact retention/checksums;
- Inspect adapter with agentic/tool/sandbox support;
- engine-free result reading.

Do not replace those contracts to add Harbor.

### 4.2 `aiq-magnet` `dev/aiq-evals-integration`

Already present:

- generic `EvaluationNode`;
- request preflight before kwdagger node hashing;
- `measurement_identity` included in scheduling identity;
- validation of the stored run before `does_exist` succeeds;
- shared `aiq-magnet-evals` store;
- store acquisition lock around lease decision;
- no infer-stack lease when a reusable run already exists;
- per-role `endpoint` / `endpoints` leasing;
- endpoint URL injection only at execution time;
- verification that a leased alias serves the model name bound by the request;
- Dockerized node execution with `--network host` so the outer evaluation
  process can reach infer-stack's loopback gateway;
- real-GPU generation and agent acceptance paths.

Harbor should become another `engine` value handled by this same node.

### 4.3 `infer-stack`

Already present:

- endpoint catalog;
- model revisions and quantization fields;
- lease/acquire/access/run semantics;
- OpenAI-compatible LiteLLM front door;
- endpoint env descriptor;
- deployment compatibility identity;
- vLLM structural identity containing model source, revision, quantization,
  dtype, parallelism, image, chat template, adapters, attention backend,
  served name, placement pin, and custom launch identity;
- behavioral fingerprints for rendered services;
- readiness based on real generation, not container health;
- Compose and KubeAI backends.

Use these facts to derive serving provenance instead of asking evaluation
recipes to hand-maintain arbitrary strings forever.

---

## 5. Target `harbor` backend in `aiq-magnet-evals`

Add:

```text
magnet_evals/backends/harbor/
    __init__.py
    adapter.py
    normalize.py
    protocol.py          # only if native result parsing needs a focused helper
```

Register `harbor` in `magnet_evals/backends/registry.py`.

Add an optional dependency group after native acceptance selects the exact pin:

```toml
[project.optional-dependencies]
harbor = [
  "harbor==0.23.0",
]
```

Do not make Harbor a core dependency. Current Harbor requires Python 3.12+;
the worker boundary already exists to accommodate engine-specific Python.

### 5.1 Request mapping

Use the existing request fields rather than inventing a second schema.

Recommended generic mapping:

```json
{
  "schema_version": 1,
  "engine": "harbor",
  "task": "path:/abs/path/to/SWE-bench_Pro-os/v2/tasks",
  "task_revision": "<benchmark git sha>",
  "data_revision": "sha256:<task-tree-or-SHA256SUMS-digest>",
  "models": [
    {
      "role": "primary",
      "model": "qwen3.8-27b-q4_k_m",
      "provider": "openai",
      "revision": "<weight revision or immutable artifact digest>",
      "cache_token": "<serving provenance token>"
    }
  ],
  "task_options": {
    "agent": "python:locked_mini_swe:LockedMiniSwe",
    "agent_kwargs": {
      "config_file": "v2/tooling/configs/mini_toolcall.yaml"
    },
    "task_ids": ["..."],
    "environment": "docker",
    "n_concurrent": 1,
    "n_attempts": 1
  },
  "generation": {},
  "engine_options": {
    "job_options": {},
    "registration_modules": [],
    "required_secrets": ["OPENAI_API_KEY"]
  }
}
```

The exact user-facing spelling should be selected only after probing Harbor's
stable Python/CLI APIs at the pinned revision. Preserve these conceptual
separations:

- `task`: dataset/task collection identity;
- `task_options.agent`: agent/scaffold, therefore scientific identity;
- `task_options.environment`: execution/isolation behavior, therefore
  scientific identity for protocol-reproduction runs;
- concurrency/retry/attempt settings: identity when they change benchmark
  semantics;
- endpoint URL and secret values: operational only.

### 5.2 Avoid command-string identity

Do not make an opaque rendered `harbor run ...` shell command the primary
scientific input. Resolve it to structured native config, normalize it, and
include that structure in `ResolvedEvaluation.native_config`.

### 5.3 Resolve phase

`HarborBackend.resolve()` should:

1. verify Harbor imports at the tested pin;
2. resolve the task/dataset source;
3. verify task source revision/checksums;
4. resolve the agent implementation and source identity;
5. resolve the environment provider;
6. resolve agent/verifier network policy;
7. resolve task ids deterministically;
8. reject protected options that would bypass aiq-magnet-evals ownership of
   output/job directories or hidden extra runs;
9. produce path-free identity facts;
10. make the measurement non-reusable if task, agent, or engine identity cannot
    be established.

### 5.4 Execute phase

Prefer Harbor's supported Python API if it is sufficiently stable and exposes
cancellation cleanly. Otherwise use its CLI as the native API for the first
adapter, but keep the shell invocation inside the isolated worker and retain
all job artifacts.

Execution must:

1. create a native Harbor jobs root under the attempt's native directory;
2. inject the primary operational endpoint;
3. map the leased served-model name to Harbor's model argument;
4. supply credentials only through execution environment;
5. run the selected task ids;
6. retain stdout/stderr;
7. preserve per-trial result, agent, verifier, trajectory, and collected
   artifacts;
8. return a normalized result even when some trials errored;
9. fail the evaluation attempt when the native job itself is structurally
   invalid, while preserving diagnostics;
10. clean up owned Harbor/Docker resources on cancellation.

### 5.5 Normalize phase

Normalize at least:

- one `SampleRecord` per Harbor trial/attempt;
- task/instance id;
- epoch/attempt index;
- scalar verifier rewards;
- Harbor trial state;
- agent exception separately from verifier exception;
- token/usage facts where Harbor records them;
- trajectory, preferably ATIF when available;
- paths/references to `model.patch` and verifier output;
- job-level aggregate reward/success rate as `MetricRecord`s;
- coverage: expected, processed, successful native completion, errored.

Do not treat `reward == 0` as equivalent to `trial errored`.

### 5.6 Import phase

`import_results()` should accept an existing Harbor job directory and normalize
it without rerunning the agent. This is required for:

- migration of manually launched Harbor experiments;
- independent normalization regression tests;
- patch replay imports;
- debugging adapter changes against fixed native artifacts.

Content identity of imported job artifacts must participate in import identity,
using the existing aiq-magnet-evals import rules.

---

## 6. Harbor native evidence before implementation claims support

Create `docs/planning/harbor-evidence.md` and use the same evidence discipline
as the current Inspect/OLMo phases.

At the selected Harbor pin, capture these probes.

### H0-01 deterministic local task

Run a one-item local Harbor task using a deterministic/mock OpenAI-compatible
endpoint. Capture:

- job config;
- result;
- trial config/result;
- trajectory;
- verifier output;
- reward file;
- process exit behavior.

### H0-02 real OpenAI-compatible local endpoint

Run a small model through infer-stack and prove Harbor can call it.

This is transport acceptance, not a coding score.

### H0-03 agent tool execution

Use an agent that actually performs a shell/file/tool operation. Assert an
executed action appears in the trajectory, not just a tool declaration.

### H0-04 cancellation

Cancel a running Harbor task and verify:

- child process group termination;
- Harbor-owned containers removed or explicitly retained by configuration;
- no successful reusable run published;
- diagnostic artifacts survive.

### H0-05 partial failure

Run multiple tasks where one verifier or environment fails. Verify normalized
coverage and error classification.

### H0-06 import

Normalize the captured native Harbor job without Harbor execution and prove the
same scientific normalized result is obtained.

### H0-07 network policy matrix

This is a release blocker for SWE-Pro work.

Prove on the actual Linux host/kernel:

- `public` baseline behaves as expected;
- `no-network` denies external egress;
- `allowlist` denies an unlisted host;
- the model endpoint is reachable when explicitly allowed;
- a phase policy change is actually enforced, not merely accepted by config;
- verifier policy matches the benchmark's intended fresh-grading phase.

Record the exact Harbor environment capabilities reported by the pinned build.
Harbor's Docker network-policy support is conditional on environment/kernel
capability and has changed recently; documentation and implementation have
not always moved in lockstep.

---

## 7. The nested-container endpoint problem

The existing MAGNET `EvaluationNode` solves the outer-container problem by
running the node with Docker host networking. Harbor then creates its own task
containers, so `127.0.0.1` inside those containers no longer means the host.
This needs an explicit design rather than accidental connectivity.

### 7.1 Desired property

A Harbor agent sandbox should be able to reach exactly the leased model front
door while still being denied arbitrary internet access during the agent
phase.

### 7.2 Preferred solution

Add a small, tested **Harbor endpoint bridge** at the aiq-magnet-evals/Harbor
boundary rather than changing the public infer-stack API.

Candidate implementation on Linux Docker:

1. infer-stack keeps publishing LiteLLM on the host port it already manages;
2. the outer EvaluationNode receives `OPENAI_BASE_URL` as today;
3. the Harbor adapter converts only the operational sandbox URL from host
   loopback to a sandbox-reachable host-gateway address;
4. Harbor's task environment receives an explicit host mapping / network
   route, not unrestricted host networking;
5. the agent-phase allowlist permits only that gateway address/hostname;
6. the verifier receives the network policy required by the benchmark;
7. the original endpoint URL remains excluded from measurement identity;
8. the actual network policy and resolved bridge target are recorded as
   execution diagnostics.

Do not bind a new unauthenticated model server to the LAN.

### 7.3 Spike alternatives in order

Test these, in order, and stop at the first solution that preserves policy:

1. Harbor Docker's current host-gateway/extra-compose extension points.
2. A tiny custom Harbor Docker environment subclass in aiq-magnet-evals that
   adds `host.docker.internal -> host-gateway` while preserving Harbor's egress
   sidecar.
3. A loopback-to-Docker-bridge relay owned by the evaluation attempt and torn
   down with it.
4. Only if the above fail, an infer-stack feature that publishes a narrowly
   scoped sandbox-access URL bound to an explicit local bridge/interface.

Using `--network host` for the Harbor agent container is not an acceptable Pro
V2 default because it gives the sandbox much broader host reachability and
interacts poorly with network-policy claims.

### 7.4 Protocol labeling

Until local Harbor execution proves equivalent isolation to the Pro V2 locked
protocol, report results as:

`SWE-bench Pro V2 / local-harbor protocol`

not as an official-protocol reproduction.

A protocol may be promoted to `pro-v2-compatible` only after the oracle/NOP,
network, fresh-replay, and patch-integrity gates all pass.

---

## 8. infer-stack serving provenance handshake

The current MAGNET integration verifies that an infer-stack alias serves the
expected model *name*. That is necessary but not enough for quantization
benchmarking: two endpoints can expose the same served name while changing
quantization, revision, chat template, attention backend, or custom launch
arguments.

Do not rely on a person remembering to update `ModelBinding.cache_token`.

### 8.1 Add a scientific serving provenance token

Implement a stable infer-stack helper that describes behavior-relevant serving
identity without endpoint location, lease id, or GPU placement noise.

Suggested data:

```json
{
  "schema": "infer-stack-serving-provenance/1",
  "engine": "vllm",
  "model_ref": "...",
  "model_revision": "...",
  "quantization": "...",
  "dtype": "...",
  "image": "...",
  "chat_template": "...",
  "lora_adapters": [],
  "attention_backend": "...",
  "launch": {
    "command": [],
    "extra_args": [],
    "env": {}
  },
  "capacity": {
    "max_model_len": 65536
  }
}
```

Hash the canonical representation and expose both payload and digest.

Do not directly reuse `compatibility_key` as the scientific token without
review. The current compatibility key intentionally includes some deployment
placement facts and intentionally handles capacity separately because it was
designed for coalescing, not scientific measurement provenance.

### 8.2 Descriptor support

Extend the infer-stack endpoint descriptor with per-alias provenance, for
example:

```json
{
  "endpoints": {
    "qwen-local": {
      "model": "qwen3.8-27b",
      "serving_provenance": "sha256:..."
    }
  }
}
```

Preserve the existing shell variables for compatibility. Add a machine-readable
JSON descriptor path rather than exploding the entire provenance payload into
environment variables.

### 8.3 MAGNET preflight projection

On an `EvaluationNode` with `perf_params.endpoint` / `endpoints`:

1. resolve the infer-stack catalog alias without acquiring a GPU lease;
2. obtain its scientific serving provenance digest;
3. bind that digest into the effective model identity used for preflight;
4. include it in kwdagger's node identity;
5. at execution, compare the leased descriptor's provenance with the scheduled
   provenance before model inference begins;
6. exit with the existing "identity changed; reschedule" behavior on mismatch.

Prefer projecting the digest into `ModelBinding.cache_token`, because
`aiq-magnet-evals` already gives that field the correct semantic role.

Rules:

- if the recipe supplies an explicit immutable cache token, either verify it
  against infer-stack provenance or require an explicit opt-out;
- never silently overwrite a conflicting user assertion;
- endpoint URL remains operational and excluded from identity;
- model served-name equality remains checked as a separate safety condition.

### 8.4 Acceptance

A test must prove:

1. run Q4 endpoint -> result A;
2. change same alias to Q5 with same served model name;
3. compile same MAGNET recipe;
4. node identity changes before execution;
5. stale Q4 result is not reused;
6. a lease acquired after scheduling cannot substitute a different Q5/Q4
   realization without being rejected.

This is one of the most important gates in the entire roadmap.

---

## 9. SWE-bench Verified implementation path

Verified can land before Harbor.

### V1. Pin the maintained Inspect task

Add an `inspect-evals` worker environment at an exact tested version/revision
that is compatible with the pinned Inspect runtime.

Do not add `inspect-evals` to core dependencies. Either add an explicit worker
extra or maintain the worker lock used by native acceptance.

### V2. Canonical request/example

Add a repository example such as:

`examples/swebench_verified_request.json`

It should freeze:

- `princeton-nlp/SWE-bench_Verified` / current canonical dataset id;
- test split;
- exact dataset revision;
- Inspect task reference;
- sandbox type;
- internet policy;
- message/turn limit;
- tool timeout;
- generation policy;
- model identity.

### V3. Patch export

Implement an engine-free helper that exports the generated patches from a
published Inspect run into upstream SWE-bench predictions JSONL.

Proposed command:

```text
aiq-magnet-evals swebench export-predictions RUN_DIR --output preds.jsonl
```

This helper must fail if an expected instance lacks an unambiguous patch. It
must record which native sample/log supplied each patch.

### V4. Official regrade acceptance

For every release candidate of the Verified integration:

1. export predictions;
2. run upstream `swebench eval verified` at a pinned upstream revision;
3. compare per-instance verdicts with Inspect's normalized scoring;
4. investigate every disagreement;
5. keep upstream `report.json` / results artifacts.

For the first release this can be an acceptance script rather than a generic
new post-grader contract.

### V5. Decide whether a native `swebench` backend is justified

Only after V4 gives concrete artifact requirements, decide whether to add a
first-class `swebench` backend for official grading/import.

Add it if we need cached/normalized official regrades as ordinary
`EvaluationRequest`s. Do **not** add a generic postprocessing framework merely
because one benchmark has a second grading phase.

### V6. Verified sanity gates

Before spending model tokens:

- `swebench eval verified --gold` passes at the pinned upstream revision;
- a known empty/broken patch fails;
- 5 fixed smoke tasks complete;
- 25-50 frozen screening tasks complete;
- all 500 are run only for finalists.

---

## 10. SWE-bench Pro V2 implementation path

### P0. Vendor nothing prematurely

Clone/pin the upstream Pro V2 repository for acceptance work. Keep the upstream
task tree external at first. Do not copy 642 task directories into
`aiq-magnet-evals`.

Record:

- repository commit;
- `v2/SHA256SUMS` digest;
- Harbor pin;
- locked agent source digests;
- config file digests;
- image names/digests where obtainable.

### P1. Oracle and NOP

Before any local model run, reproduce upstream V2 sanity behavior:

- oracle: 642/642 resolved;
- NOP: 0/642 resolved.

Start with HARD-51 and a small sample during development, but a release claim
for complete V2 support requires the full gate.

If local Docker and official Modal produce different verifier outcomes on
oracle/NOP, stop and resolve the environment discrepancy before model testing.

### P2. Locked mini-SWE local endpoint

Use the upstream locked mini-SWE implementation unchanged except for supported
runtime arguments that point it at the leased OpenAI-compatible model endpoint.

Do not fork the agent just to make local inference convenient. If a fork is
required, its source digest becomes a distinct protocol and score label.

### P3. Patch capture

Verify every trial yields a patch artifact or an explicit reason no patch could
be produced. Hash every patch.

Normalized sample metadata should include:

- instance id;
- source trial id;
- agent completion state;
- patch SHA256;
- patch artifact path;
- pre-replay reward if present, clearly labeled non-authoritative;
- infrastructure exception if any.

### P4. Fresh patch replay

Implement the Pro V2 authoritative flow as **two Harbor jobs**:

1. locked agent generation;
2. upstream `patch_replay:PatchReplayAgent` over the source job.

Do not normalize the generation job's verifier reward as the headline Pro V2
metric when V2's protocol says the replay is authoritative.

The replay job must reference source patches by content and trial id; the
normalized result should retain both generation and replay provenance.

### P5. Represent generation + replay without making Harbor Pro-specific

Keep the registered `harbor` backend generic. Do **not** teach its public
request mapping a Pro-only magic value such as
`task_options.regrade = "fresh_patch_replay"`.

Instead, add a small benchmark profile/orchestrator adjacent to the generic
backend, for example:

```text
magnet_evals/benchmarks/swe_bench_pro.py
```

That profile should use the Harbor adapter's one-native-job execution helper to
perform, within one aiq-magnet-evals attempt:

1. the locked agent generation job;
2. the upstream fresh `patch_replay:PatchReplayAgent` job against that exact
   generation job;
3. a content/provenance join of replay trials back to generation trials.

The resulting native artifact tree contains two sibling Harbor job directories.
The normalized samples use replay reward as the authoritative benchmark result,
while retaining generation diagnostics and the exact patch under each sample's
`native` data.

This preserves two properties at once:

- Harbor remains reusable for arbitrary Harbor datasets and agents;
- Pro V2's two-job grading protocol remains one scientific measurement rather
  than forcing MAGNET to schedule 1,284 model-independent evaluation nodes.

The profile must also support importing the generation and replay jobs
separately for debugging/normalization regression tests. The generic Harbor
adapter itself should remain unaware of SWE-bench Pro task semantics.

### P6. HARD-51 screening profile

Add a canonical profile/request for `HARD-51`. This is a screening protocol,
not a substitute for the 642-task result.

Use it for:

- quantizer development;
- inference-server changes;
- agent config changes;
- regression triage.

### P7. Full 642 profile

Only run full V2 after:

- Harbor backend conformance passes;
- endpoint provenance is immutable;
- network isolation passes;
- HARD-51 is stable;
- oracle/NOP gates pass;
- patch replay parity is established.

---

## 11. Harbor adapter identity design

The Harbor adapter's measurement identity must include at least:

- Harbor version/revision;
- adapter source digest;
- benchmark task source digest/revision;
- selected task ids;
- agent class/source revision;
- agent kwargs/config file content digest;
- verifier/task configuration;
- environment provider;
- network policy;
- attempt count;
- generation parameters;
- model binding revision/cache token;
- benchmark-owned replay policy;
- any runtime option that changes agent-visible behavior.

It must exclude:

- job directory path;
- temporary job name if semantically irrelevant;
- endpoint URL;
- lease id;
- secret value;
- temporary worker path;
- stdout/stderr destination path;
- Docker container names.

### 11.1 Agent source identity

For `python:module:Class` agents, hash the importable source package/file in the
same spirit as current Inspect task source hashing.

For built-in Harbor agents, include Harbor revision plus structured agent name
and config. If Harbor allows external executable agents whose implementation
cannot be identified, mark the measurement non-reusable unless the request
supplies an immutable agent revision.

### 11.2 Config-file identity

Never put a mutable path alone into identity. Hash config bytes and retain the
path only as a resolved diagnostic.

### 11.3 Benchmark tree identity

For Pro V2, prefer the upstream repository commit plus verified
`v2/SHA256SUMS`. Verify the checksums before run. If bytes differ, resolution
fails rather than silently creating a different benchmark with the old label.

---

## 12. Result/error model hardening

The current `ExecutionStatus` is run-level: `succeeded`, `failed`, `cancelled`,
`incomplete`. Keep it unless native evidence proves a schema change is needed.
Do not rush to add `errored` globally.

Instead, for Harbor trials encode per-sample execution facts under structured
sample/native data, e.g.:

```json
{
  "trial_status": "errored",
  "agent_error": null,
  "environment_error": "image pull failed",
  "verifier_error": null,
  "reward": null,
  "counted_as_model_failure": false
}
```

Aggregate metrics must state denominators and infrastructure-error counts.

For a headline benchmark metric, require a coverage policy. Recommended
quantization campaign default:

- full expected task set present;
- no infrastructure errors;
- every task has an authoritative verdict;
- otherwise score is marked ineligible rather than treating missing tasks as
  ordinary failures.

MAGNET already has coverage policy/evidence eligibility machinery; extend
normalization to give it the facts it needs.

---

## 13. MAGNET work

Most MAGNET work should happen on top of `dev/aiq-evals-integration`, then land
that branch before depending on it in benchmark recipes.

### M-H1. Land/reconcile existing integration branch

Before Harbor-specific changes:

- review and merge the existing 19-commit integration series;
- preserve its real-GPU acceptance gate;
- preserve lease-under-store-lock semantics;
- preserve preflight resolution in the same execution environment as the node.

Harbor work should not be developed against main as though these capabilities
do not exist.

### M-H2. Harbor example recipe

Add a small Harbor recipe after the backend exists. It should demonstrate:

- generic Harbor engine;
- Dockerized evaluator worker;
- infer-stack primary endpoint lease;
- successful native artifact projection;
- no benchmark-specific MAGNET logic.

### M-H3. Pro V2 recipes

Add separate recipes/profiles for:

- 5-task smoke;
- HARD-51;
- full V2;
- deterministic quantization comparison;
- publisher-reproduction configuration when known.

Do not put all protocol variants into one matrix whose output rows are easy to
compare as though they were identical measurements. Include an explicit
protocol label column.

### M-H4. Serving provenance preflight

Implement the infer-stack provenance projection described in section 8.

### M-H5. Comparison nodes

Add/report paired comparison output by instance id:

- both fail;
- A only succeeds;
- B only succeeds;
- both succeed;
- absolute resolution-rate difference;
- paired bootstrap interval;
- McNemar statistic/p-value when meaningful;
- infrastructure errors excluded and reported separately.

Do not rank two quants from aggregate percentages alone when per-instance
pairing is available.

### M-H6. Campaign metadata

Every campaign output should retain:

- protocol name/version;
- benchmark revision;
- agent revision;
- model serving provenance;
- task set digest;
- random seed(s) when applicable;
- attempt count;
- wall clock;
- token usage where available;
- peak/runtime telemetry when separately captured.

---

## 14. infer-stack work

### I-H1. Serving provenance API

Add a dependency-light package API and CLI/JSON view that resolves a catalog
alias to scientific serving provenance without acquiring a lease.

Example conceptual CLI:

```text
infer-stack catalog endpoint provenance qwen-local --json
```

Exact command spelling is not important; stable structured output is.

### I-H2. Lease descriptor provenance

Include the same digest in access/acquire/run descriptors so runtime can verify
what was actually leased.

### I-H3. Sandbox reachability probe

Add a diagnostic command/helper that reports a host-gateway URL suitable for a
local Docker sandbox **only when it is safe and reachable**. Do not make this
the normal client URL.

If the Harbor adapter can solve reachability without an infer-stack change,
skip I-H3.

### I-H4. Benchmark-serving catalog examples

Document recommended endpoint fields for local evals:

- immutable HF/model revision;
- explicit quantization;
- explicit dtype;
- chat template identity;
- context window;
- KV-cache flags;
- speculative/MTP flags;
- tool-call parser flags where an agent needs them;
- reclaim policy suitable for campaigns.

### I-H5. No serving-policy mutation inside the evaluator

The evaluation package may request/lease an alias. It should not patch the
catalog on the fly to enable tool calling or change quantization. If a distinct
runtime configuration is required, it gets a distinct alias/provenance token.

The current MAGNET real-GPU acceptance test creates a temporary tool-enabled
alias for infrastructure testing. That pattern is acceptable for a test
fixture, not for scientific benchmark identity.

---

## 15. Local consumer-GPU campaign design

The benchmark runner and the model server contend for different resources:
Harbor task containers are mostly CPU/disk/network while the model uses the
GPU. Avoid high Harbor concurrency merely because the host has many CPU cores.
A single 3090 model server can become the bottleneck and queuing behavior can
change wall-clock/timeout outcomes.

### 15.1 Default campaign concurrency

Start with:

- one model deployment;
- one Harbor agent trial at a time for deterministic baseline;
- then measure safe concurrency 2/4 if the server and agent protocol tolerate
  it without timeout/rate-limit effects.

Record concurrency in measurement identity for benchmark protocols where it
can affect timeouts or server scheduling.

### 15.2 Context budget

Do not infer effective context from the model card. Record the context budget
the serving endpoint actually exposes and the agent actually requests.

For a 24 GB quantization campaign, differences such as Q8 KV versus Q4 KV can
change available context and potentially outputs. Treat such configuration as
part of serving provenance or run a separately named protocol.

### 15.3 Timeouts

Use independent budgets for:

- environment setup;
- agent execution;
- model request;
- verifier;
- whole trial;
- whole job.

Do not increase one global timeout until failures disappear. Preserve which
boundary fired.

### 15.4 Cost accounting

For each sample retain if available:

- prompt/input tokens;
- generated/reasoning tokens;
- cached tokens;
- model wall time;
- total agent wall time;
- number of model calls;
- number of shell/tool calls.

For local serving also collect campaign-level:

- steady generation tok/s;
- TTFT if available;
- peak VRAM;
- model load time;
- endpoint restarts.

Keep performance telemetry out of the correctness score.

### 15.5 Docker image and disk-cache policy

Repository benchmarks can pull/build many large images. Disk exhaustion must be
an explicit infrastructure state, not a late campaign surprise.

Before full runs:

1. inventory free bytes and inodes on the Docker data root and Harbor jobs root;
2. measure the actual cached size of the Verified and Pro task images used by
   the pinned task set;
3. define a minimum-free-space gate before starting a new trial;
4. use one shared read-only image cache where the native engines support it;
5. never run broad `docker system prune` from a benchmark worker;
6. make job-artifact retention/cleanup explicit and content-addressed;
7. retain patches, results, trajectories, verifier logs, and provenance even
   when bulky transient build layers are reclaimed;
8. classify ENOSPC/image-pull/build-cache failures as infrastructure errors.

Add a campaign preflight report containing Docker-root free space, jobs-root
free space, relevant image ids/digests, and cache-policy version.

### 15.6 Untrusted repository-code boundary

Treat benchmark repositories and their tests as untrusted code.

For Harbor/Verified task containers:

- do not mount the Docker socket;
- do not mount the evaluator's home directory or source checkout writable;
- expose only task-scoped work/artifact paths required by the native engine;
- keep credentials out of repository-visible files;
- provide the model credential only through the benchmark's intended agent
  process/environment boundary;
- deny host/LAN reachability except the explicitly tested model-endpoint bridge;
- preserve Harbor/SWE-bench resource limits rather than silently granting
  privileged mode to make a task pass;
- record any required capability or mount exception as protocol identity.

A benchmark result is ineligible if the evaluator had to weaken sandbox
isolation manually for an individual task.

---

## 16. Staged benchmark policy

Do not immediately run 1,142 expensive tasks for every quant.

### Stage A - zero-model infrastructure

- Verified gold grader;
- Pro oracle;
- Pro NOP;
- patch replay;
- network denial probes.

### Stage B - five fixed tasks

Purpose: transport, editing, patch capture, cleanup.

### Stage C - frozen screening sample

Select before comparing quants. Store ids in-repo.

Recommended:

- 50-100 Verified tasks stratified by repo/difficulty where metadata permits;
- Pro HARD-51.

Never tune the subset after seeing which quant wins individual tasks.

### Stage D - full Verified

500 tasks for finalists.

### Stage E - full Pro V2

642 tasks for finalists.

### Stage F - stochastic replication

For close configurations or nonzero-temperature publisher protocols, repeat
with explicit seeds/attempts. Report per-task paired outcomes and uncertainty.

---

## 17. Statistical comparison

For two model realizations A/B run on the same tasks, compute the paired table:

```text
                         B
                   fail      pass
A fail              n00       n01
  pass              n10       n11
```

Report:

- A resolution rate;
- B resolution rate;
- paired difference;
- `n01` and `n10` explicitly;
- paired bootstrap confidence interval;
- McNemar exact/asymptotic test as appropriate;
- task count with infrastructure error for either configuration.

Do not pretend the benchmark has a useful independent-Bernoulli confidence
interval when the stronger paired comparison is available.

For multiple attempts per task, specify the aggregation rule in advance:
pass@1, majority, any-pass, mean reward, etc. Do not change it after results.

---

## 18. Test plan

### `aiq-magnet-evals` unit tests

Add at minimum:

- Harbor request validation;
- unknown/protected option rejection;
- lazy dependency behavior;
- task source hashing;
- agent source/config hashing;
- operational endpoint removal from identity;
- network policy included in identity;
- native result parsing fixtures;
- trial error != zero reward;
- import parity;
- cancellation fallback;
- path-independent measurement identity;
- benchmark checksum mismatch refusal.

### `aiq-magnet-evals` native tests

Markers:

- `native`;
- `docker_sandbox`;
- optionally `external` for upstream image pulls;
- `gpu` only for the leased-local-model acceptance test.

Add CI/local scripts analogous to current native engine scripts:

```text
dev/ci/native_harbor.sh
dev/ci/swebench_verified.sh
dev/ci/swebench_pro_v2_smoke.sh
```

Do not require a 642-task Pro run in ordinary hosted CI.

### `aiq-magnet` tests

- Harbor request compiles through `EvaluationNode`;
- worker environment only exists in container;
- preflight identity includes Harbor adapter/task/agent source;
- reusable Harbor result skips lease;
- missing run acquires exactly one lease under concurrency;
- endpoint provenance change invalidates node identity;
- runtime provenance mismatch requests reschedule;
- sample/metric projection remains one evidence row per configured selector;
- Harbor infrastructure error yields ineligible evidence, not a fake zero.

### `infer-stack` tests

- serving provenance deterministic;
- operational host/GPU/lease changes do not change scientific provenance;
- quantization/revision/chat-template/KV/speculative changes do;
- descriptor includes matching provenance;
- old descriptors remain readable;
- alias mutation between schedule and acquire is detectable.

---

## 19. Implementation phases and acceptance gates

### Phase 0 - upstream capture and design probes

Owner: `aiq-magnet-evals`

- [ ] Pin Harbor candidate version and revision.
- [ ] Capture Harbor job/trial fixture.
- [ ] Capture network-policy behavior on local Docker.
- [ ] Pin Inspect-Evals/SWE-bench versions for Verified.
- [ ] Pin Pro V2 repository revision/checksums.
- [ ] Prove local sandbox can reach infer-stack without broad internet access.
- [ ] Decide Harbor Python API versus CLI worker implementation.

Gate: no core implementation before result layout, cancellation, and network
policy are evidenced.

### Phase 1 - generic Harbor backend

Owner: `aiq-magnet-evals`

- [ ] registry entry and optional dependency;
- [ ] request validation;
- [ ] resolution/identity;
- [ ] execute;
- [ ] normalization;
- [ ] import;
- [ ] cancellation/cleanup;
- [ ] native conformance fixture;
- [ ] engine-free result load.

Gate: deterministic and real-endpoint Harbor tasks pass the same backend
conformance expectations as Inspect/OLMo where applicable.

### Phase 2 - infer-stack provenance

Owners: `infer-stack`, `aiq-magnet`

- [ ] provenance schema/digest;
- [ ] catalog query;
- [ ] lease descriptor emission;
- [ ] MAGNET preflight projection;
- [ ] runtime verification;
- [ ] quantization mutation test.

Gate: same alias changing Q4 -> Q5 cannot reuse the old measurement.

### Phase 3 - SWE-bench Verified

Owner: `aiq-magnet-evals`

- [ ] pinned Inspect-Evals worker;
- [ ] canonical request;
- [ ] patch export;
- [ ] upstream official regrade acceptance;
- [ ] frozen smoke/screening ids;
- [ ] MAGNET example recipe.

Gate: per-instance Inspect verdict and official grader verdict agree on the
acceptance fixture or every discrepancy is understood/documented.

### Phase 4 - Pro V2 local protocol

Owners: `aiq-magnet-evals`, `aiq-magnet`

- [ ] oracle/NOP;
- [ ] locked mini-SWE agent against leased local model;
- [ ] enforced agent allowlist;
- [ ] exact patch capture;
- [ ] fresh patch replay;
- [ ] joined normalized samples;
- [ ] HARD-51 profile;
- [ ] infrastructure-error eligibility.

Gate: HARD-51 end to end with no policy bypass.

### Phase 5 - Pro V2 full and protocol parity

- [ ] full oracle 642/642;
- [ ] full NOP 0/642;
- [ ] full local-model run;
- [ ] replay coverage 642/642 or explicit infrastructure failure;
- [ ] compare local Docker environment with upstream documented Modal protocol;
- [ ] document whether result is `local-harbor` or `pro-v2-compatible`.

Gate: publishable benchmark provenance bundle.

### Phase 6 - quantization/distillation campaign layer

Owners: all three repos, MAGNET primarily

- [ ] protocol-named recipes;
- [ ] model endpoint matrix;
- [ ] frozen screening set;
- [ ] paired comparison report;
- [ ] resource/usage telemetry;
- [ ] full-run promotion rules;
- [ ] artifact summary suitable for a model-card table.

Gate: one end-to-end comparison of at least three realizations of the same base
model without manual edits between runs.

---

## 20. Concrete first campaign

Use one model family to prove the methodology before comparing unrelated
models.

Suggested campaign:

```text
Qwen3.8-27B
    Q8 / high-quality reference if feasible
    Q5_K_M
    Q4_K_M
    IQ4_XS or equivalent
    one optimized serving/repack variant
```

Run in this order:

1. five-task Verified smoke;
2. frozen Verified screening set;
3. HARD-51;
4. full Verified for surviving variants;
5. full Pro V2 for the top 2-3 variants;
6. replicate close calls.

This yields the missing evidence public quant repositories usually do not
provide: capability loss relative to weight/serving compression under the same
agent protocol.

---

## 21. Deliverables

### `aiq-magnet-evals`

- generic Harbor backend;
- Harbor evidence ledger;
- Verified example/profile and patch exporter;
- Pro V2 smoke/HARD/full profiles;
- Pro patch replay normalization;
- native regression fixtures;
- release-gate additions;
- user documentation for protocol labels and artifact interpretation.

### `aiq-magnet`

- landed `dev/aiq-evals-integration` functionality;
- Harbor recipes;
- infer-stack serving provenance projection;
- paired model comparison report/node;
- real-GPU Harbor acceptance script.

### `infer-stack`

- scientific serving provenance schema/digest;
- descriptor integration;
- endpoint provenance inspection API/CLI;
- optional sandbox reachability helper if Harbor cannot bridge safely on its
  own.

---

## 22. Explicit non-goals

Do not turn this project into:

- a new universal coding-agent framework;
- a fork of Harbor;
- a fork of SWE-bench Pro task definitions;
- an alternative repository patch grader;
- a second GPU scheduler next to infer-stack;
- a score-normalization layer that claims different agent scaffolds are
  directly comparable;
- an automatic benchmark subset optimizer;
- a system that treats every missing task as model failure;
- a system that mutates serving configs during a scientific run without
  changing identity.

---

## 23. Review checklist before implementation starts

A reviewer should be able to answer "yes" to each:

- [ ] Harbor is a generic engine, not Pro-specific glue.
- [ ] Pro V2 generation and authoritative replay are distinct native phases.
- [ ] Verified can proceed independently through Inspect.
- [ ] The exact patch graded is retained.
- [ ] Network isolation is tested, not assumed.
- [ ] Local nested containers have a narrowly scoped path to the leased model.
- [ ] Serving quantization/configuration is part of measurement identity.
- [ ] Endpoint URL and lease id are not part of measurement identity.
- [ ] Existing MAGNET single-flight/lease behavior is reused.
- [ ] Existing infer-stack scheduling is reused.
- [ ] Infrastructure failures cannot silently depress model scores.
- [ ] Benchmark, agent, and grader revisions are pinned.
- [ ] Screening subsets are frozen before model comparisons.
- [ ] Final comparisons use per-instance paired statistics.
- [ ] Publisher reproduction and controlled-quant protocols have different
      names and are never mixed in one ranking column.

When these are true, the stack will support both leaderboard reproduction and
the more valuable local question: whether a particular quantization,
distillation, or serving optimization preserved agentic software-engineering
capability.
