# Real parallel worker fixtures

These records contain a subset of the sanitized native samples. The reviewer for the last run-observability audit used the full samples and worked independently. The samples represented an actual overlapping two-worker Claude session and an actual overlapping two-worker Codex session. Only dispatch calls, child identity links, lifecycle rows, and their source timestamps remain.

Native session, child, and call IDs are kept solely where the adapter uses them to correlate records. Prompts, instructions, tool argument and result bodies, model names, unrelated rows, initial row UUIDs, and other incidental metadata were removed. The harmless HTML-shaped text is a synthetic rendering sentinel.

The tests copy these fixtures into temporary native source layouts and use the provider collector, authenticated HTTP handlers, and React panel. They do not replay the initial full session or attest task success. Broken-link controls alter a child identity in a copied fixture and check that the assertion rejects it.
