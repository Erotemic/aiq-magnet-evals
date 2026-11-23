# ADR-0011: Single-flight acquisition and content-keyed imports

Status: Accepted (2026-09-29). Refines ADR-0002 and ADR-0006. The rule that the
first valid import seeds the canonical run is superseded by ADR-0012.
The requirement for import content in a scheduler node ID is superseded by
[ADR-0013](0013-offline-command-planning.md).

## Context

Two defects surfaced once MAGNET consumed `ensure`:

1. **Duplicate execution.** ADR-0003 keeps MAGNET's evidence selector out of
   the measurement identity, so several kwdagger nodes (for example a matrix
   over selectors) share one measurement. kwdagger cannot deduplicate them,
   because their node identities differ. Two concurrent `ensure` calls both
   missed the reuse check and both executed the native engine. The store only
   resolved the publication race; the phase-6 record deferred the
   computation race to "the scheduler", which structurally cannot see it.
2. **Ignored imports.** `ensure(import_source=...)` checked the canonical run
   before looking at the import. Importing different native artifacts for an
   already-stored measurement silently returned the old result. The original
   plan required the opposite: "import identity includes artifact content …
   re-importing an edited log produces a new result identity."

## Decision

**Single-flight acquisition belongs to the store.** Preventing two callers
from computing the same stored result is store integrity, not campaign
scheduling. `ResultStore.acquisition_lock(digest[, native_identity])` is an
`flock` on `locks/<dd>/<key>.lock`. It spans threads and processes sharing
the store, and the kernel releases it if the holder dies. `ensure` acquires it
for a reusable identity, re-checks for a published result under the lock, and
only then executes or imports. Waiters poll, so waiting stays cancellable.

- Callers that waited and find a result report `reused` (`waited=True`).
- Publication finishes before the lock is released, even if the holder is
  cancelled while publishing. Otherwise a waiter would find nothing and
  execute again.
- Canonical runs are only published under the measurement's lock. An import
  publishes only its own slot, under its (measurement, content) lock
  (ADR-0012: imports never seed the canonical run).
- A caller that waited for a *failed* acquisition makes its own attempt, as
  if it had arrived afterwards. There is no shared failure and no retry loop:
  ADR-0006 still forbids a nested retry policy.
- Non-reusable identities never lock; they always execute.
- The lock covers one store. Stores on filesystems without working `flock`
  get in-process exclusion only.

**An explicit import is keyed by its content.** `native_source_identity(src)`
computes, without copying or importing an engine, the exact
`native_artifact_identity` the import will publish. `ensure(import_source=…)`
reuses only an import of that content for that measurement, stored at
`imports/<dd>/<digest>/<native_identity>/`. Different content, including an
edit at the same path, is imported. Under ADR-0012 an import never seeds or
replaces the canonical execution slot; it lives only in its own import slot.

## Consequences

- MAGNET needs no acquisition node or scheduler support to avoid duplicate
  native work. Concurrent claim projections of one measurement wait for one
  execution (see the MAGNET integration tests).
- Import content is checked by the executing acquisition operation. Scheduler
  command construction must not read native inputs to derive a node identity;
  the generated job reaches the content-keyed store lookup instead of assuming
  its previous output proves current native reuse (ADR-0013).
- Store layout gains `imports/` and `locks/`. Lock files are tiny and may
  remain after release; their content names the last holder for debugging.
