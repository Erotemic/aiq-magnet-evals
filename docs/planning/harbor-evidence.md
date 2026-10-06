# Harbor and SWE-bench implementation evidence

This ledger records native evidence for the roadmap, not general upstream
capability claims. Phase 0 was run on 2026-10-05 (America/New_York).

## Pinned sources and environment

- Harbor candidate `0.23.0`, release tag commit
  `1e5c5c6db929a10a140d05e606882c671ae20729`; CPython 3.12.3.
- Worker dependency constraints: `dev/environments/harbor-py312-constraints.txt`.
- SWE-bench Pro source: `66f92766bba642462d4bbe5479e83f91f9211862`.
  `v2/SHA256SUMS` SHA256:
  `9d84f8507c89241d42d8b3ef911600a1ec75dbbb32687ce9b45b93318502c0bd`.
  `cd v2 && sha256sum -c SHA256SUMS --quiet` passed.
- Docker 29.1.3; daemon kernel `6.8.0-142-generic`; bridge gateway `172.17.0.1`.
  Harbor's native kernel-support probe returned true. The actual native egress
  sidecar started healthy and enforced phase changes.
- Synthetic repository and relay base image: `python:3.12-alpine` digest
  `sha256:4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111`.
- Inspect-Evals candidate source inspected:
  `9080b5e9f1647ed14e45de8cb01e3d43411c0163` (requires Inspect >=0.3.261).
  Its Verified task pins dataset revision
  `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`. Verified native acceptance is
  scoped to the five-instance fixture below; broader capability remains untested.

## Reproduction and observed gates

```bash
dev/ci/harbor_phase0.sh
```

Observed: **6 passed**, no skipped tests, 221.29 seconds. This command is a
Phase 0 probe suite; it is not `swebench_vm_acceptance.sh`.

| Evidence | Native observation |
| --- | --- |
| Local repository task | Oracle reward 1; NOP reward 0. Both used real Harbor Docker trials and native pytest verification. |
| Endpoint transport and executed tools | The scripted OpenAI-compatible endpoint drove file inspection, source editing, and pytest execution in the sandbox. The three executed commands and observations were captured in the trajectory. Four actual chat requests reported 20 input tokens. |
| Patch capture | The captured diff matches `tests/native/harbor_tasks/division/solution/model.patch` byte for byte. Repository ignore rules exclude pytest caches/bytecode from this diff. |
| Allowlist and nested routing | The task reached the named fixed-upstream relay, which forwarded to the host's loopback-only endpoint. It could not reach the unlisted local HTTP listener or `https://example.com/`. Both negative targets were reachable during the public setup phase. |
| Phase enforcement | With no allowlist, agent-phase access to the relay and Internet was denied. Public verifier access was restored. With the relay allowlisted, verifier access to all three targets was restored. |
| Cancellation | The existing worker-group SIGINT path interrupted a native sleeping sandbox command. Harbor wrote `CancelledError`, preserved the start diagnostic, and removed its owned containers; the worker process group disappeared. No reward or successful publication marker existed. |
| Partial failure | Two oracle trials: one reward 1, one `RewardFileNotFoundError` with null verifier result. Native completed count 2, errored count 1. |
| Fresh replay | The unchanged upstream `patch_replay:PatchReplayAgent` applied the captured synthetic patch in a different native trial/sandbox. `apply_rc=0`; native verifier reward 1. |

These observations cover the synthetic task and test scaffold only. They do not
establish built-in mini-SWE-agent, Verified, Pro V2 task-image, full oracle/NOP,
Modal parity, MAGNET lease, or real-model/GPU support.

## API and artifact decisions justified by the probes

Use Harbor's supported `await Job.create(JobConfig)` and `await job.run()`.
Constructing `Job(config)` directly is rejected in this pin. Jobs contain
`config.json`, `lock.json`, `result.json`, `job.log`, and per-trial directories.
Each trial contains config/lock/result, agent logs, verifier logs/reward,
and an artifact manifest. Job `result.json` need not embed trial results;
read the individual trial result files.

After SIGINT, the captured job's `finished_at` remains null even though its one
trial has a finished timestamp and `CancelledError`, completed/cancelled counts
are 1, and pending/running counts are 0. A cancelled job must not be classified
as successful from completed counts or its numeric mean (which is 0).

