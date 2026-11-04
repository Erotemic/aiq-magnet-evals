# Codex journal

## 2026-11-04 — Real-model SWE-bench Verified GPU smoke

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The objective was to complete a locally served, tool-using SWE-bench evaluation
on a GPU host. The operator ran the jobs on November 3; this entry records
the retained native bundles, official grader reports and host logs reviewed
on November 4. Execution used this repository's existing Verified request,
Inspect adapter and official regrade helper through a caller-owned tmux
launcher and infer-stack leases. No new evaluation engine was needed.

### Observed runs

Both completed runs used HyperQwen's prepared W4A16 serving recipe, Inspect
0.3.272, Inspect-Evals `9080b5e9f1647ed14e45de8cb01e3d43411c0163`, SWE-bench
3.0.15 and the five digest-pinned images in
`dev/environments/swebench-verified-images.json`. Dataset revision was
`c104f840cc67f8b6eec6f759ebc8b2693d585d4a`; generation used temperature 0 and
4096 maximum output tokens per model response. Evaluator source was
`6492c6c1158fa58a5ec18d379f4b52f3758a7689`; infer-stack source was
`0d3fc3445618b11b263e5310291037a6062d20c6`.

| Configuration | Official result | Patches | Agent limits |
| --- | --- | --- | --- |
| TP=1, one concurrent problem, 30-message budget | 0/5 resolved | Four empty; one 497-byte patch | All five reached the message cap |
| TP=4, four concurrent problems, 200-message budget | 2/5 resolved | Five nonempty | Three reached the message cap |

The TP=1 agent made 74 tool calls with no recorded tool or parsing errors.
The TP=4 per-instance results were:

| Instance | Official verdict | Tool calls | Reached 200-message cap |
| --- | --- | --- | --- |
| `django__django-10554` | Unresolved | 89 | Yes |
| `django__django-10880` | Resolved | 100 | Yes |
| `django__django-10914` | Unresolved | 99 | Yes |
| `django__django-10999` | Unresolved | 24 | No |
| `psf__requests-1142` | Resolved | 35 | No |

Both native evaluations recorded `succeeded`. Exported model patches were
checked in fresh official grader containers, with no grading errors or
incomplete predictions; official verdicts agreed with Inspect. Empty patches
in the first run were retained as failed predictions. For TP=4, model
readiness passed at 18:13:55 EST and cleanup finished at 18:41:52 EST: 27m57s
including evaluation and official regrading. Host logs show placement on four
GPUs, generation readiness, lease release and removal of the model container.
The changed agent budget and concurrency prevent attributing a speed or
quality difference to TP alone.

### Setup failure and execution details

The first attempt started the model but failed before any samples because
the worker lacked Inspect's optional OpenAI SDK. An isolated reproduction
confirmed that Inspect 0.3.272 requires OpenAI SDK >=3.1.0; installing 3.1.0
allowed provider initialization. The caller's launcher now performs that
initialization without an HTTP request before acquiring a GPU lease. Native
execution errors are also included in its terminal failure message.

The custom HyperQwen container command consumes `EXTRA_ARGS`; infer-stack's
stock vLLM flags are not automatically appended to that command. TP=4 therefore
requires both `runtime.tensor_parallel_size: 4` for GPU placement and
`--tensor-parallel-size=4` in the launcher's `EXTRA_ARGS`. Its `MAX_SEQS`,
Inspect's `max_samples`, and `max_sandboxes` were raised to four. A derived
endpoint in a run-local catalog preserved the operator's existing recipe.
The observed startup HTTP 500s occurred before generation readiness and did
not persist into the completed evaluations.

### Evidence and scope

The operator retains artifacts outside this repository under
`benchmark_results/swebench-hyperqwen-m3Q7VQa3/` (TP=1) and
`benchmark_results/swebench-hyperqwen-eAnqbabA/` (TP=4). Each includes the request,
source revisions, native bundle, exported predictions, official report and
regrade protocol. SHA256 fingerprints reviewed here:

| Artifact | SHA256 |
| --- | --- |
| TP=1 native Inspect `.eval` | `2a20671fde322b21190ae28942fa83220108cc471f46b5c24cd4404c7297bf2e` |
| TP=1 official aggregate JSON | `d9c444bcde37da2b2fdc4ec8485f8e13cc0518c1e7b3aba5b30742bb887f01cd` |
| TP=4 native Inspect `.eval` | `7adb1697e661a0feb8058c750b28482509a96d3068bdc6c5101b1aa17be868e5` |
| TP=4 official aggregate JSON | `35283573033ab1d4e8ba177e17f2925f523ddfd6a6f240eda6cc856f4782d730` |

This is real-model evidence for five Verified instances. Prepared weight
contents lack an immutable manifest, so reuse was disabled. The captures have
not been promoted into committed native regression fixtures or a new release
gate. Full Verified, Pro GPU execution and comparative TP speed remain unproven.

A separate November 4 invocation of the broad CPU/Docker acceptance suite
passed engine-free, Harbor Phase 0, Harbor conformance and Verified grading.
It failed Pro image-ID validation, serving provenance (the current infer-stack
branch lacks that API/test), and MAGNET cases requiring that API. The dedicated
`dev/ci/swebench_gpu_acceptance.sh` gate remains unrun; the successful Verified
measurements above do not imply that the broader suite passed.

The practical lessons are to initialize the chosen provider before leasing
expensive resources, align evaluator concurrency with server sequence capacity,
and distinguish protocol completion from a model solving the selected tasks.
The remaining scientific question is how much additional agent budget helps
the three capped tasks; answering it needs another explicitly recorded request.

## 2026-11-04 — Audit of the three unresolved TP=4 instances

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The requested next step was a trajectory audit before spending more GPU time.
Reviewed sample messages/model events, submitted diffs, per-instance official
reports and raw grader output. The detailed record is
[Verified failure audit](../../docs/planning/swebench-hyperqwen-failure-audit-2026-11-04.md).

`django__django-10554` spends its cap reproducing PostgreSQL ordering behavior
with SQLite, then repeatedly validates a clearing-ordering patch that leaves
the official missing-column failure. Its new regression test is skipped on
SQLite. `django__django-10914` implements the requested file-permission change
but also changes the directory default; the requested regression passes while
the preserved directory test fails. The agent edited that test to accept its
new behavior and used the altered suite as reassurance. It reaches the cap
while reviewing its existing diff, not implementing a correction.

`django__django-10999` submits normally with independently signed time-component
semantics. A CPU-only check reconstructed the captured parser and actual edit:
`-00:01:01` produces +61 seconds rather than the official -61. Its own tests
confirm its mistaken interpretation. More messages would not prolong that
already completed attempt.

The two capped failures each have ten per-response token-limit stops, plus
pager, locale, backend-reproduction or broad-test detours. Raw grader output
also exposes imperfect per-test attribution after failing subtests; aggregate
zero verdicts remain supported by concrete code/test failures. No score was
changed and no new GPU run was launched.

This supersedes the earlier working hypothesis that simply increasing the
message budget is the next useful experiment. A generic minimal-change and
independent-testing scaffold, with noninteractive/UTF-8/bounded test execution,
is a better candidate to compare against the retained 200-message baseline.
Exact gold fixes and hidden regression expectations belong in this analyst
audit, not in a subsequent benchmark prompt.

## 2026-11-04 — Prepare the minimal-edit protocol comparison

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The next authorized step was to prepare a generic scaffold experiment from
the audit. Added the opt-in Verified task argument
`agent_protocol: minimal-edit/v1`. The default upstream path is preserved.
The candidate keeps upstream agent/tools/scoring and adds issue-independent
guidance on minimal edits, independent tests, targeted checks, stateful shell
use and offline dependency handling. It configures UTF-8, noninteractive Git,
`DJANGO_TEST_PROCESSES=1`, and single-thread BLAS/OpenMP inside the container.
The prompt is constructed only from a fixed instruction prefix and the task
input. Gold/test patches and hints are not consulted.

The protocol option is part of the request and changes measurement identity;
the task module's source digest also covers the prompt and environment. Oracle
and NOP reject the intervention. Unit checks exercise default-path preservation,
unchanged solver/scorer/setup, hidden-metadata independence, unsupported protocol
rejection and identity separation.

