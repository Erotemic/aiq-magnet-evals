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

## 2026-11-04 — Prepare the frozen 25-instance screening stage

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The requested continuation was broader evaluation after the 3/5 protocol
experiment. Kept the selection already frozen in
`dev/environments/swebench-verified-selection.json`: the previous five plus
the original twenty hash-ranked additions. Verified its exact membership and
ranking against the cached 500-row dataset at the recorded revision.

Added a 25-entry image-pin file. The five smoke pins remain unchanged; the
twenty new pins resolve DockerHub manifests for linux/amd64 and verify the
registry's digest against the returned manifest bytes. The pinning helper reads
metadata only and does not download layers. Registry metadata is retained by
the operator under `benchmark_results/screening-preparation/`; its unique
compressed layers total about 10.16 GiB before considering existing cache.
This is not an estimate of expanded disk use or proof of offline execution.

The caller-owned screening launcher prepares the pinned worker and images,
then runs the existing native oracle/NOP test with the 25-image manifest.
Both modes must pass all instances and fresh official grading before GPU
leasing. The native test still defaults to the original five pins. Model
requests retain minimal-edit/v1, TP=4, four concurrent problems, 200 messages
and 4,096 output tokens. Summaries separate the previous five from the
additional twenty; no five-versus-25 protocol comparison is emitted.
The official regrade helper retains its old one-hour budget for sets up to
five and scales its subprocess timeout for larger selections.

Preparation checks cover exact frozen membership, preservation of smoke pins,
architecture selection and registry-checksum rejection. The actual host request
builder was exercised for both 5 and 25 instances with generation/budget held
fixed. No new model job was launched, and the full 25-instance native gate has
not run here. `runtime_verified_ids` remains the original five. Any offline
grading failure must be diagnosed without dropping or replacing selected tasks.

Validation: the clean engine-free CI script passed lint and 247 tests, with
four absent-engine skips and 51 native deselections. Caller shell syntax and
profile request construction passed. The screening preflight requires exact
JUnit evidence for both oracle/NOP cases, rejecting skipped or missing cases.

## 2026-11-04 — Screening preflight blocked on an oracle reward mismatch

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The operator's first 25-instance CPU/Docker preflight finished with one failure
and one pass after 2,041.67 seconds. Oracle native execution completed with
all 25 samples and no recorded sample errors, but at least one gold patch
received a score other than one. It stopped at the reward assertion before
fresh official oracle regrading. NOP completed and passed official grading.
The GPU stage was not entered, and the frozen membership remains unchanged.

The assertion reported only `all(...) == False`, and capture ran only at the
end of a successful test. Consequently, the failed oracle's native artifacts
remained in the host's pytest temporary directory while the shared output
contained only NOP evidence. At that point the shared report did not identify the failing instances
or their causes. A caller-owned collector is prepared
to recover the existing host files; no expensive preflight rerun is needed
to inspect them if those temporary files still exist.

Moved native capture into fixture teardown so assertions cannot discard
failure evidence, and replaced the aggregate reward assertion with per-instance
unexpected scores. The caller now keeps pytest work under its shared output,
uses a short traceback, and stops at the first failure. The existing gate still
requires both oracle and NOP to pass before GPU leasing. This changes diagnostics,
not acceptance criteria. No image, task membership, grader or score was changed.


## 2026-11-04 — Recovered screening oracle failures; focused replay prepared

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The recovered 25-sample oracle bundle scored 21/25. Four gold patches scored
zero: `sphinx-doc__sphinx-8595`, `sphinx-doc__sphinx-8638`,
`sphinx-doc__sphinx-9229`, and `sphinx-doc__sphinx-9281`. There were no native
sample errors. This is a failed environment/grading acceptance gate, not a
model result. The common repository suggests a shared setup issue, but does
not establish its cause.

Read the recovered native `.eval` as well as normalized trajectories. Inspect
0.3.272's sandbox event logger truncates file contents to the first 20 lines;
all four captured test outputs end during pip setup, before test diagnostics.
The scorer consumed the full output, but the saved event did not preserve it.
No traceback or dependency diagnosis can be recovered from these events.

