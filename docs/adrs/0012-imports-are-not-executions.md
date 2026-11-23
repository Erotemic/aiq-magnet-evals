# ADR-0012: Imports are not executions; an import reads its source once

Status: Accepted (2026-09-29). Refines ADR-0011; supersedes its rule that an
import may seed the canonical run.
The scheduling-time content-identification requirement below is superseded by
[ADR-0013](0013-offline-command-planning.md).

## Context

A review of ADR-0011 found two problems with native imports:

1. **Unproven provenance became reusable execution.** ADR-0011 let the first
   valid result of a measurement seed its canonical run, whether executed or
   imported. But an imported native artifact cannot prove the request's task,
   data, or model revisions; the adapters say so (for example, OLMo records
   that caller-supplied revisions are not proven by native metrics). An
   explicit import of 0.25 then answered every later plain
   `ensure(request)` as if the engine had computed it. The original plan
   required unknown provenance to stay unknown and reuse to be conservative.
2. **Two reads of a live source.** Import normalized the source, then
   publication copied it again. A source that changed in between produced a
   valid bundle whose normalized metric (0.25) disagreed with its preserved
   native file (0.75).

## Decision

- **An import never becomes the canonical run.** It is published only in
  its content-keyed import slot (`imports/<digest>/<native identity>/`) and
  reused only by an import of the same content for the same measurement. A
  plain execute-or-reuse `ensure` returns only executed results. If a future
  adapter can positively attest that native artifacts establish the full
  measurement identity, a later ADR may relax this for that adapter.
- **An import reads its source once.** `import_evaluation` copies the source
  into a private snapshot. The content identity, the adapter's normalization,
  and the published native files all come from that snapshot. Diagnostics
  keep naming the caller's source path.
- **An import can be pinned to identified content.**
  `ensure(..., expected_import_identity=...)` (and `import_evaluation(...,
  expected_native_identity=...)`) raise `ImportIdentityMismatch` before
  normalizing or publishing anything if the snapshot differs. Without it,
  `ensure` pins the import to the content it hashed for its reuse check.

## Consequences

- Seeding a store with previously computed runs is an explicit import, and
  it is reused only as that import (for example by a MAGNET node that
  declares `import_source`), never as an execution.
- MAGNET may pass an `import_identity` identified by the executing acquisition
  operation, so an import publishes exactly that content or nothing. Identifying
  native content is not a prerequisite for constructing its command (ADR-0013).
- `ResultStore.seed_canonical` is removed.
