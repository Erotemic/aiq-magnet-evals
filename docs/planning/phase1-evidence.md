# Phase-1 evidence ledger

> **Current status: Phase 1 CLOSED (2026-09-29).** Every P1 task is done; the
> MAGNET cardinality spike moved to integration gate M6. For the closure table,
> read "follow-up 3" → "P1-10: Phase 1 closed" below. For the per-task summary,
> run `aiq-evals phase1-status`. The "Repository bootstrap evidence" and "Runtime
> items" sections are the original pre-campaign snapshot. Their `Status:` lines
> are marked *(bootstrap snapshot, superseded)* and are kept for history only.
> Records are append-only and read in date order.

This is the canonical record for phase-1 validation. The repository-bootstrap
snapshot below predates the 2026-09-29 native campaign; later campaign records
supersede its OPEN status labels. A checkbox is not complete
until its evidence is recorded here. Documentation or a historical integration
may motivate a test but does not replace it.

## Record template

For each runtime item record:

```text
ID:
Date:
Implementer/reviewer:
aiq-evals revision:
Upstream engine/revision:
Python/runtime identity:
Dependency lock or container digest:
Command/test ID:
Output artifact path/checksum:
Outcome:
Failure classification (if any):
Notes/limitations:
```

Do not record credentials. Preserve failed/retried attempts rather than replacing
them with only the eventual green attempt.

## Repository bootstrap evidence

### P1-01 - evidence ledger

Status *(bootstrap snapshot, superseded)*: COMPLETE for repository scaffolding.

Evidence:

- this file defines the canonical record and required fields;
- `aiq_evals.phase1.PHASE1_TASKS` exposes the checklist programmatically;
- `aiq-evals phase1-status` reports the repository snapshot.

No native engine behavior is implied by this completion.

### P1-02 - pins and worker instructions

Status *(bootstrap snapshot, superseded)*: PARTIAL.

Implemented evidence tooling:

- `aiq-evals phase1-probe` captures Python/host and installed-engine facts;
- repeated `--checkout ENGINE=PATH` captures exact git HEAD, tracked cleanliness,
  origin URL, `requires-python`, and `uv.lock` presence;
- `aiq_evals.probes.isolated.build_locked_uv_command` constructs locked upstream
  `uv run` commands without adding engine dependencies to core;
- `validate_git_revision` rejects mutable branch/tag names when an immutable
  source revision is required.

Candidate/history facts currently known from supplied source material:

- original OLMo Eval plan inspection:
  `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`;
- supplied `eval_audit` OLMo prototype revision:
  `c84828e4af096004c561b668b68e0b126c7f60e9`;
- existing MAGNET dependency declaration: `crfm-helm>=0.5.8`.

None of these is yet the `aiq-evals` supported pin. Selection requires the native
fixture suite below.

## Runtime items

### P1-03 - OLMo Eval generation + tool execution

Status *(bootstrap snapshot, superseded)*: OPEN.

Required artifacts:

- scored generation fixture;
- tool-calling multi-turn fixture;
- request/prediction/trajectory artifacts;
- failure-after-diagnostics fixture;
- worker registration and cleanup evidence.

### P1-04 - Inspect generation + tool execution

Status *(bootstrap snapshot, superseded)*: IMPLEMENTATION PRESENT; NATIVE EVIDENCE OPEN.

The phase-4 adapter targets candidate release `inspect-ai==0.3.272` through the
public eval/log APIs. Fake-native and owned-worker contract tests are recorded in
`phase4-evidence.md`; they do not satisfy this native gate.

Required artifacts:

- scored generation fixture;
- solver/agent tool fixture;
- multi-log/sample-error/epoch/reducer fixtures;
- cancellation/nonterminal fixture;
- worker import/cleanup evidence.

### P1-05 - HELM compute/reuse/import

Status *(bootstrap snapshot, superseded)*: OPEN.

Required artifacts:

- fresh computation;
- cached reuse/materialization;
- native run import;
- aggregate/per-instance records;
- unknown/incomplete coverage fixture.

### P1-06 - async/worker/cleanup

Status *(bootstrap snapshot, superseded)*: OPEN.

Must be demonstrated with selected native pins.

### P1-07 - capability matrix

Status *(bootstrap snapshot, superseded)*: PARTIAL.

The matrix categories are defined in `aiq-evals-plan.md`; no runtime capability
is yet marked supported in this new repository.

### P1-08 - EEE normalization decision

Status *(bootstrap snapshot, superseded)*: OPEN.

The supplied `eval_audit` source demonstrates that EEE was already considered a
normalization substrate, but its `every_eval_ever` submodule contents were not
present in the supplied archive. This repository therefore does not infer the
current EEE schema from that snapshot. Inspect the real current EEE source and
run fixture conversions before deciding.

### P1-09 - OLMo Eval packaging go/no-go

Status *(bootstrap snapshot, superseded)*: OPEN.

Default hypothesis: prefer an isolated locked upstream worker if co-installation
is not cleanly reproducible. This is not yet a decision.

### P1-10 - acceptance gate

Status *(bootstrap snapshot, superseded)*: BLOCKED by P1-02 through P1-09 runtime evidence and the separate MAGNET
cardinality experiment.

