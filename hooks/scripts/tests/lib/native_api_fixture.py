"""A bounded local Messages API fixture for exercising the real Claude CLI."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def stream_events(message: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Encode a deterministic response using the documented native SSE protocol."""
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    **message,
                    "content": [],
                    "stop_reason": None,
                    "usage": {"input_tokens": 100, "output_tokens": 0},
                },
            },
        )
    ]
    for index, block in enumerate(message["content"]):
        initial: dict[str, Any] = {**block, "text": ""} if block["type"] == "text" else {**block, "input": {}}
        delta = (
            {"type": "text_delta", "text": block["text"]}
            if block["type"] == "text"
            else {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        )
        events.extend(
            [
                ("content_block_start", {"type": "content_block_start", "index": index, "content_block": initial}),
                ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": delta}),
                ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ]
        )
    events.extend(
        [
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
                    "usage": {"output_tokens": 20},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )
    return events


class NativeAPIFixture:
    """Serve model-side fixtures while the unmodified CLI owns tools and transcripts."""

    def __init__(self, dispatches: Callable[[], list[dict[str, Any]]]) -> None:
        """Bind only loopback, with bounded request counts and no external forwarding."""
        self.dispatches = dispatches
        self.requests = 0
        self.errors: list[str] = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            """Serve the minimum Messages endpoints without logging request bodies."""

            def log_message(self, format: str, *args: object) -> None:
                """Keep synthetic prompts out of the test output."""

            def do_HEAD(self) -> None:
                """Accept the CLI connection-warming probe."""
                self.send_response(200)
                self.end_headers()

            def do_POST(self) -> None:
                """Respond to one bounded request or fail the fixture closed."""
                try:
                    fixture.requests += 1
                    length = int(self.headers.get("Content-Length", "0"))
                    if fixture.requests > 16 or length > 1048576:
                        raise ValueError("local fixture request limit exceeded")
                    body = json.loads(self.rfile.read(length))
                    if "count_tokens" in self.path:
                        self.send_json({"input_tokens": 100})
                        return
                    message = fixture.respond(body)
                    if not body.get("stream"):
                        self.send_json(message)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for name, payload in stream_events(message):
                        self.wfile.write(f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode())
                        self.wfile.flush()
                except (ValueError, OSError, KeyError, TypeError) as error:
                    fixture.errors.append(str(error))
                    self.send_json(
                        {"type": "error", "error": {"type": "invalid_request_error", "message": str(error)}}, 400
                    )

            def send_json(self, data: dict[str, Any], status: int = 200) -> None:
                """Write one JSON response with an explicit status."""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        """Return the loopback endpoint for the CLI's per-process configuration."""
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        """Stop the local server and close its listening socket."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def respond(self, body: dict[str, Any]) -> dict[str, Any]:
        """Choose fixed model-side actions; never manufacture native tool results."""
        messages = body.get("messages", [])
        history = json.dumps(messages)
        latest = json.dumps(messages[-1:])
        if "toolu_graph_fixture_" in history:
            blocks = [{"type": "text", "text": "NATIVE_PARENT_COMPLETED"}]
        elif "CODERAILS_GRAPH_DISPATCH=" in latest:
            blocks = [{"type": "text", "text": "NATIVE_CHILD_COMPLETED"}]
        else:
            blocks = self.dispatches()
        reason = "tool_use" if any(block["type"] == "tool_use" for block in blocks) else "end_turn"
        return {
            "id": "msg_" + uuid.uuid4().hex,
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": blocks,
            "stop_reason": reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
