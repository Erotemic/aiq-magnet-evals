# ADR-0013: Command construction is independent of runtime resolution

Status: Accepted (2026-11-22). Refines ADR-0002 and ADR-0006. Supersedes
ADR-0011's requirement for import content in a scheduler node ID and
ADR-0012's requirement that MAGNET identify imported content while scheduling.
Their store locking, content-keyed import slots and snapshot rules remain.

## Context

MAGNET put native request resolution in `EvaluationNode.final_algo_config`
so kwdagger could hash an observed measurement identity. Reading configuration
launched a MAGNET subprocess and then an isolated engine worker. Every distinct
request paid native startup before any job could be submitted, even when the
result store already held its measurement.

The cost exposed a more basic defect: the machine constructing commands may
not have the target interpreter, packages, hardware, containers, credentials
or network access. It must still be able to describe the entire workload.

## Decision

- Configuration reads, hashing, graph compilation and command rendering use
  declared parameters. They do not invoke target programs, import native
  runtimes/task plugins, query serving catalogs or probe execution hardware.
  A missing target executable is valid input to command construction.
- Runtime resolution belongs inside the generated command when it executes.
  That command resolves engine/task/serving facts in its execution environment,
  checks the native store, and reuses or executes the requested evaluation.
- A scheduler node ID identifies declared work. It is distinct from the
  evaluator's runtime measurement identity. Explicit caller-supplied revision
  tokens may affect scheduling; observing them is not a compilation prerequisite.
- Native store lookup and import-content checks occur at execution. Consumers
  must reach that lookup rather than treating a completed scheduler output as
  proof that a mutable runtime input has not changed. An import may be pinned
  to content identified by the executing acquisition operation; snapshot
  mismatch still prevents publication under ADR-0012.
- A mandatory preparation phase before compilation, parallel preflight or a
  persistent resolver does not repair this boundary. Command construction must
  work without running any of them. The rule applies to normal scheduling,
  not only to a special dry-run path.

## Consequences

No native measurement identity algorithm or stored bundle needs to change.
Different outer scheduler IDs can reach the same valid native store entry.
Completed evaluations remain reusable without inference or grading again.

Tests must construct and write complete job commands with target runtimes
absent and subprocess creation forbidden. Runtime tests separately establish
resolution, native cache reuse, content changes and lease cleanup. Existing
rendered commands with explicitly pinned identities remain compatible.
