# Initial CPU/Docker acceptance: PASS

Command: `dev/ci/swebench_vm_acceptance.sh`, on the Docker VM, 2026-10-06.
The unmodified `report.json` records seven passing gates and all 17 independent
checks, with exact JUnit case bindings, evidence checksums and source fingerprints.
`capture.json` identifies the committed source revisions and retained file hashes.

| Gate | Result | Seconds |
| --- | --- | --- |
| Engine-free | 238 passed; 4 absent-engine skips | 10.17 |
| Harbor Phase 0 | 6 passed; no skips | 214.76 |
| Harbor conformance | 13 passed; no skips | 186.90 |
| Verified plus fresh official regrade | 2 passed; no skips; oracle 5/5, NOP 5 empty patches | 392.19 |
| Pro generation/fresh replay | 4 passed; no skips | 820.62 |
| Serving provenance | 14 passed; no skips | 0.54 |
| MAGNET integration | 27 passed; no skips; 6 heavy-engine cases deselected | 255.81 |

MAGNET started from the exact `b2311d2` integration base and uses its existing
EvaluationNode/kwdagger scheduler. Its fixture uses real infer-stack null-backend
leases and real Harbor Docker workers with a scripted OpenAI-compatible endpoint.
Both host and container-only worker paths execute the tool script, capture the
exact patch, project two selector rows, and reuse one measurement with one released
lease. Concurrent gates start one native run. Changing Q4 to Q5 under the same
alias produces a different node and measurement; stale catalog or leased facts
stop before inference. Mutable serving inputs disable reuse. Native infrastructure
errors and incomplete paired Pro grading do not become claim-facing zero scores.

Cancellation also crosses the real lease gate: SIGTERM reaches the owned native
worker, releases the lease, removes the sandbox/network, and retains a cancelled
attempt with no successful publication. It required fixing the gate's thread-based
wait, which could previously leave the child running, and infer-stack's signal
handling, which could previously bypass lease release.

`magnet-native.zip` retains 112 native/observation files byte for byte. It contains
successful host/container bundles and a cancelled bundle; observation files sit
outside the bundle manifests. After extraction, the engine-free reader validates
all three bundles and re-normalization matches `tests.regression.summary.summarize`
for each. That audit ran in Python 3.11 with no engines, MAGNET or kwdagger installed.
The archive avoids treating captured sandbox Python as repository source.

Broader local regressions: MAGNET 309 passed, 36 optional-engine skips;
infer-stack 1203 passed, 8 optional/native skips. Changed source lint, types and
shell syntax passed. The separate hosted HELM/Inspect/OLMo integration job was
configured for the new evaluator/serving source pins but was not rerun or pushed.

Pins: Harbor 0.23.0 / `1e5c5c6db929a10a140d05e606882c671ae20729`;
Pro V2 `66f92766bba642462d4bbe5479e83f91f9211862`;
Inspect-Evals `9080b5e9f1647ed14e45de8cb01e3d43411c0163`;
Verified dataset `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`;
Inspect 0.3.272; SWE-bench 3.0.15 / `b524f150d5d76f188c741d75669025f718c89c2e`.

GPU acceptance: **NOT RUN**. Later command:

```bash
AIQ_GPU_ALIAS=<managed-alias> \
AIQ_VM_REPORT=docs/planning/evidence/swebench-vm-2026-10-06/report.json \
  dev/ci/swebench_gpu_acceptance.sh
```

The script prepares the pinned host workers/images, acquires one owned model
lease, checks serving provenance, runs the synthetic task, five Verified instances
with official regrading and one Pro generation/replay instance, then verifies cleanup.
This VM evidence does not attest loaded weights or real-model capability. Pro uses
the local Docker/offline replay protocol; Modal/publisher parity is untested.
Installed mini-SWE runtime closure remains mutable and nonreusable. The 25-instance
Verified screening set, HARD-51 and full 500/642 campaigns remain unrun.