Added a diagnostic replay helper for only failed captured oracle samples. It
uses the request's pinned images, networking disabled, the same repository
reset/cleanup, each actual captured solver patch and the upstream native eval
script. Full output is written directly to a caller-owned artifact directory;
image, patch, script, exit code and replay verdict are retained. Container
cleanup is scoped to containers it creates. This does not change a request,
accept a failing oracle, or replace a selected instance. The caller supplies a
zero-placeholder host command that selects the latest failed oracle bundle.

Validation: Python compilation and lint. Native replay is pending on the
operator host, where the four images are cached. No new model run or GPU
lease was launched, and the 25-instance acceptance gate remains blocked.


## 2026-11-04 — Sphinx gold failures were missing per-test reporting

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The operator's focused replay completed all four Sphinx cases. Actual test
summaries were 1, 35, 14 and 39 passed for instances 8595, 8638, 9229 and 9281,
respectively: 89 passed, no failed tests. All four native verdicts remained
zero. Running SWE-bench 3.0.15's actual Sphinx log parser against those full
logs returned no test IDs in every case.

The image build specification edits tracked `tox.ini` to add `pytest -rA`.
Our `git-reset-clean/v1` setup resets that file, removing the per-test report
the grader expects. Compact progress dots and a suite total cannot supply
individual FAIL_TO_PASS/PASS_TO_PASS outcomes. This was a harness setup bug,
not evidence that the gold fixes or installed Sphinx dependencies failed.

The task now supplies `PYTEST_ADDOPTS=-rA` and tox's public
`testenv.pass_env+=PYTEST_ADDOPTS` override for Sphinx whenever cleanup is
enabled. It leaves tracked files clean and keeps the upstream solver,
patch capture and scorer. It applies equally to oracle, NOP and agent, and
combines with minimal-edit environment defaults. The task module source hash
changes measurement identity. Existing native bundles retain their original
scores; none are relabeled. The diagnostic helper can opt into the current
environment and records that difference alongside its source and replay score.

A local reporting probe with tox 4.16.0, tox-current-env 0.0.11, pytest 8.3.3
and SWE-bench 3.0.15 exercised one passing and one deliberately failing test.
Without the fix the parser found only the failure; with it both IDs and
statuses were recognized. Probe output is retained by the caller under
`benchmark_results/swebench-sphinx-reporting-validation-20261104`. This probe
uses Python 3.12 and a temporary project, not the host's Sphinx images.

Validation: clean engine-free CI passed lint and 251 tests, with four
absent-engine skips and 51 native deselections. The full 25-instance oracle,
NOP and fresh official grading must still pass on the operator host before
GPU leasing. The frozen selection and image pins are unchanged.


## 2026-11-04 — Prepared an unattended paired screening follow-up

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

After the operator started the corrected 25-instance minimal-edit screening,
prepared a caller-owned follow-up that waits for successful official grading
and lease cleanup, then runs the upstream agent on the same frozen set. The
baseline keeps TP=4, concurrency four, 200 messages, temperature zero and
4,096 output tokens. It repeats oracle/NOP acceptance before model leasing.
This tests whether the exploratory five-instance protocol difference extends
to the additional twenty, without introducing new task membership or budgets.

The caller records separate run paths and a descriptive paired comparison.
It checks requests except protocol, serving recipes, native task and
registration source hashes, engine/adapter versions, and complete official
grading. Prepared weight contents remain unattested. No earlier native score
is changed. The wait stops on failed preflight or a launcher that exits
without a complete result; a per-candidate lock prevents duplicate active
follow-ups. The wait is bounded at twelve hours. Source changes since the
candidate prevent launching a nominally matched baseline.

Validation: eight caller regression tests cover failure/abandonment gates,
lease-cleanup waiting, exact launcher tracking, source mismatch, incomplete
official grading, valid zero-success results and baseline/candidate selection.
The extended comparison helper reproduced the retained smoke pairing: two
both-resolved, one candidate-only, zero baseline-only and two neither-resolved.
Strict source matching correctly rejected those historical runs, whose task
sources differed. Shell syntax and Python lint passed. No new GPU run was
launched from the guest. The current screening and paired model results are
still pending.

