# Real parallel worker fixture

This fixture contains only the necessary records from the sanitized native Codex sample in the last run-observability inspection, which a different reviewer ran. The native session had two workers that ran at the same time. The fixture keeps only parent spawn calls, links to native worker records, child metadata, lifecycle rows, and their source timestamps. It keeps session, child, and call IDs for correlation. It does not include prompts, instructions, actual arguments and results, unrelated data, paths, or incidental metadata.

The HTML-shaped argument marker is synthetic and tests text escaping.

The integration test copies this fixture into a temporary native source layout and exercises the collector, authenticated endpoint handlers, and React panel. It replays only the selected correlation pattern. The broken-link control changes the parent ID for a copied child. It checks that the assertion rejects the data.