## Local build-environment observation

At archive creation time the current build interpreter did not have `helm`,
`olmo_eval`, `inspect_ai`, `kwdagger`, or `magnet` installed. Consequently no
native runtime success is claimed by this archive. The dependency-free core test
suite is the only executed validation recorded by the archive builder.

### API-surface probe support

`aiq-evals phase1-probe` also checks the intended public OLMo Eval and Inspect
adapter seams when those packages are installed. These symbol checks are only a
compatibility precondition; a symbol existing is not evidence that execution,
status mapping, or cleanup semantics work.

## 2026-09-29 native validation campaign

Evidence producer: GPT-6-Sol (OpenAI). All `aiq-evals` revisions below are
ancestral commits in this campaign; the Inspect partial-coverage correction is
at `b1f64cf`. All tests used deterministic local providers or preserved native
files, with no external model service. Fixture paths are relative to this repo.

### P1-02: tested pins and reproducible environments — PARTIAL

| Engine | Tested version/revision | Python | Reproduction and isolation |
| --- | --- | --- | --- |
| Inspect | `inspect-ai==0.3.272` | CPython 3.11.15, `/tmp/aiq-inspect-p1` | `uv venv --python 3.11 /tmp/aiq-inspect-p1`; `uv pip install --python /tmp/aiq-inspect-p1/bin/python -e '.[inspect,tests]'`. The adapter executes in an owned process; the package's optional extra installs Inspect only when requested. |
| OLMo Eval | checkout `73ade80e24f796af55caeb8fd7b75a7f3fd607fd`; upstream `uv.lock` SHA256 `8c3ac8e85dad2de9d7934df0c6c7cf645648effdc955d0b84bea942f1ab4217e` | CPython 3.12.3, `/tmp/olmo-eval-p1/.venv` | At that checkout: `uv sync --frozen --no-default-groups --extra litellm --extra agents --python 3.12`; `uv pip install --python .venv/bin/python pytest`. Run with `PYTHONPATH=/home/joncrall/code/aiq-evals`. Isolated worker required for the chosen delivery mode. |
| HELM | `crfm-helm==0.5.14`, MAGNET checkout `7bb105ab1c85bfaa01bf68c97ff7523332479ee4` | CPython 3.12.3, `/tmp/aiq-helm-p1` | `uv venv --python 3.12 /tmp/aiq-helm-p1`; `uv pip install --python /tmp/aiq-helm-p1/bin/python -e '/home/joncrall/code/aiq-magnet[helm]' 'crfm-helm==0.5.14' pytest`. This pulls large Torch/CUDA dependencies; keep it isolated from core. Only import/reuse is tested at this pin. |

OLMo checkout was clean. The candidate source revision was selected for the
native local smokes, but no cross-revision compatibility claim is made.
Inspect and OLMo pins are supported for the tested combinations in the matrix;
HELM's pin is an import/reuse pin only until fresh execution succeeds. No
complete lock authority exists for the Inspect/HELM pip environments, so their
reproduction is version-pinned at the engine level, not byte-for-byte locked.

### P1-03: OLMo Eval — native gates demonstrated, broader support open

`aiq-evals` revisions: `225a40a`, `9a06d1a`, `9579d33`.
Upstream: OLMo checkout and Python environment above. Command:
`PYTHONPATH=/home/joncrall/code/aiq-evals /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_olmo_native.py`
(4 passed). Native registration imports `tests.native.olmo_fixture` in both
owned evaluation and spawned inference workers. The mock-provider task scored
`contains_42=1.0` and wrote request, prediction, and metrics files; native
reimport succeeded. The local HTTP LiteLLM/OpenAI Agents task made two actual
model requests and called `double`, yielding assistant/tool/assistant turns and
`contains_42=1.0`. It also reimported from native artifacts. Source checksums:
`olmo-native/metrics.json` SHA256 `d723ed6575ed0ba9b7bfda407406e12c79c735986ad8e6ad52212662d58fa4ca`;
`olmo-native/tool/metrics.json` `8b2e448cf40780ef8a483535d6c7e971b4ae4a2c80fd240cad7bb48d20f5fbca`;
`olmo-native/tool/predictions.jsonl` `2080fb21c3ab11d08f066e6f356c8bc2784659fbff513a9e61b570b6f52964b5`;
`olmo-native/tool/requests.jsonl` `820b1b5cf392cb59436483ea6220f444495ecd11eb21c37cc7dfc7b320b8c631`.

The forced native `HardFailureRateExceeded` wrote `olmo-native/failure/metrics.json`
(SHA256 `d2f6f63f4fe2bc33add49da33d647809331b47045d9e3703eccd9372f7afe42d`):
processed 1, saved 0, failed 1. The attempt was failed and lacked a successful
run marker. The first agent-tool attempt exposed missing registration in an
inference worker; the adapter was fixed to bootstrap those modules. The worker's
redacted stdout/stderr are retained. Tool capability is confined to this
scaffold/provider; log probabilities, sandboxing, resume, rescore, and
multi-task native runs remain untested.

### P1-04: Inspect — native gates demonstrated for local provider

