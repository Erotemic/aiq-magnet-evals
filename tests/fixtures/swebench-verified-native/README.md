# Native SWE-bench Verified acceptance

These are unmodified native captures from the five-instance offline acceptance
on 2026-10-05/06. `oracle/run` and `nop/run` are checksum-verified published
Inspect bundles. Each `official` tree retains fresh upstream SWE-bench reports,
commands, patches and test output. NOP's empty predictions are counted by the
official harness without launching grading containers.

Inspect 0.3.272, Inspect-Evals `9080b5e9f1647ed14e45de8cb01e3d43411c0163`,
SWE-bench 3.0.15, immutable dataset/image pins and the explicit
`git-reset-clean/v1` baseline are recorded in the protocol files and evidence
ledger. This is infrastructure acceptance, not a model benchmark result or
evidence for all 500 instances.

`capture.json` inventories the original files. Do not edit them. To capture a
new acceptance in a separate destination:

```bash
dev/ci/swebench_verified_acceptance.sh
python3 dev/capture_verified_fixtures.py \
  --source /tmp/aiq-harbor-roadmap/verified-acceptance-captures \
  --destination /tmp/verified-new-fixtures
```

The engine-free tests export the exact captured patches and compare them with
the patches consumed by the official grader.