Native `TrialResult.exception_info`, timing boundaries, `agent_result` usage,
and nullable `verifier_result.rewards` must be retained. Harbor job stats in
the partial-failure fixture report `mean=0.5` despite the only observed reward
being 1: the upstream aggregate includes the verifier error in its denominator.
Keep that statistic as native diagnostics; never present it as a complete
model score or synthesize a zero reward for the failed trial.

The selected bridge uses Harbor's `extra_docker_compose` extension point.
A separate fixed-upstream relay service explicitly joins the project network;
the sandbox continues to share Harbor's egress-control sidecar network namespace.
Only the relay hostname is allowlisted. A second, attempt-owned host HTTP hop
binds to the Docker bridge gateway and forwards to loopback. No container port
is published, and the sandbox does not use host networking. Both hops close
after the job. Generic adapter execution and Phase 0 now share this bridge.
Real-model timing/streaming and benchmark protocol acceptance remain separate
gates.

The upstream replay agent searches `instance_*/result.json`; the fresh-replay
fixture therefore uses task name `instance_division`. It selects the first
matching source task, so multi-attempt joins must be made unambiguous by the
benchmark profile rather than silently replaying the wrong trial.

## Remaining gates

- Hard-kill fallback cleanup and real-model bridge timing/streaming.
- Pinned Inspect-Evals/official SWE-bench worker acceptance and patch export.
- Actual Pro V2 oracle/NOP, locked mini-SWE generation, replay joins and profiles.
- infer-stack scientific serving provenance and MAGNET preflight/runtime checks.
- Full VM acceptance command, then the separate small GPU acceptance command.

No supported Harbor adapter pin or complete SWE-bench capability is claimed yet.

## Verified native acceptance: 2026-10-05/06

The candidate worker freezes Inspect 0.3.272, Inspect-Evals
`9080b5e9f1647ed14e45de8cb01e3d43411c0163`, SWE-bench 3.0.15
(tag commit `b524f150d5d76f188c741d75669025f718c89c2e`), Python 3.12.3,
and `dev/environments/swebench-verified-py312-constraints.txt`.
`dev/environments/swebench-verified-images.json` records actual pulled image
digests. The pinned Verified dataset contains 500 rows; only these five were
accepted: django__django-10554, -10880, -10914, -10999 and psf__requests-1142.

`tests/native/test_swebench_verified.py`: **2 passed**, 388.18 seconds.
The complete reproduction script `dev/ci/swebench_verified_acceptance.sh`
also passed **2 tests** in 385.54 seconds, including its constrained worker
installation and digest-pinned image preparation.
Each test executes five fresh Inspect sandboxes. Oracle: **5/5**, and fresh
official containers regrade the exact exported patches **5/5** with no errors
or incomplete instances. NOP: **0/5** with five actual empty patches. The
official harness records those five as empty submissions, runs no grading
containers, and resolves none. No per-instance NOP grader report is fabricated.

Unmodified Inspect bundles, official grader reports/logs/patches, selected
dataset rows and commands are under `tests/fixtures/swebench-verified-native`.
The engine-free regression tests verify their SHA256 inventory, export the
same patches byte for byte, compare each oracle patch to the official grader's
`patch.diff`, and refuse tampered artifacts.

### Explicit local protocol changes and excluded cells

The task wrapper uses upstream Inspect-Evals agent/scorer/oracle code, selecting
pinned dataset rows and digest-pinned images. It uses public ComposeConfig to
avoid the upstream shared YAML-cache race. Before agent execution it runs
`git reset --hard <base_commit>` and `git clean -fd` (`git-reset-clean/v1`).
This changes the repository baseline explicitly: the original Requests image
contained build residue, causing an oracle capture around 872 KB rather than
the 743-byte gold patch. That capture scored 1 in Inspect but 0 on fresh
official replay; grading the gold alone scored 1. Cleaning untracked files
alone still left tracked mode changes in another image and made NOP nonempty.
Reset plus clean produced the accepted exact oracle/NOP behavior above.