Timing is an estimate: the measured five-instance minimal-edit run took
26m12s including official regrading. Linear extrapolation is about two hours
for 25, before CPU/Docker acceptance and startup. Budget 2–4 hours for one
screening and 4–8 hours for the pair until the broader run supplies actual
timing.


## 2026-11-05 — 17/25 screening completed; baseline patch fallback reversed a fix

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The corrected minimal-edit screening completed on the operator host: 17/25
resolved with exact Inspect/official agreement, no native errors and no
incomplete official predictions. The earlier smoke contributed 3/5 and the
additional twenty contributed 14/20. Oracle/NOP and fresh official acceptance
passed across all 25; `runtime_verified_ids` now records those instances.
The native model run made 1,754 tool calls and nine samples hit a limit.
Readiness was November 4 22:33:31 EST and cleanup November 5 00:29:15, about
1h56m including native work, fresh grading and cleanup. CPU acceptance took
2,911 seconds. This is a selected 25-instance result, not full Verified.

The matched upstream-agent baseline completed all 25 native samples with no
errors, 1,835 tool calls and eleven limit hits. Its CPU gate passed in 4,523
seconds. Fresh grading stopped publication: native resolved 15, official 14,
with one disagreement, `matplotlib__matplotlib-24627`. Both runs used evals
`09a2444`, serving code `0d3fc34`, and task source SHA256
`7910f7b46d054203a34d93c334494d51e7962441ffaaaf4e9bf0e2230390e9f3`.
Both serving leases were removed. The failed paired campaign is retained;
no valid paired result has been published.

The baseline's 2,523-byte captured patch contains a 296-byte placeholder for
an untracked `__pycache__/lines.cpython-311.pyc.<number>` file, plus 2,227
bytes of production source changes. The textual diff contains no binary
payload. Official logs show `git apply` failed atomically, `git apply --reject`
failed after applying the source changes, then GNU patch reported the edits
already applied and reversed them. Its recorded production diff was empty.
It tested the original source and failed the target regression (776 other
tests passed). This explains the disagreement without rerunning inference.

A local Git/GNU patch probe reproduced the same upstream sequence: exit codes
1/1/0, source states original/fixed/original. The caller retains that probe
under `benchmark_results/swebench-bytecode-fallback-audit-20261105`.
Ordinary export now refuses uncaptured binary placeholders before grading.
Future setup excludes untracked Python cache directories using Git's local
exclude file, without adding harness changes to production patches. The task
source identity changes; completed native records are not relabeled.

Prepared a CPU-only diagnostic that creates a separate prediction omitting
only a newly created temporary CPython bytecode placeholder. Unknown binary
changes are refused. It records the original/derived patch hashes and omitted
block identity, verifies retained dataset/image lineage, and runs fresh
upstream official grading for the mismatch only. This is explicit transformed
prediction evidence; original native scores, predictions, official reports
and the failed pair status remain intact. Its host result is pending.

Evidence: candidate native log SHA256
`fc79bb776757b08fe1f296a223ee0192e09260faf5cb0bb36c728399068d372e`,
official report `45087cd47cba080a231bcece967a881b332c8ee046051c4cbbab884b4219d7aa`;
baseline native `bd29a6bbcc0cbcb7b08315b5bf282bb976e61f173c453dfd73d5ee1a2f231954`,
official `d18bc4c26865015a238f5fd9642dfdac899ea73834f4aefbf61dcc188481bca4`.

Validation: the new tests reject incomplete binary exports, require exact
source-patch preservation and refuse non-temporary binary omissions. A real
Git setup probe confirms that cache exclusion prevents the transient file
from entering the staged patch while preserving source edits. Engine-free CI
passed lint and 257 tests (four absent-engine skips, 51 native deselections).
The saved actual baseline patch exercised the narrow transform: exactly one
temporary cache block was omitted. No new model run was launched.


## 2026-11-05 — Bytecode-free audit passed; qualified screening comparison saved

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