A real Docker probe used the pinned upload-permissions benchmark image through
Inspect's public ComposeConfig. On the guest, its default environment reported
ASCII and 120 test processes; the candidate reported UTF-8, Git pager `cat`,
and one test process. This verifies environment delivery, not model performance.
The operator retains Compose configurations, logs and `observation.json` under
`benchmark_results/swebench-protocol-validation-20261104/`. Both probe containers
were removed. No model or benchmark grading was run for this probe.

The caller-owned launcher selects this protocol with the retained baseline's
TP=4, concurrency=4 and 200-message budget. After official regrading it writes
a paired comparison of resolved status, tool calls and limit hits. The readout
rejects request differences beyond the explicit protocol, configured serving
changes, instance-set changes and inconsistent grading coverage. It does not
attest prepared weight contents. A GPU rerun is prepared for the host but has
not been launched; the measured baseline remains 2/5.

Validation: the clean engine-free CI script passed lint and 244 tests, with
four absent-engine skips and 51 native deselections. Paired-readout checks
accepted an otherwise identical protocol change and rejected changed generation,
serving image and inconsistent grading summary. These checks and the container
probe establish readiness to try the candidate, not a measured capability gain.

## 2026-11-04 — Minimal-edit protocol host result: 3/5

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

Reviewed the operator's completed `minimal-edit/v1` host run and native bundle
`benchmark_results/swebench-hyperqwen-va9rBhIb/`. The paired-readout guard passed:
otherwise identical requests and configured serving catalog, five matching
instances, TP=4, four concurrent problems, 200 messages and 4,096 output tokens
per response. Prepared weights remain unattested. Evaluator source was
`d599cdca5ed7a436242408808ac4576629882de5`, with infer-stack unchanged at
`0d3fc3445618b11b263e5310291037a6062d20c6`.

| Instance | Upstream | Minimal-edit | Tool calls, before -> after |
| --- | --- | --- | ---: |
| `django__django-10554` | Unresolved, capped | Unresolved, capped, empty patch | 89 -> 101 |
| `django__django-10880` | Resolved, capped | Resolved, submitted normally | 100 -> 46 |
| `django__django-10914` | Unresolved, capped | Resolved, submitted normally | 99 -> 47 |
| `django__django-10999` | Unresolved | Unresolved | 24 -> 24 |
| `psf__requests-1142` | Resolved | Resolved | 35 -> 43 |

Official aggregate: 3/5 resolved, four nonempty predictions graded, one empty
prediction counted as failed, no errors or incomplete predictions. Inspect
agreed. Total message-recorded tool calls fell 347 -> 261 (24.8%); cap hits
fell three -> one. Generation readiness passed at 12:21:04 EST, cleanup at
12:47:16: 26m12s including evaluation and official grading. The lease was
released and model container removed. These are single runs over five selected
problems, with both prompt and environment changed; they do not isolate a
specific intervention or establish general model quality or repeatable speedup.

Patch review supports the intended upload-permission improvement: the agent
kept the directory permission default unchanged and all selected tests passed.
However it also changed the storage fallback to
`self._file_permissions_mode or settings.FILE_UPLOAD_PERMISSIONS`. That could
replace an explicitly requested zero mode with the default; this behavior lies
outside the selected checks. A passing benchmark patch is not automatically
a generally correct fix.

The union agent again investigates SQLite/PostgreSQL reproduction and reaches
the cap without a repository patch. Near the end it fixes its own temporary
fuzz harness, observes the ordering error, and resumes inspecting shared query
structures. The duration agent submits the same production regex change as
the baseline, retaining the audited whole-duration sign error. Both remain
unresolved; no analyst corrections were applied to model predictions.

Verified native-bundle checksums and the protocol marker on all five samples.
SHA256 of the native Inspect `.eval`:
`c45368301d5938e25ad5c74666d132266715ef2a738f18407bd2f3ebe11a55c8`.
SHA256 of the official aggregate JSON:
`2ba092ab35a82f441385d9e32bd21c97ed1906beec5651e25a691e7ce9c1f854`.
The run's `comparison.json` retains per-instance outcomes, tool counts and
limit records. No new GPU job was launched during this review.