`aiq-evals` revisions: `07d361f`, `9a06d1a`, `b1f64cf`.
Command: `/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_inspect_native.py`
(7 passed). Native generation scored `match` and `includes`; native tool
execution produced a tool message with result `4`. The three-log fixture
contains generation, tool, and auxiliary-role tasks; the auxiliary `grader`
model and primary model both appear in native events. Two epochs and explicit
`mean`/`mode` reductions were observed. `.eval`, JSON, and a directory of
multiple logs imported successfully. `partial/partial.eval` records one failed
sample and one completed sample; native log status is `success`, while normalized
coverage is correctly `partial` (expected 2, processed 2, failed 1).

Artifacts/checksums: `inspect-native/generation.eval`
`2a4e6767749575dc18667ebebbd93455b1174836d8936fba1a4d3b6808df0adf`;
`generation.json` `b796f1379db77164acdcf3deaeb1eaf2d5f15d7a43b6debcb273af844f38893b`;
`tool.eval` `47b086e66f452ba0d7cf721005af9733af20afba229f3cb73c9492f769c5131c`;
`multi/{generation,tool,role}.eval` respectively
`8b7c96bba0984c853c1ad689f5b37b6581a86025cbcb8c0064008b04bb8443a8`,
`0e3fe54264e247967caf6c578d00aecceab1fcc5df94f892538e3b67a65f1640`,
`cd899d986ff7a5101bffd0ded36b718f7b44244c6963a283fa397bdc8f7edff1`;
`reducers/reducers.eval` `77337ad4ea6b7d75d293433aefc57b00143f7913a2fd9a3122cab59c0234df5f`;
`partial/partial.eval` `08649630fb96aff7784121776d5c097a1b5a967a76a6742bfa9f5b01b966f552`.

A failed initial partial-coverage assertion caught an adapter error: counting
logged samples as complete ignored `completed_samples`. Fixed at `b1f64cf`.
Absolute local task file paths also failed under Inspect's Python 3.11
`Path.glob`; the adapter now passes a relative path and imports declared
registration modules. Native top-level error/cancelled log import, engine-owned
sandbox cleanup, resume/rescore, and log probabilities remain untested.

### P1-05: HELM — import/reuse evidence, fresh execution blocked

`aiq-evals` revision `e895107`; MAGNET and HELM pins/environment above. Command:
`/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_helm_native.py`
(1 passed). Historical native run from EEE revision
`1eb9d39aed34505e15db637153de72318bd946d4` is in
`tests/fixtures/helm-native/mmlu-philosophy-gpt2/`; its original HELM
version/Python are unknown. `stats.json` SHA256
`2ef96498f2464c6830e252f8aaf9261e163105f5c39ab474b1acfccb1a0565b2`
and `per_instance_stats.json` SHA256
`6b444efb07af4d1bb9496e177a57d9708aacd5a9c5592c506dbfe2179da35deb`.
MAGNET materialized the directory in `reuse_only` mode and read 162 aggregate
statistics and 10 per-instance entries. A derived copy without
`per_instance_stats.json` reused only with
`--require-per-instance-stats false`; complete sample coverage cannot be
inferred from its aggregates. Initial reuse of the unwrapped EEE directory
failed because MAGNET requires `benchmark_output/runs/<suite>/<run>` layout;
the fixture test wraps it in that layout. Fresh HELM computation is still open,
so the P1-05 and P1-10 gates remain open. No Phase-5 adapter was added.

### P1-06: cancellation and lifecycle — owned process proof, sandbox open

`aiq-evals` revision `9a06d1a`. Native tests above cancel asynchronous
runs after a child PID is emitted. Both OLMo and Inspect tests show their owned
child gone or reaped as a zombie, `ATTEMPT_TERMINAL=cancelled`, and no
`RUN_COMPLETE`. The `aiq-evals` runner owns the adapter worker process group;
OLMo owns its inference worker and Inspect owns its local provider invocation.
This proves cleanup of the tested child processes, not arbitrary
engine-managed sandboxes or remote resources. A prior cancellation test using
an uninstrumented fast task could finish before cancellation; a slow child
fixture was used for deterministic observation.

### P1-07: matrix — PARTIAL

The combination-level matrix is `docs/planning/phase1-capabilities.md`.
Unknown claims remain explicitly untested rather than inferred from upstream
source or marketing.

### P1-08: EEE schema — DECIDED, see ADR-0008

EEE revision `1eb9d39aed34505e15db637153de72318bd946d4`, schema 0.3.0;
aggregate schema SHA256 `c9c6195aec8a9dfa0b2aba4924ac1aa8a184c9d8ca97cee778cb531088e39b48`,
instance schema SHA256 `b16b7fa7f0aa32763444179d94ffb2336ddb12c3fd2903835fe491666c1ff3e6`.
In Python 3.12 with EEE 0.3.0, the HELM converter command equivalent to
`HELMAdapter().transform_from_directory(fixture, metadata_args={'file_uuid':
'12345678-1234-4234-8234-123456789abc'}, output_path='/tmp/aiq-eee-helm-converted')`
produced one aggregate log, 48 evaluation results, and 80 instance rows over
10 sample IDs. The first attempt omitted `file_uuid` and failed with
`file_uuids[0] is required`. In `/tmp/aiq-eee-inspect-p1` (Python 3.12,
EEE 0.3.0, Inspect 0.3.272), conversion of both `.eval` and JSON generation
fixtures failed with `Cannot determine model developer from model path
'fixture/local'`. No OLMo converter exists. Schema inspection found required
Boolean correctness, string-only tool arguments and metadata, and no unambiguous
first-class epoch/reducer/scorer/status/coverage fields. ADR-0008 keeps the
independent normalized result schema; native files remain authoritative.