The operator's fresh official audit of Matplotlib 24627 passed after explicitly
omitting the captured temporary bytecode placeholder. No source changes were
altered. Original patch SHA256 is
`b7b8c7046e04a5c6bfd6e9381d08264415a15ffa52f7bbb5d9b0c2ed39a7c69e`;
derived patch `2dba8f58539cb7b3b41aa002a2df4329d63c5224bf4e6cee0faaa47e99ff90e5`;
the fresh official audit report is
`0387f5fd87511a5dc16f003abeae34425e6a9d7818b03f2efcf6a608b0a2fb42`.
It submitted exactly that one instance, resolved it, and reported no errors
or incomplete predictions. The original 14/25 official result remains intact.

Validated and saved a caller-owned qualified comparison, using the original
24 agreeing baseline verdicts and the one explicit transformed-prediction
audit verdict: baseline 15/25 versus minimal-edit 17/25 (60% versus 68%).
Fifteen resolved under both, two under minimal-edit only, none under baseline
only, and eight under neither. The additional successes were Django 10914
and 15268. The original smoke contributes 2/5 versus 3/5; the additional
twenty contribute 13/20 versus 14/20. Calls were 1,835 versus 1,754 and limit
hits 11 versus nine. These are descriptive paired observations on the selected
25, not full Verified performance or evidence of a repeatable effect.

The caller's readout verifies completed native bundles, identical requests
except protocol, task/registration source hashes and engine/adapter versions,
selected serving recipes, exact membership, original grading coverage,
retained dataset/image lineage, and the exact supported patch transform and
checksums. The result explicitly labels the baseline audit and retains hashes
of the original report, audit, derived predictions and new report. It is saved
as `comparison-audited.json`, while the failed raw pair status and ordinary
comparison path are unchanged. Prepared weights remain unattested.

The first audit accidentally included an identical epoch-reduction record
alongside the native sample, duplicating its prediction and lineage entry.
The official report still submitted and resolved exactly one unique instance.
Fixed the helper to select native samples only and refuse genuinely repeated
samples. The historical readout accepts only byte-identical duplicate rows,
records their counts, and rejects conflicting entries. No audit was rerun to
correct this bookkeeping, and no original artifact was edited.

Validation: 258 engine-free tests passed, with four absent-engine skips and
51 native deselections; lint passed. A regression test verifies that epoch
reductions cannot create extra audit predictions. Nine caller tests passed,
including explicit duplicate counting and conflict rejection. The qualified
readout executed against the retained native and host audit artifacts. No
additional model work or host command is needed to obtain this comparison.


## 2026-11-05 — Full Verified manifests and resumable caller campaign prepared

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

Frozen all 500 IDs from the cached dataset at the existing revision. The
accepted 25 remain first, followed by SHA256(seed:instance_id) order for the
remaining 475. Added 500 linux/amd64 image digests, preserving every accepted
pin. Registry GET lookups resolved 100 additions before throttling; the
remaining metadata came from Docker Hub's architecture-specific tag records.
A checkpointed resolver retries transient failures; digest pulls on the host
verify image content. No case was removed after pinning difficulty.

Added optional ownership metadata through supported Compose environment fields,
not unsupported ComposeService labels. The default task remains unchanged.
Official regrading now accepts caller-specific run IDs and image tags to avoid
container/tag collisions and support scoped cleanup. This adds no MAGNET claim
logic or core engine dependency.

The private caller prepares one frozen campaign, snapshots both package sources
and the pinned upstream task checkout, installs an isolated constrained worker,
and records source/dependency and serving-input fingerprints. Per-instance
oracle/NOP acceptance precedes that instance's model work. Twenty groups of
25 bound image storage and GPU lease lifetimes; four model jobs run concurrently.
All 500 remain in the manifest and partial summary. Failed checks retain native
artifacts and remain blocked; no full score is emitted unless all 500 are graded.
Completed checkpoints are hash-verified on resume; native results can be reused
within the frozen campaign when their attested model binding is unchanged.

The serving child hashes its actual weight files and image content before and
after each model batch, pins the observed image for later starts, and refuses
changed realization. This mechanism is prepared for the operator model but not
yet exercised against that model. A cached CPU-image fixture with toy weight
files verified the hashing path, repeated-content acceptance and changed-byte
rejection. The model message budget remains 200, temperature zero and 4,096
output tokens. Native model execution has a 24-hour infrastructure timeout per
problem, rather than the previous six-hour timeout for an entire campaign.