An earlier Requests smoke attempt (1142, 1724, 1766, 1921, 2317) failed offline
acceptance: the latter four gold patches encounter HTTP-dependent tests. That
set was replaced by the now-frozen offline infrastructure fixture before any
model comparisons. Those four offline cells and the remaining 495 Verified
instances are untested, not supported by this acceptance. The separate
25-instance screening selection is frozen but has not been executed.

The official 3.0.15 CLI lacks a dataset-revision argument, so acceptance writes
the pinned selected rows as its documented local JSON input. This preserves
dataset identity rather than silently grading against the moving HF default.
No GPU/model scores, full benchmark capability or publisher parity are claimed.

## Generic adapter acceptance: 2026-10-05

`dev/ci/native_harbor.sh`: **12 passed, 12 other-engine tests deselected**,
190.74 seconds, at the candidate pin and worker constraints above. The shared
conformance checks cover execution, stable identity/reuse, native import and
SIGINT process/container cleanup. Adapter-specific native checks cover task
and config content identity, endpoint/location invariance, checksum refusal,
input drift refusal, imported model mismatch, rejection of ignored agent
options, consumed attempt-owned config snapshots, and scripted tools through
the shared production bridge with unrelated LAN/Internet access denied.

The Python 3.11 engine-free suite passed **193 tests**, 4 absent-engine module
skips and 43 native deselections. Native Harbor captures normalize and
round-trip without Harbor installed. Eight normalized regression summaries
were regenerated with `dev/regenerate_native_regressions.py harbor` and
reviewed; unchanged raw fixture checksums pass. Earlier type and lint checks
passed for the adapter; benchmark-specific work is still in progress.

Resolution hashes selected task bytes, agent Python source, explicit file
configuration, Harbor source, installed dependency versions and Python runtime.
Execution re-resolves before copying immutable inputs into the owned attempt.
The native retry exception-set defaults are sorted before identity hashing;
their otherwise nondeterministic JSON order must not change worker identity.
Installed agents remain nonreusable until the complete sandbox runtime is
pinned, even with a fixed package version. Mutable task images/build downloads
also require an enforced physical image pin for reuse. Conformance now uses a
concrete prebuilt image ID. Docker daemon platform/version are identified
separately from operational endpoint locations.
The optional dependency and `uv.lock` select the candidate engine; only the
recorded worker constraints describe the environment accepted above.

## Local Pro V2 paired protocol: 2026-10-05/06

Frozen smoke instance:
`instance_ansible__ansible-0ea40e09d1b35bcb69ff4d9cecf3d0defa4b36e8-v30a923fb5c164d6cd18280c02422f75e611e8fb2`.
Observed image ID/digest:
`sha256:af7d28fe6608951bf88e39b6a24d5574dcd1b5b82a6c983147666289f8014f18`.
Its registry reference is in `dev/environments/swebench-pro-smoke.json`.
The source/checksum pins above were verified against the actual task tree.

Native oracle and NOP initially returned rewards 1 and 0. Separate generation
and pristine replay jobs then returned oracle **1 -> 1**, NOP **0 -> 0**. The
oracle patch is 1,892 bytes, SHA256
`5531ce2ce92ec2a2b657be69afb696802fd7d3086fa010b78f2958ca0fed71fb`.
NOP has an actually captured empty patch. Both replay trials retain required
native test observations. Generation/replay UUIDs differ, and the replay input
matches the captured patch checksum.

Unchanged upstream `locked_mini_swe:LockedMiniSwe` installed mini-SWE **2.4.6**,
executed four scripted tool calls in the synthetic Docker task, captured the
exact expected division fix and passed native generation/fresh upstream replay.
The accepted repeat passed **1 test** in 75.31 seconds. Observed managed Python
is **3.12.14**; `runtime-agent.json` preserves the package closure. This mutable
installation is not yet reproducible or reusable.

Successful unmodified bundles are in `tests/fixtures/swebench-pro-native`.
Engine-free tests verify checksums, re-normalize raw jobs after original worker
paths disappear, validate UUID/patch joins, compare recorded rewards, and import
paired trees with correct artifact paths. Derived summaries were regenerated
with `dev/regenerate_native_regressions.py pro`.

