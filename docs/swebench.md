# SWE-bench experimental protocols

SWE-bench Verified uses the maintained Inspect-Evals task and scorer in an
isolated worker. The native acceptance currently covers the five instances in
`dev/environments/swebench-verified-images.json`, with gold oracle patches and
NOP predictions. It does not establish support for all 500 instances or report
real-model performance. Pins and observed limits are in
[the evidence ledger](planning/harbor-evidence.md).

Run the Docker-only acceptance with:

```bash
dev/ci/swebench_verified_acceptance.sh
```

The script installs Inspect 0.3.272, the pinned Inspect-Evals checkout and
SWE-bench 3.0.15 under the recorded Python 3.12 constraints, then pulls immutable
image digests. Each acceptance runs in a fresh store. Official grading uses a
local JSON snapshot of the same pinned dataset rows and fresh containers.

Start a model request from `examples/swebench_verified_request.json`. Replace
the served model name and add its immutable `revision` or `cache_token` before
using result reuse. Supply the endpoint and credentials operationally through
the existing runner/worker interface. The example deliberately leaves the model
realization unresolved. Its fixed agent protocol uses temperature 0, output
limit 4096, message limit 30 and one sandbox at a time.

Before the agent runs, the task resets the repository to the dataset's exact
base commit and removes untracked files with `git clean -fd`. This explicit
`git-reset-clean/v1` protocol avoids capturing pre-existing build files or mode
changes from benchmark images. The agent, scorer and grader remain upstream.
The task uses a public ComposeConfig rather than a shared per-instance YAML
cache and disables sandbox Internet access.

Export actual scored patches from a completed run:

```bash
aiq-magnet-evals swebench export-predictions /path/to/run \
  --output predictions.jsonl
```

The official JSONL contains `instance_id`, `model_name_or_path` and
`model_patch`. Its adjacent provenance file records run/artifact identity,
native sample UUIDs and patch checksums. Empty patches are preserved; missing
captures, native errors, ambiguous repeated epochs and invalid diffs are refused.
The exporter never substitutes the dataset's gold patch for a missing model
patch. It verifies the source bundle before writing.

`dev/environments/swebench-verified-selection.json` freezes the five-instance
smoke and a deterministic 25-instance screening selection before any model
comparisons. Only the smoke set has runtime evidence and image pins. Screening
execution needs its remaining images pinned and its offline verifier behavior
validated first. Some unselected Requests instances require Internet access
even with the gold patch; their offline capability remains unverified.

## SWE-bench Pro V2 with Harbor

Pro V2 uses the generic `harbor` engine with
`python:magnet_evals.benchmarks.swe_bench_pro:ProV2Protocol` as its execution
protocol. One owned worker runs generation and a separate native fresh-replay
job. The normalized reward comes exclusively from replay. Both jobs, exact
patch, source/replay UUIDs, verifier output, trajectory and observed sandbox
image remain in the bundle.

```bash
dev/ci/swebench_pro_v2_smoke.sh
```

Candidates are Pro V2 `66f92766bba642462d4bbe5479e83f91f9211862`, Harbor
0.23.0 and locked mini-SWE 2.4.6. This is a `local-harbor` protocol; it does
not claim Modal parity or publisher scores. Only ledger cells have native
acceptance.

`profile_request(source, profile, model, image_ids)` in
`magnet_evals.benchmarks.swe_bench_pro` creates standard EvaluationRequests for
`smoke`, `hard51` or `full`. HARD-51's 51 ids are preserved from pinned upstream
and included in the wheel. Full selects 642 task directories. Definitions are
not runtime evidence. Every selected physical image ID must be supplied. The
profile validates SHA256SUMS and checks owned container images after setup,
before inference. Setup/verifier networking stays public; the agent can reach
the named model relay under the native sidecar policy.

The locked agent and replay code remain upstream. The profile gives upstream
first-match replay an unambiguous view of unchanged results and patch bytes.
One attempt per instance is supported. Missing captures are errors; actually
empty patches remain valid failed predictions. Missing parser output or
ambiguous required-test coverage withholds a complete aggregate while retaining
the original reward and diagnostics.

Paired trees can be imported with the same Harbor request and `import_source`.
Imports verify observed generation model/task facts and patch joins, preserve
both phases, and remain separate from canonical executions. They do not attest
source/runtime revision assertions.

Mini-SWE's version does not freeze managed Python, dependencies or setup
downloads. Observed runtime versions are retained and its requested version is
checked, but these runs remain nonreusable until the entire runtime is pinned.
Plain Harbor mutable images/builds also remain nonreusable; digest-pinned
images or protocol-enforced physical image pins are required for reuse.

## Acceptance and remaining integration

```bash
dev/ci/swebench_vm_acceptance.sh
```

The CPU/Docker command reports engine-free, Harbor, Verified, Pro, serving
provenance and MAGNET gates. It retains JUnit/native captures, rejects skipped
required checks and fails when a required integration is unavailable. MAGNET
must supply its fake-lease hook at `dev/ci/swebench_vm_acceptance.sh` on the
EvaluationNode integration branch. The available legacy checkout lacks it.
The recorded 2026-10-05 run passed the other six gates and failed this required
MAGNET gate; its report and JUnit evidence are in
`docs/planning/evidence/swebench-vm-2026-10-05`.

The GPU script is implemented for a later GPU host and has not been run:

```bash
AIQ_GPU_ALIAS=<managed-alias> AIQ_VM_REPORT=/path/to/passing/report.json \
  dev/ci/swebench_gpu_acceptance.sh
```

It verifies VM/source fingerprints, queries preflight provenance, acquires one
owned infer-stack lease, checks its descriptor, and runs the synthetic coding
task, fixed Verified smoke/official grading and one Pro generation/replay task.
It releases only its lease on exit and verifies release and Harbor cleanup.
It launches no HARD-51/full run. Immutable configured provenance is required;
infer-stack reports configured facts rather than attesting weight files or
hardware. MAGNET provenance projection/rescheduling and fake-lease acceptance
remain unfinished until the referenced integration checkout is available.
