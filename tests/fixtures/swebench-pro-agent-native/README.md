# Locked mini-SWE in the actual Pro image

This unmodified native bundle records four scripted tool calls from upstream
locked mini-SWE 2.4.6 in the frozen Ansible Pro V2 image. Its captured patch is
byte-identical to the native oracle capture, and a separate pristine replay
passed all 16 required tests. Managed Python was 3.12.15. The dependency closure
is observed but not pinned; the measurement is nonreusable.

`capture.json` inventories original bytes. This scripted-gold infrastructure
fixture does not measure a real model. Regenerate derived summaries with
`python3 dev/regenerate_native_regressions.py pro`.

To capture this label from a later smoke run into a new tree, use
`dev/capture_pro_fixtures.py --source CAPTURE --destination NEW_TREE
--labels locked-mini-pro-scripted-gold`. Never edit or execute captured sandbox
files on the host.
