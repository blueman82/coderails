# Real parallel worker fixture

These records are a minimal reduction of the sanitized native Codex sample used in the final independent run-observability review. The reviewed native session had two overlapping workers. Only parent spawn calls, native activity links, child metadata, lifecycle rows, and their source timestamps remain. Session, child, and call IDs are retained for correlation. Prompts, instructions, actual arguments and results, unrelated events, paths, and incidental metadata were removed. The HTML-shaped argument marker is synthetic and tests text escaping.

The integration test copies this fixture into a temporary native source layout and exercises the collector, authenticated route handlers, and React panel. It is a replay of the selected correlation shape, not of the full original session or task outcome. Its broken-link control mutates a copied child parent identity and confirms the correctness assertion rejects the trace.