### P1-09: OLMo packaging — ISOLATED WORKER SELECTED

The locked upstream Python 3.12 environment passes generation, tool execution,
import, hard failure, and cancellation; core supports Python 3.11 and has no
OLMo dependency. Therefore OLMo is delivered through the isolated pinned
worker checkout above. A reproducibly co-installed optional extra was not
established and is not advertised. The local HTTP fixture avoids external
credentials but only proves that tested scaffold/provider combination.

### MAGNET cardinality spike — BLOCKED BY MISSING PROJECTION

MAGNET revision `7bb105ab1c85bfaa01bf68c97ff7523332479ee4`.
The actual Inspect `multi/` logs show three result records and two epochs;
OLMo fixtures currently show one task each. Inspecting MAGNET's existing
`build_tables`, `KWDaggerProcessor.load_available_result_rows`, and
`ClaimResultNamespace` shows that they consume already flattened DAG result
rows. There is no current projection from an `aiq-evals` multi-result run into
one MAGNET evidence row, nor a native multi-result OLMo fixture. Passing these
fixtures through those paths would require the later MAGNET integration, which
is outside Phase 1. No claim-vote cardinality result is asserted. The P1-10
acceptance gate remains open.

### Final local validation — 2026-09-29

At `b1f64cf` plus import-only lint commit `b2e008e` and the documentation
commit that contains this record:

- `python -m pytest -q`: 48 passed, 3 native skips (base interpreter has no engines).
- `python -m compileall -q aiq_evals tests`: passed.
- `ruff check .`: passed after clearing 10 import/unused-import lint findings;
  the first check failed with 9 findings before the new native fixture added one.
- `/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_inspect_native.py`: 7 passed.
- `PYTHONPATH=/home/joncrall/code/aiq-evals /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_olmo_native.py --basetemp=/tmp/aiq-olmo-final2`: 5 passed after the multi-task suite was added.
- `/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_helm_native.py --basetemp=/tmp/aiq-helm-final`: 3 passed, 4 upstream MAGNET deprecation warnings after fresh generic and scored fixtures were added.
- A clean `/tmp/aiq-core-p1` CPython 3.11.15 environment built with
  `uv venv --python 3.11 /tmp/aiq-core-p1` and
  `uv pip install --python /tmp/aiq-core-p1/bin/python -e .` imported
  `aiq_evals`, parsed an `EvaluationRequest`, and loaded
  `tests/fixtures/run-v1`. `find_spec` returned no Inspect, OLMo, or HELM.
  `RunBundle.load` then read the native OLMo success (1 result, 1 sample),
  native OLMo failed bundle (1 result, 0 samples), and native Inspect
  multi-log bundle (3 results, 11 sample/reduction records) with that same
  engine-free interpreter.
- No static type checker is configured in `pyproject.toml`; Ruff is the
  configured lint check.

For the MAGNET blocker, the source inspection commands were
`rg -n 'build_tables' /home/joncrall/code/aiq-magnet` and
`rg -n 'aiq_evals|inspect_ai|olmo_eval' /home/joncrall/code/aiq-magnet/magnet -g '*.py'`.
The latter returned no projection. `build_tables` is imported from kwdagger
inside `magnet/_kwdagger.py`, and its rows are handed to
`ClaimResultNamespace` by MAGNET. The native multi-log/epoch fixtures cannot
be presented to these paths as one claim row without implementing the future
MAGNET projection.

## 2026-09-29 follow-up: fresh HELM and OLMo multi-task fixtures

These records supersede the earlier P1-05/MAGNET notes where they said HELM
fresh execution and an OLMo multi-task fixture were still absent. MAGNET's
one-claim-row projection remains absent.

### HELM fresh computation — demonstrated

`aiq-evals` revisions `05a665f` (generic generation) and `ad6b69a`
(scored MCQA); `crfm-helm==0.5.14`, MAGNET `7bb105ab1c85bfaa01bf68c97ff7523332479ee4`,
CPython 3.12.3 in `/tmp/aiq-helm-p1`. The reproducible native command is
`/tmp/aiq-helm-p1/bin/python -m pytest -q tests/native/test_helm_native.py`
(3 passed, four MAGNET deprecation warnings). The test prepends the worker's
`bin` directory to `PATH` so MAGNET invokes that environment's `helm-run`.

The direct first attempt without that `PATH` used a global `helm-run` entrypoint
whose interpreter lacked `helm` and failed with `ModuleNotFoundError`. A second
attempt with `simple1` but no `model=` run expander failed because HELM required
`--models-to-run`. The successful generic command, run from the worker Python
with its `bin` first on `PATH`, was:

`python -m magnet.backends.helm.cli.materialize_helm_run --run-entry 'simple1:model=simple/model1' --suite aiq-p1-fresh --max-eval-instances 1 --out-dpath /tmp/aiq-helm-fresh3 --mode compute_if_missing --num-threads 1`

