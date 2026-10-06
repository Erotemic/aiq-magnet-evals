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
