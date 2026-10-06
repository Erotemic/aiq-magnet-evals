# Harbor Phase 0 native captures

Unmodified job/trial files captured with Harbor 0.23.0 on 2026-10-05.
`capture.json` records source-job locations, upstream revisions, and each
captured file's SHA256. Absolute native paths, ephemeral endpoint ports, trial
identifiers, and timestamps are intentionally preserved as evidence.

Generate new captures with:

```bash
dev/ci/harbor_phase0.sh
python dev/capture_harbor_fixtures.py \
  --source=/tmp/aiq-harbor-roadmap/phase0-artifacts \
  --destination=/tmp/harbor-native-new
```

The capture tool refuses to overwrite an existing tree. Review the new fixture
diff before replacing these captures. See `docs/planning/harbor-evidence.md`
for the commands, observed gates, protocol limitations, and normalization
decisions supported by these files.

These are synthetic repository/test-agent fixtures. The fresh replay uses the
unchanged upstream Pro V2 replay agent against that synthetic repository;
it is not evidence of full SWE-bench Pro task support.