It ran HELM's real local SimpleClient, computed 30 requests, and wrote 57
aggregate statistics and 30 per-instance trial rows (10 test IDs, three train
trials). Native fixture `tests/fixtures/helm-native/simple1-fresh/` has
`stats.json` SHA256 `d8b2b44018ce5360802f083030961b6977ecf57dcb9f31943c3e2db516f2ffdd`,
`per_instance_stats.json` SHA256
`3480ed7df61b97d9d3d87ca13e6a2ee7ac06b121c166130e8f643ef9bf0dc1e3`,
and `scenario_state.json` SHA256
`48a8c0eb817180e99a568a2843f216abd4ee92df8ad94d667b4a0de9d7e45e09`.
The supplied `--max-eval-instances 1` did not reduce this simple1 scenario's
10 test IDs; the observed output, rather than the CLI value, is the coverage
claim.

A separate fresh scored run used:

`python -m magnet.backends.helm.cli.materialize_helm_run --run-entry 'simple_mcqa:model=simple/model1' --suite aiq-p1-scored --max-eval-instances 1 --out-dpath /tmp/aiq-helm-scored --mode compute_if_missing --num-threads 1`

It made one new native request, produced 81 aggregate statistics including
`exact_match` with count 1 and mean 0.0, and one per-instance row. A zero score
is still a demonstrated native score; it is not called a successful answer.
`tests/fixtures/helm-native/simple-mcqa-fresh/stats.json` SHA256
`666ecfb4acd8e47a48fc325285838003f8768702d8bdef50d49feaec4735862e`;
`per_instance_stats.json` SHA256
`cf67c7007ff0f82e0a8ca77d75345f59f9042db8e1f54566b746732b545da885`;
`scenario_state.json` SHA256
`0521e14243eb6465b5d3bfd0b564a186a8a6fcd69d5aa4600819b24697ef58f5`.
This closes fresh HELM execution for the tested local simple model. No external
HELM provider is claimed.

### EEE against newly captured HELM fixtures

EEE revision `1eb9d39aed34505e15db637153de72318bd946d4` in the isolated
HELM CPython 3.12.3 environment. Running `HELMAdapter().transform_from_directory`
with `metadata_args={'file_uuid':'12345678-1234-4234-8234-123456789abc'}`
and an output path converted `simple-mcqa-fresh` to one log and 24 evaluation
results plus a samples JSONL. The same call on `simple1-fresh` raised
`SourceRecordsError`: none of its generic generation metrics were recognized
as a benchmark score. An initial run in the EEE/Inspect environment failed
because the EEE `helm` extra's `dacite` dependency and HELM were absent there;
using the isolated HELM environment with `dacite` resolved the import gate.
This strengthens ADR-0008: even valid new HELM output does not always convert
without an EEE metric policy change.

### OLMo native multi-task suite — demonstrated

`aiq-evals` revision `5ed0483`, OLMo revision and environment as above.
Command: `PYTHONPATH=/home/joncrall/code/aiq-evals /tmp/olmo-eval-p1/.venv/bin/python -m pytest -q tests/native/test_olmo_native.py -k multi_task --basetemp=/tmp/aiq-olmo-multi`
(1 passed). The registered `aiq_p1_multi` suite expanded to
`aiq_p1_local` and `aiq_p1_local_alt`. The native run produced two complete
scored result records, separate request/prediction files, and a native metrics
file; native import preserved both records. The fixture
`tests/fixtures/olmo-native/multi/metrics.json` SHA256 is
`40f3716d04e4b7eb6b3af9ba6d5e6baf5cf162ea0f7a86db641d9eeb2145887f`.
The two request and prediction file checksums are available from `sha256sum
 tests/fixtures/olmo-native/multi/*`; the local-task prediction content is
identical for both tasks, but separate native task records are proven by metrics
and artifact paths.

The MAGNET cardinality experiment now has real multi-result fixtures from both
engines. It remains blocked at the MAGNET projection boundary: neither
`build_tables` nor `KWDaggerProcessor.load_available_result_rows` reads these
engine bundles directly, and `ClaimResultNamespace` accepts one already flat
row. We did not add the later integration merely to make this spike pass.

## 2026-09-29 follow-up 2: Inspect nonterminal statuses and environment constraints

Evidence producer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).
These records supersede the P1-04 note above that native top-level
error/cancelled log import was untested.

### P1-04: Inspect run-level error, cancelled, and started logs — demonstrated

`aiq-evals` revision `10d1c9b`; `inspect-ai==0.3.272`, CPython 3.11.15,
`/tmp/aiq-inspect-p1`. Command:
`/tmp/aiq-inspect-p1/bin/python -m pytest -q tests/native/test_inspect_native.py`
(10 passed). Local fixture provider only.

Probing first showed that Inspect writes run-level `error` and `cancelled` logs
with `results=None`. The adapter then reported bare `unknown` coverage although
the log held native sample records. Coverage for such logs is now derived from
logged samples and from Inspect's own expected count,
`len(eval.dataset.sample_ids) * epochs` (see `inspect_ai/_eval/task/log.py`
at the pin). It stays unknown when samples were not read or sample IDs are
absent. Engine-free unit coverage is in `tests/test_inspect_adapter.py`.

