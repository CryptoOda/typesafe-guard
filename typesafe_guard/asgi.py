"""ASGI middleware: scan incoming request bodies for guardrail violations
before they reach the application (e.g. before an LLM call downstream).

Framework-agnostic at the ASGI level: works with FastAPI, Starlette, and any
other ASGI app without a framework-specific dependency.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from .core import Guard, ScanResult, decide


class GuardrailMiddleware:
    """Scans a configurable JSON field of the request body on matching paths.

    Blocks with HTTP 400 when `decide(...)` returns 'block'. 'warn' results
    are attached to the ASGI scope as `scope["typesafe_guard"]` for the app
    to read; they do not block the request.
    """

    def __init__(
        self,
        app: Callable,
        *,
        guard: Guard | None = None,
        field: str = "prompt",
        paths: Iterable[str] | None = None,
        block_threshold: float = 0.85,
        warn_threshold: float = 0.5,
    ) -> None:
        self.app = app
        self.guard = guard or Guard()
        self.field = field
        self.paths = set(paths) if paths is not None else None
        self.block_threshold = block_threshold
        self.warn_threshold = warn_threshold

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> Any:
        if scope["type"] != "http" or (self.paths is not None and scope["path"] not in self.paths):
            return await self.app(scope, receive, send)

        body = b""
        more_body = True
        messages = []
        while more_body:
            message = await receive()
            messages.append(message)
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        text = self._extract_text(body)
        if text is not None:
            result = self.guard.scan(text)
            verdict = decide(
                result,
                block_threshold=self.block_threshold,
                warn_threshold=self.warn_threshold,
            )
            if verdict == "block":
                return await self._reject(send, result)
            scope["typesafe_guard"] = {"verdict": verdict, "result": result}

        async def replay_receive() -> dict:
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        return await self.app(scope, replay_receive, send)

    def _extract_text(self, body: bytes) -> str | None:
        if not body:
            return None
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        value = payload.get(self.field) if isinstance(payload, dict) else None
        return value if isinstance(value, str) else None

    async def _reject(self, send: Callable, result: ScanResult) -> None:
        triggered = {name: r.probability for name, r in result.results.items() if r.triggered}
        body = json.dumps({"error": "blocked_by_guardrail", "triggered": triggered}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})
