# Native hard-kill cleanup

This captured cancelled bundle comes from a real Harbor Docker sandbox whose
agent ignores SIGINT and SIGTERM. The parent escalated to SIGKILL (return code
-9), removed only journaled attempt resources, and verified that an unrelated
container survived. No reward or successful run was published.

`capture.json` inventories original bytes; `native-acceptance.xml` records the
native acceptance. Engine-free tests verify checksums and read the cancelled
bundle without Harbor. Do not edit captured files or execute copied sandbox
tests on the host.