- **Run-level error through the adapter.** `run_error_task` uses
  `fail_on_error=True`, three samples, and `max_samples=1`. Native status
  `error`; sample 1 scored, sample 2 raised, and sample 3 was cancelled by
  Inspect. Normalized status `failed`, coverage partial
  (expected 3, processed 3, failed 2), no metrics, `ATTEMPT_TERMINAL=failed`,
  and no `RUN_COMPLETE`. Re-importing the native log gives the same status and
  coverage. Fixture `inspect-native/error/run-error.eval` SHA256
  `2b2ef05904e8bffa079933de84983f545a5840f666d2f84dab2e2aaa35eed44f`.
- **Native cancellation (SIGINT).** An Inspect process running `slow_task`
  received SIGINT after the provider started. `eval()` returned `[]` and exited
  0, and Inspect wrote a `cancelled` log with one errored sample. The import
  status is `cancelled`, with partial coverage (1/1/1) and no `RUN_COMPLETE`.
  The adapter's fallback of reading `log_dir` after an empty return is
  therefore exercised by real behavior. Fixture
  `inspect-native/cancelled/cancelled.eval` SHA256
  `244e16dbf45bcdd612526818f6888e05d1a7894e58f3aaaeab834260c70bea08`.
- **Nonterminal (SIGKILL).** Killing the process leaves a native `started` log
  with zero samples, the same state that killing an owned worker process group
  produces. The import status is `incomplete`, with partial coverage
  (expected 1, processed 0) and no `RUN_COMPLETE`. Fixture
  `inspect-native/nonterminal/started.eval` SHA256
  `5e226ea2b8346aa5e7b568f9678a5016b52f538a70d8581aae6bce8e5c596ed0`.

The clean engine-free `/tmp/aiq-core-p1` interpreter (CPython 3.11.15, no
`inspect_ai`) loaded the published failed and cancelled bundles with
`RunBundle.load`.

Limitations: the SIGINT fixture's `sleep` grandchild was *not* cleaned up by
Inspect. The test kills it explicitly, and no Inspect cleanup claim follows.
An aiq-evals asynchronous cancellation still kills its owned worker group, as
the earlier record shows; it does not produce Inspect's own `cancelled` log.
Engine-owned sandbox cleanup remains untested.

### P1-02: exact environment constraints — captured and reproduced

`uv pip freeze` output from the tested worker environments, with editable
checkouts removed, is committed as:

- `dev/environments/phase1/inspect-py311-constraints.txt` (85 pins,
  CPython 3.11.15, x86_64 Linux);
- `dev/environments/phase1/helm-py312-constraints.txt` (165 pins,
  CPython 3.12.3, x86_64 Linux, `torch==2.14.0` CUDA 13.0 build). Its header
  names the editable MAGNET and EEE revisions.

Both files were checked by rebuilding each environment from scratch in a
scratch directory:

```sh
uv venv --python 3.11 $R/inspect
uv pip install --python $R/inspect/bin/python \
  -c dev/environments/phase1/inspect-py311-constraints.txt -e '.[inspect,tests]'
uv venv --python 3.12.3 $R/helm
uv pip install --python $R/helm/bin/python \
  -c dev/environments/phase1/helm-py312-constraints.txt \
  -e '/home/joncrall/code/aiq-magnet[helm]' 'crfm-helm==0.5.14' pytest
```

In each rebuilt environment the `uv pip freeze` output was identical to the
constraints file. The native Inspect suite passed there (10 passed), as did the
native HELM suite with that `bin` first on `PATH` (3 passed). These are
version pins, not hash locks. They also depend on the local uv cache and on
platform wheels. OLMo keeps its upstream frozen `uv.lock` as the lock
authority. Top-level requested sets: Inspect `aiq-evals[inspect,tests]`; HELM
`aiq-magnet[helm]` + `crfm-helm==0.5.14` + `pytest`; OLMo upstream
`--extra litellm --extra agents` + `pytest`. These are the tested sets; they
have not been proven minimal.

At capture time the MAGNET checkout had an uncommitted one-line change in
`magnet/demo/helm_demodata.py` (demo output directory name). It is not used by
these native tests and was left untouched.

### Validation at `10d1c9b` plus this documentation commit

- `python -m pytest -q`: 49 passed, 3 native skips.
- `python -m compileall -q aiq_evals tests`, `ruff check .`: passed.
- Inspect native: 10 passed. OLMo native (`PYTHONPATH` = repo): 5 passed.
  HELM native: 3 passed, 4 MAGNET deprecation warnings.

The MAGNET cardinality spike is unchanged and still blocks P1-10.

## 2026-09-29 follow-up 3: review corrections, P1-06 lifecycle, and closure

Evidence producer: Claude Opus 5.5 (Anthropic, `claude-opus-5-5`, 1M context).
This follows an external review of the Phase-1 work. Environments are
unchanged from the records above.

### Identity and provenance corrections (`fbf84d0`)

