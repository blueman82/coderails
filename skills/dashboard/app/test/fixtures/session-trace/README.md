# Real parallel Claude worker fixture

This folder contains a sanitized native Claude sample from the final
independent review of run observability. It has two Claude workers that
ran at the same time. The Codex plugin has a separate Codex sample.

The fixture keeps dispatch calls, child identity links, lifecycle rows,
and relevant timestamps. It keeps native IDs only when the adapter needs
them to match records. It removes prompts, instructions, tool arguments
and results, model names, unrelated rows, original row UUIDs, and other
incidental data. The HTML-shaped text is synthetic. It tests rendering.

Tests copy the fixture into a temporary Claude source layout. They exercise
the Claude collector, authenticated route handlers, and React panel.
The fixture does not replay the full session or prove task success.

A broken-link control changes one child identity in a copy. The test checks
that its correctness assertion rejects the changed fixture.
