# Verified failure audit: 2026-11-04

The three unresolved instances in the completed HyperQwen TP=4 smoke have
identifiable patch defects. Two consumed the 200-message budget, but neither
ended in the middle of a promising corrective edit. A larger message limit
alone is not supported as the primary remedy by these trajectories.

This audits the November 3 run retained by the operator in
`benchmark_results/swebench-hyperqwen-eAnqbabA/`. It uses the normalized sample
messages/events, exact exported patches, per-instance official reports and raw
grader output. Message references below are zero-based positions in the
normalized sample's `trajectory.messages`, not tool-call numbers. Original
artifacts were not changed. Extracted transcripts and a pure-parser check are
retained separately under that directory's `audit/`.

| Instance | Model events | Tool calls in messages | Final patch | Budget |
| --- | ---: | ---: | ---: | --- |
| `django__django-10554` | 99 | 89 | 2,449 bytes | Reached 200 messages |
| `django__django-10914` | 90 | 99 | 6,274 bytes | Reached 200 messages |
| `django__django-10999` | 24 | 24 | 1,446 bytes | Submitted before limit |

The native event stream also records the completed submission tool for the
last instance; that call is not present as an ordinary message tool call.
Counts in the table use the same message-based convention as the run journal.

## Union ordering: wrong fix, weak reproduction

For `django__django-10554`, the agent added
`compiler.query.clear_ordering(True)` inside `get_combinator_sql()` at message
154. Its added regression test requires a database feature unavailable on the
SQLite backend and was skipped: the tool output at message 179 reports 27
tests, three skips. Messages 180–198 then simulate SQL, repeat existing test
suites and investigate an incorrectly named test module. The final patch
still contains the original clearing-ordering change.

The official grader applied the patch successfully but retained the unresolved
verdict. Its report lists both required union regressions as failing. The raw
output ends in `get_order_by()` raising
`DatabaseError: ORDER BY term does not match any column in the result set.`
The submitted change is in a different compiler path and does not provide
the missing ordering column needed by that query. The reference patch adds
that column to the selection instead of clearing subquery ordering.

Much of the earlier work was spent trying to reproduce PostgreSQL behavior
with SQLite: message 61 has an app import error, 65 a SQLite syntax error,
67 an incorrect `get_compiler(conn=...)` call, and 85 reports missing
`psycopg2`. Message 87 shows a failed package download in the intentionally
offline sandbox. These are agent-side reproduction/setup detours, not failed
model transport or sandbox startup.

**Assessment:** the message cap limited exploration, but the final state was
repeated validation of the wrong fix with inadequate backend coverage. More
budget might permit reconsideration; the trace does not show reconsideration
already underway when it stopped.

## Upload permissions: requested fix plus an unnecessary regression

For `django__django-10914`, message 103 changes both
`FILE_UPLOAD_PERMISSIONS` to `0o644` and
`FILE_UPLOAD_DIRECTORY_PERMISSIONS` to `0o755`. Only the file default was
requested. At message 121 the agent also changes the existing directory
permission test to expect its new default. Later runs of that edited test
suite therefore provide misleading reassurance: message 159 reports 110
tests passing, with one skip.

Official grading passes the required
`test_override_file_upload_permissions` test. Its sole reported compatibility
failure is `test_override_file_upload_directory_permissions`: the preserved
test expects `None`, but the submitted directory default produces decimal
493 (`0o755`). This directly identifies the extra change as the regression.
The required behavior was implemented; unrelated behavior was changed too.

After the last edit at message 121, the agent performs bespoke upload checks,
many related test runs, and an attempted full suite. Messages 174–180 are
empty reads while waiting for that suite; it interrupts at 182. It then runs
more suites and hits the cap during diff review. It does not revert the
directory default. Locale errors and a root-user permission test also consume
time; the agent compares them with an unmodified tree and correctly finds
they are pre-existing.

**Assessment:** scope control and test independence are the main issues.
The evidence does not justify treating this as a missing-budget failure.
A file-default-only patch is a plausible repair, but no new patch was graded
as part of this audit and the original score remains zero.

## Negative durations: confidently completed with incorrect semantics

For `django__django-10999`, the agent follows the proposed regex edit in the
issue text at message 19, adds tests matching its interpretation at 22, and
submits after message 50. It treats the signs on hours/minutes/seconds as
independent components. Official regression expectations require a leading
minus to apply to the entire time portion, including signed zero hours.

| Input | Submitted parser, seconds | Official expectation, seconds |
| --- | ---: | ---: |
| `-15:30` | -870 | -930 |
| `-1:15:30` | -2670 | -4530 |
| `-00:01:01` | +61 | -61 |

These results were independently reproduced on the CPU by reconstructing
the pure parser from the captured pre-edit `text_editor` view and applying
the actual recorded model edit. No model inference or new official grading
was used. The check output is retained as `audit/sign-semantics-check.json`.

The agent's own tests pass because they preserve the old expectations for
leading minus signs and add independently signed component cases. Official
tests introduce the required whole-duration semantics; `test_negative` has
five failing subcases. The agent's final submission says the fix is verified,
so this is not an interrupted attempt or a shortage of messages.

**Assessment:** incorrect interpretation and self-confirming tests. Increasing
the message cap would not extend this normally completed attempt.

## Shared friction and reporting limits

The two capped failures each have ten model events with
`stop_reason=max_tokens` under the 4,096-token per-response limit. Recorded
output/reasoning token totals are respectively 114,173/98,054 for union
ordering and 74,821/64,452 for upload permissions. This distinguishes long
reasoning and per-response truncation from productive additional edits; it
does not establish that a higher token limit would improve the result.

Interactive Git pagers repeatedly require Return or `q`. Locale defaults cause
ASCII encoding failures, and some Django runs default to up to 128 processes.
These add tool-management work alongside the conceptual mistakes. They are
candidate generic environment/scaffold improvements, not proof of a broken
evaluation runtime.

Per-test report attribution is imperfect in these logs. The official duration
report lists `test_parse_postgresql_format` as failed, although its raw line
ends in `ok`; a preceding failing subtest shares that line. Likewise the union
report lists a second test whose raw line ends in `ok`, and formatting the first
failing subtest itself raises while representing a queryset. Conclusions above
use the raw assertions and submitted code as well as the aggregate JSON.
These attribution issues do not remove the demonstrated patch defects or
justify changing the unresolved verdicts.

## Decision before another run

The highest-value follow-up is a separately identified, generic agent/scaffold
experiment: constrain edits to requested behavior, keep existing tests as
independent checks, use noninteractive Git and a UTF-8 shell, bound test-runner
parallelism, and avoid retrying network installation in an offline sandbox.
Compare it with the retained 200-message baseline before assuming 400 messages
is the fix. No instance-specific gold edits or hidden test expectations should
be fed back into the evaluation prompt.

This audit launched no new GPU evaluation and changed neither the scoring
protocol nor the model predictions. All five instances remain officially
scored 2/5 overall. Source artifact hashes are recorded in
[the run journal](../../dev/journals/codex.md).