Each batch lease uses a 30-day backstop and stop-on-reclaim. Normal exit,
failure and cancellation release the exact lease. Recovery also discovers
leases by the exact campaign owner if interruption preceded descriptor capture.
Cleanup identifies only campaign-marked native containers, uniquely named
official graders and caller-created image tags; images cached before the
campaign are preserved. There is no global prune, evict-all or release-all.
The same entry command resumes pending/failed cases; explicit cleanup is
available after a hard interruption. GPU work remains on the operator host.

Native evidence retained by the caller under
`benchmark_results/swebench-full-native-check-20261105`: Requests 1142 oracle
and NOP both matched fresh official verdicts (1 and 0), and checkpoint resume
created no additional attempt. Oracle manifest SHA256
`1977168910b30bad4650f74488c386b5622bd449ea22c08fb47e9706a155bd32`,
official report `f92b81a6df06fd49be199d9118514cc9c07934d7561291fd90343de285ca74ff`;
NOP manifest `c33365ab52d4cfd9563d0756c4cd5caad396d8041a5dec9c94508975fc339d23`,
official `3c14759e7de25945f5cc1c39601b3c066e01c12169d3c50a84841bb8333afc98`.
A real Docker probe removed an owned container while preserving a different
owner. Existing inference-lifecycle tests passed five real signal cases,
covering SIGINT/SIGTERM during child work and readiness with lease release.

Validation: 264 engine-free tests passed, four absent-engine skips and 51
native deselections; lint passed. Fourteen caller tests cover all-500 coverage,
partial-score refusal, checkpoint corruption, cache reuse, per-case isolation,
TP forwarding, owned cleanup, failure recovery and acquisition interruption.
Shell and Python syntax checks passed. Full 500-instance runtime acceptance,
operator-model attestation and GPU throughput remain pending.


## 2026-11-05 — Full-campaign packaging and cancellation checks completed

Author: GPT-6 (Codex; exact weights/configuration variant undetermined).

Exercised the frozen-source installation path in a separate worker with the
retained operator catalog as a read-only fixture. All 142 packages installed,
source fingerprints survived the build, the OpenAI provider initialized without
HTTP, and the cached dataset matched the complete 500-instance manifest. The
upstream archive needs an editable installation to preserve task resource
files; the pinned source commit is independently checked and SCM build metadata
retains its observed version. The final single-instance request also passed
native oracle plus fresh official regrading from that frozen worker. No GPU
lease or real model execution was involved in these guest checks.

Working package edits and new package modules can be frozen without changing
the live checkout; snapshots record a working-content fingerprint alongside
the commit. The upstream task checkout remains required to match its exact pin.
A real Git fixture covered tracked changes, a newly added module and replacing
a tracked symlink, while unrelated untracked files stayed out of the snapshot.

The serving-content probe now also checks the live MODEL path and ownership
marker. A cached CPU-image fixture accepted repeated identical content, rejected
modified bytes and rejected a different owner. This tests the mechanism with
toy files, not attestation of the operator's prepared weights. The user-facing
entry command acquires an exclusion lock that survives exec into its frozen
worker. A signal during child-process creation is deferred until ownership is
registered, preventing an orphaned acquisition or task process.

Checkpoint validation covers native files, normalized results, requests,
official reports and the campaign model realization. Completed zero outcomes
are retained; resuming retries incomplete work and records native/grading
attempt counts. Summaries include finish reasons, truncation fraction and
native limit hits beside coverage and score.

Validation totals: 264 engine-free tests, 20 full-campaign caller tests,
nine existing paired-campaign tests and five real inference-lifecycle signal
tests passed. The caller tests include real timeout termination, a real signal
during child creation and inherited-lock behavior across worker exec. Shell
syntax, Python compilation and lint passed. Captures are retained under the
caller's full-preparation and full-native-check directories. Full 500-instance
runtime acceptance, operator-model attestation and GPU throughput remain
pending on the host; no full score is claimed from these probes.