The full VM repeat additionally ran unchanged locked mini-SWE 2.4.6 inside the
actual frozen Ansible image against four scripted tool calls. Captured gold is
byte-identical to the native oracle patch above; generation and pristine replay
both returned 1, and replay observed all **16 required tests**. Managed Python
was **3.12.15**, demonstrating that an agent version alone does not pin runtime.
The nonreusable raw bundle and checksums are retained separately in
`tests/fixtures/swebench-pro-agent-native`, with engine-free re-normalization
and paired import checks. This is scripted-gold infrastructure evidence.

### Explicit local decisions and limits

- Local Docker is used rather than upstream's documented Modal provider. No
  `pro-v2-compatible` or publisher-score reproduction label is claimed.
- Task trees, locked agent and replay source remain unchanged. The acceptance
  wrapper invokes real native OracleAgent/NOP and upstream patch capture.
- First-match replay receives a derived view with one unchanged result/patch
  per task. Multiple attempts are refused. Missing patches are errors; actually
  empty patches are preserved.
- Public `agent-start` verifies owned images and observes installed mini-SWE
  before inference. `environment-start` precedes container creation in this pin.
- Synthetic tasks use explicitly prebuilt image IDs: adding a Compose relay
  changes Harbor's build path/image labels, so its image ID is not assumed to
  equal the shared native build-cache ID.
- Pro's verifier EXIT trap can emit 0 early. Native required-test observations
  are separate facts; missing/ambiguous coverage withholds a complete aggregate
  while retaining the original reward, without asserting an unobserved cause.
- HARD-51/full are definitions only. No full 642 oracle/NOP, HARD-51 model run,
  actual leased model, GPU acceptance or Modal parity is claimed.

## Cross-repository status

infer-stack `be1add2` exposes scientific catalog/lease provenance and passed
**1201 tests**, 8 skips. Focused tests cover revision, Q4 -> Q5, dtype, context,
attention, launch arguments, chat template/image changes, placement invariance
and real SQLite lease descriptor emission. These are configured facts, not
GPU/weight attestation.

MAGNET `dev/aiq-evals-integration` / `b2311d2` is absent from the local checkout
and available remotes. Legacy main lacks EvaluationNode and the fake-lease
hook. No replacement scheduler was created. MAGNET projection/runtime checks
and full VM acceptance remain open. GPU acceptance is implemented but not run.

## Full VM gate record: 2026-10-05

Command: `dev/ci/swebench_vm_acceptance.sh`. Overall **FAIL**, solely because
the required MAGNET integration checkout/hook is unavailable. The unmodified
report, JUnit files and missing-integration diagnostic are retained in
`docs/planning/evidence/swebench-vm-2026-10-05`. The report identifies the tested
working-tree source fingerprints; its HEAD field is not a clean-commit claim.

| Gate | Observed result |
| --- | --- |
| Engine-free | 219 passed, 4 absent-engine skips; 9.88 seconds |
| Harbor Phase 0 | 6 passed, no skips; 214.01 seconds |
| Generic Harbor conformance | 12 passed, no skips; 174.67 seconds |
| Verified + fresh official regrading | 2 passed, no skips; 386.23 seconds; oracle 5/5, NOP 5 empty |
| Pro generation + fresh replay | 4 passed, no skips; 816.01 seconds |
| infer-stack serving provenance | 13 passed, no skips; 0.48 seconds |
| MAGNET fake lease | FAIL: required integration/hook absent |

GPU acceptance: **NOT RUN**. Later command:
`AIQ_GPU_ALIAS=<alias> AIQ_VM_REPORT=<passing-report> dev/ci/swebench_gpu_acceptance.sh`.
The failed VM report cannot authorize that stage. No full benchmark campaign
was launched. Final engine-free checks also cover the newly retained fourth
Pro fixture and stale/missing GPU descriptor rejection: **226 passed**, 4
absent-engine skips and 50 native deselections in 10.39 seconds. Lint, core
types, native regrade-helper types, shell syntax and wheel checks passed. The
wheel retains Python >=3.11, only kwconf as its runtime dependency, and the
frozen HARD-51 data; tests are excluded. After the recorded VM run, the driver
was adjusted to create fresh per-run environments and raw captures were
excluded from lint without modifying them.
