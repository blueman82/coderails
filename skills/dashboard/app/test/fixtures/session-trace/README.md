# Real parallel worker fixtures

These records come from sanitized native samples used in the final independent review of run observability. One sample has two Claude workers running at the same time. The other has two Codex workers running at the same time.

The fixtures keep dispatch calls, child identity links, lifecycle rows, and relevant timestamps. They keep native session, child, and call IDs only when the adapter needs them to match records. They remove prompts, instructions, tool arguments and results, model names, unrelated rows, original row UUIDs, and incidental metadata. The HTML-shaped text is synthetic and tests rendering.

The tests copy these fixtures into temporary native source layouts. They exercise the provider collector, authenticated route handlers, and React panel. The fixtures do not replay the full sessions or prove that the tasks succeeded.

Broken-link controls change a child identity in a copied fixture. The tests check that the correctness assertion rejects it.
