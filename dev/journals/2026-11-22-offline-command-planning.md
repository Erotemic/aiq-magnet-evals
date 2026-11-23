# Command planning and runtime resolution

Model: GPT-6 (Codex); exact serving variant/configuration unavailable.

ADR-0013 corrects the integration requirement that a scheduler must obtain an
observed native identity before hashing a node. That made a configuration read
launch native workers and required the planning machine to have the execution
environment. A mandatory preparation stage or warm resolver retains the defect.

Command construction uses declared configuration. Native resolution, serving
facts and content-keyed reuse belong to the executing acquisition operation.
The existing store and identity algorithms support that distinction; this
change edits architecture guidance, not evaluator Python or stored bundles.
ADR-0011/0012 keep their locking, import slots and snapshot integrity rules.

The corresponding MAGNET correction is isolated on
`fix/offline-command-planning`, preserving an active campaign's source. Its
tests construct ordinary host/container job commands with native imports,
catalog queries and subprocess creation forbidden. Runtime tests separately
exercise native cache reuse, mutable task/import changes and lease cleanup.


## 2026-11-23: keep completion checks cheap

The initial consumer correction forced completed nodes pending so runtime
resolution could audit them on every resume. Moving that work out of compilation
was insufficient. ADR-0013 and the integration plan now state the complementary
rule: completed outputs use normal file-existence checks. Native store lookup
belongs to acquisition commands that actually execute; readout validates
evidence separately. Undeclared changes require explicit refresh or a declared
revision. Evaluator Python, native identities and stored bundles are unchanged.
