# Real parallel Claude worker fixture

This folder contains a sanitized native Claude sample from the final
independent review of run observability. It has two Claude workers that
ran at the same time. The Codex plugin has a separate Codex sample.

The fixture keeps dispatch calls, child identity links, lifecycle rows,
and relevant timestamps. It keeps native IDs only when the adapter needs
them to match records. It removes prompts, instructions, tool arguments
and results, model names, unrelated rows, original row UUIDs, and other
incidental data. The HTML-shaped text is synthetic. It tests rendering.

Collector and detail tests load `claude/native-shape.json` into a temporary
Claude source layout. A panel test reads the same file. The real-parallel
test copies `real-parallel/projects` and exercises authenticated routes and
the React panel. The standalone `sessionTrace.route.test.ts` uses separate
inline events; it does not read this fixture. These tests do not replay the
full session or prove task success.

A broken-link control changes one child identity in a copy. The test checks
that its correctness assertion rejects the changed fixture.