- `measurement_inputs()` had hashed only `engine_revision` from
  `resolved_facts`. Editing an Inspect task file, or an OLMo/Inspect
  registration module, therefore left a *reusable* digest unchanged, which
  violates ADR-0003. Adapters now pass an explicit, path-free `identity_facts`
  subset (task source digest and module digests), and that subset enters the
  digest. A module without hashable source makes identity non-reusable. The
  identity algorithm is now `aiq-evals-measurement-v2`.
- Adapter behavior changed during Phase 1 while `ADAPTER_VERSION` stayed
  `0.1.0`. Both adapters are now `0.2.0`, and `adapter_source_sha256` (a
  digest of the adapter package's Python source) also enters identity.
- `upstream_revision` had been recorded without being checked. The new
  `verify_engine_revision()` observes the revision from the imported module's
  tracked git checkout, or else from PEP 610 metadata. It rejects a
  contradicting request; an unverifiable claim or a dirty checkout makes
  identity non-reusable. Natively, in the OLMo environment, the request
  `73ade80…` resolved as reusable with `engine_revision_source=git-checkout`.
  Requesting the `eval_audit` SHA `c84828e…` against that checkout raised
  `EngineCompatibilityError`.

### Secret redaction of returned results (`b2f199f`, refined in `ee7fe7a`)

Adapter diagnostics, including native exception text and tracebacks, were
published unscrubbed. Every key and string leaf of the returned result is now
scrubbed of `ExecutionContext.env` values of at least 8 characters. The first
native sandbox run showed that scrubbing the value `"1"` corrupted the
measurement digest, so shorter values are skipped and named in
`env_values_not_redacted_as_too_short`, and the resolved identity is always
kept. Worker log files are still scrubbed of every value. Native engine
artifacts are retained unmodified: an engine that writes a credential into its
own log is not covered.

### Engine-free fixture regression (`273cfbe`)

`tests/test_native_fixture_regression.py` runs in the dependency-free suite.
Inspect `.eval` entries are zstd-compressed (zip method 93), which the stdlib
cannot read before Python 3.14. `dev/regenerate_native_regressions.py`
therefore writes each fixture through Inspect's own JSON writer into
`inspect-native/json/`, and records goldens normalized from the native
`EvalLog` objects. The tests normalize the plain JSON dicts and must reproduce
those goldens. OLMo import is already engine-free.

This surfaced a real OLMo import bug: prediction files were attributed to tasks
by substring. In the native two-task suite, the `aiq_p1_local_alt` sample was
therefore assigned to a nonexistent task named `aiq_p1_local_alt_494d4e`, so the
earlier "native import preserved both records" held for records but not for
samples. Attribution now follows upstream's `<sanitized spec>[_<hash6>]`
naming (`write_predictions_jsonl` at the pin). The native multi-task test now
asserts sample attribution after both execution and import.

**Fixture paths changed.** The OLMo generation and tool fixtures had been
committed with the native filename prefix removed, so native import (which
discovers `*-predictions.jsonl`) never read them. Contents and SHA256 values are
unchanged; see `tests/fixtures/olmo-native/README.md`:

- `olmo-native/metrics.json` → `olmo-native/generation/metrics.json`;
- `olmo-native/{predictions,requests}.jsonl` →
  `olmo-native/generation/aiq_p1_local-{predictions,requests}.jsonl`;
- `olmo-native/tool/{predictions,requests}.jsonl` →
  `olmo-native/tool/aiq_p1_tool-{predictions,requests}.jsonl`.

### P1-06: active-loop boundary and lifecycle — demonstrated (`ee7fe7a`)

Entry points at the pins:

| Engine | Public sync entry | Inside an active loop | Public async entry used by aiq-evals |
| --- | --- | --- | --- |
| Inspect 0.3.272 | `inspect_ai.eval()` | raises `RuntimeError: Already running asyncio in this thread` | none: `eval()` runs in an owned worker's main thread (`execute_blocking`), or via `asyncio.to_thread` in-process; `eval_async` exists but is unused |
| OLMo 73ade80 | `AsyncEvalRunner.run()` = `asyncio.run(run_async())` | raises `asyncio.run() cannot be called from a running event loop` | `AsyncEvalRunner.run_async()` awaited directly |

`test_active_event_loop_boundary` in both native suites shows the following
from inside a running loop:

- the native sync entry fails;
- `run_evaluation()` raises `ActiveEventLoopError` instead of nesting;
- the adapter's `execute()` succeeds in-process;
- `run_evaluation_async()` with a worker succeeds.

Sandbox cleanup. `inspect_sandbox_fixture.sandbox_task` runs its tool through
`sandbox().exec` in Inspect's `local` sandbox, whose `TemporaryDirectory` is
removed by `sample_cleanup`.

- On completion: tool result `4`, and the recorded directory is gone.
- On cancellation, before this change: SIGTERM to the worker group killed
  Inspect before `sample_cleanup`, and `/tmp/tmpkhp4t1o3` leaked. The owned
  processes were gone and only a `started`-status log remained.
- On cancellation, after this change: the runner sends SIGINT, waits up to
  `CANCEL_GRACE_SECONDS` (15), then escalates to SIGTERM (5 s) and SIGKILL.
  The worker runs Inspect's `eval()` on its main thread, so Inspect handles the
  interrupt: the sandbox directory is removed, the sandbox `sleep` child is
  gone, and Inspect writes a `cancelled` log. That log's records are published
  with `ATTEMPT_TERMINAL=cancelled` and no `RUN_COMPLETE`.
- Docker sandboxes were not tested: the test user cannot access the Docker
  socket. OLMo sandboxes were not tested.

OLMo cancellation passes, but it took 15.9 s: the fixture's slow task blocks its
event loop with synchronous `time.sleep`, so asyncio cannot deliver the SIGINT
cancellation, and the SIGTERM escalation cleaned up. Cooperative OLMo cleanup
under SIGINT is therefore not demonstrated.

Lifecycle ownership:

| Boundary | Owner | Termination / cleanup |
| --- | --- | --- |
| Worker process group (`start_new_session`) | `aiq-evals` runner | SIGINT, then 15 s grace, SIGTERM, 5 s, SIGKILL, and a final group SIGKILL |
| Worker stdout/stderr | runner (files under `native/aiq_worker/`) | redacted after exit, retained in the bundle |
| Work directory and atomic publication | runner/`publish_run` | removed after publication; terminal markers always written |
| Inspect eval loop, samples, sandboxes, logs | Inspect, in the worker's main thread | Inspect's SIGINT handling, `sample_cleanup` |
| OLMo `AsyncEvalRunner` and its spawned inference workers | OLMo, in the worker's asyncio task | task cancellation (SIGINT via `asyncio.run`), runner `finally` |
| HELM run through MAGNET | MAGNET/HELM | not an aiq-evals adapter yet (phase 5) |

### P1-10: Phase 1 closed

The MAGNET cardinality spike moved to integration gate M6
(`aiq-magnet-integration-plan.md`). It needs the MAGNET projection scheduled after
the adapters, and Phase 1 supplied its native multi-result inputs. The remaining
conditions have records in this ledger:

| Condition | Evidence |
| --- | --- |
| exact pins/environments for all three engines | P1-02 records, `dev/environments/phase1/`, OLMo `uv.lock` |
| native scored generation in all three | OLMo `contains_42`, Inspect `match`/`includes`, HELM MCQA `exact_match` |
| real multi-turn tool execution in OLMo and Inspect | OLMo Agents `double`, Inspect `use_tools` `double` and sandbox tool |
| failure/cancellation fixtures | OLMo hard failure; Inspect sample/run error, cancelled, started; cancellation of both |
| worker cleanup | owned child processes (both); Inspect local sandbox |
| EEE decision | ADR-0008 |
| OLMo packaging path | isolated pinned worker (P1-09) |

Still untested, and still marked T in the matrix: log probabilities, resume,
rescore, Docker/OLMo sandboxes, HELM cancellation, and external providers.

### Validation at this record

- `python -m pytest -q`: 78 passed, 3 native skips. The same result holds on
  the engine-free `/tmp/aiq-core-p1` CPython 3.11.15, where `find_spec`
  returns `None` for `inspect_ai`, `olmo_eval`, and `helm`.
- `ruff check .`: passed.
- Inspect native: 13 passed. OLMo native: 6 passed. HELM native: 3 passed.

### Correction: MAGNET `--require-per-instance-stats` is inert on reuse

The P1-05 record said the derived copy without `per_instance_stats.json`
"reused only with `--require-per-instance-stats false`". Reading MAGNET
`7bb105ab` `materialize_helm_run.py` shows that the completeness check in its
reuse search is commented out. That flag therefore does not affect reuse, and
the incomplete copy would also have been reused with it set to true. MAGNET
matches reusable runs by name tokens only: it does no hashing and checks no
HELM version or model configuration. The aiq-evals HELM adapter (phase 5) does not
inherit this behavior. See `phase5-evidence.md`; phase-6 reuse must stay
identity-based.

## 2026-09-29: package rename (no evidence change)

The Python module `aiq_evals` is now `magnet_evals`, and the distribution
`aiq-evals` is now `aiq-magnet-evals`, mirroring `aiq-magnet-theory`. Records
above keep the module names that were used when they were made; read
`aiq_evals.X` as `magnet_evals.X` today. Data-format identifiers are unchanged
on purpose: the identity algorithm `aiq-evals-measurement-v2+sha256`, native
log metadata keys such as `aiq_evals_measurement_identity`, and the committed
fixtures. The repository and directory will be renamed to `aiq-magnet-evals`
separately.

## 2026-11-19: completed native verifier failures with missing tests

Retained Harbor 0.23.0 replay output shows the official Pro verifier reaching
`RESULT: FAILED`, returning reward zero, with nine of ten required tests passed
and one absent. Required-test presence is a diagnostic, not an additional
condition for accepting this completed native verdict. Missing tests can be the
reason the upstream verifier fails a patch. An early setup trap without the
native final RESULT line remains incomplete.

Evidence: `tests/fixtures/swebench-pro-verifier-failed/capture.json` lists hashes
of the retained stdout, parsed test results, reward and task test configuration.
No agent trajectory, model configuration or execution environment is included.
`test_completed_native_failure_keeps_its_missing_test_diagnostics` reads this
capture without running Harbor or tests. Existing oracle/NOP/native replay
fixtures still normalize to their original rewards; an additional regression
retains the incomplete status when a final verdict is absent.
