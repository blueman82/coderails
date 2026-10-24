# Real parallel worker fixture

These records come from a sanitized native Codex sample. The final independent run-observability review used this sample. The native session had two workers that ran at the same time.

The fixture keeps parent spawn calls, native activity links, child metadata, lifecycle rows, and source timestamps. It keeps session, child, and call IDs so the test can match records. It removes prompts, instructions, actual arguments and results, unrelated events, paths, and incidental metadata. The HTML-shaped argument marker is synthetic. It tests text escaping.

The integration test copies this fixture into a temporary native source layout. It exercises the collector, authenticated route handlers, and React panel. The fixture contains only the records needed to test how those parts link workers to the parent. It does not replay the full session or prove that the task succeeded.

The broken-link control changes a copied child's parent identity. The test checks that the correctness assertion rejects that trace.
