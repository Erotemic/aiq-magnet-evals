# Native local Pro V2 generation/replay evidence

These unmodified bundles preserve two native jobs per run, exact patch source
views, trial UUID joins, replay input snapshots, verifier output, trajectories,
physical images and installed runtime metadata. `capture.json` inventories
original bytes. Regenerate the derived summaries with:

```bash
python3 dev/regenerate_native_regressions.py pro
```

The fixed Ansible task passed oracle generation/fresh replay (1), and NOP
generation/fresh replay (0, actually empty patch). The unchanged locked mini-SWE
agent completed the synthetic division task through a scripted endpoint,
captured the expected patch and passed fresh replay (1). These are infrastructure
fixtures, not model scores. Scope and deviations are in the evidence ledger.

Capture a later acceptance into a new tree:

```bash
dev/ci/swebench_pro_v2_smoke.sh
python3 dev/capture_pro_fixtures.py \
  --source /path/printed/by/the/smoke/script \
  --destination /tmp/pro-new-fixtures
```

Do not edit captured files or execute their copied sandbox tests on the host.
Engine-free tests re-normalize both phases, verify patch joins and read the
bundles without Harbor or the original worker paths.
